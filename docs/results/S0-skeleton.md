# S0-skeleton — results

PLAN S0: uv project, `assist` CLI, `config/sources.yaml`, socket guard, `assist doctor`.

- Accept: `uv sync && uv run pytest -q tests/test_doctor.py && uv run ruff check .` → 33 passed,
  ruff clean.
- Deps (frozen for the build): duckdb, httpx, jsonschema, pyyaml; dev: pytest, ruff. Python 3.12.
  The CLI uses argparse, so typer is not a dependency. No psycopg: Postgres goes through DuckDB's
  postgres extension.
- `ruff check .` excludes the vendored `slicer.py` (17 findings there, not owned by any slice).
- `tests/fixtures/` is not in this slice's globs, so the doctor tests build their tiny DuckDB,
  SQLite, CSV, JSON and Parquet fixtures in `tmp_path` from the real schemas.

## Live run, 2026-10-23 (`uv run assist doctor`, exit 0)

| Source | Status | Newest | Via | Probes (newest, age / max) |
|---|---|---|---|---|
| sec-edgar | **stale** | 2026-10-12 | duckdb (serve down) | fred VIXCLS 2026-10-12 11d/7d stale; tic 2026-07-01 114d/120d |
| bisfetcher | present | 2026-10-13 | duckdb | WS_EER.D.N.B.ID 2026-10-13 10d/14d; WS_CBPOL.D.ID 2026-10-05 18d/45d |
| worldbankscape | present | 2026-10-23 | files | index.json entries.as_of 2026-10-23 |
| bps-looker | present | 2026-10-09 | postgres | observation.last_update 2026-10-09 14d/45d; trade_flow 2026-08 83d/120d |
| ausdata | present | 2026-10-21 | duckdb | observations 2026-10-21 |
| singstat | present | 2026-10-07 | duckdb | observations 2026-10-07 16d/45d |
| dbnomics | present | 2026-10-17 | http (`dbn serve`) | series_latest 2026-10-17 6d/14d |
| satudatascape | **missing** | — | sqlite | no `data/satudata.db` on this Mac |
| jquantster | **stale** | 2026-10-20 | sqlite | macro usdjpy 2026-10-20; investor_types **empty**; daily_bars 2026-07-30 85d/100d |
| idxscape | present | 2026-10-21 | duckdb | stock_summary 2026-10-21; fx_rate (JISDOR) 2026-10-16 7d/7d; sbn_ownership 2026-10-21; igsyc_point **absent** (optional) |
| kseistat | present | 2026-09-30 | duckdb | holdings 2026-09-30 23d/45d |
| idx-method | **stale** | 2026-10-12 | files | jkse_daily.csv 2026-09-30 23d/7d (frozen); stockbiter.db bars 2026-10-12 11d/7d |
| openkrx | present | 2026-10-23 | files (Parquet) | dart_filing 2026-10-23 |
| financer | present | 2026-10-16 | sqlite | holdings.as_of 2026-09-30 23d/45d; transactions 2026-10-16 |

Summary: 1 missing, 3 stale, 10 present.

## Findings (where the siblings differ from CLAUDE.md / PLAN.md / slice notes)

- **sec-edgar:** `usfin serve` is not running here (8660 refused), so doctor reads
  `data/usfin.duckdb` read-only. The file was last written 2026-10-14, and the newest VIXCLS is
  2026-10-12: the FRED/TIC jobs have not run on this Mac for 9 days.
- **idx-method:** stale beyond the frozen CSVs. `jkse_daily.csv` ends 2026-09-30 as expected, but
  `store/data/stockbiter.db` bars and `data/snapshots/` also stop at 2026-10-12.
- **jquantster:** `investor_types` has 0 rows, so the TSE investor flows that CLAUDE.md lists for
  layer 3 are not loaded on this Mac. `macro_obs` holds Tankan forecasts dated 2026-12-31,
  so the probe reads the `usdjpy` key. The file is in WAL mode with no `-shm` beside it, and
  `mode=ro` cannot open that, so doctor uses `mode=ro&immutable=1` for that case only. That is
  safe because no `-shm` means no writer has it open, and it creates no file next to the store.
- **idxscape:** `schema_migrations` max is 8, so migration 9 (PHEI `igsyc_point`,
  `phei_bond_quote`, `credit_curve_point`) has not been applied here. That matches the notes. The
  probe is marked optional and reports `absent`.
- **openkrx:** `docs/HANDOFF.md` does not exist yet (R1 pending). `data/parquet` holds only
  `dart_*` tables (hive `market=KR/date=…`). The `tw_*` tables that CLAUDE.md names, such as
  `tw_adjusted_daily`, are not there yet.
- **bps-looker:** `.env` has no `DATABASE_URL`, so the default from its `settings.py`
  (`postgresql+psycopg://bps:bps@localhost:5432/bps`) applies. There is no separate read-only
  role (PLAN says "read-only role"). Doctor attaches with DuckDB `READ_ONLY` and strips the
  SQLAlchemy driver. The password is never printed.
- **ausdata:** `observations` carries period-end dates after today (2026-10-31). The probe filters
  `date <= current_date`, and every probe ignores future dates.
- **Env overrides:** every source uses a uniform `ASSIST_*` variable
  (`ASSIST_<SOURCE>_DB|_DIR|_OUT|_PARQUET|_DSN|_URL`, plus `ASSIST_SIBLINGS_ROOT`). The siblings'
  own variables (`USFIN_DB`, `BISFETCHER_DB`, `AUSDATA_DB`, `SGECON_DB`, `DBN_DB`,
  `IDXSCAPE_DB`, `JQUANTS_DB`, `SDS_DB`) are deliberately not read, so a sibling's relative
  default can't leak in.
- **DuckDB postgres extension:** doctor never installs extensions (autoinstall off; it reports
  an error if `postgres` is missing). During schema inspection for this slice, `INSTALL postgres`
  was run once, which downloaded `postgres_scanner` into `~/.duckdb/extensions`.
- **Read-only check:** across two live runs, the `.duckdb` / `.db` / `-wal` files in the siblings
  stayed unchanged. Only idx-method's `stockbiter.db-shm` mtime moved. A WAL reader updates the
  read marks in that file, or the fetcher touched it in the meantime.
