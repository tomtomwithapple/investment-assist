"""The industries pages (/industries and /industries/<id>): the per-industry charts of the names
with PE and PBV below the industry average, ROE above it and D/E under the industry's cap, the
chart (one bar and one ring per name and category, tier groups, the legend), the category tables
with benchmarks and deviations, stars from out/candidates/IDN.json, the .json twins, a missing or
invalid file, escaping and the 404 cases. A temp out/ written from a synthetic `Comparison`
through `peers.build`; no real out/, store or network."""

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
from assist.views import industries

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
        c.industry_avg[sym] = {PE: 10.0, PBV: 2.0, ROE: 10.0}
        c.sector_avg[sym] = {PE: 12.0}
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
    """bank2's Stockbit average is PE 10, PBV 2, yield 5, ROE 10, D/E 0.5, and eleven names sit
    level on it; each test name is scored against it. The industry is named "Keuangan" (no
    anchor), so its D/E cap is the common 1.0. AAAA, EEEE and JJJJ pass; the others fail one."""
    c = Comparison(date=date(2026, 10, 26))
    rows = {f"M{i:03d}": {PE: 10.0, PBV: 2.0, YIELD: 5.0, ROE: 10.0, DER: 0.5, MKTCAP: 1e12}
            for i in range(11)}  # level: overall 1.00x
    rows.update({
        "AAAA": {PE: 5.0, PBV: 1.0, YIELD: 10.0, ROE: 20.0, DER: 0.45, MKTCAP: 100e12},  # passes
        "CCCC": {PE: 20.0, PBV: 4.0, YIELD: 1.0, ROE: 5.0, MKTCAP: 0.5e12},  # below
        "EEEE": {PE: 5.0, PBV: 1.0, ROE: 20.0, DER: 0.8, MKTCAP: 2e12},  # no yield, D/E > avg
        "FFFF": {PE: 15.0, PBV: 3.0, YIELD: 20.0, ROE: 40.0, MKTCAP: 3e12},  # red valuation
        "GGGG": {PE: 5.0, PBV: 1.0, YIELD: 20.0, ROE: 5.0, MKTCAP: 4e12},  # red profitability
        "HHHH": {PE: 5.0, PBV: 1.0, YIELD: 20.0, MKTCAP: 6e12},  # no profitability
        "IIII": {PE: 2.0, PBV: 3.0, YIELD: 20.0, ROE: 20.0, MKTCAP: 7e12},  # dear PBV
        "JJJJ": {PE: 5.0, PBV: 1.0, YIELD: 3.0, ROE: 40.0, DER: 0.3, MKTCAP: 8e12},  # yield 0.6x
        "KKKK": {PE: 5.0, PBV: 1.0, YIELD: 10.0, ROE: 20.0, DER: 1.0, MKTCAP: 9e12},  # at the cap
        "LLLL": {PE: 5.0, PBV: 1.0, ROE: 20.0, MKTCAP: 10e12},  # no D/E
        "NNNN": {PE: 5.0, PBV: 1.0, ROE: 20.0, DER: -0.5, MKTCAP: 11e12},  # negative equity
    })
    for sym, vals in rows.items():
        c.ratios[sym], c.industry[sym], c.sectors[sym] = dict(vals), "bank2", "Keuangan"
        c.names[sym] = f"{sym} Tbk"
        c.industry_avg[sym] = {PE: 10.0, PBV: 2.0, YIELD: 5.0, ROE: 10.0, DER: 0.5}
        c.sector_avg[sym] = {PE: 12.0}
    o = tmp_path / "ranked"
    peers.write(peers.build(c, date(2026, 10, 27)), o)
    return o


