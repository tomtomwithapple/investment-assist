"""Foreign overrides, layer 2 (P28, PLAN S11): macro momentum per foreign market (US, JP, euro
area, AU, SG) turned into one bounded shift of the layer-1 score per asset, clamped to ±10, with
the market's currency measured against IDR.

Most tests feed in-memory sources (tidy `Row`s, no store); the last one runs the real ausdata,
singstat, jquantster and bisfetcher adapters over their fixture stores."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES

from assist.layers.overrides_foreign import (
    EMU_MEMBERS,
    MARKETS,
    WEIGHTS,
    ForeignOverrides,
    MarketOverrides,
    apply,
    foreign_overrides,
    market,
)
from assist.layers.types import MAX_OVERRIDE, AssetScore, Override
from assist.sources import ausdata as aus
from assist.sources import jquantster as jq
from assist.sources import singstat as sg
from assist.sources.ausdata import AusdataSource
from assist.sources.base import Row, SourceUnavailable
from assist.sources.bisfetcher import BisfetcherSource
from assist.sources.idxscape import JISDOR
from assist.sources.jquantster import JquantsterSource
from assist.sources.singstat import SingstatSource

AS_OF = date(2026, 10, 23)
SUBJECTS = {"USA", "JPN", "EMU", "AUS", "SGP"}


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


# ---------------- synthetic series ----------------


def _months(last: date, n: int) -> list[date]:
    out, y, m = [], last.year, last.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return sorted(out)


def _quarter_starts(last: date, n: int) -> list[date]:
    return [d for d in _months(last, 3 * n) if d.month in (1, 4, 7, 10)]


def _quarter_ends(last: date, n: int) -> list[date]:
    out = []
    for d in _quarter_starts(date(last.year, last.month - 2, 1), n):
        m = d.month + 2
        out.append(date(d.year, m, calendar.monthrange(d.year, m)[1]))
    return out


def _days(last: date, n: int = 900) -> list[date]:
    return [last - timedelta(days=i) for i in range(n - 1, -1, -1)]


def series(sid, dates, values, src, recorded=None) -> list[Row]:
    if not isinstance(values, (list, tuple)):
        values = [values] * len(dates)
    return [Row(sid, d, float(v), recorded, src) for d, v in zip(dates, values, strict=True)]


def tail(values: tuple, n: int, fill: float) -> list[float]:
    """`n` values ending in `values`, padded in front with `fill`."""
    return [fill] * (n - len(values)) + list(values)


def monthly(sid, src, values=(), fill=100.0, last=date(2026, 9, 1), n=24, recorded=None):
    return series(sid, _months(last, n), tail(values, n, fill), src, recorded)


def daily(sid, src, values=(), fill=1.0, last=AS_OF - timedelta(days=1), recorded=None):
    dates = _days(last)
    return series(sid, dates, tail(values, len(dates), fill), src, recorded)


def gdp_levels(growth=(2.0,) * 12, last=date(2026, 4, 1)) -> list[Row]:
    """FRED GDPC1 levels whose y/y growth (%) per quarter is `growth`, oldest first."""
    n = len(growth) + 4
    dates = _quarter_starts(last, n)
    levels = [100.0, 100.5, 101.0, 101.5]
    for g in growth:
        levels.append(levels[-4] * (1 + g / 100))
    return series("GDPC1", dates, levels, "sec-edgar", None)


def world(**over) -> dict[str, Fake]:
    """Every store with flat inputs (no momentum anywhere); `over` replaces a store's rows."""
    rows = {
        "fred": gdp_levels() + daily("T10Y2Y", "sec-edgar", fill=0.4)
        + daily("DFF", "sec-edgar", fill=3.875),
        "tic": monthly("for_lt_eqty_net_99996", "sec-edgar", fill=10_000, last=date(2026, 7, 1))
        + monthly("for_lt_treas_net_99996", "sec-edgar", fill=20_000, last=date(2026, 7, 1)),
        "dbnomics": [r for sid in ("usa.cli", "jpn.cli", "g4e.cli", "ea20.bci", "aus.cli")
                     for r in monthly(sid, "dbnomics", fill=100.0)]
        + monthly("usa.cpi.yoy", "dbnomics", fill=3.0)
        + monthly("ea.hicp.yoy", "dbnomics", fill=2.5)
        + monthly("aus.cpi.yoy", "dbnomics", fill=3.5)
        + monthly("ea.bund.10y", "dbnomics", fill=3.0) + monthly("ea.bond.2y", "dbnomics", fill=2.5)
        + daily("ea.rate.deposit", "dbnomics", fill=2.5, last=AS_OF - timedelta(days=6)),
        "bisfetcher": [r for iso2, v in (("US", 3.875), ("JP", 1.0), ("XM", 2.5), ("AU", 4.35),
                                         ("ID", 5.75))
                       for r in monthly(f"WS_CBPOL.M.{iso2}", "bisfetcher", fill=v)],
        "jquantster": series(jq.TANKAN_LM, _quarter_ends(date(2026, 9, 30), 8), [20.0] * 8,
                             "jquantster")
        + daily(jq.JGB_10Y, "jquantster", fill=2.9) + daily(jq.JGB_2Y, "jquantster", fill=1.9)
        + daily(jq.USDJPY, "jquantster", fill=150.0) + daily(jq.CALL_RATE, "jquantster", fill=1.0),
        "ausdata": series(aus.GDP_YY, _quarter_ends(date(2026, 6, 30), 8), [2.0] * 8, "ausdata")
        + monthly(aus.CPI_YY_M, "ausdata", fill=3.5, last=date(2026, 8, 1))
        + daily(aus.CASH_RATE, "ausdata", fill=4.35) + daily(aus.CURVE_10Y_2Y, "ausdata", fill=0.4)
        + daily(aus.AUD_IDR, "ausdata", fill=12_000.0),
        "singstat": series(sg.REAL_GDP_YOY, _quarter_starts(date(2026, 4, 1), 8), [4.0] * 8,
                           "singstat")
        + monthly(sg.CPI, "singstat", fill=103.0, last=date(2026, 8, 1))
        + daily(sg.SORA_3M, "singstat", fill=1.2, last=AS_OF - timedelta(days=2))
        + daily(sg.SGS_10Y, "singstat", fill=2.5, last=AS_OF - timedelta(days=2))
        + daily(sg.SGS_2Y, "singstat", fill=1.9, last=AS_OF - timedelta(days=2))
        + daily(sg.fx_id("IDR"), "singstat", fill=1 / 14_000, last=AS_OF - timedelta(days=2))
        + daily(sg.fx_id("EUR"), "singstat", fill=1.45, last=AS_OF - timedelta(days=2)),
        "usdidr": daily(JISDOR, "idxscape", fill=18_000.0),
    }
    rows.update(over)
    return {k: Fake(k, v) if isinstance(v, list) else v for k, v in rows.items()}


