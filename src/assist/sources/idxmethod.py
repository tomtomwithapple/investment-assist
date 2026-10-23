"""idx-method adapter, index series only: `data/*_daily.csv` and `data/*_weekly.csv` (files).

idx-method stopped updating these on 2026-10-19 (README, *Changes the parent must follow*):
they stay committed but frozen at their last pull (2026-09-30 daily, 2026-09-25 weekly). Every
row's `as_of` is its file's real last date, so a stance built on them names the staleness.
JCI (IHSG, `jkse_daily.csv`) is read through `jci()` only, so a future JCI fetcher swaps in
there. Stock-level reads (stockbiter.db, cache/) are P19's, not this file's.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, Source, SourceUnavailable

__all__ = ["JCI", "SERIES", "SOURCE", "IdxMethodIndexSource", "jci"]

SOURCE = "idx-method"
JCI = "JKSE"

# series id → (file under the repo root, value column). `_TR` is the total-return index.
SERIES: dict[str, tuple[str, str]] = {
    JCI: ("data/jkse_daily.csv", "close"),
    "LQ45": ("data/lq45_daily.csv", "close"),
    "LQ45_TR": ("data/lq45_tr_daily.csv", "total_return"),
    "XIHD": ("data/xihd_daily.csv", "close"),
    "DBX": ("data/dbx_weekly.csv", "price"),
    "MBX": ("data/mbx_weekly.csv", "price"),
    "IDX30": ("data/idx30_weekly.csv", "price"),
    "IDX80": ("data/idx80_weekly.csv", "price"),
    "IDX80_TR": ("data/idx80_weekly.csv", "total_return"),
    "IDXG30": ("data/idxg30_weekly.csv", "price"),
    "IDXV30": ("data/idxv30_weekly.csv", "price"),
    "INVESTOR33": ("data/investor33_weekly.csv", "price"),
    "INVESTOR33_TR": ("data/investor33_weekly.csv", "total_return"),
    "KOMPAS100": ("data/kompas100_weekly.csv", "price"),
    "KOMPAS100_TR": ("data/kompas100_weekly.csv", "total_return"),
}


class IdxMethodIndexSource:
    """idx-method's index CSVs as tidy rows, sorted by series and date. With no `series_ids`,
    every series whose file exists; a named series whose file is gone is `missing`."""

    name = SOURCE

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()

    @classmethod
    def from_config(
        cls, config: Path = DEFAULT_CONFIG, env: dict | None = None
    ) -> IdxMethodIndexSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        if not self.root.is_dir():
            raise SourceUnavailable(self.name, "missing", f"no directory at {self.root}")
        if series_ids is None:
            ids = sorted(s for s, (f, _) in SERIES.items() if (self.root / f).is_file())
        else:
            ids = sorted(set(series_ids))
            unknown = [s for s in ids if s not in SERIES]
            if unknown:
                raise KeyError(f"unknown idx-method index series: {unknown}")
        files: dict[str, list[dict[str, str]]] = {}
        out = []
        for sid in ids:
            file, column = SERIES[sid]
            if file not in files:
                files[file] = self._read(file)
            recs = files[file]
            last = max(date.fromisoformat(r["date"]) for r in recs) if recs else None
            for r in recs:
                d = date.fromisoformat(r["date"])
                if (start is None or d >= start) and (end is None or d <= end):
                    value = float(r[column]) if r[column] else None
                    out.append(Row(sid, d, value, last, self.name))
        return sorted(out, key=lambda r: (r.series_id, r.date))

    def _read(self, file: str) -> list[dict[str, str]]:
        path = self.root / file
        if not path.is_file():
            raise SourceUnavailable(self.name, "missing", f"no file at {path}")
        with path.open(newline="") as f:
            return list(csv.DictReader(f))


def jci(
    start: date | None = None, end: date | None = None, source: Source | None = None
) -> list[Row]:
    """JCI (IHSG) daily close. The one place JCI is read: point it at a new fetcher here."""
    return (source or IdxMethodIndexSource.from_config()).rows([JCI], start, end)
