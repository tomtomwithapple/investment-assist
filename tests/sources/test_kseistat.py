"""kseistat adapter (P14): KSEI monthly local/foreign ownership from `v_market_composition` and
`v_type_composition`, read READ-ONLY as tidy rows.

The fixture store (tests/fixtures/kseistat/) is kseistat's own SCHEMA + VIEWS DDL with two tiny
months; every percentage is of KSEI-recorded holdings (not sec_num), as in kseistat's README."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.base import Row, SourceUnavailable, read_rows
from assist.sources.kseistat import (
    FOREIGN_PCT_EQUAL,
    FOREIGN_PCT_SUM,
    KseistatSource,
    market_series,
    type_series,
)

FIX = FIXTURES / "kseistat"
AUG, SEP = date(2026, 8, 31), date(2026, 9, 30)
LOADED_AUG, LOADED_SEP = date(2026, 9, 5), date(2026, 10, 7)


def _build(path: Path, data: bool = True, ddl: str | None = None) -> Path:
    con = duckdb.connect(str(path))
    try:
        con.execute(ddl or (FIX / "schema.sql").read_text())
        if data:
            con.execute((FIX / "data.sql").read_text())
    finally:
        con.close()
    return path


@pytest.fixture
def store(tmp_path) -> Path:
    return _build(tmp_path / "ksei.duckdb")


def test_series_ids():
    assert FOREIGN_PCT_SUM == market_series("sum", "foreign_pct") == "KSEI.sum.foreign_pct"
    assert FOREIGN_PCT_EQUAL == "KSEI.equal_weight.foreign_pct"
    assert type_series("foreign", "CP", "pct_sum") == "KSEI_TYPE.foreign.CP.pct_sum"
    with pytest.raises(ValueError):
        market_series("cap_weight", "foreign_pct")
    with pytest.raises(ValueError):
        type_series("foreign", "CP", "pct")


def test_market_foreign_share_sum_and_equal_weight(store):
    rows = KseistatSource(store).rows([FOREIGN_PCT_SUM, FOREIGN_PCT_EQUAL])
    assert rows == [
        # equal weight: AAAA 20%, BBBB 50% → 35; in 09 BBBB holds 0 so only AAAA counts
        Row(FOREIGN_PCT_EQUAL, AUG, 35.0, LOADED_AUG, "kseistat"),
        Row(FOREIGN_PCT_EQUAL, SEP, 30.0, LOADED_SEP, "kseistat"),
        # sum: (20 + 150) / 400
        Row(FOREIGN_PCT_SUM, AUG, 42.5, LOADED_AUG, "kseistat"),
        Row(FOREIGN_PCT_SUM, SEP, 30.0, LOADED_SEP, "kseistat"),
    ]


def test_market_counts_and_groups(store):
    src = KseistatSource(store)
    n = src.rows([market_series("sum", "n_stocks")])
    assert [(r.date, r.value) for r in n] == [(AUG, 2.0), (SEP, 1.0)]
    total = src.rows([market_series("sum", "total_holdings")])
    assert [(r.date, r.value) for r in total] == [(AUG, 400.0), (SEP, 100.0)]
    fi = src.rows([market_series("sum", "foreign_individual_pct")], end=AUG)
    assert [(r.date, r.value) for r in fi] == [(AUG, pytest.approx(7.5))]


def test_type_composition(store):
    src = KseistatSource(store)
    measures = ("shares", "pct_sum", "pct_equal_weight")
    rows = src.rows([type_series("foreign", "CP", m) for m in measures], end=AUG)
    assert {r.series_id: r.value for r in rows} == {
        "KSEI_TYPE.foreign.CP.shares": 140.0,
        "KSEI_TYPE.foreign.CP.pct_sum": pytest.approx(35.0),
        "KSEI_TYPE.foreign.CP.pct_equal_weight": pytest.approx(30.0),  # avg(20%, 40%)
    }
    assert {r.as_of for r in rows} == {LOADED_AUG}


def test_types_returns_every_origin_and_type(store):
    rows = KseistatSource(store).types(start=SEP)
    assert len(rows) == 2 * 2 * 3  # origins × investor types × measures
    pct = [r for r in rows if r.series_id.endswith(".pct_sum")]
    assert sum(r.value for r in pct) == pytest.approx(100.0)
    keys = [(r.series_id, r.date) for r in rows]
    assert keys == sorted(keys)


def test_default_rows_are_market_series_only(store):
    rows = KseistatSource(store).rows()
    ids = {r.series_id for r in rows}
    assert FOREIGN_PCT_SUM in ids and FOREIGN_PCT_EQUAL in ids
    assert len(ids) == 2 * 10  # two methods × (n_stocks, total_holdings, eight *_pct)
    assert not any(s.startswith("KSEI_TYPE.") for s in ids)
    keys = [(r.series_id, r.date) for r in rows]
    assert keys == sorted(keys)


def test_window_filter(store):
    rows = KseistatSource(store).rows([FOREIGN_PCT_SUM, type_series("local", "ID", "pct_sum")],
                                      start=SEP, end=SEP)
    assert {(r.series_id, r.date) for r in rows} == {
        (FOREIGN_PCT_SUM, SEP), ("KSEI_TYPE.local.ID.pct_sum", SEP)
    }


def test_unknown_series_are_dropped(store):
    src = KseistatSource(store)
    assert src.rows(["NOT_A_SERIES", "KSEI.sum.bogus_pct", "KSEI_TYPE.alien.ID.pct_sum"]) == []
    assert src.rows([type_series("foreign", "ZZ", "pct_sum")]) == []


def test_as_of_none_without_loads_row(tmp_path):
    path = _build(tmp_path / "k.duckdb")
    con = duckdb.connect(str(path))
    con.execute("delete from loads")
    con.close()
    rows = KseistatSource(path).rows([FOREIGN_PCT_SUM])
    assert [r.as_of for r in rows] == [None, None]


def test_store_is_never_written(store):
    before = store.read_bytes()
    KseistatSource(store).rows()
    KseistatSource(store).types()
    assert store.read_bytes() == before


def test_missing_views_is_missing(tmp_path):
    ddl = (FIX / "schema.sql").read_text().split("CREATE OR REPLACE VIEW")[0]  # tables only
    src = KseistatSource(_build(tmp_path / "old.duckdb", data=False, ddl=ddl))
    with pytest.raises(SourceUnavailable) as e:
        src.rows()
    assert e.value.reason == "missing" and "v_market_composition" in e.value.detail
    with pytest.raises(SourceUnavailable) as e:
        src.types()
    assert "v_type_composition" in e.value.detail


def test_missing_file(tmp_path):
    rows, stale = read_rows(KseistatSource(tmp_path / "nope.duckdb"))
    assert rows == [] and stale == ["kseistat (missing)"]


def test_locked_store(store):
    with hold_duckdb_lock(store):
        rows, stale = read_rows(KseistatSource(store), [FOREIGN_PCT_SUM])
    assert rows == [] and stale == ["kseistat (locked)"]
