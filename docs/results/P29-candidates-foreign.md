# P29-candidates-foreign: results

Live run 2026-10-23, read-only, from the worktree with `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects`.
Stores read: ausdata, bisfetcher, dbnomics (`dbn serve`), idxscape, jquantster, singstat.
idxscape_phei and openkrx came back `missing`. No store was locked.

## What `assist.layers.candidates_foreign` does

The layer looks at one broad index per market: USA S&P 500 (`SPX`), JPN TOPIX, AUS S&P/ASX 200 (`XJO`),
SGP STI, KOR KOSPI and TWN TAIEX. Rates and yields below are fractions, as of `as_of`, point in time.
A row counts once its store has recorded it, or once it is older than its publication lag (CRP 45 days,
OECD monthly 35, CPI 45, BIS monthly 31).

- **Valuation edge.** EY = 1/CAPE or 1/(P/E). Gap = EY − local 10Y. Hurdle = `us.erp.implied` +
  `<iso3>.crp`, which is Damodaran's US implied ERP plus the rating-based CRP. Edge = gap − hurdle.
- **IDR test.** This uses P27's `fx_edge` over 1 year.
  - Local return = EY + local CPI y/y.
  - The IDR alternative is the IDN 10Y: the PHEI `IGSYC.10`, or dbnomics `idn.rate.long` if that is missing.
  - The expected FX move is the adverse one: the 5th percentile of every 1-year change in IDR per local
    unit over 5 years. That needs 2 years of history; with less, it falls back to UIP from the short rates.
  - The hedge uses BIS `WS_CBPOL.M.<iso2>` for IDR and the local leg; SGP uses SORA 3m compounded.
- **Score.** 50 + 5 points per point of edge, clamped to 0–100, and capped at 50 when the IDR test fails.
  `passes` means the edge is above 0 *and* the IDR test survives.
- **Output.** `foreign_candidates(as_of, sources) → ForeignCandidates`. It holds `valuations`
  (`IndexValuation`), `candidates` (S1 `Candidate`, asset `stocks`, screen `index_valuation`,
  `entry_level` None), `ranked()`, `passing()`, `stale_inputs` and `sources`.
  `default_sources()` builds the 8 adapters.
- **Missing inputs.** A market without EY, 10Y, US ERP or CRP names no candidate. Each missing input
  goes into `stale_inputs`, and a "no source" entry names the fetcher that would add it. An old
  value is still used but is named stale.
- **FX legs (IDR per local unit):**
  - USD: JISDOR.
  - JPY: JISDOR ÷ BOJ USD/JPY (jquantster).
  - AUD: ausdata `FXRIR`, which is direct.
  - SGD: 1 / singstat `mas:fx:idrsgd`.
  - KRW and TWD: IDR per S$ × MAS S$ per KRW/TWD. This crosses through SGD inside one store,
    because no store quotes KRW or TWD against USD.

## Live result

**One candidate (USA). It does not pass.**

| | Value |
|---|---|
| S&P 500 CAPE earnings yield (`us.cape` 40.71, 2026-10) | 2.46% |
| US 10Y (`usa.rate.long`, 2026-09) | 4.99% |
| Gap | −2.53% |
| Hurdle: US ERP 3.70% (2026-10) + USA CRP 0.23% (Jan 2026 snapshot) | 3.93% |
| **Valuation edge** | **−6.47%** → score **17.7** |
| Local return: EY + US CPI 3.74% (2026-09) | 6.19% |
| IDR alternative: IDN 10Y (dbnomics, **2024-12, stale**; PHEI missing) | 7.01% |
| Adverse USD move vs IDR (5th pct of 958 1-year changes since 2021-10) | −0.74% |
| Unhedged / hedged IDR return (BI 5.75% vs Fed 3.875%, carry +1.81%) | +5.41% / +8.11% |
| IDR test | survives hedged, +1.10% |

How to read it: the hedge carry rescues the IDR test, but the index is far below its hurdle. The
CAPE is at the 99th percentile, so `passes` is False.

**FX and hedge carry per currency, live.** These are not used, because there is no valuation for
those markets:

| Market | Adverse 1y move vs IDR | Carry (sell local 1y fwd) | FX history |
|---|---|---|---|
| USD | −0.74% | +1.81% | JISDOR 2021-10 → 2026-10-16 |
| JPY | −9.66% | +4.44% | JISDOR ÷ BOJ USD/JPY |
| AUD | −2.95% | +1.10% | RBA FXRIR 2023-01 → 2026-10-20 |
| SGD | +1.59% | +4.46% (SORA) | MAS 2020-10 → 2026-10-07 |
| KRW | −5.23% | +2.67% | MAS cross |
| TWD | −3.47% | n/a (no rate) | MAS cross |

