"""Picks report (PLAN S92, phase Q rule 3): how held picks did against the JCI and their pool.

Input: {start date: [(symbol, weight)]}, daily closes and dividends per symbol, and the JCI. For
each start and each window in `WINDOWS` (calendar months; a month end maps to a month end), the
picks are held to the window's end, priced at the last bar on or before each date:

- **price** return from split-adjusted closes (`entry.adjusted_closes`: a 1-day move beyond
  `CORP_ACTION_JUMP` is a split or bonus, a zero return);
- **dividend** gain: dividends with ex-date in (start, end], each scaled by the same split
  factor (the one on its cum-dividend bar), summed and divided by the adjusted start price;
- **total** = price + dividend, not reinvested (user decision 5).

Each basket is reported equal-weighted and with the given weights (normalised; any None weight
makes the weighted leg n/a, as for a start financer's statements do not cover). Comparators:
the JCI price index and the same-date eligible pool equal-weighted (user decision 7), with the
excess of the picks' total return over each. A name whose last bar is more than `STOP_DAYS`
before the window's end is held at that bar and flagged `stopped` (delisted or suspended). A
name with no bar on or before the start is n/a and never filled in: a basket with any such pick
is n/a; the pool drops such names and counts them.

A window ending after `as_of` (default: the last JCI bar) is `open`. The summary averages every
complete start per window and gives `n_independent`, the number of non-overlapping windows
behind the mean: only those carry a verdict (user decision 4: placebo on non-overlapping 3m).

**Price basis.** idx-method's `cache/history` closes equal `factor_series` daily `price` on
every overlapping day (981 symbols checked 2026-11-12) and both are split-adjusted by the
provider (BBCA's 1:5 split on 2021-10-13 shows no jump), so `assemble` prepends
`factor_series` bars before a name's first history bar and keeps delisted names that have no
history. The store's dividends are as paid, so the loader runs them through
`dividend_value.adjust_dividends` onto the same adjusted basis first.

`report` and its helpers are pure; `load` is the thin reader. This module is under `eval/`, so
it is part of the model fingerprint (`journal.RULE_GLOBS`).
"""

from __future__ import annotations

import calendar
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from statistics import fmean

from assist.candidates.entry import adjusted_closes

__all__ = [
    "STOP_DAYS",
    "WINDOWS",
    "Leg",
    "NameResult",
    "PicksData",
    "PicksReport",
    "Summary",
    "WindowResult",
    "add_months",
    "assemble",
    "independent",
    "load",
    "report",
]

WINDOWS: tuple[tuple[str, int], ...] = (
    ("1m", 1), ("3m", 3), ("6m", 6), ("1y", 12), ("3y", 36), ("5y", 60),
)
STOP_DAYS = 10  # a last bar this many days before the window's end: stopped, held at that bar

Picks = Mapping[date, Sequence[tuple[str, float | None]]]
Prices = Mapping[str, Sequence[tuple[date, float]]]


