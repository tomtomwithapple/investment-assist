# S15-industry-value (PLAN S15): industry-relative value screen, IDN, layer 4

Date: 2026-11-09. Branch `s15`. Heuristic, not investment advice.

## What changed

- **`src/assist/candidates/industry_value.py`** (new): the fourth IDN screen.
  - **Peers.** IDX-IC sub-industry when it holds at least 8 names in that month's pool, else
    the sector. Membership is idx-method's dated `industry_membership`: the latest snapshot on
    or before the date, else the first one back-filled (flagged). No membership → the
    `factor_universe` sector (sector only). Neither (most delisted names) → no peer group,
    counted. Peer medians are computed here; Stockbit's industry means are never read.
  - **Leg 1, fitted gap.** Within each peer group and month, an OLS of the log multiple on what
    justifies it; the gap is the residual:
    - log PBV on ROE;
    - log PE (normalised) on 3-year earnings CAGR and payout;
    - log EV/EBITDA on ROIC (`roce`).
    Financials (sector Keuangan) use only log PE and log PBV on ROE. A group with fewer than 8
    names holding a leg's inputs, or a degenerate fit, falls back to the log gap to the peer
    median.
  - **Normalised earnings.** TTM earnings = mktcap / PE on the store's daily row. The PE leg and
    ROE use the lower of TTM and the median of the last 3 TTM years.
  - **Leg 2, own history.** log PE (normalised) and log PBV against the name's own median over
    the last 60 month ends (at least 24 of them).
  - **Score.** Every gap is a percentile within its peer group (cheaper is higher). Each leg is
    the mean of its percentiles, and the score is 50/50 over the two legs, both required. The
    score is centred and scaled to unit variance (`(pct − 50) / 28.9`), so `layers.candidates`
    reads it on the other screens' z scale.
  - **Gates.** Fit pool: price ≥ 100, mktcap ≥ IDR 1T, positive book, a bar within 10 days.
    Named only: `screens.passes_gates` and `passes_quality` (or `BANK_FLOOR`) on the screener
    row. Quality is a gate, never scored.
  - **Replay.** Every month end with a later one. Top- and bottom-quintile mean next-month
    return (price plus dividends gone ex), in excess of the pool mean, go into
    `placebo.evaluate`. A month needs 40 ranked names.
- **`screens.run_screens`** adds `industry_value` to its results (`industry=True`), so the
  verdict, months, flags and named names reach `layers.candidates` and the run's `candidates`
  journal record. A missing store is a stale input
  (`idx-method factor_series / industry_membership (missing)`), and the screen then names no
  one.
- **`layers.candidates.ScreenSummary`** gains `flags`: what the replay could not reproduce point
  in time, journalled with the verdict.

## Point in time

- The store's daily PE, PBV and EV/EBITDA step on the **filing** date. Checked read-only on
  2026-11-09: BBCA's Q2 2025 earnings enter on 2025-07-30 (ASII 07-30, UNVR 07-31). No extra lag
  is added to them.
- `roce`, the only quarterly input, counts from period end + 120 days (`screens.LAG_DAYS`).
- Delisted names stay in while they have rows. But none of the 47 has a `factor_universe`
  sector or membership (only 2 have one in Stockbit's `universe` snapshots, which this screen
  does not read), so they have no peer group and sit out: survivorship, flagged.
- Membership has a single snapshot, 2026-11-06, back-filled to every replayed month (flagged).
- A month's row is the last one in its tail (day 18 on) that has a price and a mktcap. A tail
  holding a single row is an echo and is skipped.

## Tests (first, red → green)

`tests/candidates/test_industry_value.py`, 19 tests on a synthetic store: 62 names (a coal
sub-industry of 30, an oil one of 5 that falls back to its sector, 25 banks, one with only a
sector, one delisted with none). PBV = exp(3 × ROE + u). The mispricing u is either drawn fresh
each month (planted: it reverts) or a random walk (flat: no edge). The tests cover:

