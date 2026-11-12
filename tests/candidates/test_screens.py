"""IDN stock screens (P20): dividend, value and momentum, each gated by a placebo control.

The rules are idx-method's former books (paper/strategies.py, strategy.py, div_panel.py,
fundpanel.py at git 9a0ea38^). Every test runs on a synthetic market built here: 60 names over
four years of weekdays, whose daily drift is either planted (so the screen's leg predicts next
month's return) or zero (so it cannot)."""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from assist.candidates import screens as S
from assist.sources.idxmethod_stocks import IdxMethodStocks

START = date(2022, 1, 3)
N_DAYS = 1000
N_NAMES = 60
FAST = {"n_shuffles": 200, "n_controls": 5}


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DATES = _weekdays(START, N_DAYS)
LAST = DATES[-1]


def market(drift: dict[str, float], seed: int = 7, sigma: float = 0.01) -> dict[str, list]:
    """sym → bars with a constant daily drift plus Gaussian noise; liquid, priced well above
    the floors, vol ~16% a year."""
    rng = random.Random(seed)
    out = {}
    for sym, mu in sorted(drift.items()):
        px, bars = 5000.0, []
        for d in DATES:
            px *= 1 + mu + rng.gauss(0, sigma)
            bars.append({"date": d.isoformat(), "close": px, "value": 1e10, "volume": 1000})
        out[sym] = bars
    return out


def names(n: int = N_NAMES) -> list[str]:
    return [f"S{i:03d}" for i in range(n)]


def spread_drift(lo: float = -0.0015, hi: float = 0.0015) -> dict[str, float]:
    syms = names()
    return {s: lo + (hi - lo) * i / (len(syms) - 1) for i, s in enumerate(syms)}


def flat_drift() -> dict[str, float]:
    return dict.fromkeys(names(), 0.0)


def dividends_for(history: dict[str, list], weight: dict[str, float]) -> dict[str, list]:
    """A quarterly dividend whose yield on the then-current price grows with `weight`
    (0 → non-payer)."""
    out = {}
    for sym, bars in history.items():
        w = weight.get(sym, 0.0)
        recs = []
        for k in range(10, len(bars), 63):
            if w > 0:
                recs.append({"ex": bars[k]["date"], "value": bars[k]["close"] * w,
                             "ccy": "CURRENCY_IDR"})
        out[sym] = recs
    return out


def fundamentals_for(history: dict[str, list], bp: dict[str, float]) -> dict[str, dict]:
    """Quarterly bvps = bp × the price on the quarter end, so book-to-price ranks as `bp`."""
    out = {}
    for sym, bars in history.items():
        by_date = {b["date"]: b["close"] for b in bars}
        periods, vals = [], []
        for y in range(2021, 2026):
            for q, (m, dd) in S.QEND.items():
                qend = date(y, m, dd)
                px = next((by_date[(qend - timedelta(days=k)).isoformat()]
                           for k in range(7) if (qend - timedelta(days=k)).isoformat()
                           in by_date), 5000.0)
                periods.append(f"{y}Q{q}")
                vals.append(px * bp[sym])
        out[sym] = {"symbol": sym, "periods": {"bs": periods},
                    "items": {"bs": {"bvps": vals}}}
    return out


# ---------------- rule pieces (idx-method's definitions) ----------------


def test_three_screens_with_idx_method_legs():
    assert set(S.SCREENS) == {"dividend", "value", "momentum"}
    assert S.SCREENS["dividend"].legs == (("div_yield_pit", 1),)
    assert S.SCREENS["value"].legs == (("bp", 1),)
    assert S.SCREENS["momentum"].legs == (("mom_12_1", 1), ("near_52w_high", 1))


def good_row(**kw) -> dict:
    row = {"symbol": "AAA", "free_float": 40.0, "med_value_60d": 1e10, "price": 1000.0,
           "vol_1y": 0.3, "days_traded_60": 60, "piotroski": 7, "altman_z": 3.0,
           "cfo_ttm": 1e9, "der": 0.5, "interest_cov": 5.0, "pbv": 2.0}
    return {**row, **kw}