# ---------------- calendar ----------------


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def add_months(d: date, n: int) -> date:
    """`d` plus `n` calendar months; a month end stays a month end, other days are clamped."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    last = _month_end(y, m)
    if d == _month_end(d.year, d.month):
        return last
    return date(y, m, min(d.day, last.day))


def independent(starts: Iterable[date], months: int) -> int:
    """How many of the windows from `starts` do not overlap (greedy, earliest first)."""
    n, free = 0, None
    for s in sorted(set(starts)):
        if free is None or s >= free:
            n, free = n + 1, add_months(s, months)
    return n


# ---------------- results ----------------


@dataclass(frozen=True)
class Leg:
    price: float
    dividend: float
    total: float


@dataclass(frozen=True)
class NameResult:
    """One pick over one window; returns None when it is n/a (`note` says why)."""

    symbol: str
    weight: float | None
    start_bar: date | None = None
    end_bar: date | None = None
    price: float | None = None
    dividend: float | None = None
    total: float | None = None
    split_factor: float | None = None  # adjusted / raw at the start, over the same at the end
    stopped: bool = False
    note: str | None = None


@dataclass(frozen=True)
class WindowResult:
    start: date
    window: str
    months: int
    end: date
    status: str  # ok | open
    equal: Leg | None = None
    weighted: Leg | None = None
    jci: float | None = None  # price index
    pool: Leg | None = None
    pool_n: int = 0
    pool_missing: int = 0
    excess_jci: dict = field(default_factory=lambda: {"equal": None, "weighted": None})
    excess_pool: dict = field(default_factory=lambda: {"equal": None, "weighted": None})
    names: tuple[NameResult, ...] = ()
    stopped: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class Summary:
    """Means over the complete starts of one window; each figure beside its own counts."""

    window: str
    months: int
    n_starts: int
    n_independent: int
    equal_price: float | None
    equal_dividend: float | None
    equal_total: float | None
    jci: float | None
    pool_total: float | None
    excess_jci: float | None
    excess_pool: float | None
    n_weighted: int
    n_weighted_independent: int
    weighted_total: float | None
    weighted_excess_jci: float | None
    weighted_excess_pool: float | None


@dataclass(frozen=True)
class PicksReport:
    as_of: date | None
    windows: tuple[WindowResult, ...]
    summary: tuple[Summary, ...]

    def to_dict(self) -> dict:
        return _plain(asdict(self))


def _plain(x):
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_plain(v) for v in x]
    if isinstance(x, date):
        return x.isoformat()
    return x


# ---------------- core ----------------


class _Series:
    """One symbol's closes, split-adjusted, with the factor adjusted / raw on every bar."""

    def __init__(self, pts: Sequence[tuple[date, float]], divs: Sequence[Mapping]):
        pts = sorted((d, c) for d, c in pts if c and c > 0)
        self.dates = [d for d, _ in pts]
        raw = [c for _, c in pts]
        self.adj = adjusted_closes(raw) if raw else []
        self.factor = [a / r for a, r in zip(self.adj, raw, strict=True)]
        self.divs = sorted(
            (date.fromisoformat(r["ex"]) if isinstance(r["ex"], str) else r["ex"], r["value"])
            for r in divs if r.get("value") is not None and r.get("ex")
        )

    def at(self, d: date) -> int | None:
        i = bisect_right(self.dates, d)
        return i - 1 if i else None

    def hold(self, symbol: str, weight: float | None, start: date, end: date,
             market_end: date | None) -> NameResult:
        s = self.at(start)
        if s is None:
            return NameResult(symbol, weight, note="no bar on or before start")
        if self.dates[s] < start - timedelta(days=STOP_DAYS):
            return NameResult(symbol, weight, start_bar=self.dates[s],
                              note="stopped before start")
        e = self.at(end)
        p0 = self.adj[s]
        paid = 0.0
        for ex, v in self.divs:
            if start < ex <= end:
                cum = bisect_left(self.dates, ex) - 1  # the last bar before the ex-date
                paid += v * self.factor[max(cum, 0)]
        price = self.adj[e] / p0 - 1
        div = paid / p0
        ref = market_end or end
        stopped = self.dates[e] < min(ref, end) - timedelta(days=STOP_DAYS)
        return NameResult(symbol, weight, self.dates[s], self.dates[e], price, div, price + div,
                          self.factor[s] / self.factor[e], stopped,
                          "held at its last bar" if stopped else None)


def _leg(results: Sequence[NameResult], weights: Sequence[float]) -> Leg:
    tot = sum(weights)
    w = [x / tot for x in weights]
    p = sum(wi * r.price for wi, r in zip(w, results, strict=True))
    d = sum(wi * r.dividend for wi, r in zip(w, results, strict=True))
    return Leg(p, d, p + d)


def _minus(a: Leg | None, b: float | None) -> float | None:
    return None if a is None or b is None else a.total - b


