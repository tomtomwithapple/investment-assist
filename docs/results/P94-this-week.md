# P94-this-week (PLAN S76, with S77 and S79): the guided home page

Date: 2026-11-10. Branch `phase-n`. Heuristic, not investment advice. No run was made.

- **`/` is "This week"** (`views/guide.py`, reads `out/guide.json`):
  - the regime in plain words and one sentence: how many to sell and buy, in how many parts;
  - "Your portfolio against its usual shares": per leg what you hold, the target, the view in
    plain words and what closes the gap;
  - "Orders by date": one block per tranche date, the first open, the later ones folded. Each
    order: number, name, shares, price instruction, amount, strength (its meaning on hover),
    why, and a link to the evidence;
  - "After you buy": take-profit and stop for each named buy;
  - a missing or invalid file is a notice, never a 500. The `.json` twin is the file as read.
- **The old overview is `/background`**, with one line saying only three legs are in the
  benchmark and the rest are context.
- **Navigation (S77, P95; choice 9 on its default)**: This week, Portfolio · Why: Candidates,
  Regime, Signals, Industries · Track record: Paper, Journal, Status · More: Flows, Background.
- **One place per fact (S79, P97)**: `/candidates` keeps the two cost columns and one line
  linking to `/portfolio`, where the Average down table lives. Style headings read "Dividend
  screen `dividend_value`" with the meaning on hover.

Not done in this slice: plain wording on `/signals`, `/portfolio` trim reasons and the stance
pages. They still show the raw terms.

Tests: `tests/test_view_guide.py` (6), `tests/test_view_candidates.py` (1 new, 1 changed),
`tests/test_web.py` (2 changed for the new navigation), `tests/test_view_overview.py` (moved to
`/background`), `tests/test_ui_e2e.py` (`/background` added). Full suite **2053 passed**, ruff
clean.
