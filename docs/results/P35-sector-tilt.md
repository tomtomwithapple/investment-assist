# P35-sector-tilt: PLAN S16, IDN macro sector tilt

The code is `src/assist/candidates/tilt.py` and the table is `config/sector_tilt.yaml`. The tests
are in `tests/test_tilt.py`: 24 tests on in-memory data, plus `tests/fixtures/tilt/sectors.json`.
That fixture holds two real names per IDX-IC sector from idx-method's `data/sectors.json` (read
2026-10-27).

## What it does

- **Table.** The 11 IDX-IC sectors are named as in idx-method's `data/sectors.json`, which
  matches `factor_universe.sector`. Each has signed, hand-set sensitivities to 11 drivers. The
  table's sha256 is the tilt's `fingerprint`. The module is also covered by the journal's
  `RULE_GLOBS`.
- **Drivers.** Each driver is a direction: clip((reading − center) / scale, −1, +1). The center
  and scale are in the yaml. Every driver is read as of the date it is used. A row counts once
  its publication lag has passed. A newest row older than its max age is still used, but named
  stale.

  | Driver | Reading | + means |
  |---|---|---|
  | coal, nickel, palm_oil | worldbankscape `COAL_AUS`, `NICKEL`, `PALM_OIL` commodity score (live only) | score above 50 |
  | china | dbnomics `cn.pmi.mfg` level | PMI above 50 |
  | bi_rate | bisfetcher `WS_CBPOL.M.ID`, change over 6 months | hiking |
  | real_yield | BI rate − CPI y/y | real policy rate above 2% |
  | credit_gap | bisfetcher `WS_CREDIT_GAP.Q.ID.P.A.C` | credit above trend |
  | usd_idr | JISDOR % change over 3 months, else −(IDR REER `WS_EER.M.R.B.ID` % change) | IDR weaker |
  | inflation | CPI y/y change over 3 months (bps-looker `BPS_CPI_YOY`, else dbnomics `idn.cpi.yoy`) | rising |
  | consumer | dbnomics `idn.cci` | above the long-term average of 100 |
  | regime | P8 layer 0: risk_on +1, neutral 0, risk_off −1 | risk-on |

- **Tilt.** Tilt = clip(Σ sensitivity × direction, −1, +1) per sector, returned as
  `SectorTilt(sector, tilt, drivers, stale)`. A missing driver adds 0 and is listed in that
  sector's `stale`. An unknown regime counts as missing, not as neutral.
- **Mappings.**
  - The required-margin shift is −2 pt × tilt.
  - The sector cap is 5 + 2 × tilt, rounded half away from 0 and kept in 3..7. So ±0.25 gives
    6 and 4.
  - `applied(t, passed=…)` returns (0, 5) unless the verdict passed. The run output carries both
    the applied values and the raw ones.
- **Replay.**
  - It runs at every quarter end in `factor_series` that has a later one.
  - Tilts are the ones known that day. Commodities are excluded, as explained below.
  - A sector's return is Σ mktcap at the next quarter end ÷ Σ mktcap now − 1. The sum runs over
    the sector's names with a bar within 10 days before both dates, and a sector needs at least
    5 names. This return is mktcap-weighted, and splits in the unadjusted prices do not affect it.
  - Every quarter whose top-3 and bottom-3 tilts differ by at least 0.05 adds two observations:
    the top 3's mean excess return as "on" and the bottom 3's as "off". The excess is over the
    mean of all sectors.
  - These go into `assist.eval.placebo.evaluate`, which tests them against shuffled returns: a
    placebo plus a procedure control.

## Live run (2026-10-27, read-only)

**Verdict: failed**: t-stat −1.11, below 2.0.

| | |
|---|---|
| Quarters scored | 39 (2016-12-31 … 2026-06-30 → next quarter) |
| Observations | 39 on, 39 off |
| Top-3 mean excess / quarter | −0.86% |
| Bottom-3 mean excess / quarter | +4.51% |
| Spread (top − bottom) | −5.36% a quarter, spread t −0.88 |
| Placebo p | 0.841 |
| Control mean t | −0.35 |
| Regime known at | 40 of 40 quarter ends (21 risk_on, 16 neutral, 3 risk_off) |
| Fingerprint | `f171faf51990f470588fa275b41dad1ce6b62a11eff88dd187098070f962bb40` |

