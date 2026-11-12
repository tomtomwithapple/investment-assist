"""The baseline board page (/frameworks, S94): rows ranked on excess total return vs the pool,
n_independent beside each figure, the verdict-window note, gate chips, survivorship notes,
escaping, the .json twin and a missing or invalid file. A temp out/ only."""

from __future__ import annotations

import json
import re

from test_framework_board import sample_payload

from assist import framework_board as fb
from assist import web
from assist.eval.picks_report import WINDOWS
from assist.views import frameworks

EVIL = "<script>alert(1)</script>"


def _app(tmp_path, payload=None) -> web.App:
    out = tmp_path / "out"
    if payload is not None:
        fb.write(payload, out)
    return web.App(out_dir=out, snapshots_dir=tmp_path / "s", journal_path=tmp_path / "j")


def _view(app) -> web.View:
    return frameworks.page(app, re.match(r"^/frameworks$", "/frameworks"))


def test_rows_rank_on_3m_excess_vs_pool_with_n_independent():
    p = sample_payload()
    p["frameworks"].reverse()  # file order must not matter
    rows = frameworks.rows(p)
    assert [r["name"] for r in rows] == ["alpha", "beta"]
    a = rows[0]
    assert a["gate"] == "passed" and rows[1]["gate"] == "failed"
    c = a["cells"]["3m"]
    assert c["rank"] == 1 and c["n_independent"] == 4 and c["verdict_window"]
    assert c["excess_pool"] > 0 and c["excess_jci"] > 0
    assert not a["cells"]["1y"]["verdict_window"]
    assert a["cells"]["3y"]["excess_pool"] is None


def test_a_framework_without_figures_sorts_last():
    p = sample_payload()
    new = type("F", (), {"name": "aaa_new", "gate": "untested"})()
    p["frameworks"].insert(0, fb._no_replay(new, WINDOWS, "no replay yet"))
    assert [r["name"] for r in frameworks.rows(p)] == ["alpha", "beta", "aaa_new"]


def test_page_shows_figures_beside_independent_windows_and_the_verdict_note(tmp_path):
    p = sample_payload()
    v = _view(_app(tmp_path, p))
    assert "Only 1m, 3m and 6m can carry a verdict" in v.html
    a3 = next(w for w in p["frameworks"][0]["windows"] if w["window"] == "3m")
    assert f"{100 * a3['excess_pool']:+.1f}pt" in v.html
    assert "4 indep." in v.html
    assert "descriptive" in v.html and "can judge" in v.html
    assert "passed" in v.html and "failed" in v.html
    assert "1 of 1 delisted names ever enter the pool" in v.html
    assert v.data["rows"][0]["name"] == "alpha"
    assert v.data["verdict_note"] == p["verdict_note"]
    json.dumps(v.data)


def test_page_escapes_file_values(tmp_path):
    p = sample_payload()
    p["frameworks"][0]["name"] = EVIL
    p["frameworks"][0]["notes"] = [EVIL]
    p["stale_inputs"] = [EVIL]
    v = _view(_app(tmp_path, p))
    assert EVIL not in v.html and "&lt;script&gt;" in v.html


def test_missing_and_invalid_file(tmp_path):
    v = _view(_app(tmp_path))
    assert "assist frameworks" in v.html and v.data["rows"] == []
    (tmp_path / "out" / "frameworks").mkdir(parents=True)
    (tmp_path / "out" / "frameworks" / "IDN.json").write_text("{nope")
    v = _view(_app(tmp_path))
    assert "not valid JSON" in v.html and v.data["rows"] == []


def test_route_and_nav():
    assert ("/frameworks", "Frameworks") in web.NAV
    assert any(rx.match("/frameworks") for rx, _ in web.ROUTES)
