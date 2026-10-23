"""bps-looker adapter: BPS CPI, GDP and trade for Indonesia (layer 2), read-only from Postgres.

bps-looker crawls the BPS WebAPI into Postgres (schema in its Alembic migrations, checked
read-only 2026-10-23). The store is read through DuckDB's postgres extension (`postgres_ro`), so
the SQL here is DuckDB SQL; tests run it unchanged against a DuckDB file with the same tables.

National series come from `observation` (BPS dynamic tables, domain `0000`), one cell per
(var_id, vervar, turvar, th, turth): `vervar` is the row (9999 = INDONESIA, 99003 = GDP),
`turvar` the derived measure, `th` a year id (`period.label`) and `turth` the sub-period
(1-12 months, 31-34 quarters; 13 and 35 are annual and skipped). A month dates to its first
day, a quarter to its first month. `as_of` = BPS's `last_update` date for the variable, or the
WIB date of `fetched_at` when BPS gives none.

- `BPS_CPI_YOY`, `BPS_CPI_MOM`: inflation y/y and m/m, % (vars 2263, 2262; 2022=100, from 2024).
- `BPS_GDP_YOY`, `BPS_GDP_QOQ`: real GDP growth y/y and q/q, % (var 104, 2010 series).
- `BPS_EXPORTS_USD_MN`, `BPS_IMPORTS_USD_MN`, `BPS_TRADE_BALANCE_USD_MN`: monthly trade,
  USD mn (vars 196, 497, 498).
- `BPS_TRADE.<export|import>.<hs2>` (`trade_series`): monthly trade by HS chapter from
  `trade_flow` (summed over ports and countries), USD mn, e.g. 27 coal, 15 CPO, 75 nickel.
  `as_of` = the WIB date of the newest `fetched_at` in the month. Asked for by id only.

A store with none of the tables (or a series' table absent) is `missing`; Postgres down is
`missing` as well (`postgres_ro`).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import NamedTuple

import duckdb

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, duckdb_ro, postgres_ro

__all__ = [
    "CPI_MOM",
    "CPI_YOY",
    "DEFAULT",
    "EXPORTS",
    "GDP_QOQ",
    "GDP_YOY",
    "IMPORTS",
    "SOURCE",
    "TRADE_BALANCE",
    "BpsLookerSource",
    "trade_series",
]

SOURCE = "bps-looker"
NATIONAL = "0000"
INDONESIA = 9999
GDP_ROW = 99003


class Cell(NamedTuple):
    """Where a national series lives in `observation`; `freq` is M (turth 1-12) or Q (31-34)."""

    var_id: int
    vervar: int
    turvar: int
    freq: str


CPI_YOY = "BPS_CPI_YOY"
CPI_MOM = "BPS_CPI_MOM"
GDP_YOY = "BPS_GDP_YOY"
GDP_QOQ = "BPS_GDP_QOQ"
EXPORTS = "BPS_EXPORTS_USD_MN"
IMPORTS = "BPS_IMPORTS_USD_MN"
TRADE_BALANCE = "BPS_TRADE_BALANCE_USD_MN"

SERIES = {
    CPI_YOY: Cell(2263, INDONESIA, 0, "M"),
    CPI_MOM: Cell(2262, INDONESIA, 0, "M"),
    GDP_YOY: Cell(104, GDP_ROW, 5, "Q"),
    GDP_QOQ: Cell(104, GDP_ROW, 4, "Q"),
    EXPORTS: Cell(196, INDONESIA, 0, "M"),
    IMPORTS: Cell(497, INDONESIA, 0, "M"),
    TRADE_BALANCE: Cell(498, INDONESIA, 0, "M"),
}
DEFAULT = tuple(SERIES)
TURTH = {"M": (1, 12), "Q": (31, 34)}

TRADE = "BPS_TRADE."
FLOWS = {"export": 1, "import": 2}
_TRADE_ID = re.compile(r"^BPS_TRADE\.(export|import)\.(\d{2})$")


def trade_series(flow: str, hs2: str) -> str:
    return f"{TRADE}{flow}.{hs2}"


def _period(year_label: str, turth: int, freq: str) -> date | None:
    if not year_label.isdigit():
        return None
    month = turth if freq == "M" else (turth - 31) * 3 + 1
    return date(int(year_label), month, 1)


def _in(d: date, start: date | None, end: date | None) -> bool:
    return (start is None or d >= start) and (end is None or d <= end)


def _float(v) -> float | None:
    return None if v is None else float(v)


_OBS_SQL = (
    "select p.label, o.turth, o.value, cast(o.last_update as date), cast(o.fetched_at as date)"
    " from observation o join period p"
    " on p.domain_id = o.domain_id and p.var_id = o.var_id and p.th_id = o.th"
    " where o.domain_id = ? and o.var_id = ? and o.vervar = ? and o.turvar = ?"
    " and o.turth between ? and ?"
)
_TRADE_SQL = (
    "select year, month, sum(value_usd), cast(max(fetched_at) as date) from trade_flow"
    " where flow = ? and period_type = 1 and hs2 = ? and month between 1 and 12"
    " group by year, month"
)


class BpsLookerSource:
    """bps-looker's Postgres (or a DuckDB file with the same tables) as tidy rows."""

    name = SOURCE

    def __init__(self, dsn: str | None = None, *, path: Path | str | None = None):
        if (dsn is None) == (path is None):
            raise ValueError("give a Postgres dsn or a DuckDB path, not both")
        self.dsn = dsn
        self.path = Path(path).expanduser() if path is not None else None

    @classmethod
    def from_duckdb(cls, path: Path | str) -> BpsLookerSource:
        """A DuckDB file holding the same tables (test fixtures, a local dump)."""
        return cls(path=path)

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> BpsLookerSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.dsn)

    @contextmanager
    def _connect(self) -> Iterator[tuple[duckdb.DuckDBPyConnection, set[str]]]:
        opened = postgres_ro(self.dsn, self.name) if self.dsn else duckdb_ro(self.path, self.name)
        with opened as con:
            # fetched_at is TIMESTAMPTZ; take the WIB date whatever this Mac's zone
            con.execute("set TimeZone = 'Asia/Jakarta'")
            names = con.execute(
                "select table_name from information_schema.tables"
                " where table_catalog = current_database()"
            ).fetchall()
            yield con, {t for (t,) in names}

    def _need(self, tables: set[str], *needed: str) -> None:
        absent = [t for t in needed if t not in tables]
        if absent:
            raise SourceUnavailable(self.name, "missing", f"no {', '.join(absent)} table")

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        ids = DEFAULT if series_ids is None else sorted(
            {s for s in series_ids if s in SERIES or _TRADE_ID.match(s)}
        )
        with self._connect() as (con, tables):
            out = []
            for sid in sorted(ids):
                if sid in SERIES:
                    self._need(tables, "observation", "period")
                    out += self._observation(con, sid, start, end)
                else:
                    self._need(tables, "trade_flow")
                    out += self._trade(con, sid, start, end)
            return out

    def _observation(self, con, sid: str, start: date | None, end: date | None) -> list[Row]:
        cell = SERIES[sid]
        params = [NATIONAL, cell.var_id, cell.vervar, cell.turvar, *TURTH[cell.freq]]
        out = []
        for label, turth, value, updated, fetched in con.execute(_OBS_SQL, params).fetchall():
            d = _period(label, turth, cell.freq)
            if d and _in(d, start, end):
                out.append(Row(sid, d, _float(value), updated or fetched, self.name))
        return sorted(out, key=lambda r: r.date)

    def _trade(self, con, sid: str, start: date | None, end: date | None) -> list[Row]:
        flow, hs2 = _TRADE_ID.match(sid).groups()
        out = []
        for year, month, usd, fetched in con.execute(_TRADE_SQL, [FLOWS[flow], hs2]).fetchall():
            d = date(int(year), int(month), 1)
            if _in(d, start, end):
                value = None if usd is None else float(usd) / 1e6
                out.append(Row(sid, d, value, fetched, self.name))
        return sorted(out, key=lambda r: r.date)
