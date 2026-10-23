"""jquantster adapter (P23): Japan macro (MOF JGB curve, BOJ USD/JPY, call rate, Tankan), TSE
investor-type flows, daily bars and J-Quants financial summaries, read READ-ONLY as tidy rows.

The fixture store (tests/fixtures/jquantster/) is jquantster's own DDL (copied from the live file)
with a few hand-picked rows."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from helpers import FIXTURES

from assist.sources.base import Row, SourceUnavailable, read_rows
from assist.sources.jquantster import (
    CALL_RATE,
    FRGN_BAL_PRIME,
    JGB_2Y,
    JGB_10Y,
    TANKAN_LM,
    USDJPY,
    JquantsterSource,
    bar_series,
    boj_series,
    fin_series,
    flow_series,
    jgb_series,
)

FIX = FIXTURES / "jquantster"
D = date.fromisoformat


def _build(path: Path, data: bool = True, wal: bool = False, ddl: str | None = None) -> Path:
    con = sqlite3.connect(path)
    try:
        if wal:
            con.execute("pragma journal_mode=wal")
        con.executescript(ddl or (FIX / "schema.sql").read_text())
        if data:
            con.executescript((FIX / "data.sql").read_text())
        con.commit()
    finally:
        con.close()
    return path


@pytest.fixture
def store(tmp_path) -> Path:
    return _build(tmp_path / "jquantster.db")


def test_series_ids():
    assert JGB_10Y == jgb_series("10Y") == "JGB.10Y" and JGB_2Y == "JGB.2Y"
    assert USDJPY == boj_series("usdjpy") == "BOJ.usdjpy"
    assert CALL_RATE == "BOJ.call_rate" and TANKAN_LM == "BOJ.tankan_lm"
    assert FRGN_BAL_PRIME == flow_series("TSEPrime", "FrgnBal") == "TSE_FLOW.TSEPrime.FrgnBal"
    assert bar_series("72030", "adj_c") == "JQ_BAR.72030.adj_c"
    assert fin_series("72030", "FY", "EPS") == "JQ_FIN.72030.FY.EPS"
    for bad in (lambda: jgb_series("10"), lambda: flow_series("TSEPrime", "FrgnNet"),
                lambda: bar_series("72030", "close"), lambda: fin_series("72030", "FY", "PE"),
                lambda: boj_series("bad.key")):
        with pytest.raises(ValueError):
            bad()


def test_jgb_curve(store):
    rows = JquantsterSource(store).rows([JGB_2Y, JGB_10Y, "JGB.40Y"])
    assert rows == [
        Row("JGB.10Y", D("2026-10-21"), 1.66, None, "jquantster"),
        Row("JGB.10Y", D("2026-10-22"), 1.70, None, "jquantster"),
        Row("JGB.2Y", D("2026-10-21"), 0.93, None, "jquantster"),
        Row("JGB.2Y", D("2026-10-22"), 0.95, None, "jquantster"),
        Row("JGB.40Y", D("2026-10-22"), 3.35, None, "jquantster"),
    ]


def test_boj_series(store):
    src = JquantsterSource(store)
    fx = src.rows([USDJPY])
    assert [(r.date, r.value) for r in fx] == [(D("2026-10-20"), 150.1), (D("2026-10-21"), 151.2)]
    tankan = src.rows([TANKAN_LM, boj_series("tankan_lm_fc")])
    assert [(r.series_id, r.date, r.value) for r in tankan] == [
        ("BOJ.tankan_lm", D("2026-06-30"), 13.0),
        ("BOJ.tankan_lm", D("2026-09-30"), 24.0),
        ("BOJ.tankan_lm_fc", D("2026-12-31"), 21.0),  # forecast runs a quarter ahead
    ]


def test_macro_meta(store):
    meta = JquantsterSource(store).macro_meta()
    assert meta["usdjpy"]["unit"] == "Yen per U.S. Dollar"
    assert meta["tankan_lm"]["frequency"] == "QUARTERLY"
    assert set(meta) == {"usdjpy", "call_rate", "tankan_lm", "tankan_lm_fc"}


def test_flows_use_latest_publication(store):
    rows = JquantsterSource(store).rows([FRGN_BAL_PRIME])
    # week ending 10-09 was revised on 10-22: the revision wins and its pub date is as_of
    assert rows == [
        Row(FRGN_BAL_PRIME, D("2026-10-09"), 1200.0, D("2026-10-22"), "jquantster"),
        Row(FRGN_BAL_PRIME, D("2026-10-16"), -500.0, D("2026-10-22"), "jquantster"),
    ]


def test_flow_nulls_are_skipped(store):
    rows = JquantsterSource(store).rows([flow_series("TSEStandard", "IndBal"),
                                         flow_series("TSEStandard", "FrgnBal")])
    assert [(r.series_id, r.value) for r in rows] == [("TSE_FLOW.TSEStandard.FrgnBal", 40.0)]


def test_default_rows_are_macro_and_flows(store):
    rows = JquantsterSource(store).rows()
    ids = {r.series_id for r in rows}
    assert {"JGB.2Y", "JGB.10Y", "JGB.40Y"} <= ids
    assert {"BOJ.usdjpy", "BOJ.call_rate", "BOJ.tankan_lm", "BOJ.tankan_lm_fc"} <= ids
    assert {FRGN_BAL_PRIME, "TSE_FLOW.TSEPrime.IndBal", "TSE_FLOW.TSEStandard.FrgnBuy"} <= ids
    assert not any(s.startswith(("JQ_BAR.", "JQ_FIN.")) for s in ids)
    keys = [(r.series_id, r.date) for r in rows]
    assert keys == sorted(keys) and len(keys) == len(set(keys))


def test_bars(store):
    src = JquantsterSource(store)
    rows = src.rows([bar_series("99840", "adj_c"), bar_series("99840", "c"),
                     bar_series("72030", "va")])
    assert [(r.series_id, r.date, r.value) for r in rows] == [
        ("JQ_BAR.72030.va", D("2026-07-30"), 2.8e10),
        ("JQ_BAR.72030.va", D("2026-07-31"), 2.5e10),
        ("JQ_BAR.99840.adj_c", D("2026-07-31"), 4525.0),
        ("JQ_BAR.99840.c", D("2026-07-31"), 9050.0),
    ]
    assert {r.as_of for r in rows} == {None}


def test_fins_latest_disclosure_per_period(store):
    src = JquantsterSource(store)
    rows = src.rows([fin_series("72030", "FY", "EPS"), fin_series("72030", "1Q", "EPS"),
                     fin_series("72030", "FY", "FEPS"), fin_series("72030", "1Q", "FEPS")])
    assert rows == [
        Row("JQ_FIN.72030.1Q.EPS", D("2026-06-30"), 80.0, D("2026-08-01"), "jquantster"),
        # the 05-20 correction replaces the 05-08 filing; blank 1Q FEPS gives no row
        Row("JQ_FIN.72030.FY.EPS", D("2026-03-31"), 301.0, D("2026-05-20"), "jquantster"),
        Row("JQ_FIN.72030.FY.FEPS", D("2026-03-31"), 320.0, D("2026-05-20"), "jquantster"),
    ]


def test_window_filter(store):
    src = JquantsterSource(store)
    day = D("2026-10-21")
    rows = src.rows([JGB_10Y, USDJPY, FRGN_BAL_PRIME], start=day, end=day)
    assert {(r.series_id, r.date) for r in rows} == {(JGB_10Y, day), (USDJPY, day)}
    fin = src.rows([fin_series("72030", "FY", "EPS")], start=D("2026-04-01"))
    assert fin == []


def test_unknown_series_are_dropped(store):
    src = JquantsterSource(store)
    assert src.rows(["NOT_A_SERIES", "JGB.10", "TSE_FLOW.TSEPrime.Bogus", "JQ_BAR.1.x"]) == []
    assert src.rows([jgb_series("50Y"), boj_series("cpi"), bar_series("00000", "c")]) == []


def test_status(store):
    st = JquantsterSource(store).status()
    assert st["plan"] == "free" and st["window"] == "2024-07-31..2026-07-31"
    assert st["entitlements"]["investor_types"] == "ok"


def test_flows_not_in_plan_is_reported(tmp_path):
    path = _build(tmp_path / "free.db")
    con = sqlite3.connect(path)
    con.execute("delete from investor_types")
    con.execute("update entitlements set status = 'not_in_plan' where dataset = 'investor_types'")
    con.commit()
    con.close()
    src = JquantsterSource(path)
    assert src.rows([FRGN_BAL_PRIME]) == []
    assert src.status()["entitlements"]["investor_types"] == "not_in_plan"


def test_wal_store_without_shm_reads(tmp_path):
    path = _build(tmp_path / "wal.db", wal=True)
    assert not path.with_name("wal.db-shm").exists()
    assert len(JquantsterSource(path).rows([JGB_10Y])) == 2
    assert not path.with_name("wal.db-shm").exists()


def test_store_is_never_written(store):
    before = store.read_bytes()
    src = JquantsterSource(store)
    src.rows()
    src.rows([bar_series("72030", "c"), fin_series("72030", "FY", "EPS")])
    src.status()
    src.macro_meta()
    assert store.read_bytes() == before
    assert sorted(p.name for p in store.parent.iterdir()) == ["jquantster.db"]


def test_missing_tables_is_missing(tmp_path):
    path = _build(tmp_path / "old.db", data=False, ddl="create table meta (key text, value text);")
    with pytest.raises(SourceUnavailable) as e:
        JquantsterSource(path).rows()
    assert e.value.reason == "missing" and "jgb_yields" in e.value.detail


def test_missing_file(tmp_path):
    rows, stale = read_rows(JquantsterSource(tmp_path / "nope.db"))
    assert rows == [] and stale == ["jquantster (missing)"]


def test_locked_store(store):
    writer = sqlite3.connect(store)
    writer.execute("begin exclusive")
    try:
        rows, stale = read_rows(JquantsterSource(store), [JGB_10Y])
    finally:
        writer.rollback()
        writer.close()
    assert rows == [] and stale == ["jquantster (locked)"]


def test_from_config(tmp_path, store):
    src = JquantsterSource.from_config(env={"ASSIST_JQUANTSTER_DB": str(store)})
    assert src.path == store
