"""Home (IDN) regime rule (P71, PLAN S52): hand-set points on the four P70 inputs (open question
7), risk_off at 2 points or more, else neutral; an input counts only when its newest point is at
most 7 days old. `HOME_SHIFT_ADOPTED` stays False unless the walk-forward passes on JCI (open
question 8). Plus the history / check pattern of `regime.py`, the ladder-against-lump diagnostic
and the per-input diagnostics.

Inputs are built directly (`HomeInputs`) or from in-memory sources; the 2026-10-16 case reads
tests/fixtures/home/jci.csv (idxscape COMPOSITE 2026-08-26 → 11-05)."""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta

import pytest
from helpers import FIXTURES

from assist.eval.placebo import Edge, Verdict
from assist.layers import home_regime as hr
from assist.layers.home_inputs import FEATURES, HomeInputs, HomeSources
from assist.sources.base import Row
from assist.sources.idxmethod import JCI

JCI_DD, FLOW_Z, USDIDR, SBN = FEATURES
DAY = date(2026, 10, 16)


def _inp(as_of: date = DAY, age: int = 0, **values: float) -> HomeInputs:
    """Inputs on `as_of`, each named value dated `age` days back (the others absent)."""
    vals = dict.fromkeys(FEATURES)
    vals.update(values)
    last = {f: as_of - timedelta(days=age) for f in values}
    return HomeInputs(as_of, vals, last, (), ("test",))


# ---------------- the fixed numbers (open question 7) ----------------


def test_thresholds_are_open_question_7():
    assert hr.JCI_POINTS == ((-12.0, 2), (-7.0, 1))
    assert hr.FLOW_Z_AT == -1.5
    assert hr.USDIDR_POINTS == ((4.0, 2), (2.0, 1))
    assert hr.SBN_AT == -1.5
    assert hr.STATE_AT == 2
    assert timedelta(days=7) == hr.MAX_AGE
    assert hr.HOME_SHIFT_ADOPTED is False


@pytest.mark.parametrize(("dd", "pts"), [(0.0, 0), (-6.99, 0), (-7.0, 1), (-11.99, 1),
                                         (-12.0, 2), (-18.8, 2)])
def test_jci_points(dd, pts):
    assert hr.points(JCI_DD, dd) == pts


@pytest.mark.parametrize(("z", "pts"), [(0.0, 0), (-1.49, 0), (-1.5, 1), (-3.1, 1), (2.0, 0)])
def test_flow_points(z, pts):
    assert hr.points(FLOW_Z, z) == pts


@pytest.mark.parametrize(("move", "pts"), [(-5.0, 0), (1.99, 0), (2.0, 1), (3.99, 1), (4.0, 2),
                                           (9.0, 2)])
def test_usdidr_points(move, pts):
    assert hr.points(USDIDR, move) == pts


@pytest.mark.parametrize(("chg", "pts"), [(0.0, 0), (-1.49, 0), (-1.5, 1), (-4.0, 1), (3.0, 0)])
def test_sbn_points(chg, pts):
    assert hr.points(SBN, chg) == pts


# ---------------- the state ----------------


def test_no_points_is_neutral():
    r = hr.classify(_inp(**{JCI_DD: -1.0, FLOW_Z: 0.3, USDIDR: 0.5, SBN: 1.0}))
    assert (r.state, r.points, r.drivers) == ("neutral", 0, ())
    assert r.by_input == {JCI_DD: 0, FLOW_Z: 0, USDIDR: 0, SBN: 0}


def test_one_point_is_neutral():
    r = hr.classify(_inp(**{JCI_DD: -8.0, USDIDR: 0.5}))
    assert (r.state, r.points) == ("neutral", 1)
    assert len(r.drivers) == 1 and "JCI" in r.drivers[0]


def test_two_points_from_two_inputs_is_risk_off():
    r = hr.classify(_inp(**{JCI_DD: -8.0, FLOW_Z: -1.6}))
    assert (r.state, r.points) == ("risk_off", 2)
    assert len(r.drivers) == 2


def test_one_input_alone_can_reach_risk_off():
    assert hr.classify(_inp(**{USDIDR: 4.2})).state == "risk_off"
    assert hr.classify(_inp(**{JCI_DD: -12.5})).state == "risk_off"


def test_there_is_no_home_risk_on():
    r = hr.classify(_inp(**{JCI_DD: 0.0, FLOW_Z: 3.0, USDIDR: -6.0, SBN: 5.0}))
    assert r.state == "neutral"
    assert hr.STATES == ("risk_off", "neutral")


# ---------------- the 7-day freshness rule ----------------


def test_input_seven_days_old_counts():
    r = hr.classify(_inp(age=7, **{JCI_DD: -13.0}))
    assert (r.state, r.points, r.by_input[JCI_DD]) == ("risk_off", 2, 2)


def test_input_eight_days_old_scores_nothing():
    r = hr.classify(_inp(age=8, **{JCI_DD: -13.0, USDIDR: 5.0}))
    assert (r.state, r.points) == ("neutral", 0)
    assert r.by_input[JCI_DD] is None and r.by_input[USDIDR] is None
    assert r.values[JCI_DD] == -13.0  # kept for the page, just not counted


def test_stale_sbn_does_not_tip_a_one_point_jci():
    inp = HomeInputs(DAY, {JCI_DD: -8.0, FLOW_Z: None, USDIDR: 0.1, SBN: -3.0},
                     {JCI_DD: DAY, USDIDR: DAY, SBN: date(2026, 9, 4)},
                     ("idxscape SBN.TOTAL.non_resident (last 2026-09-04)",), ("test",))
    r = hr.classify(inp)
    assert (r.state, r.points, r.by_input[SBN]) == ("neutral", 1, None)
    assert r.stale_inputs == inp.stale_inputs


