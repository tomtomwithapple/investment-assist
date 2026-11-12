"""Graham's Defensive Investor screen and Graham Number (P114, PLAN S97): one test per criterion
on a hand-built name, a bank, a short-history name, point in time, a split, the Graham Number by
hand, the registry and the replay's picks."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from assist.candidates import frameworks as fw
from assist.candidates.frameworks import graham as gr
from assist.candidates.frameworks.piotroski import shift
from assist.sources.idxmethod_series import Bar

LAG = timedelta(days=120)
T = date(2025, 6, 30)  # the newest quarter
SEEN = T + LAG  # 2025-10-28, the day T becomes knowable
FIRST = date(2007, 3, 31)
SHARES = 10e9


def k_of(p: date) -> int:
    """The trailing year (0 = the four quarters to T) that quarter `p` belongs to."""
    i = 0
    while shift(T, i) > p:
        i += 1
    return i // 4


def statements(*, first=FIRST, ni=None, ca=300e9, cl=100e9, debt=150e9, equity=10e12,
               shares=None):
    """Quarters FIRST..T. NI per quarter: 250bn in years 0–2 (EPS 100 a year), 125bn in years
    10+ (EPS 50), 200bn between: growth 100%. Equity 10T at T (BVPS 1,000), CA/CL 3, debt 150bn
    against net current assets 200bn; 10bn shares."""
    st, p = {}, first
    while p <= T:
        k = k_of(p)
        q = 250e9 if k <= 2 else 125e9 if k >= 10 else 200e9
        q = ni(p, q) if ni else q
        sh = shares(p) if shares else SHARES
        st[p] = {"eps": q / sh, "shares": sh, "shares_bs": sh, "net_income_parent": q}
        p = shift(p, -1)
    st[T] |= {"current_assets": ca, "current_liabilities": cl, "total_debt": debt,
              "common_equity": equity}
    return st


def usd_reporter(st, fx=16_000.0):
    """As idx-method stores a USD reporter: net income, current assets and liabilities in USD;
    EPS, equity, total debt and working capital in IDR."""
    out = {p: dict(row, net_income_parent=row["net_income_parent"] / fx) for p, row in st.items()}
    t = out[T]
    t["working_capital"] = t["current_assets"] - t["current_liabilities"]
    t["current_assets"] /= fx
    t["current_liabilities"] /= fx
    return out


def dividends(years=range(2008, 2025), drop=()):
    return [{"ex": f"{y}-06-15", "value": 50.0} for y in years if y not in drop]


def bars(mktcap=12e12, day=date(2025, 10, 27)):
    return [Bar(day, mktcap / SHARES, mktcap)]


def run(st=None, divs=None, bs=None, d=SEEN, financial=False, first_year=None):
    return gr.defensive("XXXX", st if st is not None else statements(),
                        bs if bs is not None else bars(),
                        divs if divs is not None else dividends(), d, financial=financial,
                        div_first_year=first_year)


def crit(r, name):
    return r.components[name]


def test_a_name_meeting_every_criterion_passes():
    r = run()
    assert r.signal == "pass" and r.score == 1.0
    assert r.components["computable"] == 8 and r.components["met"] == 8
    assert r.as_of == SEEN and r.role == "context" and r.gate == "untested"
    assert crit(r, "pe3") == pytest.approx(12.0) and crit(r, "pb") == pytest.approx(1.2)
    assert crit(r, "eps_growth") == pytest.approx(1.0)


def test_a_usd_reporter_reads_idr_eps_and_working_capital():
    r = run(st=usd_reporter(statements()))
    assert r.signal == "pass"
    assert crit(r, "pe3") == pytest.approx(12.0) and crit(r, "current_ratio") == pytest.approx(3)
    assert crit(r, "net_current_assets") == pytest.approx(200e9)
    bad = run(st=usd_reporter(statements(debt=250e9)))
    assert crit(bad, "c3_debt") == 0.0


def test_a_missing_eps_converts_net_income_at_the_nearest_ratio_flagged():
    st = usd_reporter(statements())
    for p in (T, shift(T, 5)):
        del st[p]["eps"]
    r = run(st=st)
    assert r.signal == "pass" and crit(r, "pe3") == pytest.approx(12.0)
    assert any("2 quarter(s)" in f and "nearest" in f for f in r.flags)
    far = {p: dict(row) for p, row in st.items()}
    for p in far:
        far[p].pop("eps", None)
    assert run(st=far).signal == fw.NA  # no ratio to convert with: unknown, never guessed


def test_size_below_the_floor_fails():
    r = run(bs=bars(4e12), st=statements(equity=4e12))
    assert crit(r, "c1_size") == 0.0 and r.signal == "fail"
    assert r.score == pytest.approx(7 / 8)


def test_current_ratio_below_two_fails():
    r = run(st=statements(ca=150e9))
    assert crit(r, "current_ratio") == pytest.approx(1.5)
    assert crit(r, "c2_current") == 0.0 and r.signal == "fail"


def test_debt_above_net_current_assets_fails():
    r = run(st=statements(debt=250e9))
    assert crit(r, "c2_current") == 1.0 and crit(r, "c3_debt") == 0.0
    assert any("total debt stands in" in f for f in r.flags)


def test_a_loss_year_fails_earnings_stability():
    r = run(st=statements(ni=lambda p, q: -900e9 if p == shift(T, 21) else q))
    assert crit(r, "c4_stability") == 0.0 and crit(r, "positive_years") == 9


def test_a_year_without_dividend_fails_the_record():
    r = run(divs=dividends(drop=(2015,)))
    assert crit(r, "c5_dividends") == 0.0 and crit(r, "dividend_years") == 16


def test_no_dividend_at_all_fails():
    r = run(divs=[])
    assert crit(r, "c5_dividends") == 0.0


def test_dividend_record_is_17_years_and_flagged():
    r = run()
    assert crit(r, "dividend_years_required") == 17
    assert any("17 years" in f for f in r.flags)


def test_dividend_window_clipped_to_the_store_start_is_flagged():
    r = run(divs=dividends(range(2012, 2025)), first_year=2012)
    assert crit(r, "c5_dividends") == 1.0 and crit(r, "dividend_years_required") == 13
    assert any("store starts 2012" in f for f in r.flags)


def test_growth_under_a_third_fails():
    r = run(st=statements(ni=lambda p, q: 200e9 if k_of(p) >= 10 else q))
    assert crit(r, "eps_growth") == pytest.approx(0.25)
    assert crit(r, "c6_growth") == 0.0


def test_pe_above_15_on_three_year_earnings_fails():
    r = run(bs=bars(16e12), st=statements(equity=20e12))
    assert crit(r, "pe3") == pytest.approx(16.0) and crit(r, "c7_pe") == 0.0
    assert crit(r, "c8_pb") == 1.0


def test_pb_passes_on_the_product_and_fails_above_it():
    ok = run(st=statements(equity=12e12 / 1.8))
    assert crit(ok, "pb") == pytest.approx(1.8) and crit(ok, "pe_x_pb") == pytest.approx(21.6)
    assert crit(ok, "c8_pb") == 1.0
    bad = run(st=statements(equity=6e12))
    assert crit(bad, "pe_x_pb") == pytest.approx(24.0) and crit(bad, "c8_pb") == 0.0


def test_graham_number_by_hand():
    r = run(bs=bars(15e12))  # price 1,500
    # EPS TTM 1T / 10bn = 100, BVPS 10T / 10bn = 1,000: sqrt(22.5 × 100 × 1,000) = 1,500
    assert crit(r, "eps_ttm") == pytest.approx(100.0) and crit(r, "bvps") == pytest.approx(1000)
    assert crit(r, "graham_number") == pytest.approx(1500.0)
    assert crit(r, "price_to_graham") == pytest.approx(1.0)
    cheap = run()  # price 1,200
    assert crit(cheap, "price_to_graham") == pytest.approx(0.8)
    assert crit(cheap, "margin_of_safety") == pytest.approx(0.2)


def test_bank_skips_current_ratio_and_debt_flagged():
    r = run(st=statements(ca=50e9, debt=900e9), financial=True)
    assert crit(r, "c2_current") is None and crit(r, "c3_debt") is None
    assert r.components["computable"] == 6 and r.signal == "pass"
    assert any("financial" in f for f in r.flags)


def test_short_history_is_na_never_imputed():
    r = run(st=statements(first=date(2019, 3, 31)))
    assert crit(r, "c4_stability") is None and crit(r, "c6_growth") is None
    assert crit(r, "c5_dividends") is None
    assert r.score is None and r.signal == fw.NA
    assert r.components["computable"] == 5 and r.components["met_partial"] == 5
    assert any("only 5 of 8" in f for f in r.flags)


def test_short_history_still_fails_on_a_known_interruption():
    r = run(st=statements(first=date(2019, 3, 31)), divs=dividends(drop=(2021,)))
    assert crit(r, "c5_dividends") == 0.0
    assert r.signal == "fail" and r.score == pytest.approx(5 / 6)


def test_a_known_failure_below_the_minimum_still_fails():
    r = run(st=statements(first=date(2019, 3, 31), ca=150e9))
    assert r.components["computable"] == 5 and r.signal == "fail"
    assert r.score == pytest.approx(3 / 5)  # current ratio and debt both fail
    assert any("only 5 of 8" in f and "known failure" in f for f in r.flags)


def test_statement_items_include_what_the_screen_reads():
    assert {"eps", "net_income_parent", "shares", "working_capital", "common_equity",
            "total_debt", "current_assets", "current_liabilities"} <= set(gr.STATEMENT_ITEMS)


def test_a_pre_listing_share_jump_is_not_a_split():
    jump = shift(T, 20)
    r = run(st=statements(shares=lambda p: SHARES / 11111 if p < jump else SHARES))
    assert not any("restated" in f for f in r.flags)
    assert crit(r, "c6_growth") is None and any("unknown basis" in f for f in r.flags)
    assert crit(r, "pe3") == pytest.approx(12.0)  # share-free, unaffected


def test_missing_price_leaves_size_pe_pb_na():
    r = run(bs=[])
    for c in ("c1_size", "c7_pe", "c8_pb", "price_to_graham"):
        assert crit(r, c) is None
    assert any("no market cap" in f for f in r.flags)
    stale = run(bs=bars(day=date(2025, 9, 1)))
    assert crit(stale, "c1_size") is None


def test_point_in_time_ignores_later_quarters_bars_and_dividends():
    d = SEEN - timedelta(days=1)  # T not yet knowable
    st = statements(ni=lambda p, q: -5e12 if p == T else q)
    bs = bars() + [Bar(SEEN, 1.0, 1e9)]
    late = dividends() + [{"ex": "2025-11-01", "value": 1.0}]
    r = run(st=st, bs=[Bar(d - timedelta(days=2), 1200.0, 12e12), *bs[1:]], divs=late, d=d)
    assert r.as_of == shift(T, 1) + LAG
    assert crit(r, "positive_years") == 10 and crit(r, "mktcap") == 12e12
    after = run(st=st)
    assert crit(after, "c4_stability") == 0.0


def test_nothing_knowable_is_na():
    r = run(d=FIRST + LAG - timedelta(days=1))
    assert r.signal == fw.NA and r.score is None and r.as_of is None


def test_a_split_is_adjusted_in_eps_growth():
    split = shift(T, 20)
    r = run(st=statements(shares=lambda p: SHARES / 5 if p < split else SHARES))
    assert crit(r, "eps_growth") == pytest.approx(1.0) and crit(r, "c6_growth") == 1.0
    assert any("split" in f for f in r.flags)


def test_registered_and_reads_its_part_of_a_bundle():
    assert "graham" in {f.name for f in fw.registered()}
    inp = gr.GrahamInputs(SEEN, {"XXXX": statements()}, {"XXXX": bars()},
                          {"XXXX": dividends()})
    for given in (inp, {"graham": inp, "piotroski_f": None}):
        (r,) = [x for x in fw.evaluate("XXXX", given) if x.framework == "graham"]
        assert r.signal == "pass"
    (na,) = [x for x in fw.evaluate("XXXX", None) if x.framework == "graham"]
    assert na.signal == fw.NA and na.flags
    (none,) = [x for x in fw.evaluate("YYYY", inp) if x.framework == "graham"]
    assert none.signal == fw.NA and any("no statements" in f for f in none.flags)


def test_no_dividend_source_leaves_the_record_na():
    inp = gr.GrahamInputs(SEEN, {"XXXX": statements()}, {"XXXX": bars()}, None)
    r = gr.Graham().evaluate("XXXX", inp)
    assert r.components["c5_dividends"] is None
    assert any("no dividend source" in f for f in r.flags)


def test_picks_hold_the_passing_names_or_fill_with_the_cheapest():
    st = {s: statements() for s in ("AAAA", "BBBB", "CCCC")}
    caps = {"AAAA": 12e12, "BBBB": 20e12, "CCCC": 16e12}  # only AAAA passes (P/E 12)
    bs = {s: bars(c) for s, c in caps.items()}
    divs = {s: dividends() for s in st}
    inp = gr.GrahamInputs(SEEN, st, bs, divs)
    picks, pool, filled = gr.picks_on(inp, SEEN, min_picks=1)
    assert picks == ["AAAA"] and pool == ["AAAA", "BBBB", "CCCC"] and filled == 0
    picks, _, filled = gr.picks_on(inp, SEEN, min_picks=2)
    assert picks == ["AAAA", "CCCC"] and filled == 1


def test_the_pool_and_the_fill_are_names_over_the_size_floor():
    st = {"AAAA": statements(), "SMOL": statements(equity=4e12)}
    bs = {"AAAA": bars(20e12), "SMOL": bars(1e12)}  # SMOL is the cheapest, but small
    inp = gr.GrahamInputs(SEEN, st, bs, {s: dividends() for s in st})
    picks, pool, filled = gr.picks_on(inp, SEEN, min_picks=2)
    assert pool == ["AAAA"] and picks == ["AAAA"] and filled == 1
