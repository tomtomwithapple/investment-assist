"""Point-in-time Piotroski F-score (P112, PLAN S95): one test per signal on a hand-built pair of
years, a missing item, a bank, point in time, the history and the Stockbit check."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, timedelta

import pytest

from assist.candidates import frameworks as fw
from assist.candidates.frameworks import piotroski as pf
from assist.sources.idxmethod_series import Fundamentals, IdxMethodSeries

LAG = timedelta(days=120)
T = date(2025, 6, 30)  # the newest quarter; T4 / T8 are one and two years earlier
T4, T8 = date(2024, 6, 30), date(2023, 6, 30)
SEEN = T + LAG  # the day T becomes knowable


def qends(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d = pf.shift(d, -1)
    return out


QUARTERS = qends(T8, T)  # 9 quarter ends


def fund(period, *, ta=1000.0, ni=50.0, cfo=60.0, debt=300.0):
    return Fundamentals(period, period + LAG, cfo, 500.0, 100.0, ni, 70.0, 5.0, 6.0, ta, debt)


def base_quarters(**at_t):
    """TA 1000 then 1100 at T; NI TTM 50 → 80, CFO TTM 100 at T, debt 300 → 200."""
    qs = [fund(p) for p in QUARTERS]
    qs[-1] = fund(T, **({"ta": 1100.0, "ni": 80.0, "cfo": 100.0, "debt": 200.0} | at_t))
    return qs


def base_statements(cur_rev=120.0, cur_gp=40.0, ca=200.0, shares=1000.0, drop=()):
    """Prior year: revenue 100 and GP 30 each quarter; the year to T: `cur_rev`, `cur_gp`.
    Current ratio 150/100 at T4, `ca`/100 at T; shares 1000 at T4, `shares` at T."""
    st = {}
    for p in QUARTERS[1:]:
        cur = p > T4
        st[p] = {"revenue": cur_rev if cur else 100.0, "gross_profit": cur_gp if cur else 30.0}
    st[T4] |= {"current_assets": 150.0, "current_liabilities": 100.0, "shares_bs": 1000.0}
    st[T] |= {"current_assets": ca, "current_liabilities": 100.0, "shares_bs": shares}
    for p, item in drop:
        st[p].pop(item, None)
    return st


def score(quarters=None, statements=None, d=SEEN, bank=False):
    return pf.fscore("XXXX", quarters if quarters is not None else base_quarters(),
                     statements if statements is not None else base_statements(), d, bank=bank)


def test_all_nine_pass_on_the_base_case():
    r = score()
    assert r.framework == "piotroski_f" and r.role == "context" and r.gate == "untested"
    assert r.score == 9.0 and r.components["computable"] == 9.0 and r.signal == "strong"
    assert r.as_of == SEEN
    assert r.components["roa"] == pytest.approx(80 / 1000)


def test_s1_roa_positive():
    r = score(base_quarters(ni=-10.0))
    assert r.components["s1_roa"] == 0.0 and r.components["roa"] == pytest.approx(-0.01)


def test_s2_cfo_positive():
    r = score(base_quarters(cfo=-5.0))
    assert r.components["s2_cfo"] == 0.0 and r.components["s1_roa"] == 1.0


def test_s3_roa_rises():
    r = score(base_quarters(ni=40.0))  # 40 / 1000 = 4% vs 50 / 1000 = 5% a year earlier
    assert r.components["s3_droa"] == 0.0 and r.components["s1_roa"] == 1.0
    assert r.components["roa_prior"] == pytest.approx(0.05)


def test_s4_cfo_exceeds_net_income():
    r = score(base_quarters(cfo=70.0))  # CFO 70 < NI 80
    assert r.components["s4_accrual"] == 0.0 and r.components["s2_cfo"] == 1.0


def test_s5_leverage_falls():
    r = score(base_quarters(debt=400.0))  # 400 / 1050 vs 300 / 1000
    assert r.components["s5_dlever"] == 0.0
    assert r.components["leverage"] == pytest.approx(400 / 1050)


def test_s5_no_debt_either_year_passes():
    qs = [q._replace(total_debt=0.0) for q in base_quarters()]
    r = score(qs)
    assert r.components["s5_dlever"] == 1.0
    assert any("no debt" in f for f in r.flags)


def test_s6_current_ratio_rises():
    r = score(statements=base_statements(ca=120.0))  # 1.2 vs 1.5
    assert r.components["s6_dcurrent"] == 0.0 and r.score == 8.0


def test_s7_no_equity_issued():
    r = score(statements=base_statements(shares=1050.0))  # a 5% rights issue
    assert r.components["s7_no_issue"] == 0.0 and r.score == 8.0
    r = score(statements=base_statements(shares=1004.0))  # a 0.4% ESOP: within tolerance
    assert r.components["s7_no_issue"] == 1.0


def test_s7_a_whole_multiple_is_a_possible_split_and_not_counted():
    r = score(statements=base_statements(shares=5000.0))
    assert r.components["s7_no_issue"] is None and r.components["computable"] == 8.0
    assert any("split" in f for f in r.flags)


def test_s8_gross_margin_rises():
    r = score(statements=base_statements(cur_gp=30.0))  # 30/120 = 25% vs 30%
    assert r.components["s8_dmargin"] == 0.0 and r.components["s9_dturnover"] == 1.0


def test_s9_asset_turnover_rises():
    r = score(statements=base_statements(cur_rev=90.0, cur_gp=31.0))  # 360 / 1000 vs 400 / 1000
    assert r.components["s9_dturnover"] == 0.0 and r.components["s8_dmargin"] == 1.0


def test_a_missing_item_is_flagged_and_not_counted():
    qs = base_quarters()
    qs[-1] = qs[-1]._replace(total_debt=None)
    r = score(qs)
    assert r.components["s5_dlever"] is None
    assert r.score == 8.0 and r.components["computable"] == 8.0 and r.signal == "strong"
    assert any(f.startswith("s5") for f in r.flags)


def test_a_missing_quarter_breaks_the_ttm_flow():
    r = score(statements=base_statements(drop=[(date(2025, 3, 31), "revenue")]))
    assert r.components["s8_dmargin"] is None and r.components["s9_dturnover"] is None
    assert r.components["computable"] == 7.0


def test_below_the_minimum_the_score_is_none():
    r = score(statements={})  # only s1–s5 computable
    assert r.score is None and r.signal == fw.NA
    assert r.components["computable"] == 5.0 and r.components["f_partial"] == 5.0
    assert any("5 of 9" in f for f in r.flags)


def test_a_bank_drops_current_ratio_and_gross_margin():
    r = score(bank=True)
    assert r.components["s6_dcurrent"] is None and r.components["s8_dmargin"] is None
    assert r.components["computable"] == 7.0 and r.score == 7.0
    assert any(f.startswith("bank") for f in r.flags)
    assert pf.MIN_COMPUTABLE <= 7  # a bank with full data is scored, for phase P rule 5


def test_point_in_time_a_quarter_not_yet_available_is_not_used():
    qs = base_quarters()
    early = score(qs, d=SEEN - timedelta(days=1))
    prev = date(2025, 3, 31)
    assert early.as_of == prev + LAG
    assert early.components["roa"] == pytest.approx(50 / 1000)  # T−1's NI over T−5's TA
    # T8 − 1 quarter is not in the store: ΔROA and Δturnover cannot be computed
    assert early.components["s3_droa"] is None
    later = score(qs, d=SEEN)
    assert later.components["roa"] == pytest.approx(80 / 1000)


def test_nothing_available_yet_is_missing():
    r = score(d=T8 + LAG - timedelta(days=1))
    assert r.score is None and r.signal == fw.NA and r.as_of is None


def test_history_gives_one_result_per_report():
    inp = pf.PiotroskiInputs(SEEN, {"XXXX": base_quarters()}, {"XXXX": base_statements()},
                             frozenset())
    h = pf.history("XXXX", inp)
    assert [r.as_of for r in h] == [q + LAG for q in QUARTERS]
    assert h[-1].score == 9.0 and h[0].score is None
    at = pf.history("XXXX", inp, dates=[date(2025, 9, 30), date(2025, 12, 31)])
    assert [r.as_of for r in at] == [date(2025, 3, 31) + LAG, SEEN]


def test_registered_and_evaluated_through_the_registry():
    assert "piotroski_f" in {f.name for f in fw.registered()}
    inp = pf.PiotroskiInputs(SEEN, {"XXXX": base_quarters()}, {"XXXX": base_statements()},
                             frozenset())
    (r,) = [x for x in fw.evaluate("XXXX", inp) if x.framework == "piotroski_f"]
    assert r.score == 9.0
    (na,) = [x for x in fw.evaluate("XXXX", None) if x.framework == "piotroski_f"]
    assert na.signal == fw.NA and na.flags
    (none,) = [x for x in fw.evaluate("YYYY", inp) if x.framework == "piotroski_f"]
    assert none.score is None and any("no quarterly" in f for f in none.flags)


def test_compare_with_stockbit():
    ours = {"A": 5.0, "B": 3.0, "C": None, "D": 7.0}
    theirs = {"A": 5.0, "B": 6.0, "C": 4.0, "D": 6.0, "E": 2.0}
    c = pf.compare(ours, theirs, top=1)
    assert c["n"] == 3 and c["exact"] == pytest.approx(1 / 3)
    assert c["within_1"] == pytest.approx(2 / 3)
    assert c["largest"] == [("B", 3.0, 6.0)]


def test_statements_are_read_from_the_fundamentals_table(tmp_path):
    db = tmp_path / "store" / "data" / "stockbiter.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("create table fundamentals (symbol, stmt, item, period, value, currency)")
    con.execute("create table factor_series (freq, symbol, item, date, value)")
    con.executemany("insert into fundamentals values (?, ?, ?, ?, ?, 'IDR')", [
        ("BBRI", "is", "revenue", "2025Q2", 52.0), ("BBRI", "bs", "assets", "2025Q2", 1.0),
        ("BBRI", "bs", "shares_bs", "2025Q4", 151.0), ("BBRI", "is", "revenue", "2025", 9.0)])
    con.commit()
    con.close()
    st = IdxMethodSeries(tmp_path).statements()
    assert st == {"BBRI": {date(2025, 6, 30): {"revenue": 52.0},
                           date(2025, 12, 31): {"shares_bs": 151.0}}}


def test_result_is_a_valid_framework_result():
    r = score()
    assert fw.FrameworkResult.from_dict(r.to_dict()) == replace(r)
