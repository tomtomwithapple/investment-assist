"""PLAN S86 (P104-holdings): one record per held IDN stock answering the three questions apart
(thesis, valuation, fit), with the inputs judged, the cause of a change against the previous
record and the model fingerprint. Data is built in memory; nothing reads a store."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from assist.candidates import holdings as hd
from assist.candidates.dividend_value import DividendData
from assist.sources.idxmethod_series import Bar, Fundamentals

D = date.fromisoformat
DAY = D("2026-11-16")
BAR = D("2026-11-13")
FP = "sha256:" + "b" * 64
FP2 = "sha256:" + "c" * 64
HURDLE = 13.74

BANK = {"car": 20.0, "npl_gross": 2.0, "npl_cov": 200.0, "ldr": 90.0, "roe": 15.0,
        "free_float": 40.0, "med_value_60d": 5e10, "price": 4000.0, "vol_1y": 0.3,
        "days_traded_60": 60}
NONBANK = {"piotroski": 7, "altman_z": 3.0, "cfo_ttm": 1e12, "der": 0.5, "interest_cov": 5.0,
           "free_float": 40.0, "med_value_60d": 5e10, "price": 4000.0, "vol_1y": 0.3,
           "days_traded_60": 60}


def fund(period: str, *, ni=5000.0, equity=25000.0, cfo=6000.0) -> Fundamentals:
    p = D(period)
    return Fundamentals(p, p + timedelta(days=120), cfo, equity, 0.0, ni, ni, None, None,
                        None, None)


def divs(first: int, last: int, dps: float) -> list[dict]:
    return [{"ex": f"{y}-04-10", "value": dps, "ccy": "CURRENCY_IDR"}
            for y in range(first, last + 1)]


class Levels:
    def __init__(self, deep):
        self.entry_deep = deep


def judged(sym="BBNI", *, price=4000.0, row=BANK, dividends=None, period="2026-06-30",
           sector="Keuangan", deep=None, **row_kw):
    """One name's thesis inputs through the live code path (`judge_inputs`)."""
    data = DividendData(
        bars={sym: [Bar(BAR, price, price * 10)]},
        quarters={sym: [fund(period)]},
        dividends={sym: dividends if dividends is not None else divs(2021, 2026, 200.0)},
        sectors={sym: sector})
    r = {**row, "price": price, **row_kw}
    return hd.judge_inputs(sym, r, data, BAR, hurdle_pt=HURDLE,
                           levels=Levels(deep) if deep else None)


def div_name(sym, keeper, redundant, *, industry="Bank", size="large", position=2, group=3,
             allowed=False):
    return {"symbol": sym, "sector": "Keuangan", "industry": industry, "mktcap": 150e12,
            "size": size, "div_yield": 5.0, "group_size": group, "position": position,
            "keeper": keeper, "redundant": redundant, "allowed": allowed,
            "basis": "kept by a passing screen"}


def cands(names=(), trims=(), held=(), problems=(), price=None, tilt=None):
    """A minimal candidates payload: what `build` reads from it."""
    return {"market": "IDN", "as_of": DAY.isoformat(), "bar_date": BAR.isoformat(),
            "hurdle": {"required_pt": HURDLE, "drivers": []},
            "tilt": tilt or {"passed": False, "sectors": []},
            "diversification": {"names": list(names)},
            "sizing": {"trims": list(trims)},
            "average_down": {"names": [{"symbol": s, "price": (price or {}).get(s, 4000.0),
                                        "quantity": 1000} for s in held]},
            "data_problems": list(problems)}


def build(c, j, *, day=DAY, fp=FP, previous=None, holdings=None):
    held = holdings or {n["symbol"]: 4e6 for n in c["average_down"]["names"]}
    p = hd.build(c, j, day=day, fingerprint=fp, holdings=held, previous=previous)
    errors = list(hd.validator().iter_errors(json.loads(json.dumps(p))))
    assert not errors, [e.message for e in errors]
    return p


def rec(p, sym):
    return next(r for r in p["holdings"] if r["symbol"] == sym)


# ---------------- thesis ----------------


