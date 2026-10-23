"""idxscape PHEI adapter (P32): `igsyc_point`, `phei_bond_quote` and `credit_curve_point`
(idxscape J4, migration 9) read READ-ONLY.

The IGSYC curve is read by tenor, never through a bond: benchmark membership rotates, so no
series is "the 10Y benchmark". Values are percent as printed (7.1677 means 7.1677%). Defaults
stop at 30Y (beyond is extrapolated), as idxscape's J8 overlay does. `from_yesterday_column`
stays a flag. The fixture store (tests/fixtures/idxscape_phei/) is migration 9's DDL with rows
shaped like the captured pages of 2026-10-08..12."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.base import Row, SourceUnavailable, read_rows
from assist.sources.idxscape_phei import (
    IGSYC_2Y,
    IGSYC_10Y,
    SOURCE,
    BondQuote,
    CreditPoint,
    CurvePoint,
    CurveSlope,
    PheiSource,
    bond_series,
    credit_series,
    igsyc_series,
)

FIX = FIXTURES / "idxscape_phei"
D08, D09, D12, D13 = (date(2026, 10, d) for d in (8, 9, 12, 13))


def _build(path: Path, data: bool = True, ddl: str | None = None) -> Path:
    con = duckdb.connect(str(path))
    try:
        con.execute(ddl if ddl is not None else (FIX / "schema.sql").read_text())
        if data:
            con.execute((FIX / "data.sql").read_text())
    finally:
        con.close()
    return path


@pytest.fixture
def store(tmp_path) -> Path:
    return _build(tmp_path / "idxscape.duckdb")


def test_series_ids():
    assert igsyc_series(10) == IGSYC_10Y == "IGSYC.10"
    assert igsyc_series(2) == IGSYC_2Y == "IGSYC.2"
    assert igsyc_series(0.1) == "IGSYC.0.1"
    assert credit_series("AAA", 5) == "PHEI_CREDIT.AAA.5"
    assert bond_series("SBN_BENCHMARK", "FR0108") == "PHEI_BOND.SBN_BENCHMARK.FR0108"
    assert SOURCE == "idxscape_phei"


def test_curve_tenor_rows_percent_as_printed_with_wib_vintage(store):
    rows = PheiSource(store).rows([IGSYC_10Y])
    assert rows == [
        Row(IGSYC_10Y, D08, 7.15, D08, SOURCE),
        Row(IGSYC_10Y, D09, 7.1, D13, SOURCE),  # gap-filled from 10-12's page
        # fetched 17:30 UTC = 00:30 WIB on 10-13
        Row(IGSYC_10Y, D12, 7.1677, D13, SOURCE),
    ]


def test_default_rows_are_the_curve_up_to_30y(store):
    rows = PheiSource(store).rows()
    ids = {r.series_id for r in rows}
    assert ids == {"IGSYC.0.1", "IGSYC.1", "IGSYC.2", "IGSYC.10", "IGSYC.30"}
    assert len(rows) == 12


def test_beyond_30y_only_when_asked_by_id(store):
    rows = PheiSource(store).rows([igsyc_series(40)])
    assert [(r.date, r.value) for r in rows] == [(D08, 7.55), (D12, 7.58)]


def test_window_inclusive(store):
    rows = PheiSource(store).rows([IGSYC_2Y], start=D09, end=D12)
    assert [r.date for r in rows] == [D09, D12]


def test_unknown_ids_ignored(store):
    assert PheiSource(store).rows(["NOPE", "IGSYC.", "PHEI_BOND.SBN_BENCHMARK"]) == []


def test_bond_and_credit_rows_by_id(store):
    src = PheiSource(store)
    fr = bond_series("SBN_BENCHMARK", "FR0108")
    assert [(r.date, r.value, r.as_of) for r in src.rows([fr])] == [
        (D08, 7.15, D08), (D09, 7.1, D13), (D12, 7.1677, D13)]
    aaa = credit_series("AAA", 5)
    assert [(r.date, r.value) for r in src.rows([aaa], start=D12)] == [(D12, 7.656)]


def test_curve_latest_day_up_to_30y_with_flag(store):
    src = PheiSource(store)
    assert src.curve() == [
        CurvePoint(D12, 0.1, 4.95, False),
        CurvePoint(D12, 1.0, 5.25, False),
        CurvePoint(D12, 2.0, 5.625, False),
        CurvePoint(D12, 10.0, 7.1677, False),
        CurvePoint(D12, 30.0, 7.42, False),
    ]
    assert [p.tenor_y for p in src.curve(D08, max_tenor=None)][-1] == 40.0
    assert src.curve(D09) == [CurvePoint(D09, 2.0, 5.6, True), CurvePoint(D09, 10.0, 7.1, True)]
    assert src.curve(date(2026, 10, 10)) == []


def test_curve_on_or_before(store):
    # a day with no curve (weekend) falls back to the latest day on or before it
    points = PheiSource(store).curve(date(2026, 10, 11), on_or_before=True)
    assert {p.as_of for p in points} == {D09}


def test_curve_days_newest_first_and_yesterday_column_days(store):
    src = PheiSource(store)
    assert src.curve_days() == [(D12, False), (D09, True), (D08, False)]
    assert src.yesterday_column_days() == {D09}


def test_slopes_10y_minus_2y(store):
    slopes = PheiSource(store).slopes()
    assert [(s.as_of, s.from_yesterday_column) for s in slopes] == [
        (D08, False), (D09, True), (D12, False)]
    assert slopes[0] == CurveSlope(D08, 5.55, 7.15, pytest.approx(1.6), False)
    assert slopes[-1].slope_pct == pytest.approx(1.5427)
    assert [s.as_of for s in PheiSource(store).slopes(start=D09, end=D09)] == [D09]


def test_bond_quotes_keep_group_and_flag(store):
    src = PheiSource(store)
    latest = src.bond_quotes()
    assert {q.series_code for q in latest} == {"FR0108", "PBS003", "ORI024T3"}
    assert src.bond_quotes(grp="RETAIL") == [
        BondQuote(D12, "ORI024T3", "RETAIL", 1.9, 5.6, 101.0, 6.1, False)]
    [filled] = src.bond_quotes(D09)
    assert filled == BondQuote(D09, "FR0108", "SBN_BENCHMARK", None, 7.1, 98.4, 6.5, True)
    with pytest.raises(ValueError):
        src.bond_quotes(grp="BENCHMARK_10Y")


def test_credit_curve(store):
    assert PheiSource(store).credit_curve() == [
        CreditPoint(D12, 5.0, "AAA", 7.656),
        CreditPoint(D12, 5.0, "BBB", 10.2),
        CreditPoint(D12, 5.0, "IGS", 6.45),
    ]


def test_empty_tables_give_empty_results(tmp_path):
    src = PheiSource(_build(tmp_path / "e.duckdb", data=False))
    assert src.rows() == [] and src.curve() == [] and src.slopes() == []
    assert src.bond_quotes() == [] and src.credit_curve() == []


def test_without_migration_9_is_missing(tmp_path):
    # this Mac's idxscape.duckdb is at migration 8: other tables, no PHEI ones
    src = PheiSource(_build(tmp_path / "m8.duckdb", data=False, ddl="create table fx_rate (x int)"))
    rows, stale = read_rows(src)
    assert rows == [] and stale == ["idxscape_phei (missing)"]
    for call in (src.curve, src.slopes, src.bond_quotes, src.credit_curve, src.curve_days):
        with pytest.raises(SourceUnavailable) as e:
            call()
        assert e.value.reason == "missing"


def test_missing_table_for_one_kind(tmp_path):
    ddl = (FIX / "schema.sql").read_text().split("CREATE TABLE phei_bond_quote")[0]
    src = PheiSource(_build(tmp_path / "c.duckdb", data=False, ddl=ddl))
    assert src.rows([IGSYC_10Y]) == []
    with pytest.raises(SourceUnavailable, match="phei_bond_quote"):
        src.rows([bond_series("RETAIL", "ORI024T3")])


def test_missing_file(tmp_path):
    rows, stale = read_rows(PheiSource(tmp_path / "nope.duckdb"))
    assert rows == [] and stale == ["idxscape_phei (missing)"]


def test_locked(store):
    with hold_duckdb_lock(store):
        rows, stale = read_rows(PheiSource(store), [IGSYC_10Y])
    assert rows == [] and stale == ["idxscape_phei (locked)"]


def test_read_only(store):
    with PheiSource(store)._connect() as (con, _), pytest.raises(duckdb.Error):
        con.execute("delete from igsyc_point")


def test_from_config_uses_idxscape_store(tmp_path):
    src = PheiSource.from_config(env={"ASSIST_IDXSCAPE_DB": str(tmp_path / "x.duckdb")})
    assert src.path == tmp_path / "x.duckdb"
