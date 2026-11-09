# P68-stocks-history (PLAN S49): the IDN stocks rule's walk-forward on the real stores

Date: 2026-11-09. Heuristic, not investment advice. Live run only. No code and no threshold
changed. This uses the gate as of S56 (P74: reduce side, bond-return lag); the stocks rows are
the same as P66/P67.

Run: the `assist rules` logic into a scratch `Paths.under`
(`ASSIST_SIBLINGS_ROOT=/Users/tommy/Projects`, real journal read-only), 2026-11-09. Cold build
2442 s (120 month ends, shared with the bonds rule). Rule fingerprint `sha256:d217e4585d5a…`.

## Calls per month (2016-11 → 2026-10, 120 month ends, 117 with a 3-month JCI return)

| Year | hold | reduce | enter | no_call |
|---|---:|---:|---:|---:|
| 2016–2020 | 0 | 0 | 0 | 50 |
| 2021 | 2 | 1 | 0 | 9 |
| 2022 | 10 | 2 | 0 | 0 |
| 2023 | 5 | 7 | 0 | 0 |
| 2024 | 5 | 7 | 0 | 0 |
| 2025 | 0 | 2 | 0 | 10 |
| 2026 | 1 | 0 | 0 | 9 |

- **No call** in 78 months:
  - IDX foreign flow missing in 59 (2016-11 → 2021-09; idxscape `stock_summary` starts
    2021-10-01);
  - no 10Y in 19 (2025-03 → 2026-09; the OECD proxy ends 2024-12 and IGSYC starts 2026-10).
- **Reduce** in 19 months: 2021-12, 2022-06/07, 2023-02/03/04/06/08/09/10, 2024-01/04/05/06/10/11/12,
  2025-01/02.
- **Enter: never.** Implied ERP − hurdle peaks at +0.19pt (2022-12), against `ERP_BAND` 1.0,
  so valuation never reads cheap.

## Gate (window 2021-10 → 2026-07, horizon 3, stride 3, block 3, `MIN_N` 10)

| Side | On / off windows | Short of 10 | Verdict |
|---|---|---|---|
| Enter (enter vs hold + reduce) | 0 / 14 (6 windows on no_call months) | on 10, off 0 | insufficient: t 0.00, p 0.807, control t 0.00 |
| Reduce (reduce vs enter + hold, P74) | 7 / 7 | on 3, off 3 | insufficient: t 0.00, p 0.427, control t 0.00 |

Below `MIN_N` the harness reports t = 0 by construction, so the numbers below are descriptive
only. They are overlapping returns and decide nothing:
- Every call month in the window: hold n 22, mean 3-month JCI return −0.38%; reduce n 19,
  +1.31%. Reduce months came before *better* returns.
- On the stride-3 windows: reduce 7 at −0.17% against the other 7 at +0.72%, which is the
  claimed direction, on 7 per side.

**Distance to the gate:**
- **Enter** cannot be reached on this history or the live record while the valuation input
  stays rich. That needs the earnings yield to beat the hurdle by 1pt; the closest month was
  +0.19pt.
- **Reduce** is 3 short on each side. The live journal adds one call a month, so about 4
  windows a year. In the window 19 of 41 called months were reduce (46%), so about 1.9 on and
  2.1 off a year, and both sides would reach 10 in roughly 1.5–2 years. IGSYC gives the rule its
  10Y again from 2026-10, so the history keeps growing too.

  Filling the 10Y hole (2025-01 → 2026-09, see S50's ask) would make 2025-03 → 2026-07 callable:
  17 months, about 6 more windows. That would likely close the reduce side's distance on
  history alone. The enter side would still be 0.

## Earnings yield: factor_series (history) vs the screener snapshots (live), on their overlap

19 snapshot dates, 2026-08-30 → 2026-11-05. Both are cap-weighted the same way
(`market_earnings_yield`).
- factor_series EY is higher on every date: mean +0.06pt, min +0.02, max +0.22 (2026-10-12),
  mean absolute difference 0.06pt.
- Examples: 5.50% vs 5.55% (08-30), 6.02% vs 6.25% (10-12), 7.75% vs 7.78% (11-05).
- Names: the snapshots cover 963–966; factor_series covers 914–921 (it skips echoes and stale
  quotes); 913–919 names are common.
- The seam is far smaller than `ERP_BAND` (1.0pt), so the history and the live rule agree on
  valuation.

## Diagnostics (open question 5; never gate a stance)

| Variant | Window | On / off / no_call | Verdict |
|---|---|---|---|
| 1-month horizon (`--horizon 1`) | 2021-10 → 2026-09 | 0 / 41 / 19 | insufficient (no enter) |
| Valuation-only, 3 months, from 2016-11 (`--variant valuation-only`) | 2016-11 → 2026-07 | 0 / 34 / 5 | insufficient (no enter) |

The valuation-only variant reads rich on every window of ten years as well.

## Evidence for the review (no number changed here)

The phase K review (`review/phase-k`, 2026-11-07) found two construction choices that make
valuation read rich:
- `G_REAL` added to the earnings yield counts growth twice;
- the IDN CRP added on top of a local-currency 10Y counts country risk twice.

Fixing both still gives 0 cheap months. Dropping the CRP alone gives 10, which would be fitting
to this sample. This run confirms the symptom (peak +0.19pt, 0 cheap months in 120, and 0 on the
valuation-only variant). Whether to change it stays with a review agent and the user. Any
change would be a new model with its own gate.