def test_a_sound_bank_passes_its_thesis_on_the_prudential_floor_and_dividend_gates():
    t = hd.thesis(judged())
    assert (t["status"], t["gate"], t["severity"], t["failed"]) == ("pass", None, None, [])
    assert t["basis"] == "dividend_value" and t["bank"] is True


def test_a_dividend_cut_is_a_hard_fail():
    t = hd.thesis(judged(dividends=divs(2021, 2025, 200.0) + divs(2026, 2026, 100.0)))
    assert (t["status"], t["gate"], t["severity"]) == ("fail", "cut", "hard")


def test_quality_floors_are_soft_and_negative_cfo_or_equity_hard():
    t = hd.thesis(judged("ABCD", row=NONBANK, sector="Industri", piotroski=3))
    assert (t["status"], t["gate"], t["severity"]) == ("fail", "F-score", "soft")
    t = hd.thesis(judged("ABCD", row=NONBANK, sector="Industri", altman_z=1.0))
    assert (t["gate"], t["severity"]) == ("Altman Z", "soft")
    t = hd.thesis(judged("ABCD", row=NONBANK, sector="Industri", cfo_ttm=-5.0))
    assert (t["gate"], t["severity"]) == ("negative CFO", "hard")
    t = hd.thesis(judged("ABCD", row=NONBANK, sector="Industri", der=-0.2))
    assert (t["gate"], t["severity"]) == ("negative equity", "hard")


def test_a_bank_floor_miss_is_soft():
    t = hd.thesis(judged(car=10.0))
    assert (t["status"], t["gate"], t["severity"]) == ("fail", "CAR", "soft")


def test_a_bank_below_the_f_floor_is_a_soft_fail():
    """S88 (phase P rule 5): BBNI at a point-in-time F of 3 fails as soft (S87's two reports
    in a row apply); at 4 it passes; with no F (n/a) it passes, flagged in the note."""
    t = hd.thesis(judged(f_pit=3.0))
    assert (t["status"], t["gate"], t["severity"]) == ("fail", "bank F-score", "soft")
    assert t["failed"] == [{"gate": "bank F-score", "severity": "soft"}]
    t = hd.thesis(judged(f_pit=4.0))
    assert (t["status"], t["note"]) == ("pass", None)
    t = hd.thesis(judged(f_pit=None))
    assert t["status"] == "pass" and t["severity"] is None
    assert t["note"] == "bank F-score n/a (too few signals computable): not counted"


def test_a_non_bank_ignores_the_bank_f():
    t = hd.thesis(judged("ABCD", row=NONBANK, sector="Industri", f_pit=1.0))
    assert (t["status"], t["note"]) == ("pass", None)


def test_a_hard_fail_anywhere_makes_the_whole_fail_hard():
    t = hd.thesis(judged(dividends=divs(2021, 2025, 200.0) + divs(2026, 2026, 100.0), car=10.0))
    assert t["gate"] == "CAR" and t["severity"] == "hard"
    assert [f["gate"] for f in t["failed"]] == ["CAR", "cut"]


def test_a_structural_gate_blocks_new_money_only():
    t = hd.thesis(judged(med_value_60d=1e8))
    assert t["status"] == "pass" and t["buy_gate"] == "liquidity"


def test_no_inputs_is_unknown():
    t = hd.thesis(None)
    assert t["status"] == "unknown" and t["gate"] is None


# ---------------- valuation ----------------


def test_valuation_fair_price_take_profit_review_and_above_fair():
    # fair = dividend / (required - growth) = 200 / (13.74% - 8%) = 3,484
    j = judged(price=3000.0, deep=2500.0)
    v = hd.valuation(j, 3000.0, HURDLE)
    assert v["fair_price"] == pytest.approx(200 / 0.0574, rel=1e-6)
    assert v["take_profit"] == 3480.0 and v["above_fair"] is False
    assert v["review_price"] == 2500.0 and v["price"] == 3000.0
    v = hd.valuation(judged(price=4000.0), 4000.0, HURDLE)
    assert v["above_fair"] is True and v["take_profit"] == 3480.0


