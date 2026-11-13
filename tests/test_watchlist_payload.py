"""PLAN S89 (P107-watchlist): the user's Stockbit screeners are a watchlist only (phase P rule 1).
A watchlist name that no passing screen ranked is judged by the same code as a held name
(thesis, valuation, fit) and listed as a `source: watchlist` row; membership never changes a
size, a rank, a keep / sell or any verdict. In-memory data only: nothing reads a real store."""

from __future__ import annotations

import copy
import json
from datetime import timedelta

from test_run_undervalued import DAY, DIV, FP, REGIME, inputs, screen, stance, valid

from assist.candidates import holdings as hd
from assist.candidates.dividend_value import DividendData
from assist.layers import undervalued as uv
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_series import Bar, Fundamentals

BAR = DAY - timedelta(days=3)
HURDLE = 13.74
BIG = "Cheap Big Caps with Dividend"
MID = "Cheap Mid Caps with Dividend"
NONBANK = {"piotroski": 7, "altman_z": 3.0, "cfo_ttm": 1e12, "der": 0.5, "interest_cov": 5.0,
           "free_float": 40.0, "med_value_60d": 5e10, "price": 4000.0, "vol_1y": 0.3,
           "days_traded_60": 60}


def fund(period, ni=5000.0, equity=25000.0, cfo=6000.0):
    p = DAY.fromisoformat(period)
    return Fundamentals(p, p + timedelta(days=120), cfo, equity, 0.0, ni, ni, None, None,
                        None, None)


def judge(sym, *, dps=200.0, sector="Energi", cut=False, **row_kw):
    last = dps / 2 if cut else dps
    data = DividendData(
        bars={sym: [Bar(BAR, 4000.0, 4e4)]}, quarters={sym: [fund("2026-03-31")]},
        dividends={sym: [{"ex": f"{y}-04-10", "value": dps if y < 2026 else last,
                          "ccy": "CURRENCY_IDR"} for y in range(2021, 2027)]},
        sectors={sym: sector})
    return hd.judge_inputs(sym, {**NONBANK, **row_kw}, data, BAR, hurdle_pt=HURDLE)


JUDGED = {"ADRO": judge("ADRO"), "BBNI": judge("BBNI", sector="Keuangan", cut=True),
          "BMRI": judge("BMRI", sector="Keuangan")}


def watchlist(stale=None):
    members = {"ADRO": [BIG], "BBNI": [BIG, MID], "BMRI": [BIG], "ZZZZ": [MID]}
    return {"as_of": "2026-10-22", "stale": stale, "category": "Custom", "missing": [],
            "screeners": [
                {"id": 7377506, "name": BIG, "category": "Custom", "totalrows": 3,
                 "fetched": 3, "members": ["ADRO", "BBNI", "BMRI"]},
                {"id": 7377507, "name": MID, "category": "Custom", "totalrows": 2,
                 "fetched": 2, "members": ["BBNI", "ZZZZ"]}],
            "members": members}


PROFILES = {"BMRI": {"sector": "Keuangan", "industry": "Bank", "mktcap": 300e12, "div_yield": 6},
            "BBNI": {"sector": "Keuangan", "industry": "Bank", "mktcap": 150e12, "div_yield": 7},
            "ADRO": {"sector": "Energi", "industry": "Coal", "mktcap": 70e12, "div_yield": 10}}
HELD = {"BMRI": 20e6, "BBNI": 8e6}


def payload(wl=None, problems=(), held=HELD):
    inp = inputs({"dividend_value": screen("dividend_value", cands=DIV)})
    inp.judged, inp.profiles, inp.watchlist = JUDGED, PROFILES, wl
    inp.data_problems = tuple(problems)
    return valid(uv.assemble(inp, day=DAY, stance=stance("overweight", 10.0, 20.0),
                             portfolio_value_idr=1e9, holdings=held, regime=REGIME,
                             fingerprint=FP))


def rows(p):
    return {r["symbol"]: r for r in p["watchlist"]["rows"]}


def test_schema_versions_bumped():
    assert uv.SCHEMA_VERSION == "1.7.0" and payload()["schema_version"] == "1.7.0"
    assert hd.SCHEMA_VERSION >= "1.1.0"  # 1.2.0 since S87


def test_without_a_watchlist_the_payload_has_no_watchlist_block():
    assert "watchlist" not in payload()


