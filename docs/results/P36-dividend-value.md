# P36-dividend-value: PLAN S18, undervalued dividend screen (IDN)

`src/assist/candidates/dividend_value.py`; tests in `tests/test_dividend_value.py` (24 tests, in-memory
data plus a tiny `stockbiter.sql` fixture under `tests/fixtures/dividend_value/`).

## What it does

- **Expected IDR return** (pt a year) = trailing 12-month dividends by ex-date / price
  (`screens.trailing_dividend`) + g. g = ROE × (1 − payout), floored at 0 and capped at
  `CONFIG["g_cap_pt"]` = 8 (IDN nominal GDP growth). ROE = `ni_ttm` / `equity` and payout =
  dividends paid / `ni_ttm`, from P33's last quarter available by the date (period end + 120 days).
- **Safety gates** (all reasons are kept per name; rejects count the first one):
  - payout below 90% of `ni_ttm`
  - dividends covered by `cfo_ttm` (banks skip this: they pass `BANK_FLOOR` instead)
  - paid in at least 4 of the last 5 twelve-month windows
  - no cut (>10% drop in a 12-month total) in the last 2 years, unless `ni_ttm` is above its
    level a year earlier
  - before those, live only: `screens.passes_gates`, `passes_quality` (`BANK_FLOOR` for names
    with a `car`), and the holding-company skip.
- **Cheapness leg**: today's yield as a percentile of the name's own quarter-end yields over the
  previous 5 years (at least 8 quarters). It is reported and does not rank.
- **Margin** = expected − P34 IDN hurdle (`hurdle.margin`). The ranking is by margin.
  - Candidates need three things: a passed replay verdict, a known hurdle, and margin > 0.
  - Then `screens.select` takes the top 20, at most 5 per sector.
- **Replay**: every quarter end from P33's `factor_series` (2017-03-31 … 2026-06-30) that has a
  later quarter end.
  - Point in time: safety gates, price ≥ 100, and mktcap ≥ IDR 1T (a stand-in for liquidity).
  - Each name's 3-month forward return = price + dividends gone ex in the quarter.
  - Quarters with fewer than 30 names are not scored.
  - The top and bottom quintile by expected return go to `placebo.evaluate`, as
    `screens.evaluate_screen` does. On one date every name faces the same hurdle, so ranking by
    expected return is ranking by margin.
- `CONFIG` is part of the result (`fingerprint`). The module sits under `candidates/`, so the
  journal hash covers it.

## Live run (read-only, 2026-10-27; screen date 2026-10-09)

**Verdict: passed.** Beats the placebo with t 2.79 and p 0.004 (1,000 shuffles). The control t
is 0.10 (20 reruns on shuffled dates).

- 37 quarters scored (37 top and 37 bottom observations).
- Top quintile mean excess 3-month return: **+1.73%**. Bottom quintile: **−2.02%**.
- Mean quarterly spread: **3.76 pt** (t 2.32 on the spreads alone).

**IDN hurdle 13.74%**: SBN 10Y (IGSYC) + US ERP 4.09% + IDN CRP 2.46%. There was no risk-off
premium, and nothing was stale.

**Pool: 35 names** passed every gate. **6 candidates** have a positive margin:
**BMRI, JPFA, BBNI, ELSA, CPIN, STAA**.

Rejects (first rule failed):

| Rule | Names |
|---|---:|
| liquidity | 341 |
| free float | 258 |
| flagged board | 243 |
| extreme volatility | 22 |
| price floor | 17 |
| F-score | 15 |
| Altman Z | 11 |
| no dividend | 11 |
| payout | 6 |
| cut | 5 |
| paid years | 4 |
| cfo cover | 4 |
| negative CFO | 2 |
| interest cover | 2 |
| bank ROE | 1 |

Top 10 by margin:

