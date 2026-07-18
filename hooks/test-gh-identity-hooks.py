#!/usr/bin/env python3
"""Behavioral test suite for gh-identity-guard.py + gh-commit-author-guard.py.

Fires each hook as a subprocess with realistic PreToolUse JSON on stdin against
temp git repos, asserting allow (empty stdout) or deny (hookSpecificOutput
JSON with permissionDecision=deny). Covers the a 2026-06 /angel must-fix list
(identity-hook-angel-findings.md) case by case.

Uses the REAL identity map (~/.claude/github-identity-map.json) — identity ids
PropterMalone / your-personal-account / RetiredAccount / local-only are load-bearing contract.

Run: python3 ~/.claude/hooks/test-gh-identity-hooks.py
Exit 0 all pass, 1 any fail.
"""

import json
import os
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.abspath(__file__))
PUSH_HOOK = os.path.join(HOOKS, "gh-identity-guard.py")
COMMIT_HOOK = os.path.join(HOOKS, "gh-commit-author-guard.py")

PASS = 0
FAIL = 0
FAIL_NAMES = []
# Assigned inside the tempdir block below, before any fire() call. Declared here
# (not relying on later-global-capture) so fire()'s reference is unambiguous.
STATE_DIR = ""
MAP_FILE = ""


def fire(hook: str, command: str, cwd: str) -> dict | None:
    """Run hook; return parsed deny JSON or None for allow. Asserts exit 0."""
    payload = json.dumps({"tool_input": {"command": command, "cwd": cwd}, "cwd": cwd})
    env = dict(os.environ)
    env["HOOK_TEST_STATE_DIR"] = STATE_DIR  # isolate the audit log
    env["CLAUDE_GH_IDENTITY_MAP"] = MAP_FILE  # fixture map, not the real one
    proc = subprocess.run(
        [sys.executable, hook], input=payload, capture_output=True,
        text=True, timeout=60, env=env,
    )
    assert proc.returncode == 0, f"hook exited {proc.returncode}: {proc.stderr}"
    out = proc.stdout.strip()
    if not out:
        return None
    parsed = json.loads(out)
    assert parsed["hookSpecificOutput"]["permissionDecision"] == "deny", parsed
    return parsed


def check(name: str, hook: str, command: str, cwd: str, expect_deny: bool,
          reason_contains: str = ""):
    global PASS, FAIL
    try:
        result = fire(hook, command, cwd)
        denied = result is not None
        if denied != expect_deny:
            raise AssertionError(
                f"expected {'DENY' if expect_deny else 'ALLOW'}, got "
                f"{'DENY: ' + result['hookSpecificOutput']['permissionDecisionReason'] if denied else 'ALLOW'}"
            )
        if denied and reason_contains:
            reason = result["hookSpecificOutput"]["permissionDecisionReason"]
            if reason_contains.lower() not in reason.lower():
                raise AssertionError(
                    f"deny reason missing {reason_contains!r}: {reason}"
                )
        print(f"  PASS {name}")
        PASS += 1
    except AssertionError as exc:
        print(f"  FAIL {name}: {exc}")
        FAIL += 1
        FAIL_NAMES.append(name)


def make_repo(base: str, name: str, tag: str | None, remote_url: str | None,
              user_name: str | None = None, user_email: str | None = None) -> str:
    path = os.path.join(base, name)
    os.makedirs(path)
    subprocess.run(["git", "init", "-q", path], check=True, capture_output=True)
    if tag:
        subprocess.run(["git", "-C", path, "config", "claude.identity", tag], check=True)
    if remote_url:
        subprocess.run(["git", "-C", path, "remote", "add", "origin", remote_url], check=True)
    if user_name:
        subprocess.run(["git", "-C", path, "config", "user.name", user_name], check=True)
    if user_email:
        subprocess.run(["git", "-C", path, "config", "user.email", user_email], check=True)
    return path


