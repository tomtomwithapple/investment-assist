"""Layer 2, foreign overrides: is each foreign economy speeding up or slowing now? (PLAN S11)

The IDN overrides (`overrides.py`, P17) carried abroad: per market (USA, JPN, the euro area as
`EMU`, AUS, SGP) a set of hand-set momentum components, each a change in one series read point
in time, with a direction of +1 (rising), -1 (falling) or 0 (inside its dead band):

- `growth`: real GDP y/y, latest minus the mean of the 4 quarters before (US FRED `GDPC1` levels,
  ausdata `DER.GDP_YY`, singstat `M015631:2`); a business survey over 3 months where there is no
  GDP (Japan's Tankan large manufacturers DI, the euro area's OECD BCI).
- `cli`: dbnomics OECD composite leading indicator over 3 months (`g4e.cli` for the euro area;
  OECD publishes none for Singapore).
- `inflation`: CPI y/y over 3 months (dbnomics, ausdata, singstat's CPI index turned into y/y).
  No store has Japanese CPI.
- `policy`: the policy or short rate over 6 months, +1 = hiking (BIS `WS_CBPOL`, ECB deposit
  rate, RBA cash rate, SORA 3M for Singapore, whose MAS steers the S$NEER, not a rate).
- `curve`: 10Y − 2Y over 3 months, +1 = steepening. The euro-area 2Y benchmark stands in for the
  Bund 2Y (dbnomics has none).
- `fx`: IDR per local unit over 3 months, in percent: +1 = the currency gaining on the rupiah,
  which an unhedged IDR investor earns on top of the local return. IDR per USD is the P65 splice
  (`sources.usdidr`, key `usdidr`: JISDOR from its first fixing, the MAS cross before it; P80,
  phase L choice 12, so the 3-month change has a base although idxscape's JISDOR here starts
  2026-10-22); JPY is crossed through USD/JPY (jquantster), EUR through MAS's S$ rates
  (singstat), AUD is RBA's direct AUD/IDR (ausdata), SGD is MAS's S$ per IDR inverted.
- `flows_equity`, `flows_treasury` (US only): sec-edgar TIC foreign net purchases of US equities
  and of long-term Treasuries, grand total, last 3 months' sum minus the 3 before.

Each asset's shift is the sum of `WEIGHTS[component][asset] x direction`, clamped to ±10
(`MAX_OVERRIDE`), the same `Override` the IDN layer makes; `apply` shifts a layer-1 score by it.
The weights and bands are hand-set and must not move a stance until the rule using them beats
its placebo. Each market also carries `IdrTerms`: IDR per local unit, its 3- and 12-month
change, and the 1-year hedge carry (BI rate against the local short rate, `assist.fx`), so a
later layer can express a local return in IDR, hedged or not.

Point in time as in P17: a row counts as known on `as_of` if its store recorded it by then
(`Row.as_of`) or it is older than its series' publication lag (`Ref.lag_days`); dbnomics keeps no
vintage and FRED/TIC history is read at its latest version, so the lag decides in a backtest.
ausdata is asked with `as_of` so a month it dates at its month end is skipped until it is over.
A store that is missing or locked, a series too short for its window and a newest point older
than `Ref.max_age_days` are named in `stale_inputs`, never raised. MAS data older than a week is
flagged (singstat's store was last refreshed 2026-10-07). An input no store has is listed in
`Market.gaps` and reads `n/a` in the reason.
"""

from __future__ import annotations

import calendar
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from assist.doctor import DEFAULT_CONFIG
from assist.fx import cross, fx_change, hedge_carry
from assist.layers.overrides import apply
from assist.layers.types import MAX_OVERRIDE, Override
from assist.sources import ausdata, jquantster, singstat
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.bisfetcher import BI_RATE_M
from assist.sources.idxscape import JISDOR

__all__ = [
    "EMU_MEMBERS",
    "MARKETS",
    "WEIGHTS",
    "Component",
    "ForeignOverrides",
    "FxSpec",
    "IdrTerms",
    "Market",
    "MarketOverrides",
    "Ref",
    "Spec",
    "apply",
    "default_sources",
    "foreign_overrides",
    "market",
]

ASSETS = ("stocks", "bonds", "currency")
EMU_MEMBERS = ("DEU", "FRA", "ITA", "ESP", "NLD")  # worldbankscape subjects in the euro area

