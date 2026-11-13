"""Flip counter (PLAN S91, phase P rule 7): acted verdict flips per held name per calendar
quarter from journalled `holding` records, split into real causes and method/data bugs, with
S87's replay as the baseline. Synthetic journal records only."""

from __future__ import annotations

from datetime import date

import pytest

from assist import flips
from assist import paper as pp
from assist.journal import Journal

FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64


def rec(sym, as_of, verdict="hold", *, cause=None, acted_cause=None, fp=FP_A, market="IDN",
        kind="holding", acted=True):
    """A journalled `holding` record whose acted verdict is `verdict` (sell / take_profit /
    hold)."""
    a = {"thesis": {"status": "fail" if verdict == "sell" else "pass",
                    "acts": verdict == "sell"},
         "valuation": {"state": "fired" if verdict == "take_profit" else "armed"},
         "action": {"sell": "sell_all", "take_profit": "trim_to_half"}.get(verdict, "hold"),
         "cause": acted_cause, "changed": []}
    outs = {"symbol": sym, "cause": cause, "changed": [], "stale": False,
            "judged_by": fp, "moves_stance": False}
    if acted:
        outs["acted"] = a
    return {"kind": kind, "fingerprint": fp, "subject": market, "asset": "stocks",
            "as_of": as_of, "outputs": outs, "inputs": {}}


def test_verdict_matches_the_replay_mapping():
    assert flips.verdict(rec("X", "2026-11-13", "sell")["outputs"]["acted"]) == "sell"
    assert flips.verdict(rec("X", "2026-11-13", "take_profit")["outputs"]["acted"]) == \
        "take_profit"
    assert flips.verdict(rec("X", "2026-11-13")["outputs"]["acted"]) == "hold"
    assert flips.verdict(None) is None


def test_quarter_label():
    assert flips.quarter("2026-11-13") == "2026Q4"
    assert flips.quarter(date(2026, 3, 31)) == "2026Q1"


def test_no_records_gives_an_empty_count_with_baseline():
    out = flips.count([])
    assert out["summary"] == {"name_quarters": 0, "flips": 0, "real": 0, "method_or_data": 0,
                              "per_name_quarter": None, "over_target": 0, "bugs": 0}
    assert out["over_target"] == [] and out["bugs"] == []
    assert out["target_per_quarter"] == flips.TARGET_PER_QUARTER == 1
    b = out["baseline"]
    assert b["raw_per_name_quarter"] == 0.56 and b["acted_per_name_quarter"] == 0.26


def test_steady_verdict_counts_a_name_quarter_and_no_flip():
    out = flips.count([rec("BBNI", "2026-11-13", acted_cause="first", cause="first"),
                       rec("BBNI", "2026-11-20"), rec("BBNI", "2026-11-27")])
    assert out["summary"]["name_quarters"] == 1
    assert out["summary"]["flips"] == 0 and out["summary"]["per_name_quarter"] == 0
    assert out["names"] == [{"market": "IDN", "symbol": "BBNI", "quarter": "2026Q4",
                             "flips": 0, "real": 0, "method_or_data": 0}]


def test_real_flips_split_by_cause_and_over_target():
    rs = [rec("KLBF", "2026-10-02", acted_cause="first"),
          rec("KLBF", "2026-10-09", "take_profit", acted_cause="price_cross"),
          rec("KLBF", "2026-10-16", "take_profit"),
          rec("KLBF", "2026-11-06", "sell", acted_cause="new_filing"),
          rec("TOWR", "2026-10-02", acted_cause="first"),
          rec("TOWR", "2026-12-04", "take_profit", acted_cause="price_cross")]
    out = flips.count(rs)
    s = out["summary"]
    assert s["name_quarters"] == 2 and s["flips"] == 3 and s["real"] == 3
    assert s["method_or_data"] == 0 and s["per_name_quarter"] == 1.5 and s["bugs"] == 0
    assert s["over_target"] == 1
    assert out["over_target"] == [{"market": "IDN", "symbol": "KLBF", "quarter": "2026Q4",
                                   "flips": 2, "real": 2, "method_or_data": 0}]
    q = out["quarters"]["2026Q4"]
    assert q == {"names": 2, "flips": 3, "real": 3, "method_or_data": 0, "over_target": 1}
    assert [f["cause"] for f in out["flips"]] == ["price_cross", "new_filing", "price_cross"]
    assert out["flips"][1] == {"market": "IDN", "symbol": "KLBF", "as_of": "2026-11-06",
                               "quarter": "2026Q4", "from": "take_profit", "to": "sell",
                               "cause": "new_filing", "kind": "real"}


