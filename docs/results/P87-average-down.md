# P87-average-down (PLAN S68): the average-down rule

Date: 2026-11-10. Branch `phase-m`. Heuristic, not investment advice. Live check read-only
(stores read through the adapters; nothing written to `out/` or the journal).

## What changed

- **`candidates/average_down.py`** (pure). `judge` gives one verdict per held name: status
  `average_down`, `unfunded` or `stopped`, the gate it stopped at and the reason. Gates, with the
  user's three choices of 2026-11-10:
  1. Underwater: price 5% or more below the average cost (`UNDERWATER_PCT`, choice 3).
  2. Thesis intact: kept by a placebo-passing screen with `net_margin_pt` > 0; otherwise the
     reason is sizing's trim or exclusion.
  3. Entry status: **context only** (`GATE3 = "context"`, choice 2; S69 came back
     insufficient). It is reported and stops nothing.
  4. Room: sizing's own conditions (`vol_1y`, price, turnover, a place under the sector cap by
     margin, holding below the per-name cap), or sizing's exclusion when it had a budget.
  5. Money: sized by sizing. With no budget the name is `unfunded`, sized 0 (choice 1).
  6. Timing: sizing's schedule; `limit_tranches` limits the later tranches at `entry_typical`
     where below today's price (no `entry_deep`).
- **`layers/undervalued.py`**: `assemble(..., cost_basis=)`. Every row gains `cost_basis`
  (`avg_cost`, `quantity`, `below_cost_pct`, `new_avg_cost`) and `average_down` (`status`,
  `gate`, `reason`), both null when not held. A funded one's row gets action `average_down`.
  The payload gains an `average_down` block with every held name's verdict, a row or not, and
  `config.average_down`. `SCHEMA_VERSION` 1.0.0 → 1.1.0.
- **`schema/candidates.schema.json`**: action enum gains `average_down`; the row's two fields
  and the top-level block are optional, so a 1.0.0 file still validates.
- **`pipeline.py`**: passes `cost_basis_from(statements, market)`; the `undervalued` journal
  record carries the `average_down` block, and each `undervalued_row` record its row's fields.
  `journal.py` needed no change.

The label changes no amount: sizes, trims and the budget are sizing's, untouched.

## Judgment calls

- **`cost_basis`, not `cost`.** The plan named the block `cost`, which the row already uses for
  the execution cost.
- **`new_avg_cost`** assumes every tranche fills at today's price and adds the 15bp buy fee, as
  financer's `roll` counts a buy. A tranche that fills at its limit gives a lower average.
- **Unfunded rows keep action `hold`.** Only a sized one is `average_down`; "unfunded" is in the
  row's `average_down.status` and the top-level block, for S70 to show.
- **Price of a held name that is not a row**: the factor table's, else statement value ÷
  quantity.
- **Entry status is known only for the screens' candidates** (`entry_plan` runs on those), so a
  name stopped at gate 2 for not being rated shows no status.
- **`views/portfolio.py` lists a buy only when action is `add`.** A funded average down would be
  missing there until S70 (P89 owns that file). None is funded today.
- `tests/test_run_undervalued.py` gained the integration tests; added to P87's `owns`.

## Fingerprint

`candidates/**` and `layers/**` are hashed: `sha256:8aeca8e62547…` → `sha256:aa9e0c60fe9c…`.
This one is a real model change (a new action). No run was made, so the journal segment still
opens at the fan-in run (S71).

## Tests

- `tests/candidates/test_average_down.py` (16): the user's choices; one case per gate (fee-sized
  gap, exactly 5%, no cost basis; trim reason, not kept, no screen passed; `avoid` stops
  nothing; per-name cap, sector cap and a tilted cap, unknown liquidity, sizing's exclusion; no
  budget and an `avoid` stance; all gates clear with the new average); tranche limits; one
  verdict per held name.
- `tests/test_run_undervalued.py` (4): unfunded under no budget with the row and block fields;
  funded is `average_down` with the same size as a plain add and `entry_typical` limits; entry
  status `avoid` does not stop it; no cost basis, no average down. All payloads schema-valid.
- The module and its tests were written together (no separate red run); one integration test
  failed first on its own fixture numbers and was corrected.
- Full suite **1995 passed** (baseline 1975), ruff clean.

## Live (run of 2026-11-09, bars to 2026-11-05, regime risk_off)

IDN stocks 96.9% against a 48.0% target, so the budget is 0. 67 held names: 46 stop at gate 1,
20 at gate 2, 1 at gate 4. **No name is an average down, funded or unfunded.** Sizes, trims and
row actions are identical to the last run's `out/candidates/IDN.json`; the payload validates.

| Symbol | vs cost | Entry status | Stops at | Reason |
|---|---:|---|---|---|
| BMRI | −15.2% | deep | 4 room | at or over the per-name cap of 5% |
| AMRT | −35.0% | | 2 thesis | trim in full: fails its screen |
| PWON | −19.7% | | 2 thesis | trim in full: fails its screen |
| BBNI | −11.3% | avoid | 2 thesis | trim in full: fails its screen |
| ELSA | −8.4% | deep | 2 thesis | trim in full: fails its screen |
| CPIN | −7.2% | avoid | 2 thesis | trim in full: fails its screen |
| ERAA | −6.6% | | 2 thesis | trim in full: fails its screen |
| BFIN | −5.5% | buy_zone | 2 thesis | trim in full: fails its screen |
| HRTA | −5.3% | | 2 thesis | trim in full: fails its screen |
| KKGI, CTRA, KLBF, TOWR, ASII, TPMA, TAPG, ASSA, NRCA, MSTI, GEMS, SICO | −21.6% to −5.6% | | 2 thesis | held, not rated by any passing screen: no trim call |

BMRI is the only underwater name a passing screen keeps, and it is already over the 5% cap, as
the plan expected. The percentages use the last bar (2026-11-05), so they differ a little from
P86's statement prices (21 names at 5% or more below, against 19 there).
