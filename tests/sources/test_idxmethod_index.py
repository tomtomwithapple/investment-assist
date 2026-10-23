"""idx-method index CSVs (P3): `data/*_daily.csv`, `data/*_weekly.csv` as tidy rows.

The CSVs are frozen at 2026-09-30 (idx-method README, *Changes the parent must follow*,
2026-10-19), so `as_of` carries each file's real last date and staleness shows downstream.
tests/fixtures/idxmethod/index/ stands in for the idx-method repo root."""

from __future__ import annotations

import shutil
from datetime import date

import pytest
from helpers import FIXTURES

from assist.sources.base import Row, Source, SourceUnavailable, read_rows
from assist.sources.idxmethod import JCI, SERIES, SOURCE, IdxMethodIndexSource, jci

FIX = FIXTURES / "idxmethod" / "index"


@pytest.fixture
def src() -> IdxMethodIndexSource:
    return IdxMethodIndexSource(FIX)


def test_is_a_source(src):
    assert isinstance(src, Source)
    assert src.name == SOURCE == "idx-method"


def test_series_table_covers_the_real_files():
    files = {f for f, _ in SERIES.values()}
    assert "data/jkse_daily.csv" in files and SERIES[JCI] == ("data/jkse_daily.csv", "close")
    assert SERIES["LQ45_TR"] == ("data/lq45_tr_daily.csv", "total_return")


def test_jci_close_with_last_file_date_as_of(src):
    rows = src.rows([JCI])
    assert rows == [
        Row(JCI, date(2026, 9, 28), 6118.8062, date(2026, 9, 30), "idx-method"),
        Row(JCI, date(2026, 9, 29), 6121.7002, date(2026, 9, 30), "idx-method"),
        Row(JCI, date(2026, 9, 30), 6071.1382, date(2026, 9, 30), "idx-method"),
    ]


def test_weekly_and_total_return_columns(src):
    rows = src.rows(["INVESTOR33", "INVESTOR33_TR", "IDX30"], start=date(2026, 9, 25))
    got = {(r.series_id, r.date): (r.value, r.as_of) for r in rows}
    assert got == {
        ("IDX30", date(2026, 9, 25)): (344.14, date(2026, 9, 25)),
        ("INVESTOR33", date(2026, 9, 25)): (333.73, date(2026, 9, 25)),
        ("INVESTOR33_TR", date(2026, 9, 25)): (466.4177, date(2026, 9, 25)),
    }


def test_blank_value_is_none(src):
    first = src.rows(["INVESTOR33_TR"], end=date(2014, 3, 21))
    assert first == [Row("INVESTOR33_TR", date(2014, 3, 21), None, date(2026, 9, 25), SOURCE)]


def test_all_present_series_by_default_and_window(src):
    rows = src.rows(end=date(2026, 9, 29), start=date(2026, 9, 29))
    assert {r.series_id for r in rows} == {JCI, "LQ45", "LQ45_TR"}
    assert all(r.date == date(2026, 9, 29) for r in rows)
    assert rows == sorted(rows, key=lambda r: (r.series_id, r.date))


def test_jci_is_the_one_entry_point(src):
    assert jci(source=src) == src.rows([JCI])
    assert jci(start=date(2026, 9, 30), source=src)[0].value == 6071.1382


def test_unknown_series_raises(src):
    with pytest.raises(KeyError):
        src.rows(["NOPE"])


def test_missing_dir_or_file(tmp_path):
    rows, stale = read_rows(IdxMethodIndexSource(tmp_path / "nope"))
    assert rows == [] and stale == ["idx-method (missing)"]
    shutil.copytree(FIX, tmp_path / "repo")
    (tmp_path / "repo" / "data" / "jkse_daily.csv").unlink()
    with pytest.raises(SourceUnavailable) as e:
        IdxMethodIndexSource(tmp_path / "repo").rows([JCI])
    assert e.value.reason == "missing" and "jkse_daily.csv" in e.value.detail
    # without a filter, absent files are skipped, not fatal
    assert {r.series_id for r in IdxMethodIndexSource(tmp_path / "repo").rows()} >= {"LQ45"}


def test_from_config_honours_env():
    src = IdxMethodIndexSource.from_config(env={"ASSIST_IDX_METHOD_DIR": str(FIX)})
    assert src.root == FIX
    assert jci(source=src)[-1].date == date(2026, 9, 30)