with tempfile.TemporaryDirectory(prefix="gh-identity-test-") as TMP:
    STATE_DIR = os.path.join(TMP, "state")
    os.makedirs(STATE_DIR)

    # Fixture identity map — the guards read this via CLAUDE_GH_IDENTITY_MAP,
    # so the suite is self-contained and never depends on the operator's real map.
    MAP_FILE = os.path.join(TMP, "identity-map.json")
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        json.dump({"identities": {
            "PropterMalone": {"gh_account": "PropterMalone", "ssh_host": "github.com",
                "user_name": "PropterMalone",
                "user_email": "proptermalone@users.noreply.github.com",
                "push": True, "retired": False},
            "your-personal-account": {"gh_account": "your-personal-account",
                "ssh_host": "github.com-personal", "user_name": "Pat Personal",
                "user_email": "pat@personal.example", "push": True, "retired": False},
            "RetiredAccount": {"gh_account": "RetiredAccount",
                "ssh_host": "github.com-retiredaccount", "user_name": "RetiredAccount",
                "user_email": "retired@personal.example", "push": True, "retired": True},
            "local-only": {"push": False, "retired": False},
        }}, f)

    # Fixture repos. SSH remotes only — no network, no gh calls on these paths.
    untagged = make_repo(TMP, "untagged", None, "git@github.com:PropterMalone/x.git")
    propter = make_repo(TMP, "propter", "PropterMalone", "git@github.com:PropterMalone/x.git")
    pat_ok = make_repo(TMP, "pat-ok", "your-personal-account", "git@github.com-personal:your-personal-account/y.git",
                      "Pat Personal", "pat@personal.example")
    pat_wrong_host = make_repo(TMP, "pat-wrong", "your-personal-account", "git@github.com:your-personal-account/y.git")
    localonly = make_repo(TMP, "localonly", "local-only", "git@github.com:PropterMalone/z.git")
    retired = make_repo(TMP, "retired", "RetiredAccount", "git@github.com-retiredaccount:RetiredAccount/w.git")
    pat_badauthor = make_repo(TMP, "pat-badauthor", "your-personal-account",
                             "git@github.com-personal:your-personal-account/y.git",
                             "PropterMalone", "proptermalone@users.noreply.github.com")
    notarepo = os.path.join(TMP, "plain")
    os.makedirs(notarepo)

    print("gh-identity-guard.py:")
    # Baseline behavior (pre-existing contract)
    check("allow: non-push command", PUSH_HOOK, "ls -la && echo done", propter, False)
    check("allow: tagged+matching ssh host", PUSH_HOOK, "git push origin main", propter, False)
    check("allow: your-personal-account matching alias host", PUSH_HOOK, "git push", pat_ok, False)
    check("deny: untagged repo", PUSH_HOOK, "git push", untagged, True, "not tagged")
    check("deny: wrong ssh host for tag", PUSH_HOOK, "git push origin main", pat_wrong_host, True, "mismatch")
    check("deny: local-only tag", PUSH_HOOK, "git push", localonly, True, "disabled by policy")
    check("deny: retired RetiredAccount tag", PUSH_HOOK, "git push", retired, True, "RETIRED")
    check("deny: push outside any repo", PUSH_HOOK, "git push", notarepo, True, "no git repository")

    # Must-fix #1: ALL push segments validated, not just the first
    check("MF1 deny: second push violates", PUSH_HOOK,
          f"git -C {propter} push && git -C {untagged} push",
          propter, True, "not tagged")
    check("MF1 allow: both pushes clean", PUSH_HOOK,
          f"git -C {propter} push && git -C {pat_ok} push", propter, False)

    # Must-fix #2: env prefix
    check("MF2 deny: env git push (untagged)", PUSH_HOOK, "env git push", untagged, True)
    check("MF2 deny: env VAR=x git push (untagged)", PUSH_HOOK,
          "env FOO=bar git push", untagged, True)
    check("MF2 allow: env git push (clean repo)", PUSH_HOOK, "env git push", propter, False)
    check("MF2 deny: env --chdir defeats cwd", PUSH_HOOK,
          f"env --chdir={untagged} git push", propter, True)

    # Must-fix #3: cd before push
    check("MF3 deny: cd to untagged then push", PUSH_HOOK,
          f"cd {untagged} && git push", propter, True, "not tagged")
    check("MF3 allow: cd to clean repo then push", PUSH_HOOK,
          f"cd {pat_ok} && git push", propter, False)
    check("MF3 deny: cd $VAR taints cwd", PUSH_HOOK,
          'cd "$SOMEWHERE" && git push', propter, True, "unresolvable")
    check("MF3 deny: popd taints cwd", PUSH_HOOK,
          "popd && git push", propter, True, "unresolvable")

    # Must-fix #4: remote mutation before push
    check("MF4 deny: set-url then push", PUSH_HOOK,
          "git remote set-url origin git@github.com:evil/x.git && git push",
          propter, True, "separate commands")
    check("MF4 deny: remote add then push", PUSH_HOOK,
          "git remote add other git@github.com:evil/x.git && git push other main",
          propter, True, "separate commands")
    check("MF4 allow: push then set-url (order matters)", PUSH_HOOK,
          "git push && git remote set-url origin git@github.com:evil/x.git",
          propter, False)

    # Must-fix #5: --repo forms
    subprocess.run(["git", "-C", propter, "remote", "add", "wrongid",
                    "git@github.com-personal:your-personal-account/y.git"], check=True)
    check("MF5 deny: --repo space form wrong host", PUSH_HOOK,
          "git push --repo wrongid", propter, True, "mismatch")
    check("MF5 deny: --repo= form wrong host", PUSH_HOOK,
          "git push --repo=wrongid", propter, True, "mismatch")
    check("MF5 allow: --repo matching remote", PUSH_HOOK,
          "git push --repo origin", propter, False)

    # Must-fix #7: send-pack
    check("MF7 deny: send-pack wrong host", PUSH_HOOK,
          "git send-pack git@github.com:evil/x.git refs/heads/main",
          pat_ok, True, "mismatch")
    check("MF7 allow: send-pack matching host", PUSH_HOOK,
          "git send-pack git@github.com-personal:your-personal-account/y.git refs/heads/main",
          pat_ok, False)
    check("MF7 deny: send-pack no destination", PUSH_HOOK,
          "git send-pack", pat_ok, True)

    # Exotic mitigations: dangerous env / -c on push segments
    check("ADV deny: GIT_SSH_COMMAND on push", PUSH_HOOK,
          "GIT_SSH_COMMAND='ssh -i /tmp/evil' git push", propter, True, "reroute")
    check("ADV deny: GIT_CONFIG_COUNT on push", PUSH_HOOK,
          "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.url git push",
          propter, True, "reroute")
    check("ADV deny: -c remote.origin.url push", PUSH_HOOK,
          "git -c remote.origin.url=git@github.com:evil/x.git push",
          propter, True, "reroute")
    check("ADV deny: -c core.sshCommand push", PUSH_HOOK,
          "git -c core.sshCommand='ssh -i /tmp/evil' push", propter, True, "reroute")
    check("ADV allow: harmless -c on push", PUSH_HOOK,
          "git -c push.default=current push", propter, False)
    check("ADV deny: bash -c wrapped push (untagged)", PUSH_HOOK,
          "bash -c 'git push'", untagged, True)

    # a 2026-07 re-review regressions (all live-verified fail-opens then).
    # C1: bash -c-wrapped mutation/cd must taint a later push (expand_tokens
    # must splice in place so segment order == execution order).
    check("RE-C1 deny: bash -c remote set-url then push", PUSH_HOOK,
          "bash -c 'git remote set-url origin git@github.com:evil/x.git' && git push",
          propter, True, "separate commands")
    check("RE-C1 deny: bash -c cd untagged then push", PUSH_HOOK,
          f"bash -c 'cd {untagged}' && git push", propter, True)
    # C2: git -C d1 -C d2 — git uses the LAST -C; guard must too.
    check("RE-C2 deny: -C good -C untagged push", PUSH_HOOK,
          f"git -C {propter} -C {untagged} push", propter, True, "not tagged")
    check("RE-C2 allow: -C untagged -C good push", PUSH_HOOK,
          f"git -C {untagged} -C {propter} push", untagged, False)
    # I1: two-token global opt before `remote set-url` must not hide it.
    check("RE-I1 deny: git -C dir remote set-url then push", PUSH_HOOK,
          f"git -C {propter} remote set-url origin git@github.com:evil/x.git "
          f"&& git -C {propter} push", propter, True, "separate commands")
    # I4: git config remote.*.url write == remote mutation.
    check("RE-I4 deny: git config remote.origin.url then push", PUSH_HOOK,
          "git config remote.origin.url git@github.com:evil/x.git && git push",
          propter, True, "separate commands")
    check("RE-I4 allow: git config --get remote.origin.url (read) then push", PUSH_HOOK,
          "git config --get remote.origin.url && git push", propter, False)

    print("gh-commit-author-guard.py:")
    check("allow: non-commit command", COMMIT_HOOK, "git status", pat_ok, False)
    check("allow: commit with matching author", COMMIT_HOOK,
          "git commit -m 'x'", pat_ok, False)
    check("allow: commit in untagged repo", COMMIT_HOOK,
          "git commit -m 'x'", untagged, False)
    check("allow: --dry-run", COMMIT_HOOK,
          "git commit --dry-run -m 'x'", pat_badauthor, False)
    check("deny: author mismatch", COMMIT_HOOK,
          "git commit -m 'x'", pat_badauthor, True, "mismatch")
    check("MF6 deny: bash -c wrapped commit, mismatch", COMMIT_HOOK,
          "bash -c 'git commit -m x'", pat_badauthor, True, "mismatch")
    check("deny: -c user.email override mismatches", COMMIT_HOOK,
          "git -c user.email=wrong@evil.com commit -m 'x'", pat_ok, True, "mismatch")
    check("allow: -c overrides matching map", COMMIT_HOOK,
          "git -c user.name='Pat Personal' -c user.email=pat@personal.example commit -m 'x'",
          pat_badauthor, False)
    check("deny: --author mismatch", COMMIT_HOOK,
          "git commit --author='Evil <evil@x.com>' -m 'x'", pat_ok, True, "mismatch")
    check("deny: --author=<pattern> can't be verified statically", COMMIT_HOOK,
          "git commit --author=whoknows -m 'x'", pat_ok, True, "pattern form")
    check("RE-I3 allow: --author=<own name> pattern resolves to identity", COMMIT_HOOK,
          "git commit --author='Pat Personal' -m 'x'", pat_ok, False)
    check("deny: env-wrapped commit, mismatch", COMMIT_HOOK,
          "env git commit -m 'x'", pat_badauthor, True, "mismatch")
    check("allow: commit message containing 'git push'", COMMIT_HOOK,
          "git commit -m 'docs: how to git push safely'", pat_ok, False)
    # a 2026-07 re-review regressions.
    # I2: every commit in a chain is checked, not just the first.
    check("RE-I2 deny: second chained commit has wrong author", COMMIT_HOOK,
          "git commit -m x && git commit --author='Evil <evil@x.com>' -m y",
          pat_ok, True, "mismatch")
    # I5: value-taking global flag must not let its value displace the verb.
    check("RE-I5 deny: git --namespace foo commit, mismatch", COMMIT_HOOK,
          "git --namespace foo commit -m x", pat_badauthor, True, "mismatch")
    # C2: -C last-wins on the commit guard too.
    check("RE-C2 deny: -C good -C badauthor commit", COMMIT_HOOK,
          f"git -C {pat_ok} -C {pat_badauthor} commit -m x", pat_ok, True, "mismatch")

    # Message-text false-positive guard for the push hook too
    print("false-positive guards:")
    check("allow: echo mentioning push", PUSH_HOOK,
          "echo 'remember to git push later'", propter, False)
    # Parse-failure fallback must not deny innocent commands that merely contain
    # "push" and happen to be shlex-unparseable (unbalanced quote). Regression
    # for the 2026-07 live false-positive on an echo+grep+heredoc command.
    check("allow: unparseable non-git command with 'push' word", PUSH_HOOK,
          "echo \"what push guard would block now: it's fine\" | grep push",
          propter, False)
    check("allow: unbalanced-quote heredoc-ish mentioning pushd", PUSH_HOOK,
          "echo 'pushd/popd don't parse cleanly here", propter, False)
    check("deny: unparseable but real git push shape", PUSH_HOOK,
          "git push origin \"unterminated", untagged, True)
    check("allow: grep for push in file", PUSH_HOOK,
          "grep -rn 'git push' README.md", propter, False)

    # Nested-subshell parse failure must fail CLOSED on mutation shapes: an
    # unparseable inner string under bash -c used to be silently dropped from
    # the token stream (fail-open; cross-model review catch, 2026-07).
    print("nested-subshell parse-failure guards:")
    check("deny: unparseable inner subshell with git-mutation shape", PUSH_HOOK,
          "bash -c 'git pu" + "sh \"unclosed'", untagged, True)
    check("deny: unparseable inner subshell with gh-create shape", PUSH_HOOK,
          "bash -c 'gh repo cre" + "ate foo \"unclosed'", untagged, True)
    check("allow: unparseable inner subshell, benign", PUSH_HOOK,
          "bash -c 'echo \"unclosed'", propter, False)

print(f"\npass={PASS} fail={FAIL}")
if FAIL:
    print("failed:", ", ".join(FAIL_NAMES))
    sys.exit(1)
sys.exit(0)
