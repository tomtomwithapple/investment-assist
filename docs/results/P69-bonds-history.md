# P69-bonds-history (PLAN S50): the IDN bonds rule's walk-forward on the real stores, "not yet"

Date: 2026-11-09. Heuristic, not investment advice. Live run only. No code and no threshold
changed. This uses the gate as of S56 (P74): the reduce side has its own gate, and the bond
return lags the OECD monthly averages one month so it starts after the call.

Run: the `assist rules` logic into a scratch `Paths.under`
(`ASSIST_SIBLINGS_ROOT=/Users/tommy/Projects`, real journal read-only), 2026-11-09. Cold build
2442 s. Rule fingerprint `sha256:deb1f60cd776…`. USD/IDR is the P65 splice (JISDOR from
2026-10-22, the MAS cross before).

**Verdict: not yet.** The sample cannot reach the gate on today's stores, and at its call rate
the live record would need many years.

## Calls per month (2016-11 → 2026-10, 120 month ends, 94 with a 3-month return)

| Year | enter | hold | reduce | no_call |
|---|---:|---:|---:|---:|
| 2016–2020 | 0 | 0 | 0 | 50 |
| 2021 | 5 | 5 | 0 | 2 |
| 2022 | 1 | 7 | 4 | 0 |
| 2023 | 0 | 12 | 0 | 0 |
| 2024 | 3 | 9 | 0 | 0 |
| 2025 | 1 | 1 | 0 | 10 |
| 2026 | 0 | 1 | 0 | 9 |

- **No call** in 71 months:
  - non-resident SBN missing in 52 (2016-11 → 2021-02; idxscape `sbn_ownership` starts
    2021-01-04, and 20 days are needed);
  - no 10Y in 19 (2025-03 → 2026-09).
- **Enter** in 10 months: 2021-03/05/07/09/10, 2022-03, 2024-08/09/11, 2025-01.
- **Reduce** in 4: 2022-08 → 11.
- The 10Y source is the OECD proxy (`idn.rate.long`, a monthly average) on 119 months and IGSYC
  on 2026-10 only. The 2026-10 call (hold) has no forward return until 2027-01.
- The proxy is a monthly average, so the return proxy (carry − 7 × Δyield) is smoothed. Since
  P74 it runs from the month after the call (M+1's average to M+4's). The window therefore ends
  2024-08, not 2024-09, and the 2024-09 → 2025-02 calls have no forward return.

## Gate (window 2021-03 → 2024-08, horizon 3, stride 3, block 3, `MIN_N` 10)

| Side | On / off windows | Short of 10 | Verdict |
|---|---|---|---|
| Enter (enter vs hold + reduce) | 3 / 11 | on 7, off 0 | insufficient: t 0.00, p 0.582, control t 0.00 |
| Reduce (reduce vs enter + hold, P74) | 1 / 13 | on 9, off 0 | insufficient: t 0.00, p 1.000, control t 0.00 |

Below `MIN_N` the harness reports t = 0 by construction. The following are descriptive only:
they are overlapping returns and decide nothing.
- Every call month in the window: enter n 7, mean 3-month return +0.58%; hold n 31, +1.31%;
  reduce n 4, +4.26%. All four reduce months came before the late-2022 rally.
- On the stride windows: enter 3 at +1.18% against 11 at +1.62%; reduce 1 at +7.54% against 13
  at +1.06%. So far both point the wrong way.

The 1-month diagnostic (`--horizon 1`, 2021-03 → 2024-10) has on 8 / off 36: also insufficient.

**Distance to the gate:**
- **Enter** is 7 windows short. Enter came in 10 of 46 called months (22%), so the live record
  adds about 0.9 enter windows a year (4 windows a year): about 8 years to 10.
- **Reduce** is 9 short. Reduce came in 4 of 46 months (9%), so it adds about 0.35 a year:
  decades.
- Filling the 10Y hole (below) makes 2025-03 → 2026-07 callable and gives the 2024-09 → 2025-02
  calls their returns. The window would run to about 2026-07: roughly 65 months, about 22
  windows instead of 14. At the same rate that is about 2 more enter windows (5 of 10), still
  short. P31 (2026-10-23) found 5 enter in 39 months, which is consistent.

## The 10Y ask (open question 6), written into PLAN.md *Open data gaps*

No IDN 10Y exists for 2025-01 → 2026-09 (21 months) in any store. Each item below is asked of
the fetcher named and is never built here.
1. **dbnomics:** an IMF IFS IDN government bond yield (monthly) if it runs past 2024-12.
2. **idxscape:** DJPPR SUN auction results (the 10Y benchmark's weighted-average yield), as a
   dated series.
3. The Windows machine's PHEI captures fill only IGSYC 2026-10-22 → 11-03 (deferred by the
   user).

What it adds: 19 callable months for each rule (2025-03 → 2026-09), returns for the bonds calls
2024-09 → 2025-02, about 8 more bonds windows and about 6 more stocks windows. The bonds enter
side still would not reach 10, but the stocks reduce side might (P68).
