"""ausdata adapter: Australian macro (RBA, ABS, AOFM, plus ausdata's derived indicators) for the
AU overrides (layer 2) and AUD FX, read-only from `warehouse.duckdb`.

Tables per ausdata's `store.py` SCHEMA: `observations` (series_id, source, date, value, unit,
frequency, pulled_at), `series_meta` (... extra JSON) and, from ausdata S26, `raw_loads` (source,
dataset, path, loaded_at): which archived raw file each dataset was last loaded from.

- `observations.source` is the publisher: rba, abs, aofm, asic, abr, or `derived` (ausdata's own
  indicators, `DER.*`). Series ids are the publisher's (`FIRMMCRTD`, `FXRIR`) or ausdata's
  (`ABS.<dataflow>.<key>`, `AOFM.*`, `DER.*`).
- Dates: RBA, AOFM and derived rows are dated at period end; ABS rows at period **start** (a
  month or quarter's first day). A derived monthly row for the running month is dated at its
  month end before the month is over. A point-in-time read (`as_of=`) therefore keeps rows whose
  period has ended by then, as ausdata's own brief does (`period_end`).
- `Row.as_of` is the date ausdata pulled the value (`pulled_at`, naive UTC). The store holds the
  latest vintage only.
- `raw_loads` may be absent: a warehouse not refreshed since S26 has none (live on 2026-10-23).
  `loads()` then returns [] and `freshness()` leaves `last_loaded_at` empty.
- The DuckDB lock belongs to the open connection; the weekly refresh (launchd, Wednesdays 10:00)
  holds it while writing. Every call opens, queries and closes, retrying a locked store a few
  times before reporting it `locked`.

Path: `$ASSIST_AUSDATA_DB`, else ausdata's own `$AUSDATA_DB`, else `config/sources.yaml`.
"""

from __future__ import annotations

import calendar
import json
import os
import time
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, duckdb_ro

__all__ = [
    "AGS_2Y",
    "AGS_10Y",
    "AUD_IDR",
    "AUD_IDR_M",
    "AUD_USD",
    "AUD_USD_M",
    "CASH_RATE",
    "CPI_TRIMMED_YY_M",
    "CPI_YY_M",
    "CREDIT_GROWTH_YY",
    "CURVE_10Y_2Y",
    "GDP_YY",
    "NONRES_AGS_PCT",
    "REAL_CASH_RATE",
    "SOURCE",
    "TWI",
    "UNEMPLOYMENT",
    "AusdataSource",
    "period_end",
]

SOURCE = "ausdata"

# The ids ausdata's brief (src/ausdata/config/brief.yaml) reports, plus AUD/IDR.
CASH_RATE = "FIRMMCRTD"  # RBA F1, cash rate target, daily
AGS_2Y, AGS_10Y = "FCMYGBAG2D", "FCMYGBAG10D"  # RBA F2, daily, % p.a.
AUD_USD, AUD_IDR, TWI = "FXRUSD", "FXRIR", "FXRTWI"  # RBA F11.1, A$1 = USD / IDR; TWI May-1970=100
# Daily F11.1 history starts 2023-01-03 (RBA's current file); month-end F11.1 from 2010-01.
AUD_USD_M, AUD_IDR_M = "FXRUSD_M", "FXRIR_M"
CPI_YY_M = "ABS.CPI.3.10001.10.50.M"  # headline CPI % y/y, monthly
CPI_TRIMMED_YY_M = "ABS.CPI.3.999902.20.50.M"  # trimmed mean % y/y, SA, monthly
UNEMPLOYMENT = "ABS.LF.M13.3.1599.20.AUS.M"  # % SA
GDP_YY = "DER.GDP_YY"  # real GDP % y/y, quarterly
REAL_CASH_RATE = "DER.REAL_CASH_RATE"
CURVE_10Y_2Y = "DER.CURVE_10Y_2Y"
CREDIT_GROWTH_YY = "DER.CREDIT_GROWTH_YY"
NONRES_AGS_PCT = "AOFM.FH.AGS.NONRES_PCT"  # non-resident share of AGS on issue, quarterly

TABLES = ("observations", "series_meta")

# ABS rows are dated at period start; the period comes from the id suffix (.M/.Q/.A), else
# `frequency` (annual ABS regional series carry an empty frequency).
_ABS_FREQ = (
    "case when o.series_id like '%.M' or o.frequency = 'Monthly' then 'M'"
    " when o.series_id like '%.Q' or o.frequency = 'Quarterly' then 'Q'"
    " when o.series_id like '%.A' or o.frequency = 'Annual' then 'A' end"
)
PERIOD_END = (
    f"(case when o.source = 'abs' then case {_ABS_FREQ}"
    " when 'M' then last_day(o.date)"
    " when 'Q' then last_day(o.date + interval 2 month)"
    " when 'A' then cast(o.date + interval 1 year - interval 1 day as date)"
    " else o.date end else o.date end)"
)

LATEST_COLS = "series_id, source, date, period_end, value, unit, frequency, pulled_at, title"


def period_end(source: str, frequency: str | None, series_id: str, d: date) -> date:
    """The last day of the period an observation covers (Python twin of `PERIOD_END`)."""
    if source != "abs":
        return d
    freq = frequency or ""
    if series_id.endswith(".M") or freq == "Monthly":
        return d.replace(day=calendar.monthrange(d.year, d.month)[1])
    if series_id.endswith(".Q") or freq == "Quarterly":
        m = d.month + 2
        y, m = d.year + (m - 1) // 12, (m - 1) % 12 + 1
        return date(y, m, calendar.monthrange(y, m)[1])
    if series_id.endswith(".A") or freq == "Annual":
        return d.replace(year=d.year + 1) - timedelta(days=1)
    return d


