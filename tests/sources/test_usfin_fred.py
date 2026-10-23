"""FRED adapter (PLAN S2): sec-edgar's `usfin serve` CSV or a read-only ATTACH of its store.

One fixture (tests/fixtures/usfin) feeds both paths: a tiny usfin.duckdb built from sec-edgar's
FRED DDL, and a fake `usfin serve` (httpx MockTransport, no socket) that answers
`/series/fred/<id>?format=csv[&as_of=]` from that same file the way sec-edgar's route does."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import httpx
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.base import Row, Source, SourceUnavailable, read_rows
from assist.sources.usfin import (
    LAYER0_SERIES,
    NET_LIQUIDITY,
    FredSource,
    Usfin,
    net_liquidity,
)

FIX = FIXTURES / "usfin"
URL = "http://127.0.0.1:8660"
LATEST = datetime(9999, 12, 31)  # sec-edgar's "every version stored"


@pytest.fixture
def store(tmp_path) -> Path:
    path = tmp_path / "usfin.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute((FIX / "schema.sql").read_text())
        for table in ("fred_series", "fred_observation"):
            con.execute(
                f"insert into {table} select * from read_csv(?, header = true, all_varchar = true)",
                [str(FIX / f"{table}.csv")],
            )
    finally:
        con.close()
    return path


def _plain(value: Decimal) -> str:
    text = f"{Decimal(value):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def fake_serve(path: Path, calls: list[str] | None = None) -> httpx.MockTransport:
    """sec-edgar's /series/fred/<id> CSV (web/series.fred_rows + web/tables.to_csv)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        parts = request.url.path.strip("/").split("/")
        if parts[:2] != ["series", "fred"] or len(parts) != 3:
            return httpx.Response(404)
        series_id = parts[2]
        raw = request.url.params.get("as_of")
        ts = date.fromisoformat(raw) if raw else LATEST
        con = duckdb.connect(str(path), read_only=True)
        try:
            if not con.execute(
                "select 1 from fred_series where series_id = ?", [series_id]
            ).fetchone():
                return httpx.Response(404, text=f"unknown FRED series {series_id!r}")
            rows = con.execute(
                "SELECT a.date, a.value, a.realtime_start, a.first_seen_at,"
                " (SELECT count(*) FROM fred_observation o WHERE o.series_id = a.series_id"
                "   AND o.date = a.date AND o.first_seen_at <= a_utc.ts) AS versions"
                " FROM fred_as_of(?) a, (SELECT bls_as_of_utc(?) AS ts) a_utc"
                " WHERE a.series_id = ? ORDER BY a.date",
                [ts, ts, series_id],
            ).fetchall()
        finally:
            con.close()
        lines = ["date,value,realtime_start,first_seen_at,versions"]
        for d, v, rs, seen, n in rows:
            value = "" if v is None else _plain(v)
            lines.append(f"{d},{value},{rs},{seen:%Y-%m-%d %H:%M:%S}Z,{n}")
        return httpx.Response(200, text="\n".join(lines) + "\n")

    return httpx.MockTransport(handler)


def down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def fred(path: Path | None, transport=None) -> FredSource:
    client = httpx.Client(transport=transport or httpx.MockTransport(down))
    return FredSource(Usfin(url=URL, path=path, client=client))


ALL = ["GDPC1", "NFCI", "RRPONTSYD", "VIXCLS", "WALCL", "WTREGEN"]


# ---------------- the store (ATTACH) ----------------


def test_is_a_source(store):
    assert isinstance(fred(store), Source)
    assert fred(store).name == "sec-edgar"


def test_attach_reads_latest_version_with_vintage_as_of(store):
    rows = fred(store).rows_duckdb(["VIXCLS"])
    assert rows == [
        Row("VIXCLS", date(2026, 10, 5), 16.1, date(2026, 10, 6), "sec-edgar"),
        Row("VIXCLS", date(2026, 10, 6), 17.2, date(2026, 10, 7), "sec-edgar"),
        Row("VIXCLS", date(2026, 10, 7), 18.25, date(2026, 10, 9), "sec-edgar"),
        Row("VIXCLS", date(2026, 10, 8), None, date(2026, 10, 9), "sec-edgar"),
    ]


def test_attach_as_of_gives_values_known_that_day(store):
    src = fred(store)
    gdp = src.rows_duckdb(["GDPC1"], as_of=date(2020, 5, 1))
    assert [(r.date, r.value) for r in gdp] == [(date(2020, 1, 1), 18987.877)]
    # a DATE is 23:59:59 New York that day: the 2026-10-09 revision is not known on 2026-10-08
    vix = src.rows_duckdb(["VIXCLS"], as_of=date(2026, 10, 8))
    assert [(r.date, r.value) for r in vix][-1] == (date(2026, 10, 7), 18.0)


def test_filters_series_and_dates(store):
    rows = fred(store).rows_duckdb(
        ["NFCI", "RRPONTSYD"], start=date(2026, 9, 30), end=date(2026, 10, 6)
    )
    assert [(r.series_id, r.date) for r in rows] == [
        ("NFCI", date(2026, 10, 3)),
        ("RRPONTSYD", date(2026, 9, 30)),
        ("RRPONTSYD", date(2026, 10, 6)),
    ]
    assert fred(store).rows_duckdb([]) == []


