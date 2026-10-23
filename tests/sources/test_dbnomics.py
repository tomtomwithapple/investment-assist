"""dbnomics adapter (P16): `dbn serve` CSV first, open-query-close on the store otherwise.

One fixture (tests/fixtures/dbnomics) feeds both paths: a tiny dbnomics.duckdb built from the
store's DDL (../dbnomics/src/dbnomics/store.py), and a fake `dbn serve` (httpx MockTransport, no
socket) answering `/api/series`, `/api/series/<id>[?from=]` and `/api/latest` with `?format=csv`
from that same file the way dbnomics' serve.py does."""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import date, datetime
from pathlib import Path

import duckdb
import httpx
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.base import Row, Source, SourceUnavailable, read_rows
from assist.sources.dbnomics import DEFAULT_URL, SOURCE, DbnomicsSource

FIX = FIXTURES / "dbnomics"
ALL = ["cn.pmi.mfg", "ea.rate.deposit", "idn.cli", "idn.crp", "idn.rate.long", "us.erp.implied"]


@pytest.fixture
def store(tmp_path) -> Path:
    path = tmp_path / "dbnomics.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute((FIX / "schema.sql").read_text())
        con.execute((FIX / "seed.sql").read_text())
    finally:
        con.close()
    return path


# ---------------- a fake `dbn serve` (serve.py api_series, api_series_one, api_latest) -------

SERIES_SQL = """
select s.series_id, s.title, s.country, s.freq, s.unit, s.grp, s.chain, s.max_lag_days,
       st.source, st.latest_period, st.stale, st.checked_at
from series s left join series_status st using (series_id)
{where}
order by s.grp, s.series_id
"""


def _jsonable(value):
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _csv(con, sql, params=()) -> str:
    cur = con.execute(sql, list(params))
    cols = [d[0] for d in cur.description]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    writer.writeheader()
    for row in cur.fetchall():
        writer.writerow(dict(zip(cols, map(_jsonable, row), strict=True)))
    return buf.getvalue()


