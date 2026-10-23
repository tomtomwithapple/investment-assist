# P12-bisfetcher — results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

The bisfetcher adapter (P12) is done and committed as `3e77b08` on `slice/P12-bisfetcher`, not pushed. The accept command exits 0 (18 tests pass, ruff is clean), and the full suite still passes (252 tests).

**What it reads** (`src/assist/sources/bisfetcher.py`):
- **Observations:** tidy rows for any series ids, optionally limited to a date range. A point-in-time read keeps only periods that had ended by the given date, as bisfetcher's README says to.
- **Series list:** each series with its unit, labels, first and last date, and whether it was discontinued. It can be filtered by dataset or country.
- **Latest values:** the newest value per series, or the newest as of a past date.
- **Datasets:** each dataset with its version, last pull time and series count.
- **Named ids:** constants for the series bisfetcher's README lists, such as the BI rate (`WS_CBPOL.M.ID`/`.D.ID`), the Fed rate, the IDR real effective exchange rate and the Indonesian credit gap.
- **Store handling:** every call opens the store read-only and closes it straight away, so it holds the lock only briefly and never writes. A missing store, or one without bisfetcher's tables, is reported as missing. A store locked by a refresh is reported as locked. A broken query raises an error instead.
- **Test fixture:** bisfetcher's own table definitions, seeded with real values copied from the store.

**Live run** (read-only, 0.24 s): 5 datasets and 732 series, none discontinued.

| Series | Latest | Value |
|---|---|---|
| BI rate, monthly (`WS_CBPOL.M.ID`) | 2026-09 | 5.75 |
| BI rate, daily (`WS_CBPOL.D.ID`) | 2026-10-05 | 5.75 |
| Fed rate (`WS_CBPOL.M.US`) | 2026-09 | 3.875 |
| IDR real effective exchange rate (`WS_EER.M.R.B.ID`) | 2026-08 | 87.77 |
| IDR nominal effective exchange rate, daily (`WS_EER.D.N.B.ID`) | 2026-10-13 | 86.0 |
| Indonesia credit-to-GDP gap | 2026-Q1 | −1.33 |
| Indonesia debt-service ratio | 2026-Q1 | 4.2 |
| Indonesia real house prices, year on year | 2026-Q2 | −2.19 |

The BI rate path for 2026 was 4.75 to April, 5.25 in May and 5.75 from June. These match the values bisfetcher recorded itself. The newest refresh was 2026-10-21.

**Where the sibling differs from this repo's docs** (I followed bisfetcher):
- **Store path:** this repo's config uses `ASSIST_BISFETCHER_DB`, but the slice notes and bisfetcher use `BISFETCHER_DB`. The adapter checks `ASSIST_BISFETCHER_DB` first, then `BISFETCHER_DB`, then the config path.
- **Extra tables:** bisfetcher's contract also includes `fetch_log` and an `observation_latest` view, not just `series`, `observations` and `datasets`. The adapter reads current values from `observation_latest`.
- **No live server fallback:** PLAN.md suggests reading bisfetcher's server while a refresh holds the lock. But its server (port 8771) also answers "busy" during a refresh, so it can't stand in. The adapter reports `bisfetcher (locked)` instead.
- **Monthly REER only:** the IDR real effective exchange rate is monthly only; the BIS publishes no daily version. The daily series is nominal.
- **Data age stamp:** the store keeps only the latest published values. Each row's data-age stamp is therefore the date bisfetcher last wrote the value, not when the BIS published it.

This slice has no `docs/results/P12-bisfetcher.md`, so the numbers above are recorded only here.
