# P88-dip-placebo (PLAN S69): placebo for gate 3 of the average-down rule

Date: 2026-11-10. Branch `phase-m`. Heuristic, not investment advice. Read-only on idx-method's
`cache/history/` and `cache/dividends/` (history to 2026-11-05).

## Verdict

**Insufficient: gate 3 stays context.** One non-overlapping 12-month window against the 10 that
phase K's gate needs. idx-method's history starts 2021-11, `entry.py` needs 750 bars (about three
years) before it measures a level, and an add needs 12 months after it, so the scoreable month
ends run only 2024-11 to 2025-10. Ten windows need about 14 years of history; at one more per
year the gate is reachable around 2035. The entry status stays on the row as context and may not
stop or allow an average down (phase M choice 2's default).

## What was built

`src/assist/eval/dip_gate.py` (pure, plus `run()` on the live store; `uv run python -m
assist.eval.dip_gate [horizon]` prints the result as JSON). No payload, schema or pipeline change;
nothing reads it yet.

- **Dates.** Month ends. At each one `entry.measure` runs on the name's bars on or before it, so
  every level and the dip-buy record come from the past. `entry.py` is untouched.
- **Add.** The close of the name's first session after the month end; return = total return
  (price plus dividends, a split is a zero return) to the first session 12 months later.
- **Real.** Per month, the mean forward return of the adds in `buy_zone` or `deep` (at least 5).
- **Placebo.** The same names added on a random day instead (any session with 750 bars before
  it and a full forward return), 200 seeded sets.
- **Verdict.** Phase K's numbers, unchanged: non-overlapping windows (month ends 12 months
  apart), `MIN_N` 10 per side, t ≥ 2.0, p ≤ 0.05, control rerun, seed 20261023. It also has to
  beat 95% of the random-day sets.

The design and its constants (`MIN_NAMES` 5, `N_SETS` 200, `BAR_WINDOW_DAYS` 10, the last two
taken from `tiers_replay`) were written before the live run and not changed after it.

## Live, 12 months (the gate)

797 names with a pool of random days; 11 scored months, 1,844 zone adds; 1 window (2024-11-29,
7 zone adds, real +16.0% against placebo +52.9%).

| Month end | Zone adds | Real | Placebo |
|---|---:|---:|---:|
| 2024-11 | 7 | +16.0% | +52.9% |
| 2024-12 | 229 | +84.3% | +50.2% |
| 2025-01 | 238 | +85.1% | +54.6% |
| 2025-02 | 280 | +80.7% | +48.8% |
| 2025-04 | 184 | +77.3% | +54.6% |
| 2025-05 | 161 | +50.3% | +51.6% |
| 2025-06 | 169 | +37.2% | +51.1% |
| 2025-07 | 155 | +33.3% | +35.6% |
| 2025-08 | 142 | +24.4% | +19.3% |
| 2025-09 | 141 | +35.8% | +40.1% |
| 2025-10 | 138 | +8.0% | +54.7% |

Diagnostics only (the months overlap, so these decide nothing):

- All 11 months: real +48.4% against placebo +46.7%, ahead in 5 of 11, naive t 0.21. No sign of
  an edge.
- By status at the add (mean 12-month return, share above zero): `wait` +64.9%, 58%
  (4,295 adds); `buy_zone` +60.1%, 56% (639); `deep` +55.8%, 59% (1,205); `avoid` +46.9%, 38%
  (1,569). `avoid` has the lowest share of winners, which is the direction it claims, but the
  zones do not beat `wait`.
- The means are equal-weighted over every IDX name with a history, so a few multi-baggers in
  the 2025 small-cap run lift them all; the comparison between columns matters, not the level.

## Live, 3 months (diagnostic, not the gate)

The plan asks for 12 months; phase K's own horizon is 3. At 3 months: 7 windows (needs 10), so
also insufficient. Real +8.0% against placebo +12.5% on the windows; over all 20 months real
+8.7% against +12.4%, ahead in 9 of 20, naive t −0.70. Either reading of "phase K's gate
numbers" gives the same answer.

## Judgment calls

- **Add at the next session**, not at the month-end close, so the levels use only bars before
  the add.
- **The random-day pool** is the name's whole scoreable span, not the same month, as the plan
  says ("random days for the same names"). It mixes market timing into the placebo: 2025-10's
  real +8.0% against +54.7% is mostly the market after that date, not the zone.
- **March 2025 is missing.** The month end (03-27) was followed by the Lebaran break, so the
  next session was more than `BAR_WINDOW_DAYS` away and every name sat out. Left as written; it
  cannot change an insufficient verdict.
- **Windows are picked from the first scored month**, which here is 2024-11 with only 7 names
  old enough. A single window is not a result either way.
- **No output file.** P88 owns only the module, its test and this page. S68 treats gate 3 as
  context; if a later slice wants the verdict in `out/`, `run()` returns it whole.

## Fingerprint

`journal.RULE_GLOBS` hashes `eval/**/*.py`, so the new module changes the model fingerprint with
identical behaviour: `sha256:0054161d53f8…` → `sha256:8aeca8e62547…`. As for S67, the new journal
segment opens at the phase M fan-in run (S71).

## Tests

`tests/eval/test_dip_gate.py`, 17 tests: the gate numbers are phase K's; month ends and month
arithmetic; total return counts IDR dividends and ignores a split; status at a month end equals
`measure` on bars up to it and does not move when the future is changed; the add is priced at
the first session after the month end; names without 750 bars, without a forward return or with
a stale bar sit out; windows do not overlap; too few windows is insufficient; a real edge passes
and binds; no edge fails; only zone adds are scored and thin months sit out; a rerun gives the
same verdict; a missing store is `blocked`; `run` reads the store. The tests and the module were
written together and passed on the first run (no separate red run). Full suite **1975 passed**
(baseline 1958), ruff clean.
