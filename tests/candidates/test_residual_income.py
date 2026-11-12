"""Bank residual income (P113, PLAN S96) on a hand-computed table.

Both banks: 1e9 adjusted shares (mktcap / price), r = 12%, N = 3 years (ROE_t = ROE0 + (r −
ROE0) × t / 3, so year 3 earns exactly r and has no residual income).

Bank A (AAAA): equity 1,000bn at T, 900bn a year before → average 950bn; NI TTM 199.5bn →
ROE0 = 21%. Dividends 99.75 a share in the last 12 months → payout 99.75e9 / 199.5e9 = 50%.
B0 = 1,000. Price 1,500.

    year  ROE   B_{t-1}   RI = (ROE − r)·B   PV = RI / 1.12^t   B_t = B + ROE·B·(1 − 0.5)
    1     18%   1,000.00  60.00              53.5714            1,090.00
    2     15%   1,090.00  32.70              26.0682            1,171.75
    3     12%   1,171.75   0.00               0.0000            1,242.055
    V0 = 1,000 + 53.5714 + 26.0682 = 1,079.6397; justified P/B 1.0796; price ÷ fair 1.3894.

Bank B (BBBB): equity 500bn at T, 460bn a year before → average 480bn; NI TTM 28.8bn → ROE0 =
6%; dividends 11.52 a share → payout 40%. B0 = 500. Price 400.

    year  ROE   B_{t-1}   RI       PV         B_t = B + ROE·B·0.6
    1      8%   500.00   −20.00   −17.8571    524.00
    2     10%   524.00   −10.48    −8.3546    555.44
    3     12%   555.44     0.00     0.0000    595.43168
    V0 = 500 − 17.8571 − 8.3546 = 473.7883; justified P/B 0.9476; price ÷ fair 0.8443.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from assist.candidates import frameworks as fw
from assist.candidates.frameworks import residual_income as ri
from assist.sources.idxmethod_series import Bar, Fundamentals

LAG = timedelta(days=120)
T, T4 = date(2025, 6, 30), date(2024, 6, 30)
SEEN = T + LAG
R_PT = 12.0


def q(period, equity, ni):
    return Fundamentals(period, period + LAG, 1.0, equity, 0.0, ni, 1.0, 1.0, 1.0, 1.0, 0.0)


def quarters(eq_t, eq_t4, ni_t, ni_t4=None):
    return [q(T4, eq_t4, ni_t4 if ni_t4 is not None else ni_t), q(date(2024, 9, 30), eq_t4, ni_t),
            q(date(2024, 12, 31), eq_t4, ni_t), q(date(2025, 3, 31), eq_t4, ni_t),
            q(T, eq_t, ni_t)]


def bars(price):
    return [Bar(SEEN - timedelta(days=400), price, price * 1e9), Bar(SEEN, price, price * 1e9)]


def divs(dps):
    return [{"ex": (SEEN - timedelta(days=100)).isoformat(), "value": dps}]


A = dict(quarters=quarters(1000e9, 900e9, 199.5e9), bars=bars(1500.0), divs=divs(99.75))
B = dict(quarters=quarters(500e9, 460e9, 28.8e9), bars=bars(400.0), divs=divs(11.52))


def value(bank, d=SEEN, r=R_PT, years=3):
    return ri.bank_ri("XXXX", bank["quarters"], bank["bars"], bank["divs"], d, r, years=years)


def test_bank_a_hand_table():
    res = value(A)
    c = res.components
    assert c["b0"] == pytest.approx(1000.0)
    assert c["roe0"] == pytest.approx(0.21)
    assert c["payout"] == pytest.approx(0.5)
    assert [c[f"roe_y{t}"] for t in (1, 2, 3)] == pytest.approx([0.18, 0.15, 0.12])
    assert [c[f"ri_y{t}"] for t in (1, 2, 3)] == pytest.approx([60.0, 32.7, 0.0], abs=1e-9)
    assert [c[f"b_y{t}"] for t in (1, 2, 3)] == pytest.approx([1090.0, 1171.75, 1242.055])
    assert c["pv_ri_y1"] == pytest.approx(53.5714, abs=1e-4)
    assert c["pv_ri_y2"] == pytest.approx(26.0682, abs=1e-4)
    assert c["fair_value"] == pytest.approx(1079.6397, abs=1e-4)
    assert c["justified_pb"] == pytest.approx(1.0796, abs=1e-4)
    assert res.score == pytest.approx(1.3894, abs=1e-4)
    assert res.signal == "rich" and res.as_of == SEEN and res.flags == ()
    assert (res.framework, res.role, res.gate) == ("bank_ri", "context", "untested")


def test_bank_b_hand_table_below_book():
    res = value(B)
    c = res.components
    assert (c["b0"], c["roe0"], c["payout"]) == pytest.approx((500.0, 0.06, 0.4))
    assert [c[f"ri_y{t}"] for t in (1, 2, 3)] == pytest.approx([-20.0, -10.48, 0.0], abs=1e-9)
    assert c["b_y3"] == pytest.approx(595.43168)
    assert c["fair_value"] == pytest.approx(473.7883, abs=1e-4)
    assert c["justified_pb"] == pytest.approx(0.9476, abs=1e-4)
    assert res.score == pytest.approx(0.8443, abs=1e-4) and res.signal == "cheap"


def test_default_fade_is_ten_years():
    res = ri.bank_ri("XXXX", A["quarters"], A["bars"], A["divs"], SEEN, R_PT)
    assert res.components["years"] == 10 and res.components["roe_y10"] == pytest.approx(0.12)
    assert "roe_y11" not in res.components
    assert res.components["fair_value"] > value(A).components["fair_value"]


def test_negative_earnings_valued_below_book_and_flagged():
    bank = dict(A, quarters=quarters(1000e9, 900e9, -47.5e9))  # ROE0 = -5%
    res = value(bank)
    c = res.components
    assert c["roe0"] == pytest.approx(-0.05) and c["payout"] == 0.0
    assert c["fair_value"] < c["b0"] and res.score is not None
    assert any("negative earnings" in f for f in res.flags)


@pytest.mark.parametrize("equity, why", [(None, "no book equity"), (-5e9, "<= 0")])
def test_missing_or_negative_equity_is_na_never_imputed(equity, why):
    res = value(dict(A, quarters=quarters(equity, 900e9, 199.5e9)))
    assert res.score is None and res.signal == fw.NA
    assert any(why in f for f in res.flags)


def test_no_hurdle_or_no_bar_is_na():
    assert value(A, r=None).score is None
    res = ri.bank_ri("XXXX", A["quarters"], [], A["divs"], SEEN, R_PT, years=3)
    assert res.score is None and "no bar" in res.flags[0]


def test_no_prior_equity_uses_ending_equity_flagged():
    qs = [x for x in A["quarters"] if x.period != T4]
    res = ri.bank_ri("XXXX", qs, A["bars"], A["divs"], SEEN, R_PT, years=3)
    assert res.components["roe0"] == pytest.approx(0.1995)
    assert any("ending equity" in f for f in res.flags)


def test_point_in_time_reads_only_the_quarter_knowable():
    qs = A["quarters"][:-1] + [q(T, 2000e9, 199.5e9)]  # T's equity doubles
    before = ri.bank_ri("XXXX", qs, A["bars"], A["divs"], SEEN - timedelta(days=1), R_PT,
                        years=3)
    on = ri.bank_ri("XXXX", qs, A["bars"], A["divs"], SEEN, R_PT, years=3)
    assert before.as_of == date(2025, 3, 31) + LAG
    assert before.components["equity"] == 900e9 and on.components["equity"] == 2000e9
    assert ri.bank_ri("XXXX", qs, A["bars"], A["divs"], date(2024, 1, 1), R_PT).score is None


def test_payout_above_one_is_capped_and_flagged():
    res = value(dict(A, divs=divs(300.0)))
    assert res.components["payout"] == 1.0
    assert any("capped" in f for f in res.flags)


def test_registered_framework_reads_inputs_and_skips_non_banks():
    inp = ri.BankRIInputs(SEEN, {"AAAA": A["quarters"], "CCCC": A["quarters"]}, {},
                          frozenset({"AAAA"}), bars={"AAAA": A["bars"]},
                          dividends={"AAAA": A["divs"]}, required_pt=R_PT, years=3)
    by = {r.framework: r for r in fw.evaluate("AAAA", inp)}
    assert by["bank_ri"].score == pytest.approx(1.3894, abs=1e-4)
    assert by["piotroski_f"].ticker == "AAAA"  # the F-score reads the same object
    other = {r.framework: r for r in fw.evaluate("CCCC", inp)}["bank_ri"]
    assert other.score is None and "not a bank" in other.flags[0]
    none = {r.framework: r for r in fw.evaluate("AAAA", None)}["bank_ri"]
    assert none.score is None


def test_context_goes_on_held_bank_inputs_only():
    inp = ri.BankRIInputs(SEEN, {"AAAA": A["quarters"]}, {}, frozenset({"AAAA"}),
                          bars={"AAAA": A["bars"]}, dividends={"AAAA": A["divs"]},
                          required_pt=R_PT, years=3)
    judged = {"AAAA": {"bank": True}, "CCCC": {"bank": False}}
    ri.attach_context(judged, inp)
    assert judged["AAAA"]["context"]["bank_ri"]["score"] == pytest.approx(1.3894, abs=1e-4)
    assert judged["AAAA"]["context"]["bank_ri"]["as_of"] == SEEN.isoformat()
    assert "context" not in judged["CCCC"]


def test_replay_panel_ranks_cheapest_first_with_forward_return():
    q0, q1 = SEEN, SEEN + timedelta(days=91)
    later = [Bar(q1, 1650.0, 1650e9)]
    bars_ = {"AAAA": A["bars"] + later, "BBBB": [Bar(d.date, 1200.0, 1200e9) for d in
                                                   B["bars"]]}
    # BBBB at 1,200 a share against fair 473.79: rich; AAAA at 1,500 against 1,079.64
    panel = ri.replay_panel(bars_, {"AAAA": A["quarters"], "BBBB": B["quarters"]},
                            {"AAAA": A["divs"], "BBBB": B["divs"]}, ["AAAA", "BBBB"], R_PT,
                            [q0, q1], cfg=ri.CONFIG | {"years": 3})
    (d0, recs0), (d1, recs1) = panel
    by = {r["symbol"]: r for r in recs0}
    assert by["AAAA"]["price_to_fair"] == pytest.approx(1.3894, abs=1e-4)
    assert by["AAAA"]["fwd"] == pytest.approx(0.1)  # 1,500 → 1,650, no dividend ex in between
    assert by["BBBB"]["fwd"] is None  # no later bar
    assert by["AAAA"]["cheap"] > by["BBBB"]["cheap"]
    assert [r["symbol"] for r in recs1] == ["AAAA"]  # BBBB's last bar is too old by q1
