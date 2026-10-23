# P18-signals-idn — PLAN S8: IDN market signals (layer 3)

`src/assist/layers/signals.py`: `idn_signals(as_of, idxscape=, kseistat=, tic=)` → `IdnSignals`
(`signals`, `stale_inputs`, `sources`, `for_asset()`, `tally()`). It reads through the P13, P14 and
P15 adapters and does no I/O of its own. A missing or locked store drops that store's signals and
is named in `stale_inputs`.

| Signal | Asset | Series | Window | Dead band |
|---|---|---|---|---|
| `idx_foreign_flow` | stocks | idxscape `IDX_NET_FOREIGN_IDR` (detail: `_USD` via same-day JISDOR, gaps counted) | last 20 IDX days | ±IDR 1T |
| `sbn_non_resident_change` | bonds | idxscape `SBN.TOTAL.non_resident` (detail: share of `SBN.TOTAL.total`) | 4 weeks | ±IDR 2T |
| `ksei_foreign_share` | stocks | kseistat `KSEI.sum.foreign_pct` (detail: equal-weight) | 3 month-ends | ±0.25 pt |
| `tic_us_equity_net` | stocks | sec-edgar `us_lt_eqty_net_42218` | 3 months | ±US$ 50 mn |
| `tic_us_bond_net` | bonds | sec-edgar `us_lt_bond_net_42218` | 3 months | ±US$ 50 mn |

The bands are hand-set. They must not move a stance until the rule that uses them (P22, P31)
beats its placebo.

Tests: `uv run pytest -q tests/layers/test_signals_idn.py` gives 31 passed; ruff is clean. The
full suite gives 283 passed.

## Live run (read-only, 2026-10-23)

| as_of | idx flow 20d | SBN non-res Δ4w | KSEI foreign Δ3m | TIC US eqty 3m | TIC US bond 3m | tally stocks / bonds | stale |
|---|---|---|---|---|---|---|---|
| 2026-10-23 | IDR −16.09T (US$ −616m, 3 JISDOR gaps) **−1** | IDR +5.74T (914T held, 13.02%) **+1** | 31.32%, −4.27pt (eq-wt 21.40%, −0.39pt) **−1** | −1,577 May–Jul **−1** | +921 **+1** | −3 / +2 | none |
| 2026-10-21 | same **−1** | IDR −1.83T to 09-30 (Oct file not yet out) **0** | same **−1** | same **−1** | same **+1** | −3 / +1 | none |
| 2025-06-30 (backtest) | IDR −9.55T (US$ −584m) **−1** | IDR +18.67T to 05-21 (14.40%) **+1** | 38.48%, −0.29pt **−1** | −396 Feb–Apr **−1** | −1,062 **−1** | −3 / 0 | none |

All three stores were present and unlocked. sec-edgar was read over its HTTP or ATTACH path, as
the P15 adapter chooses.

## Findings (siblings vs the plan)

- **Every store is a backfill, so `Row.as_of` is not a publication date for history.** As of
  2026-10-23, every IDX flow day carries `recorded_at` 2026-10-06, every DJPPR day 2026-10-08,
  every KSEI month `loaded_at` 2026-10-07, and every TIC month `first_seen_at` 2026-10-14 (back to
  1994). sec-edgar's `tic_as_of(DATE)` returns nothing before 2026-10-14. A strict `Row.as_of`
  filter would empty every backtest. The layer counts a row as known if it was recorded by
  `as_of` **or** its date is older than that series' normal publication lag: IDX 1 day, DJPPR 40
  days, KSEI 14 days, TIC 80 days. TIC is therefore read as latest, not through the adapter's
  `as_of` vintage, even though the plan names `tic_as_of` for point-in-time reads.
- **DJPPR posts monthly files.** October's SBN days arrived in a file fetched on 2026-10-22, so
  on 10-21 the newest known day is 09-30. SBN freshness is therefore 47 days, not the 7 used for
  daily series.
- **JISDOR in idxscape ends at 2026-10-16** while IDX flow runs to 10-21, so the 20-day USD sum
  has 3 gaps. They are left unfilled and shown in the detail, as idxscape's J8 does. idxscape's
  JISDOR job may need a look; that belongs to idxscape, not here.
- **KSEI `sum` foreign share fell 3.75pt in September** (35.07 → 31.32%) while the equal-weight
  share fell only 0.33pt. The `sum` method is dominated by stocks with huge share counts (kseistat
  README), so one listing or corporate action can move it. The signal keeps `sum` as the plan
  names it, and the detail carries the equal-weight view. P22 should consider equal-weight
  if `sum` fails its placebo.
- The real TIC source name is `sec-edgar` (from `usfin.SOURCE`), not `usfin`, so that is what
  appears in `sources` and `stale_inputs`.
