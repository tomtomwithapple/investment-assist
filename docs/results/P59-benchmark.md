# P59-benchmark — results

PLAN S39: the whole portfolio gets one benchmark, decided by the user on 2026-11-06, and every
stance's target becomes a share of one plan that sums to at most 100%. Heuristic context, not
investment advice; the tax lines are not tax advice.

## Rule

- `stance.BENCHMARK_PCT` = IDN stocks 48, IDN bonds 32, USA stocks 20. Its keys are the mandate
  (`stance.MANDATE`).
- **In the mandate:** target = clip(benchmark + `TILT_PT[stance]`) (±5 pt, neutral 0), `avoid` → 0.
  A driver names it: `benchmark 48%, tilt +0pt (neutral)`.
- **Outside the mandate** (46 of 49 stances): the stance, score, drivers and risks stay as
  they were. The target is 0%, and the driver `outside the 80/20 mandate: target 0%` is added.
  The delta is a trim when something is held, else `0.0pt hold`.
- **Currency stances:** IDN currency and the foreign currencies are views on the currency, not
  allocations. Before this slice they anchored on the holding, which is always 0 because cash
  maps to `cash`, not `currency`, so they showed 0 → 0 (or 0 → 5 when overweight). They now
  target 0% with the driver `a currency view, not an allocation: target 0% (the cash rest is
  IDR)`.
