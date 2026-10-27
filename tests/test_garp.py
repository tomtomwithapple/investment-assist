"""PLAN S19 (P37): undervalued growth (GARP) screen. Reverse DCF at the P34 IDN hurdle against
realised (5-year `ni_ttm` / `cfo_ttm` CAGR) and consensus EPS growth, quality gates, PEG
cross-check, quarterly placebo replay on realised growth only. Data is built in memory, or from
tests/fixtures/garp/consensus.json (two real entries of idx-method's `data/consensus.json`, read
2026-10-27, plus two made-up edge cases)."""

from __future__ import annotations

import json
import random
import shutil
from datetime import date, timedelta

import pytest
from helpers import FIXTURES

from assist.candidates import garp
from assist.candidates.dividend_value import DividendData
from assist.candidates.hurdle import Hurdle
from assist.sources.idxmethod_series import Bar, Fundamentals, quarter_ends
from assist.sources.idxmethod_stocks import IdxMethodStocks

D = date.fromisoformat
FIX = FIXTURES / "garp"
AS_OF = D("2026-09-30")


def fund(period: str, *, ni=100.0, equity=500.0, cfo=100.0, roce=15.0) -> Fundamentals:
    p = D(period)
    return Fundamentals(p, p + timedelta(days=120), cfo, equity, 0.0, ni, ni, None, roce,
                        None, None)


def growing(last="2026-03-31", years=6, g=0.15, *, ni0=100.0, cfo_ratio=1.0, equity_ratio=5.0,
            roce=15.0) -> list[Fundamentals]:
    """Quarters back from `last`, ni growing at `g` a year, ROE and ROCE flat."""
    qs = quarter_ends(D(last) - timedelta(days=365 * years + 2), D(last))
    out = []
    for q in qs:
        t = (q - qs[0]).days / 365.25
        ni = ni0 * (1 + g) ** t
        out.append(fund(q.isoformat(), ni=ni, cfo=ni * cfo_ratio, equity=ni * equity_ratio,
                        roce=roce))
    return out


def test_config_is_hand_set_and_fingerprinted():
    c = garp.CONFIG
    assert c["years"] == 10 and c["cagr_years"] == 5 and c["quality_years"] == 3
    assert c["gdp_pt"] == 8.0
    assert c["min_cfo_ni"] == 0.8 and c["max_dilution"] == 0.05


# ---------------- reverse DCF ----------------


def test_implied_growth_closed_form():
    # payout 0, g = r: (1+g)^10/(1+r)^10 = 1, so mktcap = E0 (1 + gT) / (r - gT) = 21.6 E0
    assert garp.implied_growth(21.6, 1.0, 0.0, 13.0) == pytest.approx(13.0, abs=1e-4)
    # with full payout every year adds E0 (1+g)^t / (1+r)^t = E0 at g = r
    assert garp.implied_growth(31.6, 1.0, 1.0, 13.0) == pytest.approx(13.0, abs=1e-4)


def test_implied_growth_rises_with_price_and_needs_earnings_and_a_spread():
    lo = garp.implied_growth(10.0, 1.0, 0.3, 13.0)
    hi = garp.implied_growth(40.0, 1.0, 0.3, 13.0)
    assert lo < hi
    assert garp.implied_growth(10.0, -1.0, 0.3, 13.0) is None  # a loss implies nothing
    assert garp.implied_growth(10.0, 1.0, 0.3, None) is None  # no hurdle
    assert garp.implied_growth(10.0, 1.0, 0.3, 8.5) is None  # hurdle too near nominal GDP
    # out of range: clamped to the search bounds
    assert garp.implied_growth(1e-6, 1.0, 0.0, 13.0) == pytest.approx(
        100 * garp.CONFIG["g_bounds"][0])


def test_pv_matches_the_sum():
    r, gT, g, p = 0.13, 0.08, 0.10, 0.4
    want = sum(p * (1 + g) ** t / (1 + r) ** t for t in range(1, 11))
    want += (1 + g) ** 10 * (1 + gT) / (r - gT) / (1 + r) ** 10
    assert garp.pv(1.0, p, g, r) == pytest.approx(want)


