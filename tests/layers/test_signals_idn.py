"""IDN market signals, layer 3 (P18, PLAN S8): foreign flow into IDX (IDR and USD via JISDOR),
non-resident SBN holdings change (DJPPR), KSEI foreign share trend and US TIC net purchases of
Indonesian equities and bonds, each a `Signal` with a direction of -1, 0 or +1.

Most tests feed in-memory sources (tidy `Row`s, no store); the last ones run the real idxscape and
kseistat adapters over their existing fixture stores, so the layer reads what the adapters give."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES

from assist.layers.signals import (
    FLOW_DAYS,
    IdnSignals,
    idn_signals,
)
from assist.layers.types import Signal
from assist.sources.base import Row, SourceUnavailable
from assist.sources.idxscape import (
    IDX_NET_FOREIGN_IDR,
    IDX_NET_FOREIGN_USD,
    SBN_NON_RESIDENT,
    SBN_TOTAL,
    IdxscapeSource,
)
from assist.sources.kseistat import FOREIGN_PCT_EQUAL, FOREIGN_PCT_SUM, KseistatSource

AS_OF = date(2026, 10, 21)
T = 1e12  # IDR trillion


class Fake:
    """A source holding rows in memory; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, rows or [], error
        self.calls: list[dict] = []

    def rows(self, series_ids=None, start=None, end=None, **kw):
        self.calls.append({"series_ids": series_ids, "start": start, "end": end, **kw})
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted(
            (r for r in self._rows
             if (series_ids is None or r.series_id in series_ids)
             and (start is None or r.date >= start) and (end is None or r.date <= end)),
            key=lambda r: (r.series_id, r.date),
        )


