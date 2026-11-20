"""PLAN S87 (P105-hysteresis): phase P rule 4 on the holding record. One test per rule branch:
a hard fail acts at once; a first soft fail holds; the second soft fail in a row sells; a
report-less day changes nothing; take-profit fires at fair and re-fires only after the price was
10% below fair; a sold name re-enters only with a margin; a regime toggle alone does not flip the
take-profit (the required return is held between reports). Pure, in memory."""

from __future__ import annotations

import pytest

from assist.candidates import hysteresis as hy

Q2 = {"report_period": "2026-06-30", "last_dividend_ex": "2026-04-10"}
Q3 = {"report_period": "2026-09-30", "last_dividend_ex": "2026-04-10"}
Q4 = {"report_period": "2026-12-31", "last_dividend_ex": "2026-04-10"}
DIV = {"report_period": "2026-09-30", "last_dividend_ex": "2026-11-20"}
# fair = price × yield / (required − g) = 200 / (13.74% − 8%) ≈ 3,484 at 13.74
DV = {"price": 4000.0, "legs": {"yield_pt": 5.0, "g_pt": 8.0}}
R = 13.74


def t(status="pass", gate=None, severity=None):
    return {"status": status, "gate": gate, "severity": severity}


PASS = t()
SOFT = t("fail", "F-score", "soft")
HARD = t("fail", "cut", "hard")
UNKNOWN = t("unknown")


def act(prev, thesis=PASS, inputs=Q2, price=3000.0, required=R, dv=DV, **kw):
    return hy.act(prev, thesis, inputs, price=price, dv=dv, required_live=required, **kw)


def chain(*steps):
    """Run `act` over (thesis, inputs, price[, required]) steps; → every acted block."""
    out, prev = [], None
    for s in steps:
        th, inp, price, *rest = s
        prev = act(prev, th, inp, price, *(rest or [R]))
        out.append(prev)
    return out


# ---------------- thesis ----------------


def test_a_hard_fail_sells_at_once():
    a = act(None, HARD)
    assert a["thesis"]["acts"] is True and a["action"] == "sell_all"
    b = act(act(None), HARD, Q3)
    assert b["action"] == "sell_all" and b["cause"] == "new_filing" and "thesis" in b["changed"]


def test_a_first_soft_fail_holds():
    a = act(act(None), SOFT, Q3)
    assert a["thesis"]["status"] == "fail" and a["thesis"]["acts"] is False
    assert a["thesis"]["soft_fail_periods"] == ["2026-09-30"]
    assert a["action"] == "hold" and a["cause"] == "new_filing"


def test_a_first_soft_fail_on_the_first_record_also_holds():
    a = act(None, SOFT)
    assert a["action"] == "hold" and a["thesis"]["soft_fail_periods"] == ["2026-06-30"]


def test_the_second_soft_fail_report_in_a_row_sells():
    *_, b = chain((SOFT, Q2, 3000.0), (SOFT, Q3, 3000.0))
    assert b["thesis"]["soft_fail_periods"] == ["2026-06-30", "2026-09-30"]
    assert b["thesis"]["acts"] is True and b["action"] == "sell_all"


def test_a_pass_between_two_soft_fails_resets_the_count():
    *_, c = chain((SOFT, Q2, 3000.0), (PASS, Q3, 3000.0), (SOFT, Q4, 3000.0))
    assert c["thesis"]["soft_fail_periods"] == ["2026-12-31"] and c["action"] == "hold"


def test_a_dividend_record_rejudges_but_is_not_a_second_report():
    a, b = chain((SOFT, Q3, 3000.0), (SOFT, DIV, 3000.0))
    assert b["thesis"]["soft_fail_periods"] == ["2026-09-30"] and b["action"] == "hold"
    a, b = chain((PASS, Q3, 3000.0), (HARD, DIV, 3000.0))  # a dividend cut acts at once
    assert b["action"] == "sell_all"


def test_a_report_less_day_changes_nothing():
    first = act(None, PASS)
    for th in (SOFT, HARD, UNKNOWN):
        a = act(first, th, Q2)
        assert a["thesis"] == first["thesis"], th
        assert a["action"] == "hold" and a["cause"] is None and a["changed"] == []
    sold = act(act(None), HARD, Q3)
    assert act(sold, PASS, Q3)["action"] == "sell_all"  # a sell stands until the next report


def test_a_report_less_day_takes_only_the_gate_label_with_the_same_status_and_severity():
    """holdings 0.1.1 relabels ADRO's hard fail from cfo cover to cut: the kept thesis takes
    the label between reports; acts, the count and the action do not move."""
    sold = act(None, t("fail", "cfo cover", "hard"))
    a = act(sold, HARD, Q2)
    assert a["thesis"]["gate"] == "cut" and a["thesis"]["acts"] is True
    assert a["action"] == "sell_all" and a["cause"] is None and a["changed"] == []
    soft = act(None, SOFT)
    b = act(soft, t("fail", "Altman Z", "soft"), Q2)
    assert b["thesis"]["gate"] == "Altman Z"
    assert b["thesis"]["soft_fail_periods"] == soft["thesis"]["soft_fail_periods"]
    assert act(soft, HARD, Q2)["thesis"]["gate"] == "F-score"  # severity moved: kept whole


