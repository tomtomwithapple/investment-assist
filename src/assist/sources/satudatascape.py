"""satudatascape adapter (stub): the data.go.id catalogue in SQLite, read-only.

satudatascape holds no ready macro series: it crawls the data.go.id catalogue (`packages`,
`resources`) and extracts downloaded files into Parquet tables graded A/B/C (`tables`). Tables
read by the parent are listed in its `docs/PLAN.md` (*Tables read by investment-assist*). Until a
series is picked from those extracts, this adapter gives only:

- `SATUDATA_RUNS.<kind>` rows (`rows()`): one per finished run in `runs` (`crawl`, `download`),
  dated by its finish (UTC date of `finished_at`), value = `count_stored`. Freshness, not data.
- `tables(grades)`: the extracted Parquet tables of the given grades (A and B by default); their
  `path` is as stored, relative to satudatascape's own data directory.

The store is absent on this Mac as of 2026-10-23, so live it raises `SourceUnavailable`
(missing), which callers turn into `stale_inputs`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import NamedTuple

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, sqlite_ro

__all__ = ["RUNS", "SOURCE", "ExtractedTable", "SatudatascapeSource"]

SOURCE = "satudatascape"
RUNS = "SATUDATA_RUNS."


class ExtractedTable(NamedTuple):
    resource_id: str
    path: str
    quality: str
    n_rows: int | None
    n_cols: int | None
    extracted_at: str | None


class SatudatascapeSource:
    """satudatascape's `data/satudata.db`, opened read-only (`mode=ro`)."""

    name = SOURCE

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()

    @classmethod
    def from_config(
        cls, config: Path = DEFAULT_CONFIG, env: dict | None = None
    ) -> SatudatascapeSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        sql = (
            "select kind, substr(finished_at, 1, 10), count_stored from runs"
            " where finished_at is not null order by kind, finished_at"
        )
        with sqlite_ro(self.path, self.name) as con:
            found = con.execute(sql).fetchall()
        out = []
        for kind, day, stored in found:
            sid, d = RUNS + kind, date.fromisoformat(day)
            if series_ids is not None and sid not in series_ids:
                continue
            if (start is None or d >= start) and (end is None or d <= end):
                out.append(Row(sid, d, None if stored is None else float(stored), d, self.name))
        return out

    def last_run(self, kind: str = "crawl") -> date | None:
        """Finish date of the newest finished run of `kind`, or None if it never finished."""
        days = [r.date for r in self.rows([RUNS + kind])]
        return max(days, default=None)

    def tables(self, grades: Sequence[str] = ("A", "B")) -> list[ExtractedTable]:
        marks = ", ".join("?" for _ in grades)
        sql = (
            "select resource_id, path, quality, n_rows, n_cols, extracted_at from tables"
            f" where quality in ({marks}) order by resource_id"
        )
        with sqlite_ro(self.path, self.name) as con:
            return [ExtractedTable(*r) for r in con.execute(sql, list(grades)).fetchall()]
