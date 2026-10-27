# P34-hurdle: PLAN S17, IDR hurdle per market

`src/assist/candidates/hurdle.py`; tests in `tests/test_hurdle.py` (19 tests, in-memory sources).

## What it does

- `hurdle(market, as_of, regime, sources=...) -> Hurdle` gives the annual IDR return (in pt) that
  a name must beat. The index and single names use the same function: every name is held to its
  market's hurdle. `hurdles(markets, ...)` reads each store once for several markets.
- **IDN** = SBN 10Y + US implied ERP + IDN CRP.
  - The 10Y is IGSYC 10Y from PHEI (P32). Without it, the code uses dbnomics `idn.rate.long`,
    flagged as a proxy in drivers and in stale_inputs.
  - ERP and CRP use the same series, lags and `idn.erp.hurdle` fallback as
    `layers/rules/idn_stocks`. They are imported from there, not copied.
- **Foreign** = local 10Y + US ERP + that country's CRP, read from P29's market specs.
  - EMU is defined here: `ea20.rate.long`, with `deu.crp` standing in for the CRP, plus BIS
    `WS_CBPOL.M.XM` and MAS EUR via SGD.
  - The unhedged view uses P29's `expected_fx_move` (the adverse 5% quantile of 1-year moves in
    IDR per local unit over 5 years, else UIP). There is no hedge cost.
  - A name's expected IDR return is `Hurdle.idr_return(expected_local)`
    (`fx.unhedged_idr_return`) and is held to `required`.
  - `local_required` = (1 + required)/(1 + fx_move) − 1 is the same bar in local currency, and
    `components["fx_haircut"]` is the difference between the two. The haircut is applied once.
- **Risk-off** adds `CONFIG["risk_off_premium_pt"]` = 1.0 pt. An unknown regime adds nothing and
  says so in drivers.
  - `CONFIG` sits in a module under `candidates/`, so `journal.RULE_GLOBS` already hashes it into
    the model fingerprint.
- `margin(expected_idr, hurdle, sector_shift_pt=0)` = expected − hurdle − shift, in pt. The S16
  shift is clamped to ±2 pt (`CONFIG["sector_shift_max_pt"]`).

## Live run, 2026-10-27 (read-only)

Regime (P8): **neutral**, dollar flat, so the risk-off premium is 0.

| Market | IDR hurdle | 10Y | US ERP | CRP | Expected FX move (IDR per local) | Local return needed |
|---|---|---|---|---|---|---|
| **IDN** | **13.61%** | IGSYC (withheld, see below) | 3.70% | 2.46% (2026-01 snapshot) | n/a | 13.61% |
| **USA** | **8.92%** | 4.99% (`usa.rate.long`, 2026-09) | 3.70% | 0.23% | −0.74% (adverse 5th pct, 961 windows since 2021-10-28) | 9.73% (haircut +0.81) |
| JPN | 7.45% | 2.84% (JGB 10Y, 2026-10-23) | 3.70% | 0.91% | −9.36% | 18.55% (haircut +11.10) |
| EMU | 7.73% | 4.03% (`ea20.rate.long`, 2026-09) | 3.70% | 0.00% (`deu.crp`) | −0.87% | 8.67% |
| AUS | 9.01% | 5.31% (AGS 10Y, 2026-10-14, stale) | 3.70% | 0.00% | −2.95% (703 windows since 2023-01-03) | 12.33% |
| SGP | 6.18% | 2.48% (SGS 10Y, 2026-10-07) | 3.70% | 0.00% | +1.58% | 4.52% (haircut −1.66) |

- The IDN 10Y came from PHEI (`ten_year_source = igsyc`), and nothing was stale. Its value stays
  in `Hurdle.components` on this Mac. PHEI is local-use only, so drivers and this file carry only
  the total, ERP and CRP.
- USA: a US stock needs about 9.7% a year in USD to clear 8.9% in IDR after the adverse USD/IDR
  move.

## Findings

- **SGP's "haircut" is a tailwind.** SGD rose against IDR in every 1-year window of the last 5
  years, so even the 5th percentile is +1.6% and the SGD return needed is *below* the IDR hurdle.
  This follows from P29's definition. It is not a bug here.
- **JPN haircut is large (+11 pt).** The 5th percentile of JPY/IDR 1-year moves is −9.4%, from the
  2022–24 yen slide.
- **EMU 10Y is the euro-area aggregate** (ECB convergence rate via dbnomics, 4.03% for 2026-09),
  not a Bund yield. dbnomics has no euro-area CRP, so `deu.crp` (0) stands in and drivers name it.
- **AUS 10Y stale:** ausdata `FCMYGBAG10D` was last 2026-10-14 (13 days, over the 10-day
  limit). It is used and flagged.
- **IDN proxy fallback:** dbnomics `idn.rate.long` ends 2024-12 (its HANDOFF), so if PHEI were
  down the proxy would be about 2 years old. It would still be used and flagged as stale.
- **Sibling check:** dbnomics HANDOFF matches what the code reads (ids `us.erp.implied`,
  `<iso3>.crp`, `<iso3>.rate.long`, `ea20.rate.long`, all fractions except rates in % p.a.). No
  conflict with CLAUDE.md or the slice notes.
- **Modelling choice:** the foreign hurdle in IDR is the local requirement, as the slice notes
  say. It is not converted to an IDR risk-free rate. The FX risk enters only through the adverse
  move on the return, so an S20 comparison (`margin(h.idr_return(e_local), h)`) applies the
  haircut exactly once.
