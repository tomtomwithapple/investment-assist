# P92-exits (PLAN S74): entry cap, take-profit and stop on candidate rows

Date: 2026-11-10. Branch `phase-n`. Heuristic, not investment advice. No run was made.

- **`candidates/exits.py`** (pure, hashed). Per row an `exits` block:
  - `entry_cap`: last close + 1%, floored to the IDX tick. The first tranche buys at market, not
    above it (choice 4, built on its default; not yet confirmed by the user).
  - `take_profit`: the fair price, where the margin over the required return (hurdle + the
    sector's tilt shift) reaches 0. Dividend screen: price × yield ÷ (required − growth).
    Reaching it means "stop adding and trim to half" (choice 5, user 2026-11-10).
  - `thesis_stop`: "sell when it fails its screen"; `review_at`: `entry_deep` when below the
    price, a flag that never sells (choice 6, user 2026-11-10).
- **`layers/undervalued.py`**: every row carries `exits`; `config.exits`; candidates schema
  1.1.0 → 1.2.0 (the field is optional, so older files still validate).
- **GARP has no take-profit**: its expected return is a reverse DCF with no closed form for the
  fair price. It is `null` with basis `none`. GARP fails its placebo today, so no row is affected.
- Changes no size and no name. The fingerprint changes because the module is under
  `candidates/`.

Tests: `tests/candidates/test_exits.py` (12), `tests/test_run_undervalued.py` (1 new, one
version expectation). One expectation of mine was wrong on the tick grid (4,950 for 4,960) and
was corrected.
