# P14-kseistat — results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

I built the P14-kseistat adapter and committed it as `71fc424` on `slice/P14-kseistat` (not pushed). The acceptance command passes: 13 tests and ruff are clean, and the full suite passes too (163 tests).

**What it reads**

`src/assist/sources/kseistat.py` reads kseistat's store read-only and returns tidy rows, sorted by series and date:

- **Market shares:** `KSEI.<method>.<metric>` from `v_market_composition`.
  - `method` is `sum` or `equal_weight`.
  - `metric` is `n_stocks`, `total_holdings` or one of the eight `*_pct` columns.
  - The two main series have named constants, `FOREIGN_PCT_SUM` and `FOREIGN_PCT_EQUAL`.
  - The default `rows()` returns these 20 series.
- **Investor-type shares:** `KSEI_TYPE.<origin>.<investor_type>.<measure>` from `v_type_composition`, where measure is `shares`, `pct_sum` or `pct_equal_weight`. You get these by asking for an id or by calling `types()`; they are never in the default `rows()`.
- **`as_of`:** the date kseistat loaded that month (`loads.loaded_at`), or None if that month has no `loads` row.
- **Unavailable store:** a missing file, a store without the views, or a locked store becomes a `stale_inputs` entry instead of failing the run.

**Test fixtures**

`tests/fixtures/kseistat/schema.sql` is kseistat's own table and view definitions, copied from its `kseistat/db.py` at commit `40791dc`. `data.sql` adds two small months with expected values worked out by hand. They include a stock with zero holdings, which gets NULL percentages and is left out of the equal-weight average.

**Live run (read-only, real store)**

- **Series:** 720 market rows (20 series × 36 months, 2023-10-31 to 2026-09-30) and 1,944 type rows (54 series). Nothing was reported unavailable.
- **Foreign share, sum method:** 40.40% → 31.32% (35.07% in August). Equal-weight: 23.28% → 21.40%. These match the figures in kseistat's own PLAN log.
- **Investor-type check:** the `pct_sum` values for 2026-09-30 add up to exactly 100.
- **Freshness:** the newest month is 2026-09-30, loaded 2026-10-07. That is within the doctor's 45-day limit.
- **Store untouched:** the file's checksum was the same before and after the run.

**Where the sibling differs from CLAUDE.md / PLAN.md**

- Neither doc says this, but kseistat writes each load into a copy of the file and then swaps it into place. So a reader never blocks a load, and a "locked" result from this store would be unusual.
- Percentages are shares of the holdings KSEI records, not of shares outstanding (`sec_num`). This follows kseistat's README.

There is no `docs/results/P14-kseistat.md` in this slice's files, so the numbers above are only recorded here.
