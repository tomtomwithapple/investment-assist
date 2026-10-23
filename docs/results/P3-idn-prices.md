# P3-idn-prices: results

Live run 2026-10-23, read-only against the real stores on this Mac.

## Sources checked first

- **idxscape** (HEAD `e7862c8`, J8): `fx_rate` is migration 7, keyed on `(rate_date, pair)`,
  `rate` DECIMAL(18,2) IDR per USD, `carried_forward` BOOLEAN, `recorded_at` TIMESTAMPTZ
  (`docs/storage.md`, `src/idxscape/db.py`). The real table matches. PHEI (migration 9) is still
  absent from this Mac's copy (no `igsyc_point`), not needed here.
- **idx-method** (HEAD `b0e8547`): README *Changes the parent must follow*, 2026-10-19: the
  index CSVs stay committed but frozen. Matches the slice notes. The weekly files stop at
  **2026-09-25**, not 2026-09-30 as CLAUDE.md and PLAN.md say (only the daily files reach 09-30).

## Adapters

- `assist.sources.idxscape.IdxscapeSource`: series `JISDOR` (pair USDIDR). `as_of` = the WIB date
  of `recorded_at`, i.e. when idxscape stored the range, not a BI vintage (BI does not revise
  JISDOR). BI's carried-forward days come from `carried_forward()`. If the `fx_rate` table is
  absent the source is reported `missing`.
- `assist.sources.idxmethod.IdxMethodIndexSource`: 15 series from 12 CSVs (close/price, plus
  `_TR` total-return columns). Every row's `as_of` is its file's real last date. JCI is read only
  through `jci()`, so a future JCI fetcher replaces that one function.

## Numbers

| Series | Rows | First | Last | as_of | Notes |
|---|---|---|---|---|---|
| JISDOR | 1213 | 2021-10-01 | 2026-10-16 (18,052) | 2026-10-16 | 2 carried-forward days (2021-11-26, 2021-12-17); longest gap 12 days (holidays) |
| JKSE (JCI) | 7288 | 1996-10-02 | 2026-09-30 (6,071.14) | 2026-09-30 | frozen |
| LQ45 / LQ45_TR | 7188 / 2675 | 1997-02-24 / 2015-09-01 | 2026-09-30 | 2026-09-30 | frozen |
| XIHD | 1900 | 2018-12-17 | 2026-09-30 | 2026-09-30 | frozen |
| Weekly (DBX, MBX, IDX30, IDX80[_TR], IDXG30, IDXV30, INVESTOR33[_TR], KOMPAS100[_TR]) | 369–945 each | 2008–2019 | 2026-09-25 | 2026-09-25 | frozen; INVESTOR33_TR has 130 blank (None) values, KOMPAS100_TR 429, all early |

JCI and JISDOR overlap on 1198 days (2021-10-01 to 2026-09-30). That is what the P8 regime
walk-forward can use for JCI and IDR returns, and it stops growing until JCI has a fetcher.
JISDOR is 7 days old (last row 2026-10-16), right at the doctor's 7-day limit.

Tests: `uv run pytest -q tests/sources/test_idxscape_prices.py tests/sources/test_idxmethod_index.py`
gives 19 passed. The full suite gives 121 passed. ruff is clean.
