# P66-rule-history (PLAN S47): point-in-time history of the IDN bonds and stocks rules

Date: 2026-11-07. Heuristic, not investment advice.

## What changed

- **`src/assist/history.py`** (new, plumbing outside the rule logic). On every calendar month
  end from 2016-11-30 to the last one before `today`, it calls `idn_bonds` and `idn_stocks`
  unchanged, with inputs as they were known on that date:
  - the regime from `regime.classify(regime.read_inputs(day))` (FRED `fred_as_of`);
  - P17 overrides and P18 signals as of the day;
  - the bonds rule's USD/IDR from `IdnSources.usdidr` (the P65 splice);
  - for stocks, the EY from `FactorSeriesEY`, with layer 1 held at 50 (`held_score`, open
    question 4) and P17's override applied by the rule, as it is live.

  Each `HistoryRow` holds:
  - as_of, call and proposed stance;
  - `missing`: the inputs whose absence made the month a no_call, as `input: reason`;
  - `ten_year_source` and the regime;
  - the numbers behind the call and the stale inputs;
  - the forward return over `HORIZON` = 3 month ends, or null.

  Forward returns:
  - stocks: the JCI month-end close (`JciSource`, stitched P51);
  - bonds: `bond_returns` on the month-end 10Y (IGSYC where present, else the OECD proxy, as
    `pipeline._ten_year_months`).

  Both are paired only between months exactly 3 apart, so a return never spans the 2025-01 →
  2026-09 hole. A month still running on `today` is never a target.

  `RuleHistory` adds two helpers:
  - `sample()`: non-overlapping windows exactly as `rule_verdict` → `placebo.edge` counts them
    (stride 3 over the months with a return);
  - `summary()`.

  The cache is `data/history/IDN-<asset>.json`, keyed by the model fingerprint, each store's
  newest date (the doctor's), the date range and the horizon. A change to any of them rebuilds
  it. For the live check, run `python -m assist.history [--today D] [--rebuild] [--rows]`. No
  CLI subcommand was added: `cli.py` belongs to P67.
- **`src/assist/sources/idxmethod_series.py`**: new `FactorSeriesEY`, which has
  `FactorSnapshots`' interface (`name`, `factors_on(as_of)`, plus `history(dates)`).
  - It reads daily `pe` and `mktcap`. A name counts when its newest row falls in
    (as_of − 14 d, as_of], so weekends and holidays carry the last trading day forward.
  - EY = 100 / PE. A negative PE is kept; a PE of 0 or a missing PE gives no EY.
  - There is no extra lag (the multiples step on the filing date, idx-method c432999).
  - A row more than 14 days after the name's previous row is dropped. This removes the
    pull-date echo, where the store repeats delisted names' last values on its newest date:
    35 extra names on 2026-11-06, e.g. APOL's last real quote is 2023-04.

## Tests (first, on fixtures)

- `tests/test_history.py` (20 tests): in-memory stores over 2020-06 → 2023-02.
  - The key test runs at three cut-off dates. It replaces every value not yet known on the
    cut-off with an absurd one: values dated after it, values recorded after it (PHEI fetch
    date), and values inside a publication lag (CPI 35 d, OECD proxy 45 d, ERP 10 d, CRP 45 d,
    JISDOR/IDX flow 1 d, SBN 40 d). It then checks that no row up to the cut-off changes.
    A deliberate leak (signals read 20 days ahead) fails it.
  - Further cases:
    - a PHEI point fetched after the as-of is not used;
    - CPI counts only past its lag;
    - a month with no 10Y is a no_call with `10Y: dbnomics idn.rate.long (no data)…`;
    - an old proxy is a no_call with `10Y: proxy from 2022-06 too old to call`;
    - forward returns;
    - a bond return never spans a gap;
    - window counting;
    - the JSON round trip;
    - the cache (a hit reads no store; a new fingerprint or a moved store date rebuilds).
- `tests/test_idxmethod_series.py`: 9 new tests on `tests/fixtures/history/factor_ey.sql`. They
  cover the interface, cap weighting with loss makers, PE 0, weekend carry, the filing-day step,
  no reads after the as-of, the echo and quiet names, an as-of before the series, and a missing
  store.
- Full suite: 1693 passed, 1 skipped (accept command: 139 passed). `ruff check .` is clean.

## Live run (2026-11-07, real stores read-only, from the worktree)

The build covers 120 month ends and took 18 min 38 s. About 5 s per month is FRED over HTTP and
about 2 s is bps-looker. The cache was written to the worktree's `data/history/`.

### Bonds rule

| | |
|---|---|
| history | 2016-11 → 2026-10 (120 months) |
| calls | enter 10, hold 35, reduce 4, no_call 71 |
| months with a call | 2021-03 → 2025-02, plus 2026-10 (hold, IGSYC) |
| missing inputs | foreign SBN 52 months (2016-11 → 2021-02; idxscape `sbn_ownership` starts 2021-01-04, and the signal needs 4 weeks known past the 40-day lag); 10Y 19 months (2025-03 → 2026-09: "proxy from 2024-12 too old to call") |
| with a forward return | 95 months; among the called ones, 43 (8 enter, 31 hold, 4 reduce) |
| non-overlapping 3-month windows | whole history from 2016-11: on 2 / off 12 (18 no_call). From the first called month (2021-03): **on 4 / off 11**. The other two stride phases give 2 / 12 |

- Enters: 2021-03, 05, 07, 09, 10, 2022-03, 2024-08, 09, 11, 2025-01.
- Reduces: 2022-08 → 11.
- The 2026-10-31 row reads IGSYC dated 2026-10-21 (the capture hole). Its real yield is 4.11%,
  at the 51st percentile, so the call is hold.

### Stocks rule

| | |
|---|---|
| history | 2016-11 → 2026-10 (120 months) |
| calls | **enter 0**, hold 23, reduce 19, no_call 78 |
| months with a call | 2021-10 → 2025-02, plus 2026-10 (hold, IGSYC) |
| missing inputs | foreign flow 59 months (2016-11 → 2021-09; idxscape `stock_summary` starts 2021-10-01); 10Y 19 months (2025-03 → 2026-09, proxy too old) |
| with a forward return | 117 months; among the called ones, 41 (0 enter, 22 hold, 19 reduce) |
| non-overlapping 3-month windows | whole history: on 0 / off 14 (25 no_call). From 2021-10: **on 0 / off 14** (6 no_call); the other phases give 0 / 14 and 0 / 13 |

### Earnings yield from factor_series

- The first date is 2016-11-08: the series starts 2016-11-07, and the echo guard needs a
  previous row. On that date the EY is 3.82% over 452 names. The first month end, 2016-11-30,
  reads 4.09% over 453 names.
- On 2026-11-05 the series gives **7.78%** over 918 names (Rp 8,762T). The live snapshot gives
  **7.75%** over 963 names (Rp 8,779T).
  - 46 of the 47 names in the snapshot only have a PE of 0 in both stores. The snapshot counts
    them at EY 0; the series gives them no EY.
  - Over the 916 names in both, the snapshot gives 7.80% and the series 7.78%.
- Other dates: 2026-08-31 5.59%, 2026-10-30 7.70%, 2026-11-06 7.94% (919 names after the echo
  guard).

## Surprises and evidence (no fixed number changed)

1. **The stocks rule never calls enter in the 41 months with every input.** The implied ERP
   minus the hurdle reaches at most +0.19pt (2022-12). Over 2023 → 2025 it is between −1.4 and
   −6.6pt, while `ERP_BAND` = 1.0.
   - The hurdle (US ERP + IDN CRP) is 6.1–8.9%.
   - The real 10Y is 1.4–6.3%.
   - With `G_REAL` = 2.0, the EY would need to be about 9–12% to read cheap. The JCI EY stayed
     at 3.4–7.1%.

   So the stocks gate has 0 "on" windows on this history and cannot pass on any sample this
   design produces. The cause is the valuation construction (G_REAL, ERP_BAND, the CRP added
   to the hurdle, the real-10Y term), not the window. It is for the phase K review agent;
   nothing was changed.
2. **The bonds rule has 8 enter months with a forward return, and at most 4 non-overlapping
   "on" windows.** It cannot reach 10 on the stores today. That is the "not yet" P69 expects.
3. **The factor_series EY jumps in December 2021.** It reads 3.51% on 11-30, 6.47% on 12-20,
   5.66% on 12-31 and 3.69% on 2022-01-06.
   - The cause is AVIA (IPO 2021-12-08), whose PE is 0.23 on a Rp 55T cap (EY 435%) until the
     year end.
   - It is a data artifact in idx-method's store and should be reported there. Here it only
     touches the 2021-12-31 row, which is a reduce either way (valuation −3.5pt).
4. **The cache key includes each store's newest date, and those move daily.** A rebuild costs
   about 19 min. P67's "rebuild when stale (older than its newest month end)" should key on
   the month end, or accept the cost.
5. **The bonds `missing` reason repeats both SBN stale lines.** This is cosmetic.

## Files

- Inside `owns`: `src/assist/history.py`, `src/assist/sources/idxmethod_series.py`,
  `tests/test_history.py`, `tests/test_idxmethod_series.py`, `tests/fixtures/history/`, and
  this file.
- Outside `owns`: none.
