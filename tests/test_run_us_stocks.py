"""F6 (PLAN S21 fan-in): the US undervalued list from P39's engines, assembled as F5 does for
IDN: out/candidates/USA.json, a USA block in the brief and Telegram, sizes in IDR from the USA
stocks stance, and the journal. No S16 tilt for the US (default caps, every name its own sector
bucket: sec-edgar has no SIC). In-memory P39 results and the F1 fixtures only: nothing here reads
a real store or reaches the network."""

from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import parse_qs

import pytest
from test_run_e2e import CREDS, FakeFred, financer, paths, telegram, wbs  # noqa: F401
from test_run_undervalued import DIV, fake_source, screen

from assist import brief, journal, pipeline
from assist.layers import undervalued as uv
from assist.layers.types import Regime
from assist.sources.financer import Holding, Statement
from assist.sources.idxmethod_series import Bar

DAY = date(2026, 10, 23)
BARS = date(2026, 10, 22)
REGIME = Regime(as_of=DAY, state="neutral", dollar="flat", sources=("sec-edgar",))
FP = "sha256:" + "b" * 64
FX = 16_500.0  # IDR per USD


def us_row(sym, style, usd, idr, m_usa, m_idn, price=100.0, med=5e8, **kw):
    legs = ({"yield_pt": 3.0, "g_pt": 4.5, "own_yield_pct": 0.8, "own_yield_n": 20}
            if style == "dividend_value" else
            {"implied_pt": 2.0, "realised_pt": 9.0, "consensus_pt": None})
    row = {"symbol": sym, "cik": 1, "title": f"{sym} Inc", "sector": None, "bank": False,
           "style": style, "expected_usd_pt": usd, "expected_idr_pt": idr,
           "margin_usa_pt": m_usa, "margin_idn_pt": m_idn,
           "margin_pt": None if m_usa is None or m_idn is None else min(m_usa, m_idn),
           "legs": legs, "price": price, "mktcap": 5e10, "med_value": med, "bar_date": BARS,
           "period": date(2026, 6, 30), "reasons": [], **kw}
    if style == "garp":
        row |= {"gap_pt": 7.0, "realised_gap_pt": 7.0,
                "risks": ["no consensus: realised growth only"]}
    return row


def us_result(style, rows, passed=True):
    """The shape of `us_stocks.run`'s output for one style."""
    return {
        "screen": f"us_{style}", "as_of": BARS, "passed": passed,
        "blocked": None if passed else "insufficient sample (0 quarters)",
        "verdict": {"passed": passed,
                    "reason": "beats placebo" if passed else "insufficient sample (0 quarters)",
                    "t": 2.5 if passed else None, "p": 0.01 if passed else None},
        "quarters": 40 if passed else 0, "hurdle_pt": 8.92, "idn_hurdle_pt": 13.61,
        "usd_bar_pt": 14.45, "binding": "IDN",
        "hurdle_drivers": ["USA hurdle 8.92% = 10Y 4.10% + US ERP 4.32% + CRP 0.00%",
                           "IDN hurdle 13.61%"],
        "universe": 10, "with_bars": 10, "pool": len(rows), "rejects": {},
        "ranking": rows, "top": rows, "candidates": rows if passed else [],
        "fingerprint": {"min_mktcap": 2e9, "engine": {"x": 1}},
        "stale_inputs": ["sec-edgar edgar_company has no SIC: no peer groups, every name its"
                         " own sector"],
    }


# expected IDR = (1 + usd)(1 + fx move) - 1; margins vs USA 8.92 and IDN 13.61
DIV_US = [us_row("KO", "dividend_value", 17.0, 16.1, 7.18, 2.49, price=70.0),
          us_row("JNJ", "dividend_value", 16.0, 15.1, 6.18, 1.49, price=150.0),
          us_row("PEP", "dividend_value", 14.0, 13.2, 4.28, -0.41, price=140.0)]
GARP_US = [us_row("MSFT", "garp", 20.0, 19.1, 10.18, 5.49, price=500.0),
           us_row("KO", "garp", 18.0, 17.1, 8.18, 3.49, price=70.0)]


def results(div=DIV_US, garp=GARP_US, div_passed=True, garp_passed=True):
    return {"dividend_value": us_result("dividend_value", div, div_passed),
            "garp": us_result("garp", garp, garp_passed)}


