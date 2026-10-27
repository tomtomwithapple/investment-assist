"""The UI shell: route table, layout and nav, .json twins, 404/500, HEAD, escaping, localhost.
Every server here gets a fake App on a temp dir and port 0: no real store, path or network."""

from __future__ import annotations

import json
import re
import threading
from datetime import date
from pathlib import Path

import httpx
import pytest

from assist import web

EVIL = "<script>alert(1)</script>"


def _app(tmp_path: Path) -> web.App:
    return web.App(out_dir=tmp_path / "out", snapshots_dir=tmp_path / "snapshots",
                   journal_path=tmp_path / "journal", paper=lambda until: {"until": until},
                   health=lambda: {"ok": True})


def _hello(app, m):
    name = m.group(1)
    if name == "nobody":
        return None
    return web.View(f"Hello {name}", f"<p>hi {web.esc(name)}</p>", {"name": name})


def _boom(app, m):
    raise ValueError(EVIL)


ROUTES = [(re.compile(r"^/hello/([^/]+)$"), _hello), (re.compile(r"^/boom$"), _boom),
          *web.ROUTES]


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("web")
    started, box = threading.Event(), {}

    def ready(server):
        box["server"] = server
        started.set()

    t = threading.Thread(target=web.serve, args=(_app(tmp_path),),
                         kwargs={"port": 0, "ready": ready, "routes": ROUTES}, daemon=True)
    t.start()
    assert started.wait(5)
    server = box["server"]
    box["host"] = server.server_address[0]
    yield f"http://127.0.0.1:{server.server_address[1]}", box
    server.shutdown()
    t.join(5)


def _get(url: str, method: str = "GET") -> httpx.Response:
    return httpx.request(method, url, trust_env=False, follow_redirects=False)


def test_listens_on_localhost_only(base):
    _, box = base
    assert box["host"] == "127.0.0.1" == web.HOST


def test_route_match_renders_in_layout(base):
    url, _ = base
    r = _get(url + "/hello/ann?x=1")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    assert "<title>Hello ann</title>" in r.text and "<p>hi ann</p>" in r.text


def test_json_twin_returns_view_data(base):
    url, _ = base
    r = _get(url + "/hello/ann.json")
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    assert r.json() == {"name": "ann"}


def test_json_twin_serialises_dates(tmp_path):
    got = web.to_json({"d": date(2026, 10, 27), "p": tmp_path})
    assert json.loads(got) == {"d": "2026-10-27", "p": str(tmp_path)}


@pytest.mark.parametrize("path", ["/nope", "/hello/nobody", "/hello/a/b", "/nope.json"])
def test_unknown_or_none_is_404_in_layout(base, path):
    url, _ = base
    r = _get(url + path)
    assert r.status_code == 404
    assert "Not found" in r.text and web.DISCLAIMER in r.text and 'href="/status"' in r.text


def test_handler_error_is_500_with_message_escaped(base):
    url, _ = base
    r = _get(url + "/boom")
    assert r.status_code == 500
    assert "ValueError" in r.text and EVIL not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text


def test_path_in_404_is_escaped(base):
    url, _ = base
    r = _get(url + "/%3Cscript%3E")
    assert r.status_code == 404 and "<script>" not in r.text


def test_value_from_view_is_escaped_in_title(base):
    url, _ = base
    r = _get(url + "/hello/" + "%3Cscript%3E")
    assert r.status_code == 200 and "<script>" not in r.text
    assert "<title>Hello &lt;script&gt;</title>" in r.text


def test_head_sends_headers_without_body(base):
    url, _ = base
    get, head = _get(url + "/hello/ann"), _get(url + "/hello/ann", "HEAD")
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == get.headers["content-length"]
    assert _get(url + "/nope", "HEAD").status_code == 404


def test_other_methods_are_refused(base):
    url, _ = base
    assert _get(url + "/hello/ann", "POST").status_code == 501


def test_root_is_the_overview(base):
    url, _ = base
    r = _get(url + "/")
    assert r.status_code == 200 and "location" not in r.headers
    assert '<a href="/" class="active">Overview</a>' in r.text
    for href, label in web.NAV:
        assert f'href="{href}"' in r.text and label in r.text


def test_candidates_is_served_over_http(base):
    url, _ = base  # the temp out/ has no candidates/: a 200 page with a notice, never a 500
    r = _get(url + "/candidates")
    assert r.status_code == 200
    assert '<a href="/candidates" class="active">Candidates</a>' in r.text
    assert "no candidate lists" in r.text
    assert _get(url + "/candidates/IDN").status_code == 404


def test_layout_has_nav_disclaimer_and_dark_mode():
    page = web.layout(EVIL, "<p>body</p>", "/paper")
    for href, label in web.NAV:
        assert f'href="{href}"' in page and label in page
    assert '<a href="/paper" class="active">Paper</a>' in page
    assert web.DISCLAIMER == "Heuristic, not investment advice." and web.DISCLAIMER in page
    assert "prefers-color-scheme: dark" in page and "--good-bg" in page
    assert EVIL not in page and "<p>body</p>" in page


@pytest.mark.parametrize("path, active", [("/", "/"), ("/status", "/status"),
                                          ("/candidates/IDN", "/candidates"), ("/x", None)])
def test_active_nav(path, active):
    assert web.active_nav(path) == active


def test_chip_escapes_and_tones():
    assert web.chip("<b>", "bad") == '<span class="chip bad">&lt;b&gt;</span>'


def test_app_defaults_are_the_real_paths():
    from assist import pipeline
    paths = pipeline.Paths.default()
    app = web.App(health=lambda: None)
    assert (app.out_dir, app.snapshots_dir, app.journal_path) == (
        paths.out, paths.snapshots, paths.journal)
    assert callable(app.paper)


def test_app_default_paper_uses_its_journal(tmp_path, monkeypatch):
    from assist import paper
    seen = {}

    def fake(journal=None, until=None, **kw):
        seen["root"], seen["until"] = journal.root, until
        return "report"
    monkeypatch.setattr(paper, "paper_track", fake)
    app = web.App(journal_path=tmp_path / "j", health=lambda: None)
    assert app.paper(date(2026, 10, 27)) == "report"
    assert seen == {"root": tmp_path / "j", "until": date(2026, 10, 27)}
