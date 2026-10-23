# P26-openkrx — results

Live run 2026-10-23, read-only, against `/Users/tomtomtomtom/Projects/openkrx/data/parquet`
(openkrx HEAD `6fb0925`, 2026-10-23 15:35 +0700).

## What was built

`src/assist/sources/openkrx.py` (`OpenkrxSource`) reads openkrx's vintaged Parquet through an
in-memory DuckDB (`read_parquet(..., hive_partitioning=false, union_by_name=true)`), never
`meta.duckdb` and never Postgres. Per market + key it takes the highest `vintage` (what openkrx's
`{name}_latest` view does); `as_of` = UTC date of `observed_at`. Index level only, for P29:

| Series id | Dataset (market) | Measures |
|---|---|---|
| `TW_INDEX.<index_name>.<measure>` | `tw_index` (TW, MI_INDEX, T3) | close, change, change_pct |
| `KR_INDEX.<family>.<index_name>.<measure>` | `krx_index_daily` (KR, spec §4; K3 not built) | close, change, change_pct, open, high, low, volume, value_krw |
| `TW_ADJ.<code>.<measure>` | `tw_adjusted_daily` (TW, V8) | close_raw, close_adj, close_tr, total_return, tr_index |

Constants: `TAIEX` (發行量加權股價指數), `TW50` (臺灣50指數), `KOSPI` (코스피), `KOSPI200` (코스피 200).
The KR names are KRX's IDX_NM as expected from the API; unverified until openkrx K3 stores them.
`indices()` lists every index close on disk; default `rows()` reads those. No index dataset at all,
or a named series whose dataset has no files → `missing`; an unreadable part → `error`. Parquet is
never locked, so `locked` cannot occur here.

Tests: 12 in `tests/sources/test_openkrx.py` over committed Parquet fixtures
(`tests/fixtures/openkrx/parquet`, rebuilt by `build.py`): restated vintage, null change, writer
temp file ignored, unvintaged `tw_adjusted_daily` (as_of None), partial store, corrupt part, env
override. Full suite 363 passed, 1 skipped; ruff clean.

## Live numbers

- `rows()` → `[]`, stale `openkrx (missing)`; `rows([TAIEX])` → missing "no tw_index parquet";
  `tw_adjusted_daily` likewise. **No index or TW dataset is on disk yet.**
- On disk only KR DART: `dart_filing` 576 rows, `dart_insider` 4,316, `dart_major_holder` 874,
  `dart_fs_line` 106, `dart_event` 7, plus `dart_corp` (SCD2 single file). All observed
  2026-10-23 06:27–09:30 UTC (first live day). 1,574 Parquet files.
- TWSE raw is being captured (`data/raw/twse/2026/10`, 23 MI_INDEX snapshots) but not yet parsed
  into `tw_index` Parquet (no TWSE job writes it yet).
- `assist doctor` shows openkrx present, newest 2026-10-23 (its probe is `dart_filing`).

## Where the sibling differed from our notes

- `docs/HANDOFF.md` does not exist yet (R1-read-contract pending); this follows the R1 notes in
  openkrx's `plan.yaml` and its code: `core/store/dataset.py` (layout, vintage, observed_at),
  `twse/parsers/market/index.py` (tw_index schema), `factors/tw_adjust/adjust.py` (V8 schema).
- `krx_index_daily` exists only in KRX spec §4 (K3 not built); its columns here are the spec's.
- R1 says `tw_adjusted_daily` is "not vintaged"; no writer exists yet, so the adapter reads it
  with or without `vintage`/`observed_at` (without → `as_of` None).
- DART fundamentals (`current_fs_lines` semantics: newest rcept_no per
  corp/year/reprt_code/fs_div; `combined_fs_lines` with `dart_fs_line_bulk`) are NOT read here;
  index level only, as the slice notes say. A later stock-level slice should follow HANDOFF.

## For later slices

- P29 should take `read_rows(OpenkrxSource.from_config(), [TAIEX, KOSPI, ...])` and expect
  `openkrx (missing)` until openkrx's TWSE/KRX jobs write index Parquet.
- When R1 lands, re-check dataset names/columns (esp. `krx_index_daily` family/index names and
  whether TW index names stay Chinese) against `docs/HANDOFF.md`.
- In a worktree, `from_config()` resolves siblings relative to the worktree; set
  `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects` (or `ASSIST_OPENKRX_PARQUET`) for live runs.
