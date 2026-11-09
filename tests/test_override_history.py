"""Point-in-time input history of the IDN layer-2 overrides (phase L, P75, PLAN S57).

Every store is an in-memory fake of tidy `Row`s over 2015-01 → 2019-12, recorded as the real
stores record them (bps-looker stamps every row with its last update, bisfetcher with its fetch,
dbnomics keeps no vintage), so only the publication lags in `overrides.LAG` decide what was known
on a month end. The key test poisons every value that was not yet known on a cut-off and checks
that no row up to the cut-off moves."""

from __future__ import annotations

import dataclasses
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


def test_preloaded_reraises_an_unavailable_store_on_every_call(monkeypatch):
    monkeypatch.setattr(OH, "LOCK_WAIT", 0.0)
    fake = Fake("bps-looker", error="locked")
    pre = OH.Preloaded(fake, [GDP_YOY], end=END)
    for _ in range(2):
        with pytest.raises(SourceUnavailable) as e:
            pre.rows([GDP_YOY], start=START, end=END)
        assert e.value.stale_input == "bps-looker (locked)"
    assert fake.calls == OH.LOCK_TRIES  # a lock is retried, then named on every call
    missing = Fake("bps-looker", error="missing")
    pre = OH.Preloaded(missing, [GDP_YOY], end=END)
    for _ in range(2):
        with pytest.raises(SourceUnavailable):
            pre.rows([GDP_YOY])
    assert missing.calls == 1


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


def test_a_short_bps_cpi_falls_back_to_dbnomics():
    """bps-looker CPI known for under 3 months (as the real store from 2024-02 to 2024-04):
    since P85 (choice 9) inflation reads dbnomics there, and the bps short line stays stale."""
    h = OH.replay(dates(), **stores())
    row = h.row(D("2018-03-31"))  # bps CPI known for 2018-01 and 2018-02 only
    assert row.components["inflation"].series_id == DBN_CPI
    assert f"bps-looker {CPI_YOY} (history from 2018-01-01)" in row.stale_inputs
    assert row.complete
    assert h.row(D("2018-05-31")).components["inflation"].series_id == CPI_YOY


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
    # one trade month missing (2018-06): no 6 consecutive months until 2018-12 is known
    bps = [r for r in _bps_rows() if not (r.series_id == TRADE_BALANCE
                                          and r.date == D("2018-06-01"))]
    h = OH.replay(dates(), **stores(bps=bps))
    cov = h.coverage()
    assert cov["trade"]["first"] == "2016-07"  # Jan-Jun 2016 known 2016-07-21
    assert cov["trade"]["holes"] == [["2018-08", "2018-12"]]
    assert cov["inflation"]["holes"] == []  # the short bps CPI falls back (P85)
    assert cov["inflation"]["series"] == [CPI_YOY, DBN_CPI]
    assert cov["bi_rate"]["first"] == "2016-01" and cov["bi_rate"]["holes"] == []
    assert cov["bi_rate"]["months"] == len(dates())
    assert h.complete_from() == D("2016-07-31")
    assert h.incomplete_after_start() == [["2018-08", "2018-12"]]


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


# ---------------- forward returns (P76, PLAN S58) ----------------

from assist.history import HORIZON  # noqa: E402
from assist.layers.bonds.idn import PROXY_10Y  # noqa: E402
from assist.sources.idxmethod import JCI  # noqa: E402
from assist.sources.idxscape import JISDOR  # noqa: E402
from assist.sources.idxscape_phei import IGSYC_10Y  # noqa: E402


def _daily_month_ends(first: date, last: date, value) -> list[tuple[date, float]]:
    return [(d, value(i)) for i, d in enumerate(OH.month_ends(first, last))]


def return_stores(*, jci=None, tens=None, fx=None) -> OH.ReturnSources:
    jci = jci if jci is not None else _daily_month_ends(D("2015-01-31"), D("2019-12-31"),
                                                        lambda i: 5000 * (1 + 0.01 * i))
    tens = tens if tens is not None else [(d.replace(day=1), 7.0 + 0.05 * (i % 7))
                                          for i, d in enumerate(OH.month_ends(D("2015-01-31"),
                                                                              D("2019-11-30")))]
    fx = fx if fx is not None else _daily_month_ends(D("2015-01-31"), D("2019-12-31"),
                                                     lambda i: 13000 + 20 * i)
    return OH.ReturnSources(
        jci=Fake("jci", [Row(JCI, d, v, None, "jci") for d, v in jci]),
        dbnomics=Fake("dbnomics", [Row(PROXY_10Y, d, v, None, "dbnomics") for d, v in tens]),
        phei=Fake("idxscape_phei", error="missing"),
        usdidr=Fake("USD/IDR", [Row(JISDOR, d, v, None, "singstat") for d, v in fx]))


