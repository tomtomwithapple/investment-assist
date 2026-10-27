# P37-garp: PLAN S19, undervalued growth screen (GARP), IDN

The code is `src/assist/candidates/garp.py`. The tests are in `tests/test_garp.py`: 25 tests on
in-memory data, plus `tests/fixtures/garp/consensus.json`. That fixture holds two real entries of
idx-method's `data/consensus.json` (AADI and ACES, read 2026-10-27) and two made-up edge cases:
a name with no EPS forecast and a name with a loss year.

## What it does

### Reverse DCF

- `implied_growth` finds the constant 10-year earnings growth at which the present value equals
  today's mktcap. The discount rate is the P34 IDN hurdle.
- Each year pays out earnings × payout. Payout = trailing 12-month dividends (split-adjusted by
  P36's `load`) / `ni_ttm`, clamped to [0, 1].
- After year 10 there is a terminal value: year-11 earnings / (hurdle − 8%). 8% is IDN nominal
  GDP growth, the same value as P36's `g_cap_pt`.
- It is solved by bisection between −50% and +100%. An answer outside that range is clamped to
  the bound.
- No reverse DCF is run when the hurdle is less than 1 pt above GDP growth.

### Realised growth

- Realised growth is the 5-year CAGR of `ni_ttm` and of `cfo_ttm`, both from P33. Each needs
  positive values at both ends. Realised growth = the lower of the two.
- For banks it is the `ni_ttm` CAGR alone, because a bank's CFO swings with deposits (as in P36).

### Consensus (live only)

- `consensus_growth` reads `consensus.json` (94 names have an EPS forecast). Growth = the EPS
  CAGR from the last actual year to the furthest estimate.
- Forward PE = consensus price / next-year EPS. PEG = forward PE / growth (pt). PEG is reported
  as a cross-check and does not gate.

### Gap, expected return and margin

- **Gap** = min(realised, consensus) − implied, in pt. Where a name has no consensus, the gap
  uses realised growth alone. The live ranking is by gap.
- **Realised gap** = realised − implied. It is reported alongside.
- **Expected return** = the IRR at the gap's growth, capped at 25%. **Margin** = expected − hurdle
  (`hurdle.margin`). Both are there for S20.

### Quality gates

Every failed gate is kept per name. The rejects count only the first one.

1. Positive `ni_ttm`.
2. Realised growth is known.
3. ROE (`ni_ttm` / `equity`) or `roce` is no more than 2 pt below its level 3 years earlier.
4. `cfo_ttm` / `ni_ttm` ≥ 0.8. Banks are exempt.
5. Equity dilution under 5% a year, using `mktcap / price` 3 years apart as the share-count
   proxy.

Before these, live only: `screens.passes_gates` and `passes_quality` (`BANK_FLOOR` for names
with a `car`).

### Candidates

A name is a candidate only when all of these hold:

- the replay verdict passed;
- the hurdle is known;
- the gap is at least 2 pt (`min_gap_pt`, "clearly below").

`screens.select` then takes the top 20, at most 5 per sector.

### Replay

- It runs every quarter end with a later one, and uses **realised growth only** (the realised
  gap). The consensus leg is journalled live and never ranks in a replayed verdict.
- Point-in-time gates: price ≥ 100 and mktcap ≥ IDR 1T.
- The 3-month forward return is price plus dividends gone ex in the quarter.
- Quarters with fewer than 30 names are not scored.
- The top and bottom quintile go to `placebo.evaluate`, as in P36.
- `CONFIG` is returned as `fingerprint`. The module sits under `candidates/`, so the journal hash
  covers it.

## Live run (read-only, 2026-10-27; screen date 2026-10-09)

**Verdict: failed (t 1.30, below the 2.0 bar).**

- p = 0.085 (1,000 shuffles). Control t −0.03 (20 reruns).
- **17 quarters scored**, 2022-06-30 … 2026-06-30 (90–113 names per quarter).
- Top quintile mean excess 3-month return: **+0.97%**. Bottom quintile: **−0.99%**.
- Mean spread: **1.96 pt** (t 1.17 on the spreads alone).
- The sign is right, but the replay is too short to clear the bar. **No candidate is named.**

**IDN hurdle: 13.74%** (SBN 10Y from IGSYC + US ERP 4.09% + IDN CRP 2.46%). Nothing was stale.

**Pool: 30 names** passed every gate.

- 21 of them have a gap of at least 2 pt; they would be candidates if the verdict had passed.
- 25 have a consensus.

Rejects (first rule failed):

| Rule | Names |
|---|---:|
| liquidity | 341 |
| free float | 258 |
| flagged board | 243 |
| extreme volatility | 22 |
| realised growth | 19 |
| price floor | 17 |
| F-score | 15 |
| Altman Z | 11 |
| returns trend | 10 |
| accruals | 6 |
| negative CFO | 2 |
| interest cover | 2 |
| bank ROE | 1 |

Top 10 by gap. Growth, gaps, expected return and margin are in pt; ROE in %.

| # | Name | Sector | Gap | Realised gap | Implied g | NI CAGR | CFO CAGR | Consensus g | Fwd PE | PEG | Expected | Margin | ROE now / 3y ago | CFO/NI | Payout |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| 1 | NICL | Barang Baku | +30.5 | +30.5 | 9.1 | 46.9 | 39.5 | n/a | n/a | n/a | 21.0 | +7.3 | 30.2 / 32.0 | 1.12 | 24% |
| 2 | ELSA | Energi | +17.8 | +24.4 | -2.1 | 29.4 | 22.3 | 15.8 | 5.4 | 0.34 | 24.3 | +10.5 | 13.1 / 9.9 | 3.40 | 45% |
| 3 | RAJA | Energi | +17.6 | +17.6 | 15.9 | 63.3 | 33.5 | n/a | n/a | n/a | 17.5 | +3.8 | 11.0 / 8.9 | 1.70 | 57% |
| 4 | BBTN | Keuangan (bank) | +12.5 | +18.5 | -2.6 | 15.9 | n/a (bank) | 9.9 | 3.3 | 0.33 | 19.6 | +5.9 | 10.1 / 11.1 | n/a (bank) | 0% |
| 5 | JPFA | Barang Konsumen Primer | +11.6 | +11.6 | -4.5 | 29.1 | 7.1 | 11.2 | 4.5 | 0.40 | 20.1 | +6.3 | 23.3 / 4.2 | 1.23 | 32% |
| 6 | DSNG | Barang Konsumen Primer | +11.6 | +19.3 | 2.7 | 30.9 | 22.0 | 14.3 | 6.4 | 0.44 | 19.3 | +5.5 | 15.8 / 14.5 | 1.45 | 26% |
| 7 | BBNI | Keuangan (bank) | +11.3 | +74.4 | -4.0 | 70.4 | n/a (bank) | 7.3 | 6.1 | 0.84 | 20.5 | +6.8 | 12.2 / 13.5 | n/a (bank) | 64% |
| 8 | BRMS | Barang Baku | +10.4 | +28.4 | 33.7 | 62.1 | 84.0 | 44.1 | 94.2 | 2.14 | 11.6 | -2.2 | 4.9 / 1.5 | 1.35 | 0% |
| 9 | AUTO | Barang Konsumen Non-Primer | +10.4 | +10.7 | -0.9 | 113.1 | 9.8 | 9.4 | 6.7 | 0.71 | 19.3 | +5.5 | 12.9 / 11.3 | 0.88 | 49% |
| 10 | BBRI | Keuangan (bank) | +9.1 | +30.5 | -2.9 | 27.6 | n/a (bank) | 6.2 | 7.4 | 1.20 | 19.2 | +5.5 | 17.0 / 19.2 | n/a (bank) | 90% |

Notes on the ranking:

- **BRMS** has a positive gap but a negative margin. The expected return caps growth at 25%, and
  its implied 33.7% is above that cap. S20 ranks by margin, so it would fall out there.
- **NICL** and **RAJA** have no consensus, so their gap is realised-only (flagged in `risks`).
- Banks' 5-year NI CAGRs (BBNI 70%) start from the 2021 provisioning trough. The consensus leg
  (min) is what pulls their live gap back down.

**Sensitivity (context only, not adopted):** with a 3-year CAGR, the replay starts in 2020-06 and
scores 25 quarters. It gives t 1.79 and p 0.033: still below the t 2.0 bar.

## Findings and where the sources differ from the notes

- **No consensus history** (as PLAN S19 says). `consensus.json` holds only the last actual year
  and 2 estimate years (2025, 2026e, 2027e for all 98 names). So "consensus growth" is a 2-year
  EPS CAGR, not a 10-year view. Judging this leg needs idx-method's V4 (monthly dated snapshots).
- **The replay is short.** `factor_series` quarterlies start 2016-12. A 5-year CAGR plus the
  120-day lag puts the first quarter that can be scored at 2022-06-30, which leaves 17 quarters.
  The verdict can only firm up as quarters accrue (or if V3 shortens the lag).
- **The replay hurdle is one number.** P34 is not replayed per quarter, so every quarter uses
  today's 13.74%. Within a quarter every name faces the same hurdle, so only the level of the
  implied growth shifts, not much the order.
- **The share-count proxy works.** `mktcap / price` moves by more than 1% over 3 years for 139 of
  925 names (GIAA, WIKA and PYFA are up 4–4.5×, after rights issues). None of the 30 names in the
  pool dilutes, because earlier gates already drop the issuers.
- idx-method's newest commit (71ef6ed, 2026-10-26: "every root fetch also writes the store")
  changes no table this screen reads. The store's schema matches P33 and P36's fixtures.
