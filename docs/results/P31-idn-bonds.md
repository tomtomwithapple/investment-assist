# P31-idn-bonds — PLAN S9: IDN bonds rule

`src/assist/layers/bonds/idn.py` (re-exported from `assist.layers.bonds`):

- **`idn_bonds(as_of, regime=None, overrides=None, signals=None, *, phei=, dbnomics=, bps=, idxscape=)`** returns `IdnBonds`. Its fields are:
  - `call`: `enter | hold | reduce | no_call`
  - `proposed_stance`: `overweight | neutral | underweight | None`
  - `entry`: a stance-schema `entry` dict
  - the inputs: `signals`, `real_yield`, `real_yield_pct`, `real_window`, `slope`, `breakout`, `ten_year_source` and `regime`
  - the context: `drivers`, `risks`, `stale_inputs` and `sources`

  The rule does no I/O of its own. It reads through the P32, P16, P11 and P3 adapters, and takes P17's `IdnOverrides` and P18's `IdnSignals`.
- **`decide(real_dir, foreign_dir, breakout)`** is the decision table:
  - **enter** when the real yield is high, foreign SBN holdings are stable or rising (direction ≥ 0) and there is no USD/IDR breakout.
  - **reduce** when the real yield is low and foreigners sell or USD/IDR breaks out.
  - **hold** otherwise.
  - **no_call** when any input is missing.

  An enter is laddered (3 × 10 days, from `assist.stance`) when the regime is `risk_off` or not given, and bought lump-sum otherwise. `regime` is the S1 `Regime` type. `layers/regime.py` is not imported.
- **`gated_stance(base, bonds, verdict)`** keeps `base` unless the rule made a call **and** its P9 placebo `Verdict` passed. It returns a note for the journal.
- **`rule_verdict(calls, yields, horizon=3)`** runs the P9 harness. It asks whether an enter precedes a better 10Y bond return than hold or reduce. The return proxy is `bond_returns`: carry − duration 7 × Δyield. `stride` and `block` default to the horizon.

| Input | Source | Rule (hand-set) |
|---|---|---|
| `real_yield` | IGSYC 10Y (idxscape PHEI) − newest CPI y/y. CPI comes from P17's `inputs["cpi_yoy"]` when given, otherwise bps-looker `BPS_CPI_YOY`, otherwise dbnomics `idn.cpi.yoy` | Percentile against its own monthly history (10Y at month end − that month's CPI) over up to 120 months: ≥ 66.7 is high, ≤ 33.3 is low. With fewer than 24 months the rule switches to absolute levels: ≥ 3.0% is high, < 1.5% is low |
| `curve_slope` | IGSYC 10Y − 2Y on the newest day with both, as idxscape J8 computes it | ≥ +0.75pt is steep (+1), < 0 is inverted (−1). Context only: it does not gate the call |
| `sbn_non_resident_change` | P18 (DJPPR via idxscape, 4 weeks, ±IDR 2T) | The direction is used as is |
| `jisdor_trend` | idxscape `JISDOR` | 20-fixing % change. A breakout is a new high over the previous 120 fixings (~6m) or a rise of ≥ +2.0% over 20 fixings |
| `tic_us_bond_net` | P18 (sec-edgar TIC) | Driver only |
| BI rate | P17 `bi_rate` component | Driver only. A hike shows up as a risk |

**Point in time:** PHEI's `as_of` is the page's fetch date, a real vintage, so PHEI rows count as known only once they were fetched. A gap-filled day is known only once the later page that filled it was loaded. CPI, the dbnomics series and JISDOR use publication lags (35, 45, 45 and 1 days), as P17 and P18 do.

**Local use only:** drivers, risks and signal details carry only derived numbers: the real yield, its percentile and the slope. They never carry a PHEI curve point. A test checks this.

## Live run (read-only, 2026-10-23, `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects`)

