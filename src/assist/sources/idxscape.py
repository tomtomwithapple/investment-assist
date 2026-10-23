"""idxscape adapter: JISDOR (BI's USD/IDR reference rate) from `fx_rate`, read-only.

`fx_rate` (migration 7, keyed on `(rate_date, pair)`, `rate` DECIMAL(18,2) IDR per USD) is
written per fetched range by idxscape's `jisdor.write_fx_rates`; schema in its
`docs/storage.md`. Rows carry series `JISDOR` (pair `USDIDR`), `as_of` = the WIB date of
`recorded_at` (when idxscape stored the range; BI does not revise JISDOR). Days BI says used
D-1 data are in `carried_forward()`. A store without the table (migration 7 not applied) is
`missing`. P13 extends this file with the IDX foreign flow reads.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import duckdb

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, duckdb_ro

__all__ = ["JISDOR", "SOURCE", "IdxscapeSource"]

SOURCE = "idxscape"
JISDOR = "JISDOR"
PAIRS = {JISDOR: "USDIDR"}


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

    def _query(self, sql: str, params: list) -> list[tuple]:
        with duckdb_ro(self.path, self.name) as con:
            # recorded_at is TIMESTAMPTZ; take its WIB date whatever this Mac's zone is
            con.execute("set TimeZone = 'Asia/Jakarta'")
            try:
                return con.execute(sql, params).fetchall()
            except duckdb.CatalogException as e:
                raise SourceUnavailable(self.name, "missing", "no fx_rate table") from e

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        ids = sorted(PAIRS if series_ids is None else set(series_ids) & PAIRS.keys())
        out = []
        for sid in ids:
            where, params = ["pair = ?"], [PAIRS[sid]]
            if start:
                where.append("rate_date >= ?")
                params.append(start)
            if end:
                where.append("rate_date <= ?")
                params.append(end)
            sql = (
                "select rate_date, rate, cast(recorded_at as date) from fx_rate"
                f" where {' and '.join(where)} order by rate_date"
            )
            out += [Row(sid, d, float(v), rec, self.name) for d, v, rec in self._query(sql, params)]
        return out

    def carried_forward(self, pair: str = PAIRS[JISDOR]) -> set[date]:
        """Days BI says used D-1 data (never inferred from equal rates)."""
        sql = "select rate_date from fx_rate where pair = ? and carried_forward"
        return {d for (d,) in self._query(sql, [pair])}
