"""Paper tracking (PLAN S13, S40): stance-implied allocation vs the IDR benchmark 48% JCI / 32%
SBN leg / 20% US stocks in IDR (the legacy 60/40 for segments before S39), marked weekly, scored
per model fingerprint and never across fingerprints. No store is opened: every leg is given."""

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


def _flat_us(n, start=FRI, usd=500.0, fx=16000.0):
    days = _fridays(n, start)
    return pp.UsLeg([(d, usd) for d in days], [(d, fx) for d in days], label="test US leg")


LEGACY = pp.LEGACY_BENCHMARK_PCT


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
    assert leg.daily


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


def _daily(start, n):
    return [start + timedelta(days=i) for i in range(n)]


def test_daily_bond_capture_gap_while_idx_traded_leaves_weeks_unscored():
    # JCI trades every day 2026-10-09 .. 11-06; IGSYC captured to 10-21, then 11-04 .. 11-06
    days = _daily(date(2026, 10, 9), 29)
    jci = pp.JciLeg([Row("JKSE", d, 100.0 + i, None, "idxscape") for i, d in enumerate(days)])
    caught = [d for d in days if d <= date(2026, 10, 21) or d >= date(2026, 11, 4)]
    bond = pp.YieldBondLeg([(d, 7.0) for d in caught], label="x", name="IGSYC.10", daily=True)
    grid = pp.fridays(date(2026, 10, 9), date(2026, 11, 6))
    marks = pp.benchmark_marks(jci, bond, grid, pct=LEGACY)
    got = {m.week_end: m.benchmark is not None for m in marks}
    # 10-16 scored; 10-23 and 10-30 lag (yield 10-21); 11-06 starts from the lagging 10-30 mark
    assert got == {date(2026, 10, 16): True, date(2026, 10, 23): False,
                   date(2026, 10, 30): False, date(2026, 11, 6): False}
    m23 = next(m for m in marks if m.week_end == date(2026, 10, 23))
    assert m23.sbn is None and m23.stale == [
        "SBN leg: no IGSYC.10 yield on 2026-10-23's last IDX day (last 2026-10-21)"]
    # the same yields as a monthly-style leg (daily=False) carry forward as before
    loose = pp.YieldBondLeg([(d, 7.0) for d in caught], label="x", name="IGSYC.10")
    assert all(m.benchmark is not None for m in pp.benchmark_marks(jci, loose, grid, pct=LEGACY))


def test_daily_bond_holiday_shuts_both_markets_and_is_not_a_gap():
    # Friday 10-23 is a holiday for both: last JCI close and last yield are both Thursday
    days = [d for d in _daily(date(2026, 10, 16), 11) if d != date(2026, 10, 23)]
    jci = pp.JciLeg([Row("JKSE", d, 100.0, None, "idxscape") for d in days])
    bond = pp.YieldBondLeg([(d, 7.0) for d in days], label="x", name="IGSYC.10", daily=True)
    marks = pp.benchmark_marks(jci, bond, [date(2026, 10, 16), date(2026, 10, 23)], pct=LEGACY)
    assert marks[0].benchmark is not None and marks[0].stale == []


def test_benchmark_marks_are_60_40_rebalanced_weekly_and_stale_marks_carry_no_return():
    jci = pp.JciLeg(_jci_rows([100.0, 110.0, 121.0]))
    bond = _flat_bond(4, 5.2)
    marks = pp.benchmark_marks(jci, bond, _fridays(4), pct=LEGACY)
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
    rep = pp.paper_track(journal=j, jci=jci, bond=bond, until=d[-1], us=_flat_us(8))

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
                         bond=_flat_bond(4), until=d[-1], us=_flat_us(4))
    (seg,) = rep.segments
    assert [m.weights["stocks"] for m in seg.marks] == [60.0, 60.0, 0.0]


def test_weeks_past_frozen_jci_are_stale_and_excluded(tmp_path):
    j = Journal(tmp_path)
    d = _fridays(5)
    _stance(j, FP_A, "stocks", "neutral", d[0])
    rep = pp.paper_track(journal=j, jci=pp.JciLeg(_jci_rows([100, 101, 102])),
                         bond=_flat_bond(5), until=d[-1], us=_flat_us(5))
    (seg,) = rep.segments
    assert seg.weeks == 2 and seg.stale_weeks == 2
    assert all(m.portfolio is None and m.stale for m in seg.marks[2:])