def test_currency_return_is_positive_when_the_rupiah_gains():
    fx = [(D("2018-01-31"), 15000.0), (D("2018-02-28"), 14800.0), (D("2018-03-31"), 14500.0),
          (D("2018-04-30"), 14000.0), (D("2018-05-31"), 14700.0)]
    fwd = OH.currency_forward(fx, 3, D("2019-01-01"))
    assert fwd[(2018, 1)] == pytest.approx(15000 / 14000 - 1)  # USD/IDR fell: rupiah up
    assert fwd[(2018, 1)] > 0
    assert fwd[(2018, 2)] == pytest.approx(14800 / 14700 - 1)
    assert (2018, 3) not in fwd  # no point 3 months on


def test_currency_return_never_crosses_a_gap():
    fx = [(D("2018-01-31"), 15000.0), (D("2018-02-28"), 14800.0),
          (D("2018-04-30"), 14000.0), (D("2018-05-31"), 14100.0), (D("2018-06-30"), 14200.0),
          (D("2018-07-31"), 14300.0)]
    fwd = OH.currency_forward(fx, 3, D("2019-01-01"))
    assert (2018, 1) not in fwd and (2018, 2) not in fwd  # March is missing
    assert fwd[(2018, 4)] == pytest.approx(14000 / 14300 - 1)


def test_no_return_from_a_month_still_running():
    src = return_stores()
    fwd = OH.idn_returns(src, today=D("2019-12-15"), horizon=3)
    # December 2019 is still running on 12-15: nothing priced to it
    assert (2019, 8) in fwd["stocks"] and (2019, 9) not in fwd["stocks"]
    assert (2019, 8) in fwd["currency"] and (2019, 9) not in fwd["currency"]
    later = OH.idn_returns(src, today=D("2020-01-01"), horizon=3)
    assert (2019, 9) in later["stocks"] and (2019, 9) in later["currency"]


def test_bonds_return_stops_at_the_ten_year_hole():
    tens = [(d.replace(day=1), 7.0) for d in OH.month_ends(D("2015-01-31"), D("2017-06-30"))]
    tens += [(d.replace(day=1), 6.5) for d in OH.month_ends(D("2018-01-31"), D("2019-11-30"))]
    fwd = OH.idn_returns(return_stores(tens=tens), today=D("2020-01-01"), horizon=3)["bonds"]
    # averages are lagged a month (P74): the call on M is priced from M+1's average to M+4's
    assert (2017, 2) in fwd and (2017, 3) not in fwd  # 2017-03 would need the 2017-07 average
    assert not any((2017, m) in fwd for m in range(3, 12))
    assert (2017, 12) in fwd  # the first call priced from 2018-01 on
    assert fwd[(2017, 1)] == pytest.approx(7.0 / 100 * 3 / 12)  # flat yield: carry only


def test_returns_join_the_rows_and_round_trip():
    h = OH.replay(dates(), **stores())
    fwd = OH.idn_returns(return_stores(), today=D("2020-01-15"), horizon=HORIZON)
    hr = OH.with_returns(h, fwd)
    row = hr.row(D("2018-03-31"))
    assert row.forward["stocks"] == pytest.approx(fwd["stocks"][(2018, 3)])
    assert row.forward["currency"] == pytest.approx(fwd["currency"][(2018, 3)])
    assert row.forward["bonds"] == pytest.approx(fwd["bonds"][(2018, 3)])
    assert hr.row(D("2019-12-31")).forward["stocks"] is None  # no close 3 months on
    assert OH.OverrideHistory.from_dict(json.loads(json.dumps(hr.to_dict()))) == hr
    cov = hr.return_coverage()
    assert cov["stocks"]["last"] == "2019-09" and cov["bonds"]["last"] == "2019-07"


