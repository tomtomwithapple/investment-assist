# P98, P99, P100 (PLAN S81–S83): the investing principle as rules

Date: 2026-11-10. Branch `phase-o`. Heuristic, not investment advice. The live check was
read-only (stores through the adapters; nothing written to `out/` or the journal).

## What changed

- **`candidates/diversify.py`** (S81, pure, hashed). `judge`: a name's group is its IDX-IC
  industry (idx-method `industry_membership`, 58 groups) and its size bucket (large at Rp 50T
  or more, mid from Rp 5T, small below). Order in a group: kept by a passing screen (margin),
  then ranked by one (margin), then unrated (largest holding). The first is the keeper, the
  rest are redundant. A redundant name is `allowed` only where a passed tilt favours its sector
  or industry (tilt > 0). No industry or no market cap: no group.
- **Buying (S82)**: `sizing.size` gives a row marked `redundant` no new money and lists it in
  `excluded` ("redundant with BMRI (same industry, same size: Bank, large)"). It is not trimmed
  for that. `layers/undervalued.py`: `UndervaluedInputs.profiles` (the newest membership
  snapshot on or before the run date plus the screener's market cap, read-only), a
  `diversification` block in the payload, candidates schema 1.2.0 → 1.3.0. Names the passing
  screens ranked but did not keep are sold in full by sizing, so they are in no group.
- **Rebalance sales (S83)**: `rebalance.ordered_sales`. For the part of a cut no trim covers:
  redundant names in full first (the lowest-ordered of the most crowded groups first, then the
  smallest holding), then pro rata over the other names no passing screen keeps, and the kept
  names last, only if still needed. The guide's steps say which name is the keeper and why.

## Decided by the user (2026-11-10) and defaults

- User: three size buckets by market cap; only a favourable tilt allows redundancy; a different
  size is never redundant; rebalance sales respect the rule.
- Defaults, not confirmed: the lines at Rp 50T (32 of 963 names are large) and Rp 5T (181 mid);
  the 58-group `industry` level; keeper among unrated names = the largest holding.

## Judgment calls

- The keeper of a group is not protected from the pro-rata step unless a passing screen keeps
  it: "keeper" only means it is not sold for redundancy.
- The USA list has no profiles (sec-edgar has no industry code), so no US name is judged.
- No industry tilt exists yet; `industry_tilts` is an empty hook.
- The sector tilt failed its placebo, so today no redundancy is allowed anywhere.

## Live (read-only, run of 2026-11-10, bars to 2026-11-05)

963 profiles read. 52 names judged (67 held, less the 15 sold in full on a failed screen): 4
large, 21 mid, 27 small; **16 redundant, none allowed**. Sizing's trims are unchanged.

The guide, against phase N's on the same run:

| | Phase N (pro rata) | Phase O |
|---|---|---|
| Sell steps | 54 | 51 |
| On a trim (cap, failed screen) | 16 | 16 |
| Redundant, sold in full | 0 | 16 (about Rp 7.0m) |
| Pro-rata cuts | 38 | 19 |
| Total sold | Rp 27.1m | Rp 27.1m |

Redundant names sold in full: TSPC (keeps KLBF), TAPG, SMAR, SIMP, TLDN (keep JPFA), NRCA
(PBSA), ARNA, SPTO (TOTO), IPCM (IPCC), MYOH (SICO), BTPS (BJBR), ISAT (TOWR), MCOL (GEMS), AVIA
(UNIC), AMOR (PANS), KKGI (TPMA). The portfolio would go from 67 names to 36.

## Tests

`tests/candidates/test_diversify.py` (8), `tests/candidates/test_rebalance.py` (4 new),
`tests/test_run_undervalued.py` (4 new, one version expectation), `tests/test_guide.py` (2
new). One expectation of mine was wrong (a group's keeper still takes its pro-rata share) and
was corrected to the rule as written. Full suite **2071 passed**, ruff clean.
