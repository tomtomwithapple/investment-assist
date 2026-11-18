"""idx-method adapter, insider and major-holder trades (PLAN S106, phase S): `insider_history`
in `store/data/stockbiter.db`, read with `sqlite_ro`, never written.

idx-method imports Stockbit's insider feed (key, date, symbol, raw JSON) after every run,
2021-08 on. Each record is one holder's change in shares from one source: `SOURCE_TYPE_IDX`
(insider disclosures: directors, commissioners) or `SOURCE_TYPE_KSEI` (holders above 5%). The
`date` column is the record's own date; when it became public is the caller's rule.

`trades(start, end)` keeps **market trades** only (`ACTION_TYPE_BUY` / `ACTION_TYPE_SELL`), with
the signed share change (`changes.value`, "+626,237"), and counts what it leaves out in
`dropped`:

- `not a market trade`: transfers, crossings, rights issues, options, splits, conversions, ...
  (live 2026-11-18: 2,651 of 77,778 rows);
- `sign disagrees`: a buy whose change is negative or a sell whose change is positive (45);
- `no share change`: a change that is not a nonzero whole number (3);
- `duplicate`: the same symbol, holder and change again, on the same day from a source already
  counted, or from the other source within `DEDUP_DAYS` (KSEI dates a trade at settlement, two
  trading days after IDX: KETR's 3,951,500 shares on 10-29 from IDX and 11-02 from KSEI), kept
  once at the earlier date with both sources named;
- `unreadable`: raw that is not a JSON object.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import NamedTuple

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import SourceUnavailable, sqlite_ro
from assist.sources.idxmethod_stocks import SOURCE

__all__ = ["DB", "IdxMethodInsider", "InsiderTrade", "InsiderTrades"]

DB = Path("store/data/stockbiter.db")
ACTIONS = {"ACTION_TYPE_BUY": "buy", "ACTION_TYPE_SELL": "sell"}
DEDUP_DAYS = 7
_INT = re.compile(r"^[+-]?\d{1,3}(,\d{3})*$|^[+-]?\d+$")
BADGE = "SHAREHOLDER_BADGE_"


class InsiderTrade(NamedTuple):
    date: date
    symbol: str
    holder: str
    action: str  # "buy" | "sell"
    shares: int  # signed change
    shares_after: int | None
    price: float | None
    sources: tuple[str, ...]  # ("IDX",), ("KSEI",) or both
    badges: tuple[str, ...]  # "DIREKTUR", "KOMISARIS", ...
    nationality: str | None


class InsiderTrades(NamedTuple):
    trades: list[InsiderTrade]  # by date, symbol, holder
    dropped: dict[str, int]


def _int(v) -> int | None:
    s = str(v or "").strip()
    return int(s.replace(",", "")) if _INT.match(s) else None


def _float(v) -> float | None:
    try:
        x = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _source(r: dict) -> str:
    return str((r.get("data_source") or {}).get("type") or "").removeprefix("SOURCE_TYPE_")


class IdxMethodInsider:
    """Read-only view of `insider_history`."""

    name = SOURCE

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None
                    ) -> IdxMethodInsider:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    @property
    def db(self) -> Path:
        return self.root / DB

    def trades(self, start: date | None = None, end: date | None = None) -> InsiderTrades:
        where, params = [], []
        if start:
            where.append("date >= ?")
            params.append(start.isoformat())
        if end:
            where.append("date <= ?")
            params.append(end.isoformat())
        with sqlite_ro(self.db, self.name) as con:
            have = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            if "insider_history" not in have:
                raise SourceUnavailable(self.name, "missing",
                                        f"no table insider_history in {self.db}")
            rows = con.execute(
                "select date, symbol, raw from insider_history"
                f" where {' and '.join(where) or '1'} order by date, symbol, key", params
            ).fetchall()
        dropped: Counter[str] = Counter()
        kept: list[InsiderTrade] = []
        seen: dict[tuple, list[int]] = {}  # (symbol, holder, shares) -> indices into kept
        for d, sym, raw in rows:
            try:
                r = json.loads(raw)
            except (TypeError, ValueError):
                r = None
            if not isinstance(r, dict) or not sym:
                dropped["unreadable"] += 1
                continue
            action = ACTIONS.get(str(r.get("action_type")))
            if action is None:
                dropped["not a market trade"] += 1
                continue
            shares = _int((r.get("changes") or {}).get("value"))
            if shares is None or shares == 0:
                dropped["no share change"] += 1
                continue
            if (shares > 0) != (action == "buy"):
                dropped["sign disagrees"] += 1
                continue
            holder = str(r.get("name") or "").strip()
            day = date.fromisoformat(d[:10])
            key = (sym, holder, shares)
            src = _source(r)
            same = next((i for i in seen.get(key, ()) if _same_trade(kept[i], day, src)), None)
            if same is not None:
                dropped["duplicate"] += 1
                t = kept[same]
                kept[same] = t._replace(sources=tuple(sorted({*t.sources, src})),
                                        price=t.price or _float(((r.get("price") or {}).get("raw")
                                                                 or {}).get("value")))
                continue
            seen.setdefault(key, []).append(len(kept))
            kept.append(InsiderTrade(
                date=day, symbol=sym, holder=holder, action=action,
                shares=shares, shares_after=_int((r.get("current") or {}).get("value")),
                price=_float(((r.get("price") or {}).get("raw") or {}).get("value")),
                sources=(src,) if src else (),
                badges=tuple(str(b).removeprefix(BADGE) for b in r.get("badges") or ()),
                nationality=str(r.get("nationality") or "").removeprefix("NATIONALITY_TYPE_")
                or None,
            ))
        trades = sorted(kept, key=lambda t: (t.date, t.symbol, t.holder, t.shares))
        return InsiderTrades(trades, dict(sorted(dropped.items())))


def _same_trade(t: InsiderTrade, day: date, src: str) -> bool:
    """The record repeats `t`: the same day from a source already counted, or the other source
    within `DEDUP_DAYS` (KSEI records a trade at settlement, a few days after IDX's date)."""
    if src in t.sources:
        return day == t.date
    return 0 <= (day - t.date).days <= DEDUP_DAYS