@pytest.mark.parametrize(
    ("kw", "flagged", "why"),
    [
        ({}, {"AAA"}, "flagged board"),
        ({"free_float": 10.0}, set(), "free float"),
        ({"med_value_60d": 4e9}, set(), "liquidity"),
        ({"med_value_60d": None}, set(), "liquidity"),
        ({"price": 99.0}, set(), "price floor"),
        ({"vol_1y": 1.2}, set(), "extreme volatility"),
        ({"days_traded_60": 40}, set(), "trades too rarely"),
    ],
)
def test_gates_reject_with_first_rule_failed(kw, flagged, why):
    assert S.passes_gates("AAA", good_row(**kw), flagged) == (False, why)


def test_gates_pass_a_clean_row():
    assert S.passes_gates("AAA", good_row(), set()) == (True, None)


@pytest.mark.parametrize(
    ("kw", "why"),
    [
        ({"piotroski": 4}, "F-score"),
        ({"altman_z": 1.0}, "Altman Z"),
        ({"cfo_ttm": -1.0}, "negative CFO"),
        ({"der": -0.2}, "negative equity"),
        ({"interest_cov": 1.0}, "interest cover"),
        # banks are judged on prudential metrics instead (a CAR marks a bank)
        ({"car": 12.0, "piotroski": 2, "altman_z": 0.6}, "CAR"),
        ({"car": 20.0, "npl_gross": 6.0}, "NPL"),
    ],
)
def test_quality_floor(kw, why):
    assert S.passes_quality(good_row(**kw)) == (False, why)


def test_quality_waives_interest_cover_without_debt_and_passes_healthy_bank():
    assert S.passes_quality(good_row(der=0.0, interest_cov=0.5)) == (True, None)
    bank = good_row(car=20.0, npl_gross=2.0, npl_cov=150.0, ldr=90.0, roe=15.0,
                    piotroski=3, altman_z=0.7)
    assert S.passes_quality(bank) == (True, None)


def test_trailing_dividend_is_idr_only_in_the_last_365_days():
    recs = [{"ex": "2024-12-20", "value": 10.0, "ccy": "CURRENCY_IDR"},
            {"ex": "2025-06-01", "value": 20.0, "ccy": None},
            {"ex": "2025-07-01", "value": 99.0, "ccy": "CURRENCY_USD"},
            {"ex": "2026-01-05", "value": 5.0, "ccy": "CURRENCY_IDR"}]
    assert S.trailing_dividend(recs, date(2026, 1, 5)) == 25.0
    assert S.trailing_dividend(recs, date(2026, 1, 4)) == 20.0


def test_book_per_share_waits_120_days_after_quarter_end():
    fund = {"periods": {"bs": ["2025Q4", "2026Q1"]},
            "items": {"bs": {"bvps": [100.0, 110.0]}}}
    assert S.book_per_share(fund, date(2026, 4, 30)) == 100.0  # 2026Q1 knowable 2026-07-29
    assert S.book_per_share(fund, date(2026, 7, 29)) == 110.0
    assert S.book_per_share(fund, date(2026, 1, 1)) is None


def test_blend_zscores_clip_and_drop_names_missing_a_leg():
    rows = [{"symbol": f"N{i}", "a": float(i), "b": float(-i)} for i in range(10)]
    rows.append({"symbol": "OUT", "a": 1000.0, "b": 0.0})
    rows.append({"symbol": "GAP", "a": None, "b": 1.0})
    ranked = S.blend(rows, (("a", 1),))
    assert ranked[0][2]["symbol"] == "OUT" and ranked[0][1]["a"] == 3.0
    assert "GAP" not in {r["symbol"] for _, _, r in ranked}
    # opposite legs cancel to zero for every name
    both = S.blend(rows[:10], (("a", 1), ("b", 1)))
    assert all(abs(sc) < 1e-12 for sc, _, _ in both)


