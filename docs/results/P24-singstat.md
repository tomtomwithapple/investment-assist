# P24-singstat — results

Run 2026-10-23, read-only against `../singstat/data/sgecon.duckdb` (0.37 s for catalog, latest,
refresh log and the full SORA history).

## What the adapter reads (`src/assist/sources/singstat.py`)

- `rows(ids, start, end)`: tidy `Row`s; `as_of` is `series.updated_at` (the store keeps one vintage).
- `latest(ids, as_of=)`: newest non-null value per series, with unit, title, origin.
- `series(origin=, prefix=)`: catalog with first/last date and count.
- `idr_per_sgd(start, end)`: rupiah per S$, the inverse of `mas:fx:idrsgd` (nulls dropped).
- `refresh_log()`: newest refresh per origin, with its last `ok` time.
- Constants: `SORA`, `SORA_3M`, `SGS_2Y`, `SGS_10Y`, `TBILL_6M`, `USD_SGD`, `fx_id(ccy)`, `CPI`,
  `REAL_GDP_YOY`, `IDR_PER_SGD`.
- Each call ATTACHes the file READ_ONLY into a fresh in-memory DuckDB, queries and closes. A locked
  store is retried (3 tries, 2 s apart by default) before it is reported `singstat (locked)`.

## Live numbers

Store: 478 series (singstat 346, ura 71, mas 36, acra 25), none empty.

| Series | Range | Obs | Latest |
|---|---|---|---|
| `mas:sora` | 2005-07-01 → 2026-10-06 | 5,337 | 1.3152 % |
| `mas:sora:comp3m` | 2005-10-03 → 2026-10-06 | 5,272 | 1.2323 % |
| `mas:tbill:6m` | 2012-07-09 → 2026-10-07 | 2,324 | 1.87 % |
| `mas:tbill:1y` | 2005-01-03 → 2026-10-07 | 5,461 | 1.73 % |
| `mas:sgs:2y` | 2005-01-03 → 2026-10-07 | 5,461 | 1.95 % |
| `mas:sgs:5y` | 2005-01-03 → 2026-10-07 | 5,461 | 2.21 % |
| `mas:sgs:10y` | 2005-01-03 → 2026-10-07 | 5,461 | 2.48 % |
| `mas:sgs:30y` | 2012-03-28 → 2026-10-07 | 3,641 | 2.54 % |
| `mas:fx:usdsgd` | 2005-01-03 → 2026-10-07 | 5,461 | 1.2789 S$/USD |
| `mas:fx:eursgd` | 2005-01-03 → 2026-10-07 | 5,461 | 1.4372 |
| `mas:fx:jpysgd` | 2005-01-03 → 2026-10-07 | 5,461 | 0.008072 |
| `mas:fx:audsgd` | 2005-01-03 → 2026-10-07 | 5,461 | 0.8919 |
| `mas:fx:idrsgd` | 2005-01-03 → 2026-10-07 | 5,461 | 7.155e-05 → **13,976 IDR per S$** |
| `singstat:M213751:1` CPI (2024=100) | 1961-01 → 2026-08 | 788 | 103.334 |
| `singstat:M015631:2` real GDP y/y | → 2026-Q2 | | 5.9 % |
| `singstat:M182342:1` unemployment SA | → 2026-Q2 | 138 | 1.9 % |
| `singstat:M355352:1` IPI SA | → 2026-08 | 524 | 109.192 |
| `singstat:M602202:1` retail volume SA | → 2026-08 | 500 | 99.882 |
| `singstat:M451002:4.2` NODX SA | → 2026-08 | 608 | S$20.28bn (unit: thousand dollars) |

MAS has 21 FX series, 7 SGS tenors (2/5/10/15/20/30/50y), 3 T-bill ids and 5 SORA ids, 36 in all.

## Findings

- **Stale store.** The last refresh was 2026-10-07 20:29 SGT (`refresh_log`: mas ok, singstat ok
  at 20:28). Nothing has run in 16 days, so singstat's launchd schedule is not running on this Mac.
  MAS data is 16 days old; SingStat monthly data runs to 2026-08. The doctor probe
  (`max_age_days: 45`) still passes. Overrides should flag MAS data older than about a week.
- **Tables missing from the store.** singstat's code has the S18 tables (M183891, M184101, M182981,
  M015861, M250431, M250142) and the S19 HDB series, but the store was last filled before they
  landed, so it has none of them. URA was skipped because no access key is set.
- **The obvious GDP id is nominal.** `singstat:M015631:1` is GDP at *current* prices y/y (12.4 %).
  Real GDP y/y is `singstat:M015631:2` (5.9 %), which this slice exports as `REAL_GDP_YOY`.
- **FX units.** `mas:fx:<ccy>sgd` is S$ per ONE unit; singstat already divides MAS's per-100
  quotes by 100. The IDR quote has only 4 significant figures, a resolution of about 0.07 %
  (about ±7 IDR per S$). For IDR conversion, a USD cross (JISDOR ÷ USD/SGD) is more precise:
  1.2789 / 7.155e-05 gives an implied USD/IDR of about 17,874.
- **`mas:tbill:3m` ends 2013-09-18.** Use `mas:tbill:6m` or `mas:sora:comp3m` for the short rate.
- **Store path.** In a worktree, the default `config/sources.yaml` path resolves the siblings
  relative to the worktree, so a live run there needs `ASSIST_SIBLINGS_ROOT=/Users/.../Projects`.
  The adapter also follows singstat's own `$SGECON_DB`, resolved against the singstat repo when
  relative, after `$ASSIST_SINGSTAT_DB`.
- There is no `.wal` file and the store was not locked during the run.
