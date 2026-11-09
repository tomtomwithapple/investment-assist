"""IDN bonds rule (P31, PLAN S9): real yield (IGSYC 10Y − CPI y/y), IGSYC 10Y−2Y slope, foreign
SBN holdings change (P18), JISDOR trend and the global regime, turned into a call and an entry
plan that may change a stance only once it beats its placebo (P9).

Most tests feed in-memory sources (tidy `Row`s, no store); the last ones run the real PHEI
adapter over its fixture store."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES

from assist.eval.placebo import Verdict
from assist.layers.bonds import (
    IdnBonds,
    bond_returns,
    decide,
    gated_stance,
    idn_bonds,
    rule_verdict,
)
from assist.layers.bonds.idn import PROXY_10Y
from assist.layers.overrides import DBN_CPI, Component, IdnOverrides
from assist.layers.signals import IdnSignals
from assist.layers.types import Regime, Signal
from assist.sources.base import Row, SourceUnavailable
from assist.sources.bpslooker import CPI_YOY
from assist.sources.idxscape import JISDOR
from assist.sources.idxscape_phei import IGSYC_2Y, IGSYC_10Y, PheiSource

AS_OF = date(2026, 10, 23)


class Fake:
    """A source holding rows in memory; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, rows or [], error

    def rows(self, series_ids=None, start=None, end=None, **kw):
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted(
            (r for r in self._rows
             if (series_ids is None or r.series_id in series_ids)
             and (start is None or r.date >= start) and (end is None or r.date <= end)),
            key=lambda r: (r.series_id, r.date),
        )


def _months(end: date, n: int) -> list[date]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return sorted(out)


def _days(end: date, n: int) -> list[date]:
    """`n` weekdays ending on `end`, oldest first."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def cpi_source(level=3.0, now=None, months=72, last=date(2026, 9, 1), bps=True) -> Fake:
    """CPI y/y: `level` for every month, `now` for the newest; bps-looker or dbnomics."""
    dates = _months(last, months)
    values = [level] * (months - 1) + [level if now is None else now]
    sid, name = (CPI_YOY, "bps-looker") if bps else (DBN_CPI, "dbnomics")
    pairs = zip(dates, values, strict=True)
    return Fake(name, [Row(sid, d, v, date(2026, 10, 1), name) for d, v in pairs])


def phei_source(ten=7.0, two=5.5, hist_ten=6.0, months=72, last=date(2026, 10, 22),
                recorded_lag=0) -> Fake:
    """IGSYC 10Y and 2Y: `hist_ten` at each past month-end, `ten`/`two` on the last 5 days."""
    rows = []
    for m in _months(last, months)[:-1]:
        end = (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        rows += [Row(IGSYC_10Y, end, hist_ten, end, "idxscape_phei"),
                 Row(IGSYC_2Y, end, hist_ten - 1.5, end, "idxscape_phei")]
    for d in _days(last, 5):
        rec = d + timedelta(days=recorded_lag)
        rows += [Row(IGSYC_10Y, d, ten, rec, "idxscape_phei"),
                 Row(IGSYC_2Y, d, two, rec, "idxscape_phei")]
    return Fake("idxscape_phei", rows)


def dbn_source(ten=6.0, months=156, last=date(2024, 12, 1), cpi=None) -> Fake:
    """dbnomics' OECD IDN long-term rate (the 10Y proxy), plus optional `idn.cpi.yoy`."""
    rows = [Row(PROXY_10Y, d, ten, None, "dbnomics") for d in _months(last, months)]
    if cpi is not None:
        rows += [Row(DBN_CPI, d, cpi, None, "dbnomics") for d in _months(last, months)]
    return Fake("dbnomics", rows)


def jisdor_source(level=16000.0, last_move=0.0, n=150, last=date(2026, 10, 22)) -> Fake:
    """JISDOR flat at `level` (gently oscillating), the last day moved by `last_move` %."""
    days = _days(last, n)
    values = [level * (1 + 0.002 * ((i % 4) - 1.5)) for i in range(n)]
    values[-1] = level * (1 + last_move / 100)
    pairs = zip(days, values, strict=True)
    return Fake("idxscape", [Row(JISDOR, d, v, d, "idxscape") for d, v in pairs])


