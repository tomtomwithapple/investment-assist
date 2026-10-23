# P32-phei — live results

**What `src/assist/sources/idxscape_phei.py` reads (read-only, idxscape J4 / migration 9):**
- **`IGSYC.<tenor>`** (`igsyc_series(10)` = `IGSYC_10Y` = `"IGSYC.10"`, `"IGSYC.0.1"`): `igsyc_point.yield_pct` per day at one tenor. The default `rows()` returns every curve point up to 30Y. Points past 30Y are extrapolated, so they come back only when asked for by id (`IGSYC.40`) or with `curve(max_tenor=None)`.
- **`PHEI_BOND.<grp>.<series_code>`**: a bond's PHEI fair yield, with `grp` one of `SBN_BENCHMARK|SBSN_BENCHMARK|RETAIL`. You get it only by asking for its id. `bond_quotes(as_of=None, grp=None)` returns the full quote (ttm, yield, price, coupon, flag).
- **`PHEI_CREDIT.<rating>.<tenor>`**: `credit_curve_point`, with rating one of `IGS|AAA|AA|A|BBB`. You get it by asking for its id or through `credit_curve(as_of=None)`.
- **Helpers:**
  - `curve(as_of=None, max_tenor=30, on_or_before=False)` returns `CurvePoint`s. With no date it uses the newest day. `on_or_before` covers weekends and holidays.
  - `curve_days()` lists the curve days, newest first, each with its flag.
  - `yesterday_column_days()` lists the days filled from a later page's Yesterday column.
  - `slopes(start, end, short=2, long=10)` returns 10Y − 2Y per day, built the same way as idxscape J8's `igsyc_slopes`.
- **Units and dates:** values are percent as printed (7.1677 means 7.1677%) and are returned as floats. `as_of` is the WIB date of `fetched_at` (the snapshot's fetch). `from_yesterday_column` is kept as a flag on `CurvePoint`, `CurveSlope` and `BondQuote`. A bond's `ttm_y` is None when its row was gap-filled.
- **Source name:** the adapter reports itself as `idxscape_phei`, so a stale entry reads `idxscape_phei (missing)`. It reads the store at config entry `idxscape` (`ASSIST_IDXSCAPE_DB`). It sets `PheiSource.local_only = True`.

**Live run (2026-10-23, read-only):**
- **No PHEI tables on this Mac:** `../idxscape/data/idxscape.duckdb` was last written 2026-10-22 20:32 and is at **migration 8** (`schema_migrations` max = 8). It has no `igsyc_point`, `phei_bond_quote` or `credit_curve_point`.
- **What the adapter returns:** `read_rows(PheiSource.from_config())` returns `([], ["idxscape_phei (missing)"])`. `curve()` raises `SourceUnavailable(missing: no igsyc_point table (idxscape migration 9))`.
- **The code is ahead of the store:** idxscape's checkout already holds J4 and J8 (HEAD e7862c8), so migration 9 will most likely be applied the next time its own `load phei` or nightly `phei` step runs here. I did not run it, because siblings are read-only.
- **No live numbers yet:** the adapter is verified only against the fixture, which copies the migration 9 DDL verbatim from `../idxscape/src/idxscape/db.py`. Re-run the live check once the tables exist.

**Notes for later slices (P22, P31, P38 benchmark):**
- **Read tenors from the curve:** take the 10Y and 2Y points from the curve (`IGSYC_10Y`, `IGSYC_2Y`, `slopes()`), never from a bond. idxscape says benchmark membership rotates.
- **Keep raw PHEI values on this Mac:** PHEI is for the owner's local use only. Raw curve points and quotes must not go into Telegram or anything else sent off this Mac. Send derived numbers only (for example the real yield, the slope or a percentile).
- **Fallback while the tables are missing:** treat `idxscape_phei (missing)` as a stale input and fall back to dbnomics' IDN long-term rate, as P22's notes say.
- **Gap-filled days:** days with `from_yesterday_column` came from a later page and can be revised when that day's own page loads. Flag them if a rule uses them.
- **TIMESTAMPTZ needs pytz:** fetching a raw TIMESTAMPTZ column from DuckDB into Python needs `pytz`, which is not installed. The adapter avoids this by casting `fetched_at` to a date in SQL (WIB). Any new query should do the same.

**Where I followed idxscape rather than our notes:** nothing conflicted. `docs/storage.md`, `db.py` migration 9 and `queries.py` (J8) all match the slice notes.

**Tests:** `tests/sources/test_idxscape_phei.py` has 20 tests covering:
- tenor rows and the WIB vintage
- the 30Y default
- 40Y returned only when asked for by id
- the date window and unknown ids
- bond and credit rows
- `curve`, `curve_days` and `slopes`
- bond quotes, including an invalid grp
- the credit curve and empty tables
- a store at migration 8 and a single table missing
- a missing file, a locked store and the read-only connection
- `from_config`

The full suite passes (371 passed, 1 skipped) and `ruff` is clean.
