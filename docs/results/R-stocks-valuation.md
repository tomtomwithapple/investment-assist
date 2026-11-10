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