def test_valuation_without_a_dividend_has_no_fair_price():
    v = hd.valuation(judged(dividends=[]), 4000.0, HURDLE)
    assert v["fair_price"] is None and v["above_fair"] is None and v["take_profit"] is None


# ---------------- the record ----------------


def test_bbni_reads_thesis_ok_valuation_near_fair_and_fit_redundant():
    c = cands(names=[div_name("BMRI", "BMRI", False, position=1),
                     div_name("BBRI", "BMRI", True), div_name("BBNI", "BMRI", True, position=3)],
              held=["BMRI", "BBRI", "BBNI"], price={"BBNI": 3400.0})
    j = {s: judged(s, price=3400.0) for s in ("BMRI", "BBRI", "BBNI")}
    p = build(c, j)
    r = rec(p, "BBNI")
    assert r["thesis"]["status"] == "pass"
    assert r["valuation"]["fair_price"] == pytest.approx(3484, abs=1)
    assert r["valuation"]["above_fair"] is False
    assert r["fit"]["redundant"] is True and r["fit"]["keeper"] == "BMRI"
    assert r["fit"]["ok"] is False and r["fit"]["group"] == {"industry": "Bank", "size": "large"}
    assert r["cause"] == "first" and r["previous"] is None and r["stale"] is False
    assert r["model_fingerprint"] == FP and r["judged_on"] == DAY.isoformat()
    assert r["inputs"] == {"report_period": "2026-06-30", "bar_date": BAR.isoformat(),
                           "last_dividend_ex": "2026-04-10"}
    assert r["context"] == {}
    assert p["schema_version"] == hd.SCHEMA_VERSION and p["model_fingerprint"] == FP
    assert [x["symbol"] for x in p["holdings"]] == ["BBNI", "BBRI", "BMRI"]


def test_a_held_banks_framework_context_is_carried_and_never_a_cause():
    """S96: `judged[sym]["context"]` (bank residual income) lands on the record as context;
    a moved RI fair value alone changes no answer and gives no cause."""
    ri_ctx = {"bank_ri": {"framework": "bank_ri", "ticker": "BBNI", "as_of": "2026-10-28",
                          "score": 0.9, "signal": "cheap", "components": {"fair_value": 3700.0},
                          "flags": [], "version": "0.1.0", "role": "context",
                          "gate": "untested"}}
    first = build(cands(held=["BBNI"]), {"BBNI": judged() | {"context": ri_ctx}},
                  day=D("2026-11-09"))
    assert rec(first, "BBNI")["context"] == ri_ctx
    assert hd.validator().is_valid(first)
    moved = {"bank_ri": ri_ctx["bank_ri"] | {"score": 1.2, "signal": "rich"}}
    r = rec(_again(first, {"BBNI": judged() | {"context": moved}}), "BBNI")
    assert r["context"] == moved and r["cause"] is None and r["changed"] == []


def test_a_cap_trim_is_a_fit_matter():
    c = cands(trims=[{"symbol": "BMRI", "idr": 4e6, "reason": "trim to the per-name cap of 5%"}],
              held=["BMRI"])
    r = rec(build(c, {"BMRI": judged("BMRI")}), "BMRI")
    assert r["fit"]["over_cap"] is True and r["fit"]["ok"] is False


def test_a_held_name_with_no_inputs_is_unknown_not_failed():
    r = rec(build(cands(held=["ZZZZ"]), {}), "ZZZZ")
    assert r["thesis"]["status"] == "unknown" and r["valuation"]["fair_price"] is None


def _again(prev, j, c=None, **kw):
    return build(c or cands(held=["BBNI"], price=kw.pop("price", None)), j, previous=prev, **kw)


def test_unchanged_verdict_has_no_cause_and_keeps_the_previous():
    first = build(cands(held=["BBNI"]), {"BBNI": judged()}, day=D("2026-11-09"))
    p = _again(first, {"BBNI": judged()})
    r = rec(p, "BBNI")
    assert r["cause"] is None and r["changed"] == []
    assert r["previous"]["judged_on"] == "2026-11-09"
    assert r["previous"]["thesis"]["status"] == "pass"


