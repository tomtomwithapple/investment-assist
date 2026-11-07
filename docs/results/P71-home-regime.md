# P71-home-regime (PLAN S52): home (IDN) regime rule and its walk-forward

Date: 2026-11-07. Heuristic, not investment advice. Live reads were read-only
(`ASSIST_SIBLINGS_ROOT=/Users/tommy/Projects`). Nothing was written outside this worktree, and
nothing was sent.

## What changed

- **`src/assist/layers/home_regime.py`** (new). This is the open question 7 rule on the four P70
  inputs. The thresholds were written and committed to the module before the walk-forward ran,
  and they were not tuned afterwards.

  | Input | 1 point | 2 points |
  |---|---|---|
  | JCI vs its 20-day high | ≤ −7% | ≤ −12% |
  | IDX net foreign 20d sum, z vs trailing 250 | ≤ −1.5 | – |
  | USD/IDR over 20 fixings (P65 splice) | ≥ +2% | ≥ +4% |
  | Non-resident SBN over 20 DJPPR days | ≤ −1.5% | – |

  - **State:** 2 points or more is `risk_off`, anything else is `neutral` (there is no home
    risk_on).
  - **Freshness:** an input counts only if its newest point is at most 7 days old
    (`HomeInputs.counted`). If it is older, or absent, it is `None` in `by_input`, and its value
    is kept for the pages.
  - **API:** `classify(inputs, drop=())` returns a `HomeRegime` with `as_of`, `state`, `points`,
    `by_input`, `values`, `last`, `drivers`, `stale_inputs` and `sources`. Also in the module:
    `home_regime(as_of)`, `history(dates)` (P70's one-read history), `check` (`regime.check`,
    `direction=-1`), and `weekly`.
  - **Adoption:** `HOME_SHIFT_ADOPTED = False`. `shift_adopted(jci, idr=None)` is True only when
    the JCI verdict passes. The IDR verdict is reported and decides nothing.
  - **Diagnostics only:** `ladder_vs_lump` and `input_counts`, plus `drop=`.
  - `HomeRegime` lives in this module. P72 owns `layers/types.py` and may move it there.
- **`tests/layers/test_home_regime.py`** (new, 42 tests). It covers the points at each boundary,
  the state, the 7-day rule (7 days counts, 8 does not, a stale SBN does not tip a 1-point JCI),
  the 2026-10-06 and 10-16 cases on the real JCI fixture, history equal to one call per date,
  `shift_adopted` False on a failing JCI check, a planted edge against noise, ladder fills, and
  the drop and count diagnostics. The tests first failed on the missing module, then passed.
  Accept command: 70 passed (42 + 28 regime). Full suite: 1718 passed, 1 skipped; ruff clean.

## Live: weekly states, Fridays 2021-10-01 → 2026-11-06 (267 weeks)

There were **24 risk_off weeks** (243 neutral). They fall in **7 episodes** of consecutive weeks,
which give **5 independent 20-day windows** at stride 4 with an entry return. The 2026-10-16
episode has no 20-day forward return yet.

| Episode | Weeks | Points | Inputs that scored |
|---|---|---|---|
| 2024-04-19 → 04-26 | 2 | 2, 2 | flow z, USD/IDR |
| 2024-06-21 | 1 | 2 | flow z, USD/IDR |
| 2024-11-15 → 11-22 | 2 | 2, 2 | flow z, JCI, USD/IDR |
| 2026-02-06 → 02-20 | 3 | 3, 2, 2 | flow z, JCI |
| 2026-03-13 → 04-03 | 4 | 2 each | JCI only |
| 2026-04-24 → 06-12 | 8 | 2, 3, 3, 2, 4, 4, 4, 4 | flow z, JCI, USD/IDR |
| 2026-10-16 → 11-06 | 4 | 2 each | JCI only |

Before 2024-04 the home regime was never risk_off. The flow z only exists from 2022-11, so the
2022 period was tested on JCI and USD/IDR alone. The home and global regimes are both risk_off on
one Friday only, 2026-11-06.

**Named dates:**

