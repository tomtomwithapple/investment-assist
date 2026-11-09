"""P65 (PLAN S46): one USD/IDR source for the IDN bonds rule, JISDOR spliced on the MAS cross.

`UsdIdrSource` wraps `paper.usd_idr`: JISDOR (idxscape) from its first fixing, the MAS cross
USD/SGD ÷ IDR/SGD (singstat) before, a JISDOR gap after the seam kept as a gap. Each point says
which leg it came from; the overlap (days both legs have after the seam) is measured, never used.
In-memory sources only: no store, no network."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from assist.layers.bonds import idn_bonds
from assist.layers.bonds.idn import MIN_FX_DAYS, PROXY_10Y
from assist.layers.signals import IdnSignals
from assist.layers.types import Regime, Signal
from assist.sources.base import Row, SourceUnavailable
from assist.sources.bpslooker import CPI_YOY
from assist.sources.idxscape import JISDOR
from assist.sources.idxscape_phei import IGSYC_2Y, IGSYC_10Y
from assist.sources.usdidr import UsdIdrSource

USD, IDR = "mas:fx:usdsgd", "mas:fx:idrsgd"
SEAM = date(2026, 10, 22)
AS_OF = date(2026, 11, 7)


class Fake:
    def __init__(self, name, rows=None, error=None, carried=()):
        self.name, self._rows, self.error, self._carried = name, rows or [], error, set(carried)
        self.calls = 0

    def rows(self, series_ids=None, start=None, end=None, **kw):
        self.calls += 1
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted((r for r in self._rows
                       if (series_ids is None or r.series_id in series_ids)
                       and (start is None or r.date >= start) and (end is None or r.date <= end)),
                      key=lambda r: (r.series_id, r.date))

    def carried_forward(self, pair="USDIDR"):
        return set(self._carried)


def weekdays(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def mas(days, level=16000.0, step=0.0, updated=date(2026, 11, 6)) -> Fake:
    """The MAS cross at `level` IDR per USD (+ `step` per day), as singstat's two S$ legs."""
    rows = []
    for i, d in enumerate(days):
        usd = 1.30
        rows += [Row(USD, d, usd, updated, "singstat"),
                 Row(IDR, d, usd / (level + step * i), updated, "singstat")]
    return Fake("singstat", rows)


def jisdor(days, level=16010.0, step=0.0) -> Fake:
    return Fake("idxscape", [Row(JISDOR, d, level + step * i, d + timedelta(days=0), "idxscape")
                             for i, d in enumerate(days)])


JIS_DAYS = weekdays(SEAM, date(2026, 11, 5))  # 11 fixings
MAS_DAYS = weekdays(date(2026, 1, 5), date(2026, 11, 5))


# ---------------- the splice ----------------


def test_mas_before_the_seam_jisdor_from_it():
    src = UsdIdrSource(jisdor(JIS_DAYS), mas(MAS_DAYS))
    rows = src.rows([JISDOR])
    assert len(JIS_DAYS) == 11
    assert all(r.series_id == JISDOR for r in rows)
    assert [r.date for r in rows] == [d for d in MAS_DAYS if d < SEAM] + JIS_DAYS
    pre = [r for r in rows if r.date < SEAM]
    assert pre[-1].value == pytest.approx(16000.0)
    assert [r.value for r in rows if r.date >= SEAM] == [16010.0] * 11  # MAS after the seam unused
    assert src.seam == SEAM and src.name == "MAS+JISDOR"


def test_provenance_per_point():
    src = UsdIdrSource(jisdor(JIS_DAYS), mas(MAS_DAYS))
    pts = src.points()
    assert {p.leg for p in pts if p.date < SEAM} == {"MAS"}
    assert {p.leg for p in pts if p.date >= SEAM} == {"JISDOR"}
    assert [(p.name, p.first, p.last, p.days) for p in src.pieces] == [
        ("MAS", MAS_DAYS[0], date(2026, 10, 21), len([d for d in MAS_DAYS if d < SEAM])),
        ("JISDOR", SEAM, JIS_DAYS[-1], 11)]
    # JISDOR keeps its vintage; the cross has none of its own (known past the rule's 1-day lag)
    rows = {r.date: r for r in src.rows([JISDOR])}
    assert rows[SEAM].as_of == SEAM and rows[SEAM].source == "idxscape"
    assert rows[MAS_DAYS[0]].as_of is None and rows[MAS_DAYS[0]].source == "singstat"


def test_jisdor_gap_after_the_seam_stays_a_gap():
    hole = JIS_DAYS[4]
    src = UsdIdrSource(jisdor([d for d in JIS_DAYS if d != hole]), mas(MAS_DAYS),)
    dates = [r.date for r in src.rows([JISDOR])]
    assert hole not in dates and hole in MAS_DAYS  # MAS had the day; it is not borrowed


def test_carried_forward_marking_passes_through():
    idx = jisdor(JIS_DAYS)
    idx._carried = {JIS_DAYS[2]}
    assert UsdIdrSource(idx, mas(MAS_DAYS)).carried_forward() == {JIS_DAYS[2]}


