"""idx-method adapter, index series only: `data/*_daily.csv` and `data/*_weekly.csv` (files).

idx-method stopped updating these on 2026-10-19 (README, *Changes the parent must follow*):
they stay committed but frozen at their last pull (2026-09-30 daily, 2026-09-25 weekly). Every
row's `as_of` is its file's real last date, so a stance built on them names the staleness.
Stock-level reads (stockbiter.db, cache/) are P19's, not this file's.

JCI (IHSG) is read through `jci()` / `JciSource` only (gap 2b, closed by P51-jci-idxscape):
idxscape's `index_daily` COMPOSITE (2021-10-01 on, nightly) wherever it has rows, and idx-method's
`jkse_daily.csv` (1996 on, frozen) only for days before idxscape's first close. The two agree
within 0.01 up to 2026-09-30 (idxscape slice K1), so the seam has no break. Every row keeps the
series id `JKSE` and names its own source.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, Source, SourceUnavailable

__all__ = ["JCI", "SERIES", "SOURCE", "IdxMethodIndexSource", "JciSource", "jci"]

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
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


class JciSource:
    """JCI as one series: idxscape COMPOSITE where it has rows, idx-method's frozen CSV before
    idxscape's first close. A source that is missing or locked drops out and the other carries
    on; only both gone raises (idxscape's error). Any series other than `JKSE` is ignored."""

    name = "idxscape+idx-method"

    def __init__(self, idxscape: Source, idxmethod: Source):
        self.idxscape, self.idxmethod = idxscape, idxmethod

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> JciSource:
        from assist.sources.idxscape import IdxscapeSource

        return cls(IdxscapeSource.from_config(config, env),
                   IdxMethodIndexSource.from_config(config, env))

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        from assist.sources.idxscape import COMPOSITE

        if series_ids is not None and JCI not in series_ids:
            return []
        errors = []
        try:  # from idxscape's first close, not the window's, so the seam never moves
            live = [r._replace(series_id=JCI)
                    for r in self.idxscape.rows([COMPOSITE], None, end)]
        except SourceUnavailable as e:
            live, errors = [], [e]
        first = live[0].date if live else None
        try:
            old = [r for r in self.idxmethod.rows([JCI], start, end)
                   if first is None or r.date < first]
        except SourceUnavailable as e:
            old, errors = [], [*errors, e]
        if len(errors) == 2:
            raise errors[0]
        return old + [r for r in live if start is None or r.date >= start]


def jci(
    start: date | None = None, end: date | None = None, source: Source | None = None
) -> list[Row]:
    """JCI (IHSG) daily close. The one place JCI is read; defaults to `JciSource`."""
    return (source or JciSource.from_config()).rows([JCI], start, end)
