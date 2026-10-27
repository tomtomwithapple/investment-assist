"""Position sizing (P38, PLAN S20a): stance budget, margin/vol split, per-name, sector and
liquidity caps, tranches and trims. Pure function over in-memory rows shaped like S20's ranked
rows (`symbol`, `sector`, `margin_pt`, `passes`) joined with P19's factor columns (`price`,
`vol_1y`, `med_value_60d`, `amihud`)."""

from __future__ import annotations

from datetime import date

import pytest

from assist.candidates import sizing as Z
from assist.candidates.costs import LOT, MAX_PARTICIPATION, cost_for
from assist.candidates.entry import EntryLevels
from assist.layers.types import Regime
from assist.stance import LADDER_SPACING_DAYS, LADDER_TRANCHES

V = 1e9  # portfolio value, IDR
DEEP = 1e15  # turnover that never binds


def row(sym, margin=4.0, vol=0.30, price=1000.0, mv=DEEP, sector="Banks", passes=True):
    return {"symbol": sym, "sector": sector, "margin_pt": margin, "vol_1y": vol,
            "price": price, "med_value_60d": mv, "amihud": None, "passes": passes}


def stance(name="overweight", current=10.0, target=15.0, entry=None):
    return {"subject": "IDN", "asset": "stocks", "stance": name,
            "portfolio": {"current_pct": current, "target_pct": target},
            "entry": entry or {"style": "lump", "tranches": 1, "spacing_days": 0}}


def by_sym(result):
    return {s.symbol: s for s in result.sizes}


def test_budget_is_target_minus_current_times_portfolio():
    r = Z.size([row("AAAA"), row("BBBB", sector="Energy")], stance(current=10, target=12), V, {},
               "neutral")
    assert r.budget_idr == pytest.approx(0.02 * V)
    assert sum(s.idr for s in r.sizes) + r.unspent_idr == pytest.approx(r.budget_idr)


def test_split_proportional_to_margin_over_vol():
    rows = [row("AAAA", margin=6, vol=0.30), row("BBBB", margin=2, vol=0.20, sector="Energy")]
    r = Z.size(rows, stance(current=10, target=12), V, {}, "neutral",
               caps={"name_pct": 100.0})
    s = by_sym(r)
    # weights 20 : 10 → 2/3 and 1/3 of 20M, rounded down to whole lots of IDR 100k
    assert s["AAAA"].idr == pytest.approx(13_300_000)
    assert s["BBBB"].idr == pytest.approx(6_600_000)


def test_non_positive_margin_failed_or_missing_vol_excluded():
    rows = [row("AAAA"), row("NEG", margin=-1), row("ZERO", margin=0),
            row("FAIL", passes=False), row("NOVOL", vol=None)]
    r = Z.size(rows, stance(), V, {}, "neutral")
    assert set(by_sym(r)) == {"AAAA"}
    reasons = dict(r.excluded)
    assert "margin" in reasons["NEG"] and "margin" in reasons["ZERO"]
    assert "fails" in reasons["FAIL"] and "vol_1y" in reasons["NOVOL"]


@pytest.mark.parametrize("name", ["underweight", "avoid"])
def test_underweight_or_avoid_gives_no_adds(name):
    r = Z.size([row("AAAA")], stance(name, current=10, target=5), V, {}, "neutral")
    assert r.budget_idr == 0 and r.sizes == []


def test_negative_gap_gives_no_adds():
    r = Z.size([row("AAAA")], stance("neutral", current=12, target=10), V, {}, "neutral")
    assert r.budget_idr == 0 and r.sizes == []


def test_per_name_cap_and_redistribution_once():
    # budget 10% = 100M; per-name cap 5% = 50M. Weights A:B:C = 8:1:1 (vol equal).
    rows = [row("AAAA", margin=8), row("BBBB", margin=1, sector="Energy"),
            row("CCCC", margin=1, sector="Tech")]
    r = Z.size(rows, stance(current=0, target=10), V, {}, "neutral")
    s = by_sym(r)
    assert s["AAAA"].idr == pytest.approx(50e6)  # capped
    # A's excess 30M goes once to B and C (equal weights): 10M + 15M each = 25M
    assert s["BBBB"].idr == pytest.approx(25e6) and s["CCCC"].idr == pytest.approx(25e6)
    assert r.unspent_idr == pytest.approx(0)
    assert "per-name cap" in s["AAAA"].reason


def test_leftover_after_one_redistribution_is_left_unspent():
    # budget 20% = 200M, two names each capped at 50M: 100M stays unspent
    rows = [row("AAAA"), row("BBBB", sector="Energy")]
    r = Z.size(rows, stance(current=0, target=20), V, {}, "neutral")
    assert all(s.idr == pytest.approx(50e6) for s in r.sizes)
    assert r.unspent_idr == pytest.approx(100e6)


def test_held_value_counts_against_name_cap():
    r = Z.size([row("AAAA"), row("BBBB", sector="Energy")], stance(current=0, target=20), V,
               {"AAAA": 40e6}, "neutral")
    assert by_sym(r)["AAAA"].idr == pytest.approx(10e6)


