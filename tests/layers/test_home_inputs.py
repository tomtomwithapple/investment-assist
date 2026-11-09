"""Home (IDN) regime inputs (P70, PLAN S51): JCI 20-day drawdown, IDX net foreign 20-day z-score,
USD/IDR 20-fixing move and non-resident SBN 20-day change, each point in time with its newest
date and a stale line. No thresholds and no points here (those are P71's).

Sources are in memory (tidy `Row`s, no store). The JCI fixture (tests/fixtures/home/jci.csv) is
idxscape `index_daily` COMPOSITE 2026-08-26 → 11-05 as read on 2026-11-07, so the 2026-10-06 →
10-16 fall (6,192.9 → 5,185.1, −11.6% on 10-16 alone) is the real one."""

from __future__ import annotations

import csv
import statistics
from datetime import date, timedelta

import pytest
from helpers import FIXTURES

from assist.layers.home_inputs import (
    FEATURES,
    FLOW_DAYS,
    MAX_AGE,
    Z_DAYS,
    HomeInputs,
    HomeSources,
    history,
    home_inputs,
)
from assist.sources.base import Row, SourceUnavailable
from assist.sources.idxmethod import JCI
from assist.sources.idxscape import IDX_NET_FOREIGN_IDR, JISDOR, SBN_NON_RESIDENT

JCI_DD, FLOW_Z, USDIDR, SBN = FEATURES
T = 1e12