## Inputs per market, live, and who would add the missing ones

| Market | Valuation (EY) | Local 10Y | CPI y/y | CRP | Short rate | FX |
|---|---|---|---|---|---|---|
| USA | ✅ dbnomics `us.cape` | ✅ dbnomics `usa.rate.long` 4.99% | ✅ `usa.cpi.yoy` 3.74% | ✅ 0.23% | ✅ BIS 3.875% | ✅ JISDOR |
| JPN | ❌ **jquantster**: add a TOPIX level + index EPS or P/E (Free plan has per-stock only) | ✅ jquantster JGB 2.91% | ❌ **dbnomics**: add `jpn.cpi.yoy` | ✅ 0.91% | ✅ BIS 1.25% | ✅ |
| AUS | ❌ **ausdata**: add an ASX 200 P/E or earnings series | ✅ ausdata AGS 5.31% | ✅ `aus.cpi.yoy` 3.97% (dbnomics flags it stale) | ✅ 0% | ✅ BIS 4.60% | ✅ FXRIR (only since 2023) |
| SGP | ❌ **singstat** (or an SGX fetcher): add an STI P/E | ✅ SGS 2.48% | ✅ singstat CPI index → 2.35% | ✅ 0% | ✅ SORA 3m 1.23% | ✅ |
| KOR | ❌ **openkrx**: write index Parquet (K3) and add KRX index PER; `krx_index_daily` has closes only | ✅ `kor.rate.long` 4.45% | ✅ `kor.cpi.yoy` 2.88% | ✅ 0.64% | ✅ BIS 3.00% | ✅ MAS cross |
| TWN | ❌ **openkrx**: write `tw_index` (raw MI_INDEX is captured, not parsed) and add TWSE index P/E | ❌ none (not OECD): openkrx or dbnomics | ❌ none: dbnomics | ✅ 0.78% | ❌ CBC rate not in BIS `WS_CBPOL`: bisfetcher or dbnomics | ✅ MAS cross |

Shared inputs:

- The IDN 10Y should come from the PHEI curve, but idxscape is still at migration 8 on this Mac
  (`idxscape_phei (missing)`). The dbnomics fallback `idn.rate.long` stops at 2024-12 and is
  flagged stale.
- The BI rate comes from BIS `WS_CBPOL.M.ID` at 5.75%.

## Where the siblings differed from the notes

- **No JP, AU or SG index valuation anywhere.** jquantster has no index series, and neither do
  ausdata or singstat. This matches P23.
- **openkrx's index datasets are not on disk.** `openkrx (missing)`; its HEAD is `6fb0925`, with
  DART tables only. Even when they land, the KR/TW index schemas carry closes, not PER. Until then
  the openkrx index close is read only as context (`level`).
- **US 10Y.** The notes suggest Shiller GS10 or Damodaran `tbond`. The layer uses dbnomics' OECD
  `usa.rate.long`, the same family as KOR/AUS fallbacks, so the US is valued like the others.
  Shiller's own `excess_cape_yield` is not used.
- **FX legs.** The notes name JPY via jquantster, SGD via singstat and AUD via ausdata, and the
  layer follows them. KRW and TWD were expected from no store, but singstat's MAS table has both
  against SGD, so they cross through SGD.
- **Hurdle definition.** CLAUDE.md says "US ERP + CRP". The layer uses Damodaran's *implied* US ERP
  (`us.erp.implied`, 3.70%), as dbnomics' `idn.erp.hurdle` does. It does not use the mature-market
  base in `damodaran_crp.us_erp_base` (4.23%).

## For later slices (F3-foreign, P30)

- **Scores are hand-set.** The 5 pt/pp scale, the cap at 50 and the 5th-percentile FX move must not
  move a stance until they beat a placebo (P9).
- **The hedged return is an estimate.** It is based on the policy-rate gap, not NDF points (P27 caveat).
- **EY + CPI is a crude 1-year expected return.** The IDR test compares it with a nominal IDN 10Y.
- **Running from a worktree** needs `ASSIST_SIBLINGS_ROOT`.

Tests: `tests/layers/test_candidates_foreign.py`, 22 passed. They cover:

- the pure core
- the FX-move choice
- point-in-time CRP lag
- fallbacks
- stale and unavailable stores
- every one of the six markets on fixture rows
- the real dbnomics adapter over a tmp store

Full suite: 603 passed, 1 skipped. ruff is clean.