def run(as_of=AS_OF, **over) -> ForeignOverrides:
    return foreign_overrides(as_of, world(**over))


def deltas(m: MarketOverrides) -> dict[str, float]:
    return {o.asset: o.delta for o in m.overrides}


def without(store: str, sid: str) -> list[Row]:
    return [r for r in world()[store]._rows if r.series_id != sid]


# ---------------- shape ----------------


def test_flat_inputs_give_zero_overrides_for_every_market():
    out = run()
    assert isinstance(out, ForeignOverrides)
    assert {m.subject for m in out.markets} == SUBJECTS
    for m in out.markets:
        assert all(isinstance(o, Override) for o in m.overrides)
        assert {o.asset for o in m.overrides} == {"stocks", "bonds", "currency"}
        assert all(o.subject == m.subject and o.as_of == AS_OF for o in m.overrides)
        assert deltas(m) == {"stocks": 0, "bonds": 0, "currency": 0}, m.subject
    assert out.stale_inputs == ()


def test_each_market_reads_its_own_components():
    out = run()
    names = {m.subject: {c.name for c in m.components} for m in out.markets}
    assert names["USA"] == {"growth", "cli", "inflation", "policy", "curve", "fx",
                            "flows_equity", "flows_treasury"}
    assert names["JPN"] == {"growth", "cli", "policy", "curve", "fx"}
    assert names["EMU"] == {"growth", "cli", "inflation", "policy", "curve", "fx"}
    assert names["AUS"] == {"growth", "cli", "inflation", "policy", "curve", "fx"}
    assert names["SGP"] == {"growth", "inflation", "policy", "curve", "fx"}


def test_gaps_are_named_and_show_in_the_reason():
    jpn = run().market("JPN")
    assert dict(jpn.gaps).keys() >= {"inflation"}
    assert "inflation n/a" in jpn.for_asset("bonds").reason
    assert "cli" in dict(run().market("SGP").gaps)


