# R-stocks-valuation: agent review of the IDN stocks rule's valuation leg

Date: 2026-11-10. Reviewer: independent agent, branch `review-stocks-valuation` off `main` at
`741ca27`. Heuristic, not investment advice. **Nothing is adopted here**: the locked rule
(phase K numbers, `G_REAL`, `ERP_BAND`, the hurdle) runs unchanged by default. The decision
is the user's.

The finding under review (PLAN *Open questions*, "Phase K review findings still open"; P66,
P67, P68): the valuation leg reads rich in every month (0 cheap months in 120, implied ERP −
hurdle peaks at +0.19pt in 2022-12 against `ERP_BAND` 1.0), so the enter side cannot be
reached. Suspected causes: real growth counted twice (`G_REAL` added to the earnings yield) and
the IDN country risk premium counted twice (CRP on top of a local-currency 10Y).

## 1. The two double counts, from first principles

The locked construction (`src/assist/layers/rules/idn_stocks.py`):

- `:84` `G_REAL = 2.0  # % long-run real earnings growth added to the EY`
- `:352` `h = 100 * (erp.value + crp.value)` (hurdle = US implied ERP + IDN CRP; the fallback
  `idn.erp.hurdle` at `:358-362` is the same sum, built by dbnomics)
- `:380-382` `real = ten.value - cpi.value`; `implied = ey + G_REAL - real`;
  `diff = implied - hurdle`
- `:384` `direction = _direction(diff, ERP_BAND)` with `ERP_BAND = 1.0` (`:85`)
- docstring `:12-17`: "EY + `G_REAL` (long-run real earnings growth, so EY stands for a real
  return)" and "The local yield already carries some country risk, so adding the CRP is
  conservative."

So the rule calls cheap when `EY + 2.0 − (10Y − CPI) − (US ERP + CRP) ≥ 1.0`.

### 1a. `G_REAL` added to the earnings yield: **confirmed, a double count**

- Gordon: expected return r = D₁/P + g. With payout ratio p and retained earnings reinvested
  at ROE, g = (1 − p)·ROE and D/P = p·E/P.
