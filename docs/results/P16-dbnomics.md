# P16-dbnomics — results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

P16-dbnomics is done and committed as `c110f2d` on `slice/P16-dbnomics`, not pushed. The done check exits 0: all 25 tests in `test_dbnomics.py` pass and ruff is clean.

**What it does** (`src/assist/sources/dbnomics.py`, class `DbnomicsSource`)
- It reads from `dbn serve` first: the series list, one series at a time (`?from=` for the start date), and the latest value per series. If the server is down, it reads the store directly, opening it read-only for one query and closing it straight away.
- If the server answers 503 (a refresh is holding the lock), it reports the source as locked rather than reading the file, which would be locked too. A missing or locked store gives `SourceUnavailable`, which shows up in `stale_inputs`.
- The Damodaran ERP and CRP tables and the Shiller table are only read from the store, one query at a time, because the API doesn't serve them.
- Tests check that the server path and the direct read return identical rows, lists and latest values. They use a small fixture DuckDB built from dbnomics' own table definitions and a fake server that answers the same way `serve.py` does. Nothing touches the network or the real store.

**Live run (read-only, 2026-10-23)**
- The server is up (`healthz ok`) and served everything: 121 series (44 OECD, 11 China, 5 Eurozone, 61 valuation) and 44,963 rows, newest dated 2026-10-17. Reading the store directly gave identical rows, list and latest values.
- 21 series are flagged stale, including `idn.bci`, `idn.cci`, `idn.rate.short`, `idn.rate.long`, `chn.bci`, `chn.cci`, most `cn.*` series apart from CPI/PPI/PMI, and `ea.unemp`.
- Sample values:

| Series | Date | Value |
|---|---|---|
| `idn.cli` | 2026-09 | 98.63 |
| `usa.cli` | 2026-09 | 101.00 |
| `chn.cli` | 2026-09 | 97.41 |
| `cn.pmi.mfg` | 2026-09 | 50.1 |
| `ea.hicp.yoy` | 2026-09 | 3.8% |
| `ea.rate.deposit` | 2026-10-17 | 2.5% |
| `idn.cpi.yoy` | 2026-09 | 3.28% |
| `us.erp.implied` | 2026-10 | 3.70% |
| `idn.crp` (Jan 2026 snapshot) | 2026-01 | 2.46% |
| `idn.erp.hurdle` | 2026-10 | 6.16% |
| `us.cape` (provisional) | 2026-10 | 40.71 |
| `us.cape.pct` | 2026-10 | 0.989 |

- The direct reads found 218 monthly ERP rows, 26 Indonesia CRP snapshots and 1,870 Shiller months.

**Where dbnomics differs from CLAUDE.md, PLAN.md or the slice notes** (I followed dbnomics in each case):
- **Dates on rows (`Row.as_of`) are always None.** The store keeps no publication dates (each fetch replaces a series' whole history), and the API doesn't expose when a value was fetched. Use the `stale` and `checked_at` fields from `series()` to judge freshness.
- **Damodaran CRP snapshots need lagging in back-tests.** Each is dated at the start of the update month but published about six weeks later, per dbnomics' `docs/HANDOFF.md`.
- **The server's 503 has two meanings.** It means "locked by a refresh" but also "no store yet"; both are reported as locked.
- **The store path setting has a different name.** dbnomics uses `DBN_DB`; this adapter uses this repo's own `ASSIST_DBNOMICS_DB` from `sources.yaml`, which HANDOFF allows.

There's no `docs/results/P16-dbnomics.md` in this slice's allowed files, so the numbers above are recorded only here.
