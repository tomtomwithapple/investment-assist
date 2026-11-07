# P62-rebalance-split (PLAN S42): rebalance vs tilt

Date: 2026-11-07. Heuristic, not investment advice.

## What changed

- **Stance payload** (`stance.py`, schema 1.0.0 → **1.1.0**): `portfolio.rebalance_pt` and
  `portfolio.tilt_pt`, both optional in `schema/stance.schema.json`, so 1.0.0 payloads still
  validate (tested). Every existing field and value is unchanged (`target_pct`, `delta`, `entry`,
  `benchmark_pct`). No change to targets, bands, tilt, benchmark, the pro-rata rule or the
  3 × 10-day ladder.
  - `tilt_pt` = (target − benchmark before the pro-rata cap) × the cap's scale, rounded to 0.1 pt.
  - `rebalance_pt` = (target − current) − `tilt_pt`, i.e. the scaled benchmark share − current
    to within 0.1 pt.
  - **Why this choice:** the cap's largest-remainder rounding (±0.1 pt) goes into the
    rebalance part, not the tilt, so a neutral leg always shows a 0 tilt, and
    `rebalance_pt + tilt_pt = target − current` exactly. Example under scaling (all neutral but
    USA overweight, 105 → 100): IDN stocks 96.9 → 45.7 = −51.2 rebalance, 0.0 tilt; USA
    0 → 23.8 = +19.0 rebalance, +4.8 tilt.
  - Outside the mandate: benchmark 0, so rebalance = −current and tilt = 0. Holdings
    unavailable: both null.
  - `stance.split_text(pf)` gives "−51.2pt = −48.9pt rebalance to benchmark, −2.3pt tilt", and
    `stance.BENCHMARK_TEXT` gives "48/32/20". All views and the brief use these two.
- **Brief** (`brief.py`, not `paper_lines`): each Delta cell gets the split after it, and a
  "Rebalance vs tilt: …" line under the Targets line says the rebalance part is a move to the
  48/32/20 benchmark, not a model call. Payloads without the split render as before, so the
  golden brief is unchanged.
- **/portfolio**: the stance rows show the split under the delta when the gap is not zero.
  **/stance**: the portfolio card gets a "Rebalance vs tilt" row.
- **Telegram**: `notify.header(day)` puts the title, then the disclaimer, then
  `notify.PAPER_LINE`. `notify.leg_line(stances, market)` labels each market's sized list
  with its stocks leg's split. `pipeline.message` and `trade_lines` take `stances`.

### Files outside `owns` (minimal edits)

- `src/assist/pipeline.py`: `message(..., stances=())` uses `notify.header` and passes stances to
  `trade_lines`, which puts the leg label in front of each market. `run` passes `res.stances`.
- `src/assist/cli.py`: `assist brief --send` passes `loaded.stances` to `pipeline.message`.
- `src/assist/layers_out.py` and `schema/layers/portfolio.schema.json`: the `portfolio.json`
  stance rows carry `rebalance_pt` and `tilt_pt` as optional fields, so /portfolio can show them.

## Live run (worktree out/, `ASSIST_SIBLINGS_ROOT=/Users/tommy/Projects`, `--no-send`)

Today all three mandate legs are **neutral** (USA stocks fell back from overweight). The targets
therefore sum to exactly 100, no pro-rata scaling applies, and every point of each move is a
rebalance:

| Leg | Now → target | Delta | Rebalance | Tilt |
|---|---|---|---:|---:|
| IDN stocks | 96.9% → 48% | −48.9pt trim over 3 tranches | −48.9pt | +0.0pt |
| IDN bonds | 1.8% → 32% | +30.2pt over 3 tranches | +30.2pt | +0.0pt |
| USA stocks | 0% → 20% | +20.0pt over 3 tranches | +20.0pt | +0.0pt |

(The −51.2 / +28.7 / +23.8 from 2026-11-06 came from USA overweight with ×0.952 scaling. Under
this slice's rule that would read −51.2 rebalance / 0 tilt, and +19.0 rebalance / +4.8 tilt for
USA.)

### Telegram preview (built by `pipeline.message`, not sent)

```
investment-assist 2026-11-07
Heuristic, not investment advice.
Paper only, not an order. Sizes rebalance to the 48/32/20 benchmark plus the model tilt; read the brief.

Undervalued IDN (dividend_value 1; garp failed):
  BMRI  dividend_value #1 margin +4.1pt, held
...
IDN stocks leg (paper): -48.9pt = -48.9pt rebalance to benchmark, +0.0pt tilt
IDN to sell (16, IDR 17.1m):
...
USA stocks leg (paper): +20.0pt = +20.0pt rebalance to benchmark, +0.0pt tilt
USA to sell: none
USA to buy: none (IDR 11.1m budget unspent)
```

## Tests

15 new tests: 8 in test_stance (the split sums to the gap with and without scaling, outside the
mandate, null holdings, a 300-case random mix, old and new payloads against the schema, and
`split_text`), 4 in test_notify (paper line, header order, leg labels, and `pipeline.message`
end to end), 1 in test_brief, and 2 in test_view_portfolio (the /portfolio rows, and the
/stance row, because test_view_stance.py is outside this slice). One existing exact-dict
assertion in test_stance gained the two new keys.
`uv run pytest -q`: 1620 passed, 1 skipped. `uv run ruff check .`: clean.

## Note

The journal fingerprint hashes the rule modules' raw bytes until P61 lands, so this slice's
edits to stance.py open a new model segment, although no rule changed.
