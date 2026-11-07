"""Paper tracking (PLAN S13, S40): each model's stance-implied allocation vs the IDR benchmark
48% JCI / 32% SBN leg / 20% US stocks in IDR (`stance.BENCHMARK_PCT`, S39), marked weekly and
scored per model fingerprint; segments journalled before S39 keep the old 60/40 benchmark.

Reads journal records only (`Journal.read()`, kind `stance`, IDN stocks|bonds and USA stocks).
Every number here is a score of past decisions, never a decision, so this module is outside the
fingerprint's rule set.

- **Grid.** Marks fall on Fridays. A week runs from one Friday (`week_start`) to the next
  (`week_end`); a leg's level on a mark is its last value on or before that Friday. A daily
  bond leg (IGSYC) must also have a yield on JCI's last trading day before the mark: a capture
  gap while IDX traded makes the mark stale rather than carrying the old yield (P52).
- **JCI leg.** P3's `idxmethod.jci()`, the one place JCI is read (price index, dividends not
  included): idxscape `index_daily` COMPOSITE from 2021-10-01 (nightly), idx-method's frozen
  CSV before that (P51). A mark after the last close has no return and is reported stale, never
  carried forward.
- **SBN leg.** OPEN QUESTION (PLAN.md): which SBN index. The leg is pluggable (`YieldBondLeg`
  or anything with the same `returns`/`stale_reason`); the default is a labelled synthetic
  constant-maturity 10Y par bond: each week it earns a week of coupon at the starting yield and
  is repriced at the ending yield (semiannual coupons; roll-down ignored). Yield from the IGSYC
  10Y curve point (idxscape PHEI), else dbnomics `idn.rate.long` (OECD monthly average, stamped
  at its month end so it is never used before it was known).
- **US leg (S40).** US stocks in IDR, unhedged, price index: Alpaca SPY close × split factor
  (sec-edgar, `alpaca_bar_adjusted_lookup`; dividends not included, as JCI) × IDR per USD.
  USD/IDR is JISDOR (idxscape `fx_rate`) from its first fixing and, before that, the MAS cross
  USD/SGD ÷ IDR/SGD (singstat, daily since 2005). US and IDX holidays differ, so a mark needs
  the US close of the Friday or the Thursday before (`US_MAX_LAG_DAYS`), never IDX's last day;
  the USD/IDR fixing must be no older than the earlier of the Thursday and JCI's last close.
- **Benchmarks.** `BENCHMARK_PCT` (48/32/20 from `stance.BENCHMARK_PCT`) and the legacy
  `LEGACY_BENCHMARK_PCT` (60/40), both rebalanced weekly, reported side by side, never chained.
  A mark is stale if any leg its benchmark holds has no return.
- **Portfolio.** A segment whose stance payloads carry `portfolio.benchmark_pct` (S39 on) holds
  each mandate leg at its journalled `portfolio.target_pct` (else benchmark + `stance.TILT_PT`)
  known at the start of the week (`as_of <= week_start`) and is scored on 48/32/20. An older
  segment is scored exactly as before S40: the IDN sleeve, 60/40 tilted by the paper's own
  `TILT_PT` (±10). A leg with no stance sits at its benchmark weight and the segment says so.
  Weights above 100 are scaled down; the rest is cash earning 0.
- **Segments.** Records are grouped by fingerprint. A segment rules the weeks that start from
  its first decision until the next segment's first decision. Each segment is scored on its own
  weeks only; nothing is pooled across fingerprints. Stale weeks are counted, not scored.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from assist import stance as _stance
from assist.journal import Journal, jsonable
from assist.layers.types import DISCLAIMER
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.usfin import US_HTTP_TIMEOUT  # `usfin serve`: ~12 s for SPY's ten years

__all__ = [
    "BENCHMARK_PCT",
    "DBN_LONG_RATE",
    "LEGACY_BENCHMARK_PCT",
    "TILT_PT",
    "BondLeg",
    "FxPiece",
    "JciLeg",
    "Mark",
    "PaperReport",
    "SegmentScore",
    "YieldBondLeg",
    "benchmark_marks",
    "bond_leg",
    "bond_price",
    "fridays",
    "implied_weights",
    "mandate_weights",
    "paper_track",
    "pct_text",
    "summarize",
    "UsLeg",
    "us_index",
    "us_leg",
    "usd_idr",
]

ASSETS = ("stocks", "bonds")  # the legacy IDN sleeve
LEGS = ("stocks", "bonds", "usa")
LEG_KEYS = {("IDN", "stocks"): "stocks", ("IDN", "bonds"): "bonds", ("USA", "stocks"): "usa"}
LEG_SUBJECT = {v: f"{s}/{a}" for (s, a), v in LEG_KEYS.items()}
LEG_NAMES = {"stocks": "JCI", "bonds": "SBN leg", "usa": "US stocks (IDR)"}
# One place: the S39 benchmark, keyed by paper leg (a KeyError if stance drops a leg).
BENCHMARK_PCT = {LEG_KEYS[k]: float(v) for k, v in _stance.BENCHMARK_PCT.items()}
BENCHMARK_PCT = {k: BENCHMARK_PCT[k] for k in LEGS}
LEGACY_BENCHMARK_PCT = {"stocks": 60.0, "bonds": 40.0}  # segments journalled before S39
US_SYMBOL = "SPY"
US_MAX_LAG_DAYS = 1  # Friday's US close, or Thursday's when Friday is a US holiday
FX_MAX_LAG_DAYS = 1  # ... and the same for USD/IDR, unless IDX was shut longer (Lebaran)
# TODO(PLAN.md, Open questions): the legacy paper tilt per stance in points of the IDN sleeve.
TILT_PT = {"overweight": 10.0, "neutral": 0.0, "underweight": -10.0}  # "avoid" holds 0
DBN_LONG_RATE = "idn.rate.long"
TENOR_Y = 10
WEEKS_PER_YEAR = 52
MIN_ANNUALISE_WEEKS = 12  # below this many scored weeks a summary shows cumulative only (S41)
EPS = 1e-12


# ---------------- grid ----------------


def fridays(start: date, end: date) -> list[date]:
    """Every Friday in [start, end]."""
    first = start + timedelta(days=(4 - start.weekday()) % 7)
    n = (end - first).days // 7 + 1 if end >= first else 0
    return [first + timedelta(weeks=i) for i in range(n)]


def _month_end(d: date) -> date:
    nxt = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


class _Series:
    """Sorted (date, value) pairs with an on-or-before lookup bounded by `valid_through`."""

    def __init__(self, points: Iterable[tuple[date, float]], valid_through: date | None = None,
                 grace_days: int = 0):
        pts = sorted((d, float(v)) for d, v in points if v is not None)
        self.points = pts
        self.days = [d for d, _ in pts]
        self.valid_through = valid_through or (self.days[-1] if self.days else None)
        self.grace = timedelta(days=grace_days)

    def at(self, d: date) -> float | None:
        if self.valid_through is None or d > self.valid_through + self.grace:
            return None
        i = bisect_right(self.days, d)
        return self.points[i - 1][1] if i else None

    def last(self, d: date) -> float | None:
        """The last value on or before `d`, ignoring `valid_through` (callers check its age)."""
        i = bisect_right(self.days, d)
        return self.points[i - 1][1] if i else None

    def last_day(self, d: date) -> date | None:
        """The date of the point `at(d)` would use (None if none)."""
        i = bisect_right(self.days, d)
        return self.days[i - 1] if i else None


class BondLeg(Protocol):
    name: str
    label: str
    stale_inputs: list[str]
    valid_through: date | None

    def returns(self, grid: Sequence[date]) -> dict[date, float | None]: ...

    def stale_reason(self, d: date) -> str: ...


def _weekly(grid: Sequence[date], level, step) -> dict[date, float | None]:
    out: dict[date, float | None] = {}
    for a, b in zip(grid, grid[1:], strict=False):
        x0, x1 = level(a), level(b)
        out[b] = None if x0 is None or x1 is None else step(x0, x1)
    return out


# ---------------- JCI leg ----------------


class JciLeg:
    """JCI (IHSG) weekly price returns; no return past the last close."""

    name = "JKSE"
    label = ("JCI (IHSG) price index, idxscape index_daily COMPOSITE, idx-method"
             " data/jkse_daily.csv before 2021-10-01 (dividends not included)")

    def __init__(self, rows: Iterable[Row], stale_inputs: Iterable[str] = ()):
        self.series = _Series((r.date, r.value) for r in rows)
        self.stale_inputs = list(stale_inputs)

    @classmethod
    def from_source(cls, source: Source | None = None) -> JciLeg:
        from assist.sources.idxmethod import jci

        try:
            return cls(jci(source=source))
        except SourceUnavailable as e:
            return cls([], [e.stale_input])

    @property
    def valid_through(self) -> date | None:
        return self.series.valid_through

    def returns(self, grid: Sequence[date]) -> dict[date, float | None]:
        return _weekly(grid, self.series.at, lambda c0, c1: c1 / c0 - 1)

    def stale_reason(self, d: date) -> str:
        vt = self.valid_through
        if vt is None:
            return "JCI: no data (" + (", ".join(self.stale_inputs) or "empty") + ")"
        if d > vt:
            return f"JCI: no close after {vt} (idxscape index_daily)"
        return f"JCI: no close on or before {d}"


# ---------------- SBN leg ----------------


def bond_price(coupon: float, yld: float, years: float, freq: int = 2) -> float:
    """Price per 1 of face of a bond paying `coupon` (annual, decimal) at yield `yld`."""
    n = round(years * freq)
    c, y = coupon / freq, yld / freq
    if abs(y) < EPS:
        return c * n + 1
    disc = (1 + y) ** -n
    return c * (1 - disc) / y + disc


class YieldBondLeg:
    """Synthetic constant-maturity par bond from a yield series in percent: each week it buys a
    new par bond at the starting yield, earns a week of coupon and is repriced at the end yield."""

    def __init__(
        self,
        yields: Iterable[tuple[date, float]],
        label: str,
        name: str = "synthetic",
        stale_inputs: Iterable[str] = (),
        tenor_y: float = TENOR_Y,
        grace_days: int = 0,
        daily: bool = False,
    ):
        self.series = _Series(yields, grace_days=grace_days)
        self.label, self.name, self.tenor_y = label, name, tenor_y
        self.daily = daily  # a daily yield must exist on JCI's last trading day of each mark
        self.stale_inputs = list(stale_inputs)

    @property
    def yields(self) -> list[tuple[date, float]]:
        return list(self.series.points)

    @property
    def valid_through(self) -> date | None:
        return self.series.valid_through

    def _step(self, y0: float, y1: float) -> float:
        y0, y1 = y0 / 100, y1 / 100
        return bond_price(y0, y1, self.tenor_y) - 1 + y0 / WEEKS_PER_YEAR

    def returns(self, grid: Sequence[date]) -> dict[date, float | None]:
        return _weekly(grid, self.series.at, self._step)

    def stale_reason(self, d: date) -> str:
        vt = self.valid_through
        if vt is None:
            return "SBN leg: no yield (" + (", ".join(self.stale_inputs) or "empty") + ")"
        if d > vt:
            return f"SBN leg: no {self.name} yield after {vt}"
        return f"SBN leg: no {self.name} yield on or before {d}"


def bond_leg(
    phei: Source | None = None,
    dbn: Source | None = None,
    start: date | None = None,
    end: date | None = None,
) -> YieldBondLeg:
    """Default SBN leg: IGSYC 10Y (idxscape PHEI), else dbnomics' IDN long rate; labelled."""
    from assist.sources.idxscape_phei import IGSYC_10Y, PheiSource

    stale: list[str] = []
    try:
        phei = phei or PheiSource.from_config()
        rows = phei.rows([IGSYC_10Y], start, end)
        if not rows:
            stale.append("idxscape_phei (no IGSYC 10Y rows)")
    except SourceUnavailable as e:
        rows = []
        stale.append(e.stale_input)
    if rows:
        return YieldBondLeg(
            [(r.date, r.value) for r in rows], name=IGSYC_10Y, daily=True,
            label="synthetic constant-maturity 10Y par bond from the IGSYC 10Y yield "
                  "(idxscape PHEI, daily); not an SBN index")

    from assist.sources.dbnomics import DbnomicsSource

    try:
        dbn = dbn or DbnomicsSource.from_config()
        rows = dbn.rows([DBN_LONG_RATE], start, end)
    except SourceUnavailable as e:
        rows = []
        stale.append(e.stale_input)
    if not rows:
        if not any(s.startswith("dbnomics") for s in stale):
            stale.append(f"dbnomics (no {DBN_LONG_RATE} rows)")
        return YieldBondLeg([], label="no SBN yield available", name="none", stale_inputs=stale)
    return YieldBondLeg(
        [(_month_end(r.date), r.value) for r in rows], name=DBN_LONG_RATE, stale_inputs=stale,
        grace_days=6,  # the week that straddles a month end is priced with that month's value
        label="synthetic constant-maturity 10Y par bond from dbnomics idn.rate.long (OECD IDN "
              "10Y, monthly average dated at month end); not an SBN index")


