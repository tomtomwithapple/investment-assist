"""ausdata adapter (P25): read-only DuckDB over `warehouse.duckdb` (RBA, ABS, AOFM, derived).

The fixture (tests/fixtures/ausdata) is ausdata's own DDL (its store.py SCHEMA, incl. S26's
`raw_loads`) seeded with real values: cash rate, AGS 2y/10y, AUD/USD, AUD/IDR, CPI, unemployment,
GDP, the AOFM non-resident share and two derived indicators."""

from __future__ import annotations

from datetime import date, datetime

import duckdb
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.ausdata import (
    AGS_2Y,
    AGS_10Y,
    AUD_IDR,
    AUD_IDR_M,
    AUD_USD,
    AUD_USD_M,
    CASH_RATE,
    CPI_YY_M,
    GDP_YY,
    NONRES_AGS_PCT,
    SOURCE,
    UNEMPLOYMENT,
    AusdataSource,
    period_end,
)
from assist.sources.base import Row, Source, SourceUnavailable, read_rows

FIX = FIXTURES / "ausdata"
REGION = "ABS.ABS_REGIONAL_ASGS2021.ERP_P_20.SA4.123.A"


def _build(path, raw_loads: bool = True):
    con = duckdb.connect(str(path))
    try:
        ddl = (FIX / "schema.sql").read_text()
        seed = (FIX / "seed.sql").read_text()
        if not raw_loads:  # a warehouse built before ausdata S26 (as live on 2026-10-23)
            ddl = ddl[: ddl.index("CREATE TABLE IF NOT EXISTS raw_loads")]
            seed = seed[: seed.index("INSERT INTO raw_loads")]
        con.execute(ddl)
        con.execute(seed)
    finally:
        con.close()
    return path


@pytest.fixture
def store(tmp_path):
    return _build(tmp_path / "warehouse.duckdb")


def src(path, **kw) -> AusdataSource:
    return AusdataSource(path, retry_delay=0, **kw)


def test_is_a_source(store):
    assert isinstance(src(store), Source)
    assert src(store).name == SOURCE == "ausdata"


def test_ids_match_ausdata_brief():
    assert (CASH_RATE, AGS_2Y, AGS_10Y) == ("FIRMMCRTD", "FCMYGBAG2D", "FCMYGBAG10D")
    assert (AUD_USD, AUD_IDR) == ("FXRUSD", "FXRIR")
    assert (AUD_USD_M, AUD_IDR_M) == ("FXRUSD_M", "FXRIR_M")
    assert CPI_YY_M == "ABS.CPI.3.10001.10.50.M"
    assert UNEMPLOYMENT == "ABS.LF.M13.3.1599.20.AUS.M"
    assert GDP_YY == "DER.GDP_YY" and NONRES_AGS_PCT == "AOFM.FH.AGS.NONRES_PCT"


def test_cash_rate_rows(store):
    assert src(store).rows([CASH_RATE]) == [
        Row(CASH_RATE, date(2026, 10, 16), 4.6, date(2026, 10, 21), SOURCE),
        Row(CASH_RATE, date(2026, 10, 19), 4.6, date(2026, 10, 21), SOURCE),
        Row(CASH_RATE, date(2026, 10, 20), 4.6, date(2026, 10, 21), SOURCE),
    ]


def test_rows_sorted_and_windowed(store):
    ids = [AUD_IDR, AGS_10Y, CPI_YY_M]
    rows = src(store).rows(ids, start=date(2026, 8, 1), end=date(2026, 10, 19))
    assert [(r.series_id, r.date, r.value) for r in rows] == [
        (CPI_YY_M, date(2026, 8, 1), 4.0),
        (AGS_10Y, date(2026, 10, 13), 5.288),
        (AGS_10Y, date(2026, 10, 14), 5.314),
        (AUD_IDR, date(2026, 10, 19), 12585.0),
    ]
    assert rows[1].as_of == date(2026, 10, 17)


def test_period_end_abs_is_period_start_dated():
    assert period_end("abs", "Monthly", CPI_YY_M, date(2026, 8, 1)) == date(2026, 8, 31)
    q = "ABS.ANA_AGG.M1.GPM.20.AUS.Q"
    assert period_end("abs", "Quarterly", q, date(2026, 4, 1)) == date(2026, 6, 30)
    assert period_end("abs", "", REGION, date(2025, 1, 1)) == date(2025, 12, 31)
    # RBA, AOFM and derived rows are already dated at period end
    assert period_end("rba", "Daily", CASH_RATE, date(2026, 10, 20)) == date(2026, 10, 20)
    assert period_end("derived", "Monthly", "DER.X", date(2026, 10, 31)) == date(2026, 10, 31)


def test_point_in_time_uses_period_end(store):
    s = src(store)
    # August CPI (dated 2026-08-01) only counts once August is over
    assert [r.date for r in s.rows([CPI_YY_M], as_of=date(2026, 8, 30))] == [date(2026, 7, 1)]
    assert len(s.rows([CPI_YY_M], as_of=date(2026, 8, 31))) == 2
    # the derived partial month dated 2026-10-31 is not visible on 2026-10-23
    rows = s.rows(["DER.REAL_CASH_RATE"], as_of=date(2026, 10, 23))
    assert [r.date for r in rows] == [date(2026, 9, 30)]


