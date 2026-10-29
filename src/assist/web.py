"""The local UI shell: one read-only server on 127.0.0.1 with a shared layout and a route table.

A route is (regex, handler(app, match) -> View | None). A trailing `.json` is stripped before
matching and returns the view's data as JSON (the page's twin); None or no match is a 404 page, a
handler error a 500 page with the error escaped. GET and HEAD only. Every page is rebuilt on each
request and shows the same nav and disclaimer; every value read from a file goes through `esc`.
Views live in `assist.views.*` and `assist.status`; they import this module at load time, and this
module imports a view only inside its route handler.
"""

from __future__ import annotations

import contextlib
import html
import json
import re
import traceback
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

HOST = "127.0.0.1"
DEFAULT_PORT = 8790
DISCLAIMER = "Heuristic, not investment advice."
NAV = (("/", "Overview"), ("/candidates", "Candidates"), ("/industries", "Industries"),
       ("/paper", "Paper"),
       ("/journal", "Journal"), ("/status", "Status"))
ALIASES = {"/json": "/status.json"}

esc = html.escape


def _paths():
    from assist import pipeline  # heavy; only when a default path is needed
    return pipeline.Paths.default()


@dataclass
class App:
    """What the views read: the run's paths, the paper report and the health snapshot."""

    out_dir: Path = field(default_factory=lambda: _paths().out)
    snapshots_dir: Path = field(default_factory=lambda: _paths().snapshots)
    journal_path: Path = field(default_factory=lambda: _paths().journal)
    paper: Callable[[date], Any] | None = None  # until -> report; default paper.paper_track
    health: Callable[[], Any] | None = None  # the `assist status` snapshot builder
    today: Callable[[], date] = date.today  # the day /paper reports up to
    cache: dict = field(default_factory=dict, repr=False, compare=False)  # per-view caches

    def __post_init__(self) -> None:
        if self.paper is None:
            def paper(until: date) -> Any:
                from assist import paper as paper_mod
                from assist.journal import Journal
                return paper_mod.paper_track(journal=Journal(self.journal_path), until=until)
            self.paper = paper


@dataclass
class View:
    title: str
    html: str  # the page body, wrapped by `layout`
    data: Any = None  # the .json twin
    redirect: str | None = None  # a 302 to this location instead of a page (none use it yet)


Handler = Callable[[App, "re.Match[str]"], View | None]
Route = tuple["re.Pattern[str]", Handler]


# ---------------- layout ----------------


def chip(text: str, tone: str) -> str:
    """tone: good | warn | bad | muted."""
    return f'<span class="chip {tone}">{esc(text)}</span>'


def notice(text: str) -> str:
    return f'<p class="notice">{esc(text)}</p>'


def active_nav(path: str) -> str | None:
    for href, _ in NAV:
        if path == href or (href != "/" and path.startswith(href + "/")):
            return href
    return None


def layout(title: str, body: str, active: str | None) -> str:
    nav = " ".join(f'<a href="{h}"{" class=\"active\"" if h == active else ""}>{label}</a>'
                   for h, label in NAV)
    return PAGE.format(title=esc(title), nav=nav, body=body, disclaimer=DISCLAIMER)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f7f7f5; --card:#fff; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e3df;
  --good:#1f7a3f; --good-bg:#e3f3e8; --warn:#8a5a00; --warn-bg:#fbf0d9;
  --bad:#b3261e; --bad-bg:#fbe4e2; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141413; --card:#1e1e1c; --fg:#ececea;
  --muted:#9a9a94; --line:#33332f; --good:#7bd69a; --good-bg:#1d3a27; --warn:#f0c46a;
  --warn-bg:#3d2f12; --bad:#ff8a80; --bad-bg:#47201d; }} }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
  font:14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ max-width:980px; margin:0 auto; }}
