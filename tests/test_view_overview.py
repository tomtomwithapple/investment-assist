"""The overview page (/): regime and dollar banner, country x asset grid, commodities, stale
markers, problems and the empty state. Reads tests/fixtures/ui/out/ (out/ layout) or a temp copy;
no real out/, store or network."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from assist import web

FIXTURE = Path(__file__).parent / "fixtures" / "ui" / "out"
EVIL = "<script>alert(1)</script>"


def _app(out_dir: Path) -> web.App:
    return web.App(out_dir=out_dir, snapshots_dir=out_dir / "none", journal_path=out_dir / "none",
                   paper=lambda until: None, health=lambda: None)


def _get(out_dir: Path, path: str = "/background") -> web.Response:
    return web.dispatch(_app(out_dir), web.ROUTES, path)


@pytest.fixture
def copy(tmp_path) -> Path:
    out = tmp_path / "out"
    shutil.copytree(FIXTURE, out)
    return out


def _row(html: str, subject: str) -> str:
    m = re.search(rf'<tr data-subject="{subject}">(.*?)</tr>', html, re.S)
    assert m, f"no row for {subject}"
    return m.group(1)


def test_background_is_the_old_overview_not_a_redirect():
    r = _get(FIXTURE)
    assert r.status == 200 and r.location is None
    assert "<title>Assist Background</title>" in r.body
    assert '<a href="/background" class="active">Background</a>' in r.body
    assert web.DISCLAIMER in r.body


def test_banner_as_of_regime_dollar_and_counts():
    body = _get(FIXTURE).body
    banner = re.search(r'<section class="card banner">(.*?)</section>', body, re.S).group(1)
    assert "2026-10-13" in banner
    assert "Regime: <strong>neutral</strong>" in banner  # one value
    # mixed, grouped by value as the brief prints it
    assert ("Dollar: mixed, <strong>flat</strong> (IDN bonds, GOLD commodities); "
            "<strong>up</strong> (IDN stocks, USA bonds)") in banner
    assert "1 overweight" in banner and "1 neutral" in banner and "2 underweight" in banner
    assert "avoid" not in banner


def test_grid_rows_columns_and_cells():
    body = _get(FIXTURE).body
    grid = re.search(r'<table class="grid">(.*?)</table>', body, re.S).group(1)
    assert re.findall(r"<th>(\w+)</th>", grid)[1:] == ["stocks", "bonds", "currency"]
    subjects = re.findall(r'<tr data-subject="([A-Z0-9_]+)">', grid)
    assert subjects == ["IDN", "USA"]  # IDN first; GOLD is not a country row
    idn = _row(grid, "IDN")
    assert '<a href="/stance/IDN/bonds"><span class="chip good">overweight</span></a>' in idn
    assert '<span class="chip muted">neutral</span>' in idn
    assert "68" in idn and "0.74" in idn and "52" in idn and "0.61" in idn
    usa = _row(grid, "USA")
    assert '<span class="chip bad">underweight</span>' in usa
    cells = re.findall(r"<td[^>]*>(.*?)</td>", usa, re.S)
    assert cells[0].strip() == "USA"
    assert cells[1].strip() == "-" and cells[3].strip() == "-"  # no USA stocks, no USA currency


def test_stale_marker_only_on_cells_with_stale_inputs():
    body = _get(FIXTURE).body
    idn = _row(body, "IDN")
    stocks, bonds = re.findall(r"<td[^>]*>(.*?)</td>", idn, re.S)[1:3]
    assert "stale" in stocks and "jkse_daily.csv" in stocks  # the input names as a tooltip
    assert "stale" not in bonds


def test_commodities_in_their_own_table():
    body = _get(FIXTURE).body
    table = re.search(r'<table class="commodities">(.*?)</table>', body, re.S).group(1)
    assert '<a href="/stance/GOLD/commodities">GOLD</a>' in table
    assert '<span class="chip bad">underweight</span>' in table and "31.1" in table
    assert "GOLD" not in re.search(r'<table class="grid">(.*?)</table>', body, re.S).group(1)


def test_json_twin_is_the_rows_used():
    r = _get(FIXTURE, "/background.json")
    assert r.status == 200 and r.ctype == "application/json"
    data = json.loads(r.body)
    assert data["as_of"] == "2026-10-13"
    assert data["regime"] == {"neutral": ["IDN stocks", "IDN bonds", "GOLD commodities",
                                          "USA bonds"]}
    assert data["columns"] == ["stocks", "bonds", "currency"]
    usa = next(r for r in data["countries"] if r["subject"] == "USA")
    assert usa["cells"]["currency"] is None and usa["cells"]["stocks"] is None
    assert usa["cells"]["bonds"] == {"subject": "USA", "asset": "bonds", "stance": "underweight",
                                     "score": 41, "confidence": 0.55,
                                     "stale_inputs": ["financer (locked)"],
                                     "href": "/stance/USA/bonds"}
    assert [c["subject"] for c in data["commodities"]] == ["GOLD"]
    assert data["problems"] == []


def test_counts_cover_every_stance():
    data = json.loads(_get(FIXTURE, "/background.json").body)
    assert data["counts"] == {"overweight": 1, "neutral": 1, "underweight": 2, "avoid": 0}


@pytest.mark.skipif(sys.platform == "win32", reason="'<' is not allowed in Windows file names")
def test_problems_are_a_notice_and_values_are_escaped(copy):
    (copy / "IDN" / "<script>x.json").write_text("{not json")
    usa = json.loads((copy / "USA" / "bonds.json").read_text())
    usa["stale_inputs"] = [EVIL]
    (copy / "USA" / "bonds.json").write_text(json.dumps(usa))
    r = _get(copy)
    assert r.status == 200
    assert EVIL not in r.body and "<script>" not in r.body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.body  # stale tooltip
    assert '<p class="notice">IDN/&lt;script&gt;x.json: not readable JSON' in r.body
    problems = json.loads(_get(copy, "/background.json").body)["problems"]
    assert problems[0].startswith("IDN/<script>x.json")


def test_empty_out_says_run_assist_run(tmp_path):
    for out in (tmp_path / "missing", tmp_path):
        r = _get(out)
        assert r.status == 200
        assert "no stances in out/ yet: run `assist run`" in r.body
        assert "<table" not in r.body
        data = json.loads(_get(out, "/background.json").body)
        assert data["countries"] == [] and data["commodities"] == [] and data["as_of"] is None


def test_banner_links_to_the_regime_page():
    body = _get(FIXTURE).body
    banner = re.search(r'<section class="card banner">(.*?)</section>', body, re.S).group(1)
    assert 'href="/regime"' in banner