# Points of layer-1 score per unit of direction (+1 = the series is rising).
WEIGHTS = {
    "growth": {"stocks": 3, "bonds": -1, "currency": 1},
    "cli": {"stocks": 3, "bonds": -1, "currency": 1},
    "inflation": {"stocks": -1, "bonds": -3, "currency": -1},
    "policy": {"stocks": -2, "bonds": -3, "currency": 1},
    "curve": {"stocks": 1, "bonds": -1, "currency": 0},
    "fx": {"stocks": 1, "bonds": 1, "currency": 3},
    "flows_equity": {"stocks": 2, "bonds": 0, "currency": 1},
    "flows_treasury": {"stocks": 0, "bonds": 2, "currency": 1},
}

# How a component turns a series into one number.
CHANGE = "change"  # latest − the value `months` before
VS_MEAN = "vs_mean"  # latest − mean of the 4 points before (quarterly y/y)
PCT = "pct"  # % change over `months`
FLOW = "flow"  # sum of the last 3 monthly values − the 3 before

# How a stored value becomes what a component uses.
LEVEL = "level"  # as stored
INVERSE = "inverse"  # 1 / value (S$ per IDR → IDR per S$)
YOY = "yoy"  # an index or level → its % change over 12 months

READ_BACK = timedelta(days=1200)  # 9 quarters of GDP levels for 5 y/y points, plus slack
FX_BAND = 1.5  # % over 3 months
MAX_GAP_DAYS = 7  # a spread's short leg older than this on the long leg's date is no match
CARRY_YEARS = 1.0


@dataclass(frozen=True)
class Ref:
    """One stored series. `source` is the key of its store in the sources mapping (`fred` and
    `tic` are both sec-edgar). A row dated d is known on d + `lag_days` (or once recorded); a
    newest known row older than `max_age_days` is used but named stale."""

    source: str
    series_id: str
    lag_days: int = 0
    max_age_days: int = 10
    unit: str = LEVEL

    @property
    def label(self) -> str:
        return f"{self.source} {self.series_id}"


@dataclass(frozen=True)
class Spec:
    """One component of one market: `refs` are tried in order (the first with data wins);
    `minus` makes it a spread (long − short), e.g. 10Y − 2Y."""

    name: str
    what: str
    method: str
    refs: tuple[Ref, ...]
    band: float
    months: int = 3
    minus: tuple[Ref, ...] = ()


@dataclass(frozen=True)
class FxSpec:
    """IDR per local unit: `base` is IDR per unit of USD, SGD or the local currency itself;
    `leg` the local currency against that base, quoted local per base (USD/JPY) or base per
    local (`local_per_base=False`, S$ per EUR)."""

    base: Ref
    leg: Ref | None = None
    local_per_base: bool = True

    @property
    def refs(self) -> tuple[Ref, ...]:
        return (self.base,) if self.leg is None else (self.base, self.leg)


@dataclass(frozen=True)
class Market:
    subject: str
    name: str
    currency: str
    specs: tuple[Spec, ...]
    fx: FxSpec | None = None
    short_rate: tuple[Ref, ...] = ()  # for the hedge carry against the BI rate
    gaps: tuple[tuple[str, str], ...] = ()  # input → why it is missing, who would add it


# ---------------- where the inputs live (as of 2026-10-23) ----------------

DAILY, MAS_DAILY, MONTHLY = 10, 7, 90


def _dbn(sid: str, lag: int = 45, max_age: int = MONTHLY) -> Ref:
    """dbnomics: OECD/ECB monthly values dated at the month start, no vintage."""
    return Ref("dbnomics", sid, lag, max_age)


def _cbpol(iso2: str) -> Ref:
    return Ref("bisfetcher", f"WS_CBPOL.M.{iso2}", 35, 70)


def _mas(sid: str, unit: str = LEVEL) -> Ref:
    return Ref("singstat", sid, 1, MAS_DAILY, unit)


def _cli(sid: str) -> Spec:
    return Spec("cli", "OECD CLI", CHANGE, (_dbn(sid),), 0.2)


def _policy(what: str, *refs: Ref) -> Spec:
    return Spec("policy", what, CHANGE, refs, 0.125, months=6)


