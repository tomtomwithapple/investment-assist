"""Paper tracking (PLAN S13): stance-implied IDN allocation vs a fixed IDR 60/40 benchmark (60%
JCI, 40% SBN leg), marked weekly, scored per model fingerprint and never across fingerprints."""

from datetime import date, timedelta

import pytest

from assist import paper as pp
from assist.journal import Journal
from assist.sources.base import Row, SourceUnavailable

FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64

FRI = date(2026, 1, 2)  # a Friday


def _fridays(n, start=FRI):
    return [start + timedelta(weeks=i) for i in range(n)]


class FakeSource:
    def __init__(self, name, rows=None, error=None):
        self.name, self._rows, self.error, self.calls = name, rows or [], error, []

    def rows(self, series_ids=None, start=None, end=None):
        self.calls.append(tuple(series_ids or ()))
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return [r for r in self._rows if series_ids is None or r.series_id in series_ids]


def _jci_rows(closes, start=FRI, last=None):
    days = _fridays(len(closes), start)
    last = last or days[-1]
    return [Row("JKSE", d, c, last, "idx-method") for d, c in zip(days, closes, strict=True)]


def _flat_bond(n, y=7.0, start=FRI):
    return pp.YieldBondLeg([(d, y) for d in _fridays(n, start)], label="test flat 10Y")


# ---------------- grid and legs ----------------


def test_fridays_grid():
    g = pp.fridays(date(2026, 1, 1), date(2026, 1, 20))
    assert g == [date(2026, 1, 2), date(2026, 1, 9), date(2026, 1, 16)]
    assert all(d.weekday() == 4 for d in g)


def test_jci_leg_weekly_returns_from_last_close_on_or_before():
    leg = pp.JciLeg(_jci_rows([100.0, 110.0, 99.0]))
    grid = _fridays(3)
    r = leg.returns(grid)
    assert r[grid[1]] == pytest.approx(0.10)
    assert r[grid[2]] == pytest.approx(-0.10)
    assert grid[0] not in r  # the first grid day has no week behind it
    assert leg.valid_through == grid[2]


def test_jci_leg_is_stale_after_its_last_close_not_carried_forward():
    leg = pp.JciLeg(_jci_rows([100.0, 101.0]))
    grid = _fridays(4)
    r = leg.returns(grid)
    assert r[grid[1]] == pytest.approx(0.01)
    assert r[grid[2]] is None and r[grid[3]] is None  # frozen: not invented
    assert "JCI" in leg.stale_reason(grid[2])


def test_jci_leg_reads_p3_jci_function_and_reports_missing():
    src = FakeSource("idx-method", _jci_rows([1.0, 2.0]))
    leg = pp.JciLeg.from_source(src)
    assert src.calls == [("JKSE",)]
    assert leg.valid_through == _fridays(2)[1]
    gone = pp.JciLeg.from_source(FakeSource("idx-method", error="missing"))
    assert gone.stale_inputs == ["idx-method (missing)"]
    assert gone.returns(_fridays(3))[_fridays(3)[2]] is None


def test_par_price_and_flat_yield_earns_carry_only():
    assert pp.bond_price(0.07, 0.07, 10) == pytest.approx(1.0)
    leg = _flat_bond(3, 7.0)
    r = leg.returns(_fridays(3))
    assert r[_fridays(3)[1]] == pytest.approx(0.07 / 52)


def test_synthetic_bond_loses_when_yield_rises():
    days = _fridays(2)
    leg = pp.YieldBondLeg([(days[0], 7.0), (days[1], 8.0)], label="x")
    r = leg.returns(days)[days[1]]
    # 10Y par bond, +100bp: about -6.8% price, plus a week of 7% carry
    assert r == pytest.approx(pp.bond_price(0.07, 0.08, 10) - 1 + 0.07 / 52)
    assert -0.07 < r < -0.06


def test_bond_leg_prefers_igsyc_10y_and_labels_it_synthetic():
    days = _fridays(3)
    phei = FakeSource("idxscape_phei", [Row("IGSYC.10", d, 6.5, d, "idxscape_phei") for d in days])
    dbn = FakeSource("dbnomics", [])
    leg = pp.bond_leg(phei=phei, dbn=dbn)
    assert leg.name == "IGSYC.10"
    assert "synthetic" in leg.label and "IGSYC 10Y" in leg.label
    assert leg.stale_inputs == []
    assert dbn.calls == []
    assert leg.valid_through == days[-1]


