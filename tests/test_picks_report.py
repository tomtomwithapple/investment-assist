"""S92 picks report (P109): price, dividend and total return of held picks vs JCI and the pool."""

from __future__ import annotations

from datetime import date

import pytest

from assist.eval import picks_report as pr
from assist.sources.base import Row
from assist.sources.idxmethod_series import Bar

D = date.fromisoformat


def bars(*pts: tuple[str, float]) -> list[tuple[date, float]]:
    return [(D(d), float(c)) for d, c in pts]


def div(ex: str, value: float) -> dict:
    return {"ex": ex, "value": value}


JCI = bars(("2024-01-31", 1000), ("2024-02-29", 1050), ("2024-03-28", 1100),
           ("2024-04-30", 1000), ("2024-05-31", 1000), ("2024-06-28", 1000),
           ("2024-07-31", 1000), ("2024-08-30", 1000))


def window(rep: pr.PicksReport, start: str, label: str) -> pr.WindowResult:
    return next(w for w in rep.windows if w.start == D(start) and w.window == label)


# ---------------- calendar ----------------


def test_add_months_keeps_month_ends_and_clamps():
    assert pr.add_months(D("2024-01-31"), 1) == D("2024-02-29")
    assert pr.add_months(D("2024-02-29"), 1) == D("2024-03-31")  # a month end stays one
    assert pr.add_months(D("2024-01-15"), 1) == D("2024-02-15")
    assert pr.add_months(D("2023-11-30"), 3) == D("2024-02-29")
    assert pr.add_months(D("2021-11-12"), 60) == D("2026-11-12")


def test_windows_are_the_six_calendar_windows():
    assert [w for w, _ in pr.WINDOWS] == ["1m", "3m", "6m", "1y", "3y", "5y"]
    assert dict(pr.WINDOWS)["5y"] == 60


# ---------------- one name ----------------


def test_price_dividend_and_total_return_not_reinvested():
    prices = {"AAA": bars(("2024-01-31", 100), ("2024-02-29", 110))}
    divs = {"AAA": [div("2024-02-10", 5)]}
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0)]}, prices, divs, JCI, windows=[("1m", 1)])
    w = window(rep, "2024-01-31", "1m")
    assert w.status == "ok"
    assert w.equal.price == pytest.approx(0.10)
    assert w.equal.dividend == pytest.approx(0.05)
    assert w.equal.total == pytest.approx(0.15)


def test_split_inside_the_window_is_back_adjusted_and_scales_the_dividends():
    # 2:1 split on 02-15: raw 100 → 50; a pre-split dividend of 4 is 2 on the post-split basis
    prices = {"AAA": bars(("2024-01-31", 100), ("2024-02-14", 100), ("2024-02-15", 50),
                          ("2024-02-29", 55))}
    divs = {"AAA": [div("2024-02-10", 4), div("2024-02-20", 1)]}
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0)]}, prices, divs, JCI, windows=[("1m", 1)])
    w = window(rep, "2024-01-31", "1m")
    assert w.equal.price == pytest.approx(0.10)
    assert w.equal.dividend == pytest.approx((2 + 1) / 50)
    assert w.names[0].split_factor == pytest.approx(0.5)


def test_ex_date_on_a_boundary_is_excluded_at_start_and_included_at_end():
    prices = {"AAA": bars(("2024-01-31", 100), ("2024-02-29", 100))}
    divs = {"AAA": [div("2024-01-31", 7), div("2024-02-29", 3)]}
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0)]}, prices, divs, JCI, windows=[("1m", 1)])
    assert window(rep, "2024-01-31", "1m").equal.dividend == pytest.approx(0.03)


