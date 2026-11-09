# P80-foreign-fx (PLAN S62): USA and JPN `fx` read USD/IDR from the P65 splice

Date: 2026-11-09. Branch `phase-l`. Phase L choice 12 (accepted 2026-11-09). A live model change.
Heuristic, not investment advice.

## What changed

- **`src/assist/layers/overrides_foreign.py`** (P28):
  - IDR per USD now comes from the P65 splice (`sources.usdidr.UsdIdrSource`): JISDOR from its
    first fixing, the MAS cross (singstat USD/SGD ÷ IDR/SGD) before it.
  - It is read under the store key `usdidr` (`JISDOR_REF = Ref("usdidr", JISDOR, 1, DAILY)`)
    instead of idxscape's JISDOR alone.
  - JISDOR points keep idxscape's vintage. MAS cross points have none, so they count from the
    day after their date (lag 1).
  - `default_sources()` builds `usdidr` from idxscape and the same singstat source P28 already
    reads. idxscape is no longer a P28 store of its own.
  - USA reads the splice directly. JPN crosses it through USD/JPY, as before.
- EMU, AUS and SGP are unchanged. The model fingerprint changes (`layers/**`), so the next
  run opens a new journal segment.
- Tests: the fixtures key the USD/IDR store `usdidr` (`tests/layers/test_overrides_foreign.py`,
  `tests/test_run_foreign.py`).

## Tests (first, red → green)

- **11 JISDOR fixings plus MAS history** give USA and JPN a 3-month `fx` change. The base is
  the MAS cross 16,000, the newest is JISDOR 16,800, so +5.0%, direction +1. No JISDOR stale
  line, and the IDR terms read 16,800.
- **JISDOR alone** (MAS missing) is too short: `fx` is n/a and named
  (`history from <first fixing>`), as live before P80.
- **The MAS leg waits its one-day lag.**
- `default_sources()` serves `usdidr` as a `UsdIdrSource` and has no `idxscape` key.

Full suite: 1862 passed, 1 skipped. `ruff check .` is clean.

## Live (2026-11-09, real stores read-only)

| Market | fx | Shift (stocks / bonds / currency) |
|---|---|---|
| USA | IDR 18,094 per USD on 2026-11-05, +0.87% since 2026-08-05 → direction 0 (band 1.5%) | 0 / −3 / +2 (unchanged) |
| JPN | IDR 114.17 per JPY on 2026-11-05, +0.38% since 2026-08-05 → 0 | −3 / −2 / +1 (unchanged) |

- Both components compute again. Neither stale line ("idxscape JISDOR (history from
  2026-10-22)") is left.
- Both changes sit inside the 1.5% band today, so no shift moves. A move past ±1.5% over 3
  months now shifts USA and JPN by fx's weights (stocks ±1, bonds ±1, currency ±3).
- In history (S63) the splice gives both markets an `fx` from 2005 on.