def test_bond_leg_falls_back_to_dbnomics_long_rate_at_month_end():
    phei = FakeSource("idxscape_phei", error="missing")
    dbn = FakeSource("dbnomics", [
        Row("idn.rate.long", date(2024, 11, 1), 6.8, None, "dbnomics"),
        Row("idn.rate.long", date(2024, 12, 1), 7.0, None, "dbnomics"),
    ])
    leg = pp.bond_leg(phei=phei, dbn=dbn)
    assert leg.name == "idn.rate.long"
    assert "dbnomics" in leg.label and "synthetic" in leg.label and "monthly" in leg.label
    assert leg.stale_inputs == ["idxscape_phei (missing)"]
    # a monthly average is known at month end, not on the 1st (no look-ahead)
    assert leg.yields == [(date(2024, 11, 30), 6.8), (date(2024, 12, 31), 7.0)]
    assert leg.valid_through == date(2024, 12, 31)
    r = leg.returns(pp.fridays(date(2024, 12, 6), date(2025, 1, 10)))
    assert r[date(2024, 12, 13)] == pytest.approx(0.068 / 52)  # still November's yield
    assert r[date(2025, 1, 3)] is not None  # Dec 27 → Jan 3 straddles Dec 31: priced
    assert r[date(2025, 1, 10)] is None  # past the last month end: stale


def test_bond_leg_empty_igsyc_also_falls_back():
    phei = FakeSource("idxscape_phei", [])
    dbn = FakeSource("dbnomics", [Row("idn.rate.long", date(2024, 1, 1), 6.0, None, "dbnomics")])
    leg = pp.bond_leg(phei=phei, dbn=dbn)
    assert leg.name == "idn.rate.long"
    assert leg.stale_inputs == ["idxscape_phei (no IGSYC 10Y rows)"]


def test_bond_leg_with_both_sources_down_is_empty_and_named():
    leg = pp.bond_leg(phei=FakeSource("idxscape_phei", error="missing"),
                      dbn=FakeSource("dbnomics", error="locked"))
    assert leg.yields == [] and leg.valid_through is None
    assert leg.stale_inputs == ["idxscape_phei (missing)", "dbnomics (locked)"]
    assert set(leg.returns(_fridays(2)).values()) == {None}


# ---------------- allocation ----------------


def test_implied_weights_tilt_from_60_40():
    assert pp.implied_weights("neutral", "neutral") == {"stocks": 60.0, "bonds": 40.0,
                                                         "cash": 0.0}
    assert pp.implied_weights("underweight", "overweight") == {"stocks": 50.0, "bonds": 50.0,
                                                              "cash": 0.0}
    w = pp.implied_weights("overweight", "overweight")  # 70 + 50 > 100: scaled down
    assert w["stocks"] + w["bonds"] == pytest.approx(100.0) and w["cash"] == 0.0
    assert w["stocks"] / w["bonds"] == pytest.approx(70 / 50)
    assert pp.implied_weights("avoid", "neutral") == {"stocks": 0.0, "bonds": 40.0, "cash": 60.0}


# ---------------- benchmark ----------------


def test_benchmark_marks_are_60_40_rebalanced_weekly_and_stale_marks_carry_no_return():
    jci = pp.JciLeg(_jci_rows([100.0, 110.0, 121.0]))
    bond = _flat_bond(4, 5.2)
    marks = pp.benchmark_marks(jci, bond, _fridays(4))
    assert len(marks) == 3
    m = marks[0]
    assert m.week_start == FRI and m.week_end == _fridays(2)[1]
    assert m.benchmark == pytest.approx(0.6 * 0.10 + 0.4 * 0.052 / 52)
    assert m.stale == []
    last = marks[-1]
    assert last.jci is None and last.benchmark is None
    assert any("JCI" in s for s in last.stale)
    summ = pp.summarize([m.benchmark for m in marks])
    assert summ["weeks"] == 2 and summ["stale_weeks"] == 1
    assert summ["cumulative"] == pytest.approx((1 + marks[0].benchmark) * (1 + marks[1].benchmark)
                                               - 1)


# ---------------- segments ----------------


def _stance(j, fp, asset, stance, as_of):
    out = {"subject": "IDN", "asset": asset, "stance": stance, "model_fingerprint": fp,
           "as_of": as_of.isoformat()}
    return j.record(kind="stance", fingerprint=fp, inputs={}, outputs=out, subject="IDN",
                    asset=asset, as_of=as_of)


