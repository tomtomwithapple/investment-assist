# P74-reduce-side (PLAN S56): the reduce side's own gate, and bond returns that start after the call

Date: 2026-11-09. Heuristic, not investment advice. This slice comes from the phase K review
(`review/phase-k`, 2026-11-07). The review kept all ten phase K numbers and found two flaws
outside them; this slice fixes both. No threshold, window, `MIN_N` or revocation number changed.

## The two flaws

1. **Reduce calls were never tested.** The gate's verdict tests enter (on) against hold and
   reduce together (off). Yet `gated_stance` in both rules applied *any* proposal once that
   verdict passed, so a reduce → underweight (and a hold → neutral) would have moved a stance
   on a test that says nothing about reduce. On the record so far, the bonds rule's four reduce
   months (2022-08 → 11) came before rallies.
2. **The bond return proxy started before the call.** Before IGSYC, the bonds forward return
   reads dbnomics' OECD `idn.rate.long`. That series is a monthly average dated the 1st and
   centred mid-month, so the return scored for a month-end call started half a month before the
   call.

## What changed

- **`eval/gate.py`** (rules schema 1.1.0). `SideGate` and `Gate.reduce`: the same machinery on
  the reduce side, reduce (on) against enter and hold (off), `direction` −1 (a reduce claims
  weaker returns). It uses the same window, horizon 3, stride 3, block 3, `MIN_N` 10, placebo,
  control and revocation (5 per side, signed t ≤ −1.0). `Gate.reduce_verdict` is its effective
  verdict. The top-level `verdict` is documented as enter-side only. `rules.schema.json` adds
  `reduce` {side, direction, state, verdict, historical, live, live_edge, sample, distance,
  why}. The journal's `gate` block carries `reduce` {state, sample, distance}.
- **`gated_stance(base, rule, verdict, *, reduce_verdict=None)`** in both rules:
  - an enter applies only on a passing `verdict`;
  - a reduce applies only on a passing `reduce_verdict` ("reduce side untested" without one);
  - a hold never applies ("a hold claims no edge").

  The three-argument call still works.
- **`pipeline._idn_view`** hands the gate's `reduce_verdict` to `gated_stance`. The stance
  takes the rule's proposal only when the note says the rule was applied.
  `pipeline.rule_prices` now takes `history.ten_year_months` instead of its own copy.
- **`history.py`**. `lag_monthly_averages`: a 10Y point dated the 1st is a monthly average and
  is re-dated to the previous month end, so the call on month end M is priced from M+1's
  average to M+4's. Daily IGSYC month-end closes stand as they are and win over a lagged average
  for the same month. `bond_forward` applies it in history, in the gate's refresh and in the
  live monitor.
- **`assist rules`** prints the reduce side's state, sample and effective verdict.
- Rule fingerprints change (history.py and both rule modules), so `out/rules/` rebuilds on the
  next run.
- Tests (written first):
  - a passing enter verdict never applies a reduce, and a hold is never applied (rules and run
    level);
  - a reduce side that beats its placebo passes on its own, and a reduce side with no edge
    fails;
  - no history gives no reduce verdict, and `rules.json` validates with `reduce`;
  - the 2016-11-30 bonds call is priced from December's average, and IGSYC closes are not
    lagged.
- Full suite: 1792 passed, 1 skipped; ruff clean.

## Live (`assist rules` logic into a scratch `Paths.under`, real journal read-only, 2026-11-09)

Cold rebuild of both rule histories: 120 month ends, 2442 s (run beside other live checks).
New rule fingerprints: bonds `sha256:deb1f60cd776…`, stocks `sha256:d217e4585d5a…`.

| Rule | Window | Enter side (on / off vs 10) | Reduce side (on / off vs 10) | State |
|---|---|---|---|---|
| IDN bonds | 2021-03 → 2024-08 | 3 / 11 (was 4 / 11 to 2024-09 before the lag) | 1 / 13 | insufficient, both sides |
| IDN stocks | 2021-10 → 2026-07 | 0 / 14 (unchanged) | 7 / 7 | insufficient, both sides |

- Bonds: the one-month lag drops the last proxy month with a forward return (window now ends
  2024-08) and moves one enter window off the stride, so the enter side has 3 on, not 4. Calls
  are unchanged: enter 10, hold 35, reduce 4, no_call 71. The reduce side has one window on
  (one of the four 2022 reduce months falls on the stride).
- Stocks: 19 reduce months in the window give 7 reduce windows against 7 enter-or-hold windows.
  The reduce side is 3 short on each side. It is the closer of the two sides of that rule, but
  it is still insufficient, so it applies nothing.
- No stance moves. Before this slice, a passing enter verdict would also have applied the
  stocks rule's reduce calls (19 of 42 called months).
