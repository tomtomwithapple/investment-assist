"""bisfetcher adapter: BIS policy rates and EER (layers 0, 2), credit gap, property prices and
debt-service ratios (layer 2), read-only from `warehouse.duckdb`.

Tables per the `contract` block in ../bisfetcher/PLAN.md: `series`, `observations`, `datasets`,
`fetch_log` and the view `observation_latest`.

- Series ids are the flow plus the BIS series key (`WS_CBPOL.M.ID`, `WS_EER.M.R.B.ID`, ...).
  `date` is the start of the period, `period_end` its last day. There is no daily real EER: the
  IDR REER is monthly only (`WS_EER.M.R.B.ID`); `WS_EER.D.N.B.ID` is the daily nominal.
- Values are as published, in the series' `unit` (`Per cent per year` 5.75 = 5.75%; EER is an
  index, 2020 = 100); `unit_mult` is recorded by bisfetcher, never applied, and not applied here.
- The store keeps the latest vintage only. `Row.as_of` is the date bisfetcher last wrote the value
  (`observations.updated_at`); a point-in-time read (`as_of=`) keeps periods with
  `period_end <= as_of`, as bisfetcher's README says to.
- The DuckDB lock belongs to the open connection: a reader blocks the 07:30 refresh, and a
  refresh blocks readers (`locked`). Every call opens, queries and closes. Its `serve` API answers
  503 while a refresh writes, so it is no fallback and is not read here.

Path: `$ASSIST_BISFETCHER_DB`, else bisfetcher's own `$BISFETCHER_DB`, else `config/sources.yaml`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, duckdb_ro

__all__ = [
    "BI_RATE_D",
    "BI_RATE_M",
    "DATASETS",
    "FED_RATE_M",
    "IDN_CREDIT_GAP",
    "IDN_DSR",
    "IDN_SPP_REAL_YOY",
    "IDR_NEER_D",
    "IDR_REER_M",
    "SOURCE",
    "USD_NEER_M",
    "BisfetcherSource",
]

SOURCE = "bisfetcher"
DATASETS = ("WS_CBPOL", "WS_EER", "WS_CREDIT_GAP", "WS_SPP", "WS_DSR")

# The useful ids in bisfetcher's README.
BI_RATE_M, BI_RATE_D = "WS_CBPOL.M.ID", "WS_CBPOL.D.ID"
FED_RATE_M = "WS_CBPOL.M.US"
IDR_REER_M, IDR_NEER_D = "WS_EER.M.R.B.ID", "WS_EER.D.N.B.ID"
USD_NEER_M = "WS_EER.M.N.B.US"
IDN_CREDIT_GAP = "WS_CREDIT_GAP.Q.ID.P.A.C"  # `.A` ratio, `.B` trend, `.C` gap (actual − trend)
IDN_DSR = "WS_DSR.Q.ID.P"
IDN_SPP_REAL_YOY = "WS_SPP.Q.ID.R.771"

TABLES = ("series", "observations", "datasets", "observation_latest")

SERIES_SQL = (
    "select s.series_id, s.dataset, s.freq, s.ref_area, s.ref_area_name, s.title, s.unit,"
    " s.unit_code, s.unit_mult, s.decimals, s.dims, s.attrs, s.updated_at, s.discontinued_at,"
    " min(o.date) as first_date, max(o.date) as last_date, count(o.date) as n_obs"
    " from series s left join observations o using (series_id)"
)
LATEST_COLS = (
    "series_id, date, period, period_end, value, obs_status, updated_at,"
    " dataset, freq, ref_area, title, unit"
)

JOINED = (
    "(select o.*, s.dataset, s.freq, s.ref_area, s.title, s.unit"
    " from observations o join series s using (series_id))"
)


def _ids(series_ids: Sequence[str]) -> tuple[str, list[str]]:
    ids = sorted(set(series_ids))
    return f"series_id in ({', '.join('?' for _ in ids)})", ids


class BisfetcherSource:
    """bisfetcher's warehouse as tidy rows, sorted by series and date."""

    name = SOURCE

    def __init__(self, path: Path | str | None):
        self.path = Path(path).expanduser() if path else None

    @classmethod
    def from_config(
        cls, config: Path = DEFAULT_CONFIG, env: dict | None = None
    ) -> BisfetcherSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        if not env.get(src.env) and env.get("BISFETCHER_DB"):
            return cls(Path(env["BISFETCHER_DB"]).expanduser().absolute())
        return cls(src.location)

    def _query(self, sql: str, params: Sequence | None = None) -> list[dict[str, Any]]:
        """Open read-only, check the contract tables, run `sql`, close."""
        if self.path is None:
            raise SourceUnavailable(SOURCE, "missing", "no store path configured")
        with duckdb_ro(self.path, SOURCE) as con:
            tables = con.execute("select table_name from information_schema.tables").fetchall()
            found = {r[0] for r in tables}
            if absent := [t for t in TABLES if t not in found]:
                raise SourceUnavailable(SOURCE, "missing", f"no {', '.join(absent)} in {self.path}")
            cur = con.execute(sql, list(params or []))
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
        """With no `series_ids`, every series (1.29M rows live: pass ids). `start`/`end` bound
        `date`; `as_of` keeps only periods that had ended by then."""
        where, params = [], []
        if series_ids is not None:
            if not series_ids:
                return []
            clause, ids = _ids(series_ids)
            where.append(clause)
            params += ids
        for clause, value in (("date >= ?", start), ("date <= ?", end), ("period_end <= ?", as_of)):
            if value is not None:
                where.append(clause)
                params.append(value)
        sql = "select series_id, date, value, updated_at from observations"
        if where:
            sql += " where " + " and ".join(where)
        found = self._query(sql + " order by series_id, date", params)
        return [
            Row(
                r["series_id"],
                r["date"],
                None if r["value"] is None or r["value"] != r["value"] else r["value"],
                r["updated_at"].date() if r["updated_at"] else None,
                SOURCE,
            )
            for r in found
        ]

    # ---------------- catalog, latest, datasets ----------------

    def series(self, dataset: str | None = None, ref_area: str | None = None) -> list[dict]:
        """Every series with its unit, dims, attrs, date range and `discontinued_at`."""
        where, params = [], []
        for col, value in (("s.dataset", dataset), ("s.ref_area", ref_area)):
            if value is not None:
                where.append(f"{col} = ?")
                params.append(value)
        sql = SERIES_SQL + (" where " + " and ".join(where) if where else "")
        sql += " group by all order by s.series_id"
        out = self._query(sql, params)
        for r in out:
            r["dims"] = json.loads(r["dims"]) if r["dims"] else {}
            r["attrs"] = json.loads(r["attrs"]) if r["attrs"] else {}
        return out

    def latest(
        self, series_ids: Sequence[str] | None = None, as_of: date | None = None
    ) -> list[dict]:
        """The newest observation per series (`observation_latest`), or the newest whose period
        had ended by `as_of`."""
        where, params = [], []
        if as_of is not None:
            where.append("period_end <= ?")
            params.append(as_of)
        if series_ids is not None:
            if not series_ids:
                return []
            clause, ids = _ids(series_ids)
            where.append(clause)
            params += ids
        table = "observation_latest" if as_of is None else JOINED
        sql = f"select {LATEST_COLS} from {table}"
        if where:
            sql += " where " + " and ".join(where)
        if as_of is not None:
            sql += " qualify row_number() over (partition by series_id order by date desc) = 1"
        return self._query(sql + " order by series_id", params)

    def datasets(self) -> list[dict]:
        """Each dataset with its version, structure pull time and series count."""
        return self._query(
            "select d.dataset, d.name, d.version, d.structure_pulled_at,"
            " count(s.series_id) as series"
            " from datasets d left join series s using (dataset)"
            " group by all order by d.dataset"
        )