def test_a_price_crossing_fair_is_the_cause():
    first = build(cands(held=["BBNI"], price={"BBNI": 3000.0}), {"BBNI": judged(price=3000.0)},
                  day=D("2026-11-09"))
    r = rec(_again(first, {"BBNI": judged(price=4000.0)}, price={"BBNI": 4000.0}), "BBNI")
    assert r["cause"] == "price_cross" and r["changed"] == ["valuation"]


def test_a_new_report_is_the_cause_of_a_thesis_change():
    first = build(cands(held=["BBNI"]), {"BBNI": judged()}, day=D("2026-11-09"))
    j = judged(car=10.0)
    j["report_period"] = "2026-09-30"  # the Q3 report arrived with the CAR miss
    r = rec(_again(first, {"BBNI": j}), "BBNI")
    assert r["cause"] == "new_filing" and "thesis" in r["changed"]
    assert r["inputs"]["report_period"] == "2026-09-30"


def test_a_model_change_is_the_cause_whatever_else_moved():
    first = build(cands(held=["BBNI"]), {"BBNI": judged()}, day=D("2026-11-09"))
    r = rec(_again(first, {"BBNI": judged(car=10.0)}, fp=FP2), "BBNI")
    assert r["cause"] == "rule_version"


def test_a_fit_change_from_a_new_holding_is_a_holdings_change():
    c1 = cands(names=[div_name("BBNI", "BBNI", False, position=1, group=1)], held=["BBNI"])
    first = build(c1, {"BBNI": judged()}, day=D("2026-11-09"))
    c2 = cands(names=[div_name("BMRI", "BMRI", False, position=1, group=2),
                      div_name("BBNI", "BMRI", True, group=2)], held=["BBNI", "BMRI"])
    p = _again(first, {"BBNI": judged(), "BMRI": judged("BMRI")}, c=c2)
    assert rec(p, "BBNI")["cause"] == "holdings_change"
    assert rec(p, "BMRI")["cause"] == "first"


def test_bad_data_keeps_the_previous_verdict_marked_stale():
    first = build(cands(held=["BBNI"]), {"BBNI": judged()}, day=D("2026-11-09"))
    bad = "idx-method factors: price is null for 959 of 959 names"
    p = _again(first, {"BBNI": judged(car=10.0)}, c=cands(held=["BBNI", "NEWW"], problems=[bad]))
    assert p["stale"] is True and p["data_problems"] == [bad]
    r = rec(p, "BBNI")
    assert r["stale"] is True and r["thesis"]["status"] == "pass"  # not today's CAR fail
    assert r["judged_on"] == "2026-11-09" and r["cause"] is None
    n = rec(p, "NEWW")
    assert n["stale"] is True and n["thesis"]["status"] == "unknown"
    # the next clean run: a change after a stale record is a data fix
    r2 = rec(_again(p, {"BBNI": judged(car=10.0)}, day=D("2026-11-23")), "BBNI")
    assert r2["cause"] == "data_fix" and r2["stale"] is False


def test_a_same_day_rerun_is_identical():
    first = build(cands(held=["BBNI"], price={"BBNI": 3000.0}), {"BBNI": judged(price=3000.0)},
                  day=D("2026-11-09"))
    j = {"BBNI": judged(price=4000.0)}
    a = _again(first, j, price={"BBNI": 4000.0})
    b = _again(a, j, price={"BBNI": 4000.0})
    assert a == b and rec(b, "BBNI")["cause"] == "price_cross"


def test_write_and_load_round_trip(tmp_path):
    p = build(cands(held=["BBNI"]), {"BBNI": judged()})
    path = hd.write(json.loads(json.dumps(p)), tmp_path)
    assert path == tmp_path / "holdings" / "IDN.json"
    assert hd.load(tmp_path, "IDN") == json.loads(json.dumps(p))
    assert hd.load(tmp_path, "USA") is None
    path.write_text("{}")
    assert hd.load(tmp_path, "IDN") is None  # fails the schema: no previous


