"""singstat adapter: MAS SORA, SGS and T-bill yields, MAS FX, SingStat macro tables (layer 2, SG
overrides) and SGD FX for IDR conversion, read-only from singstat's `data/sgecon.duckdb`.

Tables per `sgecon.store.SCHEMA`: `series` (series_id, source, title, unit, frequency,
updated_at), `observations` (series_id, date, value, unit, source) and `refresh_log` (source,
started_at, finished_at, status, detail).

- Series ids are singstat's own: `mas:sora`, `mas:sora:comp{1,3,6}m`, `mas:sora:index`,
  `mas:sgs:{2,5,10,15,20,30,50}y`, `mas:tbill:{6m,1y}` (`mas:tbill:3m` ends 2013),
  `mas:fx:<ccy>sgd` (21 currencies) and `singstat:<table>:<seriesNo>` (e.g. `singstat:M213751:1`
  CPI all items). Origins `acra` and `ura` share the tables.
- Rates are `% p.a.` (1.95 = 1.95%). FX is S$ per ONE unit of the foreign currency: singstat
  already divides MAS's per-100 quotes by 100, so `mas:fx:idrsgd` is ~7.2e-05 (4 significant
  figures, ~0.07% resolution). `idr_per_sgd` inverts it for the IDR investor.
- `date` is the observation day (MAS) or the period start (SingStat monthly/quarterly). The store
  keeps one vintage; `Row.as_of` is the day singstat last wrote the series (`series.updated_at`).
- singstat's refresh holds a read-write lock while it writes. Each call ATTACHes the file READ_ONLY
  into a fresh in-memory connection, runs, and closes; a locked store is retried a few times
  before it is reported `locked`.

Path: `$ASSIST_SINGSTAT_DB`, else singstat's own `$SGECON_DB` (relative to the singstat repo),
else `config/sources.yaml`.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, attach_ro

__all__ = [
    "CPI",
    "IDR_PER_SGD",
    "REAL_GDP_YOY",
    "SGS_10Y",
    "SGS_2Y",
    "SORA",
    "SORA_3M",
    "SOURCE",
    "TBILL_6M",
    "USD_SGD",
    "SingstatSource",
    "fx_id",
]

SOURCE = "singstat"
ALIAS = "sgecon"
TABLES = ("series", "observations", "refresh_log")

SORA, SORA_3M = "mas:sora", "mas:sora:comp3m"
SGS_2Y, SGS_10Y = "mas:sgs:2y", "mas:sgs:10y"
TBILL_6M = "mas:tbill:6m"
CPI = "singstat:M213751:1"  # CPI all items, 2024 = 100, monthly
# Real GDP y/y %, quarterly. `singstat:M015631:1` is the NOMINAL (current prices) y/y.
REAL_GDP_YOY = "singstat:M015631:2"
IDR_PER_SGD = "idr_per_sgd"  # derived here: 1 / mas:fx:idrsgd


def fx_id(ccy: str) -> str:
    """singstat's id for S$ per one unit of `ccy` (e.g. `USD` → `mas:fx:usdsgd`)."""
    return f"mas:fx:{ccy.lower()}sgd"


USD_SGD = fx_id("USD")


def _ids(series_ids: Sequence[str], col: str = "series_id") -> tuple[str, list[str]]:
    ids = sorted(set(series_ids))
    return f"{col} in ({', '.join('?' for _ in ids)})", ids


def _where(clauses: list[str]) -> str:
    return " where " + " and ".join(clauses) if clauses else ""


