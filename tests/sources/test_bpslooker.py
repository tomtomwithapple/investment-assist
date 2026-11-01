"""bps-looker adapter (P11): BPS CPI, GDP and trade from its Postgres, read READ-ONLY, plus the
satudatascape stub (a data.go.id catalogue with no ready macro series).

There is no live Postgres in tests: the fixture is a DuckDB file holding the same tables and
columns (tests/fixtures/bpslooker/schema.sql), opened read-only. Through DuckDB's postgres
extension the adapter runs the same SQL against the real store. Rows are shaped like the live
store on 2026-10-23."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES, make_sqlite

from assist.sources.base import Row, Source, SourceUnavailable, read_rows
from assist.sources.bpslooker import (
    CPI_MOM,
    CPI_YOY,
    DEFAULT,
    EXPORTS,
    GDP_QOQ,
    GDP_YOY,
    IMPORTS,
    SOURCE,
    TRADE_BALANCE,
    BpsLookerSource,
    trade_series,
)
from assist.sources.satudatascape import SatudatascapeSource

FIX = FIXTURES / "bpslooker"


def _build(path: Path, data: bool = True) -> Path:
    con = duckdb.connect(str(path))
    try:
        con.execute((FIX / "schema.sql").read_text())
        if data:
            con.execute((FIX / "data.sql").read_text())
    finally:
        con.close()
    return path


@pytest.fixture
def src(tmp_path) -> BpsLookerSource:
    return BpsLookerSource.from_duckdb(_build(tmp_path / "bps.duckdb"))


def _by(rows: list[Row], sid: str) -> list[tuple]:
    return [(r.date, r.value, r.as_of) for r in rows if r.series_id == sid]


def test_is_a_source(src):
    assert isinstance(src, Source)
    assert src.name == SOURCE == "bps-looker"


def test_cpi_monthly_national_only(src):
    rows = src.rows([CPI_YOY, CPI_MOM])
    assert all(r.source == SOURCE for r in rows)
    # annual (turth 13) and province (vervar 1100) rows are skipped; month → first of month
    assert _by(rows, CPI_YOY) == [
        (date(2025, 12, 1), 2.92, date(2026, 10, 1)),
        (date(2026, 8, 1), 3.19, date(2026, 10, 1)),
        (date(2026, 9, 1), 3.28, date(2026, 10, 1)),
    ]
    # no BPS last_update → the WIB date of fetched_at
    assert _by(rows, CPI_MOM) == [(date(2026, 9, 1), 0.21, date(2026, 10, 9))]


def test_gdp_quarterly(src):
    rows = src.rows([GDP_YOY, GDP_QOQ])
    # quarter → its first month; annual (turth 35) and other GDP lines are skipped
    assert _by(rows, GDP_YOY) == [
        (date(2025, 10, 1), 5.39, date(2026, 8, 5)),
        (date(2026, 1, 1), 5.61, date(2026, 8, 5)),
        (date(2026, 4, 1), 5.29, date(2026, 8, 5)),
    ]
    assert _by(rows, GDP_QOQ) == [(date(2026, 4, 1), 3.73, date(2026, 8, 5))]


def test_trade_headline(src):
    rows = src.rows([EXPORTS, IMPORTS, TRADE_BALANCE])
    assert _by(rows, EXPORTS) == [
        (date(2026, 7, 1), 26216.7, date(2026, 10, 1)),
        (date(2026, 8, 1), 26612.2, date(2026, 10, 1)),
    ]
    assert _by(rows, IMPORTS) == [(date(2026, 8, 1), 23060.0, date(2026, 10, 1))]
    assert _by(rows, TRADE_BALANCE) == [(date(2026, 8, 1), 3552.2, date(2026, 10, 1))]


def test_default_is_headline_series(src):
    rows = src.rows()
    assert {r.series_id for r in rows} == set(DEFAULT)
    assert set(DEFAULT) == {CPI_YOY, CPI_MOM, GDP_YOY, GDP_QOQ, EXPORTS, IMPORTS, TRADE_BALANCE}
    # sorted by series, then date
    assert rows == sorted(rows, key=lambda r: (r.series_id, r.date))


def test_window_inclusive(src):
    rows = src.rows([CPI_YOY], start=date(2026, 8, 1), end=date(2026, 8, 1))
    assert _by(rows, CPI_YOY) == [(date(2026, 8, 1), 3.19, date(2026, 10, 1))]


def test_trade_by_hs2(src):
    assert trade_series("export", "27") == "BPS_TRADE.export.27"
    coal_x, cpo_x, coal_m = trade_series("export", "27"), trade_series("export", "15"), \
        trade_series("import", "27")
    rows = src.rows([coal_x, cpo_x, coal_m])
    # monthly sum over ports and countries, USD mn; annual rows skipped; as_of = newest fetch (WIB)
    assert _by(rows, coal_x) == [
        (date(2026, 7, 1), 1800.0, date(2026, 9, 2)),
        (date(2026, 8, 1), 2000.0, date(2026, 10, 10)),
    ]
    assert _by(rows, cpo_x) == [(date(2026, 8, 1), 700.0, date(2026, 10, 10))]
    assert _by(rows, coal_m) == [(date(2026, 8, 1), 2100.0, date(2026, 10, 10))]


def test_unknown_series_ignored(src):
    assert src.rows(["NOPE", "BPS_TRADE.export.x7", "BPS_TRADE.both.27"]) == []


def test_empty_store_is_missing(tmp_path):
    src = BpsLookerSource.from_duckdb(_build(tmp_path / "empty.duckdb", data=False))
    assert src.rows() == []  # tables present, no rows yet
    con = duckdb.connect(str(tmp_path / "bare.duckdb"))
    con.close()
    with pytest.raises(SourceUnavailable) as e:
        BpsLookerSource.from_duckdb(tmp_path / "bare.duckdb").rows()
    assert e.value.reason == "missing"


def test_missing_fixture_file(tmp_path):
    rows, stale = read_rows(BpsLookerSource.from_duckdb(tmp_path / "absent.duckdb"))
    assert rows == [] and stale == ["bps-looker (missing)"]


def test_postgres_down_is_unavailable():
    # nothing listens on port 1; the DSN never leaves localhost
    src = BpsLookerSource("postgresql://bps:secret@127.0.0.1:1/bps")
    with pytest.raises(SourceUnavailable) as e:
        src.rows()
    assert e.value.reason in ("missing", "error")
    assert "secret" not in str(e.value)


def test_from_config_reads_dsn_env():
    src = BpsLookerSource.from_config(env={"ASSIST_BPS_LOOKER_DSN": "postgresql://u:p@localhost/x"})
    assert src.dsn == "postgresql://u:p@localhost/x"


# ---------------- satudatascape stub ----------------


@pytest.fixture
def satu(tmp_path) -> SatudatascapeSource:
    path = make_sqlite(tmp_path / "satudata.db", (FIX / "satudata.sql").read_text())
    return SatudatascapeSource(path)


def test_satudata_is_a_source(satu):
    assert isinstance(satu, Source)
    assert satu.name == "satudatascape"


def test_satudata_runs_as_freshness_rows(satu):
    rows = satu.rows()
    # finished runs only (run 4 is still going); value = count_stored, as_of = finish date (UTC)
    d20, d22 = date(2026, 10, 20), date(2026, 10, 22)
    assert rows == [
        Row("SATUDATA_RUNS.crawl", d20, 120.0, d20, "satudatascape"),
        Row("SATUDATA_RUNS.crawl", d22, 130.0, d22, "satudatascape"),
        Row("SATUDATA_RUNS.download", d22, 40.0, d22, "satudatascape"),
    ]
    assert satu.rows(["SATUDATA_RUNS.download"], start=date(2026, 10, 21))[0].value == 40.0
    assert satu.last_run() == date(2026, 10, 22)
    assert satu.last_run("download") == date(2026, 10, 22)
    assert satu.last_run("nope") is None


def test_satudata_extracted_tables(satu):
    t = satu.tables()
    assert [x.resource_id for x in t] == ["r-a", "r-b"]  # grade A and B by default
    assert t[0].quality == "A" and t[0].n_rows == 34 and t[0].path == "tables/r-a.parquet"
    assert [x.resource_id for x in satu.tables(grades=("C",))] == ["r-c"]


def test_satudata_missing_file(tmp_path):
    src = SatudatascapeSource(tmp_path / "satudata.db")
    with pytest.raises(SourceUnavailable) as e:
        src.rows()
    assert e.value.reason == "missing"
    assert read_rows(src) == ([], ["satudatascape (missing)"])
    assert not (tmp_path / "satudata.db").exists()  # read-only: never created


def test_satudata_from_config(tmp_path):
    db = tmp_path / "nowhere" / "satudata.db"
    src = SatudatascapeSource.from_config(env={"ASSIST_SATUDATASCAPE_DB": str(db)})
    assert src.path == db