def test_holdings_change_is_real_from_the_record_cause():
    out = flips.count([rec("A", "2026-10-02"),
                       rec("A", "2026-10-09", "take_profit", cause="holdings_change")])
    assert out["flips"][0]["cause"] == "holdings_change"
    assert out["flips"][0]["kind"] == "real" and out["bugs"] == []


@pytest.mark.parametrize("kw, cause", [
    ({"cause": "rule_version"}, "rule_version"),
    ({"cause": "data_fix"}, "data_fix"),
    ({}, None),  # a change with no cause
    ({"acted_cause": "first", "cause": "first"}, "first"),  # the record restarted mid-history
    ({"fp": FP_B}, "rule_version"),  # no cause but another model judged it
])
def test_method_or_data_flips_are_bugs(kw, cause):
    out = flips.count([rec("BBNI", "2026-10-02"), rec("BBNI", "2026-10-09", "sell", **kw)])
    assert out["summary"]["method_or_data"] == 1 and out["summary"]["real"] == 0
    assert out["bugs"] == [{"market": "IDN", "symbol": "BBNI", "as_of": "2026-10-09",
                            "quarter": "2026Q4", "from": "hold", "to": "sell", "cause": cause,
                            "kind": "method_or_data"}]


def test_acted_cause_wins_over_the_record_cause():
    out = flips.count([rec("A", "2026-10-02"),
                       rec("A", "2026-10-09", "take_profit", acted_cause="price_cross",
                           cause="rule_version")])
    assert out["flips"][0]["cause"] == "price_cross" and out["bugs"] == []


def test_same_day_rerun_keeps_the_last_record_only():
    out = flips.count([rec("A", "2026-10-02"),
                       rec("A", "2026-10-09", "sell", cause="data_fix"),
                       rec("A", "2026-10-09", "hold"),
                       rec("A", "2026-10-16")])
    assert out["summary"]["flips"] == 0


def test_flip_counts_in_the_quarter_of_the_later_record():
    out = flips.count([rec("A", "2026-09-25"),
                       rec("A", "2026-10-02", "sell", acted_cause="new_filing")])
    assert {(n["quarter"], n["flips"]) for n in out["names"]} == {("2026Q3", 0), ("2026Q4", 1)}


def test_markets_kept_apart_and_other_records_ignored():
    out = flips.count([rec("A", "2026-10-02"), rec("A", "2026-10-09", "sell", market="SGP",
                                                   acted_cause="new_filing"),
                       rec("A", "2026-10-16", "sell", kind="stance"),
                       rec("B", "2026-10-02", acted=False),
                       rec("B", "2026-10-09", "sell", acted=False)])
    assert out["summary"]["flips"] == 0 and out["summary"]["name_quarters"] == 2


def test_lines_name_over_target_bugs_and_baseline():
    out = flips.count([rec("BBNI", "2026-10-02"),
                       rec("BBNI", "2026-10-09", "take_profit", acted_cause="price_cross"),
                       rec("BBNI", "2026-10-16", "sell", cause="rule_version")])
    text = "\n".join(flips.lines(out))
    assert "1 name-quarter" in text and "2 flip" in text
    assert "Over the target of 1 per quarter: IDN BBNI 2026Q4 (2)" in text
    assert "bug" in text and "BBNI 2026-10-16 take_profit → sell (rule_version)" in text
    assert "0.56" in text and "0.26" in text


def test_lines_with_no_holding_records():
    text = "\n".join(flips.lines(flips.count([])))
    assert "no holding records" in text and "0.26" in text


def test_paper_track_carries_the_flip_count(tmp_path):
    j = Journal(tmp_path / "j")
    fp = j.register_model({"config": {}, "rules": {}})
    for r in (rec("BBNI", "2026-10-02", fp=fp),
              rec("BBNI", "2026-10-09", "sell", fp=fp, cause="data_fix")):
        j.record(kind="holding", fingerprint=fp, subject="IDN", asset="stocks",
                 as_of=r["as_of"], inputs={}, outputs=r["outputs"])
    d = [date(2026, 1, 2), date(2026, 1, 9)]
    rep = pp.paper_track(journal=j, jci=pp.JciLeg([]), bond=pp.YieldBondLeg([], label="b"),
                         us=pp.UsLeg([], [], label="u"), start=d[0], until=d[-1])
    assert rep.flips["summary"]["method_or_data"] == 1
    assert rep.to_dict(marks=False)["flips"]["bugs"][0]["symbol"] == "BBNI"
