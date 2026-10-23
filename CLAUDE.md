# investment-assist

The **parent** and entry point of the investment data repos, all siblings in `../`: ausdata,
bisfetcher, bps-looker, dbnomics, financer, geospacer, idx-method, idxscape, jquantster, kseistat,
openkrx, satudatascape, sec-edgar (usfin), singstat (sgecon), worldbankscape (wbs). Paths below are
relative to this repo.

The children stay where they are as independent repos (own remote, store, launchd jobs). This repo
is their parent by ownership, not by folder: it holds the decision flow, the cross-repo coverage
gaps and build order, and the read-only registry of their stores. Each child's `CLAUDE.md` has a
*Parent: investment-assist* section pointing back here. Cross-repo progress is checked from here;
start a session in this repo for anything that spans more than one child.

## Investment decision flow

Goal: for an **IDR-based investor**, decide a stance and entry terms per country × asset class
(stocks, bonds, currency, commodities) across Indonesia, US, Japan, EU, Singapore, Australia,
Korea/Taiwan. Each repo is a fetcher with its own local store. **investment-assist** is the entry
point (plan in `PLAN.md`): it reads those stores **read-only** and never fetches
anything itself. Its output is heuristic context, **not investment advice**; every payload carries
a disclaimer and source attribution.

### Entry point: investment-assist

- No fetcher repo calls another. Only investment-assist reads across repos, so each fetcher keeps
  one job and none becomes a dependency of the others.
- It never fetches from the internet and never writes into another repo. Missing data goes into
  the fetcher repo it belongs to (as the FRED layer-0 series went into sec-edgar), then
  investment-assist reads it.
- One DuckDB process attaches the stores read-only: DuckDB files (idxscape, kseistat, ausdata,
  singstat, worldbankscape, bisfetcher `warehouse.duckdb`, dbnomics `data/dbnomics.duckdb`), SQLite (jquantster, financer `~/.financer/financer.db`, idx-method
  `store/data/stockbiter.db`, satudatascape `data/satudata.db`) and Postgres (bps-looker).
  openkrx is read as DuckDB over its `data/parquet` (its Postgres holds only ops tables; read
  contract in its `docs/HANDOFF.md`, slice R1, pending as of 2026-10-23). worldbankscape is read from its
  `out/*.json` contract. sec-edgar is read over HTTP (`usfin serve`, `?format=csv`) because
  `serve` holds the DuckDB lock. dbnomics' lock is mutual (a reader blocks `dbn refresh`), so
  prefer its API (`dbn serve`, 127.0.0.1:8770, `?format=csv`) or open-query-close; its tables,
  ids and units are in `../dbnomics/docs/HANDOFF.md`. bisfetcher's tables are locked by the
  `contract` block in its `PLAN.md`.
- A fetcher that adds or renames a table another layer reads should note it in its own plan, so
  the matching adapter in investment-assist can be updated.

### Flow, from data to output

