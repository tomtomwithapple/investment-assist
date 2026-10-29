"""The industries page (/industries).

Schema 4 (S31, P49): the top tier table (rows, ordering by best composite, pillar bars, Tier B
muted), the industry cards (Tier A then B, sector fallback label, gate failure counts, the old
filter as a chip, charts and financials of the picks), industries without picks, escaping and the
.json twin; built from the S31 tier fixtures (tests/fixtures/tiers/) through `peers.build`.
Schema 3 (S30): the per-industry charts of the names with PE and PBV below the industry average,
ROE above it and D/E under the industry's cap, their financials, stars, the twin, behind a notice.
Also a missing or invalid file and no page per industry (404). A temp out/ only; no real out/,
store or network."""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path

import pytest

from assist import web
from assist.candidates import peers, tiers
from assist.sources.idxmethod_comparison import Comparison
from assist.views import industries

EVIL = "<script>alert(1)</script>"
PE, PBV, YIELD, ROE, DER, MKTCAP = 2891, 2896, 2915, 1461, 1508, 2892
TIER_FIX = Path(__file__).resolve().parent / "fixtures" / "tiers"
TIER_FIELDS = ("gates", "metrics", "pillars", "composite", "rank", "pick")


def _schema3(p: dict) -> dict:
    """A schema 4 payload as S30 wrote it: no tier fields."""
    p = json.loads(json.dumps(p))
    p["schema_version"] = 3
    for k in ("fingerprint", "tier_config"):
        p.pop(k, None)
    for ind in p["industries"]:
        for k in ("peer_group", "picks", "gated", "gate_failures"):
            ind.pop(k, None)
        for s in ind["stocks"]:
            for k in TIER_FIELDS:
                s.pop(k, None)
    return p


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
    peers.write(_schema3(_payload()), o)
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
    peers.write(_schema3(peers.build(c, date(2026, 10, 27))), o)
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
    p = _schema3(_payload())
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
    json.loads(_get(out, "/industries.json").body)  # the twin is data (application/json)


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


# ---------------- schema 4: the top tier (S31) ----------------


def _tier_cmp() -> tuple[Comparison, dict]:
    """manuf (Tier A MNF1, Tier B MNF2, five gate failures), thin (3 gated names, ranked within
    the sector, Tier B THN1), mixed (no Tier A, Tier B MIX1) from the S31 fixtures, and nopick
    (one name, no extras: fails liquidity). Stockbit's industry average is PE 10, PBV 1, ROE 27
    everywhere, so of the picks only MNF1 beats it on PE, PBV and ROE."""
    fid = {key: f for _, key, f, _ in peers.METRICS} | {"mktcap": peers.MKTCAP}
    c = Comparison(date=date(2026, 10, 26))
    names: dict = {}
    for f in ("industry.json", "no_tier_a.json"):
        names |= json.loads((TIER_FIX / f).read_text())["names"]
    names["NOPK"] = {"industry": "nopick", "sector": "Lainnya",
                     "values": {"pe": 5, "pbv": 0.5, "roe": 30, "der": 0.1, "mktcap": 1e12}}
    extras = {}
    for sym, n in sorted(names.items()):
        c.ratios[sym] = {fid[k]: v for k, v in n["values"].items()}
        c.industry[sym] = n["industry"]
        c.sector_key[sym] = c.sectors[sym] = n["sector"]
        c.names[sym] = f"{sym} Tbk"
        c.industry_avg[sym] = {fid["pe"]: 10.0, fid["pbv"]: 1.0, fid["roe"]: 27.0}
        c.sector_avg[sym] = {fid["pe"]: 10.0}
        c.competitors[sym] = []
        extras[sym] = n.get("extra") or {}
    c.statements = {"MNF1": {"revenue": {"2026Q1": 10e12, "2026Q2": 11e12}},
                    "MNF3": {"revenue": {"2026Q1": 3e12, "2026Q2": 4e12}}}
    return c, extras


def _tier_payload() -> dict:
    c, extras = _tier_cmp()
    return peers.build(c, date(2026, 10, 27), extras=extras)


