# P25-ausdata — results

ausdata adapter (`src/assist/sources/ausdata.py`): RBA, ABS, AOFM and ausdata's derived
indicators, read-only from `../ausdata/warehouse.duckdb`. Feeds the AU overrides (P28) and AUD FX
(P27).

## What it reads

- `rows(series_ids, start, end, as_of)`: tidy `Row`s; `Row.as_of` = `pulled_at` date. `as_of=`
  keeps rows whose **period has ended** by then (ausdata's brief does the same).
- `series(source=)`: catalog with `extra` JSON, first/last date, `n_obs`.
- `latest(series_ids, as_of=)`: newest non-null row per series with `period_end`, unit, `pulled_at`.
- `loads()`: `raw_loads` (ausdata S26); `[]` when the table is absent.
- `freshness()`: per publisher, the counts, date range, newest `pulled_at` and newest
  `raw_loads.loaded_at`.
- `period_end()`: ABS rows are dated at period **start** (M, Q, and A from the id suffix or
  `frequency`). RBA, AOFM and derived rows are already dated at period end.
- Named ids: `CASH_RATE` FIRMMCRTD, `AGS_2Y`/`AGS_10Y`, `AUD_USD` FXRUSD, `AUD_IDR` FXRIR, `TWI`,
  `AUD_USD_M`/`AUD_IDR_M`, `CPI_YY_M`, `CPI_TRIMMED_YY_M`, `UNEMPLOYMENT`, `GDP_YY`,
  `REAL_CASH_RATE`, `CURVE_10Y_2Y`, `CREDIT_GROWTH_YY`, `NONRES_AGS_PCT`.
- Every call opens, queries and closes the store. A locked store is retried 3 times, 2 s apart,
  and then reported as `ausdata (locked)`. A missing store, or one without
  `observations`/`series_meta`, is reported as `ausdata (missing)`.
- Path: `$ASSIST_AUSDATA_DB`, then ausdata's own `$AUSDATA_DB`, then `config/sources.yaml`.

Tests: 19 in `tests/sources/test_ausdata.py`. The fixture is ausdata's own DDL plus real seeded
values, and it covers a pre-S26 store with no `raw_loads`, the lock retry, and that the adapter
never writes.

## Live run (2026-10-23, read-only, 0.66 s, no lock)

The store holds 1,226 series and 172,369 observations, newest pull 2026-10-21 03:24 UTC.

| Publisher | Series | Obs | Last date | Last pulled (UTC) |
|---|---|---|---|---|
| abr | 36 | 6,169 | 2026-10-21 | 2026-10-21 03:23 |
| abs | 386 | 8,124 | 2026-09-01 | 2026-10-21 03:00 |
| aofm | 631 | 33,991 | 2026-10-16 | 2026-10-17 13:25 |
| asic | 13 | 2,270 | 2026-09-01 | 2026-10-21 03:02 |
| derived | 14 | 10,234 | 2026-10-31 | 2026-10-21 03:24 |
| rba | 144 | 111,581 | 2026-10-21 | 2026-10-21 03:00 |

| Series | Range | Obs | Latest | Value | Unit |
|---|---|---|---|---|---|
| `FIRMMCRTD` cash rate | 2011-01-04 → 2026-10-20 | 3,999 | 2026-10-20 | 4.60 | % |
| `FCMYGBAG2D` AGS 2y | 2013-09-02 → 2026-10-14 | 3,297 | 2026-10-14 | 4.919 | % p.a. |
| `FCMYGBAG10D` AGS 10y | 2013-05-20 → 2026-10-14 | 3,375 | 2026-10-14 | 5.314 | % p.a. |
| `FXRUSD` AUD/USD | 2023-01-03 → 2026-10-20 | 954 | 2026-10-20 | 0.6984 | USD |
| `FXRIR` AUD/IDR | 2023-01-03 → 2026-10-20 | 954 | 2026-10-20 | 12,578 | IDR |
| `FXRTWI` TWI | 2023-01-03 → 2026-10-20 | 954 | 2026-10-20 | 64.7 | index |
| `FXRIR_M` AUD/IDR month-end | 2010-01-29 → 2026-09-30 | 201 | 2026-09-30 | 12,450 | IDR |
| `ABS.CPI.3.10001.10.50.M` CPI y/y | 2025-04 → 2026-08 | 17 | 2026-08 | 4.0 | % |
| `ABS.CPI.3.999902.20.50.M` trimmed mean y/y | 2025-04 → 2026-08 | 17 | 2026-08 | 3.6 | % |
| `ABS.LF.M13.3.1599.20.AUS.M` unemployment | 1978-02 → 2026-09 | 584 | 2026-09 | 4.72 | % |
| `DER.GDP_YY` real GDP y/y | 1960-Q3 → 2026-Q2 | 264 | 2026-06-30 | 2.14 | % |
| `DER.REAL_CASH_RATE` | 2011-01 → 2026-10 | 190 | 2026-10-31 (partial) | 1.00 | % |
| `DER.CURVE_10Y_2Y` | 2013-09-02 → 2026-10-14 | 3,297 | 2026-10-14 | 0.395 | pp |
| `DER.CREDIT_GROWTH_YY` | 1977-09 → 2026-08 | 576 | 2026-08-31 | 8.6 | % |
| `AOFM.FH.AGS.NONRES_PCT` | 2003-Q2 → 2026-Q2 | 93 | 2026-06-30 | 52.37 | % |

## Findings and differences from our notes

- **There is no `raw_loads` table in the live store yet.** ausdata S26 added it, but this
  warehouse has not been refreshed since that change (the newest pull is 2026-10-21). The adapter
  treats the table as optional: `loads()` returns `[]` and `last_loaded_at` stays None, so
  freshness falls back to `pulled_at`. ausdata's PLAN calls `raw_loads` "read-only bookkeeping;
  no adapter change needed". It only proves which raw file was loaded, not when the data was
  published, so `pulled_at` plus the period end is the better staleness signal anyway.
- **The derived monthly indicators date the running month at its month end.** For example,
  `DER.REAL_CASH_RATE` and `DER.TENDER_*_3M` have a 2026-10-31 row on 2026-10-23. A plain
  `latest()` returns that row; `latest(as_of=today)` hides it until the month is over. P28 should
  pass `as_of`.
- **ABS rows are dated at period start** (Aug CPI = 2026-08-01). `as_of` handles this through
  `period_end`.
- **The daily RBA FX history only goes back to 2023-01-03** (RBA's current F11.1 file). For a
  longer AUD/IDR or AUD/USD history, use the month-end `FXRIR_M`/`FXRUSD_M` series (from
  2010-01). `FXRIR` gives AUD/IDR directly, so P27 does not need to cross through USD for AUD.
- **The monthly ABS CPI series start only in 2025-04.** For earlier history, use the quarterly
  `ABS.CPI_Q.*` or `DER.CPI_HEADLINE_YY_Q`.
- **The env var follows the bisfetcher pattern:** `ASSIST_AUSDATA_DB`, then ausdata's
  `AUSDATA_DB`.
- **The live run needs `ASSIST_SIBLINGS_ROOT`.** From a worktree under `.claude/worktrees/`, the
  config resolves `../` relative to the worktree, so the live run needed
  `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects`.
