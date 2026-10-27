"""idx-method adapter, peer comparison: Stockbit's `/comparison` responses in `api_raw` (S30).

idx-method's `store/endpoints_pull.py` (weekdays 16:30) stores three endpoints verbatim,
zlib-compressed, under (date, endpoint, symbol, params):

- `comparison_metrics` (market-wide): the metric catalogue, groups of `fitem_id` + name
- `comparison_ratios` (per symbol): the name's own value per `fitem_id`
- `comparison_industries` (per symbol): Stockbit's `industry` and `sector` averages per
  `fitem_id`, and up to four `competitor` symbols

The averages are Stockbit's (means, sometimes negative, today only: `/comparison` takes no
date). The responses carry no industry name or id, so an industry here is the set of symbols
whose `industry` block is identical. Values are display strings ("16.00%", "129,422 B",
"(47,342 B)", "-", "N/A", "25 Mar 26") and are parsed to floats in IDR and percent points.
Only the newest date is read. Read with `sqlite_ro`, never written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import SourceUnavailable, sqlite_ro
from assist.sources.idxmethod_series import DB
from assist.sources.idxmethod_stocks import SOURCE

__all__ = ["ENDPOINTS", "Comparison", "IdxMethodComparison", "block_key", "parse_value"]

ENDPOINTS = ("comparison_metrics", "comparison_ratios", "comparison_industries")
_UNIT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
_NUM = re.compile(r"^(-)?([\d,]*\.?\d+)\s*([%KMBT])?$")


def parse_value(raw: object) -> float | None:
    """'16.00%' → 16.0, '129,422 B' → 1.29422e14, '(47,342 B)' → -4.7342e13, '-9' → -9.0;
    '-', 'N/A', a date or anything else → None."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = str(raw or "").strip()
    paren = s.startswith("(") and s.endswith(")")
    m = _NUM.match(s[1:-1].strip() if paren else s)
    if not m:
        return None
    neg = paren or bool(m.group(1))
    v = float(m.group(2).replace(",", ""))
    unit = m.group(3)
    if unit and unit != "%":
        v *= _UNIT[unit]
    return -v if neg else v


def block_key(block: object) -> str:
    """A short stable id for an `industry` or `sector` block: the same averages, the same id."""
    text = json.dumps(block, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(text.encode()).hexdigest()[:8]


def _values(items: object) -> dict[int, float | None]:
    out: dict[int, float | None] = {}
    for x in items if isinstance(items, list) else []:
        if isinstance(x, Mapping) and "fitem_id" in x:
            out[int(x["fitem_id"])] = parse_value(x.get("value"))
    return out


@dataclass
class Comparison:
    """One pull date. `ratios[sym][fid]`, `industry_avg[sym][fid]` and `sector_avg[sym][fid]`
    are floats or None; `industry[sym]` and `sector_key[sym]` are `block_key` ids."""

    date: date
    metrics: dict[int, tuple[str, str]] = field(default_factory=dict)  # fid → (group, name)
    names: dict[str, str] = field(default_factory=dict)
    sectors: dict[str, str] = field(default_factory=dict)  # IDX-IC sector, factor_universe
    ratios: dict[str, dict[int, float | None]] = field(default_factory=dict)
    industry_avg: dict[str, dict[int, float | None]] = field(default_factory=dict)
    sector_avg: dict[str, dict[int, float | None]] = field(default_factory=dict)
    industry: dict[str, str] = field(default_factory=dict)
    sector_key: dict[str, str] = field(default_factory=dict)
    competitors: dict[str, list[str]] = field(default_factory=dict)


class IdxMethodComparison:
    """Read-only view of the `comparison_*` rows in `api_raw`. A missing db, table or pull is
    `missing`, a locked db `locked`; a body that will not decode is skipped (one symbol, not
    the whole pull)."""

    name = SOURCE

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG,
                    env: dict | None = None) -> IdxMethodComparison:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    @property
    def db(self) -> Path:
        return self.root / DB

    @contextmanager
    def _con(self) -> Iterator:
        with sqlite_ro(self.db, self.name) as con:
            have = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            if "api_raw" not in have:
                raise SourceUnavailable(self.name, "missing", f"no table api_raw in {self.db}")
            yield con

    def latest(self) -> Comparison:
        """The newest date that holds `comparison_industries`, with every endpoint of that date."""
        with self._con() as con:
            row = con.execute("select max(date) from api_raw where endpoint = ?",
                              ("comparison_industries",)).fetchone()
            if not row or not row[0]:
                raise SourceUnavailable(self.name, "missing",
                                        "no comparison_industries in api_raw")
            day = row[0]
            cmp = Comparison(date=date.fromisoformat(day[:10]))
            for endpoint, sym, body in con.execute(
                    "select endpoint, symbol, body from api_raw where date = ? and endpoint in "
                    "(?, ?, ?) order by endpoint, symbol", (day, *ENDPOINTS)):
                data = _decode(body)
                if data is None:
                    continue
                _take(cmp, endpoint, sym, data)
            have = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            if "factor_universe" in have:
                for sym, name, sector in con.execute(
                        "select symbol, name, sector from factor_universe"):
                    if sym in cmp.industry:
                        cmp.names.setdefault(sym, name or "")
                        cmp.sectors[sym] = sector or ""
        return cmp


def _decode(body: object) -> object | None:
    if body is None:
        return None
    raw = bytes(body) if isinstance(body, (bytes, bytearray, memoryview)) else str(body).encode()
    with suppress(zlib.error):
        raw = zlib.decompress(raw)
    try:
        return (json.loads(raw) or {}).get("data")
    except (ValueError, AttributeError):
        return None


def _take(cmp: Comparison, endpoint: str, sym: str, data: object) -> None:
    if endpoint == "comparison_metrics":
        for g in data if isinstance(data, list) else []:
            for c in g.get("child") or []:
                cmp.metrics[int(c["fitem_id"])] = (str(g.get("fitem_name", "")),
                                                   str(c.get("fitem_name", "")))
    elif endpoint == "comparison_ratios" and isinstance(data, Mapping):
        cmp.ratios[sym] = _values(data.get("data_value"))
    elif endpoint == "comparison_industries" and isinstance(data, Mapping):
        if not data.get("industry"):
            return
        cmp.industry_avg[sym] = _values(data.get("industry"))
        cmp.sector_avg[sym] = _values(data.get("sector"))
        cmp.industry[sym] = block_key(data.get("industry"))
        cmp.sector_key[sym] = block_key(data.get("sector"))
        cmp.competitors[sym] = [str(c["symbol"]) for c in data.get("competitor") or []
                                if isinstance(c, Mapping) and c.get("symbol")]
