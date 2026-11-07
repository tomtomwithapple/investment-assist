# P63-us-universe (PLAN S44): USA universe over HTTP

Date: 2026-11-07. Heuristic, not investment advice.

## Root cause (confirmed live)

The 2026-11-06 run wrote `out/candidates/USA.json` with pool 0 in both styles and
`sec-edgar (locked): universe`. The chain:

1. `UsStocks()` used `Usfin`'s default 5 s timeout (`doctor.HTTP_TIMEOUT`). `usfin serve` answers
   `/prices/universe?status=active&matched=1` in 19–22 s (7 177 rows, ~1 MB).
2. `base.http_csv` mapped every `httpx.TransportError`, `ReadTimeout` included, to `missing`. So
   `Usfin.fetch` took the server to be down and fell back to the read-only ATTACH.
3. `usfin serve` opens the store for each request (`store.session` in its `web/app.py`), not for
   its whole life. A read-only ATTACH works when serve is idle: checked live, it attached while
   serve was up. But after the timeout serve was still running the universe query and holding the
   lock, so the ATTACH could only fail with `locked`.

Fixing the timeout alone would not have been enough. The next step read bars one symbol at a
time over `/prices`, at about 11 s each (measured on A, AA, AAAU, AAC, AAC.U). For the 6 009 names
with net income facts that is about 18 h. Over the ATTACH it is 0.45 s a symbol, about 45 min.

## Fix

- **`base.http_csv`**: a read, write or pool timeout means the server is up but busy. It now
  raises `locked`, with the detail "ReadTimeout, timed out after N s", the same as a 503. A
  `ConnectTimeout` or a refused connection stays `missing`, and the file fallback still runs.
  No new reason was added: `locked` was already in `REASONS`, the brief's problem order, status
  `BAD` and doctor. Doctor's own probe (`doctor.http_newest`) does not go through `http_csv`, so
  it is unchanged. dbnomics' `fetch` gets the same behaviour for free.
- **One timeout constant**: `sources.usfin.US_HTTP_TIMEOUT = 60.0`. When `UsStocks` builds its
  own `Usfin` from the config, it uses this timeout, so `us_stocks.load()` (called by
  `undervalued.gather_live_usa`) and paper's SPY leg share it. `paper.py` now imports the constant
  instead of defining its own 60.0.
- **One bulk bar read**: `UsStocks.bars_many(symbols, min_value, min_sessions, each)` runs one
  query over the ATTACH: `alpaca_bar_adjusted` joined to `alpaca_security_symbol` (the security
  each symbol names today) and to the newest `alpaca_bar` version for volume. It streams the rows
  with `fetchmany` and groups them per symbol. `usfin serve` has no bulk route (its routes, read
  in `../sec-edgar/src/usfin/web/app.py`, are `/prices` for one symbol and `/edgar/<cik>`, whose
  facts are picked by frame, not point in time). So this read goes to the file, as `facts_many`
  already did.
  - Checked live against `bars(sym)` on 33 symbols (25 random, plus META, AAPL, GOOGL, BRK.B and
    the first diffs): every row has the same date, symbol, close and volume. The factors differ
    by at most 6.7e-16 relative (float product order).
- **Liquidity floor, exact**: `us_stocks.liquid_floor(cfg)` returns (US$20m, 10 sessions).
  `median_value` judges a window of at least `med_sessions // 3` = 20 sessions, and a median of
  at least v needs half the window at or above v. A name with fewer than 10 sessions of close ×
  volume ≥ US$20m therefore fails the liquidity gate on every date, live and in the replay. Its
  bars are not read, and no ranking or verdict changes. The floor counts over all dates, so it
  is looser than any single window. A test checks it against `median_value`.
- `load(..., cfg=CONFIG)` builds each name's engine inputs as its bars stream in (`each`), so
  raw bars are never all held at once.
- No decision rule, band, tilt, benchmark, screen threshold or ladder changed.

## Tests (1633 → 1646 pass; ruff clean)

- `tests/sources/test_usfin_fetch.py` (new, 6 tests): a ReadTimeout gives `locked` with "timed out
  after 7 s"; ConnectError and ConnectTimeout give `missing`; `fetch` after a ReadTimeout does not
  call the file path, while `fetch` with the server down still does; `US_HTTP_TIMEOUT` ≥ 60.
- `tests/test_us_stocks.py` (+7): `load()` with no source sends `/prices/universe` with read
  timeout 60 (from the MockTransport request extensions); `bars_many` equals `bars` per symbol;
  the liquidity floor; bulk bars go to the file; `load` makes no `/prices` GET; the 4-session
  fixture names are skipped under the live floor. `test_load_reads_the_fixture_store` now passes
  `cfg=LOOSE` (a 3-session median), because the fixture has only 4 sessions.
- Red first, for the right reasons: `'missing' == 'locked'`, then no `US_HTTP_TIMEOUT`, no
  `bars_many`, no `liquid_floor`, and `load()` taking no `cfg`. The ConnectError fallback test
  passed before the change, as it should.

