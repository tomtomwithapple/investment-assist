"""TIC adapter (P15): sec-edgar's `usfin serve` CSV or a read-only ATTACH of its store.

One fixture (tests/fixtures/usfin_tic) feeds both paths: a tiny usfin.duckdb built from
sec-edgar's TIC DDL (migration 021), and a fake `usfin serve` (httpx MockTransport, no socket)
answering `/series/tic?country=…&format=csv` (the catalog) and `/series/tic/<id>?format=csv
[&as_of=]` (one series) from that same file the way sec-edgar's web/series.py does."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import httpx
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.sources.base import Row, Source, SourceUnavailable, read_rows
from assist.sources.usfin import Usfin
from assist.sources.usfin_tic import INDONESIA, TicSource

FIX = FIXTURES / "usfin_tic"
URL = "http://127.0.0.1:8660"
LATEST = datetime(9999, 12, 31)  # sec-edgar's "every version stored"
IDN = [
    "for_lt_eqty_net_42218",
    "for_treas_pos_42218",
    "us_lt_bond_net_42218",
    "us_lt_eqty_net_42218",
    "us_lt_eqty_pos_42218",
]


@pytest.fixture
def store(tmp_path) -> Path:
    path = tmp_path / "usfin.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute((FIX / "schema.sql").read_text())
        for table in ("tic_series", "tic_observation"):
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


def _cell(value) -> str:
    """sec-edgar's web/tables.cell for the types these routes send."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return f"{value:%Y-%m-%d %H:%M:%S}Z"
    if isinstance(value, Decimal):
        return _plain(value)
    return value.isoformat() if isinstance(value, date) else str(value)


def _csv(header: tuple[str, ...], rows) -> httpx.Response:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows([_cell(v) for v in r] for r in rows)
    return httpx.Response(200, text=out.getvalue())


