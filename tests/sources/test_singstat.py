"""singstat adapter (P24): read-only DuckDB over singstat's `data/sgecon.duckdb`.

The fixture (tests/fixtures/singstat) is singstat's own DDL (`sgecon.store.SCHEMA` plus the live
`refresh_log`) seeded with real values: SORA, compounded SORA 3m, SGS 2y/10y, T-bill 6m, USD/SGD,
IDR/SGD and headline CPI."""

from __future__ import annotations

from datetime import date, datetime

import duckdb
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.base import Row, Source, SourceUnavailable, read_rows
from assist.sources.singstat import (
    CPI,
    IDR_PER_SGD,
    REAL_GDP_YOY,
    SGS_2Y,
    SGS_10Y,
    SORA,
    SORA_3M,
    SOURCE,
    TBILL_6M,
    USD_SGD,
    SingstatSource,
    fx_id,
)

FIX = FIXTURES / "singstat"
MAS_AS_OF = date(2026, 10, 7)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "sgecon.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute((FIX / "schema.sql").read_text())
        con.execute((FIX / "seed.sql").read_text())
    finally:
        con.close()
    return path


def src(path, **kw):
    return SingstatSource(path, retries=kw.pop("retries", 1), retry_delay=0, **kw)


def test_is_a_source(store):
    assert isinstance(SingstatSource(store), Source)
    assert SingstatSource(store).name == SOURCE == "singstat"


def test_ids_match_singstat_store():
    assert SORA == "mas:sora" and SORA_3M == "mas:sora:comp3m"
    assert SGS_2Y == "mas:sgs:2y" and SGS_10Y == "mas:sgs:10y" and TBILL_6M == "mas:tbill:6m"
    assert USD_SGD == "mas:fx:usdsgd" == fx_id("USD") == fx_id("usd")
    assert CPI == "singstat:M213751:1" and REAL_GDP_YOY == "singstat:M015631:2"


def test_sora_rows(store):
    assert src(store).rows([SORA]) == [
        Row(SORA, date(2026, 10, 2), 1.3724, MAS_AS_OF, SOURCE),
        Row(SORA, date(2026, 10, 5), 1.3484, MAS_AS_OF, SOURCE),
        Row(SORA, date(2026, 10, 6), 1.3152, MAS_AS_OF, SOURCE),
    ]


def test_rows_sorted_and_windowed(store):
    rows = src(store).rows([SGS_10Y, SGS_2Y, CPI], start=date(2026, 8, 1), end=date(2026, 10, 6))
    assert [(r.series_id, r.date, r.value) for r in rows] == [
        (SGS_10Y, date(2026, 10, 6), 2.5),
        (SGS_2Y, date(2026, 10, 6), 1.96),
        (CPI, date(2026, 8, 1), 103.334),
    ]


def test_null_value_kept_as_none(store):
    rows = src(store).rows([fx_id("IDR")], start=date(2026, 10, 8))
    assert rows == [Row("mas:fx:idrsgd", date(2026, 10, 8), None, MAS_AS_OF, SOURCE)]


def test_unknown_and_empty_ids(store):
    assert src(store).rows(["mas:fx:zzzsgd"]) == []
    assert src(store).rows([]) == []


def test_all_rows_by_default(store):
    rows = src(store).rows()
    assert len(rows) == 19
    assert {r.source for r in rows} == {SOURCE}


def test_series_catalog(store):
    cat = {s["series_id"]: s for s in src(store).series()}
    assert len(cat) == 9
    sgs = cat[SGS_10Y]
    assert sgs["source"] == "mas" and sgs["unit"] == "% p.a." and sgs["frequency"] == "D"
    assert sgs["first_date"] == date(2026, 10, 6) and sgs["last_date"] == MAS_AS_OF
    assert sgs["n_obs"] == 2 and sgs["updated_at"] == datetime(2026, 10, 7, 19, 29, 0)
    assert cat["ura:empty"]["n_obs"] == 0 and cat["ura:empty"]["last_date"] is None


def test_series_filters(store):
    s = src(store)
    assert [r["series_id"] for r in s.series(origin="singstat")] == [CPI]
    assert [r["series_id"] for r in s.series(prefix="mas:fx:")] == ["mas:fx:idrsgd", USD_SGD]


