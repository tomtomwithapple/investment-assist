# P39-us-stocks — PLAN S21: US single stocks

Live run 2026-10-27, read-only against `../sec-edgar/data/usfin.duckdb` (main at 51c36ec) and
`usfin serve` on 127.0.0.1:8660.

## What was built

- `src/assist/sources/usfin_stocks.py`: the universe (`/prices/universe?status=active&matched=1`,
  or the same `alpaca_universe` → `edgar_company` join on `ticker_norm`, lowest CIK), bars for one
  symbol at a time (`/prices?symbol=`, or `alpaca_bar_adjusted_lookup(sym)` joined to the newest
  `alpaca_bar` for volume; never the whole view), and XBRL facts per CIK from `xbrl_as_of(d)`.
  HTTP and ATTACH give identical rows (tested).
- `src/assist/candidates/us_stocks.py`: the P36 dividend and P37 GARP engines, imported
  unchanged, run on US inputs:
  - **Bars**: split-adjusted price. Mktcap is the traded close × the last share count filed by
    that day, rescaled for later splits.
  - **Dividends**: read from the `tr_factor / split_factor` steps, which are Alpaca's cash
    dividends.
  - **Fundamentals**: one row per 10-K/10-Q, available on its filed date. TTM = year to date +
    prior fiscal year − prior year to date. Period ends are snapped to month ends, which fixes
    52/53-week fiscal years.
  - **Hurdles**: margins against the P34 USA hurdle in unhedged IDR and against the IDN hurdle;
    the margin is the lower of the two. GARP discounts at the USD bar, which is the higher of the
    two hurdles converted to USD.
  - **Gates**: US$2bn mktcap and US$20m median daily value (60 sessions), applied both live and
    point in time in the replay.
  - **Replay**: quarter ends, scored on P36's 3-month forward return, with P36's placebo.
- `tests/test_us_stocks.py`: 27 tests. The fixtures in `tests/fixtures/usfin_stocks/` use
  sec-edgar's DDL, with a stand-in for the security and adjusted-bar macros.

## Live numbers

| | |
|---|---|
| Universe (listed, joined to EDGAR) | **0**: `alpaca_bar`, `alpaca_asset_history` and `alpaca_corp_action` hold 0 rows in this store |
| Names with bars | 0 |
| Dividend verdict | not passed: insufficient sample (0 quarters) |
| GARP verdict | not passed: insufficient sample (0 quarters) |
| Top 10 per style | none (no priced name) |
| USA hurdle (IDR) | 8.92% (fx move −0.74%, adverse 5th pct) |
| IDN hurdle (IDR) | 13.61% |
| USD bar | **14.45%**, set by the IDN hurdle: a US name has to earn this in USD to beat the IDN alternative in IDR |
| XBRL facts read | 100 CIKs in 0.37 s (90,755 facts); the full ~8k filers take about 30 s |

A point-in-time spot check of the XBRL TTM build, newest quarter each:
- **AAPL**: NI 128.9bn, CFO 146.7bn, equity 107.5bn (2026-06-30, filed 2026-07-31). 69
  quarters since 2009.
- **MSFT**: NI 133.8bn, CFO 182.9bn.
- **JPM**: marked as a bank (it files `Deposits`). NI 65.0bn; CFO −162.5bn, which is why banks
  skip the CFO cover check.
- **KO**: NI 13.7bn, CFO 14.6bn. Its 2025 CFO of 7.4–7.6bn reflects the fairlife and IRS
  payments.
- **JNJ**: NI 16.1bn (2026-09-30, filed 2026-10-21).

## Findings (the sibling wins where it disagrees with the slice notes)

1. **No Alpaca data in this Mac's store.** Migrations 022–028 are applied, but the tables are
   empty, and `/prices/universe` returns only its header. S13's backfill figures (25.1M bars,
   648 MB) belong to a different DB file. The full and daily backfills have to run on the main
   checkout before S21 can rank anything. The brief shows this as the stale input
   `sec-edgar universe empty`.
2. **There is no SIC in sec-edgar.** `edgar_company` is (cik, ticker, title, ticker_norm, active,
   updated_at), and no migration or route carries SIC. So there are no peer groups: every name is
   its own sector bucket (journalled in `stale_inputs`). Banks are found by a `Deposits` fact
   instead. **Ask to sec-edgar:** store SIC from the submissions JSON (`sic`,
   `sicDescription`).
3. **There is no "statement view".** The slice notes name one, but sec-edgar has only `xbrl_fact`
   and `xbrl_as_of`. TTM is built here from the raw facts.
4. **`usfin serve` has no point-in-time facts route.** `/screen` and `/edgar/<cik>` choose facts
   by `frame`, which SEC moves to the newest filing. Facts therefore come only from the read-only
   ATTACH. The adapter tries HTTP first and falls back to the file. On this Mac the ATTACH
   succeeded while serve was running, because serve opens a session per request. When the file
   is locked, this is reported as stale and no name is judged.
5. **Survivorship.** sec-edgar joins delisted symbols to no CIK, so the replay runs on today's
   listed names. Any verdict will be biased upwards; this is stated in `replay_basis`.
6. **Dividends come from Alpaca's adjustment factors, not from XBRL.** XBRL's
   `CommonStockDividendsPerShareDeclared` is read but not used, because it has no ex-date. Alpaca
   dividends include specials.
7. **Run time once bars exist.** Bars are read one symbol at a time over HTTP, at about 0.2–0.5 s
   each (S13 lookups). Only names with net income facts are read (about 7k), so a full live run
   is roughly 30–60 minutes. `limit=` or `symbols=` cap it.

## Hand-set values (in the fingerprint)

| Setting | Value |
|---|---|
| `min_mktcap` | US$2bn |
| `min_med_value` | US$20m, over 60 sessions |
| `g_cap_pt` / `gdp_pt` | 4.5 (US nominal GDP growth) |
| GARP `replay_hurdle_pt` | 10.0, used only when no USD bar exists |
| `top` | 10 |

Everything else uses the P36/P37 configs.