def test_a_delisted_name_is_held_at_its_last_bar_and_flagged():
    prices = {"AAA": bars(("2024-01-31", 100), ("2024-02-05", 95), ("2024-02-09", 90)),
              "BBB": bars(("2024-01-31", 100), ("2024-02-29", 100))}
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0), ("BBB", 1.0)]}, prices, {}, JCI,
                    windows=[("1m", 1)])
    w = window(rep, "2024-01-31", "1m")
    a = next(n for n in w.names if n.symbol == "AAA")
    assert a.stopped and a.end_bar == D("2024-02-09")
    assert a.price == pytest.approx(-0.10)
    assert w.equal.price == pytest.approx(-0.05)
    assert "AAA" in w.stopped


def test_a_window_starting_before_the_first_bar_is_na_never_filled():
    prices = {"AAA": bars(("2024-02-05", 100), ("2024-02-29", 110)),
              "BBB": bars(("2024-01-31", 100), ("2024-02-29", 100))}
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0), ("BBB", 1.0)]}, prices, {}, JCI,
                    windows=[("1m", 1)])
    w = window(rep, "2024-01-31", "1m")
    a = next(n for n in w.names if n.symbol == "AAA")
    assert a.price is None and a.total is None and a.note == "no bar on or before start"
    assert w.equal is None and w.weighted is None  # the basket is n/a, not BBB alone
    assert w.missing == ("AAA",)


def test_a_window_ending_after_the_data_is_open():
    prices = {"AAA": bars(("2024-01-31", 100), ("2024-08-30", 120))}
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0)]}, prices, {}, JCI,
                    windows=[("6m", 6), ("1y", 12)])
    assert window(rep, "2024-01-31", "6m").status == "ok"
    open_ = window(rep, "2024-01-31", "1y")
    assert open_.status == "open" and open_.equal is None and open_.jci is None


# ---------------- comparators and weights ----------------


def _three():
    return {"AAA": bars(("2024-01-31", 100), ("2024-02-29", 110)),
            "BBB": bars(("2024-01-31", 100), ("2024-02-29", 100)),
            "CCC": bars(("2024-01-31", 100), ("2024-02-29", 96)),
            "NEW": bars(("2024-02-10", 100), ("2024-02-29", 200))}


def test_jci_and_pool_comparators_and_excess():
    pools = {D("2024-01-31"): ["AAA", "BBB", "CCC", "NEW"]}
    rep = pr.report({D("2024-01-31"): [("AAA", 0.75), ("BBB", 0.25)]}, _three(), {}, JCI,
                    pools=pools, windows=[("1m", 1)])
    w = window(rep, "2024-01-31", "1m")
    assert w.jci == pytest.approx(0.05)
    assert w.equal.total == pytest.approx(0.05)
    assert w.weighted.total == pytest.approx(0.075)
    assert w.pool.total == pytest.approx(0.02)  # NEW had no start bar: out of the pool, counted
    assert w.pool_n == 3 and w.pool_missing == 1
    assert w.excess_jci == {"equal": pytest.approx(0.0), "weighted": pytest.approx(0.025)}
    assert w.excess_pool == {"equal": pytest.approx(0.03), "weighted": pytest.approx(0.055)}


def test_weights_are_normalised_and_none_makes_the_weighted_leg_na():
    rep = pr.report({D("2024-01-31"): [("AAA", 30.0), ("BBB", 10.0)]}, _three(), {}, JCI,
                    windows=[("1m", 1)])
    assert window(rep, "2024-01-31", "1m").weighted.total == pytest.approx(0.075)
    rep = pr.report({D("2024-01-31"): [("AAA", None), ("BBB", 1.0)]}, _three(), {}, JCI,
                    windows=[("1m", 1)])
    w = window(rep, "2024-01-31", "1m")
    assert w.weighted is None and w.excess_jci["weighted"] is None
    assert w.equal.total == pytest.approx(0.05)


def test_no_pool_given_means_no_pool_leg():
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0)]}, _three(), {}, JCI, windows=[("1m", 1)])
    w = window(rep, "2024-01-31", "1m")
    assert w.pool is None and w.excess_pool["equal"] is None


# ---------------- independent windows and the summary ----------------