IDR_RATE = Ref("bisfetcher", BI_RATE_M, 35, 70)
# The P65 splice served as JISDOR rows: JISDOR points carry idxscape's vintage, MAS cross points
# none, so they count from the day after their date (P80).
JISDOR_REF = Ref("usdidr", JISDOR, 1, DAILY)
IDR_PER_SGD = _mas(singstat.fx_id("IDR"), INVERSE)
# Monthly ABS CPI (and OECD's copy of it) starts 2025-04; the quarterly y/y covers backtests.
AU_CPI_Q = "DER.CPI_HEADLINE_YY_Q"  # dated at the quarter end
TIC_LAG, TIC_AGE = 80, 125  # month M is published mid M+2; dated the 1st

MARKETS: tuple[Market, ...] = (
    Market(
        "USA", "United States", "USD",
        specs=(
            Spec("growth", "real GDP y/y", VS_MEAN, (Ref("fred", "GDPC1", 120, 230, YOY),), 0.25),
            _cli("usa.cli"),
            Spec("inflation", "CPI y/y", CHANGE, (_dbn("usa.cpi.yoy"),), 0.3),
            _policy("Fed rate", _cbpol("US"), Ref("fred", "DFF", 1, DAILY)),
            Spec("curve", "10Y−2Y", CHANGE, (Ref("fred", "T10Y2Y", 1, DAILY),), 0.15),
            Spec("flows_equity", "foreign net buying of US equities, US$ mn", FLOW,
                 (Ref("tic", "for_lt_eqty_net_99996", TIC_LAG, TIC_AGE),), 20_000),
            Spec("flows_treasury", "foreign net buying of US LT Treasuries, US$ mn", FLOW,
                 (Ref("tic", "for_lt_treas_net_99996", TIC_LAG, TIC_AGE),), 30_000),
        ),
        fx=FxSpec(JISDOR_REF),
        short_rate=(_cbpol("US"), Ref("fred", "DFF", 1, DAILY)),
    ),
    Market(
        "JPN", "Japan", "JPY",
        specs=(
            Spec("growth", "Tankan large manufacturers DI", CHANGE,
                 (Ref("jquantster", jquantster.TANKAN_LM, 5, 120),), 3.0),
            _cli("jpn.cli"),
            _policy("BOJ rate", _cbpol("JP"), Ref("jquantster", jquantster.CALL_RATE, 1, DAILY)),
            Spec("curve", "JGB 10Y−2Y", CHANGE, (Ref("jquantster", jquantster.JGB_10Y, 1, DAILY),),
                 0.15, minus=(Ref("jquantster", jquantster.JGB_2Y, 1, DAILY),)),
        ),
        fx=FxSpec(JISDOR_REF, Ref("jquantster", jquantster.USDJPY, 1, DAILY)),
        short_rate=(_cbpol("JP"), Ref("jquantster", jquantster.CALL_RATE, 1, DAILY)),
        gaps=(
            ("inflation", "no store has Japanese CPI (OECD CPI in dbnomics skips JPN, jquantster "
                          "has none); dbnomics would add jpn.cpi.yoy"),
            ("flows", "TSE investor flows are not in jquantster's J-Quants Free plan"),
        ),
    ),
    Market(
        "EMU", "Euro area", "EUR",
        specs=(
            Spec("growth", "OECD business confidence", CHANGE, (_dbn("ea20.bci"),), 0.2),
            _cli("g4e.cli"),
            Spec("inflation", "HICP y/y", CHANGE, (_dbn("ea.hicp.yoy", lag=35),), 0.3),
            _policy("ECB deposit rate", Ref("dbnomics", "ea.rate.deposit", 1, DAILY),
                    _cbpol("XM")),
            Spec("curve", "Bund 10Y − euro-area 2Y", CHANGE, (_dbn("ea.bund.10y", lag=35),),
                 0.15, minus=(_dbn("ea.bond.2y", lag=35),)),
        ),
        fx=FxSpec(IDR_PER_SGD, _mas(singstat.fx_id("EUR")), local_per_base=False),
        short_rate=(Ref("dbnomics", "ea.rate.deposit", 1, DAILY), _cbpol("XM")),
        gaps=(
            ("growth", "dbnomics has no euro-area GDP; the OECD BCI stands in"),
            ("curve", "no Bund 2Y in dbnomics; the euro-area 2Y benchmark stands in"),
        ),
    ),
    Market(
        "AUS", "Australia", "AUD",
        specs=(
            Spec("growth", "real GDP y/y", VS_MEAN, (Ref("ausdata", ausdata.GDP_YY, 70, 200),),
                 0.25),
            _cli("aus.cli"),
            Spec("inflation", "CPI y/y", CHANGE,
                 (Ref("ausdata", ausdata.CPI_YY_M, 60, 100), _dbn("aus.cpi.yoy"),
                  Ref("ausdata", AU_CPI_Q, 30, 130)), 0.3),
            _policy("RBA cash rate", Ref("ausdata", ausdata.CASH_RATE, 1, DAILY), _cbpol("AU")),
            Spec("curve", "AGS 10Y−2Y", CHANGE, (Ref("ausdata", ausdata.CURVE_10Y_2Y, 1, DAILY),),
                 0.15),
        ),
        fx=FxSpec(Ref("ausdata", ausdata.AUD_IDR, 1, DAILY)),
        short_rate=(Ref("ausdata", ausdata.CASH_RATE, 1, DAILY), _cbpol("AU")),
    ),
    Market(
        "SGP", "Singapore", "SGD",
        specs=(
            Spec("growth", "real GDP y/y", VS_MEAN,
                 (Ref("singstat", singstat.REAL_GDP_YOY, 105, 230),), 0.25),
            Spec("inflation", "CPI y/y", CHANGE, (Ref("singstat", singstat.CPI, 30, 100, YOY),),
                 0.3),
            _policy("SORA 3M", _mas(singstat.SORA_3M)),
            Spec("curve", "SGS 10Y−2Y", CHANGE, (_mas(singstat.SGS_10Y),), 0.15,
                 minus=(_mas(singstat.SGS_2Y),)),
        ),
        fx=FxSpec(IDR_PER_SGD),
        short_rate=(_mas(singstat.SORA_3M),),
        gaps=(
            ("cli", "OECD publishes no CLI for Singapore"),
            ("policy", "MAS steers the S$NEER, not a rate; SORA 3M stands in"),
        ),
    ),
)


