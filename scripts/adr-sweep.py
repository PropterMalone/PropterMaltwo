#!/usr/bin/env python3
# pattern: imperative shell
"""Mechanical ADR falsifier sweep. No LLM anywhere.

Walks every ADR dir you point it at, runs each ADR's `falsifier_cmd:` entries, and
records the verdict IN THE ADR FILE ITSELF (`fired:` / `support_lost:` lines in
frontmatter). A central falsifier registry was rejected on purpose: a second
source of truth drifts, and an uncommitted line a destructive git op wipes
self-heals at the next sweep. The append-only log carries the history.

Exit-code contract, which is the whole interface a falsifier has to honour:
    0   clean   — the condition the ADR bets against was NOT observed
    1   fired   — it WAS observed
    124 / other error   — the command broke; NEVER read as a fire

Erring toward silence is deliberate: a falsifier that fires on its own breakage
trains the reader to ignore fires, which is worse than no read side at all. For
the same reason a run with any errored label never self-heals an existing line.

State lives in `fired:` / `support_lost:` lines that a human (the /retro
adjudication step) annotates with ` — adjudicated: real|false <date>`. An
adjudicated line is untouchable by this script; retro removes it.

The lifecycle this script executes is documented in `docs/decision-records.md`;
the frontmatter fields it reads are in `templates/adr-template.md`.

Usage: adr-sweep.py [--dry-run] [--no-tasks] [--no-notify] [--only SUBSTR] [--json]
Cron:  adr-falsifier-sweep.sh (flock wrapper). Sweep writes are never committed.
Log:   $ADR_SWEEP_LOG (TSV, append-only; the last line of each run is the
       liveness heartbeat — /kickoff reads it to notice a dead sweep)

Configuration. Nothing below is hardcoded to one machine's layout; the defaults
are the layout this repo installs, and every one of them is overridable:

    ADR_SWEEP_ROOTS        colon-separated `alias=dir` pairs. REPLACES the whole
                           default scan — the only override the tests need.
    ADR_SWEEP_EXTRA_ROOTS  colon-separated `alias=dir` pairs ADDED to the default
                           scan, for decision dirs living outside the projects root.
    ADR_SWEEP_CLAUDE_DIR   Claude config dir (default ~/.claude)
    ADR_SWEEP_PROJECTS     projects root to scan (default ~/Projects)
    ADR_SWEEP_SUBDIR       decisions dir relative to a repo root (default docs/decisions)
    ADR_SWEEP_STATE        state dir (default <claude dir>/state)
    ADR_SWEEP_LOG          log file (default <state dir>/adr-sweep.log)
    ADR_SWEEP_MEMORY_ROOT  memory root for `mem:` refs (default <claude dir>/projects)
    ADR_SWEEP_NOTIFY       optional hook: a command taking (title, body). Absent or
                           non-executable → the push is skipped, never an error.
    ADR_SWEEP_TASK         optional hook: a command taking (title, notes), to open
                           one tracker item per NEW fire. Same skip-if-absent rule.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

HOME = Path.home()

COMMAND_TIMEOUT_SECONDS = 120
OBSERVATION_MAX_CHARS = 200
NOTIFY_MAX_ITEMS = 10

ALIVE_STATUSES = {"draft", "active", "adopted", "accepted", "proposed"}
HARD_DEAD_STATUSES = {"retracted", "rejected"}
SOFT_DEAD_STATUSES = {"superseded", "deprecated"}

ADR_GLOB = "[0-9][0-9]*-*.md"
FIRED_KEY = "fired"
SUPPORT_KEY = "support_lost"
SEPARATOR = " — "  # em dash, matching the frontmatter line format

DEFAULT_SUBDIR = "docs/decisions"
LOG_NAME = "adr-sweep.log"

CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
ADJUDICATED_RE = re.compile(r"adjudicated:\s*(real|false)\b", re.IGNORECASE)
ADJUDICATED_SUFFIX_RE = re.compile(r"\s*—\s*adjudicated:\s*(?:real|false)\b.*$", re.IGNORECASE)
DATE_PREFIX_RE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}\s*—\s*(.*)$", re.DOTALL)


# ============================== functional core ==============================
# Parsing, decision logic and line formatting. No file, subprocess or clock I/O
# below this banner — the tests drive these directly.


def parse_frontmatter(text: str) -> tuple[dict, str | None]:
    """-> (mapping, error). A file with no frontmatter is empty, not broken."""
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return {}, None
    close = None
    for i in range(1, len(lines)):
        # column-0 only: an indented `---` inside a block scalar is content
        if lines[i].rstrip() == "---":
            close = i
            break
    if close is None:
        return {}, "unterminated frontmatter"
    try:
        data = yaml.safe_load("\n".join(lines[1:close]))
    except yaml.YAMLError as exc:
        return {}, f"yaml: {str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__}"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return {}, "frontmatter is not a mapping"
    return data, None


def status_word(meta: dict) -> str:
    raw = meta.get("status")
    return "" if raw is None else str(raw).strip().lower()


def classify_status(word: str) -> str:
    """-> alive | hard-dead | soft-dead | unknown | absent."""
    if not word:
        return "absent"
    if word in ALIVE_STATUSES:
        return "alive"
    if word in HARD_DEAD_STATUSES:
        return "hard-dead"
    if word in SOFT_DEAD_STATUSES:
        return "soft-dead"
    return "unknown"


def is_dead(word: str) -> bool:
    return classify_status(word) in ("hard-dead", "soft-dead")


def normalize_falsifiers(value) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """-> ([(label, cmd)], [(label, problem)]). A bare string entry is labelled f<N>."""
    if value is None:
        return [], []
    entries = value if isinstance(value, list) else [value]
    out: list[tuple[str, str]] = []
    problems: list[tuple[str, str]] = []
    for n, entry in enumerate(entries, 1):
        fallback = f"f{n}"
        if isinstance(entry, str):
            if entry.strip():
                out.append((fallback, entry))
            else:
                problems.append((fallback, "falsifier entry is empty"))
        elif isinstance(entry, dict):
            label = str(entry.get("label") or fallback).strip() or fallback
            cmd = entry.get("cmd")
            if isinstance(cmd, str) and cmd.strip():
                out.append((label, cmd))
            else:
                problems.append((label, "falsifier entry has no cmd"))
        else:
            problems.append((fallback, "falsifier entry is not a string or mapping"))
    return out, problems


def normalize_ref(value) -> str | None:
    """A ref as written. YAML reads a bare `ref: 02` as int 2, but the file it
    names is `02-*.md`, so an integer ref is re-padded to the two-digit form."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:02d}"
    text = str(value).strip()
    return text or None


