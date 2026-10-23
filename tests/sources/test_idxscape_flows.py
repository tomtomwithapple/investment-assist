"""IDX flows adapter (P13): idxscape's `stock_summary`, `broker_summary` and DJPPR `sbn_ownership`
read READ-ONLY as tidy rows, next to P3's JISDOR.

Semantics follow idxscape's own J8 macro overlay (`queries.macro_overlay`): market foreign flow is
the day's sum of the per-stock estimate `net_foreign_value_est_idr` (net shares x close), its USD
value uses that day's JISDOR only (a missing rate is a gap, never filled), and non-resident SBN
holdings are `(non_resident, TOTAL)`. The fixture store (tests/fixtures/idxscape_flows/) is built
from the migrations' DDL and a few rows shaped like the real 2026-10-19..21."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.base import Row, SourceUnavailable, read_rows
from assist.sources.idxscape import (
    BROKER_VALUE,
    IDX_NET_FOREIGN_IDR,
    IDX_NET_FOREIGN_USD,
    JISDOR,
    SBN_NON_RESIDENT,
    SBN_TOTAL,
    IdxscapeSource,
    sbn_series,
)

FIX = FIXTURES / "idxscape_flows"
D19, D20, D21, D22 = (date(2026, 10, d) for d in (19, 20, 21, 22))


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
    return _build(tmp_path / "idxscape.duckdb")


def _by(rows: list[Row], sid: str) -> list[Row]:
    return [r for r in rows if r.series_id == sid]


def test_series_ids():
    assert SBN_NON_RESIDENT == sbn_series("TOTAL", "non_resident") == "SBN.TOTAL.non_resident"
    assert SBN_TOTAL == "SBN.TOTAL.total"


def test_market_net_foreign_idr(store):
    rows = IdxscapeSource(store).rows([IDX_NET_FOREIGN_IDR])
    assert rows == [
        Row(IDX_NET_FOREIGN_IDR, D19, 3.2e9, D19, "idxscape"),
        Row(IDX_NET_FOREIGN_IDR, D20, -1.61e9, D20, "idxscape"),
        # trading_day.recorded_at 17:30 UTC is 00:30 WIB the next day
        Row(IDX_NET_FOREIGN_IDR, D21, 5e8, D22, "idxscape"),
    ]


def test_market_net_foreign_usd_same_day_jisdor_only(store):
    rows = IdxscapeSource(store).rows([IDX_NET_FOREIGN_USD])
    assert [(r.date, r.value) for r in rows] == [
        (D19, pytest.approx(200_000.0)),
        (D20, pytest.approx(-100_000.0)),
        (D21, None),  # no JISDOR on 10-21: a gap, not filled from 10-20
    ]
    assert [r.as_of for r in rows] == [D19, D20, D22]


def test_jisdor_gaps(store):
    assert IdxscapeSource(store).jisdor_gaps() == {D21}


def test_sbn_ownership_with_file_vintage_as_of(store):
    rows = IdxscapeSource(store).rows([SBN_NON_RESIDENT])
    assert rows == [
        Row(SBN_NON_RESIDENT, D19, 920.44e12, D20, "idxscape"),
        Row(SBN_NON_RESIDENT, D20, 918.07e12, D20, "idxscape"),
        # file bbb fetched 20:00 UTC = 03:00 WIB on 10-22
        Row(SBN_NON_RESIDENT, D21, 914.41e12, D22, "idxscape"),
    ]
    sun = IdxscapeSource(store).rows([sbn_series("SUN", "non_resident")])
    assert [(r.date, r.value) for r in sun] == [(D21, 850e12)]


def test_broker_value(store):
    src = IdxscapeSource(store)
    assert src.rows([BROKER_VALUE + "AD"]) == [
        Row("BROKER_VALUE_IDR.AD", D20, 1985742000.0, None, "idxscape"),
        Row("BROKER_VALUE_IDR.AD", D21, 1000000.0, None, "idxscape"),
    ]
    day = src.brokers(start=D20, end=D20)
    assert [(r.series_id, r.value) for r in day] == [
        ("BROKER_VALUE_IDR.AD", 1985742000.0),
        ("BROKER_VALUE_IDR.AF", 2577805900.0),
    ]


def test_default_rows_cover_jisdor_flows_and_sbn(store):
    rows = IdxscapeSource(store).rows()
    assert {r.series_id for r in rows} == {
        JISDOR, IDX_NET_FOREIGN_IDR, IDX_NET_FOREIGN_USD, SBN_NON_RESIDENT, SBN_TOTAL
    }
    keys = [(r.series_id, r.date) for r in rows]
    assert keys == sorted(keys)


def test_window_filter(store):
    rows = IdxscapeSource(store).rows(
        [IDX_NET_FOREIGN_USD, SBN_NON_RESIDENT, BROKER_VALUE + "AD"], start=D20, end=D20
    )
    assert {(r.series_id, r.date) for r in rows} == {
        (IDX_NET_FOREIGN_USD, D20), (SBN_NON_RESIDENT, D20), ("BROKER_VALUE_IDR.AD", D20)
    }


def test_unknown_series_are_dropped(store):
    src = IdxscapeSource(store)
    assert src.rows(["NOT_A_SERIES", "SBN.BOGUS.non_resident"]) == []
    assert src.rows([sbn_series("TOTAL", "no_such_type")]) == []


def test_store_is_never_written(store):
    before = store.read_bytes()
    IdxscapeSource(store).rows()
    IdxscapeSource(store).brokers()
    assert store.read_bytes() == before


def test_requested_series_on_missing_table_is_missing(tmp_path):
    ddl = (FIXTURES / "idxscape" / "schema.sql").read_text()  # fx_rate only
    path = _build(tmp_path / "old.duckdb", data=False, ddl=ddl)
    src = IdxscapeSource(path)
    assert src.rows() == []  # only JISDOR's table exists, and it is empty
    with pytest.raises(SourceUnavailable) as e:
        src.rows([SBN_NON_RESIDENT])
    assert e.value.reason == "missing" and "sbn_ownership" in e.value.detail
    with pytest.raises(SourceUnavailable) as e:
        src.rows([IDX_NET_FOREIGN_USD])
    assert "stock_summary" in e.value.detail


def test_locked_store(store):
    with hold_duckdb_lock(store):
        rows, stale = read_rows(IdxscapeSource(store), [IDX_NET_FOREIGN_IDR])
    assert rows == [] and stale == ["idxscape (locked)"]