# ---------------- US leg (S40) ----------------


@dataclass
class FxPiece:
    """One source spliced into the USD/IDR series: what it is and the dates it supplies."""

    name: str
    label: str
    first: date
    last: date
    days: int


class UsLeg:
    """US stocks in IDR, unhedged, price index: the US index level (USD) × USD/IDR on each mark.

    A mark's level needs the US close on the mark (Friday) or the day before (a US holiday on
    Friday, known once a later close exists: a mark past the last close is stale, as JCI's is);
    US and IDX holidays differ, so the US close is never tied to IDX's last trading day.
    The USD/IDR fixing must be no older than the earlier of the day before the mark and JCI's
    last close on or before it: a holiday that shuts IDX (Lebaran) also stops JISDOR and passes,
    a capture gap while IDX traded does not. Weekly return = L(end) / L(start) − 1, so a rising
    US index and a weaker rupiah (more IDR per USD) both raise it."""

    def __init__(
        self,
        usd: Iterable[tuple[date, float]],
        fx: Iterable[tuple[date, float]],
        label: str,
        name: str = US_SYMBOL,
        fx_label: str = "USD/IDR",
        fx_pieces: Sequence[FxPiece] = (),
        stale_inputs: Iterable[str] = (),
    ):
        self.usd, self.fx = _Series(usd), _Series(fx)
        self.label, self.name, self.fx_label = label, name, fx_label
        self.fx_pieces = list(fx_pieces)
        self.stale_inputs = list(stale_inputs)

    @property
    def valid_through(self) -> date | None:
        vts = [self.usd.valid_through, self.fx.valid_through]
        return None if None in vts else min(vts)

    @property
    def first(self) -> date | None:
        if not self.usd.points or not self.fx.points:
            return None
        return max(self.usd.days[0], self.fx.days[0])

    def level(self, m: date, idx_day: date | None = None) -> tuple[float | None, list[str]]:
        """(IDR level on mark `m`, []) or (None, why). `idx_day`: JCI's last close ≤ m."""
        why = []
        u, f = self.usd.last_day(m), self.fx.last_day(m)
        if u is None:
            why.append(f"US leg: no {self.name} close on or before {m}")
        elif m > self.usd.days[-1]:  # Friday's close may still come: not carried forward
            why.append(f"US leg: no {self.name} close after {u} (mark {m})")
        elif (m - u).days > US_MAX_LAG_DAYS:
            why.append(f"US leg: no {self.name} close for the {m} mark (last {u})")
        need = m - timedelta(days=FX_MAX_LAG_DAYS)
        if idx_day is not None:
            need = min(need, idx_day)
        if f is None:
            why.append(f"US leg: no USD/IDR on or before {m}")
        elif m > self.fx.days[-1]:
            why.append(f"US leg: no USD/IDR fixing after {f} (mark {m})")
        elif f < need:
            why.append(f"US leg: no USD/IDR fixing for the {m} mark (last {f})")
        if why:
            return None, why
        return self.usd.last(m) * self.fx.last(m), []

    def weekly(self, grid: Sequence[date], idx_day=None
               ) -> dict[date, tuple[float | None, float | None, float | None, list[str]]]:
        """{week end: (IDR return, USD return, USD/IDR move, stale reasons)}."""
        idx_day = idx_day or (lambda d: None)
        lv = {m: self.level(m, idx_day(m)) for m in grid}
        out = {}
        for a, b in zip(grid, grid[1:], strict=False):
            (x0, w0), (x1, w1) = lv[a], lv[b]
            why = list(dict.fromkeys([*w0, *w1]))
            if why:
                out[b] = (None, None, None, why)
                continue
            usd = self.usd.last(b) / self.usd.last(a) - 1
            fx = self.fx.last(b) / self.fx.last(a) - 1
            out[b] = (x1 / x0 - 1, usd, fx, [])
        return out

    def returns(self, grid: Sequence[date]) -> dict[date, float | None]:
        return {b: r for b, (r, *_rest) in self.weekly(grid).items()}

    def stale_reason(self, d: date) -> str:
        return "; ".join(self.level(d)[1]) or f"US leg: no level on {d}"


