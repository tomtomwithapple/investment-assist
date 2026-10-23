from datetime import date

import pytest

from assist import fx
from assist.sources.base import Row


def _rows(sid: str, points: list[tuple[str, float | None]], source: str = "t") -> list[Row]:
    return [Row(sid, date.fromisoformat(d), v, None, source) for d, v in points]


JISDOR = _rows(
    "JISDOR",
    [
        ("2026-01-02", 16000.0),
        ("2026-01-05", 16100.0),
        ("2026-01-06", None),
        ("2026-01-07", 16200.0),
    ],
)


# ---------------- levels and changes ----------------


def test_level_at_takes_last_value_on_or_before_and_skips_none():
    assert fx.level_at(JISDOR, date(2026, 1, 5)) == 16100.0
    assert fx.level_at(JISDOR, date(2026, 1, 6)) == 16100.0  # None skipped
    assert fx.level_at(JISDOR, date(2026, 1, 31)) == 16200.0
    assert fx.level_at(JISDOR, date(2025, 12, 31)) is None


def test_level_at_respects_max_age():
    assert fx.level_at(JISDOR, date(2026, 1, 31), max_age_days=7) is None
    assert fx.level_at(JISDOR, date(2026, 1, 10), max_age_days=7) == 16200.0


def test_level_at_ignores_input_order():
    assert fx.level_at(list(reversed(JISDOR)), date(2026, 1, 5)) == 16100.0


def test_fx_change():
    assert fx.fx_change(JISDOR, date(2026, 1, 2), date(2026, 1, 7)) == pytest.approx(0.0125)
    assert fx.fx_change(JISDOR, date(2025, 1, 1), date(2026, 1, 7)) is None


def test_horizon_changes_pairs_each_date_with_the_level_horizon_days_later():
    rows = _rows("X", [("2026-01-01", 100.0), ("2026-01-11", 110.0), ("2026-01-21", 99.0)])
    assert fx.horizon_changes(rows, 10) == pytest.approx([0.10, -0.10])
    assert fx.horizon_changes(rows, 30) == []


# ---------------- cross rates ----------------


def test_cross_via_usd():
    # IDR per USD ÷ JPY per USD = IDR per JPY
    jpy = _rows("DEXJPUS", [("2026-01-02", 160.0), ("2026-01-05", 161.0), ("2026-01-07", 162.0)])
    out = fx.cross(JISDOR, jpy, series_id="IDRJPY")
    assert [r.date for r in out] == [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 7)]
    assert out[0].value == pytest.approx(100.0)
    assert out[2].value == pytest.approx(16200 / 162)
    assert {r.series_id for r in out} == {"IDRJPY"}
    assert out[0].source == "t+t"


def test_cross_inverts_usd_per_local_quotes():
    # EUR quoted as USD per EUR (1.10) → IDR per EUR = 16000 × 1.10
    eur = _rows("DEXUSEU", [("2026-01-02", 1.10)])
    out = fx.cross(JISDOR, eur, local_per_usd=False)
    assert out[0].value == pytest.approx(17600.0)


def test_cross_carries_the_local_leg_forward_within_max_gap_only():
    local = _rows("L", [("2026-01-02", 2.0)])
    out = fx.cross(JISDOR, local, max_gap_days=3)
    # 01-02 and 01-05 (3 days later) match; 01-07 is 5 days stale → dropped
    assert [r.date for r in out] == [date(2026, 1, 2), date(2026, 1, 5)]
    assert out[1].value == pytest.approx(8050.0)


def test_cross_keeps_the_later_as_of():
    a = [Row("A", date(2026, 1, 2), 16000.0, date(2026, 1, 3), "a")]
    b = [Row("B", date(2026, 1, 2), 2.0, date(2026, 1, 9), "b")]
    assert fx.cross(a, b)[0].as_of == date(2026, 1, 9)


def test_to_idr_converts_a_local_price_series():
    prices = _rows("SPX", [("2026-01-02", 10.0), ("2026-01-07", 11.0), ("2026-02-28", 12.0)])
    usd_idr = _rows("JISDOR", [("2026-01-02", 16000.0), ("2026-01-07", 16200.0)])
    out = fx.to_idr(prices, usd_idr)
    assert [(r.series_id, r.date, r.value) for r in out] == [
        ("SPX_IDR", date(2026, 1, 2), 160000.0),
        ("SPX_IDR", date(2026, 1, 7), 178200.0),
    ]  # 02-28 has no rate within 7 days


# ---------------- returns ----------------


