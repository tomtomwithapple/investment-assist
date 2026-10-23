# P8-regime: PLAN S3, regime layer 0

Live run on 2026-10-23, read-only against this Mac's stores.

## What was built

`src/assist/layers/regime.py`. This is a hand-set rule on five FRED inputs from sec-edgar. Each
input is read point in time with `FredSource.rows(..., as_of=D)`, which goes through
`fred_as_of(D)`, so there is no look-ahead.

| Input | Risk-off point | Risk-on point |
|---|---|---|
| VIXCLS level | ≥ 25 (2 points at ≥ 35) | ≤ 15 |
| BAMLH0A0HYM2 change over 13 weeks | ≥ +0.75 pt | ≤ −0.50 pt |
| DTWEXBGS change over 13 weeks | ≥ +3 % | ≤ −3 % |
| DFII10 level | ≥ 2.5 % | ≤ 0.5 % |
| NFCI level | > 0 | ≤ −0.5 |

- **State:** net = off − on. A net of +2 or more is `risk_off`, −2 or less is `risk_on`, and
  anything else is `neutral`.
- **Dollar:** `up` or `down` when DTWEXBGS moves more than ±2 % over 13 weeks, otherwise `flat`.
- **Missing data:** a missing, short or old input scores nothing and is named in `stale_inputs`.
  A locked or missing store gives a neutral, flat regime with `sec-edgar (<reason>)`.
- **Candidates:** `CANDIDATES` holds net liquidity Δ13w (%), EM corporate OAS Δ13w, term premium
  Δ13w (THREEFYTP10) and STLFSI4. They are computed every run but only count when listed in
  `ADOPTED`, which is `()` (see the verdict below).
- **Backtest helpers:** `history(dates)` gives point-in-time inputs per date and `weekly()` gives
  the Fridays. `entry_returns` enters at the first price strictly after the signal date, since
  FRED's day ends at 23:59 New York, after the Jakarta close. A signal with no price within 14
  days gets no return, so a date before the series starts does not take its first price. `check`
  runs the P9 harness with `direction=-1`.
- **Tests:** `tests/layers/test_regime.py` has 28 tests and passes. The full suite has 379
  passed and 1 skipped, and ruff is clean.

## Live: the regime now

On 2026-10-16 and on 2026-10-13 the regime is **neutral, dollar flat**. The only driver is the
10Y real yield at 2.91 % (a risk-off point). VIX is 15.21, NFCI −0.494 (just above the −0.5
risk-on line) and HY OAS 3.11. `stale_inputs` is empty. The read went through ATTACH (`via
duckdb`) because `usfin serve` is not running on this Mac. This Mac's sec-edgar copy stops at
2026-10-13, so a fresh run on the jobs Mac may differ.

## Live: walk-forward, does `risk_off` come before weaker JCI and IDR?

- **Signals:** 406 weekly Fridays, 2019-01-04 to 2026-10-09, each read as known that day. All of
  them took 10 s through ATTACH.
- **JCI:** idx-method `jkse_daily.csv`, **frozen at 2026-09-30**, so the JCI test stops there.
- **IDR:** idxscape JISDOR, 2021-10-01 to 2026-10-16. The IDR return is
  JISDOR(entry) / JISDOR(exit) − 1.
- **Settings:** the harness default seed, 1000 shuffles and 20 controls.

**States, 2019–2026:** neutral 214, risk_on 173, risk_off 19. Since 2024-01 the counts are 90,
53 and 2. The dollar was flat 245 times, up 83 and down 78.

**The 19 risk_off weeks:**
- 2020-03-20 to 05-01 (7 weeks)
- 2022-06-24 and 07-01
- 2022-09-02 to 10-28 (8 weeks)
- 2025-04-04 and 04-11

