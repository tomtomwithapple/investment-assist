# P45-start — PLAN S29: one-step `./start.sh`

Date: 2026-10-27. Branch `slice/P45-start`.

## Tests

- Red: `tests/test_start.py` with no `start.sh`: 1 failed, 20 errors (`start.sh missing`,
  `FileNotFoundError` copying it).
- Green: 21 passed (about 10 s, most of it the 2 s timeout case and the SIGTERM case).
  Cases: fresh out/ (no run), stale and empty out/ (`run --no-send`), no out/ at all, `--send`,
  `--run`, `--no-run`, `--run --no-run` (exit 2), `--no-open` with `--port 8799`,
  `--install-jobs` (install.sh right after the sync), no flag (install.sh and launchctl never
  called, no `$HOME` created), uv missing (exit 1 with the install link), bad flags `--bogus`,
  `--port`, `--port x` (exit 2), `--help`, server never answering (exit 1 after the timeout,
  log tail shown, server stopped, no `open`), server exiting early (exit 1 at once), failed
  doctor and run (pages still served), SIGTERM (script stops, server process gone).
- Full suite: 1257 passed. `ruff check .` clean, `sh -n start.sh` clean.

## Live run (real repo)

`./start.sh --no-open --port 8799`, started in the background:

| Step | Result |
|---|---|
| `uv sync` | 22 packages resolved, 21 checked, under 0.1 s |
| `assist doctor` | 11 of 14 present and fresh, 2 stale (jquantster `investor_types` empty, daily bars 2026-08-03; idx-method `jkse_daily.csv` 2026-09-30), 1 missing (satudatascape); about 4 s |
| run decision | **no run**: all 51 out/ files have `as_of` 2026-10-27 (today) |
| `assist status --port 8799` | answered within about 1 s (13:05:49 → 13:05:50) |
| total, start to "pages on" | 6.1 s (a second start with `--no-run` under a pty: 5.1 s) |

- `curl /`: 200, 15,190 B, 17 ms. `curl /candidates`: 200, 10,536 B, 4 ms.
- Processes: `sh start.sh` → `uv run assist status` → Python listening on 127.0.0.1:8799.
- Stop: SIGINT sent with `kill -INT` to the script started with `&` from a non-interactive
  shell did nothing. POSIX shells ignore SIGINT in asynchronous commands, and a trap cannot
  catch a signal that was ignored on entry. SIGTERM stopped it (it logged "stopped"), uv
  passed the TERM on to Python, and port 8799 was free with no server process left. Ctrl-C at a
  real terminal (a pty from Python, `\x03`) stopped it too: exit 130, port free, no process
  left.
- out/ (51 files) sha-identical before and after; journal still 865 records.

## Data gaps, checked against the live doctor and `assist paper`

- PHEI `igsyc_point` fresh at 2026-10-26. The IDN bonds rule now proposes neutral and the stocks
  rule underweight, but neither is applied (insufficient sample, on 0 / off 0).
- FRED VIXCLS fresh at 2026-10-23. IDN bonds confidence 0.79, so the ×0.9⁵ cut is gone.
- Paper: the benchmark has no week scored (2 stale), and all 8 model segments have 0 weeks.
  JCI is frozen at 2026-09-30 and IGSYC.10 ends 2026-10-26.
- singstat observations are newest at 2026-10-07: within the doctor's 45-day window, so not
  flagged stale, but still lagging.

## Notes

- The server's output goes to a `mktemp` file under `$TMPDIR` (named in the startup line). It
  is kept after exit. `web.serve` logs no requests, so the file holds only the startup line
  unless something fails.
- Polling uses `sleep 1` (POSIX integer sleep), so the pages show up to 1 s after they first
  answer.
