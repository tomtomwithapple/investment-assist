"""The industries page (/industries): the per-industry charts of the names with PE and PBV below
the industry average, ROE above it and D/E under the industry's cap, the financials timelines of
those names under each chart, stars from out/candidates/IDN.json, the .json twin, a missing or
invalid file, escaping, and no page per industry (404).
A temp out/ written from a synthetic `Comparison` through `peers.build`; no real out/, store or
network."""

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
        "BBBB": ("bank1", "Keuangan", {PE: 8.0, PBV: 1.5, YIELD: 5.0, ROE: 12.0, DER: 0.6,
                                       MKTCAP: 5e12}),
        "CCCC": ("bank1", "Keuangan", {PE: 20.0, PBV: 4.0, ROE: -3.0, MKTCAP: 0.5e12}),
        "XEVL": ("other", EVIL, {PE: 8.0}),
    }
    for sym, (ind, sector, vals) in rows.items():
        c.ratios[sym], c.industry[sym], c.sectors[sym] = dict(vals), ind, sector
        c.names[sym] = EVIL if sym == "XEVL" else f"{sym} Tbk"
        c.industry_avg[sym] = {PE: 10.0, PBV: 2.0, ROE: 10.0}
        c.sector_avg[sym] = {PE: 12.0}
    c.statements = {
        "AAAA": {"revenue": {"2025Q2": 10e12, "2026Q1": 11e12, "2026Q2": 12e12},
                 "net_income": {"2026Q1": -1e12, "2026Q2": 2e12}, "equity": {"2026Q2": 50e12}},
        "BBBB": {"revenue": {"2025Q2": 4e12, "2026Q2": 5e12}},
    }
    return peers.build(c, date(2026, 10, 27), {**peers.CONFIG, "quarters": 5})


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
    assert "<h2>Keuangan</h2>" in card and "href=\"/industries/" not in card
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
    # AAAA and BBBB pass (bank1's label is "Keuangan": cap 1); AAAA is on the S20 list
    assert "AAAA ★" in _get(out, "/industries").body
    data = json.loads(_get(out, "/industries.json").body)
    assert data["as_of"] == "2026-10-26"
    assert [r["symbol"] for r in data["rows"]] == ["AAAA", "BBBB"]


def test_index_financials(out):
    body = _get(out, "/industries").body
    card = re.search(r'<section class="card chart industry" data-industry="bank1">.*?</section>',
                     body, re.S).group(0)
    fin = card[card.index("<h3>Financials"):]
    assert "<h3>Financials, 2025Q2 to 2026Q2</h3>" in fin
    inc = re.search(r'<div data-statement="is">(.*?)</div>', fin, re.S).group(1)
    assert ">Revenue</text>" in inc and ">Net income</text>" in inc
    # one path per name and panel with a value: AAAA on revenue and net income only
    paths = re.findall(r'class="line" stroke="var\(--s1\)" d="([^"]*)"', inc)
    assert len(paths) == 2
    assert paths[0].count("M") == 2  # revenue skips 2025Q3 and 2025Q4: a gap, not a line
    assert 'stroke="var(--s2)"' in inc  # BBBB's lone dots still get a (moveto-only) path
    assert "AAAA 2026Q2 Revenue: IDR 12.0T" in inc
    assert 'class="zero"' in inc  # net income crosses 0
    assert ">-1T</text>" in inc and ">2026Q2</text>" in inc
    bs = re.search(r'<div data-statement="bs">(.*?)</div>', fin, re.S).group(1)
    assert "no values for these names" in bs  # total debt
    assert "CCCC" not in card  # fails the filters: neither in the chart nor the financials
    prof = re.search(r'<div data-statement="profitability">(.*?)</div>', fin, re.S).group(1)
    assert "<h4>Profitability, 2025Q2 to 2026Q2</h4>" in prof
    assert ">Gross margin</text>" in prof and ">ROE (annualised)</text>" in prof
    assert "AAAA 2026Q2 Net margin: 16.7%" in prof  # 2T on 12T
    assert "AAAA 2026Q2 ROE (annualised): 16.0%" in prof  # 2T × 4 on 50T
    assert "AAAA 2026Q1 ROE (annualised)" not in prof  # no equity that quarter


