# P41-ui-overview — PLAN S24: UI overview

`src/assist/views/overview.py` serves `/` (`web.ROUTES` now maps `^/$` to it; the S23 redirect is
gone). `web._overview` imports the view inside the handler, because the views import `web` at
load time.

- `build(brief.load_out(app.out_dir))` gives the rows, and the `.json` twin is that dict:
  - `as_of` (the newest), `regime` and `dollar` (`brief._by_value`);
  - `counts` per stance (overweight, neutral, underweight, avoid);
  - `columns` (stocks, bonds, currency);
  - `countries` `[{subject, cells: {asset: row | null}}]`;
  - `commodities` `[row]` and `problems`.

  A row is `{subject, asset, stance, score, confidence, stale_inputs, href}`. Country rows are
  subjects with a non-commodities stance, in `brief._sort_key` order (IDN first). `subject_type`
  is not read.
- Banner: "As of", then Regime and Dollar from `brief._grouped_line`. The bullet is dropped, the
  line is escaped, then `**x**` becomes `<strong>`, so a mixed value reads "Dollar: mixed,
  **flat** (IDN bonds, GOLD commodities); **up** (...)". Below that come the non-zero counts.
- Grid: one stance chip per cell (overweight good, neutral muted, underweight and avoid bad)
  linking to `/stance/<SUBJECT>/<asset>`, then the score (`brief._num`) and the confidence (2 dp).
  A cell with stale inputs gets a warn "stale" chip, with the input names as its escaped `title`.
  A missing cell is "-".
- Commodities are in a second table with the same fields. The subject links to its stance.
- Load problems are a notice each. An empty or missing out/ shows "no stances in out/ yet: run
  `assist run`" and no tables.

Fixtures are in `tests/fixtures/ui/out/` in the out/ layout:
- IDN/bonds, IDN/stocks and USA/bonds are copies of `tests/fixtures/stance/`;
- GOLD/commodities is the real `out/GOLD` file, re-dated to 2026-10-13.

Together they cover:
- a mixed dollar;
- USA with no stocks and no currency cell;
- one stale cell and one commodity.

`tests/test_view_overview.py` has 9 tests:
- `/` is a 200, not a 302;
- the banner (one value, mixed and the counts);
- the grid's columns, row order, chips, numbers and "-" cells;
- the stale marker;
- the commodities table;
- the JSON twin;
- the counts;
- problems as a notice, with a `<script>` filename and a `<script>` stale input escaped;
- empty and missing out/.

Red: the 302 at `/`. Green: 9 passed.

## Results

- Accept command: 49 passed, ruff clean (after `test_web.py` was fixed, see Findings).
- Full suite: 1164 passed.

## Live run (2026-10-27, `uv run assist status --port 8799`, real out/)

| Request | Code | Size | Time |
|---|---|---|---|
| GET / | 200 | 15,190 B | 18 ms |
| GET /.json | 200 | 20,646 B | 15 ms |
| HEAD / | 200 | | |

- as_of is 2026-10-27, and regime is neutral and dollar flat on every stance.
- **12 countries and 35 cells**, plus **14 commodities**. The only missing cell is USA currency.
- 30 of the 35 country cells have stale inputs, and none of the 14 commodities do.
- Counts: 15 overweight, 31 neutral, 2 underweight, 1 avoid (49 stances).
- No problems were reported. The page has 49 `/stance/...` links and 30 stale chips.
- After the server was stopped, a curl got no answer.

## Findings

- **The plan contradicts itself on ownership.** The notes say "/ replaces the S23 redirect".
  But `tests/test_web.py::test_root_redirects_to_status` (owned by P40, and in this slice's
  accept command) asserts `/` is a 302 to `/status`. This slice's `owns` does not include
  `tests/test_web.py`, so accept cannot pass without editing a file outside `owns`. The fix is to
  drop that test, or change it to assert `/` is a 200 (`test_view_overview.py` already covers
  that). This needs a plan change or permission.
  Resolved: the coordinator added `tests/test_web.py` to P41's `owns` (plan commit "plan: phase G
  views own tests/test_web.py"). The test became `test_root_is_the_overview`: `/` is a 200 with
  the nav and Overview marked active.
- 30 of 35 country cells are stale (financer, idx-method frozen CSVs and similar), so the stale
  chip is the norm, not the exception. S25's detail page is where the names matter. The chip's
  tooltip lists them here.
- The page is cheap (about 15 ms), unlike `/status` (about 3 s).
