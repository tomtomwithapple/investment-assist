"""idx-method adapter, watchlist (PLAN S89): Stockbit screeners in `store/data/stockbiter.db`.

`screener_preset` (date, screener_id, category, grp, name, description, rules, universe, sort,
totalrows, fetched) and `screener_member` (date, screener_id, rank, symbol, results), written
nightly since 2026-11-12 by idx-method's `store/screener_pull.py`. Phase P rule 1: they are a
**watchlist only**. A name on one may join the IDN pool to be judged by this repo's own code;
membership never gives a verdict, a size or a rank.

Which screeners count is `config/watchlist.yaml`: `screeners` (ids or names), else every
screener in `category` (default `Custom`, the user's own saved screeners). The newest member date
on or before the run day is read; older than `max_age_days` it is still read and named `stale`
(a stale input, never a failure). A missing db or table is `SourceUnavailable("missing")`. Read
with `sqlite_ro`, never written.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import yaml

from assist.doctor import DEFAULT_CONFIG, REPO, load_sources
from assist.sources.base import SourceUnavailable, sqlite_ro
from assist.sources.idxmethod_stocks import SOURCE

__all__ = ["DEFAULT_WATCHLIST", "IdxMethodWatchlist", "load_config"]

DB = Path("store/data/stockbiter.db")
DEFAULT_WATCHLIST = REPO / "config" / "watchlist.yaml"
DEFAULTS = {"category": "Custom", "screeners": [], "max_age_days": 3}
TABLES = ("screener_preset", "screener_member")


def load_config(path: Path = DEFAULT_WATCHLIST) -> dict:
    """The watchlist settings; a missing file gives the defaults (every `Custom` screener)."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except OSError:
        raw = {}
    out = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS and v is not None}}
    out["screeners"] = list(out["screeners"] or [])
    return out


class IdxMethodWatchlist:
    """Read-only view of the screener tables."""

    name = SOURCE

    def __init__(self, root: Path | str, config: Mapping | None = None):
        self.root = Path(root).expanduser()
        self.config = {**DEFAULTS, **(config or {})}

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None,
                    watchlist: Path = DEFAULT_WATCHLIST) -> IdxMethodWatchlist:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location, load_config(watchlist))

    @property
    def db(self) -> Path:
        return self.root / DB

    def latest(self, day: date) -> dict:
        """The watchlist on the newest member date on or before `day`, as plain JSON:
        {as_of, stale (reason or None), category, missing (configured screeners not found),
        screeners: [{id, name, category, totalrows, fetched, members (rank order)}],
        members: {symbol: [screener names]}}."""
        with sqlite_ro(self.db, self.name) as con:
            have = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            for t in TABLES:
                if t not in have:
                    raise SourceUnavailable(self.name, "missing", f"no table {t} in {self.db}")
            (newest,) = con.execute("select max(date) from screener_member where date <= ?",
                                    (day.isoformat(),)).fetchone()
            if newest is None:
                raise SourceUnavailable(self.name, "missing",
                                        f"no screener_member by {day} in {self.db}")
            presets = con.execute(
                "select screener_id, category, name, totalrows, fetched from screener_preset"
                " where date = ? order by screener_id", (newest,)).fetchall()
            members: dict[int, list[str]] = {}
            for sid, sym in con.execute(
                    "select screener_id, symbol from screener_member where date = ?"
                    " order by screener_id, rank, symbol", (newest,)):
                members.setdefault(sid, []).append(sym)
        wanted = [str(x) for x in self.config["screeners"]]
        if wanted:
            chosen = [p for p in presets if str(p[0]) in wanted or p[2] in wanted]
            found = {str(p[0]) for p in chosen} | {p[2] for p in chosen}
            missing = [w for w in wanted if w not in found]
        else:
            chosen = [p for p in presets if p[1] == self.config["category"]]
            missing = []
        screeners = [{"id": int(sid), "name": name or str(sid), "category": cat,
                      "totalrows": total, "fetched": fetched, "members": members.get(sid, [])}
                     for sid, cat, name, total, fetched in chosen]
        by_sym: dict[str, list[str]] = {}
        for s in screeners:
            for sym in s["members"]:
                by_sym.setdefault(sym, []).append(s["name"])
        age = (day - date.fromisoformat(newest)).days
        stale = (f"{self.name} screener_member (stale: newest {newest}, {age}d old)"
                 if age > int(self.config["max_age_days"]) else None)
        return {"as_of": newest, "stale": stale,
                "category": None if wanted else self.config["category"], "missing": missing,
                "screeners": screeners, "members": dict(sorted(by_sym.items()))}
