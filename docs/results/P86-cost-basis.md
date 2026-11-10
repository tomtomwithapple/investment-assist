# P86-cost-basis (PLAN S67): cost basis in layer 5

Date: 2026-11-10. Branch `phase-m`. Heuristic, not investment advice. Live check read-only
(`mode=ro` URI, through the adapter) against `~/.financer/financer.db`; the file's mtime and size
were the same before and after. Account numbers are left out of this page.

## What changed

- **`sources/financer.py` `Holding`**: trailing `avg_cost` (per unit) and `cost_value`, default
  None, from `holdings.avg_cost_minor` and `cost_value_minor` (÷ 100). A printed average of 0
  (an SBN line, a right) is None for both.
- **`roll`**: a symbol's statement lines pool their cost. A buy adds its `net_minor` (amount
  paid, fees included); a sell takes cost out in proportion to the quantity sold, so the average
  stays. A position the trades open is costed from its buys. `Trade` gained a trailing `net`.
- **`layers/undervalued.py` `cost_basis_from(statements, market="IDN")`**: per symbol of the
  market's stocks (layer 5's `classify`, as `holdings_from`), `CostBasis(avg_cost, quantity)`,
  a NamedTuple equal to a plain tuple. Both names are in `__all__`.
- Nothing reads it: no payload, schema, sizing, stance, pipeline, brief or view change.

## Fingerprint

`journal.RULE_GLOBS` hashes `layers/**/*.py`, so adding the function to `layers/undervalued.py`
changes the model fingerprint with identical behaviour (`sources/financer.py` is not hashed):

- before `sha256:13d8dceb4fa3c0153af6bcf139406b54e9449851e569b171be448643a708878b`
- after `sha256:0054161d53f8d4a96a148cd9786217b41d6035eb65a4ea5ad1d40bf0b072f185`

Accepted; the new journal segment opens at the phase M fan-in run (S71), not before. The plan
said "no fingerprint change"; PLAN.md and plan.yaml are corrected.

## Judgment calls

- **Below zero.** Once a symbol's quantity goes below zero its cost is None, and stays None
  even if later buys bring it back above zero (what was sold had a cost nobody printed).
- **Trades that net to nothing.** The statement lines are kept as printed, cost included, as
  `roll` already does for their value.
- **Unknown base.** If any statement line of a symbol has no cost, the rolled cost is None, even
  after a full sell-out and a rebuy.
- **`cost_basis_from` quantity** counts only the lines with a known cost, so a symbol with
  mixed lines would report less than its holding. Live, no symbol is affected.
- **Ajaib's printed average is rounded**: CTRA 753 × 2,700 = 2,033,100 against a printed cost of
  2,033,397. `cost_basis_from` weights `avg_cost` by quantity; `roll` pools `cost_value`. The
  difference is a few hundred rupiah.

## Tests (first, red → green)

Red: the 12 new tests failed before the implementation.

- `tests/sources/test_financer.py` (10 new): a statement line keeps its cost; a printed 0 is
  None; a later buy re-averages (UNVR 100 at 2,000 + 100 for 210,000 → 2,050); a buy moves the
  average by its net amount, fees included; a sell does not move the average and cost falls with
  the quantity; a position opened by trades is costed from its buys, an unheld line has none; an
  unknown base stays unknown through a buy; two lines of one symbol pool their cost; cost is
  unknown once sold below zero; a `Holding` without cost still builds.
- `tests/test_run_undervalued.py` (2 new): two accounts weight by quantity (100 at 9,000 and
  300 at 7,000 → 400 at 7,500; bonds, USD lines and no-cost lines left out); only lines with a
  known cost are averaged.
- `tests/layers/test_portfolio.py`: `test_money_is_minor_units_over_100` compares a whole
  `Holding`, so its expectation gained `9_000.0, 900_000.0` (file added to P86's `owns`).
- No fixture file changed: `seed.sql` already had usable cost columns.
- Full suite **1958 passed** (baseline 1946), ruff clean.

## Live (statements as of 2026-11-02 and 2026-10-30)

Two accounts hold stocks: Ajaib (tommy), the 2026-10-31 statement rolled through one trade
document, 11 lines; Stockbit (priskila), 8 trade confirmations and no statement, 63 lines costed
entirely from their buys.

67 IDN stock names, all with a cost; **61 below cost**, 6 above. Total cost Rp58,905,894 against
value Rp53,697,910 (**−8.8%**). The only line without a cost is FR0080 (printed average 0);
nothing is unheld. "Last" is the statement price, or the last trade price for a traded line.

| Symbol | Qty | Avg cost | Last | vs cost |
|---|---:|---:|---:|---:|
| AMRT | 1,400 | 1,446.0 | 915 | −36.7% |
| KKGI | 19 | 370.0 | 290 | −21.6% |
| CTRA | 3,500 | 701.1 | 560 | −20.2% |
| KLBF | 3,300 | 897.0 | 730 | −18.6% |
| TOWR | 4,400 | 457.0 | 374 | −18.2% |
| ASII | 700 | 5,654.6 | 4,691 | −17.0% |
| BMRI | 1,300 | 4,243.8 | 3,609 | −15.0% |
| PWON | 9,600 | 321.2 | 279 | −13.2% |
| BBNI | 900 | 3,741.0 | 3,249 | −13.2% |
| BBRI | 600 | 2,713.4 | 2,460 | −9.3% |
| TPMA | 1,700 | 387.2 | 356 | −8.1% |
| TAPG | 400 | 1,799.5 | 1,665 | −7.5% |
| ERAA | 1,200 | 528.8 | 490 | −7.3% |
| ASSA | 1,400 | 498.6 | 464 | −6.9% |
| ICBP | 300 | 5,901.4 | 5,550 | −6.0% |
| NRCA | 1,600 | 435.9 | 410 | −5.9% |
| MSTI | 200 | 1,243.0 | 1,170 | −5.9% |
| GEMS | 200 | 7,149.8 | 6,750 | −5.6% |
| SICO | 5,400 | 102.7 | 97 | −5.6% |
| PBSA | 3,100 | 311.3 | 296 | −4.9% |
| HRTA | 200 | 1,494.7 | 1,435 | −4.0% |

- 40 more names are 0.1–0.5% below cost: Stockbit lines valued at their own last trade price,
  so the gap is roughly the buy fee.
- Above cost: BISI +0.2%, LSIP +0.5%, ISSP +0.5%, ARNA +0.6%, IPCM +1.1%, SIMP +1.4%.

Cross-check against a direct read-only query of `holdings` (Ajaib, 2026-10-31):

- Single-account names match the printed average: AMRT 1,446, KLBF 897, KKGI 370, MSTI 1,243.
- Names in both accounts blend: BMRI 4,457 × 1,000 → 4,243.8 over 1,300; ASII 6,145 × 500 →
  5,654.6 over 700; CTRA 753 × 2,700 → 701.1 over 3,500.
- FR0080 is printed with average 0 and cost 0, read as None.

## Where the plan was wrong (corrected in S67)

- "No fingerprint change": it changes (above).
- Phase M's "nine holdings 16–37% below cost" and "BMRI −16.5%" were the Ajaib statement alone.
  Over both accounts six names are 16% or more below cost and BMRI is −15.0%.
