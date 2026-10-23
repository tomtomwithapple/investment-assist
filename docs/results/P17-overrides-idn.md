# P17-overrides-idn — PLAN S7: IDN overrides (layer 2)

`src/assist/layers/overrides.py`: `idn_overrides(as_of, bps=, bisfetcher=, dbnomics=, satudatascape=)`
→ `IdnOverrides`. It holds one `Override` per asset (stocks, bonds, currency), the `components` behind
them, the uncapped `raw` sums, `inputs` (the latest known `cpi_yoy`, `gdp_yoy`, `cli`, `trade_balance`
and `bi_rate`, for P31's real yield), `stale_inputs` and `sources`. `apply(score, override)` shifts a
layer-1 score and keeps it in 0..100. The layer reads through the P11, P12 and P16 adapters and does
no I/O of its own.

| Component | Series | Change | Dead band | stocks / bonds / currency points per +1 |
|---|---|---|---|---|
| `growth` | bps-looker `BPS_GDP_YOY` | latest y/y − mean of the 4 quarters before | ±0.25pt | +3 / −1 / +1 |
| `cli` | dbnomics `idn.cli` (OECD) | 3 months | ±0.2 | +3 / −1 / +1 |
| `inflation` | bps-looker `BPS_CPI_YOY`, else dbnomics `idn.cpi.yoy` | 3 months; detail sets the level against BI's 1.5–3.5% target | ±0.3pt | −1 / −3 / −1 |
| `trade` | bps-looker `BPS_TRADE_BALANCE_USD_MN` | last 3 months' sum − the 3 before | ±US$ 1.5bn | +1 / +1 / +3 |
| `bi_rate` | bisfetcher `WS_CBPOL.M.ID` | 6 months (+1 = hiking) | ±0.125pt | −2 / −3 / +1 |

Each asset's shift is Σ weight × direction, clamped to ±10 (`MAX_OVERRIDE`). The weights and
bands are hand-set. They must not move a stance until a rule using them beats its placebo.

Point in time: a row counts as known on `as_of` if it was recorded by then, or if its date is
older than the series' publication lag (CPI 35 days, trade 50, GDP 130, BI rate 35, CLI and
dbnomics CPI 45). A missing or locked store, a series too short for its window, and a newest
point older than `MAX_AGE` are each named in `stale_inputs`, never raised.

Tests: `uv run pytest -q tests/layers/test_overrides_idn.py` gives 21 passed and ruff is clean. The
full suite gives 352 passed.

## Live run (read-only, 2026-10-23)

| as_of | growth | cli | inflation | trade | bi_rate | stocks / bonds / currency | stale |
|---|---|---|---|---|---|---|---|
| 2026-10-23 | GDP 5.29% (Q2) vs 5.29% avg **0** | 98.63, −0.64 since Jun **−1** | CPI 3.28% Sep, −0.06 (inside target) **0** | US$ 3.22bn vs 1.80bn (+1.42bn) **0** | 5.75%, +1.00 since Mar **+1** | **−5 / −2 / 0** | satudatascape (missing) |
| 2026-09-25 | same **0** | 98.76 Aug, −0.98 **−1** | CPI 3.19% Aug, +0.11 **0** | same **0** | 5.75% Aug, +1.00 **+1** | −5 / −2 / 0 | satudatascape (missing) |
| 2025-06-30 (backtest) | 4.87% (Q1) vs 5.03% **0** | 100.32, +0.04 **0** | CPI 1.60% May, +1.69 **+1** | US$ 8.80bn vs 8.79bn **0** | 5.50%, −0.50 **−1** | +1 / 0 / −2 | satudatascape (missing) |

No raw sum reached the ±10 cap. bps-looker (Postgres via DuckDB), bisfetcher and dbnomics were all
present and unlocked.

## Findings (siblings vs the plan)

- **BI rate comes from bisfetcher, as the slice notes say.** `WS_CBPOL.M.ID` runs to 2026-09
  (5.75%). BI hiked from 4.75% to 5.75% in May–Jun 2026. PLAN's fallback to worldbankscape's BIS
  series is not needed and is not wired.
- **bps-looker's `Row.as_of` is the variable's `last_update`, not a release date.** Every CPI
  and trade month from 2024 on carries 2026-10-01, and every GDP quarter 2026-08-05. dbnomics
  rows have no `as_of` at all. The layer therefore uses publication lags (as P18 does) so that
  backtests neither leak nor empty out.
- **BPS CPI (var 2263, 2022=100) starts in 2024.** For older backtests, `idn.cpi.yoy` from
  dbnomics is the fallback. It is used only when bps-looker has no CPI, and that case is named in
  `stale_inputs`.
- **satudatascape is still absent on this Mac** (`data/satudata.db`). It also has no ready macro
  series, only a catalogue of extracted tables. The layer probes it so that its absence shows as
  `satudatascape (missing)`, but it feeds no component yet.
- No sibling changed its tables or docs after the adapters were written. The latest commits are
  bps-looker 2026-10-19 (launchd), bisfetcher 2026-10-19 (setup.sh), and satudatascape and
  dbnomics 2026-10-14.
