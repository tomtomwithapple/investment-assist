"""Point-in-time input history of the IDN layer-2 overrides (phase L, P75, PLAN S57).

Every store is an in-memory fake of tidy `Row`s over 2015-01 → 2019-12, recorded as the real
stores record them (bps-looker stamps every row with its last update, bisfetcher with its fetch,
dbnomics keeps no vintage), so only the publication lags in `overrides.LAG` decide what was known
on a month end. The key test poisons every value that was not yet known on a cut-off and checks
that no row up to the cut-off moves."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

import pytest

from assist import override_history as OH
from assist.layers.overrides import CLI, DBN_CPI, LAG, idn_overrides
from assist.sources.base import Row, SourceUnavailable
from assist.sources.bisfetcher import BI_RATE_M
from assist.sources.bpslooker import CPI_YOY, GDP_YOY, TRADE_BALANCE

D = date.fromisoformat
BPS_RECORDED = D("2026-10-01")  # bps-looker's last_update on every row (seen 2026-10-23)
BPS_CPI_FROM = D("2018-01-01")  # bps-looker CPI starts late, as the real one does (2024-01)
BIS_RECORDED = D("2026-10-19")
START, END = D("2016-01-31"), D("2019-12-31")


class Fake:
    """A store as tidy rows; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, list(rows or []), error
        self.calls = 0

    def rows(self, series_ids=None, start=None, end=None, **kw):
        self.calls += 1
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted(
            (r for r in self._rows
             if (series_ids is None or r.series_id in series_ids)
             and (start is None or r.date >= start) and (end is None or r.date <= end)),
            key=lambda r: (r.series_id, r.date))


def _months(first: date, last: date) -> list[date]:
    out, y, m = [], first.year, first.month
    while date(y, m, 1) <= last:
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _bps_rows(cpi_from: date = BPS_CPI_FROM) -> list[Row]:
    rows = []
    for i, d in enumerate(_months(D("2014-01-01"), D("2019-10-01"))):
        if d.month in (1, 4, 7, 10):
            rows.append(Row(GDP_YOY, d, 5.0 + math.sin(i / 5), BPS_RECORDED, "bps-looker"))
        if d >= D("2016-01-01"):
            rows.append(Row(TRADE_BALANCE, d, 800 * math.sin(i / 4), BPS_RECORDED,
                            "bps-looker"))
        if d >= cpi_from:
            rows.append(Row(CPI_YOY, d, 3.0 + math.cos(i / 6), BPS_RECORDED, "bps-looker"))
    return rows


