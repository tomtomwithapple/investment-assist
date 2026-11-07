# investment-assist — plan

The entry point that reads the sibling fetcher repos and turns their data into a **stance and an
entry plan per country × asset class** for an IDR-based investor. The decision flow it implements
is in `CLAUDE.md` (*Investment decision flow*); this plan is how it gets built.

---

## STATUS — read this first in a new session

**Last updated:** 2026-11-07 (**phase J done**: S41 P61-fingerprint-scope, the fingerprint hashes each rule module's AST without docstrings, so comments and formatting no longer segment the journal, and the paper track shows only cumulative returns below 12 scored weeks; S42 P62-rebalance-split, each stance's `portfolio` splits the gap into `rebalance_pt` (to the 48/32/20 benchmark) and `tilt_pt` (the model's call), schema 1.1.0, shown in the brief, `/portfolio`, `/stance` and Telegram, which now opens "Paper only, not an order"; live all three legs neutral, so IDN stocks −48.9pt, IDN bonds +30.2, USA stocks +20.0 are all rebalance, tilt 0; S43 F9-docs; model `sha256:b836b881ad37…` on main, no run since, so the next run opens one new journal segment; 1633 tests). Earlier: 2026-11-06 (S40 done, P60-paper-benchmark, **phase I done**: the paper benchmark is 48% JCI / 32% SBN leg / 20% US stocks in IDR (unhedged price index: Alpaca SPY × USD/IDR, JISDOR from 2026-10-22 spliced onto the MAS cross before it), from `stance.BENCHMARK_PCT`; the old 60/40 is reported beside it and still scores every segment journalled before S39; live 1 week scored (10-16, −7.7% vs −9.4% on 60/40), 3 stale on the IGSYC hole and the 11-06 mark). Earlier: 2026-11-06 (S39 done, P59-benchmark: whole-portfolio benchmark IDN stocks 48 / IDN bonds 32 / USA stocks 20; every target is benchmark + tilt, the three legs scaled pro rata to at most 100%, the rest cash; the other 46 stances target 0% outside the 80/20 mandate; live 45.7 / 30.5 / 23.8 = 100%, cash 0%; model 0.4.0, new journal segment). Earlier: 2026-11-06 (**phase H done**, S37 F8-ui-layers: the nav adds Regime, Signals, Portfolio and Flows; the overview banner links `/regime`, a stance's Drivers card links `/signals/<SUBJECT>` (only when that layer file exists) and its Portfolio card `/portfolio`; every page and its `.json` twin is 200 live and in the e2e test). **Phases A–D are done** (F4-ops); phase F is done up to S21 (F6-us-stocks): one undervalued list per market, IDN and USA, in `out/candidates/`. **Phase G is done** (F7-ui): `assist status` serves the output read-only on 127.0.0.1:8790 (`/` stance grid, `/stance/<SUBJECT>/<asset>`, `/candidates[/<MKT>]`, `/paper`, `/journal`, `/status`, each with a `.json` twin), and `./start.sh` goes from a checkout to those pages in one step (S29: sync, doctor, a run if out/ is stale, serve, open). S30 adds `/industries[/<id>]`: every IDN name against Stockbit's industry average and the sector median in valuation, dividend, profitability and solvency, charted per industry (`out/industries/IDN.json`, context only). S31 (top tier per industry) is built, P48–P50, but waits for its live run and replay verdict. **Phases H, I and J are done** (layer pages, the 48/32/20 benchmark, review quick fixes). S15 and S22 are open.

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
- It sends one Telegram summary a day.

Two launchd jobs are **installed and loaded** on this Mac (checked 2026-11-07; README,
*Scheduled jobs*):
- `com.tommy.investment-assist.weekly`: `assist run`, Monday 07:00 WIB.
- `com.tommy.investment-assist.regime`: `assist regime --check`, daily 07:00 WIB. It sends
  Telegram only on a regime or dollar change.

No stance has moved in phases B–D:
- With PHEI fresh here since 2026-10-26, both IDN rules now propose a call (bonds neutral, stocks underweight), but neither is applied: each placebo sample is still too small (P45-start).
- The foreign overrides and candidates are hand-set, so they move scores but not bands until they
  beat a placebo.

**Gap 2b closed 2026-11-06 (P51-jci-idxscape):** JCI now reads idxscape `index_daily`
COMPOSITE (nightly, 2021-10-01 on), stitched to idx-method's frozen CSV before that. Paper
tracking scores its first week (2026-10-09 → 10-16, benchmark −9.4%). PHEI capture now runs on
this Mac (idxscape, 2026-11-06), but IGSYC has a hole 2026-10-22 → 11-03 here; since P52 a week
whose mark falls in a capture gap is left unscored rather than priced on an old yield.

**Next up:** phase K (user, 2026-11-07, not yet written): G1, gate rules on a point-in-time
historical walk-forward with placebo instead of live journal months only (`MIN_N` = 10 live
months each side means no rule could pass before about 2028); G2, a home IDN regime from JCI
drawdown, IDX foreign flow z-score, JISDOR move and foreign SBN change (JCI fell 19% 10-06 →
11-05 while the global regime read neutral). Meanwhile let the jobs and this Mac's PHEI history
build a record; backfilling 10-22 → 11-03 from the Windows machine's raw captures stays deferred.
Open ops question: of the fetchers, only bisfetcher.refresh, dbnomics.refresh/serve,
worldbankscape.daily and idxscape.phei are launchd agents on this Mac; the other stores are fresh
but what refreshes them here is not traced.

| Phase | Slices | Done |
|---|---|---|
| A. Skeleton + base layers (0, 1, 5; S32: layer 5 reads trade documents) | S0–S6, S32 | 8 / 8 |
| B. Indonesia overrides and rules (2, 3, 4) | S7–S10 | 4 / 4 |
| C. Foreign markets | S11–S12 | 2 / 2 |
| D. Track record and ops | S13–S14 | 2 / 2 |
| E. Layer 4 refinements (S31: top tier per industry) | S15, S31 | 0 / 2 |
| F. Undervalued stocks, macro-weighted (IDN, then US, JP) | S16–S22 | 7 / 8 |
| G. Local UI view (read-only pages over `out/`, journal, paper) | S23–S30 | 8 / 8 |
| H. Layer pages (regime, signals, portfolio) | S33–S37 | 5 / 5 |
| I. Benchmark and portfolio limits (80% IDN / 20% US stocks) | S39–S40 | 2 / 2 |
| J. Review quick fixes (fingerprint scope, rebalance vs tilt, docs) | S41–S43 | 3 / 3 |

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
  This unblocks S15; no adapter reads them yet.

**Known bug (P21).** Entry levels are wrong for momentum names at fresh 3-year highs. For
example, BSML at 575 (its high) gets `entry_typical` 21: a −96% "typical correction" read from a
short, unadjusted history. DEWI reads −86%, giving 35. Until P21 bounds the correction (or uses
adjusted prices), treat `entry_typical` for those names as missing.

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

- [ ] **S15 Industry-relative value screen (IDN, layer 4).** Undervalued in any style, not a
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

- [ ] **S31 Top tier per industry (IDN, planned 2026-10-29).** A score from 0 to 100 for each
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
    Fundamentals are lagged by `screens.LAG_DAYS`. Membership is today's, back-filled and
    flagged; that is survivorship bias until idx-method V2 lands.
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
    (2026-10-29), so the live run waits for it. Tests use fixtures.
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

## Open questions

- ~~Target weight bands per stance~~: benchmark decided 2026-11-06 (80% IDN as 48 stocks / 32
  SBN, 20% US stocks; phase I). The ±5 pt tilt and S20a's 5% per-name cap are still the
  placeholders; confirm them once phase I runs.
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