def _ids(series_ids: Sequence[str]) -> tuple[str, list[str]]:
    ids = sorted(set(series_ids))
    return f"o.series_id in ({', '.join('?' for _ in ids)})", ids


class AusdataSource:
    """ausdata's warehouse as tidy rows, sorted by series and date."""

    name = SOURCE

    def __init__(self, path: Path | str | None, retries: int = 3, retry_delay: float = 2.0):
        self.path = Path(path).expanduser() if path else None
        self.retries, self.retry_delay = max(1, retries), retry_delay

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> AusdataSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        if not env.get(src.env) and env.get("AUSDATA_DB"):
            return cls(Path(env["AUSDATA_DB"]).expanduser().absolute())
        return cls(src.location)

    def _query(self, sql: str, params: Sequence | None = None) -> list[dict[str, Any]]:
        """`_run` with a locked store retried `retries` times, `retry_delay` seconds apart."""
        for attempt in range(self.retries):
            try:
                return self._run(sql, params)
            except SourceUnavailable as e:
                if e.reason != "locked" or attempt == self.retries - 1:
                    raise
                time.sleep(self.retry_delay)
        raise AssertionError("unreachable")

    def _run(self, sql: str, params: Sequence | None) -> list[dict[str, Any]]:
        """Open read-only, check the core tables, run `sql`, close. `{raw_loads}` in `sql` is
        replaced by the table, or by an empty stand-in on a pre-S26 store."""
        if self.path is None:
            raise SourceUnavailable(SOURCE, "missing", "no store path configured")
        with duckdb_ro(self.path, SOURCE) as con:
            tables = con.execute("select table_name from information_schema.tables").fetchall()
            found = {r[0] for r in tables}
            if absent := [t for t in TABLES if t not in found]:
                raise SourceUnavailable(SOURCE, "missing", f"no {', '.join(absent)} in {self.path}")
            raw_loads = (
                "raw_loads"
                if "raw_loads" in found
                else "(select null::text as source, null::text as dataset, null::text as path,"
                " null::timestamp as loaded_at where false)"
            )
            cur = con.execute(sql.replace("{raw_loads}", raw_loads), list(params or []))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    # ---------------- observations ----------------

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
        as_of: date | None = None,
    ) -> list[Row]:
        """With no `series_ids`, every series (~170k rows live: pass ids). `start`/`end` bound
        `date`; `as_of` keeps only periods that had ended by then."""
        where, params = [], []
        if series_ids is not None:
            if not series_ids:
                return []
            clause, ids = _ids(series_ids)
            where.append(clause)
            params += ids
        for clause, value in (
            ("o.date >= ?", start),
            ("o.date <= ?", end),
            (f"{PERIOD_END} <= ?", as_of),
        ):
            if value is not None:
                where.append(clause)
                params.append(value)
        sql = "select o.series_id, o.date, o.value, o.pulled_at from observations o"
        if where:
            sql += " where " + " and ".join(where)
        found = self._query(sql + " order by o.series_id, o.date", params)
        return [
            Row(
                r["series_id"],
                r["date"],
                None if r["value"] is None or r["value"] != r["value"] else r["value"],
                r["pulled_at"].date() if r["pulled_at"] else None,
                SOURCE,
            )
            for r in found
        ]

    # ---------------- catalog, latest, freshness ----------------

    def series(self, source: str | None = None) -> list[dict]:
        """Every series with its publisher, unit, frequency, `extra` and date range."""
        sql = (
            "select m.series_id, m.source, m.title, m.description, m.unit, m.frequency, m.extra,"
            " min(o.date) as first_date, max(o.date) as last_date, count(o.date) as n_obs"
            " from series_meta m left join observations o using (series_id)"
        )
        params = []
        if source is not None:
            sql += " where m.source = ?"
            params.append(source)
        out = self._query(sql + " group by all order by m.series_id", params)
        for r in out:
            r["extra"] = json.loads(r["extra"]) if r["extra"] else {}
        return out

    def latest(
        self, series_ids: Sequence[str] | None = None, as_of: date | None = None
    ) -> list[dict]:
        """The newest non-null observation per series, or the newest whose period had ended by
        `as_of`, with its `period_end`, unit and `pulled_at`."""
        where, params = ["o.value is not null", "not isnan(o.value)"], []
        if series_ids is not None:
            if not series_ids:
                return []
            clause, ids = _ids(series_ids)
            where.append(clause)
            params += ids
        if as_of is not None:
            where.append(f"{PERIOD_END} <= ?")
            params.append(as_of)
        sql = (
            f"select {LATEST_COLS} from (select o.*, {PERIOD_END} as period_end, m.title"
            " from observations o left join series_meta m using (series_id)"
            f" where {' and '.join(where)}"
            " qualify row_number() over (partition by o.series_id order by o.date desc) = 1)"
        )
        return self._query(sql + " order by series_id", params)

    def loads(self) -> list[dict]:
        """`raw_loads` (ausdata S26): the archived raw file each dataset was last loaded from.
        Empty on a store not yet refreshed since S26."""
        return self._query(
            "select source, dataset, path, loaded_at from {raw_loads} order by source, dataset"
        )

    def freshness(self) -> list[dict]:
        """Per publisher: series and observation counts, date range, newest `pulled_at`, and the
        newest `raw_loads.loaded_at` (None for `derived`, or before S26)."""
        return self._query(
            "select o.source, count(distinct o.series_id) as series, count(*) as observations,"
            " min(o.date) as first_date, max(o.date) as last_date,"
            " max(o.pulled_at) as last_pulled_at, any_value(l.loaded_at) as last_loaded_at"
            " from observations o left join"
            " (select source, max(loaded_at) as loaded_at from {raw_loads} group by source) l"
            " using (source) group by o.source order by o.source"
        )
