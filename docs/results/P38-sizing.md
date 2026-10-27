# P38-sizing: PLAN S20a, position sizing

`src/assist/candidates/sizing.py`; tests in `tests/test_sizing.py` (20 tests, pure, no store).

## What it does

`size(candidates, stance, portfolio_value_idr, holdings, regime, caps=None, entry=None) -> Sizing`
returns `sizes` (`Size(symbol, idr, tranches, reason)`), `trims` (`Trim(symbol, idr, reason)`),
`excluded` (symbol, why), `budget_idr`, `unspent_idr` and the sizing `fingerprint`.

- **Budget** = (`target_pct` − `current_pct`) of the market's stocks stance payload × portfolio
  value. `underweight` / `avoid`, or a target at or below the holding, gives a budget of 0. Only
  trims are returned in that case.
- **Split** ∝ `margin_pt / vol_1y`. A name that fails its screen (`passes` False), has a margin
  ≤ 0, or has no `vol_1y`, price or `med_value_60d` is excluded, and the reason is recorded.
- **Caps**, in this order:
  1. Sector: at most `sector_names` names per sector, best margins kept. This is an int, or a dict by
     sector so S16's tilted 3..7 caps can be passed in. The default is 5.
  2. Per name: `name_pct` (5%) of the portfolio, minus what is already held.
  3. Liquidity: tranches × `max_participation` (costs.py's 10%) × `med_value_60d`.

  Allocations above a cap are clipped, and the excess goes **once**, by weight, to the names still
  under their cap. Anything left after that stays unspent.
- **Tranches**: a ladder when the stance's `entry` is a ladder (its count and spacing) or when the
  regime is `risk_off` (S5's 3 × 10 days). Otherwise one lump. Each tranche is rounded down to whole
  IDX lots at today's price. It is then checked with `costs.cost_for`: a name flagged
  `below_one_lot` (or `over_participation`) is dropped, and its money is left unspent. With
  `entry.entry_plan` output, tranches 2.. carry `entry_typical` and then `entry_deep` as limit
  prices, where these are below today's price.
- **Trims** are returned for any stance. A held name is trimmed in full if it is not in the
  candidate list, fails its screen, or has a margin ≤ 0. A held name above the per-name cap is
  trimmed back to the cap.
- **Fingerprint**: `config(caps)` = `{sizing_version, caps, ladder}`, hashed with
  `stance.model_fingerprint`. `journal.RULE_GLOBS` already hashes `candidates/*.py`.
  `CAPS = {name_pct: 5.0, sector_names: 5, max_participation: 0.10}` are starting values. They
  wait on the user's weight bands (PLAN Open questions), so sizes stay paper until those are
  confirmed.

## Worked example (2026-10-27)

The factor rows are real: idx-method `load_factors()` read-only gave 977 names with no stale
inputs (idx-method HEAD `71ef6ed`). The **margins and sectors are illustrative**. S20 (F5), which
joins the P36/P37 margins to these rows, is not built yet.

| Symbol | Sector | margin_pt | price | vol_1y | med_value_60d (IDR) |
|---|---|---|---|---|---|
| BBCA | Banks | 3.0 | 4,940 | 0.339 | 715bn |
| BBRI | Banks | 5.0 | 2,910 | 0.313 | 524bn |
| BMRI | Banks | 4.0 | 3,910 | 0.328 | 515bn |
| TLKM | Infrastructure | 2.5 | 2,250 | 0.440 | 273bn |
| ASII | Industrials | 1.5 | 4,560 | 0.408 | 209bn |
| PTBA | Energy | 6.0 | 3,220 | 0.316 | 65.7bn |
| ITMG | Energy | 4.5 | 25,200 | 0.278 | 33.2bn |
| UNVR | Consumer | −1.0 | 1,425 | 0.458 | 20.9bn |

**Live stance (C).** `out/IDN/stocks.json` (as of 2026-10-23) is `neutral`, with current = target
= 60.4%. The budget is 0, so there are **no adds today**.

**A: the real portfolio value (IDR 29,617,701, P4) under a hypothetical overweight 60.4 → 65.4,
neutral regime.** The budget is IDR 1,480,885, which is also the 5% per-name cap. Only PTBA (1 lot,
IDR 322,000) can be bought. The other six names each get less than one lot (for example BBRI IDR
289,825 against a lot of IDR 291,000), so they are dropped. IDR 1,158,885 is left unspent. UNVR is
excluded for its margin. *Finding:* at this portfolio size, lot granularity decides the result,
not the split.

**B: IDR 1bn, overweight 10 → 20, risk_off, Banks capped at 2 names.** Holdings are BBRI 30M,
UNVR 8M and GGRM 5M. The budget is IDR 100M.

| Symbol | IDR | Tranches (day: shares) | Why |
|---|---|---|---|
| PTBA | 26,082,000 | 0/10/20: 2,700 each | margin 6.0 / vol 32% |
| ITMG | 22,680,000 | 3 × 300 | margin 4.5 / vol 28% |
| BBRI | 19,206,000 | 3 × 2,200 | per-name cap (50M − 30M held) |
| BMRI | 16,422,000 | 3 × 1,400 | margin 4.0 / vol 33% |
| TLKM | 7,425,000 | 3 × 1,100 | margin 2.5 / vol 44% |
| ASII | 4,104,000 | 3 × 300 | margin 1.5 / vol 41% |

- **Excluded:** BBCA (over the Banks cap of 2 names; it has the lowest bank margin) and UNVR (its
  margin is −1.0).
- **Trims:** UNVR IDR 8,000,000 (margin ≤ 0) and GGRM IDR 5,000,000 (not in the candidate list).
- **Unspent:** IDR 4,081,000, from rounding down to whole lots. Most of it is ITMG, whose lot is
  IDR 2.52M.
- No tranche comes near the 10% participation limit. The tightest is PTBA, at 8.7M against a
  6.57bn limit.

## Findings and notes

- Money dropped for `below_one_lot` is not redistributed. The notes say "redistributed once, then
  left unspent" for caps, and a lot drop is applied after that one pass. For a small portfolio
  like the live one, F5 may want to pre-filter names whose share is under one lot, or show the
  unspent amount clearly.
- A name with no `med_value_60d` is excluded (liquidity unknown) rather than charged as thin.
  `cost_for` would not flag its participation.
- `holdings` is IDR per symbol for that market. P4's `Portfolio` keeps buckets only, so F5 has
  to pass the per-symbol values from financer's statement lines.
- Sibling check: idx-method's recent log (store import after every fetch) does not change the
  factor columns this uses (`price`, `vol_1y`, `med_value_60d`, `amihud`).