def normalize_depends_on(value) -> list[tuple[str | None, str | None]]:
    """-> [(ref, claim)]. A bare string entry is a ref with no claim."""
    if value is None:
        return []
    entries = value if isinstance(value, list) else [value]
    out: list[tuple[str | None, str | None]] = []
    for entry in entries:
        if isinstance(entry, (str, int)) and not isinstance(entry, bool):
            out.append((normalize_ref(entry), None))
        elif isinstance(entry, dict):
            ref = normalize_ref(entry.get("ref"))
            claim = entry.get("claim")
            claim = str(claim) if claim is not None else None
            out.append((ref, claim))
        else:
            out.append((None, None))
    return out


def encode_project_path(path: Path) -> str:
    """Claude Code names a per-project memory dir after the cwd with every path
    separator replaced by a dash: /home/you/Projects/foo -> -home-you-Projects-foo.
    Deriving it beats hardcoding one machine's home dir."""
    return str(path).replace(os.sep, "-")


def classify_exit(code: int) -> str:
    """0 clean, 1 fired, everything else (124 included) an error. Never a fire."""
    if code == 0:
        return "clean"
    if code == 1:
        return "fired"
    return "error"


def extract_observation(stdout: str, stderr: str) -> str:
    for stream in (stdout, stderr):
        for line in (stream or "").splitlines():
            cleaned = CONTROL_CHARS_RE.sub("", line).strip()
            if cleaned:
                return cleaned[:OBSERVATION_MAX_CHARS]
    return ""