def _bis_rows() -> list[Row]:
    return [Row(BI_RATE_M, d, 5.0 + 0.25 * (i // 7 % 4), BIS_RECORDED, "bisfetcher")
            for i, d in enumerate(_months(D("2014-01-01"), D("2019-11-01")))]


def _dbn_rows() -> list[Row]:
    rows = []
    for i, d in enumerate(_months(D("2014-01-01"), D("2019-11-01"))):
        rows.append(Row(CLI, d, 100 + 0.8 * math.sin(i / 3), None, "dbnomics"))
        rows.append(Row(DBN_CPI, d, 3.1 + math.cos(i / 6), None, "dbnomics"))
    return rows


def stores(bps=None, bis=None, dbn=None) -> dict[str, Fake]:
    return {"bps": Fake("bps-looker", _bps_rows() if bps is None else bps),
            "bisfetcher": Fake("bisfetcher", _bis_rows() if bis is None else bis),
            "dbnomics": Fake("dbnomics", _dbn_rows() if dbn is None else dbn),
            "satudatascape": Fake("satudatascape", error="missing")}


def dates() -> list[date]:
    return OH.month_ends(START, END)


# ---------------- Preloaded ----------------


def test_preloaded_reads_the_store_once_and_filters_like_it():
    fake = Fake("bps-looker", _bps_rows())
    pre = OH.Preloaded(fake, [CPI_YOY, GDP_YOY, TRADE_BALANCE], end=END)
    assert pre.name == "bps-looker"
    pre.rows([GDP_YOY])
    assert fake.calls == 1
    for start, end in ((D("2016-03-01"), D("2017-02-01")), (None, D("2015-06-30")),
                       (D("2019-01-01"), None)):
        for ids in ([GDP_YOY], [CPI_YOY, TRADE_BALANCE], None):
            assert pre.rows(ids, start=start, end=end) == fake.rows(ids, start, end)
    assert fake.calls == 1 + 9  # one preload; every other call above was a direct read


def test_preloaded_never_serves_past_its_end():
    fake = Fake("bps-looker", _bps_rows())
    pre = OH.Preloaded(fake, [GDP_YOY], end=D("2017-12-31"))
    assert max(r.date for r in pre.rows([GDP_YOY])) <= D("2017-12-31")


def test_preloaded_reraises_an_unavailable_store_on_every_call():
    fake = Fake("bps-looker", error="locked")
    pre = OH.Preloaded(fake, [GDP_YOY], end=END)
    for _ in range(2):
        with pytest.raises(SourceUnavailable) as e:
            pre.rows([GDP_YOY], start=START, end=END)
        assert e.value.stale_input == "bps-looker (locked)"
    assert fake.calls == 1


# ---------------- replay ----------------


def test_replay_equals_the_layer_called_directly():
    s = stores()
    h = OH.replay(dates(), **s)
    assert h.subject == "IDN" and len(h.rows) == len(dates())
    for day in (D("2016-06-30"), D("2017-11-30"), D("2019-12-31")):
        direct = idn_overrides(day, bps=s["bps"], bisfetcher=s["bisfetcher"],
                               dbnomics=s["dbnomics"], satudatascape=s["satudatascape"])
        row = h.row(day)
        assert row.shift == {o.asset: o.delta for o in direct.overrides}
        assert row.raw == direct.raw
        assert {n: c.value for n, c in row.components.items()} == {
            c.name: c.value for c in direct.components}
        assert row.stale_inputs == direct.stale_inputs


def test_replay_reads_each_store_once():
    s = stores()
    OH.replay(dates(), **s)
    assert {k: f.calls for k, f in s.items()} == {
        "bps": 1, "bisfetcher": 1, "dbnomics": 1, "satudatascape": 1}


def _poison(rows: list[Row], cutoff: date) -> list[Row]:
    """Every value not yet known on `cutoff` (dated after it, or inside its publication lag)
    made absurd."""
    out = []
    for r in rows:
        known = r.date <= cutoff and r.date + LAG[r.series_id] <= cutoff
        out.append(r if known else r._replace(value=-9999.0))
    return out


@pytest.mark.parametrize("cutoff", [D("2016-09-30"), D("2018-02-28"), D("2019-06-30")])
def test_no_row_uses_a_value_not_yet_known(cutoff):
    clean = OH.replay(dates(), **stores())
    dirty = OH.replay(dates(), **stores(bps=_poison(_bps_rows(), cutoff),
                                        bis=_poison(_bis_rows(), cutoff),
                                        dbn=_poison(_dbn_rows(), cutoff)))
    upto = [r.as_of for r in clean.rows if r.as_of <= cutoff]
    assert upto
    for day in upto:
        assert dirty.row(day).to_dict() == clean.row(day).to_dict(), day
    later = [r.as_of for r in clean.rows if r.as_of > cutoff + timedelta(days=130)]
    assert any(dirty.row(d).to_dict() != clean.row(d).to_dict() for d in later)


def test_a_leak_would_be_caught(monkeypatch):
    """The poison test bites: with the publication lags at zero, early rows move."""
    cutoff = D("2018-02-28")
    clean = OH.replay(dates(), **stores())
    poisoned = stores(bps=_poison(_bps_rows(), cutoff), bis=_poison(_bis_rows(), cutoff),
                      dbn=_poison(_dbn_rows(), cutoff))  # with the real lags
    for sid in list(LAG):
        monkeypatch.setitem(LAG, sid, timedelta(0))
    dirty = OH.replay(dates(), **poisoned)
    assert any(dirty.row(d).to_dict() != clean.row(d).to_dict()
               for d in (r.as_of for r in clean.rows if r.as_of <= cutoff))


def test_component_points_carry_value_direction_and_newest_date():
    h = OH.replay(dates(), **stores())
    row = h.row(D("2018-06-30"))
    assert set(row.components) == {"growth", "cli", "inflation", "trade", "bi_rate"}
    cli = row.components["cli"]
    assert cli.series_id == CLI and cli.source == "dbnomics"
    assert cli.last == D("2018-05-01")  # May is known 45 days after 05-01, June not yet
    assert cli.direction in (-1, 0, 1)
    gdp = row.components["growth"]
    assert gdp.last == D("2018-01-01")  # Q1 dated 01-01 is known after 130 days (05-11)
    assert row.complete and row.missing == ()


def test_inflation_switches_from_dbnomics_to_bps_looker_when_bps_is_known():
    h = OH.replay(dates(), **stores())
    assert h.row(D("2017-12-31")).components["inflation"].series_id == DBN_CPI
    assert h.row(D("2019-06-30")).components["inflation"].series_id == CPI_YOY


def test_a_short_bps_cpi_leaves_inflation_missing_with_its_reason():
    """bps-looker CPI known for under 3 months: P17 neither computes it nor falls back to
    dbnomics (as the real store does from 2024-02 to 2024-04)."""
    h = OH.replay(dates(), **stores())
    row = h.row(D("2018-03-31"))  # bps CPI known for 2018-01 and 2018-02 only
    assert "inflation" not in row.components
    assert row.missing == (f"inflation: bps-looker {CPI_YOY} (history from 2018-01-01)",)
    assert not row.complete


def test_a_short_trade_history_is_missing_until_six_months_are_known():
    h = OH.replay(dates(), **stores())
    early, late = h.row(D("2016-06-30")), h.row(D("2016-07-31"))
    assert early.missing == (
        f"trade: bps-looker {TRADE_BALANCE} (history from 2016-01-01)",)
    assert "trade" in late.components  # Jan-Jun known by 07-21 (lag 50 days)


def test_an_unavailable_store_names_every_component_it_holds():
    s = stores()
    s["bisfetcher"] = Fake("bisfetcher", error="missing")
    h = OH.replay(dates(), **s)
    row = h.row(D("2019-06-30"))
    assert "bi_rate: bisfetcher (missing)" in row.missing
    assert "bisfetcher (missing)" in row.stale_inputs
    assert "bi_rate" not in row.components


# ---------------- coverage and summary ----------------


def test_coverage_names_first_month_and_holes_per_component():
    h = OH.replay(dates(), **stores())
    cov = h.coverage()
    assert cov["trade"]["first"] == "2016-07"  # Jan-Jun 2016 known 2016-07-21
    assert cov["inflation"]["holes"] == [["2018-02", "2018-04"]]  # bps CPI < 3 months known
    assert cov["bi_rate"]["first"] == "2016-01" and cov["bi_rate"]["holes"] == []
    assert cov["bi_rate"]["months"] == len(dates())
    assert h.complete_from() == D("2016-07-31")
    assert h.incomplete_after_start() == [["2018-02", "2018-04"]]


def test_summary_counts_shift_signs_on_complete_months_only():
    h = OH.replay(dates(), **stores())
    s = h.summary()
    complete = [r for r in h.rows if r.complete]
    assert s["months"] == len(h.rows) and s["complete"] == len(complete)
    for a in OH.ASSETS:
        signs = s["shift_signs"][a]
        assert signs["up"] + signs["zero"] + signs["down"] == len(complete)
        assert signs["up"] == sum(r.shift[a] > 0 for r in complete)


def test_json_round_trip():
    h = OH.replay(dates(), **stores())
    doc = json.loads(json.dumps(h.to_dict()))
    assert OH.OverrideHistory.from_dict(doc) == h
    assert doc["subject"] == "IDN" and doc["schema"] == OH.SCHEMA


def test_month_end_dates_and_default_end():
    assert OH.month_ends(D("2016-01-15"), D("2016-03-31")) == [
        D("2016-01-31"), D("2016-02-29"), D("2016-03-31")]
    assert OH.last_month_end(D("2026-11-09")) == D("2026-10-31")