def market(subject: str) -> Market:
    for m in MARKETS:
        if m.subject == subject:
            return m
    raise KeyError(subject)


# ---------------- results ----------------


@dataclass(frozen=True)
class Component:
    """One momentum input: its change over the window, direction and the newest point used."""

    name: str
    source: str
    series_id: str
    value: float
    direction: int
    last: Row
    detail: str


@dataclass(frozen=True)
class IdrTerms:
    """The market's currency against the rupiah on `as_of`: IDR per local unit, its change over
    3 and 12 months (fractions, + = the local currency gained), and the 1-year hedge carry
    (forward premium from the BI rate against the local short rate; + = hedging back to IDR
    earns it)."""

    currency: str
    level: float
    on: date
    change_3m: float | None
    change_12m: float | None
    carry: float | None

    def detail(self) -> str:
        parts = [f"IDR {self.level:,.2f} per {self.currency} on {self.on}"]
        for label, v in (("3m", self.change_3m), ("12m", self.change_12m)):
            if v is not None:
                parts.append(f"{v:+.1%} {label}")
        if self.carry is not None:
            parts.append(f"hedge carry {self.carry:+.2%}/y")
        return ", ".join(parts)


@dataclass(frozen=True)
class MarketOverrides:
    """Layer 2 for one foreign market: one Override per asset, the components behind them, the
    uncapped sums, the IDR terms, the inputs missing or stale, and the stores read."""

    subject: str
    as_of: date
    overrides: tuple[Override, ...]
    components: tuple[Component, ...]
    raw: dict[str, float]
    idr: IdrTerms | None
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    gaps: tuple[tuple[str, str], ...] = ()

    def for_asset(self, asset: str) -> Override | None:
        return next((o for o in self.overrides if o.asset == asset), None)

    def component(self, name: str) -> Component | None:
        return next((c for c in self.components if c.name == name), None)


@dataclass(frozen=True)
class ForeignOverrides:
    as_of: date
    markets: tuple[MarketOverrides, ...]
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    @property
    def overrides(self) -> tuple[Override, ...]:
        return tuple(o for m in self.markets for o in m.overrides)

    def market(self, subject: str) -> MarketOverrides | None:
        """`subject` may be a euro-area member (DEU, FRA, ...): it reads the `EMU` market."""
        subject = "EMU" if subject in EMU_MEMBERS else subject
        return next((m for m in self.markets if m.subject == subject), None)

    def for_asset(self, subject: str, asset: str) -> Override | None:
        m = self.market(subject)
        return None if m is None else m.for_asset(asset)