def test_sector_cap_keeps_best_margins():
    rows = [row(f"B{i:03d}", margin=10 - i) for i in range(7)]
    r = Z.size(rows, stance(current=0, target=10), V, {}, "neutral")
    assert set(by_sym(r)) == {f"B{i:03d}" for i in range(5)}  # default 5 names
    assert sum("sector cap" in why for _, why in r.excluded) == 2
    r2 = Z.size(rows, stance(current=0, target=10), V, {}, "neutral",
                caps={"sector_names": {"Banks": 3}})
    assert len(r2.sizes) == 3


def test_liquidity_cap_each_tranche_under_participation():
    mv = 50e6  # 10% participation → 5M per tranche
    r = Z.size([row("THIN", mv=mv)], stance(current=0, target=5), V, {}, "risk_off")
    s = by_sym(r)["THIN"]
    assert len(s.tranches) == LADDER_TRANCHES
    for t in s.tranches:
        assert t.idr <= MAX_PARTICIPATION * mv
        c = cost_for(row("THIN", mv=mv), t.idr)
        assert "over_participation" not in c.flags
    assert "liquidity" in s.reason


def test_below_one_lot_dropped():
    # price 9,000 × 100 shares = 900k per lot; budget share far below that
    rows = [row("AAAA", margin=50, sector="X"), row("PRICY", margin=0.01, price=9000)]
    r = Z.size(rows, stance(current=0, target=1), V, {}, "neutral")
    assert "PRICY" not in by_sym(r)
    assert "below one lot" in dict(r.excluded)["PRICY"]


def test_no_turnover_dropped():
    r = Z.size([row("AAAA"), row("NOMV", mv=None, sector="X")], stance(), V, {}, "neutral")
    assert "NOMV" not in by_sym(r) and "turnover" in dict(r.excluded)["NOMV"]


def test_tranches_whole_lots_lump_vs_ladder():
    lump = by_sym(Z.size([row("AAAA")], stance(current=0, target=3), V, {}, "neutral"))["AAAA"]
    assert len(lump.tranches) == 1 and lump.tranches[0].day == 0
    assert lump.tranches[0].shares % LOT == 0
    lad = by_sym(Z.size([row("AAAA")], stance(current=0, target=3), V, {},
                        Regime(date(2026, 10, 27), "risk_off", "flat")))["AAAA"]
    assert [t.day for t in lad.tranches] == [i * LADDER_SPACING_DAYS
                                             for i in range(LADDER_TRANCHES)]
    assert sum(t.idr for t in lad.tranches) == pytest.approx(lad.idr)
    assert all(t.shares % LOT == 0 for t in lad.tranches)


def test_stance_ladder_entry_used():
    st = stance(current=0, target=3, entry={"style": "ladder", "tranches": 4, "spacing_days": 7})
    s = by_sym(Z.size([row("AAAA")], st, V, {}, "neutral"))["AAAA"]
    assert [t.day for t in s.tranches] == [0, 7, 14, 21]


def test_entry_levels_give_tranche_limits():
    lv = EntryLevels("AAAA", date(2026, 10, 27), 1000.0, 1400.0, -28.0, 30.0, 3, -30.0, -50.0,
                     -40.0, 10.0, 15.0, 70.0, 3.0, 950.0, 840.0, "wait")
    s = by_sym(Z.size([row("AAAA")], stance(current=0, target=3), V, {}, "risk_off",
                      entry={"AAAA": {"levels": lv, "cost": None}}))["AAAA"]
    assert [t.limit for t in s.tranches] == [None, 950.0, 840.0]


def test_trims_for_failed_or_negative_margin_holdings():
    rows = [row("GOOD"), row("NEG", margin=-2), row("FAIL", passes=False)]
    held = {"GOOD": 10e6, "NEG": 20e6, "FAIL": 30e6, "GONE": 5e6}
    r = Z.size(rows, stance("avoid", current=6, target=0), V, held, "neutral")
    assert r.sizes == []
    trims = {t.symbol: t for t in r.trims}
    assert set(trims) == {"NEG", "FAIL", "GONE"}
    assert trims["NEG"].idr == pytest.approx(20e6) and "margin" in trims["NEG"].reason
    assert "fails" in trims["FAIL"].reason and "not in the candidate list" in trims["GONE"].reason


def test_trim_above_name_cap():
    r = Z.size([row("BIG")], stance(current=10, target=10), V, {"BIG": 70e6}, "neutral")
    (t,) = r.trims
    assert t.symbol == "BIG" and t.idr == pytest.approx(20e6) and "per-name cap" in t.reason


def test_caps_in_config_and_fingerprint():
    cfg = Z.config()
    assert cfg["caps"] == Z.CAPS
    assert Z.CAPS["name_pct"] == 5.0 and Z.CAPS["sector_names"] == 5
    assert Z.fingerprint() != Z.fingerprint({"name_pct": 4.0})
    r = Z.size([row("AAAA")], stance(), V, {}, "neutral")
    assert r.fingerprint == Z.fingerprint()


def test_deterministic():
    rows = [row("AAAA", margin=3), row("BBBB", margin=5, sector="E"), row("CCCC", sector="F")]
    a = Z.size(rows, stance(), V, {"CCCC": 1e6}, "neutral")
    b = Z.size(list(reversed(rows)), stance(), V, {"CCCC": 1e6}, "neutral")
    assert a == b
