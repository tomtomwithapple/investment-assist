# P13-idx-flows — live results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

**What `src/assist/sources/idxscape.py` now reads (all read-only):**
- **`IDX_NET_FOREIGN_IDR`**: the day's total of `stock_summary.net_foreign_value_est_idr`. This is an estimate: idxscape computes net foreign shares × close because IDX publishes no foreign IDR value. `as_of` is the Jakarta-time date of `trading_day.recorded_at`.
- **`IDX_NET_FOREIGN_USD`**: that total divided by the same day's JISDOR. If a day has no JISDOR rate, the value is `None` and the day is listed by `jisdor_gaps()`. It is never filled from another day.
- **`SBN.<SUN|SBSN|TOTAL>.<investor_type>`**: DJPPR holdings in IDR. `as_of` is the Jakarta-time date the source file was fetched (`sbn_ownership_file.fetched_at`).
- **`BROKER_VALUE_IDR.<code>`**: per-broker daily value traded, readable by id or all at once through `brokers()`. It is not in the default `rows()`.
- **Defaults and missing tables**: the default `rows()` returns JISDOR, both flow series, `SBN.TOTAL.non_resident` and `SBN.TOTAL.total`, but only for tables that exist. A series asked for by id whose table is absent is reported as `missing`.

**Live run against the real idxscape store:**
- **Coverage**: foreign flow runs from 2021-10-01 to 2026-10-21 (1,213 days); broker summary and SBN ownership both run to 2026-10-21.
- **Net foreign flow**: −Rp2.30T on 10-19, −Rp2.21T on 10-20 and −Rp0.54T on 10-21. On 10-16 it was −Rp3.31T, which is −$183.2M at JISDOR 18,052.
- **USD gaps**: only 3 days in the whole history (10-19 to 10-21), because the newest JISDOR stored is 2026-10-16. That rate data is 7 days old, so it is close to the 7-day staleness limit in `config/sources.yaml`.
- **Non-resident SBN holdings**: Rp914.41T on 2026-10-21, up Rp5.74T over about 4 weeks.
- **Broker summary**: 88 brokers on 10-21, Rp35.8T total value. That counts both the buy and sell side, since idxscape stores no split.

**Where I followed idxscape rather than the notes:**
- **Same numbers as idxscape**: the calculations follow idxscape's own J8 macro overlay (`queries.macro_overlay`), so both repos show the same figures. Nothing in CLAUDE.md or PLAN.md conflicted with it.
- **Foreign flow is an estimate**: idxscape labels it "est.", and that should carry through to the brief.
- **No broker `as_of`**: `broker_summary` stores no fetch time, so its `as_of` is `None`. Its tables have no buy/sell split, so per-broker foreign net flow can't be derived here.
- **SBN days can be revised**: DJPPR's newer files rewrite earlier days, so every day in the latest file shows that file's fetch date (2026-10-22).
