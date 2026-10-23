# P15-tic — results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

P15-tic is finished and committed on `slice/P15-tic` as `5984ef6` (not pushed). The accept command exits 0: 29 tests pass and ruff is clean. The full suite also passes (192).

**What it does.** `TicSource` in `src/assist/sources/usfin_tic.py` imports the HTTP/ATTACH helper from `usfin.py` without editing it. It reads TIC series through `usfin serve`'s CSV when the server answers, and otherwise opens the store read-only. One test checks that both paths return identical rows.
- **Default:** all 34 Indonesia series (country code `42218`), both `us_*` and `for_*`. Other countries can be picked by code or by name, e.g. `99996` Grand Total or "total asia".
- **Current or point in time:** latest values come from `tic_observation_latest`; values as known on a given date come from `tic_as_of(DATE)`.
- **Missing values:** months with no value come back as None.
- **Catalog:** `series()` lists a country's series with each one's newest month and value.

**Where sec-edgar differs from the slice notes (I followed sec-edgar).**
- `/series/tic?country=…&format=csv` returns the list of a country's series, not observations. Each series' data comes from `/series/tic/<id>?format=csv[&as_of=]`, so the HTTP path makes the list request first, then one request per series.
- TIC has no vintage date the way FRED does. The `as_of` date on each row is the date (UTC) sec-edgar first saw that value.

**Live run (read-only).** `usfin serve` was not answering, so it read the store directly:
- 34 Indonesia series, 12,363 rows, from 1984-12 to 2026-07, in about 0.5 s.
- US net purchases of Indonesian equities (`us_lt_eqty_net_42218`): −835 / −735 / −7 $mn for May, June and July 2026.
- Indonesia's US Treasury holdings (`for_treas_pos_42218`): 35,663 / 32,009 / 37,547 $mn.
- Grand-total foreign Treasury holdings: 9,248,126 $mn in July 2026.
- Asking for values as known on 2026-10-01 returns nothing, because the whole TIC history was first loaded on 2026-10-14. Point-in-time backtests on TIC can't go back before that date.

There was no `docs/results/P15-tic.md` in my allowed files, so these numbers are only recorded here.