def test_weights_cover_the_three_assets():
    for name, w in WEIGHTS.items():
        assert set(w) == {"stocks", "bonds", "currency"}, name
    for m in MARKETS:
        assert {s.name for s in m.specs} <= set(WEIGHTS)


def test_reason_names_every_component_and_the_idr_terms():
    usa = run().market("USA")
    reason = usa.for_asset("stocks").reason
    for c in usa.components:
        assert c.name in reason
    assert "IDR" in reason


# ---------------- components ----------------


def test_us_gdp_speeding_up_lifts_stocks():
    out = run(fred=gdp_levels(growth=(2.0,) * 11 + (2.8,)) + daily("T10Y2Y", "sec-edgar", fill=0.4))
    usa = out.market("USA")
    g = usa.component("growth")
    assert g.direction == 1
    assert g.value == pytest.approx(0.8, abs=0.01)
    assert deltas(usa)["stocks"] == WEIGHTS["growth"]["stocks"] > 0


def test_us_tic_equity_inflows_lift_stocks_and_the_dollar():
    eq = monthly("for_lt_eqty_net_99996", "sec-edgar", (40_000,) * 3, fill=10_000,
                 last=date(2026, 7, 1))
    tr = monthly("for_lt_treas_net_99996", "sec-edgar", fill=20_000, last=date(2026, 7, 1))
    usa = run(tic=eq + tr).market("USA")
    f = usa.component("flows_equity")
    assert f.direction == 1
    assert f.value == pytest.approx(120_000 - 30_000)
    d = deltas(usa)
    assert d["stocks"] == WEIGHTS["flows_equity"]["stocks"] > 0
    assert d["currency"] == WEIGHTS["flows_equity"]["currency"]


def test_fed_hiking_hurts_us_bonds():
    rates = monthly("WS_CBPOL.M.US", "bisfetcher", (4.5,) * 3, fill=3.875)
    others = [r for r in world()["bisfetcher"]._rows if r.series_id != "WS_CBPOL.M.US"]
    usa = run(bisfetcher=others + rates).market("USA")
    p = usa.component("policy")
    assert p.direction == 1 and p.value == pytest.approx(0.625)
    assert deltas(usa)["bonds"] == WEIGHTS["policy"]["bonds"] < 0


def test_policy_falls_back_to_the_next_source():
    usa = run(bisfetcher=without("bisfetcher", "WS_CBPOL.M.US")).market("USA")
    p = usa.component("policy")
    assert p is not None and p.series_id == "DFF"
    assert any("WS_CBPOL.M.US" in s for s in usa.stale_inputs)


def test_euro_curve_is_bund_10y_minus_the_euro_area_2y():
    dbn = without("dbnomics", "ea.bund.10y") + monthly(
        "ea.bund.10y", "dbnomics", (3.2, 3.4, 3.6), fill=3.0)
    emu = run(dbnomics=dbn).market("EMU")
    c = emu.component("curve")
    assert c.direction == 1  # steepening
    assert c.value == pytest.approx(0.6)
    assert "2Y" in c.detail
    assert deltas(emu)["bonds"] == WEIGHTS["curve"]["bonds"] < 0


def test_rising_hicp_hurts_euro_bonds():
    dbn = without("dbnomics", "ea.hicp.yoy") + monthly(
        "ea.hicp.yoy", "dbnomics", (2.9, 3.2, 3.8), fill=2.5)
    emu = run(dbnomics=dbn).market("EMU")
    assert emu.component("inflation").direction == 1
    assert deltas(emu)["bonds"] == WEIGHTS["inflation"]["bonds"]


def test_tankan_improving_counts_as_japan_growth():
    jqrows = without("jquantster", jq.TANKAN_LM) + series(
        jq.TANKAN_LM, _quarter_ends(date(2026, 9, 30), 8), [20.0] * 7 + [25.0], "jquantster")
    jpn = run(jquantster=jqrows).market("JPN")
    g = jpn.component("growth")
    assert g.direction == 1 and g.value == pytest.approx(5.0)
    assert "Tankan" in g.detail