- **Portfolio pass:** `stance.apply_limits(stances)` runs from `pipeline.build` after every
  stance is built and before schema validation.
  - If the mandate legs' targets sum above `MANDATE_CAP_PCT` (100), each leg is scaled pro rata
    in 0.1 pt steps by largest remainder, so the rounded legs sum to exactly 100.0.
  - Each scaled leg gets a driver (`mandate targets sum 105.0%: scaled ×0.952 pro rata to 100%
    (48.0% → 45.7%)`), and its delta and entry are recomputed with the same `_delta_text` the
    per-stance build uses.
  - Scaling only lowers a target, so an add keeps its style (lump, ladder or the rule's entry)
    with a smaller size. One whose gap drops to ≤ 0 becomes `none` with a trim or hold.
- **Transition ladder** (user, 2026-11-06, added before merge): after the scaling, any
  mandate leg more than `TRANSITION_PT` (10 pt) from its target gets `entry = ladder`
  (`LADDER_TRANCHES` 3 × `LADDER_SPACING_DAYS` 10) for adds and trims alike. The delta reads
  `+28.7pt over 3 tranches` or `-51.2pt trim over 3 tranches`, and a driver says "move of
  51.2pt to target is above 10pt: laddered over 3 tranches". A move of 10 pt or less keeps the
  per-stance logic: a ladder under risk_off or a gated rule, else a lump add, and a trim is
  `none`. Outside-mandate trims are not laddered.
  - **Schema:** no enum change. The entry style's description now says the direction is the
    sign of `portfolio.delta`, so a `ladder` with a negative delta is a laddered trim.
  - **Brief:** shows it as "ladder 3×10d" next to the "… trim over 3 tranches" delta.
  - **`/portfolio`:** lists the stance as active, with a ladder entry.
  - **S20a sizing:** only reads the entry when there is a budget (an add). The USA add is
    therefore split over 3 tranches. The IDN stocks trim has no budget, and its per-name trims
    are still listed as amounts. Spreading them over the 3 tranches is left to whoever executes
    them; sizing does not schedule trims.
  - **Fingerprint:** `TRANSITION_PT` is in `MODEL_CONFIG` as `transition_pt`.
- **US estate tax:** the USA stocks stance always carries a risk line: "US estate tax: US-situs
  assets above US$60k held by a non-resident are exposed (heuristic, not tax advice;
  Ireland-domiciled UCITS ETFs avoid it)" (`stance.LEG_RISKS`).
- **Model version and fingerprint:** `MODEL_VERSION` 0.3.0 → 0.4.0. `MODEL_CONFIG` gains the
  benchmark, `mandate_cap_pct`, `outside_mandate_target_pct` and the scale method. The new
  fingerprint opens a new journal segment, and no old journal record was touched.

## Contract

- `schema/stance.schema.json` gains an optional field, `portfolio.benchmark_pct`: 0 outside the
  mandate, absent in payloads before 0.4.0. `schema_version` stays 1.0.0, as P53 did when it
  added `portfolio.notes`.
- `schema/layers/portfolio.schema.json`:
  - each stance row gains an optional `benchmark_pct`;
  - an optional `mandate` block is added: `benchmark_pct`, `targets_pct` per leg,
    `target_sum_pct` over all stances, and `cash_pct` = 100 − sum.
- `layers_out.portfolio_payload` writes both. `stance.mandate_summary` works on stance payloads
  and on layer rows alike.

## Where it shows

- **Brief:** a line under the Stances table, e.g. `Targets: IDN bonds 30.5% + IDN stocks 45.7%
  + USA stocks 23.8% = 100%; cash rest 0%. Benchmark …; every other stance is outside the 80/20
  mandate and targets 0%.`
- **`/portfolio`:**
  - the old note ("the targets need not add up to 100%") is replaced by the sums, the cash
    rest and the benchmark;
  - the cash asset-class row shows the cash rest as its target;
  - the mandate is read from the file's `mandate` block, or worked out from its rows when the
    file predates S39.
- **`/stance/<S>/<a>`:** a Benchmark row (`32%`, or `0% (outside the 80/20 mandate)`), shown
  only when the field is present.
- **S20a sizing** and the undervalued lists read `target_pct − current_pct` as before, so they
  follow the new targets without a code change (docstring updated). The 5% per-name cap is
  unchanged.

## Live run (2026-11-06, worktree, `assist --siblings-root /Users/tommy/Projects run --no-send`)

The run used `--no-send` ("telegram: not sent (--no-send)"). It wrote only this worktree's
gitignored `out/`, `data/` and `journal/`.

Files under `/Users/tommy/Projects` that changed during the run, outside this repo:
- idx-method `stockbiter.db-shm`: SQLite's shared-memory file, touched by any read-only open in
  WAL mode; the db and its WAL are unchanged;
- sec-edgar `usfin-serve.log`: its server logging our GETs;
- jquantster `jquantster.db` and `sync.log`: its own sync job ("Done: 19 calls"), which we
  never call.

49 stances, all model 0.4.0, fingerprint
`sha256:7822bcfd80e492f8dd74c8299157df3d3abae0595c4b783ea6be8e8930720e6a (with the transition ladder; the first run without it was `0866f88bb5…`)`. Regime neutral.

| Leg | Stance | Benchmark | Raw target | Scaled target | Current | Delta | Entry |
|---|---|---:|---:|---:|---:|---|---|
| IDN stocks | neutral | 48 | 48 | 45.7 | 96.9 | −51.2pt trim over 3 tranches | ladder 3×10d |
| IDN bonds | neutral | 32 | 32 | 30.5 | 1.8 | +28.7pt over 3 tranches | ladder 3×10d |
| USA stocks | overweight | 20 | 25 | 23.8 | 0.0 | +23.8pt over 3 tranches | ladder 3×10d |

- **Mandate:** raw sum 105, scaled ×0.952 to 45.7 + 30.5 + 23.8 = **100.0%**; cash rest
  **0.0%**. Sum over all 49 stances: 100.0.
- **Outside the mandate:** 46 stances at 0%, with **0 trims**. Nothing is held outside IDN; the
  IDR cash of 1.31% has no stance.
- **S20a budget:** IDN Rp0 (target below the holding, so trims only: 10 trims), USA
  Rp13,188,871 (23.8% of Rp55.4M; unspent, as USA has no names yet).
- **Pages:** `/portfolio` 200 (58.5 kB) and `.json` 200. The weights card reads "Targets: IDN
  bonds 30.50% + IDN stocks 45.70% + USA stocks 23.80% = 100.00% of the household; cash rest
  0.00%"; the cash row reads current 1.31%, target 0.00%. `/stance/JPN/stocks` shows "0%
  (outside the 80/20 mandate)".
- **Entry:** all three moves exceed `TRANSITION_PT`, so all three are laddered 3 × 10 days,
  including the IDN stocks trim. The first live run, before the transition rule, had lump adds
  and a trim with entry `none`, because the regime is neutral.

## Tests

- **New, in `tests/test_stance.py`:**
  - outside the mandate (view kept, target 0, trim when held, hold when not);
  - a currency view;
  - the estate-tax risk on USA stocks only;
  - all three legs overweight: 53 + 37 + 25 = 115 → 46.1 / 32.2 / 21.7 = 100, with IDN stocks
    trimmed and USA lump;
  - a scaled ladder keeps its tranches;
  - IDN stocks underweight alone: 43 + 32 + 20 = 95, cash 5;
  - `mandate_summary` on layer rows;
  - a property test with 400 random mixes: 3 legs × {overweight, neutral, underweight, avoid},
    5 outside-mandate stances always overweight, random holdings and regimes. It checks that the
    sum of targets is between 0 and 100, that outside targets are 0 with trim or hold, that an
    underweight or avoid with no overweight leg leaves cash, and that entry is `none` exactly
    when the gap is ≤ 0.
- **Changed on purpose:** these assumed the old anchor-on-holdings rule.
  - `test_stance.py`: overweight now anchors on the benchmark (32 + 5 against 8 held); the
    neutral hold is at 32 held; the underweight trim and avoid exit are at 32 held; the
    "never below zero" test passes its own 2% benchmark.
  - `test_run_idn.py::test_rule_view_with_a_passed_stance…`: the delta is +29.0pt (37 − 8), not
    +5.0.
  - `test_run_foreign.py::test_usa_stocks_idr_edge…`: the risks are the estate-tax line, not
    `[]`.
  - `test_view_portfolio.py`: the cash row's target is the cash rest, not "-", and the old
    "need not add up" note is gone. A new test covers a file with a `mandate` block.
  - `tests/fixtures/brief/expected.md`: regenerated; the only change is the Targets line.
- **Extended:** `test_layers_out.py` (mandate block, `benchmark_pct` on rows) and
  `test_view_stance.py` (Benchmark row).
- **Transition tests:** `test_moves_above_transition_pt_are_laddered_adds_and_trims` covers
  +28.7 → ladder, −51.2 → laddered trim, +9.9 → lump, −9.9 and −10.0 → trim with `none`.
  `test_transition_ladder_is_fingerprinted` and `test_outside_the_mandate_trims_are_not_laddered`
  are new as well. The 115 → 100 test now expects both large moves laddered. The scaled-ladder
  test now uses a 7.2 pt risk_off add, so it still exercises the old path. The 400-mix property
  test now checks for a ladder whenever a leg's |gap| > 10, and the old none ⇔ gap ≤ 0 rule
  otherwise.
- **Totals:** 1592 passed, 1 skipped; ruff clean.