def test_identical_stances_track_the_benchmark(tmp_path):
    j = Journal(tmp_path)
    d = _fridays(5)
    _stance(j, FP_A, "stocks", "neutral", d[0])
    _stance(j, FP_A, "bonds", "neutral", d[0])
    rep = pp.paper_track(journal=j, jci=pp.JciLeg(_jci_rows([100, 97, 99, 104, 101])),
                         bond=_flat_bond(5), until=d[-1], us=_flat_us(5))
    (seg,) = rep.segments
    assert seg.active_return == pytest.approx(0.0, abs=1e-12)
    assert seg.tracking_error == pytest.approx(0.0, abs=1e-12)
    assert seg.hit_rate == 0.0


def test_no_journal_gives_benchmark_marks_only(tmp_path):
    d = _fridays(4)
    rep = pp.paper_track(journal=Journal(tmp_path / "none"),
                         jci=pp.JciLeg(_jci_rows([100, 101, 102, 103])),
                         bond=_flat_bond(4), start=d[0], until=d[-1],
                         us=_flat_us(4))
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
    rep = pp.paper_track(records=[], jci=jci, bond=bond, start=d[0], until=d[-1],
                         us=_flat_us(3))
    assert "idxscape_phei (missing)" in rep.stale_inputs
    assert any(s.startswith("JCI") for s in rep.stale_inputs)


# ---------------- S40: the US leg and the 48/32/20 benchmark ----------------


def test_benchmark_weights_come_from_stance_and_sum_to_100():
    from assist import stance

    assert pp.BENCHMARK_PCT == {"stocks": 48.0, "bonds": 32.0, "usa": 20.0}
    assert sum(pp.BENCHMARK_PCT.values()) == pytest.approx(100.0)
    assert {pp.LEG_KEYS[k]: v for k, v in stance.BENCHMARK_PCT.items()} == pp.BENCHMARK_PCT
    assert sum(pp.LEGACY_BENCHMARK_PCT.values()) == pytest.approx(100.0)
    assert pp.pct_text(pp.BENCHMARK_PCT) == "48% JCI / 32% SBN leg / 20% US stocks (IDR)"


def _us(usd, fx, days=None):
    days = days or _fridays(len(usd))
    return pp.UsLeg(list(zip(days, usd, strict=True)), list(zip(days, fx, strict=True)),
                    label="t")


def test_us_leg_idr_return_rises_with_usd_and_with_a_weaker_rupiah():
    g = _fridays(2)
    only_usd = _us([100.0, 110.0], [16000.0, 16000.0]).weekly(g)[g[1]]
    only_fx = _us([100.0, 100.0], [16000.0, 16800.0]).weekly(g)[g[1]]
    both = _us([100.0, 110.0], [16000.0, 16800.0]).weekly(g)[g[1]]
    assert only_usd[0] == pytest.approx(0.10) and only_usd[2] == pytest.approx(0.0)
    assert only_fx[0] == pytest.approx(0.05) and only_fx[1] == pytest.approx(0.0)
    assert both[:3] == pytest.approx((1.10 * 1.05 - 1, 0.10, 0.05))
    assert both[3] == []
    stronger = _us([100.0, 100.0], [16000.0, 15200.0]).weekly(g)[g[1]]
    assert stronger[0] == pytest.approx(-0.05)  # rupiah stronger: the unhedged leg loses


def test_us_leg_staleness_is_its_own_calendar_not_idx():
    fri0, fri1 = date(2026, 10, 16), date(2026, 10, 23)
    mon = date(2026, 10, 26)
    fx = [(fri0, 16000.0), (fri1, 16100.0), (mon, 16100.0)]
    # US closed Friday 10-23 (holiday): Thursday's close is the mark's level once Monday's exists
    leg = pp.UsLeg([(fri0, 100.0), (date(2026, 10, 22), 101.0), (mon, 102.0)], fx, label="t")
    r, *_, why = leg.weekly([fri0, fri1])[fri1]
    assert why == [] and r == pytest.approx(1.01 * 16100 / 16000 - 1)
    # before Monday's close the Friday close may still come: past the last close is stale
    early = pp.UsLeg([(fri0, 100.0), (date(2026, 10, 22), 101.0)], fx, label="t")
    assert early.weekly([fri0, fri1])[fri1][3] == [
        "US leg: no SPY close after 2026-10-22 (mark 2026-10-23)"]
    # last US close Wednesday: a capture gap, stale and named
    gap = pp.UsLeg([(fri0, 100.0), (date(2026, 10, 21), 101.0), (mon, 102.0)], fx, label="t")
    r, *_, why = gap.weekly([fri0, fri1])[fri1]
    assert r is None and why == ["US leg: no SPY close for the 2026-10-23 mark (last 2026-10-21)"]
    # IDX shut Friday but the US traded: the US leg does not need IDX's last day
    jci = pp.JciLeg([Row("JKSE", d, 100.0, None, "idxscape")
                     for d in (fri0, date(2026, 10, 22))])
    ok = pp.UsLeg([(fri0, 100.0), (fri1, 102.0)], fx, label="t")
    assert ok.weekly([fri0, fri1], jci.series.last_day)[fri1][3] == []


