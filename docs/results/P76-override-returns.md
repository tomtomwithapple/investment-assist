# P76-override-returns (PLAN S58): forward returns per IDN asset on the override month ends

Date: 2026-11-09. Branch `phase-l`. Phase L choices 2 and 3 (accepted 2026-11-09). Heuristic, not
investment advice.

## What changed

- **`src/assist/override_history.py`** (plumbing, outside the model fingerprint):
  - `ReturnSources` (JCI, dbnomics, PHEI, the P65 USD/IDR splice; `default()` from
    `IdnSources`).
  - `idn_returns(src, today=, horizon=3)` gives `{asset: {(year, month): return}}`:
    - **stocks:** `history.stock_forward` on the stitched JCI (P51), month-end close to the
      close 3 complete months later (as P66);
    - **bonds:** `history.bond_forward` over `history.ten_year_months`. The OECD proxy's
      monthly averages are lagged one month (P74) and IGSYC closes are used as they stand.
      Nothing is priced across the 2025-01 → 2026-09 10Y hole;
    - **currency:** the rupiah against the dollar, USD/IDR(t) / USD/IDR(t+3) − 1 on the
      month-end closes of the P65 splice (`currency_forward`). A rupiah gain is positive.
  - Every return runs only between consecutive months (`history._forward` runs) and never
    from a month still running on `today` (`history._complete`). `history.py` is imported,
    not edited (it is in both rule fingerprints).
  - `with_returns(history, fwd)` joins them onto the rows (`OverrideRow.forward`, history
    schema 2, `horizon` kept). `return_coverage()` gives the first and last complete month
    with a return per asset.
  - `python -m assist.override_history --returns` prints the coverage. `--rows` adds each
    row's three returns.
- No gate, no verdict, no threshold. P17 and every rule module are unchanged.

## Tests (first, red → green)

`tests/test_override_history.py` has 6 new tests (24 in all):
- the currency return is positive when USD/IDR falls (15,000 → 14,000: +7.1%);
- the currency return never crosses a missing month;
- nothing is priced from a month still running (2019-12-15: no September return yet;
  2020-01-01: there is one);
- the bonds return stops at a 10Y hole, with the averages lagged a month (the call on M runs
  from M+1's average to M+4's; flat yield = carry only);
- IGSYC closes are priced on their own dates, not lagged;
- returns join the rows, round trip through JSON, and `return_coverage` ends where the prices
  do.

Full suite: 1855 passed, 1 skipped. `ruff check .` is clean.

## Live (2026-11-09, real stores read-only)

Complete months (every P17 component) with a 3-month forward return:

| Asset | First | Last | Months | Stride-3 windows (about) |
|---|---|---|---|---|
| Stocks (JCI) | 2017-07 | 2026-07 | 106 | 36 |
| Bonds (10Y proxy, IGSYC) | 2017-07 | 2024-08 | 83 | 28 |
| Currency (USD/IDR splice) | 2017-07 | 2026-07 | 106 | 36 |

- The window matches choice 5. The bonds side ends 2024-08: its 3-month return needs the
  2024-12 OECD average (lagged to 2024-11-30), and nothing follows until IGSYC in 2026-10.
- The three complete months 2024-02 → 04 (the CPI hole) carry returns, but they are not
  complete until S61b. S59's window counts complete months only (choice 4).
- 2026-07-31 reads stocks −18.9%, bonds none, currency −0.4%. The JCI fell from July to
  October 2026, as the home regime's risk_off reading in phase K showed.