def test_blend_needs_eight_values_per_leg():
    rows = [{"symbol": f"N{i}", "a": float(i)} for i in range(7)]
    assert S.blend(rows, (("a", 1),)) == []


def test_select_caps_names_per_sector():
    ranked = [(10 - i, {}, {"symbol": f"N{i}"}) for i in range(10)]
    sectors = {f"N{i}": ("bank" if i < 7 else "mining") for i in range(10)}
    picks = S.select(ranked, top_n=6, sectors=sectors, max_per_sector=5)
    assert [r["symbol"] for r in picks] == ["N0", "N1", "N2", "N3", "N4", "N7"]
    # a name with no sector is its own bucket, never pooled into "unknown"
    picks = S.select(ranked, top_n=10, sectors={}, max_per_sector=1)
    assert len(picks) == 10


# ---------------- the monthly panel (point in time) ----------------


def test_panel_is_point_in_time_month_ends():
    hist = market(spread_drift())
    panel = S.build_panel(hist)
    months = [d for d, _ in panel]
    assert months == sorted(months)
    # every formation date is a month's last bar, at least a year in, with a full month after
    assert all(d.month != DATES[DATES.index(d) + 1].month for d in months)
    assert DATES.index(months[0]) >= 252 and months[-1] < LAST
    rec = panel[0][1][0]
    assert {"symbol", "price", "mom_12_1", "near_52w_high", "fwd"} <= set(rec)
    # cut at as_of: nothing formed, and no forward return reaching, past it
    cut = S.build_panel(hist, as_of=months[5])
    assert [d for d, _ in cut] == months[:5]


def test_panel_applies_point_in_time_gates():
    hist = market(spread_drift())
    for b in hist["S000"]:
        b["value"] = 1e9  # below the 5bn/day liquidity floor
    panel = S.build_panel(hist, flagged={"S001"})
    syms = {r["symbol"] for _, recs in panel for r in recs}
    assert "S000" not in syms and "S001" not in syms and "S002" in syms


def test_panel_dividend_yield_and_book_to_price():
    hist = market(flat_drift())
    divs = dividends_for(hist, {"S000": 0.01})
    fund = fundamentals_for(hist, {s: 0.5 for s in hist})
    panel = S.build_panel(hist, dividends=divs, fundamentals=fund)
    rec = {r["symbol"]: r for r in panel[-1][1]}
    assert rec["S000"]["div_yield_pit"] == pytest.approx(0.04, rel=0.4)
    assert rec["S001"]["div_yield_pit"] == 0.0  # in the cache, never paid
    assert rec["S001"]["bp"] == pytest.approx(0.5, rel=0.4)
    bare = {r["symbol"]: r for r in S.build_panel(hist)[-1][1]}
    assert bare["S001"]["div_yield_pit"] is None and bare["S001"]["bp"] is None


# ---------------- placebo-gated verdicts ----------------


def test_momentum_with_planted_drift_beats_its_placebo():
    panel = S.build_panel(market(spread_drift()))
    v = S.evaluate_screen(S.SCREENS["momentum"], panel, **FAST)
    assert v.passed, v.reason
    assert v.rule.diff > 0 and v.p_value <= 0.05 and abs(v.control_t) < 2


def test_momentum_on_a_driftless_market_fails():
    panel = S.build_panel(market(flat_drift(), seed=11))
    v = S.evaluate_screen(S.SCREENS["momentum"], panel, **FAST)
    assert not v.passed


def test_dividend_screen_passes_when_yield_carries_the_drift():
    drift = spread_drift(0.0, 0.002)
    hist = market(drift)
    weight = {s: 0.002 + 4 * mu for s, mu in drift.items()}
    panel = S.build_panel(hist, dividends=dividends_for(hist, weight))
    v = S.evaluate_screen(S.SCREENS["dividend"], panel, **FAST)
    assert v.passed, v.reason