def quote_yaml_scalar(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def format_fired_value(today: str, items: list[tuple[str, str]]) -> str:
    return today + SEPARATOR + "; ".join(f"{label}: {obs}" for label, obs in items)


def format_support_value(today: str, items: list[tuple[str, str]]) -> str:
    return today + SEPARATOR + "; ".join(f"{ref} {reason}" for ref, reason in items)


def adjudication(value) -> str | None:
    if value is None:
        return None
    match = ADJUDICATED_RE.search(str(value))
    return match.group(1).lower() if match else None


def support_pairs(value) -> set[str]:
    """The `<ref> <reason>` set carried by a support_lost line, date/adjudication stripped."""
    if value is None:
        return set()
    body = ADJUDICATED_SUFFIX_RE.sub("", str(value)).strip()
    match = DATE_PREFIX_RE.match(body)
    if match:
        body = match.group(1)
    return {part.strip() for part in body.split(";") if part.strip()}


def frontmatter_bounds(lines: list[str]) -> tuple[int, int] | None:
    if not lines or lines[0].rstrip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return 0, i
    return None


def upsert_frontmatter_line(text: str, key: str, value: str | None) -> str:
    """Insert / replace / (value=None) remove one frontmatter line. Every other byte survives."""
    lines = text.splitlines(keepends=True)
    bounds = frontmatter_bounds([line.rstrip("\r\n") for line in lines])
    if bounds is None:
        return text
    open_idx, close_idx = bounds
    target = None
    for i in range(open_idx + 1, close_idx):
        if lines[i].startswith(key + ":"):
            target = i
            break
    if value is None:
        if target is None:
            return text
        del lines[target]
        return "".join(lines)
    newline = "\r\n" if lines[close_idx].endswith("\r\n") else "\n"
    rendered = f"{key}: {quote_yaml_scalar(value)}{newline}"
    if target is None:
        lines.insert(close_idx, rendered)
    else:
        lines[target] = rendered
    return "".join(lines)


@dataclass(frozen=True)
class Decision:
    action: str  # write | remove | none
    log_status: str | None  # refire | refire-suppressed | healed | None
    transition: bool


def decide_fired(existing, new_value: str | None, may_heal: bool = True) -> Decision:
    adjudicated = adjudication(existing)
    if new_value is not None:
        if existing is None:
            return Decision("write", None, True)
        if adjudicated == "false":
            return Decision("none", "refire-suppressed", False)
        if adjudicated == "real":
            return Decision("none", "refire", False)
        return Decision("write", "refire", False)
    if existing is None or adjudicated is not None or not may_heal:
        return Decision("none", None, False)
    return Decision("remove", "healed", False)


def decide_support(existing, new_value: str | None, new_pairs: set[str], has_hard: bool,
                   may_heal: bool = True) -> Decision:
    adjudicated = adjudication(existing)
    if new_value is not None:
        if existing is None:
            return Decision("write", None, has_hard)
        if adjudicated == "false":
            return Decision("none", "refire-suppressed", False)
        if adjudicated == "real":
            return Decision("none", "refire", False)
        if support_pairs(existing) == new_pairs:
            # same refs, same reasons: nothing changed, so nothing to say and no
            # rewrite — keeping the original date preserves first-observed
            return Decision("none", None, False)
        return Decision("write", "refire", has_hard)
    if existing is None or adjudicated is not None or not may_heal:
        return Decision("none", None, False)
    return Decision("remove", "healed", False)


def scrub_field(value) -> str:
    return CONTROL_CHARS_RE.sub("", str(value)).strip()


def log_line(ts: str, target: str, kind: str, key: str, status: str, exit_code, observation: str) -> str:
    return "\t".join(
        scrub_field(field) for field in (ts, target, kind, key, status, exit_code, observation)
    )


def summary_fields(counts: dict) -> str:
    return (
        f"adrs={counts['adrs']} cmds={counts['cmds']} fired={counts['fired']} "
        f"lost={counts['lost']} errors={counts['errors']} new={counts['new']}"
    )


def notify_body(items: list[str]) -> str:
    head = items[:NOTIFY_MAX_ITEMS]
    if len(items) > NOTIFY_MAX_ITEMS:
        head.append(f"+{len(items) - NOTIFY_MAX_ITEMS} more")
    return "\n".join(head)


def parse_root_pairs(spec: str | None) -> list[tuple[str, Path]]:
    """`alias=dir:alias=dir` -> [(alias, path)]. Empty segments are ignored."""
    if not spec:
        return []
    roots = []
    for pair in spec.split(":"):
        if not pair.strip():
            continue
        alias, _, directory = pair.partition("=")
        if directory:
            roots.append((alias.strip(), Path(directory).expanduser()))
    return roots


# ============================= imperative shell ==============================


def claude_dir(env) -> Path:
    return Path(env.get("ADR_SWEEP_CLAUDE_DIR") or (HOME / ".claude")).expanduser()


def projects_root(env) -> Path:
    return Path(env.get("ADR_SWEEP_PROJECTS") or (HOME / "Projects")).expanduser()


def decisions_subdir(env) -> str:
    return (env.get("ADR_SWEEP_SUBDIR") or DEFAULT_SUBDIR).strip("/")


def state_dir(env) -> Path:
    return Path(env.get("ADR_SWEEP_STATE") or (claude_dir(env) / "state")).expanduser()


def log_path(env) -> Path:
    override = env.get("ADR_SWEEP_LOG")
    return Path(override).expanduser() if override else state_dir(env) / LOG_NAME


def memory_root(env) -> Path:
    return Path(env.get("ADR_SWEEP_MEMORY_ROOT") or (claude_dir(env) / "projects")).expanduser()


def enumerate_roots(env) -> list[tuple[str, Path]]:
    """-> [(alias, decisions dir)]. ADR_SWEEP_ROOTS replaces the whole default scan."""
    override = parse_root_pairs(env.get("ADR_SWEEP_ROOTS"))
    if override:
        return override

    subdir = decisions_subdir(env)
    roots = []
    for alias, directory in (
        ("house", claude_dir(env) / subdir),
        ("angel", claude_dir(env) / "skills" / "angel" / subdir),
        *parse_root_pairs(env.get("ADR_SWEEP_EXTRA_ROOTS")),
    ):
        if directory.is_dir():
            roots.append((alias, directory))
    projects = projects_root(env)
    if projects.is_dir():
        for repo in sorted(p for p in projects.iterdir() if p.is_dir()):
            # `.git` as a regular file means a linked-worktree checkout: the same
            # ADRs already counted under the main checkout
            if (repo / ".git").is_file():
                continue
            directory = repo / subdir
            if directory.is_dir():
                roots.append((repo.name, directory))
    return roots


def enumerate_adrs(roots: list[tuple[str, Path]], only: str | None) -> list[tuple[str, Path]]:
    found = []
    for alias, directory in roots:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(ADR_GLOB)):
            if path.is_file() and (only is None or only in str(path)):
                found.append((alias, path))
    return found


