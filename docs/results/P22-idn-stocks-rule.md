# P22-idn-stocks-rule — PLAN S10a: IDN stocks market rule

`src/assist/layers/rules/idn_stocks.py` (re-exported from `assist.layers.rules`). It follows the
structure of P31's bonds rule:

- **`idn_stocks(as_of, regime=None, overrides=None, signals=None, score=None, *, phei=, dbnomics=, bps=, idxmethod=, snapshots=, worldbankscape=)`** returns `IdnStocks`. Its fields are:
  - `call` and `proposed_stance`
  - `entry`
  - the inputs: `earnings_yield`, `pe`, `factors_date`, `ey_gap`, `real_yield`, `implied_erp`, `hurdle`, `macro_score`, `ten_year_source`
  - `signals`, `drivers`, `risks`, `stale_inputs` and `sources`

  The rule reads through the P32, P16, P11, P3 and P1 adapters, and takes P17's `IdnOverrides` and P18's `IdnSignals`. It reuses P31's `_cpi`, so CPI comes from the overrides first, then bps-looker, then dbnomics.
- **`decide(valuation, flows, macro)`** works as follows:
  - **enter** when the market is cheap and neither flows nor macro are negative.
  - **reduce** when the market is rich and flows or macro are negative.
  - **hold** otherwise.
  - **no_call** when any input is None.

  An enter is laddered when the regime is `risk_off` or not given, and lump-sum otherwise.
- **`gated_stance(base, stocks, verdict)`** keeps `base` unless there is a call **and** a passing P9 verdict.
- **`rule_verdict(calls, prices, horizon=3)`** asks whether an enter precedes a better forward JCI return. `month_end_closes` builds the prices from JCI rows.
- **`market_earnings_yield(factors)`** and **`FactorSnapshots`**: the snapshot reader is described under the first finding below.

| Input | Source | Rule (hand-set, gated by the placebo) |
|---|---|---|
| JCI earnings yield | Cap-weighted from idx-method's screener: Σ mktcap·EY / Σ mktcap. Loss makers are included, as in an index P/E. It uses the newest `data/snapshots/<date>.json.gz` dated on or before as_of, and falls back to `factors.json` dated by its file time | Older than 14 days goes in stale_inputs |
| `ey_vs_sbn` | EY − SBN 10Y | Context only (±0.5pt) |
| `implied_erp_vs_hurdle` | Implied ERP = EY + 2.0% real earnings growth − real 10Y (10Y − CPI y/y). Hurdle = `us.erp.implied` + `idn.crp` from dbnomics/Damodaran, with publication lags of 10 and 45 days. `idn.erp.hurdle` is the fallback | ≥ +1pt is cheap (+1), ≤ −1pt is rich (−1). **This gates the call** |
| 10Y | IGSYC 10Y (PHEI), otherwise dbnomics `idn.rate.long`, named as a proxy in the drivers and in stale_inputs | A proxy older than 90 days gives no call (same as P31) |
| flows | P18 `idx_foreign_flow` (required) + `ksei_foreign_share` (optional), netted. `tic_us_equity_net` is a driver only | — |
| macro | worldbankscape IDN stocks score + P17 stocks override (`apply`) | ≥ 55 is a tailwind, ≤ 45 a headwind |
| JCI level | idx-method `JKSE` (frozen) | Driver, plus `idx-method JKSE (frozen, last …)` in stale_inputs. Never blocks the call |

**PHEI stays on this Mac:** drivers carry only derived numbers (EY − 10Y, real yield, implied ERP), never the raw IGSYC 10Y. A test checks this.

## Live run (read-only, 2026-10-23, `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects`)

The run used P8's live regime (neutral, dollar flat), P17's overrides and P18's signals.

| as_of | call | JCI EY (P/E) | EY − 10Y | real 10Y | implied ERP vs hurdle | flows | macro | stale |
|---|---|---|---|---|---|---|---|---|
| 2026-10-23 | **no_call** (10Y proxy from 2024-12 is too old) | 6.02% (16.6), 965 names, Rp 10,718T, snapshot 2026-10-12 | −0.99pt (proxy) | 3.73% | 4.29% vs **6.16%** (US ERP 3.70% Oct + IDN CRP 2.46% Jan): **−1.87pt, rich** | IDX −16.09T (−1), KSEI 31.32% −4.27pt (−1) → **−1**; TIC −1,577 US$ mn | 53.6 − 5 = **48.6** (0) | idxscape_phei (missing); idn.rate.long proxy (last 2024-12-01); idx-method JKSE (frozen, last 2026-09-30); satudatascape (missing); industrial_momentum and retail_momentum (missing, from P17) |
| 2026-10-12 | no_call | same snapshot | same | same | same | IDX −12.32T (−1), KSEI −1 | none: worldbankscape's payload is dated 2026-10-23, after as_of | as above, plus worldbankscape (as_of after) |