# ---------------- S87: the acted verdict (hysteresis) on the record ----------------


def _risk(c, pt):
    return c | {"hurdle": {"required_pt": pt, "drivers": []}}


def test_bbni_regime_toggle_moves_no_fair_price_and_no_verdict():
    """2026-11-11 risk-off (+1pt), 11-12 neutral, no filing: the fair price and the take-profit
    stay where the last report set them (S87 option a)."""
    c = cands(held=["BBNI"], price={"BBNI": 3400.0})
    off = build(_risk(c, HURDLE + 1.0), {"BBNI": judged(price=3400.0)}, day=D("2026-11-11"))
    on = build(_risk(c, HURDLE), {"BBNI": judged(price=3400.0)}, day=D("2026-11-12"),
               previous=off)
    a, b = rec(off, "BBNI"), rec(on, "BBNI")
    assert b["valuation"]["fair_price"] == a["valuation"]["fair_price"]
    assert b["valuation"]["required_pt"] == HURDLE + 1.0
    assert b["acted"]["valuation"]["required_live_pt"] == HURDLE
    assert b["valuation"]["above_fair"] == a["valuation"]["above_fair"] is True
    assert b["cause"] is None and b["acted"]["cause"] is None
    # a first record above fair is a baseline (user 2026-11-13): stop adding, no trim
    assert b["acted"]["action"] == a["acted"]["action"] == "stop_adding"
    assert a["acted"]["valuation"]["baseline"] is True


def test_a_first_soft_fail_holds_and_the_second_report_sells_on_the_record():
    c = cands(held=["BBNI"], price={"BBNI": 3000.0})
    first = build(c, {"BBNI": judged(car=10.0, price=3000.0)}, day=D("2026-11-09"))
    r = rec(first, "BBNI")
    assert r["thesis"]["status"] == "fail" and r["acted"]["action"] == "hold"
    j = judged(car=10.0, price=3000.0)
    j["report_period"] = "2026-09-30"
    r2 = rec(_again(first, {"BBNI": j}, c=c, day=D("2026-11-16")), "BBNI")
    assert r2["acted"]["action"] == "sell_all" and r2["acted"]["cause"] == "new_filing"
    assert r2["acted"]["thesis"]["soft_fail_periods"] == ["2026-06-30", "2026-09-30"]


def test_a_raw_thesis_change_without_a_report_is_not_acted():
    first = build(cands(held=["BBNI"]), {"BBNI": judged()}, day=D("2026-11-09"))
    r = rec(_again(first, {"BBNI": judged(car=10.0)}), "BBNI")
    assert r["thesis"]["status"] == "fail" and r["cause"] == "data_fix"  # raw, S86
    assert r["acted"]["thesis"]["status"] == "pass" and r["acted"]["cause"] is None


def test_a_name_sold_on_its_thesis_is_listed_until_bought_back():
    j = judged(dividends=divs(2021, 2025, 200.0) + divs(2026, 2026, 100.0))  # cut: hard
    first = build(cands(held=["BBNI", "BMRI"]), {"BBNI": j, "BMRI": judged("BMRI")},
                  day=D("2026-11-09"))
    assert rec(first, "BBNI")["acted"]["action"] == "sell_all" and first["sold"] == []
    p = _again(first, {"BMRI": judged("BMRI")}, c=cands(held=["BMRI"]))
    assert p["sold"] == [{"symbol": "BBNI", "since": DAY.isoformat(), "gate": "cut"}]
    p2 = _again(p, {"BMRI": judged("BMRI")}, c=cands(held=["BMRI"]), day=D("2026-11-23"))
    assert p2["sold"] == p["sold"]


def test_the_acted_block_survives_a_stale_run_and_the_config_names_the_numbers():
    first = build(cands(held=["BBNI"]), {"BBNI": judged()}, day=D("2026-11-09"))
    p = _again(first, {}, c=cands(held=["BBNI"], problems=["bad"]))
    assert rec(p, "BBNI")["acted"] == rec(first, "BBNI")["acted"]
    assert p["config"]["hysteresis"]["rearm_below_fair_pct"] == 10.0