def us_index(stocks=None, symbol: str = US_SYMBOL) -> tuple[list[tuple[date, float]], list[str]]:
    """`symbol`'s split-adjusted close (price index: close × split_factor, dividends not
    included, as JCI) from sec-edgar's Alpaca bars (`alpaca_bar_adjusted_lookup`)."""
    from assist.sources.usfin_stocks import UsStocks

    try:
        if stocks is None:
            stocks = UsStocks()
            stocks.usfin.timeout = US_HTTP_TIMEOUT
        bars = stocks.bars(symbol)
    except SourceUnavailable as e:
        return [], [e.stale_input]
    pts = [(b.date, b.close * b.split_factor) for b in bars if b.close]
    return pts, ([] if pts else [f"sec-edgar (no {symbol} bars)"])


def usd_idr(idx: Source | None = None, sg: Source | None = None
            ) -> tuple[list[tuple[date, float]], list[FxPiece], list[str]]:
    """Daily IDR per USD: JISDOR (idxscape `fx_rate`) from its first fixing; before that the MAS
    cross USD/SGD ÷ IDR/SGD (singstat, same day, both S$ per unit). A JISDOR gap after its start
    is not filled from MAS: it stays a gap. Returns (points, pieces, stale inputs)."""
    from assist.sources.idxscape import JISDOR, IdxscapeSource
    from assist.sources.singstat import SingstatSource, fx_id

    stale: list[str] = []
    try:
        jis = [(r.date, r.value) for r in (idx or IdxscapeSource.from_config()).rows([JISDOR])
               if r.value]
    except SourceUnavailable as e:
        jis = []
        stale.append(e.stale_input)
    usd_id, idr_id = fx_id("USD"), fx_id("IDR")
    try:
        rows = (sg or SingstatSource.from_config()).rows([usd_id, idr_id])
    except SourceUnavailable as e:
        rows = []
        stale.append(e.stale_input)
    by: dict[str, dict[date, float]] = {usd_id: {}, idr_id: {}}
    for r in rows:
        if r.value and r.series_id in by:
            by[r.series_id][r.date] = r.value
    mas = sorted((d, v / by[idr_id][d]) for d, v in by[usd_id].items() if d in by[idr_id])
    if not jis and not any(s.startswith("idxscape") for s in stale):
        stale.append("idxscape (no JISDOR rows)")
    if not mas and not any(s.startswith("singstat") for s in stale):
        stale.append(f"singstat (no {usd_id} / {idr_id} rows)")
    seam = min(d for d, _ in jis) if jis else None
    before = [(d, v) for d, v in mas if seam is None or d < seam]
    pieces = []
    if before:
        pieces.append(FxPiece("MAS", f"MAS cross {usd_id} ÷ {idr_id} (singstat, daily)",
                              before[0][0], before[-1][0], len(before)))
    if jis:
        jis.sort()
        pieces.append(FxPiece("JISDOR", "JISDOR (idxscape fx_rate, BI daily fixing)",
                              jis[0][0], jis[-1][0], len(jis)))
    return before + jis, pieces, stale


