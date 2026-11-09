# P85-cpi-fallback (PLAN S61b): P17 inflation falls back to dbnomics when bps-looker's CPI is too short

Date: 2026-11-09. Branch `phase-l`. Phase L choice 9 (accepted 2026-11-09). Lands before S59's
first verdict. Heuristic, not investment advice.

## What changed

- **`src/assist/layers/overrides.py` `_inflation`** (a P17 model change):
  - Before, P17 fell back to dbnomics `idn.cpi.yoy` only when bps-looker had no CPI at all.
  - Now it also falls back when bps-looker's CPI has no point 3 months before its newest
    (`_spans`), i.e. the series is too short for the 3-month change.
  - The bps-looker short line stays in `stale_inputs`
    (`bps-looker BPS_CPI_YOY (history from …)`).
  - If dbnomics has no CPI either, the component stays missing, as before.
  - The newest CPI level (`inputs["cpi_yoy"]`, read by the bonds rule's real yield) stays
    bps-looker's whenever it has a point, as before. Only the momentum component switches
    source.
- Fingerprints. `layers/overrides.py` is in both IDN rules' `RULE_FILES` and under the model
  fingerprint's `layers/**`, so:
  - bonds rule `sha256:deb1f60cd776…` → `sha256:f9be0b944e8e…`;
  - stocks rule `sha256:d217e4585d5a…` → `sha256:457c6c858be4…`;
  - the model fingerprint changes too.

  `out/rules/` rebuilds cold at the fan-in run (S66, about 45 min).

## Tests (first, red → green)

- `tests/layers/test_overrides_idn.py`:
  - **bps-looker CPI known for 2 months:** inflation comes from dbnomics (+0.9 → direction
    +1). The bps short line is still stale, and the newest CPI level is still bps-looker's
    3.1%.
  - A bps-looker CPI long enough is kept over dbnomics.
  - A short bps-looker CPI with dbnomics locked stays missing.
- `tests/test_override_history.py`: the S57 test of the splice hole now expects the fallback
  (2018-03 reads dbnomics, 2018-05 bps-looker, the row is complete). The coverage test gets its
  hole from a missing trade month instead.

Full suite: 1858 passed, 1 skipped. `ruff check .` is clean.

## Live (2026-11-09, real stores read-only)

- Inflation is computed on every month end 2005-01 → 2026-10 with no hole. It reads dbnomics up
  to 2024-04 and bps-looker from 2024-05.
- **Complete months: 112** (was 109), 2017-07 → 2026-10 with no gap.
- 2024-02 → 04 shifts (stocks / bonds / currency): −3 / −4 / −2, −3 / −4 / −2, −4 / −7 / −3.
  Inflation reads 0, 0 and +1.
- Shift signs on the complete months: stocks up 66 / zero 8 / down 38; bonds 48 / 7 / 57;
  currency 43 / 23 / 46.
- Complete months with a 3-month return:
  - stocks and currency: 109 (2017-07 → 2026-07);
  - bonds: 86 (2017-07 → 2024-08).
- Live P17 on 2026-11-09 is unchanged: bps-looker CPI has run since 2024-01, long past its
  3-month window.