def test_independent_windows_count_non_overlapping_starts():
    starts = [pr.add_months(D("2024-01-31"), k) for k in range(12)]
    assert pr.independent(starts, 3) == 4  # Jan, Apr, Jul, Oct
    assert pr.independent(starts, 1) == 12
    assert pr.independent(starts, 12) == 1
    assert pr.independent([], 3) == 0
    assert pr.independent([D("2024-01-31"), D("2024-02-15"), D("2024-04-30")], 3) == 2


def test_summary_means_over_complete_starts_with_the_independent_count():
    prices = {"AAA": bars(*[(d.isoformat(), 100 + 10 * i) for i, (d, _) in enumerate(JCI)])}
    ends = [pr.add_months(D("2024-01-31"), k) for k in range(6)]  # calendar month ends
    rep = pr.report({d: [("AAA", 1.0)] for d in ends}, prices, {}, JCI,
                    windows=[("1m", 1), ("3m", 3)])
    s1 = next(s for s in rep.summary if s.window == "1m")
    s3 = next(s for s in rep.summary if s.window == "3m")
    assert s1.n_starts == 6 and s1.n_independent == 6
    assert s3.n_starts == 4 and s3.n_independent == 2  # 3m to 08-31 and 09-30 is still open
    w = [window(rep, d.isoformat(), "3m") for d in ends[:4]]
    assert s3.equal_total == pytest.approx(sum(x.equal.total for x in w) / 4)
    assert s3.excess_jci == pytest.approx(sum(x.excess_jci["equal"] for x in w) / 4)


def test_report_round_trips_to_a_plain_dict():
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0)]}, _three(), {}, JCI, windows=[("1m", 1)])
    d = rep.to_dict()
    assert d["as_of"] == "2024-02-29"  # the pick's last bar, before the JCI's
    assert d["windows"][0]["start"] == "2024-01-31"
    assert d["windows"][0]["equal"]["total"] == pytest.approx(0.10)
    assert d["summary"][0]["window"] == "1m"


def test_as_of_defaults_to_the_last_jci_bar_and_can_be_set():
    prices = {"AAA": bars(("2024-01-31", 100), ("2024-02-29", 110))}
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0)]}, prices, {}, JCI, windows=[("1m", 1)],
                    as_of=D("2024-02-15"))
    assert window(rep, "2024-01-31", "1m").status == "open"


def test_as_of_defaults_to_the_earlier_of_the_jci_and_the_newest_pick_bar():
    # Stock bars ended 2026-11-05 while the JCI ran to 11-11: a window ending in between must
    # stay open, not set a stale close against a fresh index.
    prices = {"AAA": bars(("2024-01-31", 100), ("2024-02-15", 110))}
    rep = pr.report({D("2024-01-31"): [("AAA", 1.0)]}, prices, {}, JCI, windows=[("1m", 1)])
    assert rep.as_of == D("2024-02-15")
    assert window(rep, "2024-01-31", "1m").status == "open"


# ---------------- assembling the stores ----------------


def test_assemble_prepends_factor_series_before_the_history_and_keeps_delisted():
    history = {"AAA": [{"date": "2021-11-01", "close": 110}, {"date": "2021-11-02", "close": 111}]}
    factor = {"AAA": [Bar(D("2021-10-29"), 109.0, 1e12), Bar(D("2021-11-01"), 999.0, 1e12)],
              "DEAD": [Bar(D("2019-01-02"), 50.0, 1e11), Bar(D("2019-06-28"), None, None)]}
    jci_rows = [Row("JKSE", D("2021-11-01"), 6500.0, None, "x")]
    data = pr.assemble(history, factor, {"AAA": [div("2021-12-01", 2)]}, jci_rows)
    assert data.prices["AAA"] == bars(("2021-10-29", 109), ("2021-11-01", 110),
                                      ("2021-11-02", 111))
    assert data.prices["DEAD"] == bars(("2019-01-02", 50))
    assert data.jci == bars(("2021-11-01", 6500))
    assert data.dividends["AAA"] == [div("2021-12-01", 2)]