def test_store_is_attached_read_only(store):
    src = fred(store)
    src.rows_duckdb(["VIXCLS"])
    with src.usfin.attached() as con, pytest.raises(duckdb.Error, match="read-only|read only"):
        con.execute("delete from fred_observation")


# ---------------- HTTP == ATTACH ----------------


@pytest.mark.parametrize("as_of", [None, date(2020, 5, 1), date(2026, 10, 8)])
@pytest.mark.parametrize(
    "window", [(None, None), (date(2026, 9, 30), date(2026, 10, 7))], ids=["all", "window"]
)
def test_http_and_attach_give_identical_rows(store, as_of, window):
    src = fred(store, fake_serve(store))
    start, end = window
    via_http = src.rows_http(ALL, start=start, end=end, as_of=as_of)
    via_db = src.rows_duckdb(ALL, start=start, end=end, as_of=as_of)
    assert via_http == via_db
    if as_of is None and start is None:
        assert len(via_db) == 16  # every (series, date) in the fixture, latest version


def test_http_sends_as_of_and_csv(store):
    calls = []
    fred(store, fake_serve(store, calls)).rows_http(["GDPC1"], as_of=date(2020, 5, 1))
    assert calls == [f"{URL}/series/fred/GDPC1?as_of=2020-05-01&format=csv"]


def test_unknown_series_is_empty_on_both_paths(store):
    src = fred(store, fake_serve(store))
    assert src.rows_http(["NOPE"]) == src.rows_duckdb(["NOPE"]) == []


# ---------------- choosing the path ----------------


def test_uses_http_when_serve_answers(store):
    calls = []
    src = fred(store, fake_serve(store, calls))
    rows = src.rows(["VIXCLS"])
    assert src.usfin.via == "http" and calls
    assert rows == src.rows_duckdb(["VIXCLS"])


def test_falls_back_to_attach_when_serve_is_down(store):
    src = fred(store)
    rows = src.rows(["VIXCLS"], as_of=date(2026, 10, 8))
    assert src.usfin.via == "duckdb"
    assert rows[-1].value == 18.0


def test_default_series_are_the_layer0_set(store):
    assert len(LAYER0_SERIES) == 25
    assert {"VIXCLS", "NFCI", "STLFSI4", "WALCL", "WTREGEN", "RRPONTSYD"} <= set(LAYER0_SERIES)
    ids = {r.series_id for r in fred(store).rows()}
    assert ids == {"VIXCLS", "WALCL", "WTREGEN", "RRPONTSYD", "NFCI"}  # GDPC1 is layer 2


def test_down_and_missing_is_unavailable(tmp_path):
    src = fred(tmp_path / "nope.duckdb")
    with pytest.raises(SourceUnavailable) as e:
        src.rows(["VIXCLS"])
    assert e.value.reason == "missing"
    assert read_rows(src, ["VIXCLS"]) == ([], ["sec-edgar (missing)"])


def test_locked_store_is_unavailable(store):
    with hold_duckdb_lock(store), pytest.raises(SourceUnavailable) as e:
        fred(store).rows(["VIXCLS"])
    assert e.value.reason == "locked"


def test_busy_serve_is_locked_not_a_fallback(store):
    busy = httpx.MockTransport(lambda r: httpx.Response(503, text="busy"))
    with pytest.raises(SourceUnavailable) as e:
        fred(store, busy).rows(["VIXCLS"])
    assert e.value.reason == "locked"


def test_from_config_reads_sources_yaml(tmp_path):
    u = Usfin.from_config(env={"ASSIST_SEC_EDGAR_DB": str(tmp_path / "x.duckdb")})
    assert u.url == URL
    assert u.path == tmp_path / "x.duckdb"


# ---------------- net liquidity ----------------


def test_net_liquidity_in_millions(store):
    src = fred(store)
    rows = src.rows_duckdb(["WALCL", "WTREGEN", "RRPONTSYD"])
    assert net_liquidity(rows) == [
        Row(
            NET_LIQUIDITY,
            date(2026, 9, 30),
            6608000 - 850000 - 20.25 * 1000,
            date(2026, 10, 2),
            "sec-edgar",
        ),
        Row(
            NET_LIQUIDITY,
            date(2026, 10, 7),
            6590000 - 800000 - 2.5 * 1000,
            date(2026, 10, 9),
            "sec-edgar",
        ),
    ]


def test_net_liquidity_uses_last_known_component():
    rows = [
        Row("WALCL", date(2026, 10, 7), 100.0, date(2026, 10, 9), "sec-edgar"),
        Row("WTREGEN", date(2026, 9, 30), 10.0, date(2026, 10, 2), "sec-edgar"),
        Row("RRPONTSYD", date(2026, 10, 6), 0.002, date(2026, 10, 7), "sec-edgar"),
        Row("RRPONTSYD", date(2026, 10, 8), 9.0, date(2026, 10, 9), "sec-edgar"),
    ]
    assert net_liquidity(rows) == [
        Row(NET_LIQUIDITY, date(2026, 10, 7), 100.0 - 10.0 - 2.0, date(2026, 10, 9), "sec-edgar")
    ]
    assert net_liquidity(rows[:1]) == []  # no TGA or RRP yet: no value, not a guess
