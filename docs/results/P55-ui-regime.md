# P55-ui-regime — results

PLAN S34: `/regime` shows layer 0 from `out/layers/regime.json` (S33) and the regime history
from the journal. Read-only; nothing is written. Checked live 2026-11-06 on a copy of the S33
live `out/` and the main checkout's `journal/`.

## What the page shows

- **Call card:** regime and dollar chips, the dollar input with its band ("broad dollar
  +1.6%/13w; up past +2%, down past -2% over 13 weeks"), points off / on / net against
  `state_at`, drivers, adopted candidates, sources, the file's stale inputs, model fingerprint.
- **Layer-0 inputs:** one row per input in the file, counted first, then candidates (dimmed,
  "candidate, not counted"): label with series id, feature and kind; value (level, `+x.xxpt`
  for a diff, `+x.xx%` for a pct); newest date; direction chip; vote; a 160x34 inline-SVG line
  of the input's 52 weekly values (the value the rule votes on; a dashed zero line when the
  range crosses 0; a null week is a gap, never filled; the tooltip gives first/last, low/high
  and, for change inputs, the series level).
- **Stale marker** per input: no value, newest point more than 14 days before the file's
  `as_of`, or one of the file's `stale_inputs` names its feature or series id.
- **Regime history:** every journal record of kind `regime`, newest first, with state, dollar,
  from (weekly run or daily check, by `inputs.job`), drivers and model; a row whose state or
  dollar differs from the one before it is marked "changed".
- `/regime.json`: `{"regime": <file as read or null>, "history": [...], "problems": [...]}`.
- Failures are notices, never a 500: missing file, unreadable JSON, a file that fails
  `schema/layers/regime.schema.json` (checked with `layers_out.validator`), a stub with
  `error`, a missing or unparseable journal. The history still shows when the file is bad.

## Files

- `src/assist/views/regime.py` (new), `web.py`: one `ROUTES` entry `^/regime$` (lazy import as
  the other views). `NAV` and other pages' links untouched (S37 owns them).
- `tests/test_view_regime.py` (19), fixture `tests/fixtures/ui/layers/regime.json`: the S33
  live file cut to 8 weeks, the term premium input with no value, one VIX week null; the test
  checks it against the schema. The journal is built in a tmp dir (4 regime records incl. a
  daily check that changed, plus stance records carrying a different regime that must not show).

## Tests

19 in `test_view_regime.py`; full suite **1519 passed, 1 skipped**; ruff clean.

## Live (2026-11-06)

`uv run assist status --port 54469 --no-http` (listening on 127.0.0.1 only, per `lsof`):

| GET | Status | Size |
|---|---:|---:|
| `/regime` | 200 | 16,604 B |
| `/regime.json` | 200 | 61,713 B |
| `/nope` | 404 | 2,501 B |

Values shown: neutral, dollar flat; points off 1, on 0, net 1; driver "10Y real yield 2.64%
(risk-off)"; VIX 16.61 (2026-11-04), HY OAS +0.57pt, broad dollar +1.64%, real yield 2.64
risk-off +1, NFCI -0.46; candidates net liquidity -0.84%, EM corp OAS +0.37pt, term premium
+0.04pt, STLFSI4 -0.52 risk-on -1 (not counted); none stale; 52-week lines for all 9. History:
2 regime records (2026-10-29 and 2026-11-06, both neutral / flat, from weekly runs, two
models). Headless Chrome screenshots in light and dark (dark forced by turning the
`prefers-color-scheme: dark` blocks on) read cleanly.

## Decided differently or found

- **The inputs are the file's 9**, not the longer list in phase H's Done-when (curve T10Y2Y,
  Brent, EM HY OAS are not inputs of `layers.regime`, so S33 does not write them). The page
  shows what the run computed; adding inputs is out of scope for phase H.
- **History is `regime` records only.** Every run journals one `regime` record before its
  stances, and stance records carry the same regime, so reading them too would only repeat it.
- **The line draws `value`** (what the rule votes on: a level, or the 13-week change), not the
  series level; the level is in the tooltip.
- First screenshot caught the page's scoped CSS redefining the layout's `--line` token (borders
  and muted chips turned blue); renamed to `--spark*`, and a test now fails if a page style
  reuses a layout token name.
- `assist status --help` does not list `/regime` yet: `cli.py` belongs to S37.
