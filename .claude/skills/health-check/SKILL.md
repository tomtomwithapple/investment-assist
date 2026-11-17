---
name: health-check
description: Use when asked to check, recheck or report health status (sources, jobs, servers, the last runs) across investment-assist and its fetcher repos.
---

# Health check

Read-only. Run from the investment-assist checkout; put multi-step shell in a bash script in the
scratchpad (zsh aborts on an unmatched glob).

1. **Known gaps first.** Read `config/alerts.yaml` `accepted`: those are reported as known gaps,
   never as problems. jquantster on J-Quants Free: `investor_types` empty and `daily_bars` ~85
   days old (12-week delay, window moves daily) are normal.
2. **Sources:** `uv run assist doctor` (present / missing / locked / stale per probe).
3. **Jobs:** `launchctl list | grep -iE "tommy|investment|kseistat|jquant|ausdata|bps|usfin"`; a
   non-zero second column is a failed last run.
4. **Servers:** `curl -s -m5 -o /dev/null -w "%{http_code}"` on 127.0.0.1:8660 (sec-edgar `usfin
   serve`) and :8770 (dbnomics `dbn serve`); :8790/:8791 (`assist status`) are only up when started.
5. **Last runs:** tail `launchd/weekly.log` and `launchd/regime.log`. A `start` line with no
   `end` line means the job died: check `pmset -g log | grep -E "^<date> 0[6-9]" | grep -E
   "Sleep|Wake"` (a laptop asleep on battery at 07:00 kills it). Age of `out/guide.json`.
6. **Run's own stale lines:** `grep "^stale:"` in the last run log; `sec-edgar (locked)` or
   `dbnomics (locked)` means a sibling job held the store (sec-edgar's feed runs every 15 min
   18:00-10:46 WIB and its reconcile at 11:30 WIB, in `../sec-edgar/data/usfin-serve.log`).

## Report

One table per group: fresh / stale / missing sources, then problems (new or changed), then known
gaps, then services and jobs. Say what changed since the previous check when it is a recheck.
To redo a finished weekly run: `uv run assist run --no-send` (no second Telegram).