# ---------------- series helpers ----------------


def _direction(value: float, band: float) -> int:
    return 1 if value > band else -1 if value < -band else 0


def _shift(d: date, months: int) -> date:
    """`d` moved by `months` (negative = back), the day clamped to the month's length; a month
    end stays a month end (Tankan and ausdata quarters are dated on it)."""
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    days = calendar.monthrange(y, m + 1)[1]
    month_end = d.day == calendar.monthrange(d.year, d.month)[1]
    return date(y, m + 1, days if month_end else min(d.day, days))


def _at(series: list[Row], when: date, max_age_days: int | None = None) -> Row | None:
    """The last point on or before `when` (None if older than `max_age_days`)."""
    r = next((r for r in reversed(series) if r.date <= when), None)
    if r is not None and max_age_days is not None and (when - r.date).days > max_age_days:
        return None
    return r


def _known(rows: Sequence[Row], ref: Ref, as_of: date) -> list[Row]:
    """Non-null rows of `ref` known on `as_of`, oldest first."""
    lag = timedelta(days=ref.lag_days)
    return sorted(
        (r for r in rows
         if r.value is not None and r.date <= as_of
         and ((r.as_of is not None and r.as_of <= as_of) or r.date + lag <= as_of)),
        key=lambda r: r.date,
    )


def _convert(ref: Ref, rows: list[Row]) -> list[Row]:
    if ref.unit == INVERSE:
        return [r._replace(value=1 / r.value) for r in rows if r.value]
    if ref.unit == YOY:
        out = []
        for r in rows:
            base = _at(rows, _shift(r.date, -12), max_age_days=45)
            if base is not None and base.value:
                out.append(r._replace(value=(r.value / base.value - 1) * 100))
        return out
    return rows


def _spread(long: list[Row], short: list[Row]) -> list[Row]:
    out = []
    for a in long:
        b = _at(short, a.date, MAX_GAP_DAYS)
        if b is not None:
            known = [d for d in (a.as_of, b.as_of) if d is not None]
            out.append(Row(f"{a.series_id}-{b.series_id}", a.date, a.value - b.value,
                           max(known) if known else None, a.source))
    return out


# ---------------- reading the stores ----------------


class _Reader:
    """Reads each store once (every series any market needs), then answers per `Ref`."""

    def __init__(self, sources: Mapping[str, Source], as_of: date, refs: Sequence[Ref]):
        self.as_of = as_of
        self.failed: dict[str, str] = {}
        self.read: dict[str, str] = {}
        self.rows: dict[tuple[str, str], list[Row]] = defaultdict(list)
        wanted: dict[str, set[str]] = defaultdict(set)
        for ref in refs:
            wanted[ref.source].add(ref.series_id)
        for key in sorted(wanted):
            src = sources.get(key)
            if src is None:
                self.failed[key] = f"{key} (not configured)"
                continue
            kw = {"as_of": as_of} if key == "ausdata" else {}
            try:
                found = src.rows(sorted(wanted[key]), as_of - READ_BACK, as_of, **kw)
            except SourceUnavailable as e:
                self.failed[key] = e.stale_input
                continue
            self.read[key] = src.name
            for r in found:
                self.rows[(key, r.series_id)].append(r)

    def series(self, ref: Ref) -> list[Row]:
        return _convert(ref, _known(self.rows.get((ref.source, ref.series_id), []), ref,
                                    self.as_of))