@pytest.fixture
def tout(tmp_path) -> Path:
    o = tmp_path / "tiers"
    peers.write(_tier_payload(), o)
    (o / "candidates").mkdir()
    (o / "candidates" / "IDN.json").write_text(json.dumps(
        {"styles": [{"style": "dividend_value", "rows": [{"symbol": "MNF1"}]}]}))
    return o


def _table(body: str) -> str:
    return re.search(r'<table class="top-tier">.*?</table>', body, re.S).group(0)


def _card(body: str, iid: str) -> str:
    return re.search(rf'<section class="card chart industry" data-industry="{iid}">.*?</section>',
                     body, re.S).group(0)


def test_tier_table_rows_and_order(tout):
    body = _get(tout, "/industries").body
    assert "Top tier by industry" in body and "predates the top tier" not in body
    table = _table(body)
    syms = re.findall(r'<td class="sym"><b>(\w+)', table)
    assert syms == ["MNF1", "MNF2", "THN1", "MIX1"]  # by best composite: 78.31, 56.55, 52.57
    row = re.search(r'<tr class="tier-a\b[^>]*>.*?</tr>', table, re.S).group(0)
    assert "MNF1 Tbk" in row and ">78.3<" in row and "MNF1 ★" in row and ">big<" in row
    assert row.count('class="fill"') == 4 and row.count('class="miss"') == 1  # growth missing
    assert "<title>Growth: missing</title>" in row and "<title>Value 93.8</title>" in row
    data = json.loads(_get(tout, "/industries.json").body)
    assert [r["symbol"] for r in data["rows"]] == syms
    first = data["rows"][0]
    assert first["pick"] == "A" and first["composite"] == 78.31 and first["starred"]
    assert first["pillars"] == {"value": 93.75, "quality": 93.75, "growth": None,
                                "health": 93.75, "momentum": 6.25}
    assert first["industry"] == "manuf" and first["beats_average"] is True
    assert data["schema_version"] == 4 and data["fingerprint"] == tiers.fingerprint()
    assert [i["id"] for i in data["industries"]] == ["manuf", "thin", "mixed", "nopick"]
    assert data["industries"][0]["gate_failures"]["liquidity"] == 1


def test_tier_b_is_muted(tout):
    table = _table(_get(tout, "/industries").body)
    assert len(re.findall(r'<tr class="tier-a\b', table)) == 1
    assert len(re.findall(r'<tr class="tier-b\b', table)) == 3
    assert re.search(r'<tr class="tier-b\b[^>]*>.*?MNF2', table, re.S)
    card = _card(_get(tout, "/industries").body, "manuf")
    picks = re.search(r'<table class="picks">.*?</table>', card, re.S).group(0)
    assert picks.index("MNF1") < picks.index("MNF2")  # Tier A first
    assert re.search(r'<tr class="tier-b\b[^>]*>.*?MNF2', picks, re.S)
    assert ".peers tr.tier-b" in _get(tout, "/industries").body  # the muting rule ships


def test_tier_card_peer_group_and_gate_counts(tout):
    body = _get(tout, "/industries").body
    thin = _card(body, "thin")
    assert "ranked within sector Perindustrian (11 names past the gates)" in thin
    manuf = _card(body, "manuf")
    assert "ranked within sector" not in manuf
    assert "ranked within the industry (8 names past the gates)" in manuf
    gates = re.search(r'<p class="gates[^"]*">(.*?)</p>', manuf, re.S).group(1)
    for reason in ("D/E above cap", "F-score", "TTM loss", "liquidity", "trades too rarely"):
        assert f"{reason} 1" in gates
    assert "No name failed a gate" in thin


def test_tier_card_chip_and_charts(tout):
    body = _get(tout, "/industries").body
    manuf = _card(body, "manuf")
    chip = "beats the industry average on PE, PBV and ROE"
    picks = re.search(r'<table class="picks">.*?</table>', manuf, re.S).group(0)
    mnf1 = re.search(r"<tr[^>]*>(?:(?!</tr>).)*MNF1(?:(?!</tr>).)*</tr>", picks, re.S).group(0)
    mnf2 = re.search(r"<tr[^>]*>(?:(?!</tr>).)*MNF2(?:(?!</tr>).)*</tr>", picks, re.S).group(0)
    assert chip in mnf1 and chip not in mnf2
    svg = re.search(r"<svg viewBox[^>]*aria-label=\"[^\"]*PE, PBV.*?</svg>", manuf, re.S).group(0)
    assert ">MNF1 ★</tspan>" in svg and "MNF2" in svg and "MNF3" not in svg
    assert svg.count('class="hit"') == 5 * 3  # 5 panels × (average, MNF1, MNF2)
    fin = manuf[manuf.index("<h3>Financials"):]
    assert "MNF1 2026Q2 Revenue" in fin and "MNF3" not in fin  # MNF3 has statements, no pick


