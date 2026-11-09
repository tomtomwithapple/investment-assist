# P77-override-gate (PLAN S59): the layer-2 override gate per subject × asset × side

Date: 2026-11-09. Branch `phase-l`. Phase L choices 1, 3–8 and 10 (accepted 2026-11-09).
Heuristic, not investment advice.

## What changed

- **`src/assist/eval/override_gate.py`** (new, under the model fingerprint's `eval/**`). It
  reuses `placebo.evaluate`, `placebo.edge`, and phase K's `gate._state` / `gate._effective`.
  They are imported, not forked.
  - **Sides** (choice 1):
    - up: shift > 0 (on) against ≤ 0 (off), direction +1;
    - down: shift < 0 (on) against ≥ 0 (off), direction −1.

    Each is gated on its own (`feature`).
  - **Months and window** (choices 4, 5): complete months only (`OverrideRow.complete`); an
    incomplete one is a no_call. The window runs from the first complete month to the last
    month with that asset's forward return.
  - **Numbers** (choice 3): horizon / stride / block 3, `MIN_N` 10, `T_MIN` 2.0, `ALPHA` 0.05,
    1,000 shuffles, 20 controls, `SEED`. All are phase K's, unchanged.
  - **Holm** (choice 6, `holm`): step-down over the subject's tests (IDN: 6). A test without a
    full sample counts p = 1. `combine` fails a placebo pass that Holm does not confirm.
  - **CLI zeroed** (choice 10, `zeroed_shift`): the CLI's points come out of the uncapped sum
    before the ±10 cap. The same test runs on that, with its own Holm family. A side passes
    only if it passes both ways.
  - **Live monitor** (choice 7): the journal's `overrides` records with this override
    fingerprint, from `since` to the day before the run, the last record in a month standing
    for it.
    - They are priced on the history's own forward return for that month.
    - The live family gets Holm too.
    - Revocation is phase K's: ≥ 5 live windows per side and signed t ≤ −1.0.
  - **Fingerprint** (choice 8, `override_fingerprint`): AST without docstrings of
    `layers/overrides.py` (IDN) or `layers/overrides_foreign.py` (foreign), `layers/types.py`,
    `override_history.py`, plus the gate's numbers. Comments and docstrings do not change it.
  - **`refresh(day, out_dir, subject, records=, build=)`** reads and writes
    `out/overrides/<SUBJECT>.json`. It rebuilds when the file is missing, is for another
    fingerprint, is behind the newest month end, or `rebuild` is set. A failed build never
    raises: the cached verdict stands, named stale, or there is none.
  - Gated assets (choice 13): IDN and USA get stocks, bonds and currency; JPN, EMU, AUS and SGP
    get bonds and currency.
- **`schema/overrides.schema.json`** (new). Per side it holds the effective verdict, the
  combined historical verdict, the placebo verdict, the CLI-zeroed verdict, both Holm records,
  the live verdict and edge, the sample, the distance to `MIN_N` and revocation, the window and
  why. Plus covers, `passed` per asset, stale inputs and the rows.
- **`src/assist/override_history.py`**:
  - `idn_build(src, day)`: the replay plus the S58 returns, from a `pipeline.IdnSources`;
  - `live_build(subject, day)`: IDN on the real stores (foreign comes in S63/S64);
  - `expected_components(subject)` and `complete_live(...)`: choice 4 for a live reading.
- **`src/assist/pipeline.py`**:
  - `Sources.override_history` (`Sources.default`: `override_history.live_build`; None in
    tests: no rebuild, no verdict);
  - `gather(..., overrides_dir=)` and `gather_idn` read the IDN gate through `override_gates`,
    which never raises, into `IdnLayers.override_gate`. Its stale lines join the run's;
  - `run` passes `out/overrides/`.
  - Journal: a new `overrides` record for IDN. It carries the deltas, raw sums, `complete`,
    `cli_direction`, `override_fingerprint` (the live monitor's input), the gate state per asset
    and side, the stances it reached, and `moves_band` False.
  - The P28 markets' `overrides` records carry the same live-monitor fields.
- **`src/assist/cli.py`**: `assist overrides [--today D] [--subject S]... [--rebuild]` writes
  and prints the gates. `assist run` prints one override gate line per IDN asset.
- Nothing moves a stance yet. What a pass allows (choice 11) is S61.

## Tests (first, red → green)

`tests/eval/test_override_gate.py` has 21 tests:
- sides and their features; incomplete months are no_calls; CLI zeroing before the cap;
- Holm: the step-down, a lone p of 0.03 blocked, a placebo pass that fails Holm is failed;
- **pass**; **insufficient** (15 windows: 8/7); the window opens at the first complete month;
- **a CLI-zeroed fail blocks a pass** (every up shift is the CLI's alone: the placebo and
  Holm pass, zeroed has no up month, so the state is `failed`);
- **revoked** (the history still passes; 10 live windows went the other way);
- no history is no verdict; the live monitor counts only this fingerprint, since `since`,
  the last record per month, and complete months;
- **fingerprint:** the IDN fingerprint moves on a P17 edit and not on a comment; USA differs
  from IDN and EMU (the asset lists differ);
- `refresh`: builds a missing file (schema-valid); the schema rejects an unknown state; it
  builds nothing within the month and builds when a month end passes (`since` kept); a file
  for another fingerprint is no verdict; a failed rebuild keeps the cached verdict and says
  why; `--rebuild` forces a build; no directory writes nothing.

`tests/test_run_idn.py` (3) and `tests/test_ops.py` (1):
- a run writes `out/overrides/IDN.json` and journals the IDN `overrides` record with the
  file's fingerprint;
- a rerun in the same month builds nothing and is byte-identical;
- a failing build never fails the run; without a builder there is no verdict;
- `assist run` prints the gate line; `assist overrides` writes, caches and rebuilds.

`tests/test_run_foreign.py`: the journal now opens with the IDN `overrides` record.

Full suite: 1887 passed, 1 skipped. `ruff check .` is clean.

## Live check (2026-11-09, real stores read-only, scratch `out/`)

`override_gate.refresh` on IDN with the main checkout's journal (read-only) took 6 s:
- 262 month ends, 112 complete from 2017-07;
- override fingerprint `sha256:045b0b6695f3…`;
- every side **failed**. The numbers are in P78 (S60);
- no override may cross a band.

Model fingerprint on this branch: `sha256:9b9058ff8f11…` (new: `eval/override_gate.py`, P17's
CPI fallback, P28's splice).
