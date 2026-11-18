"""Phase S flow factors (S107, P128-flow-factors): four legs per name and date, pure and point in
time (rule 4), each a `FrameworkResult`; hand tables only."""

from __future__ import annotations

from array import array
from datetime import date, timedelta

import pytest

from assist.candidates import flow
from assist.candidates.frameworks.base import FrameworkResult
from assist.sources.idxmethod_insider import InsiderTrade
from assist.sources.idxscape import FlowSeries
from assist.sources.kseistat import StockHolders

START = date(2026, 1, 5)


def weekdays(n: int, start: date = START) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def series(code="AAAA", n=80, close=None, previous=None, value=None, net=None, nonreg=None,
           high=None, low=None, listed=1_000_000, start=START) -> FlowSeries:
    days = weekdays(n, start)
    close = close or [1000.0] * n
    previous = previous or [close[0], *close[:-1]]
    value = value or [10e9] * n
    return FlowSeries(
        code, array("i", [d.toordinal() for d in days]), array("d", previous), array("d", close),
        array("d", high or [c * 1.01 for c in close]), array("d", low or [c * 0.99 for c in close]),
        array("d", value), array("d", nonreg or [0.0] * n), array("d", net or [0.0] * n),
        array("d", [listed] * n), array("i", [0] * n))


def after(s: FlowSeries, k: int = 1) -> date:
    """The day after the series' last day: every day of it is known then."""
    return s.date(len(s.days) - 1) + timedelta(days=k)


# ---------------- point in time ----------------


def test_window_ends_before_the_decision_day():
    s = series(n=80)
    d = s.date(70)
    assert flow.window_end(s, d) == 69  # the decision day's own flow is known the next day
    assert flow.window_end(s, START) is None


# ---------------- accumulation ----------------


def test_accumulation_while_flat():
    n = 80
    net = [1e9 if i % 4 else -1e9 for i in range(n)]  # 3 buy days in 4
    r = flow.accumulation(series(n=n, net=net), after(series(n=n)))
    assert isinstance(r, FrameworkResult) and r.framework == "flow_accumulation"
    c = r.components
    assert c["nf_60d"] == pytest.approx(30e9 / 600e9)
    assert c["nf_20d"] == pytest.approx(10e9 / 200e9)
    assert c["buy_days_60d"] == pytest.approx(0.75)
    assert r.score == pytest.approx(c["nf_60d"]) and r.signal == "buying"
    assert r.role == "context" and r.gate == "untested"


def test_accumulation_not_counted_once_the_price_left_the_band():
    n = 80
    close = [1000.0] * 50 + [1150.0] * 30  # +15% inside the last 60 days: marked up
    r = flow.accumulation(series(n=n, close=close, net=[1e9] * n), after(series(n=n)))
    assert r.score is None and r.signal == "n/a"
    assert any("band" in f for f in r.flags)
    assert r.components["nf_60d"] == pytest.approx(1 / 10)  # still shown


def test_a_split_does_not_leave_the_band():
    n = 80
    close = [5000.0] * 40 + [1000.0] * 40
    previous = [5000.0] * 40 + [1000.0] * 40  # IDX adjusts previous on the ex-date
    r = flow.accumulation(series(n=n, close=close, previous=previous, net=[1e9] * n),
                          after(series(n=n)))
    assert r.score is not None and r.components["move_60d"] == pytest.approx(0.0)


def test_a_crossing_heavy_window_is_flagged_and_left_out():
    n = 80
    nonreg = [0.0] * 30 + [8e9] * 50  # 8 of every 10bn traded on the negotiated market
    r = flow.accumulation(series(n=n, nonreg=nonreg, net=[1e9] * n), after(series(n=n)))
    assert r.score is None and any("non-regular" in f for f in r.flags)
    assert r.components["non_regular_60d"] == pytest.approx(0.8 * 50 / 60)


def test_a_listing_inside_the_window_has_no_score():
    s = series(n=40, net=[1e9] * 40)
    r = flow.accumulation(s, after(s))
    assert r.score is None and any("history" in f for f in r.flags)


