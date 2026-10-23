"""IDX execution cost model and per-stock entry levels (P21, PLAN S10b).

Both are ported from idx-method's deleted `paper/costs.py` and `entry_levels.py` (git 9a0ea38^):
fees + spread + impact, and entry levels from each name's own drawdown history. Bars here are
synthetic and built in the test, so nothing touches the real stores."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

import pytest

from assist.candidates import costs, entry
from assist.candidates.costs import Cost, cost_for, round_trip_bps, tick_size
from assist.candidates.entry import (
    EntryLevels,
    adjusted_closes,
    classify,
    corrections,
    entry_plan,
    measure,
    percentile,
)
from assist.sources.idxmethod_stocks import IdxMethodStocks

# ---------------- costs: tick grid, fees ----------------


@pytest.mark.parametrize(
    ("price", "tick"),
    [
        (50, 1),
        (199, 1),
        (200, 2),
        (499, 2),
        (500, 5),
        (1995, 5),
        (2000, 10),
        (4990, 10),
        (5000, 25),
        (9000, 25),
    ],
)
def test_tick_grid(price, tick):
    assert tick_size(price) == tick


def test_fees_buy_and_sell_with_tax():
    assert costs.fee_bps("buy") == pytest.approx(15.0)
    assert costs.fee_bps("sell") == pytest.approx(25.0)  # 0.15% fee + 0.10% final sales tax
    assert pytest.approx(0.001) == costs.TAX_SELL


# ---------------- costs: spread ----------------


def test_spread_one_tick_wide_at_reference_turnover():
    # price 4000, tick 10 → one tick is 25bp, half of it is paid per side
    assert costs.spread_bps(4000, costs.REF_VALUE) == pytest.approx(12.5)


def test_spread_widens_per_decade_of_thin_turnover():
    # one decade below REF_VALUE → 1.5 ticks wide
    assert costs.spread_bps(4000, costs.REF_VALUE / 10) == pytest.approx(0.5 * 1.5 * 25)
    # turnover above the reference never narrows below one tick
    assert costs.spread_bps(4000, costs.REF_VALUE * 100) == pytest.approx(12.5)


def test_spread_penny_stock_pays_more_than_large_cap():
    assert costs.spread_bps(105, 1e9) > 5 * costs.spread_bps(9000, 200e9)


def test_spread_unknown_turnover_is_charged_as_thin_not_free():
    assert costs.spread_bps(4000, None) == pytest.approx(costs.spread_bps(4000, costs.FLOOR_VALUE))
    assert costs.spread_bps(4000, None) > costs.spread_bps(4000, costs.REF_VALUE)


# ---------------- costs: impact ----------------


def test_impact_square_root_law():
    # order 1% of ADV, vol 0.3 → daily vol 1e4*0.3/sqrt(252) bps, times sqrt(0.01)
    want = 1e4 * 0.3 / math.sqrt(252) * 0.1
    assert costs.impact_bps(1e8, 1e10, 0.3) == pytest.approx(want)
    # 4x the order → 2x the impact
    assert costs.impact_bps(4e8, 1e10, 0.3) == pytest.approx(2 * want)


def test_impact_falls_back_to_amihud_without_vol():
    # amihud 0.02 |ret| per IDR bn; IDR 0.5bn order → 0.01 → 100bp
    assert costs.impact_bps(5e8, 1e10, None, amihud=0.02) == pytest.approx(100.0)
    assert costs.impact_bps(5e8, 1e10, None) == 0.0


def test_amihud_impact_is_linear_in_order():
    assert costs.amihud_bps(5e6, 0.02) == pytest.approx(1.0)
    assert costs.amihud_bps(5e6, None) is None


# ---------------- costs: per candidate ----------------


def test_lots_round_down_to_100_shares():
    assert costs.lot_shares(10_000_000, 1000) == 10_000
    assert costs.lot_shares(10_050_000, 1000) == 10_000
    assert costs.lot_shares(150_000, 2000) == 0  # less than one lot


def test_cost_for_breakdown_matches_hand_computation():
    row = {"price": 105, "med_value_60d": 1e9, "vol_1y": 0.35, "amihud": 0.5}
    c = cost_for(row, 5_000_000)
    assert isinstance(c, Cost)
    shares = costs.lot_shares(5e6, 105)
    notional = shares * 105
    spread = 0.5 * (1 + 0.5 * math.log10(20)) * 1e4 / 105
    impact = 1e4 * 0.35 / math.sqrt(252) * math.sqrt(notional / 1e9)
    assert c.shares == shares and c.notional == pytest.approx(notional)
    assert c.spread_bps == pytest.approx(spread)
    assert c.impact_bps == pytest.approx(impact)
    assert c.buy_bps == pytest.approx(15 + spread + impact)
    assert c.sell_bps == pytest.approx(25 + spread + impact)
    assert c.round_trip_bps == pytest.approx(c.buy_bps + c.sell_bps)
    assert c.participation == pytest.approx(notional / 1e9)
    assert c.amihud_impact_bps == pytest.approx(0.5 * notional / 1e9 * 1e4)
    assert c.flags == ()


def test_cost_for_liquid_name_is_cheap_and_illiquid_is_flagged():
    liquid = cost_for(
        {"price": 9000, "med_value_60d": 500e9, "vol_1y": 0.2, "amihud": 0.0001}, 50e6
    )
    thin = cost_for({"price": 120, "med_value_60d": 50e6, "vol_1y": 0.8, "amihud": 3.0}, 50e6)
    assert liquid.round_trip_bps < 80  # 40bp fees + 2 × ~14bp spread
    assert thin.round_trip_bps > 5 * liquid.round_trip_bps
    assert "over_participation" in thin.flags
    assert thin.participation == pytest.approx(thin.notional / 50e6)


def test_cost_for_missing_liquidity_is_flagged():
    c = cost_for({"price": 1000, "med_value_60d": None, "vol_1y": None, "amihud": None}, 10e6)
    assert "no_turnover" in c.flags
    assert c.spread_bps == pytest.approx(costs.spread_bps(1000, None))


def test_cost_for_no_price_returns_none():
    assert cost_for({"price": None, "med_value_60d": 1e9}, 10e6) is None


def test_round_trip_bps_helper():
    row = {"price": 4000, "med_value_60d": costs.REF_VALUE, "vol_1y": 0.0}
    assert round_trip_bps(row, 4e6) == pytest.approx(15 + 25 + 2 * 12.5)


# ---------------- entry: pieces ----------------


def test_percentile_linear_like_numpy():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(xs, 50) == 3.0
    assert percentile(xs, 25) == 2.0
    assert percentile(xs, 10) == pytest.approx(1.4)
    assert percentile([7.0], 10) == 7.0


def test_corrections_completed_and_open():
    dd = [0, -10, -16, -30, -20, -4, -2, -18, -25, -12]
    done, open_depth = corrections(dd)
    assert done == [-30]
    assert open_depth == -25


def test_adjusted_closes_remove_split_and_keep_last_price():
    raw = [1000, 1010, 1020, 510, 515, 520]  # 2:1 split on day 3
    adj = adjusted_closes(raw)
    assert adj[-1] == 520
    assert adj[2] == pytest.approx(adj[3])  # the split day counts as a zero return
    assert adj[0] == pytest.approx(1000 * 510 / 1020)
    assert adj[1] / adj[0] == pytest.approx(1.01)


# ---------------- entry: synthetic histories ----------------


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _path(n: int, legs: list[tuple[int, float]], start: float = 1000.0) -> list[float]:
    """Piecewise geometric path: each leg (bars, total move) after the first bar."""
    px = [start]
    for bars, move in legs:
        step = (1 + move) ** (1 / bars)
        for _ in range(bars):
            px.append(px[-1] * step)
    px += [px[-1]] * (n - len(px))
    return px[:n]


def _bars(
    prices: list[float], start: date = date(2021, 8, 26), split_at: int | None = None
) -> list[dict]:
    days = _weekdays(start, len(prices))
    out = []
    for i, (d, p) in enumerate(zip(days, prices, strict=True)):
        raw = p / 2 if split_at is not None and i >= split_at else p
        out.append({"date": d.isoformat(), "close": round(raw, 2), "value": 5e10, "volume": 1e6})
    return out


# rise, dip 25%, recover, rise, dip 30%, recover, then fall 40% into today
LEGS = [
    (200, 0.5),
    (60, -0.25),
    (80, 0.40),
    (150, 0.2),
    (60, -0.30),
    (90, 0.45),
    (100, 0.1),
    (120, -0.40),
]
N = sum(b for b, _ in LEGS) + 1  # 861 bars


def test_measure_basic_shape():
    lv = measure(_bars(_path(N, LEGS)), [])
    assert isinstance(lv, EntryLevels)
    assert lv.price == pytest.approx(_path(N, LEGS)[-1], rel=1e-3)
    assert lv.dd_now == pytest.approx(-40.0, abs=0.1)
    assert lv.high_3y == pytest.approx(max(_path(N, LEGS)[-760:]), rel=1e-3)
    assert lv.corrections >= 1
    assert lv.typical_correction is not None and lv.typical_correction < -15
    assert lv.deep_zone <= lv.dd_now or lv.status in ("deep", "avoid")
    assert lv.entry_typical < lv.high_3y and lv.entry_deep < lv.high_3y
    # entry levels sit on the IDX tick grid, rounded down
    assert lv.entry_typical % tick_size(lv.entry_typical) == 0
    assert lv.entry_deep % tick_size(lv.entry_deep) == 0
    assert lv.dd_rank_pct == pytest.approx(0.0)  # today is the deepest drawdown on record
    assert lv.as_of == date.fromisoformat(_bars(_path(N, LEGS))[-1]["date"])


def test_measure_ignores_a_split():
    plain = measure(_bars(_path(N, LEGS)), [])
    split = measure(_bars(_path(N, LEGS), split_at=300), [])
    assert split.dd_now == pytest.approx(plain.dd_now, abs=0.2)
    assert split.corrections == plain.corrections
    assert split.price == pytest.approx(plain.price / 2, rel=1e-3)
    assert split.high_3y == pytest.approx(plain.high_3y / 2, rel=1e-2)


def test_measure_as_of_truncates():
    bars = _bars(_path(N, LEGS))
    cut = date.fromisoformat(bars[800]["date"])
    lv = measure(bars, [], as_of=cut)
    assert lv.as_of == cut
    assert lv.dd_now > -40


def test_measure_too_short_is_none():
    assert measure(_bars(_path(500, LEGS)), []) is None
    assert measure([], []) is None


def test_measure_dividends_raise_total_return_and_yield():
    bars = _bars(_path(N, LEGS))
    last = date.fromisoformat(bars[-1]["date"])
    divs = [
        {"ex": (last - timedelta(days=d)).isoformat(), "value": 30.0, "ccy": "CURRENCY_IDR"}
        for d in range(30, 1500, 182)
    ]
    plain = measure(bars, [])
    with_div = measure(bars, divs)
    assert with_div.yield_ttm == pytest.approx(100 * 60.0 / with_div.price, rel=1e-3)
    assert plain.yield_ttm == 0.0
    assert with_div.fwd12_all > plain.fwd12_all


def test_classify_order():
    base = dict(fwd12_after_dip=10.0, dip_win_rate=70.0, typical_correction=-20.0, deep_zone=-35.0)
    assert classify(dd_now=-10.0, **base) == "wait"
    assert classify(dd_now=-25.0, **base) == "buy_zone"
    assert classify(dd_now=-40.0, **base) == "deep"
    assert classify(dd_now=-40.0, **{**base, "fwd12_after_dip": -5.0}) == "avoid"
    assert classify(dd_now=-40.0, **{**base, "dip_win_rate": 40.0}) == "avoid"
    # no completed correction yet: only the deep zone can trigger
    assert classify(dd_now=-25.0, **{**base, "typical_correction": None}) == "wait"
    # no forward record yet: judged on depth alone
    assert (
        classify(dd_now=-25.0, **{**base, "fwd12_after_dip": None, "dip_win_rate": None})
        == "buy_zone"
    )


# ---------------- entry_plan: files + factors + costs ----------------


def _store(tmp_path, histories: dict[str, list[dict]], divs: dict[str, list[dict]] | None = None):
    for kind in ("history", "dividends"):
        (tmp_path / "cache" / kind).mkdir(parents=True)
    for sym, bars in histories.items():
        (tmp_path / "cache" / "history" / f"{sym}.json").write_text(json.dumps(bars))
    for sym, rows in (divs or {}).items():
        (tmp_path / "cache" / "dividends" / f"{sym}.json").write_text(json.dumps(rows))
    return IdxMethodStocks(tmp_path)


def test_entry_plan_combines_levels_and_costs(tmp_path):
    stocks = _store(tmp_path, {"AAA": _bars(_path(N, LEGS)), "TINY": _bars(_path(300, LEGS))})
    factors = {
        "AAA": {"price": 999, "med_value_60d": 5e10, "vol_1y": 0.3, "amihud": 0.001},
        "TINY": {"price": 1000, "med_value_60d": 1e8, "vol_1y": 0.5, "amihud": 1.0},
    }
    plan, stale = entry_plan(stocks, ["AAA", "TINY", "NONE"], factors=factors, order_idr=20e6)
    assert stale == []
    assert set(plan) == {"AAA", "TINY"}
    a = plan["AAA"]
    assert a["levels"].status in entry.STATUSES
    # cost is priced at the history's last close, not the screener's price
    assert a["cost"].notional == pytest.approx(
        costs.lot_shares(20e6, a["levels"].price) * a["levels"].price
    )
    assert a["cost"].round_trip_bps > 40
    assert plan["TINY"]["levels"] is None  # too short for entry levels, still costed
    assert plan["TINY"]["cost"].round_trip_bps > a["cost"].round_trip_bps


def test_entry_plan_missing_store_is_stale_not_a_crash(tmp_path):
    plan, stale = entry_plan(IdxMethodStocks(tmp_path / "nope"), ["AAA"], factors={})
    assert plan == {}
    assert stale and "idx-method" in stale[0]
