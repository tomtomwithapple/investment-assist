"""bisfetcher adapter (P12): read-only DuckDB over `warehouse.duckdb`.

The fixture (tests/fixtures/bisfetcher) is bisfetcher's own DDL (its store.py SCHEMA, the contract
block in its PLAN.md) seeded with a few real values: the BI rate monthly and daily, the Fed rate,
the IDR broad REER, and the IDN credit gap, DSR and real house prices."""

from __future__ import annotations

from datetime import date, datetime

import duckdb
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.base import Row, Source, SourceUnavailable, read_rows
from assist.sources.bisfetcher import (
    BI_RATE_D,
    BI_RATE_M,
    DATASETS,
    FED_RATE_M,
    IDN_CREDIT_GAP,
    IDN_DSR,
    IDN_SPP_REAL_YOY,
    IDR_REER_M,
    SOURCE,
    BisfetcherSource,
)

FIX = FIXTURES / "bisfetcher"
UPDATED = date(2026, 10, 14)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute((FIX / "schema.sql").read_text())
        con.execute((FIX / "seed.sql").read_text())
    finally:
        con.close()
    return path


def test_is_a_source(store):
    assert isinstance(BisfetcherSource(store), Source)
    assert BisfetcherSource(store).name == SOURCE == "bisfetcher"


def test_ids_match_bisfetcher_readme():
    assert BI_RATE_M == "WS_CBPOL.M.ID" and BI_RATE_D == "WS_CBPOL.D.ID"
    assert FED_RATE_M == "WS_CBPOL.M.US" and IDR_REER_M == "WS_EER.M.R.B.ID"
    assert IDN_CREDIT_GAP == "WS_CREDIT_GAP.Q.ID.P.A.C" and IDN_DSR == "WS_DSR.Q.ID.P"
    assert IDN_SPP_REAL_YOY == "WS_SPP.Q.ID.R.771"
    assert DATASETS == ("WS_CBPOL", "WS_EER", "WS_CREDIT_GAP", "WS_SPP", "WS_DSR")


def test_bi_rate_rows(store):
    rows = BisfetcherSource(store).rows([BI_RATE_M])
    assert rows == [
        Row(BI_RATE_M, date(2026, 7, 1), 5.75, UPDATED, SOURCE),
        Row(BI_RATE_M, date(2026, 8, 1), 5.75, UPDATED, SOURCE),
        Row(BI_RATE_M, date(2026, 9, 1), 5.75, date(2026, 10, 21), SOURCE),
    ]


def test_rows_sorted_by_series_and_date_and_window(store):
    src = BisfetcherSource(store)
    rows = src.rows([IDR_REER_M, BI_RATE_D, IDN_DSR], start=date(2026, 1, 1), end=date(2026, 10, 2))
    assert [(r.series_id, r.date, r.value) for r in rows] == [
        (BI_RATE_D, date(2026, 10, 2), 5.75),
        (IDN_DSR, date(2026, 1, 1), 4.2),
        (IDR_REER_M, date(2026, 7, 1), 88.10),
        (IDR_REER_M, date(2026, 8, 1), 87.77),
    ]


def test_point_in_time_filters_on_period_end(store):
    """A quarter is not known before its quarter-end: 2026-Q1 (date 2026-01-01) has period_end
    2026-03-31, so as of 2026-03-30 only 2025-Q4 is visible."""
    src = BisfetcherSource(store)
    rows = src.rows([IDN_CREDIT_GAP], as_of=date(2026, 3, 30))
    assert [(r.date, r.value) for r in rows] == [(date(2025, 10, 1), -1.10)]
    rows = src.rows([IDN_CREDIT_GAP], as_of=date(2026, 3, 31))
    assert [r.value for r in rows] == [-1.10, -1.3337]


def test_null_value_kept_as_none(store):
    assert BisfetcherSource(store).rows(["WS_DSR.Q.XX.P"])[0].value is None


def test_unknown_and_empty_ids(store):
    src = BisfetcherSource(store)
    assert src.rows(["WS_CBPOL.M.ZZ"]) == []
    assert src.rows([]) == []


def test_all_rows_by_default(store):
    rows = BisfetcherSource(store).rows()
    assert len(rows) == 15
    assert {r.source for r in rows} == {SOURCE}