- When the reinvestment earns its cost of capital (ROE = r), r = p·E/P + (1 − p)·r, so
  **r = E/P**. The earnings yield already *is* the expected return including the growth that
  retained earnings buy. With inflation passed through to nominal earnings, it is a **real**
  return. This is why EY is set against a real yield (Siegel's "EY is a real yield"), which the
  rule already does by subtracting the real 10Y.
- "EY + g" is right only if the growth is free: 100% payout and growth anyway. JCI's payout is
  well below 100%, so EY + g double counts the growth that the retained half of earnings
  funds. The Gordon pairing is D/P + g, never E/P + g.
- The only case where EY understates the expected return is value-creating growth (ROE > r).
  The correction is then (1 − p)(ROE − r)/r-shaped and estimate-dependent, not a constant
  +2pt. Adding a constant 2pt is a hand-set number standing in for an unmeasured estimate.

Verdict: the `+ G_REAL` term is a double count. On principle the EY-based implied real ERP is
`EY − real 10Y`.

### 1b. The IDN CRP added on top of a local-currency 10Y: **partly confirmed**

Damodaran's convention for a cost of equity in local currency
(*Country Risk: Determinants, Measures and Implications*, and his `ctryprem` notes):

- local risk-free rate = local-currency government bond yield − the country's **default
  spread**, because the local government bond yield contains the sovereign default risk;
- cost of equity = that risk-free rate + mature-market ERP + CRP;
- CRP = default spread × (σ equity / σ government bond), which is ≥ the default spread.

Measured against the raw SBN 10Y (which still contains the default spread), the required
excess return is therefore

    hurdle over raw SBN = mature ERP + CRP − default spread.

The locked rule uses mature ERP + CRP, so it counts the **default-spread part** of the CRP
twice: once inside the SBN yield and again in the hurdle. The rest, CRP − default spread (the
extra volatility of equity over the bond), is **not** a double count: equity in Indonesia
carries more country risk than the government's own debt. So "CRP counted twice" is half right:

- keeping the full CRP overstates the hurdle by the default spread;
- dropping the CRP entirely (the earlier "dropping the CRP alone gives 10 cheap months")
  understates it by CRP − default spread, and is not a principled specification.

The data for this is in dbnomics' `damodaran_crp` table (store only, open-query-close): IDN's
rating-based `default_spread` sits beside `crp` in every snapshot. IDN, from the table
(fractions, CRP/DS = Damodaran's σE/σB multiplier):

| snapshot | Moody's | default spread | CRP | CRP/DS |
|---|---|---:|---:|---:|
| 2016-07 | Baa3 | 2.47% | 3.46% | 1.40 |
| 2017-01 | Baa3 | 2.54% | 3.13% | 1.23 |
| 2018-01 | Baa3 | 2.26% | 2.54% | 1.12 |
| 2019-01 | Baa2 | 2.15% | 2.64% | 1.23 |
| 2020-01 | Baa2 | 1.59% | 1.88% | 1.18 |
| 2021-01 | Baa2 | 1.68% | 1.84% | 1.10 |
| 2022-01 | Baa2 | 1.62% | 1.88% | 1.16 |
| 2023-01 | Baa2 | 2.33% | 3.29% | 1.41 |
| 2024-01 | Baa2 | 2.07% | 2.78% | 1.34 |
| 2025-01 | Baa2 | 1.89% | 2.54% | 1.35 |
| 2026-01 | Baa2 | 1.62% | 2.46% | 1.52 |

The same construction (local 10Y + US ERP + full CRP) is in the candidates' IDR hurdle
(`src/assist/candidates/hurdle.py`, P34). It is out of scope here and unchanged; it has the
same default-spread double count.

### 1c. A third point found on the way (not a double count): mixed estimators

Damodaran's US implied ERP is not an earnings-yield measure: it solves a 5-year cash-flow DCF
(dividends + buybacks, analyst growth, terminal growth = the T-bond rate) for the return, minus
the T-bond. The IDN side is an earnings-yield measure. Comparing the two mixes estimators. Is the
mismatch a one-signed bias? The same EY − real 10Y yardstick on the S&P 500 (Shiller's price,
trailing earnings, CPI and GS10, in dbnomics' `shiller` table) against Damodaran's ERP in the
same month:

| month | S&P EY | US real 10Y (GS10 − CPI y/y) | EY − real 10Y | Damodaran ERP |
|---|---:|---:|---:|---:|
| 2023-01 | 4.38% | −2.88% | 7.26% | 5.94% |
| 2024-01 | 3.99% | 0.97% | 3.02% | 4.60% |
| 2025-07 | 3.60% | 1.69% | 1.92% | 4.21% |

The gap changes sign, mostly because a trailing-CPI real yield swings, so there is no constant
bias to correct, and swapping the hurdle for a like-for-like US EY measure would add noise and a
new lag choice. It is noted as a limitation, not folded into the spec.

## 2. Ex-ante specification (written before any variant run)

Written and committed before the variant's history was built. **What the reviewer already knew
when writing it:** the P66/P68 numbers above (locked peak +0.19pt; "fixing both still gives
0 cheap months"; "dropping the CRP alone gives 10"), and the IDN default spreads in the table.
The specification is chosen on the principles in §1, not on those numbers. It adds no new
hand-set number.

**Spec R1 (`SPEC_R1 = "r1"`):**

1. Expected real equity return = the JCI earnings yield, as now (cap-weighted, trailing,
   loss makers included; `factor_series` in history, the screener snapshot live). Unchanged.
2. Real 10Y = 10Y − CPI y/y, as now (IGSYC 10Y, else the OECD proxy; the same CPI, lags,
   `PROXY_CALL_AGE`). Unchanged.
3. **Implied ERP = EY − real 10Y.** No `G_REAL` term (§1a).
4. **Hurdle over the raw SBN 10Y = US implied ERP + IDN CRP − IDN default spread** (§1b).
   The default spread is Damodaran's rating-based `default_spread` for IDN from
   `damodaran_crp`, from the same snapshot family as the CRP, with the CRP's publication lag
   (45 days) and maximum age (450 days). When the ERP or the CRP is missing, the fallback is
   `idn.erp.hurdle` − default spread. When the default spread is missing, there is no hurdle,
   so the valuation leg makes no call (named in stale_inputs). It never silently falls back to
   the locked hurdle.
5. Cheap when implied ERP − hurdle ≥ `ERP_BAND` (1.0), rich when ≤ −1.0. **`ERP_BAND`,
   `GAP_BAND`, `MACRO_HIGH/LOW`, `decide`, the gate (window, horizon 3, stride 3, block 3,
   `MIN_N` 10, revocation) and every other phase K number stay as they are.** None of them is
   wrong on principle. `ERP_BAND` is a dead band on a premium that is now measured correctly,
   and the reviewer has no ex-ante reason to move it.

Equivalently: R1 diff = locked diff − `G_REAL` + default spread = locked diff − 2.0 + DS.

**Prediction, written before the run.** In the gate window (2021-10 → 2026-07) the default
spread known at each month end is 1.62–2.33%, so R1 moves the diff by −0.38 to +0.33pt. With the
locked peak at +0.19pt, R1 should give **0 cheap months**, so the enter side stays unreachable.
The reduce side may lose or gain a few months near −1.0.

Known conservative biases left in on purpose (each would need a new estimated number):
trailing rather than forward earnings (about +0.4pt at 6% EY and 7% nominal growth), and ROE
above the cost of capital (EY then understates the expected return).

<!-- results below were added after the run -->

## 3. Prototype

The spec above was committed as `a3df8de` before any code or run. The prototype was committed as
`a7d653f`.

- `src/assist/layers/rules/idn_stocks.py`: `idn_stocks(..., spec=SPEC)`, with `SPEC =
  SPEC_LOCKED = "k"` (the locked rule, the default) and `SPEC_R1 = "r1"`. In r1:
  - `_valuation` adds no growth;
  - `_hurdle` subtracts the default spread that `_default_spread` reads from
    `damodaran_crp` (IDN rows, `snapshot_date` + 45 days ≤ as_of, max age 450 days);
  - a missing spread gives no hurdle.
  `IdnStocks.spec` records which spec ran. `G_REAL`, `ERP_BAND` and every phase K number are
  untouched.
- `src/assist/history.py`: `rules_on` and `build` take `stocks_spec` and `assets` (stocks only,
  so the run skips the bonds rule). Defaults are unchanged.
- Tests: 9 new cases in `tests/layers/rules/test_idn_stocks.py`:
  - the default is still the locked rule;
  - r1's ERP and hurdle arithmetic;
  - `ERP_BAND` is unchanged;
  - the spread respects the CRP's lag;
  - no spread (empty, locked, no table) gives no call;
  - the fallback hurdle also nets the spread;
  - an unknown spec raises.
  1 new case in `tests/test_history.py` (stocks only, the spec passes through).
- **Full suite: 2081 passed, 1 skipped** (`uv run pytest -q`; the skip is the absent
  worldbankscape checkout).

**Fingerprints.** The flag alone changes them, even with the default `k`:
- stocks rule `sha256:457c6c858be4…` (main) → `sha256:4f659ec6313a…` (branch);
- bonds rule `sha256:f9be0b944e8e…` → `sha256:ccbe7ef6b7c1…` (it hashes `history.py`);
- the model fingerprint changes too (`layers/**`, branch `sha256:e509720344cb…`).

An adoption would open a new journal segment and reset each rule's live monitor (`since`). To
keep the bonds fingerprint, it should ship r1 as the only spec, edit only `idn_stocks.py`, and
leave out the `history.py` plumbing used for this run.

## 4. Results: point-in-time history and gate, r1 vs locked

Run on 2026-11-10 with the real stores read-only (`ASSIST_SIBLINGS_ROOT=/Users/tommy/Projects`),
`history.build` on the 120 month ends 2016-11 → 2026-10, stocks only, both specs in parallel:
1395 s for k and 1383 s for r1. The gate is `eval/gate.evaluate_gate` on those rows (window,
horizon 3, stride 3, block 3, `MIN_N` 10, seed as live; no journal records). **Check:** the
spec-k rerun matches the live `out/rules/IDN-stocks.json` (fingerprint `457c6c85…`) on all 120
calls, with the same implied ERP − hurdle to 4 decimals. So the plumbing change does not alter
the locked rule.

| | locked (k) | r1 |
|---|---:|---:|
| calls (120 months) | hold 23, reduce 19, no_call 78 | hold 22, reduce 20, no_call 78 |
| cheap months (diff ≥ +1.0), all 120 / 42 called | **0 / 0** | **0 / 0** |
| rich months (diff ≤ −1.0), all 120 / 42 called | 115 / 37 | 117 / 39 |
| peak implied ERP − hurdle | +0.19pt (2022-12) | −0.19pt (2022-12) |
| mean over the 42 called months | −3.61pt | −3.65pt |
| enter months | none | none |
| call changes | — | 2022-11 hold → reduce (diff −0.63 → −1.02) |
| gate window | 2021-10 → 2026-07 | 2021-10 → 2026-07 |
| **enter side** (enter vs hold + reduce) | on 0 / off 14, insufficient, t 0.00, p 0.807, control t 0.00 | the same: on 0 / off 14, insufficient, t 0.00, p 0.807, control t 0.00 |
| **reduce side** (reduce vs enter + hold) | on 7 / off 7, insufficient, p 0.427; mean on −0.17%, off +0.72% | the same: on 7 / off 7, insufficient, p 0.427; mean on −0.17%, off +0.72% (2022-11 is not a stride-3 window) |
| valuation-only diagnostic (2016-11 → 2026-07) | on 0 / off 34 | on 0 / off 34 |

The prediction written in §2 held: **0 cheap months, the enter side unreachable**, and the gate
numbers are identical. The per-month shift r1 − k ranged from −0.41 to +0.54pt over all 120
months (default spread 1.59–2.54%), as the arithmetic `−2.0 + DS` says.

## 5. Sensitivity (diagnostics only: NOT a basis for choosing a spec)

These variants were computed after the run, on the 42 called months of the locked rows. Each one
is a forking path, and picking among them by their cheap count is exactly the post-hoc fitting
the placebo cannot catch. They show *where* the gap is, nothing more.

Components (percent, mean / min / max): EY 5.35 / 3.38 / 7.70; real 10Y 3.59 / 1.39 / 6.25; US
ERP 4.81 / 3.70 / 6.21; CRP 2.57 / 1.84 / 3.29; default spread 1.96 / 1.62 / 2.33.

| variant | cheap | rich | mean diff | peak |
|---|---:|---:|---:|---:|
| locked: EY + 2 − real − (US + CRP) | 0 | 37 | −3.61 | +0.19 |
| **r1: EY − real − (US + CRP − DS)** | **0** | **39** | **−3.65** | **−0.19** |
| drop `G_REAL` only | 0 | 42 | −5.61 | −1.81 |
| net DS only, keep `G_REAL` | 3 | 28 | −1.65 | +1.81 |
| drop CRP only, keep `G_REAL` | 10 | 25 | −1.04 | +2.07 |
| drop both `G_REAL` and CRP | 0 | 32 | −3.04 | +0.07 |

What drives the gap:
- The two double counts **roughly cancel**. `G_REAL` adds 2.0pt to the ERP, and the default
  spread over-charges the hurdle by about 2.0pt. Fixing both moves the diff by only −0.04pt on
  average.
- The variants that produce cheap months (net DS only: 3; drop CRP only: 10) each fix one
  error and keep the other. Neither is a principled spec.
- **The gap is structural.** Under r1, a cheap month needs a JCI EY of about 10.0% on average
  (actual mean 5.35%; short by 1.2–7.4pt, mean 4.65pt). The required real return is real
  SBN 3.6% + US ERP 4.8% + (CRP − DS) 0.6% ≈ 9.0%. A JCI at P/E ~19 does not clear that
  against a ~3.6% real SBN yield. That is a reading of the market, not an arithmetic slip.

Two measurement points that were not in the spec, noted for later:
- **Free-float weighting.** JCI is free-float weighted. The rule weights by total market cap,
  which over-weights low-float, high-P/E names (DCII P/E 368, BREN 103, DNET 132, SMMA 100;
  together about 11% of total cap on 2026-11-05). On the screener snapshots that carry
  `ff_mktcap`, a free-float weighted EY is higher by 0.9–1.3pt: 6.43 vs 5.51% (08-31),
  7.01 vs 6.02% (10-12), 9.01 vs 7.75% (11-05). `factor_series` (the history) has no free
  float, so this could not be tested on the 120 months. It ties to the open question *JCI P/E
  level*. Even +1.3pt would not close a ~4.7pt mean gap.
- **The estimator mismatch (§1c)** has no constant sign, so it explains no constant bias.

## 6. Risks of post-hoc fitting

- The reviewer knew P68's headline numbers before writing §2. The spec was fixed on Damodaran's
  convention and the Gordon identity, with no free parameter, and committed before the run. Its
  outcome (0 cheap months) was predicted in writing. Nothing was chosen to make enter reachable.
- Any change now made *because* enter is unreachable would be outcome-driven. That covers
  lowering `ERP_BAND`, dropping the CRP, switching to a free-float EY "to get calls", or putting
  a growth term back. A rule that never says enter is not evidence that the rule is wrong; JCI
  may simply have been dear against SBN all through 2021–2026.
- The 2022-11 reduce that r1 adds falls on no stride-3 window, so the gate cannot tell the
  specs apart on this sample. The reduce side is 3 short per side either way.

## 7. Recommendation (the decision is the user's)

- **On principle: r1 is the correct construction, and the locked rule's two errors are
  real.** `G_REAL` is a full double count. The CRP is double counted only by its
  default-spread part.
- **On the evidence: adopting r1 changes nothing measurable.** It gives 0 cheap months (as
  before), identical enter and reduce gate numbers, and one call changed in 120 (2022-11 hold →
  reduce).
- **Recommendation: needs more data. Do not adopt now**, and do not treat it as urgent.
  Adopting would cost a new fingerprint (a new journal segment, and the live monitor resets)
  for no change in any verdict.
- **Fold r1 in at the next valuation-leg change that has to happen anyway**, as one model
  change with its own gate. The obvious candidates:
  - a free-float EY history (ask idx-method for `ff_mktcap` in `factor_series`);
  - the 10Y hole being filled;
  - the same default-spread fix in `candidates/hurdle.py` (P34).
  Until then, the docstring line "adding the CRP is conservative" in `idn_stocks.py:16-17`
  understates the issue. It is the default-spread part of the CRP that is double counted, and
  it is cancelled by `G_REAL`.
- **Leave `ERP_BAND` and the other phase K numbers as they are.** Nothing here shows that any
  of them is wrong on principle.

Scripts (session scratchpad, not committed): `rsv/run.py` (stocks-only history for one spec),
`rsv/analyse.py` (calls, gate, diagnostics, sensitivity).
