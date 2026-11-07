# P70-home-inputs (PLAN S51): home (IDN) regime inputs, point in time

Date: 2026-11-07. Heuristic, not investment advice. Inputs only: no thresholds, no points (P71).

## What changed

- **`src/assist/layers/home_inputs.py`** (new). `HomeInputs(as_of, values, last, stale_inputs,
  sources)`, shaped like `regime.Inputs`, plus `fresh(feature)` and `counted()`. `counted()`
  gives the values P71 may score, with None where the input is absent or stale. Other entry
  points: `home_inputs(as_of, sources)`, `history(dates, sources)` (reads each store once and
  gives the same result as one `home_inputs` per date; a test checks this), the pure
  `inputs(series, as_of, ...)`, and `HomeSources.default()` (`JciSource`, idxscape, and the P65
  `UsdIdrSource(idxscape, singstat)`).
- The four features, each read as known on `as_of`:

  | Feature | Definition | Known when |
  |---|---|---|
  | `jci_drawdown_20d` | JCI close vs the highest of its last 20 closes (today's included), % | on its date (the stores keep no vintage) |
  | `idx_foreign_z` | IDX market net foreign IDR 20-day sum, z-score vs the 250 20-day sums ending on the 250 days before (sample sd; the current sum is excluded from its baseline); needs 270 days | recorded by `as_of`, or 1 day after the trade (P18) |
  | `usdidr_20d` | P65 USD/IDR (JISDOR spliced on the MAS cross), % change over 20 fixings | JISDOR: from the day idxscape recorded it; MAS (no vintage): 1 day after its date (as in the bonds rule) |
  | `sbn_non_resident_20d` | idxscape `SBN.TOTAL.non_resident` % change over 20 DJPPR days (observations) | file fetched by `as_of`, or 40 days after its date (P18) |

- Staleness: an input is stale when its newest known point is more than 7 days older than
  `as_of` (open question 7). A stale input keeps its value and is named
  `"<store> <series> (last D)"`. A short history gives None, named `"(n of N closes|days|fixings)"`.
  An input with no data gives `"(no data)"`. An unavailable store gives `"<store> (locked|missing)"`
  and is never raised.
- `src/assist/sources/idxscape.py` did not change: its rows already carry what this slice needs.
  `stock_summary` covers only trading days (1,224 days, none with zero value), and
  `sbn_ownership` has one row per (as_of, instrument, investor_type).
- Tests: `tests/layers/test_home_inputs.py`, 12 tests on in-memory sources and
  `tests/fixtures/home/jci.csv`. The fixture is the real idxscape COMPOSITE for 2026-08-26 →
  11-05, which includes the 2026-10-06 → 10-16 case. They first failed on the missing module,
  then passed. Full suite: 1676 passed, 1 skipped; ruff clean.

## Live (read-only, `ASSIST_SIBLINGS_ROOT=/Users/tommy/Projects`, 2026-11-07)

| as_of | JCI 20d drawdown | IDX foreign z (20d vs 250) | USD/IDR 20 fixings | Non-resident SBN 20d |
|---|---|---|---|---|
| 2026-10-06 | −7.27% (10-06) | −0.42 (10-05) | +1.57% (10-05) | +1.79% (08-27, **stale**) |
| 2026-10-16 | −18.79% (10-16) | −0.32 (10-15) | +1.07% (10-15) | +3.06% (09-04, **stale**) |
| 2026-10-23 | −12.17% (10-23) | −0.81 (10-22) | +0.90% (10-22) | +2.76% (09-11, **stale**) |
| 2026-11-05 | −17.45% (11-05) | −0.81 (11-04) | +1.49% (11-04) | +0.10% (09-25, **stale**) |
| 2026-11-07 | −17.45% (11-05) | −0.72 (11-05) | +1.15% (11-05) | +0.45% (11-04) |

The newest date of each input is in brackets. Every input not marked stale is fresh. The stores
read were idxscape+idx-method, idxscape and MAS+JISDOR (MAS cross 2005-01-03 → 2026-10-21, then
JISDOR 2026-10-22 → 11-05).

- On 10-16 the JCI was 18.8% below its 20-day high (6,384.7 on 2026-09-21). The "−11.6%" in the
  plan is that day's own fall (5,863.8 → 5,185.1); the drop from the 10-06 close is −16.3%.
  On 10-06, before the fall, the JCI was already 7.3% below its 20-day high (6,678.2 on 09-09).
- SBN is stale on every date before 11-06. DJPPR's whole history in idxscape came in one file,
  fetched 2026-11-06, so before that date a point is known only after its 40-day lag.

First date with a value (first counted, i.e. fresh, in brackets):

| Input | First value | Fresh Fridays 2021-10-01 → 2026-11-06 |
|---|---|---|
| JCI drawdown | 1996-10-29 (idx-method CSV, 20th close) | 265 / 267 (2 Fridays after the Lebaran closes are stale) |
| IDX foreign z | 2022-11-05 (270th flow day from 2021-10-01, plus the 1-day lag) | 208 / 267 |
| USD/IDR move | 2005-02-02 (21st MAS fixing, plus the 1-day lag) | 267 / 267 |
| Non-resident SBN | 2021-03-13 (21st DJPPR day plus 40 days) [first fresh 2026-11-06] | 1 / 267 |

So the P71 walk-forward can test the JCI and USD/IDR inputs from 2021-10 and the flow z from
2022-11. SBN is stale on every historical Friday, as open question 7 expected.

## Evidence for the review agent (no number changed)

The Phase K defaults stay fixed. These live distributions bear on open question 7:

- **The flow z never reached −1.5 during the 2026-10 shock.** Its lowest from 2026-09-01 to 11-06
  was −1.09 (10-27/28). On 10-22 the 20-day sum was −IDR 16.2T, against a 250-day baseline mean
  of −8.0T, sd 10.1T and minimum −33.2T: 2025's outflows were larger and widen the baseline. On
  weekly Fridays from 2022-11-04 the z is ≤ −1.5 on 29 of 209 (13.9%), with a minimum of −3.11.
  So the flow input is live, but it gave no point in this event.
- **USD/IDR +4% over 20 fixings never happened** on weekly Fridays from 2022-11-04 → 2026-11-04
  (0 of 210). +2% happened 28 times. The 2-point level has never fired in the testable sample.
- JCI: ≤ −7% on 28 of 210 Fridays, ≤ −12% on 13. In the shock, the JCI input alone reaches 2
  points on 10-16, 10-23 and 11-05, so risk_off on those days would rest on the JCI input only.
- SBN: ≤ −1.5% on 39 of 210 Fridays, but those values are stale, so they would not count.

## Notes

- A flow row with no recorded date (`as_of` None, which happens only without a `trading_day`
  table) counts only after its lag. P18's `_known` counts such a row at once. This slice takes
  the stricter reading.
- 20 days means 20 observations for all four inputs. For SBN this is 20 DJPPR days, not P18's
  4 calendar weeks.
