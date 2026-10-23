# P21-cost-entry — PLAN S10b: IDX cost model + entry levels

Both modules are ported from idx-method's deleted code (git `9a0ea38^`), not reinvented:
`paper/costs.py` → `src/assist/candidates/costs.py`, `entry_levels.py` →
`src/assist/candidates/entry.py`.

**Cost model** (`cost_for(row, order_idr) → Cost`, all components in bps):
- fees: 0.15% buy; 0.15% + 0.10% final sales tax on sell (published, never fitted)
- spread: half the quoted width per side, on the IDX tick grid (1/2/5/10/25 at 200/500/2000/5000);
  one tick wide at IDR 20bn/day turnover, +0.5 tick per decade thinner (continuous)
- impact: square-root law, `1.0 × daily vol × sqrt(order / med_value_60d)` with P19's `vol_1y`;
  Amihud linear impact (`amihud × order in IDR bn`) is the fallback without `vol_1y` and is reported
  for every name as a cross-check
- orders are rounded down to 100-share lots; flags: `over_participation` (order > 10% of ADV),
  `no_turnover` (charged as IDR 0.1bn/day, not spread-free as idx-method did), `below_one_lot`
- Only the structural prior is kept. idx-method's `fit()` never had real fills (simulated fills at the
  open print fit a cost of zero), and this repo places no orders.

**Entry levels** (`measure(bars, dividends, as_of) → EntryLevels`, `entry_plan(...)` joins levels and
costs per symbol, with `stale_inputs`): drawdown from the rolling 3-year high; typical correction
(median completed fall past −15% that recovered to within −5%); deep zone (10th pct of daily
drawdown); dip-buy record (median 12-month total return incl. dividends from bottom-quartile days,
and its win rate). Status: `avoid` (dip record < 0 or win rate < 50%), `deep`, `buy_zone`, `wait`.
Entry prices are rounded down to the tick grid.

Tests: `tests/candidates/test_costs_entry.py`, 35 passed; ruff clean. Full suite 386 passed, 1 skipped.

## Where the data forced a change from idx-method

- idx-method used 10 years of Yahoo split-adjusted closes. Here the source is `cache/history/`, which
  holds about 5 years (2021-08-26 → 2026-10-09 on this Mac) of **unadjusted** closes. Closes are
  back-adjusted with P19's rule (a 1-day move beyond ±40% counts as a split, a zero return).
  `MIN_BARS` = 750, as before. Drawdowns count after the first 365 days, so the window is about 4 years.
- With ~4 years instead of 10, many large caps have **no completed correction** in the window: the
  whole window is one long fall from the 2022–23 highs. `entry_typical` is then `None` and only the
  deep zone can trigger. The dip-buy record also turns negative for names whose only dips are this
  bear market, so BBCA, BBRI, MYOR and ICBP read `avoid` here, where they read `DEEP` in
  idx-method's 2026-09-30 `entry_levels.csv`. This is a property of the short sample, not a bug.
  A longer history in idx-method's cache would fix it.

## Live run (read-only, 2026-10-23, `ASSIST_IDX_METHOD_DIR=../idx-method`)

Bars as of 2026-10-09 (the cache on this Mac). `load_factors` 3.9s for 978 names; `entry_plan` over all
1,023 history files 4.7s. 890 names have entry levels: 410 wait, 191 avoid, 149 buy_zone, 140 deep.
Round trip for an IDR 10m order across all names: p10 111bp, median 330bp, p90 813bp. 216 names
are flagged `over_participation` at IDR 10m and 156 `no_turnover`.

Round-trip cost (bps) by order size:

| Name | Price | ADV (IDR bn) | Spread/side | RT @10m | RT @100m | RT @1bn |
|---|---|---|---|---|---|---|
| BBCA | 6,050 | 715.3 | 20.7 | 83 | 86 | 97 |
| BBRI | 3,100 | 523.7 | 16.1 | 74 | 78 | 90 |
| TLKM | 2,320 | 273.3 | 21.6 | 87 | 94 | 117 |
| ASII | 4,820 | 208.7 | 10.4 | 64 | 72 | 96 |
| ICBP | 6,950 | 27.3 | 18.0 | 83 | 99 | 150 |
| MYOR | 1,375 | 15.3 | 19.2 | 90 | 116 | 198 |
| SIDO | 354 | 7.8 | 34.0 | 119 | 141 | 212 (flag) |
| SMMA | 20,150 | 0.020 | 15.5 | 393 (flag) | 1,199 | 3,661 |
| MPRO | 12,000 | 0.031 | 25.1 | 540 (flag) | 1,540 | 4,683 |
| SRAJ | 13,000 | 0.023 | 23.7 | 558 (flag) | 1,638 | 5,021 |
| CASA | 1,830 | 0.017 | 34.6 | 646 (flag) | 1,816 | 5,507 |
| DCII | 199,475 | 0.101 | 1.3 | below one lot | 519 (flag) | 1,548 |