def us_leg(stocks=None, idx: Source | None = None, sg: Source | None = None) -> UsLeg:
    """The default US leg: Alpaca SPY price index (sec-edgar) × the spliced daily USD/IDR."""
    usd, stale = us_index(stocks)
    fx, pieces, fx_stale = usd_idr(idx, sg)
    fx_label = (" then ".join(f"{p.label} {p.first} → {p.last}" for p in pieces)
                or "no USD/IDR available")
    label = (f"US stocks in IDR, unhedged, price index: Alpaca {US_SYMBOL} close × split factor "
             f"(sec-edgar alpaca_bar_adjusted_lookup, dividends not included) × USD/IDR "
             f"({fx_label})")
    return UsLeg(usd, fx, label=label, fx_label=fx_label, fx_pieces=pieces,
                 stale_inputs=[*stale, *fx_stale])


# ---------------- allocation ----------------


def implied_weights(stocks: str, bonds: str) -> dict[str, float]:
    """Legacy (before S39): percent of the IDN sleeve per leg for a stocks and a bonds stance
    around 60/40 with the paper's own ±10 pt tilt; the rest is cash. Scores the old segments."""
    w = {}
    for asset, stance in (("stocks", stocks), ("bonds", bonds)):
        w[asset] = 0.0 if stance == "avoid" else min(100.0, max(
            0.0, LEGACY_BENCHMARK_PCT[asset] + TILT_PT[stance]))
    total = w["stocks"] + w["bonds"]
    if total > 100.0:
        w = {k: v * 100.0 / total for k, v in w.items()}
    w["cash"] = max(0.0, 100.0 - w["stocks"] - w["bonds"])
    return w


