# investment-assist — plan

The entry point that reads the sibling fetcher repos and turns their data into a **stance and an
entry plan per country × asset class** for an IDR-based investor. The decision flow it implements
is in `CLAUDE.md` (*Investment decision flow*); this plan is how it gets built.

---

## STATUS — read this first in a new session

**Last updated:** 2026-11-11 (**P102-stocks-r1**: the IDN stocks rule's valuation is spec r1 (review R-stocks-valuation, user 2026-11-11): implied ERP = EY − real 10Y (no `G_REAL`) against US ERP + IDN CRP − IDN default spread (dbnomics `damodaran_crp`, the CRP's lag and age; none, no call); every phase K number unchanged, `idn_stocks.py` only; same journal segment as P101. Live read: 2022-12 diff −0.17pt (review −0.19 on the OECD proxy), today −1.22pt so the stocks rule calls **reduce** (was hold), gated, not applied. Also idx-method V4 applied on this Mac by hand (`db.py scrub-listing-pe`, 264 points moved, AVIA's 2021 P/E gone): JCI EY 2021-12-31 3.74%, not 6.47%. 2085 tests). **Live run** 2026-11-11 `assist run --no-send` on main `6da3bdd`, exit 0: model `sha256:108d3a4587e7…`, journal 929 records; both rule fingerprints new (stocks `dab419fa…`, bonds `3c1d99aa…`, `since` 2026-11-11), `out/rules/` rebuilt on 120 month ends. Gates, all still insufficient: stocks enter 0/10 on, 20 off (2021-10 → 2026-07); stocks reduce 12 on, 8/10 off (was 7/7), mean on −2.3% vs off +0.9%, p 0.199; bonds enter 5/10 on, 17 off (2021-03 → 2026-07; was 3/11); bonds reduce 3 on, 19 off (was 1/13). Live: stocks rule proposes underweight (implied ERP 3.32% vs hurdle 4.64%, −1.31pt), not applied; bonds hold; IDN stocks and bonds stay neutral. Override gates unchanged (all failed). Earlier: 2026-11-11 (**P101-sun-10y**, branch `j9-sun-10y`: the IDN 10Y falls back to DJPPR's SUN 10Y benchmark quote (idxscape J9 `sun_benchmark_quote`, daily, 2021-01 → today) when there is no IGSYC 10Y, before the OECD proxy, in both IDN rules, the hurdle, the foreign candidates' IDR 10Y and `history.ten_year_months` (rule gate and override replay); read live, both rules call again on the old gap (2025-06-30 bonds enter / stocks reduce, 2026-03-31 reduce / reduce, all on `idxscape_sun`), today still reads IGSYC (hold / hold); touches rule modules, so the next run opens a journal segment and rebuilds `out/rules/` cold; 2081 tests). Earlier: 2026-11-10 (**S31 done, live run**, branch `s31-live`: idx-method's `endpoints_pull.py` run on this Mac for the three `comparison_*` endpoints only, after the close (16:17–16:22 WIB, 304 s; 1 metrics, 836 ratios, 836 industries rows, 0 failed); `assist industries` writes schema 4, 33 industries, 836 names, 4 s, identical bytes on a rerun; 162 names pass the gates, Tier A 23 names in 15 industries, Tier B 29, 22 industries with a pick (6 more have passing names but none scores 50); context only, the replay of record stays failed (t 0.02); 2072 tests). Earlier: 2026-11-10 (**keeper by dividend yield**, P98b: among unrated names in an industry and size group the highest `div_yield` is kept; size lines, industry level and phase N's defaults confirmed by the user; live run model `sha256:f38a1c1be6a4…`, journal 857 records, 11 models; guide 33 sells and 2 bucket buys). Earlier: 2026-11-10 (**phase O done**, F15: the investing principle as rules, S81–S84 merged to main `55dec7a`, 2071 tests; one name per industry and size bucket (`candidates/diversify.py`), a redundant row gets no new money, rebalance sales take redundant names in full first, then pro rata, kept names last; live run `--no-send`, model `sha256:427a7008dd87…`, journal 786 records, 10 models; guide 51 sells (16 redundant in full) and 2 bucket buys; size lines Rp 50T / 5T and the industry level are unconfirmed defaults). Earlier: 2026-11-10 (**phase N done**, F14: guided UI, S72–S80 merged to main `56c5025`, 2053 tests; `/` is "This week": orders by date with amount, shares, entry price, take-profit, stop, strength and why, from `out/guide.json`; the old overview is `/background`; unnamed sales are pro rata (`candidates/rebalance.py`), SBN and US stocks are bucket steps; live run `--no-send`, model `sha256:cf920942a6d4…`, journal 715 records, 9 models; 54 sells Rp 27.1m and 2 buys Rp 27.8m; choices 4, 7, 8, 9 on defaults; next: the user's investing principle as rules, phase O). Earlier: 2026-11-10 (**phase M done**, F13: average down on a held name, S67–S71 merged to main `bc595b9`, 2001 tests; cost basis in layer 5, `candidates/average_down.py` labels a sized add on a held name 5% or more below cost, entry status is context because its placebo is insufficient (1 of 10 windows), no name qualifies today (IDN stocks 96.9% vs 48%, BMRI over the 5% cap); live run model `sha256:aa9e0c60fe9c…`, journal 644 records, 8 models; Telegram not sent from that run, not configured in the shell). Earlier: 2026-11-10 (**P21 bug fixed**, P21b-entry-peak: a correction completes only on recovery to the peak it fell from, and no `entry_deep` fallback, so BSML, DEWI and 403 other names have no entry level; 1946 tests). Earlier: 2026-11-09 (**S31 replay of record on `industry_membership`**, branch `s31-replay` (user's call 2026-11-09): **failed**, t 0.02, p 0.508, perm_p 0.468, control t −0.17, 15 quarters 2022-12 → 2026-06, all on today's membership back-filled; momentum and liquidity stay on `cache/history/` because no store has traded value before 2021-10; 1943 tests). Earlier: 2026-11-09 (**S31 live run blocked again**, branch `s31`: idx-method's `stockbiter.db` is here but its `api_raw` is empty (no `/comparison` pull on this Mac), so `assist industries` exits 1 and no name has a tier; a diagnostic replay on `industry_membership` (same 33 IDX sub-sectors, code and `CONFIG` unchanged) **fails** its placebo, t 0.02, perm_p 0.47, control t −0.17, 15 quarters 2022-12 → 2026-06 (`docs/results/P50-tier-replay.md`); 1938 tests). Earlier: 2026-11-09 (**S15 done**, merged to main: `candidates/industry_value.py`, the fourth IDN screen, ranks within IDX-IC peers (sub-industry ≥ 8 names, else sector) on log multiples vs what ROE, growth, payout and ROIC justify plus PE and PBV vs own 5-year median; replay 95 of 119 month ends 2018-11 → 2026-09 **failed** (t 1.76 < 2.0, p 0.040, control t 0.37), names no one; its 10 defaults accepted by the user 2026-11-09 (`industry_value.CONFIG`, `docs/results/S15-industry-value.md`); dropping the own-history leg (fitted leg alone t 2.44) would be post-hoc, so only via an agent review; 1937 tests). Earlier: 2026-11-09 (**phase L done**, S57–S66 and S61b, merged to main `a8dd638`, F11 run opened model `sha256:b68e9bce1774…` (0.6.0); 1919 tests). What phase L delivered: the layer-2 overrides replayed point in time (IDN P17 on 262 month ends, 112 complete from 2017-07, S57; the five P28 markets with FRED GDP at its vintage, AUS fx on the MAS cross before 2023, S63), forward returns in IDR (IDN JCI, 10Y, rupiah vs USD, S58; foreign currency, local 10Y × FX, USA SPY, S64), and `eval/override_gate.py` (S59): up / down per asset, phase K's numbers, Holm per subject, a CLI-zeroed check, live monitor and revocation, written to `out/overrides/<SUBJECT>.json` by `assist run` and `assist overrides`. A passed side may cross a band in its direction (S61, MODEL_VERSION 0.6.0, stance `layer2`). P17 inflation falls back to dbnomics when bps-looker CPI is too short (S61b); P28 reads USD/IDR on the P65 splice (S62). **All 26 sides failed** (IDN currency down beat its placebo alone, t 2.47 p 0.047, but not Holm or CLI zeroed; S60, S65), so no override crosses a band: FRA, ITA and USA bonds stay held at neutral. Earlier: 2026-11-09 (**phase L planned**, on branch `phase-l`: the layer-2 overrides get a point-in-time history and a placebo gate before a shift may cross a band; **13 choices open for the user** (Phase L section); S57 P75-override-inputs done: P17 replayed on 262 month ends, every component computed on 109 of them, 2017-07 → 2026-10 except 2024-02 → 04 (a CPI fallback hole); the USA and JPN foreign `fx` components are n/a live (JISDOR here starts 2026-10-22); 1849 tests). Earlier: 2026-11-09 (**phase K done**, S45–S56, merged to main `32eb850`, F10 run opened model `sha256:7c387d7b4148…`; 1832 tests). What phase K delivered: the fingerprint hashes every rule module under `layers/` (S45); the IDN bonds rule reads USD/IDR as JISDOR spliced on the MAS cross, so it calls again (S46); `assist.history` reruns both IDN rules point in time on 120 month ends 2016-11 → 2026-10 (S47); `eval/gate.py` gates each rule on that history plus a live journal monitor, enter and reduce sides tested separately, written to `out/rules/` (S48, S56); the walk-forwards show neither rule near its gate (stocks enter 0/14, unreachable as valuation always reads rich, reduce 7/7; bonds "not yet", enter 3/11, reduce 1/13; S49, S50); an IDN home regime on four inputs (JCI 20d drawdown, IDX foreign flow z, USD/IDR, non-resident SBN) ladders IDN stocks and bonds on home risk_off, its −5pt shift not adopted (walk-forward insufficient), shown in the brief, `/regime`, Telegram and the daily check (S51–S54). Live 2026-11-09: global and home risk_off, every IDN stance neutral and laddered, no rule applied. Earlier: 2026-11-07 (**phase K planned**; **phase J done**: S44 P63-us-universe, a read timeout from `usfin serve` is `locked`, not a down server, US reads use one 60 s timeout and all bars come in one ATTACH query, so the USA list has a pool again (576 dividend / 370 GARP) but names no one, both replays failing the placebo; model `sha256:8c6a886f278d…`, run 7 m 23 s; S41 P61-fingerprint-scope, the fingerprint hashes each rule module's AST without docstrings, so comments and formatting no longer segment the journal, and the paper track shows only cumulative returns below 12 scored weeks; S42 P62-rebalance-split, each stance's `portfolio` splits the gap into `rebalance_pt` (to the 48/32/20 benchmark) and `tilt_pt` (the model's call), schema 1.1.0, shown in the brief, `/portfolio`, `/stance` and Telegram, which now opens "Paper only, not an order"; live all three legs neutral, so IDN stocks −48.9pt, IDN bonds +30.2, USA stocks +20.0 are all rebalance, tilt 0; S43 F9-docs; model `sha256:b836b881ad37…` on main, no run since, so the next run opens one new journal segment; 1633 tests). Earlier: 2026-11-06 (S40 done, P60-paper-benchmark, **phase I done**: the paper benchmark is 48% JCI / 32% SBN leg / 20% US stocks in IDR (unhedged price index: Alpaca SPY × USD/IDR, JISDOR from 2026-10-22 spliced onto the MAS cross before it), from `stance.BENCHMARK_PCT`; the old 60/40 is reported beside it and still scores every segment journalled before S39; live 1 week scored (10-16, −7.7% vs −9.4% on 60/40), 3 stale on the IGSYC hole and the 11-06 mark). Earlier: 2026-11-06 (S39 done, P59-benchmark: whole-portfolio benchmark IDN stocks 48 / IDN bonds 32 / USA stocks 20; every target is benchmark + tilt, the three legs scaled pro rata to at most 100%, the rest cash; the other 46 stances target 0% outside the 80/20 mandate; live 45.7 / 30.5 / 23.8 = 100%, cash 0%; model 0.4.0, new journal segment). Earlier: 2026-11-06 (**phase H done**, S37 F8-ui-layers: the nav adds Regime, Signals, Portfolio and Flows; the overview banner links `/regime`, a stance's Drivers card links `/signals/<SUBJECT>` (only when that layer file exists) and its Portfolio card `/portfolio`; every page and its `.json` twin is 200 live and in the e2e test). **Phases A–D are done** (F4-ops); phase F is done up to S21 (F6-us-stocks): one undervalued list per market, IDN and USA, in `out/candidates/`. **Phase G is done** (F7-ui): `assist status` serves the output read-only on 127.0.0.1:8790 (`/` stance grid, `/stance/<SUBJECT>/<asset>`, `/candidates[/<MKT>]`, `/paper`, `/journal`, `/status`, each with a `.json` twin), and `./start.sh` goes from a checkout to those pages in one step (S29: sync, doctor, a run if out/ is stale, serve, open). S30 adds `/industries[/<id>]`: every IDN name against Stockbit's industry average and the sector median in valuation, dividend, profitability and solvency, charted per industry (`out/industries/IDN.json`, context only). S31 (top tier per industry) is built, P48–P50, but its live run is blocked: idx-method's `api_raw` is empty on this Mac (2026-11-09). **Phases H, I and J are done** (layer pages, the 48/32/20 benchmark, review quick fixes). S31 and S22 are open.

What `assist run` does:
- It reads layers 0, 1 and 5 for every subject.
- For Indonesia it also reads layers 2–4: overrides, signals, the IDN bonds and stocks rules, and
  the layer-4 candidates.
- For the foreign subjects it reads layer 2 (P28 overrides: USA, JPN, euro area, AUS, SGP) and
  layer 4 (P29 index candidates).
- It writes 49 stance JSONs to `out/`, and journals them with every rule call, override and
  candidate decision.
- It writes the brief, which now opens with the doctor and carries the paper track (S13/S14).
- It writes one ranked undervalued list per market (S20/S21: `out/candidates/IDN.json` and
  `USA.json`) with paper sizes, adds them to the brief and the Telegram top 5, and journals every
  row.
- It writes this week's steps (`out/guide.json`, S75): dated orders per benchmark leg, shown on
  the home page and at the top of the brief and the Telegram message.
- It sends one Telegram summary a day.

Two launchd jobs are **installed and loaded** on this Mac (checked 2026-11-07; README,
*Scheduled jobs*):
- `com.tommy.investment-assist.weekly`: `assist run`, Monday 07:00 WIB.
- `com.tommy.investment-assist.regime`: `assist regime --check`, daily 07:00 WIB. It sends
  Telegram only on a regime or dollar change.

No stance has moved in phases B–D:
- On 2026-11-09 both IDN rules call `hold`; neither is applied: each gate in `out/rules/` is
  insufficient on its history (bonds enter 3/11, reduce 1/13; stocks enter 0/14, reduce 7/7)
  and the live monitor starts at 0 / 0 (phase K).
- The foreign overrides and candidates are hand-set, so they move scores but not bands until they
  beat a placebo.

**Gap 2b closed 2026-11-06 (P51-jci-idxscape):** JCI now reads idxscape `index_daily`
COMPOSITE (nightly, 2021-10-01 on), stitched to idx-method's frozen CSV before that. Paper
tracking scores its first week (2026-10-09 → 10-16, benchmark −9.4%). PHEI capture now runs on
this Mac (idxscape, 2026-11-06), but IGSYC has a hole 2026-10-22 → 11-03 here; since P52 a week
whose mark falls in a capture gap is left unscored rather than priced on an old yield.

**Next up:** phase L is done and nothing moved; the suspect override weights (P17 / P28 bonds, AUS currency) were reviewed (`docs/results/R-phase-l-weights.md`: noise, no bug) and the user kept them 2026-11-09. S31 is done (live tiers 2026-11-10, context only: its replay of record failed the placebo on `industry_membership`). Open: S22. Each Monday's run extends `out/rules/` and `out/overrides/` by a month end when one has passed, and the live monitors start counting from 2026-11-09. The phase K
review findings still open are listed in *Open questions*, and any change to a phase K number goes
through an agent review the user decides. Fetcher asks: the IDN 10Y for 2025-01 → 2026-09
(dbnomics, then idxscape) and AVIA's listing P/E (idx-method), *Open data gaps*. Each Monday's
weekly run now extends `out/rules/` by a month end when one has passed (a new rule fingerprint
rebuilds it cold, about 45 min). Meanwhile let the jobs and this Mac's PHEI history build a record; backfilling 10-22 → 11-03 from the Windows machine's raw captures stays deferred.
Open ops question: of the fetchers, only bisfetcher.refresh, dbnomics.refresh/serve,
worldbankscape.daily, idxscape.phei and (since 2026-11-09, the other Mac's uninstalled)
idx-method's four `com.tommy.stockbiter.*` jobs are launchd agents on this Mac; the other stores
are fresh but what refreshes them here is not traced. The stockbiter jobs need a live Stockbit
session (`../idx-method/run.sh login`); its close job (16:30) fills `api_raw`, which S31's live
tiers read. Pull `comparison_*` only after the close: the industry id hashes Stockbit's industry
averages, so a pull during trading (15:20 on 2026-11-10) split 33 industries into 226.

| Phase | Slices | Done |
|---|---|---|
| A. Skeleton + base layers (0, 1, 5; S32: layer 5 reads trade documents) | S0–S6, S32 | 8 / 8 |
| B. Indonesia overrides and rules (2, 3, 4) | S7–S10 | 4 / 4 |
| C. Foreign markets | S11–S12 | 2 / 2 |
| D. Track record and ops | S13–S14 | 2 / 2 |
| E. Layer 4 refinements (S31: top tier per industry) | S15, S31 | 2 / 2 |
| F. Undervalued stocks, macro-weighted (IDN, then US, JP) | S16–S22 | 7 / 8 |
| G. Local UI view (read-only pages over `out/`, journal, paper) | S23–S30 | 8 / 8 |
| H. Layer pages (regime, signals, portfolio) | S33–S37 | 5 / 5 |
| I. Benchmark and portfolio limits (80% IDN / 20% US stocks) | S39–S40 | 2 / 2 |
| J. Review quick fixes (fingerprint scope, rebalance vs tilt, docs, USA universe) | S41–S44 | 4 / 4 |
| K. Rules on their history, home regime (point-in-time rule gate, IDN home regime) | S45–S56 | 12 / 12 |
| L. Layer-2 overrides on their history (point-in-time override gate, all 26 sides failed) | S57–S66, S61b | 11 / 11 |
| M. Average down on a held name (cost basis in layer 5, gated rule, dip placebo) | S67–S71 | 5 / 5 |
| N. Guided UI (this week's steps with amount, date, entry price, TP and SL; plain words) | S72–S80 | 9 / 9 |
| O. The investing principle as rules (keep the screen's names, no redundant industry and size, rebalance respects it) | S81–S84 | 4 / 4 |

### Open data gaps (fetcher side)

Each gap is fixed in the repo named, never here. The brief flags each one under *Data health* or
*Stale inputs*.

- ~~**idxscape: the PHEI tables are missing on this Mac.**~~ Resolved by 2026-10-27: the F7-ui
  live doctor shows `igsyc_point PHEI` fresh (2026-10-26), and the paper track's SBN leg reads
  IGSYC.10 (P44). The IGSYC history starts in October 2026, so the rules' walk-forwards still
  have little to test on.
- ~~**There is no JCI fetcher.**~~ Closed 2026-11-06 (P51-jci-idxscape): idxscape
  `index_daily` (47 indices, 2021-10-01 on, nightly); `jci()` stitches idx-method's CSV before
  2021-10-01. Sector indices and LQ45 are readable as `IDX.<code>` for betas and S16.
- **idxscape: IGSYC hole 2026-10-22 → 11-03 on this Mac.** PHEI capture runs here since
  2026-11-06 (`com.tommy.idxscape.phei`, user's call), from 11-04 on. PHEI serves only the
  current page, so the hole can only be filled from the Windows machine's raw captures:
  deferred by the user until this Mac's own history suffices. Until then the paper weeks ending
  10-23, 10-30 and 11-06 stay unscored (P52).
- ~~**No IDN 10Y for 2025-01 → 2026-09 (21 months) in any store**~~ Closed 2026-11-11
  (P101-sun-10y): idxscape J9 (`sun_benchmark_quote`, DJPPR's daily SUN 10Y benchmark quote,
  2021-01 on, within ~5 bp of IGSYC and OECD on their overlaps) is read as `SUN.10` between
  IGSYC and the OECD proxy. The original note (P69, 2026-11-09): The OECD
  proxy `idn.rate.long` ends 2024-12 and IGSYC starts 2026-10, so both IDN rules are `no_call`
  on 2025-03 → 2026-09 and their walk-forwards stop at 2024-08 (bonds) and 2026-07 (stocks, with
  6 windows lost). Ask, in order: **dbnomics**, an IMF IFS IDN government bond yield (monthly)
  if it runs past 2024-12; **idxscape**, DJPPR SUN auction results (10Y benchmark
  weighted-average yield) as a dated series. The Windows PHEI captures fill only 10-22 → 11-03.
  Filling it adds about 8 bonds and 6 stocks gate windows; the bonds rule still cannot reach
  10 enter windows ("not yet"), but the stocks reduce side might.
- ~~**idx-method: `api_raw` is empty on this Mac**~~ Closed 2026-11-10 (S31 live run): the
  session was live, so `endpoints_pull.py --skip <all but comparison_*>` ran in idx-method under
  its job lock after the close (1 metrics, 836 ratios, 836 industries rows dated 2026-11-10, 0
  failed, 304 s); the 16:30 close job (installed, loaded) refreshes them on weekdays. Pull only
  after the close: industry ids hash Stockbit's averages, which move intraday.
- **idx-method: AVIA's P/E right after listing is wrong** (P66, phase K review; checked
  read-only 2026-11-09). **Closed 2026-11-11:** idx-method V4
  (`db.scrub_listing_pe`, after every factors pull) was run here by hand (`python3 db.py
  scrub-listing-pe`, user's call; the 11-10 pull had failed before its scrub): 264 points moved
  to `factor_series_dropped` (220 before first price, 44 listing P/E below 1), AVIA has no P/E
  before 2022; nothing changed here. The original note: `factor_series` daily `pe` for AVIA reads 0.21–0.24 from its listing
  on 2021-12-08 to 12-30 and 0.36 on 12-31 and 2022-01-02 (39.95 on 01-01, about 40 from 01-03),
  on a Rp 52–58T cap: an EY of about 280–450%, which lifts the cap-weighted JCI EY from 3.51%
  (11-30) to 6.47% (12-20). Ask idx-method to report it (and fix or drop P/E rows before the
  first full-year earnings after a listing). Here it touches only the 2021-12-31 history row,
  a reduce either way.
- **bps-looker: trade balance starts 2017-01** (`BPS_TRADE_BALANCE_USD_MN`, P75, 2026-11-09).
  It is the last P17 input to start, so the override gate's IDN window opens 2017-07. Trade
  from 2012 (GDP's first computed month is 2012-05) would add about 20 months, roughly 6
  windows. Ask bps-looker for the earlier BPS trade years. Also: bps-looker CPI y/y
  (2022=100, var 2263) starts 2024-01; the earlier base years would let P17 read BPS CPI
  throughout instead of splicing dbnomics. bps-looker keeps one vintage per variable (every
  row carries the last update), so GDP and trade revisions are read at today's values.
- **dbnomics: the OECD CLI has no vintage** (P75). `idn.cli` and every `*.cli` hold today's
  values only, and the CLI's latest months are revised most, so the override history reads a
  smoother CLI than was known (phase L choice 10). Ask dbnomics to keep a CLI vintage per
  refresh from now on, and an original-release history if OECD serves one.
- **dbnomics: the euro-area 10Y is a monthly average** (`ea.bund.10y`, dated the 1st; P82,
  2026-11-09). The override gate's EMU bonds return is therefore lagged a month (as the IDN OECD
  proxy) while its FX leg runs month end to month end, a half-month mismatch. Ask dbnomics for a
  daily or month-end Bund 10Y (ECB yield curve, AAA or Bund) if it serves one.
- **sec-edgar: `usfin serve` reads slower than 5 s count as `locked`** (P81, 2026-11-09). The
  foreign override replay lost four USA months to transient locks until reads were retried
  (`override_history.LOCK_TRIES`); a full-history DFF read over HTTP still times out at 5 s.
  An ops note for sec-edgar (serve latency), not a data gap; the replay bounds its reads and
  retries.
- **No JP, euro-area, AU or SG equity index price in any store** (P75; jquantster has no
  TOPIX/Nikkei on the free plan, ausdata no ASX 200, singstat no STI, dbnomics no Euro Stoxx).
  Those stocks overrides cannot be gated (phase L choice 13). Ask, if wanted: jquantster
  (TOPIX), ausdata (S&P/ASX 200), singstat (STI), dbnomics (a euro-area index).
- **ausdata: AUD/IDR (`FXRIR`) starts 2023-01** (P75). The AUS `fx` override component has no
  history before 2023-04; the MAS cross (singstat, from 2005) stands in for history (phase L
  choice 13), nothing to ask.
- **jquantster runs on the J-Quants free plan.** `investor_types` is empty (no TSE flows), and
  daily bars end 2026-08-14 (85 of the doctor's 100 days on 2026-11-07, so stale around
  2026-11-22).
- **openkrx has no `data/parquet` on this Mac** (`tw_index`, KR index). There is no KR or TW
  index valuation, and its HANDOFF read contract (R1) is still pending (2026-11-07).
- ~~**singstat's refresh was stale from 2026-10-07.**~~ Fresh again: the 2026-11-07 doctor reads
  2026-11-06.
- ~~**sec-edgar's FRED data on this Mac was stale from 2026-10-12.**~~ Fresh: the 2026-11-07
  doctor reads VIXCLS 2026-11-05.
- **There are no USD/IDR forwards in any store.** Hedged IDR returns use the policy-rate
  differential as carry (P27).
- **idx-method's stock history is short and unadjusted.** It holds about 5 years of closes,
  about 4 of which are usable for drawdowns (P21).
- **satudatascape** has no store yet (still missing 2026-11-07).
- ~~**idx-method has no valuation history or industry membership**~~ (for S15). Closed
  2026-11-06 in idx-method `c432999`: `factor_series` holds 10 years of daily PE, PBV, PS,
  EV/EBIT and EV/EBITDA, and `industry_membership` is dated (963 shares, 103 sub-industries).
  This unblocks S15; `candidates/industry_value.py` reads them since S15 (2026-11-09).

~~**Known bug (P21).**~~ Fixed 2026-11-10 (P21b-entry-peak): BSML's −96% "typical correction"
(entry 21) was a crash from 1805 counted as completed once that peak left the 3-year window and
the rolling high fell. A correction now completes only on recovery to the peak it fell from, and
a name with no completed correction has no entry level (no `entry_deep` fallback, user's call).

---

## Why

Thirteen fetchers each answer one narrow question. Nothing combines them, so every decision is
made by reading several dashboards and guessing how they add up. This repo makes that combination
explicit, repeatable and recorded, so a stance can be checked later against what happened.

## What

- **In:** read-only data from the sibling repos (table below).
- **Out:** one JSON per country × asset class (`out/{SUBJECT}/{asset}.json`, schema in
  `schema/stance.schema.json`, extends worldbankscape's `score.schema.json`), a weekly Markdown
  brief, and a Telegram summary.
- **Not in scope:** fetching from the internet, placing orders, writing into another repo.
  Missing data is added to the fetcher it belongs to (e.g. the FRED layer-0 series went into
  sec-edgar), never fetched here.

Output is heuristic context, **not investment advice**. Every payload carries the disclaimer and
the attribution of every source that fed it.

## Who

One user, on this Mac. Telegram is the only push channel.

## Where — sources and how each is read

| Layer | Repo | Store (verified 2026-10-13) | Access |
|---|---|---|---|
| 0, 2, 3, 4 | sec-edgar (usfin) | `data/usfin.duckdb`: FRED `fred_observation_latest`, `fred_as_of(DATE)` (layers 0, 2); TIC `tic_observation_latest`, `/series/tic?country=…` (layer 3); US fundamentals (layer 4); Alpaca US daily bars since 2016 (layer 4, S6–S13 done 2026-10-23): `alpaca_bar` / `alpaca_bar_latest`, security identity across renames `alpaca_security`, `alpaca_security_lookup(sym)`, split- and dividend-adjusted `alpaca_bar_adjusted_lookup(sym)` (prefer the macro: the whole `alpaca_bar_adjusted` view scans ~25M bars), `alpaca_universe`; objects listed in its `docs/plans/alpaca-market-data.md` | HTTP `?format=csv` from `usfin serve` (127.0.0.1:8660), because `serve` holds the DuckDB lock; read-only `ATTACH` when no lock is held |
| 0, 2 | bisfetcher | `warehouse.duckdb` (`$BISFETCHER_DB`): `series`, `observations`, `datasets` (contract block in its `PLAN.md`); `WS_EER` (layer 0), `WS_CBPOL` incl. BI rate `WS_CBPOL.M.ID`/`.D.ID`, `WS_CREDIT_GAP`, `WS_SPP`, `WS_DSR` (layer 2) | Read-only `ATTACH`, or its `serve` API while a refresh holds the lock. Done (S1–S13 on main); daily 05:30 refresh via `launchd/install.sh` (since 2026-10-26) |
| 1 | worldbankscape | `out/{SUBJECT}/{asset_class}.json` + `out/index.json` | Files (JSON Schema contract) |
| 2 | bps-looker | Postgres (`DATABASE_URL`) | Read-only role |
| 2 | ausdata | `warehouse.duckdb` | Read-only `ATTACH` |
| 2 | singstat (sgecon) | `data/sgecon.duckdb` | Read-only `ATTACH` |
| 2, 3 | dbnomics | `data/dbnomics.duckdb` (`$DBN_DB`): `series`, `observations`, `series_latest`, `series_status`; OECD CLI/BCI/CCI/CPI/rates, China `cn.*`, Eurozone (layer 2); `damodaran_erp`, `damodaran_crp`, `shiller` (layer 3). Ids and units in `docs/HANDOFF.md` | HTTP `?format=csv` from `dbn serve` (127.0.0.1:8770) first; its lock is mutual (a reader blocks `dbn refresh`), so a direct read opens, queries and closes. Daily 05:00 refresh (since 2026-10-26) |
| 2 | satudatascape | `data/satudata.db` (SQLite): data.go.id catalogue `packages`, `resources`, `tables` (extracted Parquet, grade A/B/C), `runs` (freshness); list in its `docs/PLAN.md` *Tables read by investment-assist*. Not on this Mac yet | `mode=ro` URI; doctor reports it missing until the file exists |
| 2, 3, 4 | jquantster | `data/jquantster.db` (SQLite): macro (layer 2), TSE investor flows (layer 3), prices, EPS, EDINET (layer 4) | DuckDB `sqlite` extension, read-only |
| 3 | idxscape | `data/idxscape.duckdb`: `stock_summary`, `broker_summary`, `fx_rate` (JISDOR), `sbn_ownership`, `corporate_action`; PHEI (J4 done 2026-10-22, migration 9): `igsyc_point` (as_of, tenor_y), `phei_bond_quote` (as_of, series_code, grp; never read a series as "the 10Y benchmark"), `credit_curve_point`, local use only (`docs/storage.md`). This Mac's copy lacks migration 9 until idxscape is pulled and loaded here | Read-only `ATTACH`. Nightly fetch with a 05:30 WIB morning retry (since 2026-10-26) |
| 3 | kseistat | `data/ksei.duckdb`: `v_market_composition`, `v_type_composition` | Read-only `ATTACH`. Daily 05:15 update (since 2026-10-26) |
| 3, 4 | idx-method | Fetcher only since 2026-10-14 (no books or screens; see its README, *Changes the parent must follow*). `store/data/stockbiter.db` (SQLite; since 2026-10-26 every `run.sh` setup and `daily` also imports its files: `bars` from `cache/history`, new `dividends` (symbol, seq, ex, value, ccy) and `fundamentals` (symbol, stmt, item, period, value, currency), `insider_history` incl. root `cache/insider` 2021-08..2026-08; each import logged to `pulls` as `idx-method:<source>`; the files stay, so switching the adapter to the tables is optional); `data/factors.json`, `consensus.json`, `composition.json`, `universe.json`, `sectors.json`, `special_boards.json`, `data/snapshots/<date>.json.gz`; `data/*_daily.csv`, `*_weekly.csv` (IHSG, LQ45, XIHD, IDX indices) **frozen at 2026-09-30, no longer updated since 2026-10-19: JCI needs another fetcher**; `cache/history/` (OHLC, value, net foreign flow), `cache/dividends/`, `cache/fundamentals/` | Read-only, files |
| 4 | openkrx | `data/parquet` (KR: `dart_*`, TW: `tw_*` incl. `tw_adjusted_daily`); Postgres holds only ops tables. Read contract = its `docs/HANDOFF.md` (slice R1, pending 2026-10-23; table changes listed in its `plan.yaml` R1 notes) | DuckDB read-only over Parquet (phase C) |
| 5 | financer | `~/.financer/financer.db` (SQLite): `holdings`, `trades`, `transactions` | `mode=ro` URI |

Every path lives in `config/sources.yaml` (relative to `../`, overridable by env). A source that
is missing, locked or stale is **reported, not fatal**: the stance that needs it drops its
confidence and names it in `stale_inputs`.

## When

Weekly brief on Monday 07:00 WIB (before IDX open), plus an on-demand `assist run`. A daily
regime check at 07:00 WIB sends Telegram only when the regime changes.

## How

### Stack

Python 3.12 and [uv](https://docs.astral.sh/uv/) (same as the siblings), DuckDB as the one query
engine (it attaches DuckDB, SQLite and Postgres stores), `httpx` for usfin CSV, `jsonschema`,
`pytest`. Tests never touch the network or the real stores: fixtures are small DuckDB/SQLite/JSON
files under `tests/fixtures/`, and an autouse fixture refuses non-localhost sockets (as openkrx
does).

### Shape

```
src/assist/
  sources/      one adapter per repo → tidy rows (series_id, date, value, as_of, source)
  layers/       regime.py (0), structural.py (1), overrides.py (2), signals.py (3),
                candidates.py (4), portfolio.py (5)
  stance.py     combine layers → stance JSON; validates against schema/
  brief.py      Markdown brief
  notify.py     Telegram (env IDX-style: ASSIST_TELEGRAM_TOKEN / ASSIST_TELEGRAM_CHAT, Keychain)
  journal.py    every decision + model fingerprint (hash of rules + weights + config)
  pipeline.py   gather (read layers) → build (stances) → out/, journal, brief, notify
  paper.py      paper track vs the IDR 60/40 benchmark, per model fingerprint
  cli.py        assist doctor | run | brief | regime [--check] | paper | journal
launchd/        weekly (Mon 07:00 WIB) and daily regime (07:00 WIB) LaunchAgent templates
```

### Rules carried from idx-method

- A rule may change a stance only after it beats a **placebo control** walk-forward; a procedure
  that also improves the control is fitting noise.
- Hand-set weights first; fitted weights only if they beat the hand-set ones on the control.
- Every run journals inputs, outputs and the model fingerprint, so a rule change segments the
  record.

### Per-slice workflow

Red (failing test) → green → `uv run pytest -q` and `uv run ruff check .` → live run against the
real stores → record numbers in the Progress table → commit. One slice per commit.

---

## Slices

### Phase A — skeleton and base layers

- [x] **S0 Skeleton + doctor.** uv project, `assist` CLI, `config/sources.yaml`, socket guard.
  `assist doctor` lists each source: present / missing / locked / newest date, never fails the run.
  *Done when:* live doctor shows all 14 sources with their newest data date (satudatascape
  reported missing until it has a store).
- [x] **S1 Adapter contract + worldbankscape.** `Source` protocol → tidy rows. worldbankscape
  adapter reads `out/` and validates against its schema. *Done when:* live run loads every
  country × asset score with its confidence and flags.
- [x] **S2 FRED adapter (usfin).** CSV over HTTP when `serve` is up, read-only `ATTACH` otherwise;
  same rows either way (one test asserts it). Reads `fred_observation_latest`, and `fred_as_of`
  for backtests. *Done when:* every layer-0 series listed in `CLAUDE.md` (25 today; `fred.yaml`
  holds 34 incl. layer-2 macro) loads live by both paths.
- [x] **S3 Regime (layer 0).** Hand-set rule on VIX level, HY OAS 13-week change, DTWEXBGS 13-week
  change, DFII10, NFCI (deliberately small; net liquidity, EM OAS, term premium and STLFSI4 are
  candidates to add only if they beat the placebo) → `risk_on | neutral | risk_off` + dollar direction. Placebo: the same rule
  on shuffled dates. Walk-forward test: does `risk_off` precede weaker JCI and IDR returns
  (JCI from idx-method `data/jkse_daily.csv`, IDR from JISDOR)? *Done when:* verdict and t-stat recorded here, with the
  control.
- [x] **S4 Portfolio (layer 5).** financer `holdings` latest `as_of` per account → weights by
  country × asset class. Mapping: IDX tickers → IDN stocks; SBN/ORI/SR/FR codes → IDN bonds;
  RDN/bank cash → IDR cash; anything unmapped is listed, not guessed. *Done when:* live weights
  add up to 100% and match the brokers' statement totals.
- [x] **S5 Stance v0 (layers 0 + 1 + 5).** `schema/stance.schema.json`; stance from the layer-1
  score, shifted by the regime; target weight band per stance; delta vs current weight; entry
  style (`lump | ladder`, ladder when `risk_off`). Journal every run. *Done when:* `assist run`
  writes valid JSON for every in-scope subject and a rerun with unchanged inputs writes identical
  files.
- [x] **S6 Brief + Telegram.** Markdown brief (regime, stance table, changes since last run,
  stale inputs, disclaimer); Telegram summary; same never-fail and send-once rules as idx-method's former paper daemon.
  *Done when:* a live brief is sent and a second send the same day is skipped.

- [x] **S32 Layer 5 reads financer's trade documents (planned 2026-11-06; done 2026-11-06,
  P53).** Roll each account's
  holdings forward from its latest statement through the trade confirmations and dailies that
  came after it, and carry each document's owner.
  - **Why.** financer slice 13 (2026-11-06) loads Stockbit Trade Confirmations as documents with
    `doc_type = 'trades'`, alongside Ajaib's dailies (also `trades`, since its slice 11). The
    adapter reads only `portfolio`, `broker_soa` and `savings_statement` (`_LATEST`), so layer 5
    misses:
    - **Priskila's Stockbit `4848825`, her whole account.** It has 8 confirmations (16–30 Oct
      2026), 95 trades, 37.2M IDR at cost, 63 positions, and no SOA yet. Layer 5 shows nothing
      for it.
    - **Every trade after an account's latest statement.** For example, Ajaib's 2026-11-02 daily
      (an ARNA sell) after its 2026-10-31 portfolio.
  - **financer's contract** (its `PLAN.md` *Slice 12 outcome* and *Slice 13 outcome*, schema 9):
    - `documents.owner` is `tommy` or `priskila`, and there is a new table `account_owners`. This
      adapter does not read either yet.
    - A `trades` document is `superseded` once a loaded SOA of the same account prints all its
      orders. So **`status = 'loaded'` already excludes every trade an SOA states**, and the
      adapter never has to de-duplicate.
    - A superseded document's settlement rows stay in `transactions`. That doesn't matter here,
      because the adapter does not read `transactions`.
    - Trades are in `trades` (`trade_date`, `symbol`, `side`, `quantity` in shares, `price_minor`,
      `gross_minor`, `net_minor`), keyed by `document_id`.
  - **Rule.** For each account (`issuer`, `coalesce(account_ref, '')`), the new holdings are the
    latest loaded broker statement's holdings, as today, plus the trades of every loaded `trades`
    document of that account with `statement_date` **after** that statement's `as_of`.
    - An account with no broker statement starts from nothing.
    - Each trade adds `quantity` for a buy and subtracts it for a sell.
    - A changed or new line is valued at the **last trade price** for that symbol in those
      documents, and an unchanged line keeps the statement's market value. The adapter has no
      price feed of its own; layer 4's idx-method bars are not on this Mac.
    - A line that reaches zero is dropped. A negative line (a sell of a position no statement
      shows) is kept in `unmapped` with its value, and never subtracted from a bucket.
    - `as_of` becomes the latest trade document's date.
  - **Known risk: the date basis of a statement's holdings.** Ajaib's portfolio moves on the trade
    date (financer FINDINGS). Whether Stockbit's SOA holdings are by trade date or by settlement
    date is unknown until Priskila's first SOA arrives. The rule assumes trade date (it applies
    trades dated after the statement). If her first SOA shows otherwise, the fix is recorded then.
  - **New fields on `Statement`:**
    - `owner`: read from `documents.owner` when the column exists, otherwise `'tommy'`
      (financer schema 8 and the test fixture).
    - `rolled_from`: the date of the broker statement the holdings start from, or None.
    - `trade_docs`: how many trade documents were applied.
    - `priced_at_trade`: the symbols valued at a trade price rather than a statement price.
    - Added by P53: `unheld`, the lines sold below zero (kept out of `holdings`, so layer 4's
      `holdings_from` never sees a negative), and `statement_holdings_idr`, the statement's own
      lines before rolling (for `StatementCheck`, which also gains `account`).
  - **Layer 5 output.**
    - `build_portfolio` sums both owners into one household portfolio, which is the user's goal
      in financer's slice 12.
    - `Portfolio` gains `by_owner`: IDR per owner per bucket.
    - `StatementCheck` is unchanged for a statement with no rolled trades. A rolled account's
      check compares the statement's own lines with its printed total, before rolling.
    - `stale_inputs` names an account whose latest input is older than `STALE_DAYS`, as today.
      For an account valued partly at trade prices, a `notes` line reads "valued at last trade
      price: N lines". It goes in the brief and the `/stance` portfolio block, not in
      `stale_inputs`.
      **Amended by P53:** to get there the note travels `Weights.notes` → the stance payload's
      optional `portfolio.notes` (`schema/stance.schema.json`, absent when empty, so outputs
      without notes are unchanged) → `brief.py` (one "Holdings:" line under the stance table) and
      `views/stance.py` (a Notes row). So P53 also touched `layers/types.py`, `stance.py`, the
      schema, `tests/test_brief.py` and `tests/test_view_stance.py`, outside its `owns`.
  - **Known gap (not this slice).** Priskila's RDN `6622844750` has no statement in financer yet
    (her Gmail filter is pending). About 12.8M IDR of her cash is therefore invisible. It appears
    without a code change once financer loads that statement, because it is an ordinary
    `savings_statement`.
  - **Tests** (`tests/layers/test_portfolio.py` and a new `tests/sources/test_financer.py`):
    - Fixture schema 9: `tests/fixtures/financer/schema.sql` gains `owner`, the `trades` table
      and the `account_owners` table, and its seed gains:
      - a priskila Stockbit account with two `trades` documents and no SOA;
      - an Ajaib-like account with a portfolio and one later daily that sells a held line to
        zero;
      - a superseded `trades` document, which must be ignored;
      - a `trades` document dated on or before its statement, which must be ignored.
    - A second fixture without `owner` (schema 8), to show the fallback.
    - Rolling forward: buys, a sell to zero, a negative line going to `unmapped`, the last
      trade price, and `as_of`.
    - `by_owner` adds up to `total_idr`.
    - `rows()` includes rolled holdings.
    - A rerun gives byte-identical stance JSON.
  - **Live:** read-only against `~/.financer/financer.db`, with the file's mtime unchanged.
    - Expect Priskila's 63 IDN stock lines, about 37.15M at trade prices. That is a little
      different from cost, which includes fees.
      **Amended by P53 (2026-11-06):** 37.15M is her trades' gross flow (buys 37,992,900 − sells
      838,500), not the rule's value. The rule values each line at its symbol's last trade
      price, which gives **36,535,800**; the 0.62M difference is price moves between a symbol's
      earlier fills and its last one.
    - Expect Ajaib's ARNA line gone, and `by_owner` showing both owners.
    - Results go in `docs/results/P53-portfolio-trades.md`, with no account numbers (as in P4).
  - *Done when:* layer 5 lists her Stockbit positions and Ajaib's post-statement sale, owners are
    split in `by_owner`, the weights still add up to 100, and a statement-only account's numbers
    are unchanged from before.
  - **Slice** (`plan.yaml`): P53-portfolio-trades.

### Phase B — Indonesia

- [x] **S7 IDN overrides (layer 2).** bps-looker CPI, trade and GDP (satudatascape once it has a store); BI rate from bisfetcher
  `WS_CBPOL.M.ID` (worldbankscape's BIS series until bisfetcher has data). Momentum shifts the layer-1 score by at most ±10 points.
- [x] **S8 IDN market signals (layer 3).** idxscape foreign net flow (IDR and USD via JISDOR),
  DJPPR non-resident SBN holdings change; kseistat foreign share trend; sec-edgar TIC US investor
  net purchases of Indonesian equities and bonds (`us_*_42218`).
- [x] **S9 IDN bonds rule.** Real yield, curve slope, foreign SBN flow, JISDOR trend, regime.
  idxscape J4 done 2026-10-22: read the IGSYC curve and `phei_bond_quote`.
- [x] **S10 IDN stocks rule + candidates (layer 4).** JCI earnings yield vs SBN yield, computed
  here (idx-method's `dividend_vs_bonds.py` was removed 2026-10-14). Candidates are built here:
  idx-method no longer picks stocks, so the dividend / value / momentum screens, cost model and
  entry levels move into investment-assist, read from its `factors.json`, `consensus.json`,
  `cache/history/`, `cache/dividends/` and `cache/fundamentals/`. Liquidity and momentum columns
  (`vol_1y`, `amihud`, `med_value_60d`, `days_traded_60`, `mom_12_1`, `near_52w_high`) are
  derived here from `cache/history/`. Each screen carries a placebo control before it may name a
  candidate. May split into S10a (market rule) and S10b (screens) when started.

### Phase C — foreign markets

- [x] **S11 Foreign overrides.** sec-edgar (BLS, FRED macro, TIC foreign holdings and net purchases
  of US securities), jquantster (macro, TSE investor flows), singstat, ausdata,
  worldbankscape ECB/BIS for the EU. Returns converted to IDR, hedged vs unhedged.
- [x] **S12 Foreign candidates.** Index-level only at first (US, JP, AU, SG); openkrx for KR/TW.

### Phase D — track record and ops

- [x] **S13 Paper tracking.** Each stance's implied allocation vs a fixed IDR 60/40 benchmark
  (60% JCI, 40% SBN index), marked weekly, segmented by model fingerprint.
- [x] **S14 launchd + README.** Weekly brief and daily regime jobs; doctor in the brief header.

### Phase E — layer 4 refinements

- [x] **S15 Industry-relative value screen (IDN, layer 4).** Undervalued in any style, not a
  dividend or growth book. A fourth screen beside `value` (B/P alone) in
  `candidates/screens.py`, behind the same gates, quality floor and placebo control.
  - **Peer group, not the market.** Rank inside the industry from the start, so structurally
    cheap industries (banks, plantations, coal, property) do not fill the list. Peers are the
    IDX-IC sub-industry with at least 8 names, else the sector. The baseline is the peer median
    computed here; Stockbit's `/comparison` industry averages are means, sometimes negative, and
    today-only, so they are a cross-check at most.
  - **Undervalued, not just cheap.** The signal is the gap between a name's multiple and the
    one its fundamentals justify, fitted within the peer group: log PBV on ROE, log PE on
    expected growth and payout, log EV/EBITDA on ROIC. Banks use PE and PBV against ROE and cost
    of credit only (no EV or FCF legs); asset-light names lean on EV/EBITDA and P/FCF.
  - **Scale.** Deviations as log(stock / peer median) or peer percentile, never percent.
  - **Earnings.** TTM is checked against the 3–5 year mean or forward EPS, so one-offs
    (e.g. LSIP EV/EBIT 0.13, BMTR PE 2 on 2026-10-26) do not rank first.
  - **Second leg: own history.** Each name's PE and PBV against its own 5-year median.
  - **Quality gates, does not score.** The existing floor stays a gate, so the screen stays a
    valuation screen.
  - **Point in time.** Peer medians per month end from idx-method's 10-year valuation series,
    fundamentals lagged to filing (check whether Stockbit's TTM steps at period end or filing),
    delisted names kept, membership as recorded (today's membership back-filled before records
    begin, flagged as such).
  - *Needs from idx-method:* the daily valuation series and industry membership in its plan,
    *Valuation history for investment-assist (planned 2026-10-26)*.
  - *Done when:* the screen replays over month ends, its placebo verdict is journalled, and a
    failing verdict names no candidate, as for the other three.
  - *Can start before idx-method V1 (found 2026-10-27).* `factor_series` already holds daily
    `mktcap` and `price` from 2016-10 and quarterly `ni_ttm`, `equity`, `cfo_ttm`,
    `op_income_ttm`, `net_debt` from 2016-12, so PE, PBV, P/CFO and EV/EBIT are computed here.
    V1 becomes a cross-check, and EV/EBITDA and PS wait for it (no revenue or D&A in the store).
    V2 (membership) and V3 (period-end vs filing lag) still block the point-in-time replay.
  - **Shipped (2026-11-09, branch `s15`).** `candidates/industry_value.py`, joined to
    `screens.run_screens` (so `layers.candidates` journals its verdict and `flags`). V3 settled
    read-only: the store's daily PE, PBV and EV/EBITDA step on the filing date (BBCA Q2 2025 on
    2025-07-30), so only `roce` is lagged 120 days. Normalised earnings use the median of 3 TTM
    years (a mean keeps 7/3 of a 5× one-off). Membership has one snapshot (2026-11-06),
    back-filled and flagged; none of the 47 delisted names has a sector, so they sit out. Not in S20
    (no expected return). Live: replay failed (t 1.76, p 0.040, control t 0.37), names no one;
    the fitted leg alone would pass (t 2.44, diagnostic only). Details and the 10 choices in
    `docs/results/S15-industry-value.md`.

- [x] **S31 Top tier per industry (IDN, planned 2026-10-29; live 2026-11-10).** A score from 0 to 100 for each
  name within its industry, and the best few names of each industry marked as the top tier.
  - **Why.** `/industries` (S30) is a pass/fail filter today: PE and PBV below Stockbit's
    industry mean, ROE above it, D/E under the cap. The names that pass are sorted by the mean of
    the four category scores. That has four flaws:
    - Being 1% cheaper passes as fully as being 50% cheaper.
    - A cheap name whose earnings are shrinking passes.
    - Dividend and solvency weigh as much as valuation.
    - Growth, earnings trend, momentum and liquidity are not read at all.
    The benchmark is also a mean that loss-makers drag down (industry PE −77). Of 836 names,
    73 pass (2026-10-26), in no order that compares one strength against another.
  - **Peer group.** The S30 industry (Stockbit's industry block). If fewer than 8 names in it
    pass the gates, the percentiles are computed over the sector instead, and the page says so
    ("ranked within sector"). Names are compared by rank, never against Stockbit's mean, so
    negative averages and outliers do not matter, and no clamp is needed.
  - **Gates.** A name that fails a gate gets no score; the page shows the reason. Gates do not
    add to the score.
    - Liquidity: `days_traded_60` ≥ 30 and `med_value_60d` ≥ IDR 1bn (`factors.derive`).
    - Positive TTM net income and positive equity.
    - Quality floor, the same numbers as the screens: `QUALITY_FLOOR` (Altman Z ≥ 1.8, interest
      cover ≥ 1.5, Piotroski ≥ 5 where present). Banks use `BANK_FLOOR`.
    - D/E under the industry cap. `DER_CAP` moves out of `views/industries.py` into the model,
      because it now decides which names get a score.
  - **Pillars.** A metric scores the name's percentile among its peers that have a value:
    (rank − 0.5) / n × 100, with ties sharing the mid-rank, and flipped where lower is better.
    A pillar is the mean of its metric percentiles.

    | Pillar | Weight | Metrics (non-financials) | Banks, insurers, multifinance |
    |---|---|---|---|
    | Value | 30 | PE on normalised earnings, PBV, EV/EBITDA, P/S | PE, PBV |
    | Quality | 25 | ROE, ROIC, operating margin, stability of the quarterly operating margin over 12 quarters (lower stdev is better), CFO/NI (`factor_series` `cfo_ttm`) | ROE, ROA, stability of quarterly ROE |
    | Growth | 15 | revenue TTM y/y, net income TTM y/y, revenue 2-year CAGR (S30 `financials`, needs ≥ 8 quarters) | net income TTM y/y, equity 2-year CAGR |
    | Health | 15 | D/E, interest cover, Altman Z, current ratio | CAR, gross NPL, NPL coverage, LDR (`factors.json`) |
    | Momentum | 15 | `mom_12_1`, `near_52w_high` | same |

    - **Normalised PE.** Price over the lower of TTM earnings and the mean of the last three
      TTM years. A one-off gain, such as BMTR's PE of 2 on 2026-10-26, then cannot rank first
      (the problem S15 names).
    - **Dividend yield** is shown, not scored. S18 owns dividend picking.
    - **Coverage rules.** A metric is dropped for a peer group when fewer than 5 peers have a
      value. A pillar needs at least half of its metrics. The composite needs at least 3
      pillars, Value and Quality among them. When a pillar is missing, the weights of the
      pillars present are scaled up to sum to 100, and the page shows the missing pillar.
  - **Composite and tiers.** The composite is the weighted mean of the pillars.
    - **Tier A:** the top 20% of the names that passed the gates in an industry, at least 1,
      at most 3 (at most 5 in an industry with 40 or more such names). Each must also score
      ≥ 60. An industry where no name scores 60 has no Tier A.
    - **Tier B:** up to as many names again, each scoring ≥ 50.
    - Ties break on market cap. Every weight, cutoff and gate lives in one `CONFIG`, and its
      sha is the model fingerprint.
  - **Output.** `out/industries/IDN.json` moves to schema 4. Each name gains `gates` (pass, and
    the reasons for a fail), `pillars` (score and metric count each), `composite`, `rank` and
    `pick` (`"A"`, `"B"` or null). Each industry gains `peer_group` and `picks`. The payload
    gains `fingerprint`. `assist run` journals one `industries` record per run: the picks, each
    name's pillars, and the fingerprint.
  - **Page.** `/industries` opens with one table, *Top tier by industry*: industry, symbol,
    composite, five pillar bars, cap tier, and S20's star. Each industry card then lists Tier A,
    and Tier B muted below it, with the gate failures counted. The metric chart and the
    financials timelines draw Tier A and B in place of the names that pass today's filter. The
    old filter is kept as a chip: "beats the industry average on PE, PBV and ROE".
  - **Replay.** At quarter ends from 2017 on, a reduced composite is rebuilt from
    `factor_series`. Value is PE, PBV, EV/EBIT and P/CFO. Quality is ROE and CFO/NI. Growth is
    `ni_ttm` y/y. Health is net debt/equity. Momentum comes from `cache/history/`.
    Fundamentals are lagged by `screens.LAG_DAYS`. Membership is idx-method's dated
    `industry_membership` (IDX sub-sector, the same 33 groups as S30), the latest snapshot on or
    before each quarter end, else the first one back-filled and flagged (survivorship and
    reclassification): the table starts 2026-11-06, so today every quarter is back-filled.
    *Changed by the user 2026-11-09* (was today's `out/industries/IDN.json`, which needs
    idx-method's `api_raw`). Momentum and liquidity from bars back to 2016-11 were approved the
    same day but no store holds daily traded value or volume before 2021-10, so they stay on
    `cache/history/` (from 2021-11) and the replay starts 2022-12.
    - **Test:** the 3-month forward return of Tier A minus its industry's median, each quarter
      (the quarterly cycle the user chose for phase F).
    - **Placebo:** the same tiers picked on composites shuffled within each industry.
    - **Weights are fixed before the replay.** The replay reports a result per pillar for
      diagnosis only. Changing a weight changes the fingerprint and makes a new model.
  - **Context only until the replay passes.** The tiers are shown and journalled. They feed no
    screen, S20 list, sizing or stance. Letting a passing Tier A feed S20 as its own style is a
    later decision, not part of this slice.
  - **Slices** (`plan.yaml`): P48-tier-model, then P49-tier-ui and P50-tier-replay, which can
    run in parallel.
    - **P48:** gates, pillars, composite and tiers in `candidates/tiers.py`, read by
      `peers.build`, plus schema 4 and the journal record.
    - **P49:** the `/industries` table and cards.
    - **P50:** the replay, its placebo, and the verdict on the page and in the brief.
  - **Blocked here today:** idx-method's `store/data/stockbiter.db` is not on this Mac
    (2026-10-29), so the live run waits for it. Tests use fixtures. *Unblocked 2026-11-10*
    (Progress, "S31 live run").
  - **Shipped in P48 (2026-10-29).** `candidates/tiers.py` (gates, pillars, composite, Tier
    A/B, `CONFIG` sha as `fingerprint`), attached by `peers.build`; `out/industries/IDN.json` is
    schema 4; `assist run` journals one `industries` record. `DER_CAP` now lives in the model
    and the view imports it. Gaps filled: a floor or D/E value that is absent is listed as
    `missing` and does not fail the name (liquidity data is required); insurers and
    multifinance have no prudential fields in any store, so their Health pillar is missing
    and only Piotroski floors them; the 2-year CAGRs need 12 quarters, not 8; a non-positive
    normalised earnings base ranks last on PE; Tier B can exist without a Tier A; `cfo_ttm` and
    the TTM NI years come from `factor_series`, else `factors.json` and the S30 statements.
    Details in `docs/results/P48-tier-model.md`. Live run still blocked (no `stockbiter.db`).
  - **Shipped in P49 and P50 (2026-10-29).** P49: `/industries` opens with *Top tier by
    industry* (Tier A, Tier B muted, five pillar bars, cap tier, S20 star), each industry tab
    lists its tiers, peer group and gate failures, the charts draw the picks, and the old filter
    is a chip; industries without picks sit in one collapsed card with the reason; a schema 3
    file shows a notice and the S30 view. P50: `candidates/tiers_replay.py` writes
    `out/industries/IDN.replay.json`, journals a `tier_replay` record (`moves_stance: false`)
    and adds a *Top tier replay* section to the brief. It picks through the same
    `tiers.assign` as the live model; quality floors have no history and are skipped (flagged);
    fundamentals count from period end + 120 days; besides `placebo.evaluate` the real mean
    must beat 95% of 200 within-industry shuffles (`perm_p` ≤ 0.05); fewer than 10 quarters
    with a Tier A in 3+ industries is an insufficient sample. **Still open:** the live run and
    verdict (no `stockbiter.db` here, and only 20 files in `cache/history/`). Since 2026-10-29
    `/industries` also shows the replay above the top tier table (status chip, verdict, Tier A
    excess vs placebo, t, p, perm p, control t, flags, per-pillar diagnostics collapsed; "has not
    run" when the file is missing) and its `.json` twin carries `replay`.
  - *Done when:* `assist industries` writes schema 4 with picks for every industry that has
    names passing the gates; a rerun with the same inputs gives identical bytes; `/industries`
    shows the top-tier table; and the replay verdict with its control is journalled and shown.

### Phase F — undervalued stocks, macro-weighted (planned 2026-10-27)

**Goal.** Name stocks that are undervalued for an IDR investor, in a dividend or growth style
(S15 covers plain value), Indonesia first, then the US and Japan. The macro outlook decides
**where to look and how much discount to demand**; valuation decides **which names**. A name
is a candidate only when its expected IDR return beats the hurdle for its market, after the
macro adjustment, costs and FX. The output is still heuristic context, not advice.

**How the pieces fit.**

```
layers 0–2 (regime, scores, overrides) ─► S16 sector tilt ─┐
layer 3 (flows, curve, ERP/CRP) ─────────► S17 IDR hurdle ─┼─► S20 one ranked list
idx-method / sec-edgar / jquantster ─► S18 dividend, S19 growth, S15 value ─┘   (+ layer 5 fit,
                                                                                entry, costs)
```

Rules that hold for every slice:
- Every expected return is in IDR, **unhedged**. Foreign names use `fx.py` and P29's
  `expected_fx_move` (the adverse 5% quantile, else UIP) as a haircut.
- Everything is point in time: fundamentals as of their filing date (`xbrl_as_of` for the US;
  the S15 V3 lag for IDN), prices as of the close, delisted names kept.
- Everything starts as context. A tilt or screen changes a ranking only after its month-end
  replay beats the placebo control (`assist.eval.placebo`); until then it is journalled and
  shown, and names no candidate.
- Quality is a gate, not a score: the existing `QUALITY_FLOOR` and `BANK_FLOOR` are reused.

**Slices** (order: S17 → S16 → S18 ∥ S19 → S20 → S20a → S21 → S22; S15 slots in before S20 when
idx-method V2/V3 land):

- [x] **S16 Macro sector tilt (IDN).** A journalled, hand-set sensitivity table: each IDX-IC
  sector against the drivers the layers already read. Coal, nickel and CPO against Pink Sheet
  trends and China momentum (worldbankscape, dbnomics `cn.*`). Banks and property against the BI
  rate direction, the real yield and the credit gap (bisfetcher `WS_CBPOL`, `WS_CREDIT_GAP`).
  Exporters vs importers against USD/IDR (JISDOR, `WS_EER` REER). Consumer names against CPI
  and consumer confidence (bps-looker, dbnomics CCI). Size and quality lean on the layer-0
  regime. The output is a tilt from −1 to +1 per sector, with its drivers. It is applied in two
  ways: a sector's required margin over the hurdle (S17) moves by at most ±2 pt, and S20's
  per-sector cap moves between 3 and 7 names. *Replay:* sector-month tilts against the
  next-quarter sector returns built from `factor_series` mktcap, with a placebo. *Done when* the
  tilt and its verdict are journalled and shown in the brief.
- [x] **S17 IDR hurdle per market.** The required return each name must beat. IDN: SBN 10Y
  (PHEI `igsyc_point`, else the dbnomics proxy, flagged) plus US implied ERP (`damodaran_erp`)
  plus IDN CRP (`damodaran_crp`). Foreign: the local 10Y plus ERP plus that country's CRP,
  converted to IDR (unhedged) with the expected FX move. Risk-off adds a premium (start: +1 pt, journalled
  in the model fingerprint). This builds on S10's JCI earnings yield vs SBN and P29's index
  test, so one function serves the index and the single names.
- [x] **S18 Undervalued dividend (IDN).** This upgrades the `dividend` screen from "high
  trailing yield" to "the dividend return beats the hurdle and is safe":
  - Expected return = forward yield + sustainable growth (ROE × retention, capped at nominal
    GDP growth).
  - Safety gates: payout below 90% of earnings and covered by CFO (`cfo_ttm`), paid in at
    least 4 of the last 5 years (`cache/dividends`, 979 names), no cut in the last 2 years
    unless earnings recovered.
  - A cheapness leg: yield against the name's own 5-year yield range.
  - Banks are judged on dividends with their prudential floor; holding companies are skipped.
  - Replay: quarter ends with trailing data, 3-month forward return, placebo as for the other
    screens.
- [x] **S19 Undervalued growth, GARP (IDN).** Growth at a price the hurdle allows:
  - Reverse DCF: the 10-year earnings growth the price implies at the S17 hurdle, against the
    name's realised growth (5-year `ni_ttm` and `cfo_ttm` CAGR) and consensus
    (`consensus.json`). A candidate is a name whose implied growth is clearly below both.
  - PEG on forward PE as a cross-check.
  - Quality: ROE or ROCE stable or rising over 3 years, CFO/NI ≥ 0.8 (accruals), equity
    dilution under 5% a year.
  - Replay uses realised growth only: there is **no consensus history** (16 snapshots since
    2026-08-30, none holding consensus). The consensus leg is live and journalled, and is
    judged once about 24 months of monthly snapshots exist (fetcher ask below).
- [x] **S20 One ranked list.** S15, S18 and S19 plus the S16 tilt and S17 hurdle make one list
  per market. Each row carries style, expected IDR return, margin over the hurdle, drivers,
  risks, entry (`entry.py`, with P21's bound), costs (`costs.py`) and layer-5 fit (held or not,
  add or trim from financer). It extends the output contract with an `out/candidates/*.json`,
  a brief section *Undervalued candidates* and the top 5 in the Telegram summary. Within a
  style, rank by margin; across styles, never by a mixed score.
- [x] **S20a Position sizing.** Each candidate that passes gets an IDR amount, top-down:
  - **Budget.** The asset-class budget is the layer-5 `target_pct` minus `current_pct` for that
    country × stocks stance, times the portfolio value from financer. An `underweight` or
    `avoid` stance gives no new money, only trims of names already held.
  - **Split.** Inside the budget, weight ∝ margin over the hurdle ÷ the name's 1-year
    volatility (`vol_1y`), so a cheaper, calmer name gets more.
  - **Caps.** At most 5% of the portfolio per name, the S16-tilted sector cap, and liquidity:
    each tranche stays under `costs.py`'s participation limit of the 60-day median value, and
    a name below one lot is dropped.
  - **Timing.** Amounts are split into `entry.py` tranches (laddered when the regime is
    risk-off).
  - **Trims.** A name already held that no longer passes, or whose margin turned negative, gets
    a trim line instead of an add.
  - Sizes are journalled with the model fingerprint and paper-tracked (S13) before real money.
    The per-name and sector caps are starting values for the user to confirm.
- [x] **S21 US single stocks.** The same engines on sec-edgar data, in USD and then IDR:
  - Fundamentals from `xbrl_as_of(d)` (point in time by filed date, 122.7M facts; one scan
    per screen through `usfin serve` `/screen` or a read-only open).
  - Prices from `alpaca_bar_adjusted_lookup(sym)`, identity across renames from
    `alpaca_security_lookup`, dividends from `alpaca_corp_action`.
  - Universe: US-listed operating companies with ≥ US$2bn market cap and ≥ US$20m median daily
    value. Peers by SIC from `edgar_company`.
  - The US hurdle and the FX haircut come from S17. A US name must beat the IDN alternative in
    IDR, not only US Treasuries.
- [ ] **S22 Japan, then KR/TW.** JP: jquantster `fins_summary` (company forecasts for EPS and
  dividends make S18/S19 natural there) and `daily_bars`. **Blocked:** bars end 2026-07-31 on
  the free plan, so prices are 12+ weeks old; it runs as context only until fresher prices
  arrive. KR/TW: openkrx `dart_fs_line` exists, but there are no prices on disk; **blocked on
  openkrx R1** and a price table. AU and SG stay index-level (P29): no single-stock store.

**Asks to the fetchers** (each goes into that repo's plan, never built here):
- idx-method: V2 and V3 (membership, TTM lag) for S15 and S19. **New V4:** keep a dated
  consensus snapshot (EPS and revenue forecasts, target price) per month into `factor_series`,
  so S19's forward leg can be tested later. **New V5:** quarterly revenue and D&A, for PS,
  EV/EBITDA and revenue growth.
- ~~idxscape: the JCI and sector index series (gap 2b).~~ Done 2026-11-06 (`index_daily`,
  read as `IDX.<code>`; P51). S16's replay and the betas can switch to the official indices.
- jquantster: a fresher daily price source (paid plan or another feed) before S22 ranks JP.
- openkrx: R1 HANDOFF and KR/TW daily prices on Parquet.

**Decided by the user (2026-10-27).**
- **Review quarterly.** Candidates are reviewed each quarter, dividend names included, so every
  replay scores the **3-month forward return** from quarter ends (not month ends) and the list
  turns over at most once a quarter. GARP follows the same cycle unless the user says otherwise.
- **Unhedged.** Foreign expected returns are unhedged IDR returns with the adverse FX haircut;
  no hedge cost is modelled for candidates (`fx.py`'s hedged path stays for the stances).
- **Size positions.** S20 sizes each candidate (S20a below).

### Phase G — local UI view (planned 2026-10-27)

**Why.** The output is spread over 49 stance JSONs, two candidate lists, a Markdown brief, the
journal and `assist paper`. Reading it means opening files. `assist status` (commit `35606ff`,
never planned) already serves a page on 127.0.0.1:8790, but it only shows source health and
launchd jobs. Phase G puts the output itself on that server.

**Done when** (each one covered by a slice's test):
1. `/` shows the regime and dollar banner and a country × asset grid (stocks, bonds, currency),
   with stance, score and confidence per cell, and a marker on cells with stale inputs.
   Commodities are listed below the grid. Cells link to their detail page (S24).
2. `/stance/<SUBJECT>/<asset>` shows drivers, risks, watch, entry, portfolio (current, target,
   delta), flags, stale inputs, sources, layer-1 score, fingerprint, and the change since the
   previous snapshot. An unknown subject or asset returns 404. A path never comes from the URL
   (S25).
3. `/candidates` shows each market's hurdle, the styles with verdict, t, p and pool, the ranked
   rows with margin, sizes and tranches, the sizing budget, trims and excluded names (S26).
4. `/paper` shows the 60/40 benchmark summary and each model segment. `/journal` shows the
   chain check and records per model (S27).
5. The existing health page moves to `/status`. Every page has the same nav, the disclaimer and
   a `.json` twin, and the HTML escapes every value read from a file (S23).
6. Everything is read-only: no page writes to `out/` or `journal/`, fetches anything, or sends
   Telegram. The server still listens on 127.0.0.1 only (S23, S28).

**Out of scope.** Editing, triggering a run or a send, auth, charts or a JS framework, any other
host, launchd for the server, changes to how stances or candidates are built.

**How.**
- **Stack.** Python 3.12 stdlib `http.server` and `html.escape`, as `status.py` already does. No
  new dependencies, no JavaScript, no templating library. The CSS tokens come from `status.PAGE`,
  with dark mode via `prefers-color-scheme`.
- **Shape.** `src/assist/web.py` holds the server loop and the shell:
  - an `App` dataclass with the paths and callables (out, snapshots, journal, paper, health),
    defaulting to `pipeline.Paths.default()` and `paper.paper_track`;
  - `layout(title, body, active)`, with `status.PAGE`'s CSS and dark mode moved into it;
  - the shared chips;
  - a route table of `(regex, handler(app, match) -> View(title, html, data) | None)`, where
    None means 404 and a trailing `.json` returns `data`.
  `status.py` imports `web`, never the reverse, and `status.serve` stays as a wrapper so the CLI
  is unchanged until S28. Views go one module each under `src/assist/views/`: `overview.py`,
  `stance.py`, `candidates.py`, `paper.py` (paper plus journal).
- **Reads.** Stances come from `brief.load_out(out)`, the previous snapshot from
  `brief.previous_snapshot`, and candidates from `out/candidates/*.json`. The journal goes
  through `journal.Journal(...).verify()` and `segments()`. Paper is
  `paper.paper_track(journal=..., until=today)`, read-only against the stores (0.5 s here). It can hit dbnomics' mutual lock, so an error is a notice and the report is cached per day and journal mtime. Every
  page is rebuilt on each request, as `/status` is. A missing or invalid file shows a notice,
  never a 500.
- **URLs.** `/stance/IDN/bonds` is matched against the loaded stances, so it is never turned
  into a path. `/candidates/<MKT>` works the same way.
- **CLI.** `assist status` keeps its name and flags. Its help text and the README line name the
  new pages (S28).

- [x] **S23 Shell + router** (P40-ui-shell). Shared layout and nav, the route table, `/status`,
  404s, `.json` twins, escaping.
- [x] **S24 Overview** (P41-ui-overview). Regime banner, stance grid, commodities, stale markers.
- [x] **S25 Stance detail** (P42-ui-stance). One stance's fields, plus the change since the last
  snapshot.
- [x] **S26 Candidates** (P43-ui-candidates). IDN and USA lists with verdicts, sizes and trims.
- [x] **S27 Paper + journal** (P44-ui-paper). Benchmark, segments, chain check.
- [x] **S28 Fan-in** (F7-ui). README and CLI help, a live check of every page against the real
  `out/`, Progress rows.

**Review** (2026-10-27, fresh subagent, folded into the notes in `plan.yaml`):
- redirect at `/` broke `test_status.py`: fixed. P40 moves that test to `/status`, and every slice touching `web.py` runs it.
- no wiring for paths and the paper callable before F7: fixed (`App` with real defaults in P40).
- import cycle between `status` and `web`: fixed (`web` owns `serve`).
- PLAN and `plan.yaml` named the shell differently: fixed (`View`, `layout(title, body, active)`).
- wrong field and function names: fixed with the real names:
  - `previous_snapshot` returns a directory;
  - `Loaded.problems`;
  - `_grouped_line`;
  - flags are objects;
  - `held_idr`, `size.idr`, `size.tranches` is a list, `net_margin_pt`, `action`, `dropped`;
  - tilt `passed` and `verdict`;
  - paper `annualized` and `volatility`, worst week computed;
  - segment fields;
  - `verify()` raises.
- stance fixtures are flat: fixed (`tests/fixtures/ui/out/` in the `out/` layout).
- USA has no currency cell: fixed (tested).
- escaping, URL guard and HEAD tested only once or not at all: fixed (a `<script>` value per view; the 404 cases are named).
- `/paper` can hit dbnomics' lock: fixed (errors shown as a notice, report cached).

- [x] **S29 One-step start** (P45-start, added 2026-10-27). `./start.sh` at the repo root goes
  from a fresh checkout to the pages in one command:
  1. check `uv` is installed;
  2. `uv sync`;
  3. `assist doctor`;
  4. `assist run --no-send` when `out/` is empty or its newest stance is older than today (`--run` forces a run, `--no-run` skips it);
  5. start `assist status`, wait until it answers, then open the browser (`--no-open` skips that).

  `--send` lets the run send Telegram, `--install-jobs` also runs `launchd/install.sh` (opt-in,
  never the default), and `--port` passes through. The README gets a *Quick start* and its
  *Data gaps* section is brought up to date: PHEI is fresh here since 2026-10-26, FRED since
  2026-10-23, and the paper track is blocked by the missing JCI fetcher.

- [x] **S30 Peer comparison per industry** (P46-peers, added 2026-10-27). Each IDN name
  against its industry and its sector in four categories: valuation (PE, PBV, P/S,
  EV/EBITDA), dividend (yield; payout shown), profitability (ROE, ROA, ROIC, net, operating
  and gross margin) and solvency (D/E, liabilities/equity, current ratio, interest cover,
  Altman Z), split into big (≥ IDR 10T), mid (1–10T) and small cap.
  - **Source.** idx-method already stores Stockbit's `/comparison/{sym}/ratios` and
    `/industries` verbatim in `api_raw` (`endpoints_pull.py`, weekdays 16:30), so nothing is
    fetched. An industry is the set of names with an identical Stockbit `industry` block
    (33 on 2026-10-26, unnamed in the data). The groups match the IDX sub-sectors Stockbit
    lists in idx-method's `data/universe.json` one for one, sector by sector, so each is named
    by the sub-sector whose anchor names it holds (`peers.SUBSECTORS`: BBCA → Bank, TLKM →
    Telekomunikasi, …); Barang Rekreasi (DOSS), Energi Alternatif (ALII, SEMA) and Logistik &
    Pengantaran (TMAS, SMDR) are by elimination. A group with no anchor takes its sector name.
  - **Benchmarks.** The industry and sector medians computed here. Stockbit's own averages are
    means that loss-makers drag below zero (industry PE −77 and −115 on 2026-10-26), so they
    are shown as a cross-check and never scored (as S15 decided).
  - **Deviation.** log(name / median), clamped at 4×; a category score is the signed mean, so
    positive is better. Context only: no screen, verdict or stance reads it.
  - **Output.** `out/industries/IDN.json` from `assist run` (never fails the run) or
    `assist industries`; `/industries` (S20 names starred). The page per industry
    (`/industries/<id>`: category chart, tables) was removed on 2026-10-29.
  - **Ranked list (2026-10-27).** `/industries` shows one chart per industry, no table: per
    metric (PE, PBV, yield, ROE, D/E) Stockbit's industry average as a grey bar, then a bar
    per passing name (blue better than the average, red worse), the average dashed and the
    D/E cap a red line; the industry of the best overall score first, its names in that order.
    Since 2026-10-28 the benchmark is Stockbit's industry average (no industry median), and a
    name passes when its PE and PBV are each below the industry average, its ROE above it, and
    its D/E is from 0 up to its industry's cap (1 by default; per-industry exceptions in
    `DER_CAP`, none for banks and insurers); dividend is not filtered and a missing value
    fails. 73 of 836 names in 19 industries pass on 2026-10-26.
  - **Financials timelines (P47-financials, 2026-10-28; moved 2026-10-29).** Each industry
    card on `/industries` shows, under its metric chart, a quarterly timeline per statement for
    its passing names with statements, at most 8 (one line each, in the chart's order): income
    statement (revenue, gross, operating and net profit) and balance sheet
    (equity, total debt, cash), the last 12 quarters (2023Q3–2026Q2), each quarter on its own.
    Then profitability per quarter over the last 3 years (since 2026-10-29, in place of y/y
    profit growth): gross, operating and net margin on revenue and ROE (net income × 4 on the
    quarter's equity), none on a revenue or equity at or below 0, the axis clipped to ±100%
    (hover gives the real value). The
    latest-quarter tables of the old page were not carried over. Read from
    idx-method's `fundamentals` at build time into `out/industries/IDN.json` (schema 3,
    `periods` + per-name `financials`; 502 of 834 names, 2.6 MB). **Not shown: total assets
    and liabilities.** idx-method's `assets`/`liabilities` are totals for some names (BBCA),
    non-current parts for others (TLKM, ASII), and neither for others (BBRI assets IDR 62T,
    BMRI liabilities 21T on 2026Q2); 459 of 480 names fail assets = liabilities + equity.
    USD reporters (ADRO) are stored as IDR and read near zero. Both are idx-method fixes.

**F7-ui notes (2026-10-27).** Per-slice details are in `docs/results/P40-ui-shell.md` …
`P44-ui-paper.md`.
- **Wiring.** `cli._status` builds `web.App` from `pipeline.Paths.default()` (out/,
  data/snapshots/, journal/) with the doctor + launchd snapshot as `health`, and calls
  `web.serve(app, routes=status.ROUTES)`. `--siblings-root` still reaches the paper track through
  `ASSIST_SIBLINGS_ROOT`. `status.serve` stays as a wrapper for its own test. The subcommand's help
  and the startup line read "local pages: stances, candidates, paper, journal, source health"
  (the startup line is flushed, so it shows in a background log).
- **Disclaimer once.** The stance page no longer repeats the stance's `disclaimer` above the
  footer; it shows it only when the text differs from `web.DISCLAIMER` (P42's finding).
- **Costs.** Every page but `/status` answers in 2–120 ms. `/status` (and its twins, and HEAD)
  takes about 3.5 s, all of it the doctor probes; the UI pages do not wait on it.
- **What the pages show today.** No stance moved and no candidate is sized (IDN budget IDR 0,
  USA no names), and `/paper` scores 0 weeks for every one of 8 model segments: see the STATUS
  section. Several fingerprints start on the same day, so only the last of each day can ever
  rule a week (P44).
- **Phase G findings carried over:** HEAD builds the whole page (P40); 30 of 35 country cells are
  stale, so the stale chip is the norm (P41); the size and tranche rendering is covered only by a
  made-up fixture until a market has a budget (P43).

---

### Phase H — layer pages (planned 2026-11-06)

**Why.** Phase G serves the *output* of every layer, but only layer 4 and the stance itself
have pages. Layer 0 shows as one word in the banner ("neutral, dollar flat"), layers 2 and 3
as free-text lines in a stance's *Drivers* card, and layer 5 as one *Portfolio* card per
stance. None of their numbers are in `out/`: the stance JSONs carry only the final fields and
text drivers, so a page cannot show them without reading the stores, which the UI must never
do. Phase H writes each layer's structured result to `out/layers/` during `assist run`, then
gives each a page.

**Done when** (each one covered by a slice's test):
1. `assist run` writes `out/layers/regime.json`, `out/layers/<SUBJECT>.json` (layers 2–3 per
   subject) and `out/layers/portfolio.json`, each with `as_of`, `schema_version`, the model
   fingerprint, sources, stale inputs and the disclaimer, and a short history for every series
   a page charts. A layer that fails is a stale input in the file, never a failed run (S33).
2. `/regime` shows the regime and dollar call, every layer-0 input (VIX, HY OAS, EM OAS, curve,
   net liquidity, NFCI, STLFSI, real yield, broad dollar, Brent, ...) with value, date,
   direction and its vote, and a 1-year weekly line per input, plus the regime history from the
   journal's regime records (S34).
3. `/signals/<SUBJECT>` shows layer 2 as a table (component, value, change over its window,
   direction, newest point, per-asset shift and cap) and layer 3 as a table (signal, value,
   direction, source). For IDN it also charts net foreign flow (IDR and USD, 60 days), JISDOR
   (60 days, carried-forward days marked), the IGSYC curve (today vs 4 weeks ago), non-resident
   SBN holdings and JCI (1 year). Unknown subject → 404 (S35).
4. `/portfolio` shows holdings per account and owner (financer, incl. P53's trade roll-forward),
   weights per asset class against each stance's target, the deltas and tranches, trims from the
   candidate lists, unmapped value and statement age (S36).
5. Nav gains Regime, Signals and Portfolio; the Overview banner links to `/regime`, a stance's
   Drivers and Portfolio cards link to `/signals/<SUBJECT>` and `/portfolio`. Every page has a
   `.json` twin, escapes every value and stays read-only on 127.0.0.1. README and a live check
   of every page close the phase (S37).

**Not in scope:** new inputs, new rules or any change to a stance: the pages show what the run
already computes. Foreign subjects get the layer-2/3 tables only (no charts) until their
signals have series worth drawing.

- [x] **S33 Layer files in `out/layers/`** (P54-layer-out). `pipeline` keeps the `Regime`
  inputs, `IdnOverrides`/foreign overrides components, `IdnSignals` and the `Portfolio` it
  already builds, and `write_layers` serialises them, with chart series cut to fixed windows
  (1y weekly for layer 0, 60 days daily for flows and JISDOR, 1y daily for JCI, two IGSYC
  curves). JSON schemas in `schema/layers/`. The brief and stances are unchanged.
- [x] **S34 `/regime`** (P55-ui-regime). Inputs table and sparklines in stdlib HTML/SVG as the
  rest of `views/`; regime history from journal records of kind `regime` (done 2026-11-06,
  `docs/results/P55-ui-regime.md`).
- [x] **S35 `/signals/<SUBJECT>`** (P56-ui-signals). Layer-2 and layer-3 tables for every
  subject; the IDN charts listed above. (Done 2026-11-06, `docs/results/P56-ui-signals.md`;
  also `/signals`, an index of the subject files.)
- [x] **S36 `/portfolio`** (P57-ui-portfolio). After P53 (it owns `layers/portfolio.py` and the
  stance view's portfolio card). Done 2026-11-06, `docs/results/P57-ui-portfolio.md`.
- [x] **S38 `/flows`: where the household's money moved** (P58-flows, planned 2026-11-06; done
  2026-11-06, `docs/results/P58-flows.md`).
  Months of transfers between the household's own accounts, matched across financer's
  statements, and the gaps where one side has no statement.
  - **Why.** The user wants to see money move from Tommy's BCA savings (`bca_tahapan`, financer
    slice 13) to Priskila's BCA RDN and on into her Stockbit trades. Layer 5 shows holdings;
    nothing reads financer's `transactions`. financer leaves linking transfers to the parent
    (*fetch and store only*).
  - **Inputs.** A new adapter method, `FinancerSource.movements(start, end)`, reads only
    `status = 'loaded'` documents of every doc type. It yields date, issuer, account, owner,
    doc_type, document id, direction, amount (IDR), description and raw_description.
    - A `trades` document (a Stockbit TC or an Ajaib daily) yields **one** movement, not its fee
      rows: the settlement, an amount of minus `closing_minor`, dated on the trades'
      `settle_date`. Its fee rows are parts of that one payment.
    - Card purchases are kept, and they count as external spending.
  - **Matching** (`assist/flows.py`, pure functions):
    - **Internal transfer.** A debit in account A pairs with a credit in another household
      account B when:
      - the amounts are equal to the rupiah;
      - the dates are within 3 days of each other;
      - and the pair is one-to-one, chosen greedily by smallest gap, then by date, then by
        document id.
      This covers savings → RDN, savings → card payment, and RDN → broker settlement.
    - **Named but unmatched.** A debit whose `raw_description` contains a name from the
      **gitignored** `config/household.local.yaml` (`owners: {tommy: [...], priskila: [...]}`;
      `config/household.example.yaml` is committed with invented names) and that has no matching
      credit is listed as "to <owner>, receiving account has no statement in financer".
    - **Broker settlement unmatched.** A trades document whose settlement has no matching
      debit is listed as "paid from RDN (statement not loaded)".
    - Everything else is external in or out, totalled per account.
  - **Output.** A `assist flows` command writes `out/flows/<YYYY-MM>.json` for the last 12
    months with data, plus `out/flows/index.json`. Each file has:
    - `as_of`, `schema_version`, `sources`, `stale_inputs` and the disclaimer;
    - accounts (issuer, account shown as its last 4 digits, owner, opening and closing for the
      month where a statement gives them);
    - matched transfers (from, to, date(s), amount, gap in days);
    - unmatched named debits and unmatched settlements;
    - external totals in and out per account and per owner.
    `out/` is gitignored and the page is local only. Schema: `schema/flows.schema.json`.
  - **Page.** `/flows` shows the latest month and `/flows/<YYYY-MM>` any month in the index.
    The month comes from the index, never from a path built out of the URL. Unknown month → 404.
    - A stdlib SVG diagram: accounts grouped by owner in columns, and an arrow per matched
      transfer whose width follows the amount. Unmatched named debits are dashed arrows to a
      "no statement" box.
    - Tables of transfers, unmatched items and external totals.
    - A `.json` twin, every value escaped, and a notice instead of a 500 when no files exist.
    - The route is added in `web.py`; the nav link comes with F8.
  - **Tests** (`tests/test_flows.py`, `tests/test_view_flows.py`, fixture
    `tests/fixtures/financer/` with invented accounts and names):
    - a savings → RDN transfer between owners matches;
    - an RDN → trades settlement matches, using one movement per trades document and not its fee
      rows;
    - a savings → card payment matches;
    - no match for a 1-rupiah difference, a 4-day gap, or the same account on both sides;
    - two equal transfers pair one-to-one;
    - a named debit with no receiving statement is listed;
    - a settlement with no RDN statement is listed;
    - superseded documents are ignored;
    - no `household.local.yaml` means no named matches and no error;
    - the page renders, the twin matches the file, an unknown month is 404, values are
      escaped;
    - a rerun gives byte-identical files.
  - **Live** (expected, 2026-10):
    - Tommy's BCA savings → his Ajaib RDN transfers match.
    - The five debits naming Priskila (12, 14, 19, 23, 31 Oct) are unmatched-named, because her
      RDN has no statement in financer yet.
    - Her 8 Stockbit TC settlements are unmatched.
    - Her Mandiri savings → Mandiri card payments match in months where both statements exist.
    - Results go in `docs/results/P58-flows.md`, with no full account numbers and no names
      beyond the owner keys.
    **Amended by P58 (2026-11-06):** the matched October transfers between his savings and
    his Ajaib RDN run RDN → savings (3, 8.36M); savings → RDN happened in March and April. There
    are six named debits, not five: the sixth is his own BCA card payment (10-23, 12.29M), whose
    credit is on the card statement of 11-16, not loaded yet. Her 8 TCs settle 6 in October and 2
    in November (37,223,485.62 together). Mandiri savings → card match in every month 2025-12 to
    2026-09. Also added: `ledgers()` and `owner_map()` on the adapter (balances, and mapped
    accounts with no statement as stale inputs); a card's debits are spending, never a transfer
    candidate; a settlement is a credit to the broker for a buy. Fixtures in
    `tests/fixtures/flows/`. `/flows` opens on 2026-11, the latest (partial) month.
  - *Done when:* `/flows/2026-10` shows Tommy → his RDN matched, Tommy → Priskila and her
    Stockbit settlements as unmatched with the reason, and the rest as above. When financer
    loads her RDN statement, those become matched transfers with no code change.
- [x] **S37 Fan-in** (F8-ui-layers). Nav and cross-links, README pages list, CLI help, e2e test
  of every route and `.json` twin, live check on the real `out/`, screenshots light and dark.
  (Done 2026-11-06, `docs/results/F8-ui-layers.md`. `assist run` does not yet write
  `out/flows/`, so run `assist flows` for now.)

### Phase I — benchmark and portfolio limits (planned 2026-11-06)

**Why.** `BENCHMARK_PCT` is empty, so each stance anchors on what is already held and adds its
own tilt (+5 pt overweight). Nothing ties the targets together: on 2026-11-06 the stock targets
sum to 111.9% (96.9% held IDN stocks + 3 overweight stock stances at 0 + 5) and bonds to 26.8%.
The deltas are directions, not a plan that can be carried out.

**Decided by the user (2026-11-06).** The whole portfolio's benchmark is **80% Indonesia, 20% US
stocks**, with the paper track's 60/40 stocks/bonds kept inside the 80:

| Leg | Benchmark |
|---|---|
| IDN stocks | 48% |
| IDN bonds (SBN) | 32% |
| USA stocks | 20% |
| everything else (other countries, foreign bonds, commodities) | 0% (outside the mandate) |

Context the user weighed (heuristic, not tax advice; confirm with a tax consultant): US stocks
have beaten JCI for an IDR holder mostly through USD/IDR depreciation; US dividends carry 15%
withholding with a W-8BEN (treaty), foreign dividends are exempt in Indonesia only if reinvested
here (UU Cipta Kerja / PMK 18/2021), foreign capital gains are taxed at progressive rates, and
US-situs assets above US$60k fall under US estate tax for a non-resident (Ireland-domiciled
UCITS ETFs avoid that). None of this is modelled yet; the brief names the estate-tax risk on the
USA stocks stance.

**Done when:**
1. ✓ (S39) Every stance's target follows one rule: benchmark + tilt (±5 pt, `avoid` → 0), then the three
   legs are scaled down pro rata if they sum above 100; anything below 100 is cash. A stance
   outside the mandate keeps its view (stance, score, drivers) but targets 0% and says "outside
   the 80/20 mandate"; a holding there shows as a trim (S39).
2. ✓ (S39) Across all 49 stances the targets sum to at most 100%, tested; `/portfolio` shows the sums
   and the cash remainder; the S20a sizing reads the new targets (its 5% per-name cap stays) (S39).
3. ✓ (S40) The paper track's benchmark becomes 48% JCI / 32% SBN leg / 20% US stocks in IDR (unhedged,
   price index), marked weekly as now; the old 60/40 segment stays as it was scored (S40).

- [x] **S39 Benchmark 48/32/20 and the 100% rule** (P59-benchmark). `stance.BENCHMARK_PCT`,
  the outside-mandate note and the pro-rata cap in `stance.py`; brief, `/portfolio` and sizing
  follow. The model fingerprint changes, so the journal opens a new segment. Expect large trims
  at first (IDN stocks 96.9% held vs 48% target, USA 0% vs 20%): the entry stays laddered.
  *Done 2026-11-06:* `docs/results/P59-benchmark.md`. A mandate leg more than
  `stance.TRANSITION_PT` (10 pt) from its target is laddered 3 × 10 days, adds and trims alike
  (user, 2026-11-06); live all three legs are.
- [x] **S40 Paper benchmark with a US leg** (P60-paper-benchmark). A third paper leg: US stocks
  in IDR from sec-edgar (Alpaca SPY adjusted bars, or FRED SP500) × USD/IDR. Data gap: this
  Mac's JISDOR starts 2026-10-22, so the history needs another IDR rate (FRED
  CCUSMA02IDM618N is monthly) or an idxscape JISDOR backfill; decide in the slice. CLAUDE.md's
  "fixed IDR 60/40 benchmark" line changes with this slice, with the user's OK.
  *Done 2026-11-06:* `docs/results/P60-paper-benchmark.md`. US index: Alpaca SPY close × split
  factor (price, 2016-01-04 →; FRED SP500 is not in sec-edgar). USD/IDR: JISDOR from
  2026-10-22, the MAS cross USD/SGD ÷ IDR/SGD (singstat, daily from 2005) before it; on the 10
  overlap days the two differ by at most 0.12%. The 60/40 is kept side by side, not chained: a
  segment whose stance payloads carry `portfolio.benchmark_pct` (S39 on) is scored on 48/32/20
  with its journalled targets, every older one exactly as before. CLAUDE.md's paper-benchmark
  line awaits the user's OK.

### Phase J — review quick fixes (planned 2026-11-07)

**Why.** The 2026-11-07 review found output that misleads before the next Monday run:
- The −51.2 pt IDN stocks trim comes from moving to the new benchmark, but the brief and
  Telegram show it as if the model called it (G3).
- The weekly job will push names sized to sell with nobody reading the brief first (O4).
- The journal opened three model segments in 8 days, because the fingerprint hashes the rule
  modules' raw bytes, so a docstring edit segments the record (G4).
- The paper track annualises a single week to −98.5% (G4).
- The docs no longer match the state (O3).

No decision rule, band, tilt, benchmark or ladder changes in this phase. The ladder (3 × 10 days,
adds and trims) stays as the user decided on 2026-11-06.

- [x] **S41 Fingerprint scope** (P61-fingerprint-scope). The fingerprint hashes each rule module's
  AST with docstrings removed, so comments, docstrings and formatting no longer change it, while
  any logic change still does. This method change segments the record once. The paper track
  hides annualised returns until a segment has 12 scored weeks.
  *Done 2026-11-07:* `docs/results/P61-fingerprint-scope.md` (`11efb4e`, merge `b7088bd`). Config
  files are still hashed by bytes, except `config/household*.yaml` (names for `/flows`), which
  `0f4d2d4` keeps out as plumbing. `paper.MIN_ANNUALISE_WEEKS` = 12: the brief, `/paper` and
  `assist paper` read "annualised after 12 scored weeks" (it showed −98.5% on one week).
- [x] **S42 Rebalance vs tilt** (P62-rebalance-split). The stance payload's `portfolio` splits the
  gap into `rebalance_pt` (benchmark − current) and `tilt_pt` (target − benchmark). The brief,
  `/portfolio` and Telegram name the benchmark part as a rebalance to the 48/32/20 benchmark, not
  a model call. Telegram's sized lists are headed "paper only, not an order" and point to the
  brief.
  *Done 2026-11-07:* `docs/results/P62-rebalance-split.md` (`679d7c4`, merge `0b88219`). Stance
  schema 1.1.0, both fields optional; the 0.1 pt rounding of the pro-rata cap goes into the
  rebalance part, so a neutral leg always shows tilt 0. Live all three legs neutral, so the whole
  gap is rebalance: IDN stocks −48.9pt, IDN bonds +30.2, USA stocks +20.0.
- [x] **S43 Docs refresh** (F9-docs). PLAN STATUS, open data gaps, README and CLAUDE.md coverage
  match 2026-11-07: launchd jobs installed, idx-method valuation history landed, JCI P/E wired,
  phases H–J, and the Progress rows for S41–S42.
  *Done 2026-11-07:* `docs/results/F9-docs.md`.

- [x] **S44 USA universe over HTTP** (P63-us-universe). The USA undervalued list is empty (pool 0
  on 2026-11-06): `usfin serve` takes ~22 s for `/prices/universe`, the adapter's HTTP timeout is
  shorter, the timeout reads as "server down", and the fallback ATTACH meets serve's lock
  (`sec-edgar (locked): universe`). Give the US candidate reads a long timeout as paper does
  (`paper.US_HTTP_TIMEOUT`), keep a timeout distinct from a down server, and keep the run's
  wall time bounded. `edgar_company` has no SIC, so there are no US peer groups: a sec-edgar gap.
  *Done 2026-11-07:* `docs/results/P63-us-universe.md`. A read timeout is `locked` (no ATTACH
  into serve's lock), one `US_HTTP_TIMEOUT` (60 s) for US candidates and paper, bars of all names
  in one ATTACH query behind an exact liquidity floor; USA pool 576 (dividend) / 370 (GARP), both
  replays fail the placebo, so no names.

### Phase K — rules on their history, home regime (planned 2026-11-07)

**Why.** Two gaps from the 2026-11-07 review.

*G1. No rule can change a stance for about two years.* Each IDN rule is gated only on its own
journalled calls (`pipeline.journalled_verdict`): one call a month, judged on the 3-month forward
return (`pipeline.RULE_HORIZON` = 3, stride 3, block 3), needing at least 10 `enter` and 10
`hold`/`reduce` months (`placebo.MIN_N` = 10). On 2026-11-07 both stand at on 0 / off 0 (the
journal holds 5 stocks calls, 4 `hold` and 1 `no_call`, none with a forward return yet, and
5 bonds calls, all `no_call`), so the
earliest pass is about late 2028. Until then every stance is layer 1 + regime + capped hand-set
overrides. What the code shows on top of that:
- The live bonds rule cannot call at all: idxscape JISDOR on this Mac starts 2026-10-22, and the
  rule needs 60 fixings (`MIN_FX_DAYS`), so 11-07 reads `idxscape JISDOR (11 of 60 fixings)` →
  `no_call`. `paper.usd_idr` already splices the MAS cross (singstat, daily from 2005) before
  JISDOR; the rule does not.
- The model fingerprint does not cover the rules: `journal.RULE_GLOBS` has `layers/*.py`, not
  recursive, so `layers/bonds/idn.py` and `layers/rules/idn_stocks.py` are not hashed. A threshold
  change in either rule today does not segment the journal.
- Point-in-time history that exists for the rule inputs (read-only checks on 2026-11-07):
  FRED through `fred_as_of`; JCI idxscape `index_daily` 2021-10-01 → 2026-11-05 stitched to
  idx-method's frozen CSV before (P51); idx-method `factor_series` daily `pe` and `mktcap`
  2016-11-07 → 2026-11-06, ~997 names listed and delisted, PE stepping on the filing date
  (`c432999`, its store/README), loss makers as negative PE; IDX foreign flow (idxscape
  `stock_summary`) 2021-10-01 on; KSEI 2023-10 on (monthly); non-resident SBN (idxscape
  `sbn_ownership`) 2021-01-04 on; BI rate bisfetcher `WS_CBPOL`; Damodaran US ERP monthly from
  2008-09 and IDN CRP semi-annual snapshots (dbnomics).
- What is missing: an IDN 10Y between the OECD proxy `idn.rate.long` (monthly average, ends
  2024-12, so no call after about 2025-02 under the 90-day `PROXY_CALL_AGE`) and IGSYC (from
  2026-10-06, with a hole 10-22 → 11-03 here): about 19 months with no 10Y anywhere in the
  stores. Both rules need it (the stocks rule's implied ERP uses the real 10Y). worldbankscape
  stores scores only from 2026-10-12, so the stocks rule's macro input has no history.
- So a historical walk-forward runs on roughly 2021-11 → 2025-02 for stocks (flows and the 10Y
  both needed: about 40 month-ends, about 13 non-overlapping 3-month windows) and 2021-02 →
  2025-02 for bonds (about 16 windows; P31 found 5 `enter` in 39 months). At 10 per side neither
  can pass on today's data. Phase K replaces "wait until 2028" with a measured distance to the
  gate per rule and side, and names the data that would close it. The bonds walk-forward
  **cannot be done to the gate yet**; it is run and reported anyway.

*G2. The regime cannot see an Indonesia-only shock.* JCI fell 18.8% from 6,192.9 (2026-10-06) to
5,030.3 (2026-11-05), −11.6% on 10-16 alone (idxscape `index_daily`), while the global regime (5
counted FRED inputs, 4 candidates) read neutral on every run to 11-06. It turned risk_off only on
2026-11-07 (VIX 28.2, HY OAS +0.77pt/13w, real yield 2.60%), after the fall. Non-resident SBN
holdings barely moved (IDR 915.4T on 10-06, 914.8T on 11-04). No laddered entry was asked for on
IDN legs because of the shock (they are laddered since S39 only because each is more than 10pt
from its target). P8 found the global risk_off coincident for JCI (2020-03 and 2025-04 came
before +14.5% and +13.9% rebounds), so a home regime is tested before it may shift a score.

**Decided** (already, by the user or earlier phases):
- No change to the stance bands, `TILT_PT`, the 48/32/20 benchmark, the 100% rule or the
  3 × 10-day ladder (`TRANSITION_PT` included).
- A placebo control before any stance change, rules and home-regime score shift alike.
- Hand-set thresholds stay as written; none is tuned to a walk-forward (P8, P22, P31). A changed
  threshold is a new model and starts a new verdict.
- The fingerprint segments the record once per released model change: the G1 and G2 model
  changes ship together. Slices land on branch `phase-k`; their live checks run with
  `Paths.under(<scratch>)` so the real `journal/` and `out/` are untouched; F10 merges to main
  and makes the one run that opens the new segment.
- The global regime stays as it is (inputs, thresholds, `REGIME_SHIFT`).

**Decided by the user (2026-11-07): all ten recommended defaults, as bracketed below.**
These numbers are fixed: they change only through an agent review (user, 2026-11-07). A slice that
finds one wrong reports the evidence and leaves it; a separate review agent judges it and the
user decides.
1. Historical window and stride. [Month-end as-of dates from the first month with every
   required input to the last with a full 3-month forward return; horizon 3 months, stride 3,
   block 3, as the live gate.]
2. `MIN_N`, historical vs live. [10 per side in non-overlapping windows for the historical
   gate, as live; the live journal keeps its own path to a pass at 10 per side.]
3. What revokes a passed rule live. [The live monitor revokes it once it has at least 5 calls per
   side and its signed t is −1.0 or lower (an edge the wrong way); a verdict whose rule
   fingerprint differs from the running rule counts as no verdict.]
4. The stocks rule's macro input in history (no worldbankscape score before 2026-10-12). [Layer 1
   held at 50, shifted by P17's override as of each date. Live, the rule's macro input uses the
   same, so the rule that passes is the rule that runs; layer 1 still sets the band stance.]
5. Diagnostic variants. [Report the 1-month horizon and a valuation-only stocks variant
   (2016-11 on, about 33 windows) in the docs; neither may gate a stance unless you adopt it as
   the rule, which makes it a new model.]
6. Bonds 10Y history. [Say "not yet" and ask the fetchers, in order: dbnomics, an IMF IFS IDN
   government bond yield if it runs past 2024-12; idxscape, DJPPR SUN auction results (10Y
   benchmark weighted-average yield); the Windows machine's PHEI captures fill only 10-22 →
   11-03.]
7. Home-regime inputs and thresholds. [Points: JCI below its 20-day high by 7% (1) or 12% (2);
   IDX net foreign 20-day sum z-score against the trailing 250 days ≤ −1.5 (1); USD/IDR +2%
   over 20 fixings (1) or +4% (2), JISDOR spliced on the MAS cross; non-resident SBN −1.5% over
   20 days (1). Risk_off at 2 points or more, else neutral (no home risk_on). An input counts
   only if its newest point is at most 7 days old; DJPPR history is posted monthly, so the
   walk-forward mostly tests the first three.]
8. What the home regime does. [Home risk_off ladders the adds and trims of IDN stocks and IDN
   bonds 3 × 10 days (an entry style, no stance change, so no gate). A −5pt shift on those two
   scores only after the P71 walk-forward passes; with global risk_off as well the shift is −5,
   not −10.]
9. The overrides (layer 2, IDN and foreign). [Leave them out of phase K: they never cross a band
   and layer 1 has no history to test a crossing. List them as the next gate to build.]
10. The bonds rule reading the spliced USD/IDR live (it then calls again, still gated). [Yes.]

**Done when:**
1. The fingerprint hashes every module under `layers/` (the IDN bonds and stocks rules too) and
   the new gate and home-regime modules (S45).
2. The bonds rule reads USD/IDR as JISDOR spliced on the MAS cross, live and in history; it no
   longer gives `no_call` on a short JISDOR (S46).
3. `assist rules` writes `out/rules/IDN-stocks.json` and `IDN-bonds.json`: the historical verdict,
   the live monitor, the state (passed, insufficient, failed, revoked), on/off per side against
   `MIN_N`, the months covered and the inputs missing per month; `assist run` gates each rule on
   it (S47–S48).
4. The stocks and bonds walk-forwards are run on the real stores, with the distance to the gate
   and the fetcher asks written down; a bonds "not yet" is stated if so (S49–S50).
5. The home regime is in `out/layers/regime.json` (`home`) and in each IDN stance (`home_regime`),
   schemas bumped a minor version; IDN entries ladder on home risk_off; a score shift only if its
   walk-forward passed (S51–S53).
6. The brief, `/regime`, Telegram and the daily `assist regime --check` show the home regime
   (S54).
7. One new journal segment from the F10 run; Progress rows and STATUS updated (S55).

- [x] **S45 Fingerprint covers the rule subpackages** (P64-fingerprint-rules). `RULE_GLOBS` goes
  recursive under `layers/`, so `bonds/idn.py` and `rules/idn_stocks.py` are hashed. Test first:
  a constant edit in either changes the fingerprint, a docstring edit does not.
- [x] **S46 USD/IDR for the bonds rule** (P65-usdidr-source). A source that serves `JISDOR` as
  `paper.usd_idr` builds it (JISDOR from its first fixing, MAS cross before, gaps after kept as
  gaps); `IdnSources` gives it to `idn_bonds`. Test first: 11 JISDOR fixings plus MAS history
  give a 20-fixing trend and a breakout flag.
- [x] **S47 Point-in-time rule history** (P66-rule-history). `assist.history`: month-end as-of
  dates, each rule rerun as known that day (FRED `fred_as_of`, the S46 USD/IDR, a `factor_series`
  EY provider with the `FactorSnapshots` interface, layer 1 per open question 4), with the call,
  the missing inputs and the 3-month forward return (JCI; `bond_returns` on the 10Y). Test first
  on fixtures: no row uses data dated after its as-of or not yet known.
- [x] **S48 Historical gate and live monitor** (P67-rule-gate). `eval/gate.py` replaces
  `journalled_verdict`: the P9 verdict on the S47 history plus the journalled calls as monitor,
  the state, the distance per side, keyed to the rule fingerprint; `assist rules` writes
  `out/rules/`, `assist run` reads it (rebuilds it when missing or stale). Test first: pass,
  insufficient, revoked, and a fingerprint mismatch.
- [x] **S49 Stocks walk-forward, live** (P68-stocks-history). Run S47–S48 on the real stores;
  record calls per month, on/off, t, p, control t, the distance to 10/10 and the S47 EY against
  the snapshot EY on their overlap (2026-08-30 →); the open question 5 variants as diagnostics.
- [x] **S50 Bonds walk-forward, live** (P69-bonds-history). The same for bonds, 2021-02 → 2025-02
  plus IGSYC months; state "not yet" if the sample cannot reach the gate, and write the 10Y ask
  into *Open data gaps*. Parallel with S49.
- [x] **S51 Home-regime inputs** (P70-home-inputs). `layers/home_inputs.py`: JCI 20-day
  drawdown, IDX net foreign 20-day z-score, USD/IDR 20-fixing move (S46), non-resident SBN 20-day
  change, each point in time with its newest date and stale line. Test first on fixtures,
  including the 2026-10-16 day (JCI −11.6%). Parallel with S47.
- [x] **S52 Home-regime rule and walk-forward** (P71-home-regime). `layers/home_regime.py`:
  classify on open question 7, `history` and `check` as `regime.py` (weekly Fridays 2021-10 →,
  JCI 20d and IDR 20d, `direction=-1`), plus a ladder-against-lump entry cost on the same
  dates and a P8 rerun of the global regime on the stitched JCI to 2026-11 (report only).
  `HOME_SHIFT_ADOPTED` stays False unless it passes. Parallel with S48.
- [x] **S53 Home regime in the stance** (P72-home-stance). `HomeRegime` type; `build_stance`
  ladders IDN stocks and bonds on home risk_off (open question 8) and shifts only if adopted;
  stance schema 1.2.0 `home_regime`; `regime.json` `home` block (layer schema 1.1.0); journalled
  with the regime. Test first: a home risk_off with a neutral global regime ladders an IDN add.
- [x] **S54 Home regime on the pages** (P73-home-pages). Brief *Home regime (IDN)* line beside
  the global one, `/regime` section with the four inputs and their 1-year lines, Telegram line,
  and `assist regime --check` sends on a home state change too.
- [x] **S56 Reduce side and bond-return timing** (P74-reduce-side; found by the phase K review
  on `review/phase-k`, 2026-11-07, which kept all ten numbers). The gate tested enter against
  hold + reduce, yet `gated_stance` would apply a reduce on that verdict, so reduce calls would
  move stances untested. The gate now also runs the reduce side (reduce vs enter / hold,
  direction −1, same window and numbers), `rules.schema` 1.1.0 `reduce`; an enter applies only on
  the enter verdict, a reduce only on the reduce verdict, a hold never. The bonds forward return
  read the OECD proxy's monthly averages, so a month-end call's return started mid-month, before
  the call: the averages are lagged one month (`history.lag_monthly_averages`). Test first: a
  passing enter verdict never applies a reduce; a reduce side that beats its placebo passes on its
  own; the 2016-11-30 call is priced from December's average.
- [x] **S55 Phase K fan-in** (F10-phase-k). Merge `phase-k`, one live `assist run` (the new
  segment), Progress rows for S45–S54, STATUS, README, *Open data gaps*; CLAUDE.md lines only
  with your OK.

Parallel groups: {S45, S46} → {S47, S51} → {S48, S52} → {S53, S56} → {S49, S50} → S54 → S55.

### Phase L — layer-2 overrides on their history (planned 2026-11-09)

**Why.** Phase K left the overrides out (its open question 9). P17 (IDN) and P28 (USA, JPN, EMU,
AUS, SGP) shift each layer-1 score by a hand-set sum of momentum components, capped at ±10
(`MAX_OVERRIDE`). Since 2026-10-23 a shift that alone would cross a stance band is held at the
band (`MODEL_CONFIG.override_moves_stance` False), so today the overrides move scores, never
stances. Phase K said they need their own point-in-time history and placebo gate first. The
obstacle phase K named, that layer 1 has no history (worldbankscape scores from 2026-10-12), is
side-stepped: the gate tests the **direction of the shift** against the asset's forward return,
which needs no layer-1 level. A crossing is that direction applied to today's level.

**What the stores hold** (read-only checks, 2026-11-09; P75 replays P17 on 262 month ends):

| Input (P17) | Store, series | Range | Vintage / lag |
|---|---|---|---|
| growth | bps-looker `BPS_GDP_YOY` (var 104) | 2011-Q1 → 2026-Q2; computed from 2012-05 | one vintage: every row stamped 2026-08-05 (BPS revisions read at today's values); lag 130 d |
| cli | dbnomics `idn.cli` (OECD) | 1994-01 → 2026-09 | **no vintage**; the CLI's latest months are revised heavily, so history reads a smoother, later CLI than was known; lag 45 d |
| inflation | bps-looker `BPS_CPI_YOY` (2022=100) from 2024-01, dbnomics `idn.cpi.yoy` before | 1990-01 → 2026-10 | one vintage each; lags 35 / 45 d; **hole 2024-02 → 04**: P17 falls back to dbnomics only when bps-looker has no CPI at all, not when it has under 3 months |
| trade | bps-looker `BPS_TRADE_BALANCE_USD_MN` | 2017-01 → 2026-09; computed from 2017-07 | one vintage (2026-11-02); lag 50 d; **the binding start** |
| bi_rate | bisfetcher `WS_CBPOL.M.ID` | 2005-07 → 2026-09; computed from 2006-02 | policy rates are not revised; lag 35 d |

Every P17 component is computed on 109 month ends, 2017-07 → 2026-10 except 2024-02 → 04.
Forward returns for IDN: JCI month-end closes from 1996 (P51 stitch); the 10Y as P66/P74 (OECD
proxy 2012-01 → 2024-12, lagged one month; IGSYC from 2026-10; nothing 2025-01 → 2026-09);
USD/IDR on the P65 splice (MAS cross from 2005-01, JISDOR from 2026-10-22).

The foreign inputs (P28; ranges 2026-11-09): FRED `GDPC1`, `DFF`, `T10Y2Y` (sec-edgar, which has
`fred_as_of` vintages), TIC from 1990 (one vintage), dbnomics OECD CLI/BCI/CPI and ECB series
from 1990 (no vintage), BIS policy rates from 1990 (euro area 1999), jquantster BOJ and JGB from
2000 (Tankan 2000-Q1), ausdata RBA/ABS (CPI monthly only from 2025-04, quarterly y/y from 1990,
**AUD/IDR only from 2023-01**), singstat MAS from 2005. **The USA and JPN `fx` components are
n/a live today:** they read idxscape JISDOR, which starts 2026-10-22 here, so the 3-month change
has no base (checked live 2026-11-09; EMU, AUS and SGP compute theirs). Forward returns abroad:
local 10Y yields exist for all five (FRED `DGS10`, JGB 10Y, `ea.bund.10y`, RBA `FCMYGBAG10D`,
SGS 10Y); IDR per local unit from the MAS crosses (2005 on, all five); equity prices only for the
US (Alpaca SPY from 2016, dbnomics Shiller monthly). No store has a Japanese, euro-area,
Australian or Singapore index price, so those stocks overrides cannot be gated.

**Decided** (already, by the user or earlier phases):
- The ten phase K numbers stay as they are; anything that differs from them below is proposed as
  a choice, not assumed.
- No change to the stance bands, `TILT_PT`, the 48/32/20 benchmark, the 100% rule, the ladder,
  the regimes or the phase K rules.
- Hand-set weights and bands stay as written on 2026-10-23 (P17, P28); none is tuned to a
  walk-forward. Thresholds and band-crossing rules are committed before any walk-forward judges
  them (the placebo cannot catch hand-tuned thresholds), so **S58 onward waits for the choices
  below**; only S57 (input history, no returns, no verdict) is built.
- A placebo control before an override may move a stance; a procedure that also improves the
  control is fitting noise.
- Slices land on branch `phase-l`; live checks use scratch paths; the fan-in merges to main and
  makes the one run that opens the new journal segment.

**Phase L choices: decided by the user (2026-11-09): all 13 proposed defaults, as bracketed below.**
These numbers are fixed: like phase K's, they change only through an agent review the user
decides. A slice that finds one wrong reports the evidence and leaves it. Each has its default in
brackets and its reason.
1. What is tested. [The sign of each asset's capped shift, P17 and P28 exactly as written
   (weights, bands, windows, ±10 cap): an **up** side, shift > 0 (on) against shift ≤ 0 (off),
   direction +1; a **down** side, shift < 0 (on) against shift ≥ 0 (off), direction −1; each
   side gated on its own, as phase K's enter and reduce. Not band crossings, which need a
   layer-1 level the stores do not have before 2026-10-12.] Reason: every non-zero shift is a
   claim the layer already makes live; a magnitude threshold chosen now would be chosen after
   seeing the shift counts in P75, which is tuning.
2. Forward return per asset, for an IDR investor. [IDN stocks: JCI price return (as P66); IDN
   bonds: `bond_returns` on the month-end 10Y, the OECD proxy lagged one month, IGSYC as it
   stands (as P66/P74); IDN currency: the rupiah against the US dollar,
   USD/IDR(t) / USD/IDR(t+h) − 1 on the P65 splice. Foreign stocks and bonds: in IDR unhedged
   (local return × the move in IDR per local unit, MAS crosses), since P28's weights already
   carry the `fx` component; foreign currency: the change in IDR per local unit. Local-currency
   returns are reported as a diagnostic only.] Reason: the user decides in IDR, and the
   weights claim IDR outcomes (the `fx` component scores stocks and bonds too).
3. Gate numbers. [Phase K's, unchanged: month ends, horizon 3, stride 3, block 3, `MIN_N` 10 per
   side, t ≥ 2.0 (`T_MIN`), p ≤ 0.05 (`ALPHA`) before choice 6, 1,000 shuffles, 20 controls,
   `SEED`.] Reason: one grid for every gate in this repo; no evidence to set others.
4. Which months count. [Only month ends where every component of that market's spec was
   computed (`OverrideRow.complete`); a partial month is a no_call. IDN: 2017-07 on.] Reason: a
   three-component shift is a different claim from the five-component one that runs live.
5. Window. [First complete month → last month with a full forward return (phase K's open
   question 1). IDN on today's stores: stocks and currency 2017-07 → 2026-07, about 36
   windows; bonds 2017-07 → 2024-08 (the 10Y hole), about 28.] Reason: as phase K.
6. Multiple testing. [Holm over each subject's tests (IDN: 3 assets × 2 sides = 6), family-wise
   0.05: the smallest p must be ≤ 0.05/6 ≈ 0.0083, the next ≤ 0.01, and so on; each test also
   keeps the placebo control (mean control t < 2.0) and t ≥ 2.0.] Reason: six tests at 0.05 each
   pass at least one by luck about 26% of the time; phase K tested one claim per side. 1,000
   shuffles reach p 0.001, so the bar is reachable.
7. Live monitor and revocation. [Phase K's: the journal's `overrides` records carrying this
   override fingerprint since the verdict's date, the last call in a month standing for it,
   the same test; revoke a passed side at ≥ 5 live windows per side with signed t ≤ −1.0; a
   verdict whose override fingerprint differs from the running code counts as none.] Reason:
   as phase K's open question 3.
8. Fingerprint. [One override fingerprint per subject: the AST (docstrings removed) of
   `layers/overrides.py` (IDN) or `layers/overrides_foreign.py` (foreign), `layers/types.py`,
   `override_history.py` and the gate numbers; it keys `out/overrides/<SUBJECT>.json`. The
   model fingerprint already hashes `layers/**`.] Reason: a weight or band edit then starts a
   new verdict, as a rule edit does.
9. The CPI splice hole (2024-02 → 04). [Fix P17's `_inflation` to fall back to dbnomics
   `idn.cpi.yoy` when bps-looker's CPI is too short for its 3-month window, not only when it is
   empty. This is a P17 model change: the model fingerprint and both IDN rule fingerprints
   change (P17 is in their `RULE_FILES`), so `out/rules/` rebuilds cold once, about 45 min, at
   the fan-in run.] Reason: a fallback bug that blanked live inflation for three months in
   2024 and costs the gate one window; fixing it before any verdict keeps it from being tuning.
10. OECD CLI vintages. [Gate on the stored CLI, and count a side as passed only if it also
   passes with the `cli` component zeroed; report both. Ask dbnomics to keep a CLI vintage per
   refresh from now on (and an original-release history if OECD serves one).] Reason: the CLI
   carries 3 of a stocks shift's points and is revised most at its end, so a pass that needs
   the revised CLI may be look-ahead; zeroing it is the one test that cannot use a revision.
11. What a pass allows. [A passed side lets that subject × asset's override cross a band in
   its direction only (an up pass: a positive shift may lift the band stance; a down pass: a
   negative shift may lower it); the shift keeps its ±10 cap; the other side stays held. The
   EMU verdict reaches its five members (they share its shift). A passed phase K rule still
   replaces the band stance after the override.] Reason: the gate tests one direction per side,
   so it licenses only that direction; no new size cap, because ±10 is what was tested.
12. Foreign `fx` for USA and JPN. [Read USD/IDR from the P65 splice (JISDOR from its first
   fixing, MAS cross before), live and in history, so both `fx` components compute again.] A
   live model change (USA and JPN shifts move by up to ±1/±1/±3), like phase K's choice 10.
   Reason: the components are n/a today only because idxscape's JISDOR here starts
   2026-10-22; history needs the splice anyway.
13. Foreign scope and vintages. [After IDN: bonds and currency for USA, JPN, EMU, AUS, SGP;
   stocks only for USA (SPY in IDR; no other index price in any store); KOR and TWN none. In
   history, FRED `GDPC1` through `fred_as_of` (its vintage); TIC, dbnomics, jquantster,
   ausdata and singstat at their one stored vintage with P28's lags, named in the result.
   AUS `fx` before 2023 has no AUD/IDR in ausdata: the history reads the MAS cross (AUD and
   IDR per SGD) there, and live keeps RBA's rate.] Reason: gate what has returns; use the one
   vintage store that has vintages; keep the AUS fx component from blanking 2017–2022.

**Done when:**
1. `assist.override_history` replays P17 point in time on every month end with its coverage and
   missing reasons (S57, done).
2. Forward returns per IDN asset as choice 2 (S58); the gate writes `out/overrides/IDN.json`
   (verdict per asset and side, Holm, CLI-zeroed check, live monitor, state, distance to
   `MIN_N`) and `assist run` reads it (S59).
3. The IDN walk-forward runs on the real stores, numbers recorded (S60).
4. A passed side may cross a band (choice 11), journalled, shown on the stance and `/signals`
   (S61); nothing moves unless a side passed.
5. Foreign: `fx` splice (S62), input history (S63), returns (S64), walk-forward (S65).
6. Fan-in: one new journal segment, Progress rows, STATUS, *Open data gaps* (S66).

- [x] **S57 IDN override input history** (P75-override-inputs). `assist.override_history`: P17
  unchanged on month ends 2005-01 → 2026-10, each store read once (`Preloaded`) and sliced per
  date under P17's own lags; per row the shift and uncapped sum per asset, each component's
  value, direction, newest point and series, the missing components with reasons, the stale
  inputs; `coverage()` per component, `complete_from()`, `summary()` (shift signs on complete
  months, descriptive). No returns, no verdict. Test first: no row moves when every value not yet
  known on a cut-off is poisoned; zero lags would leak; each store read once.
- [x] **S58 IDN override forward returns** (P76-override-returns). Choices 2, 3. Per IDN asset,
  the forward return per month end as choice 2, never across a gap; joined to the S57 rows.
  Test first: the currency return's sign (rupiah up = positive), the bonds hole, no return
  from a month still running.
- [x] **S59 Override gate** (P77-override-gate). Choices 1, 3–8, 10. `eval/override_gate.py`
  reusing `placebo.evaluate` and phase K's state logic: per asset and side, Holm per subject,
  the CLI-zeroed check, live monitor, fingerprint; `schema/overrides.schema.json`;
  `assist overrides` writes `out/overrides/IDN.json`; `assist run` reads it (rebuilds when stale,
  never fails). Test first: pass, insufficient, Holm fails a lone p 0.03, CLI-zeroed fail blocks a
  pass, revoked, fingerprint mismatch.
- [x] **S60 IDN override walk-forward, live** (P78-override-walk). Docs only: per asset and
  side on/off, t, p, Holm rank, control t, CLI-zeroed result, distance to 10/10, diagnostics
  (1-month horizon, local returns). No threshold change.
- [x] **S61 A passed side crosses a band** (P79-override-stance). Choice 11. `build_stance`
  reads each override verdict; a passed side's shift may cross in its direction; driver,
  journal, stance schema minor bump, `/signals` and brief show the gate state; MODEL_VERSION
  0.6.0. Test first: an up pass lifts neutral to overweight on a +6 shift from 57; a down shift
  on the same asset stays held; no pass, nothing moves.
- [x] **S61b P17 CPI fallback** (P85-cpi-fallback). Choice 9, before S59's first verdict. Test
  first: a bps-looker CPI known for 2 months falls back to dbnomics.
- [x] **S62 Foreign fx on the USD/IDR splice** (P80-foreign-fx). Choice 12. Test first: 11
  JISDOR fixings plus MAS history give USA and JPN a 3-month `fx` change.
- [x] **S63 Foreign override input history** (P81-foreign-override-inputs). Choice 13. S57's
  replay for P28 per market, `GDPC1` through `fred_as_of`, the AUS fx MAS fallback in
  history; coverage per market and component.
- [x] **S64 Foreign forward returns** (P82-foreign-returns). Choices 2, 3, 13. Bonds on the
  local 10Y, currency on IDR per local unit, USA stocks on SPY, all in IDR unhedged.
- [x] **S65 Foreign walk-forward, live** (P83-foreign-walk). As S60 per market.
- [x] **S66 Phase L fan-in** (F11-phase-l). Merge `phase-l`, one live run (new segment),
  Progress rows, STATUS, README, *Open data gaps*; CLAUDE.md lines only with your OK.

Parallel groups: S57 → {S58, S61b, S62} → {S59, S63} → {S60, S64} → {S61, S65} → S66.

### Phase M — average down on a held name (planned 2026-11-10)

**Why.** Nothing decides when a held name that has fallen deserves more money. Checked
2026-11-10 (run of 2026-11-09, statement of 2026-10-31):

- financer stores `avg_cost_minor` and `unrealised_minor` per holding; the adapter's `Holding`
  keeps only symbol, name, quantity, value and currency, so layer 5 has no cost basis.
- `sizing.size` adds to a held name only as any other add: it passes a placebo-passing screen
  with margin > 0, the market has budget and the name is under the per-name cap.
- `entry.py`'s status (`avoid`, `wait`, `buy_zone`, `deep`) gates nothing; its thresholds are
  in-sample and may not change a stance before a placebo control.
- IDN stocks are 96.9% of the portfolio against a 48% target, so the budget is 0. Nine holdings
  are 16–37% below cost; AMRT, PWON and BBNI are "trim in full: fails its screen". BMRI is the
  only held name that passes (−16.5% vs cost, margin 4.1pt, status `deep`) and it is over the 5%
  cap, so it is trimmed to the cap. No name would qualify today.
- Corrected by S67's live check (2026-11-10): the 16–37% and BMRI −16.5% figures were the Ajaib
  statement alone. Over both accounts: 67 IDN stock names, 61 below cost, six at 16% or more
  below, BMRI −15.0%, total cost against value −8.8%.

**Principle.** Cost basis is a label, never a signal. The test is "would the model buy this
today if none were held", plus a falling-knife guard and room under the caps.

**Flow.** A held name gets `average_down` only if it clears every gate, in order:

1. *Underwater*: price below its average cost (label only).
2. *Thesis intact*: ranked and kept by a placebo-passing screen, `net_margin_pt` > 0. Otherwise
   the existing trim applies.
3. *Not a falling knife*: entry status is not `avoid`, and is `buy_zone` or `deep`.
4. *Room*: holding below the per-name cap, sector cap not full, tranche under
   `max_participation`.
5. *Money*: the market's budget is above 0.
6. *Timing*: a ladder on global or home risk_off, else one lump; later tranches limited at
   `entry_typical`.
7. *Output*: row action `average_down` with the old and the new average cost, a Telegram block
   "IDN to average down", a journal record.

**Decided.** No change to the screens, the hurdle, `CAPS`, the ladder, the budget formula or
any phase K, phase L or S15 number. Slices land on branch `phase-m`; the fan-in merges to main.

**Phase M choices: decided by the user 2026-11-10, all three defaults as bracketed.** Choice 2
was taken after S69 came back insufficient, so gate 3 is context.
1. Money when the market is over its target. [Keep the budget rule: a name that clears gates
   1–4 with no budget is shown as "average down, unfunded" and sized 0.] Reason: funding it from
   the same run's trims would make it fire now, and slows the move to 48%.
2. Gate 3 before its placebo (S69). [Context only: the status is shown on the row, and the label
   rests on gates 1, 2, 4 and 5 until S69 passes; if S69 fails it stays context.] Reason:
   `entry.py`'s thresholds are measured on the history they would be tested on.
3. How far below cost counts as underwater (gate 1; found by P86). [5% or more below the average
   cost.] Reason: 40 of the 61 names below cost are 0.1–0.5% below, which is the buy fee on
   Stockbit lines valued at their own last trade price; the label changes no size, so the number
   only sets which adds are called an average down.

- [x] **S67 Cost basis in layer 5** (P86-cost-basis). `sources/financer.py`: `Holding` carries
  `avg_cost` and `cost_value` (None when the statement prints 0, as for an SBN line); `roll`
  recomputes the average through later trade documents (a buy moves it by its net amount, a sell
  leaves it). `undervalued.cost_basis_from(statements, market)`: quantity-weighted average cost
  and quantity per symbol across accounts. Nothing reads it yet: no payload or schema
  change. The model fingerprint does change (`journal.RULE_GLOBS` hashes `layers/**`) with
  identical behaviour, so the new segment opens at the phase M fan-in run (S71), not before.
  Test first: a statement line keeps its cost; a later buy re-averages it; a
  sell does not; two accounts weight by quantity. Live: the names below cost against the
  2026-10-31 statement.
- [x] **S68 Average-down rule** (P87-average-down). `candidates/average_down.py`, pure: gates
  1–6 over S20's rows, `sizing`'s result, the cost basis and the entry status, with the reason
  for each name that stops at a gate. Candidates schema minor bump: action `average_down`,
  `cost` block (`avg_cost`, `new_avg_cost`, `below_cost_pct`). Journalled; the module is hashed
  by `journal.RULE_GLOBS`. Waits for choices 1–3. Test first: one case per gate.
  **Done 2026-11-10**: the block is `cost_basis` (the row's `cost` is the execution cost);
  live, 67 held names, none an average down (BMRI stops at the per-name cap).
- [x] **S69 Placebo for gate 3** (P88-dip-placebo). On idx-method's `cache/history/`, point in
  time (levels measured only on bars before each date): 12-month forward total return of adds
  made in `buy_zone` or `deep` against adds on random days for the same names; phase K's gate
  numbers. Parallel with S68. A pass makes gate 3 binding; a fail leaves it context.
  **Result 2026-11-10: insufficient** (1 non-overlapping 12-month window, needs 10; the history
  starts 2021-11, so about 2035). Gate 3 stays context.
- [x] **S70 Surfacing** (P89-average-down-ui). Telegram block, brief line, `/portfolio` and
  `/candidates` columns (cost, below cost %, action).
- [x] **S71 Phase M fan-in** (F13-phase-m). Merge `phase-m`, one live run, Progress rows,
  STATUS, README; CLAUDE.md lines only with your OK.

Parallel groups: S67 → {S68, S69} → S70 → S71.

### Phase N — guided UI (planned 2026-11-10)

**Objective (user, 2026-11-10).** "Simplify for a no-think user: the most guided way to invest,
albeit not always right." The pages lead with what to do; the evidence stays one click away.
The user chose **orders with amounts and dates** over stances alone, and asked for an **entry
price, a take-profit and a stop-loss** on each order. One disclaimer per page, no repeated
caveats.

**Why.** Checked 2026-11-10 on the run of that day:

- The pages show evidence and leave the conclusion to the reader. In one session the user had
  to ask what these mean: regime risk_off, regime points, dollar up, overweight / neutral /
  underweight (countries and commodities), the Signals tab, GARP, "fails its screen", "trim in
  full", and why Industries was empty.
- The model does not yet say enough for a full order list:
  - IDN stocks must fall 48.9pt (about Rp 27.1m of Rp 55.4m). The named trims cover Rp 17.1m
    (16 names); **Rp 10.0m has no names**.
  - IDN bonds must rise 30.2pt (about Rp 16.7m). **No instrument is named.**
  - USA stocks must rise 20pt (about Rp 11.1m). **No name passes** (both US screens failed
    their placebo), so the budget is unspent.
  - A buy has an entry level (`entry_typical`) only for later tranches; nothing has a
    take-profit or a stop-loss.
- The same Average down table is on `/candidates` and `/portfolio`.

**Principle.** Guidance may be wrong, but it must not hide how strong it is. Every step
carries a strength (strong / medium / weak) and a "why" link. A number that changes what is
bought or sold, or how much, is a model change: hashed, journalled, and gated by a placebo
where history allows. A number that only says at what price or when is execution guidance and
is labelled as such.

**Flow.** One list per run, `out/guide.json`, read by the home page, the brief and Telegram:

1. *Sell steps*: each trim as name, amount, shares, tranche dates, "sell at market" or a limit.
2. *Buy steps*: each sized add as name, amount, shares, tranche dates, entry price per tranche,
   take-profit, stop-loss.
3. *Bucket steps* for a leg with no names (SBN, US stocks): the amount, the dates and the
   instrument rule of choice 2 or 3.
4. *Nothing to do* lines, when a leg is at target.
5. Each step: strength, one plain sentence of why, a link to the detail page.

**Phase N choices: 1, 2, 3, 5 and 6 decided by the user 2026-11-10, each the bracketed default
(pro rata; bucket steps for SBN and US stocks; fair-price take-profit, stop adding and trim to
half; thesis stop plus a review price that does not sell). 4, 7, 8 and 9 were not asked: built
on their defaults, still the user's to change.**
1. The unnamed Rp 10.0m of IDN stock sales. [Pro rata across the held names with no trim
   call, largest holdings first, whole lots, until the leg reaches its target over the ladder.
   Strength "medium: rebalance to the benchmark, not a view on the name".] Reason: unrated
   names have no ranking to sell by; pro rata takes no view.
2. The SBN leg's instrument. [A bucket step: "buy SBN, Rp X", with the 10Y benchmark series and
   its PHEI yield named as the reference; the user picks the product (retail SBN, FR series or
   a bond fund).] Reason: no fetcher holds retail SBN offers or fund NAVs.
3. The USA leg when no name passes. [A bucket step: "buy a US broad-market index fund, Rp X",
   strength "medium: benchmark leg, no name passes a screen".] Reason: leaving 20% in cash
   forever is also a decision, and a hidden one.
4. Entry price of a buy. [Tranche 1: at market, capped at the last close plus 1%; later
   tranches: limit at `entry_typical` when below the price, else at market on their date.]
5. Take-profit. [The fair price: where the name's margin over the hurdle reaches 0 (dividend
   screen: dividend ÷ (hurdle − growth)). Reaching it means "stop adding and trim to half",
   never "sell all".] Reason: it is the model's own valuation, so it needs no new threshold.
6. Stop-loss. [Two parts. A thesis stop, always on: the name fails its screen → sell (today's
   trim). A price level shown as "review at": `entry_deep`, the name's own deep-drawdown
   level; reaching it does not sell.] Reason: a price stop that sells is a new rule, and its
   placebo has too little history (S69 found 1 window of 10).
7. Strength labels. [Strong: over a cap, or two independent reasons. Medium: benchmark
   rebalance, or one placebo-passing screen. Weak: context only, shown under "background".]
8. Dates. [Tranche 1 on the next IDX session after the run; later tranches every 10 calendar
   days, moved to the next session.]
9. The old pages. [Kept, under one "Why" menu: Regime, Signals, Candidates, Industries. Track
   record: Paper, Journal, Status. Countries and commodities outside the benchmark move to a
   "Background" page.]

- [x] **S72 Hover explanations** (P90-regime-hover). `/regime`: every global and home (IDN)
  input explains what it measures and when it votes, on hover, focus or tap; thresholds checked
  against `layers.regime.RULES`. The empty `/industries` page says what is missing
  (idx-method's `api_raw`).
- [x] **S73 Plain words** (P91-plain-words). `assist/plain.py`: one table of term → plain label
  and one-line meaning (regime states, dollar, stances, styles, trim reasons, gates), used by
  every page as hover text and by S75's sentences. No model change.
- [x] **S74 Exits and entry prices** (P92-exits). `candidates/exits.py`, pure: entry price per
  tranche, take-profit (fair price) and the stop-loss pair per sized row; candidates schema
  minor bump. Waits for choices 4–6. A model change (hashed).
- [x] **S75 The guide** (P93-guide). `assist/guide.py`, pure: stances + candidates + layer 5 →
  ordered steps with amount, shares, dates, prices, strength and why; `schema/guide.schema.json`,
  `out/guide.json`, journalled. Waits for choices 1–3, 7, 8. A model change where choice 1
  names new sales.
- [x] **S76 Home page** (P94-this-week). `/` becomes "This week": the steps, then one line per
  leg (held, target, gap). The stance grid moves to `/background`.
- [x] **S77 Navigation** (P95-nav). This week, Portfolio, Why, Track record, Background;
  choice 9.
- [x] **S78 Brief and Telegram** (P96-guide-notify). Both open with the same steps.
- [x] **S79 One place per fact** (P97-dedupe). Average down only on `/portfolio`; style names,
  trim reasons and stances shown in plain words with the raw term on hover.
- [x] **S80 Phase N fan-in** (F14-phase-n). Merge, one live run, Progress rows, STATUS, README.

Parallel groups: S72 → {S73, S74} → S75 → {S76, S78} → {S77, S79} → S80.

### Phase O — the investing principle as rules (planned 2026-11-10)

**Principle (user, 2026-11-10).** "Hunting the best undervalued stocks with real fundamentals
along with dividends, so it grows when kept." Diversify, "but avoiding traps like redundant
sector or industries, but allow when they are different size or market". Reconciled: where a
tilt applies, redundancy in that sector or industry is allowed; different size is never
redundant; rebalance sales respect all of it.

**Why.** Checked 2026-11-10 on phase N's run: the guide's 38 rebalance sales are plain pro rata.
They trim every held name a little, sound dividend payers included, and ignore industry and
size. Of the 67 held names, 27 share an industry and a size bucket with another held name (18
groups; the largest is eight mid-cap "Produk Makanan Pertanian" names). Sizing caps names per
sector and per name only.

**Rules.**

1. *Group.* A name's group is its IDX-IC industry (idx-method `industry_membership`, the
   58-group level, newest snapshot) and its size bucket. A name with no industry or no market
   cap has no group and is never redundant. Markets are separate lists, so a US name is never
   redundant with an Indonesian one.
2. *Keeper.* Within a group the names are ordered: kept by a placebo-passing screen (margin,
   high first); then ranked by a passing screen but not kept (margin, high first); then unrated
   (largest holding first). The first is the keeper; the others are redundant.
3. *Tilt.* A redundant name is allowed when a passed tilt favours its sector (tilt > 0), or its
   industry once an industry tilt exists (none today). Decided by the user 2026-11-10: only a
   favourable tilt counts.
4. *Buying.* A redundant row that is not allowed gets no new money ("redundant with X"). It is
   not trimmed for that.
5. *Rebalance sales*, replacing phase N's pro rata for the part of a cut no trim covers:
   first the redundant names, in full, the lowest-ordered of the most crowded groups first;
   then pro rata over the other names no passing screen keeps; last, and only if still needed,
   pro rata over the kept names.

**Decided by the user 2026-11-10.** Three size buckets by market cap; only a favourable tilt
allows redundancy; the bucket lines, large at Rp 50T or more (32 of 963 names), mid from Rp 5T
(181), small below; the industry level (58 groups); and, changing rule 2, **unrated names keep
the highest dividend yield** (the screener's `div_yield`; a name with no yield after those
with one, then the larger holding), in place of the largest holding.

- [x] **S81 Groups and keepers** (P98-diversify). `candidates/diversify.py`, pure: size bucket,
  group, order, keeper, tilt exception. Test first: one case per rule.
- [x] **S82 Buying and the payload** (P99-diversify-sizing). Profiles (industry, market cap)
  gathered from idx-method; `sizing.size` skips a row marked redundant; the candidates payload
  gains a `diversification` block (schema 1.3.0). A model change.
- [x] **S83 Rebalance sales** (P100-rebalance-order). `rebalance.ordered_sales`: redundant in
  full first, then pro rata, kept names last; the guide's steps say why. A model change.
- [x] **S84 Phase O fan-in** (F15-phase-o). Merge, one live run, Progress rows, STATUS, README.

Parallel groups: S81 → S82 → S83 → S84.

### Phase P — stable verdicts per holding (planned 2026-11-12)

**Why.** On 2026-11-12 one name, BBNI, got four verdicts in one session from four methods: in
(the user's Stockbit "Cheap Big Caps"), out (its stricter version, Piotroski 3), "trim" (an ad
hoc review flag), "sell all of it" (the 11-11 guide), and "thesis intact, fair 3,380"
(investment-assist with prices fixed). Causes: a quality test unfit for banks, a data bug
(Stockbit's screener returns no `Price` since 2026-11-10, so `enrich` leaves `price` None and
every IDN name fails the price floor: dividend pool 0, all 67 held names unrated, 46 "sell all
of it"), a portfolio-fit rule read as a thesis verdict, and checks run outside the model.

**Rules.**

1. *One method of record.* investment-assist issues every keep / trim / sell. Stockbit
   screeners (idx-method `screener_preset`, `screener_member`) are a **watchlist only**: they
   may add a name to the pool to be judged, never a verdict. Reviews call this code, not
   hand-rolled flags.
2. *Three questions per held name, answered apart.* **Thesis** (fundamentals, pass / fail: the
   only sell trigger), **valuation** (price vs fair price: the only take-profit trigger, "stop
   adding and trim to half"), **fit** (redundant group, rebalance need: orders the cuts, never
   "beyond saving").
3. *Bad data holds.* A key input null across the market, or a passing screen with an empty
   pool, makes every held name's verdict `unknown`: the previous verdict stands, marked stale,
   and the guide and Telegram send a data notice instead of steps.
4. *Hysteresis.* The thesis is re-judged only when a new quarterly report or dividend record
   arrives. A **hard fail** acts at once (dividend cut, negative equity, negative CFO); a
   **soft fail** (F-score, Altman Z, other quality floors) acts only after **two quarterly
   reports in a row**. Take-profit fires at fair price and re-arms only once the price is **10%
   below fair** (may change after a retrospective review). A sold name re-enters only when it
   passes with a margin.
5. *Banks also need Piotroski >= 4*, beside the prudential floor (user 2026-11-12). BBNI
   (Piotroski 3) fails it: a soft fail, so it sells only if the next report fails too.
6. *Every change carries its cause*: new filing, price crossing, rule-version change or data
   fix. Rule changes go through the locked-numbers process (placebo, agent review) and open a
   journal segment.
7. *Stability is measured.* The paper track counts verdict flips per held name; target at
   most one per name per quarter. A flip caused by data or method is a bug.

**Decided by the user 2026-11-12.** Stockbit screeners watchlist only; soft fails need two
quarterly reports in a row; take-profit re-arms at 10% below fair; banks also need Piotroski
>= 4.

- [x] **S85 Data gate and the price fix** (P103-data-gate). `factors.enrich` keeps the price
  `derive` computes from `cache/history/` when the screener's is None; a check over the
  enriched table (a key column null for every name, or a passing screen with pool 0) marks the
  run's IDN verdicts `unknown` and the guide holds its steps with a data notice. Test first.
  Must land before the Monday 2026-11-16 07:00 weekly run.
- [ ] **S86 Holding record** (P104-holdings). `out/holdings/IDN.json`: per held name thesis,
  valuation, fit, inputs, the report period judged, cause of change, model fingerprint;
  journalled. Read by the guide in place of the unrated / redundant tags.
- [ ] **S87 Hysteresis** (P105-hysteresis). Rule 4 on the holding record (previous record +
  new report → verdict); replay over past quarter ends gives the flip rate before and after.
  A model change.
- [ ] **S88 Bank Piotroski floor** (P106-bank-f). Rule 5 in `screens._passes_bank`; rerun the
  dividend replay to show it still beats its placebo before it may change a stance. A model
  change.
- [ ] **S89 Watchlist** (P107-watchlist). The custom Stockbit screeners' names join the IDN
  pool as `source: watchlist`; no verdict from membership.
- [ ] **S90 Change-only alerts** (P108-change-alerts). The daily 07:00 check sends, send-once,
  only held names whose verdict changed, with the cause; folds into the Telegram plan.
- [ ] **S91 Flip counter and docs** (F16-phase-p). Paper-track flips per name; CLAUDE.md line
  "investment-assist is the only source of verdicts"; STATUS, README; fan-in run.

Parallel groups: S85 → S86 → {S87, S88, S89} → S90 → S91.

## Open questions

- ~~**Phase O defaults**~~ (size lines Rp 50T and Rp 5T; the 58-group industry level):
  confirmed by the user 2026-11-10, with the keeper among unrated names changed to the highest
  dividend yield.

- ~~**Phase N choices 4, 7, 8, 9**~~ (guided UI: entry cap of +1%, strength labels, tranche
  dates, menu grouping): the defaults confirmed by the user 2026-11-10.

- ~~Target weight bands per stance~~: benchmark decided 2026-11-06 (80% IDN as 48 stocks / 32
  SBN, 20% US stocks; phase I). The ±5 pt tilt and S20a's 5% per-name cap are still the
  placeholders; confirm them once phase I runs.
- Which SBN index for the benchmark (the 40% leg): pick once the PHEI parser shows what's
  available.
- ~~Phase K (2026-11-07): ten choices~~: all ten defaults accepted by the user 2026-11-07.
- **Phase K review findings still open** (`review/phase-k`, 2026-11-07; S56 fixed the reduce
  side and the bond-return timing). The ten phase K numbers stay as they are: any change below
  is a new model with its own gate, judged by an agent review and decided by the user.
  - *Stocks valuation reads rich in every month* (P68: 0 cheap months in 120, ERP − hurdle
    peaks +0.19pt against `ERP_BAND` 1.0, so the enter side is unreachable). Real growth is
    counted twice (`G_REAL` added to the EY) and so is the IDN country risk premium (CRP on
    top of a local-currency 10Y). Fixing both still gives 0 cheap months; dropping the CRP
    alone gives 10, which would be fitting to this sample. **Agent review 2026-11-10**
    (`docs/results/R-stocks-valuation.md` on branch `review-stocks-valuation`, `97b162c`):
    `G_REAL` is a full double count; of the CRP only the default spread is (the rest, ~0.6pt,
    is real equity risk). Spec r1 (EY − real 10Y vs US ERP + CRP − default spread, phase K
    numbers unchanged) gives 0 cheap months and identical gate verdicts; the two errors cancel
    (~2pt each), and the gap is structural (JCI EY 5.35% vs ~10% needed). **Adopted
    2026-11-11** (P102-stocks-r1, user's call, with the J9 10Y read P101 in one segment), as an
    edit to `idn_stocks.py` only. Still open: the same default-spread double count in
    `candidates/hurdle.py` (which never added `G_REAL`), and a free-float EY history.
  - *Headline CPI shocks.* The bonds rule's real yield subtracts headline CPI, so a one-off
    food or administered-price jump moves the real yield and the call.
  - *Non-resident SBN freshness.* DJPPR posts monthly with a lag (idxscape's whole history came
    in one file on 2026-11-06), so in history a point is known only after its ~40-day lag and
    the home regime's SBN input was stale on every date before 11-06 (P70). Does it stay fresh
    enough live to count?
  - *Core CPI.* Does bps-looker hold core CPI (to answer the headline shocks above)?
  - *JCI P/E level.* The cap-weighted EY over idx-method's snapshot and `factor_series` agree
    with each other (+0.06pt mean, P68), but nothing outside idx-method checks the level (an
    IDX or index-provider P/E).
- ~~**Suspect phase L override weights**~~ (P78, P83: AUS currency `fx` looked inverted; bonds
  weights leaned the wrong way in IDN, USA, SGP, EMU up). Agent review 2026-11-09
  (`docs/results/R-phase-l-weights.md`): noise, no sign, unit or timing bug; **kept** by the user
  2026-11-09. Design notes left for a later ex-ante review: bonds gated in IDR unhedged mix the
  FX leg into the sign; FRA and ITA bonds are gated on the Bund; USA `flows_treasury` (−2.42) is
  a lead, found in-sample.
- ~~**Phase M choices 1–3**~~ (average down): all three defaults accepted by the user 2026-11-10
  (unfunded when the market has no budget; gate 3 context only; underwater at 5% or more below
  cost); S68 is unblocked.
- ~~**Phase L choices 1–13**~~ (layer-2 overrides on their history): all 13 defaults accepted by
  the user 2026-11-09; S58 onward is unblocked.

## Progress

Details per slice in `docs/results/<slice-id>.md`; slice ids from `plan.yaml`.

| Slice | Status | Date | Commit | Tests | Live result |
|---|---|---|---|---|---|
| S0 skeleton + doctor (S0-skeleton) | done | 2026-10-23 | `b328bf5` | 33 (doctor) | 14 sources: 10 present, 3 stale (sec-edgar VIXCLS 2026-10-12, jquantster, idx-method CSVs frozen 2026-09-30), 1 missing (satudatascape) |
| S1 adapter contract + worldbankscape (S1-contracts, P1-worldbankscape) | done | 2026-10-23 | `fbe9e82`, `ab0fb79` | 47 contract + worldbankscape | 144 scores load (27 countries + 14 commodities, 6 asset classes), 0 invalid; 47 flags, 8 critical; IDN bonds 58.0, stocks 53.6, currency 52.5 |
| S2 FRED adapter (P2-usfin-fred) | done | 2026-10-23 | `3d3d921` | 22 | all 25 layer-0 series load via ATTACH (159,682 rows, 0.4 s); HTTP path proven on fixture only (`usfin serve` down here); net liquidity $5,865 bn on 2026-10-07 |
| S3 regime (P8-regime, with P3-idn-prices, P9-placebo) | done | 2026-10-23 | `21f4ef5` (`d9ed1b1`, `e347dc4`) | 28 regime | now neutral, dollar flat; walk-forward 2019–2026: **not proven** (JCI 20d p 0.910, IDR 20d p 0.052, 3 independent risk_off windows; control t ≤ 0.35); no candidate adopted |
| S4 portfolio (P4-portfolio) | done | 2026-10-23 | `4443214` | 34 | IDN stocks 60.36%, IDN cash 39.64% (Rp29.6 M, statements 2026-09-30); Ajaib total matches its lines; 0 unmapped |
| S5 stance v0 + journal (P10-stance, P5-journal, F1-run) | done | 2026-10-23 | `031d079`, `5b0f99d`, `e8662dd` | 30 stance, 18 journal, 9 e2e | `assist run`: 49 schema-valid stances (12 countries × in-scope assets + 14 commodities): 15 overweight, 31 neutral, 2 underweight, 1 avoid; IDN stocks/bonds/currency all neutral; rerun byte-identical; journal chain ok |
| S6 brief + Telegram (P6-brief, P7-notify, F1-run) | done | 2026-10-23 | `a6da657`, `e5868f7`, `e8662dd` | 20 brief, 26 notify | live 2026-10-23: brief written, Telegram summary sent (1 part, ~1.7 k chars), second run the same day skipped (`already sent`), out/ byte-identical (49 files) |
| S7 IDN overrides (P17-overrides-idn, with P11-bps, P12-bisfetcher, P16-dbnomics, F2-idn) | done | 2026-10-23 | `cfcf606` (`75b60ba`, `3e77b08`, `c110f2d`) | 21 overrides, 17 bps-looker, 18 bisfetcher, 25 dbnomics | GDP 5.29% flat (0), OECD CLI 98.63 −0.64 (−1), CPI 3.28% inside target (0), trade +US$1.42bn (0), BI rate 5.75% +1.00 since Mar (hiking, +1) → stocks −5, bonds −2, currency 0; no shift crosses a band; satudatascape missing |
| S8 IDN signals (P18-signals-idn, with P13-idx-flows, P14-kseistat, P15-tic) | done | 2026-10-23 | `ae39827` (`ba7a89e`, `71fc424`, `5984ef6`) | 31 signals, 12 idx flows, 13 kseistat, 29 TIC | IDX foreign 20d −IDR 16.09T (−US$616m, 3 JISDOR gaps) −1; non-resident SBN +IDR 5.74T/4w (IDR 914T, 13.02%) +1; KSEI foreign 31.32% −4.27pt/3m −1; TIC US equity −US$1,577m −1, bonds +US$921m +1 → stocks −3, bonds +2 |
| S9 IDN bonds rule (P31-idn-bonds, with P32-phei, F2-idn) | done | 2026-10-23 | `06c0591` (`96043c1`) | 39 bonds rule, 20 PHEI | **no call**: no PHEI tables here (idxscape at migration 8), OECD 10Y proxy ends 2024-12; real yield 3.73% (34th pct, 101 months); JISDOR +1.7%/20d; placebo walk-forward 2021-11..2025-03 insufficient sample; stance neutral (score 56.0) |
| S10 IDN stocks rule + candidates (P22-idn-stocks-rule, P19-factors, P20-screens, P21-cost-entry, F2-idn) | done | 2026-10-23 | `1d4151e` (`8767171`, `a0b07b9`, `558b744`) | 49 stocks rule, 18 factors, 34 screens, 35 cost/entry, 23 F2 run | stocks rule **no call** (10Y proxy too old): JCI EY 6.02% (P/E 16.6), implied ERP 4.29% vs hurdle 6.16% (rich), flows −1, macro 48.6; stance neutral (score 48.6); screens: momentum passes (t 2.62, p 0.004), dividend and value blocked; 20 momentum candidates at an IDR 10m tranche, 0 dropped on cost or capacity (round trips 67–172bp vs 224bp/mo edge) |
| S11 foreign overrides (P28-overrides-foreign, with P23-jquantster, P24-singstat, P25-ausdata, P27-fx-idr, F3-foreign) | done | 2026-10-23 | `9bd100d` (`3f5d1c4`, `c985760`, `7111371`, `4b45770`), F3 this commit | 30 foreign overrides, 19 jquantster, 20 singstat, 19 ausdata, 22 fx, 18 F3 run | shifts s/b/c: USA +3/−4/+3, JPN −2/−1/+4, EMU +2/−9/−1 (on DEU, FRA, ITA, ESP, NLD), AUS −2/−3/+1, SGP 0/−7/+1; all five markets hiked over 6 months, so bonds negative everywhere; KOR/TWN none. Bands held: AUS bonds 58.2, NLD bonds 54.5, SGP bonds 53.1 (stay overweight). Hedge carry USD +1.81%/y, JPY +4.44%, EUR +3.17%; MAS (SGP, EUR leg) stale since 2026-10-07 |
| S12 foreign candidates (P29-candidates-foreign, with P26-openkrx, P27-fx-idr, F3-foreign) | done | 2026-10-23 | `cb996f1` (`6ebb2b5`, `4b45770`), F3 this commit | 22 foreign candidates, 12 openkrx, 18 F3 run | 1 index candidate (S&P 500, CAPE EY 2.46% vs 10Y 4.99%, edge −6.47%, score 17.7, does not pass; IDR test survives hedged +8.11% vs IDN 10Y 7.01%); no JP/AU/SG/KR/TW index valuation in any store; openkrx index Parquet not on disk. Context only: no stance moved |
| S13 paper tracking (P30-paper, F4-ops) | done | 2026-10-23 | `93a154d`, F4 this commit | 18 paper, 4 F4 paper | benchmark 60/40 live: 674 weeks scored (2012 → 2025-01-03), cumulative +102.1%, annualised 5.6%, vol 9.8%; worst week 2020-03-20 −8.7%; 94 stale weeks after 2025-01-03 (SBN leg on dbnomics `idn.rate.long`, ends 2024-12; JCI frozen 2026-09-30); one model segment from 2026-10-23, nothing scored yet |
| S14 launchd + doctor header + README (F4-ops) | done | 2026-10-23 | F4 this commit | 31 ops | jobs rendered, not installed; live `run --no-send`: brief opens with *Data health* (9 of 14 sources fresh: sec-edgar, jquantster, idx-method stale, satudatascape missing, idxscape PHEI absent) and *Paper track*; rerun brief byte-identical; `regime --check --no-send`: neutral, dollar flat, unchanged |
| S20 one ranked undervalued list (F5-undervalued, with P35-sector-tilt, P36-dividend-value, P37-garp, P38-sizing) | done | 2026-10-27 | F5 this commit | 20 F5 run (1114 total) | IDN, bars 2026-10-09, hurdle 13.74%: dividend **passed** (t 2.79, p 0.004), pool 35, 3 names (BMRI +2.51pt, JPFA +1.12, BBNI +0.84), 3 dropped on cost (ELSA, CPIN, STAA); GARP **failed** (t 1.30), pool 30, no names; tilt **failed** (t −1.11): no shift, caps 5; IDN stocks neutral 60.4% → 60.4%, so budget IDR 0, no adds; 6 trim lines (BMRI and BBNI to the 5% cap, AMRT, KLBF, PWON, SRSN below the hurdle); rerun byte-identical |
| S21 US single stocks (F6-us-stocks, with P39-us-stocks) | done | 2026-10-27 | F6 this commit | 19 F6 run (1133 total) | `out/candidates/USA.json` written: **no names**, sec-edgar's Alpaca tables are empty on this Mac (universe 0, pool 0), so dividend and GARP both *insufficient sample (0 quarters)*; USA hurdle 8.92% in IDR, IDN 13.61% binds (a US name needs 14.45% in USD), JISDOR IDR 18,116; no tilt (S16 is IDN only), caps 5; USA stocks overweight 0% → 5%, so budget IDR 1.48M of IDR 29.6M; nothing held in USD; journal 1 `undervalued` per run, 0 rows; rerun byte-identical |
| S23–S28 local UI view (F7-ui, with P40–P44) | done | 2026-10-27 | F7 this commit (`02ca075`, `9d7253a`, `b6726bd`, `bde605d`, `c43dac8`) | 24 web, 18 status, 9 overview, 23 stance, 23 candidates, 22 paper, 2 F7 e2e (1236 total) | live `assist status --port 8799` on the real out/ and journal: `/` 200 15,190 B 21 ms, `/stance/IDN/bonds` 200 5,284 B 41 ms, `/candidates` 200 10,536 B 3 ms, `/candidates/IDN` 200 7,916 B, `/candidates/USA` 200 4,982 B, `/paper` 200 6,107 B 122 ms, `/journal` 200 3,667 B 116 ms, `/status` 200 14,796 B 3.4 s; every `.json` twin 200 (`/json` alias too), `/nope` and `/stance/IDN/..%2Fx` 404, HEAD `/paper` 200; nav and one disclaimer on every page, no notices; 49 stances, journal 865 records chain ok over 8 models; **paper 0 weeks scored** (JCI ends 2026-09-30, IGSYC 10Y starts in October: gap 2b blocks it); out/ (51 files) and `journal/decisions.jsonl` sha-identical before and after |
| S29 one-step start (P45-start) | done | 2026-10-27 | this commit | 21 start (1257 total) | live `./start.sh --no-open --port 8799` on the real repo: sync, doctor (11 of 14 fresh, 2 stale: jquantster, idx-method; satudatascape missing), **no run** (out/ all as_of 2026-10-27), pages up in 6.1 s; `/` 200 15,190 B, `/candidates` 200 10,536 B; SIGTERM (and Ctrl-C under a pty) stops it, port 8799 free, no server process left; out/ sha-identical. README data gaps brought up to date: PHEI fresh 2026-10-26 (both IDN rules now propose but are not applied, insufficient sample), FRED fresh 2026-10-23, paper 0 weeks for the benchmark and 8 segments |
| S30 peer comparison per industry (P46-peers) | done | 2026-10-27 | `8847486`, `d3cad8c` | 22 adapter, 24 peers, 15 view (1317 at S30) | `assist industries`: 33 industries, 836 names, as of 2026-10-26 (1.9 MB); `/industries` 200, `/industries/8f8ca75c` (banks, 47 names) 200, twins 200, unknown id and `..` 404; checked by screenshot in light and dark. Stockbit industry PE means of −77 (POLU group) and −115 (DOSS) confirm the switch to medians. Follow-ups `cf40630`, `79b2a15`, `33cb34c`, `d3cad8c` (1318 total): industries named by IDX sub-sector, and `/industries` is one chart per industry of the names that pass (41 of 836, 18 industries; BMRI and BBNI fail the 0.8× solvency floor). Stockbit session expired (refresh 401): nothing pulled 2026-10-27 or 10-28, page as of 2026-10-26 until `./run.sh login` in idx-method |
| S31 top tier model (P48-tier-model) | done (S31 open: P49, P50) | 2026-10-29 | `a6e38ef` | 26 tiers (1373 total) | blocked: idx-method `store/data/stockbiter.db` absent on this Mac, so `assist industries` exits 1 (`SourceUnavailable`); the tier inputs alone load (976 rows from `factors.json`, liquidity derived for 17 of the 20 names in `cache/history/`), fixtures only |
| S31 top tier page (P49-tier-ui) | done (S31 open: live run) | 2026-10-29 | `5760090` | 67 view + web (1385 total) | fixtures only (no schema 4 file here); checked by headless Chrome screenshot in light, dark and the schema 3 fallback |
| S31 top tier replay (P50-tier-replay) | done (S31 open: live verdict) | 2026-10-29 | `3d940e6` | 16 replay (1401 total) | fixtures: planted signal passes (t 19.78, p 0.001, perm_p 0.005, control t 0.15, 17 quarters), noise fails (t −0.25); live `run_live` returns `blocked` (no S30 membership: `stockbiter.db` absent) |
| S31 live run (P48–P50 live) | blocked 2026-11-09 (unblocked 2026-11-10, below) | 2026-11-09 | this commit | none (docs only; 1938 pass) | `stockbiter.db` present since 11-06 but its `api_raw` has 0 rows (`endpoints_pull.py` never ran on this Mac), so `assist industries` exits 1 (`no comparison_industries in api_raw`): no schema 4 file, no tiers, replay of record `blocked`; `/industries` 200 with "no peer comparison yet", `.json` 200, unknown id 404. **Diagnostic replay** (membership from `industry_membership`, the same 33 IDX sub-sectors; code and `CONFIG` unchanged) **failed**: 15 quarters 2022-12 → 2026-06, Tier A +3.11pt vs placebo +3.08pt, t 0.02, p 0.508, perm_p 0.468, control t −0.17, 963 members, 17.2 industries/quarter, 370 picks; pillars alone t 1.38–2.66 (diagnosis only). History starts 2021-11, hence 15 quarters (P50) |
| S31 replay membership (P50b-replay-membership) | done | 2026-11-09 | this commit | 5 replay (1943 total) | spec change approved by the user 2026-11-09: the replay of record reads dated membership from idx-method `industry_membership` (1 snapshot, 2026-11-06, 963 names, 33 sub-sectors), no longer IDN.json; `CONFIG` and fingerprints unchanged (`sha256:6cf25fa49ea6…`). **Live verdict: failed**, t 0.02 below 2.0, p 0.508, perm_p 0.468, control t −0.17, 15 quarters 2022-12 → 2026-06 (all 15 back-filled), Tier A +3.11pt vs placebo +3.08pt, 17.2 industries with a Tier A per quarter, 370 Tier A picks; pillars alone t: value 2.66, growth 2.16, health 2.12, momentum 1.53, quality 1.38 (decide nothing). Bars back to 2016-11 (#3) not done: `factor_series` has daily `price` from 2016-11-07 but no store has traded value or volume before 2021-10 (idx-method `bars` 2021-10-18, idxscape `stock_summary` 2021-10-01), so the liquidity gate cannot be replayed earlier without a proxy |
| S31 live run, unblocked (P48–P50 live) | done (**S31 done**) | 2026-11-10 | this commit (branch `s31-live`) | none (docs only; 2072 pass) | Stockbit session live (refresh to 11-17); in idx-method, under its job lock, `endpoints_pull.py --skip` all but the three `comparison_*`: 1 metrics, 836 ratios, 836 industries rows, 0 failed, 304 s (16:17–16:22 WIB). A first pull at 15:20, during trading, gave 226 industries (all ranked within sector): the industry id hashes Stockbit's averages, which moved between calls; re-pulled after the close. `assist industries`: schema 4, 33 industries, 836 names, 4 s, a rerun gives identical bytes, tier fingerprint `sha256:bb4e3805c09d…`, no stale input. Gates: 162 of 836 pass (fails: liquidity 510, TTM loss 241, F-score 221, Altman Z 187, D/E cap 102). Peer group: 7 industries ranked within the industry, 26 within the sector. **Tier A 23 names in 15 industries, Tier B 29**; 22 industries with a pick, 6 with passing names but none ≥ 50, 5 with no name passing. Tier A: Barang Baku TINS, SRSN, ESSA; Makanan & Minuman LSIP, AALI, ULTJ; Minyak, Gas & Batu Bara BSSR, ELSA, AADI; Bank NISP, NOBU; Properti DMAS, PWON; one each ERAL, KOTA, WIIM (73.5, top), TOTL, POWR, OMED, SRTG, ARNA, ASGR, MSTI. Context only: the replay of record (`industry_membership`) stays failed, t 0.02. `/industries` 200 with *Top tier by industry*, `.json` 200, unknown id 404 |
| P21 entry peak fix (P21b-entry-peak) | done | 2026-11-10 | this commit | 3 entry + 2 updated (1946 total) | root cause: `corrections` measured recovery against the rolling 3-year high, so a crash whose peak aged out of the window read as completed (BSML 1805 → 67 → 575: −96%, entry 21; DEWI −86%, entry 35). Now depth and completion are against the peak at the correction's start: 194 of 893 names change, 405 have no completed correction (was 286). User chose no fallback to `entry_deep` (median deep zone −64%, 220 names below −80%): `layers/candidates` and `layers/undervalued` give entry basis `none`; sizing's later tranches still use `entry_deep` only when below the price. Live: 488 names with a level, 29 below half their price (was 142 with fallback); BSML, DEWI, BBCA, TLKM now none; BMRI 5950 (−20.1%, 2 corrections), ASII 4190 (−43.4%). Layer modules changed, so the next run opens a new journal segment |
| Gap 2b JCI from idxscape (P51-jci-idxscape) | done | 2026-11-06 | this commit | 8 index + stitch (1412 total) | `jci()` 7,314 closes 1996-10-02 → 2026-11-05 (1,224 from idxscape); paper: 0 → 1 week scored (2026-10-16, benchmark −9.4%, JCI −14.9%); IGSYC.10 ends 2026-10-21 here, so 3 weeks stale; JCI −11.6% on 2026-10-16 in IDX's own data |
| Paper capture gaps (P52-paper-daily-gap) | done | 2026-11-06 | this commit | 2 paper (1414 total) | live: with PHEI resumed (IGSYC to 11-05) the old carry scored 3 weeks (10-23 and 10-30 on the 10-21 yield); now 1 scored (10-16, −9.4%), 3 stale, each naming the yield gap |
| S32 layer 5 reads trade documents (P53-portfolio-trades) | done | 2026-11-06 | this commit | 9 adapter, 42 portfolio, 1 brief, 1 view (1432 total) | as of 2026-11-02: IDN stocks Rp53.70 M 96.90%, bonds Rp0.99 M 1.79%, cash Rp0.73 M 1.31%, total Rp55.42 M (statements only: Rp18.98 M); by owner tommy Rp18.88 M, priskila Rp36.54 M; her Stockbit 63 lines Rp36,535,800 at last trade prices (8 TCs, gross flow 37.15 M); Ajaib's ARNA (200 sh) gone after the 11-02 daily, its check still matches; 10 statement-only accounts identical to before; 0 unmapped, 0 stale; mtime unchanged |
| S38 /flows household transfers (P58-flows) | done | 2026-11-06 | this commit | 27 flows, 17 view, 6 adapter, 1 web (1483 total) | 2026-10: 10 matched (IDR 13,066,567: Ajaib RDN ↔ dailies 7 settlements, RDN → Tahapan 3), 6 named unmatched from Tahapan (5 to priskila 12/14/19/23/31 Oct, 70.0 M; 1 his card payment 12.29 M, card statement not loaded), 6 TC settlements unmatched (34.15 M; with 2 in 2026-11, 37,223,485.62 = her payment due); Mandiri savings → card matched every month 2025-12..2026-09; `/flows`, `/flows/2026-10`, twin 200, unknown month 404; screenshots light and dark; mtime unchanged |
| S33 layer files in `out/layers/` (P54-layer-out) | done | 2026-11-06 | this commit | 17 layers out (1449 total) | 8 files, all schema-valid: regime neutral, dollar flat (off 1: real yield 2.64%), 9 inputs × 52 weekly points; IDN 5 components (stocks −5, bonds −4, currency +2), 5 signals, flows 60 IDX days 08-12 → 11-05 (USD null before JISDOR's first fixing 10-22), JISDOR 11 fixings, JCI 239 closes, SBN 239 days, IGSYC 11-05 vs 10-08; USA, JPN, EMU, AUS, SGP files; portfolio Rp55.42 M as of 11-02, 12 accounts, 49 stance targets |
| S34 /regime (P55-ui-regime) | done | 2026-11-06 | this commit | 19 view (1519 total) | `/regime` 200 16,604 B, `.json` 200 61,713 B on the S33 live file: neutral, dollar flat (broad dollar +1.64%/13w inside ±2%), points off 1 / on 0; 9 inputs (5 counted) with 52-week lines, e.g. VIX 16.61 (11-04), real yield 2.64 risk-off +1, STLFSI4 −0.52 risk-on −1 (candidate, not counted); none stale; history 2 regime records (10-29, 11-06, both neutral/flat); headless Chrome light and dark |
| S35 /signals/<SUBJECT> (P56-ui-signals) | done | 2026-11-06 | this commit | 21 signals view (1521 total) | on the S33 files: `/signals/IDN` 200 (105 kB; 5 components, shifts stocks −5, bonds −4, currency +2, none capped; 5 signals, tally stocks −3, bonds +2; 6 SVG charts: net foreign 60 IDX days 08-12 → 11-05, USD bar missing on 49 days before JISDOR's first fixing 10-22; JISDOR 11 fixings, 0 carried forward; IGSYC 31 tenors 11-05 vs 10-08; SBN non-resident 914.8T, +4.5%/1y; JCI 5,030, −39.7%/1y), `.json` twin 200 (63 kB) = the file; `/signals/USA` 200 tables only (7 components, IDR 18,094.00 on 11-05), `/signals/EMU` 200; `/signals/NOPE`, `/signals/idn` 404; screenshots light and dark |
| S36 /portfolio (P57-ui-portfolio) | done | 2026-11-06 | this commit | 19 view (1519 total) | `/portfolio` 200 (57,991 B), `.json` 200 (43,597 B): Rp55,415,423 as of 11-02; stocks 96.90% vs 111.90% summed targets, bonds 1.79% vs 26.80%; 18 of 49 stances with a weight, target or entry; priskila 65.94%, tommy 34.06%; 12 accounts masked, bnisek statement 98 d flagged, Ajaib check matches; unmapped 0; IDN 10 trims, no adds; screenshots light and dark |
| S37 fan-in: nav and cross-links (F8-ui-layers) | done | 2026-11-06 | this commit | e2e +11 routes, 5 web, 2 stance, 1 overview (1571 total) | nav Overview, Regime, Signals, Candidates, Industries, Portfolio, Flows, Paper, Journal, Status; live on a copy of the S33 `out/` + `assist flows`: 20 pages and their twins 200 (`/signals/IDN` 105 kB, `/portfolio` 58 kB, `/flows/2026-10` 15.5 kB), unknown subject and month 404; IDN bonds links `/signals/IDN` and `/portfolio`, GOLD only `/portfolio`; `/industries` a notice (no `IDN.json` in the copy); screenshots light and dark |
| S39 benchmark 48/32/20 and the 100% rule (P59-benchmark) | done | 2026-11-06 | this commit | 45 stance (+15), 1 portfolio view, 1 stance view, layers out extended (1592 total) | 49 stances, model 0.4.0 `sha256:7822bcfd80…`: raw targets IDN stocks 48 (neutral) + IDN bonds 32 (neutral) + USA stocks 25 (overweight) = 105 → ×0.952 → 45.7 / 30.5 / 23.8 = 100.0%, cash 0%; moves above 10pt laddered 3×10d, adds and trims: IDN stocks 96.9 → 45.7 −51.2pt trim over 3 tranches, IDN bonds 1.8 → 30.5 +28.7pt over 3 tranches, USA stocks 0 → 23.8 +23.8pt over 3 tranches (estate-tax risk line); 46 outside the mandate at 0%, 0 trims there (nothing held outside IDN); S20a budget IDN Rp0 (trims only), USA Rp13,188,871 (unspent, no names); `/portfolio` 200 shows the sums and cash rest |
| S40 paper benchmark with a US leg (P60-paper-benchmark) | done | 2026-11-06 | this commit | 30 paper (+10), 24 paper view (+2), ops updated (1604 total) | `assist paper` live: 48/32/20 from 2026-10-06, 1 week scored (10-16: −7.7% = JCI −14.9%, SBN leg −1.0%, US stocks −1.1% = SPY −2.0% × USD/IDR +0.9%), 3 stale (10-23 and 10-30: the IGSYC hole 10-22 → 11-03; 11-06: no JCI, SPY or JISDOR after 11-05 yet); legacy 60/40 1 week, −9.4%; journal segments `4ef43996` and `9607e4bd` are both pre-S39 and score identically to the old code (nothing scored yet); SPY 2016-01-04 → 2026-11-05 (2727 bars), USD/IDR MAS 2005-01-03 → 2026-10-21 + JISDOR 2026-10-22 → 11-05 |
| S41 fingerprint scope (P61-fingerprint-scope) | done | 2026-11-07 | `11efb4e` (merge `b7088bd`), `0f4d2d4` | 6 journal (+1 `0f4d2d4`), 2 paper, 2 brief, 2 paper view (1617 at S41) | rule modules hashed by AST without docstrings (`rules_method` in `journal/models/`); a docstring and comment edit to the real `stance.py` and `regime.py` keeps the fingerprint, `_X = 1` changes it; `config/household*.yaml` kept out as plumbing; `assist paper`: 48/32/20 1 week scored, cumulative −7.7%, "annualised after 12 scored weeks" (was −98.5%); 60/40 −9.4%; 3 stale |
| S42 rebalance vs tilt (P62-rebalance-split) | done | 2026-11-07 | `679d7c4` (merge `0b88219`) | 8 stance, 4 notify, 1 brief, 2 portfolio view (1633 total on main) | stance schema 1.1.0 (`rebalance_pt`, `tilt_pt`, optional; 1.0.0 still validates); live all three legs neutral, targets 48/32/20 = 100, no scaling: IDN stocks 96.9 → 48 −48.9pt all rebalance, IDN bonds 1.8 → 32 +30.2, USA stocks 0 → 20 +20.0, tilt 0; Telegram preview opens "Paper only, not an order…" and labels each market's sized list with its leg's split (not sent); golden brief unchanged |
| S43 docs refresh (F9-docs) | done | 2026-11-07 | this commit | none (docs only; 1633 pass) | STATUS, open data gaps, README phases and data gaps, CLAUDE.md coverage gaps brought to 2026-11-07: both jobs installed and loaded, idx-method `c432999` valuation history and industry membership (S15 unblocked), JCI P/E wired; model `sha256:b836b881ad37…` on main, no run since |
| S44 USA universe over HTTP (P63-us-universe) | done | 2026-11-07 | this commit | 6 usfin fetch, 7 us_stocks (1646 total) | read timeout → `locked`, no ATTACH into serve's lock; `US_HTTP_TIMEOUT` 60 s shared with paper; universe 7 177 over HTTP (1 call, ~20 s), facts 6 024 CIKs and bars 3 589 names / 7.59 M rows over 2 ATTACHes (was 1 GET per symbol, ~11 s each); USA step 151 s, run 7 m 23 s, peak RSS 7.4 GB; dividend pool 576 (t −1.42, failed), GARP pool 370 (t 1.70, failed), 0 names; stale_inputs only the no-SIC line; split lines unchanged (IDN stocks −48.9 / IDN bonds +30.2 / USA stocks +20.0 rebalance, tilt 0); model `sha256:8c6a886f278d…` |
| S45 fingerprint covers the rule subpackages (P64-fingerprint-rules) | done | 2026-11-07 | `c0c389d` (merge into `phase-k`) | 5 journal (1650 at S45) | `RULE_GLOBS` recursive under `layers/`: `layers/bonds/idn.py` and `layers/rules/idn_stocks.py` now hashed; a constant edit in either changes the fingerprint, a docstring edit does not |
| S46 USD/IDR for the bonds rule (P65-usdidr-source) | done | 2026-11-07 | `05aaf69` (merge `75d37d4`) | 12 usdidr, 2 run_idn (1659 at S46) | JISDOR spliced on the MAS cross: 5,482 points 2005-01-03 → 2026-11-05 (11 JISDOR, overlap max \|Δ\| 0.12%); bonds rule **hold** (was `no_call`): real yield 4.47% (58th pct), SBN +Rp4.09T, USD/IDR +1.1%/20 fixings, no breakout; IDN bonds neutral 49.0 |
| S47 point-in-time rule history (P66-rule-history) | done | 2026-11-07 | `af40d91` (merge `61b8477`) | 9 idxmethod_series + history (1693 at S47) | 120 month ends 2016-11 → 2026-10 with a `factor_series` EY provider: bonds on 4 / off 11, stocks on 0 / off 14 (never enter); AVIA's listing P/E jumps the EY in 2021-12 (an idx-method data artifact, *Open data gaps*) |
| S48 historical gate and live monitor (P67-rule-gate) | done | 2026-11-07 | `78053da` (merge `1994c01`) | 23 gate, run_idn, ops (1731 at S48) | `eval/gate.py` gates each IDN rule on its history plus the journal monitor, keyed to a per-rule fingerprint; `assist rules` writes `out/rules/`; both **insufficient** (bonds 4/11, stocks 0/14), stances neutral; warm run 5 m 29 s, cold 21 m 22 s |
| S49 stocks walk-forward, live (P68-stocks-history) | done | 2026-11-09 | `180b9ed` (merge `1a6f5ec`) | none (docs only) | 120 month ends: hold 23, reduce 19, enter 0, no_call 78 (flow 59, 10Y 19); window 2021-10 → 2026-07: enter 0/14 (unreachable, ERP − hurdle peaks +0.19pt vs 1.0), reduce 7/7, 3 short per side; factor_series EY vs snapshot EY +0.06pt mean on 19 dates; 1-month 0/41 and valuation-only 0/34, both insufficient |
| S50 bonds walk-forward, live (P69-bonds-history) | done | 2026-11-09 | `3b2772e` (merge `afa067c`) | none (docs only) | **not yet**: enter 10, hold 35, reduce 4, no_call 71 (SBN 52, 10Y 19); window 2021-03 → 2024-08: enter 3/11 (7 short, ~8 years live), reduce 1/13 (9 short); returns point the wrong way (enter +0.58%, hold +1.31%, reduce +4.26% over 3 months); 1-month 8/36; 10Y ask in *Open data gaps* |
| S51 home-regime inputs (P70-home-inputs) | done | 2026-11-07 | `07e39b4` (merge `27b3328`) | home_inputs (1676 at S51) | four inputs point in time with newest dates and 7-day stale lines; 10-16 JCI −18.8% vs its 20-day high; 11-07: JCI −17.45%, flow z −0.72, USD/IDR +1.15%, SBN +0.45% (fresh only from 11-06, DJPPR came in one file) |
| S52 home-regime rule and walk-forward (P71-home-regime) | done | 2026-11-07 | `e489758` (merge `74d55d6`) | 28 home_regime (1718 at S52) | 24 risk_off Fridays in 7 episodes since 2021-10 (risk_off 10-16 → 11-06 on JCI alone); JCI and IDR 20d walk-forward insufficient (5 windows), `HOME_SHIFT_ADOPTED` False; ladder vs lump and P8 rerun reported |
| S53 home regime in the stance (P72-home-stance) | done | 2026-11-09 | `4ce1891` (merge `e62f644`) | stance, layers, journal (1795 at S53) | stance schema 1.2.0 `home_regime`, `regime.json` `home` (layer schema 1.1.0), model 0.5.0; home risk_off at 2 points (JCI −17.5% vs 20d high), global risk_off; IDN stocks neutral 43.5, bonds neutral 49.0, both laddered, no shift |
| S54 home regime on the pages (P73-home-pages) | done | 2026-11-09 | `d75870c` (merge `cf242bb`) | brief, notify, regime view, ops (1811 at S54) | brief and Telegram "Home regime (IDN): risk_off, 2 points (JCI −17.5% vs 20d high (2))"; `/regime` 200 with the Home regime card (−5pt shift shown as not adopted); `regime --check` journals the home state, dry check unchanged (global and home risk_off) |
| S56 reduce side and bond-return timing (P74-reduce-side) | done | 2026-11-09 | `d199cd3` (merge `884f00e`) | gate, history, run_idn (1792 at S56) | the gate tests reduce on its own (rules schema 1.1.0 `reduce`); an enter applies only on the enter verdict, a reduce only on the reduce verdict; bonds returns lag the OECD averages one month; cold rebuild 2,442 s: bonds enter 3/11 (was 4/11), reduce 1/13; stocks enter 0/14, reduce 7/7; all insufficient, no stance moves |
| S55 phase K fan-in (F10-phase-k) | done | 2026-11-09 | merge `32eb850`, docs this commit | 1832 (merged main) | one live `assist run` on main 09:58 → 10:51 WIB (53 m 9 s, rule history cold rebuild 2,616 s) opens segment `sha256:7c387d7b4148…` (after `8c6a886f278d…`, 5 models, 503 records, chain ok); global risk_off, dollar flat; home (IDN) risk_off at 2 points (JCI −17.5% vs 20d high; flow z −0.72, USD/IDR +1.1%, SBN +0.4%, all counted, none stale); IDN stocks neutral 43.5 (0.65), bonds neutral 49.0 (0.79), currency neutral 49.3, stocks −48.9pt and bonds +30.2pt laddered 3 × 10 days, tilt 0; `out/rules/` both **insufficient**: bonds enter 3/11, reduce 1/13 (2021-03 → 2024-08), stocks enter 0/14, reduce 7/7 (2021-10 → 2026-07), live 0/0 since 11-09; 49 stances (7 overweight, 36 neutral, 4 underweight, 2 avoid); Telegram suppressed (07:00 weekly already sent, marker `brief_2026-11-09.json`) |
| S57 IDN override input history (P75-override-inputs) | done | 2026-11-09 | this commit (branch `phase-l`) | 18 override_history (1849 total) | P17 on 262 month ends 2005-01 → 2026-10 in 5.5 s (each store read once): every component on 109, from 2017-07 (trade binds; growth from 2012-05, bi_rate 2006-02, cli and inflation 2005-01) except 2024-02 → 04 (bps-looker CPI known < 3 months, no dbnomics fallback); shift signs on complete months: stocks up 66 / zero 8 / down 35, bonds 48 / 7 / 54, currency 43 / 23 / 43 (descriptive, no returns); 2026-10-31: stocks −4, bonds −1, currency +3 |
| S58 IDN override forward returns (P76-override-returns) | done | 2026-11-09 | this commit (branch `phase-l`) | 24 override_history (1855 total) | `idn_returns`: stocks JCI, bonds `bond_forward` (proxy lagged a month, IGSYC as is), currency USD/IDR(t)/USD/IDR(t+3) − 1 on the P65 splice (rupiah up = positive), never across a gap or from a running month; complete months with a 3-month return: stocks and currency 2017-07 → 2026-07 (106), bonds 2017-07 → 2024-08 (83) |
| S61b P17 CPI fallback (P85-cpi-fallback) | done | 2026-11-09 | this commit (branch `phase-l`) | 3 overrides_idn, override_history updated (1858 total) | P17 inflation falls back to dbnomics `idn.cpi.yoy` when bps-looker CPI has no point 3 months back (the bps short line stays stale; the newest CPI level stays bps-looker's); live: no inflation hole, 112 complete months 2017-07 → 2026-10; rule fingerprints bonds `deb1f60c…` → `f9be0b94…`, stocks `d217e458…` → `457c6c85…` (out/rules/ rebuilds cold at S66) |
| S62 Foreign fx on the USD/IDR splice (P80-foreign-fx) | done | 2026-11-09 | this commit (branch `phase-l`) | 4 overrides_foreign (1862 total) | P28 reads IDR per USD from the P65 splice (store key `usdidr`, MAS leg lagged a day); live USA fx +0.87% / 3m, JPN +0.38% (both inside 1.5%: shifts unchanged, USA 0 / −3 / +2, JPN −3 / −2 / +1); no JISDOR stale line |
| S59 Override gate (P77-override-gate) | done | 2026-11-09 | this commit (branch `phase-l`) | 21 override_gate, 3 run_idn, 1 ops (1887 total) | `eval/override_gate.py`: up / down per asset on complete months, phase K numbers, Holm per subject, CLI-zeroed check, live monitor on `overrides` records of the override fingerprint, revocation; `out/overrides/IDN.json` (schema `overrides.schema.json`), `assist overrides`, `assist run` reads it and journals an IDN `overrides` record; live IDN: all six sides failed (S60), nothing moves |
| S60 IDN override walk-forward (P78-override-walk) | done | 2026-11-09 | this commit (branch `phase-l`) | docs only (1887 total) | horizon 3, complete months: stocks up 24/13 t 1.08 p 0.186, down 12/25 t 0.92 p 0.225; bonds up 13/16 t −0.99, down 15/14 t −1.03; currency up 13/24 t 1.75 p 0.122, **down 15/22 t 2.47 p 0.047** (Holm needs 0.0083; CLI zeroed t 0.95); all six failed, none insufficient; no override may cross a band; 1-month and per-component diagnostics nothing near |t| 2 |
| S63 Foreign override input history (P81-foreign-override-inputs) | done | 2026-11-09 | this commit (branch `phase-l`) | 9 override_history (1896 total) | `foreign_replay`: P28 on 262 month ends in 86 s, stores read once, GDPC1 at its vintage per date, ausdata per date, AUS fx on the MAS cross until RBA AUD/IDR has 3 months (2023-04); complete months USA 259, JPN 259, EMU 259 (from 2005-04), AUS 155 (from 2013-12, the AGS curve), SGP 247 (2006-04); GDP read at today's revision would flip USA growth in 64 of 262 months; locked reads retried |
| S64 Foreign forward returns (P82-foreign-returns) | done | 2026-11-09 | this commit (branch `phase-l`) | 5 override_history (1901 total) | `foreign_returns`: currency = IDR per local unit (MAS crosses), bonds = local 10Y `bond_returns` × the FX move, USA stocks = SPY × IDR per USD; complete months with a 3-month IDR return: USA bonds and currency 256 (2005-04 → 2026-07), stocks 127 (2016-01 →), JPN 256, EMU 254 / 256, AUS 152 (2013-12 →), SGP 244 |
| S61 A passed side crosses a band (P79-override-stance) | done | 2026-11-09 | this commit (branch `phase-l`) | 7 stance, 4 run_foreign, 3 brief, 3 view_signals (1918 total) | `build_stance(override_gate=)`: a shift crosses a band only in the direction of a passed side, else held and named; `layer2` block (stance schema 1.3.0), MODEL_VERSION 0.6.0, `override_moves_stance` "passed_side_only"; foreign gates in the run, EMU's reaching its five members; journal `moves_band` per stance; brief line and `/signals` gate column; IDN: no side passed, nothing moves |
| S65 Foreign walk-forward (P83-foreign-walk) | done | 2026-11-09 | this commit (branch `phase-l`) | docs only (1918 total) | all 20 foreign sides failed, none insufficient (USA 6 incl. stocks on SPY 22/21 and 16/27; JPN, EMU, AUS, SGP bonds and currency); best placebo p USA stocks down 0.078, JPN bonds up 0.087; control t −0.21..+0.21; no override may cross a band anywhere; suspect: AUS currency inverted (1-month t −2.39 / −2.51), bonds wrong-signed in IDN, USA, SGP, EMU up (Open questions) |
| S66 Phase L fan-in (F11-phase-l) | done | 2026-11-09 | merge `a8dd638` | 1919 on main | `assist run --no-send` 14:55 → 15:34 WIB (38 m 37 s, rule history cold 1,916 s): model `sha256:b68e9bce1774…` (0.6.0), journal 573 records, 6 models, chain ok; out/rules/ new fingerprints, both insufficient (bonds enter 3/11 reduce 1/13; stocks 0/14, 7/7); out/overrides/ IDN, USA, JPN, EMU, AUS, SGP all sides failed; no band crossed, FRA / ITA / USA bonds held; IDN stocks 43.5, bonds 49.0, currency 49.3, all neutral; Telegram not sent |
| S15 Industry-relative value screen (S15-industry-value) | done | 2026-11-09 | this commit (branch `s15`) | 19 industry_value (1937 total) | 119 month ends, 95 scored 2018-11 → 2026-09: top − bottom quintile +0.85%/mo, **failed** t 1.76 < 2.0 (p 0.040, control t 0.37), no candidate; live 2026-11-05 pool 399 in 24 peer groups (14 sub-industries), 60 pass gates and floor; fitted leg alone t 2.44 (diagnostic); 17 s |
| S67 Cost basis in layer 5 (P86-cost-basis) | done | 2026-11-10 | this commit (branch `phase-m`) | 10 financer, 2 run_undervalued, 1 portfolio expectation updated (1958 total) | `Holding.avg_cost` / `cost_value` (None when the statement prints 0: FR0080), `roll` re-averages through trade documents (a buy by its net amount, a sell in proportion), `undervalued.cost_basis_from`; nothing reads it; live, both accounts: 67 IDN stock names all with a cost, 61 below cost, six at 16% or more below (AMRT −36.7%, KKGI, CTRA, KLBF, TOWR, ASII), BMRI −15.0%, cost Rp58,905,894 vs value Rp53,697,910 (−8.8%); model fingerprint `13d8dceb4fa3…` → `0054161d53f8…` with identical behaviour (segment opens at S71) |
| S68 Average-down rule (P87-average-down) | done | 2026-11-10 | this commit (branch `phase-m`) | 16 average_down, 4 run_undervalued (1995 total) | `candidates/average_down.py` (`judge`, gates 1–6: underwater at 5%, kept by a passing screen, entry status context, sizing's room, budget, `entry_typical` limits); `assemble(cost_basis=)`: row `cost_basis` and `average_down`, action `average_down` when sized, top-level `average_down` block, candidates schema 1.1.0, journalled; sizes and trims untouched; live (bars 2026-11-05, budget 0): 67 held, 46 stop at gate 1, 20 at gate 2, BMRI (−15.2%) at gate 4 over the 5% cap, none funded or unfunded; model fingerprint `8aeca8e62547…` → `aa9e0c60fe9c…` (a real change; segment opens at S71) |
| S69 Placebo for gate 3 (P88-dip-placebo) | done | 2026-11-10 | this commit (branch `phase-m`) | 17 dip_gate (1975 total) | `eval/dip_gate.py`: adds in `buy_zone` or `deep` at month ends (levels from bars on or before the date, add at the next session) against the same names on random days, 12-month total return, phase K's gate numbers; live **insufficient**: 1 non-overlapping window of 10 (11 scored months 2024-11 → 2025-10, 1,844 zone adds, 797 names), so gate 3 stays context; diagnostics, overlapping: real +48.4% vs placebo +46.7%, ahead 5 of 11 months, `avoid` 38% winners against 56–59% for the rest; at 3 months 7 windows, also insufficient; model fingerprint `0054161d53f8…` → `8aeca8e62547…` with identical behaviour (segment opens at S71) |
| S70 Surfacing (P89-average-down-ui) | done | 2026-11-10 | this commit (branch `phase-m`) | 3 brief, 2 view_candidates, 1 view_portfolio, 2 expectations extended (2001 total) | `brief.average_down_view` / `average_down_lines`; Telegram `IDN to average down` block after "to buy" (funded with old → new average cost, unfunded, one line on where the rest stopped); brief Action cell and bullets; `/candidates` columns `Avg cost`, `vs cost` and an *Average down* card; `/portfolio` adds table with `Action` and `Avg cost IDR`, an *Average down* table, and the JSON twin; no run made, fingerprint unchanged from S68 |
| S71 Phase M fan-in (F13-phase-m) | done | 2026-11-10 | merge `bc595b9` | 2001 on main | `assist run` 11:37 → 11:44 WIB (6 m 56 s), exit 0: model `sha256:aa9e0c60fe9c…`, 70 records, journal 644 records, 8 models; `out/candidates` schema 1.1.0; IDN 67 held, none an average down (46 gate 1, 20 gate 2, BMRI gate 4); Telegram not sent (not configured in the shell, no marker written); not pushed; CLAUDE.md untouched |
| S72 Hover explanations (P90-regime-hover) | done | 2026-11-10 | this commit (branch `phase-n`) | 11 view_regime (2012 total) | `views/regime.py` `EXPLAIN`, `HOME_EXPLAIN`, `.tip` span (hover, focus, tap) on the 9 global and 4 home inputs; thresholds in words tested against `layers.regime.RULES` and the file's home rule; `/industries` empty text names idx-method's empty `api_raw` and the 16:30 close job; no model change |
| S74 Exits and entry prices (P92-exits) | done | 2026-11-10 | `1bcd11e` (branch `phase-n`) | 12 exits, 1 run_undervalued | `candidates/exits.py`: entry cap (close + 1%), take-profit at the fair price (dividend screen; none for GARP), thesis stop and a review price that never sells; row `exits`, candidates schema 1.2.0; no size changes |
| S73, S75, S78 Plain words, the guide, brief and Telegram (P91, P93, P96) | done | 2026-11-10 | `c20a346` (branch `phase-n`) | 14 guide, 4 rebalance, 3 plain, 3 e2e expectations extended | `plain.py`; `candidates/rebalance.py` pro-rata sales (hashed); `guide.py` → `out/guide.json` (schema 1.0.0), journalled; brief and Telegram open with the steps; read-only on the 2026-11-10 run: 54 sells Rp 27.1m (1 strong, 15 failed-screen, 38 rebalance) and 2 bucket buys Rp 27.8m (SBN 16.7m, US index fund 11.1m), 3 tranches 11-11 / 11-23 / 12-01 |
| S76, S77, S79 Home page, navigation, one place per fact (P94, P95, P97) | done | 2026-11-10 | this commit (branch `phase-n`) | 6 view_guide, web / overview / candidates / e2e tests updated (2053 total) | `/` is "This week" (orders by date, legs, take-profit and stop); the old overview is `/background`; grouped navigation; Average down table only on `/portfolio`; style names in plain words; `/signals`, stance pages and trim reasons still show raw terms |
| S80 Phase N fan-in (F14-phase-n) | done | 2026-11-10 | merge `56c5025` | 2053 on main | `assist run --no-send` 13:19 → 13:26 WIB, exit 0: model `sha256:cf920942a6d4…`, 71 records, journal 715 records, 9 models; `out/guide.json` 54 sells Rp 27.1m (1 strong, 15 failed-screen, 38 rebalance) and 2 bucket buys Rp 27.8m in 3 tranches; candidates schema 1.2.0; local UI restarted; not pushed; CLAUDE.md untouched |
| S81–S83 Groups and keepers, buying, rebalance sales (P98, P99, P100) | done | 2026-11-10 | this commit (branch `phase-o`) | 8 diversify, 4 rebalance, 4 run_undervalued, 2 guide (2071 total) | `candidates/diversify.py` (industry × size group, keeper by screen rank, favourable-tilt exception); sizing gives a redundant row no new money; candidates schema 1.3.0 `diversification`; `rebalance.ordered_sales` sells redundant names in full first, then pro rata, kept names last; read-only on the 2026-11-10 run: 52 judged, 16 redundant, none allowed; guide 51 sells (16 trims, 16 redundant in full about Rp 7.0m, 19 pro-rata) against 54 before, same Rp 27.1m; trims unchanged; size lines Rp 50T / 5T and the industry level are defaults |
| S84 Phase O fan-in (F15-phase-o) | done | 2026-11-10 | merge `55dec7a` | 2071 on main | `assist run --no-send` 13:56 → 14:03 WIB, exit 0: model `sha256:427a7008dd87…`, journal 786 records, 10 models; candidates schema 1.3.0 (52 judged, 16 redundant, none allowed); guide 51 sells Rp 27.1m and 2 bucket buys Rp 27.8m; local UI restarted; not pushed; CLAUDE.md untouched |
| S81b Keeper by dividend yield (P98b-keeper-yield) | done | 2026-11-10 | merge `0b9a0dc` | 2 diversify (1 replaced), fixtures (2072 total) | unrated names in a group keep the highest `div_yield` (user 2026-11-10), then the larger holding; `diversification.names[].div_yield`, candidates schema 1.3.1; read-only on the 2026-11-10 run: still 16 redundant of 52, but larger holdings (TOWR, KLBF, TOTO, TPMA, SICO now go, ISAT, TSPC, SPTO, KKGI, MYOH stay), so the guide has 33 sells (16 trims, 16 redundant, 1 pro-rata) against 51, same Rp 27.1m; live `assist run --no-send` 14:32 → 14:39 WIB, exit 0: model `sha256:f38a1c1be6a4…`, journal 857 records, 11 models; candidates schema 1.3.1; guide 33 sells Rp 27.1m and 2 bucket buys Rp 27.8m |
| P101 SUN 10Y fallback (P101-sun-10y) | done | 2026-11-11 | this commit (branch `j9-sun-10y`) | 3 adapter, 2 bonds, 2 stocks, 1 hurdle, 1 history (2081 total) | `PheiSource` serves `SUN.<tenor>` from idxscape J9's `sun_benchmark_quote` (known on its quote date; migration 11 read apart, store key `idxscape_sun` in the Ref readers, so a store without it still serves IGSYC); order IGSYC → SUN → OECD proxy in `layers/bonds/idn`, `layers/rules/idn_stocks`, `candidates/hurdle`, `layers/candidates_foreign.IDR_10Y` and `history.ten_year_months`; slope still IGSYC only. Read-only live: `ten_year_months` 179 points, 2025-01 → 2026-09 now SUN month ends (6.98 → 6.36%); rules on 2025-06-30 bonds enter (real 5.02%) / stocks reduce (EY gap −1.67pt), 2026-03-31 reduce / reduce, 2026-11-10 hold / hold on IGSYC. Not run: `assist run` (new segment, gate rebuild ~45 min); r1 valuation fix not folded in (user to decide) |
| P102 Stocks valuation r1 (P102-stocks-r1) | done | 2026-11-11 | this commit (branch `j9-sun-10y`) | 3 new stocks (r1 band, no spread ×3 cases), 4 updated; stocks and history fakes serve spreads (2085 total) | `idn_stocks.py` only: no `G_REAL`; `_hurdle` = US ERP + CRP (else `idn.erp.hurdle`) − IDN `default_spread` from `damodaran_crp` (lag 45 d, max age 450 d; none → no hurdle, no call); `ERP_BAND` and every phase K number unchanged. Read-only live: 2021-12-31 reduce (EY 3.74% after the V4 scrub, diff −5.82), 2022-12-31 hold (−0.17, the peak), 2025-06-30 reduce (−4.96), 2026-11-10 reduce (EY 7.78%, hurdle 4.55%, −1.22; was hold) |
| S85 Data gate and price fix (P103-data-gate) | done | 2026-11-12 | `1d9c050` (branch `phase-p`) | 2 factors, 2 guide, 1 undervalued (2089 total) | `factors.enrich` takes the history's close when Stockbit's screener `Price` is None (null for all 959 names since 2026-11-10); `factors.data_check` and `undervalued.pool_problems` fill candidates `data_problems` (schema 1.4.0); any entry holds every guide step (`held_for_data`, guide 1.1.0). Live `assist run --no-send` 6 m 29 s, exit 0, model `sha256:7c55d462edbd…`: data_problems none; dividend_value pool 0 → 38, 8 rows (BMRI, ELSA, CPIN, BBRI, STAA, BFIN, BBNI, AUTO, all hold); guide 44 sells Rp 28.4m (22 redundant, 13 rebalance, BMRI to the 5% cap; BBNI no longer sold) and 2 bucket buys Rp 29.1m; Telegram not sent |

**F5-undervalued notes (2026-10-27).** `assist run` now writes one ranked undervalued list per
market (`layers/undervalued.py`, IDN only until F6 adds the US) to `out/candidates/IDN.json`
(`schema/candidates.schema.json`: disclaimer, sources and model fingerprint required).
- **Assembly.** P36 dividend and P37 GARP results, each ranked by its own margin over the S17
  hurdle; S15's value screen is one more entry in `UndervaluedInputs.screens` when it lands. A
  style whose verdict failed is listed with its verdict, t, p and pool, and no names. Across
  styles nothing is ranked on a mixed score: the Telegram top 5 takes each passing style's ranks
  in turn.
- **Tilt.** S16's applied margin shift (clamped ±2 pt) and per-sector caps reach the rows and
  sizing only when the tilt's verdict passed; otherwise shift 0, cap 5.
- **Costs and entry** as `layers/candidates.assemble`: P21's cost at an IDR 10m tranche
  (no estimate, `over_participation` or `below_one_lot` drops the name). Rows are reviewed
  quarterly and held while they pass, so one round trip a year is charged against the annual
  margin (`net_margin_pt`); a round trip that eats the margin drops the name. Entry =
  `entry_typical`, else `entry_deep`.
- **Layer 5 and sizes.** Held IDR per ticker from financer's statement lines
  (`holdings_from`, layer 5's own mapping), P38's `size` from the IDN stocks stance and the
  financer total. A name in two styles is sized once, under its larger margin. Trims only when a
  style passed, and a full trim only for a held name a passing screen ranked: a held name no
  passing screen rated is listed in `sizing.excluded` ("not rated: no trim call") instead of
  P38's "not in the candidate list", which would otherwise have told the user to sell every
  holding the dividend screen does not cover.
- **Journal.** One `undervalued` record per market (verdicts, names, sizing, stale) and one
  `undervalued_row` per row; both carry `config`: the tilt yaml sha256, `hurdle.CONFIG`,
  `sizing.config(caps)`, the tranche and each screen's CONFIG, beside the model fingerprint.
- **Brief and Telegram.** The brief gains *Undervalued candidates* (before *Paper track*), read
  from `out/candidates/`, so `assist brief` reprints it; the golden brief is unchanged without
  that directory. Telegram adds each market's style verdicts and top 5 (live: one part, 2.7k
  chars).
- **Never fails.** An error in the screens, the tilt or the assembly becomes a stale input
  ("undervalued candidates failed: …") and no file; the stances are already written.
- **Live** (`--no-send`, 2 m 20 s, most of it P35's regime replay): see the Progress row. Also:
  portfolio IDR 29.6M; BMRI (IDR 4.01M) and BBNI (2.37M) are held, so both read `hold`;
  9 held names unrated (ASII, ASSA, CTRA, DMAS, ERAA, KKGI, MSTI, PTSN, TOWR). Journal per
  run: 1 `undervalued` + 3 `undervalued_row`. idx-method HEAD `71ef6ed`, unchanged since
  P36/P37 read it; nothing in the siblings disagreed with the slice notes.
- **For later slices.** At this portfolio size P21's round trip at a 10m tranche (80–145bp)
  is larger than the thin dividend margins (0.3–0.5pt) and drops half the list; F6 should
  judge costs at the sized tranche once a budget exists. Sizes stay paper until the weight
  bands are confirmed (Open questions).

**F6-us-stocks notes (2026-10-27).** `assist run` adds the US list beside IDN's
(`Sources.undervalued_us` = `undervalued.gather_live_usa`). Each market is gathered and assembled
on its own, so a failing US store leaves IDN alone (stale input "undervalued USA candidates
failed: …").
- **Inputs.** `undervalued.us_inputs` turns P39's `us_stocks.run` output into F5's inputs, all
  in IDR at JISDOR on the last session:
  - `expected_pt` is the unhedged IDR return.
  - The payload hurdle is the **binding** one, the higher of the USA and IDN hurdles. That way
    `margin_pt` (P39's lower margin) still equals expected − hurdle.
  - The hurdle drivers name the binding market and the USD return it needs. Each row's drivers
    carry its USD price and its margins over both hurdles.
- **No tilt**, as the slice notes say. There is no margin shift and the default caps apply.
  sec-edgar has no SIC, so in sizing every name is its own sector bucket (as in P39's
  `select`); otherwise all US names would share one 5-name cap.
- **Costs.** P21's model is IDX-only (board lots, tick grid, sales tax), so a hand-set
  `US_COST` stands in, and it is journalled in `config.market`:
  - 10bp broker fee and 25bp IDR↔USD conversion per side;
  - 2bp half spread;
  - P21's square-root impact.
  A tranche below one share is `below_one_lot`. There are no entry levels, because P21 reads
  idx-method history.
- **Sizing.** P38's `size` from the USA stocks stance budget (target − current × the financer
  total). P38 counts IDX lots of 100, so it sees the IDR price ÷ 100 and its shares are divided
  back by 100. That is exact for whole shares.
  - At today's portfolio the budget is IDR 1.48M (about US$82), and so is the 5% per-name cap.
    Whole shares will therefore rule out most US$2bn+ names once there are candidates.
    Fractional shares would need a schema change (`shares` is an integer).
- **Layer 5.** financer's 2,155 holding lines are all IDR, and layer 5's `classify` maps no USD
  line. So nothing is held in the US list and no trim is called.
- **Brief.** Each market block now also prints its hurdle drivers and, under each style table,
  one line per row with its drivers after the first. The USA block follows IDN's.
- **Live** (`--no-send`, about 2 m 20 s). See the Progress row. sec-edgar is still at `51c36ec`
  (P39's read), with `alpaca_*` empty here; that is P39's finding 1, and nothing new disagreed
  with the slice notes.
  - USA.json was byte-identical across three reruns.
  - IDN.json changed once, between the first and second runs after the model fingerprint
    changed, and was identical after that. The cause was not pinned down: either journal
    history read by the IDN rules, or a sibling store updating mid-session.
  - Fixed here: F5 read `t` and `p` from the verdict dict, but `placebo.Verdict.to_dict` names
    them `score_t` and `p_value`, so every style's `t` and `p` were null. They are filled now
    (IDN dividend t 2.79, p 0.004).
  - Still open: F5's suggestion to judge costs at the sized tranche. IDN's budget is 0 today.

**F4-ops notes (2026-10-23).**
- **Brief.** `brief.render` takes optional `health` and `paper` lines:
  - *Data health* sits under the disclaimer, built by `health_lines` from `doctor.SourceStatus`.
    It has one line per source that is missing, locked or stale, or present with an absent probe.
  - *Paper track* sits before *Details*, built by `paper_lines` from `paper.PaperReport`.
  - Without either the brief is unchanged, so the golden file was **not** regenerated.
  - `pipeline.Sources` gains `doctor` and `paper` callables, live by default and None in tests.
    Paper reads the journal after this run's records, so the current model shows as a segment.
    A failure in either becomes one "… failed: …" line, never a failed run.
  - `assist brief` (reprint from out/) shows neither section.
- **Daily regime check** (`pipeline.regime_check`, `assist regime --check`):
  - It compares today's regime with the newest `regime` record on or before the day, from a
    weekly run or an earlier check.
  - The first check journals a baseline and sends nothing.
  - On a state or dollar change it sends Telegram (kind `regime`, send-once per day) and journals
    the new regime once the message is sent or was already sent. A failed or unconfigured send
    journals nothing, so the next check retries.
  - `--no-send` writes nothing. If FRED cannot be read (`Regime.sources` empty), it compares
    nothing.
- **launchd.** `launchd/install.sh [--dry-run|--uninstall]` mirrors bisfetcher's: templates with
  `__REPO__`/`__UV__`, the repo defaulting to the main checkout. `launchd/job.sh weekly|regime`
  runs `uv run assist …` under `lockf launchd/.jobs.lock`, because both jobs fire at Monday 07:00
  and the brief and out/ must not interleave. It logs to `launchd/<job>.log` (gitignored).
  Nothing was installed or loaded, and no Telegram was sent.
- **`assist paper`** prints the paper lines (`--json [--marks]` for P30's full report).
- **Live** (worktree, `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects`, `--no-send`):
  49 stances, unchanged from F3. The doctor header lists sec-edgar stale (VIXCLS 11d/7d),
  satudatascape missing, jquantster stale (`investor_types` empty), idxscape `igsyc_point PHEI`
  absent, and idx-method stale (`jkse_daily.csv` 23d/7d, stockbiter bars 11d/7d). The brief is
  about 50 kB, and the rerun gave the same bytes. Journal: 130 records after two runs, chain ok.
- **For the user.** Pull the main checkout, then `sh launchd/install.sh --dry-run` and
  `sh launchd/install.sh`. The jobs send from the login Keychain item
  `investment-assist-telegram`. Before the first daily check, the weekly run (or one manual
  `assist regime --check`) sets the baseline.

**F3-foreign notes (2026-10-23).** `assist run` now gathers the foreign layers
(`pipeline.ForeignSources`, `gather_foreign`) for the 11 foreign countries × stocks, bonds and
currency (33 stances; model 0.3.0).
- **Overrides (P28)** shift USA, JPN, AUS and SGP, and the `EMU` shift is copied to each
  worldbankscape member (DEU, FRA, ITA, ESP, NLD) under its own subject. As for IDN, a shift that
  alone would cross a band is held at the band without it until the overrides beat a placebo.
  KOR and TWN have no overrides: their score stays at layer 1 and a driver says so.
- **Layer 4 (P29)** reaches each foreign stocks stance as a driver and a watch line (no
  candidates slot in the schema). Its scoring is hand-set, so it never moves a stance. Only the
  US has an index valuation.
- **IDR edge.** Every foreign stance names it in its drivers, over 1 year, hedged against
  unhedged (P27 `fx_edge`, P29's adverse 5th-percentile FX move and policy-rate hedge):
  - stocks: P29's IDR test;
  - bonds: the local 10Y against the IDN 10Y;
  - currency: local cash against the BI rate, unhedged only, because hedged it earns the BI rate
    exactly.
  Where an input is missing the edge reads n/a. Euro members show P28's IDR terms (FX move, hedge
  carry) instead, because P29 has no euro-area market. An edge that does not survive goes into
  `risks`. CLAUDE.md's "overweight only if the edge survives" is not enforced before a placebo.
- **Journal.** Each run adds one `overrides` record per P28 market (shift per asset, and per
  stance reached whether its band was held), one `candidates` record per P29 market (`moves_stance`
  false) and one `idr_edges` record: 65 records per run, up from 53.
- **Live** (`--no-send`, because today's Telegram had already gone): 49 stances, still 15
  overweight, 31 neutral, 2 underweight and 1 avoid. **No stance changed.**
  - Bands held: AUS bonds (61.2 → 58.2), NLD bonds (63.5 → 54.5) and SGP bonds (60.1 → 53.1)
    stay overweight.
  - Scores that moved inside their band: euro bonds −9 (DEU 47.3, FRA 40.1, ITA 42.2, ESP 45.7),
    USA bonds 44.1, USA stocks 64.3 and JPN currency 56.1.
  - Confidence fell where the new inputs are stale or missing. SGP fell the most (bonds
    0.32 → 0.19), from MAS data last updated 2026-10-07 and the IDN 10Y proxy last dated 2024-12.
  - The rerun was byte-identical. Telegram is still one part, but its stale line grew (2.8k chars).
- **IDR edges live:**
  - USA stocks +1.10% (survives hedged: +8.11% vs IDN 10Y 7.01%);
  - bonds: JPN +0.48%, KOR +0.23%, SGP +0.04% (all survive hedged only), USA −0.12% and AUS −0.54%
    (neither survives);
  - every currency is negative (JPY −14.3%, KRW −8.1%, AUD −4.2%, SGD −2.9%, USD −2.6%).
  - Two overweight stances carry the "does not survive" risk: AUS bonds and SGP currency. SGP
    stocks, TWN bonds and TWN stocks are overweight with the edge n/a.
- **Stale inputs added:** the singstat MAS series (`mas:fx:eursgd`, `idrsgd`, `sgs:2y`, `sgs:10y`,
  `sora:comp3m`; last 2026-10-06/07), `dbnomics idn.rate.long` (2024-12, used as the IDR
  alternative while PHEI is missing here), `openkrx (missing)`, and P29's per-market "no source"
  gaps (JPN/AUS/SGP/KOR/TWN valuation, JPN and TWN CPI, TWN 10Y and policy rate).
- **For later slices.**
  - Every IDR edge uses the IDN 10Y. Once PHEI lands here (idxscape migration 9) that input stops
    being stale, and the bonds edges near zero (SGP +0.04%, USA −0.12%) may flip.
  - If F4 or the user wants CLAUDE.md's rule enforced, an overweight that fails its IDR edge
    would need a placebo-gated rule, like IDN's `gated_stance`.

**F2-idn notes (2026-10-23).** `assist run` now gathers Indonesia's layers 2–4 (`pipeline.IdnSources`,
`gather_idn`) and passes P8's live regime, P17's overrides and P18's signals into both IDN rules.
- **Gates.** Each rule's proposal goes through its `gated_stance` with a verdict built from the
  rule's own journalled calls (`journalled_verdict`): only calls journalled before the run day
  count, judged on the forward 3-month JCI return (stocks) or the 10Y return proxy (bonds), so the
  verdict never looks ahead and a same-day rerun gives the same bytes. Today both are
  `insufficient sample (on 0, off 0)`: no calls yet, JCI frozen at 2026-09-30. Every run journals
  a `rule` record per rule (call, proposal, stance written, verdict, inputs) and a `candidates`
  record (names, drops, every screen's verdict): 53 records per run (49 stances + regime + 2 + 1).
- **Overrides** shift the IDN scores (schema `score`), but a shift that alone would cross a band
  is held at the band without it until the overrides beat a placebo; the driver says so. Live,
  none crosses (stocks 53.6 → 48.6, bonds 58.0 → 56.0, currency 52.5).
- **Layer 4** (`layers/candidates.py`): the passing screen's monthly top − bottom spread (224bp
  for momentum) minus each name's `Cost.round_trip_bps` at the IDR 10m tranche; names flagged
  `over_participation` or `below_one_lot`, or whose cost eats the edge, are dropped; entry level
  = `entry_typical`, else `entry_deep`. The stance schema has no candidates slot (schema/ was not
  this slice's), so the headline goes into the IDN stocks `drivers` and one line per name into
  `watch`. Context only: candidates never move a stance.
- **Live** (`--no-send`; today's Telegram had already gone): 49 stances (15 overweight, 31
  neutral, 2 underweight, 1 avoid), IDN bonds neutral 56.0 (confidence 0.34), IDN stocks neutral
  48.6 (0.28), IDN currency neutral 52.5; rerun byte-identical; Telegram text still one part
  (1.9 k chars). Top names: BSML, MMIX, TINS, AADI, MARK, DEWI, AUTO, HRTA, ERAA, SRSN.
- **For later slices.** P21's entry levels are degenerate for momentum names at fresh 3-year
  highs: BSML (575, high 575) reads a typical correction of −96% → entry 21, DEWI −86% → 35, so
  read `entry_typical` with care there (a short, unadjusted history; P21's notes). PHEI landing
  on this Mac (idxscape migration 9) turns both rules from no call into calls, which then start
  building their journalled verdict.

**F1-run notes (2026-10-23).** In scope: IDN, USA, JPN, DEU, FRA, ITA, ESP, NLD (the EU as its
members; worldbankscape has no euro-area aggregate), SGP, AUS, KOR, TWN × stocks, bonds,
currency, plus all 14 commodities; worldbankscape's `business` and `property` have no stance.
This Mac's sec-edgar copy stops at 2026-10-12, so all five core regime inputs are stale and every
stance's confidence carries ×0.9⁵ (e.g. IDN stocks 0.43); the jobs Mac should not show this.
Telegram shows every IDN stance plus every non-neutral one elsewhere (one part, ~1.7 k chars);
the other neutral stances are counted and left to the brief. The live send ran from the F1
worktree (the agent sandbox blocks git in the main checkout, so it could not pull) with
`ASSIST_NOTIFY_STATE` pointing at the main checkout's `data/notify/`: the send-once marker
`brief_2026-10-23.json` is there, but the main checkout's `out/` and `journal/` stay empty until
it pulls and runs.