class _Builder:
    """One market's components, stale inputs and stores used."""

    def __init__(self, rd: _Reader, m: Market):
        self.rd, self.m, self.as_of = rd, m, rd.as_of
        self.components: list[Component] = []
        self.stale: list[str] = []
        self.used: list[str] = []

    def _touch(self, ref: Ref) -> bool:
        """Note the store `ref` lives in; False if it could not be read."""
        if ref.source in self.rd.failed:
            self.stale.append(self.rd.failed[ref.source])
            return False
        self.used.append(self.rd.read[ref.source])
        return True

    def _short(self, ref: Ref, series: list[Row]) -> None:
        what = f"history from {series[0].date}" if series else "no data"
        self.stale.append(f"{ref.label} ({what})")

    def _aged(self, ref: Ref, last: Row) -> None:
        if (self.as_of - last.date).days > ref.max_age_days:
            self.stale.append(f"{ref.label} (last {last.date})")

    def _rows(self, ref: Ref) -> list[Row] | None:
        """Known rows of `ref`; None if its store could not be read."""
        return self.rd.series(ref) if self._touch(ref) else None

    def first(self, refs: Sequence[Ref]) -> tuple[Ref, list[Row]] | None:
        """The first ref with known rows; earlier refs without are named stale."""
        for ref in refs:
            rows = self._rows(ref)
            if rows:
                self._aged(ref, rows[-1])
                return ref, rows
            if rows is not None:
                self._short(ref, rows)
        return None

    def spec(self, s: Spec) -> None:
        """The first ref whose history is long enough for the spec's window; refs before it
        are named stale."""
        for ref in s.refs:
            rows = self._rows(ref)
            if rows is None:
                continue
            sid = ref.series_id
            if s.minus and rows:
                short = self.first(s.minus)
                if short is None:
                    return
                rows, sid = _spread(rows, short[1]), f"{sid}-{short[0].series_id}"
            got = _measure(s, rows)
            if got is None:
                self._short(ref, rows)
                continue
            self._aged(ref, rows[-1])
            value, detail = got
            self.components.append(Component(
                s.name, self.rd.read[ref.source], sid, value, _direction(value, s.band),
                rows[-1], f"{s.what} {detail}"))
            return

    def fx(self) -> tuple[list[Row], Ref] | None:
        spec = self.m.fx
        if spec is None:
            return None
        base = self.first((spec.base,))
        if base is None:
            return None
        if spec.leg is None:
            return base[1], spec.base
        leg = self.first((spec.leg,))
        if leg is None:
            return None
        rows = cross(base[1], leg[1], f"IDR_PER_{self.m.currency}",
                     local_per_usd=spec.local_per_base)
        return (rows, spec.base) if rows else None


def _measure(s: Spec, rows: list[Row]) -> tuple[float, str] | None:
    """(value, detail) of a spec over its known rows; None when the history is too short."""
    if not rows:
        return None
    last = rows[-1]
    if s.method == VS_MEAN:
        if len(rows) < 5:
            return None
        mean = sum(r.value for r in rows[-5:-1]) / 4
        return (last.value - mean,
                f"{last.value:.2f}% in {last.date:%Y-%m} vs {mean:.2f}% the 4 quarters before")
    if s.method == FLOW:
        if len(rows) < 6 or rows[-6].date < _shift(last.date, -5):
            return None
        now, before = sum(r.value for r in rows[-3:]), sum(r.value for r in rows[-6:-3])
        return (now - before,
                f"{now:,.0f} over 3 months to {last.date:%Y-%m} vs {before:,.0f} the 3 before")
    base = _at(rows, _shift(last.date, -s.months))
    if base is None or base is last:
        return None
    if s.method == PCT:
        if not base.value:
            return None
        value = (last.value / base.value - 1) * 100
        return value, f"{last.value:,.2f} on {last.date}, {value:+.2f}% since {base.date}"
    value = last.value - base.value
    return value, f"{last.value:.2f} on {last.date}, {value:+.2f} since {base.date}"


def _idr_terms(b: _Builder, rows: list[Row], idr_rate: list[Row], local_rate: list[Row]
               ) -> IdrTerms:
    last = rows[-1]

    def change(months: int) -> float | None:
        start = _shift(last.date, -months)
        return fx_change(rows, start, last.date) if rows[0].date <= start else None

    carry = hedge_carry(idr_rate, local_rate, b.as_of, CARRY_YEARS) if local_rate else None
    return IdrTerms(b.m.currency, last.value, last.date, change(3), change(12), carry)


def _reason(m: Market, asset: str, comps: dict[str, Component], idr: IdrTerms | None,
            raw: float, delta: float) -> str:
    gaps = dict(m.gaps)
    names = [s.name for s in m.specs] + ["fx"] + [g for g in gaps if g in WEIGHTS]
    parts = []
    for name in dict.fromkeys(names):
        c = comps.get(name)
        if c is not None:
            parts.append(f"{name} {c.direction * WEIGHTS[name][asset]:+d} ({c.detail})")
        else:
            parts.append(f"{name} n/a" + (f" ({gaps[name]})" if name in gaps else ""))
    total = f"shift {delta:+.0f}" + (f" (raw {raw:+.0f}, capped)" if raw != delta else "")
    return "; ".join(parts) + f". {total}. " + (idr.detail() if idr else "IDR terms n/a")


