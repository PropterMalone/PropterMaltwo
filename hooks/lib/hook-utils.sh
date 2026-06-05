#!/usr/bin/env bash
# hook-utils.sh — shared helpers for Claude Code hooks.
#
# Source this from any bash hook:
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/hook-utils.sh"
#
# Convention: the location of the error log is the contract, not the
# hook_log function itself. Python hooks may write directly to
# $(hook_phyllis_state_dir)/hook-errors.log with the same line shape.
#
# Test override: set HOOK_TEST_STATE_DIR before invoking a hook to
# redirect both ~/.claude/state and ~/.phyllis/state under a tempdir.
# The harness uses this to keep production state untouched.
#
# pattern: imperative shell (sets globals, writes to disk, takes locks).

# Guard against double-source.
if [ -n "${__HOOK_UTILS_LOADED:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
__HOOK_UTILS_LOADED=1

# Canonical paths. Both honor HOOK_TEST_STATE_DIR when set so the test
# harness can isolate state without touching real ~/.claude or ~/.phyllis.
hook_state_dir() {
  if [ -n "${HOOK_TEST_STATE_DIR:-}" ]; then
    printf '%s\n' "${HOOK_TEST_STATE_DIR}/claude-state"
  else
    printf '%s\n' "${HOME}/.claude/state"
  fi
}

# adapt: ~/.phyllis is an optional usage-accounting queue tool. If you don't
# use it, these paths are harmless — the hooks that read them degrade to a
# no-op when the dir is absent.
hook_phyllis_state_dir() {
  if [ -n "${HOOK_TEST_STATE_DIR:-}" ]; then
    printf '%s\n' "${HOOK_TEST_STATE_DIR}/phyllis-state"
  else
    printf '%s\n' "${HOME}/.phyllis/state"
  fi
}

# hook_log <level> <message...>
# Appends [ts] <hook-name>: <LEVEL>: <message> to hook-errors.log.
# Best-effort: never fails the calling hook even if the dir is missing.
# Caller name is auto-detected from BASH_SOURCE[1] (the file that sourced us).
hook_log() {
  local level="${1:-INFO}"
  shift || true
  local message="$*"
  local hook_name
  if [ -n "${BASH_SOURCE[1]:-}" ]; then
    hook_name="$(basename "${BASH_SOURCE[1]}")"
  else
    hook_name="unknown-hook"
  fi
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%S.000Z 2>/dev/null || printf 'unknown')"
  local dir
  dir="$(hook_phyllis_state_dir)"
  # Create dir lazily; if mkdir fails, drop the log silently.
  mkdir -p "$dir" 2>/dev/null || return 0
  printf '[%s] %s: %s: %s\n' "$ts" "$hook_name" "$level" "$message" \
    >> "${dir}/hook-errors.log" 2>/dev/null || true
}

# hook_lock <name>
# Acquires a non-blocking flock on <state>/locks/<name>.lock.
# Returns 0 on success (and exports HOOK_LOCK_FD_<name> with the fd number),
# returns 1 on contention. Caller is responsible for releasing the lock,
# typically via:
#   trap 'hook_unlock <name>' EXIT
hook_lock() {
  local name="${1:?hook_lock requires a name}"
  local locks_dir
  locks_dir="$(hook_state_dir)/locks"
  mkdir -p "$locks_dir" 2>/dev/null || return 1
  local lockfile="${locks_dir}/${name}.lock"
  # Find an unused fd >= 9 (avoid stomping on stdin/stdout/stderr/etc).
  # eval is the portable way to assign to a dynamically-named var while
  # also opening the fd — `exec {var}>...` is bash 4.1+ but the var name
  # interpolation gets awkward for our needs.
  local fd_var="__HOOK_LOCK_FD_${name//[^A-Za-z0-9_]/_}"
  exec {fd}>"$lockfile" 2>/dev/null || return 1
  if ! flock -n "$fd"; then
    eval "exec ${fd}>&-" 2>/dev/null || true
    return 1
  fi
  eval "${fd_var}=${fd}"
  return 0
}

hook_unlock() {
  local name="${1:?hook_unlock requires a name}"
  local fd_var="__HOOK_LOCK_FD_${name//[^A-Za-z0-9_]/_}"
  local fd="${!fd_var:-}"
  if [ -n "$fd" ]; then
    flock -u "$fd" 2>/dev/null || true
    eval "exec ${fd}>&-" 2>/dev/null || true
    unset "$fd_var"
  fi
}
