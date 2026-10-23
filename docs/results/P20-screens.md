# P20-screens — results

Live run 2026-10-23, read-only against `../idx-method` (git `b0e8547`). Code is in
`src/assist/candidates/screens.py`; `run_screens()` gives one result per screen, with its
placebo verdict, rejects by rule and candidates.

## Rules (from idx-method's git history, 9a0ea38^)

| Screen | Legs | Source in idx-method |
|---|---|---|
| dividend | trailing 12m IDR dividends / price | `paper/strategies.py` `Dividend`, `div_panel.trailing` |
| value | book-to-price | `strategy.py` Tier 8 note ("bp is the leg that actually measured") |
| momentum | `mom_12_1` + `near_52w_high` | `paper/strategies.py` `Technical` |

All three screens share the same funnel, from `strategy.py`:
- **Gates:** free float ≥ 15%, 60-day median value ≥ Rp 5bn, price ≥ 100, `vol_1y` ≤ 0.96 and `days_traded_60` ≥ 45. Names on the FCA, HSC, NOTASI and ABX boards are excluded.
- **Quality floor:** Piotroski ≥ 5, Altman Z ≥ 1.8, CFO > 0 and interest cover ≥ 1.5 when the name carries debt. Banks are judged on CAR, NPL, coverage, LDR and ROE instead.
- **Ranking and selection:** each leg is z-scored and clipped at ±3, and the legs are averaged. The book takes the top 20, with at most 5 names per sector.

## Placebo gate

The screen is replayed at each month end using only data from `cache/history/` that was known at that date. The gates replayed are liquidity, price, volatility and trading days, plus today's flagged boards, as idx-method's backtests did. The quality floor isn't replayed, because it only exists for today. The inputs at each month end:
- **Dividend yield:** dividends by ex-date.
- **Book-to-price:** the last `bvps` that was knowable 120 days after its quarter end.

Each month contributes two observations: the next-month mean return of the top quintile and of the bottom quintile, each in excess of the month's pool. `placebo.evaluate` (P9) scores them with 1000 shuffles and 20 controls, using the default seed. A screen that fails still runs and reports how many names it ranked, but its `candidates` list stays empty.

Sample: 48 months, from 2022-09-30 to 2026-08-31. The pool held 97–154 names a month (about 117 on average).

| Screen | Verdict | top − bottom /mo | Welch t | p (placebo) | control t | paired monthly spread t |
|---|---|---|---|---|---|---|
| dividend | **fail**: t 1.42 below 2.0 | +1.03% | 1.42 | 0.093 | 0.40 | 1.11 |
| value | **fail**: t 1.63 below 2.0 | +1.12% | 1.63 | 0.034 | 0.25 | 1.33 |
| momentum | **pass** | +2.24% | 2.62 | 0.004 | −0.17 | 2.18 |

## Live (as of the last bar, 2026-10-09)

- Of 978 names, 65 pass the gates and the quality floor. The rejects: liquidity 350, free float 273, flagged board 218, extreme volatility 26, F-score 16, Altman Z 13, price floor 10, negative CFO 3, interest cover 3 and bank ROE 1.
- **dividend, value:** each ranked 65 names and named none, because both are blocked by their verdict.
- **momentum:** named 20 names. The top ones are BSML, MMIX, TINS, AADI, MARK, DEWI, AUTO, HRTA, ERAA, SRSN and PTBA, followed by AKRA, BFIN, DMAS, AALI, GJTL, GGRM, LSIP, INDF and MAPA.
- No stale inputs. The run took 7.3s.

## Caveats later slices must know

- **Momentum's pass is weak evidence.** It comes from 48 in-sample months, and three screens were tested with no correction for multiple tests. idx-method's own notes put this signal's IC at t 1.23, and on the 379-month Li, Wei & Zhang library `ret_12_1` is negative (−0.78%/mo) and `prc_highprc_252d` is about zero. Dividend yield is the one leg that held up over 379 months (t 4.67), and it fails on this short window. Treat the momentum list as context until paper tracking (S13) has a record.
- **The verdict is recomputed on every run.** A new month can flip any of the three verdicts. The verdict dict carries the seed and every parameter, ready for the journal.
- **Stale cache on this Mac:** the history cache stops at 2026-10-09 and `factors.json` was written 2026-10-12. These are the same dates P19 saw.
- **Board and sector lists:** `special_boards.json` and `sectors.json` are still written by idx-method's `reference_data.py`. Their 2026-10-19 change stopped only the index series and `fetch_universe.py`. They're read directly from `data/`, because `IdxMethodStocks` has no method for them. If either file is missing, it's recorded as a stale input: no names are excluded, and each name gets its own sector bucket.
- **Value uses two different sources:** the live ranking uses the screener's `pbv`, while the replay uses `bvps` from `cache/fundamentals/`, which covers only about 517 names. idx-method's live and research code made the same split.
- The screens reuse P19's private `_signals` and `_cum`, so the replay ranks on exactly the definitions in `factors.py`.
- The cost model and entry levels are not built here; they're P21's.