def _market(rd: _Reader, m: Market, idr_rate: list[Row]) -> MarketOverrides:
    b = _Builder(rd, m)
    for s in m.specs:
        b.spec(s)
    idr = None
    fx = b.fx()
    if fx is not None:
        rows, ref = fx
        local = b.first(m.short_rate) if m.short_rate else None
        idr = _idr_terms(b, rows, idr_rate, local[1] if local else [])
        got = _measure(Spec("fx", f"IDR per {m.currency}", PCT, (ref,), FX_BAND), rows)
        if got is None:
            b._short(ref, rows)
        else:
            value, detail = got
            b.components.append(Component(
                "fx", rd.read[ref.source], rows[-1].series_id, value,
                _direction(value, FX_BAND), rows[-1], f"IDR per {m.currency} {detail}"))
    comps = {c.name: c for c in b.components}
    raw = {a: float(sum(c.direction * WEIGHTS[c.name][a] for c in b.components)) for a in ASSETS}
    stale, used = tuple(dict.fromkeys(b.stale)), tuple(dict.fromkeys(b.used))
    overrides = []
    for a in ASSETS:
        delta = max(-MAX_OVERRIDE, min(MAX_OVERRIDE, raw[a]))
        overrides.append(Override(m.subject, a, rd.as_of, delta,
                                  _reason(m, a, comps, idr, raw[a], delta), used, stale))
    order = {n: i for i, n in enumerate(WEIGHTS)}
    components = tuple(sorted(b.components, key=lambda c: order[c.name]))
    return MarketOverrides(m.subject, rd.as_of, tuple(overrides), components, raw, idr, stale,
                           used, m.gaps)


def _all_refs(markets: Sequence[Market]) -> list[Ref]:
    refs = [IDR_RATE]
    for m in markets:
        for s in m.specs:
            refs += [*s.refs, *s.minus]
        refs += [*m.short_rate, *(m.fx.refs if m.fx else ())]
    return refs


def foreign_overrides(
    as_of: date,
    sources: Mapping[str, Source] | None = None,
    markets: Sequence[Market] = MARKETS,
) -> ForeignOverrides:
    """Layer-2 overrides for each foreign market's stocks, bonds and currency on `as_of`.
    `sources` is keyed by store: fred, tic (both sec-edgar), dbnomics, bisfetcher, jquantster,
    ausdata, singstat, usdidr (the P65 USD/IDR splice); None builds them all from
    `config/sources.yaml`. A store that is missing, locked or not given drops its components and
    is named in `stale_inputs`."""
    rd = _Reader(default_sources() if sources is None else sources, as_of, _all_refs(markets))
    idr_rate = [] if IDR_RATE.source in rd.failed else rd.series(IDR_RATE)
    out = [_market(rd, m, idr_rate) for m in markets]
    stale = tuple(dict.fromkeys(s for m in out for s in m.stale_inputs))
    return ForeignOverrides(as_of, tuple(out), stale, tuple(dict.fromkeys(rd.read.values())))


def default_sources(config: Path = DEFAULT_CONFIG, env: dict | None = None) -> dict[str, Source]:
    """Every store this layer reads, built from `config/sources.yaml`."""
    from assist.sources.ausdata import AusdataSource
    from assist.sources.bisfetcher import BisfetcherSource
    from assist.sources.dbnomics import DbnomicsSource
    from assist.sources.idxscape import IdxscapeSource
    from assist.sources.jquantster import JquantsterSource
    from assist.sources.singstat import SingstatSource
    from assist.sources.usdidr import UsdIdrSource
    from assist.sources.usfin import FredSource, Usfin
    from assist.sources.usfin_tic import TicSource

    env = {**os.environ, **(env or {})}
    usfin = Usfin.from_config(config=config, env=env)
    out: dict[str, Source] = {"fred": FredSource(usfin), "tic": TicSource(usfin)}
    for key, cls in (("dbnomics", DbnomicsSource), ("bisfetcher", BisfetcherSource),
                     ("jquantster", JquantsterSource), ("ausdata", AusdataSource),
                     ("singstat", SingstatSource)):
        out[key] = cls.from_config(config=config, env=env)
    out["usdidr"] = UsdIdrSource(IdxscapeSource.from_config(config=config, env=env),
                                 out["singstat"])
    return out