def test_segments_scored_separately_and_never_pooled(tmp_path):
    j = Journal(tmp_path)
    d = _fridays(8)
    _stance(j, FP_A, "stocks", "overweight", d[0])
    _stance(j, FP_A, "bonds", "neutral", d[0])
    _stance(j, FP_B, "stocks", "avoid", d[4])
    j.record(kind="candidate", fingerprint=FP_B, inputs={}, outputs={}, as_of=d[4])  # ignored
    jci = pp.JciLeg(_jci_rows([100, 102, 104, 103, 105, 107, 106, 110]))
    bond = _flat_bond(8, 7.0)
    rep = pp.paper_track(journal=j, jci=jci, bond=bond, until=d[-1])

    a, b = rep.segments
    assert (a.fingerprint, b.fingerprint) == (FP_A, FP_B)
    # A rules weeks whose start is in [d0, d4); B from d4 on
    assert [m.week_start for m in a.marks] == d[0:4]
    assert [m.week_start for m in b.marks] == d[4:7]
    assert a.decisions == 2 and b.decisions == 1
    w = a.marks[0].weights  # 70 + 40 > 100: scaled to 100, ratio kept
    assert w["stocks"] / w["bonds"] == pytest.approx(70 / 40)
    # B has no bonds stance of its own: held at benchmark, said so; A's bonds stance not reused
    assert b.marks[0].weights == {"stocks": 0.0, "bonds": 40.0, "cash": 60.0}
    assert any("bonds" in n and "benchmark" in n for n in b.notes)
    # each segment's cumulative is over its own weeks only
    ra = [m.portfolio for m in a.marks]
    assert a.portfolio_return == pytest.approx(pp.summarize(ra)["cumulative"])
    assert a.weeks == 4 and b.weeks == 3
    assert a.active_return == pytest.approx(a.portfolio_return - a.benchmark_return)


def test_stance_known_only_from_week_start_no_lookahead(tmp_path):
    j = Journal(tmp_path)
    d = _fridays(4)
    _stance(j, FP_A, "stocks", "neutral", d[0])
    _stance(j, FP_A, "stocks", "avoid", d[1] + timedelta(days=2))  # Sunday after d1
    rep = pp.paper_track(journal=j, jci=pp.JciLeg(_jci_rows([100, 101, 102, 103])),
                         bond=_flat_bond(4), until=d[-1])
    (seg,) = rep.segments
    assert [m.weights["stocks"] for m in seg.marks] == [60.0, 60.0, 0.0]


def test_weeks_past_frozen_jci_are_stale_and_excluded(tmp_path):
    j = Journal(tmp_path)
    d = _fridays(5)
    _stance(j, FP_A, "stocks", "neutral", d[0])
    rep = pp.paper_track(journal=j, jci=pp.JciLeg(_jci_rows([100, 101, 102])),
                         bond=_flat_bond(5), until=d[-1])
    (seg,) = rep.segments
    assert seg.weeks == 2 and seg.stale_weeks == 2
    assert all(m.portfolio is None and m.stale for m in seg.marks[2:])


def test_identical_stances_track_the_benchmark(tmp_path):
    j = Journal(tmp_path)
    d = _fridays(5)
    _stance(j, FP_A, "stocks", "neutral", d[0])
    _stance(j, FP_A, "bonds", "neutral", d[0])
    rep = pp.paper_track(journal=j, jci=pp.JciLeg(_jci_rows([100, 97, 99, 104, 101])),
                         bond=_flat_bond(5), until=d[-1])
    (seg,) = rep.segments
    assert seg.active_return == pytest.approx(0.0, abs=1e-12)
    assert seg.tracking_error == pytest.approx(0.0, abs=1e-12)
    assert seg.hit_rate == 0.0


def test_no_journal_gives_benchmark_marks_only(tmp_path):
    d = _fridays(4)
    rep = pp.paper_track(journal=Journal(tmp_path / "none"),
                         jci=pp.JciLeg(_jci_rows([100, 101, 102, 103])),
                         bond=_flat_bond(4), start=d[0], until=d[-1])
    assert rep.segments == []
    assert len(rep.benchmark) == 3
    assert any("no stance records" in n for n in rep.notes)
    out = rep.to_dict()
    assert out["disclaimer"] and out["legs"]["bonds"] == "test flat 10Y"
    assert out["benchmark_summary"]["weeks"] == 3


def test_report_names_stale_inputs_and_frozen_jci():
    d = _fridays(3)
    jci = pp.JciLeg(_jci_rows([100.0, 101.0]))
    bond = pp.bond_leg(phei=FakeSource("idxscape_phei", error="missing"),
                       dbn=FakeSource("dbnomics", [
                           Row("idn.rate.long", date(2025, 12, 1), 6.0, None, "dbnomics")]))
    rep = pp.paper_track(records=[], jci=jci, bond=bond, start=d[0], until=d[-1])
    assert "idxscape_phei (missing)" in rep.stale_inputs
    assert any(s.startswith("JCI") for s in rep.stale_inputs)
