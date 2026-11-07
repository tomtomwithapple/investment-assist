"""idx-method `factor_series` (P33): 10y daily price and mktcap, quarterly fundamentals point in
time, derived PE / PBV / P/CFO / EV/EBIT, and dividends, read from stockbiter.db READ-ONLY.

tests/fixtures/idxmethod_series/stockbiter.sql is built into a tmp idx-method root per test; its
schema is the real store's (inspected read-only 2026-10-27)."""

from __future__ import annotations

import shutil
from datetime import date

import pytest
from helpers import FIXTURES, make_sqlite

from assist.candidates.screens import LAG_DAYS
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_series import (
    DB,
    FUNDAMENTALS,
    SOURCE,
    Bar,
    Fundamentals,
    IdxMethodSeries,
    Multiples,
    multiples,
    quarter_ends,
)

FIX = FIXTURES / "idxmethod_series"
D = date.fromisoformat


def _root(tmp_path, *, drop: str | None = None):
    ddl = (FIX / "stockbiter.sql").read_text()
    db = tmp_path / DB
    db.parent.mkdir(parents=True)
    make_sqlite(db, ddl)
    if drop:
        import sqlite3

        con = sqlite3.connect(db)
        con.execute(f"drop table {drop}")
        con.commit()
        con.close()
    shutil.copytree(FIX / "cache", tmp_path / "cache")
    return tmp_path


@pytest.fixture
def src(tmp_path) -> IdxMethodSeries:
    return IdxMethodSeries(_root(tmp_path))


def test_name_and_lag():
    assert SOURCE == "idx-method"
    assert LAG_DAYS == 120
    assert FUNDAMENTALS == (
        "cfo_ttm",
        "equity",
        "net_debt",
        "ni_ttm",
        "op_income_ttm",
        "roa",
        "roce",
        "total_assets",
        "total_debt",
    )


def test_symbols_keep_delisted(src):
    assert src.symbols() == ["BBCA", "GONE", "LOSS"]
    uni = src.universe()
    assert uni["GONE"]["delisted"] is True and uni["BBCA"]["delisted"] is False
    assert uni["BBCA"]["sector"] == "Keuangan"


def test_daily_joins_price_and_mktcap(src):
    bars = src.daily(["BBCA"])["BBCA"]
    assert bars[0] == Bar(D("2025-12-30"), 8000.0, 1000000.0)
    assert Bar(D("2026-07-01"), 9400.0, None) in bars
    assert [b.date for b in bars] == sorted(b.date for b in bars)
    assert isinstance(bars[0].price, float)


def test_daily_filters_dates(src):
    out = src.daily(start=D("2026-06-30"), end=D("2026-07-01"))
    assert set(out) == {"BBCA"}
    assert [b.date for b in out["BBCA"]] == [D("2026-06-30"), D("2026-07-01")]


def test_quarterly_keeps_quarter_ends_only_with_available_date(src):
    q = src.quarterly()
    bbca = q["BBCA"]
    assert [f.period for f in bbca] == [D("2025-12-31"), D("2026-03-31")]  # 2026-10-26 echo dropped
    f = bbca[0]
    assert f.available == D("2026-04-30")  # period end + 120 days
    assert (f.ni_ttm, f.equity, f.net_debt, f.roa) == (100000.0, 400000.0, -200000.0, 3.63)
    assert bbca[1].roce is None  # not reported for that quarter
    assert [f.period for f in q["GONE"]] == [D("2016-12-31")]  # stray daily-dated rows dropped


def test_known_at_returns_only_available_rows(src):
    assert src.known_at("BBCA", D("2026-04-29")) == []
    assert [f.period for f in src.known_at("BBCA", D("2026-04-30"))] == [D("2025-12-31")]
    assert [f.period for f in src.known_at("BBCA", D("2026-07-29"))] == [
        D("2025-12-31"),
        D("2026-03-31"),
    ]
    assert src.known_at("NOPE", D("2026-07-29")) == []