def mandate_weights(held: Mapping[str, tuple[str, float | None]]) -> dict[str, float]:
    """Percent of the whole portfolio per leg (S39 rule): each leg's journalled
    `portfolio.target_pct` when present, else benchmark + `stance.TILT_PT` (`avoid` → 0), a leg
    with no stance at its benchmark; scaled down pro rata above 100; the rest is cash."""
    w = {}
    for leg, bench in BENCHMARK_PCT.items():
        st, target = held.get(leg, ("neutral", None))
        if target is None:
            target = 0.0 if st == "avoid" else bench + _stance.TILT_PT[st]
        w[leg] = min(100.0, max(0.0, float(target)))
    total = sum(w.values())
    if total > 100.0:
        w = {k: v * 100.0 / total for k, v in w.items()}
    w["cash"] = max(0.0, 100.0 - sum(w.values()))
    return w


def _mix(weights: Mapping[str, float], legs: Mapping[str, float | None]) -> float:
    return sum(weights[k] * legs[k] for k in LEGS if weights.get(k)) / 100.0


def pct_text(pct: Mapping[str, float]) -> str:
    """'48% JCI / 32% SBN leg / 20% US stocks (IDR)' for the legs `pct` holds."""
    return " / ".join(f"{pct[k]:g}% {LEG_NAMES[k]}" for k in LEGS if k in pct)


# ---------------- marks and scores ----------------


@dataclass
class Mark:
    week_start: date
    week_end: date
    jci: float | None
    sbn: float | None
    benchmark: float | None
    portfolio: float | None = None
    active: float | None = None
    weights: dict[str, float] | None = None
    stale: list[str] = field(default_factory=list)
    usa: float | None = None  # US stocks in IDR
    usa_usd: float | None = None  # the US index in USD
    usd_idr: float | None = None  # change in IDR per USD (+ = rupiah weaker)