def test_igsyc_closes_are_priced_on_their_own_dates():
    tens = [(d.replace(day=1), 7.0) for d in OH.month_ends(D("2016-01-31"), D("2016-12-31"))]
    src = return_stores(tens=tens)
    igsyc = [Row(IGSYC_10Y, d, v, None, "idxscape_phei")
             for d, v in ((D("2018-08-31"), 7.0), (D("2018-09-28"), 7.2),
                          (D("2018-10-31"), 7.5), (D("2018-11-30"), 8.0))]
    src = OH.ReturnSources(src.jci, src.dbnomics, Fake("idxscape_phei", igsyc), src.usdidr)
    fwd = OH.idn_returns(src, today=D("2019-06-01"), horizon=3)["bonds"]
    # daily closes are not lagged: the August call runs from 08-31 to 11-30
    assert fwd[(2018, 8)] == pytest.approx(0.07 * 3 / 12 - OH.DURATION * (8.0 - 7.0) / 100)
    assert (2018, 9) not in fwd


# ---------------- foreign input history (P81, PLAN S63) ----------------

import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402

from assist.layers import overrides_foreign as OF  # noqa: E402
from assist.sources import singstat as SG  # noqa: E402
from assist.sources.ausdata import AUD_IDR  # noqa: E402


def _foreign_fixtures():
    """P28's in-memory world (tests/layers/test_overrides_foreign.py), loaded by path."""
    path = Path(__file__).parent / "layers" / "test_overrides_foreign.py"
    spec = importlib.util.spec_from_file_location("_p28_world", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P28 = _foreign_fixtures()
F_DATES = OH.month_ends(D("2025-04-30"), D("2026-09-30"))


class Counting:
    """Wraps a fake store, counting reads and the `as_of` each read asked for."""

    def __init__(self, inner):
        self.inner, self.name, self.calls = inner, inner.name, []

    def rows(self, series_ids=None, start=None, end=None, **kw):
        self.calls.append({"ids": series_ids, "start": start, "end": end, **kw})
        return self.inner.rows(series_ids, start, end, **kw)


def foreign_world(**over):
    w = P28.world(**over)
    w["singstat"] = P28.Fake("singstat", w["singstat"]._rows + P28.daily(
        SG.fx_id("AUD"), "singstat", fill=0.85, last=P28.AS_OF - timedelta(days=2)))
    return {k: Counting(v) for k, v in w.items()}


def test_foreign_replay_equals_the_layer_called_directly():
    w = foreign_world()
    hs = OH.foreign_replay(F_DATES, w)
    assert set(hs) == set(OH.FOREIGN)
    raw = P28.world()
    raw["singstat"] = w["singstat"].inner
    for day in (D("2025-09-30"), D("2026-09-30")):
        direct = OF.foreign_overrides(day, raw)
        for m in direct.markets:
            row = hs[m.subject].row(day)
            assert row.shift == {o.asset: o.delta for o in m.overrides}, m.subject
            assert row.raw == m.raw
            assert {n: c.value for n, c in row.components.items()} == {
                c.name: c.value for c in m.components}


def test_each_foreign_store_is_read_once_but_fred_gdp_per_date_and_ausdata_per_date():
    w = foreign_world()
    OH.foreign_replay(F_DATES, w)
    for key in ("tic", "dbnomics", "bisfetcher", "jquantster", "singstat", "usdidr"):
        assert len(w[key].calls) == 1, key
    gdp = [c for c in w["fred"].calls if c["ids"] == ["GDPC1"]]
    assert [c["as_of"] for c in gdp] == F_DATES  # the vintage of each month end
    assert len(w["fred"].calls) == 1 + len(F_DATES)  # one preload of DFF / T10Y2Y
    assert [c["as_of"] for c in w["ausdata"].calls] == F_DATES


class VintageFred:
    """FRED GDPC1 whose vintage as of a date differs from today's values (a revision)."""

    name = "sec-edgar"

    def __init__(self, today_rows, vintage_rows):
        self.today, self.vintage = today_rows, vintage_rows

    def rows(self, series_ids=None, start=None, end=None, as_of=None, **kw):
        rows = self.vintage if as_of is not None else self.today
        return [r for r in rows if (series_ids is None or r.series_id in series_ids)
                and (start is None or r.date >= start) and (end is None or r.date <= end)]


def test_gdp_is_read_at_its_vintage_not_at_todays_revision():
    flat = P28.world()["fred"]._rows
    others = [r for r in flat if r.series_id != "GDPC1"]
    today = others + P28.gdp_levels(growth=(2.0,) * 12)  # revised: flat growth
    known = others + [r._replace(as_of=D("2026-07-30")) for r in P28.gdp_levels(
        growth=(2.0,) * 11 + (3.5,))]  # the vintage said growth jumped
    w = foreign_world()
    w["fred"] = VintageFred(today, known)
    row = OH.foreign_replay([D("2026-09-30")], w)["USA"].row(D("2026-09-30"))
    assert row.components["growth"].direction == 1
    w["fred"] = VintageFred(today, today)
    row = OH.foreign_replay([D("2026-09-30")], w)["USA"].row(D("2026-09-30"))
    assert row.components["growth"].direction == 0


def test_no_foreign_row_uses_a_value_dated_after_its_month_end():
    base = OH.foreign_replay(F_DATES, foreign_world())
    cut = D("2026-01-31")

    def poison(fake):
        return P28.Fake(fake.name, [r._replace(value=r.value * 7 + 13) if r.date > cut
                                    and r.value is not None else r for r in fake._rows])

    w = {k: Counting(poison(v)) for k, v in P28.world().items()}
    w["singstat"] = Counting(poison(foreign_world()["singstat"].inner))
    poisoned = OH.foreign_replay(F_DATES, w)
    for s in OH.FOREIGN:
        for d in F_DATES:
            if d <= cut:
                assert poisoned[s].row(d).shift == base[s].row(d).shift, (s, d)
                assert poisoned[s].row(d).raw == base[s].row(d).raw, (s, d)
    assert any(poisoned[s].row(D("2026-09-30")).raw != base[s].row(D("2026-09-30")).raw
               for s in OH.FOREIGN)


def test_aus_fx_reads_the_mas_cross_before_rba_aud_idr_has_three_months():
    aus = [r for r in P28.world()["ausdata"]._rows if r.series_id != AUD_IDR]
    aus += [r for r in P28.daily(AUD_IDR, "ausdata", fill=12_000.0) if r.date >= D("2026-03-02")]
    w = foreign_world(ausdata=aus)
    h = OH.foreign_replay(F_DATES, w)["AUS"]
    early, late = h.row(D("2025-12-31")), h.row(D("2026-09-30"))
    assert early.components["fx"].series_id == "IDR_PER_AUD"  # MAS: IDR per S$ x S$ per AUD
    assert early.components["fx"].source == "singstat"
    assert late.components["fx"].series_id == AUD_IDR
    assert late.complete and early.complete


def test_foreign_rows_are_complete_on_their_own_spec(monkeypatch):
    monkeypatch.setattr(OH, "LOCK_WAIT", 0.0)
    h = OH.foreign_replay(F_DATES, foreign_world())
    assert h["USA"].rows[-1].expected == OH.expected_components("USA")
    assert set(OH.expected_components("USA")) == {
        "growth", "cli", "inflation", "policy", "curve", "flows_equity", "flows_treasury", "fx"}
    assert set(OH.expected_components("SGP")) == {"growth", "inflation", "policy", "curve",
                                                   "fx"}
    for s in OH.FOREIGN:
        assert h[s].rows[-1].complete, (s, h[s].rows[-1].missing)
    jq_missing = OH.foreign_replay(F_DATES, foreign_world(
        jquantster=P28.Fake("jquantster", error="locked")))["JPN"].rows[-1]
    assert not jq_missing.complete
    assert any(m.startswith("growth: jquantster (locked)") for m in jq_missing.missing)
    cov = h["USA"].coverage()
    assert set(cov) == set(OH.expected_components("USA"))
    rt = OH.OverrideHistory.from_dict(json.loads(json.dumps(h["JPN"].to_dict())))
    assert rt == h["JPN"] and rt.rows[0].expected == OH.expected_components("JPN")


class FlakyFred(VintageFred):
    """Locked on the first vintage read of each date, then fine (another reader held it)."""

    def __init__(self, rows):
        super().__init__(rows, rows)
        self.seen: set = set()

    def rows(self, series_ids=None, start=None, end=None, as_of=None, **kw):
        if as_of is not None and as_of not in self.seen:
            self.seen.add(as_of)
            raise SourceUnavailable("sec-edgar", "locked")
        return super().rows(series_ids, start, end, as_of, **kw)


def test_a_locked_vintage_read_is_retried_and_a_lasting_lock_is_named(monkeypatch):
    monkeypatch.setattr(OH, "LOCK_WAIT", 0.0)
    w = foreign_world()
    w["fred"] = FlakyFred(P28.world()["fred"]._rows)
    row = OH.foreign_replay([D("2026-09-30")], w)["USA"].row(D("2026-09-30"))
    assert row.complete and "growth" in row.components
    w["fred"] = P28.Fake("sec-edgar", error="locked")
    row = OH.foreign_replay([D("2026-09-30")], w)["USA"].row(D("2026-09-30"))
    assert "growth: sec-edgar (locked)" in row.missing


def test_preloaded_retries_a_lock_and_bounds_its_start(monkeypatch):
    monkeypatch.setattr(OH, "LOCK_WAIT", 0.0)

    class LockedOnce(Fake):
        def rows(self, series_ids=None, start=None, end=None, **kw):
            self.starts = [*getattr(self, "starts", []), start]
            if self.calls == 0:
                self.calls += 1
                raise SourceUnavailable(self.name, "locked")
            return super().rows(series_ids, start, end, **kw)

    fake = LockedOnce("sec-edgar", _bps_rows())
    pre = OH.Preloaded(fake, [GDP_YOY], end=END, start=D("2017-01-01"))
    assert pre.rows([GDP_YOY]) and min(r.date for r in pre.rows([GDP_YOY])) >= D("2017-01-01")
    assert fake.starts == [D("2017-01-01"), D("2017-01-01")]


def test_the_foreign_preload_starts_at_the_first_date_less_the_read_back():
    w = foreign_world()
    OH.foreign_replay(F_DATES, w)
    first = F_DATES[0] - OF.READ_BACK - timedelta(days=31)
    for key in ("dbnomics", "singstat", "jquantster", "tic"):
        assert (w[key].calls[0]["start"], w[key].calls[0]["end"]) == (first, F_DATES[-1]), key
    fred = [c for c in w["fred"].calls if "as_of" not in c]
    assert fred[0]["start"] == first


# ---------------- foreign forward returns (P82, PLAN S64) ----------------

from types import SimpleNamespace as NS  # noqa: E402

from assist.sources import jquantster as JQ  # noqa: E402
from assist.sources.ausdata import AGS_10Y  # noqa: E402


def _month_end_rows(sid, src, first, last, value, *, day1=False):
    out = []
    for i, d in enumerate(OH.month_ends(first, last)):
        out.append(Row(sid, d.replace(day=1) if day1 else d, value(i), None, src))
    return out


class FakeStocks:
    def __init__(self, closes):
        self.closes = closes

    def bars(self, symbol):
        assert symbol == "SPY"
        return [NS(date=d, close=v, split_factor=1.0) for d, v in self.closes]


def foreign_return_stores(*, usd=lambda i: 1.30, idr=lambda i: 1.30 / 16_000, spy=None,
                          dgs10=lambda i: 4.0):
    first, last = D("2018-01-31"), D("2019-12-31")
    sg = []
    for ccy, f in (("USD", usd), ("JPY", lambda i: 0.012), ("EUR", lambda i: 1.5),
                   ("AUD", lambda i: 0.95), ("IDR", idr)):
        sg += _month_end_rows(SG.fx_id(ccy), "singstat", first, last, f)
    sg += _month_end_rows(SG.SGS_10Y, "singstat", first, last, lambda i: 2.5)
    spy = spy if spy is not None else [(d, 400.0) for d in OH.month_ends(first, last)]
    return OH.ForeignReturnSources(
        fred=Fake("sec-edgar", _month_end_rows("DGS10", "sec-edgar", first, last, dgs10)),
        jquantster=Fake("jquantster", _month_end_rows(JQ.JGB_10Y, "jquantster", first, last,
                                                       lambda i: 1.0)),
        dbnomics=Fake("dbnomics", _month_end_rows("ea.bund.10y", "dbnomics", first, last,
                                                   lambda i: 2.0, day1=True)),
        ausdata=Fake("ausdata", _month_end_rows(AGS_10Y, "ausdata", first, last,
                                                 lambda i: 4.0)),
        singstat=Fake("singstat", sg), stocks=FakeStocks(spy))


def test_foreign_currency_return_is_the_move_in_idr_per_local_unit():
    # IDR per USD = (S$ per USD) / (S$ per IDR): 16,000 then 16,800 from 2018-04 on
    src = foreign_return_stores(idr=lambda i: 1.30 / (16_000 if i < 3 else 16_800))
    idr, _local = OH.foreign_returns(src, today=D("2020-01-15"), horizon=3)
    assert idr["USA"]["currency"][(2018, 1)] == pytest.approx(16_800 / 16_000 - 1)  # USD up
    assert idr["USA"]["currency"][(2018, 5)] == pytest.approx(0.0)
    # every other currency is quoted in S$, so it gains on the rupiah by the same move
    assert idr["JPN"]["currency"][(2018, 1)] == pytest.approx(16_800 / 16_000 - 1)
    assert idr["SGP"]["currency"][(2018, 1)] == pytest.approx(16_800 / 16_000 - 1)


def test_foreign_bonds_are_the_local_bond_return_times_the_fx_move():
    src = foreign_return_stores(idr=lambda i: 1.30 / (16_000 if i < 3 else 16_800))
    idr, local = OH.foreign_returns(src, today=D("2020-01-15"), horizon=3)
    carry = 0.04 * 3 / 12
    assert local["USA"]["bonds"][(2018, 1)] == pytest.approx(carry)
    assert idr["USA"]["bonds"][(2018, 1)] == pytest.approx((1 + carry) * 16_800 / 16_000 - 1)
    assert idr["AUS"]["bonds"][(2018, 5)] == pytest.approx(carry)  # fx flat by then
    # the euro-area 10Y is a monthly average dated the 1st: lagged a month as the IDN proxy
    assert (2019, 8) in idr["EMU"]["bonds"] and (2019, 9) not in idr["EMU"]["bonds"]
    assert (2019, 9) in idr["USA"]["bonds"]


def test_only_usa_stocks_have_a_return_and_it_is_spy_in_idr():
    spy = [(d, 400.0 * (1.1 if i >= 3 else 1.0))
           for i, d in enumerate(OH.month_ends(D("2018-01-31"), D("2019-12-31")))]
    src = foreign_return_stores(spy=spy, idr=lambda i: 1.30 / (16_000 if i < 3 else 16_800))
    idr, local = OH.foreign_returns(src, today=D("2020-01-15"), horizon=3)
    assert local["USA"]["stocks"][(2018, 1)] == pytest.approx(0.1)
    assert idr["USA"]["stocks"][(2018, 1)] == pytest.approx(1.1 * 16_800 / 16_000 - 1)
    assert all("stocks" not in idr[s] for s in ("JPN", "EMU", "AUS", "SGP"))


def test_no_foreign_return_from_a_running_month_or_across_a_gap():
    src = foreign_return_stores(dgs10=lambda i: 4.0)
    src = dataclasses.replace(src, fred=Fake("sec-edgar", [
        r for r in src.fred._rows if r.date != D("2018-06-30")]))
    idr, _ = OH.foreign_returns(src, today=D("2019-12-15"), horizon=3)
    usa = idr["USA"]["bonds"]
    assert (2018, 2) in usa and not any((2018, m) in usa for m in (3, 4, 5, 6))
    assert (2019, 8) in usa and (2019, 9) not in usa  # December still running
    assert (2019, 8) in idr["USA"]["currency"] and (2019, 9) not in idr["USA"]["currency"]


def test_foreign_with_returns_joins_each_market_and_leaves_ungated_stocks_empty():
    hs = OH.foreign_replay(F_DATES, foreign_world())
    fwd = {s: {"bonds": {(d.year, d.month): 0.01 for d in F_DATES},
               "currency": {(d.year, d.month): -0.02 for d in F_DATES}} for s in OH.FOREIGN}
    fwd["USA"]["stocks"] = {(d.year, d.month): 0.03 for d in F_DATES}
    joined = {s: OH.with_returns(h, fwd[s]) for s, h in hs.items()}
    assert joined["USA"].rows[0].forward == {"stocks": 0.03, "bonds": 0.01, "currency": -0.02}
    assert joined["JPN"].rows[0].forward["stocks"] is None
