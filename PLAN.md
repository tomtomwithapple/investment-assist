# investment-assist — plan

The entry point that reads the sibling fetcher repos and turns their data into a **stance and an
entry plan per country × asset class** for an IDR-based investor. The decision flow it implements
is in `CLAUDE.md` (*Investment decision flow*); this plan is how it gets built.

---

## STATUS — read this first in a new session

**Last updated:** 2026-10-14, sources synced with `CLAUDE.md` (TIC, satudatascape, layer-0 series), nothing built. **Next up:** S0.

| Phase | Slices | Done |
|---|---|---|
| A. Skeleton + base layers (0, 1, 5) | S0–S6 | 0 / 7 |
| B. Indonesia overrides and rules (2, 3, 4) | S7–S10 | 0 / 4 |
| C. Foreign markets | S11–S12 | 0 / 2 |
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
| 2 | satudatascape | No store yet (`README.md`, `docs/`, `scripts/` only) | Planned; doctor reports it missing until a store exists |
| 2, 3, 4 | jquantster | `data/jquantster.db` (SQLite): macro (layer 2), TSE investor flows (layer 3), prices, EPS, EDINET (layer 4) | DuckDB `sqlite` extension, read-only |
| 3 | idxscape | `data/idxscape.duckdb`: `stock_summary`, `broker_summary`, `fx_rate` (JISDOR), `sbn_ownership`, `corporate_action`; PHEI curve after idxscape J4 | Read-only `ATTACH` |
| 3 | kseistat | `data/ksei.duckdb`: `v_market_composition`, `v_type_composition` | Read-only `ATTACH` |
| 4 | idx-method | `store/data/stockbiter.db` (SQLite), `data/*.json`, paper books | Read-only, files |
| 4 | openkrx | Postgres | Read-only role (phase C) |
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

- [ ] **S0 Skeleton + doctor.** uv project, `assist` CLI, `config/sources.yaml`, socket guard.
  `assist doctor` lists each source: present / missing / locked / newest date, never fails the run.
  *Done when:* live doctor shows all 14 sources with their newest data date (satudatascape
  reported missing until it has a store).
- [ ] **S1 Adapter contract + worldbankscape.** `Source` protocol → tidy rows. worldbankscape
  adapter reads `out/` and validates against its schema. *Done when:* live run loads every
  country × asset score with its confidence and flags.
- [ ] **S2 FRED adapter (usfin).** CSV over HTTP when `serve` is up, read-only `ATTACH` otherwise;
  same rows either way (one test asserts it). Reads `fred_observation_latest`, and `fred_as_of`
  for backtests. *Done when:* every layer-0 series listed in `CLAUDE.md` (25 today; `fred.yaml`
  holds 34 incl. layer-2 macro) loads live by both paths.
- [ ] **S3 Regime (layer 0).** Hand-set rule on VIX level, HY OAS 13-week change, DTWEXBGS 13-week
  change, DFII10, NFCI (deliberately small; net liquidity, EM OAS, term premium and STLFSI4 are
  candidates to add only if they beat the placebo) → `risk_on | neutral | risk_off` + dollar direction. Placebo: the same rule
  on shuffled dates. Walk-forward test: does `risk_off` precede weaker JCI and IDR returns
  (JCI from idx-method, IDR from JISDOR)? *Done when:* verdict and t-stat recorded here, with the
  control.
- [ ] **S4 Portfolio (layer 5).** financer `holdings` latest `as_of` per account → weights by
  country × asset class. Mapping: IDX tickers → IDN stocks; SBN/ORI/SR/FR codes → IDN bonds;
  RDN/bank cash → IDR cash; anything unmapped is listed, not guessed. *Done when:* live weights
  add up to 100% and match the brokers' statement totals.
- [ ] **S5 Stance v0 (layers 0 + 1 + 5).** `schema/stance.schema.json`; stance from the layer-1
  score, shifted by the regime; target weight band per stance; delta vs current weight; entry
  style (`lump | ladder`, ladder when `risk_off`). Journal every run. *Done when:* `assist run`
  writes valid JSON for every in-scope subject and a rerun with unchanged inputs writes identical
  files.
- [ ] **S6 Brief + Telegram.** Markdown brief (regime, stance table, changes since last run,
  stale inputs, disclaimer); Telegram summary; same never-fail and send-once rules as idx-method.
  *Done when:* a live brief is sent and a second send the same day is skipped.

### Phase B — Indonesia

- [ ] **S7 IDN overrides (layer 2).** bps-looker CPI, trade and GDP (satudatascape once it has a store); BI rate from bisfetcher
  `WS_CBPOL.M.ID` (worldbankscape's BIS series until bisfetcher has data). Momentum shifts the layer-1 score by at most ±10 points.
- [ ] **S8 IDN market signals (layer 3).** idxscape foreign net flow (IDR and USD via JISDOR),
  DJPPR non-resident SBN holdings change; kseistat foreign share trend; sec-edgar TIC US investor
  net purchases of Indonesian equities and bonds (`us_*_42218`).
- [ ] **S9 IDN bonds rule.** Real yield, curve slope, foreign SBN flow, JISDOR trend, regime.
  **Blocked on idxscape J4 (PHEI parser).**
- [ ] **S10 IDN stocks rule + candidates (layer 4).** JCI earnings yield vs SBN yield (as in
  `idx-method/dividend_vs_bonds.py`); candidates read from the idx-method paper books, not
  recomputed.

### Phase C — foreign markets

- [ ] **S11 Foreign overrides.** sec-edgar (BLS, FRED macro, TIC foreign holdings and net purchases
  of US securities), jquantster (macro, TSE investor flows), singstat, ausdata,
  worldbankscape ECB/BIS for the EU. Returns converted to IDR, hedged vs unhedged.
- [ ] **S12 Foreign candidates.** Index-level only at first (US, JP, AU, SG); openkrx for KR/TW.

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

| Slice | Status | Date | Commit | Tests | Live result |
|---|---|---|---|---|---|
| — | — | — | — | — | — |
