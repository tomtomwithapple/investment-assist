# P79-override-stance (PLAN S61): a passed override side may cross a band

Date: 2026-11-09. Branch `phase-l`. Phase L choice 11 (accepted 2026-11-09). Heuristic, not
investment advice.

## What changed

- **`src/assist/stance.py`** (MODEL_VERSION **0.6.0**, stance schema **1.3.0**):
  - `build_stance(..., override_gate=OverrideGateView(passed, states, line))`.
  - When the layer-2 shift would carry the stance into another band, it crosses only if the
    side in its direction passed its gate: up for a positive shift, down for a negative one.
    The driver then reads "layer-2 override crosses to X from Y: its up side passed its gate
    (…)".
  - Otherwise the stance is held at the band and the driver names the side and its state
    ("… held at neutral until their down side passes its gate (down side failed)", or
    "(no gate)").
  - The shift keeps its ±10 cap. A passed phase K rule still replaces the band stance after the
    override.
  - Every stance carries `layer2`: `shift`, `gate` (`{up, down}` states or null), `passed`,
    `crossed`, `held`.
  - `MODEL_CONFIG["override_moves_stance"]` is `"passed_side_only"` (was False). The model
    fingerprint changes and a new journal segment opens at the fan-in run.
- **`schema/stance.schema.json`**: optional `layer2` (schema 1.3.0); older payloads stay valid.
- **`src/assist/pipeline.py`**:
  - `gather_foreign` reads each P28 market's gate (`override_gates`, never raises) into
    `ForeignLayers.override_gates`.
  - `override_view(score, layers)` hands each stance its gate: IDN's for IDN, the market's for a
    foreign subject, **EMU's for DEU, FRA, ITA, ESP and NLD**, none for KOR, TWN, commodities
    and the foreign stocks without a gate.
  - The `overrides` journal records (IDN and the five markets) carry the gate states. Per
    stance reached they carry `held` and `crossed`; `moves_band` is true when one crossed.
  - `override_gate.LIVE_SUBJECTS` covers all six subjects, so `assist run` and
    `assist overrides` write `out/overrides/{IDN,USA,JPN,EMU,AUS,SGP}.json`.
- **`src/assist/brief.py`**: one *Global regime* line, e.g. "Layer-2 override gate: no side
  passed (N gated stance(s)); overrides move scores, never bands; held at the band: …". With a
  pass it lists the passed sides and the bands crossed.
- **`src/assist/views/signals.py`**: `/signals/<SUBJECT>`'s shift table gets a *Gate (up /
  down)* column read from `out/overrides/<SUBJECT>.json` (a chip per side: passed, failed,
  insufficient, revoked, not gated), plus a line naming the passed sides and the complete
  months. A missing or broken gate file is a line or a notice, never a 500, and every value is
  escaped.
- **`src/assist/cli.py`**: `assist run` prints each market's passed sides, the bands held and
  any crossing.

## Tests (first, red → green)

- `tests/test_stance.py` (7):
  - **an up pass lifts neutral to overweight on a +6 shift from 57** (63, `crossed`);
  - **a down shift on the same asset stays held** (42 − 6 = 36: held at neutral, the driver
    names the down side);
  - a down pass lowers the band;
  - **no pass, nothing moves** (no gate, or both sides failed);
  - a shift inside the band neither crosses nor holds;
  - a passed rule still replaces the band after a crossing;
  - versions and config.
- `tests/test_run_foreign.py` (4):
  - a passed EMU down side lowers DEU, FRA and NLD bonds (45 − 9 = 36 → underweight) with EMU's
    gate in their `layer2`;
  - an up pass does not let a down shift cross;
  - KOR, and EMU stocks, have no gate;
  - a run writes a schema-valid gate per market and journals the states, with `moves_band`
    false.
- `tests/test_brief.py` (3): the gate line with no pass, with a pass and a crossing, and no
  line without `layer2`.
- `tests/test_view_signals.py` (3): the gate chips per side, "not gated", a missing file, a
  broken file as a notice, and escaping.
- Version pins updated (`test_stance.py`, `test_run_idn.py`).

Full suite: 1918 passed, 1 skipped. `ruff check .` is clean. Model fingerprint on the branch:
`sha256:b68e9bce1774…`.

## Live

- IDN (S60): all six sides failed, so no IDN override may cross; today's shifts (stocks −5,
  bonds −4, currency +2) stay inside their bands anyway.
- The foreign verdicts are P83 (S65).
- The run that opens the 0.6.0 segment is the fan-in's (S66).
