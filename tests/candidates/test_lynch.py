"""Lynch categories and ratio (P117, PLAN S100) on hand-built inputs.

Every name: 1e9 adjusted shares (mktcap / price at each period-end bar), yearly quarters at T,
T−4, ..., T−20 (June ends), each known 120 days after its period end; the decision date d is T
+ 120 days, with a bar on d.

Ratio by hand (slow grower SLOW): EPS 100 → 110 over 5 years, g = 1.1^(1/5) − 1 = 1.9245%;
price 1,100 → PE 1,100 / 110 = 10; 55 of dividends in the last year → yield 5%. Lynch ratio =
(1.9245 + 5) / 10 = 0.69245; PEG = 10 / 1.9245 = 5.1962.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from assist.candidates import frameworks as fw
from assist.candidates.frameworks import lynch as ly
from assist.candidates.frameworks.piotroski import shift
from assist.sources.idxmethod_series import Bar, Fundamentals

LAG = timedelta(days=120)
T = date(2025, 6, 30)
D = T + LAG
SH = 1e9


def quarters(eps, *, equity=None, net_debt=0.0):
    """`eps` newest first, one per year back from T (EPS × 1e9 shares = NI TTM)."""
    out = []
    for k, e in enumerate(eps):
        p = shift(T, 4 * k)
        eq = equity if equity is not None else 1e12 * 0.5
        out.append(Fundamentals(p, p + LAG, 1.0, eq, net_debt, e * SH, 1.0, 1.0, 1.0, 1.0, 0.0))
    return sorted(out, key=lambda q: q.period)


def bars(eps, price_now):
    out = [Bar(shift(T, 4 * k), 1000.0, 1000.0 * SH) for k in range(len(eps))]
    return sorted(out) + [Bar(D, price_now, price_now * SH)]


def divs(dps):
    return [{"ex": (D - timedelta(days=100)).isoformat(), "value": dps}] if dps else []


def run(eps, price, dps=0.0, *, industry=None, sector=None, bank=False, d=D, **kw):
    return ly.lynch("XXXX", quarters(eps, **kw), bars(eps, price), divs(dps), d,
                    industry=industry, sector=sector, bank=bank)


SLOW = [110, 108, 106, 104, 102, 100]
STALWART = [161.051, 146.41, 133.1, 121, 110, 100]
FAST = [305.17578125, 244.140625, 195.3125, 156.25, 125, 100]


def test_slow_grower_and_the_ratio_by_hand():
    r = run(SLOW, 1100.0, 55.0)
    assert r.signal == "slow_grower" and r.framework == "lynch"
    assert (r.role, r.gate) == ("context", "untested")
    c = r.components
    assert c["growth_pct"] == pytest.approx(1.92449, abs=1e-4)
    assert c["growth_years"] == 5 and c["declines"] == 0
    assert c["pe"] == pytest.approx(10.0) and c["dividend_yield_pct"] == pytest.approx(5.0)
    assert r.score == pytest.approx(0.69245, abs=1e-4) == c["lynch_ratio"]
    assert c["peg"] == pytest.approx(5.1962, abs=1e-3)
    assert r.as_of == T + LAG


def test_stalwart():
    r = run(STALWART, 1610.51, 32.2102)
    assert r.signal == "stalwart"
    assert r.components["growth_pct"] == pytest.approx(10.0, abs=1e-6)
    assert r.score == pytest.approx((10 + 2) / 10, abs=1e-5)
    assert r.components["peg"] == pytest.approx(1.0, abs=1e-5)


def test_fast_grower():
    r = run(FAST, 305.17578125 * 15)
    assert r.signal == "fast_grower"
    assert r.score == pytest.approx(25 / 15, abs=1e-6)
    assert r.components["peg"] == pytest.approx(0.6, abs=1e-6)


def test_cyclical_by_industry_and_sector_fallback():
    r = run(STALWART, 1610.51, industry={"sector": "Energi", "industry": "Batu Bara",
                                         "sub_industry": "Batu Bara"})
    assert r.signal == "cyclical" and r.components["cyclical_industry"] == 1.0
    assert any("peak" in f for f in r.flags)
    assert r.score == pytest.approx(1.0, abs=1e-5)  # still computed: (10 + 0) / 10
    plant = run(STALWART, 1610.51, industry={"sector": "Barang Konsumen Primer",
                                             "industry": "Produk Makanan Pertanian",
                                             "sub_industry": "Pertanian"})
    assert plant.signal == "cyclical"
    gas = run(STALWART, 1610.51, industry={"sector": "Energi", "industry": "Minyak & Gas",
                                           "sub_industry": "Penyimpanan & Distribusi Migas"})
    assert gas.signal == "stalwart"  # gas distribution is a toll, not a commodity price
    fb = run(STALWART, 1610.51, sector="Energi")
    assert fb.signal == "cyclical" and any("sector only" in f for f in fb.flags)
    other = run(STALWART, 1610.51, sector="Barang Baku")
    assert other.signal == "stalwart" and any("sector only" in f for f in other.flags)


def test_cyclical_by_earnings_pattern():
    r = run([140, 95, 130, 90, 120, 100], 1400.0)
    assert r.signal == "cyclical" and r.components["sharp_declines"] == 2
    assert r.components["cyclical_industry"] == 0.0
    assert any("pattern" in f for f in r.flags)
    mild = run([77.1, 72.9, 64.9, 69.9, 70.9, 60.7], 771.0)  # two small dips: not a cycle
    assert mild.signal == "slow_grower" and mild.components["declines"] == 2
    assert mild.components["sharp_declines"] == 0


def test_turnaround_loss_in_window_and_loss_now():
    r = run([60, 40, 10, -20, 80, 100], 600.0)
    assert r.signal == "turnaround"
    assert r.components["growth_pct"] < 0 and r.components["peg"] is None
    assert r.score is not None  # base year profitable, so the ratio is computed
    now = run([-10, 40, 60, 80, 90, 100], 600.0)
    assert now.signal == "turnaround" and now.score is None
    assert any("PE" in f for f in now.flags)
    base = run([60, 40, 30, 20, 10, -5], 600.0)
    assert base.signal == "turnaround" and base.score is None
    assert any("base" in f for f in base.flags)
    sharp = run([40, 100, 98, 96, 94, 92], 400.0)
    assert sharp.signal == "turnaround"


def test_asset_play_by_book_and_by_net_cash():
    r = run(SLOW, 1100.0, equity=2e12)  # P/B 1.1e12 / 2e12 = 0.55
    assert r.signal == "asset_play" and r.components["pb"] == pytest.approx(0.55)
    cash = run(SLOW, 1100.0, net_debt=-0.6e12)  # net cash 55% of mktcap
    assert cash.signal == "asset_play"
    assert cash.components["net_cash_to_mktcap"] == pytest.approx(0.6 / 1.1)
    bank = run(SLOW, 1100.0, net_debt=-0.6e12, bank=True)
    assert bank.signal == "slow_grower"  # a bank's net debt is not net cash
    cyc = run(STALWART, 1610.51, equity=4e12, industry={"industry": "Batu Bara"})
    assert cyc.signal == "cyclical"  # cyclical comes before asset play


def test_three_years_is_enough_and_two_is_not():
    r = run(SLOW[:4], 1060.0)  # 106 at T ... 100 at T-12
    assert r.signal == "slow_grower" and r.components["growth_years"] == 3
    na = run(SLOW[:3], 1060.0)
    assert na.signal == "n/a" and na.score is None
    assert any("3 years" in f for f in na.flags)


def test_missing_inputs_are_na_with_a_flag():
    assert ly.lynch("XXXX", [], bars(SLOW, 1100.0), [], D).signal == "n/a"
    nobar = ly.lynch("XXXX", quarters(SLOW), [], [], D)
    assert nobar.signal == "n/a" and nobar.flags
    gap = quarters(SLOW)
    del gap[3]  # T-8 missing: only T, T-4 consecutive
    g = ly.lynch("XXXX", gap, bars(SLOW, 1100.0), [], D)
    assert g.signal == "n/a" and g.flags


def test_point_in_time():
    base = run(SLOW, 1100.0, 55.0)
    qs = quarters(SLOW) + [Fundamentals(shift(T, -1), shift(T, -1) + LAG, 1.0, 5e11, 0.0,
                                        999 * SH, 1.0, 1.0, 1.0, 1.0, 0.0)]
    bs = bars(SLOW, 1100.0) + [Bar(D + timedelta(days=5), 50.0, 50.0 * SH)]
    dv = divs(55.0) + [{"ex": (D + timedelta(days=3)).isoformat(), "value": 500.0}]
    later = ly.lynch("XXXX", qs, bs, dv, D)
    assert later.to_dict() == base.to_dict()
    early = ly.lynch("XXXX", quarters(SLOW), bars(SLOW, 1100.0), [], T + timedelta(days=30))
    assert early.as_of == shift(T, 4) + LAG  # T not yet known: T-4 is the newest


def test_registered_and_evaluate():
    assert "lynch" in {f.name for f in fw.registered()}
    inp = ly.LynchBetaInputs(D, {"XXXX": quarters(SLOW)}, bars={"XXXX": bars(SLOW, 1100.0)},
                             dividends={"XXXX": divs(55.0)},
                             industries={"XXXX": {"industry": "Batu Bara"}})
    (r,) = [x for x in fw.evaluate("XXXX", inp) if x.framework == "lynch"]
    assert r.signal == "cyclical"
    (na,) = [x for x in fw.evaluate("XXXX", None) if x.framework == "lynch"]
    assert na.signal == "n/a"


def test_replay_panel_holds_slow_growers_and_stalwarts_only():
    q0, q1 = date(2025, 9, 30), date(2025, 12, 31)
    d0 = q0 - timedelta(days=2)

    def bs(eps, p0, p1):
        b = [x for x in bars(eps, p0) if x.date < D] + [Bar(d0, p0, p0 * SH)]
        return b + [Bar(q1, p1, p1 * SH)]

    big = 1e3  # mktcap = price × 1e9 ≥ 1e12 needs price ≥ 1,000
    data = {"SLOW": (SLOW, 1100.0 * big / 1e3, 1210.0), "STAL": (STALWART, 1610.51, 1610.51),
            "FAST": (FAST, 4577.0, 5000.0), "TINY": (SLOW, 500.0, 600.0)}
    panel = ly.replay_panel(
        {s: bs(e, p0, p1) for s, (e, p0, p1) in data.items()},
        {s: quarters(e) for s, (e, _, _) in data.items()},
        {"SLOW": [{"ex": (q1 - timedelta(days=5)).isoformat(), "value": 11.0}]},
        industries={}, sectors={}, banks=frozenset(), qends=[q0, q1])
    (d, recs), (_, last) = panel
    assert d == q0 and [r["symbol"] for r in recs] == ["SLOW", "STAL"]  # FAST out, TINY < 1T
    slow = recs[0]
    assert slow["category"] == "slow_grower"
    assert slow["fwd"] == pytest.approx((1210 + 11) / 1100 - 1)
    assert all(r["fwd"] is None for r in last)