def sbn_signal(direction=1, value=5.74e12) -> Signal:
    return Signal("IDN", "bonds", AS_OF, "sbn_non_resident_change", value, direction, "idxscape",
                  f"IDR {value / 1e12:+.2f}T non-resident SBN since 2026-09-23")


def signals(direction: int | None = 1, stale=()) -> IdnSignals:
    sigs = () if direction is None else (sbn_signal(direction),)
    return IdnSignals(AS_OF, sigs, tuple(stale), ("idxscape",))


def regime(state="neutral", dollar="flat") -> Regime:
    return Regime(AS_OF, state, dollar)


def run(**kw) -> IdnBonds:
    args = {"regime": regime(), "signals": signals(), "phei": phei_source(),
            "bps": cpi_source(now=2.0), "dbnomics": dbn_source(), "idxscape": jisdor_source()}
    args.update(kw)
    return idn_bonds(AS_OF, **args)


# ---------------- the decision table ----------------


@pytest.mark.parametrize("real, foreign, breakout, call, stance", [
    (1, 1, False, "enter", "overweight"),
    (1, 0, False, "enter", "overweight"),
    (1, -1, False, "hold", "neutral"),
    (1, 1, True, "hold", "neutral"),
    (0, 1, False, "hold", "neutral"),
    (-1, 0, False, "hold", "neutral"),
    (-1, -1, False, "reduce", "underweight"),
    (-1, 1, True, "reduce", "underweight"),
    (None, 1, False, "no_call", None),
    (1, None, False, "no_call", None),
    (1, 1, None, "no_call", None),
])
def test_decide(real, foreign, breakout, call, stance):
    assert decide(real, foreign, breakout) == (call, stance)


# ---------------- the rule on in-memory sources ----------------


def test_enter_when_real_yield_high_foreign_rising_and_no_breakout():
    out = run()
    assert out.call == "enter" and out.proposed_stance == "overweight"
    assert out.real_yield == pytest.approx(7.0 - 2.0)
    assert out.real_yield_pct == pytest.approx(100.0)
    assert out.entry == {"style": "lump", "tranches": 1, "spacing_days": 0}
    assert out.signal("real_yield").direction == 1
    assert out.signal("sbn_non_resident_change").direction == 1
    assert out.breakout is False
    assert out.ten_year_source == "idxscape_phei"
    assert out.stale_inputs == ()
    assert any(d.startswith("real yield 5.00% (100th pct") for d in out.drivers)


def test_ladder_when_regime_risk_off():
    out = run(regime=regime("risk_off"))
    assert out.call == "enter"
    assert out.entry == {"style": "ladder", "tranches": 3, "spacing_days": 10}
    assert any("risk-off" in r for r in out.risks)


def test_no_regime_ladders_and_is_stale():
    out = run(regime=None)
    assert out.entry["style"] == "ladder"
    assert "regime (not given)" in out.stale_inputs


def test_dollar_up_is_a_risk():
    assert any("dollar" in r for r in run(regime=regime(dollar="up")).risks)


def test_breakout_at_six_month_high_blocks_entry():
    out = run(idxscape=jisdor_source(last_move=1.0))
    assert out.breakout is True
    assert out.call == "hold" and out.proposed_stance == "neutral"
    assert out.entry["style"] == "none"
    assert any("USD/IDR at 6m high" in r for r in out.risks)


def test_jisdor_jump_over_20_days_is_a_breakout():
    days = _days(date(2026, 10, 22), 150)
    vals = [17000.0] * 100 + [15000.0] * 30 + [15000.0 * 1.025] * 20  # +2.5%, below the 6m high
    pairs = zip(days, vals, strict=True)
    src = Fake("idxscape", [Row(JISDOR, d, v, d, "idxscape") for d, v in pairs])
    out = run(idxscape=src)
    assert out.breakout is True
    assert out.signal("jisdor_trend").direction == -1  # IDR weakening
    assert any("+2.5% over 20 days" in r for r in out.risks)