For liquid names the cost is fees plus one tick. For the Development Board names, a single IDR 10m
order is already 30–57% of a day's median value. Amihud's linear impact agrees with the
square-root law at IDR 100m (e.g. SRAJ 761 vs 775bp, CASA 991 vs 853bp) and is far higher at
IDR 1bn, where neither should be trusted.

Entry levels (IDR 10m column, as of 2026-10-09):

| Name | dd now | rank pct | high 3y | typical | deep zone | entry typ / deep | fwd12 all / after dip | win | status |
|---|---|---|---|---|---|---|---|---|---|
| BBCA | −44.7 | 3.0 | 10,950 | — (0 done) | −41.1 | — / 6,450 | −0.9 / −14.2 | 0% | avoid |
| BBRI | −51.6 | 6.7 | 6,400 | −15.3 | −49.0 | 5,400 / 3,260 | −6.6 / −6.6 | 29% | avoid |
| TLKM | −44.9 | 7.2 | 4,210 | — | −44.0 | — / 2,350 | −6.9 / 30.8 | 93% | deep |
| ASII | −34.9 | 22.5 | 7,400 | −43.4 | −37.4 | 4,190 / 4,630 | 3.5 / 21.2 | 100% | wait |
| MYOR | −53.7 | 0.3 | 2,970 | −21.8 | −38.8 | 2,320 / 1,815 | −6.6 / −9.1 | 31% | avoid |
| ICBP | −45.7 | 6.4 | 12,800 | −17.4 | −43.7 | 10,550 / 7,200 | −1.0 / −19.2 | 0% | avoid |
| SIDO | −54.3 | 3.2 | 775 | — | −51.9 | — / 372 | −11.0 / 6.1 | 61% | deep |
| DCII | −44.6 | 8.6 | 359,900 | −34.9 | −44.2 | 234,250 / 200,825 | 21.1 / 324.6 | 100% | deep |
| SRAJ | −24.4 | 24.7 | 17,200 | −33.9 | −51.6 | 11,350 / 8,300 | 231 / 581 | 100% | wait |
| CASA | −11.6 | 74.2 | 2,070 | −37.6 | −43.5 | 1,290 / 1,165 | 8.2 / 100.4 | 82% | wait |
| MPRO | −16.8 | 59.7 | 14,425 | −34.9 | −63.8 | 9,375 / 5,200 | 46.8 / 153 | 97% | wait |
| SMMA | −16.0 | 58.5 | 24,000 | −40.2 | −38.7 | 14,350 / 14,700 | 9.3 / 6.7 | 73% | wait |

**Cross-check against idx-method's last `entry_levels.csv` (2026-09-30, 10y Yahoo):** `high_3y` is
identical for all seven overlapping names (BBCA 10,950, BBRI 6,400, TLKM 4,210, ASII 7,400, MYOR
2,970, ICBP 12,800, SIDO 775). `dd_now` agrees within the price move between the two dates (BBCA
−44.5 vs −44.7, MYOR −53.2 vs −53.7, SIDO −55.1 vs −54.3). The typical and deep levels differ
because of the shorter window explained above. The Development Board names (`dbx_entry_levels.csv`)
show the same: DCII is `deep` in both, and SRAJ, CASA, MPRO and SMMA are `wait` in both.

## For later slices

- `Candidate.entry_level` can take `EntryLevels.entry_typical`, or `entry_deep` when the typical
  level is `None`. A screen should net `Cost.round_trip_bps` off its expected edge and drop names
  flagged `over_participation` at the planned tranche size.
- Neither the levels nor the cost prior may change a stance before a placebo control (CLAUDE.md).
- `entry_plan` takes `factors=` so a caller that already ran `load_factors` (P20 screens) doesn't
  derive the factors twice.