def test_multiples_pure():
    f = Fundamentals(
        D("2025-12-31"),
        D("2026-04-30"),
        80000,
        400000,
        -200000,
        100000,
        120000,
        None,
        None,
        None,
        None,
    )
    m = multiples(1300000, f)
    assert m == {
        "pe": 13.0,
        "pbv": 3.25,
        "p_cfo": 16.25,
        "ev_ebit": pytest.approx(1100000 / 120000),
    }
    loss = Fundamentals(D("2025-12-31"), D("2026-04-30"), -5, 0, 100, -10, 0, *[None] * 4)
    assert multiples(1000, loss) == {"pe": None, "pbv": None, "p_cfo": None, "ev_ebit": None}
    assert multiples(None, f) == {"pe": None, "pbv": None, "p_cfo": None, "ev_ebit": None}


def test_multiples_at_point_in_time(src):
    m = src.multiples_at("BBCA", D("2026-06-30"))
    assert m == Multiples(
        D("2026-06-30"),
        D("2026-06-30"),
        9500.0,
        1300000.0,
        D("2025-12-31"),
        13.0,
        3.25,
        16.25,
        pytest.approx(1100000 / 120000),
    )
    late = src.multiples_at("BBCA", D("2026-10-27"))
    assert (late.bar_date, late.period) == (D("2026-10-26"), D("2026-03-31"))
    assert (late.pe, late.pbv, late.p_cfo, late.ev_ebit) == (5.0, 1.25, 10.0, 6.0)


def test_multiples_use_last_bar_with_mktcap(src):
    m = src.multiples_at("BBCA", D("2026-07-01"))
    assert (m.bar_date, m.mktcap, m.pe) == (D("2026-06-30"), 1300000.0, 13.0)


def test_multiples_none_before_any_fundamentals_or_bars(src):
    m = src.multiples_at("BBCA", D("2025-12-31"))
    assert (m.bar_date, m.period, m.pe) == (D("2025-12-30"), None, None)
    assert src.multiples_at("BBCA", D("2020-01-01")) is None
    loss = src.multiples_at("LOSS", D("2026-10-26"))
    assert (loss.pe, loss.pbv, loss.p_cfo, loss.ev_ebit) == (None, None, None, None)


def test_quarter_ends():
    assert quarter_ends(D("2025-12-30"), D("2026-10-26")) == [
        D("2025-12-31"),
        D("2026-03-31"),
        D("2026-06-30"),
        D("2026-09-30"),
    ]
    assert quarter_ends(D("2026-03-31"), D("2026-03-31")) == [D("2026-03-31")]


def test_multiples_series_defaults_to_quarter_ends(src):
    ms = src.multiples_series("BBCA")
    assert [m.date for m in ms] == [
        D("2025-12-31"),
        D("2026-03-31"),
        D("2026-06-30"),
        D("2026-09-30"),
    ]
    assert [m.pe for m in ms] == [None, None, 13.0, pytest.approx(1300000 / 120000)]
    assert ms[-1].period == D("2026-03-31")  # Q1 available 2026-07-29


def test_dividends_from_table(src):
    divs = src.dividends()
    assert divs["BBCA"] == [
        {"ex": "2025-12-03", "value": 55.0, "ccy": "CURRENCY_IDR"},
        {"ex": "2026-03-30", "value": 281.0, "ccy": "CURRENCY_IDR"},
    ]
    assert set(src.dividends(["GONE"])) == {"GONE"}


def test_dividends_fall_back_to_cache_files(tmp_path):
    src = IdxMethodSeries(_root(tmp_path, drop="dividends"))
    assert src.dividends(["BBCA"]) == {
        "BBCA": [{"ex": "2025-12-03", "value": 55.0, "ccy": "CURRENCY_IDR"}]
    }


def test_missing_db_is_unavailable(tmp_path):
    src = IdxMethodSeries(tmp_path)
    with pytest.raises(SourceUnavailable) as e:
        src.daily()
    assert e.value.reason == "missing" and e.value.source == "idx-method"


