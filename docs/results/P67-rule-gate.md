# P67-rule-gate (PLAN S48): historical gate and live monitor for the IDN rules

Date: 2026-11-07. Heuristic, not investment advice.

## What changed

- **`src/assist/eval/gate.py`** (new). It replaces `pipeline.journalled_verdict`.
  - **Historical verdict.** `placebo.evaluate` runs on the P66 history rows: enter (on)
    against hold or reduce (off), no_call skipped, horizon 3, stride 3, block 3, `MIN_N` 10 per
    side. The window runs from the first month with a call to the last month with a full
    forward return (open question 1).
  - **Live monitor.** The same test runs on the journalled `rule` records. It counts only
    records that carry this rule's fingerprint (`outputs.rule_fingerprint`, new), dated from
    `since` (the day this fingerprint's gate was first written) up to the day before the run.
    Prices are the JCI month-end closes for stocks and the 10Y return proxy for bonds, as
    `journalled_verdict` used.
  - **State.** The states are checked in this order:
    1. `revoked`: the historical or the live verdict passed, and the monitor has at least 5
       windows per side with signed t ≤ −1.0.
    2. `passed`: the historical verdict passed.
    3. `live-passed`: the journal alone passes at 10 per side.
    4. `none`: no history for this rule fingerprint. A file whose fingerprint differs counts
       as no verdict, and `gated_stance` gets None.
    5. `insufficient`.
    6. `failed`.

    The effective `Verdict` goes to the unchanged `gated_stance(base, rule, verdict)`.
  - **Rule fingerprint, per rule.** It hashes the AST (without docstrings) of the modules
    that make the calls: the rule, regime, overrides, signals, types and `history.py`. For
    stocks it also hashes `bonds/idn.py` and `idxmethod_series.py`. The gate's numbers are
    hashed too. `gate.py` and `placebo.py` are left out: the verdict is recomputed from the
    rows on every run, so a gate edit does not force a 16-minute rebuild.
  - **Rebuild key: month end and rule fingerprint, not store dates.** `refresh` works like this:
    - It reruns every month end only when the file is missing, its fingerprint differs, or
      `--rebuild` is passed.
    - When a month end has passed since the file's last row, it reruns only the new month ends.
    - Otherwise it reruns nothing. Forward returns and the monitor are refreshed from the
      run's own month-end prices.
    - A failed build never raises. The cached verdict of the same rule stands, flagged as
      stale; with nothing cached there is no verdict.
  - `diagnostic()` reports another horizon and the `valuation-only` stocks variant (open
    question 5). These never gate a stance.
- **`schema/rules.schema.json`** (new). It is the contract for `out/rules/IDN-<asset>.json`,
  which holds:
  - the rule fingerprint and `since`;
  - the state, and the effective, historical and live verdicts in full;
  - the gate params;
  - the months covered, with the window;
  - the calls by type;
  - the on/off/no_call sample per side, and the distance to `MIN_N` and to revocation;
  - `why` per side, every no_call month with its reason, the history rows, and the disclaimer.
- **`src/assist/pipeline.py`**:
  - `gather_idn` gets the gates from `rule_gates` (never raises) over `rule_prices`. `run`
    passes `out/rules/`, and `Sources.rule_history` (default `gate.live_build`) rebuilds it.
  - The journal `rule` record carries `rule_fingerprint` and `gate`.
  - The stance note reads `(rule gate <state>: historical on x/10, off y/10 (window); live …)`.
  - `journalled_calls` and `journalled_verdict` are removed.
  - **The live stocks rule's macro input is now `history.held_score` (50 + P17 override)**, as
    open question 4 requires ("the rule that passes is the rule that runs"). Layer 1 still sets
    the band stance. Before this, the live rule read the worldbankscape score, which differs
    from the history it is gated on.
- **`src/assist/cli.py`**:
  - New command `assist rules [--today D] [--rebuild] [--horizon N] [--variant valuation-only]`.
    Diagnostics go to `out/rules/diagnostics/` and never gate a stance.
  - `assist run` prints a `gate …` line under each rule.

## Tests (written first)

- `tests/eval/test_gate.py` has 23 tests:
  - each state: passed, insufficient, failed, revoked, live-passed and none;
  - the monitor counts only this fingerprint, from `since`, never the day itself;
  - the distance and `why` per side, including the stocks ERP peak against `ERP_BAND`;
  - the no_call list;
  - `gated_stance` keeps its signature;
  - the rule fingerprint: a constant edit in the stocks rule changes stocks only, and a
    docstring edit changes nothing;
  - the schema, including rejection of an unknown state;
  - rebuilds: a missing file builds every month end; a run in the same month builds nothing;
    a new month end builds only that month; a new fingerprint rebuilds everything and resets
    `since`; a differing fingerprint with no builder gives no verdict;
  - a failed rebuild keeps the cached verdict and names the error;
  - `--rebuild`, forward-return refresh, and the valuation-only diagnostic.
- `tests/test_run_idn.py`:
  - a run writes `out/rules/`, and the journal carries the file's fingerprint;
  - a weekly rerun builds nothing and is byte-identical;
  - the gate line is in the note, `rule_gates` never raises, and the stocks macro input is
    held at 50;
  - the missing-stores run gives state `none` and writes no file.
- `tests/test_ops.py`: `assist rules` writes valid files, does not rebuild within the month,
  writes diagnostics, and `--rebuild` rebuilds.
- The initial red was an ImportError: the `assist.eval.gate` module did not exist yet.
- The accept command gives 109 passed. The full suite gives **1731 passed, 1 skipped**, and
  `ruff check .` is clean.

## Live check (2026-11-07, real stores read-only, from the worktree)

| | bonds | stocks |
|---|---|---|
| state | **insufficient** | **insufficient** |
| rule fingerprint | `sha256:24ccdefc4dc8…` | `sha256:50e2655984f8…` |
| history | 2016-11 → 2026-10, 120 month ends, 95 with a return | 120 month ends, 117 with a return |
| calls | enter 10, hold 35, reduce 4, no_call 71 | enter 0, hold 23, reduce 19, no_call 78 |
| window (first call → last return) | 2021-03 → 2024-09 | 2021-10 → 2026-07 |
| historical windows vs MIN_N 10 | **on 4 / off 11** (short on 6, off 0) | **on 0 / off 14** (short on 10), 6 windows on no_call |
| historical verdict | not passed, insufficient; p 0.881, control t 0.00; the placebo sets t to 0 below MIN_N. Descriptive t (min_n 2) **−1.17**: mean on +0.20% vs off +2.07% | not passed, insufficient; p 0.807, control t 0.00; no t without an on side (mean off +0.27%) |
| live monitor | on 0 / off 0 (needs 10/10 to live-pass, 5/5 to revoke), since 2026-11-07 | same |
| why on | 8 enter months with a return in the window, only 4 on the stride-3 windows | no enter in 42 called months; implied ERP − hurdle peaks at **+0.19pt (2022-12) vs ERP_BAND 1.0**, so enter is unreachable on this history |
| no_call months | 10Y 19 (2025-03 → 2026-09), foreign SBN 52 | 10Y 19, foreign flow 59 |
| stance written | **neutral** (layer-1 band; the rule proposes neutral, not applied) | **neutral** (same) |

Diagnostics (these never gate a stance):

- Bonds, 1-month horizon: window 2021-03 → 2024-11, on 9 / off 36, p 0.533.
- Stocks, 1-month horizon: on 0 / off 41.
- Stocks, valuation-only, 3 months: window 2016-11 → 2026-07, on 0 / off 34 / no_call 5.

### Wall time

- **Cold** `assist run --no-send` (no `out/rules/`): **21 m 22 s**. Of that, the rebuild of
  120 month ends took 951 s (15 m 51 s), against 18 m 38 s in P66.
- **Warm** `assist run --no-send`: **5 m 29 s**. The gate adds well under a second: a warm
  `assist rules` takes 0.55 s in total, including the JCI and 10Y reads.
- **Month end:** the first run after a month end reruns only the new month, about 8 s at
  951 s / 120.
- A full rebuild happens only on a rule-fingerprint change or `--rebuild`. That is the one
  run after the F10 merge, plus any later change to a rule constant.
- A store updating no longer triggers a rebuild.

## Evidence for the review (no fixed number changed)

1. **On today's stores, neither historical window can reach 10/10 at stride 3, whatever
   the calls.**
   - Bonds has 45 months with a call and a return in its window, which is 15 windows.
   - Stocks has 20 windows in its window, of which 6 fall on no_call months.
   - Twenty windows (10 + 10) need at least 60 called months with returns. The 19-month 10Y
     hole (2025-03 → 2026-09) and the flow and SBN start dates cap both windows well below
     that.

   So with `MIN_N` 10 and stride 3, the historical path cannot pass before new 10Y history
   arrives. The live path needs about 5 years.
2. **The stocks rule cannot call enter on 2016-11 → 2026-10.** The cause is the valuation
   construction (`ERP_BAND` 1.0, `G_REAL` 2.0, the CRP in the hurdle), not the window: the
   valuation-only variant from 2016-11 is also on 0 / off 34. The P66 finding is confirmed.
3. **On its 4 vs 11 windows, the bonds rule's enter months were followed by weaker bond
   returns than hold and reduce** (descriptive t −1.17, below the revocation line of −1.0).
   The sample is too small for any verdict, but if it held live it would revoke a pass, not
   earn one.
4. **The live journal does not carry over.** Journal rule records written before P67 have no
   `rule_fingerprint`, so the live monitor ignores them. They were also made under a model
   that did not hash the rules (before P64). The monitor starts at the F10 run.

## Files

- Inside `owns`: `src/assist/eval/gate.py`, `tests/eval/test_gate.py`,
  `schema/rules.schema.json`, `src/assist/pipeline.py`, `tests/test_run_idn.py`,
  `src/assist/cli.py`, `tests/test_ops.py` and this file.
- Outside `owns`: none. `history.py` is used unchanged: the gate calls `history.build` and
  keeps its own month-end key.