**No PHEI tables yet.** `../idxscape/data/idxscape.duckdb` is still at migration 8 (last written 2026-10-22 20:32, idxscape HEAD e7862c8), so `idxscape_phei (missing)`. The rule fell back to dbnomics `idn.rate.long` (OECD IRLT, monthly average) as the 10Y. **That series ends at 2024-12** (as dbnomics' HANDOFF says), so it is 22 months old.

| as_of | call | real yield | percentile (window) | slope | foreign SBN Δ4w | JISDOR 20d | breakout | stale |
|---|---|---|---|---|---|---|---|---|
| 2026-10-23 | **no_call** (proxy too old) | 3.73% (proxy 10Y 2024-12 − CPI 3.28% Sep 2026) | 34th pct, **101 months 2016-07..2024-11** | unavailable | IDR +5.74T **+1** | +1.7% **−1** (IDR weaker) | no | idxscape_phei (missing); curve slope unavailable; dbnomics idn.rate.long (proxy, last 2024-12-01); regime (not given) |

- **Stance:** with `gated_stance("neutral", …)` the stance stays `neutral` ("bonds rule: no call").
- **Risks:** "real yield rests on a 10Y proxy from 2024-12" and "BI hiking" (+1.00pt since March). With a risk-off, dollar-up regime the rule adds "global regime risk-off: ladder the entry" and "broad dollar rising".
- **Proxy age limit:** a proxy older than 90 days (`PROXY_CALL_AGE`) still reports a real yield but makes no call. Calling a 2026 stance on a 2024 yield would be noise.
- **Percentile window:** bps-looker CPI covers only 2024-01 on. The window therefore takes dbnomics `idn.cpi.yoy` for older months and stops where the 10Y proxy stops (2024-11). That gives 101 months, not the 120 the rule allows.

### Walk-forward placebo check (P9 harness)

- **Setup:** monthly as_of from 2021-11-30 to 2025-03-31. Each run used the dbnomics 10Y proxy, a neutral regime and P18's signals on that date. Each call is keyed on the next month, and the return is the proxy's forward return.
- **Why that span:** JISDOR in idxscape starts 2021-10 and the proxy ends 2024-12.
- **Calls:** 29 hold, 5 enter, 5 reduce, 2 no_call.

| horizon | stride / block | on / off | verdict |
|---|---|---|---|
| 3m | 3 / 3 | 1 / 10 | insufficient sample |
| 1m | 1 / 1 | 3 / 32 | insufficient sample |
| 3m | 1 / 3 | 2 / 31 | insufficient sample (mean on −0.9% vs off +1.6%) |

**Verdict: the rule does not pass its placebo, so it may not change a stance.** The sample is too small, and the few enter calls so far point the wrong way. This verdict should be revisited once PHEI history builds up. Before that, the thresholds (top third, the foreign gate) should not be tuned to this sample.

## Findings (siblings vs the notes)

- **The live fallback cannot make a call.** The slice notes say to fall back to dbnomics' IDN long-term rate. It is wired, but OECD's IDN series stopped at 2024-12, so it can only report a real yield. A current IDN 10Y needs PHEI (idxscape migration 9, which runs on idxscape's next `load phei` or nightly `phei`). Another source would have to be added in its own fetcher repo.
- **JISDOR in idxscape still ends 2026-10-16** (P18 saw the same). The 20-fixing trend is therefore a week old. That is at the 7-day limit, so it is not flagged.
- **Nothing conflicted with the siblings' docs:**
  - idxscape: J4 and J8 tables and slope as in `docs/storage.md`.
  - dbnomics HANDOFF: `idn.rate.long` ends 2024-12.
  - bps-looker: CPI from 2024-01.
- **For later slices:**
  - **F2-idn (phase B fan-in):** pass the live `Regime` from P8, P17's overrides and P18's signals. Send `proposed_stance` through `gated_stance` with the journalled verdict. Use `entry` as is.
  - **Drivers and risks are safe to send:** they hold no raw PHEI.

## Tests

`tests/layers/bonds/test_idn_bonds.py` has 39 tests. They cover:
- the decision table
- enter / ladder / lump entries and an unknown regime
- breakouts (a 6m high and a 20-day jump)
- foreign selling, and reduce
- missing signal, JISDOR, 10Y and CPI inputs
- the slope and an inverted curve
- no raw PHEI in the output
- CPI from the overrides
- the named window and the short-history fallback
- dbnomics CPI backfill and point-in-time reads
- the proxy fallback and the stale-proxy no_call
- the placebo gate, the return proxy and `rule_verdict` (working rule, noise, all no_call)
- the real PHEI adapter over its fixture store (including the gap-filled 10-09 day not being known before its page was fetched)

Results: `uv run pytest -q tests/layers/bonds` gives 39 passed. The full suite gives 555 passed and 1 skipped. `ruff check .` is clean.
