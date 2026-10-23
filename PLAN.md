# investment-assist — plan

The entry point that reads the sibling fetcher repos and turns their data into a **stance and an
entry plan per country × asset class** for an IDR-based investor. The decision flow it implements
is in `CLAUDE.md` (*Investment decision flow*); this plan is how it gets built.

---

## STATUS — read this first in a new session

**Last updated:** 2026-10-23, phase C done (F3-foreign): `assist run` reads layers 0, 1 and 5
for every subject, Indonesia's layers 2–4 (overrides, signals, the IDN bonds and stocks rules,
layer-4 candidates) and the foreign subjects' layer 2 (P28 overrides: USA, JPN, euro area, AUS,
SGP) and layer 4 (P29 index candidates), writes 49 stance JSONs to `out/` (each foreign one
names its IDR edge, hedged vs unhedged), journals them with every rule call, override and
candidate decision, writes the brief and sends one Telegram summary a day. No stance moved in
phase B or C: the IDN rules make no call on this Mac and the foreign overrides and candidates
are hand-set, so they move scores but not bands until they beat a placebo. Build runs from
`plan.yaml` (slicer worker loop). Phase D slices (P30 paper) have landed as modules but are not
wired yet. **Next up:** F4.

| Phase | Slices | Done |
|---|---|---|
| A. Skeleton + base layers (0, 1, 5) | S0–S6 | 7 / 7 |
| B. Indonesia overrides and rules (2, 3, 4) | S7–S10 | 4 / 4 |
| C. Foreign markets | S11–S12 | 2 / 2 |
| D. Track record and ops | S13–S14 | 0 / 2 |

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
| 0, 2, 3, 4 | sec-edgar (usfin) | `data/usfin.duckdb`: FRED `fred_observation_latest`, `fred_as_of(DATE)` (layers 0, 2); TIC `tic_observation_latest`, `/series/tic?country=…` (layer 3); US fundamentals (layer 4) | HTTP `?format=csv` from `usfin serve` (127.0.0.1:8660), because `serve` holds the DuckDB lock; read-only `ATTACH` when no lock is held |
| 0, 2 | bisfetcher | `warehouse.duckdb` (`$BISFETCHER_DB`): `series`, `observations`, `datasets` (contract block in its `PLAN.md`); `WS_EER` (layer 0), `WS_CBPOL` incl. BI rate `WS_CBPOL.M.ID`/`.D.ID`, `WS_CREDIT_GAP`, `WS_SPP`, `WS_DSR` (layer 2) | Read-only `ATTACH`, or its `serve` API while a refresh holds the lock. Done (S1–S13 on main); daily 07:30 refresh via `launchd/install.sh` |
| 1 | worldbankscape | `out/{SUBJECT}/{asset_class}.json` + `out/index.json` | Files (JSON Schema contract) |
| 2 | bps-looker | Postgres (`DATABASE_URL`) | Read-only role |
| 2 | ausdata | `warehouse.duckdb` | Read-only `ATTACH` |
| 2 | singstat (sgecon) | `data/sgecon.duckdb` | Read-only `ATTACH` |
| 2, 3 | dbnomics | `data/dbnomics.duckdb` (`$DBN_DB`): `series`, `observations`, `series_latest`, `series_status`; OECD CLI/BCI/CCI/CPI/rates, China `cn.*`, Eurozone (layer 2); `damodaran_erp`, `damodaran_crp`, `shiller` (layer 3). Ids and units in `docs/HANDOFF.md` | HTTP `?format=csv` from `dbn serve` (127.0.0.1:8770) first; its lock is mutual (a reader blocks `dbn refresh`), so a direct read opens, queries and closes |
| 2 | satudatascape | `data/satudata.db` (SQLite): data.go.id catalogue `packages`, `resources`, `tables` (extracted Parquet, grade A/B/C), `runs` (freshness); list in its `docs/PLAN.md` *Tables read by investment-assist*. Not on this Mac yet | `mode=ro` URI; doctor reports it missing until the file exists |
| 2, 3, 4 | jquantster | `data/jquantster.db` (SQLite): macro (layer 2), TSE investor flows (layer 3), prices, EPS, EDINET (layer 4) | DuckDB `sqlite` extension, read-only |
| 3 | idxscape | `data/idxscape.duckdb`: `stock_summary`, `broker_summary`, `fx_rate` (JISDOR), `sbn_ownership`, `corporate_action`; PHEI (J4 done 2026-10-22, migration 9): `igsyc_point` (as_of, tenor_y), `phei_bond_quote` (as_of, series_code, grp; never read a series as "the 10Y benchmark"), `credit_curve_point`, local use only (`docs/storage.md`). This Mac's copy lacks migration 9 until idxscape is pulled and loaded here | Read-only `ATTACH` |
| 3 | kseistat | `data/ksei.duckdb`: `v_market_composition`, `v_type_composition` | Read-only `ATTACH` |
| 3, 4 | idx-method | Fetcher only since 2026-10-14 (no books or screens; see its README, *Changes the parent must follow*). `store/data/stockbiter.db` (SQLite); `data/factors.json`, `consensus.json`, `composition.json`, `universe.json`, `sectors.json`, `special_boards.json`, `data/snapshots/<date>.json.gz`; `data/*_daily.csv`, `*_weekly.csv` (IHSG, LQ45, XIHD, IDX indices) **frozen at 2026-09-30, no longer updated since 2026-10-19: JCI needs another fetcher**; `cache/history/` (OHLC, value, net foreign flow), `cache/dividends/`, `cache/fundamentals/` | Read-only, files |
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
  cli.py        assist doctor | run | brief | regime | journal
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

- [ ] **S13 Paper tracking.** Each stance's implied allocation vs a fixed IDR 60/40 benchmark
  (60% JCI, 40% SBN index), marked weekly, segmented by model fingerprint.
- [ ] **S14 launchd + README.** Weekly brief and daily regime jobs; doctor in the brief header.

---

## Open questions

- Target weight bands per stance (e.g. overweight = benchmark + 10 pt): needs the user's
  risk limits and the benchmark choice confirmed.
- Which SBN index for the benchmark (the 40% leg): pick once the PHEI parser shows what's
  available.

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