def test_ratio():
    assert industries.ratio([1, None, 3, 2, -1], [4, 2, None, 0, 4]) == [
        25.0, None, None, None, -25.0]  # no ratio on a missing or non-positive base
    assert industries.ratio([1], [-5]) == [None]


def test_profitability_keeps_the_last_three_years():
    quarters = [f"{y}Q{q}" for y in range(2022, 2027) for q in range(1, 5)][:18]
    fin = {"revenue": [10.0] * 18, "net_income": [1.0] * 18}
    ind = {"label": "x", "stocks": [{"symbol": "S", "financials": fin}]}
    html = industries.financials(ind, [{"symbol": "S"}], quarters, [
        {"key": "is", "label": "Income statement", "items": [{"key": "revenue", "label": "R"}]}])
    assert f"Profitability, {quarters[-12]} to {quarters[-1]}</h4>" in html
    prof = html[html.index('data-statement="profitability"'):]
    assert f"S {quarters[-12]} Net margin" in prof and f"S {quarters[-13]} " not in prof


def test_profitability_axis_clips_but_hover_tells(out):
    names = [{"symbol": "S", "financials": {"npm": [None, 900.0, -50.0]}}]
    svg = industries.timeline({"label": "x"}, industries.PROFITABILITY, ["a", "b", "c"], names,
                              pct=True)
    assert "S b Net margin: 900.0%" in svg and ">+100%</text>" in svg
    assert ">+200%</text>" not in svg


def test_page_without_statements(tmp_path):
    p = _payload()
    p["periods"] = []
    peers.write(p, tmp_path)
    assert "no quarterly statements for these names" in _get(tmp_path, "/industries").body


@pytest.mark.parametrize(("lo", "hi", "want"), [
    (0.0, 9.0, [0, 2.5, 5, 7.5, 10]), (-1e12, 2e12, [-1e12, 0, 1e12, 2e12]), (5.0, 5.0, None)])
def test_nice_ticks(lo, hi, want):
    t = industries.nice_ticks(lo, hi)
    assert t[0] <= min(lo, 0) and t[-1] >= hi and 0 in t
    if want is not None:
        assert t == want


@pytest.mark.parametrize(("v", "want"), [(3.2e13, "32T"), (4.5e11, "450B"), (-2e10, "-20B"),
                                         (2.5e12, "2.5T"), (5e12, "5T"), (None, "-")])
def test_compact(v, want):
    assert industries.compact(v) == want


def test_escaping(out):
    assert EVIL not in _get(out, "/industries").body
    assert EVIL not in _get(out, "/industries.json").body


@pytest.mark.parametrize("path", ["/industries/bank1", "/industries/bank1.json",
                                  "/industries/nope", "/industries/..", "/industries/BANK1",
                                  "/industries/bank1/x", "/industries/", "/industries/..%2Fbank1"])
def test_404(out, path):
    assert _get(out, path).status == 404


def test_missing_and_invalid_file(tmp_path):
    o = tmp_path / "out"
    r = _get(o, "/industries")
    assert r.status == 200 and "assist industries" in r.body
    (o / "industries").mkdir(parents=True)
    (o / "industries" / "IDN.json").write_text("{not json")
    assert "is not valid JSON" in _get(o, "/industries").body
    (o / "industries" / "IDN.json").write_text("[]")
    assert "has no industries list" in _get(o, "/industries").body


def test_no_candidates_file_means_no_stars(out):
    (out / "candidates" / "IDN.json").unlink()
    assert "AAAA ★" not in _get(out, "/industries").body


def test_each_industry_is_a_tab(out):
    body = _get(out, "/industries").body
    tabs = re.search(r'<div class="tabs">(.*)</div></div>', body, re.S).group(1)
    radios = re.findall(r'<input type="radio" name="industry" id="(ind-\d+)"( checked)?>', tabs)
    assert [r[0] for r in radios] == [f"ind-{k}" for k in range(len(radios))]
    assert [bool(r[1]) for r in radios] == [True] + [False] * (len(radios) - 1)
    assert '<label for="ind-0">Keuangan <span class="muted">' in tabs
    assert tabs.count('<section class="card chart industry"') == len(radios)
