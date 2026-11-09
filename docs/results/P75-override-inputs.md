# P75-override-inputs (PLAN S57): point-in-time input history of the IDN overrides

Date: 2026-11-09. Branch `phase-l`. Heuristic, not investment advice.

## What changed

- **`src/assist/override_history.py`** (new; plumbing outside the model fingerprint, as
  `assist.history`). It calls P17's `idn_overrides` unchanged on every month end and records:
  - per asset, the capped shift and the uncapped sum;
  - per component (`growth`, `cli`, `inflation`, `trade`, `bi_rate`), the measured change, its
    direction under P17's bands, the newest point used and its series and store;
  - the components that could not be computed, as `name: reason`, and the stale inputs.
- Point in time is P17's own rule (`overrides.LAG`). Every real store records its history on
  one recent date (bps-looker its last update, bisfetcher its fetch, dbnomics nothing), so in
  history the publication lags alone decide.
- **`Preloaded`** wraps a store. It reads the store once (the series P17 asks for, up to the
  last month end) and slices it in memory as the adapters filter (ids, inclusive dates). An
  unavailable store raises the same `SourceUnavailable` on every call, so each month names it
  stale as a live read would. 262 month ends take 5.5 s instead of one read per month.
- `OverrideHistory.coverage()` gives each component's first and last month, months computed,
  series used and holes. `complete_from()` is the first month with every component.
  `summary()` counts shift signs on complete months only. It is descriptive: no forward
  return, no verdict.
- `python -m assist.override_history [--today D] [--start D] [--rows] [--json F]` replays the
  real stores.
- Nothing here depends on an open phase L choice. No forward returns, no gate, no threshold, and
  no change to P17 or any rule module, so the model and rule fingerprints are unchanged.

## Tests (first, on fixtures)

`tests/test_override_history.py` (18 tests) uses in-memory stores over 2014-01 → 2019-12. They
are recorded as the real stores record them: bps-looker stamps every row 2026-10-01, bisfetcher
2026-10-19, and dbnomics has no vintage. bps-looker CPI starts 2018-01, as the real one starts
2024-01.

- **Poison:** at three cut-offs, every value not yet known (dated after it, or inside its
  publication lag) is made absurd. No row up to the cut-off changes, and later rows do.
- **The poison test bites:** with the lags set to zero, early rows move.
- **Replay equals the layer:** shifts, sums, component values and stale inputs match
  `idn_overrides` called directly on the raw stores.
- **One read per store:** each store, satudatascape included, is read once for the whole
  replay.
- **Preloaded:** it filters like the store, never serves past its end, and re-raises an
  unavailable store.
- **Components and lags:** the newest point used respects each lag (CLI May known on 06-30;
  GDP Q1 dated 01-01 known after 130 days). Inflation switches from dbnomics to bps-looker once
  bps-looker is known. Trade is missing until 6 months are known.
- **The CPI splice hole:** a bps-looker CPI known for under 3 months leaves inflation missing,
  with its reason. P17 falls back to dbnomics only when bps-looker has no CPI at all.
- **The rest:** coverage, complete_from and the holes; the summary counts complete months only;
  a JSON round trip.

Full suite: 1849 passed, 1 skipped (worldbankscape checkout absent in the worktree). `ruff check .`
is clean.

## Live run (2026-11-09, real stores read-only, `ASSIST_SIBLINGS_ROOT=/Users/tommy/Projects`)

262 month ends from 2005-01 to 2026-10, in 5.5 s.

| Component | Series | First month computed | Holes |
|---|---|---|---|
| growth | bps-looker `BPS_GDP_YOY` (2011-Q1 → 2026-Q2) | 2012-05 | none |
| cli | dbnomics `idn.cli` (1994-01 → 2026-09) | 2005-01 | none |
| inflation | dbnomics `idn.cpi.yoy` to 2024-01, bps-looker `BPS_CPI_YOY` from 2024-05 | 2005-01 | **2024-02 → 04** |
| trade | bps-looker `BPS_TRADE_BALANCE_USD_MN` (2017-01 → 2026-09) | **2017-07** | none |
| bi_rate | bisfetcher `WS_CBPOL.M.ID` (2005-07 → 2026-09) | 2006-02 | none |

- **Every component** is computed on 109 month ends: 2017-07 → 2026-10, except 2024-02 → 04.
  Trade is the binding start.
- **The CPI hole:** bps-looker's CPI y/y (2022=100, var 2263) starts 2024-01. From 2024-02 P17
  sees a bps-looker series that is too short for its 3-month change and does not fall back to
  dbnomics. Live P17 had the same gap then. The fix is phase L choice 9; nothing here changes it.
- **Shift signs on the 109 complete months** (descriptive, no returns):

  | Asset | Up | Zero | Down |
  |---|---|---|---|
  | Stocks | 66 | 8 | 35 |
  | Bonds | 48 | 7 | 54 |
  | Currency | 43 | 23 | 43 |

  At stride 3, each side has more than `MIN_N` 10 windows, unlike the phase K rules.
- **Size of the shifts:** |shift| reaches 9 once (stocks, 2021-05), so the ±10 cap never binds
  on the complete months.
- **Trade direction:** trade reads 0 (inside its US$1.5bn band) on every month before 2021-02.
- **2026-10-31:** stocks −4, bonds −1, currency +3. Components: growth 0, cli −1, inflation 0,
  trade +1, bi_rate +1. The live run of 11-09 differs (stocks −5, bonds −4, currency +2)
  because bps-looker's rows recorded 2026-11-02 count from that day.

### Vintages and lags (what the replay cannot fix)

- **bps-looker** keeps one vintage per variable: GDP rows all carry 2026-08-05, trade and CPI
  2026-11-02. BPS revisions are therefore read at today's values.
- **dbnomics** keeps no vintage. The OECD CLI is revised most at its end, so this history reads
  a smoother, later CLI than was known on each date. That is phase L choice 10 and a dbnomics
  ask under *Open data gaps*.
- **bisfetcher** policy rates are not revised.
- **The lags are P17's** (CPI 35 d, dbnomics CPI 45 d, trade 50 d, GDP 130 d, BI rate 35 d,
  CLI 45 d). They were set on 2026-10-23 from the release calendars and are not changed here.

### Also found (for the plan, not changed here)

- **Foreign `fx` is n/a live for USA and JPN.** Both read idxscape JISDOR, which starts
  2026-10-22 on this Mac, so the 3-month change has no base ("idxscape JISDOR (history from
  2026-10-22)" in their stale inputs, 2026-11-09). EMU, AUS and SGP compute theirs. This is
  phase L choice 12.
- **Foreign return and input ranges** (for S63–S64):
  - The MAS crosses for USD, JPY, EUR, AUD and IDR all run 2005-01-03 → 2026-11-06.
  - ausdata AUD/IDR (`FXRIR`) starts 2023-01, and AU monthly CPI starts 2025-04.
  - FRED `GDPC1` rows carry vintage dates (realtime start), and `fred_as_of` serves vintages.
  - No store has a JP, euro-area, AU or SG equity index price.
