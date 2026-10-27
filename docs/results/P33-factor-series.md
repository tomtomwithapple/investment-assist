# P33-factor-series — idx-method `factor_series` adapter (live run 2026-10-27)

`src/assist/sources/idxmethod_series.py` reads `../idx-method/store/data/stockbiter.db`
READ-ONLY (`sqlite_ro`). The db file was not modified (size and mtime 09:00 unchanged); only
the `-shm` mtime moved, which any WAL reader does.

## Sibling checked first

- idx-method HEAD `71ef6ed` ("Every root fetch also writes the store"). README *Changes the
  parent must follow* has nothing on `factor_series`. PLAN *Valuation history for
  investment-assist*: V1 (daily pe/pbv/ps/ev_ebit/ev_ebitda), V2 (membership) and **V3 (TTM
  steps on period end or filing) are all still open**, so the lag stays
  `screens.LAG_DAYS` = 120 days after period end.
- Real schema: `factor_series(freq, symbol, item, date, value)`, PK (freq, symbol, item, date),
  `freq` in `daily | quarterly`. The value column is untyped (integers for IDR amounts, reals for
  `roa`/`roce` in %). `factor_universe(symbol, name, sector, status, delisted)`.
  `dividends(symbol, seq, ex, value, ccy)` is present, so the `cache/dividends` fallback is
  not used on this Mac.

## Findings that differ from the slice notes

- **Quarterly rows are not all quarter ends.** Every symbol also has a row dated on the pull
  date (2026-10-26, 8,885 rows) that repeats the latest quarter. ITMA also has a run of
  daily-dated "quarterly" rows from 2019-12-10 to 2020-01-08. Both are dropped: only `03-31`,
  `06-30`, `09-30` and `12-31` count as periods. Without this, the pull-date echo would become
  "available" 120 days after the pull and repeat the latest quarter. That is why `span()`
  shows quarterly items ending on 2026-10-26, while the newest real period is 2026-06-30.
- **Prices look split-adjusted.** BBCA is 3,100 on 2016-12-30; it traded near 15,500 before
  its 1:5 split in 2021. `mktcap` is the real market cap (382T IDR), so multiples are
  unaffected.

## Counts

- Symbols with a series: **1,005**. `factor_universe`: 1,009 rows, **46 delisted** (kept).
- Quarterly fundamentals after the quarter-end filter: **991 symbols, 32,423 quarters**.
- Dividends: **607 symbols, 5,068 rows** (table).

| item | freq | symbols | first | last |
|---|---|---:|---|---|
| price | daily | 1,005 | 2016-10-26 | 2026-10-26 |
| mktcap | daily | 996 | 2016-10-27 | 2026-10-26 |
| cfo_ttm | quarterly | 991 | 2016-12-31 | 2026-10-26* |
| equity | quarterly | 966 | 2016-12-31 | 2026-10-26* |
| net_debt | quarterly | 989 | 2016-12-31 | 2026-10-26* |
| ni_ttm | quarterly | 991 | 2016-12-31 | 2026-10-26* |
| op_income_ttm | quarterly | 989 | 2016-12-31 | 2026-10-26* |
| roa | quarterly | 991 | 2016-12-31 | 2026-10-26* |
| roce | quarterly | 989 | 2016-12-31 | 2026-10-26* |
| total_assets | quarterly | 990 | 2016-12-31 | 2026-10-26* |
| total_debt | quarterly | 989 | 2016-12-31 | 2026-10-26* |

\* The pull-date echo, as stored. The adapter's last period is 2026-06-30.

## Point-in-time multiples

On 2026-10-26, from the latest quarter available by then (2026-03-31, since Q2 2026 becomes
available on 2026-10-28):

| name | price | mktcap (IDR T) | period | PE | PBV | P/CFO | EV/EBIT |
|---|---:|---:|---|---:|---:|---:|---:|
| BBCA | 4,940 | 609.0 | 2026-03-31 | 10.49 | 2.35 | 6.75 | 8.14 |
| TLKM | 2,250 | 222.9 | 2026-03-31 | 13.42 | 1.43 | 3.46 | 7.60 |
| ADRO | 2,450 | 70.6 | 2026-03-31 | 8.52 | 0.77 | 5.92 | 7.14 |

Quarter ends (`multiples_series`, last four):

| name | date | period used | PE | PBV | P/CFO | EV/EBIT |
|---|---|---|---:|---:|---:|---:|
| BBCA | 2025-12-31 | 2025-06-30 | 17.47 | 3.80 | 20.78 | 13.76 |
| BBCA | 2026-03-31 | 2025-09-30 | 13.91 | 2.87 | 17.45 | 10.92 |
| BBCA | 2026-06-30 | 2025-12-31 | 11.89 | 2.43 | 8.83 | 9.25 |
| BBCA | 2026-09-30 | 2026-03-31 | 12.90 | 2.89 | 8.30 | 10.09 |
| TLKM | 2025-12-31 | 2025-06-30 | 16.33 | 2.32 | 5.35 | 10.14 |
| TLKM | 2026-03-31 | 2025-09-30 | 14.78 | 1.96 | 4.65 | 9.15 |
| TLKM | 2026-06-30 | 2025-12-31 | 13.07 | 1.55 | 3.65 | 7.89 |
| TLKM | 2026-09-30 | 2026-03-31 | 13.66 | 1.46 | 3.52 | 7.72 |
| ADRO | 2025-12-31 | 2025-06-30 | 4.26 | 0.66 | 2.53 | 5.60 |
| ADRO | 2026-03-31 | 2025-09-30 | 9.36 | 0.88 | 4.83 | 9.13 |
| ADRO | 2026-06-30 | 2025-12-31 | 9.00 | 0.79 | 6.69 | 7.39 |
| ADRO | 2026-09-30 | 2026-03-31 | 8.45 | 0.76 | 5.88 | 7.08 |

Each series starts at 2016-12-31 with no multiples, because the first quarter (2016-12-31)
becomes available on 2017-04-30. For banks such as BBCA, EV/EBIT treats `net_debt` as a
non-bank figure, so read it with care. The whole live run took about 5 s.

## Not here yet

- PS and EV/EBITDA: the store has no revenue or D&A until idx-method V1.
- The 120-day lag is a placeholder until idx-method V3 records whether the TTM steps on
  period end or filing.
