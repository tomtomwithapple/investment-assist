"""kseistat adapter: KSEI monthly local/foreign ownership of IDX stocks, read-only.

Views and their meaning are in kseistat's README (*Analysis views*); every percentage (0-100) is
of the shares KSEI records for a stock (local + foreign), not of `sec_num`. One date per loaded
month-end file.

- `KSEI.<method>.<metric>` (`market_series`): `v_market_composition`, method `sum` (shares summed
  across stocks, dominated by huge share counts) or `equal_weight` (plain average of each stock's
  percentages); metric `n_stocks`, `total_holdings` or one of the eight `*_pct` columns
  (`foreign_pct`, `local_individual_pct`, ...).
- `KSEI_TYPE.<origin>.<investor_type>.<measure>` (`type_series`): `v_type_composition`, origin
  `local|foreign`, investor type a KSEI code (`ID` individual, `CP`, `IB`, `IS`, `MF`, `PF`, `SC`,
  `FD`, `OT`), measure `shares`, `pct_sum` or `pct_equal_weight`. Asked for by id or all at once
  through `types()`; never in the default `rows()`.

`as_of` is the date kseistat loaded that month (`loads.loaded_at`, a naive local timestamp);
None when the month has no `loads` row. The default `rows()` is every market series. kseistat
swaps a new file into place on load, so a read never blocks it; a store without the views is
`missing`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import duckdb

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, duckdb_ro

__all__ = [
    "FOREIGN_PCT_EQUAL",
    "FOREIGN_PCT_SUM",
    "SOURCE",
    "KseistatSource",
    "market_series",
    "type_series",
]

SOURCE = "kseistat"
MARKET, TYPE = "KSEI.", "KSEI_TYPE."
MARKET_VIEW, TYPE_VIEW = "v_market_composition", "v_type_composition"
METHODS = ("equal_weight", "sum")
GROUPS = ("local", "foreign", "individual", "institution", "local_individual",
          "local_institution", "foreign_individual", "foreign_institution")
METRICS = ("n_stocks", "total_holdings", *(f"{g}_pct" for g in GROUPS))
ORIGINS = ("foreign", "local")
MEASURES = ("pct_equal_weight", "pct_sum", "shares")


def market_series(method: str, metric: str) -> str:
    if method not in METHODS or metric not in METRICS:
        raise ValueError(f"method must be one of {METHODS} and metric one of {METRICS}")
    return f"{MARKET}{method}.{metric}"


def type_series(origin: str, investor_type: str, measure: str) -> str:
    if origin not in ORIGINS or measure not in MEASURES or not investor_type:
        raise ValueError(f"origin must be one of {ORIGINS} and measure one of {MEASURES}")
    return f"{TYPE}{origin}.{investor_type}.{measure}"


FOREIGN_PCT_SUM = market_series("sum", "foreign_pct")
FOREIGN_PCT_EQUAL = market_series("equal_weight", "foreign_pct")
DEFAULT = tuple(market_series(m, x) for m in METHODS for x in METRICS)


def _parse(sid: str) -> tuple[str, ...] | None:
    """('market', method, metric) or ('type', origin, investor_type, measure); None if unknown."""
    if sid.startswith(TYPE):
        parts = tuple(sid.removeprefix(TYPE).split("."))
        if len(parts) == 3 and parts[0] in ORIGINS and parts[1] and parts[2] in MEASURES:
            return ("type", *parts)
    elif sid.startswith(MARKET):
        parts = tuple(sid.removeprefix(MARKET).split("."))
        if len(parts) == 2 and parts[0] in METHODS and parts[1] in METRICS:
            return ("market", *parts)
    return None


def _window(col: str, start: date | None, end: date | None) -> tuple[list[str], list]:
    where, params = [], []
    if start:
        where.append(f"{col} >= ?")
        params.append(start)
    if end:
        where.append(f"{col} <= ?")
        params.append(end)
    return where, params


def _float(v) -> float | None:
    return None if v is None else float(v)


class KseistatSource:
    """kseistat's store as tidy rows, sorted by series and date."""

    name = SOURCE

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> KseistatSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    @contextmanager
    def _connect(self, *needed: str) -> Iterator[tuple[duckdb.DuckDBPyConnection, str]]:
        """A read-only connection, the views in `needed` checked, and the `as_of` join."""
        with duckdb_ro(self.path, self.name) as con:
            names = {n for (n,) in con.execute(
                "select view_name from duckdb_views()"
                " union all select table_name from duckdb_tables()"
            ).fetchall()}
            absent = [v for v in needed if v not in names]
            if absent:
                raise SourceUnavailable(self.name, "missing", f"no {', '.join(absent)} view")
            if "loads" in names:
                yield con, "cast(l.loaded_at as date) from {} v left join loads l using (date)"
            else:
                yield con, "null::date from {} v"

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        ids = DEFAULT if series_ids is None else sorted({s for s in series_ids if _parse(s)})
        kinds = {_parse(s)[0] for s in ids}
        needed = [v for k, v in (("market", MARKET_VIEW), ("type", TYPE_VIEW)) if k in kinds]
        if not ids:
            return []
        with self._connect(*needed) as (con, as_of):
            out = []
            for sid in sorted(ids):
                sql, params = self._sql(sid, as_of, start, end)
                out += [Row(sid, d, _float(v), rec, self.name)
                        for d, v, rec in con.execute(sql, params).fetchall()]
            return out

    def _sql(self, sid: str, as_of: str, start: date | None, end: date | None):
        kind, *key = _parse(sid)
        where, params = _window("v.date", start, end)
        if kind == "market":
            method, metric = key
            sql = f"select v.date, v.{metric}, {as_of.format(MARKET_VIEW)} where v.method = ?"
            params = [method, *params]
        else:
            origin, investor_type, measure = key
            sql = (f"select v.date, v.{measure}, {as_of.format(TYPE_VIEW)}"
                   " where v.origin = ? and v.investor_type = ?")
            params = [origin, investor_type, *params]
        return sql + "".join(f" and {w}" for w in where) + " order by v.date", params

    def types(self, start: date | None = None, end: date | None = None) -> list[Row]:
        """Every origin × investor type × measure from `v_type_composition`."""
        with self._connect(TYPE_VIEW) as (con, as_of):
            where, params = _window("v.date", start, end)
            measures = ", ".join(f"v.{m}" for m in MEASURES)
            sql = (f"select v.origin, v.investor_type, v.date, {measures},"
                   f" {as_of.format(TYPE_VIEW)} where {' and '.join(where) or 'true'}")
            out = []
            for origin, itype, d, *values, rec in con.execute(sql, params).fetchall():
                for measure, v in zip(MEASURES, values, strict=True):
                    out.append(Row(type_series(origin, itype, measure), d, _float(v), rec, SOURCE))
            return sorted(out, key=lambda r: (r.series_id, r.date))