def test_names_no_passing_screen_ranked_become_watchlist_rows_with_their_screeners():
    p = payload(watchlist())
    w = p["watchlist"]
    assert w["as_of"] == "2026-10-22" and w["stale"] is None
    assert [s["name"] for s in w["screeners"]] == [BIG, MID]
    assert w["in_pool"] == ["BMRI"]  # the dividend screen ranked it: judged there, not here
    r = rows(p)
    assert sorted(r) == ["ADRO", "BBNI", "ZZZZ"]
    assert all(x["source"] == "watchlist" for x in r.values())
    assert r["BBNI"]["screeners"] == [BIG, MID] and r["BBNI"]["held"] is True
    assert r["ADRO"]["held"] is False and r["ADRO"]["held_idr"] == 0.0
    # judged by the same code as a holding record
    assert r["ADRO"]["thesis"] == hd.thesis(JUDGED["ADRO"])
    assert r["BBNI"]["thesis"]["gate"] == "cut" and r["BBNI"]["thesis"]["severity"] == "hard"
    assert r["ZZZZ"]["thesis"]["status"] == "unknown"
    assert r["ADRO"]["valuation"]["fair_price"] is not None
    # watch only: no size, no rank, no action besides watch
    for x in r.values():
        assert x["action"] == "watch" and x["size"] is None and "rank" not in x


def test_fit_says_whether_a_held_or_kept_name_already_holds_the_group():
    r = rows(payload(watchlist()))
    assert r["BBNI"]["fit"]["redundant"] is True and r["BBNI"]["fit"]["keeper"] == "BMRI"
    assert r["ADRO"]["fit"]["redundant"] is False and r["ADRO"]["fit"]["ok"] is True
    assert r["ZZZZ"]["fit"]["group"] is None


def strip(p):
    q = copy.deepcopy(p)
    q.pop("watchlist", None)
    return q


def test_membership_changes_no_verdict_size_rank_or_trim():
    bare, with_wl = payload(), payload(watchlist())
    assert uv._dumps(strip(with_wl)) == uv._dumps(bare)


def test_a_holding_verdict_is_identical_on_or_off_the_watchlist():
    on = payload(watchlist())
    off = payload()
    kw = {"day": DAY, "fingerprint": FP, "holdings": HELD}
    a = json.loads(json.dumps(hd.build(on, JUDGED, **kw)))
    b = json.loads(json.dumps(hd.build(off, JUDGED, **kw)))
    for p in (a, b):
        assert not list(hd.validator().iter_errors(p))
    ra = {r["symbol"]: r for r in a["holdings"]}
    rb = {r["symbol"]: r for r in b["holdings"]}
    assert ra["BBNI"]["watchlists"] == [BIG, MID] and ra["BMRI"]["watchlists"] == [BIG]
    assert rb["BBNI"]["watchlists"] == []
    for sym in HELD:
        x, y = dict(ra[sym]), dict(rb[sym])
        x.pop("watchlists"), y.pop("watchlists")
        assert x == y
    # the watchlist row and the holding record give the same answer for the held name
    w = rows(on)["BBNI"]
    assert w["thesis"] == ra["BBNI"]["thesis"]
    assert w["valuation"]["fair_price"] == ra["BBNI"]["valuation"]["fair_price"]


def test_a_previous_holdings_file_without_watchlists_still_loads(tmp_path):
    p = json.loads(json.dumps(hd.build(payload(), JUDGED, day=DAY, fingerprint=FP,
                                       holdings=HELD)))
    for r in p["holdings"]:
        r.pop("watchlists")
    p["schema_version"] = "1.0.0"
    hd.write(p, tmp_path)
    assert hd.load(tmp_path, "IDN") is not None


def test_bad_data_makes_every_watchlist_verdict_unknown():
    r = rows(payload(watchlist(), problems=["price: null for every name"]))
    assert {x["thesis"]["status"] for x in r.values()} == {"unknown"}
    assert all(x["valuation"]["fair_price"] is None for x in r.values())


def test_a_stale_watchlist_is_a_stale_input_and_still_listed():
    p = payload(watchlist(stale="idx-method screener_member (stale: newest 2026-10-12, 11d old)"))
    assert p["watchlist"]["stale"].startswith("idx-method screener_member (stale")
    assert any("screener_member (stale" in s for s in p["stale_inputs"])
    assert rows(p)


class FakeSource:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def latest(self, day):
        if self.error:
            raise self.error
        return self.result


def test_live_reader_turns_a_missing_or_stale_store_into_stale_inputs():
    wl, st = uv.read_watchlist(DAY, FakeSource(error=SourceUnavailable("idx-method", "missing",
                                                                       "no table")))
    assert wl is None and st == ["idx-method (missing): no watchlist"]
    wl, st = uv.read_watchlist(DAY, FakeSource(watchlist(stale="x (stale)")))
    assert wl is not None and st == []  # assemble names it once, from the block
    w = watchlist()
    w["missing"] = ["99"]
    _, st = uv.read_watchlist(DAY, FakeSource(w))
    assert st == ["idx-method watchlist: configured screener 99 not found"]
