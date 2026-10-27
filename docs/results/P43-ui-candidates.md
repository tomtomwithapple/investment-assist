# P43-ui-candidates — PLAN S26: UI candidates

`src/assist/views/candidates.py` serves `/candidates` and `/candidates/<MKT>`. `web.ROUTES` maps
`^/candidates$` to `web._candidates` and `^/candidates/([^/]+)$` to `web._market`; both import
the view inside the handler, as `_overview` and `_stance` do.

- **Reading.** `load(out_dir)` globs `out/candidates/*.json` (IDN first, then by file stem) and
  json-loads each file here, not through `undervalued.load_out`, which drops an invalid file
  silently. A file that is not JSON, or not a JSON object, is a notice (at the top of
  `/candidates`, and the whole body of its own page). A file that parses but fails
  `schema/candidates.schema.json` (via `undervalued.validator()`) gets a notice in its section
  and still renders. Every field is read with `.get`, so an absent one shows "-".
- **Matching.** `<MKT>` is compared exactly with the file stems found and never becomes a path:
  `XXX`, `idn` (case), `IDN/x`, `..`, `..%2FIDN`, `IDN.json/x`, `XXX.json` and `/candidates/`
  are all 404.
- **Per market** (one `<section class="market">`):
  - summary: as of, bars, currency, regime, hurdle `required_pt`, stocks stance chip with
    current → target, short model fingerprint;
  - hurdle drivers;
  - sector tilt: chip passed / failed / none (none when there is no tilt run at all, as for USA,
    following `brief.undervalued_lines`), the verdict, and a sector table (tilt, margin shift,
    cap);
  - one card per style: verdict chip and text, then t, p, quarters, pool and the name count.
    t and p are hidden when `quarters` is 0, as the brief does. The ranked rows have rank,
    symbol, sector, action, expected, margin, tilt shift, net of cost, round-trip bps, entry
    (level, basis, status), held (IDR held or "no") and size. A null size is "-". A non-null
    size is "IDR x in n tranches", with a row under it listing the size reason and each
    tranche's day, IDR, shares and limit ("-" for a null limit). Dropped names are listed under
    the table. A failed style shows its verdict, "no names", and no table;
  - sizing (portfolio, budget, unspent), trims (symbol, IDR, reason), excluded (symbol,
    reason), stale inputs and sources.
- **`.json` twins.** `/candidates.json` is `{markets: [payloads], problems: [{file, error}]}`.
  `/candidates/<MKT>.json` is the payload as written (`{file, error}` for an unreadable file).

Fixtures in `tests/fixtures/ui/candidates/`, copied by the tests into a temp `out/candidates/`:
- `IDN.json`: the real file, with `config` emptied, tilt sectors cut to 3, excluded to 2 and
  trims to 3;
- `USA.json`: the real file with `config` emptied;
- `AUS.json`: made up from IDN, with a passed tilt (shift -0.5pt), a budget of IDR 2M, one
  sized row (JPFA, IDR 1.5M in 3 tranches, the last with a null limit), one excluded name and a
  stale input. All three pass the schema.

`tests/test_view_candidates.py` has 23 tests: the index (order, links, nav, `.json` twin, no
directory), IDN's summary, hurdle, failed tilt, passed style with every cell of a row, null
size, dropped, the failed GARP style, sizing, trims, excluded; AUS's sized row with tranches;
USA's no-names page; the market twin equal to the file; an invalid file and a non-object file
as notices; a schema mismatch with every absent field rendering "-"; `<script>` in 11 places
(hurdle driver, tilt verdict, style verdict, symbol, sector, size reason, dropped reason,
excluded symbol and reason, trim reason, stale input) escaped on both pages; 8 404 cases; every
index link resolving. `tests/test_web.py` gained one HTTP test for `/candidates` with no
`candidates/` directory (200 with a notice) and `/candidates/IDN` (404).

Red: 15 failed (all 404, no route yet); the 8 404 cases already passed. Green: 23 passed.

## Results

- Accept command: 64 passed, ruff clean (also on the test files).
- Full suite: 1209 passed.

## Live run (2026-10-27, `uv run assist status --port 8799`, real out/)

| Request | Code | Size | Time |
|---|---|---|---|
| GET /candidates | 200 | 10,536 B | 5 ms |
| GET /candidates.json | 200 | 15,939 B | 3 ms |
| GET /candidates/IDN | 200 | 7,916 B | 2 ms |
| GET /candidates/IDN.json | 200 | 9,570 B | 3 ms |
| GET /candidates/USA | 200 | 4,982 B | 2 ms |
| GET /candidates/USA.json | 200 | 4,142 B | 2 ms |
| HEAD /candidates/IDN | 200 | | |
| GET /candidates/XXX | 404 | 2,489 B | 2 ms |
| GET /candidates/idn | 404 | 2,489 B | 2 ms |

Both `.json` twins are equal to `out/candidates/IDN.json` and `USA.json`. `/candidates` shows
IDN then USA, with no notices. After the server was stopped, a curl got no answer.

- **IDN** (as of 2026-10-27, bars 2026-10-09, regime neutral, hurdle 13.74%, stocks neutral
  60.4% → 60.4%):
  - tilt failed (t-stat -1.11 below 2.0), 11 sectors, every shift +0.00pt, cap 5;
  - dividend_value passed (t 2.79, p 0.004, 37 quarters, pool 35), 3 rows:
    1 BMRI hold +2.51pt (net +1.85pt, 67 bps, entry 5,950 typical/deep, held IDR 4,010,000),
    2 JPFA watch +1.12pt (net +0.11pt, 101 bps, 1,915 typical/wait, not held),
    3 BBNI hold +0.84pt (net +0.11pt, 73 bps, 3,770 deep/avoid, held IDR 2,373,000);
    size "-" on all three; 3 dropped on cost (ELSA, CPIN, STAA);
  - garp failed (t-stat 1.30 below 2.0, p 0.085, 17 quarters, pool 30), no names;
  - budget IDR 0, unspent IDR 0, portfolio IDR 29,617,701;
  - 6 trims: AMRT 1,848,000, BBNI 892,115, BMRI 2,529,115, KLBF 2,409,000, PWON 1,935,000,
    SRSN 13,400;
  - 9 excluded (ASII, ASSA, CTRA, DMAS, ERAA, KKGI, MSTI, PTSN, TOWR: held, not rated by any
    passing screen); no stale inputs.
- **USA** (bars "-", hurdle 13.61%, stocks overweight 0% → 5%):
  - tilt none ("none for USA (S16 is IDN only)"), no sector table;
  - dividend_value and garp both failed, "insufficient sample (on 0, off 0)", 0 quarters,
    pool 0, no names;
  - budget IDR 1,480,885, all unspent; no trims, no excluded;
  - 2 stale inputs (sec-edgar universe empty; edgar_company has no SIC); 4 hurdle drivers.

## Findings

- **USA's t 0.00 and p 1.000 meant nothing.** The first live run printed them for styles with
  0 quarters. The brief hides them in that case, so the page does too now (tested).
- **No real file has a size today.** IDN's budget is 0 and USA has no names, so the size and
  tranche rendering is covered only by the made-up `AUS.json` fixture.
- **An unreadable file is a notice, not a market section.** On `/candidates` it sits at the
  top; `/candidates/<stem>` still finds it (200 with the notice), because the URL is matched
  against the files found, as the notes ask.
- **macOS's case-insensitive disk.** Saving the curl of `/candidates/idn` overwrote the saved
  `/candidates/IDN` page in the scratch directory during the first live run. The server itself
  is case sensitive (404), which is tested.
- No contradiction with the plan.