def test_latest(store):
    latest = {r["series_id"]: r for r in src(store).latest()}
    assert set(latest) == {SORA, SORA_3M, SGS_2Y, SGS_10Y, TBILL_6M, USD_SGD, "mas:fx:idrsgd", CPI}
    assert latest[SORA]["date"] == date(2026, 10, 6) and latest[SORA]["value"] == 1.3152
    assert latest[CPI]["unit"] == "Index" and latest[CPI]["title"] == "All Items"
    # the newest non-null value, not the null cell after it
    assert latest["mas:fx:idrsgd"]["date"] == MAS_AS_OF
    assert latest["mas:fx:idrsgd"]["value"] == 7.155e-05


def test_latest_by_id_and_point_in_time(store):
    s = src(store)
    assert [(r["series_id"], r["value"]) for r in s.latest([USD_SGD, SGS_2Y])] == [
        (USD_SGD, 1.2789),
        (SGS_2Y, 1.95),
    ]
    then = s.latest([USD_SGD], as_of=date(2026, 10, 5))
    assert [(r["date"], r["value"]) for r in then] == [(date(2026, 10, 5), 1.2823)]
    assert s.latest([]) == []


def test_idr_per_sgd_inverts_mas_quote(store):
    """MAS quotes S$ per rupiah; the IDR investor wants rupiah per S$. Nulls are skipped."""
    rows = src(store).idr_per_sgd(start=date(2026, 10, 6))
    assert [r.series_id for r in rows] == [IDR_PER_SGD, IDR_PER_SGD]
    assert [r.date for r in rows] == [date(2026, 10, 6), MAS_AS_OF]
    assert rows[1].value == pytest.approx(1 / 7.155e-05)
    assert round(rows[1].value) == 13976
    assert rows[1].as_of == MAS_AS_OF and rows[1].source == SOURCE


def test_refresh_log_last_per_source(store):
    log = {r["source"]: r for r in src(store).refresh_log()}
    assert set(log) == {"mas", "singstat", "ura"}
    assert log["singstat"]["status"] == "skipped"  # the newest run, not the last ok
    assert log["singstat"]["last_ok"] == datetime(2026, 10, 7, 20, 28, 19)
    assert log["ura"]["last_ok"] is None


def test_missing_store(tmp_path):
    rows, stale = read_rows(src(tmp_path / "nope.duckdb"), [SORA])
    assert rows == [] and stale == ["singstat (missing)"]


def test_no_path_is_missing():
    with pytest.raises(SourceUnavailable) as e:
        SingstatSource(None).rows([SORA])
    assert e.value.reason == "missing"


def test_store_without_tables_is_missing(tmp_path):
    path = tmp_path / "empty.duckdb"
    duckdb.connect(str(path)).close()
    with pytest.raises(SourceUnavailable) as e:
        src(path).rows([SORA])
    assert e.value.reason == "missing"


def test_locked_store_after_retries(store):
    sleeps = []
    s = SingstatSource(store, retries=3, retry_delay=0.5, sleep=sleeps.append)
    with hold_duckdb_lock(store):
        rows, stale = read_rows(s, [SORA])
    assert rows == [] and stale == ["singstat (locked)"]
    assert sleeps == [0.5, 0.5]


def test_retry_succeeds_once_refresh_lets_go(store):
    lock = hold_duckdb_lock(store)
    lock.__enter__()

    def release(_):
        lock.__exit__(None, None, None)

    s = SingstatSource(store, retries=3, retry_delay=1, sleep=release)
    assert [r.value for r in s.rows([SGS_2Y])] == [1.96, 1.95]


def test_never_writes(store):
    before = store.stat().st_mtime_ns
    s = src(store)
    s.rows(), s.series(), s.latest(), s.idr_per_sgd(), s.refresh_log()
    assert store.stat().st_mtime_ns == before
    duckdb.connect(str(store)).close()  # no connection left open


def test_from_config_env_overrides(store, tmp_path):
    assert SingstatSource.from_config(env={"ASSIST_SINGSTAT_DB": str(store)}).path == store
    # singstat's own variable, used when the assist-specific one is unset
    env = {"ASSIST_SINGSTAT_DB": "", "SGECON_DB": str(store)}
    assert SingstatSource.from_config(env=env).path == store
    env = {"ASSIST_SIBLINGS_ROOT": str(tmp_path), "ASSIST_SINGSTAT_DB": "", "SGECON_DB": ""}
    assert SingstatSource.from_config(env=env).path == tmp_path / "singstat/data/sgecon.duckdb"