def test_missing_table_is_unavailable(tmp_path):
    src = IdxMethodSeries(_root(tmp_path, drop="factor_series"))
    with pytest.raises(SourceUnavailable) as e:
        src.quarterly()
    assert e.value.reason == "missing" and "factor_series" in e.value.detail


def test_span_per_item(src):
    span = src.span()
    assert span["price"] == ("daily", 3, D("2017-03-01"), D("2026-10-26"))
    assert span["ni_ttm"][0] == "quarterly"


def test_store_opened_read_only(src, tmp_path):
    before = sorted(p.name for p in (tmp_path / DB).parent.iterdir())
    src.daily()
    src.quarterly()
    src.dividends()
    assert sorted(p.name for p in (tmp_path / DB).parent.iterdir()) == before


# ---------------- P66: the factor_series EY provider (FactorSnapshots' interface) ----------------

EY_FIX = FIXTURES / "history" / "factor_ey.sql"


@pytest.fixture
def ey(tmp_path):
    from assist.sources.idxmethod_series import FactorSeriesEY

    db = tmp_path / DB
    db.parent.mkdir(parents=True)
    make_sqlite(db, EY_FIX.read_text())
    return FactorSeriesEY(tmp_path)


def test_ey_provider_has_the_snapshot_interface(ey):
    assert ey.name == "idx-method"
    on, factors = ey.factors_on(D("2026-10-30"))
    assert on == D("2026-10-30")
    assert factors["AAA"] == {"mktcap": 3000.0, "pe": 10.0, "earnings_yield": 10.0}
    assert factors["BBB"]["earnings_yield"] == pytest.approx(-20.0)  # loss maker kept
    assert factors["ZZZ"]["earnings_yield"] is None  # PE 0: no earnings yield


def test_ey_cap_weighted_counts_loss_makers(ey):
    from assist.layers.rules import market_earnings_yield

    _, factors = ey.factors_on(D("2026-10-30"))
    value, n, cap = market_earnings_yield(factors)
    assert n == 2 and cap == 4000.0
    assert value == pytest.approx((3000 * 10 - 1000 * 20) / 4000)


def test_ey_weekend_carries_the_last_trading_day(ey):
    assert ey.factors_on(D("2026-11-01"))[0] == D("2026-10-30")  # Sunday


def test_ey_steps_on_the_filing_day_without_extra_lag(ey):
    assert ey.factors_on(D("2026-10-30"))[1]["AAA"]["pe"] == 10.0
    assert ey.factors_on(D("2026-11-02"))[1]["AAA"]["pe"] == 20.0


def test_ey_never_reads_after_as_of(ey):
    on, factors = ey.factors_on(D("2026-11-06"))
    assert on == D("2026-11-02")
    assert factors["AAA"]["pe"] == 20.0  # the 2026-11-09 row is not known yet


def test_ey_drops_a_pull_date_echo_and_quiet_names(ey):
    on, factors = ey.factors_on(D("2026-11-03"))
    assert "OLD" not in factors  # delisted 2023, echoed on the pull date
    assert "QUIET" not in factors  # no row within the window
    assert on == D("2026-11-02")


def test_ey_before_the_series_is_unavailable(ey):
    with pytest.raises(SourceUnavailable) as e:
        ey.factors_on(D("2016-01-01"))
    assert e.value.reason == "missing" and e.value.source == "idx-method"


def test_ey_history_on_dates(ey):
    hist = ey.history([D("2026-10-30"), D("2026-11-02"), D("2016-01-01")])
    assert [d for d, _ in hist] == [D("2026-10-30"), D("2026-11-02")]
    assert hist[1][1] == pytest.approx((3000 * 5 - 1000 * 20) / 4000)


def test_ey_missing_store(tmp_path):
    from assist.sources.idxmethod_series import FactorSeriesEY

    with pytest.raises(SourceUnavailable) as e:
        FactorSeriesEY(tmp_path).factors_on(D("2026-10-30"))
    assert e.value.reason == "missing"