def _days(end: date, n: int) -> list[date]:
    """`n` weekdays ending on `end`."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def idx_rows(daily_idr: float, end: date = AS_OF, n: int = 40, rate: float = 16_000.0,
             usd_gaps: int = 0, holdings: tuple[float, float] = (900 * T, 900 * T)) -> list[Row]:
    """`n` days of market net foreign flow, plus weekly non-resident SBN holdings moving linearly
    from holdings[0] (8 weeks back) to holdings[1] (on `end`) out of IDR 6 400T total."""
    rows = []
    for i, d in enumerate(_days(end, n)):
        rows.append(Row(IDX_NET_FOREIGN_IDR, d, daily_idr, d, "idxscape"))
        usd = None if i >= n - usd_gaps else daily_idr / rate
        rows.append(Row(IDX_NET_FOREIGN_USD, d, usd, d, "idxscape"))
    lo, hi = holdings
    for k in range(9):
        d = end - timedelta(weeks=8 - k)
        rows.append(Row(SBN_NON_RESIDENT, d, lo + (hi - lo) * k / 8, d, "idxscape"))
        rows.append(Row(SBN_TOTAL, d, 6400 * T, d, "idxscape"))
    return rows


def ksei_rows(pcts: list[float], last: date = date(2026, 9, 30)) -> list[Row]:
    """Month-end foreign share (sum method), oldest first, the last one dated `last`."""
    rows = []
    for k, p in enumerate(reversed(pcts)):
        d = _month_end(last, k)
        rows.append(Row(FOREIGN_PCT_SUM, d, p, d + timedelta(days=7), "kseistat"))
        rows.append(Row(FOREIGN_PCT_EQUAL, d, p - 10, d + timedelta(days=7), "kseistat"))
    return rows


def _month_end(last: date, back: int) -> date:
    y, m = last.year, last.month - back
    while m < 1:
        y, m = y - 1, m + 12
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)


def tic_rows(eqty: list[float], bond: list[float], last: date = date(2026, 7, 1)) -> list[Row]:
    """Monthly US net purchases ($mn), oldest first, the last one dated `last` (the 1st)."""
    rows = []
    for sid, vals in (("us_lt_eqty_net_42218", eqty), ("us_lt_bond_net_42218", bond)):
        for k, v in enumerate(reversed(vals)):
            d = _month_end(last, k).replace(day=1)
            rows.append(Row(sid, d, v, d + timedelta(days=75), "sec-edgar"))
    return rows


def run(idx=None, ksei=None, tic=None, as_of: date = AS_OF) -> IdnSignals:
    return idn_signals(
        as_of,
        idxscape=idx if idx is not None else Fake("idxscape", idx_rows(0.0)),
        kseistat=ksei if ksei is not None else Fake("kseistat", ksei_rows([30.0] * 4)),
        tic=tic if tic is not None else Fake("sec-edgar", tic_rows([0.0] * 3, [0.0] * 3)),
    )


def by_name(out: IdnSignals) -> dict[str, Signal]:
    return {s.name: s for s in out.signals}


# ---------------- shape ----------------


def test_every_signal_is_idn_and_tagged_with_its_asset():
    out = run()
    names = by_name(out)
    assert set(names) == {
        "idx_foreign_flow", "sbn_non_resident_change", "ksei_foreign_share",
        "tic_us_equity_net", "tic_us_bond_net",
    }
    assert all(s.subject == "IDN" and s.as_of == AS_OF for s in out.signals)
    assert {n for n, s in names.items() if s.asset == "stocks"} == {
        "idx_foreign_flow", "ksei_foreign_share", "tic_us_equity_net"}
    assert {n for n, s in names.items() if s.asset == "bonds"} == {
        "sbn_non_resident_change", "tic_us_bond_net"}
    assert out.stale_inputs == ()
    assert out.sources == ("idxscape", "kseistat", "sec-edgar")


def test_flat_inputs_point_nowhere():
    assert {s.direction for s in run().signals} == {0}


def test_for_asset_and_tally():
    out = run(idx=Fake("idxscape", idx_rows(200e9)))  # +IDR 4T over 20 days
    bonds = [s.name for s in out.for_asset("bonds")]
    assert bonds == ["sbn_non_resident_change", "tic_us_bond_net"]
    assert out.tally("stocks") == 1
    assert out.tally("bonds") == 0


# ---------------- IDX foreign flow ----------------


@pytest.mark.parametrize(("daily", "direction"), [(200e9, 1), (-200e9, -1), (20e9, 0)])
def test_idx_foreign_flow_sums_the_last_20_days(daily, direction):
    s = by_name(run(idx=Fake("idxscape", idx_rows(daily))))["idx_foreign_flow"]
    assert FLOW_DAYS == 20
    assert s.value == pytest.approx(daily * FLOW_DAYS)
    assert s.direction == direction
    assert s.source == "idxscape"


def test_idx_foreign_flow_detail_has_the_usd_sum_and_jisdor_gaps():
    s = by_name(run(idx=Fake("idxscape", idx_rows(-160e9, usd_gaps=2))))["idx_foreign_flow"]
    # 18 days with a JISDOR rate: 18 x -160bn / 16 000 = -US$180m; the 2 gap days are not filled
    assert "IDR -3.20T" in s.detail
    assert "US$ -180m" in s.detail
    assert "2 JISDOR gaps" in s.detail


def test_idx_foreign_flow_ignores_days_after_as_of():
    rows = idx_rows(-200e9) + [Row(IDX_NET_FOREIGN_IDR, AS_OF + timedelta(days=1), 99 * T, None,
                                   "idxscape")]
    out = run(idx=Fake("idxscape", rows))
    assert by_name(out)["idx_foreign_flow"].value == pytest.approx(-4 * T)


def test_idx_reads_are_point_in_time():
    idx = Fake("idxscape", idx_rows(0.0))
    run(idx=idx)
    assert all(c["end"] == AS_OF for c in idx.calls)


def test_short_flow_history_gives_no_signal_and_says_so():
    out = run(idx=Fake("idxscape", idx_rows(1e12, n=5)))
    assert "idx_foreign_flow" not in by_name(out)
    assert "idxscape IDX_NET_FOREIGN_IDR (5 of 20 days)" in out.stale_inputs


def test_old_flow_is_still_shown_but_listed_stale():
    old = AS_OF - timedelta(days=30)
    out = run(idx=Fake("idxscape", idx_rows(200e9, end=old)))
    assert by_name(out)["idx_foreign_flow"].direction == 1
    assert f"idxscape IDX_NET_FOREIGN_IDR (last {old})" in out.stale_inputs


# ---------------- non-resident SBN holdings ----------------


@pytest.mark.parametrize(
    ("holdings", "change", "direction"),
    [((900 * T, 908 * T), 4 * T, 1),     # +8T over 8 weeks → +4T over the last 4
     ((908 * T, 900 * T), -4 * T, -1),
     ((900 * T, 901 * T), 0.5 * T, 0)],
)
def test_sbn_non_resident_change_over_4_weeks(holdings, change, direction):
    out = run(idx=Fake("idxscape", idx_rows(0.0, holdings=holdings)))
    s = by_name(out)["sbn_non_resident_change"]
    assert s.value == pytest.approx(change)
    assert s.direction == direction
    assert s.asset == "bonds"


def test_sbn_without_a_value_4_weeks_back_gives_no_signal():
    two_weeks = AS_OF - timedelta(weeks=2)
    rows = [r for r in idx_rows(0.0) if r.series_id != SBN_NON_RESIDENT or r.date >= two_weeks]
    out = run(idx=Fake("idxscape", rows))
    assert "sbn_non_resident_change" not in by_name(out)
    assert f"idxscape SBN.TOTAL.non_resident (history from {two_weeks})" in out.stale_inputs


def test_sbn_comes_in_monthly_files_so_a_month_old_value_is_not_stale():
    rows = idx_rows(0.0, end=AS_OF - timedelta(days=30))
    out = run(idx=Fake("idxscape", [r for r in rows if r.series_id.startswith("SBN")]
                       + [r for r in idx_rows(0.0) if not r.series_id.startswith("SBN")]))
    assert "sbn_non_resident_change" in by_name(out)
    assert out.stale_inputs == ()
    old = AS_OF - timedelta(days=50)
    out = run(idx=Fake("idxscape", idx_rows(0.0, end=old)))
    assert f"idxscape SBN.TOTAL.non_resident (last {old})" in out.stale_inputs


def test_sbn_detail_has_the_level_and_non_resident_share():
    s = by_name(run(idx=Fake("idxscape", idx_rows(0.0, holdings=(900 * T, 908 * T)))))[
        "sbn_non_resident_change"]
    assert "IDR 908T held" in s.detail
    assert "14.19% of tradable SBN" in s.detail  # 908 / 6 400


# ---------------- KSEI foreign share ----------------


@pytest.mark.parametrize(
    ("pcts", "change", "direction"),
    [([30.0, 30.2, 30.4, 30.8], 0.8, 1), ([31.0, 30.8, 30.5, 30.4], -0.6, -1),
     ([30.0, 30.1, 30.0, 30.1], 0.1, 0)],
)
def test_ksei_foreign_share_change_over_3_months(pcts, change, direction):
    s = by_name(run(ksei=Fake("kseistat", ksei_rows(pcts))))["ksei_foreign_share"]
    assert s.value == pytest.approx(change)
    assert s.direction == direction
    assert f"{pcts[-1]:.2f}% foreign" in s.detail
    assert "equal-weight" in s.detail


def test_ksei_month_not_yet_loaded_on_as_of_is_ignored():
    # September's file is loaded 2026-10-07: on 10-03 the layer must still see August as latest
    out = run(ksei=Fake("kseistat", ksei_rows([30.0, 30.0, 30.0, 30.0, 40.0])),
              as_of=date(2026, 10, 3))
    s = by_name(out)["ksei_foreign_share"]
    assert s.value == pytest.approx(0.0)
    assert "30.00% foreign" in s.detail


def test_short_ksei_history_gives_no_signal_and_says_so():
    out = run(ksei=Fake("kseistat", ksei_rows([30.0, 31.0])))
    assert "ksei_foreign_share" not in by_name(out)
    assert "kseistat KSEI.sum.foreign_pct (history from 2026-08-31)" in out.stale_inputs


# ---------------- TIC ----------------


def test_tic_sums_the_last_3_months_of_us_net_purchases():
    rows = tic_rows([-200.0, 40.0, 30.0, 50.0], [10.0, -40.0, -30.0, -20.0])
    out = run(tic=Fake("sec-edgar", rows))
    s = by_name(out)
    assert s["tic_us_equity_net"].value == pytest.approx(120.0)
    assert s["tic_us_equity_net"].direction == 1
    assert s["tic_us_bond_net"].value == pytest.approx(-90.0)
    assert s["tic_us_bond_net"].direction == -1
    assert "US$ mn" in s["tic_us_bond_net"].detail


def test_tic_is_read_latest_then_cut_by_publication_lag():
    """sec-edgar backfilled all TIC history on 2026-10-14, so its own `as_of` vintage is empty
    before then: the layer reads the latest values and keeps a month once its normal ~80-day
    publication lag has passed, even if first seen later."""
    seen = date(2026, 10, 14)
    rows = [r._replace(as_of=seen) for r in tic_rows([5.0, 10.0, 20.0, 30.0], [0.0] * 4)]
    tic = Fake("sec-edgar", rows)
    out = run(tic=tic, as_of=date(2026, 8, 25))  # 1 Jun + 80 days = 20 Aug; July not yet out
    assert tic.calls and all("as_of" not in c for c in tic.calls)
    s = by_name(out)["tic_us_equity_net"]
    assert s.value == pytest.approx(35.0)  # Apr–Jun: 5 + 10 + 20
    assert "Apr–Jun 2026" in s.detail


def test_backfilled_rows_count_once_their_publication_lag_has_passed():
    backfill = date(2026, 10, 7)
    rows = [r._replace(as_of=backfill) for r in ksei_rows([30.0, 30.0, 30.0, 30.0, 31.0])]
    out = run(ksei=Fake("kseistat", rows), as_of=date(2026, 10, 5))  # 30 Sep + 14 days > 5 Oct
    assert by_name(out)["ksei_foreign_share"].value == pytest.approx(0.0)  # May → Aug
    out = run(ksei=Fake("kseistat", rows), as_of=date(2026, 10, 15))
    assert by_name(out)["ksei_foreign_share"].value == pytest.approx(1.0)


def test_tic_lags_about_two_months_so_a_july_print_is_fresh_in_october():
    assert not any(s.startswith("sec-edgar") for s in run().stale_inputs)
    out = run(tic=Fake("sec-edgar", tic_rows([0.0] * 3, [0.0] * 3, last=date(2026, 3, 1))))
    assert "sec-edgar us_lt_eqty_net_42218 (last 2026-03-01)" in out.stale_inputs


def test_tic_missing_months_count_as_no_data_not_zero():
    rows = [r._replace(value=None) if r.date == date(2026, 7, 1) else r
            for r in tic_rows([10.0, 20.0, 30.0], [0.0] * 3)]
    s = by_name(run(tic=Fake("sec-edgar", rows)))["tic_us_equity_net"]
    assert s.value == pytest.approx(30.0)  # 10 + 20, July is n.a.
    assert "2 of 3 months" in s.detail


# ---------------- unavailable sources ----------------


@pytest.mark.parametrize("reason", ["missing", "locked"])
def test_unavailable_source_drops_its_signals_and_is_listed(reason):
    out = run(ksei=Fake("kseistat", error=reason))
    assert "ksei_foreign_share" not in by_name(out)
    assert f"kseistat ({reason})" in out.stale_inputs
    assert "kseistat" not in out.sources
    assert "idx_foreign_flow" in by_name(out)


def test_nothing_available_is_empty_not_an_error():
    out = idn_signals(AS_OF, idxscape=Fake("idxscape", error="missing"),
                      kseistat=Fake("kseistat", error="missing"),
                      tic=Fake("sec-edgar", error="locked"))
    assert out.signals == ()
    assert out.sources == ()
    assert set(out.stale_inputs) == {
        "idxscape (missing)", "kseistat (missing)", "sec-edgar (locked)"}


# ---------------- through the real adapters (existing fixture stores) ----------------


def _store(path: Path, fixture: str) -> Path:
    con = duckdb.connect(str(path))
    try:
        con.execute((FIXTURES / fixture / "schema.sql").read_text())
        con.execute((FIXTURES / fixture / "data.sql").read_text())
    finally:
        con.close()
    return path


def test_through_the_idxscape_and_kseistat_adapters(tmp_path):
    idx = IdxscapeSource(_store(tmp_path / "idxscape.duckdb", "idxscape_flows"))
    ksei = KseistatSource(_store(tmp_path / "ksei.duckdb", "kseistat"))
    out = idn_signals(date(2026, 10, 21), idxscape=idx, kseistat=ksei,
                      tic=Fake("sec-edgar", error="missing"))
    # 10-21's IDX day was recorded 00:30 WIB 10-22, after as_of: only two days are known
    assert "idxscape IDX_NET_FOREIGN_IDR (2 of 20 days)" in out.stale_inputs
    # three DJPPR days and two KSEI months: no base 4 weeks / 3 months back
    assert "idxscape SBN.TOTAL.non_resident (history from 2026-10-19)" in out.stale_inputs
    assert "kseistat KSEI.sum.foreign_pct (history from 2026-08-31)" in out.stale_inputs
    assert "sec-edgar (missing)" in out.stale_inputs
    assert out.signals == ()
    assert out.sources == ("idxscape", "kseistat")