- the calendar, OLS, and the median fallback;
- peer groups, back-filled membership and the sector fallback;
- the fit removing what ROE justifies (gap vs u correlation > 0.95, vs ROE < 0.2);
- the EV leg, and banks having no EV leg;
- the own-history minimum;
- a 5× one-off not ranking first on PE;
- the echo skip, and a missing store as a stale input;
- no read after `as_of`;
- planted passes and names cheap names (at most 5 per sector);
- flat fails and names no one;
- gates and quality floor rejects;
- determinism;
- `run_screens` carrying the fourth screen, with and without the store;
- layer 4 keeping the flags and naming no one on a failed verdict.

1918 → 1937 passed (1 skipped). Ruff clean.

## Live run (2026-11-09, read-only, `industry_value.run_live()`, 17 s)

- Store `../idx-method/store/data/stockbiter.db` present (2026-11-06).
- **Replay:** 119 month ends, of which 95 are scored, 2018-11-30 → 2026-09-30. The own leg
  needs 24 months of history, so the first scored month is 2018-11. About 352 names a month are
  in the pool, and 902 name-months have no peer group.
- **Verdict: failed**, "t-stat 1.76 below 2.0": edge +0.85%/month top minus bottom quintile,
  p 0.040, control t 0.37 (spread t 1.42). **No candidate named.**
- **Live, on bar date 2026-11-05:**
  - 399 names in the pool, 24 peer groups (14 of them sub-industries), 1 name with no peer group.
  - Fit legs: PBV 391 fitted; PE 210 fitted, 65 on the median fallback; EV 310 fitted, 7 on the
    median fallback.
  - 60 names pass the gates and the floor.
  - Rejects: free float 116, liquidity 88, flagged board 75, no own history 16, Altman Z 13,
    F-score 10, extreme volatility 10, no fitted leg 5, negative CFO 4, bank ROE 1, interest
    cover 1.
  - The pool's top names before the gates (context only) are DNAR, PNLF, PNIN, KRAS, SDRA, TOWR,
    MYOH, CTRA and BSDE.
  - KRAS's TTM PE is 0.41 and its normalised PE 3.6: the one-off is removed.
- **Per-leg diagnostics** (decide nothing; choosing the weights from them would be fitting on
  the replay):
  - fitted gap alone: t 2.44, p 0.008, control t 0.34, would pass;
  - own history alone: t 0.86, p 0.197.

## Choices for the user (in `industry_value.CONFIG`, marked "(choice)")

1. `min_fit` 8: names a peer group needs for the OLS fit, else the median gap.
2. `min_group` 5: names a leg needs in a group before its percentiles count.
3. `norm_years` 3, **median** not mean: normalised earnings = min(TTM, median of 3 TTM years).
   A 3-year mean still keeps 7/3 of a 5× one-off, which S31 uses (mean).
4. `growth_years` 3: span of the earnings CAGR the PE leg is fitted on.
5. `min_own` 24 of 60 month ends for the own-history leg.
6. `weights` fit 0.5 / own 0.5, both legs required. The diagnostic above shows the fitted leg
   alone would pass. Changing the weight now is a decision taken after seeing the replay, so it
   needs the agent review that phase K/L numbers go through, and a new fingerprint.
7. `clip`: ROE and ROIC [−50%, 60%], growth ±50%, payout [0, 1].
8. Financials = the whole Keuangan sector (banks, insurers, multifinance, holding and
   investment), on PE and PBV vs ROE only.
9. Live score scale: percentile mapped to a z (`(pct − 50) / PCT_SD`), because
   `layers.candidates` sorts names from all screens on one `score`.
10. Fit-pool liquidity stand-in: mktcap ≥ IDR 1T, as P36/P37. Replay: next-month return at month
    ends, as the other `screens`, not the quarterly 3-month cycle of phase F.

## Not done here

- **S20.** The undervalued list needs an expected return and a margin over the hurdle. A
  relative-value gap has neither, so `industry_value` is not one of `undervalued.STYLES`;
  adding it needs a rule for its expected return.
- **Inputs no store holds:**
  - cost of credit for banks;
  - P/FCF (no capex);
  - sub-industry for delisted names;
  - membership history before 2026-11-06.

  Asks for idx-method: keep dating `industry_membership` snapshots (it does from now on), and
  record a sector or sub-industry for delisted names if Stockbit serves one.
