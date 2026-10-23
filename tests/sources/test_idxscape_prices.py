"""JISDOR adapter (P3): idxscape's `fx_rate` (migration 7) read READ-ONLY as tidy rows.

The fixture store is built from the migration's DDL (tests/fixtures/idxscape/schema.sql) and a
few rows shaped like the real table, incl. one BI carried-forward day (2021-11-26)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.base import Row, Source, SourceUnavailable, read_rows
from assist.sources.idxscape import JISDOR, SOURCE, IdxscapeSource

FIX = FIXTURES / "idxscape"


@pytest.fixture
def store(tmp_path) -> Path:
    path = tmp_path / "idxscape.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute((FIX / "schema.sql").read_text())
        con.execute(
            "insert into fx_rate select * from read_csv(?, header = true, columns = {"
            "'rate_date': 'DATE', 'pair': 'VARCHAR', 'rate': 'DECIMAL(18,2)', 'source': 'VARCHAR',"
            "'carried_forward': 'BOOLEAN', 'recorded_at': 'TIMESTAMPTZ'})",
            [str(FIX / "fx_rate.csv")],
        )
    finally:
        con.close()
    return path


def test_is_a_source(store):
    assert isinstance(IdxscapeSource(store), Source)
    assert IdxscapeSource(store).name == SOURCE == "idxscape"


def test_jisdor_rows_sorted_with_recorded_date_as_of(store):
    rows = IdxscapeSource(store).rows()
    assert [r.date for r in rows] == sorted(r.date for r in rows)
    assert len(rows) == 6
    assert rows[-1] == Row(JISDOR, date(2026, 10, 16), 18052.0, date(2026, 10, 16), "idxscape")
    # recorded_at is TIMESTAMPTZ in WIB: its date is the WIB day, whatever the local zone
    assert rows[0].as_of == date(2026, 10, 3)  # 2026-10-02 23:30 UTC
    assert all(isinstance(r.value, float) for r in rows)


def test_window_and_series_filter(store):
    src = IdxscapeSource(store)
    rows = src.rows([JISDOR], start=date(2026, 10, 15), end=date(2026, 10, 16))
    assert [r.date for r in rows] == [date(2026, 10, 15), date(2026, 10, 16)]
    assert src.rows(["NOT_A_SERIES"]) == []
    assert src.rows([]) == []


def test_carried_forward_days(store):
    assert IdxscapeSource(store).carried_forward() == {date(2021, 11, 26)}


def test_store_is_never_written(store):
    before = store.read_bytes()
    IdxscapeSource(store).rows()
    assert store.read_bytes() == before


def test_missing_store(tmp_path):
    rows, stale = read_rows(IdxscapeSource(tmp_path / "nope.duckdb"))
    assert rows == [] and stale == ["idxscape (missing)"]


def test_missing_table_is_missing(tmp_path):
    path = tmp_path / "old.duckdb"
    duckdb.connect(str(path)).close()
    with pytest.raises(SourceUnavailable) as e:
        IdxscapeSource(path).rows()
    assert e.value.reason == "missing" and "fx_rate" in e.value.detail


def test_locked_store(store):
    with hold_duckdb_lock(store):
        rows, stale = read_rows(IdxscapeSource(store))
    assert rows == [] and stale == ["idxscape (locked)"]


def test_from_config_honours_env(store):
    src = IdxscapeSource.from_config(env={"ASSIST_IDXSCAPE_DB": str(store)})
    assert src.path == store
    assert src.rows()[-1].value == 18052.0
