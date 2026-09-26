#!/usr/bin/env python3
"""PropterMaltwo multi-host installer (Python standard library only).

The functional core builds concrete file operations from manifests/hosts-v1.json.
The imperative shell serializes mutations through a flock, journals every
operation before it runs, writes files atomically, and commits the ledger last.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = 1
LEDGER_SCHEMA = 1
JOURNAL_SCHEMA = 1
ACTIVATION_SCHEMA = 1
STATIC_VALUES = {"native", "adapted", "degraded", "unsupported", "not-tested"}
ACTIVATION_VALUES = {"verified-active", "installed-untrusted", "inactive", "unverified", "failed"}
CAPABILITY_KEYS = {"instructions", "skills", "memory", "subagents", "identity_hooks", "permissions", "integrations"}
LEGACY_ROOTS = ("CLAUDE.md", "rules", "skills", "hooks", "templates", "scripts", "docs", "statusline-command.sh")
EXEC_PATTERNS = (
    re.compile(r"^hooks/.*\.(?:sh|py)$"),
    re.compile(r"^scripts/"),
    re.compile(r"^statusline-command\.sh$"),
    re.compile(r"^skills/[^/]+/scripts/"),
)


class InstallerError(Exception):
    """Expected refusal with a useful user-facing message."""


@dataclasses.dataclass(frozen=True)
class Targets:
    claude_home: Path
    codex_home: Path
    codex_skills_home: Path
    polytoken_home: Path
    proptermaltwo_home: Path
    project: Path | None

    def get(self, name: str) -> Path:
        value = getattr(self, name)
        if value is None:
            raise InstallerError(f"target {name!r} requires --project")
        return value


@dataclasses.dataclass
class Operation:
    destination: Path
    owners: set[str]
    operation: str
    source: str | None = None
    content: bytes | None = None
    mode: int = 0o644
    link_target: str | None = None
    note: str = ""
    managed_definition_hashes: list[str] = dataclasses.field(default_factory=list)

    def identity(self) -> tuple[str, str, str | None]:
        return (str(self.destination), self.operation, self.link_target)


@dataclasses.dataclass
class Selection:
    hosts: dict[str, str]

    @property
    def owners(self) -> set[str]:
        return set(self.hosts)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()
        raise


def atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode(), mode)


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        try:
            path.rmdir()
        except OSError:
            raise InstallerError(f"refusing to remove nonempty directory: {path}")


def path_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_file():
        return "file"
    if path.exists():
        return "other"
    return "absent"


def current_fingerprint(path: Path) -> dict[str, Any]:
    kind = path_kind(path)
    result: dict[str, Any] = {"kind": kind}
    if kind == "file":
        result.update(checksum=sha256_file(path), mode=stat.S_IMODE(path.stat().st_mode))
    elif kind == "symlink":
        result["target"] = os.readlink(path)
    return result


def matches_record(path: Path, record: dict[str, Any]) -> bool:
    current = current_fingerprint(path)
    if record["operation"] == "symlink":
        return current == {"kind": "symlink", "target": record["installed_target"]}
    return current.get("kind") == "file" and current.get("checksum") == record.get("installed_checksum")


def load_json_strict(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise InstallerError(f"missing {label}: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallerError(f"corrupt {label} at {path}: {exc}") from exc


def load_manifest(repo: Path) -> dict[str, Any]:
    manifest = load_json_strict(repo / "manifests/hosts-v1.json", "host manifest")
    validate_manifest(manifest, repo, check_sources=False)
    return manifest


def validate_manifest(manifest: dict[str, Any], repo: Path, *, check_sources: bool = True) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"manifest schema_version must be {SCHEMA_VERSION}")
    hosts = manifest.get("hosts")
    if not isinstance(hosts, dict) or set(hosts) != {"claude-code", "codex", "polytoken", "copilot"}:
        errors.append("manifest hosts must be exactly claude-code, codex, polytoken, copilot")
        hosts = hosts if isinstance(hosts, dict) else {}
    sources: set[str] = set()
    for group in manifest.get("shared_groups", {}).values():
        for item in group:
            sources.update(filter(None, (item.get("source"), item.get("source_tree"))))
    for host_id, host in hosts.items():
        if host.get("maturity") not in {"first-class", "preview"}:
            errors.append(f"{host_id}: invalid maturity")
        supported = host.get("supported_profiles", [])
        profiles = host.get("profiles", {})
        if set(supported) != set(profiles):
            errors.append(f"{host_id}: supported_profiles and profiles differ")
        if host.get("default_profile") not in supported:
            errors.append(f"{host_id}: invalid default_profile")
        lifecycle = host.get("lifecycle", {})
        if host.get("maturity") == "first-class" and not all(lifecycle.get(key) is True for key in ("doctor", "rollback", "uninstall")):
            errors.append(f"{host_id}: first-class host lacks lifecycle declarations")
        previous_groups: set[str] = set()
        previous_skills: set[str] = set()
        for profile_name in manifest.get("profile_order", []):
            if profile_name not in profiles:
                continue
            profile = profiles[profile_name]
            capabilities = profile.get("capabilities", {})
            if set(capabilities) != CAPABILITY_KEYS:
                errors.append(f"{host_id}/{profile_name}: capability keys differ from schema")
            for key, value in capabilities.items():
                if value not in STATIC_VALUES:
                    errors.append(f"{host_id}/{profile_name}: invalid {key} status {value!r}")
            groups = set(profile.get("groups", []))
            skills_value = profile.get("skills", [])
            skills = set(skills_value if isinstance(skills_value, list) else [])
            if previous_groups - groups:
                errors.append(f"{host_id}/{profile_name}: profile groups are not monotonic")
            if previous_skills - skills:
                errors.append(f"{host_id}/{profile_name}: profile skills are not monotonic")
            previous_groups, previous_skills = groups, skills
        for group in host.get("artifact_groups", {}).values():
            for item in group:
                sources.update(filter(None, (item.get("source"), item.get("source_tree"))))
    if manifest.get("hosts", {}).get("codex", {}).get("profiles", {}).get("standard") != manifest.get("hosts", {}).get("codex", {}).get("profiles", {}).get("full"):
        errors.append("codex full must equal standard")
    if manifest.get("hosts", {}).get("polytoken", {}).get("profiles", {}).get("standard") != manifest.get("hosts", {}).get("polytoken", {}).get("profiles", {}).get("full"):
        errors.append("polytoken full must equal standard")
    if check_sources:
        for source in sorted(sources):
            if not (repo / source).exists():
                errors.append(f"admitted source does not exist: {source}")
    if errors:
        raise InstallerError("manifest validation failed:\n  - " + "\n  - ".join(errors))
    return errors


def resolve_targets(args: argparse.Namespace) -> Targets:
    home = Path(os.path.expanduser(os.environ.get("HOME", "~"))).resolve()
    xdg_config = Path(os.path.expanduser(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))).resolve()
    xdg_data = Path(os.path.expanduser(os.environ.get("XDG_DATA_HOME", str(home / ".local/share")))).resolve()
    proptermaltwo = Path(args.proptermaltwo_home or os.environ.get("PROPTERMALTWO_HOME", xdg_data / "proptermaltwo")).expanduser().resolve()
    claude = Path(args.claude_home or os.environ.get("CLAUDE_HOME", home / ".claude")).expanduser().resolve()
    codex = Path(args.codex_home or os.environ.get("CODEX_HOME", home / ".codex")).expanduser().resolve()
    codex_skills = Path(args.codex_skills_home or os.environ.get("CODEX_SKILLS_HOME", home / ".agents/skills")).expanduser().resolve()
    polytoken = Path(args.polytoken_home or os.environ.get("POLYTOKEN_HOME", xdg_config / "polytoken")).expanduser().resolve()
    project = Path(args.project).expanduser().resolve() if args.project else None
    return Targets(claude, codex, codex_skills, polytoken, proptermaltwo, project)


def select_hosts(args: argparse.Namespace, manifest: dict[str, Any]) -> Selection:
    host_arg = args.host or "claude-code"
    if host_arg == "all":
        if args.profile:
            raise InstallerError("--host all selects fixed profiles and does not accept --profile")
        if args.project:
            raise InstallerError("--host all excludes Copilot and does not accept --project")
        return Selection(dict(manifest["all_selection"]))
    if host_arg not in manifest["hosts"]:
        raise InstallerError(f"unknown host: {host_arg}")
    host = manifest["hosts"][host_arg]
    profile = args.profile or host["default_profile"]
    if profile not in host["supported_profiles"]:
        accepted = ", ".join(host["supported_profiles"])
        raise InstallerError(f"{host_arg} does not support profile {profile!r}; accepted: {accepted}")
    if host["scope"] == "project" and not args.project:
        raise InstallerError(f"{host_arg} is repository-scoped and requires --project")
    if host["scope"] != "project" and args.project:
        raise InstallerError("--project is accepted only with --host copilot")
    return Selection({host_arg: profile})


def source_mode(path: Path, relative: str) -> int:
    mode = stat.S_IMODE(path.stat().st_mode)
    if any(pattern.search(relative) for pattern in EXEC_PATTERNS):
        mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    return mode


def expand_tree(repo: Path, source_tree: str, destination_root: Path, owners: set[str], operation: str) -> list[Operation]:
    root = repo / source_tree
    if not root.is_dir():
        raise InstallerError(f"admitted source tree does not exist: {source_tree}")
    result: list[Operation] = []
    for source in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = source.relative_to(root)
        repo_relative = source.relative_to(repo).as_posix()
        result.append(Operation(destination_root / relative, set(owners), operation, repo_relative, source.read_bytes(), source_mode(source, repo_relative)))
    return result


def expand_item(repo: Path, targets: Targets, item: dict[str, Any], owners: set[str]) -> list[Operation]:
    target_name = item.get("target", "proptermaltwo_home")
    target = targets.get(target_name)
    destination = target / item["destination"]
    operation = item["operation"]
    if "source_tree" in item:
        return expand_tree(repo, item["source_tree"], destination, owners, operation)
    if operation == "symlink":
        link_namespace, relative = item["link_target"].split(":", 1)
        return [Operation(destination, set(owners), operation, link_target=str(targets.get(link_namespace) / relative))]
    source = repo / item["source"]
    if not source.is_file():
        raise InstallerError(f"admitted source does not exist: {item['source']}")
    content = source.read_bytes()
    if source.suffix in {".md", ".tmpl", ".json"}:
        bridge = targets.proptermaltwo_home / "shared/hooks/host-hook-bridge.py"
        # HOST_HOOK_BRIDGE appears inside template-owned single quotes, so
        # replace it with an escaped quote interior rather than adding quotes.
        bridge_quote_interior = str(bridge).replace("'", "'\"'\"'")
        # Tokens occur inside JSON strings. json.dumps supplies the necessary
        # JSON escaping; strip only its outer quote delimiters.
        bridge_json_interior = json.dumps(bridge_quote_interior)[1:-1]
        home_json_interior = json.dumps(str(targets.proptermaltwo_home))[1:-1]
        text = content.decode()
        text = text.replace("{{PROPTERMALTWO_HOME}}", home_json_interior)
        text = text.replace("{{HOST_HOOK_BRIDGE}}", bridge_json_interior)
        text = text.replace("{{BRIDGE_PATH}}", str(bridge))
        shell_quoted_bridge_json_interior = json.dumps(shell_single_quote(str(bridge)))[1:-1]
        text = text.replace("{{BRIDGE_PATH_SHELL_QUOTED}}", shell_quoted_bridge_json_interior)
        content = text.encode()
    return [Operation(destination, set(owners), operation, item["source"], content, source_mode(source, item["source"]))]


def legacy_operations(repo: Path, targets: Targets) -> list[Operation]:
    result: list[Operation] = []
    owner = {"claude-code"}
    for root_name in LEGACY_ROOTS:
        source = repo / root_name
        if source.is_file():
            relative = source.relative_to(repo).as_posix()
            result.append(Operation(targets.claude_home / relative, set(owner), "legacy-replace", relative, source.read_bytes(), source_mode(source, relative)))
        elif source.is_dir():
            result.extend(expand_tree(repo, root_name, targets.claude_home / root_name, owner, "legacy-replace"))
    settings_example = repo / "settings.example.json"
    result.append(Operation(targets.claude_home / "settings.example.json", set(owner), "legacy-replace", "settings.example.json", settings_example.read_bytes(), source_mode(settings_example, "settings.example.json")))
    result.append(Operation(targets.claude_home / "settings.json", set(owner), "seed-only", "settings.example.json", settings_example.read_bytes(), 0o644))
    return result


def parse_json_content(content: bytes, label: str) -> Any:
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallerError(f"invalid JSON in {label}: {exc}") from exc


def codex_definitions(document: Any) -> list[Any]:
    if isinstance(document, list):
        return document
    if not isinstance(document, dict):
        raise InstallerError("Codex hook template must be a JSON object or array")
    hooks = document.get("hooks", document)
    if isinstance(hooks, dict):
        definitions = hooks.get("PreToolUse", [])
        if isinstance(definitions, list):
            return definitions
    raise InstallerError("Codex hook template lacks hooks.PreToolUse array")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def hook_commands(value: Any) -> set[str]:
    commands: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"command", "bash"} and isinstance(child, str):
                commands.add(child)
            else:
                commands.update(hook_commands(child))
    elif isinstance(value, list):
        for child in value:
            commands.update(hook_commands(child))
    return commands


def same_bridge_guard(left: Any, right: Any) -> bool:
    def signatures(value: Any) -> set[tuple[str, str]]:
        result: set[tuple[str, str]] = set()
        for command in hook_commands(value):
            for guard in ("push", "commit"):
                if "host-hook-bridge.py" in command and f"--guard {guard}" in command:
                    result.add(("bridge", guard))
        return result
    return bool(signatures(left) & signatures(right))


def definition_hashes(definitions: Iterable[Any]) -> list[str]:
    return sorted(sha256_bytes(canonical_json(definition).encode()) for definition in definitions)


def stage_operation(op: Operation, suffix: str, ledger: dict[str, Any]) -> Operation:
    primary = op.destination
    destination = primary.with_name(primary.name + suffix)
    staged = dataclasses.replace(op, destination=destination, operation="staged-fragment", note=f"merge required for {primary}")
    current = current_fingerprint(destination)
    desired = sha256_bytes(staged.content or b"")
    existing = ledger.get("artifacts", {}).get(str(destination))
    if current["kind"] == "absent" or (current["kind"] == "file" and current.get("checksum") == desired):
        return staged
    if existing and matches_record(destination, existing):
        return staged
    raise InstallerError(f"refusing to overwrite unmanaged staged fragment: {destination}")


def resolve_operation(op: Operation, targets: Targets, ledger: dict[str, Any]) -> Operation | None:
    """Resolve conflict-sensitive operations to the exact file mutation."""
    destination = op.destination
    if op.operation == "seed-only":
        return None if destination.exists() or destination.is_symlink() else op
    if op.operation == "install-or-stage":
        if path_kind(destination) == "absent":
            return dataclasses.replace(op, operation="managed-copy")
        if destination.is_file() and sha256_file(destination) == sha256_bytes(op.content or b""):
            return dataclasses.replace(op, operation="managed-copy")
        existing = ledger.get("artifacts", {}).get(str(destination))
        if existing and matches_record(destination, existing):
            return dataclasses.replace(op, operation="managed-copy")
        return stage_operation(op, ".proptermaltwo.example", ledger)
    if op.operation == "polytoken-hooks-merge":
        expected = parse_json_content(op.content or b"", op.source or "Polytoken hook template")
        if not isinstance(expected, list) or len(expected) != 2:
            raise InstallerError("Polytoken hook template must be an array of exactly two definitions")
        if path_kind(destination) == "absent":
            return dataclasses.replace(
                op,
                operation="managed-config",
                content=(json.dumps(expected, indent=2) + "\n").encode(),
                managed_definition_hashes=definition_hashes(expected),
            )
        if not destination.is_file():
            return stage_operation(op, ".proptermaltwo.example.json", ledger)
        try:
            current = json.loads(destination.read_text())
        except (OSError, json.JSONDecodeError):
            return stage_operation(op, ".proptermaltwo.example.json", ledger)
        if not isinstance(current, list):
            return stage_operation(op, ".proptermaltwo.example.json", ledger)
        expected_by_name = {item.get("name"): item for item in expected if isinstance(item, dict)}
        if len(expected_by_name) != 2 or None in expected_by_name:
            raise InstallerError("Polytoken managed hooks require two unique names")
        merged = list(current)
        existing_record = ledger.get("artifacts", {}).get(str(destination))
        managed_upgrade = bool(existing_record and matches_record(destination, existing_record))
        prior_hashes = set(existing_record.get("managed_definition_hashes", [])) if managed_upgrade else set()
        for name, definition in expected_by_name.items():
            matches = [index for index, item in enumerate(merged) if isinstance(item, dict) and item.get("name") == name]
            if len(matches) > 1:
                return stage_operation(op, ".proptermaltwo.example.json", ledger)
            if matches:
                current_definition = merged[matches[0]]
                if canonical_json(current_definition) != canonical_json(definition):
                    current_hash = sha256_bytes(canonical_json(current_definition).encode())
                    if not managed_upgrade or current_hash not in prior_hashes:
                        return stage_operation(op, ".proptermaltwo.example.json", ledger)
                merged[matches[0]] = definition
            else:
                merged.append(definition)
        return dataclasses.replace(
            op,
            operation="managed-config",
            content=(json.dumps(merged, indent=2) + "\n").encode(),
            managed_definition_hashes=definition_hashes(expected_by_name.values()),
        )
    if op.operation == "codex-hooks-merge":
        expected_document = parse_json_content(op.content or b"", op.source or "Codex hook template")
        expected = codex_definitions(expected_document)
        config_toml = targets.codex_home / "config.toml"
        if config_toml.is_file() and re.search(r"(?m)^\s*\[+\s*hooks(?:\.|\])", config_toml.read_text(errors="replace")):
            return stage_operation(op, ".proptermaltwo.example.json", ledger)
        if path_kind(destination) == "absent":
            document = {"hooks": {"PreToolUse": expected}}
            return dataclasses.replace(
                op,
                operation="managed-config",
                content=(json.dumps(document, indent=2) + "\n").encode(),
                managed_definition_hashes=definition_hashes(expected),
            )
        if not destination.is_file():
            return stage_operation(op, ".proptermaltwo.example.json", ledger)
        try:
            current = json.loads(destination.read_text())
            current_defs = codex_definitions(current)
        except (OSError, json.JSONDecodeError, InstallerError):
            return stage_operation(op, ".proptermaltwo.example.json", ledger)
        if not isinstance(current, dict) or not isinstance(current.get("hooks"), dict):
            return stage_operation(op, ".proptermaltwo.example.json", ledger)
        merged = list(current_defs)
        existing_record = ledger.get("artifacts", {}).get(str(destination))
        managed_upgrade = bool(existing_record and matches_record(destination, existing_record))
        prior_hashes = set(existing_record.get("managed_definition_hashes", [])) if managed_upgrade else set()
        for definition in expected:
            if any(canonical_json(existing) == canonical_json(definition) for existing in merged):
                continue
            conflicts = [index for index, existing in enumerate(merged) if same_bridge_guard(existing, definition)]
            if conflicts:
                if len(conflicts) != 1:
                    return stage_operation(op, ".proptermaltwo.example.json", ledger)
                current_definition = merged[conflicts[0]]
                current_hash = sha256_bytes(canonical_json(current_definition).encode())
                if not managed_upgrade or current_hash not in prior_hashes:
                    return stage_operation(op, ".proptermaltwo.example.json", ledger)
                merged[conflicts[0]] = definition
            else:
                merged.append(definition)
        document = json.loads(json.dumps(current))
        document["hooks"]["PreToolUse"] = merged
        return dataclasses.replace(
            op,
            operation="managed-config",
            content=(json.dumps(document, indent=2) + "\n").encode(),
            managed_definition_hashes=definition_hashes(expected),
        )
    return op


def build_operations(repo: Path, manifest: dict[str, Any], selection: Selection, targets: Targets, ledger: dict[str, Any] | None = None) -> list[Operation]:
    ledger = ledger or default_ledger()
    operations: list[Operation] = []
    shared_groups = manifest["shared_groups"]
    for host_id, profile_name in selection.hosts.items():
        if host_id == "claude-code":
            operations.extend(legacy_operations(repo, targets))
            continue
        host = manifest["hosts"][host_id]
        for group_name in host["profiles"][profile_name]["groups"]:
            if group_name in shared_groups:
                items = shared_groups[group_name]
            else:
                items = host["artifact_groups"][group_name]
            for item in items:
                operations.extend(expand_item(repo, targets, item, {host_id}))
    # Destination/content deduplication adds owner sets for --host all.
    deduped: dict[str, Operation] = {}
    for operation in operations:
        resolved = resolve_operation(operation, targets, ledger)
        if resolved is None:
            continue
        key = str(resolved.destination)
        prior = deduped.get(key)
        if prior is None:
            deduped[key] = resolved
            continue
        if prior.operation != resolved.operation or prior.content != resolved.content or prior.link_target != resolved.link_target:
            raise InstallerError(f"destination collision with different definitions: {key}")
        prior.owners.update(resolved.owners)
    return sorted(deduped.values(), key=lambda item: str(item.destination))


def default_ledger() -> dict[str, Any]:
    return {"schema_version": LEDGER_SCHEMA, "product": "PropterMaltwo", "updated_at": utc_now(), "artifacts": {}}


def load_ledger(path: Path, *, mutation: bool) -> dict[str, Any]:
    if not path.exists():
        return default_ledger()
    try:
        ledger = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        if mutation:
            raise InstallerError(f"corrupt ledger blocks mutation: {path}: {exc}") from exc
        return {"schema_version": None, "artifacts": {}, "error": f"corrupt ledger: {exc}"}
    if ledger.get("schema_version") != LEDGER_SCHEMA or not isinstance(ledger.get("artifacts"), dict):
        message = f"unsupported or malformed ledger schema at {path}"
        if mutation:
            raise InstallerError(message)
        ledger["error"] = message
    return ledger


def snapshot_path(source: Path, backup_root: Path, key: str) -> dict[str, Any]:
    fingerprint = current_fingerprint(source)
    snapshot: dict[str, Any] = dict(fingerprint)
    if fingerprint["kind"] == "file":
        backup = backup_root / f"{key}.bin"
        if not backup.exists():
            atomic_write(backup, source.read_bytes(), fingerprint["mode"])
        snapshot["backup"] = str(backup)
    return snapshot


def restore_snapshot(destination: Path, snapshot: dict[str, Any]) -> None:
    kind = snapshot["kind"]
    if path_kind(destination) != "absent":
        if destination.is_dir() and not destination.is_symlink():
            destination.rmdir()
        else:
            destination.unlink()
    if kind == "absent":
        prune_empty_parents(destination.parent)
    elif kind == "file":
        atomic_write(destination, Path(snapshot["backup"]).read_bytes(), snapshot.get("mode", 0o644))
    elif kind == "symlink":
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(snapshot["target"], destination)
        fsync_dir(destination.parent)
    else:
        raise InstallerError(f"cannot restore unsupported prior path kind at {destination}")


def prune_empty_parents(path: Path) -> None:
    # Stop naturally at the first nonempty directory. Never remove a filesystem root.
    while path != path.parent:
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def immutable_original(destination: Path, backup_root: Path) -> dict[str, Any]:
    fingerprint = current_fingerprint(destination)
    if fingerprint["kind"] == "file":
        key = sha256_bytes((str(destination) + "\0" + fingerprint["checksum"]).encode())
        backup = backup_root / f"{key}.bin"
        if not backup.exists():
            atomic_write(backup, destination.read_bytes(), fingerprint["mode"])
        fingerprint["backup"] = str(backup)
    return fingerprint


def ensure_journal_clear(journal_path: Path) -> None:
    if journal_path.exists():
        raise InstallerError(
            f"unresolved transaction journal blocks mutation: {journal_path}\n"
            f"Recovery command: ./install.sh --recover --proptermaltwo-home {shell_single_quote(str(journal_path.parent.parent))}"
        )


@contextlib.contextmanager
def exclusive_lock(lock_path: Path, *, nonblocking: bool = True) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as stream:
        flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
        try:
            fcntl.flock(stream.fileno(), flags)
        except BlockingIOError as exc:
            raise InstallerError(f"another PropterMaltwo mutation holds lock: {lock_path}") from exc
        stream.seek(0)
        stream.truncate()
        stream.write(f"pid={os.getpid()} started={utc_now()}\n")
        stream.flush()
        yield


def maybe_inject(stage: str, index: int) -> None:
    variable = "PROPTERMALTWO_ROLLBACK_FAIL_AT" if stage == "rollback" else "PROPTERMALTWO_FAIL_AT"
    requested = os.environ.get(variable)
    if requested in {stage, str(index), f"{stage}:{index}"}:
        raise RuntimeError(f"injected failure at {stage}:{index}")
    sleep_at = os.environ.get("PROPTERMALTWO_SLEEP_AT")
    if sleep_at in {stage, f"{stage}:{index}"}:
        time.sleep(float(os.environ.get("PROPTERMALTWO_SLEEP_SECONDS", "5")))


def operation_record(op: Operation, prior: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    original = existing.get("original") if existing else prior
    created = existing.get("created_by_installer") if existing else prior["kind"] == "absent"
    record: dict[str, Any] = {
        "owners": sorted(op.owners | set(existing.get("owners", []) if existing else [])),
        "operation": op.operation,
        "canonical_source": op.source,
        "created_by_installer": created,
        "original": original,
        "mode": op.mode,
        "note": op.note,
        "managed_definition_hashes": op.managed_definition_hashes,
        "updated_at": utc_now(),
    }
    if op.operation == "symlink":
        record["installed_target"] = op.link_target
        record["installed_checksum"] = None
    else:
        record["installed_checksum"] = sha256_bytes(op.content or b"")
        record["installed_target"] = None
    return record


def mutation_needed(op: Operation, existing: dict[str, Any] | None) -> bool:
    current = current_fingerprint(op.destination)
    if op.operation == "symlink":
        if current["kind"] == "symlink" and current["target"] == op.link_target:
            return False
        if current["kind"] != "absent":
            if existing and matches_record(op.destination, existing):
                return True
            raise InstallerError(f"refusing conflicting path for symlink: {op.destination}")
        return True
    checksum = sha256_bytes(op.content or b"")
    if current["kind"] == "file" and current["checksum"] == checksum and current.get("mode") == op.mode:
        return False
    if current["kind"] != "absent" and op.operation not in {"legacy-replace", "managed-config"}:
        if not existing or not matches_record(op.destination, existing):
            raise InstallerError(f"refusing unmanaged conflict at {op.destination}")
    if existing and current["kind"] != "absent" and not matches_record(op.destination, existing) and op.operation != "legacy-replace":
        raise InstallerError(f"managed file was modified; refusing overwrite: {op.destination}")
    return True


def perform_operation(op: Operation) -> None:
    if path_kind(op.destination) != "absent":
        if op.destination.is_dir() and not op.destination.is_symlink():
            op.destination.rmdir()
        else:
            op.destination.unlink()
    op.destination.parent.mkdir(parents=True, exist_ok=True)
    if op.operation == "symlink":
        os.symlink(op.link_target, op.destination)
        fsync_dir(op.destination.parent)
    else:
        atomic_write(op.destination, op.content or b"", op.mode)


def rollback_journal(journal_path: Path, journal: dict[str, Any], ledger_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    entries = list(journal.get("completed", []))
    pending = journal.get("pending")
    if isinstance(pending, dict):
        entries.append(pending)
    for reverse_index, entry in enumerate(reversed(entries)):
        try:
            maybe_inject("rollback", reverse_index)
            restore_snapshot(Path(entry["destination"]), entry["prior"])
        except BaseException as exc:
            errors.append(f"{entry.get('destination')}: {exc}")
    if not errors and ledger_path is not None:
        ledger_before = journal.get("ledger_before")
        if not isinstance(ledger_before, dict):
            errors.append("journal lacks ledger_before snapshot")
        elif ledger_path.exists() or ledger_before.get("artifacts"):
            atomic_json(ledger_path, ledger_before)
        else:
            ledger_path.unlink(missing_ok=True)
            fsync_dir(ledger_path.parent)
    if not errors:
        journal_path.unlink(missing_ok=True)
        fsync_dir(journal_path.parent)
    else:
        journal["status"] = "rollback-failed"
        journal["rollback_errors"] = errors
        atomic_json(journal_path, journal)
    return errors


def apply_operations(operations: list[Operation], paths: dict[str, Path]) -> tuple[int, list[str]]:
    ledger = load_ledger(paths["ledger"], mutation=True)
    ensure_journal_clear(paths["journal"])
    txid = f"{int(time.time())}-{os.getpid()}"
    legacy_backup_stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    recovery_root = paths["recovery"] / txid
    recovery_root.mkdir(parents=True, exist_ok=True)
    journal: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA, "transaction_id": txid, "status": "applying",
        "started_at": utc_now(), "ledger_before": copy.deepcopy(ledger), "completed": []
    }
    atomic_json(paths["journal"], journal)
    warnings: list[str] = []
    changed = 0
    try:
        for index, op in enumerate(operations):
            key = str(op.destination)
            existing = ledger["artifacts"].get(key)
            prior = immutable_original(op.destination, paths["backups"]) if not existing else current_fingerprint(op.destination)
            if existing and not matches_record(op.destination, existing):
                if op.operation == "legacy-replace":
                    # Legacy behavior intentionally replaces modified mirrored files,
                    # but preserves the first pre-managed original across upgrades.
                    warnings.append(f"legacy replace of modified managed file: {op.destination}")
                else:
                    raise InstallerError(f"managed file was modified; refusing overwrite: {op.destination}")
            needs_mutation = mutation_needed(op, existing)
            if needs_mutation:
                recovery = snapshot_path(op.destination, recovery_root, f"{index:05d}")
                journal["pending"] = {"destination": key, "prior": recovery}
                atomic_json(paths["journal"], journal)
                maybe_inject("before-mutation", index)
                if (
                    op.operation == "legacy-replace"
                    and path_kind(op.destination) == "file"
                    and sha256_file(op.destination) != sha256_bytes(op.content or b"")
                ):
                    relative = Path(op.source or op.destination.name)
                    target_root = op.destination.parents[len(relative.parts) - 1]
                    visible_backup = target_root / f".propter-maltwo-backup-{legacy_backup_stamp}" / relative
                    visible_backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(op.destination, visible_backup)
                perform_operation(op)
                changed += 1
                maybe_inject("after-mutation", index)
                journal["completed"].append(journal.pop("pending"))
                atomic_json(paths["journal"], journal)
            ledger["artifacts"][key] = operation_record(op, prior, existing)
        maybe_inject("before-ledger", len(operations))
        ledger["updated_at"] = utc_now()
        journal["status"] = "ready-to-commit"
        journal["ledger_after"] = ledger
        atomic_json(paths["journal"], journal)
        atomic_json(paths["ledger"], ledger)
        journal["status"] = "committed"
        atomic_json(paths["journal"], journal)
        paths["journal"].unlink(missing_ok=True)
        fsync_dir(paths["journal"].parent)
        shutil.rmtree(recovery_root, ignore_errors=True)
        return changed, warnings
    except BaseException as exc:
        # If interruption happened after mutation but before completion was
        # journaled, the pending entry is also part of the rollback set.
        if "pending" in journal:
            journal["completed"].append(journal.pop("pending"))
        journal["status"] = "rolling-back"
        journal["failure"] = f"{type(exc).__name__}: {exc}"
        atomic_json(paths["journal"], journal)
        rollback_errors = rollback_journal(paths["journal"], journal, paths["ledger"])
        if rollback_errors:
            raise InstallerError(
                f"transaction failed ({exc}); rollback incomplete: {'; '.join(rollback_errors)}\n"
                f"Recovery command: ./install.sh --recover --proptermaltwo-home {shell_single_quote(str(paths['home']))}"
            ) from exc
        if isinstance(exc, KeyboardInterrupt):
            raise InstallerError("installation interrupted; completed mutations were rolled back") from exc
        raise


def uninstall(selection: Selection, paths: dict[str, Path]) -> tuple[int, list[str]]:
    ledger = load_ledger(paths["ledger"], mutation=True)
    ensure_journal_clear(paths["journal"])
    selected = selection.owners
    plans: list[tuple[Path, dict[str, Any], set[str]]] = []
    warnings: list[str] = []
    for key, record in sorted(ledger["artifacts"].items()):
        owners = set(record.get("owners", []))
        remaining = owners - selected
        if owners & selected:
            plans.append((Path(key), record, remaining))
    txid = f"uninstall-{int(time.time())}-{os.getpid()}"
    recovery_root = paths["recovery"] / txid
    recovery_root.mkdir(parents=True, exist_ok=True)
    journal: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA, "transaction_id": txid, "status": "uninstalling",
        "started_at": utc_now(), "ledger_before": copy.deepcopy(ledger), "completed": []
    }
    atomic_json(paths["journal"], journal)
    changed = 0
    try:
        for index, (destination, record, remaining) in enumerate(plans):
            key = str(destination)
            if remaining:
                record["owners"] = sorted(remaining)
                continue
            if not matches_record(destination, record):
                record["owners"] = []
                record["status"] = "modified-preserved"
                warnings.append(f"preserved modified managed path: {destination}")
                continue
            recovery = snapshot_path(destination, recovery_root, f"{index:05d}")
            journal["pending"] = {"destination": key, "prior": recovery}
            atomic_json(paths["journal"], journal)
            maybe_inject("before-mutation", index)
            original = record.get("original", {"kind": "absent"})
            if record.get("created_by_installer"):
                restore_snapshot(destination, {"kind": "absent"})
            elif original.get("kind") in {"file", "symlink"}:
                restore_snapshot(destination, original)
            # Adopted identical unledgered content remains in place.
            changed += 1
            maybe_inject("after-mutation", index)
            journal["completed"].append(journal.pop("pending"))
            atomic_json(paths["journal"], journal)
            del ledger["artifacts"][key]
        maybe_inject("before-ledger", len(plans))
        ledger["updated_at"] = utc_now()
        journal["status"] = "ready-to-commit"
        journal["ledger_after"] = ledger
        atomic_json(paths["journal"], journal)
        atomic_json(paths["ledger"], ledger)
        journal["status"] = "committed"
        atomic_json(paths["journal"], journal)
        paths["journal"].unlink(missing_ok=True)
        fsync_dir(paths["journal"].parent)
        shutil.rmtree(recovery_root, ignore_errors=True)
        return changed, warnings
    except BaseException as exc:
        if "pending" in journal:
            journal["completed"].append(journal.pop("pending"))
        journal["status"] = "rolling-back"
        journal["failure"] = f"{type(exc).__name__}: {exc}"
        atomic_json(paths["journal"], journal)
        rollback_errors = rollback_journal(paths["journal"], journal, paths["ledger"])
        if rollback_errors:
            raise InstallerError(
                f"uninstall failed ({exc}); rollback incomplete: {'; '.join(rollback_errors)}\n"
                f"Recovery command: ./install.sh --recover --proptermaltwo-home {shell_single_quote(str(paths['home']))}"
            ) from exc
        raise


def recover(paths: dict[str, Path]) -> None:
    if not paths["journal"].exists():
        print("No unresolved transaction journal.")
        return
    journal = load_json_strict(paths["journal"], "transaction journal")
    if journal.get("schema_version") != JOURNAL_SCHEMA or not isinstance(journal.get("completed"), list):
        raise InstallerError(f"corrupt journal cannot be recovered automatically: {paths['journal']}")
    ledger_after = journal.get("ledger_after")
    if journal.get("status") in {"ready-to-commit", "committed"} and isinstance(ledger_after, dict):
        current = load_ledger(paths["ledger"], mutation=True)
        if current == ledger_after:
            paths["journal"].unlink(missing_ok=True)
            fsync_dir(paths["journal"].parent)
            print(f"Finalized committed transaction {journal.get('transaction_id', '<unknown>')}; ledger and filesystem retained.")
            return
    errors = rollback_journal(paths["journal"], journal, paths["ledger"])
    if errors:
        raise InstallerError("recovery remains incomplete: " + "; ".join(errors))
    print(f"Recovered transaction {journal.get('transaction_id', '<unknown>')}; prior filesystem and ledger state restored.")


def state_paths(home: Path) -> dict[str, Path]:
    state = home / "state"
    return {
        "home": home,
        "state": state,
        "ledger": state / "ledger-v1.json",
        "journal": state / "journal-v1.json",
        "lock": state / "installer.lock",
        "backups": state / "backups-v1",
        "recovery": state / "recovery-v1",
        "activation": state / "activation-v1.json",
    }


def plan_line(op: Operation, ledger: dict[str, Any]) -> str:
    existing = ledger.get("artifacts", {}).get(str(op.destination))
    current = current_fingerprint(op.destination)
    if op.operation == "symlink":
        desired = {"kind": "symlink", "target": op.link_target}
        action = "keep" if current == desired else ("add" if current["kind"] == "absent" else "update")
    else:
        desired_checksum = sha256_bytes(op.content or b"")
        action = "keep" if current.get("checksum") == desired_checksum and current.get("mode") == op.mode else ("add" if current["kind"] == "absent" else "update")
    owners = ",".join(sorted(op.owners | set(existing.get("owners", []) if existing else [])))
    note = f" ({op.note})" if op.note else ""
    return f"  {action:<7} {op.destination} [{op.operation}; owners={owners}]{note}"


def load_activation(path: Path) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if not path.exists():
        return {"schema_version": ACTIVATION_SCHEMA, "hosts": {}}, warnings
    try:
        activation = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"schema_version": ACTIVATION_SCHEMA, "hosts": {}}, [f"activation evidence unreadable: {exc}"]
    if activation.get("schema_version") != ACTIVATION_SCHEMA or not isinstance(activation.get("hosts"), dict):
        return {"schema_version": ACTIVATION_SCHEMA, "hosts": {}}, ["activation evidence has invalid schema"]
    return activation, warnings


def activation_for(activation: dict[str, Any], host_id: str, capability: str, static: str) -> dict[str, Any]:
    local = activation.get("hosts", {}).get(host_id, {}).get("capabilities", {}).get(capability, {})
    status = local.get("status")
    if status not in ACTIVATION_VALUES:
        status = "inactive" if static in {"unsupported", "not-tested"} else "unverified"
    # activation-v1 is a presentation index, not a trust root. Until a host-specific
    # evidence validator is wired into doctor, a claimed pass may not become active.
    if status == "verified-active":
        status = "unverified"
        remediation = "run the host-specific admission verifier; unvalidated activation labels cannot prove active behavior"
    else:
        remediation = local.get("remediation") or default_remediation(host_id, capability, status)
    return {
        "status": status,
        "timestamp": local.get("timestamp"),
        "host_version": local.get("host_version"),
        "evidence": local.get("evidence"),
        "check": local.get("check"),
        "remediation": remediation,
    }


def default_remediation(host_id: str, capability: str, status: str) -> str | None:
    if status == "verified-active" or status == "inactive":
        return None
    if capability == "identity_hooks" and status == "installed-untrusted":
        return f"trust and reload the installed {host_id} hooks, then rerun host admission"
    if status == "failed":
        return "repair the recorded failing check and rerun host admission"
    return "run the host validation/admission checks and record fresh evidence"


def doctor_report(manifest: dict[str, Any], selection: Selection, targets: Targets, paths: dict[str, Path]) -> dict[str, Any]:
    ledger = load_ledger(paths["ledger"], mutation=False)
    activation, activation_warnings = load_activation(paths["activation"])
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "state": {
            "ledger": str(paths["ledger"]),
            "ledger_error": ledger.get("error"),
            "unresolved_journal": paths["journal"].exists(),
            "recovery_command": (
                f"./install.sh --recover --apply --proptermaltwo-home {shell_single_quote(str(paths['home']))}"
                if paths["journal"].exists() else None
            ),
            "warnings": activation_warnings,
        },
        "hosts": {},
    }
    for host_id, profile_name in selection.hosts.items():
        host = manifest["hosts"][host_id]
        profile = host["profiles"][profile_name]
        capabilities: dict[str, Any] = {}
        for capability, static in profile["capabilities"].items():
            capabilities[capability] = {
                "static_support": static,
                "activation": activation_for(activation, host_id, capability, static),
            }
        host_artifacts = []
        for destination, record in ledger.get("artifacts", {}).items():
            if host_id in record.get("owners", []):
                present = matches_record(Path(destination), record)
                host_artifacts.append({
                    "destination": destination, "operation": record.get("operation"), "state": "installed" if present else "modified-or-missing",
                    "owners": record.get("owners", []), "source": record.get("canonical_source"), "note": record.get("note")
                })
        omitted = [{"skill": skill, "reason": f"not admitted by {host_id}/{profile_name}"} for skill in manifest.get("omitted_skills", []) if skill not in profile.get("skills", [])]
        report["hosts"][host_id] = {
            "profile": profile_name, "maturity": host["maturity"], "scope": host["scope"],
            "capabilities": capabilities, "artifacts": host_artifacts, "omissions": omitted,
        }
    return report


def print_doctor(report: dict[str, Any]) -> None:
    print("PropterMaltwo doctor")
    state = report["state"]
    if state["ledger_error"]:
        print(f"ERROR: {state['ledger_error']}")
    if state["unresolved_journal"]:
        print("ERROR: unresolved transaction journal blocks mutation")
        print(f"RECOVERY: {state['recovery_command']}")
    for warning in state["warnings"]:
        print(f"WARNING: {warning}")
    for host_id, host in report["hosts"].items():
        print(f"\n{host_id} ({host['maturity']}, profile={host['profile']})")
        print(f"  artifacts: {len(host['artifacts'])} tracked")
        for capability, item in host["capabilities"].items():
            activation = item["activation"]
            suffix = " — active" if activation["status"] == "verified-active" else ""
            print(f"  {capability}: static={item['static_support']}; activation={activation['status']}{suffix}")
            if activation["remediation"]:
                print(f"    remediation: {activation['remediation']}")
        if host["omissions"]:
            print("  omitted by policy: " + ", ".join(item["skill"] for item in host["omissions"]))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Install PropterMaltwo for Claude Code, Codex, Polytoken, or Copilot (dry run by default).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  ./install.sh                         # legacy Claude full dry run
  ./install.sh --apply                 # legacy Claude full apply
  ./install.sh --host polytoken --profile standard --apply
  ./install.sh --host all --apply
  ./install.sh --host copilot --project ./my-repo --apply
  ./install.sh --host polytoken --doctor --json
  ./install.sh --host codex --uninstall --apply

Environment overrides:
  CLAUDE_HOME, CODEX_HOME, CODEX_SKILLS_HOME, POLYTOKEN_HOME,
  PROPTERMALTWO_HOME, XDG_CONFIG_HOME, XDG_DATA_HOME, HOME
""",
    )
    result.add_argument("--host", choices=("claude-code", "codex", "polytoken", "copilot", "all"))
    result.add_argument("--profile", choices=("core", "standard", "full"))
    result.add_argument("--project")
    action = result.add_mutually_exclusive_group()
    action.add_argument("--doctor", action="store_true")
    action.add_argument("--uninstall", action="store_true")
    action.add_argument("--recover", action="store_true")
    result.add_argument("--apply", action="store_true", help="perform writes; otherwise print a dry-run plan")
    result.add_argument("--json", action="store_true", help="emit JSON (doctor only)")
    result.add_argument("--validate-manifest", action="store_true")
    result.add_argument("--claude-home")
    result.add_argument("--codex-home")
    result.add_argument("--codex-skills-home")
    result.add_argument("--polytoken-home")
    result.add_argument("--proptermaltwo-home")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = Path(__file__).resolve().parent.parent
    try:
        manifest = load_manifest(repo)
        targets = resolve_targets(args)
        paths = state_paths(targets.proptermaltwo_home)
        if args.validate_manifest:
            validate_manifest(manifest, repo, check_sources=True)
            print("Manifest valid: schema, profiles, capabilities, lifecycle declarations, and admitted sources.")
            return 0
        if args.recover:
            if not args.apply:
                raise InstallerError("--recover requires --apply")
            with exclusive_lock(paths["lock"]):
                recover(paths)
            return 0
        selection = select_hosts(args, manifest)
        if args.json and not args.doctor:
            raise InstallerError("--json is accepted only with --doctor")
        if args.doctor:
            report = doctor_report(manifest, selection, targets, paths)
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print_doctor(report)
            return 1 if report["state"]["ledger_error"] or report["state"]["unresolved_journal"] else 0
        if args.uninstall:
            if not args.apply:
                ledger = load_ledger(paths["ledger"], mutation=False)
                print("PropterMaltwo uninstall (dry run — pass --apply to write)")
                for destination, record in sorted(ledger.get("artifacts", {}).items()):
                    if set(record.get("owners", [])) & selection.owners:
                        print(f"  review  {destination} [owners={','.join(record.get('owners', []))}]")
                return 0
            with exclusive_lock(paths["lock"]):
                changed, warnings = uninstall(selection, paths)
            print(f"Uninstalled {changed} unchanged managed artifact(s).")
            for warning in warnings:
                print(f"WARNING: {warning}")
            return 0
        label = ", ".join(f"{host}:{profile}" for host, profile in selection.hosts.items())
        print(f"PropterMaltwo [{label}]")
        if not args.apply:
            ledger = load_ledger(paths["ledger"], mutation=False)
            operations = build_operations(repo, manifest, selection, targets, ledger)
            print("(dry run — pass --apply to write)\n")
            for operation in operations:
                print(plan_line(operation, ledger))
            if "claude-code" in selection.hosts:
                settings = targets.claude_home / "settings.json"
                print("\n  settings.json exists — would leave it, see settings.example.json to merge" if settings.exists() else "\n  would seed settings.json from example (none present)")
            print("\nDry run — nothing written.")
            return 0
        with exclusive_lock(paths["lock"]):
            # Resolve merge/conflict-sensitive operations with the current ledger
            # while holding the same lock used for mutation.
            ledger = load_ledger(paths["ledger"], mutation=True)
            operations = build_operations(repo, manifest, selection, targets, ledger)
            changed, warnings = apply_operations(operations, paths)
        print(f"Applied {changed} filesystem change(s); ledger: {paths['ledger']}")
        for operation in operations:
            if operation.operation == "staged-fragment":
                print(f"MERGE REQUIRED: staged {operation.destination} for {operation.note}")
        for warning in warnings:
            print(f"WARNING: {warning}")
        return 0
    except InstallerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    except BaseException as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
