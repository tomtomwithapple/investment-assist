# P9-placebo — results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

P9-placebo is done and committed as `e347dc4` on `slice/P9-placebo`, not pushed. The accept command exits 0: 17 tests pass and ruff is clean. The full suite also passes (234 tests).

**What's in it** (`src/assist/eval/placebo.py`)
- **Inputs:** a *procedure* takes the features and forward returns lined up by date and returns one signal per date: active, inactive, or `None` for no call. Helpers `forward_returns(prices, horizon)` and `align(features, returns)` build those inputs.
- **Edge:** `edge(...)` is the mean forward return on active dates minus inactive dates, with a Welch t-stat. `direction=-1` is for rules that predict weaker returns, such as `risk_off`. `stride` scores only non-overlapping dates, and below `min_n` the verdict says "insufficient sample".
- **Walk-forward:** `walk_forward(fit, train, test, gap, expanding)` refits on past data only. `gap` drops training dates whose forward returns overlap the test window; set it to horizon − 1.
- **Verdict:** `evaluate(...) -> Verdict` checks two things:
  1. **Placebo:** the real signal against `n_shuffles` shuffled-date versions of the returns (shuffled in blocks to keep autocorrelation). The p-value is the share of shuffles that score at least as well.
  2. **Control:** the whole procedure rerun `n_controls` times on shuffled dates. If the mean control t is at or above `t_min`, it fails with "fitting noise" however good it looks on the real dates.
  
  It passes only if the sample is big enough, the control shows no edge, t ≥ 2 and p ≤ 0.05. Everything uses a fixed `SEED`, so a rerun gives the same verdict. `Verdict.to_dict()` holds every parameter, ready for the journal.
- **Tests:** cover a real rule (passes), a noise rule (fails), a rule that peeks at the returns it's scored on (fails as "fitting noise"), the walk-forward end to end, the no-lookahead windows, determinism, the shuffle and the stats.

**Live run:** the notes didn't ask for one and I don't own a `docs/results` file, so I ran a quick read-only check instead. I read only `../idx-method/data/jkse_daily.csv`, which runs from 1996-10-02 to 2026-09-30 and is frozen, as CLAUDE.md says. The rule was "JCI 20-day return < 0 predicts a weaker next 20 days", scored with `stride=20` and `block=20`. It passed: t 2.21, p 0.013, control t 0.20. This is only a check that the harness runs on real data, not a rule for the regime layer (P8).

**Sibling check:** the only store I read was that idx-method CSV. Its recent git log matches CLAUDE.md (index series no longer fetched), so there was nothing to reconcile.

**Notes for P8 and P20:**
- With overlapping horizons, pass `stride≈horizon` and `block≈horizon`, or the t-stats come out inflated.
- Use `walk_forward(..., gap=horizon-1)` for fitted rules so training returns don't overlap the test window.