def test_us_leg_fx_gap_while_idx_traded_is_stale_but_a_long_idx_holiday_is_not():
    fri0, fri1 = date(2026, 10, 16), date(2026, 10, 23)
    usd = [(fri0, 100.0), (fri1, 100.0), (date(2026, 10, 26), 100.0)]
    fx = [(fri0, 16000.0), (date(2026, 10, 20), 16050.0),  # Tuesday, then nothing to Monday
          (date(2026, 10, 26), 16060.0)]
    leg = pp.UsLeg(usd, fx, label="t")
    traded = pp.JciLeg([Row("JKSE", d, 1.0, None, "x") for d in (fri0, fri1)])
    why = leg.weekly([fri0, fri1], traded.series.last_day)[fri1][3]
    assert why == ["US leg: no USD/IDR fixing for the 2026-10-23 mark (last 2026-10-20)"]
    lebaran = pp.JciLeg([Row("JKSE", d, 1.0, None, "x") for d in (fri0, date(2026, 10, 20))])
    assert leg.weekly([fri0, fri1], lebaran.series.last_day)[fri1][3] == []


def test_benchmark_48_32_20_mix_and_us_staleness_only_where_held():
    d = _fridays(3)
    jci = pp.JciLeg(_jci_rows([100.0, 110.0, 110.0]))
    bond = _flat_bond(3, 5.2)
    us = _us([100.0, 104.0], [16000.0, 16000.0], d[:2])  # US ends after week 1
    marks = pp.benchmark_marks(jci, bond, d, us)
    assert marks[0].benchmark == pytest.approx(0.48 * 0.10 + 0.32 * 0.052 / 52 + 0.20 * 0.04)
    assert marks[0].usa == pytest.approx(0.04) and marks[0].usd_idr == pytest.approx(0.0)
    assert marks[1].benchmark is None and any(s.startswith("US leg") for s in marks[1].stale)
    legacy = pp.benchmark_marks(jci, bond, d, us, pct=LEGACY)
    assert legacy[1].benchmark is not None and legacy[1].stale == []  # 60/40 needs no US


def test_us_index_is_split_adjusted_price_not_total_return():
    from assist.sources.usfin_stocks import UsBar

    class Stocks:
        def bars(self, symbol):
            assert symbol == "SPY"
            return [UsBar(date(2026, 1, 2), "SPY", 600.0, 1.0, 590.0, 1.0, 0.98),
                    UsBar(date(2026, 1, 5), "SPY", 300.0, 1.0, 295.0, 2.0, 0.98)]

    pts, stale = pp.us_index(Stocks())
    assert pts == [(date(2026, 1, 2), 600.0), (date(2026, 1, 5), 600.0)] and stale == []


def test_usd_idr_splices_mas_cross_before_jisdor_and_names_the_seam():
    seam = date(2026, 10, 22)
    days = [date(2026, 10, 20), date(2026, 10, 21), seam, date(2026, 10, 23)]
    sg = FakeSource("singstat", [
        *[Row("mas:fx:usdsgd", d, 1.28, None, "singstat") for d in days],
        *[Row("mas:fx:idrsgd", d, 1.28 / 18000, None, "singstat") for d in days]])
    idx = FakeSource("idxscape", [Row("JISDOR", d, 18047.0, None, "idxscape")
                                  for d in days[2:]])
    pts, pieces, stale = pp.usd_idr(idx=idx, sg=sg)
    assert [d for d, _ in pts] == days and stale == []
    assert pts[0][1] == pytest.approx(18000.0) and pts[2][1] == 18047.0  # JISDOR from the seam
    assert [(p.name, p.first, p.last) for p in pieces] == [
        ("MAS", days[0], days[1]), ("JISDOR", seam, days[3])]
    # without singstat the history before JISDOR is missing and named, not invented
    pts, pieces, stale = pp.usd_idr(idx=idx, sg=FakeSource("singstat", error="locked"))
    assert [d for d, _ in pts] == days[2:] and stale == ["singstat (locked)"]


