# P30-paper: results

`src/assist/paper.py` scores paper tracking (PLAN S13). It compares each model's stance-implied IDN allocation against a fixed IDR 60/40 benchmark (60% JCI, 40% SBN leg). Marks are weekly, on Fridays, and each fingerprint segment is scored on its own. There are 18 tests in `tests/test_paper.py`. The full suite gives 568 passed and 1 skipped, and ruff is clean.

## How it works

- **Inputs:** it reads journal records only (`Journal.read()`). It keeps records with kind `stance`, subject IDN and asset stocks or bonds, and ignores everything else.
- **JCI leg:** this is P3's `idxmethod.jci()`, a price index without dividends. A mark after the last close has no return and lists the reason in `stale`. It is never carried forward.
- **SBN leg:** this is pluggable (`BondLeg` protocol). The default, `bond_leg()`, is a labelled synthetic constant-maturity 10Y par bond:
  - Each week it earns a week of coupon at the starting yield and is repriced at the ending yield, with semiannual coupons. Roll-down is ignored.
  - The yield comes from IGSYC 10Y (idxscape PHEI) when that exists. Otherwise it falls back to dbnomics `idn.rate.long`.
  - The dbnomics series is a monthly average. Each value is stamped at its month end, so it is never used before it was known. A 6-day grace window prices the week that straddles a month end.
  - The label always says "synthetic … not an SBN index". Which SBN index to use is still an open question in PLAN.md.
- **Benchmark:** 60/40, rebalanced weekly.
- **Portfolio:** each asset's latest stance known at the week start (`as_of <= week_start`, so no look-ahead) tilts its benchmark weight:
  - The tilt is `TILT_PT`: overweight +10, underweight −10, and avoid holds 0. These are placeholders, as in stance.py, until the bands are settled.
  - If the weights add up to more than 100, they are scaled down. Whatever is left is cash earning 0.
  - If a segment has no stance for an asset, that asset is held at its benchmark weight, and a note says so.
- **Segments:** a segment rules the weeks that start between its first decision and the next segment's first decision. For each segment the scorer reports:
  - cumulative portfolio, benchmark and active return
  - hit rate
  - tracking error (annualised, √52)
  - information ratio
  
  Stale weeks are counted but not scored. Nothing is pooled across fingerprints.
- **Running it:** `python -m assist.paper [--marks]` prints the report as JSON. `PaperReport.to_dict()` gives the same report, carries the disclaimer, and names the source of each leg.

## Live run (2026-10-23, read-only, `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects`)

- **Journal:** there is no journal yet; `journal/decisions.jsonl` is absent even in the main checkout, because `assist run` is not wired until F1. `segments` is therefore empty. The report says "no stance records in the journal: benchmark marks only" and shows only the benchmark's own marks.
- **Bond leg:** this uses the **dbnomics `idn.rate.long`** fallback. idxscape on this Mac is still at migration 8, so the stale inputs include `idxscape_phei (missing)`. The dbnomics series **ends 2024-12** (dbnomics flags it stale), so the bond leg stops at 2024-12-31.
- **Stale inputs reported:**
  - `idxscape_phei (missing)`
  - `JCI frozen at 2026-09-30 (idx-method index CSVs; no JCI fetcher)`
  - `idn.rate.long ends 2024-12-31`

| | Weeks | Cumulative | Annualised | Vol (ann.) |
|---|---|---|---|---|
| Benchmark 60/40 | 674 (2012-02-10 → 2025-01-03) | +102.1% | 5.6% | 9.8% |
| JCI leg (price) | 674 | +78.4% | 4.6% | 14.8% |
| SBN leg (synthetic, monthly) | 674 | +118.3% | 6.2% | 8.8% |

- **Stale weeks:** 94 weeks are stale (2025-01-10 → 2026-10-23). In 90 of them the SBN leg is past 2024-12-31. In the last 4, the JCI leg is also past 2026-09-30.
- **Worst benchmark week:** 2020-03-20, at −8.7% (JCI −14.5%, SBN leg +0.1%).
- **Monthly averages understate bond volatility:** in March 2020 the SBN leg shows no sell-off. A daily IGSYC 10Y would fix this.

## For later slices

- **Nothing can be scored yet:** even after F1 starts journalling, every week stays stale. The bond leg (dbnomics, ends 2024-12) and the JCI leg (frozen 2026-09-30) both have no current data. Scoring needs both of these:
  - idxscape's PHEI tables loaded on this Mac (migration 9). The IGSYC 10Y then takes over automatically.
  - a JCI fetcher, swapped in at `idxmethod.jci()`.
- **PHEI is local only:** once the IGSYC 10Y is the source, the synthetic returns are derived numbers, fine to send in a brief. Raw curve points are not, and paper.py does not emit any.
- **To change the SBN index:** pass any object with `name`, `label`, `stale_inputs`, `valid_through`, `returns(grid)` and `stale_reason(d)` as `bond=` to `paper_track`.
- **Weekly cadence:** F4 (launchd) can run `python -m assist.paper` weekly. The CLI wiring belongs to cli.py and is not done here.
- **Sibling docs:** nothing in a sibling's docs conflicted with the notes. The only difference is that the dbnomics IDN long rate's last observation is 2024-12, older than the notes implied.
