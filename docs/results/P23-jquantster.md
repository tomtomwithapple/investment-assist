# P23-jquantster — results

Live run 2026-10-23, read-only against `../jquantster/data/jquantster.db` (jquantster at
`e42574b`, last sync 2026-10-23T16:50). File checksum identical before and after; no `-shm` or
`-wal` left beside it.

## What the adapter reads

`src/assist/sources/jquantster.py`, `JquantsterSource` (SQLite via `sqlite_ro`; the file is WAL
with no `-shm`, so it opens with `immutable=1`):

| Series id | Table | Date / as_of | Layer |
|---|---|---|---|
| `JGB.<tenor>` (`JGB_2Y`, `JGB_10Y`) | `jgb_yields` (MOF, %) | trade date / None | 2 |
| `BOJ.<key>` (`USDJPY`, `CALL_RATE`, `TANKAN_LM`, `TANKAN_LN`, `*_fc`) | `macro_obs`; units via `macro_meta()` | obs date (quarter end for Tankan) / None | 2 |
| `TSE_FLOW.<section>.<column>` (`FRGN_BAL_PRIME`) | `investor_types_latest` | week end / pub date | 3 |
| `JQ_BAR.<code>.<field>` | `daily_bars` | trade date / None | 4 |
| `JQ_FIN.<code>.<1Q\|2Q\|3Q\|FY>.<field>` | `fins_summary.raw` (newest disclosure per period) | period end / disclosure date | 4 |

Default `rows()` = every JGB tenor + BOJ key + TSE flow series present. `status()` returns the
J-Quants plan, data window and per-dataset entitlement.

## Live numbers

109,097 default rows, no stale inputs.

| Series | Rows | Range | Latest |
|---|---|---|---|
| JGB.1Y | 6,567 | 2000-01-04..2026-10-22 | 1.660 |
| JGB.2Y | 6,567 | 2000-01-04..2026-10-22 | 1.914 |
| JGB.3Y | 6,567 | 2000-01-04..2026-10-22 | 2.028 |
| JGB.4Y | 6,567 | 2000-01-04..2026-10-22 | 2.184 |
| JGB.5Y | 6,567 | 2000-01-04..2026-10-22 | 2.304 |
| JGB.6Y | 6,567 | 2000-01-04..2026-10-22 | 2.399 |
| JGB.7Y | 6,567 | 2000-01-04..2026-10-22 | 2.508 |
| JGB.8Y | 6,567 | 2000-01-04..2026-10-22 | 2.659 |
| JGB.9Y | 6,567 | 2000-01-04..2026-10-22 | 2.785 |
| JGB.10Y | 6,567 | 2000-01-04..2026-10-22 | 2.914 |
| JGB.15Y | 6,567 | 2000-01-04..2026-10-22 | 3.438 |
| JGB.20Y | 6,567 | 2000-01-04..2026-10-22 | 3.707 |
| JGB.25Y | 5,529 | 2004-03-22..2026-10-22 | 3.985 |
| JGB.30Y | 6,567 | 2000-01-04..2026-10-22 | 3.952 |
| JGB.40Y | 4,635 | 2007-11-06..2026-10-22 | 3.959 |
| BOJ.usdjpy | 6,566 | 2000-01-04..2026-10-21 | 158.29 |
| BOJ.call_rate | 6,566 | 2000-01-04..2026-10-21 | 1.227 |
| BOJ.tankan_lm | 107 | 2000-03-31..2026-09-30 | 24 |
| BOJ.tankan_ln | 107 | 2000-03-31..2026-09-30 | 35 |
| BOJ.tankan_lm_fc | 108 | 2000-03-31..2026-12-31 | 21 |
| BOJ.tankan_ln_fc | 108 | 2000-03-31..2026-12-31 | 30 |
| TSE_FLOW.* | 0 | — | — |

10Y−2Y = +100 bp; Tankan large manufacturers 24 now, forecast 21 for Q4 (non-manufacturers 35 → 30).

Layer 4 spot check: `daily_bars` 4,453 codes × 499 days, 2024-07-16..2026-07-31; `fins_summary`
has 47 disclosures for 5 watchlist codes only (67580, 68610, 72030, 83060, 99840). E.g. Toyota
72030 FY EPS 359.56 (FY2025-03) → 295.25 (FY2026-03, disclosed 2026-05-08), next-FY forecast
`NxFEPS` 251.25.

## Where jquantster differs from our notes

- **No TSE investor flows.** `investor_types` is empty: the J-Quants key is on the **Free** plan
  and the entitlement is `not_in_plan`. Layer 3 TSE flows need a paid plan in jquantster
  (`JQUANTS_PLAN`); the adapter returns no rows and `status()` says why. The doctor probe
  `select max(en_date) from investor_types` will report it empty/stale.
- **No index-level prices or EPS.** jquantster stores per-stock bars and per-stock summaries, no
  TOPIX/Nikkei series. P29 (foreign candidates, index-level JP) needs either an index series
  added to jquantster or another source (e.g. dbnomics/FRED); building a cap-weighted aggregate
  from 4,453 stocks would need shares outstanding for all of them, which jquantster has only for
  the 5 watchlist codes.
- **Free plan is 12 weeks delayed.** Bars end 2026-07-31 (`status()['window']`), so a
  `daily_bars` freshness probe with a short max age will always show stale.
- **EDINET is empty** (`no_key`), so not read.
- FY summaries leave `FEPS` blank and carry the next year's forecast in `NxFEPS`.
- The default `config/sources.yaml` path resolves against the repo's parent; from a worktree set
  `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects` (as this run did).