nav {{ display:flex; gap:14px; flex-wrap:wrap; margin:0 0 14px; }}
nav a {{ color:var(--muted); text-decoration:none; }}
nav a.active {{ color:var(--fg); font-weight:600; }}
a {{ color:inherit; }}
h1 {{ font-size:20px; margin:0 0 4px; }}
h2 {{ font-size:15px; margin:0; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; margin:12px 0; overflow-x:auto; }}
.card header {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
.muted {{ color:var(--muted); }}
.notice {{ background:var(--warn-bg); color:var(--warn); border-radius:8px; padding:8px 12px; }}
.chip {{ font-size:12px; padding:1px 8px; border-radius:999px; white-space:nowrap; }}
.good {{ color:var(--good); background:var(--good-bg); }}
.warn {{ color:var(--warn); background:var(--warn-bg); }}
.bad {{ color:var(--bad); background:var(--bad-bg); }}
.chip.muted {{ background:var(--line); }}
table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
th, td {{ text-align:left; padding:5px 8px 5px 0; border-top:1px solid var(--line);
  vertical-align:top; }}
th {{ font-weight:500; color:var(--muted); font-size:12px; }}
code {{ font-size:12px; }}
.tail {{ color:var(--muted); font-size:12px; word-break:break-word; white-space:pre-wrap;
  margin:2px 0 0; }}
footer {{ color:var(--muted); font-size:12px; margin-top:24px; }}
</style></head>
<body><main>
<nav>{nav}</nav>
{body}
<footer>{disclaimer} Read-only, local only.</footer>
</main></body></html>
"""


# ---------------- routes ----------------


def _overview(app: App, m: re.Match[str]) -> View:
    from assist.views import overview  # views import this module at load time, so import late
    return overview.page(app, m)


def _stance(app: App, m: re.Match[str]) -> View | None:
    from assist.views import stance
    return stance.page(app, m)


def _candidates(app: App, m: re.Match[str]) -> View:
    from assist.views import candidates
    return candidates.index(app, m)


def _market(app: App, m: re.Match[str]) -> View | None:
    from assist.views import candidates
    return candidates.page(app, m)


def _industries(app: App, m: re.Match[str]) -> View:
    from assist.views import industries
    return industries.index(app, m)


def _industry(app: App, m: re.Match[str]) -> View | None:
    from assist.views import industries
    return industries.page(app, m)


def _paper(app: App, m: re.Match[str]) -> View:
    from assist.views import paper
    return paper.page(app, m)


def _journal(app: App, m: re.Match[str]) -> View:
    from assist.views import paper
    return paper.journal(app, m)


ROUTES: list[Route] = [(re.compile(r"^/$"), _overview),
                       (re.compile(r"^/stance/([^/]+)/([^/]+)$"), _stance),
                       (re.compile(r"^/candidates$"), _candidates),
                       (re.compile(r"^/candidates/([^/]+)$"), _market),
                       (re.compile(r"^/industries$"), _industries),
                       (re.compile(r"^/industries/([^/]+)$"), _industry),
                       (re.compile(r"^/paper$"), _paper),
                       (re.compile(r"^/journal$"), _journal)]


def to_json(data: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        if isinstance(o, Path):
            return str(o)
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)
        if hasattr(o, "to_json"):
            return o.to_json()
        raise TypeError(f"not JSON serialisable: {type(o).__name__}")
    return json.dumps(data, indent=2, default=default)


@dataclass
class Response:
    status: int
    body: str
    ctype: str = "text/html; charset=utf-8"
    location: str | None = None


def dispatch(app: App, routes: Sequence[Route], raw_path: str) -> Response:
    path = unquote(raw_path.split("?")[0])
    path = ALIASES.get(path, path)
    as_json = path.endswith(".json")
    path = path.removesuffix(".json") if as_json else path
    active = active_nav(path)
    try:
        view = next((h(app, m) for rx, h in routes if (m := rx.match(path))), None)
    except Exception as e:  # noqa: BLE001 - one broken view is a 500 page, never a dead server
        tb = traceback.format_exc(limit=-3)
        body = (f"<h1>Server error</h1><p><code>{esc(type(e).__name__)}: {esc(str(e))}</code></p>"
                f'<pre class="tail">{esc(tb)}</pre>')
        return Response(500, layout("Assist error", body, active))
    if view is None:
        body = f'<h1>Not found</h1><p class="muted">No page at <code>{esc(raw_path)}</code>.</p>'
        return Response(404, layout("Assist not found", body, active))
    if view.redirect:
        return Response(302, "", location=view.redirect)
    if as_json:
        return Response(200, to_json(view.data), "application/json")
    return Response(200, layout(view.title, view.html, active))


# ---------------- server ----------------


def serve(app: App, port: int = DEFAULT_PORT,
          ready: Callable[[ThreadingHTTPServer], None] | None = None,
          routes: Sequence[Route] | None = None, host: str = HOST) -> None:
    """Serve `routes` (default ROUTES) on `host` (default 127.0.0.1) until interrupted. `ready`
    gets the server."""
    table = list(ROUTES if routes is None else routes)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, with_body: bool) -> None:
            r = dispatch(app, table, self.path)
            data = r.body.encode()
            self.send_response(r.status)
            if r.location:
                self.send_header("Location", r.location)
            self.send_header("Content-Type", r.ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if with_body:
                # the client may hang up while the page is built
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 - http.server's name
            self._send(True)

        def do_HEAD(self) -> None:  # noqa: N802
            self._send(False)

        def log_message(self, fmt: str, *args) -> None:
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    if ready is not None:
        ready(server)
    try:
        server.serve_forever()
    finally:
        server.server_close()
