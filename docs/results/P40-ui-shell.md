# P40-ui-shell — PLAN S23: UI shell, router, /status

`src/assist/web.py` holds the server loop and the shell. `status.py` imports it, and `web` never
imports `status`.

- `App(out_dir, snapshots_dir, journal_path, paper, health)`: the paths default to
  `pipeline.Paths.default()` (`out/`, `data/snapshots/`, `journal/`), imported lazily.
  `paper(until)` defaults to `paper.paper_track(journal=Journal(app.journal_path), until=until)`.
- `View(title, html, data, redirect=None)`. `html` is the page body and `layout` wraps it.
  `redirect` is a 302, which `/` uses until S24.
- `layout(title, body, active)` builds the nav (Overview, Candidates, Paper, Journal, Status;
  `active_nav` marks the section a path falls under) and puts the disclaimer "Heuristic, not
  investment advice." in the footer. It carries `status.PAGE`'s CSS tokens and dark mode, plus
  `nav`, `.notice`, `.chip.muted` and `footer` styles. The title is escaped.
- Shared helpers: `esc` (`html.escape`), `chip(text, tone)`, `notice(text)` and `to_json` (dates,
  Paths, dataclasses and `.to_json()` objects).
- `dispatch(app, routes, path)`: it strips the query and URL-decodes the path, maps
  `/json` → `/status.json`, then strips a trailing `.json` and returns `View.data` as JSON.
  None or no match gives a 404 page in the layout with the path escaped. A handler exception gives
  a 500 page with the error and the last traceback frames escaped.
- `serve(app, port, ready, routes)`: 127.0.0.1 only, with `Cache-Control: no-store`. It answers
  GET and HEAD (HEAD sends the same headers and Content-Length, with no body). Any other method
  gets http.server's 501. A client that hangs up mid-build no longer dumps a traceback.
- `status.py`:
  - `body(snap)` is the old page body, with the json link now `/status.json`;
  - `render(snap)` is `web.layout("Assist Status", body, "/status")`;
  - `page` is the `/status` handler;
  - `ROUTES = [/status, *web.ROUTES]`;
  - `serve(build, port, ready, *, app=None)` is a thin wrapper over `web.serve`, so `cli._status`
    is unchanged.

  `PAGE`, `json` and the http handler are gone from `status.py`.
- `src/assist/views/__init__.py`: the empty package for S24–S27.

Tests: `tests/test_web.py` covers matching, the `.json` twin, 404 (unknown path, a handler
returning None, too many segments, `/nope.json`), 500 with `<script>` escaped, an escaped path and
title, HEAD, POST 501, `/` 302, nav and disclaimer, `active_nav`, `chip`, the real App defaults
and the default paper using the App's journal. It gives 22 passed. The serve test in
`tests/test_status.py` now checks `/status`, `/status.json` and `/json` and asserts nothing about
`/`. Accept gives 40 passed and ruff is clean. The full suite gives 1155 passed.

## Live run (2026-10-27, `uv run assist status --port 8799`)

| Request | Code | Size | Time |
|---|---|---|---|
| GET /status | 200 | 14,801 B | 6.2 s (first load), 4.2 s after |
| GET /status.json | 200 | 16,437 B | 2.8 s |
| GET /json | 200 | 16,437 B | 2.8 s |
| GET / | 302 → /status | 0 B | <1 ms |
| GET /nope | 404 | 2,464 B | <1 ms |
| GET /nope.json | 404 | 2,469 B | <1 ms |
| GET /%3Cscript%3E | 404 (escaped) | 2,472 B | <1 ms |
| HEAD /status | 200, Content-Length 14801, no body | 0 B | 2.8 s |
| POST /status | 501 | | |

The page showed `<title>Assist Status</title>`, the nav with Status active and the disclaimer
footer. The summary read "14 sources: 1 missing, 2 stale, 11 present · 26 jobs, 1 failed or
down". Once the server was stopped, a curl got no answer.

## Findings

- **HEAD builds the whole page.** It costs the same as GET (about 3 s here, mostly the doctor
  probes), because Content-Length needs the body. That is fine for a local page. A later view
  that is expensive (`/paper`) gets the same cost on HEAD.
- **A client timeout during the build used to print a BrokenPipe traceback** to the server's
  stderr. My first readiness probe (`curl -m 1`) triggered it. The old `status.serve` had the same
  gap. The write is now wrapped in `contextlib.suppress`.
- Paths are URL-decoded before matching, so `/stance/IDN/..%2Fx` reaches S25's handler as
  `/stance/IDN/../x`. S25 matches against the loaded stances and never builds a path, so the
  decoded form is what it must reject.
- No contradiction with the plan.
