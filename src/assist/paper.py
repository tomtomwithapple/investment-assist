"""Paper tracking (PLAN S13): each model's stance-implied IDN allocation vs a fixed IDR 60/40
benchmark (60% JCI, 40% SBN leg), marked weekly and scored per model fingerprint.

Reads journal records only (`Journal.read()`, kind `stance`, subject IDN, asset stocks|bonds).
Every number here is a score of past decisions, never a decision, so this module is outside the
fingerprint's rule set.

- **Grid.** Marks fall on Fridays. A week runs from one Friday (`week_start`) to the next
  (`week_end`); a leg's level on a mark is its last value on or before that Friday.
- **JCI leg.** P3's `idxmethod.jci()`, the one place JCI is read (price index, dividends not
  included). idx-method's index CSVs are frozen at 2026-09-30 until a JCI fetcher exists: a mark
  after the last close has no return and is reported stale, never carried forward.
- **SBN leg.** OPEN QUESTION (PLAN.md): which SBN index. The leg is pluggable (`YieldBondLeg`
  or anything with the same `returns`/`stale_reason`); the default is a labelled synthetic
  constant-maturity 10Y par bond: each week it earns a week of coupon at the starting yield and
  is repriced at the ending yield (semiannual coupons; roll-down ignored). Yield from the IGSYC
  10Y curve point (idxscape PHEI), else dbnomics `idn.rate.long` (OECD monthly average, stamped
  at its month end so it is never used before it was known).
- **Benchmark.** 60/40, rebalanced weekly. **Portfolio.** Each asset's latest stance known at the
  start of the week (`as_of <= week_start`) tilts its benchmark weight (`TILT_PT`, placeholder
  until the weight bands are settled); a segment with no stance for an asset holds it at the
  benchmark weight and says so. Weights above 100 are scaled down; the rest is cash earning 0.
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

from assist.journal import Journal, jsonable
from assist.layers.types import DISCLAIMER
from assist.sources.base import Row, Source, SourceUnavailable

__all__ = [
    "BENCHMARK_PCT",
    "DBN_LONG_RATE",
    "TILT_PT",
    "BondLeg",
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
    "paper_track",
    "summarize",
]

ASSETS = ("stocks", "bonds")
BENCHMARK_PCT = {"stocks": 60.0, "bonds": 40.0}
# TODO(PLAN.md, Open questions): placeholder tilt per stance in points of the IDN sleeve.
TILT_PT = {"overweight": 10.0, "neutral": 0.0, "underweight": -10.0}  # "avoid" holds 0
DBN_LONG_RATE = "idn.rate.long"
TENOR_Y = 10
WEEKS_PER_YEAR = 52
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
    label = "JCI (IHSG) price index, idx-method data/jkse_daily.csv (dividends not included)"

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
            return f"JCI: no close after {vt} (idx-method index CSVs frozen; no JCI fetcher)"
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
    ):
        self.series = _Series(yields, grace_days=grace_days)
        self.label, self.name, self.tenor_y = label, name, tenor_y
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
            [(r.date, r.value) for r in rows], name=IGSYC_10Y,
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


# ---------------- allocation ----------------


def implied_weights(stocks: str, bonds: str) -> dict[str, float]:
    """Percent of the IDN sleeve per leg for a stocks and a bonds stance; the rest is cash."""
    w = {}
    for asset, stance in (("stocks", stocks), ("bonds", bonds)):
        w[asset] = 0.0 if stance == "avoid" else min(100.0, max(
            0.0, BENCHMARK_PCT[asset] + TILT_PT[stance]))
    total = w["stocks"] + w["bonds"]
    if total > 100.0:
        w = {k: v * 100.0 / total for k, v in w.items()}
    w["cash"] = max(0.0, 100.0 - w["stocks"] - w["bonds"])
    return w


def _mix(weights: Mapping[str, float], rj: float, rb: float) -> float:
    return (weights["stocks"] * rj + weights["bonds"] * rb) / 100.0


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


def _marks(jci: JciLeg, bond: BondLeg, grid: Sequence[date]) -> list[Mark]:
    rj, rb = jci.returns(grid), bond.returns(grid)
    out = []
    for a, b in zip(grid, grid[1:], strict=False):
        stale = []
        if rj[b] is None:
            stale.append(jci.stale_reason(b))
        if rb[b] is None:
            stale.append(bond.stale_reason(b))
        bench = None if stale else _mix(BENCHMARK_PCT, rj[b], rb[b])
        out.append(Mark(a, b, rj[b], rb[b], bench, stale=stale))
    return out


def benchmark_marks(jci: JciLeg, bond: BondLeg, grid: Sequence[date]) -> list[Mark]:
    """The 60/40 benchmark's weekly marks over `grid` (Fridays); a stale week has no return."""
    return _marks(jci, bond, grid)


def _cum(rs: Iterable[float]) -> float:
    return math.prod(1 + r for r in rs) - 1