def test_unknown_on_a_new_report_keeps_the_previous_thesis():
    first = act(None, SOFT)
    a = act(first, UNKNOWN, Q3)
    assert a["thesis"]["status"] == "fail" and a["thesis"]["soft_fail_periods"] == ["2026-06-30"]
    assert act(None, UNKNOWN)["thesis"]["status"] == "unknown"
    assert act(None, UNKNOWN)["action"] == "hold"


def test_a_rule_change_rejudges_without_counting_a_report():
    first = act(None, PASS)
    a = act(first, SOFT, Q2, rejudge=True)
    assert a["thesis"]["soft_fail_periods"] == ["2026-06-30"] and a["action"] == "hold"


# ---------------- take-profit ----------------


def test_take_profit_fires_at_fair_then_does_not_refire_until_10pct_below():
    fair = 200 / ((R - 8.0) / 100)
    steps = [(PASS, Q2, 3000.0),          # armed, below fair
             (PASS, Q2, fair + 10),       # fires: trim to half
             (PASS, Q2, fair - 50),       # dips below fair, not 10% below: still fired
             (PASS, Q2, fair + 10),       # back above: no second trim
             (PASS, Q2, fair * 0.90),     # 10% below fair: re-armed
             (PASS, Q2, fair + 10)]       # fires again
    acts = chain(*steps)
    assert [a["valuation"]["state"] for a in acts] == [
        "armed", "fired", "fired", "fired", "armed", "fired"]
    assert [a["action"] for a in acts] == [
        "hold", "trim_to_half", "stop_adding", "stop_adding", "hold", "trim_to_half"]
    assert acts[1]["cause"] == "price_cross" and acts[1]["changed"] == ["valuation"]
    assert acts[2]["cause"] is None
    assert acts[0]["valuation"]["rearm_below"] == pytest.approx(fair * 0.9)
    assert hy.REARM_BELOW_FAIR_PCT == 10.0


def test_a_first_record_above_fair_is_a_baseline_not_a_trim():
    """User 2026-11-13: a name already above fair on its first record stops adding, no trim;
    it trims only on a later crossing up through fair after re-arming."""
    fair = 200 / ((R - 8.0) / 100)
    acts = chain((PASS, Q2, fair + 10),    # first record above fair: baseline
                 (PASS, Q2, fair + 20),    # still above: no trim
                 (PASS, Q2, fair * 0.90),  # re-armed
                 (PASS, Q2, fair + 10))    # a real crossing: trim
    assert [a["valuation"]["state"] for a in acts] == ["fired", "fired", "armed", "fired"]
    assert [a["action"] for a in acts] == [
        "stop_adding", "stop_adding", "hold", "trim_to_half"]
    assert acts[0]["valuation"]["baseline"] is True
    assert acts[0]["cause"] == "first"


# ---------------- a take-profit trim stays open until it is done (P135) ----------------

FAIR = 200 / ((R - 8.0) / 100)


def test_a_trim_stays_open_until_half_the_shares_are_sold():
    """The 11-17 BBRI trim was lost: a rerun the next day read `fired` and called it stop adding
    before anything was sold. The trim now stays until the shares drop to the half kept."""
    armed = act(None, price=3000.0, shares=1000)
    fired = act(armed, price=FAIR + 10, shares=1000)
    assert fired["action"] == "trim_to_half"
    assert fired["valuation"]["trim"] == {"shares_at_fire": 1000, "keep_shares": 500}
    rerun = act(fired, price=FAIR + 20, shares=1000)  # nothing sold yet
    assert rerun["action"] == "trim_to_half" and rerun["cause"] is None
    assert rerun["valuation"]["trim"] == fired["valuation"]["trim"]
    part = act(rerun, price=FAIR + 20, shares=700)  # 300 of the 500 sold
    assert part["action"] == "trim_to_half" and part["changed"] == []
    done = act(part, price=FAIR + 20, shares=500)
    assert done["action"] == "stop_adding" and done["valuation"]["trim"] is None
    assert done["cause"] == "holdings_change" and done["changed"] == ["valuation"]
    after = act(done, price=FAIR + 20, shares=500)
    assert after["action"] == "stop_adding" and after["cause"] is None


def test_the_half_is_in_whole_lots_and_under_two_lots_nothing_is_carried():
    a = act(act(None, price=3000.0, shares=1500), price=FAIR + 10, shares=1500)
    assert a["valuation"]["trim"] == {"shares_at_fire": 1500, "keep_shares": 800}
    one_lot = act(act(None, price=3000.0, shares=100), price=FAIR + 10, shares=100)
    assert one_lot["action"] == "trim_to_half" and one_lot["valuation"]["trim"] is None
    assert act(one_lot, price=FAIR + 10, shares=100)["action"] == "stop_adding"