def test_quarter_end_series_compare_with_the_previous_quarter_end():
    # On 09-25 the newest Tankan is June 30: it compares with March 31, not December 31.
    jqrows = without("jquantster", jq.TANKAN_LM) + series(
        jq.TANKAN_LM, _quarter_ends(date(2026, 9, 30), 8), [10.0] * 5 + [17.0, 22.0, 24.0],
        "jquantster")
    g = run(as_of=date(2026, 9, 25), jquantster=jqrows).market("JPN").component("growth")
    assert g.last.date == date(2026, 6, 30)
    assert g.value == pytest.approx(5.0)
    assert "since 2026-03-31" in g.detail


def test_singapore_cpi_index_becomes_inflation_yoy():
    values = [100.0] * 12 + [100.0 + 0.3 * i for i in range(1, 13)]
    sgrows = without("singstat", sg.CPI) + series(
        sg.CPI, _months(date(2026, 8, 1), 24), values, "singstat")
    s = run(singstat=sgrows).market("SGP")
    infl = s.component("inflation")
    assert infl.direction == 1  # y/y climbs from 2.7% to 3.6% over 3 months
    assert infl.value == pytest.approx(3.6 - 2.7, abs=0.01)


# ---------------- IDR terms ----------------


def test_jpy_gaining_on_idr_is_a_currency_tailwind():
    # USD/JPY falls from 150 to 140 while JISDOR stays: IDR per JPY rises ~7%.
    jqrows = without("jquantster", jq.USDJPY) + daily(jq.USDJPY, "jquantster", (140.0,) * 60,
                                                      fill=150.0)
    jpn = run(jquantster=jqrows).market("JPN")
    fx = jpn.component("fx")
    assert fx.direction == 1
    assert fx.value == pytest.approx((150 / 140 - 1) * 100, rel=1e-3)
    assert deltas(jpn)["currency"] == WEIGHTS["fx"]["currency"] > 0
    assert jpn.idr.level == pytest.approx(18_000 / 140)


def test_euro_is_crossed_through_mas_sgd_rates():
    emu = run().market("EMU")
    assert emu.idr.level == pytest.approx(14_000 * 1.45, rel=1e-6)


def test_hedge_carry_is_bi_rate_against_the_local_short_rate():
    usa = run().market("USA")
    assert usa.idr.carry == pytest.approx(1.0575 / 1.03875 - 1)
    assert usa.idr.level == pytest.approx(18_000)
    assert usa.idr.change_3m == pytest.approx(0.0)


# ---------------- point in time, staleness ----------------


def test_mas_data_older_than_a_week_is_flagged():
    old = AS_OF - timedelta(days=16)
    sgrows = [r for r in world()["singstat"]._rows if not r.series_id.startswith("mas:")]
    for sid, v in ((sg.SORA_3M, 1.2), (sg.SGS_10Y, 2.5), (sg.SGS_2Y, 1.9),
                   (sg.fx_id("IDR"), 1 / 14_000), (sg.fx_id("EUR"), 1.45)):
        sgrows += daily(sid, "singstat", fill=v, last=old)
    out = run(singstat=sgrows)
    s = out.market("SGP")
    assert s.component("policy") is not None  # still used
    assert any(sg.SORA_3M in x and str(old) in x for x in s.stale_inputs)
    assert any(sg.fx_id("EUR") in x for x in out.market("EMU").stale_inputs)


def test_ausdata_is_asked_for_finished_periods_only():
    stores = world()
    foreign_overrides(AS_OF, stores)
    assert all(c.get("as_of") == AS_OF for c in stores["ausdata"].calls)
    for name, f in stores.items():
        assert all(c["end"] == AS_OF and c["start"] is not None for c in f.calls), name


def test_au_cpi_falls_back_to_dbnomics():
    a = run(ausdata=without("ausdata", aus.CPI_YY_M)).market("AUS")
    assert a.component("inflation").source == "dbnomics"
    assert any(aus.CPI_YY_M in s for s in a.stale_inputs)


def test_too_short_a_history_falls_back_too():
    # ABS monthly CPI starts in 2025-04: a mid-2025 backtest needs the OECD series.
    short = monthly(aus.CPI_YY_M, "ausdata", fill=3.5, last=date(2026, 8, 1), n=2)
    a = run(ausdata=without("ausdata", aus.CPI_YY_M) + short).market("AUS")
    assert a.component("inflation").source == "dbnomics"
    assert any(aus.CPI_YY_M in s and "history from" in s for s in a.stale_inputs)


