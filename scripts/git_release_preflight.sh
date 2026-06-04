#!/usr/bin/env bash

set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: bash scripts/git_release_preflight.sh

Runs non-mutating local git checks before publishing release/provenance commits.
It does not create repositories, add remotes, push, fetch, merge, rebase, or
print credentials.

Optional environment:
  REMOTE_NAME       Remote to validate, default origin.
  EXPECTED_BRANCH   Require the current branch name.
  PROTECTED_BRANCH  Protected branch, default main.
USAGE
  exit 0
fi

REMOTE_NAME="${REMOTE_NAME:-origin}"
PROTECTED_BRANCH="${PROTECTED_BRANCH:-main}"

log() {
  printf '[git_release_preflight] %s\n' "$1"
}

fail() {
  printf '[git_release_preflight] %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

require_command git

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "not inside a git worktree"

branch="$(git branch --show-current)"
if [[ -z "$branch" ]]; then
  fail "detached HEAD is not allowed for release provenance"
fi
if [[ "$branch" == "$PROTECTED_BRANCH" ]]; then
  fail "current branch must not be protected branch $PROTECTED_BRANCH"
fi
if [[ -n "${EXPECTED_BRANCH:-}" && "$branch" != "$EXPECTED_BRANCH" ]]; then
  fail "current branch $branch does not match EXPECTED_BRANCH"
fi
log "branch=$branch"

if [[ -n "$(git status --porcelain)" ]]; then
  fail "working tree must be clean before release provenance"
fi
log "working tree clean"

remote_url="$(git remote get-url "$REMOTE_NAME" 2>/dev/null || true)"
if [[ -z "$remote_url" ]]; then
  fail "remote $REMOTE_NAME is not configured"
fi
if [[ "$remote_url" == *"yuzhnyi/deutsch-trainer-bot"* ]]; then
  fail "remote $REMOTE_NAME points to the rejected repository"
fi
case "$remote_url" in
  http:*|git://*)
    fail "remote $REMOTE_NAME must use HTTPS or SSH"
    ;;
esac
log "remote $REMOTE_NAME configured"

head_sha="$(git rev-parse --short HEAD)"
log "head=$head_sha"
log "git release preflight finished"