class SingstatSource:
    """singstat's store as tidy rows, sorted by series and date."""

    name = SOURCE

    def __init__(
        self,
        path: Path | str | None,
        retries: int = 3,
        retry_delay: float = 2.0,
        sleep: Callable[[float], Any] = time.sleep,
    ):
        self.path = Path(path).expanduser() if path else None
        self.retries, self.retry_delay, self._sleep = max(1, retries), retry_delay, sleep

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> SingstatSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        location = Path(src.location) if src.location else None
        if not env.get(src.env) and env.get("SGECON_DB"):
            own = Path(env["SGECON_DB"]).expanduser()
            if not own.is_absolute() and location is not None:
                own = location.parents[1] / own  # relative to the singstat repo
            return cls(own)
        return cls(location)

    def _query(self, sql: str, params: Sequence | None = None) -> list[dict[str, Any]]:
        """ATTACH read-only, check the tables, run `sql` (tables unqualified), close. Retries
        while singstat's refresh holds the lock."""
        if self.path is None:
            raise SourceUnavailable(SOURCE, "missing", "no store path configured")
        for attempt in range(1, self.retries + 1):
            try:
                return self._query_once(sql, params)
            except SourceUnavailable as e:
                if e.reason != "locked" or attempt == self.retries:
                    raise
                self._sleep(self.retry_delay)
        raise AssertionError("unreachable")

    def _query_once(self, sql: str, params: Sequence | None) -> list[dict[str, Any]]:
        con = duckdb.connect()
        try:
            attach_ro(con, self.path, ALIAS, SOURCE)
            con.execute(f'use "{ALIAS}"')
            found = {
                r[0]
                for r in con.execute(
                    "select table_name from information_schema.tables where table_catalog = ?",
                    [ALIAS],
                ).fetchall()
            }
            if absent := [t for t in TABLES if t not in found]:
                raise SourceUnavailable(SOURCE, "missing", f"no {', '.join(absent)} in {self.path}")
            cur = con.execute(sql, list(params or []))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        finally:
            con.close()

    # ---------------- observations ----------------

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        """With no `series_ids`, every series (~264k rows live, mostly ACRA: pass ids)."""
        where, params = [], []
        if series_ids is not None:
            if not series_ids:
                return []
            clause, ids = _ids(series_ids, "o.series_id")
            where.append(clause)
            params += ids
        for clause, value in (("o.date >= ?", start), ("o.date <= ?", end)):
            if value is not None:
                where.append(clause)
                params.append(value)
        sql = (
            "select o.series_id, o.date, o.value, s.updated_at from observations o"
            " left join series s using (series_id)"
            + _where(where)
            + " order by o.series_id, o.date"
        )
        return [
            Row(
                r["series_id"],
                r["date"],
                None if r["value"] is None or r["value"] != r["value"] else r["value"],
                r["updated_at"].date() if r["updated_at"] else None,
                SOURCE,
            )
            for r in self._query(sql, params)
        ]

    def idr_per_sgd(self, start: date | None = None, end: date | None = None) -> list[Row]:
        """Rupiah per S$, the inverse of MAS's S$ per rupiah; null cells are dropped."""
        return [
            r._replace(series_id=IDR_PER_SGD, value=1 / r.value)
            for r in self.rows([fx_id("IDR")], start, end)
            if r.value
        ]

    # ---------------- catalog, latest, refresh log ----------------

    def series(self, origin: str | None = None, prefix: str | None = None) -> list[dict]:
        """Every series with its origin (`mas`, `singstat`, `acra`, `ura`), unit, frequency,
        `updated_at` and observed date range."""
        where, params = [], []
        if origin is not None:
            where.append("s.source = ?")
            params.append(origin)
        if prefix is not None:
            where.append("starts_with(s.series_id, ?)")
            params.append(prefix)
        sql = (
            "select s.series_id, s.source, s.title, s.unit, s.frequency, s.updated_at,"
            " min(o.date) as first_date, max(o.date) as last_date, count(o.date) as n_obs"
            " from series s left join observations o using (series_id)"
            + _where(where)
            + " group by all order by s.series_id"
        )
        return self._query(sql, params)

    def latest(
        self, series_ids: Sequence[str] | None = None, as_of: date | None = None
    ) -> list[dict]:
        """The newest non-null observation per series (on or before `as_of`), with its unit,
        title and origin."""
        where, params = ["o.value is not null", "not isnan(o.value)"], []
        if as_of is not None:
            where.append("o.date <= ?")
            params.append(as_of)
        if series_ids is not None:
            if not series_ids:
                return []
            clause, ids = _ids(series_ids, "o.series_id")
            where.append(clause)
            params += ids
        sql = (
            "select o.series_id, o.date, o.value, o.unit, s.title, s.source as origin,"
            " s.frequency, s.updated_at from observations o left join series s using (series_id)"
            + _where(where)
            + " qualify row_number() over (partition by o.series_id order by o.date desc) = 1"
            " order by o.series_id"
        )
        return self._query(sql, params)

    def refresh_log(self) -> list[dict]:
        """singstat's newest refresh per origin, with when it last finished `ok`."""
        return self._query(
            "select source, started_at, finished_at, status, detail,"
            " max(finished_at) filter (where status = 'ok') over (partition by source) as last_ok"
            " from refresh_log"
            " qualify row_number() over (partition by source order by started_at desc) = 1"
            " order by source"
        )