def fake_serve(path: Path, calls: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if request.url.params.get("format") != "csv":
            return httpx.Response(400, text="want csv in these tests")
        parts = request.url.path.strip("/").split("/")
        con = duckdb.connect(str(path), read_only=True)
        try:
            if parts == ["api", "series"]:
                return httpx.Response(200, text=_csv(con, SERIES_SQL.format(where="")))
            if parts == ["api", "latest"]:
                sql = (
                    "select l.series_id, s.title, s.country, s.freq, s.unit, s.grp, l.date,"
                    " l.value, l.prev_value, l.change, l.source, l.stale"
                    " from series_latest l left join series s using (series_id)"
                    " order by s.grp, l.series_id"
                )
                return httpx.Response(200, text=_csv(con, sql))
            if parts[:2] == ["api", "series"] and len(parts) == 3:
                sid = parts[2]
                if not con.execute("select 1 from series where series_id = ?", [sid]).fetchone():
                    return httpx.Response(404, text=f"unknown series: {sid}")
                sql = (
                    "select date, period, value, source, source_series_id from observations"
                    " where series_id = ?"
                )
                args = [sid]
                if start := request.url.params.get("from"):
                    sql += " and date >= ?"
                    args.append(date.fromisoformat(start))
                return httpx.Response(200, text=_csv(con, sql + " order by date", args))
            return httpx.Response(404, text="not found")
        finally:
            con.close()

    return httpx.MockTransport(handler)


def down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def dbn(path: Path | None, transport=None) -> DbnomicsSource:
    client = httpx.Client(transport=transport or httpx.MockTransport(down))
    return DbnomicsSource(url=DEFAULT_URL, path=path, client=client)


# ---------------- the store (open-query-close) ----------------


def test_is_a_source(store):
    assert isinstance(dbn(store), Source)
    assert dbn(store).name == SOURCE == "dbnomics"
    assert DEFAULT_URL == "http://127.0.0.1:8770"


def test_store_rows_are_tidy(store):
    rows = dbn(store).rows_duckdb(["idn.cli"])
    assert rows == [
        Row("idn.cli", date(2026, 7, 1), 98.9529, None, "dbnomics"),
        Row("idn.cli", date(2026, 8, 1), 98.75598, None, "dbnomics"),
        Row("idn.cli", date(2026, 9, 1), 98.62859, None, "dbnomics"),
    ]


def test_null_value_is_none(store):
    rows = dbn(store).rows_duckdb(["idn.rate.long"])
    assert [(r.date, r.value) for r in rows] == [
        (date(2024, 11, 1), 6.85),
        (date(2024, 12, 1), None),
    ]


def test_default_is_every_series(store):
    rows = dbn(store).rows_duckdb()
    assert sorted({r.series_id for r in rows}) == ALL
    assert rows == sorted(rows, key=lambda r: (r.series_id, r.date))
    assert len(rows) == 13


def test_filters_series_and_dates(store):
    rows = dbn(store).rows_duckdb(
        ["cn.pmi.mfg", "us.erp.implied"], start=date(2026, 9, 1), end=date(2026, 9, 30)
    )
    assert [(r.series_id, r.date, r.value) for r in rows] == [
        ("cn.pmi.mfg", date(2026, 9, 1), 49.8),
        ("us.erp.implied", date(2026, 9, 1), 0.0383),
    ]
    assert dbn(store).rows_duckdb([]) == []


def test_catalog_carries_unit_group_and_staleness(store):
    cat = dbn(store).series_duckdb()
    assert [s["series_id"] for s in cat] == [
        "cn.pmi.mfg", "ea.rate.deposit", "idn.cli", "idn.rate.long", "idn.crp", "us.erp.implied",
    ]  # fmt: skip
    long = next(s for s in cat if s["series_id"] == "idn.rate.long")
    assert (long["unit"], long["grp"], long["freq"], long["stale"]) == ("% p.a.", "oecd", "M", True)
    assert long["latest_period"] == "2024-12"
    assert long["checked_at"] == datetime(2026, 10, 21, 6, 40, 2)
    pmi = next(s for s in cat if s["series_id"] == "cn.pmi.mfg")
    assert [c["kind"] for c in pmi["chain"]] == ["nbs", "dbnomics"]
    assert pmi["max_lag_days"] == 75


def test_latest_has_change_and_stale(store):
    latest = {r["series_id"]: r for r in dbn(store).latest_duckdb()}
    cli = latest["idn.cli"]
    assert (cli["date"], cli["value"], cli["prev_value"]) == (date(2026, 9, 1), 98.62859, 98.75598)
    assert cli["change"] == pytest.approx(98.62859 - 98.75598)
    assert (cli["unit"], cli["stale"]) == ("index, long-term average = 100", False)
    assert latest["idn.rate.long"]["value"] is None and latest["idn.rate.long"]["stale"] is True


def test_store_is_opened_read_only_and_closed(store):
    src = dbn(store)
    src.rows_duckdb(["idn.cli"])
    # nothing stays open: a writer (as `dbn refresh`) can take the lock straight after
    con = duckdb.connect(str(store))
    con.close()


# ---------------- valuation tables (store only: the API does not serve them) ----------------


def test_damodaran_erp_monthly_headline(store):
    rows = dbn(store).damodaran_erp()
    assert [(r["date"], r["value"], r["tbond"]) for r in rows] == [
        (date(2026, 9, 1), 0.0383, 0.0510),
        (date(2026, 10, 1), 0.037, 0.0529),
    ]
    annual = dbn(store).damodaran_erp(freq="A", variant="fcfe")
    assert [(r["date"], r["value"]) for r in annual] == [(date(2025, 12, 31), 0.0433)]
    assert dbn(store).damodaran_erp(start=date(2026, 10, 1))[0]["sp500"] == 7652.0


def test_damodaran_crp_by_country_and_snapshot(store):
    src = dbn(store)
    idn = src.damodaran_crp(["IDN"])
    assert [(r["snapshot_date"], r["moodys"]) for r in idn] == [
        (date(2025, 1, 1), "Baa2"),
        (date(2026, 1, 1), "Baa2"),
    ]
    assert idn[-1]["crp"] == pytest.approx(0.024649631345505598)
    assert idn[-1]["total_erp"] == pytest.approx(idn[-1]["us_erp_base"] + idn[-1]["crp"])
    latest = src.damodaran_crp(snapshot=date(2026, 1, 1))
    assert [r["country"] for r in latest] == ["Abu Dhabi", "Indonesia", "Japan"]
    assert latest[0]["iso3"] is None
    assert len(src.damodaran_crp()) == 4


def test_shiller(store):
    rows = dbn(store).shiller(start=date(2026, 10, 1))
    assert len(rows) == 1
    r = rows[0]
    assert (r["date"], r["gs10"], r["provisional"]) == (date(2026, 10, 1), 5.24, True)
    assert r["cape"] == pytest.approx(40.7106, abs=1e-4)
    assert r["earnings"] is None
    assert len(dbn(store).shiller()) == 2


# ---------------- HTTP == store ----------------


@pytest.mark.parametrize(
    "window", [(None, None), (date(2026, 9, 1), date(2026, 9, 30))], ids=["all", "window"]
)
@pytest.mark.parametrize("ids", [None, ["idn.cli", "idn.rate.long", "ea.rate.deposit"]])
def test_http_and_store_give_identical_rows(store, window, ids):
    src = dbn(store, fake_serve(store))
    start, end = window
    assert src.rows_http(ids, start, end) == src.rows_duckdb(ids, start, end)


def test_http_catalog_and_latest_match_store(store):
    src = dbn(store, fake_serve(store))
    assert src.series_http() == src.series_duckdb()
    assert src.latest_http() == src.latest_duckdb()


def test_http_routes_use_from_and_csv(store):
    calls = []
    src = dbn(store, fake_serve(store, calls))
    src.rows_http(["idn.cli"], start=date(2026, 8, 1))
    assert calls == [f"{DEFAULT_URL}/api/series/idn.cli?from=2026-08-01&format=csv"]
    calls.clear()
    src.rows_http()
    assert calls[0] == f"{DEFAULT_URL}/api/series?format=csv"
    assert len(calls) == 1 + len(ALL)


def test_unknown_series_is_empty_on_both_paths(store):
    src = dbn(store, fake_serve(store))
    assert src.rows_http(["nope"]) == src.rows_duckdb(["nope"]) == []


# ---------------- choosing the path ----------------


def test_uses_http_when_serve_answers(store):
    calls = []
    src = dbn(store, fake_serve(store, calls))
    rows = src.rows(["idn.crp"])
    assert src.via == "http" and calls
    assert rows == src.rows_duckdb(["idn.crp"])
    assert src.series() == src.series_duckdb()
    assert src.latest() == src.latest_duckdb()


def test_falls_back_to_store_when_serve_is_down(store):
    src = dbn(store)
    rows = src.rows(["us.erp.implied"])
    assert src.via == "duckdb"
    assert rows[-1].value == 0.037
    assert len(src.series()) == 6


def test_down_and_missing_is_unavailable(tmp_path):
    src = dbn(tmp_path / "nope.duckdb")
    with pytest.raises(SourceUnavailable) as e:
        src.rows()
    assert e.value.reason == "missing"
    assert read_rows(src) == ([], ["dbnomics (missing)"])
    with pytest.raises(SourceUnavailable):
        src.shiller()


def test_locked_store_is_unavailable(store):
    with hold_duckdb_lock(store), pytest.raises(SourceUnavailable) as e:
        dbn(store).rows()
    assert e.value.reason == "locked"
    with hold_duckdb_lock(store), pytest.raises(SourceUnavailable) as e:
        dbn(store).damodaran_crp(["IDN"])
    assert e.value.reason == "locked"


def test_busy_serve_is_locked_not_a_fallback(store):
    busy = httpx.MockTransport(lambda r: httpx.Response(503, text="locked by refresh"))
    with pytest.raises(SourceUnavailable) as e:
        dbn(store, busy).rows()
    assert e.value.reason == "locked"


def test_from_config_reads_sources_yaml(tmp_path, store):
    src = DbnomicsSource.from_config(
        env={"ASSIST_DBNOMICS_DB": str(store), "ASSIST_DBNOMICS_URL": "http://127.0.0.1:9"}
    )
    assert src.url == "http://127.0.0.1:9"
    assert Path(src.path) == store


def test_chain_is_json_list_on_both_paths(store):
    src = dbn(store, fake_serve(store))
    for cat in (src.series_http(), src.series_duckdb()):
        assert all(isinstance(s["chain"], list) for s in cat)
        assert json.dumps(cat[0]["chain"])
