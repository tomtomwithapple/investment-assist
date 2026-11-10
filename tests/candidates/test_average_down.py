"""Average down on a held name (P87, PLAN S68): one case per gate. Pure inputs built here."""

from __future__ import annotations

import pytest

from assist.candidates import average_down as ad
from assist.candidates.average_down import (
    GATE3,
    UNDERWATER_PCT,
    below_cost_pct,
    judge,
    limit_tranches,
    new_avg_cost,
)


def row(sym, sector="Keuangan", margin=2.0, price=1000.0, vol=0.3, med=5e10, passes=True):
    return {"symbol": sym, "sector": sector, "margin_pt": margin, "net_margin_pt": margin - 0.4,
            "price": price, "vol_1y": vol, "med_value_60d": med, "passes": passes}


def size(idr=3e6, shares=3000, n=1, why="margin 2.0pt / vol 30%; lump"):
    return {"idr": idr, "reason": why,
            "tranches": [{"day": 10 * i, "idr": idr / n, "shares": shares // n, "limit": None}
                         for i in range(n)]}


def call(**kw):
    rows = kw.pop("rows", [row("BMRI")])
    base = dict(held={"BMRI": 20e6}, basis={"BMRI": (1200.0, 20_000.0)},
                prices={"BMRI": 1000.0}, kept={r["symbol"]: r for r in rows if r["passes"]},
                size_rows=rows, sizes={}, budget_idr=0.0, portfolio_value_idr=1e9,
                stance={"stance": "neutral", "current_pct": 96.9, "target_pct": 48.0})
    return {v["symbol"]: v for v in judge(**{**base, **kw})}


def test_choices_are_the_users():
    assert UNDERWATER_PCT == 5.0 and GATE3 == "context"
    assert ad.config()["underwater_pct"] == 5.0


def test_below_cost_pct():
    assert below_cost_pct(1000.0, 1200.0) == pytest.approx(-16.667, abs=1e-3)
    assert below_cost_pct(None, 1200.0) is None and below_cost_pct(1000.0, None) is None


# ---------------- gate 1: underwater ----------------


def test_gate1_a_fee_sized_gap_is_not_underwater():
    v = call(prices={"BMRI": 1197.0})["BMRI"]
    assert (v["status"], v["gate"]) == ("stopped", 1)
    assert v["reason"] == "0.2% below cost (needs 5%)"
    assert call(prices={"BMRI": 1300.0})["BMRI"]["reason"] == "8.3% above cost"


def test_gate1_exactly_five_percent_below_counts():
    v = call(prices={"BMRI": 1140.0})["BMRI"]
    assert v["gate"] != 1 and v["below_cost_pct"] == pytest.approx(-5.0)


def test_gate1_no_cost_basis():
    v = call(basis={})["BMRI"]
    assert (v["gate"], v["reason"], v["avg_cost"]) == (1, "no cost basis", None)


# ---------------- gate 2: thesis intact ----------------


def test_gate2_a_name_no_passing_screen_kept_takes_the_trim_reason():
    v = call(kept={}, trims=[{"symbol": "BMRI", "idr": 20e6,
                              "reason": "trim in full: fails its screen"}])["BMRI"]
    assert (v["status"], v["gate"], v["reason"]) == (
        "stopped", 2, "trim in full: fails its screen")
    assert call(kept={})["BMRI"]["reason"] == "not kept by a passing screen"
    assert call(kept={}, any_passed=False)["BMRI"]["reason"] == "no screen passed its placebo"


# ---------------- gate 3: context only ----------------


def test_gate3_avoid_is_shown_and_stops_nothing():
    v = call(entry_status={"BMRI": "avoid"})["BMRI"]
    assert v["entry_status"] == "avoid"
    assert (v["status"], v["gate"]) == ("unfunded", 5)


# ---------------- gate 4: room ----------------


def test_gate4_at_the_per_name_cap():
    v = call(held={"BMRI": 50e6})["BMRI"]
    assert (v["status"], v["gate"], v["reason"]) == (
        "stopped", 4, "at or over the per-name cap of 5%")


def test_gate4_sector_cap_full():
    rows = [row(f"B{i}", margin=5.0 + i) for i in range(5)] + [row("BMRI", margin=2.0)]
    v = call(rows=rows)["BMRI"]
    assert (v["gate"], v["reason"]) == (4, "sector cap of 5 names (Keuangan)")
    # a tilted cap of 6 makes room
    assert call(rows=rows, caps={"sector_names": {"Keuangan": 6}})["BMRI"]["status"] == "unfunded"


def test_gate4_liquidity_unknown():
    v = call(rows=[row("BMRI", med=None)])["BMRI"]
    assert (v["gate"], v["reason"]) == (4, "no turnover (med_value_60d), liquidity unknown")


def test_gate4_sizing_dropped_the_tranche():
    v = call(budget_idr=5e6, excluded=[{"symbol": "BMRI",
                                        "reason": "tranche over the participation limit"}])
    assert (v["BMRI"]["gate"], v["BMRI"]["reason"]) == (4, "tranche over the participation limit")


# ---------------- gate 5: money ----------------


def test_gate5_no_budget_is_unfunded_and_sized_zero():
    v = call()["BMRI"]
    assert (v["status"], v["gate"], v["new_avg_cost"]) == ("unfunded", 5, None)
    assert v["reason"] == "no budget: 96.9% held against a target of 48.0%"
    st = {"stance": "avoid", "current_pct": 10.0, "target_pct": 20.0}
    assert call(stance=st)["BMRI"]["reason"] == "no budget: the stance is avoid"


def test_all_gates_clear_average_down_with_the_new_average():
    v = call(budget_idr=10e6, sizes={"BMRI": size()})["BMRI"]
    assert (v["status"], v["gate"]) == ("average_down", None)
    assert v["reason"].startswith("16.7% below cost; margin 2.0pt")
    # 20,000 at 1,200 + 3,000 at 1,000 with the 15bp buy fee
    assert v["new_avg_cost"] == pytest.approx((24e6 + 3e6 * 1.0015) / 23_000)
    assert v["new_avg_cost"] < v["avg_cost"]


def test_new_avg_cost_without_a_size():
    assert new_avg_cost(1200.0, 100.0, None) is None


# ---------------- gate 6: timing ----------------


def test_gate6_later_tranches_limited_at_entry_typical_below_the_price():
    t = size(n=3)["tranches"]
    assert [x["limit"] for x in limit_tranches(t, 1000.0, 900.0)] == [None, 900.0, 900.0]
    assert [x["limit"] for x in limit_tranches(t, 1000.0, 1100.0)] == [None, None, None]
    assert [x["limit"] for x in limit_tranches(t, 1000.0, None)] == [None, None, None]
    assert [x["day"] for x in limit_tranches(t, 1000.0, 900.0)] == [0, 10, 20]


def test_every_held_name_gets_one_verdict_in_symbol_order():
    out = judge(held={"ZZZZ": 1e6, "AAAA": 1e6}, basis={}, prices={}, kept={}, size_rows=[],
                sizes={})
    assert [v["symbol"] for v in out] == ["AAAA", "ZZZZ"]
    assert all(v["status"] in ad.STATUSES for v in out)
