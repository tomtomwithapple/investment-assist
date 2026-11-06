# P56-ui-signals — results

PLAN S35: `/signals/<SUBJECT>` shows one subject's layer-2 overrides and layer-3 signals from
`out/layers/<SUBJECT>.json` (S33), and for IDN the chart windows. The page never opens a store.
Live check 2026-11-06 on the files of the S33 live run (copied into this worktree's gitignored
`out/`), served by `uv run assist status --port 8796 --no-http` on 127.0.0.1.

## What the pages show

- `/signals/<SUBJECT>`:
  - summary: as of, model fingerprint, EMU's members, stale inputs, sources;
  - layer 2: component, newest value and date, change over its window, direction, weights per
    asset, source and series id, detail; then the shift per asset with the uncapped raw sum, the
    cap and a *capped* chip, and the reason; for a foreign subject the IDR terms (level,
    3m/12m change, hedge carry) and the gaps (inputs that stand in for missing ones);
  - layer 3: signal, asset, value, vote (+1/−1 chip), source, detail, then the tally; a foreign
    subject says it has none (IDN only);
  - IDN charts (inline SVG, light and dark via the page's CSS tokens, a native tooltip per bar
    or point):
    - net foreign flow as two bar charts, IDR and USD (no dual axis). A day without JISDOR has
      no USD bar: a dotted tick at zero marks it, and the subtitle counts those days;
    - JISDOR: a line with dots. A BI carried-forward day is a ring. An IDX day without a fixing
      breaks the line and gets a dotted vertical mark;
    - the IGSYC curve by tenor: the latest solid, the earlier one dashed. A point taken from
      the yesterday column is hollow;
    - non-resident SBN and JCI (1 year): a null value breaks the line and is never bridged.
- `/signals`: an index of the subject files with as of, the shift per asset, the signal count
  and any problem.
- `.json` twin: the file as written. For a file that cannot be read, the twin is
  `{subject, problem, file}`.

## Rules kept

- The subject in the URL is matched exactly against the upper-case stems in `out/layers/`. It
  is never turned into a path, so `regime`, `portfolio`, `idn`, `..%2FIDN` and any unknown
  subject are 404s.
- A file that is invalid JSON, not an object, of another `kind`, an S33 error stub, or missing
  `layer2` gives a notice on a 200 page, never a 500. Malformed parts (wrong types, bad points)
  render as `n/a` or `-`, and one test feeds them all.
- Every value read from a file goes through `esc`.
- The routes are registered in `web.ROUTES` (`/signals`, `/signals/<SUBJECT>`). Per the
  slice's scope, `NAV` and cross-links are untouched; F8 adds them.

## Tests

`tests/test_view_signals.py` has 21 tests. The fixture subjects (IDN with series, EMU foreign
with members, IDR terms and gaps) are built in the test and checked against
`schema/layers/subject.schema.json`. They cover:

- the tables;
- the charts: USD gaps marked and counted, IDR bars, the JISDOR carried-forward ring and gap
  mark with the line broken, the IGSYC solid and dashed lines and a hollow yesterday-column
  point, the JCI line broken at a null;
- a null chart shown as a notice;
- a foreign subject shown as tables only;
- the twin equal to the file;
- 8 404 paths;
- invalid JSON and a non-object file;
- the error stub;
- malformed parts;
- escaping;
- the index;
- no `out/layers/`;
- number formatting.

Full suite: **1521 passed, 1 skipped**; ruff clean.

## Live (2026-11-06)

| Path | Status | Size |
|---|---:|---:|
| `/signals` | 200 | 6,271 B |
| `/signals.json` | 200 | 1,256 B |
| `/signals/IDN` | 200 | 105,007 B |
| `/signals/IDN.json` | 200 | 63,392 B |
| `/signals/USA` | 200 | 11,164 B |
| `/signals/USA.json` | 200 | 6,306 B |
| `/signals/EMU` | 200 | 10,633 B |
| `/signals/NOPE`, `/signals/idn` | 404 | 2.5 kB |

**IDN** (stale input: satudatascape (missing)):

- Layer 2: 5 components (growth flat, CLI down −0.6421, inflation up +0.35, trade up +9,002,
  BI rate up +1). Shifts: stocks −5, bonds −4, currency +2, none capped.
- Layer 3: 5 signals. `idx_foreign_flow` is −15.89T (−1). Tally: stocks −3, bonds +2.
- Charts:
  - Net foreign: 60 IDX days, 2026-08-12 → 11-05. 49 of the 60 days have no USD bar, every
    day before JISDOR's first fixing here (10-22).
  - JISDOR: 11 fixings, 10-22 → 11-05, 0 carried forward, 0 IDX days without a fixing.
  - IGSYC: 31 tenors on 11-05 against 31 on 10-08. The 10-22 → 11-03 hole does not touch
    either curve.
  - SBN non-resident: 914.8T, +4.5% over the year.
  - JCI: 5,030 on 11-05, −39.7% over the year (8,337 on 2025-11-06). Shown as the file has it.
    The window has single-day moves of 7–11% (2026-01-28, 06-09, 10-16, 10-20) in the stitched
    idxscape + idx-method series, which may be worth a look in P51's stitch.

**USA:** tables only, 7 components, IDR 18,094.00 per USD on 11-05; stale input: idxscape
JISDOR (history from 2026-10-22).

Screenshots of IDN and USA, light and dark, were taken with headless Chrome. They show no
overflow, and the charts read in both themes. Two-colour categorical pair (#2a78d6 / #eb6834
light, #3987e5 / #d95926 dark) passes the dataviz palette validator.

## Decided differently or found

- **Value vs change.** "Value" in the spec is read as the component's newest point, with
  "change over its window" being the file's `value`. Both are shown.
- **Index page.** Added `/signals` (small), linked from nothing until F8.
- **Missing file.** A subject with no file is a 404, not a notice. The subject set *is* the
  files present, so there is nothing to match against. An unreadable file of a known subject
  is a notice.
- **Large values.** Levels above a million are shown as T/B/M. A level in the thousands is
  shown whole (153,942), never in exponent form, which the first live look caught on USA's TIC
  flows.
