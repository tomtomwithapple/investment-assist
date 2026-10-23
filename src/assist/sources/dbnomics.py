"""dbnomics adapter: OECD CLI/BCI/CCI/CPI/rates, China `cn.*`, Eurozone `ea.*` (layer 2) and
Damodaran ERP/CRP, Shiller CAPE (layer 3).

`dbn serve` (127.0.0.1:8770) is read first: `/api/series?format=csv` (the catalog),
`/api/series/<id>?format=csv[&from=YYYY-MM-DD]` (one series) and `/api/latest?format=csv`. When it
is down the store is read directly, and only open-query-close: dbnomics' lock is mutual (any open
reader makes the 06:40 `dbn refresh` crash), so no connection outlives one query. A busy server
(503: a refresh holds the lock and that path was never rendered) is `locked`, not a fallback,
since the file would be locked too. Both paths give identical rows
(tests/sources/test_dbnomics.py asserts it).

- Series ids are dbnomics' logical ids (`idn.cli`, `cn.pmi.mfg`, `ea.hicp.yoy`, `us.erp.implied`,
  `idn.erp.hurdle`, `idn.crp`, ...); `date` is the start of the period. 121 series as of
  2026-10-23; the catalog is authoritative.
- Units differ by group, so read `series()["unit"]`: macro series are percent or index points
  (`% p.a.` 3.28 = 3.28%; `cn.cpi`/`cn.ppi` are "same month last year = 100"), valuation series
  and the Damodaran tables are fractions (0.0247 = 2.47%), `shiller.gs10` is percent.
- `Row.as_of` is None: the store keeps no vintage (a fetch replaces a series' whole history) and
  the API does not expose `fetched_at`. Freshness is `stale`/`checked_at` in `series()`.
- `damodaran_erp`, `damodaran_crp` and `shiller` are not served by the API, so those reads always
  go to the store (open-query-close). CRP is a semi-annual snapshot dated at the start of
  Damodaran's update month, published ~6 weeks later: lag it in back-tests.

Contract: ../dbnomics/docs/HANDOFF.md; routes: its src/dbnomics/serve.py.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, http_csv, open_query_close

__all__ = ["DEFAULT_URL", "SOURCE", "DbnomicsSource"]

SOURCE = "dbnomics"
DEFAULT_URL = "http://127.0.0.1:8770"

# serve.py SERIES_SQL and api_latest, so both paths return the same columns in the same order.
SERIES_SQL = (
    "select s.series_id, s.title, s.country, s.freq, s.unit, s.grp, s.chain, s.max_lag_days,"
    " st.source, st.latest_period, st.stale, st.checked_at"
    " from series s left join series_status st using (series_id) order by s.grp, s.series_id"
)
LATEST_SQL = (
    "select l.series_id, s.title, s.country, s.freq, s.unit, s.grp, l.date, l.value,"
    " l.prev_value, l.change, l.source, l.stale"
    " from series_latest l left join series s using (series_id) order by s.grp, l.series_id"
)


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    out = float(value)
    return None if out != out else out  # NaN → None, as the API sends it


def _bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, bool) else value == "True"


def _int(value: Any) -> int | None:
    return None if value is None or value == "" else int(value)


def _date(value: Any) -> date | None:
    if value is None or value == "" or isinstance(value, date):
        return value or None
    return date.fromisoformat(value)


def _datetime(value: Any) -> datetime | None:
    if value is None or value == "" or isinstance(value, datetime):
        return value or None
    return datetime.fromisoformat(value)


def _text(value: Any) -> str | None:
    return None if value is None or value == "" else value


def _catalog(r: dict) -> dict[str, Any]:
    return {
        **{k: _text(r[k]) for k in ("series_id", "title", "country", "freq", "unit", "grp")},
        "chain": json.loads(r["chain"]) if r["chain"] else [],
        "max_lag_days": _int(r["max_lag_days"]),
        "source": _text(r["source"]),
        "latest_period": _text(r["latest_period"]),
        "stale": _bool(r["stale"]),
        "checked_at": _datetime(r["checked_at"]),
    }


def _latest(r: dict) -> dict[str, Any]:
    return {
        **{k: _text(r[k]) for k in ("series_id", "title", "country", "freq", "unit", "grp")},
        "date": _date(r["date"]),
        **{k: _num(r[k]) for k in ("value", "prev_value", "change")},
        "source": _text(r["source"]),
        "stale": _bool(r["stale"]),
    }


def _in_window(d: date, start: date | None, end: date | None) -> bool:
    return (start is None or d >= start) and (end is None or d <= end)


def _window(column: str, start: date | None, end: date | None) -> tuple[list[str], list]:
    where, params = [], []
    if start:
        where.append(f"{column} >= ?")
        params.append(start)
    if end:
        where.append(f"{column} <= ?")
        params.append(end)
    return where, params


class DbnomicsSource:
    """dbnomics as tidy rows, sorted by series and date. `via` records the path the last
    `rows`/`series`/`latest` took (`http` or `duckdb`)."""

    name = SOURCE

    def __init__(
        self,
        url: str | None = DEFAULT_URL,
        path: Path | str | None = None,
        client: httpx.Client | None = None,
    ):
        self.url = url.rstrip("/") if url else None
        self.path = Path(path).expanduser() if path else None
        self.client = client
        self.via: str | None = None

    @classmethod
    def from_config(
        cls, config: Path = DEFAULT_CONFIG, env: dict | None = None, client=None
    ) -> DbnomicsSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(url=src.url, path=src.location, client=client)

    # ---------------- plumbing ----------------

    def _get_csv(self, route: str, params: dict | None = None) -> list[dict[str, str]] | None:
        """GET `route` as CSV; None for a 404 (an id the server does not know)."""
        if self.client is None:
            self.client = httpx.Client()
        try:
            return http_csv(self.client, self.url + route, SOURCE, params)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    def _query(self, sql: str, params: Sequence | None = None) -> list[dict[str, Any]]:
        """Open read-only, run `sql`, close: never hold the file (the lock is mutual)."""
        if self.path is None:
            raise SourceUnavailable(SOURCE, "missing", "no store path configured")
        cols, found = open_query_close(self.path, sql, params, SOURCE)
        return [dict(zip(cols, row, strict=True)) for row in found]

    def _fetch[T](self, http_fn: Callable[[], T], db_fn: Callable[[], T]) -> T:
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
                raise SourceUnavailable(SOURCE, "missing", f"{down}; {e.detail}") from e
            raise
        self.via = "duckdb"
        return out

    # ---------------- catalog and latest ----------------

    def series(self) -> list[dict[str, Any]]:
        """Every series with its unit, group, fallback chain and freshness (`stale`)."""
        return self._fetch(self.series_http, self.series_duckdb)

    def series_http(self) -> list[dict[str, Any]]:
        return [_catalog(r) for r in self._get_csv("/api/series") or []]

    def series_duckdb(self) -> list[dict[str, Any]]:
        return [_catalog(r) for r in self._query(SERIES_SQL)]

    def latest(self) -> list[dict[str, Any]]:
        """One row per series: latest value, the one before and `change` (absolute, in unit)."""
        return self._fetch(self.latest_http, self.latest_duckdb)

    def latest_http(self) -> list[dict[str, Any]]:
        return [_latest(r) for r in self._get_csv("/api/latest") or []]

    def latest_duckdb(self) -> list[dict[str, Any]]:
        return [_latest(r) for r in self._query(LATEST_SQL)]

    # ---------------- observations ----------------

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        """With no `series_ids`, every series in the catalog."""
        args = (series_ids, start, end)
        return self._fetch(lambda: self.rows_http(*args), lambda: self.rows_duckdb(*args))

    def rows_http(self, series_ids=None, start=None, end=None) -> list[Row]:
        if series_ids is None:
            series_ids = [s["series_id"] for s in self.series_http()]
        params = {"from": start.isoformat()} if start else None
        out = []
        for sid in sorted(set(series_ids)):
            for r in self._get_csv(f"/api/series/{sid}", params) or []:
                d = date.fromisoformat(r["date"])
                if _in_window(d, start, end):
                    out.append(Row(sid, d, _num(r["value"]), None, SOURCE))
        return out

    def rows_duckdb(self, series_ids=None, start=None, end=None) -> list[Row]:
        where, params = _window("date", start, end)
        if series_ids is not None:
            ids = sorted(set(series_ids))
            if not ids:
                return []
            where.append(f"series_id in ({', '.join('?' for _ in ids)})")
            params += ids
        sql = "select series_id, date, value from observations"
        if where:
            sql += " where " + " and ".join(where)
        found = self._query(sql + " order by series_id, date", params)
        return [Row(r["series_id"], r["date"], _num(r["value"]), None, SOURCE) for r in found]

    # ---------------- valuation tables (store only) ----------------

    def damodaran_erp(
        self,
        freq: str = "M",
        variant: str = "t12m",
        start: date | None = None,
        end: date | None = None,
    ) -> list[dict[str, Any]]:
        """Damodaran implied ERP (`value`, `tbond` fractions; `sp500` index level), by date.
        The default is the monthly headline, the same values as `us.erp.implied`."""
        where, params = _window("date", start, end)
        where = ["freq = ?", "variant = ?", *where]
        return self._query(
            "select date, freq, variant, value, sp500, tbond from damodaran_erp"
            f" where {' and '.join(where)} order by date",
            [freq, variant, *params],
        )

    def damodaran_crp(
        self, iso3: Sequence[str] | None = None, snapshot: date | None = None
    ) -> list[dict[str, Any]]:
        """Damodaran country risk premiums (fractions) per snapshot, by snapshot and country.
        `total_erp = us_erp_base + crp`, where `us_erp_base` is the mature-market ERP."""
        where, params = [], []
        if iso3 is not None:
            codes = sorted(set(iso3))
            if not codes:
                return []
            where.append(f"iso3 in ({', '.join('?' for _ in codes)})")
            params += codes
        if snapshot:
            where.append("snapshot_date = ?")
            params.append(snapshot)
        sql = "select * from damodaran_crp"
        if where:
            sql += " where " + " and ".join(where)
        return self._query(sql + " order by snapshot_date, country", params)

    def shiller(self, start: date | None = None, end: date | None = None) -> list[dict[str, Any]]:
        """Shiller monthly data (`cape`, `gs10` in percent, `excess_cape_yield` a fraction); the
        last row is `provisional`."""
        where, params = _window("date", start, end)
        sql = "select * from shiller"
        if where:
            sql += " where " + " and ".join(where)
        return self._query(sql + " order by date", params)
