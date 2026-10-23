#!/usr/bin/env bash
# Per-slice step for `python3 slicer.py run --exec ./worker.sh --on-done ./integrate.sh`.
# Starts each slice from fresh origin/main, runs one agent test-first, then checks ownership.
set -euo pipefail
git fetch -q origin
git checkout -q -B "slice/$SLICER_ID" origin/main

claude -p "You are implementing ONE slice of investment-assist: $SLICER_ID — $SLICER_TITLE.
Read CLAUDE.md (decision flow, sources, rules) and PLAN.md (stack, shape, per-slice workflow;
PLAN slice numbers appear in the title), plus the header comment of plan.yaml.
Slice notes: $SLICER_NOTES

Rules:
- You may ONLY create or edit files matching these globs (anything else fails the slice):
$SLICER_OWNS
- Dependencies ($SLICER_DEPENDS_ON) are already on main. Import their code, never edit it.
- Do not edit PLAN.md, CLAUDE.md, plan.yaml, slicer.py, worker.sh or integrate.sh unless owned above.
- The sibling repos in ../ are READ-ONLY: never write into them, never run their fetchers or
  refresh jobs. This repo never fetches from the internet.
- The siblings keep changing. Before reading a sibling store, check that repo's recent git log and
  its own docs (CLAUDE.md, PLAN.md, README *Changes the parent must follow*, docs/HANDOFF.md,
  docs/storage.md) and inspect the real schema read-only. Where they disagree with CLAUDE.md,
  PLAN.md or the slice notes here, follow the sibling and say so in your final message (and in
  docs/results/$SLICER_ID.md if you own it).
- Work test-first: write the tests, run them and confirm they fail for the right reason, then write
  the minimum code to pass, then tidy up. Tests never touch the network or the real stores; use
  small fixtures under tests/fixtures/ (inspect the real store's schema read-only to build them).
- Done means this command exits 0: $SLICER_ACCEPT
- Then do the live run the notes ask for (read-only against the real stores) and, if a
  docs/results/$SLICER_ID.md is in your globs, write the numbers there. A missing or locked
  store is a finding to record, not a reason to fail.
- When it passes, commit everything with message '$SLICER_ID: $SLICER_TITLE' ending with the line
  'Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>'. Do not push.
- If you cannot get it green, say why in your final message and do not commit." \
  --permission-mode bypassPermissions

# Commit anything the agent left uncommitted.
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "$SLICER_ID: $SLICER_TITLE (leftovers)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
fi

# Ownership check: every changed path must match one of the slice's globs.
git diff --name-only origin/main...HEAD | python3 -c '
import fnmatch, os, sys
owns = [g.strip() for g in os.environ["SLICER_OWNS"].replace(",", "\n").split("\n") if g.strip()]
bad = [p for p in sys.stdin.read().split() if not any(fnmatch.fnmatch(p, g) for g in owns)]
if bad:
    print("ownership violation in " + os.environ["SLICER_ID"] + ": " + ", ".join(bad), file=sys.stderr)
    sys.exit(1)
'
