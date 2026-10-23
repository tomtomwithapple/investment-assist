"""jquantster adapter: Japan macro, TSE investor-type flows, daily bars and financial summaries.

jquantster's store is one SQLite file (`data/jquantster.db`, WAL mode), read with `sqlite_ro`
(`mode=ro`, `immutable=1` when no writer has it open). Tables and meaning are in jquantster's
README (*Data and storage*) and `docs/macro-plan.md`. Series ids:

- `JGB.<tenor>` (`jgb_series`): MOF JGB par yield in %, `jgb_yields`; tenors `1Y`..`40Y`
  (`25Y` from 2004, `40Y` from 2007). Layer 2.
- `BOJ.<key>` (`boj_series`): `macro_obs`, keys from `macro_series` (`usdjpy` yen per USD at 9:00
  JST, `call_rate` % p.a., Tankan large-enterprise business-conditions DI `tankan_lm`/`tankan_ln`
  and forecasts `*_fc`, which run one quarter ahead; quarterly dates are quarter ends). Units via
  `macro_meta()`. Layer 2.
- `TSE_FLOW.<section>.<column>` (`flow_series`): weekly TSE trading by investor type from
  `investor_types_latest` (newest publication of each week), section e.g. `TSEPrime`, column one
  of jquantster's `<group><Sell|Buy|Tot|Bal>` (e.g. `FrgnBal`, foreigners' net buying in yen).
  Date = week end (`en_date`), `as_of` = `pub_date`. Layer 3. Needs a paid J-Quants plan: on
  Free the table is empty and `status()` shows `investor_types` as `not_in_plan`.
- `JQ_BAR.<code>.<field>` (`bar_series`): `daily_bars` per stock (5-digit J-Quants code), raw
  `o h l c vo va` and split-adjusted `adj_*`. Never in the default `rows()`. Layer 4.
- `JQ_FIN.<code>.<period_type>.<field>` (`fin_series`): J-Quants financial summary
  (`fins_summary.raw`), period type `1Q|2Q|3Q|FY`, date = period end (`CurPerEn`), `as_of` =
  disclosure date; when a period was disclosed more than once (a correction) the newest
  disclosure wins. Blank fields give no row: quarterly reports carry this year's forecast in
  `FEPS`, FY reports leave it blank and carry next year's in `NxFEPS`. Only jquantster's
  watchlist codes have summaries. Never in the default `rows()`. Layer 4.

There are no index-level prices or EPS (no TOPIX/Nikkei series) in jquantster; on the Free plan
bars and summaries are 12 weeks delayed (`status()['window']`). NULL values give no row. The
default `rows()` is every JGB tenor, BOJ key and TSE flow series in the store.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, sqlite_ro

__all__ = [
    "CALL_RATE",
    "FRGN_BAL_PRIME",
    "JGB_10Y",
    "JGB_2Y",
    "SOURCE",
    "TANKAN_LM",
    "TANKAN_LN",
    "USDJPY",
    "JquantsterSource",
    "bar_series",
    "boj_series",
    "fin_series",
    "flow_series",
    "jgb_series",
]

SOURCE = "jquantster"
JGB, BOJ, FLOW, BAR, FIN = "JGB.", "BOJ.", "TSE_FLOW.", "JQ_BAR.", "JQ_FIN."
TABLES = ("jgb_yields", "macro_obs", "macro_series", "investor_types", "daily_bars",
          "fins_summary")

FLOW_GROUPS = ("Prop", "Brk", "Tot", "Ind", "Frgn", "SecCo", "InvTr", "BusCo", "OthCo", "InsCo",
               "Bank", "TrstBnk", "OthFin")
FLOW_COLUMNS = tuple(g + s for g in FLOW_GROUPS for s in ("Sell", "Buy", "Tot", "Bal"))
BAR_FIELDS = ("o", "h", "l", "c", "vo", "va", "adj_factor", "adj_o", "adj_h", "adj_l", "adj_c",
              "adj_vo")
PERIOD_TYPES = ("1Q", "2Q", "3Q", "FY")
FIN_FIELDS = ("EPS", "DEPS", "BPS", "FEPS", "NxFEPS", "Sales", "OP", "OdP", "NP", "TA", "Eq",
              "EqAR", "CFO", "DivAnn", "FDivAnn", "PayoutRatioAnn", "ShOutFY", "TrShFY", "AvgSh")

_TENOR = re.compile(r"\d{1,2}Y")
_KEY = re.compile(r"[A-Za-z0-9_]+")


def jgb_series(tenor: str) -> str:
    if not _TENOR.fullmatch(tenor):
        raise ValueError(f"tenor must look like '10Y', got {tenor!r}")
    return JGB + tenor


def boj_series(key: str) -> str:
    if not _KEY.fullmatch(key):
        raise ValueError(f"BOJ key must be [A-Za-z0-9_]+, got {key!r}")
    return BOJ + key


def flow_series(section: str, column: str) -> str:
    if not _KEY.fullmatch(section) or column not in FLOW_COLUMNS:
        raise ValueError(f"section must be [A-Za-z0-9_]+ and column one of {FLOW_COLUMNS}")
    return f"{FLOW}{section}.{column}"


def bar_series(code: str, field: str) -> str:
    if not _KEY.fullmatch(code) or field not in BAR_FIELDS:
        raise ValueError(f"code must be [A-Za-z0-9_]+ and field one of {BAR_FIELDS}")
    return f"{BAR}{code}.{field}"


def fin_series(code: str, period_type: str, field: str) -> str:
    if not _KEY.fullmatch(code) or period_type not in PERIOD_TYPES or field not in FIN_FIELDS:
        raise ValueError(f"period type must be one of {PERIOD_TYPES} and field one of {FIN_FIELDS}")
    return f"{FIN}{code}.{period_type}.{field}"


JGB_2Y, JGB_10Y = jgb_series("2Y"), jgb_series("10Y")
USDJPY, CALL_RATE = boj_series("usdjpy"), boj_series("call_rate")
TANKAN_LM, TANKAN_LN = boj_series("tankan_lm"), boj_series("tankan_ln")
FRGN_BAL_PRIME = flow_series("TSEPrime", "FrgnBal")


def _parse(sid: str) -> tuple[str, ...] | None:
    """(kind, *key) for a well-formed id, None otherwise."""
    for prefix, kind, n, ok in (
        (JGB, "jgb", 1, lambda p: _TENOR.fullmatch(p[0])),
        (BOJ, "boj", 1, lambda p: _KEY.fullmatch(p[0])),
        (FLOW, "flow", 2, lambda p: _KEY.fullmatch(p[0]) and p[1] in FLOW_COLUMNS),
        (BAR, "bar", 2, lambda p: _KEY.fullmatch(p[0]) and p[1] in BAR_FIELDS),
        (FIN, "fin", 3, lambda p: _KEY.fullmatch(p[0]) and p[1] in PERIOD_TYPES
         and p[2] in FIN_FIELDS),
    ):
        if sid.startswith(prefix):
            parts = tuple(sid.removeprefix(prefix).split("."))
            return (kind, *parts) if len(parts) == n and ok(parts) else None
    return None


def _window(col: str, start: date | None, end: date | None) -> tuple[str, list]:
    where, params = "", []
    if start:
        where += f" and {col} >= ?"
        params.append(start.isoformat())
    if end:
        where += f" and {col} <= ?"
        params.append(end.isoformat())
    return where, params


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class JquantsterSource:
    """jquantster's store as tidy rows, sorted by series and date."""

    name = SOURCE

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()

    @classmethod
    def from_config(
        cls, config: Path = DEFAULT_CONFIG, env: dict | None = None
    ) -> JquantsterSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    def _check(self, con: sqlite3.Connection, *needed: str) -> None:
        names = {n for (n,) in con.execute("select name from sqlite_master")}
        absent = [t for t in needed if t not in names]
        if absent:
            raise SourceUnavailable(self.name, "missing", f"no {', '.join(absent)} table")

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        with sqlite_ro(self.path, self.name) as con:
            self._check(con, *TABLES)
            ids = self._default(con) if series_ids is None else {
                s for s in series_ids if _parse(s)}
            out: list[Row] = []
            for sid in sorted(ids):
                kind, *key = _parse(sid)
                out += getattr(self, f"_{kind}")(con, sid, *key, start=start, end=end)
            return sorted(out, key=lambda r: (r.series_id, r.date))

    def _default(self, con: sqlite3.Connection) -> set[str]:
        ids = {jgb_series(t) for (t,) in con.execute("select distinct tenor from jgb_yields")}
        ids |= {boj_series(k) for (k,) in con.execute("select distinct key from macro_obs")}
        sections = [s for (s,) in con.execute("select distinct section from investor_types")]
        for s in sections:
            values = ", ".join(f"count({c})" for c in FLOW_COLUMNS)
            counts = con.execute(
                f"select {values} from investor_types where section = ?", [s]).fetchone()
            ids |= {flow_series(s, c) for c, n in zip(FLOW_COLUMNS, counts, strict=True) if n}
        return ids

    def _rows(self, con, sid, sql, params, start, end, col="date") -> list[Row]:
        where, wparams = _window(col, start, end)
        cur = con.execute(f"{sql}{where} order by {col}", [*params, *wparams])
        return [Row(sid, _d(d), float(v), _d(rec), self.name)
                for d, v, rec in cur.fetchall() if v is not None]

    def _jgb(self, con, sid, tenor, *, start, end):
        return self._rows(con, sid, "select date, yield_pct, null from jgb_yields where tenor = ?",
                          [tenor], start, end)

    def _boj(self, con, sid, key, *, start, end):
        return self._rows(con, sid, "select date, value, null from macro_obs where key = ?",
                          [key], start, end)

    def _flow(self, con, sid, section, column, *, start, end):
        sql = (f"select en_date, {column}, pub_date from investor_types_latest"
               " where section = ?")
        return self._rows(con, sid, sql, [section], start, end, col="en_date")

    def _bar(self, con, sid, code, field, *, start, end):
        return self._rows(con, sid, f"select date, {field}, null from daily_bars where code = ?",
                          [code], start, end)

    def _fin(self, con, sid, code, period_type, field, *, start, end):
        latest: dict[str, tuple[str | None, float | None]] = {}
        cur = con.execute("select disc_date, raw from fins_summary where code = ?"
                          " order by disc_date, disc_no", [code])
        for disc_date, raw in cur.fetchall():
            rec = json.loads(raw)
            period_end = rec.get("CurPerEn")
            if rec.get("CurPerType") != period_type or not period_end:
                continue
            latest[period_end] = (disc_date or rec.get("DiscDate"), _num(rec.get(field)))
        out = []
        for period_end, (disc_date, value) in latest.items():
            d = _d(period_end)
            if value is None or (start and d < start) or (end and d > end):
                continue
            out.append(Row(sid, d, value, _d(disc_date), self.name))
        return out

    # ---------------- metadata ----------------

    def macro_meta(self) -> dict[str, dict]:
        """`macro_series` per BOJ key: db, code, name, unit, frequency, last_update."""
        with sqlite_ro(self.path, self.name) as con:
            self._check(con, "macro_series")
            cur = con.execute("select key, db, code, name, unit, frequency, last_update"
                              " from macro_series")
            cols = [c[0] for c in cur.description][1:]
            return {k: dict(zip(cols, rest, strict=True)) for k, *rest in cur.fetchall()}

    def status(self) -> dict:
        """J-Quants plan, its data window and each dataset's entitlement (`ok`, `not_in_plan`,
        `no_key`, ...): an empty `investor_types` is `not_in_plan` on Free, not a broken store."""
        with sqlite_ro(self.path, self.name) as con:
            self._check(con, "meta", "entitlements")
            meta = dict(con.execute("select key, value from meta").fetchall())
            ent = dict(con.execute("select dataset, status from entitlements").fetchall())
        return {"plan": meta.get("plan"), "window": meta.get("window"),
                "last_sync": meta.get("last_sync"), "entitlements": ent}
