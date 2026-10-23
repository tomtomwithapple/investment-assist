# S1-contracts — results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

S1-contracts is committed as `fbe9e82` and not pushed. The acceptance command exits 0: 47 contract tests pass, ruff is clean, and the whole suite passes (80 tests).

**What's in it**
- **`src/assist/sources/base.py`:**
  - `Row` (series_id, date, value, as_of, source) and a `Source` protocol: anything with a `name` and `rows(series_ids, start, end)`.
  - `SourceUnavailable` carries a reason of `missing`, `locked` or `error`. `read_rows()` turns it into a `stale_inputs` entry such as `"financer (locked)"`. Real bugs, such as a bad query or an HTTP 404, still raise.
  - Read-only openers for DuckDB, SQLite, Postgres and localhost HTTP CSV, built on S0's doctor code rather than duplicating it. `open_query_close` is for dbnomics, whose lock blocks its own refresh while any reader has the file open.
  - For HTTP: server down → `missing`, 503 → `locked` (dbnomics returns 503 while a refresh holds the lock), other 5xx → `error`.
- **`src/assist/layers/types.py`:** frozen `Regime`, `AssetScore`, `Override`, `Signal`, `Candidate` and `Weights`, which reject out-of-range values when created. For example, an override can move the score by at most ±10 points, and weights must add up to 100 ± 0.5. It also holds the enum constants and validators for both schemas.
- **`schema/stance.schema.json`:** reuses the date, semver and flag definitions from worldbankscape's `score.schema.json`. I copied that schema into `schema/worldbankscape/`, so tests don't depend on the sibling repo; a test checks the copy still matches worldbankscape's file.
- **Three sample stances** in `tests/fixtures/stance/`: IDN bonds overweight with a ladder entry, IDN stocks neutral with a stale input, and USA bonds underweight with holdings unavailable.

**Contract choices you may want to check before others build on it** (changing them later means `slicer invalidate S1-contracts`):
- Besides the CLAUDE.md example fields, a stance must have `schema_version`, `model_fingerprint` (`sha256:…`, for the journal) and `sources`.
- I used `sources` as the slice notes say; worldbankscape calls the same thing `attribution`.
- `entry.style` also allows `none`, for when there's nothing to buy.
- `portfolio.current_pct` can be `null` when financer is unavailable.
- The disclaimer must contain "not investment advice".
- `asset` is limited to stocks, bonds, currency and commodities, so worldbankscape's `property` and `business` classes have no stance.

**Live run (read-only)**

| Source | Result |
|---|---|
| bisfetcher | 1,291,126 rows, newest 2026-10-13 |
| ausdata | 172,366 rows, newest 2026-10-21 |
| singstat | 264,324 rows, newest 2026-10-07 |
| idxscape | 1,084,168 rows, newest 2026-10-21 |
| kseistat | 636,750 rows, newest 2026-09-30 |
| sec-edgar (DuckDB file) | 168,250 FRED rows |
| sec-edgar (HTTP) | `missing`: `usfin serve` isn't running on :8660 |
| dbnomics (direct read) | 121 latest rows, newest 2026-10-17 |
| dbnomics (HTTP) | 121 rows |
| jquantster | 55,745 daily bars, newest 2026-07-30 |
| financer | 2,155 holdings rows, newest 2026-09-30 |
| idx-method `stockbiter.db` | 1,118,402 bars, newest 2026-10-12 |
| bps-looker (Postgres) | 12,546,908 observation rows |
| satudatascape | `missing`: no store on this Mac, as expected |

Attaching bisfetcher and ausdata read-only into one shared connection worked. All 144 worldbankscape payloads (`out/*/*.json`) validate against the copied schema.

I found nothing in the siblings that contradicts CLAUDE.md, PLAN.md or the slice notes. One small thing: dbnomics' docs describe DuckDB 1.5.x, and this repo runs DuckDB 2.0.0, which read its store without trouble. There is no `docs/results/S1-contracts.md` in this slice's allowed files, so these numbers are only in this message.