def test_foreign_selling_blocks_entry():
    out = run(signals=signals(-1))
    assert out.call == "hold"


def test_low_real_yield_and_foreign_selling_reduces():
    out = run(phei=phei_source(ten=4.0), bps=cpi_source(now=3.0), signals=signals(-1))
    assert out.real_yield == pytest.approx(1.0)
    assert out.signal("real_yield").direction == -1
    assert out.call == "reduce" and out.proposed_stance == "underweight"


def test_no_foreign_signal_is_no_call():
    out = run(signals=signals(None, stale=("idxscape SBN.TOTAL.non_resident (no data)",
                                           "kseistat (missing)")))
    assert out.call == "no_call" and out.proposed_stance is None
    assert out.entry["style"] == "none"
    assert "idxscape SBN.TOTAL.non_resident (no data)" in out.stale_inputs
    assert "kseistat (missing)" not in out.stale_inputs  # a stocks input


def test_missing_jisdor_store_is_no_call():
    out = run(idxscape=Fake("idxscape", error="locked"))
    assert out.call == "no_call"
    assert "idxscape (locked)" in out.stale_inputs


def test_slope_is_10y_minus_2y_on_the_latest_day():
    out = run(phei=phei_source(ten=7.0, two=5.25))
    assert out.slope == pytest.approx(1.75)
    assert out.signal("curve_slope").direction == 1
    assert any("10Y−2Y slope +1.75pt" in d for d in out.drivers)
    inverted = run(phei=phei_source(ten=5.0, two=5.5))
    assert inverted.signal("curve_slope").direction == -1


def test_raw_phei_values_never_reach_drivers_or_risks():
    out = run(phei=phei_source(ten=7.1677, two=5.6250))
    text = " ".join([*out.drivers, *out.risks, *(s.detail for s in out.signals)])
    assert "7.1677" not in text and "7.17" not in text and "5.62" not in text
    assert out.local_only is False  # derived numbers only


def test_cpi_comes_from_the_overrides_inputs_when_given():
    cpi = Row(CPI_YOY, date(2026, 9, 1), 2.5, date(2026, 10, 1), "bps-looker")
    bi = Component("bi_rate", "bisfetcher", "WS_CBPOL.M.ID", 1.0, 1,
                   Row("WS_CBPOL.M.ID", date(2026, 9, 1), 5.75, None, "bisfetcher"),
                   "BI rate 5.75% on 2026-09-01, +1.00 since 2026-03-01")
    ov = IdnOverrides(AS_OF, (), (bi,), {}, {"cpi_yoy": cpi}, (), ("bps-looker",))
    out = run(overrides=ov)
    assert out.real_yield == pytest.approx(7.0 - 2.5)
    assert any(d.startswith("BI rate 5.75%") for d in out.drivers)


def test_percentile_window_is_named():
    out = run()
    assert out.real_window == "72 months 2020-10..2026-09"
    assert "72 months 2020-10..2026-09" in out.signal("real_yield").detail


def test_short_history_falls_back_to_absolute_thresholds():
    out = run(phei=phei_source(months=6), bps=cpi_source(months=6, now=2.0), dbnomics=dbn_source(
        months=1))
    assert out.real_yield_pct is None
    assert out.signal("real_yield").direction == 1  # 5.0% >= 3.0% absolute
    assert "absolute" in out.signal("real_yield").detail


def test_dbnomics_cpi_fills_older_history():
    out = run(bps=cpi_source(months=12, now=2.0),
              dbnomics=dbn_source(last=date(2026, 9, 1), months=156, cpi=3.0))
    assert out.real_window.startswith("120 months")


