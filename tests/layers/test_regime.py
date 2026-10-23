"""Regime, layer 0 (P8, PLAN S3): a small hand-set rule on VIX, HY OAS Δ13w, broad dollar Δ13w,
the 10Y real yield and NFCI → risk_on | neutral | risk_off plus the dollar's direction.

Tests feed in-memory FRED rows through a fake source (no store, no network); the walk-forward
check runs the P9 placebo harness on synthetic prices."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from assist.layers.regime import (
    ADOPTED,
    CANDIDATES,
    CORE,
    READ_BACK,
    Inputs,
    check,
    classify,
    entry_returns,
    history,
    inputs,
    read_inputs,
    regime,
    weekly,
)
from assist.layers.types import Regime
from assist.sources.base import Row, SourceUnavailable

AS_OF = date(2026, 10, 16)  # a Friday
SRC = "sec-edgar"


def series(sid: str, start_value: float, end_value: float, *, end: date = AS_OF,
           days: int = 120, step: int = 1, as_of: date | None = None) -> list[Row]:
    """A straight line from `start_value` (end − days) to `end_value` (end), every `step` days
    counted back from `end`."""
    out = []
    for back in range(0, days + 1, step):
        d = end - timedelta(days=back)
        v = start_value + (end_value - start_value) * (days - back) / days
        out.append(Row(sid, d, v, as_of or d, SRC))
    return sorted(out)


def calm(**over) -> list[Row]:
    """Every core input inside its neutral band, unless overridden as sid=(start, end)."""
    base = {
        "VIXCLS": (18.0, 18.0),
        "BAMLH0A0HYM2": (3.2, 3.2),
        "DTWEXBGS": (120.0, 120.0),
        "DFII10": (1.5, 1.5),
        "NFCI": (-0.3, -0.3),
    }
    base.update(over)
    rows = []
    for sid, (a, b) in base.items():
        rows += series(sid, a, b, step=7 if sid == "NFCI" else 1)
    return rows


class Fake:
    name = SRC

    def __init__(self, rows: list[Row] | None = None, error: SourceUnavailable | None = None):
        self._rows, self.error, self.calls = rows or [], error, []

    def rows(self, series_ids=None, start=None, end=None, as_of=None):
        self.calls.append((tuple(series_ids or ()), start, end, as_of))
        if self.error:
            raise self.error
        return [r for r in self._rows
                if (series_ids is None or r.series_id in series_ids)
                and (start is None or r.date >= start) and (end is None or r.date <= end)
                and (as_of is None or r.as_of <= as_of)]


# ---------------- features ----------------


def test_core_is_the_five_layer0_inputs():
    assert CORE == ("VIXCLS", "BAMLH0A0HYM2", "DTWEXBGS", "DFII10", "NFCI")
    assert set(CANDIDATES) == {"net_liquidity", "em_oas", "term_premium", "stlfsi"}
    assert ADOPTED == ()  # no candidate has beaten the placebo yet


def test_inputs_levels_and_13_week_changes():
    rows = calm(VIXCLS=(20.0, 27.5), BAMLH0A0HYM2=(3.0, 4.0), DTWEXBGS=(100.0, 104.0))
    inp = inputs(rows, AS_OF)
    assert isinstance(inp, Inputs)
    assert inp.values["vix"] == pytest.approx(27.5)
    # 91 days back on a 120-day line: start + (end-start) * 29/120
    assert inp.values["hy_oas_d13w"] == pytest.approx(1.0 * 91 / 120)
    assert inp.values["usd_d13w"] == pytest.approx(100 * (104 / (100 + 4 * 29 / 120) - 1))
    assert inp.values["real_yield"] == pytest.approx(1.5)
    assert inp.values["nfci"] == pytest.approx(-0.3)
    assert inp.stale_inputs == ()


def test_inputs_ignore_points_after_as_of_and_none_values():
    rows = calm() + [Row("VIXCLS", AS_OF + timedelta(days=1), 80.0, AS_OF, SRC),
                     Row("VIXCLS", AS_OF, None, AS_OF, SRC)]
    assert inputs(rows, AS_OF).values["vix"] == pytest.approx(18.0)


def test_missing_series_is_stale_and_scores_nothing():
    rows = [r for r in calm() if r.series_id != "BAMLH0A0HYM2"]
    inp = inputs(rows, AS_OF)
    assert inp.values["hy_oas_d13w"] is None
    assert "sec-edgar BAMLH0A0HYM2 (no data)" in inp.stale_inputs
    assert classify(inp).state == "neutral"


def test_short_history_has_no_change():
    rows = [r for r in calm() if r.series_id != "BAMLH0A0HYM2"]
    rows += series("BAMLH0A0HYM2", 3.0, 5.0, days=30)
    inp = inputs(rows, AS_OF)
    assert inp.values["hy_oas_d13w"] is None
    assert any("BAMLH0A0HYM2" in s and "history" in s for s in inp.stale_inputs)


def test_old_last_point_is_stale():
    rows = [r for r in calm() if r.series_id != "VIXCLS"]
    rows += series("VIXCLS", 18.0, 18.0, end=AS_OF - timedelta(days=20))
    inp = inputs(rows, AS_OF)
    assert inp.values["vix"] == pytest.approx(18.0)
    assert f"sec-edgar VIXCLS (last {AS_OF - timedelta(days=20)})" in inp.stale_inputs


# ---------------- rule ----------------


def test_calm_is_neutral_and_dollar_flat():
    reg = classify(inputs(calm(), AS_OF))
    assert isinstance(reg, Regime)
    assert (reg.state, reg.dollar) == ("neutral", "flat")
    assert reg.as_of == AS_OF


def test_stress_is_risk_off_with_drivers():
    rows = calm(VIXCLS=(18.0, 31.0), BAMLH0A0HYM2=(3.0, 4.5), NFCI=(-0.3, 0.2))
    reg = classify(inputs(rows, AS_OF))
    assert reg.state == "risk_off"
    assert any(d.startswith("VIX 31.0") for d in reg.drivers)
    assert any(d.startswith("HY OAS +") for d in reg.drivers)
    assert any(d.startswith("NFCI 0.20") for d in reg.drivers)


def test_one_red_flag_alone_stays_neutral():
    assert classify(inputs(calm(VIXCLS=(18.0, 27.0)), AS_OF)).state == "neutral"


def test_extreme_vix_counts_double():
    assert classify(inputs(calm(VIXCLS=(18.0, 40.0)), AS_OF)).state == "risk_off"


def test_easy_conditions_are_risk_on():
    rows = calm(VIXCLS=(16.0, 12.0), BAMLH0A0HYM2=(4.0, 3.2), NFCI=(-0.4, -0.6))
    assert classify(inputs(rows, AS_OF)).state == "risk_on"


def test_red_and_green_flags_offset():
    rows = calm(VIXCLS=(16.0, 12.0), NFCI=(-0.4, -0.6), DFII10=(2.6, 2.7),
                DTWEXBGS=(100.0, 104.0))
    assert classify(inputs(rows, AS_OF)).state == "neutral"


@pytest.mark.parametrize("end, dollar", [(104.0, "up"), (101.0, "flat"), (96.0, "down")])
def test_dollar_direction_from_13_week_change(end, dollar):
    reg = classify(inputs(calm(DTWEXBGS=(100.0, end)), AS_OF))
    assert reg.dollar == dollar


def test_strong_dollar_is_a_risk_off_point():
    rows = calm(VIXCLS=(18.0, 27.0), DTWEXBGS=(100.0, 105.0))
    assert classify(inputs(rows, AS_OF)).state == "risk_off"


def test_candidates_count_only_when_adopted():
    rows = calm(VIXCLS=(18.0, 27.0)) + series("STLFSI4", 0.5, 1.2, step=7)
    inp = inputs(rows, AS_OF)
    assert inp.values["stlfsi"] == pytest.approx(1.2)
    assert classify(inp).state == "neutral"
    assert classify(inp, extra=("stlfsi",)).state == "risk_off"


def test_net_liquidity_candidate_from_its_three_inputs():
    rows = calm()
    rows += series("WALCL", 7_000_000, 6_500_000, step=7)
    rows += series("WTREGEN", 800_000, 800_000, step=7)
    rows += series("RRPONTSYD", 100.0, 100.0)
    inp = inputs(rows, AS_OF)
    assert inp.values["net_liquidity_d13w"] < -3


# ---------------- reading, point in time ----------------


def test_regime_reads_point_in_time():
    fake = Fake(calm(VIXCLS=(18.0, 31.0), BAMLH0A0HYM2=(3.0, 4.5), NFCI=(-0.3, 0.2)))
    reg = regime(AS_OF, source=fake)
    assert reg.state == "risk_off"
    assert reg.sources == (SRC,)
    ids, start, end, as_of = fake.calls[0]
    assert set(CORE) <= set(ids)
    assert (start, end, as_of) == (AS_OF - READ_BACK, AS_OF, AS_OF)


def test_regime_never_sees_later_vintages():
    rows = calm()
    # a VIX spike recorded after AS_OF must not leak back
    rows.append(Row("VIXCLS", AS_OF, 45.0, AS_OF + timedelta(days=3), SRC))
    rows = [r for r in rows if not (r.series_id == "VIXCLS" and r.date == AS_OF
                                     and r.value == 18.0)]
    assert regime(AS_OF, source=Fake(rows)).state == "neutral"


def test_unavailable_store_is_neutral_and_stale():
    fake = Fake(error=SourceUnavailable(SRC, "locked", "held by serve"))
    reg = regime(AS_OF, source=fake)
    assert (reg.state, reg.dollar) == ("neutral", "flat")
    assert reg.stale_inputs == ("sec-edgar (locked)",)
    assert reg.sources == ()
    assert read_inputs(AS_OF, source=fake).values["vix"] is None


def test_history_reads_each_date_as_of_that_date():
    fake = Fake(calm())
    dates = [AS_OF - timedelta(days=7), AS_OF]
    out = history(dates, source=fake)
    assert list(out) == dates
    assert [c[3] for c in fake.calls] == dates


def test_weekly_gives_fridays():
    days = weekly(date(2026, 10, 1), date(2026, 10, 31))
    assert days == [date(2026, 10, 2), date(2026, 10, 9), date(2026, 10, 16),
                    date(2026, 10, 23), date(2026, 10, 30)]


# ---------------- walk-forward ----------------


def test_entry_returns_start_after_the_signal_date():
    prices = [(date(2026, 1, d), float(100 + d)) for d in (2, 5, 6, 7, 8)]
    # signal Fri 2 Jan: enter on 5 Jan (strictly after), exit 2 obs later (7 Jan)
    out = entry_returns([date(2026, 1, 2), date(2026, 1, 7)], prices, horizon=2)
    assert out == {date(2026, 1, 2): pytest.approx(107 / 105 - 1)}


def test_entry_returns_skip_signals_with_no_price_soon_after():
    prices = [(date(2026, 1, d), float(100 + d)) for d in (20, 21, 22)]
    # 2 Jan has no price within a week (the series starts 20 Jan): no entry, not 20 Jan's
    out = entry_returns([date(2026, 1, 2), date(2026, 1, 16)], prices, horizon=1)
    assert list(out) == [date(2026, 1, 16)]


def test_entry_returns_inverted_for_idr():
    prices = [(date(2026, 1, d), float(v)) for d, v in ((2, 16000), (5, 16000), (6, 16800))]
    out = entry_returns([date(2026, 1, 2)], prices, horizon=1, invert=True)
    # USD/IDR up 5% = IDR return 16000/16800 − 1
    assert out[date(2026, 1, 2)] == pytest.approx(16000 / 16800 - 1)


def _synthetic(predictive: bool):
    rng = random.Random(7)
    start = date(2015, 1, 2)
    fridays = [start + timedelta(weeks=k) for k in range(400)]
    off = {d: rng.random() < 0.25 for d in fridays}
    prices, p, d = [], 100.0, start
    while d <= fridays[-1] + timedelta(days=60):
        if d.weekday() < 5:
            last_friday = d - timedelta(days=(d.weekday() - 4) % 7)
            drift = -0.004 if predictive and off.get(last_friday) else 0.0005
            p *= 1 + drift + rng.gauss(0, 0.004)
            prices.append((d, p))
        d += timedelta(days=1)
    return off, prices


def test_check_finds_a_real_edge():
    off, prices = _synthetic(predictive=True)
    v = check(off, prices, horizon=5, stride=1, block=1, n_shuffles=200, n_controls=5)
    assert v.passed, v.reason
    assert v.direction == -1
    assert v.rule.mean_on < v.rule.mean_off


def test_check_rejects_noise():
    off, prices = _synthetic(predictive=False)
    v = check(off, prices, horizon=5, stride=1, block=1, n_shuffles=200, n_controls=5)
    assert not v.passed
