"""sec-edgar (usfin) FRED adapter: `usfin serve` CSV when it answers, a read-only ATTACH otherwise.

`serve` holds the DuckDB lock, so while it runs the store is read over HTTP
(`/series/fred/<id>?format=csv[&as_of=YYYY-MM-DD]`); when it is down the file is ATTACHed
READ_ONLY. Both paths give identical rows (tests/sources/test_usfin_fred.py asserts it):

- current values from `fred_observation_latest`, point in time from `fred_as_of(DATE)` (a DATE
  means 23:59:59 New York that day, as in sec-edgar);
- `Row.as_of` is the FRED vintage date (`realtime_start`), `value` is None where FRED sent ".";
- every query filters by series in SQL: NFCI (~930k rows) and STLFSI4 (~310k) carry every weekly
  vintage of their whole history.

`Usfin` (choose the path, GET a CSV, ATTACH the store) is shared with the TIC adapter (P15).
Schema: ../sec-edgar/src/usfin/migrations/020_fred.sql, route: its web/series.py `fred_rows`.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import duckdb
import httpx

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, attach_ro, http_csv

__all__ = [
    "DEFAULT_URL",
    "LAYER0_SERIES",
    "NET_LIQUIDITY",
    "NET_LIQUIDITY_INPUTS",
    "SOURCE",
    "FredSource",
    "Usfin",
    "net_liquidity",
]

SOURCE = "sec-edgar"
DEFAULT_URL = "http://127.0.0.1:8660"
ALIAS = "usfin"

# Layer 0 in CLAUDE.md (25 series); config/fred.yaml in sec-edgar holds these plus layer-2 macro.
LAYER0_SERIES = (
    "VIXCLS", "BAMLH0A0HYM2", "T10Y2Y", "WALCL", "M2SL", "DFF", "SOFR", "DGS2", "DGS10",
    "DTWEXBGS", "DFII10", "NFCI", "DCOILBRENTEU",
    "WTREGEN", "RRPONTSYD",  # net liquidity
    "BAMLEMCBPIOAS", "BAMLEMHBHYCRPIOAS",  # EM corporate OAS, from 2023-10-10 only
    "GDPNOW", "WEI",
    "THREEFYTP10", "T5YIE", "T10YIE", "STLFSI4", "USEPUINDXD",
    "CCUSMA02IDM618N",  # IDR per USD, monthly
)  # fmt: skip

NET_LIQUIDITY = "NET_LIQUIDITY"
NET_LIQUIDITY_INPUTS = ("WALCL", "WTREGEN", "RRPONTSYD")


class Usfin:
    """sec-edgar's store seen through `usfin serve` (HTTP CSV) or a read-only ATTACH.

    `fetch(http_fn, db_fn)` tries HTTP and falls back to the file only when the server is down
    (a busy server, 503, is `locked`: the file would be locked too). `via` records the path
    the last fetch took."""

    def __init__(
        self,
        url: str | None = DEFAULT_URL,
        path: Path | str | None = None,
        client: httpx.Client | None = None,
        source: str = SOURCE,
    ):
        self.url = url.rstrip("/") if url else None
        self.path = Path(path).expanduser() if path else None
        self.client = client
        self.source = source
        self.via: str | None = None

    @classmethod
    def from_config(
        cls,
        config: Path = DEFAULT_CONFIG,
        env: dict | None = None,
        client: httpx.Client | None = None,
        name: str = SOURCE,
    ) -> Usfin:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == name)
        return cls(url=src.url, path=src.location, client=client, source=name)

    def get_csv(self, route: str, params: dict | None = None) -> list[dict[str, str]] | None:
        """GET `route` as CSV; None for a 404 (a series the server does not know)."""
        if self.client is None:
            self.client = httpx.Client()
        try:
            return http_csv(self.client, self.url + route, self.source, params)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    @contextmanager
    def attached(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """An in-memory connection with the store ATTACHed READ_ONLY and selected, so the
        store's own macros (fred_as_of → bls_as_of_utc) resolve their tables."""
        if self.path is None:
            raise SourceUnavailable(self.source, "missing", "no store path configured")
        con = duckdb.connect()
        try:
            attach_ro(con, self.path, ALIAS, self.source)
            con.execute(f'use "{ALIAS}"')
            yield con
        finally:
            con.close()

    def fetch[T](self, http_fn: Callable[[], T], db_fn: Callable[[], T]) -> T:
        down = ""
        if self.url:
            try:
                out = http_fn()
                self.via = "http"
                return out
            except SourceUnavailable as e:
                if e.reason != "missing":
                    raise
                down = e.detail
        try:
            out = db_fn()
        except SourceUnavailable as e:
            if down and e.reason == "missing":
                raise SourceUnavailable(self.source, "missing", f"{down}; {e.detail}") from e
            raise
        self.via = "duckdb"
        return out


