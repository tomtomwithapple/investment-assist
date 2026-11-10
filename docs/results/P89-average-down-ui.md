# P89-average-down-ui (PLAN S70): average down in Telegram, the brief and the pages

Date: 2026-11-10. Branch `phase-m`. Heuristic, not investment advice. No run was made: nothing
was sent to Telegram and nothing written to `out/` or the journal.

## What changed

- **`brief.py`**: `average_down_view(payload)` sorts S68's block for display (funded with the
  sized amount, unfunded, stopped names 5% or more below cost with the deepest first, counts by
  gate); `average_down_lines(payload)` gives the plain lines both the brief and Telegram use.
  The brief's candidates table shows `average down IDR …` in the Action cell of a funded row and
  ends with `- average down: …` bullets.
- **`pipeline.py` `trade_lines`** (Telegram): after "to buy", `IDN to average down (n):` with
  each funded name (amount, % vs cost, old → new average cost) and each unfunded name with its
  reason, then one line on the rest. With none: a single line, e.g. `IDN to average down: none:
  21 of 67 held names are 5% or more below cost (20 not kept by a passing screen, 1 no room
  under the caps)`. A market with nothing held (USA) gets no line. A funded average down is
  still listed under "to buy".
- **`/candidates`**: the row table gains `Avg cost` and `vs cost`; a new *Average down* card
  lists the names 5% or more below cost with status, average cost, price, % vs cost, new
  average cost, entry status and reason. No card when the payload has no block (a 1.0.0 file).
- **`/portfolio`**: the adds table gains `Action` and `Avg cost IDR` (old → new) and now lists
  an `average_down` row (S68 noted it would otherwise be missing); a new *Average down* table
  per market. `/portfolio.json` carries `action`, `avg_cost`, `new_avg_cost`, `below_cost_pct`
  on each add and an `average_down` list.

Names that stop at gate 1 (not 5% below cost) are counted, never listed.

## Tests

- `tests/test_brief.py` (3): none, with where the names stopped and the Telegram line; funded
  and unfunded lines and the Telegram block; nothing held, nothing underwater, no block.
- `tests/test_view_candidates.py` (2): the two columns and the card (funded, unfunded, stopped;
  gate 1 left out); no card without the block. One existing expectation gained two cells.
- `tests/test_view_portfolio.py` (1): the average down among the adds and in its own table,
  HTML and JSON. One existing JSON expectation gained the new keys.
- Code and tests were written together; the two existing expectations failed first, as
  expected, and were extended.
- Full suite **2001 passed** (baseline 1995), ruff clean. None of these files is hashed by
  `journal.RULE_GLOBS`: the model fingerprint is S68's (`sha256:aa9e0c60fe9c…`).