def test_a_rearm_cancels_an_open_trim_and_a_thesis_sell_outranks_it():
    fired = act(act(None, price=3000.0, shares=1000), price=FAIR + 10, shares=1000)
    rearmed = act(fired, price=FAIR * 0.90, shares=1000)
    assert rearmed["action"] == "hold" and rearmed["valuation"]["trim"] is None
    assert rearmed["cause"] == "price_cross"
    sold = act(fired, HARD, Q3, price=FAIR + 10, shares=1000)
    assert sold["action"] == "sell_all"


def test_without_shares_a_trim_lasts_one_run_as_before():
    fired = act(act(None, price=3000.0), price=FAIR + 10)
    assert fired["action"] == "trim_to_half" and fired["valuation"]["trim"] is None
    assert act(fired, price=FAIR + 10)["action"] == "stop_adding"


def test_a_trim_fired_before_shares_were_kept_is_carried_from_the_shares_then_held():
    """A record written before P135 (no `trim` key) whose action was trim_to_half: the trim is
    rebuilt from the shares held on that record, so a half sold in between counts as done."""
    old = act(act(None, price=3000.0), price=FAIR + 10)
    del old["valuation"]["trim"]
    assert old["action"] == "trim_to_half"
    unsold = act(old, price=FAIR + 10, shares=1000, prev_shares=1000)
    assert unsold["action"] == "trim_to_half"
    assert unsold["valuation"]["trim"] == {"shares_at_fire": 1000, "keep_shares": 500}
    sold_half = act(old, price=FAIR + 10, shares=500, prev_shares=1000)
    assert sold_half["action"] == "stop_adding" and sold_half["cause"] == "holdings_change"
    no_prev = act(old, price=FAIR + 10, shares=1000)  # no shares on the old record: today's
    assert no_prev["valuation"]["trim"] == {"shares_at_fire": 1000, "keep_shares": 500}
    past = {**old, "action": "stop_adding"}  # an old record already past its trim stays past
    assert act(past, price=FAIR + 10, shares=1000, prev_shares=1000)["action"] == "stop_adding"


def test_a_thesis_sell_outranks_take_profit():
    a = act(None, HARD, price=5000.0)
    assert a["action"] == "sell_all" and a["valuation"]["state"] == "fired"


def test_without_a_fair_price_take_profit_stays_as_it_was():
    a = act(None, dv=None)
    assert a["valuation"]["fair_price"] is None and a["valuation"]["state"] == "armed"
    assert a["action"] == "hold"


# ---------------- the regime toggle (the 2026-11-11 → 11-12 BBNI flip) ----------------


def test_a_regime_toggle_alone_does_not_move_fair_or_flip_take_profit():
    # 11-11 risk-off (+1pt), 11-12 neutral: no new filing in between.
    off = act(None, price=3500.0, required=R + 1.0)
    fair_off = off["valuation"]["fair_price"]
    assert off["valuation"]["state"] == "fired"  # 3,500 ≥ fair at 14.74 (≈ 2,960)
    on = act(off, price=3500.0, required=R)
    assert on["valuation"]["required_pt"] == R + 1.0 and on["valuation"]["required_live_pt"] == R
    assert on["valuation"]["fair_price"] == fair_off
    assert on["valuation"]["state"] == "fired" and on["action"] == "stop_adding"
    assert on["cause"] is None
    # and the other way round: a neutral lock is not tripped by a risk-off day
    calm = act(None, price=3300.0, required=R)
    assert calm["valuation"]["state"] == "armed"
    assert act(calm, price=3300.0, required=R + 1.0)["valuation"]["state"] == "armed"


def test_the_required_return_is_reset_by_a_new_report():
    a = act(None, required=R + 1.0)
    b = act(a, PASS, Q3, required=R)
    assert b["valuation"]["required_pt"] == R and b["valuation"]["required_for"] == Q3


# ---------------- re-entry ----------------


def test_a_sold_name_reenters_only_with_a_margin():
    assert hy.reenters(None) is False
    assert hy.reenters(0.2) is False
    assert hy.reenters(hy.REENTRY_MARGIN_PT - 0.01) is False
    assert hy.reenters(hy.REENTRY_MARGIN_PT) is True


def test_sold_carries_names_the_model_sold_until_held_again():
    prev = [{"symbol": "BBNI", "acted": {"action": "sell_all", "thesis": {"gate": "cut"}}},
            {"symbol": "BMRI", "acted": {"action": "hold", "thesis": {"gate": None}}}]
    s = hy.sold(prev, [], held=["BMRI"], since="2026-11-16")
    assert s == [{"symbol": "BBNI", "since": "2026-11-16", "gate": "cut"}]
    s2 = hy.sold([], s, held=["BMRI"], since="2026-11-23")
    assert s2 == s  # kept, with its first date
    assert hy.sold([], s, held=["BBNI"], since="2026-11-23") == []  # bought back


def test_config_names_the_numbers_and_the_flag():
    c = hy.config()
    assert c["soft_fail_reports"] == 2 and c["rearm_below_fair_pct"] == 10.0
    assert c["act_on_verdicts"] is hy.ACT_ON_VERDICTS
    assert hy.ACT_ON_VERDICTS is True  # user 2026-11-13: thesis sells and trims act
    assert hy.REENTRY_MARGIN_PT == 1.0  # confirmed by the user 2026-11-13
