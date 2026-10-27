"""F5 (PLAN S20): one ranked undervalued list per market from P36 (dividend) and P37 (GARP), the
S16 tilt, P21's entry and costs, layer 5 and P38's sizes, into out/candidates, the brief, the
Telegram summary and the journal. In-memory screen results and the F1 fixtures only: nothing here
reads a real store or reaches the network."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs

import pytest
from test_run_e2e import CREDS, FakeFred, _run, financer, paths, telegram, wbs  # noqa: F401

from assist import brief, journal, pipeline
from assist.candidates import sizing
from assist.candidates.costs import Cost
from assist.candidates.entry import EntryLevels
from assist.layers import undervalued as uv
from assist.layers.types import Regime
from assist.sources.financer import Holding, Statement

DAY = date(2026, 10, 23)
BARS = date(2026, 10, 9)
REGIME = Regime(as_of=DAY, state="neutral", dollar="flat", sources=("sec-edgar",))
FP = "sha256:" + "a" * 64


def screen(name, passed=True, cands=(), pool=None, reason=None):
    rows = [dict(c) for c in cands]
    return {
        "screen": name, "as_of": BARS, "passed": passed,
        "blocked": None if passed else (reason or "t-stat 1.30 below 2.0"),
        "verdict": {"passed": passed, "reason": reason or ("beats placebo" if passed
                                                           else "t-stat 1.30 below 2.0"),
                    "t": 2.79 if passed else 1.30, "p": 0.004 if passed else 0.085},
        "quarters": 37, "pool": len(rows) if pool is None else pool, "hurdle_pt": 13.74,
        "hurdle_drivers": ["SBN 10Y 7.19% (IGSYC)"], "ranking": rows,
        "candidates": rows if passed else [], "stale_inputs": [],
    }


def cand(sym, sector, expected, margin, **kw):
    return {"symbol": sym, "sector": sector, "bank": False, "expected_pt": expected,
            "margin_pt": margin, "price": 1000.0, "risks": [], "legs": {}, **kw}


def cost(flags=(), rt=40.0):
    half = (rt - 40.0) / 2
    return Cost(1000.0, 10000, 1e7, 15.0, 25.0, half, 0.0, None, 0.01, tuple(flags))


def levels(sym, typical=900.0, deep=800.0, status="wait"):
    return EntryLevels(sym, BARS, 1000.0, 1200.0, -16.7, 40.0, 3, -20.0, -35.0, -33.0, 10.0,
                       12.0, 60.0, 5.0, typical, deep, status)


def factor(price=1000.0, vol=0.3, med=5e10):
    return {"price": price, "vol_1y": vol, "med_value_60d": med, "amihud": 1e-12}


def tilt(passed=False, shifts=None, caps=None):
    shifts, caps = shifts or {}, caps or {}
    sectors = ["Energi", "Keuangan", "Barang Konsumen Primer"]
    return {
        "passed": passed, "blocked": None if passed else "t-stat -1.11 below 2.0",
        "verdict": {"reason": "beats placebo" if passed else "t-stat -1.11 below 2.0"},
        "fingerprint": "f" * 64,
        "tilts": [{"sector": s, "tilt": 0.25 if s == "Energi" else -0.3,
                   "margin_shift_pt": shifts.get(s, 0.0), "cap": caps.get(s, 5),
                   "raw_margin_shift_pt": -0.5, "raw_cap": 6, "drivers": [], "stale": []}
                  for s in sectors],
        "stale_inputs": [],
    }


def inputs(screens, tilt_res=None, plan=None, factors=None):
    syms = {c["symbol"] for s in screens.values() for c in s["ranking"]}
    return uv.UndervaluedInputs(
        market="IDN", bar_date=BARS, screens=screens, tilt=tilt_res or tilt(),
        factors=factors if factors is not None else {s: factor() for s in syms},
        plan=plan if plan is not None else {s: {"levels": levels(s), "cost": cost()}
                                            for s in syms},
        stale_inputs=("idx-method cache/history (ends 2026-10-09)",),
        sources=("idx-method", "dbnomics"))


def stance(kind="neutral", current=10.0, target=10.0, entry=None):
    return {"subject": "IDN", "asset": "stocks", "stance": kind,
            "entry": entry or {"style": "lump", "tranches": 1, "spacing_days": 0},
            "portfolio": {"current_pct": current, "target_pct": target, "delta": "x"}}


def build(inp, *, st=None, value=1e9, holdings=None, regime=REGIME):
    return uv.assemble(inp, day=DAY, stance=st or stance(), portfolio_value_idr=value,
                       holdings=holdings or {}, regime=regime, fingerprint=FP)


def valid(payload):
    errors = list(uv.validator().iter_errors(payload))
    assert not errors, [e.message for e in errors]
    return payload


def by_style(payload):
    return {s["style"]: s for s in payload["styles"]}


DIV = [cand("BMRI", "Keuangan", 16.25, 2.51), cand("JPFA", "Barang Konsumen Primer", 14.86, 1.12),
       cand("ELSA", "Energi", 14.26, 0.52)]
GARP = [cand("NICL", "Barang Baku", 21.0, 7.3), cand("ELSA", "Energi", 24.3, 10.5),
        cand("JPFA", "Barang Konsumen Primer", 20.1, 6.3)]


# ---------------- assembly ----------------


def test_failed_screen_is_listed_with_its_verdict_and_no_names():
    p = valid(build(inputs({"dividend_value": screen("dividend_value", cands=DIV),
                            "garp": screen("garp", passed=False, cands=GARP, pool=30)})))
    g = by_style(p)["garp"]
    assert g["passed"] is False and g["rows"] == [] and g["pool"] == 30
    assert "t-stat 1.30" in g["verdict"]
    assert [r["symbol"] for r in by_style(p)["dividend_value"]["rows"]] == ["BMRI", "JPFA", "ELSA"]


def test_rank_within_style_by_margin_never_mixed():
    p = valid(build(inputs({"dividend_value": screen("dividend_value", cands=DIV),
                            "garp": screen("garp", cands=GARP)})))
    s = by_style(p)
    assert [(r["rank"], r["symbol"]) for r in s["garp"]["rows"]] == [
        (1, "ELSA"), (2, "NICL"), (3, "JPFA")]
    assert [r["rank"] for r in s["dividend_value"]["rows"]] == [1, 2, 3]
    assert all(r["style"] == "garp" for r in s["garp"]["rows"])
    assert [x["style"] for x in p["styles"]] == ["dividend_value", "garp"]


def test_failed_tilt_moves_nothing_and_keeps_default_caps():
    p = build(inputs({"dividend_value": screen("dividend_value", cands=DIV)},
                     tilt_res=tilt(passed=False)))
    assert p["tilt"]["passed"] is False
    assert all(r["margin_shift_pt"] == 0 for r in p["styles"][0]["rows"])
    assert p["styles"][0]["rows"][0]["margin_pt"] == pytest.approx(2.51)
    assert p["tilt"]["fingerprint"] == "f" * 64


def test_passed_tilt_shifts_the_required_margin_and_drops_a_name_below_it():
    t = tilt(passed=True, shifts={"Energi": -0.5, "Keuangan": 0.6}, caps={"Keuangan": 4})
    p = valid(build(inputs({"dividend_value": screen("dividend_value", cands=DIV)},
                           tilt_res=t)))
    rows = {r["symbol"]: r for r in p["styles"][0]["rows"]}
    assert rows["BMRI"]["margin_pt"] == pytest.approx(2.51 - 0.6)
    assert rows["ELSA"]["margin_pt"] == pytest.approx(0.52 + 0.5)
    assert [r["symbol"] for r in p["styles"][0]["rows"]] == ["BMRI", "JPFA", "ELSA"]
    # a headwind larger than the margin takes the name off the list
    t2 = tilt(passed=True, shifts={"Energi": 0.6})
    p2 = build(inputs({"dividend_value": screen("dividend_value", cands=DIV)}, tilt_res=t2))
    assert "ELSA" not in {r["symbol"] for r in p2["styles"][0]["rows"]}
    assert any(d["symbol"] == "ELSA" and "tilt" in d["reason"]
               for d in p2["styles"][0]["dropped"])


def test_passed_tilt_caps_reach_sizing(monkeypatch):
    seen = {}
    real = sizing.size

    def spy(*a, **kw):
        seen["caps"] = kw.get("caps")
        return real(*a, **kw)

    monkeypatch.setattr(uv.sizing, "size", spy)
    build(inputs({"dividend_value": screen("dividend_value", cands=DIV)},
                 tilt_res=tilt(passed=True, caps={"Keuangan": 4})))
    assert seen["caps"]["sector_names"]["Keuangan"] == 4
    build(inputs({"dividend_value": screen("dividend_value", cands=DIV)},
                 tilt_res=tilt(passed=False, caps={"Keuangan": 4})))
    assert seen["caps"] is None


def test_entry_and_costs_as_layer4_assembles_them():
    plan = {"BMRI": {"levels": levels("BMRI", typical=None, deep=800.0), "cost": cost()},
            "JPFA": {"levels": levels("JPFA"), "cost": cost(flags=("over_participation",))},
            "ELSA": {"levels": None, "cost": cost(rt=40.0)}}
    p = valid(build(inputs({"dividend_value": screen("dividend_value", cands=DIV)}, plan=plan)))
    rows = {r["symbol"]: r for r in p["styles"][0]["rows"]}
    assert rows["BMRI"]["entry"] == {"level": 800.0, "basis": "deep", "status": "wait"}
    assert rows["ELSA"]["entry"]["basis"] == "none"
    assert rows["ELSA"]["net_margin_pt"] == pytest.approx(0.52 - 0.4)
    assert rows["ELSA"]["cost"]["round_trip_bps"] == pytest.approx(40.0)
    assert "JPFA" not in rows
    assert {"symbol": "JPFA", "reason": "over_participation"} in p["styles"][0]["dropped"]


def test_name_whose_round_trip_eats_the_margin_is_dropped():
    plan = {s: {"levels": levels(s), "cost": cost(rt=200.0)} for s in ("BMRI", "JPFA", "ELSA")}
    p = build(inputs({"dividend_value": screen("dividend_value", cands=DIV)}, plan=plan))
    assert [r["symbol"] for r in p["styles"][0]["rows"]] == ["BMRI"]
    assert any("round trip" in d["reason"] for d in p["styles"][0]["dropped"])


def test_neutral_stance_sizes_nothing_and_held_names_show_layer5_fit():
    p = valid(build(inputs({"dividend_value": screen("dividend_value", cands=DIV)}),
                    holdings={"BMRI": 20e6, "GGRM": 5e6}))
    rows = {r["symbol"]: r for r in p["styles"][0]["rows"]}
    assert rows["BMRI"]["held"] is True and rows["BMRI"]["held_idr"] == 20e6
    assert rows["BMRI"]["action"] == "hold" and rows["JPFA"]["action"] == "watch"
    assert all(r["size"] is None for r in rows.values())
    assert p["sizing"]["budget_idr"] == 0
    # GGRM is held but no passing screen ranked it: no trim call, only listed
    assert not any(t["symbol"] == "GGRM" for t in p["sizing"]["trims"])
    assert {"symbol": "GGRM", "reason": "held, not rated by any passing screen: no trim call"} \
        in p["sizing"]["excluded"]


def test_held_name_a_passing_screen_ranked_below_the_hurdle_is_trimmed():
    res = screen("dividend_value", cands=DIV)
    res["ranking"] = [*DIV, cand("UNVR", "Barang Konsumen Primer", 12.0, -1.74)]
    p = valid(build(inputs({"dividend_value": res}),
                    holdings={"UNVR": 8e6, "BMRI": 80e6}))
    trims = {t["symbol"]: t for t in p["sizing"]["trims"]}
    assert trims["UNVR"]["idr"] == 8e6 and "fails its screen" in trims["UNVR"]["reason"]
    assert trims["BMRI"]["idr"] == pytest.approx(30e6)  # back to the 5% per-name cap


def test_overweight_stance_sizes_each_name_once_across_styles():
    p = valid(build(inputs({"dividend_value": screen("dividend_value", cands=DIV),
                            "garp": screen("garp", cands=GARP)}),
                    st=stance("overweight", 10.0, 20.0)))
    assert p["sizing"]["budget_idr"] == pytest.approx(1e8)
    sized = [r for s in p["styles"] for r in s["rows"] if r["size"]]
    assert sized and all(r["action"] == "add" for r in sized)
    # ELSA and JPFA are in both styles: one size each, shown under the style with the larger margin
    assert sorted(r["symbol"] for r in sized) == sorted({r["symbol"] for r in sized})
    elsa = [r for s in p["styles"] for r in s["rows"] if r["symbol"] == "ELSA"]
    assert [r["style"] for r in elsa if r["size"]] == ["garp"]
    total = sum(r["size"]["idr"] for r in sized)
    assert total + p["sizing"]["unspent_idr"] == pytest.approx(p["sizing"]["budget_idr"])


def test_no_trims_when_no_screen_passed():
    p = valid(build(inputs({"dividend_value": screen("dividend_value", passed=False, cands=DIV)}),
                    holdings={"BMRI": 20e6}))
    assert p["sizing"]["trims"] == []
    assert p["styles"][0]["rows"] == []


def test_payload_carries_config_disclaimer_and_sources():
    p = valid(build(inputs({"dividend_value": screen("dividend_value", cands=DIV)})))
    assert p["model_fingerprint"] == FP and p["currency"] == "IDR"
    assert p["disclaimer"] == "Heuristic, not investment advice."
    assert "idx-method" in p["sources"]
    cfg = p["config"]
    assert cfg["tilt_fingerprint"] == "f" * 64
    assert cfg["hurdle"]["risk_off_premium_pt"] == 1.0
    assert cfg["sizing"]["caps"]["name_pct"] == 5.0
    assert set(cfg["screens"]) == {"dividend_value"}
    assert p["hurdle"]["required_pt"] == pytest.approx(13.74)
    assert "idx-method cache/history (ends 2026-10-09)" in p["stale_inputs"]
    bad = dict(p)
    del bad["disclaimer"]
    assert list(uv.validator().iter_errors(bad))


def test_top_takes_ranks_in_turn_never_a_mixed_score():
    p = build(inputs({"dividend_value": screen("dividend_value", cands=DIV),
                      "garp": screen("garp", cands=GARP)}))
    assert [(r["style"], r["symbol"]) for r in uv.top(p, 5)] == [
        ("dividend_value", "BMRI"), ("garp", "ELSA"), ("dividend_value", "JPFA"),
        ("garp", "NICL"), ("dividend_value", "ELSA")]


def test_holdings_from_statements_keeps_idx_stocks_per_symbol():
    st = Statement("ajaib", "A", "portfolio", DAY, None, None, 0.0,
                   (Holding("BBCA", "", "1", 600.0, "IDR"), Holding("FR0081", "", "1", 9.0, "IDR"),
                    Holding("BBCA", "", "1", 100.0, "IDR"), Holding("AAPL", "", "1", 5.0, "USD")))
    assert uv.holdings_from([st]) == {"BBCA": 700.0}


# ---------------- brief and Telegram ----------------


def test_brief_lines_show_counts_verdicts_rows_and_failed_screens():
    p = build(inputs({"dividend_value": screen("dividend_value", cands=DIV),
                      "garp": screen("garp", passed=False, cands=GARP, pool=30)}))
    lines = brief.undervalued_lines(p)
    text = "\n".join(lines)
    assert "dividend_value: passed" in text and "3 name(s)" in text
    assert "garp: verdict failed (t-stat 1.30 below 2.0)" in text and "no names" in text
    assert "BMRI" in text and "NICL" not in text


def test_build_brief_adds_the_section_from_out_candidates(tmp_path):
    out = tmp_path / "out"
    p = build(inputs({"dividend_value": screen("dividend_value", cands=DIV)}))
    uv.write(p, out)
    text = brief.build_brief(out, tmp_path / "snap")
    assert "## Undervalued candidates" in text and "BMRI" in text
    assert "## Undervalued candidates" not in brief.build_brief(tmp_path / "empty",
                                                               tmp_path / "snap")


def test_message_lists_top_five():
    p = build(inputs({"dividend_value": screen("dividend_value", cands=DIV),
                      "garp": screen("garp", cands=GARP)}))
    st = [{"subject": "IDN", "asset": "stocks", "stance": "neutral", "score": 48.6,
           "portfolio": {"delta": "0.0pt hold"}, "stale_inputs": []}]
    text = pipeline.message(st, regime="neutral", day=DAY, brief_path=None, undervalued=[p])
    assert "Undervalued IDN" in text
    assert text.index("BMRI") < text.index("NICL")
    assert text.count("\n  ") >= 5 and text.rstrip().endswith("not investment advice.")


# ---------------- assist run ----------------


def fake_source(screens):
    def fn(day, regime):
        return inputs(screens)
    return fn


def test_run_writes_candidates_journals_every_row_and_adds_brief_and_telegram(
        paths, wbs, financer, telegram):  # noqa: F811
    src = fake_source({"dividend_value": screen("dividend_value", cands=DIV),
                       "garp": screen("garp", passed=False, cands=GARP)})
    sources = pipeline.Sources(worldbankscape=wbs, fred=FakeFred(), financer=financer,
                               undervalued=src)
    res = pipeline.run(DAY, paths=paths, sources=sources, send=True,
                       notify_kw={"creds": CREDS, "client": telegram[1]})
    assert res.ok
    path = paths.out / "candidates" / "IDN.json"
    p = valid(json.loads(path.read_text()))
    assert p["model_fingerprint"] == res.fingerprint
    assert res.undervalued and res.undervalued[0]["market"] == "IDN"
    # layer 5 from the financer fixture: BBCA held (IDR 600,000), not rated by the screens
    assert p["sizing"]["trims"] == []
    assert any(x["symbol"] == "BBCA" for x in p["sizing"]["excluded"])
    # stances are still exactly the stance files, the candidates file survives write_out
    assert (paths.out / "IDN" / "stocks.json").is_file()

    recs = list(journal.Journal(paths.journal).read())
    rows = [r for r in recs if r["kind"] == "undervalued_row"]
    assert [r["outputs"]["symbol"] for r in rows] == ["BMRI", "JPFA", "ELSA"]
    assert all(r["fingerprint"] == res.fingerprint for r in rows)
    assert rows[0]["inputs"]["config"]["tilt_fingerprint"] == "f" * 64
    summ = [r for r in recs if r["kind"] == "undervalued"]
    assert len(summ) == 1
    assert summ[0]["outputs"]["styles"]["garp"]["passed"] is False

    text = res.brief_path.read_text()
    assert "## Undervalued candidates" in text and "BMRI" in text
    body = parse_qs(telegram[0][0].content.decode())["text"][0]
    assert "Undervalued IDN" in body and "BMRI" in body


def test_run_is_byte_identical_on_rerun_and_survives_a_failing_source(
        paths, wbs, financer):  # noqa: F811
    src = fake_source({"dividend_value": screen("dividend_value", cands=DIV)})
    sources = pipeline.Sources(worldbankscape=wbs, fred=FakeFred(), financer=financer,
                               undervalued=src)
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    path = paths.out / "candidates" / "IDN.json"
    before = path.read_bytes()
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert path.read_bytes() == before

    def boom(day, regime):
        raise RuntimeError("store exploded")

    sources.undervalued = boom
    res = pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert res.ok and res.undervalued == []
    assert any("undervalued" in s and "store exploded" in s for s in res.stale_inputs)


def test_run_without_the_source_writes_no_candidates(paths, wbs, financer):  # noqa: F811
    res = _run(paths, wbs, financer, send=False)
    assert res.ok and not (paths.out / "candidates").exists()