## Live (main checkout, `uv run assist run --no-send`, 2026-11-07)

| | before (11-06) | after |
|---|---|---|
| sec-edgar HTTP calls in the USA step | 1 (timed out) | **1** (`/prices/universe`), plus 2 ATTACHes (facts, bars) |
| universe | 0 (locked) | **7 177** listings (HTTP, 18.8–22 s) |
| XBRL facts | not read | 6 024 CIKs over the ATTACH, 18.4 s |
| names with net income facts | – | 6 009 |
| bars read | 0 | **3 589** names past the floor, **7 587 023** rows, one query (~35 s) |
| `us_stocks.load` | – | 94–100 s |
| both styles (replay + live ranking) | – | dividend 18.0 s, GARP 21.4 s |
| USA step alone (load + regime + hurdles + both styles) | – | **151 s**, peak RSS 7.0 GB |
| `assist run --no-send` wall time | ~2 m 20 s (earlier runs) | **7 m 23 s** (443 s), peak RSS 7.4 GB |
| USA stale_inputs | `sec-edgar (locked): universe`, no SIC | **only** the no-SIC line |

Measured alone, the USA step adds about 2.5 min. The full run grew by about 5 min. The other
~2.5 min is not attributed. Paging under the 7 GB peak on this 16 GB Mac is a likely cause, but it
was not measured.

**Pools** (`out/candidates/USA.json`, bars 2026-11-06, hurdle 14.87% in IDR, IDN binding):

- **dividend_value**: pool **576**, 30 replay quarters. The verdict **fails** (t −1.42 below 2.0),
  so the list names **0** rows. Rejects: mktcap 1 750, no dividend 590, no price 245, payout 125,
  liquidity 115, no earnings 92, cfo cover 42, paid years 35, cut 18, no recent session 1. Top 5 by
  margin over both hurdles: INSW +4.60pt, WU +0.85, ORI +0.11, OMF −0.86, VZ −2.22.
- **garp**: pool **370**, 42 quarters. The verdict **fails** (t 1.70 below 2.0), so **0** rows.
  Top 5 by gap: UDR 52.9pt (margin +8.34), FIX 42.7 (+2.76), MU 39.1 (+8.05), PLMR 34.2 (+3.59),
  VRT 34.1 (+0.32).
- The USA budget is IDR 11,083,085, all unspent (no names). The tilt does not apply (S16 is IDN
  only).

The list is no longer empty for lack of data. It names no one because neither replay beats its
placebo, which is the rule working as built.

**Brief, rebalance vs tilt** (`data/briefs/2026-11-07.md`):

- IDN stocks neutral 96.9% → 48%: −48.9pt trim over 3 tranches; −48.9pt = −48.9pt rebalance to
  benchmark, +0.0pt tilt.
- IDN bonds neutral 1.8% → 32%: +30.2pt over 3 tranches; +30.2pt rebalance, +0.0pt tilt.
- USA stocks neutral 0% → 20%: +20.0pt over 3 tranches; +20.0pt rebalance, +0.0pt tilt.
- "Rebalance vs tilt: IDN stocks -48.9pt rebalance, +0.0pt tilt; IDN bonds +30.2pt rebalance,
  +0.0pt tilt; USA stocks +20.0pt rebalance, +0.0pt tilt."

New model segment `sha256:8c6a886f278d…` (us_stocks.py sits under `candidates/`). Telegram was
not sent, and `ASSIST_NOTIFY_STATE` was not set.

## Notes and gaps

- **No SIC (sec-edgar fetcher gap, not fixed here):** `edgar_company` has no SIC code, so there
  are no US peer groups and every name is its own sector bucket. The stale input line stays.
- **Lock window:** the facts and bars ATTACHes hold a shared lock on `usfin.duckdb` for about
  18 s and about 35 s. A serve request or serve-scheduled job in that window waits (serve's
  `store.session(wait=…)`) or answers 503. If a job is writing when we ATTACH, the read fails as
  `locked`: a stale input, never a crash.
- **Memory:** about 7 GB peak. The retained engine inputs (7.6 M bars plus their values) are
  inherent to the per-name engines. Lowering this would mean narrowing the replay universe, which
  is a methodology change and out of scope.

### Files outside `owns`

- `src/assist/paper.py`: imports `US_HTTP_TIMEOUT` from `sources.usfin` instead of defining 60.0.
- `tests/fixtures/usfin_stocks/schema.sql`: stand-in views `alpaca_bar_adjusted` and
  `alpaca_security_symbol` over `fixture_adjusted`, for the bulk query.
- `tests/sources/test_usfin_fetch.py`: new. It matches `tests/sources/test_usfin*.py`, so it is
  inside `owns`.
- Docs: PLAN.md (S44 ticked, phase J 4/4, Progress row) and README.md (data-gap line).