def test_implied_return_inverts_the_dcf():
    assert garp.implied_return(21.6, 1.0, 0.0, 13.0) == pytest.approx(13.0, abs=1e-4)
    mc = garp.pv(1.0, 0.3, 0.12, 0.15)
    assert garp.implied_return(mc, 1.0, 0.3, 12.0) == pytest.approx(15.0, abs=1e-4)
    assert garp.implied_return(mc, -1.0, 0.3, 12.0) is None


# ---------------- growth legs ----------------


def test_cagr_needs_positive_ends():
    assert garp.cagr(100.0, 200.0, 5) == pytest.approx(100 * (2 ** 0.2 - 1))
    assert garp.cagr(-1.0, 200.0, 5) is None
    assert garp.cagr(100.0, 0.0, 5) is None
    assert garp.cagr(None, 200.0, 5) is None


def test_realised_growth_from_quarters_five_years_apart():
    qs = growing(g=0.15)
    ni, cfo = garp.realised_growth(qs)
    assert ni == pytest.approx(15.0, abs=0.05)
    assert cfo == pytest.approx(15.0, abs=0.05)
    assert garp.realised_growth(qs[-12:]) == (None, None)  # 3 years: not enough history


def test_consensus_growth_forward_pe_and_peg_from_the_real_shape():
    cons = json.loads((FIX / "consensus.json").read_text())
    c = garp.consensus_growth(cons["AADI"])
    # EPS 2025 actual 1608.59 -> 2027 estimate 2008.00, two years
    assert c["growth_pt"] == pytest.approx(100 * ((2008.0 / 1608.59) ** 0.5 - 1))
    assert c["fwd_eps"] == 2284.18
    assert c["fwd_pe"] == pytest.approx(11525 / 2284.18)
    assert c["peg"] == pytest.approx(c["fwd_pe"] / c["growth_pt"])
    assert garp.consensus_growth(cons["NOEP"]) is None
    loss = garp.consensus_growth(cons["LOSS"])
    assert loss["growth_pt"] is None and loss["peg"] is None
    assert loss["fwd_pe"] == pytest.approx(200.0)
    assert garp.consensus_growth(None) is None


def test_consensus_is_read_through_the_stocks_adapter(tmp_path):
    (tmp_path / "data").mkdir()
    shutil.copy(FIX / "consensus.json", tmp_path / "data" / "consensus.json")
    cons = IdxMethodStocks(tmp_path).consensus()
    assert set(cons) == {"AADI", "ACES", "NOEP", "LOSS"}
    assert garp.consensus_growth(cons["ACES"])["growth_pt"] > 0


# ---------------- assess: legs and quality gates ----------------


def bars_flat(shares=10.0, price=1000.0, start="2019-03-29", end="2026-09-30"):
    return [Bar(q, price, price * shares) for q in quarter_ends(D(start), D(end))]


def test_assess_legs_and_gap():
    qs = growing(g=0.15)  # ni at 2026-03-31 ~ 100 * 1.15^6
    ni = qs[-1].ni_ttm
    bars = bars_flat(shares=10.0, price=ni)  # mktcap = 10 x earnings: cheap
    a = garp.assess(AS_OF, bars, qs, [], hurdle_pt=13.0)
    assert a.ok, a.reasons
    assert a.period == D("2026-03-31")
    assert a.payout == 0.0
    assert a.implied_pt == pytest.approx(garp.implied_growth(10 * ni, ni, 0.0, 13.0))
    assert a.realised_pt == pytest.approx(15.0, abs=0.05)
    assert a.consensus_pt is None
    assert a.gap_pt == pytest.approx(a.realised_pt - a.implied_pt)
    assert a.realised_gap_pt == a.gap_pt
    assert a.expected_pt > 13.0  # realised beats implied, so the IRR beats the hurdle
    assert a.cfo_ni == pytest.approx(1.0)
    assert a.dilution_pt == pytest.approx(0.0)


def test_assess_gap_takes_the_lower_of_realised_and_consensus():
    qs = growing(g=0.15)
    bars = bars_flat(price=qs[-1].ni_ttm)
    low = garp.assess(AS_OF, bars, qs, [], hurdle_pt=13.0,
                      consensus={"growth_pt": 5.0, "fwd_pe": 9.0, "peg": 1.8, "fwd_eps": 1.0})
    assert low.consensus_pt == 5.0 and low.peg == 1.8
    assert low.gap_pt == pytest.approx(5.0 - low.implied_pt)
    assert low.realised_gap_pt == pytest.approx(low.realised_pt - low.implied_pt)
    high = garp.assess(AS_OF, bars, qs, [], hurdle_pt=13.0, consensus={"growth_pt": 40.0})
    assert high.gap_pt == pytest.approx(high.realised_gap_pt)