def test_point_in_time_ignores_rows_not_yet_known():
    late = phei_source(ten=9.0, last=date(2026, 10, 30))  # after as_of
    out = run(phei=late)
    assert out.real_yield == pytest.approx(6.0 - 2.0)  # month-end history only
    unknown = phei_source(ten=9.0, recorded_lag=30)  # recorded after as_of, inside the lag
    assert run(phei=unknown).real_yield == pytest.approx(6.0 - 2.0)


# ---------------- the proxy when the curve is missing ----------------


def test_phei_missing_falls_back_to_dbnomics_proxy():
    out = run(phei=Fake("idxscape_phei", error="missing"),
              dbnomics=dbn_source(ten=8.0, last=date(2026, 8, 1)))
    assert out.ten_year_source == "dbnomics proxy"
    assert out.real_yield == pytest.approx(8.0 - 2.0)
    assert out.slope is None and out.signal("curve_slope") is None
    assert "idxscape_phei (missing)" in out.stale_inputs
    assert any("proxy" in s and PROXY_10Y in s for s in out.stale_inputs)
    assert any("slope unavailable" in s for s in out.stale_inputs)
    assert any("proxy" in d for d in out.drivers)
    assert out.call == "enter"


def test_stale_proxy_reports_but_makes_no_call():
    out = run(phei=Fake("idxscape_phei", error="missing"), dbnomics=dbn_source(ten=8.0))
    assert out.real_yield == pytest.approx(6.0)  # 2024-12 10Y − newest CPI
    assert out.signal("real_yield").direction is None or out.call == "no_call"
    assert out.call == "no_call"
    assert any("last 2024-12-01" in s for s in out.stale_inputs)


def test_no_ten_year_anywhere_is_no_call():
    out = run(phei=Fake("idxscape_phei", error="missing"),
              dbnomics=Fake("dbnomics", error="locked"))
    assert out.real_yield is None and out.call == "no_call"
    assert {"idxscape_phei (missing)", "dbnomics (locked)"} <= set(out.stale_inputs)


def test_no_cpi_is_no_call():
    out = run(bps=Fake("bps-looker", error="missing"), dbnomics=dbn_source())
    assert out.real_yield is None and out.call == "no_call"
    assert "bps-looker (missing)" in out.stale_inputs


# ---------------- placebo gate ----------------


def _verdict(passed: bool) -> Verdict:
    from assist.eval.placebo import Edge
    e = Edge(20, 20, 0.02, 0.0, 0.02, 2.5 if passed else 0.5, True)
    return Verdict(passed, "beats placebo" if passed else "t-stat 0.50 below 2.0", e, e.t, 0.01,
                   0.1, (), 1, 10, 2, 3, 3, 1, 2.0, 0.05)


def test_gate_keeps_base_stance_without_a_passing_verdict():
    out = run()
    assert gated_stance("neutral", out, None)[0] == "neutral"
    stance, note = gated_stance("neutral", out, _verdict(False))
    assert stance == "neutral" and "not applied" in note and "t-stat 0.50" in note
    stance, note = gated_stance("neutral", out, _verdict(True))
    assert stance == "overweight" and "applied" in note


def test_gate_with_no_call_keeps_base():
    out = run(signals=signals(None))
    assert gated_stance("underweight", out, _verdict(True))[0] == "underweight"


def test_gate_applies_a_reduce_only_on_a_passed_reduce_verdict():
    # P74: a passed enter verdict never moves a reduce proposal
    import dataclasses
    red = dataclasses.replace(run(), call="reduce", proposed_stance="underweight")
    stance, note = gated_stance("neutral", red, _verdict(True))
    assert (stance, note) == ("neutral",
                              "bonds rule proposes underweight; not applied: reduce side untested")
    stance, note = gated_stance("neutral", red, _verdict(True), reduce_verdict=_verdict(False))
    assert stance == "neutral" and "reduce side t-stat 0.50 below 2.0" in note
    stance, _ = gated_stance("neutral", red, _verdict(False), reduce_verdict=_verdict(True))
    assert stance == "underweight"
    hold = dataclasses.replace(run(), call="hold", proposed_stance="neutral")
    assert gated_stance("underweight", hold, _verdict(True))[0] == "underweight"


