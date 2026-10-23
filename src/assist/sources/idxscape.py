"""idxscape adapter: JISDOR, IDX foreign flow, broker summary and DJPPR SBN ownership, read-only.

Tables and keys are in idxscape's `docs/storage.md`; the flow semantics follow its own J8 macro
overlay (`idxscape.queries.macro_overlay`), so both repos show the same numbers.

- `JISDOR`: BI's USD/IDR reference rate from `fx_rate` (migration 7, `rate` DECIMAL(18,2) IDR
  per USD, pair `USDIDR`). `as_of` = the WIB date of `recorded_at` (BI does not revise JISDOR).
  Days BI says used D-1 data are in `carried_forward()`.
- `IDX_NET_FOREIGN_IDR`: the day's market sum of `stock_summary.net_foreign_value_est_idr`, an
  estimate (net foreign shares x close; IDX publishes no foreign IDR value). `as_of` = the WIB
  date of `trading_day.recorded_at`.
- `IDX_NET_FOREIGN_USD`: that sum / the same day's JISDOR. A day without a JISDOR rate is a gap
  (value None, listed by `jisdor_gaps()`), never filled from another day.
- `SBN.<instrument>.<investor_type>` (`sbn_series`): DJPPR holdings of tradable rupiah SBN in
  IDR from `sbn_ownership` (migration 8); instrument `SUN|SBSN|TOTAL`, investor type a DJPPR slug
  (`non_resident`, `total`, `bank`, ...). `as_of` = the WIB date its file was fetched
  (`sbn_ownership_file.fetched_at`, the vintage; a later file may revise a day).
- `BROKER_VALUE_IDR.<code>`: per-broker daily value traded from `broker_summary` (migration 4;
  buy and sell combined, no split). No fetch time is stored, so `as_of` is None. Asked for by id
  or all at once through `brokers()`; never in the default `rows()`.

The default `rows()` is every default series whose tables exist. A series asked for by id whose
table is absent (migration not applied) is `missing`, as is a store with none of the tables.
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
    "BROKER_VALUE",
    "IDX_NET_FOREIGN_IDR",
    "IDX_NET_FOREIGN_USD",
    "JISDOR",
    "SBN_NON_RESIDENT",
    "SBN_TOTAL",
    "SOURCE",
    "IdxscapeSource",
    "sbn_series",
]

SOURCE = "idxscape"
JISDOR = "JISDOR"
PAIRS = {JISDOR: "USDIDR"}
IDX_NET_FOREIGN_IDR = "IDX_NET_FOREIGN_IDR"
IDX_NET_FOREIGN_USD = "IDX_NET_FOREIGN_USD"
BROKER_VALUE = "BROKER_VALUE_IDR."
SBN_INSTRUMENTS = ("SUN", "SBSN", "TOTAL")


def sbn_series(instrument: str, investor_type: str) -> str:
    return f"SBN.{instrument}.{investor_type}"


SBN_NON_RESIDENT = sbn_series("TOTAL", "non_resident")
SBN_TOTAL = sbn_series("TOTAL", "total")
DEFAULT = (JISDOR, IDX_NET_FOREIGN_IDR, IDX_NET_FOREIGN_USD, SBN_NON_RESIDENT, SBN_TOTAL)

# The day's market net foreign (IDR est.) with its WIB record date; `{td}` is the as_of source.
_IDR_SQL = (
    "select s.trade_date as day, sum(s.net_foreign_value_est_idr) as net, {td} as rec"
    " from stock_summary s{join} where {where} group by s.trade_date"
)


def _kind(sid: str) -> str | None:
    if sid == JISDOR:
        return "jisdor"
    if sid == IDX_NET_FOREIGN_IDR:
        return "idr"
    if sid == IDX_NET_FOREIGN_USD:
        return "usd"
    if sid.startswith(BROKER_VALUE) and len(sid) > len(BROKER_VALUE):
        return "broker"
    parts = sid.split(".")
    if len(parts) == 3 and parts[0] == "SBN" and parts[1] in SBN_INSTRUMENTS and parts[2]:
        return "sbn"
    return None


TABLES = {
    "jisdor": ("fx_rate",),
    "idr": ("stock_summary",),
    "usd": ("stock_summary", "fx_rate"),
    "sbn": ("sbn_ownership",),
    "broker": ("broker_summary",),
}


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


class IdxscapeSource:
    """idxscape's store as tidy rows, sorted by series and date."""

    name = SOURCE

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> IdxscapeSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    @contextmanager
    def _connect(self) -> Iterator[tuple[duckdb.DuckDBPyConnection, set[str]]]:
        with duckdb_ro(self.path, self.name) as con:
            # recorded_at/fetched_at are TIMESTAMPTZ; take the WIB date whatever this Mac's zone
            con.execute("set TimeZone = 'Asia/Jakarta'")
            names = con.execute("select table_name from duckdb_tables()").fetchall()
            tables = {t for (t,) in names}
            yield con, tables

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
        with self._connect() as (con, tables):
            if series_ids is None:
                ids = [s for s in DEFAULT if set(TABLES[_kind(s)]) <= tables]
                if not ids:
                    self._need(tables, "fx_rate", "stock_summary", "sbn_ownership")
            else:
                ids = [s for s in set(series_ids) if _kind(s)]
                for sid in ids:
                    self._need(tables, *TABLES[_kind(sid)])
            out = []
            for sid in sorted(ids):
                sql, params = self._sql(sid, start, end, tables)
                out += [Row(sid, d, _float(v), rec, self.name)
                        for d, v, rec in con.execute(sql, params).fetchall()]
            return out

    def _sql(self, sid: str, start: date | None, end: date | None, tables: set[str]):
        kind = _kind(sid)
        if kind == "jisdor":
            where, params = _window("rate_date", start, end)
            return (
                "select rate_date, rate, cast(recorded_at as date) from fx_rate"
                f" where {' and '.join(['pair = ?', *where])} order by rate_date",
                [PAIRS[sid], *params],
            )
        if kind in ("idr", "usd"):
            where, params = _window("s.trade_date", start, end)
            has_td = "trading_day" in tables
            idr = _IDR_SQL.format(
                td="cast(any_value(t.recorded_at) as date)" if has_td else "null::date",
                join=" left join trading_day t using (trade_date)" if has_td else "",
                where=" and ".join(where) or "true",
            )
            if kind == "idr":
                return f"select day, net, rec from ({idr}) order by day", params
            return (
                f"with idx as ({idr}) select idx.day,"
                " cast(idx.net as double) / cast(f.rate as double),"
                " greatest(idx.rec, cast(f.recorded_at as date))"
                " from idx left join fx_rate f on f.rate_date = idx.day and f.pair = ?"
                " order by idx.day",
                [*params, PAIRS[JISDOR]],
            )
        if kind == "sbn":
            _, instrument, investor = sid.split(".")
            where, params = _window("o.as_of", start, end)
            has_file = "sbn_ownership_file" in tables
            vintage = "cast(f.fetched_at as date)" if has_file else "null::date"
            join = " left join sbn_ownership_file f on f.sha256 = o.artifact_sha256"
            return (
                f"select o.as_of, o.amount_idr, {vintage} from sbn_ownership o"
                + (join if has_file else "")
                + f" where {' and '.join(['o.instrument = ?', 'o.investor_type = ?', *where])}"
                " order by o.as_of",
                [instrument, investor, *params],
            )
        where, params = _window("trade_date", start, end)
        return (
            "select trade_date, value_idr, null::date from broker_summary"
            f" where {' and '.join(['broker_code = ?', *where])} order by trade_date",
            [sid.removeprefix(BROKER_VALUE), *params],
        )

    def brokers(self, start: date | None = None, end: date | None = None) -> list[Row]:
        """Every broker's daily value traded as `BROKER_VALUE_IDR.<code>` rows."""
        with self._connect() as (con, tables):
            self._need(tables, "broker_summary")
            where, params = _window("trade_date", start, end)
            sql = (
                "select broker_code, trade_date, value_idr from broker_summary"
                f" where {' and '.join(where) or 'true'} order by broker_code, trade_date"
            )
            return [Row(BROKER_VALUE + code, d, float(v), None, self.name)
                    for code, d, v in con.execute(sql, params).fetchall()]

    def _days(self, needed: tuple[str, ...], sql: str, params: list) -> set[date]:
        with self._connect() as (con, tables):
            self._need(tables, *needed)
            return {d for (d,) in con.execute(sql, params).fetchall()}

    def carried_forward(self, pair: str = PAIRS[JISDOR]) -> set[date]:
        """Days BI says used D-1 data (never inferred from equal rates)."""
        sql = "select rate_date from fx_rate where pair = ? and carried_forward"
        return self._days(TABLES["jisdor"], sql, [pair])

    def jisdor_gaps(self) -> set[date]:
        """IDX trading days with no JISDOR rate (their USD flow is None, not filled)."""
        sql = (
            "select distinct trade_date from stock_summary where trade_date not in"
            " (select rate_date from fx_rate where pair = ?)"
        )
        return self._days(TABLES["usd"], sql, [PAIRS[JISDOR]])
