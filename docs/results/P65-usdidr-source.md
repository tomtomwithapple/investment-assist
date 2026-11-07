# P65-usdidr-source (PLAN S46): USD/IDR for the IDN bonds rule

Date: 2026-11-07. Heuristic, not investment advice.

## Problem

The live IDN bonds rule was `no_call` on "idxscape JISDOR (11 of 60 fixings)". It needs
`MIN_FX_DAYS = 60` fixings, and idxscape `fx_rate` on this Mac starts on 2026-10-22.

## What changed

- **`src/assist/sources/usdidr.py`**: `UsdIdrSource(idxscape, singstat)` is a `Source` of `JISDOR`
  rows. The splice comes from `paper.usd_idr`, imported as is (`paper.py` is unchanged): JISDOR
  from its first fixing, and before that the MAS cross USD/SGD ÷ IDR/SGD. A JISDOR gap after the
  seam stays a gap, and `carried_forward()` passes idxscape's days through unchanged. On top of
  that splice the source adds:
  - provenance for each point (`points()` → `FxPoint(date, value, leg)`);
  - each JISDOR row keeps its idxscape vintage (`as_of`); MAS rows carry `as_of` None, so the
    rule takes them only after its 1-day lag;
  - an overlap check: on each JISDOR day, JISDOR against the MAS cross. It is reported, never
    used;
  - `name`, which says which legs were used (`MAS+JISDOR`, `JISDOR` or `MAS`), plus
    `seam_line()`, the legs' `stale_inputs` and `sources`;
  - one read of the two stores per instance. Only when both legs are unavailable does `rows`
    raise `SourceUnavailable("USD/IDR", …)`.
- **`src/assist/pipeline.py`**:
  - `IdnSources.usdidr` (default None, which keeps the old idxscape path); `default()` sets it to
    `UsdIdrSource(idxscape, singstat)`.
  - `gather_idn` passes it as `idn_bonds(idxscape=...)`. The signals still read idxscape.
  - `_with_fx_seam` adds the seam line to the rule's drivers and the legs' stale inputs to the
    rule's. In the attribution it puts the stores (idxscape, singstat) in place of the splice's
    name.
- No rule threshold, band, tilt, benchmark or ladder changed.

## Live (2026-11-07, `assist --siblings-root /Users/tommy/Projects run --no-send`, worktree out/)

- Spliced series: **5 482 points, 2005-01-03 → 2026-11-05**: MAS cross for 2005-01-03 →
  2026-10-21 (5 471 days), then JISDOR for 2026-10-22 → 2026-11-05 (11 days). Overlap: 11 days,
  JISDOR vs MAS cross max |Δ| 0.12% (mean +0.006%). No carried-forward days, no legs stale.
- Bonds rule: **hold** (proposes neutral, not applied: insufficient sample, on 0 / off 0). It is
  no longer `no_call`.
  - real yield 4.47%: IGSYC 10Y on 2026-11-05 minus CPI 3.23% y/y (2026-10), 58th percentile of
    103 months (2016-07..2026-10). Direction 0, which is why the call is hold.
  - IGSYC 10Y−2Y slope +0.60pt (context only).
  - non-resident SBN +Rp4.09T since 2026-10-07, Rp915T held (12.97%). Direction +1.
  - US investors' net purchases of IDN bonds: +US$147mn over Jun–Aug 2026.
  - USD/IDR **+1.1% over 20 fixings** to 2026-11-05 (source `MAS+JISDOR`, direction −1). Not a
    6-month high and below the 2% jump, so breakout = False.
  - regime risk_off; BI rate 5.75%, +1.00 since 2026-03 (BI hiking is a risk).
- `out/IDN/bonds.json` stays neutral, 49.0. Its `stale_inputs` no longer list JISDOR, and
  `singstat` joins its sources.

## Notes

- The rule's own driver still reads "JISDOR +1.1% over 20 fixings", although its base point
  (20 fixings back) is a MAS cross value: 10 of the 21 points in the window are MAS. That label is in `layers/bonds/idn.py`, outside this slice. The seam line
  next to it names the legs.
- Other readers still use idxscape JISDOR directly, so the run's stale list still has "idxscape
  JISDOR (history from 2026-10-22)". It comes from the IDR reference in `candidates/tilt.py`.
  Moving those readers is left for a later slice.

Tests: `tests/sources/test_usdidr.py` (12) and 2 in `tests/test_run_idn.py`. Full suite 1 659
passed, 1 skipped; ruff clean.
