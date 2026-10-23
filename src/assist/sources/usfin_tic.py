"""sec-edgar (usfin) TIC adapter: cross-border securities flows by country (layer 3).

Read through `Usfin` (usfin.py): `usfin serve` CSV when it answers, a read-only ATTACH otherwise;
both paths give identical rows (tests/sources/test_usfin_tic.py asserts it).

- The catalog is `/series/tic?country=…&format=csv` (one row per series with its newest month
  and value; `country` is a code or a case-insensitive name substring, as in sec-edgar), and a
  series is `/series/tic/<id>?format=csv[&as_of=YYYY-MM-DD]`. The ATTACH path reads
  `tic_series`, `tic_observation_latest` and `tic_as_of(DATE)` (a DATE means 23:59:59 New York).
- Series ids are `<measure>_<kind>_<country code>`: `for_*` are foreign holdings (`pos`), net
  purchases (`net`) and valuation changes (`valchg`) of US securities, `us_*` the same for US
  investors in foreign bonds and equities, e.g. `us_lt_eqty_net_42218` (US net purchases of
  Indonesian equities). Monthly, dated the 1st, $ millions; "n.a." is None.
- TIC has no vintage date: `Row.as_of` is the date (UTC) sec-edgar first saw that value.

The default selection is every series of Indonesia (`42218`). Schema:
../sec-edgar/src/usfin/migrations/021_tic.sql, routes: its web/series.py `tic_list`, `tic_rows`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from assist.sources.base import Row
from assist.sources.usfin import SOURCE, Usfin

__all__ = ["CATALOG_COLUMNS", "INDONESIA", "TicSource"]

INDONESIA = "42218"
CATALOG_COLUMNS = (
    "series_id", "title", "measure", "kind", "country_code", "country", "active", "last", "value",
)  # fmt: skip


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _in_window(d: date, start: date | None, end: date | None) -> bool:
    return (start is None or d >= start) and (end is None or d <= end)


def _country_where(country: str | None) -> tuple[str, list]:
    """sec-edgar's filter: the code, or a case-insensitive substring of the name."""
    if not country:
        return "true", []
    return "(s.country_code = ? or lower(s.country) like ?)", [country, f"%{country.lower()}%"]


class TicSource:
    """TIC series from sec-edgar as tidy rows, sorted by series and month. With no `series_ids`
    every series of `country` is read (None: all ~4 260); `as_of` (a date) gives the values known
    that day, None the latest version of every month."""

    name = SOURCE

    def __init__(self, usfin: Usfin | None = None):
        self.usfin = usfin or Usfin.from_config()

    # ---------------- catalog ----------------

    def series(self, country: str | None = INDONESIA) -> list[dict[str, Any]]:
        return self.usfin.fetch(
            lambda: self.series_http(country), lambda: self.series_duckdb(country)
        )

    def series_http(self, country: str | None = INDONESIA) -> list[dict[str, Any]]:
        params = {"country": country} if country else None
        out = []
        for r in self.usfin.get_csv("/series/tic", params) or []:
            out.append(
                {
                    **{k: r[k] for k in CATALOG_COLUMNS[:6]},
                    "country": r["country"] or None,
                    "active": r["active"] == "True",
                    "last": date.fromisoformat(r["last"]) if r["last"] else None,
                    "value": _num(r["value"]),
                }
            )
        return out

    def series_duckdb(self, country: str | None = INDONESIA) -> list[dict[str, Any]]:
        where, params = _country_where(country)
        sql = (
            "select s.series_id, s.title, s.measure, s.kind, s.country_code, s.country, s.active,"
            " l.date, l.value from tic_series s left join ("
            "   select series_id, date, value from tic_observation_latest"
            "   qualify row_number() over (partition by series_id order by date desc) = 1"
            f" ) l using (series_id) where {where} order by s.country_code, s.measure, s.kind"
        )
        with self.usfin.attached() as con:
            found = con.execute(sql, params).fetchall()
        out = []
        for row in found:
            d = dict(zip(CATALOG_COLUMNS, row, strict=True))
            d["value"] = _num(d["value"])
            out.append(d)
        return out

    # ---------------- observations ----------------

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
        as_of: date | None = None,
        country: str | None = INDONESIA,
    ) -> list[Row]:
        args = (series_ids, start, end, as_of, country)
        return self.usfin.fetch(lambda: self.rows_http(*args), lambda: self.rows_duckdb(*args))

    def rows_http(
        self, series_ids=None, start=None, end=None, as_of=None, country=INDONESIA
    ) -> list[Row]:
        if series_ids is None:
            series_ids = [s["series_id"] for s in self.series_http(country)]
        params = {"as_of": as_of.isoformat()} if as_of else None
        out = []
        for sid in sorted(set(series_ids)):
            for r in self.usfin.get_csv(f"/series/tic/{sid}", params) or []:
                d = date.fromisoformat(r["date"])
                if _in_window(d, start, end):
                    seen = datetime.strptime(r["first_seen_at"], "%Y-%m-%d %H:%M:%SZ").date()
                    out.append(Row(sid, d, _num(r["value"]), seen, self.name))
        return out

    def rows_duckdb(
        self, series_ids=None, start=None, end=None, as_of=None, country=INDONESIA
    ) -> list[Row]:
        table, params = (
            ("tic_as_of(cast(? as date))", [as_of]) if as_of else ("tic_observation_latest", [])
        )
        if series_ids is None:
            cwhere, cparams = _country_where(country)
            where = [f"series_id in (select series_id from tic_series s where {cwhere})"]
            params += cparams
        else:
            ids = sorted(set(series_ids))
            if not ids:
                return []
            where = [f"series_id in ({', '.join('?' for _ in ids)})"]
            params += ids
        if start:
            where.append("date >= ?")
            params.append(start)
        if end:
            where.append("date <= ?")
            params.append(end)
        sql = (
            f"select series_id, date, value, first_seen_at from {table}"
            f" where {' and '.join(where)} order by series_id, date"
        )
        with self.usfin.attached() as con:
            found = con.execute(sql, params).fetchall()
        return [Row(sid, d, _num(v), seen.date(), self.name) for sid, d, v, seen in found]
