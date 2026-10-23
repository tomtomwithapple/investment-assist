# P28-overrides-foreign — PLAN S11: foreign overrides (layer 2) in IDR terms

`src/assist/layers/overrides_foreign.py`: `foreign_overrides(as_of, sources=None)` returns
`ForeignOverrides`, which holds one `MarketOverrides` each for USA, JPN, EMU (euro area), AUS and SGP.
Each market has:

- one `Override` per asset (stocks, bonds, currency). This is the same type, ±10 cap and
  `apply` as the IDN layer in `overrides.py`.
- `components`, the uncapped `raw` sums, `stale_inputs`, `sources` and `gaps`.
- `IdrTerms`: IDR per local unit, its 3- and 12-month change, and the 1-year hedge carry from
  `assist.fx.hedge_carry` (BI rate against the local short rate).

`ForeignOverrides.for_asset("DEU", "bonds")` maps the worldbankscape euro-area members (DEU, FRA,
ITA, ESP, NLD) to `EMU`. `sources` is keyed by store: `fred` and `tic` (both sec-edgar),
`dbnomics`, `bisfetcher`, `jquantster`, `ausdata`, `singstat` and `idxscape`. When it is None,
`default_sources()` builds them from `config/sources.yaml`.

| Component | USA | JPN | EMU | AUS | SGP | Window, band | stocks / bonds / ccy per +1 |
|---|---|---|---|---|---|---|---|
| `growth` | FRED `GDPC1` → y/y | Tankan `BOJ.tankan_lm` | dbnomics `ea20.bci` | ausdata `DER.GDP_YY` | singstat `M015631:2` | GDP: latest − mean of 4 q before, ±0.25pt; surveys: 3m, ±3 DI / ±0.2 | +3 / −1 / +1 |
| `cli` | `usa.cli` | `jpn.cli` | `g4e.cli` | `aus.cli` | — (none) | 3m, ±0.2 | +3 / −1 / +1 |
| `inflation` | `usa.cpi.yoy` | — (none) | `ea.hicp.yoy` | ABS monthly, else `aus.cpi.yoy`, else `DER.CPI_HEADLINE_YY_Q` | CPI index → y/y | 3m, ±0.3pt | −1 / −3 / −1 |
| `policy` | BIS `M.US`, else `DFF` | BIS `M.JP`, else call rate | `ea.rate.deposit`, else BIS `M.XM` | RBA cash rate, else BIS `M.AU` | SORA 3M | 6m, ±0.125pt (+1 = hiking) | −2 / −3 / +1 |
| `curve` | `T10Y2Y` | JGB 10Y − 2Y | `ea.bund.10y` − `ea.bond.2y` | `DER.CURVE_10Y_2Y` | SGS 10Y − 2Y | 3m, ±0.15pt (+1 = steeper) | +1 / −1 / 0 |
| `fx` (IDR per local unit) | JISDOR | JISDOR ÷ USD/JPY | IDR/SGD × S$/EUR (MAS) | RBA `FXRIR` | 1 ÷ MAS S$/IDR | 3m %, ±1.5% | +1 / +1 / +3 |
| `flows_equity` | TIC `for_lt_eqty_net_99996` | | | | | 3m sum − 3 before, ±US$ 20bn | +2 / 0 / +1 |
| `flows_treasury` | TIC `for_lt_treas_net_99996` | | | | | 3m sum − 3 before, ±US$ 30bn | 0 / +2 / +1 |

Point in time works as in P17. A row counts once its store has recorded it, or once it is older
than its series' publication lag (`Ref.lag_days`). ausdata is called with `as_of`, so it skips
months that have not ended. A `Ref` list is tried in order, and the first series with enough
history for the window wins. The ones skipped are named in `stale_inputs`. A newest point older
than `max_age_days` is still used but is flagged. For MAS series that limit is 7 days. Inputs that
no store has are listed in `gaps` and appear as `n/a (why)` in the reason. The weights and bands
are hand-set and must not move a stance until a rule using them beats its placebo.

Tests: `uv run pytest -q tests/layers/test_overrides_foreign.py` gives 30 passed, and ruff is
clean. The tests use in-memory fakes plus one run over the real ausdata, singstat, bisfetcher and
jquantster adapters on their fixture stores. Full suite: 787 passed, 1 skipped.

## Live run (read-only, 2026-10-23, 0.3–0.5 s per date)