def test_unhedged_return_compounds_local_return_and_fx_move():
    assert fx.unhedged_idr_return(0.10, 0.05) == pytest.approx(0.155)
    assert fx.unhedged_idr_return(0.10, -0.10) == pytest.approx(-0.01)
    assert fx.unhedged_idr_return(0.10, 0.0) == pytest.approx(0.10)


def test_forward_premium_is_the_rate_differential_over_the_horizon():
    # IDR 5.75%, USD 3.875%, 1 year: (1.0575 / 1.03875) − 1
    assert fx.forward_premium(0.0575, 0.03875, 1.0) == pytest.approx(1.0575 / 1.03875 - 1)
    # half a year, simple interest
    assert fx.forward_premium(0.06, 0.02, 0.5) == pytest.approx(1.03 / 1.01 - 1)
    assert fx.forward_premium(0.05, 0.05, 1.0) == 0.0


def test_hedged_return_is_local_return_plus_carry():
    h = fx.hedged_idr_return(0.08, 0.0575, 0.03875, 1.0)
    assert h == pytest.approx(1.08 * 1.0575 / 1.03875 - 1)
    # ≈ r_local + (i_IDR − i_local) × T
    assert h == pytest.approx(0.08 + (0.0575 - 0.03875), abs=0.002)


def test_hedge_carry_from_rate_rows_in_percent():
    bi = _rows("WS_CBPOL.M.ID", [("2026-08-01", 5.75), ("2026-09-01", 5.75)])
    fed = _rows("WS_CBPOL.M.US", [("2026-08-01", 4.125), ("2026-09-01", 3.875)])
    c = fx.hedge_carry(bi, fed, date(2026, 9, 30), 1.0)
    assert c == pytest.approx(fx.forward_premium(0.0575, 0.03875, 1.0))
    assert fx.hedge_carry(bi, fed, date(2026, 1, 1), 1.0) is None


def test_breakeven_fx_move():
    # local 10%, IDR alternative 6%: the local currency may fall ~3.6% vs IDR before the edge goes
    be = fx.breakeven_fx_move(0.10, 0.06)
    assert be == pytest.approx(1.06 / 1.10 - 1)
    assert fx.unhedged_idr_return(0.10, be) == pytest.approx(0.06)


def test_uip_expected_move_equals_forward_premium():
    assert fx.uip_expected_move(0.0575, 0.03875, 1.0) == fx.forward_premium(0.0575, 0.03875, 1.0)


# ---------------- the overweight test ----------------


def test_edge_survives_unhedged_when_fx_move_is_favourable():
    e = fx.fx_edge(r_local=0.10, r_idr=0.06, expected_fx_move=0.02, i_idr=0.0575, i_local=0.0575)
    assert e.unhedged == pytest.approx(1.10 * 1.02 - 1)
    assert e.hedged == pytest.approx(0.10)
    assert e.best == "unhedged"
    assert e.survives
    assert e.edge == pytest.approx(e.unhedged - 0.06)


def test_edge_dies_when_the_expected_fx_move_eats_it_and_hedging_costs_carry():
    # local currency expected to fall 8% vs IDR, and hedging pays away the rate gap
    e = fx.fx_edge(r_local=0.10, r_idr=0.06, expected_fx_move=-0.08, i_idr=0.02, i_local=0.08)
    assert e.unhedged < 0.06 and e.hedged < 0.06
    assert not e.survives
    assert e.best is None
    assert e.breakeven_fx_move == pytest.approx(1.06 / 1.10 - 1)


def test_hedged_rescues_the_edge_when_idr_pays_more_carry():
    e = fx.fx_edge(r_local=0.08, r_idr=0.06, expected_fx_move=-0.10, i_idr=0.0575, i_local=0.03875)
    assert e.unhedged < 0.06
    assert e.hedged > 0.06
    assert e.best == "hedged" and e.survives


def test_edge_margin_is_required_and_hedge_optional():
    e = fx.fx_edge(r_local=0.07, r_idr=0.06, expected_fx_move=0.0, margin=0.02)
    assert e.hedged is None
    assert not e.survives
    assert fx.fx_edge(r_local=0.07, r_idr=0.06, expected_fx_move=0.0, margin=0.005).survives


def test_fx_edge_rejects_mismatched_rate_inputs():
    with pytest.raises(ValueError):
        fx.fx_edge(r_local=0.07, r_idr=0.06, expected_fx_move=0.0, i_idr=0.05)


def test_fx_edge_detail_is_human_readable():
    e = fx.fx_edge(r_local=0.08, r_idr=0.06, expected_fx_move=-0.10, i_idr=0.0575, i_local=0.03875)
    s = e.detail()
    assert "hedged" in s and "%" in s
