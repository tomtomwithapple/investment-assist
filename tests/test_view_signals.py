"""The signals pages (/signals, /signals/<SUBJECT>, PLAN S35): the layer-2 and layer-3 tables,
the IDN charts (USD gaps and JISDOR carried-forward days marked, never filled; IGSYC today vs
earlier; a null JCI close breaks the line), tables only for a foreign subject, the .json twin,
404 for a subject without a file (matched exactly, never a path), a notice instead of a 500 and
escaping. Subject files are built here, checked against schema/layers/subject.schema.json and
written to a temp out/layers/."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from assist import layers_out, web
from assist.views import signals

EVIL = "<script>alert(1)</script>"
FP = "sha256:" + "ab" * 32
COMMON = {"schema_version": "1.0.0", "kind": "subject", "as_of": "2026-11-06",
          "model_fingerprint": FP, "disclaimer": "Heuristic, not investment advice."}


def _component(name, source, sid, value, direction, last_date, last_value, detail, w):
    return {"name": name, "source": source, "series_id": sid, "value": value,
            "direction": direction, "last": {"date": last_date, "value": last_value},
            "detail": detail, "weights": dict(zip(("stocks", "bonds", "currency"), w, strict=True))}


def _asset(asset, shift, raw, capped=False, reason="r"):
    return {"asset": asset, "shift": shift, "raw": raw, "cap": 10.0, "capped": capped,
            "reason": reason}


IDN = {
    **COMMON, "subject": "IDN", "members": [],
    "sources": ["bps-looker", "idxscape"], "stale_inputs": ["satudatascape (missing)"],
    "layer2": {
        "components": [
            _component("cli", "dbnomics", "idn.cli", -0.64212, -1, "2026-09-01", 98.62859,
                       "OECD CLI 98.63 on 2026-09-01", (3, -1, 1)),
            _component("bi_rate", "bisfetcher", "WS_CBPOL.M.ID", 1.0, 1, "2026-09-01", 5.75,
                       "BI rate 5.75% on 2026-09-01", (-2, -3, 1)),
        ],
        "assets": [_asset("stocks", -10.0, -14.0, capped=True, reason="cli -3; bi_rate -2"),
                   _asset("bonds", -4.0, -4.0), _asset("currency", 2.0, 2.0)],
        "idr_terms": None, "gaps": []},
    "layer3": {"signals": [
        {"asset": "stocks", "name": "idx_foreign_flow", "value": -15886605556100.0,
         "direction": -1, "source": "idxscape", "detail": "IDR -15.89T net foreign"},
        {"asset": "bonds", "name": "sbn_non_resident_change", "value": 4.09e12,
         "direction": 1, "source": "idxscape", "detail": "IDR +4.09T non-resident SBN"}],
        "tally": {"stocks": -1, "bonds": 1}},
    "charts": {
        "net_foreign": {"days": 60, "unit_idr": "IDR", "unit_usd": "USD", "points": [
            {"date": "2026-10-20", "idr": 5.0e11, "usd": None},
            {"date": "2026-10-21", "idr": -1.2e12, "usd": None},
            {"date": "2026-10-22", "idr": -3.0e11, "usd": -1.66e7},
            {"date": "2026-10-23", "idr": 2.0e11, "usd": 1.1e7}]},
        "jisdor": {"days": 60, "unit": "IDR per USD", "gaps": ["2026-10-24"], "points": [
            {"date": "2026-10-22", "value": 18047.0, "carried_forward": False},
            {"date": "2026-10-23", "value": 18069.0, "carried_forward": True},
            {"date": "2026-10-27", "value": 18100.0, "carried_forward": False}]},
        "jci": {"unit": "index", "source": "idxscape+idx-method", "points": [
            {"date": "2026-10-20", "value": 5100.0}, {"date": "2026-10-21", "value": None},
            {"date": "2026-10-22", "value": 5050.0}, {"date": "2026-10-23", "value": 5030.0}]},
        "igsyc": {"unit": "% a year",
                  "latest": {"as_of": "2026-11-05", "points": [
                      {"tenor_y": 1.0, "yield_pct": 6.85, "from_yesterday_column": False},
                      {"tenor_y": 10.0, "yield_pct": 7.70, "from_yesterday_column": True}]},
                  "earlier": {"target": "2026-10-08", "as_of": "2026-10-08", "points": [
                      {"tenor_y": 1.0, "yield_pct": 6.40, "from_yesterday_column": False},
                      {"tenor_y": 10.0, "yield_pct": 7.20, "from_yesterday_column": False}]}},
        "sbn_non_resident": {"unit": "IDR", "series_id": "SBN.TOTAL.non_resident", "points": [
            {"date": "2026-10-20", "value": 9.1e14}, {"date": "2026-10-21", "value": 9.15e14}]},
    },
}

EMU = {
    **COMMON, "subject": "EMU", "members": ["DEU", "FRA"],
    "sources": ["dbnomics"], "stale_inputs": [],
    "layer2": {
        "components": [_component("curve", "dbnomics", "ea.curve", -0.07, 0, "2026-11-05", 0.38,
                                  "10Y-2Y 0.38", (0, 1, 0))],
        "assets": [_asset("stocks", 0.0, 0.0), _asset("bonds", -9.0, -9.0),
                   _asset("currency", 1.0, 1.0)],
        "idr_terms": {"currency": "EUR", "level": 20393.99093, "on": "2026-11-04",
                      "change_3m": -0.017668, "change_12m": 0.058924, "carry": 0.031707,
                      "detail": "IDR 20,393.99 per EUR"},
        "gaps": [{"input": "curve", "why": "no Bund 2Y in dbnomics"}]},
    "layer3": None, "charts": None,
}


def _write(out: Path, name: str, payload) -> Path:
    d = out / "layers"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}.json"
    f.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return f


@pytest.fixture
def out(tmp_path: Path) -> Path:
    o = tmp_path / "out"
    _write(o, "IDN", IDN)
    _write(o, "EMU", EMU)
    _write(o, "regime", {"kind": "regime"})
    _write(o, "portfolio", {"kind": "portfolio"})
    return o


def _get(out: Path, path: str) -> web.Response:
    app = web.App(out_dir=out, snapshots_dir=out / "s", journal_path=out / "j",
                  paper=lambda until: None, health=lambda: None)
    return web.dispatch(app, web.ROUTES, path)


def _section(html: str, name: str) -> str:
    m = re.search(rf'<section class="card {name}">(.*?)</section>', html, re.S)
    assert m, f"no {name} section"
    return m.group(1)


def test_fixtures_match_the_schema():
    v = layers_out.validator("subject")
    for p in (IDN, EMU):
        assert not list(v.iter_errors(p)), p["subject"]


def test_idn_tables(out):
    r = _get(out, "/signals/IDN")
    assert r.status == 200
    assert "<title>Assist Signals IDN</title>" in r.body and web.DISCLAIMER in r.body
    l2 = _section(r.body, "layer2")
    assert "<b>cli</b>" in l2 and "98.63" in l2 and "2026-09-01" in l2 and "-0.6421" in l2
    assert '<span class="chip muted">down</span>' in l2 and "stocks +3 bonds -1 currency +1" in l2
    assert "<code>WS_CBPOL.M.ID</code>" in l2 and "BI rate 5.75% on 2026-09-01" in l2
    stocks = l2[l2.index("<b>stocks</b>"):l2.index("<b>bonds</b>")]
    assert ">-10<" in stocks and ">-14<" in stocks and "±10" in stocks
    assert '<span class="chip warn">capped</span>' in stocks and "cli -3; bi_rate -2" in stocks
    l3 = _section(r.body, "layer3")
    assert "<b>idx_foreign_flow</b>" in l3 and "-15.89T" in l3 and "+4.09T" in l3
    assert '<span class="chip bad">-1</span>' in l3 and '<span class="chip good">+1</span>' in l3
    assert "Tally: bonds +1 · stocks -1" in l3
    summary = _section(r.body, "summary")
    assert "satudatascape (missing)" in summary and "sha256:abababababab" in summary


def test_idn_charts(out):
    body = _get(out, "/signals/IDN").body
    assert body.count('<svg class="chart"') == 6  # flows IDR + USD, JISDOR, IGSYC, SBN, JCI
    flows = _section(body, "chart net-foreign")
    usd = flows[flows.index("<h3>USD</h3>"):]
    assert "2 of 4 days have no JISDOR rate" in usd
    assert usd.count('<line class="gap"') == 2  # the two null days: marked, no bar
    assert usd.count('class="pos"') == 1 and usd.count('class="neg"') == 1
    assert "2026-10-20: no JISDOR: no USD" in usd
    idr = flows[:flows.index("<h3>USD</h3>")]
    assert idr.count('class="pos"') == 2 and idr.count('class="neg"') == 2
    j = _section(body, "chart jisdor")
    assert j.count('class="dot cf"') == 1 and "2026-10-23: 18,069 (BI carried forward" in j
    assert "2026-10-24: IDX day without a JISDOR rate" in j
    assert "1 carried forward, 1 IDX days without a fixing" in j
    line = re.search(r'<path class="line s1" d="([^"]+)"', j).group(1)
    assert line.count("M") == 2  # the gap day breaks the line
    g = _section(body, "chart igsyc")
    assert '<path class="line s2 dash"' in g and '<path class="line s1"' in g
    assert "dot s1 hollow" in g and "(from the yesterday column)" in g
    assert "2026-11-05 (2 tenors) against 2026-10-08 (target 2026-10-08)" in g
    jci = _section(body, "chart jci")
    assert re.search(r'<path class="line s1" d="([^"]+)"', jci).group(1).count("M") == 2
    assert "latest 5,030, -1.4% over the window" in jci
    assert "latest 915.0T" in _section(body, "chart sbn")


def test_null_chart_is_a_notice(out):
    p = copy.deepcopy(IDN)
    p["charts"]["igsyc"] = None
    p["charts"]["jisdor"] = None
    _write(out, "IDN", p)
    r = _get(out, "/signals/IDN")
    assert r.status == 200
    assert "IGSYC curve: no chart in this run" in r.body and "JISDOR: no chart" in r.body
    assert r.body.count('<svg class="chart"') == 4


def test_foreign_subject_tables_only(out):
    r = _get(out, "/signals/EMU")
    assert r.status == 200
    assert "<svg" not in r.body and "Charts" not in r.body
    assert "no layer-3 signals for this subject (IDN only)" in _section(r.body, "layer3")
    l2 = _section(r.body, "layer2")
    assert "IDR terms" in l2 and "20,393.99 on 2026-11-04" in l2 and "-1.8% / +5.9%" in l2
    assert "+3.2% a year" in l2 and "<b>curve</b>: no Bund 2Y in dbnomics" in l2
    assert "DEU, FRA" in _section(r.body, "summary")


def test_json_twin_is_the_file(out):
    r = _get(out, "/signals/IDN.json")
    assert r.status == 200 and r.ctype == "application/json"
    assert json.loads(r.body) == IDN


@pytest.mark.parametrize("path", ["/signals/NOPE", "/signals/idn", "/signals/regime",
                                  "/signals/portfolio", "/signals/..%2FIDN", "/signals/%2E%2E",
                                  "/signals/IDN/x", "/signals/NOPE.json"])
def test_unknown_subject_is_404(out, path):
    assert _get(out, path).status == 404


def test_invalid_file_is_a_notice(out):
    _write(out, "USA", "{not json")
    r = _get(out, "/signals/USA")
    assert r.status == 200 and "layers/USA.json is not valid JSON" in r.body
    twin = json.loads(_get(out, "/signals/USA.json").body)
    assert twin["subject"] == "USA" and "not valid JSON" in twin["problem"]
    _write(out, "JPN", [1, 2])
    assert "is not a JSON object" in _get(out, "/signals/JPN").body


def test_error_stub_is_a_notice(out):
    stub = {**COMMON, "subject": "SGP", "error": f"KeyError: {EVIL}", "stale_inputs": [],
            "sources": []}
    assert not list(layers_out.validator("subject").iter_errors(stub))
    _write(out, "SGP", stub)
    r = _get(out, "/signals/SGP")
    assert r.status == 200 and "the run could not build layers/SGP.json" in r.body
    assert EVIL not in r.body and "&lt;script&gt;" in r.body


def test_malformed_parts_never_500(out):
    p = copy.deepcopy(IDN)
    p["layer2"]["components"] = [{"name": 3}, "x", None]
    p["layer2"]["assets"] = [{"shift": "big"}]
    p["layer3"] = {"signals": [{"direction": "up"}], "tally": []}
    p["charts"] = {"net_foreign": {"points": [{"date": "2026-10-01", "idr": "x", "usd": None}]},
                   "jisdor": {"points": "nope"}, "igsyc": {"latest": {"points": []}},
                   "jci": {"points": [{"date": "2026-10-01", "value": 5.0}]},
                   "sbn_non_resident": {}}
    _write(out, "IDN", p)
    assert _get(out, "/signals/IDN").status == 200


def test_every_value_escaped(out):
    p = copy.deepcopy(IDN)
    p["layer2"]["components"][0]["name"] = EVIL
    p["layer2"]["components"][0]["detail"] = EVIL
    p["layer2"]["assets"][0]["reason"] = EVIL
    p["layer3"]["signals"][0]["source"] = EVIL
    p["stale_inputs"] = [EVIL]
    p["charts"]["jci"]["points"][0]["date"] = "2026-10-20" + EVIL
    _write(out, "IDN", p)
    body = _get(out, "/signals/IDN").body
    assert EVIL not in body and body.count("&lt;script&gt;") >= 5


def test_index_lists_subjects(out):
    r = _get(out, "/signals")
    assert r.status == 200
    assert '<a href="/signals/IDN">IDN</a>' in r.body and '<a href="/signals/EMU">EMU</a>' in r.body
    main = r.body.split("</nav>", 1)[1]  # the nav links /regime and /portfolio since F8
    assert "regime" not in main and "portfolio" not in main.lower()
    data = json.loads(_get(out, "/signals.json").body)["subjects"]
    assert [d["subject"] for d in data] == ["EMU", "IDN"]
    assert data[1]["shifts"] == {"stocks": -10.0, "bonds": -4.0, "currency": 2.0}
    assert data[1]["signals"] == 2


def test_no_layers_dir(tmp_path):
    r = _get(tmp_path / "out", "/signals")
    assert r.status == 200 and signals.EMPTY.split(":")[0] in r.body
    assert _get(tmp_path / "out", "/signals/IDN").status == 404


def test_num_format():
    assert signals.num(-15886605556100.0) == "-15.89T"
    assert signals.num(4.09e12, signed=True) == "+4.09T"
    assert signals.num(3356.6) == "3,357"
    assert signals.num(153900.4) == "153,900" and signals.num(86270, signed=True) == "+86,270"
    assert signals.num(-0.64212) == "-0.6421" and signals.num(98.62859) == "98.63"
    assert signals.num(None) == "n/a" and signals.num(True) == "n/a"
    assert signals.num(float("nan")) == "n/a"