def test_split_needs_no_adjustment_of_flow():
    # value, not shares: the same IDR flow before and after a 1:5 split
    n = 80
    close = [5000.0] * 40 + [1000.0] * 40
    previous = [5000.0] * 40 + [1000.0] * 40
    a = flow.accumulation(series(n=n, close=close, previous=previous, net=[2e9] * n),
                          after(series(n=n)))
    assert a.components["nf_60d"] == pytest.approx(0.2)


# ---------------- supply and demand ----------------


def test_supply_demand_up_value_share():
    n = 60
    close, prev = [], []
    for i in range(n):
        up = i % 3 != 0  # 2 up days, 1 down day
        prev.append(1000.0)
        close.append(1010.0 if up else 990.0)
    value = [10e9 if i % 3 else 40e9 for i in range(n)]  # a down day trades 4x an up day
    s = series(n=n, close=close, previous=prev, value=value)
    r = flow.supply_demand(s, after(s))
    assert r.framework == "flow_supply_demand"
    # the last 50 days (10..59): 34 up days at 10bn, 16 down days at 40bn
    assert r.score == pytest.approx(340 / 980) and r.signal == "selling"


def test_supply_demand_flat_days_do_not_count():
    s = series(n=60)  # every close equals its previous
    r = flow.supply_demand(s, after(s))
    assert r.score is None and r.flags


# ---------------- ownership ----------------

M = [date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)]


def holders(month, inst, ind, loaded=None, funds=0):
    return StockHolders(month, "AAAA", 1000, inst + ind + funds + 100, inst, 0, funds, ind,
                        loaded)


def test_ownership_shift_of_institutions_in_the_register():
    rows = [holders(M[0], 200, 800), holders(M[1], 250, 750), holders(M[2], 300, 700),
            holders(M[3], 300, 600, funds=100)]
    r = flow.ownership(rows, date(2026, 10, 15))
    assert r.framework == "flow_ownership"
    # (foreign institutions + local funds) / all KSEI holdings (1,100 shares each month)
    assert r.components["inst_share"] == pytest.approx(100 * 400 / 1100)
    assert r.components["inst_shift_1m"] == pytest.approx(100 * 100 / 1100)
    assert r.components["inst_shift_3m"] == pytest.approx(100 * 200 / 1100)
    assert r.score == pytest.approx(100 * 200 / 1100) and r.signal == "buying"
    assert r.as_of == date(2026, 10, 10)  # month end + 10 days
    assert not r.flags


def test_ownership_reclassified_holder_moves_no_score_but_is_flagged():
    # BYAN 2026-10: 10.75bn shares left "local individual" for a local company; nobody bought
    base = [StockHolders(m, "BYAN", 33, 32_338, 6_970, 7_536, 0, 14_496, None) for m in M[:3]]
    moved = StockHolders(M[3], "BYAN", 33, 32_338, 6_970, 7_536, 0, 3_748, None)
    r = flow.ownership([*base, moved], date(2026, 10, 15))
    assert r.components["inst_shift_1m"] == pytest.approx(0.0)
    assert r.components["local_ind_shift_1m"] == pytest.approx(100 * (3_748 - 14_496) / 32_338)
    assert any("reclassified" in f for f in r.flags)


def test_ownership_backfilled_month_counts_from_month_end_plus_lag():
    late = date(2026, 10, 12) + timedelta(days=400)
    rows = [holders(m, 200 + 10 * i, 800, loaded=late) for i, m in enumerate(M)]
    assert flow.ownership(rows, date(2026, 10, 9)).components["inst_month"] == M[2].toordinal()
    assert flow.ownership(rows, date(2026, 10, 10)).components["inst_month"] == M[3].toordinal()


def test_ownership_loaded_early_counts_from_load():
    rows = [holders(m, 200, 800, loaded=m + timedelta(days=2)) for m in M]
    assert flow.ownership(rows, M[3] + timedelta(days=2)).components["inst_month"] == \
        M[3].toordinal()


def test_ownership_needs_the_months_before():
    rows = [holders(M[0], 200, 800), holders(M[3], 300, 700)]  # July and August missing
    r = flow.ownership(rows, date(2026, 10, 15))
    assert r.score is None and r.components["inst_shift_1m"] is None
    assert any("month" in f for f in r.flags)


def test_ownership_nothing_known_yet():
    r = flow.ownership([holders(M[3], 300, 700)], M[3])
    assert r.score is None and r.as_of is None