def fake_serve(path: Path, calls: list[str] | None = None) -> httpx.MockTransport:
    """sec-edgar's /series/tic and /series/tic/<id> CSV (web/series.tic_list, tic_rows)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        parts = request.url.path.strip("/").split("/")
        if parts[:2] != ["series", "tic"] or len(parts) > 3:
            return httpx.Response(404)
        con = duckdb.connect(str(path), read_only=True)
        try:
            if len(parts) == 2:
                country = request.url.params.get("country") or None
                where, params = "", []
                if country:
                    where = " WHERE (s.country_code = ? OR lower(s.country) LIKE ?)"
                    params = [country, f"%{country.lower()}%"]
                found = con.execute(
                    "SELECT s.series_id, s.title, s.measure, s.kind, s.country_code, s.country,"
                    " s.active, l.date, l.value FROM tic_series s LEFT JOIN ("
                    "   SELECT series_id, date, value FROM tic_observation_latest"
                    "   QUALIFY row_number() OVER (PARTITION BY series_id ORDER BY date DESC) = 1"
                    " ) l USING (series_id)"
                    + where
                    + " ORDER BY s.country_code, s.measure, s.kind",
                    params,
                ).fetchall()
                header = ("series_id", "title", "measure", "kind", "country_code", "country",
                          "active", "last", "value")  # fmt: skip
                return _csv(header, found)
            series_id = parts[2]
            raw = request.url.params.get("as_of")
            ts = date.fromisoformat(raw) if raw else LATEST
            if not con.execute(
                "select 1 from tic_series where series_id = ?", [series_id]
            ).fetchone():
                return httpx.Response(404, text=f"unknown TIC series {series_id!r}")
            found = con.execute(
                "SELECT a.date, a.value, a.first_seen_at,"
                " (SELECT count(*) FROM tic_observation o WHERE o.series_id = a.series_id"
                "   AND o.date = a.date AND o.first_seen_at <= a_utc.ts) AS versions"
                " FROM tic_as_of(?) a, (SELECT bls_as_of_utc(?) AS ts) a_utc"
                " WHERE a.series_id = ? ORDER BY a.date",
                [ts, ts, series_id],
            ).fetchall()
        finally:
            con.close()
        return _csv(("date", "value", "first_seen_at", "versions"), found)

    return httpx.MockTransport(handler)


def down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def tic(path: Path | None, transport=None) -> TicSource:
    client = httpx.Client(transport=transport or httpx.MockTransport(down))
    return TicSource(Usfin(url=URL, path=path, client=client))


# ---------------- the store (ATTACH) ----------------


def test_is_a_source(store):
    assert isinstance(tic(store), Source)
    assert tic(store).name == "sec-edgar"
    assert INDONESIA == "42218"


def test_attach_reads_latest_version_with_first_seen_as_of(store):
    rows = tic(store).rows_duckdb(["us_lt_eqty_net_42218"])
    assert rows == [
        Row("us_lt_eqty_net_42218", date(2026, 5, 1), -835.0, date(2026, 8, 19), "sec-edgar"),
        Row("us_lt_eqty_net_42218", date(2026, 6, 1), -735.0, date(2026, 9, 19), "sec-edgar"),
        Row("us_lt_eqty_net_42218", date(2026, 7, 1), -7.0, date(2026, 9, 19), "sec-edgar"),
    ]


def test_null_value_is_none(store):
    rows = tic(store).rows_duckdb(["us_lt_eqty_pos_42218"])
    assert [(r.date, r.value) for r in rows][-1] == (date(2026, 7, 1), None)


def test_attach_as_of_gives_values_known_that_day(store):
    # first seen 2026-09-19 01:00 UTC = 2026-09-18 21:00 New York: known on the 18th, not the 17th
    before = tic(store).rows_duckdb(["us_lt_eqty_net_42218"], as_of=date(2026, 9, 17))
    assert [(r.date, r.value) for r in before] == [
        (date(2026, 5, 1), -835.0),
        (date(2026, 6, 1), -700.0),
    ]
    after = tic(store).rows_duckdb(["us_lt_eqty_net_42218"], as_of=date(2026, 9, 18))
    assert after[-1].value == -7.0


def test_default_is_every_indonesia_series(store):
    rows = tic(store).rows_duckdb()
    assert sorted({r.series_id for r in rows}) == IDN
    assert rows == sorted(rows, key=lambda r: (r.series_id, r.date))


def test_country_by_code_or_name(store):
    src = tic(store)
    asia = src.rows_duckdb(country="total asia")
    assert {r.series_id for r in asia} == {"us_lt_eqty_net_49999"}
    assert src.rows_duckdb(country="99996")[0].series_id == "for_treas_pos_99996"
    assert src.rows_duckdb(country="Indonesia") == src.rows_duckdb(country=INDONESIA)


def test_filters_series_and_dates(store):
    rows = tic(store).rows_duckdb(
        ["us_lt_eqty_net_42218", "for_treas_pos_99996"],
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
    )
    assert [(r.series_id, r.date) for r in rows] == [
        ("for_treas_pos_99996", date(2026, 6, 1)),
        ("us_lt_eqty_net_42218", date(2026, 6, 1)),
    ]
    assert tic(store).rows_duckdb([]) == []


def test_catalog_lists_a_country_with_parts(store):
    cat = tic(store).series_duckdb(INDONESIA)
    assert [s["series_id"] for s in cat] == [
        "for_lt_eqty_net_42218",
        "for_treas_pos_42218",
        "us_lt_bond_net_42218",
        "us_lt_eqty_net_42218",
        "us_lt_eqty_pos_42218",
    ]
    eq = next(s for s in cat if s["series_id"] == "us_lt_eqty_net_42218")
    assert (eq["measure"], eq["kind"], eq["country"], eq["active"]) == (
        "us_lt_eqty", "net", "Indonesia", True,
    )  # fmt: skip
    assert (eq["last"], eq["value"]) == (date(2026, 7, 1), -7.0)


def test_store_is_attached_read_only(store):
    src = tic(store)
    with src.usfin.attached() as con, pytest.raises(duckdb.Error, match="read-only|read only"):
        con.execute("delete from tic_observation")


# ---------------- HTTP == ATTACH ----------------


@pytest.mark.parametrize("as_of", [None, date(2026, 9, 17), date(2026, 9, 18)])
@pytest.mark.parametrize(
    "window", [(None, None), (date(2026, 6, 1), date(2026, 6, 30))], ids=["all", "window"]
)
@pytest.mark.parametrize("ids", [None, ["for_treas_pos_99996", "us_lt_eqty_net_42218"]])
def test_http_and_attach_give_identical_rows(store, as_of, window, ids):
    src = tic(store, fake_serve(store))
    start, end = window
    via_http = src.rows_http(ids, start=start, end=end, as_of=as_of)
    via_db = src.rows_duckdb(ids, start=start, end=end, as_of=as_of)
    assert via_http == via_db
    if ids is None and as_of is None and start is None:
        assert len(via_db) == 11  # every Indonesia (series, month), latest version


def test_http_catalog_matches_attach(store):
    src = tic(store, fake_serve(store))
    for country in (INDONESIA, "indonesia", "asia", None):
        assert src.series_http(country) == src.series_duckdb(country)


def test_http_routes(store):
    calls = []
    src = tic(store, fake_serve(store, calls))
    src.rows_http(as_of=date(2026, 9, 18))
    assert calls[0] == f"{URL}/series/tic?country=42218&format=csv"
    assert f"{URL}/series/tic/us_lt_eqty_net_42218?as_of=2026-09-18&format=csv" in calls
    assert len(calls) == 1 + len(IDN)


def test_unknown_series_is_empty_on_both_paths(store):
    src = tic(store, fake_serve(store))
    assert src.rows_http(["NOPE"]) == src.rows_duckdb(["NOPE"]) == []
    assert src.rows_http(country="atlantis") == src.rows_duckdb(country="atlantis") == []


# ---------------- choosing the path ----------------


def test_uses_http_when_serve_answers(store):
    calls = []
    src = tic(store, fake_serve(store, calls))
    rows = src.rows(["us_lt_eqty_net_42218"])
    assert src.usfin.via == "http" and calls
    assert rows == src.rows_duckdb(["us_lt_eqty_net_42218"])
    assert src.series(INDONESIA) == src.series_duckdb(INDONESIA)


def test_falls_back_to_attach_when_serve_is_down(store):
    src = tic(store)
    rows = src.rows(["us_lt_eqty_net_42218"], as_of=date(2026, 9, 17))
    assert src.usfin.via == "duckdb"
    assert rows[-1].value == -700.0
    assert len(src.series()) == 5


def test_down_and_missing_is_unavailable(tmp_path):
    src = tic(tmp_path / "nope.duckdb")
    with pytest.raises(SourceUnavailable) as e:
        src.rows()
    assert e.value.reason == "missing"
    assert read_rows(src) == ([], ["sec-edgar (missing)"])


def test_locked_store_is_unavailable(store):
    with hold_duckdb_lock(store), pytest.raises(SourceUnavailable) as e:
        tic(store).rows()
    assert e.value.reason == "locked"


def test_busy_serve_is_locked_not_a_fallback(store):
    busy = httpx.MockTransport(lambda r: httpx.Response(503, text="busy"))
    with pytest.raises(SourceUnavailable) as e:
        tic(store, busy).rows()
    assert e.value.reason == "locked"