| Date | State | Points | Inputs |
|---|---|---|---|
| 2026-10-06 | neutral | 1 | JCI −7.3% (1); flow 0, USD/IDR 0, SBN stale (last 08-27) |
| 2026-10-16 | **risk_off** | 2 | JCI −18.8% (2); flow 0, USD/IDR 0, SBN stale (last 09-04) |
| 2026-10-23 | **risk_off** | 2 | JCI −12.2% (2); flow 0, USD/IDR 0, SBN stale (last 09-11) |
| 2026-11-05 | **risk_off** | 2 | JCI −17.5% (2); flow 0, USD/IDR 0, SBN stale (last 09-25) |

## Live: walk-forward (P9 harness, seed 20261023, 1000 shuffles, 20 controls)

Entry is at the first price after the Friday. The test is 20 days ahead, stride 4, block 4,
`direction=-1`. Prices are JCI 2021-01-04 → 2026-11-05 (stitched, P51) and USD/IDR (P65 splice)
2019-01-02 → 2026-11-05, inverted for the IDR.

| Test | on / off | Mean on | Mean off | t | p | Control t | Verdict |
|---|---|---|---|---|---|---|---|
| **JCI 20d (gate)** | 5 / 61 | −1.05% | +0.48% | – | 0.306 | – | **fail: insufficient sample** |
| **IDR 20d** | 5 / 61 | −1.16% | −0.38% | – | 0.102 | – | **fail: insufficient sample** |
| JCI 5d, stride 1 | 22 / 243 | −0.13% | +0.01% | +0.11 | 0.425 | −0.01 | fail |
| IDR 5d, stride 1 | 22 / 243 | −0.21% | −0.10% | +0.55 | 0.287 | +0.28 | fail |
| JCI 20d, stride 1 (overlapping, t inflated) | 20 / 242 | −3.99% | +0.23% | +2.22 | 0.001 | −0.01 | "pass", not the gate |
| IDR 20d, stride 1 (overlapping) | 20 / 242 | −1.00% | −0.36% | +1.96 | 0.032 | +0.29 | fail |

A "–" means the harness gives no t when either side is below `MIN_N` (10).

**`HOME_SHIFT_ADOPTED` stays False.** The gate test has 5 risk_off windows against the 10 it
needs. The signs are as claimed on both assets: JCI −1.05% after risk_off against +0.48%
otherwise, and the IDR −1.16% against −0.38%. The overlapping JCI 20d test clears t 2.0 with a
clean control, but its 20 risk_off weeks are about 5 episodes counted many times over, which is
exactly what stride 4 exists to stop. It is reported as a pointer for a rerun when more data
exists, not as a pass.

## Live: ladder against lump (diagnostic)

This compares a 3 × 10-day buy ladder (equal IDR, harmonic mean fill) on JCI against one lump at
the first price after the Friday, as a % of the lump price. Negative means the ladder was
cheaper.

| Signals | n | Mean | Median | Ladder cheaper |
|---|---|---|---|---|
| Every risk_off week | 20 | −1.17% | −0.06% | 10 |
| First week of each episode | 6 | **+0.78%** | +0.71% | 1 |
| All other weeks | 243 | +0.04% | +0.23% | 101 |
| All weeks | 263 | −0.06% | +0.20% | 111 |

Per episode start: 2024-04-19 +0.32%, 2024-06-21 +3.43%, 2024-11-15 +1.69%, 2026-02-06 +0.92%,
2026-03-13 +0.51%, and 2026-04-24 −2.20%. The 2026-10-16 episode has no third tranche yet.

The mean over every risk_off week favours the ladder by 1.2%, but that comes from the later weeks
of the long 2026-04 → 06 episode. On the first week of each episode, which is when a ladder would
actually be set, the ladder filled higher than the lump 5 times out of 6: JCI tended to bounce
after the first risk_off Friday. Six episodes prove nothing either way, and open question 8 (the
ladder on home risk_off) stays as decided.

## Live: P8's global regime rerun to 2026-11 (report only)

This ran on Fridays 2019-01-04 → 2026-11-06, FRED point in time over `usfin serve` HTTP (1,848 s).
JCI is the stitched series from 2018-06 and the IDR is the P65 splice.

- **States:** neutral 217, risk_on 173, risk_off 20. The 20 are P8's 19 plus **2026-11-06**, the
  first global risk_off of the 2026-10 shock, three weeks after the home regime turned.