def _lagging(jci: JciLeg, bond: BondLeg, grid: Sequence[date]) -> dict[date, date]:
    """Marks where a daily bond leg's last yield is older than JCI's last close: IDX traded
    but the yield was not captured, so the level would be carried forward. Mark → yield date.
    A holiday shuts both markets, so it never shows here; a monthly leg is never checked."""
    series = getattr(bond, "series", None)
    if not getattr(bond, "daily", False) or series is None:
        return {}
    out = {}
    for m in grid:
        j, y = jci.series.last_day(m), series.last_day(m)
        if j is not None and y is not None and y < j:
            out[m] = y
    return out


def _marks(jci: JciLeg, bond: BondLeg, grid: Sequence[date], us: UsLeg | None = None,
           pct: Mapping[str, float] | None = None) -> list[Mark]:
    """Weekly marks of a benchmark `pct` (default `BENCHMARK_PCT`). A mark is stale when a leg
    the benchmark holds has no return; the US leg's reasons count only where it is held."""
    pct = BENCHMARK_PCT if pct is None else pct
    rj, rb = jci.returns(grid), bond.returns(grid)
    lag = _lagging(jci, bond, grid)
    ru = us.weekly(grid, jci.series.last_day) if us is not None else {}
    out = []
    for a, b in zip(grid, grid[1:], strict=False):
        stale = []
        if rj[b] is None:
            stale.append(jci.stale_reason(b))
        late = [(m, lag[m]) for m in (a, b) if m in lag]
        if late:
            rb = {**rb, b: None}
            stale += [f"SBN leg: no {bond.name} yield on {m}'s last IDX day (last {y})"
                      for m, y in late]
        elif rb[b] is None:
            stale.append(bond.stale_reason(b))
        usa, usd, fx, why = ru.get(b, (None, None, None, ["US leg: not loaded"]))
        if pct.get("usa"):
            stale += why
        legs = {"stocks": rj[b], "bonds": rb[b], "usa": usa}
        bench = None if stale else _mix(pct, legs)
        out.append(Mark(a, b, rj[b], rb[b], bench, stale=stale, usa=usa, usa_usd=usd,
                        usd_idr=fx))
    return out


def benchmark_marks(jci: JciLeg, bond: BondLeg, grid: Sequence[date], us: UsLeg | None = None,
                    pct: Mapping[str, float] | None = None) -> list[Mark]:
    """A benchmark's weekly marks over `grid` (Fridays), `BENCHMARK_PCT` unless `pct` is given
    (`LEGACY_BENCHMARK_PCT` for 60/40); a stale week has no return."""
    return _marks(jci, bond, grid, us, pct)


def _cum(rs: Iterable[float]) -> float:
    return math.prod(1 + r for r in rs) - 1


def summarize(returns: Sequence[float | None]) -> dict[str, Any]:
    """Cumulative return over the non-stale weeks, and the annualised one only from
    `MIN_ANNUALISE_WEEKS` scored weeks (None below: one week compounded 52 times is noise, S41);
    stale weeks are counted."""
    ok = [r for r in returns if r is not None]
    cum = _cum(ok) if ok else None
    ann = ((1 + cum) ** (WEEKS_PER_YEAR / len(ok)) - 1
           if len(ok) >= MIN_ANNUALISE_WEEKS and cum > -1 else None)
    vol = statistics.stdev(ok) * math.sqrt(WEEKS_PER_YEAR) if len(ok) > 1 else None
    return {"weeks": len(ok), "stale_weeks": len(returns) - len(ok), "cumulative": cum,
            "annualized": ann, "volatility": vol, "annualize_min_weeks": MIN_ANNUALISE_WEEKS}


def annualized_note(summary: Mapping[str, Any] | None) -> str | None:
    """"annualised after N scored weeks" while a summary is below its minimum, else None."""
    if not summary:
        return None
    n = summary.get("annualize_min_weeks")
    if n and summary.get("annualized") is None and (summary.get("weeks") or 0) < n:
        return f"annualised after {n} scored weeks"
    return None


@dataclass
class SegmentScore:
    fingerprint: str
    decisions: int
    first_as_of: date
    last_as_of: date
    until: date | None  # exclusive: the next segment's first decision
    weeks: int
    stale_weeks: int
    portfolio_return: float | None
    benchmark_return: float | None
    active_return: float | None
    hit_rate: float | None
    tracking_error: float | None
    info_ratio: float | None
    marks: list[Mark]
    notes: list[str]
    benchmark_pct: dict[str, float] | None = None  # the benchmark this segment is scored on