| Layer | Question | Source repos |
|---|---|---|
| **0. Global regime** | Risk-on, neutral or risk-off? Dollar up or down? | sec-edgar job `fred` (`config/fred.yaml`, point in time via `fred_as_of(DATE)`): VIXCLS, BAMLH0A0HYM2, T10Y2Y, WALCL, M2SL, DFF, SOFR, DGS2, DGS10, DTWEXBGS (broad dollar), DFII10 (10Y real yield), NFCI, DCOILBRENTEU; net liquidity = WALCL − WTREGEN − RRPONTSYD (RRP in $bn, the others in $mn); EM corporate OAS BAMLEMCBPIOAS, BAMLEMHBHYCRPIOAS (from 2023-10-10 only); nowcasts GDPNOW, WEI; THREEFYTP10 (term premium), T5YIE, T10YIE (breakevens), STLFSI4 (stress), USEPUINDXD (policy uncertainty); CCUSMA02IDM618N (IDR per USD monthly, cross-check vs JISDOR). · bisfetcher (BIS SDMX: `WS_EER` broad real and nominal effective exchange rates, M and D, incl. IDR REER; done, S1–S13 on main). Read current values from `fred_observation_latest`: NFCI (~930k rows) and STLFSI4 (~310k) are large, because each weekly release revises the whole history |
| **1. Country × asset score** | Structural macro tailwind or headwind (0–100, 50 neutral) | worldbankscape (`out/{SUBJECT}/{asset_class}.json`, 27 countries + 14 commodities) |
| **2. Fresh macro overrides** | Is the economy speeding up or slowing now? Adjusts the layer-1 score | bps-looker, satudatascape (IDN; data.go.id catalogue in SQLite with extracted tables as Parquet, not a series store) · sec-edgar (US CPI/PPI/jobs/Treasury; FRED GDP, GDPC1, PCE, INDPRO, retail, housing, UMich sentiment) · jquantster macro (JGB, BOJ, Tankan, USD/JPY) · singstat (MAS SORA, SGS, FX) · ausdata (RBA, ABS, AOFM) · dbnomics (OECD CLI, BCI, CCI, CPI, rates, unemployment for IDN, CHN, USA, JPN, KOR, AUS, EA20/G4E; China monthly `cn.*` with NBS fallback; Eurozone monthly via ECB) · bisfetcher (`WS_CBPOL` policy rates incl. BI rate `WS_CBPOL.M.ID`/`.D.ID`; credit-to-GDP gap `WS_CREDIT_GAP`, property prices `WS_SPP`, debt-service ratios `WS_DSR`) |
| **3. Market signals** | Who's buying, what does the curve say, is it cheap? | idxscape (IDX foreign flow, broker summary, JISDOR, DJPPR SBN ownership; PHEI since J4 2026-10-22: IGSYC curve `igsyc_point` (as_of, tenor_y), `phei_bond_quote`, `credit_curve_point`, local use only, see its `docs/storage.md`) · kseistat (local/foreign ownership) · jquantster (TSE investor flows) · sec-edgar job `tic` (TIC/CSLT monthly by country: foreign holdings and net purchases of US securities `for_*`, US investors in foreign bonds and equities `us_*`, e.g. `us_lt_eqty_net_42218` for Indonesia; `tic_observation_latest`, `/series/tic?country=…&format=csv`) · dbnomics valuation (Damodaran implied ERP US monthly and CRP per country, `damodaran_erp`, `damodaran_crp`; Shiller CAPE `shiller`), for the IDN equity hurdle (US ERP + IDN CRP) vs JCI earnings yield |
| **4. Candidates** | Which instruments to buy | idx-method (data only since 2026-10-14: Stockbit screener factors, consensus, shareholder composition, daily history with net foreign flow, dividends, quarterly statements, `stockbiter.db`; its index CSVs incl. `jkse_daily.csv` are frozen at 2026-09-30 since 2026-10-19); the screens, books, cost model and entry levels are built here from that data · sec-edgar (US fundamentals) · jquantster (prices, EPS, EDINET) · openkrx (KR/TW) |
| **5. Portfolio fit** | What I already hold → how much to add or trim | financer (broker, bank and RDN statements → SQLite) |
| **Output** | Stance + entry plan | Weekly Markdown brief + Telegram (never-fail, send-once, as idx-method's former paper daemon did), plus one JSON per country × asset class |

geospacer (alternative data) is for theme research only and does not feed the flow.

### Decision rules by asset

- **IDN bonds (SBN):** real yield (yield − CPI), PHEI curve slope, change in foreign SBN
  holdings, JISDOR trend, BI rate direction, global regime. Enter when the real yield is high,
  foreign holdings are stable or rising and USD/IDR isn't breaking out. Ladder the entry when the
  regime is risk-off.
- **IDN stocks:** macro score + IDX foreign flow + KSEI foreign share + JCI earnings yield vs
  SBN yield, computed here (idx-method's `dividend_vs_bonds.py` is gone). Market stance first,
  then names from screens built here on idx-method data.
- **Foreign stocks and bonds (US, JP, EU, AU, SG):** macro score, local curve and inflation,
  valuation, with **returns converted to IDR** (hedged vs unhedged). Overweight only if the edge
  survives the expected FX move.
- **Commodities:** Pink Sheet trend and China momentum, mainly as context for IDX sectors
  (coal, nickel, CPO).

### Output contract (extends the worldbankscape schema)

```json
{ "subject": "IDN", "asset": "bonds", "as_of": "2026-10-13",
  "stance": "overweight", "score": 68, "confidence": 0.74,
  "regime": "neutral", "drivers": ["real yield 3.1% (82nd pct)", "foreign SBN +Rp4.2T/4w"],
  "risks": ["USD/IDR at 6m high"], "watch": ["BI meeting 2026-10-22", "US CPI 2026-10-15"],
  "entry": {"style": "ladder", "tranches": 3, "spacing_days": 10},
  "portfolio": {"current_pct": 8, "target_pct": 15, "delta": "+7pt over 3 tranches"},
  "stale_inputs": [], "disclaimer": "Heuristic, not investment advice." }
```

`stance` is one of `overweight | neutral | underweight | avoid`.

### Rules (carried over from idx-method's former paper engine)

- Every rule carries a **placebo control** before it may change a stance; a rule that also
  improves the control is fitting noise.
- Every decision is journalled with a fingerprint of the model that made it, so a rule change
  segments the record instead of averaging two regimes.
- Paper-track stances against a fixed IDR 60/40 benchmark (60% JCI, 40% SBN index) before
  acting with real money.

### Coverage gaps, in priority order (as of 2026-10-23)

1. ~~Finish layer 0~~ (done 2026-10-13: DTWEXBGS, DFII10, NFCI, DCOILBRENTEU added to `../sec-edgar/config/fred.yaml`).
2. ~~idxscape J4: PHEI parser~~ (done 2026-10-22: `igsyc_point`, `phei_bond_quote`,
   `credit_curve_point`; the jobs Mac must pull idxscape so migration 9 runs there).
2b. **JCI and IDX index series have no fetcher** (since 2026-10-19 idx-method no longer updates
   `data/*_daily.csv`; frozen at 2026-09-30). Needed by the regime walk-forward, the IDN stocks
   rule and paper tracking; belongs in idxscape (or another fetcher), not here.
3. ~~China monthly~~ (done 2026-10-14: dbnomics `cn.*`; NBS mirror stale since 2026-03, no TSF/credit).
4. ~~Eurozone monthly~~ (done 2026-10-14: dbnomics via ECB; no Bund 2Y, the euro-area 2Y
   benchmark stands in; unemployment from OECD).
5. ~~OECD leading indicators~~ (done 2026-10-14: dbnomics; no CLI for SGP or EA20).
6. ~~BI rate~~ (done 2026-10-14: bisfetcher `WS_CBPOL.M.ID`/`.D.ID`). SEKI money/credit still missing. Index-level
   ERP and US CAPE done in dbnomics; JCI P/E from idx-method still to wire.
7. IDN stock screens and books: idx-method stopped picking stocks on 2026-10-14 (it only fetches
   now). The dividend / value / momentum books, cost model and entry levels move into
   investment-assist (S10); `vol_1y`, `amihud`, `med_value_60d`, `days_traded_60`, `mom_12_1`
   and `near_52w_high` are derived here from its `cache/history/`.

Also missing: a cross-country release calendar (only US BLS has one). (US TIC flows done 2026-10-14: sec-edgar S43.)

### Build order

1. ~~FRED global block~~ (done, sec-edgar S42 + 4 layer-0 series) → 2. ~~idxscape J4~~ (done 2026-10-22) → 3. investment-assist phase A, S0–S6 (layers 0, 1, 5 + weekly brief) →
4. layers 2–3 → 5. ~~China and EU monthly fetchers~~ (dbnomics) → 6. paper tracking.
