# P81-foreign-override-inputs (PLAN S63): point-in-time input history of the foreign overrides

Date: 2026-11-09. Branch `phase-l`. Phase L choice 13 (accepted 2026-11-09). Heuristic, not
investment advice.

## What changed

- **`src/assist/override_history.py`** (plumbing). `foreign_replay(dates, sources)` calls P28's
  `foreign_overrides` unchanged on every month end for USA, JPN, EMU, AUS and SGP. It returns
  one `OverrideHistory` per market.
  - **Store reads:**
    - Every store is read once (`Preloaded`), from the first date less P28's `READ_BACK` to the
      last date, and sliced per date.
    - **FRED `GDPC1`** is read per date at its vintage (`FredVintage`: `rows(..., as_of=day)`,
      sec-edgar's `fred_as_of`). Choice 13: it is the one foreign input whose store keeps
      vintages. DFF and T10Y2Y (daily, not revised) are preloaded.
    - **ausdata** is asked per date with `as_of`, as P28 asks it, so a period not yet over is
      skipped.
  - **AUS `fx` in history** (choice 13): where RBA's AUD/IDR (`FXRIR`, from 2023-01) has no
    3-month base, AUS reads IDR per AUD from the MAS cross (IDR per S$ × S$ per AUD,
    `IDR_PER_AUD`). Both variants run in the same call; the RBA one wins once it computes.
    Live P28 keeps RBA's rate.
  - **Rows:** `OverrideRow.expected` holds the market's own components (`expected_components`:
    the spec plus `fx`). `complete` and `coverage()` use it. Missing reasons name the store
    line (e.g. `growth: jquantster (locked)`).
  - **A read that finds its store locked by another reader retries** (`LOCK_TRIES` 4, waits 2,
    4, 6 s), in `Preloaded` and in the per-date vintage read. The first live replay lost four
    USA months to transient `sec-edgar (locked)` reads: `usfin serve` holds the lock, and an
    HTTP read slower than 5 s reads as locked (phase J). A lock that lasts is still named,
    never raised.
  - `python -m assist.override_history --subject USA|JPN|EMU|AUS|SGP` prints a market's
    coverage.
- P28 itself is unchanged. The replay is outside the model fingerprint but inside each override
  fingerprint (choice 8), so the S59 IDN override fingerprint changes as well.

## Tests (first, red → green)

`tests/test_override_history.py`, 9 new tests (33 in all), over P28's in-memory world (loaded by
path from `tests/layers/test_overrides_foreign.py`):
- the replay equals `foreign_overrides` called directly (shifts, raw sums, component values);
- each store is read once; FRED GDPC1 once per date at that date's vintage; ausdata once per
  date with `as_of`;
- **GDP at its vintage:** a vintage with a growth jump gives direction +1 where today's revised
  values give 0;
- **poison:** no row up to a cut-off moves when every value dated after it is poisoned; later
  rows do;
- **AUS fx:** reads `IDR_PER_AUD` (singstat) before `FXRIR` has 3 months, then `FXRIR`;
- completeness on each market's own spec (USA 8 components, SGP 5); a locked jquantster makes
  JPN incomplete with its reason; JSON round trip keeps `expected`;
- a locked vintage read is retried; a lasting lock is named;
- `Preloaded` retries a lock and passes its start bound; the foreign preload starts at the
  first date less the read-back.

Full suite: 1896 passed, 1 skipped. `ruff check .` is clean.

## Live (2026-11-09, real stores read-only)

262 month ends 2005-01 → 2026-10, in 86 s (FRED over HTTP from `usfin serve`).

| Market | Complete months | From | Holes after | Shift signs on complete months, up / zero / down (stocks; bonds; currency) |
|---|---|---|---|---|
| USA | 259 | 2005-04 | none | 121 / 24 / 114; 106 / 27 / 126; 133 / 35 / 91 |
| JPN | 259 | 2005-04 | none | 115 / 21 / 123; 83 / 48 / 128; 127 / 20 / 112 |
| EMU | 259 | 2005-04 | none | 140 / 12 / 107; 111 / 25 / 123; 140 / 18 / 101 |
| AUS | 155 | 2013-12 | none | 66 / 17 / 72; 89 / 18 / 48; 72 / 11 / 72 |
| SGP | 247 | 2006-04 | none | 112 / 20 / 115; 125 / 27 / 95; 123 / 38 / 86 |

- **What binds the start:**
  - USA, JPN and EMU start at the 3-month `fx` base (the MAS crosses from 2005-01).
  - AUS starts at ausdata's `DER.CURVE_10Y_2Y` (2013-12).
  - SGP starts at SORA 3M (2006-04).
- **AUS fx:** the MAS cross (`IDR_PER_AUD`) 2005-04 → 2023-03, RBA `FXRIR` from 2023-04.
- **Series read:**
  - USA: GDPC1 at its vintage, `usa.cli`, `usa.cpi.yoy`, `WS_CBPOL.M.US`, T10Y2Y, TIC
    `for_lt_eqty_net_99996` / `for_lt_treas_net_99996`, USD/IDR on the P65 splice.
  - JPN: Tankan LM, `jpn.cli`, `BOJ.call_rate` / `WS_CBPOL.M.JP`, JGB 10Y − 2Y,
    `IDR_PER_JPY`.
  - EMU: `ea20.bci`, `g4e.cli`, `ea.hicp.yoy`, `ea.rate.deposit`, Bund 10Y − EA 2Y,
    `IDR_PER_EUR`.
  - AUS: `DER.GDP_YY`, `aus.cli`, ABS monthly CPI / `DER.CPI_HEADLINE_YY_Q`, `FIRMMCRTD` /
    `WS_CBPOL.M.AU`, `DER.CURVE_10Y_2Y`, `IDR_PER_AUD` → `FXRIR`.
  - SGP: real GDP y/y, CPI y/y, SORA 3M, SGS 10Y − 2Y, `mas:fx:idrsgd`.
- **Vintage per store** (choice 13):
  - sec-edgar FRED GDPC1: **vintage per date**.
  - Every other store: one stored vintage, read under P28's publication lags. That is FRED
    DFF / T10Y2Y, TIC (first-seen dates), dbnomics (none), bisfetcher (fetch date),
    jquantster, ausdata (`pulled_at`) and singstat (fetch date 2026-11-08).
- **GDP vintage vs today's revision:** read at today's values instead, USA's growth direction
  would differ in **64 of 262 months**. The OECD CLI (no vintage) is the input choice 10's
  CLI-zeroed check covers.
- **2026-10-31 shifts** (stocks / bonds / currency): USA 0 / −3 / +2, JPN −2 / −1 / +4,
  EMU +2 / −9 / −1, AUS −2 / −5 / +3, SGP 0 / −3 / +2.
