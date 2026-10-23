# P11-bps — live results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

**What was built**
- **`src/assist/sources/bpslooker.py`**: reads bps-looker's Postgres read-only through DuckDB's postgres extension. Tests run the same SQL against a DuckDB fixture with the same tables. The default rows are the national (domain `0000`) series from `observation`:
  - CPI: `BPS_CPI_YOY` and `BPS_CPI_MOM` (vars 2263 and 2262, Indonesia row 9999).
  - GDP: `BPS_GDP_YOY` and `BPS_GDP_QOQ` (var 104, GDP row 99003, measures 5 and 4).
  - Trade: `BPS_EXPORTS_USD_MN`, `BPS_IMPORTS_USD_MN` and `BPS_TRADE_BALANCE_USD_MN` (vars 196, 497, 498).
  - Annual sub-periods are skipped. A month is dated to its first day and a quarter to its first month.
  - `as_of` is BPS's `last_update` date, or the WIB date of `fetched_at` when BPS gives none.
  - Opt-in by id: `BPS_TRADE.<export|import>.<hs2>`, monthly trade by HS chapter from `trade_flow` in USD mn (e.g. 27 coal, 15 CPO, 75 nickel). This is extra context for the commodity view.
- **`src/assist/sources/satudatascape.py`** (stub): reads `data/satudata.db` read-only.
  - `rows()` gives one `SATUDATA_RUNS.<kind>` row per finished run in `runs`, for freshness only.
  - `last_run(kind)` returns the newest finish date.
  - `tables(grades=("A","B"))` lists the extracted Parquet tables.
- **Fixtures** are in `tests/fixtures/bpslooker/`: the Postgres tables rebuilt in DuckDB with values copied from the live store, plus satudatascape's `runs` and `tables` in SQLite.

**Live run (read-only, 2026-10-23)**
- bps-looker returned 658 rows with no stale inputs, in about 11 s through the postgres scanner:

| Series | Rows | Range | Latest | `as_of` |
|---|---|---|---|---|
| CPI y/y | 33 | 2024-01 to 2026-09 | 3.28% | 2026-10-01 |
| CPI m/m | 33 | 2024-01 to 2026-09 | 0.30% | 2026-10-01 |
| GDP y/y | 62 | 2011Q1 to 2026Q2 | 5.29% | 2026-08-05 |
| GDP q/q | 62 | 2011Q1 to 2026Q2 | 3.73% | 2026-08-05 |
| Exports | 212 | 2009-01 to 2026-08 | 26,612.2 USD mn | 2026-10-01 |
| Imports | 140 | 2015-01 to 2026-08 | 23,060.0 USD mn | 2026-10-01 |
| Trade balance | 116 | 2017-01 to 2026-08 | 3,552.2 USD mn | 2026-10-01 |

- Monthly sums from `trade_flow` match the headline export figure (2026-01: 22,155.7 USD mn both ways). August 2026 by HS chapter: coal 3,986, CPO 3,974 and nickel 1,349 USD mn.
- satudatascape: as expected, the file is absent on this Mac, so it was reported as `satudatascape (missing)`, not a failure.

**Where the siblings differ from the notes**
- **bps-looker** has no doc that lists what the parent may read; its `docs/plan.md` has no parent section. I mapped the series from the live schema, read-only.
- **CPI history is short.** The 2022=100 CPI variables start in 2024, giving only 33 months. Anything needing a longer history would have to splice in the older base-year variables, which this slice doesn't do.
- **satudatascape** matches the notes: its 2026-10-14 table list has no changes, and its schema matches `migrations/0001_init.sql`.
