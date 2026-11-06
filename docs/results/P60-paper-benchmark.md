# P60-paper-benchmark — results

PLAN S40: the paper track's benchmark follows the whole-portfolio benchmark decided on
2026-11-06 (S39): **48% JCI / 32% SBN leg / 20% US stocks in IDR**, unhedged, price index,
rebalanced weekly, cash 0. The old 60/40 benchmark stays, and still scores every model segment
journalled before S39. Heuristic context, not investment advice.

## Benchmarks

- **Weights in one place.** `paper.BENCHMARK_PCT` is derived from `stance.BENCHMARK_PCT`: IDN
  stocks → `stocks` (JCI), IDN bonds → `bonds` (SBN leg), USA stocks → `usa`. If stance drops one
  of these legs, the import fails with a KeyError. A test checks that the weights sum to 100 and
  match `stance.BENCHMARK_PCT`.
- **The old benchmark.** `paper.LEGACY_BENCHMARK_PCT` is 60/40, kept with the paper's own
  `TILT_PT` (±10) and `implied_weights`, unchanged.
- **Side by side, never chained.** The report carries both: `benchmark`, `benchmark_pct` and
  `benchmark_summary` for 48/32/20, and `legacy_benchmark`, `legacy_benchmark_pct` and
  `legacy_summary` for 60/40.
  - Chaining (60/40 until the switch, 48/32/20 after) needs a switch date. The journal does not
    have one yet: both of its segments are pre-S39.
  - A chained line would also mix two mandates into one number. Showing both keeps each history
    whole and makes the cost of the switch visible.
- **Which benchmark a segment is scored on.** This is decided per fingerprint, from the
  segment's own stance payloads:
  - **48/32/20** if any mandate stance in the segment carries `portfolio.benchmark_pct`, a field
    S39 added (model 0.4.0). Each leg is then held at its journalled `portfolio.target_pct`,
    which is already pro-rata capped by `stance.apply_limits`. A leg without a target falls back
    to benchmark + `stance.TILT_PT` (`avoid` → 0), and a leg with no stance sits at its
    benchmark weight with a note. Weights above 100 are scaled down, and the rest is cash.
  - **60/40** otherwise: the IDN sleeve only, scored exactly as before. USA records are ignored
    for these segments.
  - Each `SegmentScore` names its `benchmark_pct`, and nothing is pooled across fingerprints.
- **Old scores unchanged.** Run live against the main checkout's journal (read-only), both
  segments (`4ef43996…` and `9607e4bd…`) give the same portfolio and benchmark returns and the
  same week counts as the pre-S40 `paper.py`. The legacy benchmark marks equal the old benchmark
  marks exactly. All 20 earlier `test_paper.py` tests pass unchanged in substance; the
  benchmark-mark tests now pass `pct=LEGACY_BENCHMARK_PCT`, and every test passes its US leg so
  that no store is opened.

## US leg

- **Index.** sec-edgar's Alpaca **SPY** bars (`UsStocks.bars`, i.e.
  `alpaca_bar_adjusted_lookup('SPY')`), as **close × split_factor**: a price index without
  dividends, like the JCI leg. `adj_close` is the total-return series (× `tr_factor`), so it is
  not used.
  - The series runs 2016-01-04 → 2026-11-05: 2,727 bars, no gap over 4 days.
  - FRED `SP500` is not in sec-edgar's `config/fred.yaml`, so it has 0 rows here.
- **USD/IDR.** IDR per USD, daily.
  - **JISDOR** (idxscape `fx_rate`, BI's daily fixing) from its first fixing, **2026-10-22 →
    2026-11-05** (11 days).
  - Before that, the **MAS cross** `mas:fx:usdsgd ÷ mas:fx:idrsgd` (singstat, both S$ per unit,
    same day): **2005-01-03 → 2026-10-21** (5,471 days).
  - **Seam:** 2026-10-21 (MAS) | 2026-10-22 (JISDOR), with no rescaling. On the 10 days where
    both exist, MAS / JISDOR − 1 ranges from −0.12% to +0.04%. That basis is noise next to a
    weekly FX move.
  - A JISDOR gap after the seam is not filled from MAS: it stays a gap.
- **Other IDR series checked (all read-only):**

  | Source | What it has | Why not used |
  |---|---|---|
  | FRED via sec-edgar | `CCUSMA02IDM618N`, monthly average, 1967 → 2026-09 | No daily IDR series; H.10 has no IDR |
  | bisfetcher | `WS_EER.D.N.B.ID`, a daily *effective* rate | Not bilateral |
  | ausdata | RBA FXRIR / FXRUSD, a daily cross | Only 2023-01-03 → 2026-11-04 |
  | dbnomics | No IDR FX series | — |
  | idxscape | JISDOR only, from 2026-10-22 | Used after the seam |

  MAS covers the whole SPY history, so the monthly fallback was not needed.
- **Return.** Each mark's level is SPY(m) × USD/IDR(m), and the weekly IDR return is
  L(end)/L(start) − 1 = (1 + SPY return)(1 + USD/IDR move) − 1. A US rally and a weaker rupiah
  both raise it, and a stronger rupiah lowers it (tested). Each `Mark` carries `usa` (the IDR
  return), `usa_usd` (the SPY return) and `usd_idr` (the change in IDR per USD).

## Staleness

- A benchmark mark is stale if any leg that benchmark holds has no return. The 60/40 benchmark
  never needs the US leg.
- The JCI and SBN rules are unchanged, including P52's daily-gap rule for IGSYC.
- **US close.** It must be the mark's Friday or the day before (`US_MAX_LAG_DAYS` = 1), which
  covers a US holiday on Friday (Good Friday, 4 July). It is never tied to IDX's last trading
  day, because US and IDX holidays differ: a Friday when IDX is shut and the US trades is
  fine (tested). An older close is a capture gap: "US leg: no SPY close for the … mark (last
  …)".
