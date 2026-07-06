#!/usr/bin/env bash
# ship.sh "commit message" — one commit, one push, whole monorepo.
#
# Commits any changes inside the knottra submodule (to its own repo),
# bumps the submodule pointer, commits everything in the monorepo with
# the same message, and pushes once. push.recurseSubmodules=on-demand
# makes that single push upload knottra's commits first, so a broken
# pointer can never be published.
set -euo pipefail

msg="${1:?usage: scripts/ship.sh \"commit message\"}"
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [ -n "$(git -C knottra status --porcelain)" ]; then
  if ! git -C knottra symbolic-ref -q HEAD >/dev/null; then
    echo "knottra is on a detached HEAD; fix with: git -C knottra switch main" >&2
    exit 1
  fi
  git -C knottra add -A
  git -C knottra commit -m "$msg"
  echo "committed in knottra ($(git -C knottra rev-parse --short HEAD))"
fi

git add -A
if git diff --cached --quiet; then
  echo "nothing to commit in monorepo"
else
  git commit -m "$msg"
fi

git push