def test_assess_payout_from_dividends():
    qs = growing(g=0.15)
    ni = qs[-1].ni_ttm
    bars = bars_flat(shares=10.0, price=ni)
    divs = [{"ex": "2026-05-10", "value": 0.4 * ni / 10, "ccy": "CURRENCY_IDR"}]
    a = garp.assess(AS_OF, bars, qs, divs, hurdle_pt=13.0)
    assert a.payout == pytest.approx(0.4)


def test_gate_returns_trend_roe_or_roce():
    qs = growing(g=0.15)
    # ROE falls (equity grows faster than ni) but ROCE is flat: passes on ROCE
    fall_roe = [f._replace(equity=f.equity * (1.3 ** (f.period.year - 2020))) for f in qs]
    bars = bars_flat(price=qs[-1].ni_ttm)
    assert garp.assess(AS_OF, bars, fall_roe, [], hurdle_pt=13.0).ok
    both = [f._replace(roce=30.0 - 2 * (f.period.year - 2020)) for f in fall_roe]
    a = garp.assess(AS_OF, bars, both, [], hurdle_pt=13.0)
    assert not a.ok and "returns trend" in a.failed


def test_gate_accruals_unless_bank():
    qs = growing(g=0.15, cfo_ratio=0.5)
    bars = bars_flat(price=qs[-1].ni_ttm)
    a = garp.assess(AS_OF, bars, qs, [], hurdle_pt=13.0)
    assert not a.ok and "accruals" in a.failed
    b = garp.assess(AS_OF, bars, qs, [], hurdle_pt=13.0, bank=True)
    assert b.ok, b.reasons
    assert b.realised_pt == pytest.approx(b.ni_cagr_pt)  # a bank's CFO is not a growth leg


def test_gate_dilution_from_the_share_count_proxy():
    qs = growing(g=0.15)
    p = qs[-1].ni_ttm
    # share proxy (mktcap / price) up 10% a year over the last 3 years
    bars = [Bar(q, p, p * 10 * 1.1 ** ((q - D("2023-09-30")).days / 365.25))
            for q in quarter_ends(D("2019-03-29"), AS_OF)]
    a = garp.assess(AS_OF, bars, qs, [], hurdle_pt=13.0)
    assert a.dilution_pt == pytest.approx(10.0, abs=0.1)
    assert not a.ok and "dilution" in a.failed


def test_gate_needs_realised_growth_with_both_ends_positive():
    qs = growing(g=0.15)
    qs[0] = qs[0]._replace(cfo_ttm=-5.0)
    # the quarter 5 years before the latest has negative CFO
    first = next(i for i, f in enumerate(qs) if f.period == D("2021-03-31"))
    qs[first] = qs[first]._replace(cfo_ttm=-5.0)
    a = garp.assess(AS_OF, bars_flat(price=qs[-1].ni_ttm), qs, [], hurdle_pt=13.0)
    assert a.cfo_cagr_pt is None and not a.ok and "realised growth" in a.failed


def test_assess_is_point_in_time_and_needs_a_bar():
    qs = [*growing(g=0.15), fund("2026-06-30", ni=-1e6)]  # not available until 2026-10-28
    a = garp.assess(AS_OF, bars_flat(price=100.0), qs, [], hurdle_pt=13.0)
    assert a.period == D("2026-03-31")
    assert garp.assess(D("2010-01-01"), bars_flat(), qs, [], hurdle_pt=13.0) is None
    loss = [*growing(g=0.15)[:-1], fund("2026-03-31", ni=-5.0)]
    b = garp.assess(AS_OF, bars_flat(), loss, [], hurdle_pt=13.0)
    assert not b.ok and b.failed[0] == "no earnings" and b.implied_pt is None


# ---------------- replay ----------------