| Test | n on / off | Mean on | Mean off | t (signed) | p (placebo) | Control t | Verdict |
|---|---|---|---|---|---|---|---|
| **JCI, 20d, stride 4, block 4 (primary)** | 3 / 97 | +3.85 % | +0.05 % | – | 0.910 | – | **fail: insufficient sample** |
| **IDR, 20d, stride 4, block 4 (primary)** | 3 / 63 | −1.54 % | −0.30 % | – | 0.052 | – | **fail: insufficient sample** |
| JCI, 5d, stride 1 | 19 / 384 | +1.34 % | +0.02 % | −1.27 | 0.980 | −0.02 | fail (wrong sign) |
| IDR, 5d, stride 1 | 12 / 252 | −0.46 % | −0.08 % | +2.20 | 0.057 | +0.02 | fail: p 0.057 > 0.05 |
| JCI, 20d, stride 1 (overlapping, t inflated) | 19 / 381 | +2.73 % | +0.08 % | −1.87 | 0.938 | −0.12 | fail (wrong sign) |
| IDR, 20d, stride 1 (overlapping) | 12 / 249 | −0.94 % | −0.34 % | +1.12 | 0.187 | +0.35 | fail |
| "not risk_on" → JCI, 20d, stride 4 | 58 / 42 | +0.41 % | −0.17 % | −0.59 | 0.704 | −0.14 | fail |
| "not risk_on" → IDR, 20d, stride 4 | 46 / 20 | −0.26 % | −0.58 % | −0.99 | 0.800 | −0.01 | fail |

**Verdict: not proven.** The hand-set rule does not beat the placebo on either asset. The control
shows no edge in any test (|control t| ≤ 0.35), so the procedure is not fitting noise. There are
too few risk_off episodes (3 independent 20-day windows).

- **IDR:** the sign is as claimed, and close to significant at 5 days. The 2022-09 to 10 run
  came before IDR losses of −0.1 % to −3.2 % over 20 days.
- **JCI:** the sign is the opposite. Risk_off fired at the 2020-03 and 2025-04 lows, and JCI
  rebounded +14.5 % and +13.9 % over the next 20 days. The rule is a coincident stress gauge, not
  a lead indicator for JCI.

The rule stays as written: changing the thresholds to fit these 19 weeks would be fitting noise.
The stance layer (P10) uses risk_off only to ladder entries and shift the score, and the notes
say the verdict is information, not a gate.

## Candidates: none adopted

| Candidate | Values from (point in time) | On its own → JCI 20d | On its own → IDR 20d | Added to the rule |
|---|---|---|---|---|
| net liquidity Δ13w ≤ −3 % | 2019-01 | t −1.57 (wrong sign), p 0.835 | t −1.24, p 0.884 | 5–6 risk_off windows: insufficient |
| EM corp OAS Δ13w ≥ +0.5 | 2024-01 (FRED keeps ICE data from 2023-10-10) | 0 flags | 0 flags | no change |
| term premium Δ13w ≥ +0.4 | 2019-01 | t +1.51, p 0.127 | insufficient (6 flags) | 6 windows: insufficient |
| STLFSI4 > 0 | 2022-11 (first vintage in the store) | 1 flag | 1 flag | 3–4 windows: insufficient |

None beats the placebo, so `ADOPTED = ()`. The term premium is the closest, with the right sign
on JCI (t 1.51). Re-run it when there is more history.

## Findings for later slices

- **HY OAS starts 2023-10-10:** FRED keeps ICE data only from then, so HY OAS Δ13w first exists
  in 2024-01. Before that the rule runs on four inputs and names `BAMLH0A0HYM2` in
  `stale_inputs`: 249 of 406 backtest weeks had no data and 13 had too short a history.
- **Real vintages in sec-edgar:** the store holds ALFRED vintages, so point-in-time reads are
  genuine.

  | Series | First vintage |
  |---|---|
  | VIXCLS | 2010-11 |
  | NFCI | 2011-05 |
  | WALCL | 2011-07 |
  | THREEFYTP10 | 2016-05 |
  | DTWEXBGS | 2019-02-04 |
  | STLFSI4 | 2022-11-10 |

  Before a series' first vintage, `fred_as_of` returns nothing: the 5 weeks before 2019-02-04
  have no dollar input. This matches sec-edgar's docs (HEAD `ed08075`), so nothing needed
  reconciling.
- **Entries and IDR history:** `entry_returns` had to skip signals with no price soon after.
  JISDOR starts 2021-10-01, and without the skip the 2020 signals were scored on the 2021-10
  prices. That is fixed and tested.
- **JCI is frozen:** the JCI walk-forward is frozen at 2026-09-30 with idx-method's CSVs. It
  grows only once JCI has a new fetcher, swapped in through `assist.sources.idxmethod.jci()`.
- **Running from a worktree:** set `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects`, because
  `../` of a worktree is not the siblings root.
