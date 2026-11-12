"""PLAN S87: the flip-rate replay. A name whose only news is a regime toggle (+1pt risk-off on
alternate weeks) flips its raw take-profit verdict every week and its acted verdict not at all;
a new report or dividend record re-judges it. In memory."""

from __future__ import annotations

from datetime import date, timedelta

from assist.candidates import hysteresis_replay as hr
from assist.sources.idxmethod_series import Bar, Fundamentals

D = date.fromisoformat


def fund(period: str, ni=5000.0, equity=25000.0, cfo=6000.0) -> Fundamentals:
    p = D(period)
    return Fundamentals(p, p + timedelta(days=120), cfo, equity, 0.0, ni, ni, None, None, None,
                        None)


def setup(price=3200.0):
    days = [D("2025-12-01") + timedelta(days=i) for i in range(200)]
    bars = {"BBNI": [Bar(d, price, price * 10) for d in days]}
    quarters = {"BBNI": [fund("2025-06-30")]}
    divs = {"BBNI": [{"ex": f"{y}-04-10", "value": 200.0} for y in range(2020, 2026)]}
    return bars, quarters, divs


def test_a_regime_toggle_flips_the_raw_verdict_and_not_the_acted_one():
    bars, quarters, divs = setup()
    dates = hr.fridays(D("2026-01-02"), D("2026-03-27"))
    # fair at 13.74 ≈ 3,484 (hold at 3,200); at 15.74 ≈ 2,604 (take-profit): toggle weekly
    required = {d: 13.74 + (2.0 if i % 2 else 0.0) for i, d in enumerate(dates)}
    out = hr.replay(bars, quarters, divs, banks={"BBNI"}, dates=dates, required=required,
                    min_mktcap=0.0)
    q = out["quarters"]["2026-03-31"]
    assert q["names"] == 1
    assert q["raw_flips"] == len(dates) - 1 and q["acted_flips"] <= 1
    s = out["summary"]
    assert s["raw_per_name_quarter"] > 1 and s["acted_per_name_quarter"] <= 1
    assert s["acted_over_one"] == 0


def test_flips_count_into_the_quarter_of_the_later_date_and_only_held_style_names():
    rows = {"AAAA": [(D("2026-03-27"), "hold", "hold"), (D("2026-04-03"), "sell", "hold")],
            "ZZZZ": [(D("2026-04-03"), "sell", "sell"), (D("2026-04-10"), "hold", "sell")]}
    held = {("AAAA", "2026-06-30"), ("AAAA", "2026-03-31")}
    out = hr.count(rows, held)
    assert out["quarters"]["2026-06-30"] == {"names": 1, "raw_flips": 1, "acted_flips": 0}
    assert out["quarters"]["2026-03-31"] == {"names": 1, "raw_flips": 0, "acted_flips": 0}
    assert out["summary"]["name_quarters"] == 2