@dataclass
class PaperReport:
    as_of: date
    start: date | None
    legs: dict[str, str]
    bond_series: str
    benchmark_pct: dict[str, float]
    stale_inputs: list[str]
    benchmark_summary: dict[str, Any]
    benchmark: list[Mark]
    segments: list[SegmentScore]
    notes: list[str]
    disclaimer: str = DISCLAIMER
    # the pre-S39 60/40 benchmark, side by side (it scores the segments journalled before S39)
    legacy_benchmark_pct: dict[str, float] | None = None
    legacy_start: date | None = None
    legacy_summary: dict[str, Any] | None = None
    legacy_benchmark: list[Mark] = field(default_factory=list)
    series: dict[str, Any] = field(default_factory=dict)  # the US and USD/IDR series used

    def to_dict(self, marks: bool = True) -> dict:
        out = jsonable(self)
        if not marks:
            out.pop("benchmark")
            out.pop("legacy_benchmark", None)
            for s in out["segments"]:
                s.pop("marks")
        return out


def _as_of(rec: Mapping) -> date | None:
    raw = rec.get("as_of") or (rec.get("outputs") or {}).get("as_of")
    return date.fromisoformat(raw[:10]) if raw else None


@dataclass(frozen=True)
class _Decision:
    as_of: date
    leg: str
    stance: str
    target_pct: float | None  # the journalled portfolio.target_pct (S39 payloads)
    s39: bool  # the payload carries portfolio.benchmark_pct: scored on the S39 benchmark


def _stance_records(records: Iterable[Mapping]) -> dict[str, list[_Decision]]:
    """{fingerprint: [decision]} for the mandate legs' stances (IDN stocks/bonds, USA stocks),
    in file order."""
    out: dict[str, list[_Decision]] = {}
    for rec in records:
        outs = rec.get("outputs") or {}
        asset = rec.get("asset") or outs.get("asset")
        subject = rec.get("subject") or outs.get("subject")
        d, st = _as_of(rec), outs.get("stance")
        leg = LEG_KEYS.get((subject, asset))
        if rec.get("kind") != "stance" or leg is None:
            continue
        if d is None or st not in (*TILT_PT, "avoid"):
            continue
        port = outs.get("portfolio") or {}
        target = port.get("target_pct")
        out.setdefault(rec["fingerprint"], []).append(_Decision(
            d, leg, st, None if target is None else float(target), "benchmark_pct" in port))
    # a legacy segment (no S39 payload) is the IDN sleeve only, exactly as scored before S40
    for fp in list(out):
        if not any(x.s39 for x in out[fp]):
            out[fp] = [x for x in out[fp] if x.leg in ASSETS]
            if not out[fp]:
                del out[fp]
    return out


def _held_weights(decisions: Sequence[_Decision], s39: bool, week_start: date
                  ) -> dict[str, float]:
    if not s39:
        held = {a: "neutral" for a in ASSETS}
        for x in decisions:
            if x.as_of <= week_start:
                held[x.leg] = x.stance
        return implied_weights(held["stocks"], held["bonds"])
    known: dict[str, tuple[str, float | None]] = {}
    for x in decisions:
        if x.as_of <= week_start:
            known[x.leg] = (x.stance, x.target_pct)
    return mandate_weights(known)


def _score(fp: str, decisions: list[_Decision], jci: JciLeg, bond: BondLeg, us: UsLeg | None,
           until: date, end: date | None) -> SegmentScore:
    decisions = sorted(decisions, key=lambda x: x.as_of)  # stable: file order within a day
    s39 = any(x.s39 for x in decisions)
    pct = BENCHMARK_PCT if s39 else LEGACY_BENCHMARK_PCT
    first, last = decisions[0].as_of, decisions[-1].as_of
    grid = fridays(first, until)
    marks = [m for m in _marks(jci, bond, grid, us, pct) if end is None or m.week_start < end]
    seen = {x.leg for x in decisions}
    notes = [f"{LEG_SUBJECT[a]}: no stance in this segment; held at the benchmark weight"
             for a in pct if a not in seen]
    for m in marks:
        m.weights = _held_weights(decisions, s39, m.week_start)
        if not m.stale:
            m.portfolio = _mix(m.weights, {"stocks": m.jci, "bonds": m.sbn, "usa": m.usa})
            m.active = m.portfolio - m.benchmark
    ok = [m for m in marks if not m.stale]
    port = _cum(m.portfolio for m in ok) if ok else None
    bench = _cum(m.benchmark for m in ok) if ok else None
    act = [m.active for m in ok]
    te = statistics.stdev(act) * math.sqrt(WEEKS_PER_YEAR) if len(act) > 1 else None
    ir = (statistics.fmean(act) * WEEKS_PER_YEAR / te) if te and te > EPS else None
    return SegmentScore(
        fingerprint=fp, decisions=len(decisions), first_as_of=first, last_as_of=last, until=end,
        weeks=len(ok), stale_weeks=len(marks) - len(ok), portfolio_return=port,
        benchmark_return=bench, active_return=None if port is None else port - bench,
        hit_rate=sum(a > EPS for a in act) / len(act) if act else None,
        tracking_error=te, info_ratio=ir, marks=marks, notes=notes, benchmark_pct=dict(pct))


