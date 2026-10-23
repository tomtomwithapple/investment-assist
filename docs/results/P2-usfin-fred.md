# P2-usfin-fred — PLAN S2: FRED adapter (sec-edgar / usfin)

`src/assist/sources/usfin.py`: `FredSource` (tidy rows) on top of `Usfin`, the
HTTP-or-ATTACH helper that P15 (TIC) reuses. HTTP `/series/fred/<id>?format=csv[&as_of=]` when
`usfin serve` answers on 127.0.0.1:8660, else a read-only ATTACH of `data/usfin.duckdb`. A busy
server (503) is `locked`, not a fallback. Current values come from `fred_observation_latest`;
point in time comes from `fred_as_of(DATE)` (23:59:59 New York that day, as in sec-edgar).
`Row.as_of` is the FRED vintage (`realtime_start`). Every query filters by series in SQL.
`net_liquidity(rows)` = WALCL − WTREGEN − RRPONTSYD×1000 in $ mn, on WALCL dates, using the last
known TGA and RRP values at or before each date.

## Checked against the sibling (2026-10-23)

- sec-edgar git log up to `ed08075` (S44). FRED schema in `migrations/020_fred.sql`, CSV route in
  `web/series.py` `fred_rows`, cell format in `web/tables.py`. These match CLAUDE.md, with no
  disagreement on tables, units or the net-liquidity formula. The `config/fred.yaml` comment and
  README also give RRP in $ bn and WALCL/WTREGEN in $ mn.
- **Finding:** `fred_as_of` is a macro that calls `bls_as_of_utc` and names `fred_observation`
  unqualified. Through `ATTACH ... AS usfin` it fails ("Table with name … does not exist")
  unless the attached database is selected first. The adapter runs `USE usfin` after the ATTACH.
- `usfin serve` also runs the fetch scheduler and opens the store read-write, so this slice
  never starts it.

## Tests

`uv run pytest -q tests/sources/test_usfin_fred.py`: 22 passed. The fixture
(`tests/fixtures/usfin/`) is sec-edgar's FRED DDL plus 19 observation versions (revisions, a NULL,
a New York day-boundary revision). The fake `serve` (httpx MockTransport) answers from the same
file with sec-edgar's SQL and CSV format. HTTP rows == ATTACH rows for latest, two `as_of` dates,
and with or without a date window. Full suite: 102 passed, `ruff check .` clean.

## Live run (2026-10-23, read-only)

- **HTTP path: not available.** Nothing listens on 127.0.0.1:8660 on this Mac (ConnectError), so
  `rows()` fell back to ATTACH as designed. The HTTP path is proven only against the fixture.
  Re-run the live check on the jobs Mac, where `serve` runs.
- **ATTACH path:** all 25 layer-0 series in CLAUDE.md load. 159,682 rows in 0.4 s (latest);
  `fred_as_of(2026-01-15)` gives 156,032 rows, 25 series, in 0.3 s. NFCI alone takes 0.03 s
  (2,909 dates out of ~930k stored versions, so filtering by series is effective).
- **This Mac's store is stale:** file mtime 2026-10-14; newest dates are 2026-10-13 (daily) and
  2026-10-02 (NFCI, STLFSI4). The jobs Mac holds the current copy.

| Series | Dates | First | Last | Last value | Vintage |
|---|---:|---|---|---:|---|
| VIXCLS | 9,595 | 1990-01-02 | 2026-10-12 | 15.21 | 2026-10-12 |
| BAMLH0A0HYM2 | 796 | 2023-10-10 | 2026-10-12 | 3.11 | 2026-10-12 |
| T10Y2Y | 13,141 | 1976-06-01 | 2026-10-13 | 0.42 | 2026-10-13 |
| WALCL | 1,243 | 2002-12-18 | 2026-10-07 | 6,747,560 | 2026-10-08 |
| M2SL | 812 | 1959-01-01 | 2026-08-01 | 23,342.8 | 2026-09-22 |
| DFF | 26,402 | 1954-07-01 | 2026-10-12 | 3.88 | 2026-10-13 |
| SOFR | 2,224 | 2018-04-03 | 2026-10-09 | 3.87 | 2026-10-13 |
| DGS2 | 13,139 | 1976-06-01 | 2026-10-09 | 4.8 | 2026-10-13 |
| DGS10 | 16,899 | 1962-01-02 | 2026-10-09 | 5.24 | 2026-10-13 |
| DTWEXBGS | 5,420 | 2006-01-02 | 2026-10-09 | 121.6023 | 2026-10-13 |
| DFII10 | 6,202 | 2003-01-02 | 2026-10-09 | 2.91 | 2026-10-13 |
| NFCI | 2,909 | 1971-01-08 | 2026-10-02 | −0.494 | 2026-10-07 |
| DCOILBRENTEU | 10,275 | 1987-05-20 | 2026-10-06 | 125.44 | 2026-10-07 |
| WTREGEN | 2,127 | 1986-01-08 | 2026-10-07 | 880,253 | 2026-10-08 |
| RRPONTSYD | 6,178 | 2003-02-07 | 2026-10-13 | 0.275 | 2026-10-13 |
| BAMLEMCBPIOAS | 796 | 2023-10-10 | 2026-10-12 | 1.55 | 2026-10-12 |
| BAMLEMHBHYCRPIOAS | 796 | 2023-10-10 | 2026-10-12 | 3.3 | 2026-10-12 |
| GDPNOW | 61 | 2011-07-01 | 2026-07-01 | 3.5862 | 2026-10-08 |
| WEI | 979 | 2008-01-05 | 2026-10-03 | 2.71 | 2026-10-08 |
| THREEFYTP10 | 9,594 | 1990-01-02 | 2026-10-09 | 1.0729 | 2026-10-13 |
| T5YIE | 6,204 | 2003-01-02 | 2026-10-13 | 2.33 | 2026-10-13 |
| T10YIE | 6,204 | 2003-01-02 | 2026-10-13 | 2.33 | 2026-10-13 |
| STLFSI4 | 1,710 | 1993-12-31 | 2026-10-02 | −0.4681 | 2026-10-07 |
| USEPUINDXD | 15,260 | 1985-01-01 | 2026-10-12 | 155.29 | 2026-10-13 |
| CCUSMA02IDM618N | 716 | 1967-01-01 | 2026-08-01 | 17,844 | 2026-09-15 |

Note: BAMLH0A0HYM2 starts at 2023-10-10 like the EM OAS series; FRED now keeps only about 3 years
of ICE data for US HY too. The regime rule's HY OAS 13-week change is fine, but any backtest
before 2023-10 has no HY OAS.

Net liquidity: 1,235 weekly values. The latest is **5,864,969 $ mn on 2026-10-07** (vintage
2026-10-08), which matches sec-edgar's own check (≈ $5,865 bn on 2026-10-07). It was 5,782,818 on
2026-09-30.
