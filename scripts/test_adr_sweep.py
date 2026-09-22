# pattern: imperative shell
"""Tests for adr-sweep.py — the mechanical ADR falsifier sweep.

Every test is hermetic. The `fleet` fixture points ADR_SWEEP_ROOTS / _CLAUDE_DIR /
_PROJECTS / _STATE / _MEMORY_ROOT / _NOTIFY / _TASK at tmp_path and repoints the
module's HOME, so no real ADR, log file, notification, or tracker item is ever
touched. Tests that want to observe a notify/task call point the override at a
recorder script instead.

Run: cd ~/.claude/scripts && python3 -m pytest test_adr_sweep.py -q
"""

import importlib.util
import os
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().with_name("adr-sweep.py")
_spec = importlib.util.spec_from_file_location("adr_sweep", MODULE_PATH)
adr_sweep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adr_sweep)

TODAY = date.today().isoformat()


# --------------------------------------------------------------- helpers ---


def write_adr(directory: Path, name: str, front: str, body: str = "\n# Title\n\nProse.\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("---\n" + front.strip("\n") + "\n---\n" + body, encoding="utf-8")
    return path


def recorder(tmp_path: Path, name: str) -> SimpleNamespace:
    """A shell script that appends its argv to a record file, one call per line."""
    record = tmp_path / f"{name}.record"
    script = tmp_path / f"{name}.sh"
    # newlines inside an argument (task notes carry one) are folded so that one
    # invocation is always exactly one recorded line
    script.write_text(
        "#!/usr/bin/env bash\n"
        f'{{ printf "%s\\t" "$@" | tr "\\n" "~"; printf "\\n"; }} >> {record}\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return SimpleNamespace(script=script, record=record,
                           calls=lambda: record.read_text().splitlines() if record.exists() else [])


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    house = tmp_path / "house" / "docs" / "decisions"
    house.mkdir(parents=True)
    state = tmp_path / "state"
    memroot = tmp_path / "projects"
    memroot.mkdir()
    monkeypatch.setattr(adr_sweep, "HOME", home)
    monkeypatch.setenv("ADR_SWEEP_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("ADR_SWEEP_PROJECTS", str(home / "Projects"))
    monkeypatch.setenv("ADR_SWEEP_ROOTS", f"house={house}")
    monkeypatch.setenv("ADR_SWEEP_STATE", str(state))
    monkeypatch.setenv("ADR_SWEEP_MEMORY_ROOT", str(memroot))
    monkeypatch.delenv("ADR_SWEEP_LOG", raising=False)
    monkeypatch.delenv("ADR_SWEEP_SUBDIR", raising=False)
    monkeypatch.delenv("ADR_SWEEP_EXTRA_ROOTS", raising=False)
    # neutralize side channels by default; a test that wants them points them at a recorder
    monkeypatch.setenv("ADR_SWEEP_NOTIFY", str(tmp_path / "no-such-notify.sh"))
    monkeypatch.setenv("ADR_SWEEP_TASK", str(tmp_path / "no-such-task.sh"))
    return SimpleNamespace(tmp=tmp_path, home=home, house=house, state=state, memroot=memroot,
                           log=state / "adr-sweep.log")


def fired_line(path: Path) -> str | None:
    for line in path.read_text().splitlines():
        if line.startswith("fired:"):
            return line
    return None


def support_line(path: Path) -> str | None:
    for line in path.read_text().splitlines():
        if line.startswith("support_lost:"):
            return line
    return None


# ------------------------------------------------------- frontmatter core ---


def test_parse_frontmatter_good():
    text = "---\nid: 01-x\nstatus: draft\n---\n\n# Body\n"
    meta, err = adr_sweep.parse_frontmatter(text)
    assert err is None
    assert meta["id"] == "01-x"
    assert meta["status"] == "draft"


def test_parse_frontmatter_missing_block_is_not_an_error():
    meta, err = adr_sweep.parse_frontmatter("# Just a heading\n\nno frontmatter\n")
    assert (meta, err) == ({}, None)


def test_parse_frontmatter_malformed_yaml_is_an_error():
    meta, err = adr_sweep.parse_frontmatter("---\nid: [unclosed\nstatus: draft\n---\n\nbody\n")
    assert meta == {}
    assert err is not None


def test_parse_frontmatter_unterminated_block_is_an_error():
    meta, err = adr_sweep.parse_frontmatter("---\nid: 01-x\n\n# body with no closing delimiter\n")
    assert meta == {}
    assert err is not None


def test_parse_frontmatter_ignores_indented_delimiter_inside_block_scalar():
    text = "---\nid: 01-x\ncmd: |\n  echo one\n  ---\n  echo two\nstatus: draft\n---\n\nbody\n"
    meta, err = adr_sweep.parse_frontmatter(text)
    assert err is None
    assert meta["status"] == "draft"


def test_status_normalization_and_classification():
    assert adr_sweep.status_word({"status": "  ACTIVE "}) == "active"
    assert adr_sweep.status_word({}) == ""
    assert adr_sweep.classify_status("active") == "alive"
    assert adr_sweep.classify_status("draft") == "alive"
    assert adr_sweep.classify_status("retracted") == "hard-dead"
    assert adr_sweep.classify_status("rejected") == "hard-dead"
    assert adr_sweep.classify_status("superseded") == "soft-dead"
    assert adr_sweep.classify_status("deprecated") == "soft-dead"
    assert adr_sweep.classify_status("mothballed") == "unknown"
    assert adr_sweep.classify_status("") == "absent"


def test_normalize_falsifiers_labels_bare_strings_by_index():
    entries, problems = adr_sweep.normalize_falsifiers(
        ["echo a", {"label": "named", "cmd": "echo b"}, {"cmd": "echo c"}]
    )
    assert entries == [("f1", "echo a"), ("named", "echo b"), ("f3", "echo c")]
    assert problems == []


def test_normalize_falsifiers_reports_entry_without_cmd():
    entries, problems = adr_sweep.normalize_falsifiers([{"label": "bad"}])
    assert entries == []
    assert problems and problems[0][0] == "bad"


def test_normalize_depends_on_accepts_bare_string_and_map():
    entries = adr_sweep.normalize_depends_on(["house:03", {"ref": "04", "claim": "c"}, {"claim": "x"}])
    assert entries == [("house:03", None), ("04", "c"), (None, "x")]


# ------------------------------------------------ exit codes, observation ---


@pytest.mark.parametrize(
    "code,expected",
    [(0, "clean"), (1, "fired"), (124, "error"), (2, "error"), (127, "error"), (-9, "error")],
)
def test_classify_exit(code, expected):
    assert adr_sweep.classify_exit(code) == expected


def test_observation_prefers_first_non_empty_stdout_line():
    assert adr_sweep.extract_observation("\n\nfires=3 false=1\nsecond\n", "err") == "fires=3 false=1"


def test_observation_falls_back_to_stderr():
    assert adr_sweep.extract_observation("   \n", "\nboom: no such file\n") == "boom: no such file"


def test_observation_strips_control_characters():
    assert adr_sweep.extract_observation("a\x00b\x07c\x1bd\ttail", "") == "abcdtail"


def test_observation_truncates_to_200_chars():
    obs = adr_sweep.extract_observation("x" * 500, "")
    assert len(obs) == 200


def test_observation_empty_when_both_streams_empty():
    assert adr_sweep.extract_observation("", "") == ""


# ------------------------------------------------------ line construction ---


def test_format_fired_value_single_and_multi_label():
    assert adr_sweep.format_fired_value("2026-09-10", [("a", "n=1")]) == "2026-09-10 — a: n=1"
    assert (
        adr_sweep.format_fired_value("2026-09-10", [("a", "n=1"), ("b", "n=2")])
        == "2026-09-10 — a: n=1; b: n=2"
    )


def test_yaml_single_quote_escaping():
    assert adr_sweep.quote_yaml_scalar("it's") == "'it''s'"
    text = "---\nid: 01-x\n---\n\nbody\n"
    out = adr_sweep.upsert_frontmatter_line(text, "fired", "2026-09-10 — a: it's fine")
    assert "fired: '2026-09-10 — a: it''s fine'" in out


def test_upsert_inserts_before_closing_delimiter_and_preserves_every_other_byte():
    text = "---\nid: 01-x\nstatus: draft\n---\n\n# Title  \n\ntrailing spaces  \nünïcode\nno newline at eof"
    out = adr_sweep.upsert_frontmatter_line(text, "fired", "2026-09-10 — a: n=1")
    lines = out.splitlines()
    assert lines[3] == "fired: '2026-09-10 — a: n=1'"
    assert lines[4] == "---"
    # everything else survives byte-for-byte
    assert out.replace("fired: '2026-09-10 — a: n=1'\n", "", 1) == text


def test_upsert_replaces_existing_line_in_place():
    text = "---\nid: 01-x\nfired: 'old'\nstatus: draft\n---\n\nbody\n"
    out = adr_sweep.upsert_frontmatter_line(text, "fired", "new")
    assert out == "---\nid: 01-x\nfired: 'new'\nstatus: draft\n---\n\nbody\n"


def test_upsert_removes_line():
    text = "---\nid: 01-x\nfired: 'old'\nstatus: draft\n---\n\nbody\n"
    out = adr_sweep.upsert_frontmatter_line(text, "fired", None)
    assert out == "---\nid: 01-x\nstatus: draft\n---\n\nbody\n"


def test_upsert_without_frontmatter_is_a_no_op():
    text = "# no frontmatter\n"
    assert adr_sweep.upsert_frontmatter_line(text, "fired", "x") == text


def test_adjudication_detection():
    assert adr_sweep.adjudication(None) is None
    assert adr_sweep.adjudication("2026-09-10 — a: n=1") is None
    assert adr_sweep.adjudication("2026-09-10 — a: n=1 — adjudicated: real 2026-09-11") == "real"
    assert adr_sweep.adjudication("2026-09-10 — a: n=1 — adjudicated: false 2026-09-11") == "false"


def test_support_pairs_ignores_date_and_adjudication():
    value = "2026-09-10 — house:03 missing; 04 retracted — adjudicated: real 2026-09-11"
    assert adr_sweep.support_pairs(value) == {"house:03 missing", "04 retracted"}


# ------------------------------------------------------- falsifier sweeps ---


def test_new_fire_writes_line_and_records_a_transition(fleet):
    adr = write_adr(
        fleet.house,
        "01-fires.md",
        "id: 01-fires\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'echo \"n=7\"; exit 1'\n",
    )
    report = adr_sweep.sweep([])
    assert report["fired"] == 1
    assert report["new"] == 1
    assert fired_line(adr) == f"fired: '{TODAY} — alpha: n=7'"
    assert report["transitions"][0]["kind"] == "fire"


def test_clean_falsifier_writes_no_line(fleet):
    adr = write_adr(
        fleet.house,
        "01-clean.md",
        "id: 01-clean\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'exit 0'\n",
    )
    report = adr_sweep.sweep([])
    assert report["fired"] == 0
    assert fired_line(adr) is None


def test_two_fired_labels_join_with_semicolon(fleet):
    adr = write_adr(
        fleet.house,
        "01-two.md",
        "id: 01-two\nstatus: draft\nfalsifier_cmd:\n"
        "  - label: alpha\n    cmd: 'echo a=1; exit 1'\n"
        "  - label: beta\n    cmd: 'echo b=2; exit 1'\n",
    )
    adr_sweep.sweep([])
    assert fired_line(adr) == f"fired: '{TODAY} — alpha: a=1; beta: b=2'"


def test_refire_overwrites_unadjudicated_line_and_is_not_a_transition(fleet):
    adr = write_adr(
        fleet.house,
        "01-refire.md",
        "id: 01-refire\nstatus: draft\nfired: '2026-01-01 — alpha: n=1'\n"
        "falsifier_cmd:\n  - label: alpha\n    cmd: 'echo n=9; exit 1'\n",
    )
    report = adr_sweep.sweep([])
    assert fired_line(adr) == f"fired: '{TODAY} — alpha: n=9'"
    assert report["new"] == 0
    assert any("\trefire\t" in line for line in report["log"])


def test_adjudicated_false_line_is_left_untouched(fleet):
    original = (
        "id: 01-false\nstatus: draft\n"
        "fired: '2026-01-01 — alpha: n=1 — adjudicated: false 2026-01-02'\n"
        "falsifier_cmd:\n  - label: alpha\n    cmd: 'echo n=9; exit 1'\n"
    )
    adr = write_adr(fleet.house, "01-false.md", original)
    before = adr.read_text()
    report = adr_sweep.sweep([])
    assert adr.read_text() == before
    assert report["new"] == 0
    assert any("\trefire-suppressed\t" in line for line in report["log"])


def test_adjudicated_real_line_is_left_untouched(fleet):
    adr = write_adr(
        fleet.house,
        "01-real.md",
        "id: 01-real\nstatus: draft\n"
        "fired: '2026-01-01 — alpha: n=1 — adjudicated: real 2026-01-02'\n"
        "falsifier_cmd:\n  - label: alpha\n    cmd: 'echo n=9; exit 1'\n",
    )
    before = adr.read_text()
    report = adr_sweep.sweep([])
    assert adr.read_text() == before
    assert report["new"] == 0
    assert any("\trefire\t" in line for line in report["log"])


def test_clean_run_self_heals_an_unadjudicated_line(fleet):
    adr = write_adr(
        fleet.house,
        "01-heal.md",
        "id: 01-heal\nstatus: draft\nfired: '2026-01-01 — alpha: n=1'\n"
        "falsifier_cmd:\n  - label: alpha\n    cmd: 'exit 0'\n",
    )
    report = adr_sweep.sweep([])
    assert fired_line(adr) is None
    assert adr.read_text() == "---\nid: 01-heal\nstatus: draft\nfalsifier_cmd:\n" \
                              "  - label: alpha\n    cmd: 'exit 0'\n---\n\n# Title\n\nProse.\n"
    assert any("\thealed\t" in line for line in report["log"])


def test_clean_run_keeps_an_adjudicated_line(fleet):
    adr = write_adr(
        fleet.house,
        "01-keep.md",
        "id: 01-keep\nstatus: draft\n"
        "fired: '2026-01-01 — alpha: n=1 — adjudicated: real 2026-01-02'\n"
        "falsifier_cmd:\n  - label: alpha\n    cmd: 'exit 0'\n",
    )
    before = adr.read_text()
    adr_sweep.sweep([])
    assert adr.read_text() == before


def test_error_exit_does_not_fire_and_does_not_self_heal(fleet):
    adr = write_adr(
        fleet.house,
        "01-err.md",
        "id: 01-err\nstatus: draft\nfired: '2026-01-01 — alpha: n=1'\n"
        "falsifier_cmd:\n  - label: alpha\n    cmd: 'echo boom >&2; exit 3'\n",
    )
    report = adr_sweep.sweep([])
    assert report["fired"] == 0
    assert report["errors"] == 1
    assert fired_line(adr) == "fired: '2026-01-01 — alpha: n=1'"


def test_timeout_is_an_error_not_a_fire(fleet, monkeypatch):
    monkeypatch.setattr(adr_sweep, "COMMAND_TIMEOUT_SECONDS", 1)
    adr = write_adr(
        fleet.house,
        "01-slow.md",
        "id: 01-slow\nstatus: draft\nfalsifier_cmd:\n  - label: slow\n    cmd: 'sleep 3'\n",
    )
    report = adr_sweep.sweep([])
    assert report["fired"] == 0
    assert report["errors"] == 1
    assert fired_line(adr) is None
    assert any("\tfalsifier\tslow\terror\t124\t" in line for line in report["log"])


def test_falsifier_command_sees_adr_file_and_dir_env(fleet):
    adr = write_adr(
        fleet.house,
        "01-env.md",
        "id: 01-env\nstatus: draft\nfalsifier_cmd:\n"
        "  - label: env\n    cmd: 'echo \"$ADR_FILE|$ADR_DIR|$PWD\"; exit 1'\n",
    )
    adr_sweep.sweep([])
    line = fired_line(adr)
    assert str(adr) in line
    assert str(fleet.house) in line
    # cwd is the repo root: the parent of the docs dir
    assert str(fleet.tmp / "house") in line


def test_parse_error_is_logged_and_the_sweep_continues(fleet):
    (fleet.house / "01-broken.md").write_text("---\nid: [unclosed\n---\n\nbody\n", encoding="utf-8")
    write_adr(
        fleet.house,
        "02-ok.md",
        "id: 02-ok\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'echo x; exit 1'\n",
    )
    report = adr_sweep.sweep([])
    assert report["errors"] == 1
    assert report["fired"] == 1
    assert any("\terror\t" in line and "01-broken.md" in line for line in report["log"])


def test_lint_until_missing_on_dead_status(fleet):
    write_adr(fleet.house, "01-dead.md", "id: 01-dead\nstatus: superseded\n")
    report = adr_sweep.sweep([])
    assert any("\tlint\tuntil-missing\tlint\t" in line for line in report["log"])


def test_lint_status_unknown(fleet):
    write_adr(fleet.house, "01-odd.md", "id: 01-odd\nstatus: mothballed\n")
    report = adr_sweep.sweep([])
    assert any("\tlint\tstatus-unknown\tlint\t" in line for line in report["log"])


# ------------------------------------------------------- tasks and notify ---


def test_task_opened_exactly_once_per_new_fire(fleet, tmp_path, monkeypatch):
    task = recorder(tmp_path, "task")
    monkeypatch.setenv("ADR_SWEEP_TASK", str(task.script))
    write_adr(
        fleet.house,
        "01-fires.md",
        "id: 01-fires\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'echo n=7; exit 1'\n",
    )
    adr_sweep.sweep([])
    calls = task.calls()
    assert len(calls) == 1
    assert calls[0].startswith("[p2] ADR fired: house:01-fires alpha")
    adr_sweep.sweep([])  # re-fire: frontmatter and log only
    assert len(task.calls()) == 1


def test_no_tasks_flag_suppresses_the_task(fleet, tmp_path, monkeypatch):
    task = recorder(tmp_path, "task")
    monkeypatch.setenv("ADR_SWEEP_TASK", str(task.script))
    write_adr(
        fleet.house,
        "01-fires.md",
        "id: 01-fires\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'echo n=7; exit 1'\n",
    )
    adr_sweep.sweep(["--no-tasks"])
    assert task.calls() == []


def test_missing_task_hook_logs_task_skipped(fleet):
    write_adr(
        fleet.house,
        "01-fires.md",
        "id: 01-fires\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'echo n=7; exit 1'\n",
    )
    report = adr_sweep.sweep([])
    assert any("task-skipped" in line for line in report["log"])


def test_notify_fires_once_per_run_with_the_item_lines(fleet, tmp_path, monkeypatch):
    notify = recorder(tmp_path, "notify")
    monkeypatch.setenv("ADR_SWEEP_NOTIFY", str(notify.script))
    write_adr(
        fleet.house,
        "01-a.md",
        "id: 01-a\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'echo n=7; exit 1'\n",
    )
    write_adr(
        fleet.house,
        "02-b.md",
        "id: 02-b\nstatus: draft\nfalsifier_cmd:\n  - label: beta\n    cmd: 'echo n=8; exit 1'\n",
    )
    adr_sweep.sweep([])
    calls = notify.calls()
    assert len(calls) == 1
    assert calls[0].startswith("ADR sweep: 2 fired, 0 support lost")


def test_notify_silent_when_nothing_is_new(fleet, tmp_path, monkeypatch):
    notify = recorder(tmp_path, "notify")
    monkeypatch.setenv("ADR_SWEEP_NOTIFY", str(notify.script))
    write_adr(
        fleet.house,
        "01-clean.md",
        "id: 01-clean\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'exit 0'\n",
    )
    adr_sweep.sweep([])
    assert notify.calls() == []


# --------------------------------------------------------- ref resolution ---


def test_resolve_ref_every_grammar_form(fleet, tmp_path, monkeypatch):
    other = tmp_path / "proj" / "docs" / "decisions"
    monkeypatch.setenv("ADR_SWEEP_ROOTS", f"house={fleet.house}:widget={other}")
    house_target = write_adr(fleet.house, "03-house-target.md", "id: 03-house-target\nstatus: draft\n")
    proj_target = write_adr(other, "07-proj-target.md", "id: 07-proj-target\nstatus: draft\n")
    citing = write_adr(fleet.house, "09-citing.md", "id: 09-citing\nstatus: draft\n")
    mem = fleet.memroot / adr_sweep.encode_project_path(fleet.home) / "memory"
    mem.mkdir(parents=True)
    (mem / "patterns.md").write_text("x", encoding="utf-8")
    projmem = (fleet.memroot
               / adr_sweep.encode_project_path(fleet.home / "Projects" / "widget") / "memory")
    projmem.mkdir(parents=True)
    (projmem / "stage.md").write_text("x", encoding="utf-8")

    roots = adr_sweep.enumerate_roots(os.environ)
    resolve = lambda ref: adr_sweep.resolve_ref(ref, citing, roots, os.environ)

    assert resolve("house:03") == (house_target, None)
    assert resolve("widget:07") == (proj_target, None)
    assert resolve("03") == (house_target, None)  # bare NN: the citing ADR's own dir
    assert resolve("mem:patterns") == (mem / "patterns.md", None)
    assert resolve("mem:widget/stage") == (projmem / "stage.md", None)
    assert resolve("house:99") == (None, "missing")
    assert resolve("mem:nope") == (None, "missing")
    assert resolve("nosuchalias:03") == (None, "unknown-alias")


def test_encode_project_path_mirrors_the_cwd_encoding():
    assert adr_sweep.encode_project_path(Path("/home/you/Projects/foo")) == "-home-you-Projects-foo"
    assert adr_sweep.encode_project_path(Path("/home/you")) == "-home-you"


# ---------------------------------------------------------------- cascade ---


def cite(fleet, name, adr_id, refs):
    block = "\n".join(f"  - ref: {r}\n    claim: because\n" for r in refs)
    return write_adr(fleet.house, name, f"id: {adr_id}\nstatus: draft\ndepends_on:\n{block}")


def test_cascade_missing_target_is_a_hard_loss(fleet):
    citing = cite(fleet, "01-citing.md", "01-citing", ["house:99"])
    report = adr_sweep.sweep([])
    assert support_line(citing) == f"support_lost: '{TODAY} — house:99 missing'"
    assert report["new"] == 1
    assert report["transitions"][0]["kind"] == "support"


@pytest.mark.parametrize("status", ["retracted", "rejected"])
def test_cascade_hard_dead_target(fleet, status):
    write_adr(fleet.house, "02-target.md", f"id: 02-target\nstatus: {status}\nuntil: 2026-01-01\n")
    citing = cite(fleet, "01-citing.md", "01-citing", ["02"])
    adr_sweep.sweep([])
    assert support_line(citing) == f"support_lost: '{TODAY} — 02 {status}'"


def test_cascade_target_with_adjudicated_real_fire(fleet):
    write_adr(
        fleet.house,
        "02-target.md",
        "id: 02-target\nstatus: active\nfired: '2026-01-01 — a: n=1 — adjudicated: real 2026-01-02'\n",
    )
    citing = cite(fleet, "01-citing.md", "01-citing", ["02"])
    adr_sweep.sweep([])
    assert support_line(citing) == f"support_lost: '{TODAY} — 02 fired-real'"


def test_cascade_superseded_names_the_successor(fleet):
    write_adr(fleet.house, "02-target.md", "id: 02-target\nstatus: superseded\nuntil: 2026-02-02\n")
    write_adr(fleet.house, "03-heir.md", "id: 03-heir\nstatus: active\nsupersedes: 02-target\n")
    citing = cite(fleet, "01-citing.md", "01-citing", ["02"])
    report = adr_sweep.sweep([])
    assert support_line(citing) == f"support_lost: '{TODAY} — 02 superseded→03-heir'"
    assert report["new"] == 0  # soft loss: line + log, no task
    assert any("\tlost-soft\t" in line for line in report["log"])


def test_cascade_superseded_without_a_successor(fleet):
    write_adr(fleet.house, "02-target.md", "id: 02-target\nstatus: superseded\nuntil: 2026-02-02\n")
    citing = cite(fleet, "01-citing.md", "01-citing", ["02"])
    adr_sweep.sweep([])
    assert support_line(citing) == f"support_lost: '{TODAY} — 02 superseded→?'"


def test_cascade_is_one_hop_only(fleet):
    write_adr(fleet.house, "03-dead.md", "id: 03-dead\nstatus: retracted\nuntil: 2026-01-01\n")
    middle = cite(fleet, "02-middle.md", "02-middle", ["03"])
    top = cite(fleet, "01-top.md", "01-top", ["02"])
    adr_sweep.sweep([])
    assert support_line(middle) is not None
    assert support_line(top) is None  # 02 is alive; its own loss does not propagate


def test_support_lost_target_does_not_cascade(fleet):
    write_adr(
        fleet.house,
        "02-middle.md",
        "id: 02-middle\nstatus: active\nsupport_lost: '2026-01-01 — 03 missing'\n",
    )
    top = cite(fleet, "01-top.md", "01-top", ["02"])
    adr_sweep.sweep([])
    assert support_line(top) is None


def test_cascade_self_reference_is_ignored(fleet):
    citing = cite(fleet, "01-self.md", "01-self", ["01"])
    report = adr_sweep.sweep([])
    assert support_line(citing) is None
    assert any("self-reference" in line for line in report["log"])


def test_depends_on_entry_without_ref_is_skipped(fleet):
    citing = write_adr(
        fleet.house, "01-noref.md", "id: 01-noref\nstatus: draft\ndepends_on:\n  - claim: vibes\n"
    )
    report = adr_sweep.sweep([])
    assert support_line(citing) is None
    assert any("\tsupport\t" in line and "\tskip\t" in line for line in report["log"])


def test_unchanged_support_set_is_not_a_transition(fleet):
    cite(fleet, "01-citing.md", "01-citing", ["house:99"])
    first = adr_sweep.sweep([])
    assert first["new"] == 1
    second = adr_sweep.sweep([])
    assert second["new"] == 0
    assert second["lost"] == 1


def test_support_line_self_heals_when_the_target_comes_back(fleet):
    citing = cite(fleet, "01-citing.md", "01-citing", ["02"])
    adr_sweep.sweep([])
    assert support_line(citing) is not None
    write_adr(fleet.house, "02-target.md", "id: 02-target\nstatus: active\n")
    report = adr_sweep.sweep([])
    assert support_line(citing) is None
    assert any("\thealed\t" in line for line in report["log"])


def test_mem_ref_resolution_in_a_sweep(fleet):
    citing = cite(fleet, "01-citing.md", "01-citing", ["mem:gone"])
    adr_sweep.sweep([])
    assert support_line(citing) == f"support_lost: '{TODAY} — mem:gone missing'"


# ----------------------------------------------- enumeration, log, dry-run ---


def test_default_scan_covers_house_and_every_project_repo(tmp_path, monkeypatch):
    monkeypatch.delenv("ADR_SWEEP_ROOTS", raising=False)
    monkeypatch.setattr(adr_sweep, "HOME", tmp_path)
    (tmp_path / ".claude" / "docs" / "decisions").mkdir(parents=True)
    for name, git_is_file in (("alpha", False), ("beta", True)):
        repo = tmp_path / "Projects" / name
        (repo / "docs" / "decisions").mkdir(parents=True)
        if git_is_file:
            # a linked-worktree checkout: its ADRs are already counted under the main checkout
            (repo / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        else:
            (repo / ".git").mkdir()
    aliases = [alias for alias, _ in adr_sweep.enumerate_roots({})]
    assert "alpha" in aliases
    assert "beta" not in aliases
    assert "house" in aliases


def test_roots_env_override_replaces_the_whole_list(fleet):
    aliases = [alias for alias, _ in adr_sweep.enumerate_roots(os.environ)]
    assert aliases == ["house"]


def test_extra_roots_are_appended_to_the_default_scan(tmp_path, monkeypatch):
    monkeypatch.delenv("ADR_SWEEP_ROOTS", raising=False)
    monkeypatch.setattr(adr_sweep, "HOME", tmp_path)
    (tmp_path / ".claude" / "docs" / "decisions").mkdir(parents=True)
    vendored = tmp_path / "elsewhere" / "docs" / "decisions"
    vendored.mkdir(parents=True)
    env = {"ADR_SWEEP_EXTRA_ROOTS": f"vendored={vendored}"}
    assert [alias for alias, _ in adr_sweep.enumerate_roots(env)] == ["house", "vendored"]


def test_projects_root_and_subdir_are_configurable(tmp_path, monkeypatch):
    monkeypatch.delenv("ADR_SWEEP_ROOTS", raising=False)
    monkeypatch.setattr(adr_sweep, "HOME", tmp_path)
    repo = tmp_path / "repos" / "alpha"
    (repo / "adr").mkdir(parents=True)
    (repo / ".git").mkdir()
    env = {"ADR_SWEEP_PROJECTS": str(tmp_path / "repos"), "ADR_SWEEP_SUBDIR": "adr"}
    assert [alias for alias, _ in adr_sweep.enumerate_roots(env)] == ["alpha"]
    # the falsifier's cwd is the repo root, whatever the subdir is named
    assert adr_sweep.command_cwd(repo / "adr" / "01-x.md", env) == repo


def test_only_filter_restricts_the_sweep(fleet):
    kept = write_adr(
        fleet.house,
        "01-keeper.md",
        "id: 01-keeper\nstatus: draft\nfalsifier_cmd:\n  - label: a\n    cmd: 'echo x; exit 1'\n",
    )
    skipped = write_adr(
        fleet.house,
        "02-other.md",
        "id: 02-other\nstatus: draft\nfalsifier_cmd:\n  - label: b\n    cmd: 'echo y; exit 1'\n",
    )
    report = adr_sweep.sweep(["--only", "keeper"])
    assert report["adrs"] == 1
    assert fired_line(kept) is not None
    assert fired_line(skipped) is None


def test_log_lines_and_summary_heartbeat(fleet):
    write_adr(
        fleet.house,
        "01-fires.md",
        "id: 01-fires\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'echo n=7; exit 1'\n",
    )
    adr_sweep.sweep([])
    lines = fleet.log.read_text().splitlines()
    first = lines[0].split("\t")
    assert len(first) == 7
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$", first[0])
    assert first[1] == "house:01-fires.md"
    assert first[2] == "falsifier"
    assert first[3] == "alpha"
    assert first[4] == "fired"
    assert first[5] == "1"
    assert first[6] == "n=7"
    summary = lines[-1].split("\t")
    assert summary[1:6] == ["-", "run", "-", "done", "0"]
    assert summary[6] == "adrs=1 cmds=1 fired=1 lost=0 errors=0 new=1"


def test_log_path_is_configurable(fleet, monkeypatch):
    elsewhere = fleet.tmp / "logs" / "sweep.tsv"
    monkeypatch.setenv("ADR_SWEEP_LOG", str(elsewhere))
    write_adr(fleet.house, "01-clean.md", "id: 01-clean\nstatus: draft\n")
    adr_sweep.sweep([])
    assert elsewhere.exists()          # created, parent dirs and all
    assert not fleet.log.exists()      # and the default location stays untouched


def test_log_appends_across_runs(fleet):
    write_adr(
        fleet.house,
        "01-clean.md",
        "id: 01-clean\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'exit 0'\n",
    )
    adr_sweep.sweep([])
    first = len(fleet.log.read_text().splitlines())
    adr_sweep.sweep([])
    assert len(fleet.log.read_text().splitlines()) == 2 * first


def test_dry_run_writes_nothing(fleet, tmp_path, monkeypatch):
    task = recorder(tmp_path, "task")
    notify = recorder(tmp_path, "notify")
    monkeypatch.setenv("ADR_SWEEP_TASK", str(task.script))
    monkeypatch.setenv("ADR_SWEEP_NOTIFY", str(notify.script))
    adr = write_adr(
        fleet.house,
        "01-fires.md",
        "id: 01-fires\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'echo n=7; exit 1'\n",
    )
    before = adr.read_text()
    report = adr_sweep.sweep(["--dry-run"])
    assert report["fired"] == 1
    assert report["new"] == 1  # the transition is computed, just not applied
    assert adr.read_text() == before
    assert not fleet.log.exists()
    assert task.calls() == []
    assert notify.calls() == []


def test_main_exits_zero_and_prints_a_summary(fleet, capsys):
    write_adr(
        fleet.house,
        "01-clean.md",
        "id: 01-clean\nstatus: draft\nfalsifier_cmd:\n  - label: alpha\n    cmd: 'exit 0'\n",
    )
    assert adr_sweep.main([]) == 0
    out = capsys.readouterr().out
    assert "adrs=1" in out


def test_main_json_output(fleet, capsys):
    import json

    write_adr(fleet.house, "01-clean.md", "id: 01-clean\nstatus: draft\n")
    assert adr_sweep.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["adrs"] == 1