def test_series_catalog(store):
    src = BisfetcherSource(store)
    cat = {s["series_id"]: s for s in src.series()}
    assert len(cat) == 8
    bi = cat[BI_RATE_M]
    assert bi["dataset"] == "WS_CBPOL" and bi["freq"] == "M" and bi["ref_area"] == "ID"
    assert bi["unit"] == "Per cent per year" and bi["unit_mult"] == 0
    assert bi["dims"]["REF_AREA"] == {"code": "ID", "label": "Indonesia"}
    assert bi["attrs"]["SOURCE_REF"] == "Bank Indonesia"
    assert bi["first_date"] == date(2026, 7, 1) and bi["last_date"] == date(2026, 9, 1)
    assert bi["discontinued_at"] is None
    assert cat["WS_DSR.Q.XX.P"]["discontinued_at"] == datetime(2026, 10, 21, 0, 31, 25)


def test_series_filters(store):
    src = BisfetcherSource(store)
    ids = [s["series_id"] for s in src.series(dataset="WS_CBPOL", ref_area="ID")]
    assert ids == [BI_RATE_D, BI_RATE_M]
    assert [s["series_id"] for s in src.series(ref_area="US")] == [FED_RATE_M]


def test_latest(store):
    latest = {r["series_id"]: r for r in BisfetcherSource(store).latest()}
    assert len(latest) == 8
    assert latest[BI_RATE_D]["date"] == date(2026, 10, 5)
    assert latest[IDR_REER_M]["value"] == 87.77
    assert latest[IDN_SPP_REAL_YOY]["period"] == "2026-Q2"
    assert latest[IDN_SPP_REAL_YOY]["period_end"] == date(2026, 6, 30)
    assert latest[IDN_DSR]["unit"] == "Per cent"


def test_latest_by_id_and_point_in_time(store):
    src = BisfetcherSource(store)
    now = src.latest([BI_RATE_M, IDN_DSR])
    assert [(r["series_id"], r["date"]) for r in now] == [
        (BI_RATE_M, date(2026, 9, 1)),
        (IDN_DSR, date(2026, 1, 1)),
    ]
    then = src.latest([BI_RATE_M, IDN_DSR], as_of=date(2026, 9, 15))
    assert [(r["series_id"], r["date"], r["value"]) for r in then] == [
        (BI_RATE_M, date(2026, 8, 1), 5.75),
        (IDN_DSR, date(2026, 1, 1), 4.2),
    ]
    assert src.latest([]) == []


def test_datasets(store):
    out = BisfetcherSource(store).datasets()
    assert [d["dataset"] for d in out] == sorted(DATASETS)
    cbpol = next(d for d in out if d["dataset"] == "WS_CBPOL")
    assert cbpol["version"] == "1.0" and cbpol["series"] == 3
    assert cbpol["structure_pulled_at"] == datetime(2026, 10, 21, 0, 30, 1)


def test_missing_store(tmp_path):
    rows, stale = read_rows(BisfetcherSource(tmp_path / "nope.duckdb"), [BI_RATE_M])
    assert rows == [] and stale == ["bisfetcher (missing)"]


def test_store_without_tables_is_missing(tmp_path):
    path = tmp_path / "empty.duckdb"
    duckdb.connect(str(path)).close()
    with pytest.raises(SourceUnavailable) as e:
        BisfetcherSource(path).rows([BI_RATE_M])
    assert e.value.reason == "missing"


def test_locked_store(store):
    with hold_duckdb_lock(store):
        rows, stale = read_rows(BisfetcherSource(store), [BI_RATE_M])
    assert rows == [] and stale == ["bisfetcher (locked)"]


def test_never_writes(store):
    before = store.stat().st_mtime_ns
    src = BisfetcherSource(store)
    src.rows(), src.series(), src.latest(), src.datasets()
    assert store.stat().st_mtime_ns == before
    duckdb.connect(str(store)).close()  # no connection left open


def test_from_config_env_overrides(store, tmp_path):
    assert BisfetcherSource.from_config(env={"ASSIST_BISFETCHER_DB": str(store)}).path == store
    # bisfetcher's own variable, used when the assist-specific one is unset
    env = {"ASSIST_BISFETCHER_DB": "", "BISFETCHER_DB": str(store)}
    assert BisfetcherSource.from_config(env=env).path == store
    env = {"ASSIST_SIBLINGS_ROOT": str(tmp_path), "ASSIST_BISFETCHER_DB": "", "BISFETCHER_DB": ""}
    assert BisfetcherSource.from_config(env=env).path == tmp_path / "bisfetcher/warehouse.duckdb"