def summarize(returns: Sequence[float | None]) -> dict[str, Any]:
    """Cumulative and annualised return over the non-stale weeks; stale weeks are counted."""
    ok = [r for r in returns if r is not None]
    cum = _cum(ok) if ok else None
    ann = (1 + cum) ** (WEEKS_PER_YEAR / len(ok)) - 1 if ok and cum > -1 else None
    vol = statistics.stdev(ok) * math.sqrt(WEEKS_PER_YEAR) if len(ok) > 1 else None
    return {"weeks": len(ok), "stale_weeks": len(returns) - len(ok), "cumulative": cum,
            "annualized": ann, "volatility": vol}


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

    def to_dict(self, marks: bool = True) -> dict:
        out = jsonable(self)
        if not marks:
            out.pop("benchmark")
            for s in out["segments"]:
                s.pop("marks")
        return out


def _as_of(rec: Mapping) -> date | None:
    raw = rec.get("as_of") or (rec.get("outputs") or {}).get("as_of")
    return date.fromisoformat(raw[:10]) if raw else None


def _stance_records(records: Iterable[Mapping]) -> dict[str, list[tuple[date, str, str]]]:
    """{fingerprint: [(as_of, asset, stance)]} for IDN stocks/bonds stances, in file order."""
    out: dict[str, list[tuple[date, str, str]]] = {}
    for rec in records:
        outs = rec.get("outputs") or {}
        asset = rec.get("asset") or outs.get("asset")
        subject = rec.get("subject") or outs.get("subject")
        d, stance = _as_of(rec), outs.get("stance")
        if rec.get("kind") != "stance" or subject != "IDN" or asset not in ASSETS:
            continue
        if d is None or stance not in (*TILT_PT, "avoid"):
            continue
        out.setdefault(rec["fingerprint"], []).append((d, asset, stance))
    return out


def _score(fp: str, decisions: list[tuple[date, str, str]], jci: JciLeg, bond: BondLeg,
           until: date, end: date | None) -> SegmentScore:
    decisions = sorted(decisions, key=lambda x: x[0])  # stable: file order within a day
    first, last = decisions[0][0], decisions[-1][0]
    grid = fridays(first, until)
    marks = [m for m in _marks(jci, bond, grid) if end is None or m.week_start < end]
    notes = [f"IDN/{a}: no stance in this segment; held at the benchmark weight"
             for a in ASSETS if a not in {x[1] for x in decisions}]
    for m in marks:
        held = {a: "neutral" for a in ASSETS}
        for d, asset, stance in decisions:
            if d <= m.week_start:
                held[asset] = stance
        m.weights = implied_weights(held["stocks"], held["bonds"])
        if not m.stale:
            m.portfolio = _mix(m.weights, m.jci, m.sbn)
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
        tracking_error=te, info_ratio=ir, marks=marks, notes=notes)


def paper_track(
    journal: Journal | None = None,
    records: Iterable[Mapping] | None = None,
    jci: JciLeg | None = None,
    bond: BondLeg | None = None,
    start: date | None = None,
    until: date | None = None,
) -> PaperReport:
    """Benchmark marks from `start` (default: where both legs have data) to `until` (default:
    today), and one score per fingerprint segment from the journal's stance records."""
    until = until or date.today()
    if records is None:
        records = (journal or Journal()).read()
    jci = jci or JciLeg.from_source()
    bond = bond or bond_leg()

    firsts = [s.points[0][0] for s in (jci.series, getattr(bond, "series", None))
              if s is not None and s.points]
    start = start or (max(firsts) if len(firsts) == 2 else None)
    bench = benchmark_marks(jci, bond, fridays(start, until)) if start else []

    stale = [*jci.stale_inputs, *bond.stale_inputs]
    if jci.valid_through and until > jci.valid_through:
        stale.append(f"JCI frozen at {jci.valid_through} (idx-method index CSVs; no JCI fetcher)")
    if bond.valid_through and until > bond.valid_through:
        stale.append(f"{bond.name} ends {bond.valid_through}")

    segs = _stance_records(records)
    order = sorted(segs, key=lambda fp: min(d for d, _, _ in segs[fp]))
    starts = [min(d for d, _, _ in segs[fp]) for fp in order]
    scores = [_score(fp, segs[fp], jci, bond, until, starts[i + 1] if i + 1 < len(order) else None)
              for i, fp in enumerate(order)]

    notes = [f"benchmark: {BENCHMARK_PCT['stocks']:g}% JCI / {BENCHMARK_PCT['bonds']:g}% SBN leg, "
             "rebalanced weekly; cash earns 0 (no deposit-rate leg)"]
    if not scores:
        notes.append("no stance records in the journal: benchmark marks only")
    return PaperReport(
        as_of=until, start=start, legs={"stocks": jci.label, "bonds": bond.label},
        bond_series=bond.name, benchmark_pct=dict(BENCHMARK_PCT), stale_inputs=stale,
        benchmark_summary=summarize([m.benchmark for m in bench]), benchmark=bench,
        segments=scores, notes=notes)


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m assist.paper [--marks]`: the report as JSON (live, read-only)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    rep = paper_track()
    print(json.dumps(rep.to_dict(marks="--marks" in argv), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