def _mean(xs: Iterable[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    return fmean(xs) if xs else None


def report(
    picks: Picks,
    prices: Prices,
    dividends: Mapping[str, Sequence[Mapping]],
    jci: Sequence[tuple[date, float]],
    *,
    pools: Mapping[date, Iterable[str]] | None = None,
    windows: Sequence[tuple[str, int]] = WINDOWS,
    as_of: date | None = None,
) -> PicksReport:
    """The picks report; see the module docstring. Pure: every input is passed in."""
    jci_s = _Series(jci, ())
    as_of = as_of or (jci_s.dates[-1] if jci_s.dates else None)
    cache: dict[str, _Series] = {}

    def series(sym: str) -> _Series:
        if sym not in cache:
            cache[sym] = _Series(prices.get(sym, ()), dividends.get(sym, ()))
        return cache[sym]

    out: list[WindowResult] = []
    for start in sorted(picks):
        held = list(picks[start])
        pool = list(dict.fromkeys(pools[start])) if pools and start in pools else None
        for label, months in windows:
            end = add_months(start, months)
            if as_of is None or end > as_of:
                out.append(WindowResult(start, label, months, end, "open"))
                continue
            j0, j1 = jci_s.at(start), jci_s.at(end)
            jret = jci_s.adj[j1] / jci_s.adj[j0] - 1 if j0 is not None and j1 is not None \
                else None
            mkt_end = jci_s.dates[j1] if j1 is not None else None
            names = tuple(series(s).hold(s, w, start, end, mkt_end) for s, w in held)
            ok = [n for n in names if n.total is not None]
            missing = tuple(n.symbol for n in names if n.total is None)
            equal = weighted = None
            if names and not missing:
                equal = _leg(names, [1.0] * len(names))
                ws = [n.weight for n in names]
                if all(w is not None for w in ws) and sum(ws) > 0:
                    weighted = _leg(names, ws)
            pool_leg, pool_n, pool_missing = None, 0, 0
            if pool is not None:
                pres = [series(s).hold(s, None, start, end, mkt_end) for s in pool]
                got = [r for r in pres if r.total is not None]
                pool_n, pool_missing = len(got), len(pres) - len(got)
                pool_leg = _leg(got, [1.0] * len(got)) if got else None
            pool_total = pool_leg.total if pool_leg else None
            out.append(WindowResult(
                start, label, months, end, "ok", equal, weighted, jret, pool_leg, pool_n,
                pool_missing,
                {"equal": _minus(equal, jret), "weighted": _minus(weighted, jret)},
                {"equal": _minus(equal, pool_total), "weighted": _minus(weighted, pool_total)},
                names, tuple(n.symbol for n in ok if n.stopped), missing,
            ))
    return PicksReport(as_of, tuple(out), tuple(_summary(out, label, months)
                                                for label, months in windows))


def _summary(rows: Sequence[WindowResult], label: str, months: int) -> Summary:
    done = [w for w in rows if w.window == label and w.equal is not None]
    wtd = [w for w in done if w.weighted is not None]
    return Summary(
        label, months, len(done), independent((w.start for w in done), months),
        _mean(w.equal.price for w in done), _mean(w.equal.dividend for w in done),
        _mean(w.equal.total for w in done), _mean(w.jci for w in done),
        _mean(w.pool.total if w.pool else None for w in done),
        _mean(w.excess_jci["equal"] for w in done), _mean(w.excess_pool["equal"] for w in done),
        len(wtd), independent((w.start for w in wtd), months),
        _mean(w.weighted.total for w in wtd), _mean(w.excess_jci["weighted"] for w in wtd),
        _mean(w.excess_pool["weighted"] for w in wtd),
    )


# ---------------- stores ----------------


@dataclass
class PicksData:
    prices: dict[str, list[tuple[date, float]]] = field(default_factory=dict)
    dividends: dict[str, list[dict]] = field(default_factory=dict)
    jci: list[tuple[date, float]] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)


def assemble(history: Mapping[str, Sequence[Mapping]], factor: Mapping[str, Sequence],
             dividends: Mapping[str, Sequence[Mapping]], jci_rows: Iterable) -> PicksData:
    """Closes per symbol: `factor_series` bars before the name's first `cache/history` bar,
    then the history (both on the same adjusted basis); names only in `factor_series`
    (delisted) keep its bars. Pure."""
    prices: dict[str, list[tuple[date, float]]] = {}
    for sym in sorted(set(history) | set(factor)):
        hist = sorted((date.fromisoformat(b["date"]), float(b["close"]))
                      for b in history.get(sym, ()) if b.get("close"))
        first = hist[0][0] if hist else None
        old = [(b.date, float(b.price)) for b in factor.get(sym, ())
               if b.price and (first is None or b.date < first)]
        if old or hist:
            prices[sym] = sorted(old) + hist
    jci = [(r.date, float(r.value)) for r in jci_rows if r.value]
    return PicksData(prices, {s: list(v) for s, v in dividends.items()}, jci)


def load(symbols: Iterable[str] | None = None) -> PicksData:
    """Read idx-method (history, `factor_series`, split-adjusted dividends) and the JCI,
    read-only. A missing store is a stale input and an empty result, never a crash."""
    from assist.candidates import dividend_value as dv
    from assist.sources.base import SourceUnavailable
    from assist.sources.idxmethod import jci
    from assist.sources.idxmethod_series import IdxMethodSeries
    from assist.sources.idxmethod_stocks import IdxMethodStocks

    syms = sorted(set(symbols)) if symbols is not None else None
    try:
        series = IdxMethodSeries.from_config()
        history = IdxMethodStocks(series.root).history(syms)
        factor = series.daily(syms)
        raw = series.dividends(syms)
        shares = dv._shares(series) or {}
        rows = jci()
    except SourceUnavailable as e:
        return PicksData(stale=[e.stale_input])
    divs = {s: dv.adjust_dividends(r, factor.get(s, []), shares.get(s, {}))
            for s, r in raw.items()}
    return assemble(history, factor, divs, rows)