| # | Name | Sector | Yield | g | Expected | Margin | ROE | Payout | CFO cover | Paid | Cut | Own-yield pct |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| 1 | BMRI | Keuangan (bank) | 11.81 | 4.45 | 16.25 | +2.51 | 18.6 | 76% | n/a (bank) | 5/5 | no | 0.85 (20q) |
| 2 | JPFA | Barang Konsumen Primer | 6.86 | 8.00 | 14.86 | +1.12 | 23.3 | 32% | 3.9x | 4/5 | no | 0.80 (20q) |
| 3 | BBNI | Keuangan (bank) | 10.19 | 4.39 | 14.58 | +0.84 | 12.2 | 64% | n/a (bank) | 5/5 | no | 0.85 (20q) |
| 4 | ELSA | Energi | 7.03 | 7.23 | 14.26 | +0.52 | 13.1 | 45% | 7.6x | 5/5 | no | 0.75 (20q) |
| 5 | CPIN | Barang Konsumen Primer | 6.08 | 8.00 | 14.08 | +0.34 | 18.2 | 44% | 2.2x | 4/5 | cut, recovered | 1.00 (20q) |
| 6 | STAA | Barang Konsumen Primer | 6.05 | 8.00 | 14.05 | +0.31 | 21.7 | 51% | 2.5x | 5/5 | no | 0.78 (18q) |
| 7 | LSIP | Barang Konsumen Primer | 5.59 | 8.00 | 13.59 | −0.15 | 13.1 | 30% | 4.1x | 5/5 | no | 0.80 (20q) |
| 8 | AUTO | Barang Konsumen Non-Primer | 6.80 | 6.60 | 13.40 | −0.34 | 12.9 | 49% | 1.8x | 5/5 | no | 0.50 (20q) |
| 9 | BBRI | Keuangan (bank) | 11.16 | 1.76 | 12.92 | −0.81 | 17.0 | 90%* | n/a (bank) | 5/5 | no | 0.95 (20q) |
| 10 | INTP | Barang Baku | 9.27 | 2.78 | 12.05 | −1.69 | 9.7 | 71% | 2.1x | 5/5 | no | 0.85 (20q) |

Yield, g, expected and margin are in pt; ROE is in %. \* BBRI's payout is just under 90%, so it
rounds to 90%. Its `cfo_ttm` is negative, which is no gate for a bank. The whole live run took
about 14 s.

## Findings (sibling checked first: idx-method HEAD `71ef6ed`, README *Changes the parent must follow*, real schema)

- **Dividends are as paid; `factor_series` prices are split-adjusted.** BBCA paid 432 in
  2021-04, while its adjusted price was about 7,000. Mixing the two would inflate pre-split
  yields and payouts, and the own-yield range with them.
  - Fix: rescale each dividend by real shares over adjusted shares. Real shares come from
    `fundamentals` `is.shares`, for the quarter of the ex-date. Adjusted shares are `mktcap /
    price` on the ex-date.
  - Result: 751 of 5,068 dividend rows rescaled, across 124 names (BBCA 0.2).
  - **270 of 607 payers have no share counts** (the `fundamentals` table covers 516 names).
    Their dividends stay as paid, so a past split there still inflates their old yields.
  - The share count of the ex-date's quarter is reported after that quarter. It only
    re-expresses a dividend already known on its ex-date, so it does not leak returns.
- **No holding-company marker.** `data/sectors.json` and `factor_universe.sector` hold only the
  IDX-IC sector. The subsectors "Perusahaan Holding & Investasi" and "Perusahaan Holding Multi
  Sektor" exist in `universe.json`, but no symbol-to-subsector map does. So the skip (any sector
  containing "holding", or a `holdings=` list) skipped **0 names** today. Ask idx-method for a
  subsector per symbol.
- **The live date is 2026-10-09, not 2026-10-26.** `cache/history/` (the liquidity, volatility
  and days-traded gates via `factors.load_factors`) ends 2026-10-09, while `factor_series` runs
  to 2026-10-26. The screen uses the screener's last bar date, as `screens` does.
- **The replay cannot use the liquidity gate** before `cache/history/` starts (2021-08). An IDR
  1T mktcap floor stands in. Free float, flagged boards and the quality floor are current-only and
  are not replayed (the same as P20). Banks in the replay are today's banks (a `car` in the
  screener).
- **Forward yield is the trailing yield** with no (1 + g) step-up, as the slice notes say.
- **The 120-day lag** is still P33's placeholder until idx-method V3.
- There was no conflict with CLAUDE.md on where the data lives: `stockbiter.db` holds `dividends`
  and `fundamentals`, as stated.