def _rec(fp, subject, asset, stance, as_of, target=None, s39=True):
    port = {"target_pct": target} if target is not None else {}
    if s39:
        port["benchmark_pct"] = 0.0
    return {"kind": "stance", "fingerprint": fp, "subject": subject, "asset": asset,
            "as_of": as_of.isoformat(), "outputs": {"stance": stance, "portfolio": port}}


def test_s39_segment_scored_on_48_32_20_and_legacy_segment_unchanged():
    d = _fridays(7)
    jci = pp.JciLeg(_jci_rows([100, 102, 104, 103, 105, 107, 106]))
    bond = _flat_bond(7, 7.0)
    us = _us([100, 101, 103, 102, 104, 105, 107], [16000 + 50 * i for i in range(7)])
    legacy_recs = [_rec(FP_A, "IDN", "stocks", "overweight", d[0], s39=False),
                   _rec(FP_A, "IDN", "bonds", "neutral", d[0], s39=False),
                   _rec(FP_A, "USA", "stocks", "overweight", d[0], s39=False)]
    new_recs = [_rec(FP_B, "IDN", "stocks", "neutral", d[3], 45.7),
                _rec(FP_B, "IDN", "bonds", "neutral", d[3], 30.5),
                _rec(FP_B, "USA", "stocks", "overweight", d[3], 23.8)]
    rep = pp.paper_track(records=legacy_recs + new_recs, jci=jci, bond=bond, us=us, until=d[-1])
    a, b = rep.segments
    # the legacy segment: the same score as the 60/40 code without any US leg (P30)
    cut = _rec(FP_B, "IDN", "stocks", "neutral", d[3], s39=False)  # the same segment end
    alone = pp.paper_track(records=[*legacy_recs[:2], cut], jci=jci, bond=bond, until=d[-1],
                           us=pp.UsLeg([], [], label="none"))
    old = alone.segments[0]
    assert a.benchmark_pct == LEGACY and a.decisions == 2
    assert (a.portfolio_return, a.benchmark_return, a.weeks) == (
        old.portfolio_return, old.benchmark_return, old.weeks)
    assert "usa" not in a.marks[0].weights
    # the S39 segment holds the journalled targets and is scored on 48/32/20
    assert b.benchmark_pct == pp.BENCHMARK_PCT and b.decisions == 3
    w = b.marks[0].weights
    assert (w["stocks"], w["bonds"], w["usa"]) == (45.7, 30.5, 23.8)
    assert w["cash"] == pytest.approx(0.0, abs=1e-9)
    m = b.marks[0]
    assert m.benchmark == pytest.approx(0.48 * m.jci + 0.32 * m.sbn + 0.20 * m.usa)
    assert m.portfolio == pytest.approx(0.457 * m.jci + 0.305 * m.sbn + 0.238 * m.usa)
    # both benchmarks are reported side by side
    assert rep.benchmark_pct == pp.BENCHMARK_PCT and rep.legacy_benchmark_pct == LEGACY
    assert rep.benchmark and rep.legacy_benchmark and "usa" in rep.legs


def test_mandate_weights_fall_back_to_benchmark_plus_tilt_and_scale():
    w = pp.mandate_weights({"stocks": ("overweight", None), "usa": ("avoid", None)})
    assert (w["stocks"], w["bonds"], w["usa"], w["cash"]) == (53.0, 32.0, 0.0, 15.0)
    w = pp.mandate_weights({k: ("neutral", 50.0) for k in pp.LEGS})
    assert sum(w[k] for k in pp.LEGS) == pytest.approx(100.0) and w["cash"] == 0.0


def test_missing_us_store_leaves_the_benchmark_weeks_stale_and_named():
    d = _fridays(3)
    us = pp.UsLeg([], [], label="none", stale_inputs=["sec-edgar (locked)"])
    rep = pp.paper_track(records=[], jci=pp.JciLeg(_jci_rows([100, 101, 102])),
                         bond=_flat_bond(3), us=us, until=d[-1])
    assert len(rep.benchmark) == 2 and all(m.benchmark is None for m in rep.benchmark)
    assert all(any(s.startswith("US leg") for s in m.stale) for m in rep.benchmark)
    assert "sec-edgar (locked)" in rep.stale_inputs
    assert rep.legacy_summary["weeks"] == 2  # the 60/40 needs no US leg