- **USD/IDR fixing.** It must be no older than the earlier of the day before the mark and JCI's
  last close on or before it.
  - A long IDX shutdown such as Lebaran also stops JISDOR, and passes.
  - A fixing missing while IDX traded is stale (both cases tested).
- **Past the last value.** A mark after the last SPY close or the last fixing is stale ("no SPY
  close after 2026-11-05 (mark 2026-11-06)"), as JCI's is. The Friday close may still come, and
  a Thursday-only week is accepted only once a later close shows that the Friday was a holiday.
- **US store down.** The 48/32/20 marks still run, each stale and naming the US leg, and the
  store shows under stale inputs (`sec-edgar (locked)`).

## Where it shows

- **`assist paper` and the brief (`brief.paper_lines`):**
  - `Benchmark 48% JCI / 32% SBN leg / 20% US stocks (IDR): …`;
  - the last scored week with every leg: `JCI …, SBN leg …, US stocks (IDR) … = SPY … × USD/IDR
    …`;
  - a `Legacy benchmark (segments before S39) 60% JCI / 40% SBN leg: …` line;
  - each model line names its benchmark (`(vs 60/40)`);
  - the Legs line names every source: JCI, IGSYC, Alpaca SPY via sec-edgar, MAS via singstat,
    JISDOR via idxscape, with the seam dates.
- **`/paper`:**
  - the summary card is titled from the weights (`IDR benchmark 48/32/20`) and has one row per
    leg with its weight and source label (`US stocks leg (20%)`);
  - a new *Legacy benchmark 60/40* card;
  - the segments table gains a *Vs* column (`60/40` or `48/32/20`);
  - an older report without the US leg still renders, titled from its own weights.
- **JSON (`to_dict`):**
  - `series` gives the SPY range and each USD/IDR piece with its dates;
  - `legacy_benchmark` marks are dropped with `marks=False`, as `benchmark` is.
- **`usfin serve` timeout.** A whole SPY history takes about 12 s over HTTP, longer than the
  shared 5 s timeout. That made the first live read fall back to the locked file. `Usfin` now
  has a `timeout` attribute, passed through `http_csv(timeout=…)`; the paper's SPY read sets it
  to 60 s, and every other caller keeps 5 s.

## Live (2026-11-06, read-only)

`uv run assist --siblings-root /Users/tommy/Projects paper` in the worktree. The worktree has no
journal, so it shows benchmark marks only. The main checkout's journal was also read by a script,
read-only.

| Week ending | 48/32/20 | JCI | SBN leg | US stocks (IDR) | SPY (USD) | USD/IDR | Stale because |
|---|---|---|---|---|---|---|---|
| 2026-10-16 | **−7.7%** | −14.9% | −1.0% | −1.1% | −2.0% | +0.9% | scored |
| 2026-10-23 | — | +4.9% | — | −0.3% | −0.4% | +0.2% | IGSYC hole: no yield on 10-23's last IDX day (last 10-21) |
| 2026-10-30 | — | −7.0% | — | −0.2% | −0.6% | +0.4% | IGSYC hole at both ends of the week |
| 2026-11-06 | — | — | — | — | — | — | no JCI, SPY or JISDOR after 11-05 yet, plus the IGSYC hole at 10-30 |

- **48/32/20:** from 2026-10-06 (IGSYC's first day), 1 week scored, cumulative −7.7%, 3 stale.
- **Legacy 60/40:** 1 week scored, −9.4%, the same as P52.
- **Segments:** `4ef43996` and `9607e4bd` are both model 0.3.0 (pre-S39), so both are scored on
  60/40. Nothing is scored in either yet: `4ef43996` has 1 stale week and `9607e4bd` has no
  complete week. The first S39 run that is journalled opens a 48/32/20 segment.
- **Stale inputs:** JCI, IGSYC.10, SPY and USD/IDR each end 2026-11-05.

## Decided differently / for later

- **USD/IDR source.** MAS's cross is used rather than an idxscape JISDOR backfill (which does
  not exist) or FRED's monthly series. If idxscape ever backfills JISDOR, the seam moves back by
  itself, because JISDOR wins from its first date.
- **Side by side, not chained.** The user can still ask for a chained "policy benchmark" line
  once a 48/32/20 segment exists.
- **Price index, not total return.** Both equity legs are price indices, which understates
  equity against the carry-earning SBN leg by the dividend yield (JCI about 2–3%, SPY about
  1.2%). This is unchanged from P30.
- **US withholding tax and estate tax** are not modelled in the paper leg (S39 names the estate
  tax risk on the stance).
- **CLAUDE.md** still says "fixed IDR 60/40 benchmark". The new wording is proposed to the user
  and not applied.
