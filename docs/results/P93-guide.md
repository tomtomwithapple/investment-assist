# P93-guide (PLAN S75, with S73 and S78): this week's steps

Date: 2026-11-10. Branch `phase-n`. Heuristic, not investment advice. The check below was
read-only on the run of 2026-11-10 (`out/`); nothing was written there.

## What changed

- **`plain.py`** (S73, P91): one table of raw term → plain label and one-line meaning for
  regime, dollar, stance, style and strength; `leg("IDN", "stocks")` → "Indonesian stocks".
  "neutral" is both a regime and a stance, so lookups name the kind.
- **`candidates/rebalance.py`** (hashed; choice 1, user 2026-11-10): `pro_rata_sales`. The part
  of a leg's cut that sizing's trims do not cover is sold pro rata over the held names with no
  trim call, in whole lots; the rounding leftover goes one lot at a time to the largest holdings
  first, never past the need or the holding.
- **`guide.py`** (pure): `build(day, stances, candidates, fingerprint)` → `out/guide.json`
  (`schema/guide.schema.json` 1.0.0). Per benchmark leg: sell steps (trims, then the pro-rata
  rebalance), buy steps (sized rows with entry price per tranche, take-profit, stop), bucket
  steps for a leg no name carries ("Buy SBN", "Buy a US broad-market index fund"; choices 2 and
  3, user 2026-11-10). Each step: amount, shares, dated tranches, strength, one sentence of why,
  a link to the evidence. Sells first, strongest and largest first.
- **`pipeline.py`**: `write_guide` (never fails the run), one `guide` journal record, the brief
  opens with a "This week" section and the Telegram message with "This week:" and the first 12
  steps (S78, P96).

## Defaults used, not yet confirmed by the user

- Choice 7, strength: a cap trim is strong; a trim on a failed screen, a rebalance sale, a
  sized buy and a bucket step are medium.
- Choice 8, dates: tranche 1 on the next weekday after the run, later ones `spacing_days`
  apart, moved off a weekend. IDX holidays are not known here.
- `MIN_STEP_IDR` Rp 100,000: a leftover below it is not a step.

## Judgment calls

- A trim smaller than one lot is dropped (nothing to place).
- A full exit sells the whole quantity, odd lot included, in the last tranche.
- A single-lot sale is one order, not three.
- Shares need a price: held names take it from S68's `average_down` block, so a 1.0.0
  candidates file gives amounts without shares.
- `guide.py` is outside `journal.RULE_GLOBS`: it picks no name and no amount. Those come from
  sizing and `rebalance`, which are hashed.

## Live (read-only, run of 2026-11-10, risk_off, 3 tranches: 11-11, 11-23, 12-01)

- 54 sell steps, **Rp 27.1m**, equal to the Indonesian stocks gap (96.9% → 48%).
  - 1 strong: BMRI, Rp 1.8m (500 shares), down to the 5% cap.
  - 15 medium on a failed screen (BBNI Rp 3.0m, PWON Rp 2.5m, ICBP Rp 1.8m, BBRI Rp 1.6m, ...).
  - 38 medium pro-rata rebalance sales, Rp 0.05m–1.5m each; 20 of them are a single lot.
- 2 buy steps, Rp 27.8m: SBN Rp 16.7m and a US broad-market index fund Rp 11.1m, each in 3.
- No named buy, so no take-profit or stop is shown today.
- The payload validates against its schema.

The list is long because the portfolio holds 67 names, many of one or two lots. The home page
groups it by order date.

## Tests

`tests/test_guide.py` (14), `tests/candidates/test_rebalance.py` (4), `tests/test_plain.py`
(3). `tests/test_run_e2e.py`: three expectations extended for `out/guide.json` and its journal
record. Tests and code were written together; two of my own expectations were wrong first (a
leftover lot in the pro-rata test, the plain-words clash on "neutral") and the second was a real
bug, fixed.
