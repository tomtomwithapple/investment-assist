"""PLAN S18 (P36): undervalued dividend screen. Gordon return (trailing yield + capped
sustainable growth) against the P34 IDN hurdle, safety gates, own-yield cheapness, quarterly
placebo replay. Data is built in memory, or from tests/fixtures/dividend_value/stockbiter.sql
(the real store's schema, inspected read-only 2026-10-27)."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest
from helpers import FIXTURES, make_sqlite

from assist.candidates import dividend_value as dv
from assist.candidates.hurdle import Hurdle
from assist.sources.idxmethod_series import DB, Bar, Fundamentals, IdxMethodSeries

D = date.fromisoformat
FIX = FIXTURES / "dividend_value"


def fund(period: str, *, ni=100.0, equity=500.0, cfo=120.0) -> Fundamentals:
    p = D(period)
    return Fundamentals(p, p + timedelta(days=120), cfo, equity, 0.0, ni, ni, None, None,
                        None, None)


def annual_divs(first_year: int, last_year: int, dps: float, month_day="04-10") -> list[dict]:
    return [{"ex": f"{y}-{month_day}", "value": dps, "ccy": "CURRENCY_IDR"}
            for y in range(first_year, last_year + 1)]


AS_OF = D("2026-09-30")
BARS = [Bar(D("2026-09-30"), 1000.0, 10000.0)]  # 10 shares
QUARTERS = [fund("2025-03-31"), fund("2025-06-30"), fund("2025-12-31", ni=100.0),
            fund("2026-03-31", ni=100.0)]


def test_config_is_hand_set_and_fingerprinted():
    assert dv.CONFIG["g_cap_pt"] == 8.0
    assert dv.CONFIG["max_payout"] == 0.90
    assert dv.CONFIG["min_paid_years"] == 4 and dv.CONFIG["paid_years"] == 5
    assert dv.CONFIG["cut_years"] == 2
    assert dv.CONFIG["own_years"] == 5


# ---------------- split adjustment ----------------


def test_adjust_dividends_rescales_pre_split_dps_to_the_adjusted_price_basis():
    bars = [Bar(D("2021-04-01"), 1000.0, 100000.0), Bar(D("2022-04-01"), 1000.0, 100000.0)]
    shares = {D("2021-06-30"): 20.0, D("2022-06-30"): 100.0}
    recs = [{"ex": "2021-04-08", "value": 250.0, "ccy": "CURRENCY_IDR"},
            {"ex": "2022-04-08", "value": 50.0, "ccy": "CURRENCY_IDR"}]
    out = dv.adjust_dividends(recs, bars, shares)
    assert [r["value"] for r in out] == pytest.approx([50.0, 50.0])
    assert out[0]["split_factor"] == pytest.approx(0.2)
    assert out[1]["split_factor"] == 1.0


def test_adjust_dividends_ignores_small_share_count_drift_and_missing_counts():
    bars = [Bar(D("2022-04-01"), 1000.0, 100000.0)]
    recs = [{"ex": "2022-04-08", "value": 50.0, "ccy": "CURRENCY_IDR"}]
    assert dv.adjust_dividends(recs, bars, {D("2022-06-30"): 95.0})[0]["value"] == 50.0
    assert dv.adjust_dividends(recs, bars, {})[0]["value"] == 50.0


# ---------------- expected return ----------------


def test_expected_return_is_yield_plus_capped_growth():
    # yield 5%, ROE 20%, payout 50% -> g = 10% capped at 8
    assert dv.expected_return(0.05, 0.20, 0.50) == pytest.approx((5.0, 8.0, 13.0))
    # ROE 10%, payout 60% -> g 4
    assert dv.expected_return(0.05, 0.10, 0.60) == pytest.approx((5.0, 4.0, 9.0))
    # payout above 100%: no retention, no growth
    assert dv.expected_return(0.05, 0.10, 1.2) == pytest.approx((5.0, 0.0, 5.0))
    assert dv.expected_return(0.05, 0.20, 0.5, g_cap_pt=6.0)[1] == 6.0


def test_assess_payout_above_earnings_fails():
    divs = annual_divs(2021, 2026, 50.0)  # 50/1000 = 5% yield, total 500 vs ni 100
    a = dv.assess(AS_OF, BARS, QUARTERS, divs)
    assert a.yield_pt == pytest.approx(5.0)
    assert a.payout == pytest.approx(0.05 * 10000 / 100)  # 5.0 -> fails
    assert "payout" in " ".join(a.reasons)


def test_assess_gates_pass_and_legs():
    divs = annual_divs(2021, 2026, 5.0)  # yield 0.5%, total div 50, payout 50%
    a = dv.assess(AS_OF, BARS, QUARTERS, divs)
    assert a.ok, a.reasons
    assert a.yield_pt == pytest.approx(0.5)
    assert a.roe_pt == pytest.approx(20.0)
    assert a.payout == pytest.approx(0.5)
    assert a.g_pt == pytest.approx(8.0)  # 20% x 0.5 = 10, capped
    assert a.expected_pt == pytest.approx(8.5)
    assert a.cfo_cover == pytest.approx(120.0 / 50.0)
    assert a.paid_years == 5
    assert a.cut is False


def test_gate_cfo_must_cover_dividends_unless_bank():
    q = [*QUARTERS[:-1], fund("2026-03-31", cfo=40.0)]
    divs = annual_divs(2021, 2026, 5.0)
    a = dv.assess(AS_OF, BARS, q, divs)
    assert not a.ok and "CFO" in " ".join(a.reasons)
    assert dv.assess(AS_OF, BARS, q, divs, bank=True).ok


def test_gate_paid_in_four_of_five_years():
    divs = annual_divs(2024, 2026, 5.0)
    a = dv.assess(AS_OF, BARS, QUARTERS, divs)
    assert a.paid_years == 3
    assert not a.ok and "paid 3 of 5" in " ".join(a.reasons)
    gap = [d for d in annual_divs(2021, 2026, 5.0) if d["ex"][:4] != "2023"]
    assert dv.assess(AS_OF, BARS, QUARTERS, gap).paid_years == 4


def test_gate_cut_in_last_two_years_unless_earnings_recovered():
    divs = annual_divs(2021, 2025, 8.0) + annual_divs(2026, 2026, 5.0)
    flat = [fund("2025-03-31", ni=100.0), fund("2025-06-30"), fund("2025-12-31"),
            fund("2026-03-31", ni=100.0)]
    a = dv.assess(AS_OF, BARS, flat, divs)
    assert a.cut is True and a.recovered is False
    assert not a.ok and "cut" in " ".join(a.reasons)
    up = [fund("2025-03-31", ni=80.0), fund("2025-06-30"), fund("2025-12-31"),
          fund("2026-03-31", ni=100.0)]
    b = dv.assess(AS_OF, BARS, up, divs)
    assert b.cut is True and b.recovered is True and b.ok, b.reasons


def test_gate_needs_positive_earnings_and_a_dividend():
    q = [*QUARTERS[:-1], fund("2026-03-31", ni=-5.0)]
    a = dv.assess(AS_OF, BARS, q, annual_divs(2021, 2026, 5.0))
    assert not a.ok and a.payout is None
    b = dv.assess(AS_OF, BARS, QUARTERS, [])
    assert not b.ok and "no dividend" in " ".join(b.reasons)


def test_assess_is_point_in_time():
    # a quarter that is not yet available (period + 120 days) is ignored
    q = [*QUARTERS, fund("2026-06-30", ni=-1000.0)]
    a = dv.assess(AS_OF, BARS, q, annual_divs(2021, 2026, 5.0))
    assert a.ok and a.period == D("2026-03-31")
    # a dividend after as_of is ignored
    later = [*annual_divs(2021, 2026, 5.0), {"ex": "2026-10-15", "value": 999.0, "ccy": None}]
    assert dv.assess(AS_OF, BARS, QUARTERS, later).yield_pt == pytest.approx(0.5)
    assert dv.assess(D("2010-01-01"), BARS, QUARTERS, []) is None


# ---------------- own-yield cheapness ----------------


def test_own_yield_percentile():
    assert dv.own_yield_percentile(0.05, [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]) == (
        pytest.approx(5 / 8))
    assert dv.own_yield_percentile(0.05, [0.01, 0.02]) is None  # too few quarters
    assert dv.own_yield_percentile(None, [0.01] * 10) is None


def test_assess_cheapness_uses_the_names_own_five_years():
    # price falls each quarter, so today's yield is the highest of its history
    bars = []
    p = 2000.0
    for qe in dv.quarter_ends(D("2020-03-31"), AS_OF):
        bars.append(Bar(qe, p, p * 10))
        p *= 0.97
    divs = annual_divs(2019, 2026, 5.0)
    a = dv.assess(AS_OF, bars, QUARTERS, divs)
    assert a.own_yield_pct == pytest.approx(1.0)
    assert a.own_yield_n == 20  # quarter ends in the 5 years before as_of


# ---------------- replay ----------------


def _universe(n=50, start="2017-03-31", end="2026-06-30", seed=1, signal=True):
    """n names; name i targets a 1%..6% yield (each April's dividend is that share of the
    price then, and the price drops by it in that quarter). With `signal`, a higher yield earns
    a higher next-quarter total return; otherwise total returns are noise."""
    rng = random.Random(seed)
    qes = dv.quarter_ends(D(start), D(end))
    bars, quarters, divs = {}, {}, {}
    for i in range(n):
        sym = f"S{i:02d}"
        p, b = 1000.0, []
        y = 0.01 + 0.001 * i
        for qe in qes:
            b.append(Bar(qe, p, p * 1e9))
            ex_drop = y * p if qe.month == 3 else 0.0
            p = p * (1 + (0.0005 * i if signal else 0.0) + rng.gauss(0, 0.01)) - ex_drop
        bars[sym] = b
        divs[sym] = [{"ex": f"{yr}-04-10",
                      "value": y * next((x.price for x in reversed(b)
                                         if x.date <= D(f"{yr}-04-10")), 1000.0),
                      "ccy": "CURRENCY_IDR"} for yr in range(2012, 2027)]
        quarters[sym] = [fund(qe.isoformat(), ni=2e11, equity=1e13, cfo=2e11)
                         for qe in dv.quarter_ends(D("2015-12-31"), D(end))]
    return bars, quarters, divs


def test_replay_panel_point_in_time_and_forward_return():
    bars = {"A": [Bar(D("2022-12-30"), 1000.0, 1e12), Bar(D("2023-03-31"), 1100.0, 1.1e12),
                  Bar(D("2023-06-30"), 1210.0, 1.21e12)]}
    quarters = {"A": [fund("2022-06-30", ni=1e11, equity=5e11, cfo=1e11)]}
    divs = {"A": [*annual_divs(2018, 2022, 30.0),
                  {"ex": "2023-05-02", "value": 55.0, "ccy": "CURRENCY_IDR"}]}
    panel = dv.replay_panel(bars, quarters, divs, min_mktcap=0)
    by = dict(panel)
    rec = by[D("2023-03-31")][0]
    # price 1100 -> 1210 plus a 55 dividend inside the quarter
    assert rec["fwd"] == pytest.approx((1210 + 55) / 1100 - 1)
    assert rec["expected_pt"] == pytest.approx(100 * 30 / 1100 + 8.0)
    assert D("2023-06-30") not in by  # no later quarter end yet: no forward return


def test_replay_panel_applies_the_safety_gates_and_size_floor():
    bars = {"A": [Bar(D("2023-03-31"), 1000.0, 1e12), Bar(D("2023-06-30"), 1000.0, 1e12)]}
    quarters = {"A": [fund("2022-06-30", ni=1e11, equity=5e11, cfo=1e11)]}
    few = {"A": annual_divs(2022, 2022, 30.0)}
    assert dv.replay_panel(bars, quarters, few, min_mktcap=0) == [(D("2023-03-31"), [])]
    ok = {"A": annual_divs(2018, 2022, 30.0)}
    assert dv.replay_panel(bars, quarters, ok, min_mktcap=2e12) == [(D("2023-03-31"), [])]


def test_replay_panel_applies_the_bank_f_floor_point_in_time():
    """S88: a bank whose newest F knowable by the quarter end is below 4 is out; F 4 and n/a
    stay in; a name not in `bank_f` (a non-bank) is unaffected."""
    qe = [D(x) for x in ("2023-03-31", "2023-06-30", "2023-09-29", "2023-12-29", "2024-03-28",
                         "2024-06-28")]
    bars = {s: [Bar(d, 1000.0, 1e12) for d in qe] for s in ("BANK", "OTHR")}
    quarters = {s: [fund("2022-06-30", ni=1e11, equity=5e11, cfo=1e11)] for s in bars}
    divs = {s: annual_divs(2018, 2023, 30.0) for s in bars}
    # F 3 known from 2023-05-01, F 4 from 2023-08-01, n/a from 2023-11-01
    bank_f = {"BANK": [(D("2023-05-01"), 3.0), (D("2023-08-01"), 4.0), (D("2023-11-01"), None)],
              "OTHR": []}
    panel = dv.replay_panel(bars, quarters, divs, {"BANK"}, min_mktcap=0, bank_f=bank_f)
    names = {q: sorted(r["symbol"] for r in recs) for q, recs in panel}
    assert names[D("2023-03-31")] == ["BANK", "OTHR"]  # no F knowable yet: n/a, kept
    assert names[D("2023-06-30")] == ["OTHR"]  # F 3
    assert names[D("2023-09-30")] == ["BANK", "OTHR"]  # F 4
    assert names[D("2023-12-31")] == ["BANK", "OTHR"]  # n/a: flagged, not failed
    unfloored = dv.replay_panel(bars, quarters, divs, {"BANK"}, min_mktcap=0)
    assert all("BANK" in [r["symbol"] for r in recs] for _, recs in unfloored)


def test_replay_bank_f_follows_the_flag(monkeypatch):
    from assist.candidates import screens

    data = dv.DividendData(quarters={"BANK": [fund("2022-06-30")]})
    assert dv.replay_bank_f(data, {"BANK"}) == {"BANK": [(D("2022-10-28"), None)]}
    monkeypatch.setattr(screens, "BANK_F_FLOOR_ON", False)
    assert dv.replay_bank_f(data, {"BANK"}) is None


def test_observations_top_and_bottom_quintile_excess():
    recs = [{"symbol": f"S{i}", "expected_pt": float(i), "fwd": i / 100} for i in range(10)]
    feats, rets, spreads = dv.observations([(D("2023-03-31"), recs)], min_pool=10)
    mean = sum(i / 100 for i in range(10)) / 10
    assert feats == [True, False]
    assert rets == pytest.approx([(0.09 + 0.08) / 2 - mean, (0.0 + 0.01) / 2 - mean])
    assert spreads == pytest.approx([0.08])
    assert dv.observations([(D("2023-03-31"), recs)], min_pool=11) == ([], [], [])


def test_evaluate_passes_a_real_edge_and_fails_noise():
    bars, quarters, divs = _universe(signal=True)
    panel = dv.replay_panel(bars, quarters, divs, min_mktcap=0)
    assert len(panel) >= 30
    v = dv.evaluate_replay(panel, min_pool=30, n_shuffles=200, n_controls=5)
    assert v.passed, v.reason
    bars, quarters, divs = _universe(signal=False, seed=7)
    panel = dv.replay_panel(bars, quarters, divs, min_mktcap=0)
    v = dv.evaluate_replay(panel, min_pool=30, n_shuffles=200, n_controls=5)
    assert not v.passed


# ---------------- live ranking and run ----------------


def _hurdle(required=10.0) -> Hurdle:
    return Hurdle("IDN", AS_OF, "IDR", "neutral", required, required, {"ten_year": 6.0})


def _live_row(**kw) -> dict:
    r = {"free_float": 40.0, "med_value_60d": 1e10, "price": 1000.0, "vol_1y": 0.3,
         "days_traded_60": 60, "piotroski": 7, "altman_z": 3.0, "cfo_ttm": 1.0, "der": 0.3,
         "interest_cov": 10.0}
    return {**r, **kw}


def _live_data():
    divs = {"GOOD": annual_divs(2021, 2026, 50.0), "LOW": annual_divs(2021, 2026, 5.0),
            "HOLD": annual_divs(2021, 2026, 50.0), "THIN": annual_divs(2021, 2026, 50.0),
            "BANK": annual_divs(2021, 2026, 50.0)}
    big = [fund("2025-03-31", ni=1e3, equity=5e3, cfo=1e3),
           fund("2026-03-31", ni=1e3, equity=5e3, cfo=1e3)]
    quarters = {s: big for s in divs}
    quarters["BANK"] = [fund("2025-03-31", ni=1e3, equity=5e3, cfo=-1e4),
                        fund("2026-03-31", ni=1e3, equity=5e3, cfo=-1e4)]
    bars = {s: [Bar(AS_OF, 1000.0, 10000.0)] for s in divs}
    return dv.DividendData(bars=bars, quarters=quarters, dividends=divs, shares={},
                           sectors={"HOLD": "Perusahaan Holding & Investasi"}, stale=[])


def test_rank_live_gates_and_margin():
    table = {"GOOD": _live_row(), "LOW": _live_row(), "HOLD": _live_row(),
             "THIN": _live_row(med_value_60d=1.0),
             "BANK": _live_row(car=20.0, npl_gross=2.0, npl_cov=200.0, ldr=80.0, roe=15.0)}
    rows, rejects = dv.rank_live(table, _live_data(), AS_OF, _hurdle(10.0))
    syms = [r["symbol"] for r in rows]
    # GOOD: yield 5% + g = ROE 20% x (1 - 50%) = 10 capped 8 -> 13, margin +3
    assert syms[0] in ("GOOD", "BANK")
    good = next(r for r in rows if r["symbol"] == "GOOD")
    assert good["expected_pt"] == pytest.approx(13.0)
    assert good["margin_pt"] == pytest.approx(3.0)
    assert set(good["legs"]) >= {"yield_pt", "g_pt", "roe_pt", "payout", "own_yield_pct"}
    low = next(r for r in rows if r["symbol"] == "LOW")
    assert low["margin_pt"] == pytest.approx(0.5 + 8.0 - 10.0)
    assert "BANK" in syms  # negative CFO is no gate for a bank on its prudential floor
    assert "HOLD" not in syms and rejects["holding company"] == 1
    assert "THIN" not in syms and rejects["liquidity"] == 1
    assert [r["margin_pt"] for r in rows] == sorted((r["margin_pt"] for r in rows), reverse=True)


def test_run_names_no_candidate_when_the_replay_fails():
    data = _live_data()
    table = {"GOOD": _live_row(), "LOW": _live_row()}
    out = dv.run(data, table, as_of=AS_OF, hurdle=_hurdle(10.0), panel=[],
                 n_shuffles=50, n_controls=2)
    assert out["passed"] is False
    assert out["candidates"] == []
    assert [r["symbol"] for r in out["ranking"]] == ["GOOD", "LOW"]
    assert out["pool"] == 2
    assert out["hurdle_pt"] == 10.0
    assert out["fingerprint"]["g_cap_pt"] == 8.0


def test_run_candidates_need_a_passed_verdict_and_a_positive_margin(monkeypatch):
    from assist.eval.placebo import evaluate

    ok = evaluate(lambda f, _r: list(f), [True, False] * 20,
                  [0.05 + 0.001 * (i % 3) if i % 2 == 0 else -0.05 - 0.001 * (i % 3)
                   for i in range(40)], n_shuffles=50, n_controls=2)
    assert ok.passed
    monkeypatch.setattr(dv, "evaluate_replay", lambda panel, **kw: ok)
    out = dv.run(_live_data(), {"GOOD": _live_row(), "LOW": _live_row()}, as_of=AS_OF,
                 hurdle=_hurdle(10.0), panel=[])
    assert out["passed"] is True
    assert [c["symbol"] for c in out["candidates"]] == ["GOOD"]


def test_run_without_a_hurdle_ranks_by_expected_and_names_no_one():
    out = dv.run(_live_data(), {"GOOD": _live_row(), "LOW": _live_row()}, as_of=AS_OF,
                 hurdle=None, panel=[], n_shuffles=20, n_controls=1)
    assert out["candidates"] == [] and out["hurdle_pt"] is None
    assert [r["symbol"] for r in out["ranking"]] == ["GOOD", "LOW"]
    assert any("hurdle" in s for s in out["stale_inputs"])


# ---------------- loading from the store ----------------


def test_load_reads_the_store_and_adjusts_splits(tmp_path):
    db = tmp_path / DB
    db.parent.mkdir(parents=True)
    make_sqlite(db, (FIX / "stockbiter.sql").read_text())
    data = dv.load(IdxMethodSeries(tmp_path))
    assert data.shares["SPLT"] == {D("2021-06-30"): 20.0, D("2022-06-30"): 100.0}
    assert [r["value"] for r in data.dividends["SPLT"]] == pytest.approx([50.0, 50.0])
    assert data.dividends["PLAIN"][0]["value"] == 20.0
    assert data.sectors["SPLT"] == "Keuangan"
    assert [f.period for f in data.quarters["SPLT"]] == [D("2021-12-31")]  # pull-date echo dropped
    assert data.stale == []


def test_load_without_fundamentals_table_flags_unadjusted(tmp_path):
    db = tmp_path / DB
    db.parent.mkdir(parents=True)
    ddl = (FIX / "stockbiter.sql").read_text()
    make_sqlite(db, ddl)
    import sqlite3

    con = sqlite3.connect(db)
    con.execute("drop table fundamentals")
    con.commit()
    con.close()
    data = dv.load(IdxMethodSeries(tmp_path))
    assert data.dividends["SPLT"][0]["value"] == 250.0
    assert any("split" in s for s in data.stale)


def test_load_missing_store_is_stale_not_a_crash(tmp_path):
    data = dv.load(IdxMethodSeries(tmp_path))
    assert data.bars == {} and data.stale