def test_dbnomics_rows_without_vintage_wait_for_their_lag():
    cli = monthly("usa.cli", "dbnomics", (90.0,), fill=100.0)  # Sep point, 45-day lag
    dbn = without("dbnomics", "usa.cli") + cli
    usa = run(as_of=date(2026, 10, 10), dbnomics=dbn).market("USA")
    assert usa.component("cli").last.date < date(2026, 9, 1)


def test_missing_store_goes_to_stale_inputs_not_failure():
    out = run(tic=Fake("tic", error="missing"))
    usa = out.market("USA")
    assert usa.component("flows_equity") is None
    assert any("(missing)" in s for s in usa.stale_inputs)
    assert all("(missing)" not in s for s in out.market("AUS").stale_inputs)


def test_every_store_missing_still_returns_zero_overrides():
    gone = {k: Fake(k, error="missing") for k in world()}
    out = foreign_overrides(AS_OF, gone)
    for m in out.markets:
        assert deltas(m) == {"stocks": 0, "bonds": 0, "currency": 0}
        assert m.components == ()
        assert m.idr is None


def test_store_not_given_is_not_configured():
    stores = world()
    del stores["tic"]
    out = foreign_overrides(AS_OF, stores)
    assert "tic (not configured)" in out.market("USA").stale_inputs


def test_short_history_is_named_not_used():
    ausrows = without("ausdata", aus.GDP_YY) + series(
        aus.GDP_YY, [date(2026, 6, 30)], [2.0], "ausdata")
    a = run(ausdata=ausrows).market("AUS")
    assert a.component("growth") is None
    assert any(aus.GDP_YY in s for s in a.stale_inputs)


# ---------------- clamp, apply, subjects ----------------


def test_everything_bullish_for_us_stocks_is_clamped_to_ten():
    fred = gdp_levels(growth=(1.0,) * 11 + (3.0,)) + daily(
        "T10Y2Y", "sec-edgar", (1.0,) * 30, fill=0.2)
    dbn = (without("dbnomics", "usa.cli") + monthly("usa.cli", "dbnomics", (101, 102, 103)))
    eq = monthly("for_lt_eqty_net_99996", "sec-edgar", (60_000,) * 3, fill=0,
                 last=date(2026, 7, 1))
    tr = monthly("for_lt_treas_net_99996", "sec-edgar", fill=20_000, last=date(2026, 7, 1))
    bis = without("bisfetcher", "WS_CBPOL.M.US") + monthly(
        "WS_CBPOL.M.US", "bisfetcher", (3.25,) * 3, fill=3.875)  # the Fed cutting
    usa = run(fred=fred, dbnomics=dbn, tic=eq + tr, bisfetcher=bis).market("USA")
    assert usa.raw["stocks"] > MAX_OVERRIDE
    assert usa.for_asset("stocks").delta == MAX_OVERRIDE
    assert "capped" in usa.for_asset("stocks").reason


def test_euro_members_read_the_euro_area_override():
    out = run()
    assert set(EMU_MEMBERS) >= {"DEU", "FRA"}
    assert out.for_asset("DEU", "bonds") is out.market("EMU").for_asset("bonds")
    assert out.for_asset("IDN", "bonds") is None
    assert market("EMU").currency == "EUR"


def test_apply_shifts_and_bounds_the_layer1_score():
    o = Override("USA", "stocks", AS_OF, 8.0, "r", ("dbnomics",))
    assert apply(AssetScore("USA", "stocks", AS_OF, 95.0, 0.7), o) == 100.0
    assert apply(50.0, o) == 58.0


# ---------------- real adapters over fixture stores ----------------


def _duck(path: Path, *sql: Path) -> Path:
    con = duckdb.connect(str(path))
    try:
        for f in sql:
            con.execute(f.read_text())
    finally:
        con.close()
    return path


def _sqlite(path: Path, *sql: Path) -> Path:
    import sqlite3

    con = sqlite3.connect(path)
    try:
        for f in sql:
            con.executescript(f.read_text())
        con.commit()
    finally:
        con.close()
    return path


