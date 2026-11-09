"""idx-method adapter, valuation history: `factor_series` in `store/data/stockbiter.db` (P33).

- daily `price` and `mktcap` from 2016-10, listed and delisted names (`factor_universe`)
- quarterly `cfo_ttm`, `equity`, `net_debt`, `ni_ttm`, `op_income_ttm`, `roa`, `roce`,
  `total_assets`, `total_debt` from 2016-12, each made `available` LAG_DAYS (120) after its
  period end: idx-method V3 (does the TTM step on period end or filing?) is still open
- PE, PBV, P/CFO and EV/EBIT derived here, point in time (no PS or EV/EBITDA: no revenue or
  D&A in the store until idx-method V1)
- `dividends` (symbol, seq, ex, value, ccy), else the `cache/dividends` files
- `FactorSeriesEY` (P66): the JCI earnings-yield cross-section on any date from the daily `pe`
  and `mktcap` items (idx-method c432999), with `FactorSnapshots`' `factors_on(as_of)`
  interface, so the IDN stocks rule can run on history

Only quarter-end dates are quarterly rows. The store also echoes the latest quarter on the pull
date (e.g. 2026-10-26) and holds a run of daily-dated rows for ITMA around 2020-01; both are
dropped, since a period end is what the lag counts from. Read with `sqlite_ro`, never written.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

from assist.candidates.screens import LAG_DAYS
from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import SourceUnavailable, sqlite_ro
from assist.sources.idxmethod_stocks import SOURCE, IdxMethodStocks

__all__ = [
    "DB",
    "EY_ECHO_GAP",
    "EY_WINDOW",
    "FUNDAMENTALS",
    "SOURCE",
    "Bar",
    "FactorSeriesEY",
    "Fundamentals",
    "IdxMethodSeries",
    "Multiples",
    "multiples",
    "quarter_ends",
]

DB = Path("store/data/stockbiter.db")
FUNDAMENTALS = (
    "cfo_ttm",
    "equity",
    "net_debt",
    "ni_ttm",
    "op_income_ttm",
    "roa",
    "roce",
    "total_assets",
    "total_debt",
)
# EY cross-section: a name counts on `as_of` from its newest daily row in (as_of − EY_WINDOW,
# as_of], so weekends and IDX holidays (Lebaran closes ~10 days) carry the last trading day.
# A row more than EY_ECHO_GAP after the name's previous one is not a quote: the store echoes
# delisted names' last values on its pull date (e.g. 35 extra names on 2026-11-06).
EY_WINDOW = timedelta(days=14)
EY_ECHO_GAP = timedelta(days=14)
QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")
_QE_SQL = ", ".join(f"'{q}'" for q in QUARTER_ENDS)


class Bar(NamedTuple):
    date: date
    price: float | None
    mktcap: float | None


class Fundamentals(NamedTuple):
    """One quarter, knowable from `available` (period end + LAG_DAYS). IDR, ratios in %."""

    period: date
    available: date
    cfo_ttm: float | None
    equity: float | None
    net_debt: float | None
    ni_ttm: float | None
    op_income_ttm: float | None
    roa: float | None
    roce: float | None
    total_assets: float | None
    total_debt: float | None


class Multiples(NamedTuple):
    """Multiples on `date` from the last bar with a mktcap on or before it (`bar_date`) and the
    last quarter available by it (`period`, None if none yet)."""

    date: date
    bar_date: date
    price: float | None
    mktcap: float | None
    period: date | None
    pe: float | None
    pbv: float | None
    p_cfo: float | None
    ev_ebit: float | None


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den <= 0:
        return None
    return num / den


def multiples(mktcap: float | None, f: Fundamentals | None) -> dict[str, float | None]:
    """PE = mktcap/ni_ttm, PBV = mktcap/equity, P/CFO = mktcap/cfo_ttm,
    EV/EBIT = (mktcap + net_debt)/op_income_ttm; None when an input is missing or the
    denominator is <= 0."""
    if mktcap is None or f is None:
        return dict.fromkeys(("pe", "pbv", "p_cfo", "ev_ebit"))
    ev = mktcap + f.net_debt if f.net_debt is not None else None
    return {
        "pe": _ratio(mktcap, f.ni_ttm),
        "pbv": _ratio(mktcap, f.equity),
        "p_cfo": _ratio(mktcap, f.cfo_ttm),
        "ev_ebit": _ratio(ev, f.op_income_ttm),
    }


def quarter_ends(start: date, end: date) -> list[date]:
    """Calendar quarter ends in [start, end]."""
    out = []
    for y in range(start.year, end.year + 1):
        for q in QUARTER_ENDS:
            d = date.fromisoformat(f"{y}-{q}")
            if start <= d <= end:
                out.append(d)
    return out


def _f(v) -> float | None:
    return None if v is None else float(v)


class IdxMethodSeries:
    """Read-only view of `factor_series`. A missing db or table is `missing`, a locked db
    `locked`. Quarterly rows are cached per instance, so `known_at` over many dates is cheap."""

    name = SOURCE

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()
        self._quarterly: dict[str, list[Fundamentals]] | None = None

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> IdxMethodSeries:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    @property
    def db(self) -> Path:
        return self.root / DB

    @contextmanager
    def _con(self, *tables: str) -> Iterator[sqlite3.Connection]:
        with sqlite_ro(self.db, self.name) as con:
            have = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            for t in tables:
                if t not in have:
                    raise SourceUnavailable(self.name, "missing", f"no table {t} in {self.db}")
            yield con

    def symbols(self) -> list[str]:
        """Every symbol with a series, delisted ones included."""
        with self._con("factor_series") as con:
            return [
                r[0] for r in con.execute("select distinct symbol from factor_series order by 1")
            ]

    def universe(self) -> dict[str, dict]:
        """`factor_universe`: name, sector, status and delisted per symbol."""
        with self._con("factor_universe") as con:
            rows = con.execute("select symbol, name, sector, status, delisted from factor_universe")
            return {
                s: {"name": n, "sector": sec, "status": st, "delisted": bool(dl)}
                for s, n, sec, st, dl in rows
            }

    def daily(
        self,
        symbols: Iterable[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> dict[str, list[Bar]]:
        """Per symbol, (date, price, mktcap) by date; either may be None on a day."""
        sql = (
            "select symbol, date, max(case when item = 'price' then value end),"
            " max(case when item = 'mktcap' then value end) from factor_series"
            " where freq = 'daily' and item in ('price', 'mktcap')"
        )
        params: list = []
        if symbols is not None:
            syms = sorted(set(symbols))
            sql += f" and symbol in ({', '.join('?' for _ in syms)})"
            params += syms
        if start is not None:
            sql += " and date >= ?"
            params.append(start.isoformat())
        if end is not None:
            sql += " and date <= ?"
            params.append(end.isoformat())
        sql += " group by symbol, date order by symbol, date"
        out: dict[str, list[Bar]] = {}
        with self._con("factor_series") as con:
            for sym, d, p, m in con.execute(sql, params):
                out.setdefault(sym, []).append(Bar(date.fromisoformat(d), _f(p), _f(m)))
        return out

    def quarterly(self, symbols: Iterable[str] | None = None) -> dict[str, list[Fundamentals]]:
        """Per symbol, one `Fundamentals` per quarter end, oldest first."""
        if self._quarterly is None:
            self._quarterly = self._load_quarterly()
        if symbols is None:
            return dict(self._quarterly)
        return {s: self._quarterly[s] for s in sorted(set(symbols)) if s in self._quarterly}

    def _load_quarterly(self) -> dict[str, list[Fundamentals]]:
        sql = (
            "select symbol, date, item, value from factor_series where freq = 'quarterly'"
            f" and substr(date, 6, 5) in ({_QE_SQL}) order by symbol, date"
        )
        grouped: dict[str, dict[str, dict[str, float | None]]] = {}
        with self._con("factor_series") as con:
            for sym, d, item, v in con.execute(sql):
                if item in FUNDAMENTALS:
                    grouped.setdefault(sym, {}).setdefault(d, {})[item] = _f(v)
        out: dict[str, list[Fundamentals]] = {}
        for sym, periods in grouped.items():
            for d, items in periods.items():
                p = date.fromisoformat(d)
                out.setdefault(sym, []).append(
                    Fundamentals(
                        p, p + timedelta(days=LAG_DAYS), *(items.get(k) for k in FUNDAMENTALS)
                    )
                )
        return out

    def known_at(self, symbol: str, d: date) -> list[Fundamentals]:
        """The quarters of `symbol` available by `d` (period end + LAG_DAYS <= d)."""
        return [f for f in self.quarterly([symbol]).get(symbol, []) if f.available <= d]

    def multiples_at(self, symbol: str, d: date, bars: list[Bar] | None = None) -> Multiples | None:
        """Point-in-time multiples on `d`; None when there is no bar with a mktcap by then."""
        if bars is None:
            bars = self.daily([symbol], end=d).get(symbol, [])
        bar = next((b for b in reversed(bars) if b.date <= d and b.mktcap is not None), None)
        if bar is None:
            return None
        known = self.known_at(symbol, d)
        f = known[-1] if known else None
        m = multiples(bar.mktcap, f)
        return Multiples(d, bar.date, bar.price, bar.mktcap, f.period if f else None, **m)

    def multiples_series(self, symbol: str, dates: Iterable[date] | None = None) -> list[Multiples]:
        """Multiples on each of `dates` (default: the quarter ends within the daily span)."""
        bars = self.daily([symbol]).get(symbol, [])
        if not bars:
            return []
        if dates is None:
            dates = quarter_ends(bars[0].date, bars[-1].date)
        out = [self.multiples_at(symbol, d, bars) for d in dates]
        return [m for m in out if m is not None]

    def span(self) -> dict[str, tuple[str, int, date, date]]:
        """Per item: (freq, symbols, first date, last date), as stored."""
        sql = (
            "select item, freq, count(distinct symbol), min(date), max(date)"
            " from factor_series group by item, freq order by item"
        )
        with self._con("factor_series") as con:
            return {
                item: (freq, n, date.fromisoformat(lo), date.fromisoformat(hi))
                for item, freq, n, lo, hi in con.execute(sql)
            }

    def dividends(self, symbols: Iterable[str] | None = None) -> dict[str, list[dict]]:
        """Per symbol, {ex, value, ccy} in `seq` order: the `dividends` table if the store has
        it, else idx-method's `cache/dividends` files."""
        with sqlite_ro(self.db, self.name) as con:
            has = con.execute(
                "select 1 from sqlite_master where type='table' and name='dividends'"
            ).fetchone()
            if has:
                sql = "select symbol, ex, value, ccy from dividends"
                params: list = []
                if symbols is not None:
                    syms = sorted(set(symbols))
                    sql += f" where symbol in ({', '.join('?' for _ in syms)})"
                    params = syms
                out: dict[str, list[dict]] = {}
                for sym, ex, v, ccy in con.execute(sql + " order by symbol, seq", params):
                    out.setdefault(sym, []).append({"ex": ex, "value": _f(v), "ccy": ccy})
                return out
        return IdxMethodStocks(self.root).dividends(symbols)


