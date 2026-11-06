"""End to end: `assist status` serves every UI page over HTTP. The CLI runs in a thread on an
ephemeral port over a tmp repo built from tests/fixtures/ui (out/, out/candidates/,
data/snapshots/, a tmp journal) plus the phase H files (out/layers/ regime, IDN and portfolio,
out/flows/ from the S38 financer fixture), with an empty siblings root, canned doctor results
(no store is opened), no launchd scan and a canned paper report. Every route and its .json twin
is a 200 with the nav and the disclaimer, a bad path or unknown subject is a 404, the
cross-links point at pages that exist, and nothing under the tmp repo changes."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from datetime import date
from pathlib import Path

import httpx
import pytest
from test_flows import NAMES, _db
from test_view_signals import IDN

from assist import cli, doctor, flows, journal, paper, pipeline, status, web
from assist.sources.financer import FinancerSource

UI = Path(__file__).parent / "fixtures" / "ui"
FP = "sha256:" + "c" * 64
HELP = ("local pages: stances, regime, signals, candidates, industries, portfolio, flows, "
        "paper, journal, source health")

PAGES = ["/", "/stance/IDN/bonds", "/stance/IDN/stocks", "/stance/USA/bonds",
         "/stance/GOLD/commodities", "/candidates", "/candidates/IDN", "/candidates/USA",
         "/candidates/AUS", "/industries", "/regime", "/signals", "/signals/IDN",
         "/portfolio", "/flows", "/flows/2026-10", "/paper", "/journal", "/status"]


def _report(until: date) -> paper.PaperReport:
    return paper.PaperReport(
        as_of=until, start=None, legs={"stocks": "JCI", "bonds": "IGSYC 10Y"},
        bond_series="IGSYC.10", benchmark_pct={"stocks": 60.0, "bonds": 40.0},
        stale_inputs=["JCI frozen at 2026-09-30"], benchmark_summary={"weeks": 0, "stale_weeks": 0},
        benchmark=[], segments=[], notes=[])


def _tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    shutil.copytree(UI / "out", root / "out")
    shutil.copytree(UI / "candidates", root / "out" / "candidates")
    shutil.copytree(UI / "snapshots", root / "data" / "snapshots")
    layers = root / "out" / "layers"
    layers.mkdir()
    shutil.copy(UI / "layers" / "regime.json", layers / "regime.json")
    shutil.copy(UI / "portfolio" / "portfolio.json", layers / "portfolio.json")
    (layers / "IDN.json").write_text(json.dumps(IDN))
    flows.write(*flows.build_from(FinancerSource(_db(tmp_path)), NAMES), root / "out")
    j = journal.Journal(root / "journal")
    for d in ("2026-10-06", "2026-10-13"):
        j.record(kind="stance", fingerprint=FP, subject="IDN", asset="bonds", as_of=d,
                 inputs={"d": d}, outputs={"stance": "neutral"})
    siblings = tmp_path / "Projects"
    siblings.mkdir()
    monkeypatch.setattr(pipeline.Paths, "default",
                        classmethod(lambda cls: pipeline.Paths.under(root, root / "notify")))
    monkeypatch.setattr(status, "find_jobs", lambda repos: [])
    monkeypatch.setattr(doctor, "run_doctor", lambda sources, today, http_client=None: [
        doctor.SourceStatus(s.name, s.access, None, "missing") for s in sources])
    monkeypatch.setattr(paper, "paper_track", lambda journal, until: _report(until))
    return root, siblings


def _start(monkeypatch, siblings: Path):
    """Run `assist status --port 0` in a thread; return (base url, app, stop)."""
    box: dict = {}
    started = threading.Event()
    real = web.serve

    def spy(app, port=web.DEFAULT_PORT, ready=None, routes=None, host=web.HOST):
        box["app"], box["routes"] = app, routes

        def on_ready(server):
            box["server"] = server
            started.set()
        return real(app, port, on_ready, routes=routes, host=host)

    monkeypatch.setattr(web, "serve", spy)
    t = threading.Thread(target=lambda: box.setdefault("rc", cli.main(
        ["status", "--port", "0", "--no-http", "--root", str(siblings)])), daemon=True)
    t.start()
    assert started.wait(10), "server did not start"
    host, port = box["server"].server_address[:2]
    assert host == "127.0.0.1"

    def stop() -> int:
        box["server"].shutdown()
        t.join(5)
        return box["rc"]
    return f"http://127.0.0.1:{port}", box, stop


def test_every_page_and_twin_over_http(repo, monkeypatch, capsys):
    root, siblings = repo
    before = _tree(root)
    base, box, stop = _start(monkeypatch, siblings)
    try:
        app = box["app"]
        assert (app.out_dir, app.snapshots_dir, app.journal_path) == (
            root / "out", root / "data" / "snapshots", root / "journal")
        assert box["routes"] is status.ROUTES
        with httpx.Client(trust_env=False, timeout=10) as c:
            for path in PAGES:
                r = c.get(base + path)
                assert r.status_code == 200, (path, r.status_code)
                assert r.headers["content-type"].startswith("text/html")
                for href, _ in web.NAV:
                    assert f'href="{href}"' in r.text, (path, href)
                assert web.DISCLAIMER in r.text, path
                assert "Server error" not in r.text, path
                twin = c.get(base + ("/.json" if path == "/" else path + ".json"))
                assert twin.status_code == 200, (path, twin.status_code)
                assert twin.headers["content-type"] == "application/json"
                twin.json()
            assert c.get(base + "/json").json()["sources"]  # the status alias
            assert c.head(base + "/paper").status_code == 200
            for bad in ("/nope", "/nope.json", "/stance/IDN/..%2Fx", "/candidates/XXX",
                        "/signals/XXX", "/signals/XXX.json", "/signals/regime",
                        "/signals/..%2Fregime", "/flows/1999-01"):
                r = c.get(base + bad)
                assert r.status_code == 404, bad
                assert web.DISCLAIMER in r.text
            journal_page = c.get(base + "/journal.json").json()
            assert journal_page["chain_ok"] and journal_page["records"] == 2
            stance_page = c.get(base + "/stance/IDN/bonds").text
            assert stance_page.count(web.DISCLAIMER) == 1  # the footer only
            # F8 cross-links: each points at a page served above, none at a 404
            assert 'href="/regime"' in c.get(base + "/").text.split("</nav>", 1)[1]
            assert 'href="/signals/IDN"' in stance_page and 'href="/portfolio"' in stance_page
            for path in ("/stance/USA/bonds", "/stance/GOLD/commodities"):  # no layer file
                assert 'href="/signals/' not in c.get(base + path).text, path
            assert '<a href="/signals" class="active">' in c.get(base + "/signals/IDN").text
    finally:
        assert stop() == 0
    assert _tree(root) == before  # read-only: out/, snapshots and the journal unchanged
    printed = capsys.readouterr().out
    for page in ("stances", "regime", "signals", "candidates", "portfolio", "flows", "paper",
                 "journal", "status"):
        assert page in printed


def test_status_help_names_the_pages(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert HELP in " ".join(capsys.readouterr().out.split())
    with pytest.raises(SystemExit):
        cli.main(["status", "--help"])
    assert HELP in " ".join(capsys.readouterr().out.split())
