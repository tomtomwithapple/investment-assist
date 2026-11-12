"""GP/A and DuPont (P116, PLAN S99) on hand-computed tables.

T = 2025-06-30, knowable on T + 120 days (SEEN). Every name has `factor_series` quarters from
2024-03-31 to T; the quarters before T carry the year-before (t4) balance sheet, T the current.

Company CCCC (sector "Barang Baku"): total assets 2,000 at T, 1,800 before → average 1,900;
equity 600 at T, 400 before → average 500; NI TTM 120.
Discrete quarters 2024Q3..2025Q2: revenue 400 + 450 + 500 + 550 = 1,900; gross profit 100 + 110
+ 120 + 170 = 500; pretax 4 × 40 = 160; operating 4 × 50 = 200.

    GP/A      = 500 / 2,000                       = 0.25
    ROE       = 120 / 500                         = 0.24
    3-step    = (120/1,900) × (1,900/1,900) × (1,900/500) = 0.0631579 × 1 × 3.8 = 0.24
    5-step    = (120/160) × (160/200) × (200/1,900) × 1 × 3.8
              = 0.75 × 0.8 × 0.1052632 × 1 × 3.8 = 0.24
    ROA       = 120 / 1,900 = 0.0631579

Peers in "Barang Baku" (multipliers avg TA / avg E): PPP1 1.5, PPP2 2.0, PPP3 2.5, PPP4 3.0,
CCCC 3.8, DDDD 6.0 → median (2.5 + 3.0) / 2 = 2.75. r = 12%.

    CCCC: ROE 0.24 > r; ROA × 2.75 = 0.17368 >= r → not leverage-driven ("operating")
    DDDD: ROA 0.03, M 6 → ROE 0.18 > r; ROA × 2.75 = 0.0825 < r → leverage-driven,
          sustainable ROE 0.0825
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from assist.candidates import frameworks as fw
from assist.candidates.frameworks import quality as qm
from assist.candidates.frameworks import residual_income as ri
from assist.sources.idxmethod_series import Bar, Fundamentals

LAG = timedelta(days=120)
T, T4 = date(2025, 6, 30), date(2024, 6, 30)
SEEN = T + LAG
R_PT = 12.0
PERIODS = [date(2024, 3, 31), T4, date(2024, 9, 30), date(2024, 12, 31), date(2025, 3, 31), T]
SECTOR = "Barang Baku"


def q(period, equity, ni, ta):
    return Fundamentals(period, period + LAG, 1.0, equity, 0.0, ni, 1.0, 1.0, 1.0, ta, 0.0)


def firm(ni, eq_t, eq_t4, ta_t, ta_t4):
    return [q(p, eq_t if p == T else eq_t4, ni, ta_t if p == T else ta_t4) for p in PERIODS]


def statements(rev=(400, 450, 500, 550), gp=(100, 110, 120, 170), pretax=(40,) * 4,
               op=(50,) * 4, early=None):
    """2024Q3..2025Q2 from the tuples; 2023Q3..2024Q2 all `early` (default: the same
    quarter values shifted a year, so the year before is computable too)."""
    out = {}
    four = [date(2024, 9, 30), date(2024, 12, 31), date(2025, 3, 31), T]
    prev = [date(2023, 9, 30), date(2023, 12, 31), date(2024, 3, 31), T4]
    for i, p in enumerate(four):
        row = {}
        for k, v in (("revenue", rev), ("gross_profit", gp), ("pretax_profit", pretax),
                     ("operating_profit", op)):
            if v is not None and v[i] is not None:
                row[k] = float(v[i])
        out[p] = row
    for p in prev:
        out[p] = dict(early) if early is not None else {
            "revenue": 400.0, "gross_profit": 100.0, "pretax_profit": 40.0,
            "operating_profit": 50.0}
    return out


C = firm(120.0, 600.0, 400.0, 2000.0, 1800.0)
D = firm(0.03 * 1000.0, 1000.0 / 6, 1000.0 / 6, 1000.0, 1000.0)  # ROA 3%, M 6
PEERS = {f"PPP{i}": firm(10.0, 100.0, 100.0, 100.0 * m, 100.0 * m)
         for i, m in enumerate((1.5, 2.0, 2.5, 3.0), start=1)}


def inputs(d=SEEN, *, quarters=None, stmts=None, banks=frozenset(), sectors=None,
           required_pt=R_PT):
    quarters = quarters if quarters is not None else {"CCCC": C, "DDDD": D, **PEERS}
    stmts = stmts if stmts is not None else {s: statements() for s in quarters}
    sectors = sectors if sectors is not None else dict.fromkeys(quarters, SECTOR)
    return qm.QualityInputs(d, quarters, stmts, frozenset(banks), required_pt=required_pt,
                            sectors=sectors)


# ---------------- GP/A ----------------


def test_gpa_by_hand():
    res = qm.GrossProfitability().evaluate("CCCC", inputs())
    assert res.framework == "gp_a" and res.role == "context" and res.gate == "untested"
    assert res.score == pytest.approx(0.25)
    c = res.components
    assert c["gross_profit_ttm"] == pytest.approx(500.0)
    assert c["total_assets"] == pytest.approx(2000.0)
    assert c["gross_margin"] == pytest.approx(500 / 1900)
    assert res.as_of == SEEN


def test_gpa_signal_is_the_cross_sectional_fifth():
    # PPPk: gross profit 500 a year over 100·m assets → GP/A 3.33, 2.5, 2.0, 1.67; CCCC 0.25;
    # DDDD 500 / 1,000 = 0.5. Six names: the top fifth (6 // 5 = 1 name) is PPP1, the
    # bottom fifth CCCC.
    inp = inputs()
    sig = {s: qm.GrossProfitability().evaluate(s, inp) for s in ("PPP1", "PPP3", "CCCC")}
    assert sig["PPP1"].signal == "high"
    assert sig["PPP3"].signal == "middle"
    assert sig["CCCC"].signal == "low"
    assert sig["CCCC"].components["n_cross"] == 6.0


def test_gpa_point_in_time_reads_only_the_quarter_knowable():
    # a day before SEEN the newest quarter is 2025-03-31: TA 1,800, GP 2024Q2..2025Q1
    # = 100 + 100 + 110 + 120 = 430 → 0.238889; 2025Q2's 170 is not read
    res = qm.GrossProfitability().evaluate("CCCC", inputs(SEEN - timedelta(days=1)))
    assert res.score == pytest.approx(430 / 1800)
    assert res.as_of == date(2025, 3, 31) + LAG


def test_gpa_bank_and_financial_are_na_with_a_flag():
    inp = inputs(banks={"CCCC"}, sectors={"CCCC": SECTOR, "DDDD": "Keuangan"})
    bank = qm.GrossProfitability().evaluate("CCCC", inp)
    fin = qm.GrossProfitability().evaluate("DDDD", inp)
    assert bank.score is None and bank.signal == "n/a"
    assert any("bank" in f for f in bank.flags)
    assert fin.score is None and any("financial" in f for f in fin.flags)


def test_usd_reporter_flows_are_converted_at_the_stores_rate():
    # ADRO-style: flows as reported in USD, `equity` in IDR, `equity_raw` in USD; at 16,000
    # IDR a USD the IDR flows are the same as CCCC's, so GP/A and the 5-step are unchanged
    st = statements(rev=[v / 16000 for v in (400, 450, 500, 550)],
                    gp=[v / 16000 for v in (100, 110, 120, 170)], pretax=(40 / 16000,) * 4,
                    op=(50 / 16000,) * 4)
    for row in st.values():
        row |= {"equity": 600.0, "equity_raw": 600.0 / 16000}
    inp = inputs(stmts={"CCCC": st})
    g = qm.GrossProfitability().evaluate("CCCC", inp)
    assert g.score == pytest.approx(0.25)
    assert g.components["fx_rate"] == pytest.approx(16000)
    assert any("foreign currency" in f for f in g.flags)
    d = qm.DuPont().evaluate("CCCC", inp)
    assert d.components["tax_burden"] == pytest.approx(0.75)
    assert d.components["net_margin"] == pytest.approx(120 / 1900)
    # an IDR reporter (equity = equity_raw) is not flagged; no equity_raw is "unchecked"
    idr = statements()
    for row in idr.values():
        row |= {"equity": 600.0, "equity_raw": 600.0}
    g = qm.GrossProfitability().evaluate("CCCC", inputs(stmts={"CCCC": idr}))
    assert g.components["fx_rate"] == 1.0 and not g.flags
    g = qm.GrossProfitability().evaluate("CCCC", inputs())
    assert any("unchecked" in f for f in g.flags)


def test_gpa_missing_items_are_na_never_imputed():
    st = statements(gp=(100, None, 120, 170))
    res = qm.GrossProfitability().evaluate("CCCC", inputs(stmts={"CCCC": st}))
    assert res.score is None and any("gross profit" in f for f in res.flags)
    none_ta = {"CCCC": [q(p, 600.0, 120.0, None) for p in PERIODS]}
    res = qm.GrossProfitability().evaluate("CCCC", inputs(quarters=none_ta))
    assert res.score is None and any("total assets" in f for f in res.flags)
    res = qm.GrossProfitability().evaluate("CCCC", inputs(SEEN - timedelta(days=600)))
    assert res.score is None and res.as_of is None


# ---------------- DuPont ----------------


def test_dupont_three_and_five_step_identities():
    res = qm.DuPont().evaluate("CCCC", inputs())
    c = res.components
    assert res.framework == "dupont" and res.role == "context"
    assert res.score == pytest.approx(0.24)
    assert c["net_margin"] == pytest.approx(120 / 1900)
    assert c["asset_turnover"] == pytest.approx(1.0)
    assert c["equity_multiplier"] == pytest.approx(3.8)
    assert c["net_margin"] * c["asset_turnover"] * c["equity_multiplier"] == pytest.approx(
        c["roe"])
    assert c["tax_burden"] == pytest.approx(0.75)
    assert c["interest_burden"] == pytest.approx(0.8)
    assert c["ebit_margin"] == pytest.approx(200 / 1900)
    five = (c["tax_burden"] * c["interest_burden"] * c["ebit_margin"] * c["asset_turnover"]
            * c["equity_multiplier"])
    assert five == pytest.approx(c["roe"]) == pytest.approx(0.24)
    assert c["roa"] == pytest.approx(120 / 1900)


def test_dupont_roe_matches_bank_ri_roe0():
    # the same NI TTM over the same average equity as S96's ROE0
    res = qm.DuPont().evaluate("CCCC", inputs())
    assert res.components["roe"] == pytest.approx(120 / ((600 + 400) / 2))


def test_leverage_flag_both_ways():
    inp = inputs()
    c = qm.DuPont().evaluate("CCCC", inp)
    d = qm.DuPont().evaluate("DDDD", inp)
    assert c.components["peer_median_multiplier"] == pytest.approx(2.75)
    assert c.components["n_peers"] == 6.0
    assert c.components["leverage_driven"] == 0.0 and c.signal == "operating"
    assert c.components["roe_ex_leverage"] == pytest.approx(120 / 1900 * 2.75)
    assert c.components["sustainable_roe"] == pytest.approx(0.24)
    assert d.score == pytest.approx(0.18)
    assert d.components["leverage_driven"] == 1.0 and d.signal == "leverage-driven"
    assert d.components["roe_ex_leverage"] == pytest.approx(0.0825)
    assert d.components["sustainable_roe"] == pytest.approx(0.0825)
    assert any("leverage-driven" in f for f in d.flags)
    assert qm.sustainable_roe("DDDD", inp) == pytest.approx(0.0825)
    assert qm.sustainable_roe("CCCC", inp) == pytest.approx(0.24)


def test_roe_below_the_hurdle_is_not_leverage_driven():
    lo = firm(10.0, 100.0, 100.0, 1000.0, 1000.0)  # ROA 1%, M 10, ROE 10% < 12%
    inp = inputs(quarters={"LLLL": lo, **PEERS, "CCCC": C})
    res = qm.DuPont().evaluate("LLLL", inp)
    assert res.score == pytest.approx(0.10)
    assert res.components["leverage_driven"] == 0.0 and res.signal == "below hurdle"


def test_no_hurdle_leaves_the_flag_uncomputed_and_flagged():
    res = qm.DuPont().evaluate("DDDD", inputs(required_pt=None))
    assert res.score == pytest.approx(0.18) and res.signal == "unrated"
    assert res.components["leverage_driven"] is None
    assert any("hurdle" in f for f in res.flags)
    assert res.components["sustainable_roe"] is None


def test_thin_sector_falls_back_to_the_market_median_flagged():
    sectors = {"CCCC": "Teknologi", "DDDD": SECTOR, **dict.fromkeys(PEERS, SECTOR)}
    res = qm.DuPont().evaluate("CCCC", inputs(sectors=sectors))
    assert res.components["peer_median_multiplier"] == pytest.approx(2.75)  # all six names
    assert any("market median" in f for f in res.flags)


def test_bank_gets_the_three_step_only_against_bank_peers():
    banks = {f"BNK{i}": firm(20.0, 100.0, 100.0, 100.0 * m, 100.0 * m)
             for i, m in enumerate((5.0, 6.0, 7.0, 8.0, 9.0))}
    quarters = {**banks, **PEERS}
    inp = inputs(quarters=quarters, banks=set(banks))
    res = qm.DuPont().evaluate("BNK4", inp)  # ROA 20/900 = 2.22%, M 9, ROE 20%
    c = res.components
    assert res.score == pytest.approx(0.20)
    assert "tax_burden" not in c and "interest_burden" not in c
    assert c["net_margin"] * c["asset_turnover"] * c["equity_multiplier"] == pytest.approx(0.2)
    assert c["peer_median_multiplier"] == pytest.approx(7.0)  # banks only, not PEERS
    assert any("bank" in f and "3-step" in f for f in res.flags)
    # ROA × 7 = 15.6% >= 12%: the bank's ROE is not leverage-driven
    assert c["leverage_driven"] == 0.0


def test_five_step_missing_or_negative_is_flagged_three_step_stays():
    res = qm.DuPont().evaluate("CCCC", inputs(stmts={"CCCC": statements(pretax=None)}))
    assert res.score == pytest.approx(0.24) and "tax_burden" not in res.components
    assert any("5-step" in f for f in res.flags)
    res = qm.DuPont().evaluate("CCCC", inputs(stmts={"CCCC": statements(op=(-10,) * 4)}))
    assert "interest_burden" not in res.components
    assert any("5-step" in f for f in res.flags)


def test_ebt_above_ebit_is_flagged():
    res = qm.DuPont().evaluate("CCCC", inputs(stmts={"CCCC": statements(pretax=(60,) * 4)}))
    assert res.components["interest_burden"] == pytest.approx(1.2)
    assert any("EBT above EBIT" in f for f in res.flags)


def test_dupont_missing_revenue_or_equity_is_na():
    res = qm.DuPont().evaluate("CCCC", inputs(stmts={"CCCC": statements(rev=None)}))
    assert res.score is None and res.signal == "n/a"
    assert any("revenue" in f for f in res.flags)
    assert res.components["roe"] == pytest.approx(0.24)  # kept for audit, not scored
    neg = {"CCCC": firm(120.0, -5.0, -5.0, 2000.0, 1800.0)}
    res = qm.DuPont().evaluate("CCCC", inputs(quarters=neg))
    assert res.score is None and any("equity" in f for f in res.flags)


def test_dupont_point_in_time_and_attribution():
    early = qm.DuPont().evaluate("CCCC", inputs(SEEN - timedelta(days=1)))
    # t = 2025-03-31: equity 400 both ends, TA 1,800 → ROE 120 / 400 = 0.30
    assert early.score == pytest.approx(0.30)
    res = qm.DuPont().evaluate("CCCC", inputs())
    c = res.components
    # the year before (t4 = 2024-06-30, t8 has no quarter): no attribution, flagged
    assert "dln_roe" not in c and any("attribution" in f for f in res.flags)


def test_attribution_sums_to_the_log_change_in_roe():
    eight = [date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30), date(2023, 12, 31)]
    old = [q(p, 400.0, 80.0, 1800.0) for p in eight]  # t8 balance sheet
    qs = {"CCCC": old + [q(p, 400.0, 80.0 if p <= T4 else 120.0, 1800.0 if p != T else 2000.0)
                         if p != T else q(T, 600.0, 120.0, 2000.0) for p in PERIODS]}
    res = qm.DuPont().evaluate("CCCC", inputs(quarters=qs, stmts={"CCCC": statements()}))
    c = res.components
    # year before: NI 80, avg E 400, avg TA 1,800, revenue 1,600 → ROE 0.20
    assert c["roe_prior"] == pytest.approx(0.20)
    assert c["dln_roe"] == pytest.approx(math.log(0.24 / 0.20))
    assert (c["dln_net_margin"] + c["dln_asset_turnover"] + c["dln_equity_multiplier"]
            == pytest.approx(c["dln_roe"]))


# ---------------- feeding S96 ----------------


def test_bank_ri_switch_defaults_to_ttm_roe(monkeypatch):
    assert ri.CONFIG["roe_source"] == "ttm"
    lev = firm(18.0, 100.0, 100.0, 1000.0, 1000.0)  # ROA 1.8%, M 10, ROE 18%
    banks = {"LEVB": lev, **{f"BNK{i}": firm(20.0, 100.0, 100.0, 100.0 * m, 100.0 * m)
                             for i, m in enumerate((5.0, 6.0, 7.0, 8.0))}}
    bars = {s: [Bar(SEEN, 1000.0, 1000.0 * 1e9)] for s in banks}
    inp = qm.QualityInputs(SEEN, banks, {}, frozenset(banks), bars=bars,
                           dividends={}, required_pt=R_PT, years=3, sectors={})
    base = ri.BankRI().evaluate("LEVB", inp)
    assert base.components["roe0"] == pytest.approx(0.18)
    # peers' median multiplier 7 (5, 6, 7, 8, 10): ROA × 7 = 12.6% >= 12%: not flagged
    monkeypatch.setitem(ri.CONFIG, "roe_source", "dupont_sustainable")
    same = ri.BankRI().evaluate("LEVB", inp)
    assert same.components["roe0"] == pytest.approx(0.18)
    assert same.components["roe0_ttm"] == pytest.approx(0.18)
    lev2 = firm(15.0, 100.0, 100.0, 1000.0, 1000.0)  # ROA 1.5% × 7 = 10.5% < 12%, ROE 15%
    inp2 = qm.QualityInputs(SEEN, banks | {"LEVB": lev2}, {}, frozenset(banks), bars=bars,
                            dividends={}, required_pt=R_PT, years=3, sectors={})
    moved = ri.BankRI().evaluate("LEVB", inp2)
    assert moved.components["roe0_ttm"] == pytest.approx(0.15)
    assert moved.components["roe0"] == pytest.approx(0.105)
    assert any("sustainable ROE" in f for f in moved.flags)
    assert moved.score > ri.bank_ri("LEVB", lev2, bars["LEVB"], [], SEEN, R_PT,
                                    years=3).score  # less excess return, lower fair value


# ---------------- registry and replay ----------------


def test_registered_and_wrong_inputs_are_na():
    names = [f.name for f in fw.registered()]
    assert "dupont" in names and "gp_a" in names
    for f in (qm.DuPont(), qm.GrossProfitability()):
        r = f.evaluate("CCCC", {})
        assert r.score is None and r.flags


def test_gpa_replay_panel_excludes_financials_and_has_forward_return():
    q0, q1 = SEEN, SEEN + timedelta(days=91)
    bars = {s: [Bar(q0, 1000.0, 2e12), Bar(q1, 1100.0, 2.2e12)] for s in ("CCCC", "PPP1")}
    bars["DDDD"] = [Bar(q0, 1000.0, 2e12)]
    bars["SMAL"] = [Bar(q0, 1000.0, 5e11)]  # under IDR 1T: out
    qs = {"CCCC": C, "PPP1": PEERS["PPP1"], "DDDD": D, "SMAL": C, "BANK": C}
    bars["BANK"] = bars["CCCC"]
    st = {s: statements() for s in qs}
    panel = qm.replay_panel(bars, qs, st, {"PPP1": [{"ex": (q0 + timedelta(days=5))
                                                     .isoformat(), "value": 50.0}]},
                            {"BANK"}, [q0, q1])
    (_, recs0), _ = panel
    by = {r["symbol"]: r for r in recs0}
    assert set(by) == {"CCCC", "PPP1", "DDDD"}
    assert by["CCCC"]["gp_a"] == pytest.approx(0.25)
    assert by["CCCC"]["fwd"] == pytest.approx(0.1)
    assert by["PPP1"]["fwd"] == pytest.approx(0.15)  # 1,000 → 1,100 plus 50 paid
    assert by["DDDD"]["fwd"] is None