def test_absent_inputs_are_none_and_score_nothing():
    r = hr.classify(_inp())
    assert (r.state, r.points) == ("neutral", 0)
    assert set(r.by_input.values()) == {None}


# ---------------- 2026-10-06 → 10-16 on the real JCI fixture ----------------


class Fake:
    def __init__(self, name: str, rows: list[Row] | None = None):
        self.name, self._rows = name, rows or []

    def rows(self, series_ids=None, start=None, end=None, **kw):
        return sorted((r for r in self._rows
                       if (series_ids is None or r.series_id in series_ids)
                       and (start is None or r.date >= start) and (end is None or r.date <= end)),
                      key=lambda r: (r.series_id, r.date))


def _sources() -> HomeSources:
    with (FIXTURES / "home" / "jci.csv").open() as f:
        rows = [Row(JCI, date.fromisoformat(r["date"]), float(r["close"]), None,
                    "idxscape+idx-method") for r in csv.DictReader(f)]
    return HomeSources(jci=Fake("idxscape+idx-method", rows), idxscape=Fake("idxscape"),
                       usdidr=Fake("MAS+JISDOR"))


def test_2026_10_16_jci_alone_is_risk_off():
    r = hr.home_regime(DAY, _sources())
    assert r.values[JCI_DD] == pytest.approx(-18.79, abs=0.01)
    assert (r.state, r.points, r.by_input[JCI_DD]) == ("risk_off", 2, 2)
    assert r.drivers == ("JCI -18.8% vs 20d high (2)",)


def test_2026_10_06_one_point_is_neutral():
    r = hr.home_regime(date(2026, 10, 6), _sources())
    assert r.values[JCI_DD] == pytest.approx(-7.27, abs=0.01)
    assert (r.state, r.points) == ("neutral", 1)


def test_history_matches_one_call_per_date():
    days = [date(2026, 10, 2), date(2026, 10, 9), DAY, date(2026, 10, 23)]
    hist = hr.history(days, _sources())
    assert list(hist) == days
    for d in days:
        assert hr.classify(hist[d]) == hr.home_regime(d, _sources())


# ---------------- HOME_SHIFT_ADOPTED (open question 8) ----------------


def _verdict(passed: bool) -> Verdict:
    e = Edge(12, 40, -0.02, 0.01, -0.03, 2.5 if passed else 0.4, True)
    return Verdict(passed, "x", e, e.t, 0.01 if passed else 0.4, 0.1, (0.1,), 1, 100, 5, 4, 4,
                   -1, 2.0, 0.05)


def test_shift_not_adopted_on_a_failing_jci_check():
    assert hr.shift_adopted(_verdict(False)) is False
    assert hr.shift_adopted(_verdict(False), idr=_verdict(True)) is False


def test_shift_adopted_only_on_a_passing_jci_check():
    assert hr.shift_adopted(_verdict(True)) is True
    assert hr.shift_adopted(_verdict(True), idr=_verdict(False)) is True


# ---------------- check (regime.py's harness) ----------------


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


def test_check_finds_a_planted_edge_and_rejects_noise():
    off, prices = _synthetic(predictive=True)
    v = hr.check(off, prices, horizon=5, stride=1, block=1, n_shuffles=200, n_controls=5)
    assert v.passed, v.reason
    assert v.direction == -1
    off, prices = _synthetic(predictive=False)
    assert not hr.check(off, prices, horizon=5, stride=1, block=1, n_shuffles=200,
                        n_controls=5).passed


# ---------------- ladder vs lump ----------------


def test_ladder_against_lump_on_a_falling_price():
    # Friday signal 2026-01-02; closes every weekday, falling 1 a day from 100
    days = [date(2026, 1, 5) + timedelta(days=k) for k in range(40)]
    prices = [(d, 100.0 - i) for i, d in enumerate(days)]
    out = hr.ladder_vs_lump([date(2026, 1, 2)], prices)
    # lump: first close after the signal (01-05, 100); tranches on the first close on or after
    # 01-05, 01-15, 01-25: 100, 90, 80; buy fill = harmonic mean of the three
    fill = 3 / (1 / 100 + 1 / 90 + 1 / 80)
    assert out[date(2026, 1, 2)] == pytest.approx(100 * (fill / 100 - 1))


def test_ladder_needs_its_last_tranche():
    prices = [(date(2026, 1, 5) + timedelta(days=k), 100.0) for k in range(15)]
    assert hr.ladder_vs_lump([date(2026, 1, 2)], prices) == {}


# ---------------- per-input diagnostics ----------------


def test_classify_with_an_input_dropped():
    inp = _inp(**{JCI_DD: -8.0, FLOW_Z: -1.6})
    assert hr.classify(inp).state == "risk_off"
    r = hr.classify(inp, drop=(FLOW_Z,))
    assert (r.state, r.points, r.by_input[FLOW_Z]) == ("neutral", 1, None)


def test_input_counts():
    regs = [hr.classify(_inp(**{JCI_DD: -13.0, USDIDR: 2.5})),
            hr.classify(_inp(**{JCI_DD: -8.0})),
            hr.classify(_inp(age=9, **{JCI_DD: -8.0}))]
    c = hr.input_counts(regs)
    assert c[JCI_DD] == {"counted": 2, "1": 1, "2": 1}
    assert c[USDIDR] == {"counted": 1, "1": 1, "2": 0}
    assert c[FLOW_Z] == {"counted": 0, "1": 0, "2": 0}