def _date(text: str) -> date | None:
    return date.fromisoformat(text) if text else None


def _in_window(d: date, start: date | None, end: date | None) -> bool:
    return (start is None or d >= start) and (end is None or d <= end)


class FredSource:
    """FRED series from sec-edgar as tidy rows, sorted by series and date. `as_of` (a date)
    gives the values known that day; None gives the latest version of every date."""

    name = SOURCE

    def __init__(self, usfin: Usfin | None = None):
        self.usfin = usfin or Usfin.from_config()

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
        as_of: date | None = None,
    ) -> list[Row]:
        args = (series_ids, start, end, as_of)
        return self.usfin.fetch(lambda: self.rows_http(*args), lambda: self.rows_duckdb(*args))

    def rows_http(self, series_ids=None, start=None, end=None, as_of=None) -> list[Row]:
        params = {"as_of": as_of.isoformat()} if as_of else None
        out = []
        for sid in sorted(set(LAYER0_SERIES if series_ids is None else series_ids)):
            for r in self.usfin.get_csv(f"/series/fred/{sid}", params) or []:
                d = date.fromisoformat(r["date"])
                if _in_window(d, start, end):
                    value = float(r["value"]) if r["value"] else None
                    out.append(Row(sid, d, value, _date(r["realtime_start"]), self.name))
        return out

    def rows_duckdb(self, series_ids=None, start=None, end=None, as_of=None) -> list[Row]:
        ids = sorted(set(LAYER0_SERIES if series_ids is None else series_ids))
        if not ids:
            return []
        table, params = (
            ("fred_as_of(cast(? as date))", [as_of]) if as_of else ("fred_observation_latest", [])
        )
        where = [f"series_id in ({', '.join('?' for _ in ids)})"]
        params += ids
        if start:
            where.append("date >= ?")
            params.append(start)
        if end:
            where.append("date <= ?")
            params.append(end)
        sql = (
            f"select series_id, date, value, realtime_start from {table}"
            f" where {' and '.join(where)} order by series_id, date"
        )
        with self.usfin.attached() as con:
            found = con.execute(sql, params).fetchall()
        return [
            Row(sid, d, None if v is None else float(v), rs, self.name) for sid, d, v, rs in found
        ]


def net_liquidity(rows: Sequence[Row]) -> list[Row]:
    """WALCL − WTREGEN − RRPONTSYD×1000 in $ millions (RRP is in $ billions), on each WALCL
    date, with the last TGA and RRP values known at or before it. A date without all three is
    skipped, not guessed; `as_of` is the newest vintage of the three."""
    by_id: dict[str, list[Row]] = {k: [] for k in NET_LIQUIDITY_INPUTS}
    for r in rows:
        if r.series_id in by_id and r.value is not None:
            by_id[r.series_id].append(r)
    for v in by_id.values():
        v.sort(key=lambda r: r.date)

    def last(series_id: str, d: date) -> Row | None:
        known = [r for r in by_id[series_id] if r.date <= d]
        return known[-1] if known else None

    out = []
    for walcl in by_id["WALCL"]:
        tga, rrp = last("WTREGEN", walcl.date), last("RRPONTSYD", walcl.date)
        if tga is None or rrp is None:
            continue
        vintages = [r.as_of for r in (walcl, tga, rrp)]
        as_of = None if None in vintages else max(vintages)
        value = walcl.value - tga.value - rrp.value * 1000
        out.append(Row(NET_LIQUIDITY, walcl.date, value, as_of, walcl.source))
    return out