def _universe(n=50, end="2026-06-30", seed=1, signal=True):
    """n names with 15%-a-year earnings growth and a fixed PE from 6 to 30, so the gap falls
    with the PE. Price is mktcap / 1e9 times a walk `m` (the share-count proxy shrinks as `m`
    rises, like a buyback). With `signal`, a cheaper name's walk drifts up faster, so a bigger gap
    earns more the next quarter; otherwise the walk is noise."""
    rng = random.Random(seed)
    qes = quarter_ends(D("2016-12-31"), D(end))
    bars, quarters = {}, {}
    for i in range(n):
        sym = f"S{i:02d}"
        pe = 6 + 24 * i / (n - 1)

        def grow(q):
            return 1.15 ** ((q - qes[0]).days / 365.25)

        qs = [fund(q.isoformat(), ni=1e11 * grow(q), cfo=1e11 * grow(q), equity=5e11 * grow(q))
              for q in qes]
        quarters[sym] = qs
        b, m = [], 1.0
        for q in qes:
            known = [f for f in qs if f.available <= q]
            mc = pe * (known[-1].ni_ttm if known else qs[0].ni_ttm)
            b.append(Bar(q, mc / 1e9 * m, mc))
            m *= 1 + (0.0008 * (n - i) if signal else 0.0) + rng.gauss(0, 0.01)
        bars[sym] = b
    return bars, quarters


def test_replay_panel_point_in_time_and_forward_return():
    qs = growing(last="2023-06-30", g=0.15)
    bars = {"A": [Bar(D("2023-12-29"), 1000.0, 1e3 * qs[-2].ni_ttm),
                  Bar(D("2024-03-31"), 1100.0, 1.1e3 * qs[-2].ni_ttm)]}
    panel = garp.replay_panel(bars, {"A": qs}, {}, hurdle_pt=13.0, min_mktcap=0)
    by = dict(panel)
    rec = by[D("2023-12-31")][0]
    assert rec["fwd"] == pytest.approx(1100 / 1000 - 1)
    # realised growth only: the record carries no consensus
    assert set(rec) == {"symbol", "gap_pt", "fwd"}
    assert D("2024-03-31") not in by


def test_replay_panel_applies_quality_and_size_floor():
    qs = growing(last="2023-06-30", g=0.15, cfo_ratio=0.5)
    bars = {"A": [Bar(D("2023-12-29"), 1000.0, 1e12), Bar(D("2024-03-31"), 1000.0, 1e12)]}
    assert garp.replay_panel(bars, {"A": qs}, {}, hurdle_pt=13.0, min_mktcap=0) == [
        (D("2023-12-31"), [])]
    ok = growing(last="2023-06-30", g=0.15)
    assert garp.replay_panel(bars, {"A": ok}, {}, hurdle_pt=13.0, min_mktcap=2e12) == [
        (D("2023-12-31"), [])]


def test_observations_rank_on_gap():
    recs = [{"symbol": f"S{i}", "gap_pt": float(i), "fwd": i / 100} for i in range(10)]
    feats, rets, spreads = garp.observations([(D("2023-03-31"), recs)], min_pool=10)
    mean = sum(i / 100 for i in range(10)) / 10
    assert feats == [True, False]
    assert rets == pytest.approx([0.085 - mean, 0.005 - mean])
    assert spreads == pytest.approx([0.08])
    assert garp.observations([(D("2023-03-31"), recs)], min_pool=11) == ([], [], [])


def test_evaluate_passes_a_real_edge_and_fails_noise():
    bars, quarters = _universe(signal=True)
    panel = garp.replay_panel(bars, quarters, {}, hurdle_pt=13.0, min_mktcap=0)
    scored = [q for q, recs in panel if len(recs) >= 30]
    assert len(scored) >= 15
    v = garp.evaluate_replay(panel, min_pool=30, n_shuffles=200, n_controls=5)
    assert v.passed, v.reason
    bars, quarters = _universe(signal=False, seed=7)
    panel = garp.replay_panel(bars, quarters, {}, hurdle_pt=13.0, min_mktcap=0)
    v = garp.evaluate_replay(panel, min_pool=30, n_shuffles=200, n_controls=5)
    assert not v.passed


# ---------------- live ranking and run ----------------


def _hurdle(required=13.0) -> Hurdle:
    return Hurdle("IDN", AS_OF, "IDR", "neutral", required, required, {"ten_year": 6.5})


