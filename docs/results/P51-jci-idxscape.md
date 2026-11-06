# P51-jci-idxscape: gap 2b closed, JCI read from idxscape `index_daily`

Asked by the idxscape session on 2026-11-06. idxscape's nightly now writes `index_daily`
(migration 10, key `(trade_date, index_code)`): 47 IDX indices from 2021-10-01, `close` but no
open (IDX serves none), no fetch time, no rows on holidays. Nothing changed in idxscape.

Built:
- `src/assist/sources/idxscape.py`: `IDX.<index_code>` series (`index_series`, `COMPOSITE` =
  JCI), the day's `close` with `as_of` None. Asked for by id only, never in the default
  `rows()`; a store without the table (before migration 10) is `missing`.
- `src/assist/sources/idxmethod.py`: `JciSource` stitches idxscape COMPOSITE (wherever it has
  rows) onto idx-method's `jkse_daily.csv` (only before idxscape's first close, whatever the
  window, so the seam never moves). Rows keep series id `JKSE` and name their own source. Either
  store gone, the other carries on; both gone raises idxscape's error. `jci()` defaults to it.
- Callers: `IdnSources.idxmethod` (pipeline: regime walk-forward month-end JCI) and
  `idn_stocks` now default to `JciSource`, so every JCI read goes through it. The paper leg's
  label and stale wording name idxscape; the stocks rule's stale wording is "stale" not "frozen".
- Tests: `tests/sources/test_idxscape_index.py` (8), fixture `tests/fixtures/idxscape/index_daily.sql`
  (DDL copied from idxscape `db.py` plus rows straddling the 2026-09-30 seam). 1412 total.

## Live (this Mac, 2026-11-06)

- `jci()`: 7,314 closes, 1996-10-02 → 2026-11-05; 6,090 from idx-method (to 2021-09-30), 1,224
  from idxscape. No gap over 12 days (only the Lebaran and year-end breaks). idxscape's own
  `previous` equals the prior close on all 1,223 days.
- JCI fell from 6,071 (2026-09-30) to 5,030 (2026-11-05), incl. **−11.6% on 2026-10-16** and
  −3.6% on 2026-10-19. idxscape checked it against a separate IDX endpoint (stock summary,
  close × listed shares): −10.90% on 10-16, −3.43% on 10-19, +5.00% on 10-20 (the gap is
  free-float weighting). 812 of 963 stocks fell, value traded Rp32.0T vs Rp13.5T the day
  before, the large caps (BBCA, BBRI, BMRI, AMMN, BREN, TLKM) closed about −14.8% at the 15%
  auto-reject limit, and LQ45 −13.8%, IDX30 −13.7%. A real limit-down session as far as IDX's
  data goes; no source outside IDX confirms it.
- `assist paper`: before, **no week scored** (JCI ended 2026-09-30, IGSYC starts in October).
  After, **1 week scored** (2026-10-09 → 10-16: benchmark −9.4%, JCI −14.9%, SBN leg −1.0%),
  3 stale. The binding leg is now the bond: **IGSYC.10 ends 2026-10-21** in this Mac's idxscape
  store, though `index_daily` runs to 2026-11-05. Per idxscape: this Mac has no launchd jobs;
  its PHEI rows (10-07 → 10-21) came from captures copied in at J4, and scheduling has moved to
  Windows, so the machine running the PHEI job holds the newer data. A decision for the user.