def command_cwd(adr_path: Path, env) -> Path:
    """The dir a falsifier runs in: the repo root, i.e. the ADR's dir with the
    decisions subdir stripped off. A dir that doesn't end in the subdir is its own root."""
    directory = adr_path.parent
    candidate = directory
    for expected in reversed(Path(decisions_subdir(env)).parts):
        if candidate.name != expected:
            return directory
        candidate = candidate.parent
    return candidate


def run_falsifier(cmd: str, cwd: Path, adr_path: Path, env) -> tuple[int, str]:
    child_env = dict(env)
    child_env["ADR_FILE"] = str(adr_path)
    child_env["ADR_DIR"] = str(adr_path.parent)
    try:
        proc = subprocess.run(
            ["bash", "-c", cmd],
            cwd=str(cwd),
            env=child_env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {COMMAND_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return 126, f"spawn failed: {exc}"
    return proc.returncode, extract_observation(proc.stdout, proc.stderr)


def read_adr(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"read failed: {exc}"


def adr_dir_for_alias(alias: str, roots: list[tuple[str, Path]], env) -> Path | None:
    for known, directory in roots:
        if known == alias:
            return directory
    if env.get("ADR_SWEEP_ROOTS"):
        return None  # an overridden root list never falls back to the real one
    subdir = decisions_subdir(env)
    if alias == "house":
        return claude_dir(env) / subdir
    if alias == "angel":
        return claude_dir(env) / "skills" / "angel" / subdir
    directory = projects_root(env) / alias / subdir
    return directory if directory.is_dir() else None


def memory_dir_for(project: str | None, env) -> Path:
    """The memory dir behind a `mem:` ref. No project segment means the home-session
    (central) memory; a project segment means that project's dir under the projects root."""
    target = projects_root(env) / project if project else HOME
    return memory_root(env) / encode_project_path(target) / "memory"


def resolve_ref(ref: str, citing_path: Path, roots: list[tuple[str, Path]], env
                ) -> tuple[Path | None, str | None]:
    """-> (path, None) | (None, 'missing' | 'unknown-alias' | 'bad-ref')."""
    ref = str(ref).strip()
    if not ref:
        return None, "bad-ref"
    if ref.startswith("mem:"):
        rest = ref[len("mem:"):].strip().strip("/")
        if rest.endswith(".md"):
            rest = rest[: -len(".md")]
        if not rest:
            return None, "bad-ref"
        if "/" in rest:
            project, _, slug = rest.partition("/")
            directory = memory_dir_for(project, env)
        else:
            slug = rest
            directory = memory_dir_for(None, env)
        if not slug:
            return None, "bad-ref"
        path = directory / f"{slug}.md"
        return (path, None) if path.is_file() else (None, "missing")
    if ":" in ref:
        alias, _, number = ref.partition(":")
        directory = adr_dir_for_alias(alias.strip(), roots, env)
        if directory is None:
            return None, "unknown-alias"
        number = number.strip()
    else:
        number, directory = ref, citing_path.parent
    if not number:
        return None, "bad-ref"
    matches = sorted(directory.glob(f"{number}-*.md")) if directory.is_dir() else []
    if not matches:
        return None, "missing"
    return matches[0], None


def successor_id(target_path: Path, target_id: str | None) -> str:
    """The id of a sibling ADR whose `supersedes:` names this one, else '?'."""
    if not target_id:
        return "?"
    for sibling in sorted(target_path.parent.glob(ADR_GLOB)):
        if sibling == target_path:
            continue
        text, err = read_adr(sibling)
        if err or text is None:
            continue
        meta, parse_err = parse_frontmatter(text)
        if parse_err:
            continue
        supersedes = meta.get("supersedes")
        if supersedes is not None and str(supersedes).strip() == str(target_id).strip():
            return str(meta.get("id") or sibling.stem)
    return "?"


def loss_reason(target_path: Path) -> tuple[str | None, str, str | None]:
    """-> (reason, severity, error). severity is 'hard' | 'soft' | ''."""
    text, err = read_adr(target_path)
    if err or text is None:
        return None, "", err
    meta, parse_err = parse_frontmatter(text)
    if parse_err:
        return None, "", f"target frontmatter: {parse_err}"
    word = status_word(meta)
    kind = classify_status(word)
    if kind == "hard-dead":
        return word, "hard", None
    if adjudication(meta.get(FIRED_KEY)) == "real":
        return "fired-real", "hard", None
    if kind == "soft-dead":
        return f"superseded→{successor_id(target_path, meta.get('id'))}", "soft", None
    return None, "", None


def run_hook(env_key: str, default: Path, args: list[str], env, timeout: int) -> bool:
    """Optional side-channel. Missing or non-executable is a skip, never an error:
    a sweep that fails because your notifier moved is a sweep you stop trusting."""
    configured = env.get(env_key)
    script = Path(configured).expanduser() if configured else default
    if not (script.is_file() and os.access(script, os.X_OK)):
        return False
    try:
        subprocess.run([str(script), *args], check=False, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def open_task(title: str, notes: str, env) -> bool:
    return run_hook("ADR_SWEEP_TASK", claude_dir(env) / "scripts" / "task-add.sh",
                    [title, notes], env, timeout=60)


def send_notify(title: str, body: str, env) -> bool:
    return run_hook("ADR_SWEEP_NOTIFY", claude_dir(env) / "scripts" / "notify.sh",
                    [title, body], env, timeout=120)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Mechanical ADR falsifier sweep.")
    parser.add_argument("--dry-run", action="store_true",
                        help="run the commands but write nothing; print would-be transitions")
    parser.add_argument("--no-tasks", action="store_true", help="skip the task-tracker hook")
    parser.add_argument("--no-notify", action="store_true", help="skip the notification hook")
    parser.add_argument("--only", metavar="SUBSTR", help="only ADRs whose path contains SUBSTR")
    parser.add_argument("--json", action="store_true", help="print the run report as JSON")
    return parser.parse_args(argv)


def sweep(argv=None, env=None) -> dict:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    env = os.environ if env is None else env
    today = date.today().isoformat()
    counts = {"adrs": 0, "cmds": 0, "fired": 0, "lost": 0, "errors": 0, "new": 0}
    records: list[str] = []
    transitions: list[dict] = []

    def emit(target, kind, key, status, exit_code, observation=""):
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        records.append(log_line(ts, target, kind, key, status, exit_code, observation))

    def write_line(path: Path, text: str, key: str, value: str | None):
        if args.dry_run:
            return
        path.write_text(upsert_frontmatter_line(text, key, value), encoding="utf-8")

    roots = enumerate_roots(env)
    adrs = enumerate_adrs(roots, args.only)
    counts["adrs"] = len(adrs)

    # --- pass 1: falsifiers, lint --------------------------------------------
    for alias, path in adrs:
        target = f"{alias}:{path.name}"
        text, read_err = read_adr(path)
        if read_err or text is None:
            counts["errors"] += 1
            emit(target, "error", "-", "error", 0, read_err or "unreadable")
            continue
        meta, parse_err = parse_frontmatter(text)
        if parse_err:
            counts["errors"] += 1
            emit(target, "error", "-", "error", 0, parse_err)
            continue

        word = status_word(meta)
        if meta and word and classify_status(word) == "unknown":
            emit(target, "lint", "status-unknown", "lint", 0, f"status: {word}")
        if is_dead(word) and not str(meta.get("until") or "").strip():
            emit(target, "lint", "until-missing", "lint", 0, f"status: {word}")

        falsifiers, problems = normalize_falsifiers(meta.get("falsifier_cmd"))
        for label, problem in problems:
            counts["errors"] += 1
            emit(target, "error", label, "error", 0, problem)
        if not falsifiers:
            continue

        cwd = command_cwd(path, env)
        fired_items: list[tuple[str, str]] = []
        errored = bool(problems)
        for label, cmd in falsifiers:
            counts["cmds"] += 1
            code, observation = run_falsifier(cmd, cwd, path, env)
            outcome = classify_exit(code)
            emit(target, "falsifier", label, outcome, code, observation)
            if outcome == "fired":
                counts["fired"] += 1
                fired_items.append((label, observation))
            elif outcome == "error":
                counts["errors"] += 1
                errored = True

        new_value = format_fired_value(today, fired_items) if fired_items else None
        existing = meta.get(FIRED_KEY)
        existing = None if existing is None else str(existing)
        decision = decide_fired(existing, new_value, may_heal=not errored)
        if decision.log_status:
            key = ";".join(label for label, _ in fired_items) or "-"
            emit(target, "falsifier", key, decision.log_status, 0, new_value or "")
        if decision.action == "write":
            write_line(path, text, FIRED_KEY, new_value)
        elif decision.action == "remove":
            write_line(path, text, FIRED_KEY, None)
        if decision.transition:
            adr_id = str(meta.get("id") or path.stem)
            for label, observation in fired_items:
                counts["new"] += 1
                transitions.append({
                    "kind": "fire", "adr": target, "id": adr_id, "key": label,
                    "observation": observation, "path": str(path),
                    "title": f"[p2] ADR fired: {alias}:{adr_id} {label}",
                    "line": f"{alias}:{adr_id} {label}: {observation}",
                })

    # --- pass 2: cascade over depends_on -------------------------------------
    # Re-read: pass 1 may have just written a `fired:` line into this file.
    for alias, path in adrs:
        target = f"{alias}:{path.name}"
        text, read_err = read_adr(path)
        if read_err or text is None:
            continue
        meta, parse_err = parse_frontmatter(text)
        if parse_err:
            continue
        entries = normalize_depends_on(meta.get("depends_on"))
        if not entries:
            continue

        losses: list[tuple[str, str, str]] = []  # (ref, reason, severity)
        errored = False
        for ref, claim in entries:
            if not ref:
                emit(target, "support", "-", "skip", 0, "unverifiable: no ref")
                continue
            resolved, note = resolve_ref(ref, path, roots, env)
            if resolved is not None and resolved.resolve() == path.resolve():
                emit(target, "support", ref, "skip", 0, "self-reference")
                continue
            if note == "missing":
                losses.append((ref, "missing", "hard"))
                emit(target, "support", ref, "lost", 0, "missing")
                continue
            if note is not None:
                emit(target, "support", ref, "skip", 0, note)
                continue
            reason, severity, error = loss_reason(resolved)
            if error:
                errored = True
                counts["errors"] += 1
                emit(target, "support", ref, "error", 0, error)
                continue
            if reason is None:
                emit(target, "support", ref, "clean", 0, "")
                continue
            losses.append((ref, reason, severity))
            emit(target, "support", ref, "lost" if severity == "hard" else "lost-soft", 0, reason)

        counts["lost"] += len(losses)
        new_pairs = {f"{ref} {reason}" for ref, reason, _ in losses}
        new_value = format_support_value(today, [(r, reason) for r, reason, _ in losses]) if losses else None
        existing = meta.get(SUPPORT_KEY)
        existing = None if existing is None else str(existing)
        hard_pairs = {f"{ref} {reason}" for ref, reason, sev in losses if sev == "hard"}
        decision = decide_support(existing, new_value, new_pairs, bool(hard_pairs),
                                  may_heal=not errored)
        if decision.log_status:
            emit(target, "support", "-", decision.log_status, 0, new_value or "")
        if decision.action == "write":
            write_line(path, text, SUPPORT_KEY, new_value)
        elif decision.action == "remove":
            write_line(path, text, SUPPORT_KEY, None)
        if decision.transition:
            adr_id = str(meta.get("id") or path.stem)
            already = support_pairs(existing)
            for ref, reason, severity in losses:
                if severity != "hard" or f"{ref} {reason}" in already:
                    continue
                counts["new"] += 1
                transitions.append({
                    "kind": "support", "adr": target, "id": adr_id, "key": ref,
                    "observation": reason, "path": str(path),
                    "title": f"[p2] ADR support lost: {alias}:{adr_id} {ref}",
                    "line": f"{alias}:{adr_id} {ref} {reason}",
                })

    # --- side effects --------------------------------------------------------
    fires = [t for t in transitions if t["kind"] == "fire"]
    losses_new = [t for t in transitions if t["kind"] == "support"]
    tasks_opened: list[str] = []
    notified = False

    if not args.dry_run:
        if not args.no_tasks:
            for item in transitions:
                notes = f"{item['observation']}\n{item['path']}"
                if open_task(item["title"], notes, env):
                    tasks_opened.append(item["title"])
                else:
                    emit(item["adr"], "lint", "task-skipped", "skip", 0, item["title"])
        if transitions and not args.no_notify:
            title = f"ADR sweep: {len(fires)} fired, {len(losses_new)} support lost"
            notified = send_notify(title, notify_body([t["line"] for t in transitions]), env)

    emit("-", "run", "-", "done", 0, summary_fields(counts))

    if not args.dry_run:
        destination = log_path(env)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as fh:
            fh.write("".join(line + "\n" for line in records))

    return {
        **counts,
        "dry_run": args.dry_run,
        "roots": [alias for alias, _ in roots],
        "transitions": transitions,
        "tasks_opened": tasks_opened,
        "notified": notified,
        "log": records,
    }


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = parse_args(argv)
        report = sweep(argv)
    except Exception:  # cron-safe: only an internal crash is non-zero
        traceback.print_exc()
        return 2
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    if report["dry_run"]:
        for item in report["transitions"]:
            print(f"would write {item['kind']}: {item['line']}")
    print(
        f"ADR sweep{' (dry-run)' if report['dry_run'] else ''}: {summary_fields(report)}"
        f" | roots={len(report['roots'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
