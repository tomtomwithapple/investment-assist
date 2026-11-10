"""Pro-rata sales for a leg's unnamed cut (P93, PLAN S75, choice 1)."""

from __future__ import annotations

import pytest

from assist.candidates.rebalance import config, pro_rata_sales

HELD = {"AAAA": 10e6, "BBBB": 5e6, "CCCC": 1e6}
PX = {"AAAA": 1000.0, "BBBB": 500.0, "CCCC": 2000.0}


def test_each_name_sells_the_same_fraction_in_whole_lots():
    out = {x["symbol"]: x for x in pro_rata_sales(HELD, PX, 4e6)}
    # a quarter of each: 2,500 / 2,500 / 125 shares → lots of 100; the Rp 50,000 rounding
    # leaves buys one more BBBB lot (an AAAA lot would cost Rp 100,000)
    assert out["AAAA"]["shares"] == 2500 and out["BBBB"]["shares"] == 2600
    assert out["CCCC"]["shares"] == 100
    assert sum(x["idr"] for x in out.values()) == 4e6
    assert all(x["shares"] % 100 == 0 for x in out.values())


def test_leftover_goes_to_the_largest_holding_first_and_never_past_the_need():
    out = {x["symbol"]: x for x in pro_rata_sales(HELD, PX, 4.1e6)}
    total = sum(x["idr"] for x in out.values())
    assert 4.1e6 - 50_000 <= total <= 4.1e6  # within one BBBB lot of the need
    assert out["AAAA"]["shares"] >= 2500


def test_excluded_names_and_names_without_a_price_or_a_lot_sell_nothing():
    held = {**HELD, "TINY": 30_000.0, "NOPX": 2e6}
    px = {**PX, "TINY": 1000.0, "NOPX": None}
    out = [x["symbol"] for x in pro_rata_sales(held, px, 3e6, exclude={"AAAA"})]
    assert out == ["BBBB", "CCCC"]


def test_never_sells_more_than_is_held_and_nothing_without_a_need():
    out = pro_rata_sales(HELD, PX, 1e9)
    assert sum(x["idr"] for x in out) == pytest.approx(16e6)
    assert pro_rata_sales(HELD, PX, 0.0) == [] and pro_rata_sales({}, PX, 1e6) == []
    assert config()["lot"] == 100


# ---------------- redundant first, kept last (P100, PLAN S83) ----------------

from assist.candidates.rebalance import ordered_sales  # noqa: E402

H = {"RED1": 2e6, "RED2": 3e6, "OTH1": 10e6, "OTH2": 10e6, "KEEP": 10e6}
PR = dict.fromkeys(H, 1000.0)


def test_redundant_names_are_sold_in_full_first_in_the_order_given():
    out = ordered_sales(H, PR, 4e6, redundant=["RED1", "RED2"], protected={"KEEP"})
    assert [(x["symbol"], x["tier"], x["full"], x["idr"]) for x in out] == [
        ("RED1", "redundant", True, 2e6), ("RED2", "redundant", False, 2e6)]


def test_then_pro_rata_over_the_rest_and_the_kept_names_last():
    out = ordered_sales(H, PR, 9e6, redundant=["RED1", "RED2"], protected={"KEEP"})
    by = {x["symbol"]: x for x in out}
    assert by["RED1"]["full"] and by["RED2"]["full"]
    assert by["OTH1"]["tier"] == by["OTH2"]["tier"] == "rebalance"
    assert by["OTH1"]["idr"] == by["OTH2"]["idr"] == 2e6 and "KEEP" not in by
    # only when the others are sold out do the kept names pay
    out = ordered_sales(H, PR, 27e6, redundant=["RED1", "RED2"], protected={"KEEP"})
    by = {x["symbol"]: x for x in out}
    assert by["KEEP"]["tier"] == "protected" and by["KEEP"]["idr"] == 2e6
    assert sum(x["idr"] for x in out) == 27e6


def test_a_full_sale_takes_the_odd_lot_and_excluded_names_are_skipped():
    out = ordered_sales({"ODD": 1_419_000.0, "TRIM": 5e6}, {"ODD": 1000.0, "TRIM": 1000.0}, 3e6,
                        exclude={"TRIM"}, redundant=["TRIM", "ODD"], quantities={"ODD": 1419})
    assert out == [{"symbol": "ODD", "shares": 1419, "idr": 1_419_000.0, "tier": "redundant",
                    "full": True}]


def test_no_redundant_names_is_plain_pro_rata():
    plain = pro_rata_sales(HELD, PX, 4e6)
    assert [{k: x[k] for k in ("symbol", "shares", "idr")}
            for x in ordered_sales(HELD, PX, 4e6)] == plain