def test_bond_returns_carry_minus_duration():
    ys = [(date(2024, m, 1), y) for m, y in ((1, 7.0), (2, 7.0), (3, 7.0), (4, 6.5))]
    out = dict(bond_returns(ys, horizon=3, duration=7.0))
    assert list(out) == [date(2024, 1, 1)]
    assert out[date(2024, 1, 1)] == pytest.approx(0.07 * 3 / 12 + 7.0 * 0.005)


@pytest.mark.parametrize("n", [0, 1, 2, 3])
def test_bond_returns_too_few_points_is_empty(n):
    # 2 points with horizon 3 once sliced pts[:-1] (a negative stop) and indexed past the end
    ys = [(date(2024, m, 1), 7.0) for m in range(1, n + 1)]
    assert bond_returns(ys, horizon=3) == []


def test_rule_verdict_passes_a_rule_that_works_and_fails_noise():
    months = _months(date(2025, 12, 1), 180)
    ys, calls, y = [], {}, 7.0
    for i, m in enumerate(months):
        enter = (i // 3) % 2 == 0
        calls[m] = "enter" if enter else "hold"
        ys.append((m, y))
        y += -0.1 if enter else 0.1  # yields fall after an enter call
    good = rule_verdict(calls, ys, horizon=1, n_shuffles=200, n_controls=5)
    assert good.passed
    noise = rule_verdict({m: "enter" if i % 2 else "hold" for i, m in enumerate(months)},
                         [(m, 7.0) for m in months], horizon=1, n_shuffles=200, n_controls=5)
    assert not noise.passed


def test_rule_verdict_skips_no_calls():
    months = _months(date(2025, 12, 1), 12)
    v = rule_verdict({m: "no_call" for m in months}, [(m, 7.0) for m in months], horizon=1,
                     n_shuffles=10, n_controls=2)
    assert not v.passed and "insufficient" in v.reason


# ---------------- the real PHEI adapter over its fixture store ----------------


def _phei_store(path: Path) -> Path:
    con = duckdb.connect(str(path))
    try:
        con.execute((FIXTURES / "idxscape_phei" / "schema.sql").read_text())
        con.execute((FIXTURES / "idxscape_phei" / "data.sql").read_text())
    finally:
        con.close()
    return path


def test_real_phei_adapter_fixture(tmp_path):
    src = PheiSource(_phei_store(tmp_path / "idxscape.duckdb"))
    out = idn_bonds(date(2026, 10, 13), regime=regime(), signals=signals(), phei=src,
                    bps=cpi_source(now=2.0, last=date(2026, 9, 1)), dbnomics=dbn_source(),
                    idxscape=jisdor_source(last=date(2026, 10, 12)))
    assert out.ten_year_source == "idxscape_phei"
    assert out.real_yield == pytest.approx(7.1677 - 2.0)
    assert out.slope == pytest.approx(7.1677 - 5.625)
    text = " ".join([*out.drivers, *out.risks])
    assert "7.1677" not in text and "7.17" not in text


def test_real_phei_adapter_flags_gap_filled_day(tmp_path):
    src = PheiSource(_phei_store(tmp_path / "idxscape.duckdb"))
    out = idn_bonds(date(2026, 10, 11), regime=regime(), signals=signals(), phei=src,
                    bps=cpi_source(now=2.0, last=date(2026, 9, 1)), dbnomics=dbn_source(),
                    idxscape=jisdor_source(last=date(2026, 10, 9)))
    # 10-09 came from 10-12's Yesterday column, fetched after 10-11: not yet known, so 10-08 is used
    assert out.slope == pytest.approx(7.15 - 5.55)
    out = idn_bonds(date(2026, 10, 14), regime=regime(), signals=signals(), phei=src,
                    bps=cpi_source(now=2.0, last=date(2026, 9, 1)), dbnomics=dbn_source(),
                    idxscape=jisdor_source(last=date(2026, 10, 13)))
    assert not any("Yesterday column" in s for s in out.stale_inputs)  # newest day 10-12 is its own
