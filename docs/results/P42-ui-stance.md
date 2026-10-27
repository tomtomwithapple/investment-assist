# P42-ui-stance — PLAN S25: UI stance detail

`src/assist/views/stance.py` serves `/stance/<SUBJECT>/<asset>`. `web.ROUTES` maps
`^/stance/([^/]+)/([^/]+)$` to `web._stance`, which imports the view inside the handler, as
`_overview` does.

- **Matching.** `find(stances, subject, asset)` compares the two URL segments exactly (case
  sensitive) against the stances `brief.load_out(app.out_dir)` loaded. The URL never becomes a
  path. No match means None, which gives a 404. `/stance/IDN/..%2Fx` is decoded by `dispatch` to
  `/stance/IDN/../x`. That is three segments, so the route regex does not match it and it is a
  404. `/stance/IDN/..` matches the regex, but no stance has the asset `..`, so it is a 404 too.
- **Page.**
  - The summary card has the stance chip (overview's tones), "As of", score, layer-1 score ("-"
    if absent), confidence (2 dp), regime, dollar ("-" if absent), and the model fingerprint
    shortened with `brief._fingerprint` (`sha256:` + 12 hex) plus `model_version`.
  - Then come these cards: change since last snapshot, drivers, risks, watch, entry (style,
    tranches, spacing in days), portfolio (current and target as %, `n/a` for a null current,
    and delta), flags, stale inputs and sources.
  - Each flag is a row with a severity chip (critical bad, warn warn, info muted), its `code` and
    its `message`. An empty list shows "none".
  - The stance's own `disclaimer` closes the body, and the layout footer carries `web.DISCLAIMER`.
- **Change since last snapshot.** `brief.previous_snapshot(app.snapshots_dir, before=as_of)` is
  strictly before `as_of`. Then `brief.load_out(prev)` is matched on the same pair. It shows
  "<date>: <old chip> <old score> → now <chip> <score> (±delta)", or "not in the <date>
  snapshot", or "no earlier snapshot". An unreadable file in the snapshot is dropped by
  `load_out`, so the pair reads as not in the snapshot, never a 500.
- **`.json` twin.** This is the stance dict as written. It is equal to the file: the live run
  compared `/stance/USA/bonds.json` with `out/USA/bonds.json`.

Fixtures:
- `tests/fixtures/ui/out/USA/bonds.json` now has three flags (critical `high_gov_debt` and warn
  `large_fiscal_deficit`, copied from the real file, plus an info flag). The overview does not
  read flags, so its tests are unchanged.
- `tests/fixtures/ui/snapshots/` has IDN/bonds on three dates:
  - 2026-09-29 (underweight 30), which is older and ignored;
  - 2026-10-06 (neutral 55.5), the previous snapshot, with no USA in it;
  - 2026-10-13 (avoid 10), the same day as `as_of`, so it is not "before" and is ignored.

`tests/test_view_stance.py` has 21 tests:
- the summary fields and the short fingerprint;
- the lists, entry, portfolio and sources;
- the USA flags as chips, the stale input and a null current_pct;
- the change against the right snapshot, the pair missing from the snapshot, and no snapshot
  (missing directory and empty directory);
- the JSON twin equal to the file;
- 12 404 cases: unknown asset, unknown subject, `idn` and `BONDS` (case), `../x`, `..%2Fx`,
  `..`, `../IDN/bonds`, too few segments, too many segments, `bonds.json/x` and an unknown
  `.json`;
- `<script>` in drivers, risks, watch, sources, stale inputs, delta and a flag message, escaped
  7 times;
- an unreadable snapshot file;
- every `/stance/...` link on the overview resolves to a 200.

Red: 9 failed, all 404, because there was no route yet (the 12 404 cases already passed).
Green: 21 passed.

## Results

- Accept command: 61 passed, and ruff is clean (also on the test file).
- Full suite: 1185 passed.

## Live run (2026-10-27, `uv run assist status --port 8799`, real out/ and data/snapshots/)

| Request | Code | Size | Time |
|---|---|---|---|
| GET /stance/IDN/bonds | 200 | 5,338 B | 30 ms |
| GET /stance/IDN/bonds.json | 200 | 1,935 B | 30 ms |
| GET /stance/USA/bonds | 200 | 5,719 B | 30 ms |
| GET /stance/USA/bonds.json | 200 | 2,298 B | 30 ms |
| HEAD /stance/USA/bonds | 200 | | |
| GET /stance/idn/bonds | 404 | 2,476 B | 15 ms |
| GET /stance/IDN/..%2Fx | 404 | 2,477 B | <1 ms |
| GET /stance/USA/currency | 404 | 2,479 B | 15 ms |

- **IDN bonds** is neutral as of 2026-10-27:
  - score 56, layer-1 score 58, confidence 0.79, regime neutral, dollar flat, model
    `sha256:d0111175d4fc` v0.3.0;
  - 8 drivers (the real yield is 4.16%, 51st pct, and non-resident SBN is +IDR 8.39T since
    2026-09-25), 1 risk ("BI hiking") and no watch items;
  - entry none, portfolio 0% → 0% "0.0pt hold", no flags;
  - stale inputs `satudatascape (missing)` and `yield_spread (missing)`, and 8 sources;
  - change: 2026-10-23 neutral 56 → now neutral 56 (+0.0).
- **USA bonds** is neutral as of 2026-10-27:
  - score 44.1, layer-1 score 48.1, confidence 1.00;
  - flags: a critical `high_gov_debt` chip ("Gross government debt 136% of GDP (> 120%)
    [2026Q2]") and a warn `large_fiscal_deficit` chip ("Fiscal balance -7.1% of GDP (< -5%)
    [2025]");
  - 1 risk (the IDR edge of -0.56% does not survive the FX move), no stale inputs, 7 sources;
  - change: 2026-10-23 neutral 44.1 → now neutral 44.1 (+0.0).
- After the server was stopped, a curl got no answer.

## Findings

- **The change line has little to show today.** The only earlier snapshot is 2026-10-23, and
  both live pairs are unchanged since then, so "(+0.0)" is what the page shows. The fixtures
  cover a real move (+12.5) and the other two cases.
- **The disclaimer appears twice.** The stance's own `disclaimer` is in the body, because the
  notes ask for it, and `web.DISCLAIMER` is in the footer. Both are the same text today.
- **`/stance/IDN/..` matches the route regex.** It is only the lookup that rejects it. That is
  safe because no path is built, and it is tested.
- No contradiction with the plan.
