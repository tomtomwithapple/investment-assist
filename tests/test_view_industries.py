"""The industries pages (/industries and /industries/<id>): the one ranked table of names above 1×
overall, the chart (one bar and one ring per name and category, tier groups, the legend), the
category tables with benchmarks and deviations, stars from out/candidates/IDN.json, the .json
twins, a missing or invalid file, escaping and the 404 cases. A temp out/ written from a
synthetic `Comparison` through `peers.build`; no real out/, store or network."""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path

import pytest

from assist import web
from assist.candidates import peers
from assist.sources.idxmethod_comparison import Comparison
from assist.views.industries import overall as peers_overall

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


def _ranked_out(tmp_path) -> Path:
    """bank2's medians are pinned by eleven identical names (PE 10, PBV 2, yield 5, ROE 10, D/E
    0.5), so
    each test name is scored against those: AAAA passes every filter, the others fail one."""
    c = Comparison(date=date(2026, 10, 26))
    rows = {f"M{i:03d}": {PE: 10.0, PBV: 2.0, YIELD: 5.0, ROE: 10.0, DER: 0.5, MKTCAP: 1e12}
            for i in range(11)}  # level: overall 1.00x
    rows.update({
        "AAAA": {PE: 5.0, PBV: 1.0, YIELD: 10.0, ROE: 20.0, DER: 0.45, MKTCAP: 100e12},  # passes
        "CCCC": {PE: 20.0, PBV: 4.0, YIELD: 1.0, ROE: 5.0, MKTCAP: 0.5e12},  # below
        "EEEE": {PE: 5.0, PBV: 1.0, ROE: 20.0, MKTCAP: 2e12},  # no yield
        "FFFF": {PE: 15.0, PBV: 3.0, YIELD: 20.0, ROE: 40.0, MKTCAP: 3e12},  # red valuation
        "GGGG": {PE: 5.0, PBV: 1.0, YIELD: 20.0, ROE: 5.0, MKTCAP: 4e12},  # red profitability
        "HHHH": {PE: 5.0, PBV: 1.0, YIELD: 20.0, MKTCAP: 6e12},  # no profitability
        "IIII": {PE: 2.0, PBV: 3.0, YIELD: 20.0, ROE: 20.0, MKTCAP: 7e12},  # dear PBV
        "JJJJ": {PE: 5.0, PBV: 1.0, YIELD: 3.0, ROE: 40.0, MKTCAP: 8e12},  # dividend 0.6x
        "KKKK": {PE: 5.0, PBV: 1.0, YIELD: 10.0, ROE: 20.0, DER: 1.0, MKTCAP: 9e12},  # D/E 2x
    })
    for sym, vals in rows.items():
        c.ratios[sym], c.industry[sym], c.sectors[sym] = dict(vals), "bank2", "Keuangan"
        c.names[sym] = f"{sym} Tbk"
        c.industry_avg[sym], c.sector_avg[sym] = {PE: 11.0}, {PE: 12.0}
    o = tmp_path / "ranked"
    peers.write(peers.build(c, date(2026, 10, 27)), o)
    return o


def test_index_is_one_ranked_table_after_every_filter(tmp_path):
    o = _ranked_out(tmp_path)
    body = _get(o, "/industries").body
    assert "<table" not in body and "Big / mid / small" not in body
    data = json.loads(_get(o, "/industries.json").body)
    scores = [r["score"] for r in data["rows"]]
    assert all(x > 0 for x in scores) and scores == sorted(scores, reverse=True)
    assert all(r["score_industry"]["dividend"] is not None for r in data["rows"])
    assert all(r["score_industry"][c] > 0 for r in data["rows"]
               for c in ("valuation", "profitability"))
    every = {s["symbol"]: s for i in json.loads((o / "industries" / "IDN.json").read_text())
             ["industries"] for s in i["stocks"]}
    assert every["FFFF"]["score_industry"]["valuation"] < 0 < peers_overall(every["FFFF"])
    assert every["GGGG"]["score_industry"]["profitability"] < 0 < peers_overall(every["GGGG"])
    assert every["HHHH"]["score_industry"]["profitability"] is None
    assert peers_overall(every["HHHH"]) > 0
    iiii = every["IIII"]["score_industry"]
    assert min(iiii["valuation"], iiii["profitability"], iiii["dividend"]) > 0
    assert every["IIII"]["dev_industry"]["pbv"] > 0  # blue on valuation, but PBV above median
    assert all(r["dev_industry"][k] < 0 for r in data["rows"] for k in ("pe", "pbv"))
    for sym, cat in (("JJJJ", "dividend"), ("KKKK", "solvency")):
        sc = every[sym]["score_industry"]
        assert sc[cat] < math.log(0.8) and min(sc["valuation"], sc["profitability"]) > 0
        assert peers_overall(every[sym]) > 0
    assert every["EEEE"]["score_industry"]["solvency"] is None  # no D/E: fails the floor too
    assert [r["symbol"] for r in data["rows"]] == ["AAAA"]
    assert data["industries"][0]["symbols"] == ["AAAA"]
    assert "1 of 20 names in 1 of 1 industries pass" in body
    card = re.search(r'<section class="card chart industry" data-industry="bank2">.*?</section>',
                     body, re.S).group(0)
    assert '<h2><a href="/industries/bank2">Keuangan</a></h2>' in card
    assert "1 of 20 names pass" in card
    svg = re.search(r"<svg.*?</svg>", card, re.S).group(0)
    for lb in ("PE", "PBV", "Yield %", "ROE %", "D/E"):
        assert f">{lb}</text>" in svg
    assert ">Industry median</text>" in svg and ">Industry avg (Stockbit)</text>" in svg
    assert ">AAAA</tspan>" in svg and "· big</tspan>" in svg
    assert svg.count('class="hit"') == 5 * 3  # 5 panels × (median, average, AAAA)
    assert svg.count('class="median"') == 5  # every metric has a median here
    # AAAA: PE 5 vs 10 and D/E 0.45 vs 0.5 better (blue); every bar of it is blue
    assert "AAAA PE: 5.00, 0.50× the industry median (10.00)" in svg
    assert 'class="neg"' not in svg and svg.count('class="pos"') == 5
    assert ">» 11.00</text>" in svg  # Stockbit's average PE: past the axis end (10), cut


def test_index_stars_and_twin(out):
    assert "★ dividend_value" not in _get(out, "/industries").body  # no dividend median there
    data = json.loads(_get(out, "/industries.json").body)
    assert data["as_of"] == "2026-10-26" and data["rows"] == []


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
    assert EVIL not in _get(out, "/industries").body
    body = _get(out, "/industries/other").body
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