def test_value_screen_fails_when_book_to_price_is_noise():
    hist = market(spread_drift(), seed=3)
    rng = random.Random(5)
    fund = fundamentals_for(hist, {s: rng.uniform(0.2, 2.0) for s in hist})
    panel = S.build_panel(hist, fundamentals=fund)
    v = S.evaluate_screen(S.SCREENS["value"], panel, **FAST)
    assert not v.passed


def test_screen_without_its_inputs_is_insufficient_sample():
    panel = S.build_panel(market(spread_drift()))  # no fundamentals → no bp
    v = S.evaluate_screen(S.SCREENS["value"], panel, **FAST)
    assert not v.passed and v.reason.startswith("insufficient sample")


def test_verdict_is_deterministic():
    panel = S.build_panel(market(spread_drift()))
    a = S.evaluate_screen(S.SCREENS["momentum"], panel, **FAST)
    b = S.evaluate_screen(S.SCREENS["momentum"], panel, **FAST)
    assert a == b


# ---------------- end to end over an idx-method-shaped root ----------------


def write_root(root: Path, drift: dict[str, float], *, boards: bool = True,
               dividends: bool = True) -> Path:
    hist = market(drift)
    (root / "data").mkdir(parents=True)
    (root / "cache" / "history").mkdir(parents=True)
    factors = {}
    for sym, bars in hist.items():
        (root / "cache" / "history" / f"{sym}.json").write_text(json.dumps(bars))
        factors[sym] = good_row(symbol=sym, price=bars[-1]["close"],
                                pbv=1.0 + int(sym[1:]) / 30)
    factors["S005"]["piotroski"] = 2  # fails the quality floor
    (root / "data" / "factors.json").write_text(json.dumps(factors))
    if dividends:
        (root / "cache" / "dividends").mkdir(parents=True)
        for sym, recs in dividends_for(hist, {s: 0.01 for s in hist}).items():
            (root / "cache" / "dividends" / f"{sym}.json").write_text(json.dumps(recs))
    if boards:
        (root / "data" / "special_boards.json").write_text(json.dumps({"FCA": ["S059"]}))
        (root / "data" / "sectors.json").write_text(
            json.dumps({s: ("bank" if int(s[1:]) % 2 else "mining") for s in hist}))
    return root


def test_run_screens_names_candidates_only_for_a_passing_screen(tmp_path):
    out = S.run_screens(IdxMethodStocks(write_root(tmp_path, spread_drift())), **FAST)
    assert out["as_of"] == LAST
    mom = out["screens"]["momentum"]
    assert mom["passed"] and mom["blocked"] is None
    picks = [c["symbol"] for c in mom["candidates"]]
    assert len(picks) == 10  # top 20 wanted, but at most 5 from each of the two sectors
    assert "S059" not in picks and "S005" not in picks  # flagged board, quality floor
    assert all(int(p[1:]) >= 30 for p in picks)  # all from the upper half of planted drift
    assert mom["rejects"]["flagged board"] == 1 and mom["rejects"]["F-score"] == 1
    assert abs(mom["verdict"]["control_t"]) < 2
    c = mom["candidates"][0]
    assert {"symbol", "score", "z", "sector", "mom_12_1", "near_52w_high", "price"} <= set(c)
    # value has no fundamentals here: it may run, but it must not name anyone
    val = out["screens"]["value"]
    assert not val["passed"] and val["candidates"] == [] and val["blocked"]
    assert val["n_ranked"] > 0
    assert any("fundamentals" in s for s in out["stale_inputs"])


def test_run_screens_records_missing_boards_and_dividends(tmp_path):
    root = write_root(tmp_path, flat_drift(), boards=False, dividends=False)
    out = S.run_screens(IdxMethodStocks(root), **FAST)
    stale = " ".join(out["stale_inputs"])
    assert "special_boards" in stale and "sectors" in stale and "dividends" in stale
    for name in S.SCREENS:
        assert out["screens"][name]["candidates"] == []