def test_industry_without_picks_is_listed_briefly(tout):
    body = _get(tout, "/industries").body
    assert 'data-industry="nopick"' not in body  # no card, no tab
    rest = re.search(r'<details class="card no-picks">.*?</details>', body, re.S).group(0)
    assert "1 industry without a top tier" in rest
    assert "no name passes the gates (no liquidity data 1)" in rest
    tabs = re.findall(r'<input type="radio" name="industry" id="ind-\d+"', body)
    assert len(tabs) == 3


def test_no_picks_at_all(tmp_path):
    c, _ = _tier_cmp()
    peers.write(peers.build(c, date(2026, 10, 27)), tmp_path)  # no extras: nobody gated
    r = _get(tmp_path, "/industries")
    assert r.status == 200 and "No industry has a top tier" in r.body
    assert '<table class="top-tier">' not in r.body
    assert json.loads(_get(tmp_path, "/industries.json").body)["rows"] == []


def test_schema3_shows_notice_and_the_old_view(out):
    r = _get(out, "/industries")
    assert r.status == 200
    assert "predates the top tier (schema 3)" in r.body
    assert "Top tier by industry" not in r.body and "AAAA ★" in r.body
    data = json.loads(_get(out, "/industries.json").body)
    assert data["schema_version"] == 3 and "predates the top tier" in data["notice"]
    assert [r["symbol"] for r in data["rows"]] == ["AAAA", "BBBB"]


def test_schema3_without_a_version_never_500s(tmp_path):
    p = _schema3(_payload())
    del p["schema_version"]
    p["industries"][0]["stocks"][0]["pillars"] = "junk"  # stray field, ignored
    peers.write(p, tmp_path)
    r = _get(tmp_path, "/industries")
    assert r.status == 200 and "predates the top tier" in r.body


def test_tier_view_survives_junk_fields(tmp_path):
    p = _tier_payload()
    ind = p["industries"][0]
    ind["picks"] = {"A": ["MNF1", "GONE"], "B": "junk"}
    ind["gate_failures"] = ["junk"]
    ind["peer_group"] = None
    ind["stocks"][0]["pillars"] = {"value": "x", "quality": None}
    ind["stocks"][0]["composite"] = "high"
    peers.write(p, tmp_path)
    r = _get(tmp_path, "/industries")
    assert r.status == 200 and "Top tier by industry" in r.body


def test_tier_escaping(tmp_path):
    p = _tier_payload()
    manuf = next(i for i in p["industries"] if i["id"] == "manuf")
    nopick = next(i for i in p["industries"] if i["id"] == "nopick")
    manuf["stocks"][0]["name"] = EVIL  # MNF1, Tier A
    manuf["stocks"][0]["tier"] = EVIL
    manuf["gate_failures"][EVIL] = 2
    nopick["label"] = EVIL
    next(i for i in p["industries"] if i["id"] == "thin")["peer_group"]["label"] = EVIL
    peers.write(p, tmp_path)
    body = _get(tmp_path, "/industries").body
    assert EVIL not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in _table(body)
    data = json.loads(_get(tmp_path, "/industries.json").body)
    assert data["rows"][0]["name"] == EVIL  # the twin carries the value as data


def test_pillar_bars():
    svg = industries.pillar_bars({"value": {"score": 50.0}, "growth": {"score": None},
                                  "momentum": {"score": 100.0}})
    assert svg.count('class="fill"') == 2 and svg.count('class="miss"') == 3
    assert "<title>Momentum 100.0</title>" in svg and "<title>Quality: missing</title>" in svg
    assert industries.pillar_bars("junk").count('class="miss"') == 5


def test_tier_chart_legend(tout):
    body = _get(tout, "/industries").body
    assert "its tier and composite" in body and "multiple of the average" not in body