def test_index_filters_pe_pbv_roe_and_the_de_cap(tmp_path):
    o = _ranked_out(tmp_path)
    body = _get(o, "/industries").body
    assert "<table" not in body and "Big / mid / small" not in body
    data = json.loads(_get(o, "/industries.json").body)
    assert sorted(r["symbol"] for r in data["rows"]) == ["AAAA", "EEEE", "JJJJ"]
    scores = [r["score"] for r in data["rows"]]
    assert scores == sorted(scores, reverse=True)
    assert all(r["dev_industry"][k] < 0 for r in data["rows"] for k in ("pe", "pbv"))
    assert all(r["dev_industry"]["roe"] > 0 for r in data["rows"])
    every = {s["symbol"]: s for i in json.loads((o / "industries" / "IDN.json").read_text())
             ["industries"] for s in i["stocks"]}
    assert every["JJJJ"]["score_industry"]["dividend"] < math.log(0.8)  # dividend not filtered
    assert every["EEEE"]["dev_industry"]["der"] > 0  # D/E above the average, under the cap
    assert data["industries"][0]["der_cap"] == 1.0
    assert "3 of 22 names in 1 of 1 industries pass" in body
    card = re.search(r'<section class="card chart industry" data-industry="bank2">.*?</section>',
                     body, re.S).group(0)
    assert '<h2><a href="/industries/bank2">Keuangan</a></h2>' in card
    assert "3 of 22 names pass · D/E cap 1</span>" in card
    svg = re.search(r"<svg.*?</svg>", card, re.S).group(0)
    for lb in ("PE", "PBV", "Yield %", "ROE %", "D/E"):
        assert f">{lb}</text>" in svg
    assert ">Industry median</text>" not in svg and ">Industry avg (Stockbit)</text>" in svg
    assert ">AAAA</tspan>" in svg and "· big</tspan>" in svg
    assert svg.count('class="hit"') == 5 * 4  # 5 panels × (average, AAAA, EEEE, JJJJ)
    assert svg.count('class="avgline"') == 5  # every metric has an average here
    assert svg.count('class="capline"') == 1 and "<title>D/E cap 1</title>" in svg
    assert "AAAA PE: 5.00, 0.50× the industry average (10.00)" in svg
    assert "EEEE D/E: 0.80, 1.60× the industry average (0.50)" in svg
    assert "median" not in json.dumps(data["industries"])


def test_de_cap_by_industry():
    assert industries.der_cap("Keuangan") == 1.0
    assert industries.der_cap("Bank") is None and industries.der_cap("Asuransi") is None
    assert industries.der_cap("Jasa Pembiayaan") > 1 > industries.der_cap("Rokok")
    level = {"pe": -0.1, "pbv": -0.1, "roe": 0.1}

    def payload(label: str, der: float | None) -> dict:
        return {"industries": [{"id": "x", "label": label, "stocks": [
            {"symbol": "S", "values": {"der": der}, "dev_industry": level,
             "score_industry": {"valuation": 0.1}}]}]}

    assert industries.rows(payload("Bank", None))  # no cap: a missing D/E passes
    assert industries.rows(payload("Jasa Pembiayaan", 3.0))
    assert not industries.rows(payload("Konstruksi Bangunan", 1.2))
    assert not industries.rows(payload("Rokok", 0.6))
    assert industries.rows(payload("Rokok", 0.0))  # no debt


def test_index_stars_and_twin(out):
    # AAAA passes (bank1's label is "Keuangan": cap 1, D/E 0.5) and is on the S20 list
    assert "AAAA ★" in _get(out, "/industries").body
    data = json.loads(_get(out, "/industries.json").body)
    assert data["as_of"] == "2026-10-26" and [r["symbol"] for r in data["rows"]] == ["AAAA"]


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
    assert "AAAA Valuation: 2.00× better than the industry average" in svg
    assert "bar: score vs the industry average" in body and "ring: vs the sector median" in body


def test_page_tables(out):
    body = _get(out, "/industries/bank1").body
    val = re.search(r'<details class="card table" data-category="valuation" open>(.*?)</details>',
                    body, re.S).group(1)
    for bench in ("Industry average (Stockbit, benchmark)", "Sector median (benchmark)",
                  "Sector average (Stockbit)"):
        assert bench in val
    assert "Industry median" not in val
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
