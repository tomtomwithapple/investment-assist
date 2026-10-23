#!/usr/bin/env bash
# Example --on-done step: land the slice on main (rebase + push, retry on races).
# Runs after the accept check passed; slicer marks done only if this succeeds.
set -euo pipefail
for i in 1 2 3 4 5; do
  git fetch -q origin
  git rebase -q origin/main
  eval "$SLICER_ACCEPT"            # re-check on top of latest main
  git push -q origin HEAD:main && exit 0
  sleep $((RANDOM % 5 + 1))
done
echo "could not land $SLICER_ID" >&2; exit 1
