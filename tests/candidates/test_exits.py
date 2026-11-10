"""Entry cap, take-profit and stop-loss of a candidate row (P92, PLAN S74)."""

from __future__ import annotations

import pytest

from assist.candidates import exits as ex
from assist.candidates.exits import exits, fair_price

LEGS = {"yield_pt": 15.0, "g_pt": 4.0}


def test_choices():
    c = ex.config()
    assert c["entry_cap_pct"] == 1.0 and c["take_profit_action"] == "stop adding and trim to half"
    assert c["thesis_stop"] == "sell when it fails its screen"


def test_fair_price_is_where_the_margin_reaches_zero():
    # yield 15% at 3,600 = a dividend of 540; required 14.87% - growth 4% = 10.87% yield needed
    fair = fair_price("dividend_value", 3600.0, LEGS, 14.87)
    assert fair == pytest.approx(540 / 0.1087)
    assert 100 * 540 / fair + 4.0 == pytest.approx(14.87)  # expected return at the fair price


def test_a_sector_tilt_moves_the_fair_price():
    assert fair_price("dividend_value", 3600.0, LEGS, 15.87) < fair_price(
        "dividend_value", 3600.0, LEGS, 14.87)


@pytest.mark.parametrize(("style", "price", "legs", "req"), [
    ("garp", 3600.0, LEGS, 14.87),  # no closed form
    ("dividend_value", None, LEGS, 14.87),
    ("dividend_value", 3600.0, {}, 14.87),
    ("dividend_value", 3600.0, LEGS, None),
    ("dividend_value", 3600.0, {"yield_pt": 15.0, "g_pt": 15.0}, 14.87),  # growth >= required
    ("dividend_value", 3600.0, {"yield_pt": 0.0, "g_pt": 4.0}, 14.87),
])
def test_no_fair_price(style, price, legs, req):
    assert fair_price(style, price, legs, req) is None
    assert exits(style, price, legs, req)["take_profit_basis"] == "none"


def test_exits_block_on_the_tick_grid():
    e = exits("dividend_value", 3600.0, LEGS, 14.87, {"entry_deep": 3000.0})
    assert e["entry_cap"] == 3630.0  # 3,636 floored to the 10-rupiah tick
    assert e["take_profit"] == 4960.0 and e["take_profit_basis"] == "fair_price"  # 4,967.8
    assert e["review_at"] == 3000.0 and "do not sell" in e["review_note"]
    assert e["thesis_stop"] == ex.THESIS_STOP and e["take_profit_action"] == ex.TP_ACTION


def test_review_price_only_below_today_and_take_profit_only_above():
    assert exits("dividend_value", 3600.0, LEGS, 14.87, {"entry_deep": 3700.0})["review_at"] is None
    assert exits("dividend_value", 3600.0, LEGS, 14.87, None)["review_at"] is None
    # a row whose margin is already gone has a fair price below today's: no take-profit
    e = exits("dividend_value", 3600.0, {"yield_pt": 9.0, "g_pt": 4.0}, 14.87)
    assert e["take_profit"] is None and e["take_profit_basis"] == "none"


def test_no_price_no_levels():
    e = exits("dividend_value", None, LEGS, 14.87, {"entry_deep": 3000.0})
    assert e["entry_cap"] is None and e["take_profit"] is None and e["review_at"] is None