# ---------------- insider ----------------


def trade(day, shares, symbol="AAAA"):
    return InsiderTrade(day, symbol, "H", "buy" if shares > 0 else "sell", shares, None, None,
                        ("IDX",), (), None)


def test_insider_net_shares_over_listed_in_bp():
    d = date(2026, 6, 30)
    trades = [trade(date(2026, 4, 10), 5_000), trade(date(2026, 5, 1), -1_000),
              trade(date(2026, 6, 25), 50_000)]  # filed after d: not known yet
    r = flow.insider(trades, 1_000_000, d)
    assert r.framework == "flow_insider"
    assert r.components["trades_90d"] == 2
    assert r.score == pytest.approx(4_000 / 1_000_000 * 1e4) and r.signal == "buying"


def test_insider_window_is_90_days_of_known_filings():
    d = date(2026, 6, 30)
    old = trade(d - timedelta(days=10 + 90), 9_999)  # known on d - 90: just outside
    edge = trade(d - timedelta(days=10 + 89), 1)
    r = flow.insider([old, edge], 1_000_000, d)
    assert r.components["trades_90d"] == 1


def test_insider_block_is_a_corporate_deal_not_market_buying():
    d = date(2026, 11, 18)
    takeover = trade(date(2026, 10, 28), 500_000)  # 50% of the company in one filing
    small = trade(date(2026, 10, 29), 3_000)
    r = flow.insider([takeover, small], 1_000_000, d)
    assert r.components["blocks_90d"] == 1 and r.components["trades_90d"] == 1
    assert r.score == pytest.approx(30.0)
    assert any("block" in f for f in r.flags)
    only = flow.insider([takeover], 1_000_000, d)
    assert only.score is None


def test_insider_no_trade_is_no_score():
    r = flow.insider([], 1_000_000, date(2026, 6, 30))
    assert r.score is None and r.flags == ("no insider market trade in 90 days",)


def test_insider_no_listed_shares():
    r = flow.insider([trade(date(2026, 6, 1), 10)], 0, date(2026, 6, 30))
    assert r.score is None


# ---------------- liquidity, flags, pool ----------------


def test_liquidity_and_pool():
    n = 80
    value = [0.0 if i % 10 == 0 else 6e9 for i in range(n)]  # 6 untraded days in 60
    s = series(n=n, value=value)
    liq = flow.liquidity(s, len(s.days) - 1)
    assert liq["days_traded_60"] == 54 and liq["med_value_60d"] == pytest.approx(6e9)
    assert liq["price"] == 1000.0
    assert flow.eligible(liq) is True
    assert flow.eligible({**liq, "med_value_60d": 4e9}) is False
    assert flow.eligible({**liq, "price": 50.0}) is False


def test_effort_without_result():
    n = 100
    value = [10e9] * 80 + [25e9] * 20  # 2.5x the traded value ...
    s = series(n=n, value=value)  # ... and the price did not move
    assert flow.effort_vs_result(s, n - 1) is True
    moved = series(n=n, value=value, close=[1000.0] * 80 + [1100.0] * 20)
    assert flow.effort_vs_result(moved, n - 1) is False


def test_legs_for_one_name_and_rank():
    n = 80
    names = {}
    for k in range(12):
        net = [1e9 if i % 12 < k else -0.5e9 for i in range(n)]  # k buy days in 12
        names[f"N{k:03d}"] = series(code=f"N{k:03d}", n=n, net=net)
    d = after(names["N000"])
    legs = {c: flow.name_legs(s, [], [], d) for c, s in names.items()}
    assert set(legs["N005"]) == set(flow.LEGS)
    ranked = flow.rank(legs, "accumulation")
    assert [r[2]["symbol"] for r in ranked][:2] == ["N011", "N010"]
    assert flow.rank(legs, "insider") == []  # no insider trades: nobody to rank


def test_config_is_hand_set_and_named():
    cfg = flow.config()
    assert cfg["version"] == flow.VERSION
    assert cfg["accumulation_days"] == [20, 60] and cfg["flat_band"] == 0.10
    assert cfg["ksei_lag_days"] == 10 and cfg["insider_lag_days"] == 10
    assert cfg["insider_block_pct"] == 5.0 and cfg["reclass_pt"] == 10.0
