# P10-stance — results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

P10-stance is done and committed as `031d079` on `slice/P10-stance` (not pushed). The accept command passes: 30 tests green and ruff clean. The full suite also passes (331 tests).

**What `src/assist/stance.py` does**
- `build_stance(score, regime, weights, overrides=(), benchmark=None, …)` is a pure function over the S1 types and returns one payload in the shape of `stance.schema.json`.
- **Score:** the layer-1 score, shifted by the regime (risk_on +5, neutral 0, risk_off −5), plus any layer-2 overrides for the same subject and asset, capped at ±10 combined. The result is kept between 0 and 100.
- **Stance:** 60 or above is overweight, 40 or above neutral, 25 or above underweight, anything lower is avoid.
- **Target and delta:**
  - Overweight adds 5 points to the anchor and underweight takes 5 off; avoid targets 0.
  - The anchor is the benchmark weight when one is given, otherwise the current holding.
  - The delta is the gap between the target and the current holding.
- **Entry:** a ladder (3 tranches, 10 days apart) when buying in risk_off, a single lump when buying otherwise, and none when holding or trimming.
- **Missing inputs:** if the regime or the holdings are unavailable, the stance treats the regime as neutral and the current weight as `null`. It names the missing input in `stale_inputs` and lowers the confidence (×0.9 for each stale input) instead of failing.
- **Fingerprint:** `model_fingerprint()` hashes `MODEL_CONFIG`, which holds all the tilts and bands.
- **Determinism:** `dumps()` writes sorted keys and floats rounded to 1 decimal (2 for confidence), so identical inputs give identical bytes.

**Open question left as a TODO:** the weight bands (`TILT_PT`, `BENCHMARK_PCT`) are placeholders marked as PLAN.md's open question. `BENCHMARK_PCT` is empty, and I added no position caps or portfolio-level limits. Until you confirm your risk limits and benchmark, a stance only says which way and how far to move from what you already hold.

**Live run (read-only):** I built stances from worldbankscape's real output, `../worldbankscape/out/*/{stocks,bonds,currency,commodities}.json`, read directly because its adapter (P1) isn't on main yet.
- All 90 payloads passed the schema, and a rerun gave identical bytes.
- Stances: 60 neutral, 25 overweight, 4 underweight, 1 avoid.
- All three Indonesian stances are neutral: bonds score 58.0, currency 52.5, stocks 53.6.

The regime (P8) and portfolio (P4) layers aren't on main yet, so this run used no regime and no holdings. Every payload therefore lists `financer` and `regime` in `stale_inputs`, which lowers its confidence. `~/.financer/financer.db` exists, but I didn't read it.

**Where the sources differ from the plan:** nothing found. This slice reads no sibling store except worldbankscape's output, and that output's flags were accepted by the vendored schema as-is. There is no `docs/results/P10-stance.md` in this slice's globs, so these numbers are recorded only here.