The sign is wrong as well as weak: the sectors the table favoured did worse over the next
quarter. Because the verdict failed, **S20 applies no margin shift and keeps the default cap of
5** for every sector. The tilts below are journalled and shown only.

### Today's drivers

| Driver | Direction | Reading |
|---|---|---|
| coal | +0.39 | worldbankscape COAL_AUS score 59.8 |
| nickel | −0.31 | worldbankscape NICKEL score 42.3 |
| palm_oil | +0.17 | worldbankscape PALM_OIL score 54.3 |
| china | +0.05 | China mfg PMI 50.1 (2026-09) |
| bi_rate | +1.00 | BI rate 5.75% (2026-09), +1.00pt over 6 months |
| real_yield | +0.24 | real policy rate 2.47% (BI 5.75% − CPI 3.28%) |
| credit_gap | −0.27 | credit-to-GDP gap −1.3pt (2026Q1) |
| usd_idr | +0.27 | USD/IDR (JISDOR) 18,116 on 2026-10-26, +0.8% over 3 months |
| inflation | −0.06 | CPI 3.28% y/y (2026-09, bps-looker), −0.06pt over 3 months |
| consumer | +0.54 | IDN consumer confidence 100.8 (2026-08) |
| regime | 0.00 | neutral |

### Today's tilts

The "raw" columns show what S20 would apply if the verdict passed. Applied today: shift 0, cap 5
for every sector.

| Sector | Tilt | Raw margin shift (pt) | Raw cap | Largest driver |
|---|---|---|---|---|
| Energi | +0.26 | −0.52 | 6 | coal +0.39 × +0.50 = +0.20 |
| Barang Konsumen Primer | +0.14 | −0.27 | 5 | consumer +0.54 × +0.20 = +0.11 |
| Transportasi & Logistik | +0.03 | −0.07 | 5 | consumer +0.54 × +0.20 = +0.11 |
| Kesehatan | −0.02 | +0.04 | 5 | usd_idr +0.27 × −0.30 = −0.08 |
| Barang Konsumen Non-Primer | −0.02 | +0.05 | 5 | consumer +0.54 × +0.40 = +0.22 |
| Barang Baku | −0.05 | +0.11 | 5 | nickel −0.31 × +0.35 = −0.11 |
| Perindustrian | −0.08 | +0.16 | 5 | bi_rate +1.00 × −0.20 = −0.20 |
| Teknologi | −0.27 | +0.54 | 4 | bi_rate +1.00 × −0.20 = −0.20 |
| Keuangan | −0.29 | +0.59 | 4 | bi_rate +1.00 × −0.30 = −0.30 |
| Properti & Real Estat | −0.36 | +0.72 | 4 | bi_rate +1.00 × −0.40 = −0.40 |
| Infrastruktur | −0.37 | +0.75 | 4 | bi_rate +1.00 × −0.30 = −0.30 |

Live stale inputs: none. The run took about 1 m 45 s; most of it is P8's regime read at 41
dates from sec-edgar.

## Where the siblings differ from the slice notes

- **worldbankscape keeps no commodity score history.** Its `out/` contract holds today's payload
  only. Its `data/wbs.duckdb` has the Pink Sheet, but it is not part of the read contract. So the
  coal, nickel and palm-oil drivers are **live only**. The replay runs without them and says so
  in `replay_basis`. Energi and Barang Baku therefore rest on China, USD/IDR and the regime in
  the replay. If worldbankscape published a per-month commodity score history (or a Pink Sheet
  export), the commodity legs could be replayed.
- **Plantations (CPO) are in Barang Konsumen Primer** under IDX-IC, not in Barang Baku. That is
  where the palm_oil sensitivity sits.
- **bps-looker CPI starts in 2024-01**, so the replay before then uses dbnomics `idn.cpi.yoy`
  (from 2010).
- **JISDOR starts in 2021-10** in idxscape. Before then, `usd_idr` falls back to the monthly IDR
  REER from bisfetcher, inverted.
- **dbnomics marks `idn.cci` stale** (last 2026-08). It is still inside this module's 120-day
  max age.
- **Sector membership is today's** (`factor_universe`). There is no membership history. The 46
  names with a blank sector are left out.
- PLAN S16 says "sector-month tilts". The slice notes and this module use quarter ends, to match
  the 3-month forward return.
