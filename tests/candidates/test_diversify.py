"""Groups, keepers and the tilt exception (P98, PLAN S81)."""

from __future__ import annotations

from assist.candidates import diversify as dv
from assist.candidates.diversify import judge, size_bucket

BANK = {"sector": "Keuangan", "industry": "Bank"}
P = {
    "BMRI": {**BANK, "mktcap": 400e12}, "BBNI": {**BANK, "mktcap": 150e12},
    "BBRI": {**BANK, "mktcap": 500e12}, "BJBR": {**BANK, "mktcap": 9e12},
    "BTPS": {**BANK, "mktcap": 8e12}, "ICBP": {"sector": "Primer", "industry": "Makanan Olahan",
                                               "mktcap": 120e12},
    "NOIND": {"sector": "X", "industry": None, "mktcap": 9e12},
    "NOCAP": {**BANK, "mktcap": None},
}


def by(out):
    return {v["symbol"]: v for v in out}


def test_three_size_buckets_and_the_default_lines():
    assert dv.SIZES == ("large", "mid", "small")
    assert dv.SIZE_LINES == {"large": 50e12, "mid": 5e12} and dv.LEVEL == "industry"
    assert [size_bucket(x) for x in (50e12, 49.9e12, 5e12, 4.9e12)] == [
        "large", "mid", "mid", "small"]
    assert size_bucket(None) is None and size_bucket(0) is None


def test_same_industry_same_size_is_redundant_and_the_kept_name_is_the_keeper():
    v = by(judge(["BMRI", "BBNI", "BBRI"], P, kept={"BMRI": 4.1},
                 ranked={"BMRI": 4.1, "BBNI": -0.3}, held={"BBRI": 9e6, "BBNI": 3e6}))
    assert (v["BMRI"]["position"], v["BMRI"]["redundant"], v["BMRI"]["basis"]) == (
        1, False, "kept by a passing screen")
    assert (v["BBNI"]["position"], v["BBNI"]["basis"]) == (2, "ranked by a passing screen")
    assert (v["BBRI"]["position"], v["BBRI"]["redundant"], v["BBRI"]["basis"]) == (
        3, True, "unrated")
    assert all(x["keeper"] == "BMRI" and x["group_size"] == 3 for x in v.values())


def test_two_kept_names_keep_the_higher_margin():
    v = by(judge(["BMRI", "BBNI"], P, kept={"BMRI": 2.0, "BBNI": 3.5}))
    assert v["BBNI"]["redundant"] is False and v["BMRI"]["redundant"] is True


def test_unrated_names_keep_the_highest_dividend_yield():
    p = {**P, "BJBR": {**P["BJBR"], "div_yield": 7.5}, "BTPS": {**P["BTPS"], "div_yield": 4.0}}
    held = {"BJBR": 1e6, "BTPS": 4e6}  # BTPS is the larger holding, BJBR pays more
    v = by(judge(["BJBR", "BTPS"], p, held=held))
    assert v["BJBR"]["keeper"] == "BJBR" and v["BTPS"]["redundant"] is True
    assert v["BJBR"]["div_yield"] == 7.5
    # a name with no yield comes after one with a yield, whatever is held
    p["BTPS"] = {**P["BTPS"], "div_yield": None}
    assert by(judge(["BJBR", "BTPS"], p, held=held))["BTPS"]["redundant"] is True
    p["BJBR"] = {**P["BJBR"], "div_yield": 0.0}
    # neither pays: the larger holding is kept
    assert by(judge(["BJBR", "BTPS"], p, held=held))["BTPS"]["keeper"] == "BTPS"


def test_a_rated_name_beats_a_higher_yield():
    p = {**P, "BBNI": {**P["BBNI"], "div_yield": 12.0}}
    v = by(judge(["BMRI", "BBNI"], p, ranked={"BMRI": -1.0}))
    assert v["BMRI"]["keeper"] == "BMRI"


def test_a_different_size_or_industry_is_never_redundant():
    v = by(judge(["BMRI", "BJBR", "ICBP"], P))
    assert not any(x["redundant"] for x in v.values())
    assert (v["BMRI"]["size"], v["BJBR"]["size"]) == ("large", "mid")


def test_no_industry_or_no_market_cap_has_no_group():
    v = by(judge(["NOIND", "NOCAP", "BMRI", "UNKNOWN"], P))
    assert not any(x["redundant"] for x in v.values())
    assert v["NOCAP"]["size"] is None and v["UNKNOWN"]["industry"] is None
    assert v["NOCAP"]["group_size"] == 1


def test_only_a_favourable_tilt_allows_redundancy():
    names, kw = ["BMRI", "BBNI"], {"kept": {"BMRI": 4.0}}
    assert by(judge(names, P, **kw))["BBNI"]["allowed"] is False
    assert by(judge(names, P, sector_tilts={"Keuangan": 0.25}, **kw))["BBNI"]["allowed"] is True
    assert by(judge(names, P, sector_tilts={"Keuangan": -0.3}, **kw))["BBNI"]["allowed"] is False
    assert by(judge(names, P, sector_tilts={"Keuangan": 0.0}, **kw))["BBNI"]["allowed"] is False
    assert by(judge(names, P, industry_tilts={"Bank": 0.1}, **kw))["BBNI"]["allowed"] is True
    # the keeper is never "allowed": it is simply not redundant
    assert by(judge(names, P, sector_tilts={"Keuangan": 0.25}, **kw))["BMRI"]["allowed"] is False


def test_one_verdict_per_symbol_in_order():
    assert [v["symbol"] for v in judge(["BBRI", "BMRI", "BMRI"], P)] == ["BBRI", "BMRI"]
    assert dv.config()["size_lines"]["large"] == 50e12