class FactorSeriesEY:
    """The JCI earnings-yield cross-section on any date, from `factor_series` daily `pe` and
    `mktcap` (P66). Same interface as `FactorSnapshots`: `name` and `factors_on(as_of)` →
    (newest row date used, {symbol: {mktcap, pe, earnings_yield}}), so `idn_stocks` takes it as
    `snapshots=`. EY = 100 / PE in %, a negative PE kept (an index P/E counts loss makers), a
    zero or missing PE gives no EY. The daily multiples step on the filing date (idx-method
    c432999), so no extra lag is added. Read-only; one query per date."""

    name = SOURCE

    def __init__(self, root: Path | str):
        self.series = IdxMethodSeries(root)

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> FactorSeriesEY:
        return cls(IdxMethodSeries.from_config(config, env).root)

    def factors_on(self, as_of: date) -> tuple[date, dict[str, dict]]:
        lo = as_of - EY_WINDOW - EY_ECHO_GAP
        sql = (
            "select symbol, item, date, value from factor_series where freq = 'daily'"
            " and item in ('pe', 'mktcap') and date > ? and date <= ?"
            " and value is not null order by symbol, item, date"
        )
        rows: dict[str, dict[str, list[tuple[date, float]]]] = {}
        with self.series._con("factor_series") as con:
            for sym, item, d, v in con.execute(sql, (lo.isoformat(), as_of.isoformat())):
                rows.setdefault(sym, {}).setdefault(item, []).append((date.fromisoformat(d), _f(v)))
        out: dict[str, dict] = {}
        newest: date | None = None
        for sym, items in rows.items():
            pes, caps = items.get("pe", []), items.get("mktcap", [])
            if not pes or not caps or as_of - pes[-1][0] >= EY_WINDOW:
                continue
            if len(pes) < 2 or pes[-1][0] - pes[-2][0] > EY_ECHO_GAP:
                continue  # an echo, or a first quote after a long gap
            (d, pe), (_, cap) = pes[-1], caps[-1]
            out[sym] = {"mktcap": cap, "pe": pe, "earnings_yield": 100 / pe if pe else None}
            newest = d if newest is None or d > newest else newest
        if newest is None:
            raise SourceUnavailable(
                self.name, "missing", f"no factor_series pe by {as_of} in {self.series.db}"
            )
        return newest, out

    def history(self, dates: Iterable[date]) -> list[tuple[date, float]]:
        """(as_of, cap-weighted EY %) on each date that has a cross-section, as the stocks rule
        computes it."""
        from assist.layers.rules.idn_stocks import market_earnings_yield

        out = []
        for d in dates:
            try:
                _, factors = self.factors_on(d)
            except SourceUnavailable as e:
                if e.reason != "missing" or not self.series.db.is_file():
                    raise
                continue
            ey, _, _ = market_earnings_yield(factors)
            if ey is not None:
                out.append((d, ey))
        return out