def test_runs_over_the_real_adapters(tmp_path):
    stores = world()
    stores["ausdata"] = AusdataSource(_duck(tmp_path / "aus.duckdb", FIXTURES / "ausdata" /
                                            "schema.sql", FIXTURES / "ausdata" / "seed.sql"))
    stores["singstat"] = SingstatSource(_duck(tmp_path / "sg.duckdb", FIXTURES / "singstat" /
                                              "schema.sql", FIXTURES / "singstat" / "seed.sql"))
    stores["bisfetcher"] = BisfetcherSource(_duck(tmp_path / "bis.duckdb", FIXTURES /
                                                  "bisfetcher" / "schema.sql", FIXTURES /
                                                  "bisfetcher" / "seed.sql"))
    stores["jquantster"] = JquantsterSource(_sqlite(tmp_path / "jq.db", FIXTURES / "jquantster" /
                                                    "schema.sql", FIXTURES / "jquantster" /
                                                    "data.sql"))
    out = foreign_overrides(AS_OF, stores)
    assert {m.subject for m in out.markets} == SUBJECTS
    assert {"ausdata", "singstat", "bisfetcher", "jquantster"} <= set(out.sources)
    for m in out.markets:
        assert all(abs(o.delta) <= MAX_OVERRIDE for o in m.overrides)


# ---------------- USD/IDR on the P65 splice (P80, phase L choice 12) ----------------


def _splice(jisdor_days: int = 11, jisdor: float = 16_800.0, mas: float = 16_000.0):
    """The P65 splice over fake stores: MAS USD and IDR legs (S$ per unit) daily for ~2.5
    years up to the day before JISDOR's first fixing, then `jisdor_days` JISDOR fixings
    recorded on their own dates, as idxscape holds them on this Mac (from 2026-10-22)."""
    from assist.sources.usdidr import UsdIdrSource

    days = [d for d in _days(AS_OF - timedelta(days=1)) if d.weekday() < 5]
    fixings = days[-jisdor_days:]
    before = [d for d in days if d < fixings[0]]
    sgd_per_usd = 1.30
    mas_rows = (series(sg.fx_id("USD"), before, [sgd_per_usd] * len(before), "singstat")
                + series(sg.fx_id("IDR"), before, [sgd_per_usd / mas] * len(before), "singstat"))
    jis_rows = [Row(JISDOR, d, jisdor, d, "idxscape") for d in fixings]
    return UsdIdrSource(Fake("idxscape", jis_rows), Fake("singstat", mas_rows)), fixings


def test_usa_and_jpn_fx_read_usd_idr_from_the_splice():
    """11 JISDOR fixings plus the MAS cross before them give USA and JPN a 3-month change."""
    usdidr, fixings = _splice()
    out = run(usdidr=usdidr)
    usa, jpn = out.market("USA"), out.market("JPN")
    fx = usa.component("fx")
    assert fx is not None, usa.stale_inputs
    assert fx.value == pytest.approx((16_800 / 16_000 - 1) * 100, rel=1e-6)  # +5%: USD up
    assert fx.direction == 1 and fx.last.date == fixings[-1]
    assert jpn.component("fx") is not None
    assert jpn.component("fx").value == pytest.approx((16_800 / 16_000 - 1) * 100, rel=1e-6)
    assert not any("JISDOR" in s for s in out.stale_inputs)
    assert usa.idr.level == pytest.approx(16_800)


def test_jisdor_alone_is_too_short_for_the_3_month_change():
    """Without the MAS cross (idxscape's JISDOR from 2026-10-22 only) the fx component is n/a
    and named, as it was live before P80."""
    from assist.sources.usdidr import UsdIdrSource

    _, fixings = _splice()
    jis = [Row(JISDOR, d, 16_800.0, d, "idxscape") for d in fixings]
    out = run(usdidr=UsdIdrSource(Fake("idxscape", jis), Fake("singstat", error="missing")))
    assert out.market("USA").component("fx") is None
    assert any(f"history from {fixings[0]}" in s for s in out.market("USA").stale_inputs)


def test_the_mas_leg_waits_its_one_day_lag():
    """A MAS cross point (no vintage) counts from the day after its date."""
    usdidr, fixings = _splice(jisdor_days=1)
    out = run(as_of=fixings[0] - timedelta(days=1), usdidr=usdidr)
    fx = out.market("USA").component("fx")
    assert fx is not None and fx.last.date < fixings[0] - timedelta(days=1)


def test_default_sources_serve_usd_idr_from_the_splice():
    from assist.layers.overrides_foreign import default_sources
    from assist.sources.usdidr import UsdIdrSource

    src = default_sources(env={"ASSIST_SIBLINGS_ROOT": "/nonexistent"})
    assert isinstance(src["usdidr"], UsdIdrSource)
    assert "idxscape" not in src