def inputs(res=None, fx=FX, vols=None, stale=()):
    res = res or results()
    syms = {r["symbol"] for x in res.values() for r in x["ranking"]}
    return uv.us_inputs(res, idr_per_usd=fx, vols=vols or {s: 0.25 for s in syms},
                        bar_date=BARS, stale=stale, sources=("sec-edgar", "idxscape"))


def stance(kind="overweight", current=0.0, target=5.0, entry=None):
    return {"subject": "USA", "asset": "stocks", "stance": kind,
            "entry": entry or {"style": "lump", "tranches": 1, "spacing_days": 0},
            "portfolio": {"current_pct": current, "target_pct": target, "delta": "x"}}


def build(inp, *, st=None, value=2e9, holdings=None, regime=REGIME):
    return uv.assemble(inp, day=DAY, stance=st or stance(), portfolio_value_idr=value,
                       holdings=holdings or {}, regime=regime, fingerprint=FP)


def valid(payload):
    errors = list(uv.validator().iter_errors(journal.jsonable(payload)))
    assert not errors, [e.message for e in errors]
    return payload


def by_style(payload):
    return {s["style"]: s for s in payload["styles"]}


# ---------------- P39 results → inputs ----------------


def test_us_inputs_are_in_idr_against_the_binding_hurdle():
    inp = inputs()
    assert inp.market == "USA" and inp.bar_date == BARS and inp.tilt is None
    div = inp.screens["dividend_value"]
    # a US name has to beat both hurdles: the IDR hurdle shown is the higher (IDN here)
    assert div["hurdle_pt"] == pytest.approx(13.61)
    assert any("binding" in d and "IDN" in d for d in div["hurdle_drivers"])
    ko = next(c for c in div["candidates"] if c["symbol"] == "KO")
    assert ko["expected_pt"] == pytest.approx(16.1)  # the unhedged IDR return, not the USD one
    assert ko["margin_pt"] == pytest.approx(2.49)
    assert ko["price"] == pytest.approx(70.0 * FX)
    f = inp.factors["KO"]
    assert f["price"] == pytest.approx(70.0 * FX)
    assert f["med_value_60d"] == pytest.approx(5e8 * FX) and f["vol_1y"] == 0.25
    c = inp.plan["KO"]["cost"]
    assert c.shares == int(uv.TRANCHE_IDR // (70.0 * FX)) and not c.flags
    assert 0 < c.round_trip_bps < 150  # US fees + IDR/USD conversion, both ways
    assert inp.plan["KO"]["levels"] is None
    assert inp.config["idr_per_usd"] == FX and inp.config["us_cost"] == uv.US_COST


def test_a_name_dearer_than_one_tranche_is_below_one_share():
    res = results(div=[us_row("NVR", "dividend_value", 17.0, 16.1, 7.2, 2.5, price=7000.0)],
                  garp=[])
    inp = inputs(res)
    assert "below_one_lot" in inp.plan["NVR"]["cost"].flags
    p = valid(build(inp))
    assert by_style(p)["dividend_value"]["dropped"] == [
        {"symbol": "NVR", "reason": "below_one_lot"}]


def test_no_usd_idr_rate_judges_no_name():
    inp = inputs(fx=None)
    assert any("USD/IDR" in s for s in inp.stale_inputs)
    p = valid(build(inp))
    assert all(not s["rows"] for s in p["styles"])
    assert {d["reason"] for s in p["styles"] for d in s["dropped"]} <= {
        "no cost estimate", "no margin (hurdle unknown)", "margin -0.41pt not above the hurdle"}


def test_vol_1y_from_engine_bars():
    bars = [Bar(BARS - timedelta(days=i), 100.0 * (1.01 if i % 2 else 1.0), 1e10)
            for i in range(300, -1, -1)]
    v = uv.vol_1y(bars, BARS)
    assert v == pytest.approx(0.01 * 252 ** 0.5, rel=0.02)
    assert uv.vol_1y(bars[:10], BARS) is None


# ---------------- assembly ----------------


def test_usa_payload_valid_with_default_caps_and_no_tilt():
    p = valid(build(inputs()))
    assert p["market"] == "USA" and p["currency"] == "IDR"
    assert p["hurdle"]["required_pt"] == pytest.approx(13.61)
    assert p["tilt"]["passed"] is False and "IDN only" in p["tilt"]["verdict"]
    assert p["tilt"]["sectors"] == []
    assert p["config"]["sizing"]["caps"]["sector_names"] == 5
    assert p["config"]["market"]["idr_per_usd"] == FX
    assert not any("sector tilt (unavailable)" in s for s in p["stale_inputs"])
    s = by_style(p)
    # PEP's margin over the IDN hurdle is negative: it is not a row
    assert [r["symbol"] for r in s["dividend_value"]["rows"]] == ["KO", "JNJ"]
    assert {d["symbol"] for d in s["dividend_value"]["dropped"]} == {"PEP"}
    assert [r["symbol"] for r in s["garp"]["rows"]] == ["MSFT", "KO"]
    assert all(r["margin_shift_pt"] == 0.0 and r["sector"] is None
               for x in p["styles"] for r in x["rows"])
    assert any("US$" in d for d in s["dividend_value"]["rows"][0]["drivers"])
    assert "sec-edgar" in p["sources"] and "financer" in p["sources"]


def test_sizes_come_from_the_usa_stance_budget_in_whole_shares():
    p = valid(build(inputs(), value=2e9))
    assert p["sizing"]["budget_idr"] == pytest.approx(0.05 * 2e9)
    rows = {r["symbol"]: r for x in p["styles"] for r in x["rows"]}
    added = [r for r in rows.values() if r["action"] == "add"]
    assert added
    for r in added:
        (t,) = r["size"]["tranches"]
        assert t["shares"] >= 1
        assert t["idr"] == pytest.approx(t["shares"] * r["price"])  # whole US shares, in IDR
        assert t["idr"] <= 0.05 * 2e9 + 1e-6
    # KO is in both styles: sized once, under its larger margin (GARP's 3.49 > 2.49)
    ko = [r for x in p["styles"] for r in x["rows"] if r["symbol"] == "KO"]
    assert sorted(r["action"] for r in ko) == ["add", "watch"]
    assert next(r for r in ko if r["action"] == "add")["style"] == "garp"


def test_no_sic_means_no_shared_sector_cap():
    rows = [us_row(f"S{i}", "dividend_value", 17.0, 16.1, 7.0, 2.0 + i / 10, price=50.0)
            for i in range(7)]
    p = valid(build(inputs(results(div=rows, garp=[])), value=1e10))
    sized = [r for r in by_style(p)["dividend_value"]["rows"] if r["action"] == "add"]
    assert len(sized) == 7
    assert not any("sector cap" in x["reason"] for x in p["sizing"]["excluded"])


def test_underweight_usa_stance_adds_nothing():
    p = valid(build(inputs(), st=stance("underweight", 0.0, 0.0)))
    assert p["sizing"]["budget_idr"] == 0
    assert all(r["size"] is None for x in p["styles"] for r in x["rows"])


def test_failed_us_styles_name_no_one():
    p = valid(build(inputs(results(div_passed=False, garp_passed=False))))
    assert all(not s["rows"] and not s["passed"] for s in p["styles"])
    assert "insufficient sample" in by_style(p)["garp"]["verdict"]


def test_holdings_from_maps_no_usd_lines_to_idn_or_usa():
    st = Statement("ajaib", "1", "broker", DAY, None, None, None, (
        Holding("BBCA", "BCA", "100", 1e6, "IDR"),
        Holding("AAPL", "Apple", "1", 300.0, "USD")))
    assert uv.holdings_from([st]) == {"BBCA": 1e6}
    assert uv.holdings_from([st], market="USA") == {}


def test_idn_payload_is_unchanged_by_the_us_fields():
    from test_run_undervalued import build as idn_build
    from test_run_undervalued import inputs as idn_inputs
    p = idn_build(idn_inputs({"dividend_value": screen("dividend_value", cands=DIV)}))
    assert "market" not in p["config"]
    assert p["tilt"]["verdict"].startswith("t-stat")


# ---------------- brief and Telegram ----------------


def test_brief_has_a_usa_block_after_idn(tmp_path):
    from test_run_undervalued import build as idn_build
    from test_run_undervalued import inputs as idn_inputs
    out = tmp_path / "out"
    uv.write(journal.jsonable(build(inputs())), out)
    uv.write(idn_build(idn_inputs({"dividend_value": screen("dividend_value", cands=DIV)})),
             out)
    text = brief.build_brief(out, tmp_path / "snap")
    assert text.index("**IDN**") < text.index("**USA**")
    usa = text[text.index("**USA**"):]
    assert "IDN only" in usa and "KO" in usa and "MSFT" in usa
    assert "binding" in usa  # the hurdle line says which market's hurdle binds
    assert "US$" in usa


# ---------------- assist run ----------------


def us_source(res=None):
    def fn(day, regime):
        return inputs(res)
    return fn


def test_run_writes_both_markets_and_journals_every_row(
        paths, wbs, financer, telegram):  # noqa: F811
    sources = pipeline.Sources(
        worldbankscape=wbs, fred=FakeFred(), financer=financer,
        undervalued=fake_source({"dividend_value": screen("dividend_value", cands=DIV)}),
        undervalued_us=us_source())
    res = pipeline.run(DAY, paths=paths, sources=sources, send=True,
                       notify_kw={"creds": CREDS, "client": telegram[1]})
    assert res.ok
    assert [p["market"] for p in res.undervalued] == ["IDN", "USA"]
    p = valid(json.loads((paths.out / "candidates" / "USA.json").read_text()))
    assert p["model_fingerprint"] == res.fingerprint
    # the F1 worldbankscape fixture has no USA: no USA stocks stance, so no budget, only watch
    assert not any(s["subject"] == "USA" for s in res.stances)
    assert p["stance"]["stance"] is None and p["sizing"]["budget_idr"] == 0
    assert all(r["action"] == "watch" for x in p["styles"] for r in x["rows"])
    # the financer fixture holds IDR lines only: nothing held in the US list
    assert all(not r["held"] for x in p["styles"] for r in x["rows"])

    recs = list(journal.Journal(paths.journal).read())
    summ = [r for r in recs if r["kind"] == "undervalued"]
    assert [r["subject"] for r in summ] == ["IDN", "USA"]
    us_rows = [r for r in recs if r["kind"] == "undervalued_row" and r["subject"] == "USA"]
    assert [r["outputs"]["symbol"] for r in us_rows] == ["KO", "JNJ", "MSFT", "KO"]
    assert all(r["fingerprint"] == res.fingerprint for r in us_rows)
    assert us_rows[0]["inputs"]["config"]["market"]["idr_per_usd"] == FX

    text = res.brief_path.read_text()
    assert "**USA**" in text and "MSFT" in text
    body = parse_qs(telegram[0][0].content.decode())["text"][0]
    assert "stocks to buy</b>" in body or "No steps this run" in body


def test_a_failing_us_source_leaves_idn_and_the_run_alone(paths, wbs, financer):  # noqa: F811
    def boom(day, regime):
        raise RuntimeError("usfin locked")

    sources = pipeline.Sources(
        worldbankscape=wbs, fred=FakeFred(), financer=financer,
        undervalued=fake_source({"dividend_value": screen("dividend_value", cands=DIV)}),
        undervalued_us=boom)
    res = pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert res.ok and [p["market"] for p in res.undervalued] == ["IDN"]
    assert any("USA" in s and "usfin locked" in s for s in res.stale_inputs)
    assert not (paths.out / "candidates" / "USA.json").exists()


def test_us_rerun_is_byte_identical(paths, wbs, financer):  # noqa: F811
    sources = pipeline.Sources(worldbankscape=wbs, fred=FakeFred(), financer=financer,
                               undervalued_us=us_source())
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    path = paths.out / "candidates" / "USA.json"
    before = path.read_bytes()
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert path.read_bytes() == before


def test_default_sources_wire_the_us_list():
    import inspect
    src = inspect.getsource(pipeline.Sources.default)
    assert "gather_live_usa" in src


def test_style_t_and_p_come_from_a_placebo_verdict_dict():
    res = results(garp=[])
    res["dividend_value"]["verdict"] = {"passed": True, "reason": "beats placebo",
                                        "score_t": 2.79, "p_value": 0.004, "control_t": 0.1}
    s = by_style(valid(build(inputs(res))))["dividend_value"]
    assert s["t"] == pytest.approx(2.79) and s["p"] == pytest.approx(0.004)


def test_brief_states_t_and_p_once_and_not_for_an_empty_replay():
    res = results(garp=[], garp_passed=False)
    res["dividend_value"]["verdict"] = {"passed": True, "score_t": 2.79, "p_value": 0.004,
                                        "reason": "beats placebo (t 2.79, p 0.004)"}
    res["garp"] |= {"quarters": 0, "verdict": {"passed": False, "score_t": 0.0, "p_value": 1.0,
                                               "reason": "insufficient sample (on 0, off 0)"}}
    text = "\n".join(brief.undervalued_lines(journal.jsonable(build(inputs(res)))))
    assert text.count("t 2.79") == 1
    assert "p 1.000" not in text