class Fake:
    """A source holding rows in memory; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, rows or [], error
        self.calls: list[dict] = []

    def rows(self, series_ids=None, start=None, end=None, **kw):
        self.calls.append({"series_ids": series_ids, "start": start, "end": end})
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted(
            (r for r in self._rows
             if (series_ids is None or r.series_id in series_ids)
             and (start is None or r.date >= start) and (end is None or r.date <= end)),
            key=lambda r: (r.series_id, r.date),
        )


def _weekdays(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _jci_rows() -> list[Row]:
    with (FIXTURES / "home" / "jci.csv").open() as f:
        return [Row(JCI, date.fromisoformat(r["date"]), float(r["close"]), None,
                    "idxscape+idx-method") for r in csv.DictReader(f)]


def _sources(jci=None, idx=None, fx=None) -> HomeSources:
    return HomeSources(jci=jci or Fake("idxscape+idx-method", _jci_rows()),
                       idxscape=idx or Fake("idxscape"), usdidr=fx or Fake("MAS+JISDOR"))


# ---------------- JCI 20-day drawdown ----------------


def test_jci_fall_2026_10_06_to_10_16():
    jci = {r.date: r.value for r in _jci_rows()}
    d06, d15, d16 = date(2026, 10, 6), date(2026, 10, 15), date(2026, 10, 16)
    assert jci[d06] == pytest.approx(6192.927)
    assert jci[d16] == pytest.approx(5185.105)
    assert 100 * (jci[d16] / jci[d15] - 1) == pytest.approx(-11.57, abs=0.01)  # the day itself

    on06 = home_inputs(d06, _sources())
    # 20-day high on 10-06 is 6,678.2 (2026-09-09): already 7.3% below it before the fall
    assert on06.values[JCI_DD] == pytest.approx(100 * (6192.927 / 6678.201 - 1))
    assert on06.last[JCI_DD] == d06

    on15 = home_inputs(d15, _sources())
    assert on15.values[JCI_DD] == pytest.approx(100 * (5863.78 / 6441.159 - 1))  # -9.0%

    on16 = home_inputs(d16, _sources())
    # high 6,384.7 on 2026-09-21, the 20th close back
    assert on16.values[JCI_DD] == pytest.approx(100 * (5185.105 / 6384.726 - 1))  # -18.8%
    assert on16.values[JCI_DD] == pytest.approx(-18.79, abs=0.01)
    assert on16.last[JCI_DD] == d16
    assert not [s for s in on16.stale_inputs if JCI in s]


def test_jci_never_reads_past_as_of():
    """10-17 is a Saturday: the newest close is still 10-16; a close after as_of is ignored."""
    sat = home_inputs(date(2026, 10, 17), _sources())
    assert sat.last[JCI_DD] == date(2026, 10, 16)
    assert sat.values[JCI_DD] == pytest.approx(-18.79, abs=0.01)


def test_jci_short_history_is_none_and_named():
    rows = _jci_rows()[:10]
    out = home_inputs(rows[-1].date, _sources(jci=Fake("idxscape+idx-method", rows)))
    assert out.values[JCI_DD] is None
    assert any(f"{JCI} (10 of 20 closes)" in s for s in out.stale_inputs)


# ---------------- IDX net foreign 20-day z-score ----------------


def _flow_rows(end: date, n: int, recorded: date | None = None) -> list[Row]:
    days = _weekdays(end, n)
    # a deterministic, non-trivial pattern: IDR -0.9T .. +0.9T
    vals = [((i * 37) % 19 - 9) * 1e11 for i in range(n)]
    return [Row(IDX_NET_FOREIGN_IDR, d, v, recorded or d, "idxscape")
            for d, v in zip(days, vals, strict=True)]


def _z(values: list[float]) -> float:
    sums = [sum(values[i - FLOW_DAYS + 1:i + 1]) for i in range(FLOW_DAYS - 1, len(values))]
    now, base = sums[-1], sums[-1 - Z_DAYS:-1]
    return (now - statistics.fmean(base)) / statistics.stdev(base)


def test_flow_z_score_against_trailing_250_days():
    end = date(2026, 10, 15)
    rows = _flow_rows(end, 300)
    out = home_inputs(end, _sources(idx=Fake("idxscape", rows)))
    assert out.values[FLOW_Z] == pytest.approx(_z([r.value for r in rows]))
    assert out.last[FLOW_Z] == end
    assert not any(IDX_NET_FOREIGN_IDR in s for s in out.stale_inputs)


def test_flow_one_day_lag_on_backfilled_rows():
    """Every backfilled flow day carries one recorded date (2026-10-12 on this Mac): a day is
    known when recorded by as_of or one day after it trades (P18), so on 10-06 the newest is
    10-05, and the 10-06 row alone does not count yet."""
    d06 = date(2026, 10, 6)
    rows = _flow_rows(d06, 300, recorded=date(2026, 10, 12))
    out = home_inputs(d06, _sources(idx=Fake("idxscape", rows)))
    assert out.last[FLOW_Z] == date(2026, 10, 5)
    assert out.values[FLOW_Z] == pytest.approx(_z([r.value for r in rows[:-1]]))


def test_flow_short_history_is_none_and_named():
    end = date(2026, 10, 15)
    rows = _flow_rows(end, 100)
    out = home_inputs(end, _sources(idx=Fake("idxscape", rows)))
    assert out.values[FLOW_Z] is None
    assert out.last[FLOW_Z] == end
    need = FLOW_DAYS + Z_DAYS
    assert any(f"{IDX_NET_FOREIGN_IDR} (100 of {need} days)" in s for s in out.stale_inputs)


# ---------------- USD/IDR 20-fixing move ----------------


def _fx_rows(end: date, n: int, jisdor_from: date) -> list[Row]:
    out = []
    for i, d in enumerate(_weekdays(end, n)):
        v = 16_000 + 10 * i
        jis = d >= jisdor_from
        out.append(Row(JISDOR, d, v, d if jis else None, "idxscape" if jis else "singstat"))
    return out


def test_usdidr_20_fixing_move_on_the_splice():
    """MAS cross points (no vintage) count only past a one-day lag, as in the bonds rule; a
    JISDOR fixing counts the day idxscape recorded it."""
    end = date(2026, 10, 23)
    rows = _fx_rows(end, 40, jisdor_from=date(2026, 10, 22))
    out = home_inputs(end, _sources(fx=Fake("MAS+JISDOR", rows)))
    vals = [r.value for r in rows]
    assert out.values[USDIDR] == pytest.approx(100 * (vals[-1] / vals[-21] - 1))
    assert out.last[USDIDR] == end

    # all MAS: the as_of day's own point is not known yet
    mas = [r._replace(as_of=None, source="singstat") for r in rows]
    out = home_inputs(end, _sources(fx=Fake("MAS", mas)))
    assert out.last[USDIDR] == date(2026, 10, 22)
    assert out.values[USDIDR] == pytest.approx(100 * (vals[-2] / vals[-22] - 1))


# ---------------- non-resident SBN 20-day change ----------------


def _sbn_rows(end: date, n: int, fetched: date) -> list[Row]:
    return [Row(SBN_NON_RESIDENT, d, (900 + 0.5 * i) * T, fetched, "idxscape")
            for i, d in enumerate(_weekdays(end, n))]


def test_sbn_vintage_and_40_day_lag():
    """All of DJPPR's history came in one file fetched 2026-11-06. Before that day a point is
    known only 40 days after its date (P18), so on 11-05 the newest is 09-25 and stale; on 11-07
    the file is in and 11-04 is the newest."""
    rows = _sbn_rows(date(2026, 11, 4), 120, fetched=date(2026, 11, 6))
    on05 = home_inputs(date(2026, 11, 5), _sources(idx=Fake("idxscape", rows)))
    assert on05.last[SBN] == date(2026, 9, 25)
    assert on05.values[SBN] is not None
    assert f"idxscape {SBN_NON_RESIDENT} (last 2026-09-25)" in on05.stale_inputs
    assert on05.counted()[SBN] is None

    on07 = home_inputs(date(2026, 11, 7), _sources(idx=Fake("idxscape", rows)))
    vals = [r.value for r in rows]
    assert on07.last[SBN] == date(2026, 11, 4)
    assert on07.values[SBN] == pytest.approx(100 * (vals[-1] / vals[-21] - 1))
    assert not any(SBN_NON_RESIDENT in s for s in on07.stale_inputs)
    assert on07.counted()[SBN] == on07.values[SBN]


# ---------------- staleness, failures, history ----------------


def test_newest_point_at_most_seven_days_old_counts():
    assert timedelta(days=7) == MAX_AGE
    rows = _jci_rows()  # newest 2026-11-05 (Thursday)
    ok = home_inputs(date(2026, 11, 12), _sources())
    assert ok.last[JCI_DD] == date(2026, 11, 5)
    assert not any(JCI in s for s in ok.stale_inputs)
    assert ok.counted()[JCI_DD] == ok.values[JCI_DD]
    old = home_inputs(date(2026, 11, 13), _sources(jci=Fake("idxscape+idx-method", rows)))
    assert old.values[JCI_DD] is not None
    assert f"idxscape+idx-method {JCI} (last 2026-11-05)" in old.stale_inputs
    assert old.counted()[JCI_DD] is None


def test_unavailable_store_is_named_never_raised():
    out = home_inputs(date(2026, 10, 16), _sources(idx=Fake("idxscape", error="locked"),
                                                   fx=Fake("MAS+JISDOR", error="missing")))
    assert isinstance(out, HomeInputs)
    assert out.values[FLOW_Z] is None and out.values[SBN] is None and out.values[USDIDR] is None
    assert out.values[JCI_DD] is not None
    assert "idxscape (locked)" in out.stale_inputs
    assert "MAS+JISDOR (missing)" in out.stale_inputs
    assert out.sources == ("idxscape+idx-method",)
    assert set(out.values) == set(FEATURES)


def test_no_data_at_all_is_named():
    out = home_inputs(date(2026, 10, 16), _sources())
    assert out.values[FLOW_Z] is None and FLOW_Z not in out.last
    assert f"idxscape {IDX_NET_FOREIGN_IDR} (no data)" in out.stale_inputs
    assert f"MAS+JISDOR {JISDOR} (no data)" in out.stale_inputs


def test_history_reads_each_store_once_and_matches_single_dates():
    jci, idx = Fake("idxscape+idx-method", _jci_rows()), Fake("idxscape", _flow_rows(
        date(2026, 11, 5), 300, recorded=date(2026, 10, 12)) + _sbn_rows(
        date(2026, 11, 4), 120, fetched=date(2026, 11, 6)))
    fx = Fake("MAS+JISDOR", _fx_rows(date(2026, 11, 5), 60, jisdor_from=date(2026, 10, 22)))
    dates = [date(2026, 10, 6), date(2026, 10, 16), date(2026, 10, 23), date(2026, 11, 5)]
    hist = history(dates, HomeSources(jci=jci, idxscape=idx, usdidr=fx))
    assert list(hist) == dates
    assert len(jci.calls) == len(idx.calls) == len(fx.calls) == 1
    for d in dates:
        assert hist[d] == home_inputs(d, HomeSources(jci=jci, idxscape=idx, usdidr=fx))