| Test | on / off | Mean on | Mean off | t | p | Control t | Verdict |
|---|---|---|---|---|---|---|---|
| JCI 20d, stride 4 | 3 / 99 | +3.85% | −0.19% | – | 0.926 | – | fail: insufficient sample |
| IDR 20d, stride 4 (spliced) | 3 / 99 | +2.56% | −0.33% | – | 0.995 | – | fail: insufficient sample |
| JCI 5d, stride 1 | 19 / 389 | +1.34% | −0.03% | −1.31 | 0.978 | −0.19 | fail (wrong sign) |
| IDR 5d, stride 1 | 19 / 389 | +0.21% | −0.08% | −0.74 | 0.880 | +0.15 | fail (wrong sign) |

- **JCI:** the same as P8: coincident, with rebounds after the 2020-03 and 2025-04 lows.
- **IDR:** P8 measured IDR on idxscape JISDOR from 2021-10 only (p 0.052, right sign). With the
  MAS cross behind it, the 2020-03 signals now have IDR prices too, and the IDR rebounded after
  them, so the sign turns. Nothing changes: the global regime stays as it is (Phase K, decided).

## Per-input diagnostics (evidence for the review agent; nothing changed)

**How often each input is counted and scores, on 267 Fridays:**

| Input | Counted (fresh) | 1 point | 2 points | risk_off on its own |
|---|---|---|---|---|
| JCI 20d drawdown | 265 | 16 | 13 | 13 weeks |
| IDX foreign z | 208 (from 2022-11) | 29 (13.9%) | – | 0 (max 1 point) |
| USD/IDR 20 fixings | 267 | 35 | **0** | 0 |
| Non-resident SBN | **1** (2026-11-06) | 0 | – | 0 |

**The rule with one input removed** (gate test, 20d stride 4):

| Removed | risk_off weeks | JCI on / off, mean on | JCI p | IDR mean on | IDR p |
|---|---|---|---|---|---|
| none (the rule) | 24 | 5 / 61, −1.05% | 0.306 | −1.16% | 0.102 |
| JCI | 10 | 3 / 63, −0.25% | 0.418 | −1.35% | 0.108 |
| flow z | 17 | 3 / 63, **+3.43%** | 0.920 | −1.01% | 0.239 |
| USD/IDR | 18 | 4 / 62, −0.46% | 0.424 | −0.98% | 0.224 |
| SBN | 24 (no change) | 5 / 61, −1.05% | 0.306 | −1.16% | 0.102 |

Every variant fails on sample size. These are diagnostics, not candidates.

**Evidence bearing on the fixed numbers (open question 7):**

- **The October 2026 shock rests on the JCI input alone.** On 10-16, 10-23 and 11-05 the JCI
  12% level gives both points, while flow and USD/IDR give none. The 2026-03 episode was JCI-only
  as well. The JCI 2-point level is in effect a one-input trigger: 13 of the 24 risk_off weeks
  would be risk_off on JCI alone.
- **USD/IDR's 2-point level (+4%) never fired** on any Friday since 2021-10 (P70: 0 of 210 from
  2022-11). Its +2% level scored 35 times, and only ever in combination.
- **The flow z ≤ −1.5 scored 29 times**, but never in the 2026-10 shock (P70: lowest −1.09).
  Removing it turns the JCI mean after risk_off from −1.05% to +3.43%: its weeks (2024, 2026-02,
  2026-04 → 06) are the ones followed by weakness.
- **SBN is never counted in history:** DJPPR is posted with a lag, so the 7-day rule leaves it
  fresh on 1 of 267 Fridays. Removing it changes nothing. As the rule stands, the "non-resident
  SBN −1.5%" point cannot contribute until DJPPR is fetched within the week.
- **The gate cannot be reached on this sample.** 5 independent windows in 5 years against
  `MIN_N` 10 per side. At this rate (about 5 episodes in 2.5 years since 2024-04) a JCI pass is
  years away whatever the thresholds are.

## Notes

- The flow z exists only from 2022-11 (270 IDX days from 2021-10-01), so before that the rule ran
  on three inputs, and in practice on two.
- 2026-11-06 is home risk_off on JCI −17.5% (last close 11-05, 1 day old), with SBN fresh for the
  first time (0 points).
- The global history over HTTP is slow (one `fred_as_of` call per Friday, ~4.5 s each). A rerun
  in a page or a job would want P8's ATTACH path while serve is down.
- The live script was kept in the session scratchpad and is not part of the repo.
