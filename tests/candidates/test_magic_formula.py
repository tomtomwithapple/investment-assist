"""Greenblatt's Magic Formula (P115, PLAN S98) on a hand-built cross-section.

Every name: one quarter T = 2025-06-30, knowable from T + 120 days (SEEN); mktcap from the bar
on SEEN. EV = mktcap + net debt, EY = EBIT / EV, ROC = the quarter's `roce` (%).

    sym   EBIT  mktcap  net debt  EV     EY     roce   rank EY  rank ROC  sum
    AAAA   100     900       100  1000   10%     30       2        2       4
    BBBB    50    1000         0  1000    5%     40       3        1       4
    CCCC    80     400         0   400   20%     10       1        4       5
    DDDD    30    1000         0  1000    3%     20       4        3       7
    EEEE   -10     500         0   500   -2%     -5       5        5      10

AAAA and BBBB tie on 4; the better EY rank (AAAA's 2) goes first. Order A, B, C, D, E; the
percentile is 100 × (n − position) / (n − 1): 100, 75, 50, 25, 0; the top fifth (5 // 5 = 1)
is AAAA alone, the bottom fifth EEEE.

Out of the universe: FFFF (sector Keuangan), GGGG (no net debt: no EV), HHHH (net cash above its
mktcap: EV <= 0), IIII (no roce).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from assist.candidates import frameworks as fw
from assist.candidates.frameworks import magic_formula as mf
from assist.sources.idxmethod_series import Bar, Fundamentals

LAG = timedelta(days=120)
T = date(2025, 6, 30)
SEEN = T + LAG
B = 1e9


def q(period, ebit, net_debt, roce):
    return Fundamentals(period, period + LAG, 1.0, 1.0, net_debt, 1.0, ebit, 1.0, roce, 1.0, 1.0)


def bars(mktcap, price=1000.0, start=SEEN - timedelta(days=5), days=6):
    return [Bar(start + timedelta(days=i), price, mktcap) for i in range(days)]


TABLE = {  # sym: (EBIT, mktcap, net debt, roce)
    "AAAA": (100 * B, 900 * B, 100 * B, 30.0),
    "BBBB": (50 * B, 1000 * B, 0.0, 40.0),
    "CCCC": (80 * B, 400 * B, 0.0, 10.0),
    "DDDD": (30 * B, 1000 * B, 0.0, 20.0),
    "EEEE": (-10 * B, 500 * B, 0.0, -5.0),
    "FFFF": (90 * B, 300 * B, 0.0, 50.0),
    "GGGG": (90 * B, 300 * B, None, 50.0),
    "HHHH": (90 * B, 100 * B, -200 * B, 50.0),
    "IIII": (90 * B, 300 * B, 0.0, None),
}
GOOD_ROW = {"free_float": 40.0, "med_value_60d": 10e9, "price": 1000.0, "vol_1y": 0.3,
            "days_traded_60": 60}


def inputs(table=TABLE, d=SEEN, rows=None, universe=None, **kw):
    quarters = {s: [q(T, e, nd, r)] for s, (e, _, nd, r) in table.items()}
    bs = {s: bars(m) for s, (_, m, _, _) in table.items()}
    universe = universe if universe is not None else {
        s: {"name": f"PT {s} Tbk", "sector": "Keuangan" if s == "FFFF" else "Energi",
            "delisted": False} for s in table}
    rows = rows if rows is not None else {s: dict(GOOD_ROW) for s in table}
    return mf.MagicInputs(d, quarters, {}, kw.pop("banks", frozenset()), bars=bs, rows=rows,
                          universe=universe, **kw)


def res(sym, inp=None):
    return mf.MagicFormula().evaluate(sym, inp or inputs())


def test_ranks_on_a_hand_built_cross_section():
    out = {s: res(s) for s in ["AAAA", "BBBB", "CCCC", "DDDD", "EEEE"]}
    c = out["AAAA"].components
    assert c["earnings_yield"] == pytest.approx(0.10) and c["ev"] == pytest.approx(1000 * B)
    assert c["roc"] == pytest.approx(0.30)
    assert {s: (r.components["rank_ey"], r.components["rank_roc"],
                r.components["combined_rank"]) for s, r in out.items()} == {
        "AAAA": (2, 2, 4), "BBBB": (3, 1, 4), "CCCC": (1, 4, 5), "DDDD": (4, 3, 7),
        "EEEE": (5, 5, 10)}
    assert [out[s].components["position"] for s in out] == [1, 2, 3, 4, 5]
    assert [out[s].score for s in out] == pytest.approx([100, 75, 50, 25, 0])
    assert [out[s].signal for s in out] == ["top", "middle", "middle", "middle", "bottom"]
    assert all(r.components["n_universe"] == 5 for r in out.values())
    assert out["AAAA"].as_of == SEEN
    assert (out["AAAA"].framework, out["AAAA"].role, out["AAAA"].gate) == (
        "magic_formula", "context", "untested")
    assert any("EBIT" in f and "<= 0" in f for f in out["EEEE"].flags)


def test_rank_ties_take_the_mean_rank():
    r = mf.rank_cross_section({"A": (0.1, 0.2), "B": (0.1, 0.1), "C": (0.05, 0.3)})
    assert (r["A"]["rank_ey"], r["B"]["rank_ey"], r["C"]["rank_ey"]) == (1.5, 1.5, 3)
    assert r["A"]["combined_rank"] == 3.5 and r["A"]["position"] == 1


def test_financials_and_banks_are_out_and_flagged():
    r = res("FFFF")
    assert r.score is None and r.signal == fw.NA and "financial" in r.flags[0]
    bank = res("AAAA", inputs(banks=frozenset({"AAAA"})))
    assert bank.score is None and "bank" in bank.flags[0]
    # a delisted name has no sector: the company name tells a bank or a finance house
    uni = {s: {"name": f"PT {s} Tbk", "sector": "Energi", "delisted": False} for s in TABLE}
    uni["BBBB"] = {"name": "Bank Mitra Tbk.", "sector": None, "delisted": True}
    uni["CCCC"] = {"name": "Mandala Multifinance Tbk.", "sector": None, "delisted": True}
    inp = inputs(universe=uni)
    assert "financial" in res("BBBB", inp).flags[0] and res("CCCC", inp).score is None
    assert res("AAAA", inp).components["n_universe"] == 4  # FFFF is Energi now


@pytest.mark.parametrize("sym, why", [("GGGG", "no net debt"), ("HHHH", "EV"),
                                      ("IIII", "no roce")])
def test_missing_ev_ebit_or_roce_is_na_never_imputed(sym, why):
    r = res(sym)
    assert r.score is None and r.signal == fw.NA and any(why in f for f in r.flags)
    assert res("AAAA").components["n_universe"] == 5  # they are not in the universe


def test_no_ebit_is_na():
    t = dict(TABLE, GGGG=(None, 300 * B, 0.0, 50.0))
    r = res("GGGG", inputs(t))
    assert r.score is None and any("no EBIT" in f for f in r.flags)


def test_point_in_time_reads_only_the_quarter_knowable():
    inp = inputs()
    newer = q(date(2025, 9, 30), 1 * B, 0.0, 1.0)  # AAAA collapses next quarter
    inp.quarters["AAAA"].append(newer)
    assert res("AAAA", inp).components["position"] == 1
    later = SEEN + timedelta(days=92)
    inp2 = inputs(d=later)
    inp2.quarters["AAAA"].append(newer)
    for bs in inp2.bars.values():
        bs.extend(Bar(SEEN + timedelta(days=i), 1000.0, bs[-1].mktcap) for i in range(1, 93))
    r = res("AAAA", inp2)
    assert r.as_of == newer.available and r.components["position"] == 4  # EEEE stays last
    early = inputs(d=SEEN - timedelta(days=1))
    assert res("AAAA", early).score is None
    assert "no quarterly fundamentals" in res("AAAA", early).flags[0]


def test_a_name_failing_a_gate_is_ranked_against_the_universe_and_flagged():
    rows = {s: dict(GOOD_ROW) for s in TABLE}
    rows["CCCC"]["med_value_60d"] = 1e6
    r = res("CCCC", inputs(rows=rows))
    assert any("liquidity" in f for f in r.flags)
    assert r.components["n_universe"] == 4 and r.components["position"] == 3
    assert res("AAAA", inputs(rows=rows)).components["n_universe"] == 4


def test_wrong_inputs_are_na():
    r = mf.MagicFormula().evaluate("AAAA", None)
    assert r.score is None and r.flags


# ---------------- replay ----------------

Q0, Q1, Q2 = date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30)


def replay_data():
    """Six names over three quarter ends. XDEL (delisted, no sector) trades until 2026-02-15;
    YBNK ("Bank Y", delisted) is a financial; ZSML (mktcap 0.5T, no history) fails the
    liquidity stand-in; the rest have mktcap 2T. Every quarter T is knowable at Q0."""
    syms = {"AAAA": (100, 0.0, 30.0), "BBBB": (50, 0.0, 40.0), "CCCC": (80, 0.0, 10.0),
            "XDEL": (300, 0.0, 60.0), "YBNK": (300, 0.0, 60.0), "ZSML": (300, 0.0, 60.0)}
    quarters = {s: [q(T, e * B, nd, r)] for s, (e, nd, r) in syms.items()}
    cap = {s: 2000 * B for s in syms} | {"ZSML": 500 * B}
    days = sorted({Q0 - timedelta(days=7), Q1, Q2, date(2026, 2, 15)}
                  | {Q0 + timedelta(days=7 * i) for i in range(27)})
    bs = {}
    for s in syms:
        last = date(2026, 2, 15) if s == "XDEL" else Q2
        bs[s] = [Bar(d, 1000.0 if d <= Q0 else 1100.0, cap[s]) for d in days if d <= last]
    universe = {s: {"name": f"PT {s} Tbk", "sector": "Energi", "delisted": False}
                for s in syms}
    universe["XDEL"] = {"name": "PT X Tbk", "sector": None, "delisted": True}
    universe["YBNK"] = {"name": "Bank Y Tbk", "sector": None, "delisted": True}
    return bs, quarters, universe


def test_replay_keeps_a_delisted_name_and_drops_financials_and_illiquid():
    bs, quarters, universe = replay_data()
    divs = {"AAAA": [{"ex": "2026-02-01", "value": 50.0}]}
    panel = mf.replay_panel(bs, quarters, divs, universe, [Q0, Q1, Q2], min_mktcap=1e12)
    (d0, r0), (d1, r1), (d2, r2) = panel
    assert d0 == Q0
    assert [x["symbol"] for x in r0] == ["XDEL", "AAAA", "BBBB", "CCCC"]  # best first
    by = {x["symbol"]: x for x in r0}
    assert by["XDEL"]["fwd"] == pytest.approx(0.1)  # held at its last bar (1,100)
    assert by["AAAA"]["fwd"] == pytest.approx(0.15)  # 1,000 → 1,100 + 50 ex in the quarter
    assert "XDEL" not in {x["symbol"] for x in r1}  # no bar near Q1: stopped trading
    assert r2 and all(x["fwd"] is None for x in r2)  # the last quarter has no next one


def test_replay_uses_history_liquidity_where_it_exists():
    bs, quarters, universe = replay_data()
    liq = {"ZSML": {Q0: (10e9, 60)}, "AAAA": {Q0: (1e6, 60)}}
    panel = mf.replay_panel(bs, quarters, {}, universe, [Q0, Q1], min_mktcap=1e12,
                            liquidity=liq)
    syms = [x["symbol"] for x in panel[0][1]]
    assert "ZSML" in syms and "AAAA" not in syms  # history beats the mktcap stand-in


def test_history_liquidity_point_in_time():
    hist = {"AAAA": [{"date": (date(2025, 10, 1) + timedelta(days=i)).isoformat(),
                      "close": 100, "value": 1e9 * (i + 1), "volume": 10} for i in range(92)]}
    liq = mf.history_liquidity(hist, [date(2025, 9, 30), Q0])
    assert date(2025, 9, 30) not in liq.get("AAAA", {})  # no 60 bars yet
    med, traded = liq["AAAA"][Q0]
    assert traded == 60 and med == pytest.approx(1e9 * (92 - 60 + 1 + 30))


def test_registered_with_a_replay():
    f = mf.MagicFormula()
    assert (f.role, f.gate) == ("context", "untested") and callable(f.replay)


def test_board_replay_prints_the_delisted_coverage():
    from types import SimpleNamespace

    bs, quarters, universe = replay_data()
    ctx = SimpleNamespace(
        dividend_data=SimpleNamespace(bars=bs, quarters=quarters, dividends={}),
        universe=universe, table={"YBNK": {"car": 20.0}}, bar_date=Q2, stale=[],
        stocks=SimpleNamespace(history=lambda: {}))
    rep = mf.MagicFormula().replay(ctx)
    assert rep.name == "magic_formula" and rep.kind == "framework"
    assert rep.notes[0].startswith("delisted coverage: 2 of 2 delisted names")
    assert "1 are financials" in rep.notes[0] and "1 ever enter the pool" in rep.notes[0]