- **Stance:** `gated_stance("neutral", …)` returns `neutral` with the note "stocks rule: no call (no_call)".
- **Risks:** a 10Y proxy from 2024-12, JCI rich against the hurdle, KSEI foreign share falling, foreign net selling, and BI hiking (+1.00pt since March).
- **With a fresh 10Y at the same level, the table would say reduce (underweight):** valuation is rich, flows are −1 and macro is 0. That is context only: there is no verdict yet.

### Placebo

**No walk-forward is possible yet, so the rule cannot change a stance.**
- The market EY needs a dated cross-section. idx-method's snapshots run only from 2026-08-30 to 2026-10-12 (15 days), with EY between 5.42% and 6.07%.
- JCI is frozen at 2026-09-30, so no snapshot date has a forward JCI return of even one month.
- `rule_verdict` is wired and tested. It needs about 10 non-overlapping calls with forward returns. That means both a JCI fetcher and roughly a year more of snapshots, or a back-built EY history (see below).

## Findings (siblings vs the notes)

- **"JCI P/E from idx-method" doesn't exist as a series.** idx-method has no index P/E. The deleted `dividend_vs_bonds.py` (recovered from 9a0ea38^) compared single stocks with an SBR coupon. So the rule builds the cap-weighted P/E from the screener's per-name `mktcap` and `earnings_yield`. The large conglomerates with very high P/E (DCII 426, BREN 136, MORA 405) pull it up to 16.6.
- **`IdxMethodStocks` reads only today's `factors.json`.** For point-in-time reads, the rule reads `data/snapshots/` itself, read-only through `FactorSnapshots` in the rules module. The README says the archive is written every weekday. On this Mac it has gaps (none from 09-12 to 10-01) and ends 2026-10-12, the same date as `factors.json`. A later slice could move this reader into `sources/idxmethod_stocks.py`.
- **10Y:** PHEI tables are still missing (idxscape at migration 8) and `idn.rate.long` ends 2024-12, as in P31. The rule therefore reports the valuation but makes no call. This is now the binding constraint for **both** IDN rules.
- **Hurdle timing:** `idn.erp.hurdle` adds the latest CRP snapshot dated ≤ m, which leaks about 6 weeks in a backtest. The rule therefore builds the hurdle from `us.erp.implied` (10-day lag) + `idn.crp` (45-day lag) and keeps the derived series only as a fallback. Live, the two agree: 3.70% + 2.46% = 6.16%, matching P16's `idn.erp.hurdle`.
- **Model choice to revisit with the placebo:** `G_REAL = 2.0` is hand-set. With it, a cap-weighted EY of about 6% against a real 10Y of about 3.7% reads as rich whenever the hurdle is above about 5.3%. That is most of the time. Adding the CRP on top of a local yield that already carries country risk is conservative. Don't tune either to this sample.
- **For F2-idn:** pass the live regime, overrides and signals in. Route `proposed_stance` through `gated_stance` with a journalled verdict. Expect `no_call` until PHEI lands. Expect `idx-method JKSE (frozen…)` and the stale proxy in stale_inputs.

## Tests

`tests/layers/rules/test_idn_stocks.py` has 49 tests. They cover:
- the decision table
- the cap-weighted EY
- enter / ladder / lump entries
- reduce, hold and the valuation dead band
- the KSEI and IDX flow inputs (missing, netting)
- bond-only stale entries being dropped
- the macro override, layer-1 from worldbankscape, and a future-dated score
- the PHEI path, the proxy fallback, a too-old proxy giving no_call, and no 10Y at all
- no raw PHEI in the output
- the hurdle components, its fallback, a missing hurdle and point-in-time lags
- a missing or stale snapshot
- a frozen JCI
- missing stores
- CPI from dbnomics
- the snapshot reader (point in time, the factors.json fallback, missing or corrupt files)
- `gated_stance` and `rule_verdict` (a working rule, noise, all no_call)
- `month_end_closes`

Results: `uv run pytest -q tests/layers/rules` gives 49 passed. The full suite gives 806 passed and 1 skipped. `ruff check .` is clean.
