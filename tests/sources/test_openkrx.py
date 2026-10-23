"""openkrx adapter (P26): KR/TW index-level series, DuckDB read-only over `data/parquet`.

The fixture store (tests/fixtures/openkrx/parquet, rebuilt by `build.py` there) follows openkrx's
P6 layout: `{dataset}/market={KR|TW}/date=*/part-*.parquet`, vintaged rows with `observed_at`.
tw_index carries a restated TAIEX day, a blank change and a writer temp file; tw_adjusted_daily
is not vintaged (no `as_of`); krx_index_daily is the KRX spec §4 shape (K3 not built yet)."""

from __future__ import annotations

import shutil
from datetime import date

import pytest
from helpers import FIXTURES

from assist.sources.base import Row, SourceUnavailable, read_rows
from assist.sources.openkrx import (
    KOSPI,
    KOSPI200,
    TAIEX,
    TW50,
    OpenkrxSource,
    kr_index,
    tw_adjusted,
    tw_index,
)

FIX = FIXTURES / "openkrx" / "parquet"
D20, D21, D22 = date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)


@pytest.fixture
def src() -> OpenkrxSource:
    return OpenkrxSource(FIX)


def test_series_ids():
    assert TAIEX == tw_index("發行量加權股價指數") == "TW_INDEX.發行量加權股價指數.close"
    assert TW50 == "TW_INDEX.臺灣50指數.close"
    assert KOSPI == kr_index("KOSPI", "코스피") == "KR_INDEX.KOSPI.코스피.close"
    assert KOSPI200 == "KR_INDEX.KOSPI.코스피 200.close"
    assert tw_adjusted("0050", "tr_index") == "TW_ADJ.0050.tr_index"
    with pytest.raises(ValueError):
        tw_index("發行量加權股價指數", "open")
    with pytest.raises(ValueError):
        kr_index("", "코스피")
    with pytest.raises(ValueError):
        tw_adjusted("0050", "close")


def test_tw_index_latest_vintage_and_as_of(src):
    assert src.rows([TAIEX]) == [
        # 2026-10-20 restated: vintage 2 wins, as_of = its observed_at (UTC date)
        Row(TAIEX, D20, 46292.93, D21, "openkrx"),
        Row(TAIEX, D21, 46887.77, D21, "openkrx"),
    ]


def test_tw_index_measures_and_null(src):
    rows = src.rows([tw_index("臺灣50指數", "change"), tw_index("臺灣50指數", "change_pct")])
    assert [(r.series_id.rsplit(".", 1)[1], r.date, r.value) for r in rows] == [
        ("change", D20, -50.0),
        ("change", D21, None),
        ("change_pct", D20, -0.12),
        ("change_pct", D21, 1.08),
    ]


def test_kr_index(src):
    rows = src.rows([KOSPI, kr_index("KOSPI", "코스피 200", "volume")], start=D22)
    assert rows == [  # sorted by id: "코스피 200." < "코스피." (space before dot)
        Row("KR_INDEX.KOSPI.코스피 200.volume", D22, 95000000.0, D22, "openkrx"),
        Row(KOSPI, D22, 3650.0, D22, "openkrx"),
    ]


def test_tw_adjusted_not_vintaged_has_no_as_of(src):
    rows = src.rows([tw_adjusted("0050", "tr_index"), tw_adjusted("0050", "total_return")])
    assert rows == [
        Row("TW_ADJ.0050.total_return", D20, None, None, "openkrx"),
        Row("TW_ADJ.0050.total_return", D21, pytest.approx(0.005050505050505051), None, "openkrx"),
        Row("TW_ADJ.0050.tr_index", D20, 1.0, None, "openkrx"),
        Row("TW_ADJ.0050.tr_index", D21, pytest.approx(1.005050505050505051), None, "openkrx"),
    ]


def test_default_is_every_index_close_sorted(src):
    rows = src.rows(end=D21)
    assert {r.series_id for r in rows} == {TAIEX, TW50, KOSPI, KOSPI200}
    assert rows == sorted(rows, key=lambda r: (r.series_id, r.date))
    assert all(r.date <= D21 for r in rows)


def test_window_and_unknown_names(src):
    assert src.rows([TAIEX], start=D21, end=D21) == [Row(TAIEX, D21, 46887.77, D21, "openkrx")]
    assert src.rows([tw_index("不存在指數")]) == []
    assert src.rows([]) == []
    with pytest.raises(KeyError):
        src.rows(["NOPE.x"])


def test_indices_lists_every_close_series(src):
    assert src.indices() == sorted([KOSPI, KOSPI200, TAIEX, TW50])


def test_missing_root_and_missing_dataset(tmp_path):
    rows, stale = read_rows(OpenkrxSource(tmp_path / "nope"))
    assert (rows, stale) == ([], ["openkrx (missing)"])

    # only DART data on disk (as live on 2026-10-23): no index dataset at all → missing
    (tmp_path / "dart_filing" / "market=KR" / "date=2026-10-22").mkdir(parents=True)
    with pytest.raises(SourceUnavailable) as e:
        OpenkrxSource(tmp_path).rows()
    assert e.value.reason == "missing"
    with pytest.raises(SourceUnavailable):
        OpenkrxSource(tmp_path).rows([TAIEX])


def test_partial_store_default_reads_what_exists(tmp_path):
    shutil.copytree(FIX / "tw_index", tmp_path / "tw_index")
    src = OpenkrxSource(tmp_path)
    assert {r.series_id for r in src.rows()} == {TAIEX, TW50}
    with pytest.raises(SourceUnavailable) as e:
        src.rows([KOSPI])
    assert e.value.reason == "missing" and "krx_index_daily" in e.value.detail


def test_corrupt_part_is_error(tmp_path):
    shutil.copytree(FIX / "tw_index", tmp_path / "tw_index")
    (tmp_path / "tw_index" / "market=TW" / "date=2026-10-21" / "part-bad.parquet").write_text("x")
    with pytest.raises(SourceUnavailable) as e:
        OpenkrxSource(tmp_path).rows([TAIEX])
    assert e.value.reason == "error"


def test_from_config_env_override(tmp_path):
    src = OpenkrxSource.from_config(env={"ASSIST_OPENKRX_PARQUET": str(FIX)})
    assert src.root == FIX
    assert src.rows([TAIEX], start=D21)[0].value == 46887.77