def test_run_screens_on_a_missing_repo_never_crashes(tmp_path):
    out = S.run_screens(IdxMethodStocks(tmp_path / "nope"), **FAST)
    assert out["stale_inputs"] == ["idx-method (missing)"]
    assert all(r["candidates"] == [] for r in out["screens"].values())


# ---------------- S88: the bank Piotroski floor ----------------

SOUND_BANK = {"car": 20.0, "npl_gross": 2.0, "npl_cov": 150.0, "ldr": 90.0, "roe": 15.0,
              "piotroski": 3, "altman_z": 0.7}


def test_bank_below_the_point_in_time_f_floor_fails():
    bank = good_row(**SOUND_BANK, f_pit=3.0)
    assert S.passes_quality(bank) == (False, "bank F-score")
    assert S.bank_f_status(bank) == "fail"


def test_bank_at_the_f_floor_passes_whatever_stockbit_says():
    bank = good_row(**SOUND_BANK, f_pit=4.0)  # Stockbit's today-only piotroski 3 is not read
    assert S.passes_quality(bank) == (True, None) and S.bank_f_status(bank) == "pass"


def test_bank_with_no_f_is_flagged_not_failed():
    for bank in (good_row(**SOUND_BANK, f_pit=None), good_row(**SOUND_BANK)):
        assert S.passes_quality(bank) == (True, None)
        assert S.bank_f_status(bank) == "n/a"


def test_the_prudential_floor_still_comes_first():
    bank = good_row(**(SOUND_BANK | {"car": 10.0}), f_pit=2.0)
    assert S.passes_quality(bank) == (False, "CAR")


def test_a_non_bank_is_unaffected_by_the_bank_f():
    assert S.passes_quality(good_row(f_pit=1.0)) == (True, None)
    assert S.bank_f_status(good_row(f_pit=1.0)) is None


def test_the_bank_f_floor_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(S, "BANK_F_FLOOR_ON", False)
    bank = good_row(**SOUND_BANK, f_pit=3.0)
    assert S.passes_quality(bank) == (True, None) and S.bank_f_status(bank) is None


def test_bank_f_at_reads_the_newest_report_available():
    series = [(date(2025, 4, 30), 5.0), (date(2025, 7, 29), 3.0), (date(2025, 10, 28), None)]
    assert S.bank_f_at(series, date(2025, 3, 31)) is None
    assert S.bank_f_at(series, date(2025, 6, 30)) == 5.0
    assert S.bank_f_at(series, date(2025, 7, 29)) == 3.0
    assert S.bank_f_at(series, date(2025, 12, 31)) is None  # n/a once the newest is n/a


def test_with_bank_f_puts_s95s_f_on_bank_rows_only():
    from assist.sources.idxmethod_series import Fundamentals

    def q(p, ta, ni, cfo):
        return Fundamentals(p, p + timedelta(days=120), cfo, 500.0, 0.0, ni, ni, None, None,
                            ta, 100.0)

    qes = [date(2023, 6, 30), date(2023, 9, 30), date(2023, 12, 31), date(2024, 3, 31),
           date(2024, 6, 30), date(2024, 9, 30), date(2024, 12, 31), date(2025, 3, 31),
           date(2025, 6, 30)]
    quarters = [q(p, 1000.0, 50.0, 60.0) for p in qes]
    table = {"BANK": good_row(**SOUND_BANK), "AAA": good_row()}
    out = S.with_bank_f(table, {"BANK": quarters, "AAA": quarters}, {}, date(2025, 11, 1))
    assert S.BANK_F_KEY not in out["AAA"]
    assert S.BANK_F_KEY in out["BANK"]  # no statements: s7, s9 n/a, 5 of 7 → None (n/a)
    assert out["BANK"][S.BANK_F_KEY] is None and S.bank_f_status(out["BANK"]) == "n/a"
    assert S.BANK_F_KEY not in table["BANK"]  # the input is not changed
