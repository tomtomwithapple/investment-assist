# P44-ui-paper — PLAN S27: UI paper track and journal chain check

`src/assist/views/paper.py` serves `/paper` and `/journal`. `web.ROUTES` maps `^/paper$` to
`web._paper` and `^/journal$` to `web._journal`, and both import the view inside the handler.
`web.App` gained two fields:
- `today` (default `date.today`): the day `/paper` reports up to, so tests can move it;
- `cache` (a dict, not part of `repr` or `==`): per-view caches.

- **/paper.** `report_for(app, day)` returns the report cached under `app.cache["paper"]` when
  the key `(day, journal mtime_ns)` matches. A missing journal file gives an mtime of None. On a
  miss it calls `app.paper(day)`. A module lock makes sure only one build runs at a time.
  - Any exception from the callable is a notice, `paper track unavailable: <Type>: <msg>`, and
    the page still renders. That includes SourceUnavailable and a DuckDB lock error. Errors are
    **not** cached, so the next reload tries again: a lock is transient.
  - A return value that is not a PaperReport (AttributeError, KeyError or TypeError while
    rendering) is also a notice, never a 500.
- **The page itself:**
  - benchmark card: the 60/40 split, start → as_of, weeks scored, stale weeks, cumulative,
    annualised, volatility (unsigned), the legs and the bond series;
  - **worst week**: the minimum of `m.benchmark` over the scored benchmark marks, with its
    week end and the label "computed here from the weekly marks";
  - the last scored week, in `brief.paper_lines`' wording;
  - segments table: short fingerprint, span `first_as_of … last_as_of`, until (or "current"),
    decisions, weeks, stale weeks, portfolio, benchmark, active, hit rate, and "nothing scored
    yet" when weeks is 0. Segment notes are listed below the table. With no segments the card
    reads "No stance history in the journal yet: benchmark marks only.";
  - stale reasons: `report.stale_inputs`, then each distinct `mark.stale` (benchmark marks
    first, then the segments' marks);
  - the notes, and a footer line saying when the report was built.
- **/paper.json** is `{as_of, error, report: to_dict(marks=False), worst_week, stale_reasons}`.
- **/journal** works as `cli._journal` does. `verify()` gives the count, or ValueError gives
  "chain BROKEN: reason" with a bad chip, and the count then comes from the non-blank lines. Then
  comes `segments()` per model: records, stances and the span of `as_of`.
  - A line that is not JSON breaks the chain and makes the per-model table a notice.
  - A missing file is the notice "no journal yet".
  - **/journal.json** is `{path, records, chain, chain_ok, models, problems}`.
  - Nothing ever writes the journal.

## Tests

`tests/test_view_paper.py` has 22 tests. The paper report is a canned `PaperReport` with
`Mark`/`SegmentScore`, and the journal is a tmp one built with `journal.Journal.record`. An
autouse fixture asserts the journal file is byte-identical after every test. They cover:
- the layout and nav;
- the summary and the computed worst week, and the worst week as n/a with nothing scored;
- the segments, and no segments;
- the stale reasons, in order and deduplicated;
- the `.json` twin;
- errors as a notice (RuntimeError, SourceUnavailable locked, OSError lock), with the error
  escaped and not cached, and an unreadable report as a notice;
- the cache: a second request does not call paper again until the day moves or the journal
  mtime moves, and with no journal file nothing is created;
- `<script>` escaped in the fingerprint, legs, stale input, mark stale and notes;
- the journal: chain ok with records per model, its twin, a broken chain (an edited line, with
  the file unchanged afterwards), an unparseable line, a missing file, and a hand-edited
  `<script>` fingerprint escaped.

`tests/test_web.py` gained one HTTP test for `/paper`, HEAD `/paper`, `/journal` and
`/journal.json` over the fake App. The fake returns a dict, so `/paper` shows the "unreadable
paper report" notice.

- Red: the first run failed on `App(today=...)` (no such field) and then on missing routes.
  Green: 22 passed.
- Accept: 64 passed, ruff clean (also on both test files).
- Full suite: 1232 passed.

## Live run (2026-10-27, `uv run assist status --port 8799`, real journal)

| Request | Code | Size | Time |
|---|---|---|---|
| GET /paper (first, builds the report) | 200 | 6,107 B | 81 ms |
| GET /paper (second, cached) | 200 | 6,107 B | 0.9 ms |
| GET /paper.json | 200 | 5,129 B | 1.0 ms |
| HEAD /paper | 200 | | 0.8 ms |
| GET /journal | 200 | 3,667 B | 105 ms |
| GET /journal.json | 200 | 1,940 B | 103 ms |

`journal/decisions.jsonl` had the same sha before and after. The server log was empty, and once
the server was stopped a curl got no answer.

- **/paper**:
  - benchmark 60% JCI / 40% SBN leg from 2026-10-06 to 2026-10-27: **0 weeks scored, 2
    stale**; cumulative, annualised, volatility and worst week all n/a;
  - bond series IGSYC.10, from the IGSYC 10Y yield (idxscape PHEI);
  - 8 model segments, each with 0 weeks scored and 0 stale ("nothing scored yet");
  - stale reasons: "JCI frozen at 2026-09-30 (idx-method index CSVs; no JCI fetcher)",
    "IGSYC.10 ends 2026-10-26" and "JCI: no close after 2026-09-30 (…)".
- **/journal**: chain ok, 865 records, 8 models. Records / stances per model: 50/49, 53/49,
  65/49 (all 2026-10-23); 69/49, 138/98, 70/49, 210/147, 210/147 (all 2026-10-27).

## Findings

- **The paper track cannot score a single week today.** The JCI leg ends 2026-09-30 (idx-method
  CSVs frozen), and the IGSYC 10Y leg starts in October, so `start` (where both legs have data)
  is 2026-10-06. That is already past the last JCI close, so the legs never overlap. Coverage gap
  2b (a JCI fetcher) blocks paper tracking completely, not just its recent weeks.
- **Same-day segments.** Several fingerprints made their first decision on the same day (three
  on 10-23, five on 10-27). Every segment but the last has `until` equal to its own first
  decision, so it rules no week by construction. The page shows this honestly (until = first
  day, 0 weeks), but a model change within a day leaves only the last one scoreable.
- **The first build was 81 ms here, not the planned 0.5 s.** dbnomics was not opened because
  the PHEI 10Y was present. The cache still matters for HEAD and for days when dbnomics is the
  fallback (its lock is mutual).
- `/journal` costs about 0.1 s for 865 records. That is two passes, `verify` and `segments`.
  It is not cached: the notes ask for the chain to be checked on each request.
- No contradiction with the plan. `App.today` and `App.cache` are new fields that the notes did
  not name. They live in `web.py`, which this slice owns.