def _range(points: Sequence[tuple[date, float]]) -> dict[str, Any]:
    return {"first": points[0][0] if points else None, "last": points[-1][0] if points else None,
            "days": len(points)}


def paper_track(
    journal: Journal | None = None,
    records: Iterable[Mapping] | None = None,
    jci: JciLeg | None = None,
    bond: BondLeg | None = None,
    start: date | None = None,
    until: date | None = None,
    us: UsLeg | None = None,
) -> PaperReport:
    """The benchmark's marks (48/32/20, from where all three legs have data) and the legacy
    60/40's (from where JCI and the SBN leg have data), from `start` if given, to `until`
    (default today); one score per fingerprint segment from the journal's stance records, each
    on its own benchmark (S39 payloads on 48/32/20, earlier ones on 60/40)."""
    until = until or date.today()
    if records is None:
        records = (journal or Journal()).read()
    jci = jci or JciLeg.from_source()
    bond = bond or bond_leg()
    us = us or us_leg()

    firsts = [s.points[0][0] for s in (jci.series, getattr(bond, "series", None))
              if s is not None and s.points]
    legacy_start = start or (max(firsts) if len(firsts) == 2 else None)
    # without any US data the 48/32/20 marks still run, each stale and naming the US leg
    new_start = start or (max(legacy_start, us.first) if legacy_start and us.first
                          else legacy_start)
    bench = benchmark_marks(jci, bond, fridays(new_start, until), us) if new_start else []
    legacy = (benchmark_marks(jci, bond, fridays(legacy_start, until), us, LEGACY_BENCHMARK_PCT)
              if legacy_start else [])

    stale = [*jci.stale_inputs, *bond.stale_inputs, *us.stale_inputs]
    if jci.valid_through and until > jci.valid_through:
        stale.append(f"JCI ends {jci.valid_through} (idxscape index_daily)")
    if bond.valid_through and until > bond.valid_through:
        stale.append(f"{bond.name} ends {bond.valid_through}")
    for name, s in ((us.name, us.usd), ("USD/IDR", us.fx)):
        if s.valid_through and until > s.valid_through:
            stale.append(f"{name} ends {s.valid_through}")

    segs = _stance_records(records)
    order = sorted(segs, key=lambda fp: min(x.as_of for x in segs[fp]))
    starts = [min(x.as_of for x in segs[fp]) for fp in order]
    scores = [_score(fp, segs[fp], jci, bond, us, until,
                     starts[i + 1] if i + 1 < len(order) else None)
              for i, fp in enumerate(order)]

    notes = [f"benchmark: {pct_text(BENCHMARK_PCT)} (stance.BENCHMARK_PCT), rebalanced weekly; "
             "the US leg is unhedged, price only; cash earns 0 (no deposit-rate leg)",
             f"legacy benchmark {pct_text(LEGACY_BENCHMARK_PCT)} shown beside it, never "
             "chained: it scores the segments journalled before S39 (stance payloads without "
             "portfolio.benchmark_pct); each segment says which benchmark it is scored on"]
    pieces = {p.name: p for p in us.fx_pieces}
    if "JISDOR" in pieces and "MAS" in pieces:
        notes.append(f"USD/IDR seam: MAS cross up to {pieces['MAS'].last}, JISDOR from "
                     f"{pieces['JISDOR'].first}; a JISDOR gap after the seam is not filled")
    if not scores:
        notes.append("no stance records in the journal: benchmark marks only")
    return PaperReport(
        as_of=until, start=new_start,
        legs={"stocks": jci.label, "bonds": bond.label, "usa": us.label},
        bond_series=bond.name, benchmark_pct=dict(BENCHMARK_PCT), stale_inputs=stale,
        benchmark_summary=summarize([m.benchmark for m in bench]), benchmark=bench,
        segments=scores, notes=notes,
        legacy_benchmark_pct=dict(LEGACY_BENCHMARK_PCT), legacy_start=legacy_start,
        legacy_summary=summarize([m.benchmark for m in legacy]), legacy_benchmark=legacy,
        series={"usa": {"name": us.name, **_range(us.usd.points)},
                "usd_idr": [jsonable(p) for p in us.fx_pieces]})


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m assist.paper [--marks]`: the report as JSON (live, read-only)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    rep = paper_track()
    print(json.dumps(rep.to_dict(marks="--marks" in argv), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