Every store was present and none was locked. `usfin serve` was not running, so sec-edgar was read
through ATTACH. dbnomics was read over HTTP.

| as_of | USA s/b/c | JPN | EMU | AUS | SGP |
|---|---|---|---|---|---|
| 2026-10-23 | **+3 / −4 / +3** | −2 / −1 / +4 | +2 / **−9** / −1 | −2 / −3 / +1 | 0 / −7 / +1 |
| 2026-09-25 | +6 / +2 / +3 | +2 / −3 / +5 | +4 / −5 / +3 | −4 / +1 / +1 | 0 / −7 / +1 |
| 2025-06-30 (backtest) | −5 / +8 / −5 | −1 / −2 / +4 | **+10** (raw +11, capped) / +4 / +5 | +6 / +1 / 0 | +1 / +4 / +1 |

What drives the 2026-10-23 numbers:

- **USA:** CLI +0.24 (+1). The Fed went from 3.625 to 3.875 (policy +1). TIC foreign net buying
  of US equities was US$ 320bn in May–Jul vs 142bn before (+1). Treasuries were flat (59bn vs
  66bn). GDP was 2.19% vs 2.43% (0), CPI 3.74% (+0.21, 0) and the curve +6bp (0). JISDOR was
  18,052, +0.1% over 3 months and +8.9% over 12. The hedge carry is +1.81%/y, which matches P27.
- **JPN:** BOJ rate 1.00 → 1.25 (+1), JGB curve −29bp flatter (−1) and IDR per JPY +2.6% over
  3 months (fx +1). Tankan was 22 → 24 (0). Hedge carry is +4.44%/y.
- **EMU:** BCI +0.58, CLI +0.38, HICP 2.8 → 3.8 (+1), ECB deposit rate 2.0 → 2.5 (+1) and
  IDR per EUR −2.4% (−1). Bonds come to −9, close to the cap.
- **AUS:** RBA 4.10 → 4.60 (+1). Everything else is inside its band. AUD/IDR is 12,578, +16.6%
  over 12 months.
- **SGP:** GDP 5.9% vs 5.47% (+1), CPI y/y 1.82 → 2.35 (+1) and SORA 3M +17bp (+1). Bonds −7.
  All MAS series are flagged stale (last 2026-10-06/07).

## Findings (siblings vs the notes)

- **singstat is still stale.** The last refresh was 2026-10-07. SGP's SORA, SGS 2Y/10Y and S$/IDR,
  and EMU's EUR leg (MAS S$/EUR), are flagged against the 7-day limit the notes ask for, and are
  still used.
- **EUR has no IDR or USD quote in dbnomics.** The ECB block holds rates and HICP but no EUR/USD.
  This layer crosses EUR through singstat (IDR/SGD × S$/EUR), as P29 does for KRW/TWD, so EMU's
  fx goes stale with singstat. A `ea.fx.usd` series in dbnomics would allow a JISDOR cross.
- **The euro area has no GDP.** dbnomics has none, so the OECD business confidence indicator
  `ea20.bci` stands in for growth. As the notes say, the euro-area 2Y stands in for the Bund 2Y.
- **Japan has no CPI in any store, and no TSE flows** (jquantster is on the Free plan). Both are
  listed in `gaps`. The Tankan large manufacturers DI stands in for growth (quarter-end dated,
  5-day lag).
- **Singapore has no OECD CLI.** MAS runs policy through the S$NEER, so SORA 3M stands in for
  the policy rate.
- **AU CPI history is short.** ABS monthly CPI starts 2025-04, and dbnomics `aus.cpi.yoy` (OECD's
  copy) also starts 2025-04. For backtests before about mid-2025 the layer falls back to
  ausdata's quarterly `DER.CPI_HEADLINE_YY_Q`.
- **ausdata dates its derived quarters and Tankan at quarter end.** A 3-month look-back from a
  month end lands on the previous month end (`_shift` keeps month ends), so June 30 compares
  with March 31. An earlier draft compared it with December 31.
- **TIC on this Mac ends at 2026-07** (sec-edgar store from 2026-10-14). TIC and FRED are read at
  their latest vintage and gated by publication lag, so backtests see revised FRED data (no
  `fred_as_of`). That is fine for direction, but it is not strict point in time.
- **Policy moves are everywhere.** All five markets show a hike over 6 months as of
  2026-10 (Fed, BOJ, ECB, RBA, SORA). That is why bonds are negative across the board.
