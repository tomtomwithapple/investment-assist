"""idx-method adapter, stock level: the screener cross-section and the per-symbol caches (files).

- `data/factors.json` (Stockbit screener, ~50 metrics × ~979 names, today only),
  `data/consensus.json` (analyst ratings and forecasts), `data/composition.json` (shareholder
  register), `data/universe.json` (index, sector and watchlist lists; its `data` block)
- `cache/history/<SYM>.json` (5y daily OHLC, value, volume, net foreign flow),
  `cache/dividends/<SYM>.json`, `cache/fundamentals/<SYM>.json` (quarterly statements)

Everything is read as stored, never written. Since 2026-10-14 `factors.json` no longer gains
`vol_1y`, `amihud`, `med_value_60d`, `days_traded_60`, `mom_12_1` or `near_52w_high`
(idx-method README, *Changes the parent must follow*): `assist.candidates.factors` derives them
from `cache/history/`. The index CSVs are P3's (`idxmethod.py`), kept apart on purpose.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import SourceUnavailable

__all__ = ["SOURCE", "IdxMethodStocks"]

SOURCE = "idx-method"


class IdxMethodStocks:
    """Read-only view of idx-method's stock files. A missing repo, file or cache directory is
    `missing`; a file that won't parse (e.g. caught mid-write) is `error`. The caches are
    partial (fundamentals cover the most liquid names first), so a symbol they don't hold is
    simply absent from the result."""

    name = SOURCE

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> IdxMethodStocks:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    def factors(self) -> dict[str, dict]:
        return self._json("data/factors.json")

    def consensus(self) -> dict[str, dict]:
        return self._json("data/consensus.json")

    def composition(self) -> dict[str, dict]:
        return self._json("data/composition.json")

    def universe(self) -> dict[str, list]:
        """The `data` block: `index`, `sectors` and `watchlist` lists."""
        return self._json("data/universe.json")["data"]

    def history(self, symbols: Iterable[str] | None = None) -> dict[str, list[dict]]:
        return self._cache("history", symbols)

    def dividends(self, symbols: Iterable[str] | None = None) -> dict[str, list[dict]]:
        return self._cache("dividends", symbols)

    def fundamentals(self, symbols: Iterable[str] | None = None) -> dict[str, dict]:
        return self._cache("fundamentals", symbols)

    def _check_root(self) -> None:
        if not self.root.is_dir():
            raise SourceUnavailable(self.name, "missing", f"no directory at {self.root}")

    def _json(self, rel: str):
        self._check_root()
        path = self.root / rel
        if not path.is_file():
            raise SourceUnavailable(self.name, "missing", f"no file at {path}")
        return self._load(path)

    def _cache(self, kind: str, symbols: Iterable[str] | None) -> dict:
        self._check_root()
        folder = self.root / "cache" / kind
        if not folder.is_dir():
            raise SourceUnavailable(self.name, "missing", f"no directory at {folder}")
        if symbols is None:
            paths = sorted(folder.glob("*.json"))
        else:
            paths = [folder / f"{s}.json" for s in sorted(set(symbols))]
        return {p.stem: self._load(p) for p in paths if p.is_file()}

    def _load(self, path: Path):
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            raise SourceUnavailable(self.name, "error", f"{path}: {e}") from e
