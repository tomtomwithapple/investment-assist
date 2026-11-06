"""IDX index series from idxscape `index_daily` (migration 10), stitched JCI (P51-jci-idxscape).

`IDX.<code>` reads `close` READ-ONLY with `as_of` None (no fetch time stored). `JciSource` takes
idxscape COMPOSITE wherever it has rows and idx-method's frozen CSV only before idxscape's first
close; either store gone, the other carries on. tests/fixtures/idxscape/index_daily.sql holds
the DDL and a few rows; tests/fixtures/idxmethod/index/ the idx-method side (2026-09-28..30)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES

from assist.sources.base import Row, SourceUnavailable
from assist.sources.idxmethod import JCI, IdxMethodIndexSource, JciSource, jci
from assist.sources.idxscape import COMPOSITE, IdxscapeSource, index_series

FIX = FIXTURES / "idxscape"
IDXM = FIXTURES / "idxmethod" / "index"


@pytest.fixture
def store(tmp_path) -> Path:
    path = tmp_path / "idxscape.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute((FIX / "index_daily.sql").read_text())
    finally:
        con.close()
    return path


@pytest.fixture
def stitched(store) -> JciSource:
    return JciSource(IdxscapeSource(store), IdxMethodIndexSource(IDXM))


def test_index_series_close_with_unknown_as_of(store):
    src = IdxscapeSource(store)
    assert COMPOSITE == index_series("COMPOSITE") == "IDX.COMPOSITE"
    rows = src.rows([index_series("LQ45"), index_series("IDXENERGY")])
    assert rows == [
        Row("IDX.IDXENERGY", date(2026, 11, 5), 3010.0, None, "idxscape"),
        Row("IDX.LQ45", date(2026, 9, 30), 801.5, None, "idxscape"),
        Row("IDX.LQ45", date(2026, 11, 5), 820.0, None, "idxscape"),
    ]
    window = src.rows([COMPOSITE], start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert [(r.date, r.value) for r in window] == [(date(2026, 10, 1), 6100.5)]
    assert src.rows([index_series("NOPE")]) == []


def test_index_series_not_in_default_rows(store):
    with pytest.raises(SourceUnavailable):  # no default table in this store
        IdxscapeSource(store).rows()


def test_index_series_missing_table(tmp_path):
    path = tmp_path / "old.duckdb"
    duckdb.connect(str(path)).close()
    with pytest.raises(SourceUnavailable) as e:
        IdxscapeSource(path).rows([COMPOSITE])
    assert e.value.reason == "missing" and "index_daily" in e.value.detail


def test_jci_stitches_idxmethod_before_idxscape_first_close(stitched):
    rows = jci(source=stitched)
    assert [(r.date, r.source) for r in rows] == [
        (date(2026, 9, 28), "idx-method"),
        (date(2026, 9, 29), "idxscape"),
        (date(2026, 9, 30), "idxscape"),
        (date(2026, 10, 1), "idxscape"),
        (date(2026, 11, 5), "idxscape"),
    ]
    assert {r.series_id for r in rows} == {JCI}
    assert rows[-1] == Row(JCI, date(2026, 11, 5), 6250.25, None, "idxscape")


def test_seam_does_not_move_with_the_window(stitched):
    # a window starting after idxscape's first close never pulls idx-method rows back in
    rows = stitched.rows([JCI], start=date(2026, 9, 30), end=date(2026, 10, 1))
    assert [(r.date, r.source) for r in rows] == [
        (date(2026, 9, 30), "idxscape"), (date(2026, 10, 1), "idxscape")]
    # a window ending before it is idx-method only
    old = stitched.rows([JCI], end=date(2026, 9, 28))
    assert [(r.date, r.source) for r in old] == [(date(2026, 9, 28), "idx-method")]


def test_other_series_ignored(stitched):
    assert stitched.rows(["LQ45"]) == []
    assert stitched.rows() == jci(source=stitched)


def test_one_store_gone_the_other_carries_on(store, tmp_path):
    no_idxscape = JciSource(IdxscapeSource(tmp_path / "nope.duckdb"), IdxMethodIndexSource(IDXM))
    assert [r.source for r in jci(source=no_idxscape)] == ["idx-method"] * 3
    no_idxm = JciSource(IdxscapeSource(store), IdxMethodIndexSource(tmp_path / "nope"))
    assert [r.date for r in jci(source=no_idxm)][0] == date(2026, 9, 29)
    both = JciSource(IdxscapeSource(tmp_path / "nope.duckdb"), IdxMethodIndexSource(tmp_path / "x"))
    with pytest.raises(SourceUnavailable) as e:
        jci(source=both)
    assert e.value.source == "idxscape"


def test_from_config_honours_env(store):
    src = JciSource.from_config(env={"ASSIST_IDX_METHOD_DIR": str(IDXM),
                                     "ASSIST_IDXSCAPE_DB": str(store)})
    assert jci(source=src)[-1].date == date(2026, 11, 5)
