# P82-foreign-returns (PLAN S64): foreign forward returns in IDR, unhedged

Date: 2026-11-09. Branch `phase-l`. Phase L choices 2, 3 and 13 (accepted 2026-11-09).
Heuristic, not investment advice.

## What changed

- **`src/assist/override_history.py`** (plumbing):
  - `ForeignReturnSources`: the local 10Y per market (FRED `DGS10`, jquantster JGB 10Y,
    dbnomics `ea.bund.10y`, ausdata `FCMYGBAG10D`, singstat SGS 10Y), the MAS crosses
    (singstat) and sec-edgar's Alpaca SPY bars. `default()` reads them from P28's
    `default_sources()`, with the 60 s US read timeout.
  - `idr_per(ccy, rows)`: daily IDR per one unit from the MAS crosses (S$ per ccy ÷ S$ per IDR,
    same day; IDR per S$ = 1 / S$ per IDR).
  - `foreign_returns(src, today=, horizon=3)` returns (in IDR unhedged, local) per market and
    asset:
    - **currency:** the move in IDR per local unit over 3 complete month ends; + means the
      local currency gained on the rupiah;
    - **bonds:** `bond_returns` (carry − duration × Δyield, the IDN rule's duration) on the
      month-end local 10Y, times the IDR-per-local move: (1 + r) × (1 + fx) − 1. The
      euro-area 10Y is a monthly average dated the 1st, so it is lagged a month as the IDN
      proxy (`bond_forward`). Its FX leg stays month end to month end, a half-month timing
      mismatch for EMU only;
    - **stocks (USA only, choice 13):** the Alpaca SPY price index (close × split factor,
      dividends not included, as the paper track) times the IDR-per-USD move. No store has
      a JP, euro-area, AU or SG index price, so those stocks are not gated.
  - Never across a gap or from a month still running on `today`. The local returns are
    returned as a diagnostic only (P83).
  - `foreign_build(sources, day)`: S63's replay with the IDR returns joined (`with_returns`).
  - `live_build(subject, day)` now serves the five P28 markets. One replay builds all five and
    is kept for that day.
- All foreign FX legs read the MAS crosses (choice 2), not the P65 splice: IDR per USD here is
  MAS on every date, including after JISDOR's start.

## Tests (first, red → green)

5 new tests in `tests/test_override_history.py` (38 in all):
- the currency return is the move in IDR per local unit: IDR per USD 16,000 → 16,800 gives
  +5%; JPY and SGD, all quoted in S$, move with it;
- bonds in IDR = (1 + local carry) × the FX move. The euro-area monthly average is lagged a
  month (last call 2019-08 against USA's 2019-09);
- only USA stocks have a return: SPY +10% in USD and USD +5% against IDR give +15.5%;
- no return across a missing month or from a running month;
- joined histories carry stocks, bonds and currency for USA, and no stocks for JPN.

Full suite: 1901 passed, 1 skipped. `ruff check .` is clean.

## Live (2026-11-09, real stores read-only; 65 s with the replay)

Complete months (S63) with a 3-month IDR return:

| Market | Stocks | Bonds | Currency |
|---|---|---|---|
| USA | 2016-01 → 2026-07 (127, SPY from 2016) | 2005-04 → 2026-07 (256) | 2005-04 → 2026-07 (256) |
| JPN | not gated (no index price) | 2005-04 → 2026-07 (256) | 2005-04 → 2026-07 (256) |
| EMU | not gated | 2005-04 → 2026-05 (254; the lagged average) | 2005-04 → 2026-07 (256) |
| AUS | not gated | 2013-12 → 2026-07 (152) | 2013-12 → 2026-07 (152) |
| SGP | not gated | 2006-04 → 2026-07 (244) | 2006-04 → 2026-07 (244) |

- At stride 3 that is about 85 windows per side for USA, JPN and EMU bonds and currency, 81 for
  SGP, 50 for AUS and 42 for USA stocks. Every gated side should reach `MIN_N` 10 unless a
  shift sign is rare.
- AUS bonds returns start 2013-05 (ausdata's AGS 10Y). AUS's window starts 2013-12 anyway (its
  curve component).