def test_null_value_kept_as_none(store):
    rows = src(store).rows([GDP_YY])
    assert rows[-1].date == date(2026, 9, 30) and rows[-1].value is None


def test_unknown_and_empty_ids(store):
    s = src(store)
    assert s.rows(["NOPE"]) == [] and s.rows([]) == []


def test_all_rows_by_default(store):
    rows = src(store).rows()
    assert len(rows) == 25 and {r.source for r in rows} == {SOURCE}


def test_series_catalog(store):
    cat = {s["series_id"]: s for s in src(store).series()}
    assert len(cat) == 12
    fx = cat[AUD_IDR]
    assert fx["source"] == "rba" and fx["unit"] == "IDR" and fx["frequency"] == "Daily"
    assert fx["extra"]["table"] == "F11.1"
    assert fx["first_date"] == date(2026, 10, 19) and fx["last_date"] == date(2026, 10, 20)
    assert fx["n_obs"] == 2
    assert cat[CPI_YY_M]["extra"] == {}
    assert [s["series_id"] for s in src(store).series(source="aofm")] == [NONRES_AGS_PCT]


def test_latest(store):
    latest = {r["series_id"]: r for r in src(store).latest()}
    assert len(latest) == 12
    assert latest[AUD_IDR]["date"] == date(2026, 10, 20) and latest[AUD_IDR]["value"] == 12578.0
    # newest non-null: the null 2026-Q3 GDP row is skipped
    assert latest[GDP_YY]["date"] == date(2026, 6, 30)
    assert latest[UNEMPLOYMENT]["period_end"] == date(2026, 9, 30)
    assert latest[UNEMPLOYMENT]["pulled_at"] == datetime(2026, 10, 21, 3, 0, 17)
    assert latest[UNEMPLOYMENT]["unit"] == "Percent"


def test_latest_by_id_and_point_in_time(store):
    s = src(store)
    then = s.latest([CPI_YY_M, "DER.REAL_CASH_RATE", AUD_USD], as_of=date(2026, 10, 19))
    assert [(r["series_id"], r["date"], r["value"]) for r in then] == [
        (CPI_YY_M, date(2026, 8, 1), 4.0),
        ("DER.REAL_CASH_RATE", date(2026, 9, 30), 1.0),
        (AUD_USD, date(2026, 10, 19), 0.6975),
    ]
    assert s.latest([]) == []


def test_loads_and_freshness(store):
    s = src(store)
    loads = s.loads()
    assert [(r["source"], r["dataset"]) for r in loads] == [
        ("abs", "cpi"),
        ("aofm", "foreign_holdings"),
        ("rba", "f1"),
    ]
    fresh = {r["source"]: r for r in s.freshness()}
    assert set(fresh) == {"abs", "aofm", "derived", "rba"}
    rba = fresh["rba"]
    assert rba["series"] == 5 and rba["observations"] == 11
    assert rba["last_date"] == date(2026, 10, 20)
    assert rba["last_pulled_at"] == datetime(2026, 10, 21, 3, 0, 9)
    assert rba["last_loaded_at"] == datetime(2026, 10, 21, 3, 0, 8)
    assert fresh["derived"]["last_loaded_at"] is None  # derived rows have no raw archive


def test_store_before_raw_loads(tmp_path):
    """A warehouse not yet refreshed since ausdata S26 has no `raw_loads`: still readable."""
    s = src(_build(tmp_path / "old.duckdb", raw_loads=False))
    assert s.loads() == []
    assert {r["last_loaded_at"] for r in s.freshness()} == {None}
    assert len(s.rows([AUD_IDR])) == 2


def test_missing_store(tmp_path):
    rows, stale = read_rows(src(tmp_path / "nope.duckdb"), [CASH_RATE])
    assert rows == [] and stale == ["ausdata (missing)"]


def test_store_without_tables_is_missing(tmp_path):
    path = tmp_path / "empty.duckdb"
    duckdb.connect(str(path)).close()
    with pytest.raises(SourceUnavailable) as e:
        src(path).rows([CASH_RATE])
    assert e.value.reason == "missing"


def test_locked_store_after_retries(store, monkeypatch):
    calls = []
    import assist.sources.ausdata as mod

    real = mod.duckdb_ro

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(mod, "duckdb_ro", counting)
    with hold_duckdb_lock(store):
        rows, stale = read_rows(src(store, retries=3), [CASH_RATE])
    assert rows == [] and stale == ["ausdata (locked)"]
    assert len(calls) == 3


def test_never_writes(store):
    before = store.stat().st_mtime_ns
    s = src(store)
    s.rows(), s.series(), s.latest(), s.loads(), s.freshness()
    assert store.stat().st_mtime_ns == before
    duckdb.connect(str(store)).close()  # no connection left open


def test_from_config_env_overrides(store, tmp_path):
    assert AusdataSource.from_config(env={"ASSIST_AUSDATA_DB": str(store)}).path == store
    env = {"ASSIST_AUSDATA_DB": "", "AUSDATA_DB": str(store)}
    assert AusdataSource.from_config(env=env).path == store
    env = {"ASSIST_SIBLINGS_ROOT": str(tmp_path), "ASSIST_AUSDATA_DB": "", "AUSDATA_DB": ""}
    assert AusdataSource.from_config(env=env).path == tmp_path / "ausdata/warehouse.duckdb"
