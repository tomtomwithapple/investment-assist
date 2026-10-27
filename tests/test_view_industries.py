"""The industries pages (/industries and /industries/<id>): the sector tables with median and
average, the chart (one bar and one ring per name and category, tier groups, the legend), the
category tables with benchmarks and deviations, stars from out/candidates/IDN.json, the .json
twins, a missing or invalid file, escaping and the 404 cases. A temp out/ written from a
synthetic `Comparison` through `peers.build`; no real out/, store or network."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from assist import web
from assist.candidates import peers
from assist.sources.idxmethod_comparison import Comparison

EVIL = "<script>alert(1)</script>"
PE, PBV, YIELD, ROE, DER, MKTCAP = 2891, 2896, 2915, 1461, 1508, 2892


def _payload() -> dict:
    c = Comparison(date=date(2026, 10, 26))
    rows = {
        "AAAA": ("bank1", "Keuangan", {PE: 5.0, PBV: 1.0, YIELD: 10.0, ROE: 20.0, DER: 0.5,
                                       MKTCAP: 100e12}),
        "BBBB": ("bank1", "Keuangan", {PE: 10.0, PBV: 2.0, YIELD: 5.0, ROE: 10.0, MKTCAP: 5e12}),
        "CCCC": ("bank1", "Keuangan", {PE: 20.0, PBV: 4.0, ROE: -3.0, MKTCAP: 0.5e12}),
        "XEVL": ("other", EVIL, {PE: 8.0}),
    }
    for sym, (ind, sector, vals) in rows.items():
        c.ratios[sym], c.industry[sym], c.sectors[sym] = dict(vals), ind, sector
        c.names[sym] = EVIL if sym == "XEVL" else f"{sym} Tbk"
        c.industry_avg[sym], c.sector_avg[sym] = {PE: 11.0}, {PE: 12.0}
    return peers.build(c, date(2026, 10, 27))


@pytest.fixture
def out(tmp_path) -> Path:
    o = tmp_path / "out"
    peers.write(_payload(), o)
    (o / "candidates").mkdir()
    (o / "candidates" / "IDN.json").write_text(json.dumps(
        {"styles": [{"style": "dividend_value", "rows": [{"symbol": "AAAA"}]}]}))
    return o


def _get(out: Path, path: str) -> web.Response:
    app = web.App(out_dir=out, snapshots_dir=out / "none", journal_path=out / "none",
                  paper=lambda until: None, health=lambda: None)
    return web.dispatch(app, web.ROUTES, path)


def test_nav_has_industries(out):
    r = _get(out, "/industries")
    assert r.status == 200
    assert '<a href="/industries" class="active">Industries</a>' in r.body


def test_index_lists_industries_by_sector(out):
    body = _get(out, "/industries").body
    assert "2 industries, 4 names" in body
    assert '<h2>Keuangan</h2>' in body
    assert '<a href="/industries/bank1">AAAA, BBBB, CCCC</a>' in body
    row = re.search(r'<a href="/industries/bank1">.*?</tr>', body, re.S).group(0)
    assert "1 / 1 / 1" in row  # big / mid / small
    assert ">10.00<" in row and "11.00" in row  # PE median, then Stockbit's average


def test_index_twin(out):
    data = json.loads(_get(out, "/industries.json").body)
    assert data["as_of"] == "2026-10-26"
    assert {i["id"] for i in data["industries"]} == {"bank1", "other"}


def test_page_chart(out):
    body = _get(out, "/industries/bank1").body
    svg = re.search(r"<svg.*?</svg>", body, re.S).group(0)
    for label in ("Valuation", "Dividend", "Profitability", "Solvency"):
        assert f">{label}</text>" in svg
    for group in ("Big cap", "Mid cap", "Small cap"):
        assert group in svg
    assert ">AAAA ★</text>" in svg and ">BBBB</text>" in svg
    assert svg.count('class="hit"') == 12  # 3 names × 4 categories
    # sector medians need 3 values: PE, PBV and ROE have them, yield and D/E do not
    assert svg.count('class="ring"') == 6
    assert 'class="pos"' in svg and 'class="neg"' in svg
    assert "AAAA Valuation: 2.00× better than the industry median" in svg
    assert "bar: score vs the industry median" in body and "ring: vs the sector median" in body


def test_page_tables(out):
    body = _get(out, "/industries/bank1").body
    val = re.search(r'<details class="card table" data-category="valuation" open>(.*?)</details>',
                    body, re.S).group(1)
    for bench in ("Industry median (benchmark)", "Industry average (Stockbit)",
                  "Sector median (benchmark)", "Sector average (Stockbit)"):
        assert bench in val
    assert "★ dividend_value" in val
    aaaa = re.search(r"<strong>AAAA</strong>.*?</tr>", val, re.S).group(0)
    assert ">big<" in aaaa and "2.00×" in aaaa and "0.50× ind" in aaaa
    assert 'data-category="dividend">' in body  # closed, not open


def test_page_twin(out):
    data = json.loads(_get(out, "/industries/bank1.json").body)
    assert data["id"] == "bank1" and [s["symbol"] for s in data["stocks"]] == ["AAAA", "BBBB",
                                                                               "CCCC"]
    assert data["sector_benchmarks"]["median"]["pe"] == 10.0  # 5, 10, 20 (XEVL is elsewhere)


def test_escaping(out):
    for path in ("/industries", "/industries/other"):
        body = _get(out, path).body
        assert EVIL not in body
        assert "&lt;script&gt;" in body


@pytest.mark.parametrize("path", ["/industries/nope", "/industries/..", "/industries/BANK1",
                                  "/industries/bank1/x", "/industries/", "/industries/..%2Fbank1"])
def test_404(out, path):
    assert _get(out, path).status == 404


def test_missing_and_invalid_file(tmp_path):
    o = tmp_path / "out"
    r = _get(o, "/industries")
    assert r.status == 200 and "assist industries" in r.body
    assert _get(o, "/industries/bank1").status == 404
    (o / "industries").mkdir(parents=True)
    (o / "industries" / "IDN.json").write_text("{not json")
    assert "is not valid JSON" in _get(o, "/industries").body
    (o / "industries" / "IDN.json").write_text("[]")
    assert "has no industries list" in _get(o, "/industries").body


def test_no_candidates_file_means_no_stars(out):
    (out / "candidates" / "IDN.json").unlink()
    assert "★ dividend_value" not in _get(out, "/industries/bank1").body
