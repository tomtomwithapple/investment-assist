# P27-fx-idr: results

Live run 2026-10-23, read-only: JISDOR through the P3 adapter (`IdxscapeSource`) and the BI and Fed
policy rates through the P12 adapter (`BisfetcherSource`). Neither store was locked.

## What `assist.fx` gives later slices

Pure functions over `Row` series, no I/O (`src/assist/fx.py`):

- `level_at`, `fx_change`, `horizon_changes`: as-of levels (None skipped, optional max age), the
  change between two dates, every overlapping N-day change (for an adverse-move quantile).
- `cross(idr_per_usd, local_vs_usd)`: IDR per local unit through USD when there is no direct IDR
  quote; `local_per_usd=False` for USD-per-local quotes (EUR, AUD). The local leg may be at most
  7 days old on each JISDOR date. `to_idr(prices, idr_per_local)` turns a price series into IDR.
- `unhedged_idr_return(r, fx_move) = (1+r)(1+fx_move) − 1`, `fx_move` = change in IDR per local unit.
- `forward_premium(i_idr, i_local, T) = (1+i_idr·T)/(1+i_local·T) − 1`; `hedged_idr_return =
  (1+r)(1+premium) − 1 ≈ r + (i_IDR − i_local)·T`; `hedge_carry(idr_rate_rows, local_rate_rows,
  as_of, T)` does the same from rate rows in percent (BIS `5.75`).
- `uip_expected_move`: uncovered parity, equal to the forward premium.
- `breakeven_fx_move(r_local, r_idr)`: the local fall at which the unhedged edge is gone.
- `fx_edge(...) → FxEdge`: hedged and unhedged IDR returns against an IDR alternative, `best`
  (`hedged` | `unhedged` | None), `survives`, `edge`, `detail()`. This is CLAUDE.md's
  "overweight only if the edge survives the expected FX move". A tie goes to unhedged.

Rates and returns are fractions; rate rows are percent per year as the stores publish them.

## Live inputs

| Input | Source | As of | Value |
|---|---|---|---|
| JISDOR (IDR per USD) | idxscape `fx_rate` | 2026-10-16 | 18,052 (1,213 rows since 2021-10-01) |
| JISDOR one year earlier | idxscape | 2025-10-16 | 16,580 |
| BI rate, monthly `WS_CBPOL.M.ID` | bisfetcher | 2026-09 | 5.75% (daily `.D.ID` 5.75% on 2026-10-05) |
| Fed rate, monthly `WS_CBPOL.M.US` | bisfetcher | 2026-09 | 3.875% |

## Worked example: a USD asset held one year, IDR cash at the BI rate as the alternative

- **Hedge carry** (sell USD 1y forward): (1.0575 / 1.03875) − 1 = **+1.81%**. IDR rates are higher,
  so hedging a USD asset back into IDR *earns* carry. The same number is the UIP-expected USD gain.
- **JISDOR moves:** trailing 3m +0.60%, 6m +5.02%, 1y **+8.88%** (USD up against IDR).
  The 973 overlapping 1-year changes since 2021-10: min −2.46%, 5th pct **−0.74%**, median +3.94%,
  95th pct +10.08%, max +11.40%. In five years USD never lost more than 2.5% against IDR over a year.

| USD return | FX case (USD vs IDR) | Unhedged IDR | Hedged IDR | Edge vs 5.75% | Verdict | Breakeven FX |
|---|---|---|---|---|---|---|
| 6% | UIP +1.81% | +7.91% | +7.91% | +2.16% | survives | −0.24% |
| 6% | flat | +6.00% | +7.91% | +2.16% | survives hedged | −0.24% |
| 6% | adverse (5th pct) −0.74% | +5.22% | +7.91% | +2.16% | survives hedged (unhedged fails) | −0.24% |
| 8% | adverse −0.74% | +7.20% | +9.95% | +4.20% | survives hedged | −2.08% |
| 10% | adverse −0.74% | +9.19% | +11.99% | +6.24% | survives hedged | −3.86% |

Reading: with the BI rate 1.875 points above the Fed, a USD asset only has to beat about
**3.9% in USD** to match IDR cash once hedged, because the hedge pays the carry. Unhedged, a 6%
USD asset loses its edge on a USD fall of just 0.24%.

## Caveats for later slices

- The policy-rate gap is a proxy for forward points. Real USD/IDR forwards (NDF/DNDF) price in
  money-market rates and a basis, often a wider gap than the policy rates. No sibling store has
  IDR forwards or NDF points yet, so treat the hedged return as an estimate. That data belongs in
  idxscape or bisfetcher, not here.
- The hedged formula assumes the whole end value is hedged up front. For equities, where the
  local return is unknown, it is an approximation.
- No sibling publishes JPY/EUR/SGD/AUD per USD in one place: FRED in sec-edgar has only
  `CCUSMA02IDM618N` (monthly IDR per USD), and no `DEX*` series. For `cross`, the local legs
  come from jquantster (USD/JPY), singstat (SGD), ausdata (AUD, RBA) and dbnomics/ECB (EUR),
  each from its own adapter.
- Running from a worktree: `config/sources.yaml` paths are relative to the repo's parent, so set
  `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects` or both stores read as `missing`.

Tests: `uv run pytest -q tests/test_fx.py` gives 22 passed. The full suite gives 373 passed and
1 skipped. ruff is clean.
