"""The candidates pages (/candidates and /candidates/<MKT>): hurdle, tilt, styles with verdict,
t, p and pool, ranked rows with margins, cost, entry, held and size with tranches, dropped names,
sizing budget, trims, excluded, stale inputs, the .json twins, an invalid file as a notice,
absent fields as "-", escaping and the 404 cases. Reads temp copies of
tests/fixtures/ui/candidates/ (trimmed real IDN.json and USA.json, plus AUS.json with a sized
row) as out/candidates/; no real out/, store or network."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from assist import web

FIXTURES = Path(__file__).parent / "fixtures" / "ui" / "candidates"
EVIL = "<script>alert(1)</script>"


@pytest.fixture
def out(tmp_path) -> Path:
    o = tmp_path / "out"
    shutil.copytree(FIXTURES, o / "candidates")
    return o


def _get(out: Path, path: str) -> web.Response:
    app = web.App(out_dir=out, snapshots_dir=out / "none", journal_path=out / "none",
                  paper=lambda until: None, health=lambda: None)
    return web.dispatch(app, web.ROUTES, path)


def _market(html: str, mkt: str) -> str:
    m = re.search(rf'<section class="market" id="{mkt}">(.*?)</section><!-- /market -->',
                  html, re.S)
    assert m, f"no {mkt} market"
    return m.group(1)


def _style(html: str, style: str) -> str:
    m = re.search(rf'<section class="card style" data-style="{style}">(.*?)</section>', html,
                  re.S)
    assert m, f"no {style} style"
    return m.group(1)


def _card(html: str, name: str) -> str:
    m = re.search(rf'<section class="card {name}">(.*?)</section>', html, re.S)
    assert m, f"no {name} card"
    return m.group(1)


def _write(out: Path, name: str, text: str) -> None:
    (out / "candidates" / name).write_text(text)


# ---------------- list page ----------------


def test_index_lists_every_market_idn_first(out):
    r = _get(out, "/candidates")
    assert r.status == 200
    assert "<title>Assist Candidates</title>" in r.body
    assert web.DISCLAIMER in r.body
    assert '<a href="/candidates" class="active">' in r.body
    ids = re.findall(r'<section class="market" id="([A-Z0-9_]+)">', r.body)
    assert ids == ["IDN", "AUS", "USA"]
    for m in ids:
        assert f'<a href="/candidates/{m}">{m}</a>' in r.body


def test_index_json_twin_is_every_payload(out):
    r = _get(out, "/candidates.json")
    assert r.status == 200 and r.ctype == "application/json"
    d = json.loads(r.body)
    assert [p["market"] for p in d["markets"]] == ["IDN", "AUS", "USA"]
    assert d["markets"][0] == json.loads((FIXTURES / "IDN.json").read_text())
    assert d["problems"] == []


def test_no_candidates_dir_is_a_notice(tmp_path):
    r = _get(tmp_path / "out", "/candidates")
    assert r.status == 200
    assert '<p class="notice">no candidate lists in out/candidates/ yet' in r.body


# ---------------- one market ----------------


def test_idn_header_hurdle_and_stance(out):
    r = _get(out, "/candidates/IDN")
    assert r.status == 200
    assert "<title>Assist Candidates IDN</title>" in r.body
    assert '<a href="/candidates" class="active">' in r.body
    head = _card(r.body, "summary")
    for text in ("As of</th><td>2026-10-27", "Bars</th><td>2026-10-09",
                 "Currency</th><td>IDR", "Regime</th><td>neutral",
                 "Hurdle</th><td>13.74%", "Stocks stance</th><td>"
                 '<span class="chip muted">neutral</span> 60.4% → 60.4%'):
        assert text in head, text
    hurdle = _card(r.body, "hurdle")
    assert "<li>IDN hurdle 13.74% = SBN 10Y (igsyc) + US ERP 4.09%" in hurdle


def test_idn_tilt_failed_with_sectors(out):
    tilt = _card(_get(out, "/candidates/IDN").body, "tilt")
    assert '<span class="chip bad">failed</span>' in tilt
    assert "t-stat -1.11 below 2.0" in tilt
    assert "<td>Barang Baku</td><td>-0.053</td><td>+0.00pt</td><td>5</td>" in tilt


def test_idn_passed_style_ranked_rows_with_null_size(out):
    s = _style(_get(out, "/candidates/IDN").body, "dividend_value")
    assert '<span class="chip good">passed</span>' in s
    assert "beats placebo (t 2.79, p 0.004); control t 0.10" in s
    assert "t 2.79" in s and "p 0.004" in s and "pool 35" in s and "3 name(s)" in s
    rows = re.findall(r'<tr data-symbol="([A-Z]+)">', s)
    assert rows == ["BMRI", "JPFA", "BBNI"]
    bmri = re.search(r'<tr data-symbol="BMRI">(.*?)</tr>', s, re.S).group(1)
    cells = re.findall(r"<td[^>]*>(.*?)</td>", bmri, re.S)
    assert cells == ["1", "BMRI", "Keuangan", "hold", "16.25%", "+2.51pt", "+0.00pt", "+1.85pt",
                     "67", "5,950 (typical, deep)", "IDR 4,010,000", "-", "-", "-"]
    jpfa = re.search(r'<tr data-symbol="JPFA">(.*?)</tr>', s, re.S).group(1)
    assert "<td>no</td>" in jpfa and "<td>watch</td>" in jpfa
    dropped = re.search(r'<div class="dropped">(.*?)</div>', s, re.S).group(1)
    assert "<li>ELSA: round trip 145bp eats the 0.52pt margin</li>" in dropped


def test_failed_style_shows_verdict_and_no_rows(out):
    s = _style(_get(out, "/candidates/IDN").body, "garp")
    assert '<span class="chip bad">failed</span>' in s
    assert "t-stat 1.30 below 2.0" in s and "pool 30" in s
    assert "<table" not in s
    assert "no names" in s


def test_idn_sizing_trims_and_excluded(out):
    body = _get(out, "/candidates/IDN").body
    sz = _card(body, "sizing")
    assert "Budget</th><td>IDR 0" in sz and "Unspent</th><td>IDR 0" in sz
    assert "Portfolio</th><td>IDR 29,617,701" in sz
    trims = _card(body, "trims")
    assert "<td>AMRT</td><td>IDR 1,848,000</td><td>trim in full: fails its screen</td>" in trims
    assert len(re.findall(r"<tr><td>", trims)) == 3
    ex = _card(body, "excluded")
    assert "<td>ASII</td><td>held, not rated by any passing screen: no trim call</td>" in ex
    assert "none" in _card(body, "stale")


def test_sized_row_with_tranches(out):
    body = _get(out, "/candidates/AUS").body
    s = _style(body, "dividend_value")
    jpfa = re.search(r'<tr data-symbol="JPFA">(.*?)</tr>', s, re.S).group(1)
    assert "<td>add</td>" in jpfa
    assert "<td>-0.50pt</td>" in jpfa  # the passed tilt's shift
    assert "IDR 1,500,000 in 3 tranches" in jpfa
    tr = re.search(r'<tr class="tranches" data-symbol="JPFA">(.*?)</tr>', s, re.S)
    assert tr, "no tranche list"
    tr = tr.group(1)
    assert "quarter-Kelly, capped at 5%" in tr
    assert "<li>day 0: IDR 500,000, 200 shares, limit 1,915</li>" in tr
    assert "<li>day 10: IDR 500,000, 200 shares, limit 1,880</li>" in tr
    assert "<li>day 20: IDR 500,000, 200 shares, limit -</li>" in tr
    assert 'class="tranches" data-symbol="BMRI"' not in s  # null size: no tranche list
    assert '<span class="chip good">passed</span>' in _card(body, "tilt")
    sz = _card(body, "sizing")
    assert "Budget</th><td>IDR 2,000,000" in sz and "Unspent</th><td>IDR 500,000" in sz
    assert "none" in _card(body, "trims")
    assert "<li>financer (stale): last statement 2026-09-30</li>" in _card(body, "stale")


def test_usa_no_names_no_tilt_and_stale_inputs(out):
    body = _get(out, "/candidates/USA").body
    head = _card(body, "summary")
    assert "Bars</th><td>-" in head and "Hurdle</th><td>13.61%" in head
    assert '<span class="chip good">overweight</span> 0% → 5%' in head
    assert len(re.findall(r"<li>", _card(body, "hurdle"))) == 4
    tilt = _card(body, "tilt")
    assert "none for USA (S16 is IDN only)" in tilt and "<table" not in tilt
    for style in ("dividend_value", "garp"):
        s = _style(body, style)
        assert "insufficient sample (on 0, off 0)" in s and "pool 0" in s and "<table" not in s
        assert "0 quarters" in s and "t 0.00" not in s and "p 1.000" not in s  # nothing judged
    assert "Budget</th><td>IDR 1,480,885" in _card(body, "sizing")
    assert "none" in _card(body, "trims") and "none" in _card(body, "excluded")
    stale = _card(body, "stale")
    assert "<li>sec-edgar universe empty" in stale


def test_market_json_twin_is_the_file(out):
    r = _get(out, "/candidates/USA.json")
    assert r.status == 200
    assert json.loads(r.body) == json.loads((FIXTURES / "USA.json").read_text())


# ---------------- broken input ----------------


def test_invalid_file_is_a_notice_and_the_rest_render(out):
    _write(out, "BAD.json", "{not json")
    _write(out, "LIST.json", "[1, 2]")
    r = _get(out, "/candidates")
    assert r.status == 200
    assert '<p class="notice">BAD.json: invalid JSON' in r.body
    assert '<p class="notice">LIST.json: not a JSON object' in r.body
    ids = re.findall(r'<section class="market" id="([A-Z0-9_]+)">', r.body)
    assert ids == ["IDN", "AUS", "USA"]
    d = json.loads(_get(out, "/candidates.json").body)
    assert [p["file"] for p in d["problems"]] == ["BAD.json", "LIST.json"]
    one = _get(out, "/candidates/BAD")
    assert one.status == 200 and '<p class="notice">BAD.json: invalid JSON' in one.body


def test_schema_mismatch_is_a_notice_and_absent_fields_render_dash(out):
    _write(out, "ZZZ.json", json.dumps({"market": "ZZZ", "styles": [
        {"style": "garp", "passed": True, "rows": [{"symbol": "ABCD", "size": {}}]}]}))
    r = _get(out, "/candidates/ZZZ")
    assert r.status == 200
    assert '<p class="notice">ZZZ.json: does not match the schema' in r.body
    head = _card(r.body, "summary")
    assert "As of</th><td>-" in head and "Hurdle</th><td>-" in head
    s = _style(r.body, "garp")
    abcd = re.search(r'<tr data-symbol="ABCD">(.*?)</tr>', s, re.S).group(1)
    cells = re.findall(r"<td[^>]*>(.*?)</td>", abcd, re.S)
    assert cells[0] == "-" and cells[1] == "ABCD"
    assert all(c == "-" for c in cells[2:]), cells


def test_escapes_values_read_from_files(out):
    p = json.loads((FIXTURES / "AUS.json").read_text())
    p["market"] = "EVL"
    p["hurdle"]["drivers"] = [EVIL]
    p["tilt"]["verdict"] = EVIL
    st = p["styles"][0]
    st["verdict"] = EVIL
    st["rows"][0]["symbol"] = EVIL
    st["rows"][0]["sector"] = EVIL
    st["rows"][1]["size"]["reason"] = EVIL
    st["dropped"][0]["reason"] = EVIL
    p["sizing"]["excluded"] = [{"symbol": EVIL, "reason": EVIL}]
    p["sizing"]["trims"] = [{"symbol": "X", "idr": 1.0, "reason": EVIL}]
    p["stale_inputs"] = [EVIL]
    _write(out, "EVL.json", json.dumps(p))
    for path in ("/candidates/EVL", "/candidates"):
        body = _get(out, path).body
        assert "<script>" not in body, path
        assert body.count("&lt;script&gt;") >= 11, path


# ---------------- 404 ----------------


@pytest.mark.parametrize("path", ["/candidates/XXX", "/candidates/idn", "/candidates/IDN/x",
                                  "/candidates/..", "/candidates/..%2FIDN",
                                  "/candidates/IDN.json/x", "/candidates/XXX.json",
                                  "/candidates/"])
def test_unknown_market_is_404(out, path):
    assert _get(out, path).status == 404


def test_index_links_resolve(out):
    body = _get(out, "/candidates").body
    links = re.findall(r'href="(/candidates/[^"]+)"', body)
    assert links
    for link in links:
        assert _get(out, link).status == 200, link


# ---------------- average down (P89, PLAN S70) ----------------


def _with_average_down(out: Path) -> None:
    """AUS.json's sized JPFA row as a funded average down, plus an unfunded and a stopped name."""
    p = json.loads((FIXTURES / "AUS.json").read_text())
    row = next(r for s in p["styles"] for r in s["rows"] if r["size"])
    row.update(action="average_down", held=True, held_idr=2e6,
               cost_basis={"avg_cost": 2000.0, "quantity": 1000.0, "below_cost_pct": -12.5,
                           "new_avg_cost": 1890.0},
               average_down={"status": "average_down", "gate": None, "reason": "12.5% below"})
    base = {"quantity": 100.0, "price": 900.0, "new_avg_cost": None}
    p["average_down"] = {"underwater_pct": 5.0, "gate3": "context", "names": [
        {"symbol": row["symbol"], "status": "average_down", "gate": None,
         "reason": "12.5% below cost; sized", "avg_cost": 2000.0, "quantity": 1000.0,
         "price": 1750.0, "below_cost_pct": -12.5, "new_avg_cost": 1890.0,
         "entry_status": "deep"},
        {**base, "symbol": "BMRI", "status": "unfunded", "gate": 5, "avg_cost": 1000.0,
         "reason": "no budget: 96.9% held against a target of 48.0%", "below_cost_pct": -10.0,
         "entry_status": "avoid"},
        {**base, "symbol": "AMRT", "status": "stopped", "gate": 2, "avg_cost": 1400.0,
         "reason": "trim in full: fails its screen", "below_cost_pct": -35.7,
         "entry_status": None},
        {**base, "symbol": "BBCA", "status": "stopped", "gate": 1, "avg_cost": 902.0,
         "reason": "0.2% below cost (needs 5%)", "below_cost_pct": -0.2, "entry_status": None},
    ]}
    _write(out, "AUS.json", json.dumps(p))


def test_average_down_columns_and_card(out):
    _with_average_down(out)
    body = _get(out, "/candidates/AUS").body
    row = re.search(r'<tr data-symbol="JPFA">(.*?)</tr>', body, re.S).group(1)
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    assert cells[3] == "average_down" and cells[-3:-1] == ["2,000", "-12.5%"]
    card = _card(body, "average-down")
    assert "3 of 4 held names are 5% or more below their average cost" in card
    assert "Entry status is context" in card
    names = re.findall(r"<tr><td>([A-Z]+)</td>", card)
    assert names == ["JPFA", "BMRI", "AMRT"]  # funded, unfunded, stopped; gate 1 left out
    assert "<td>stopped (gate 2)</td>" in card and "<td>unfunded</td>" in card
    assert "<td>1,890</td>" in card and "trim in full: fails its screen" in card


def test_no_average_down_card_without_the_block(out):
    assert 'class="card average-down"' not in _get(out, "/candidates/IDN").body