def test_overlap_is_measured_not_used():
    src = UsdIdrSource(jisdor(JIS_DAYS, level=16016.0), mas(MAS_DAYS, level=16000.0))
    ov = src.overlap
    assert ov.days == 11
    assert ov.max_abs_pct == pytest.approx(0.1, abs=1e-6)
    line = src.seam_line()
    assert "MAS cross" in line and "then JISDOR" in line and str(SEAM) in line
    assert "overlap 11 days" in line and "0.10%" in line
    assert src.stale_inputs == []


def test_rows_filter_by_id_and_dates_and_read_the_stores_once():
    idx, sg = jisdor(JIS_DAYS), mas(MAS_DAYS)
    src = UsdIdrSource(idx, sg)
    assert src.rows(["OTHER"]) == []
    got = src.rows([JISDOR], start=date(2026, 10, 20), end=date(2026, 10, 23))
    assert [r.date for r in got] == [date(2026, 10, 20), date(2026, 10, 21), SEAM,
                                     date(2026, 10, 23)]
    src.rows([JISDOR])
    assert idx.calls == 1 and sg.calls == 1


def test_one_leg_missing_names_it():
    src = UsdIdrSource(jisdor(JIS_DAYS), Fake("singstat", error="locked"))
    assert src.name == "JISDOR" and len(src.rows([JISDOR])) == 11
    assert src.stale_inputs == ["singstat (locked)"]
    src = UsdIdrSource(Fake("idxscape", error="missing"), mas(MAS_DAYS))
    assert src.name == "MAS" and src.seam is None
    assert src.stale_inputs == ["idxscape (missing)"]
    assert src.overlap.days == 0


def test_both_legs_missing_is_unavailable():
    src = UsdIdrSource(Fake("idxscape", error="missing"), Fake("singstat", error="locked"))
    with pytest.raises(SourceUnavailable) as e:
        src.rows([JISDOR])
    assert "idxscape (missing)" in str(e.value) and "singstat (locked)" in str(e.value)


# ---------------- the bonds rule on the spliced series ----------------


def _months(end: date, n: int) -> list[date]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return sorted(out)


def bonds(fx, as_of=AS_OF):
    phei = Fake("idxscape_phei", [
        *[Row(s, d, v, d, "idxscape_phei") for d in weekdays(date(2026, 11, 3), as_of)
          for s, v in ((IGSYC_10Y, 7.0), (IGSYC_2Y, 5.5))]])
    cpi = Fake("bps-looker", [Row(CPI_YOY, d, 2.0, date(2026, 10, 1), "bps-looker")
                              for d in _months(date(2026, 9, 1), 72)])
    dbn = Fake("dbnomics", [Row(PROXY_10Y, d, 6.0, None, "dbnomics")
                            for d in _months(date(2025, 12, 1), 120)])
    sig = IdnSignals(as_of, (Signal("IDN", "bonds", as_of, "sbn_non_resident_change", 1e12, 1,
                                    "idxscape", "IDR +1.00T non-resident SBN"),), (),
                     ("idxscape",))
    return idn_bonds(as_of, Regime(as_of, "neutral", "flat"), None, sig, phei=phei, bps=cpi,
                     dbnomics=dbn, idxscape=fx)


def test_eleven_jisdor_fixings_plus_mas_history_give_the_rule_its_fx_inputs():
    src = UsdIdrSource(jisdor(JIS_DAYS), mas(MAS_DAYS))
    assert len(src.rows([JISDOR])) >= MIN_FX_DAYS
    out = bonds(src)
    trend = out.signal("jisdor_trend")
    assert trend is not None and out.breakout is not None
    assert "over 20 fixings" in trend.detail and trend.source == "MAS+JISDOR"
    assert not any("fixings)" in s for s in out.stale_inputs)
    assert out.call != "no_call"


def test_a_jisdor_print_above_the_120_fixing_mas_range_is_a_6m_high():
    src = UsdIdrSource(jisdor(JIS_DAYS, level=16000.0, step=10.0), mas(MAS_DAYS, level=15900.0))
    out = bonds(src)
    assert out.breakout is True and out.call == "hold"
    assert any("USD/IDR at 6m high" in r for r in out.risks)


def test_a_mas_only_window_works():
    days = weekdays(date(2026, 1, 5), date(2026, 10, 9))
    out = bonds(UsdIdrSource(Fake("idxscape", error="missing"), mas(days)),
                as_of=date(2026, 10, 12))
    assert out.breakout is False and out.signal("jisdor_trend").source == "MAS"


def test_no_mas_and_short_jisdor_stays_a_stale_input():
    out = bonds(UsdIdrSource(jisdor(JIS_DAYS), Fake("singstat", error="locked")))
    assert out.call == "no_call" and out.breakout is None
    assert f"JISDOR {JISDOR} (11 of {MIN_FX_DAYS} fixings)" in out.stale_inputs