def _live_row(**kw) -> dict:
    r = {"free_float": 40.0, "med_value_60d": 1e10, "price": 1000.0, "vol_1y": 0.3,
         "days_traded_60": 60, "piotroski": 7, "altman_z": 3.0, "cfo_ttm": 1.0, "der": 0.3,
         "interest_cov": 10.0}
    return {**r, **kw}


def _live_data():
    qs = growing(g=0.15)
    ni = qs[-1].ni_ttm
    pe = {"CHEAP": 8.0, "DEAR": 40.0, "THIN": 8.0, "FADE": 8.0}
    bars = {s: bars_flat(shares=10.0, price=p * ni / 10) for s, p in pe.items()}
    quarters = {s: qs for s in pe}
    quarters["FADE"] = growing(g=0.15, cfo_ratio=0.3)
    return DividendData(bars=bars, quarters=quarters, dividends={}, shares={},
                        sectors={"CHEAP": "Teknologi"}, stale=[])


def test_rank_live_gates_and_gap():
    table = {s: _live_row() for s in ("CHEAP", "DEAR", "FADE")}
    table["THIN"] = _live_row(med_value_60d=1.0)
    cons = {"CHEAP": {"growth_pt": 12.0, "fwd_pe": 7.0, "peg": 0.58, "fwd_eps": 1.0}}
    rows, rejects = garp.rank_live(table, _live_data(), AS_OF, _hurdle(), consensus=cons)
    assert [r["symbol"] for r in rows] == ["CHEAP", "DEAR"]
    cheap = rows[0]
    assert cheap["gap_pt"] == pytest.approx(12.0 - cheap["legs"]["implied_pt"])
    assert cheap["legs"]["consensus_pt"] == 12.0 and cheap["legs"]["peg"] == 0.58
    assert cheap["realised_gap_pt"] > cheap["gap_pt"]
    assert cheap["margin_pt"] == pytest.approx(cheap["expected_pt"] - 13.0)
    assert rows[1]["gap_pt"] < 0 and rows[1]["margin_pt"] < 0
    assert rejects["liquidity"] == 1 and rejects["accruals"] == 1


def test_run_names_no_candidate_when_the_replay_fails():
    table = {s: _live_row() for s in ("CHEAP", "DEAR")}
    out = garp.run(_live_data(), table, as_of=AS_OF, hurdle=_hurdle(), consensus={}, panel=[],
                   n_shuffles=50, n_controls=2)
    assert out["screen"] == "garp"
    assert out["passed"] is False and out["candidates"] == []
    assert [r["symbol"] for r in out["ranking"]] == ["CHEAP", "DEAR"]
    assert out["pool"] == 2 and out["hurdle_pt"] == 13.0
    assert out["replay_basis"] == "realised growth only"
    assert out["fingerprint"]["cagr_years"] == 5
    assert any("consensus" in s for s in out["stale_inputs"])  # none for CHEAP or DEAR


def test_run_candidates_need_a_passed_verdict_and_a_clear_gap(monkeypatch):
    from assist.eval.placebo import evaluate

    ok = evaluate(lambda f, _r: list(f), [True, False] * 20,
                  [0.05 + 0.001 * (i % 3) if i % 2 == 0 else -0.05 - 0.001 * (i % 3)
                   for i in range(40)], n_shuffles=50, n_controls=2)
    assert ok.passed
    monkeypatch.setattr(garp, "evaluate_replay", lambda panel, **kw: ok)
    table = {s: _live_row() for s in ("CHEAP", "DEAR")}
    cons = {"CHEAP": {"growth_pt": 12.0}, "DEAR": {"growth_pt": 30.0}}
    out = garp.run(_live_data(), table, as_of=AS_OF, hurdle=_hurdle(), consensus=cons, panel=[])
    assert out["passed"] is True
    assert [c["symbol"] for c in out["candidates"]] == ["CHEAP"]
    assert out["consensus_names"] == 2


def test_run_without_a_hurdle_ranks_nothing_and_names_no_one():
    table = {s: _live_row() for s in ("CHEAP", "DEAR")}
    out = garp.run(_live_data(), table, as_of=AS_OF, hurdle=None, consensus={}, panel=[],
                   n_shuffles=20, n_controls=1)
    assert out["candidates"] == [] and out["hurdle_pt"] is None
    assert any("hurdle" in s for s in out["stale_inputs"])
