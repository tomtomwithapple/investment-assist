"""Point-in-time input history of the IDN layer-2 overrides (phase L, PLAN S57, P75).

Plumbing, not a rule (outside the model fingerprint, like `assist.history`): it calls P17's
`idn_overrides` unchanged on every month end, each time with the stores as they were known that
day, and records what the layer computed:

- per asset, the capped shift and the uncapped sum (`shift`, `raw`);
- per component (`growth`, `cli`, `inflation`, `trade`, `bi_rate`) the measured change, its
  direction under P17's bands, the newest point used and its series (inflation reads
  bps-looker CPI once known, dbnomics before);
- the components that could not be computed, as `name: reason` (`missing`), and the stale inputs.

Point in time is P17's own rule (`overrides.LAG`): a row counts on `as_of` if its store
recorded it by then or it is older than its publication lag. Every real store records its
history on one recent date (bps-looker its last update, bisfetcher its fetch, dbnomics nothing),
so in history the lags alone decide. The stores hold one vintage: revisions (BPS GDP and trade,
OECD CLI) are read at today's values, a known look-ahead the phase L plan names.

Each store is read once (`Preloaded`, up to the last month end) and sliced in memory per date,
so 250 month ends take seconds, not the minutes of one read per month. No forward returns and no
verdict here: which returns, horizon and sides the gate tests are phase L choices.

**Forward returns (S58, P76; phase L choice 2).** `idn_returns` gives, per IDN asset and month
end, the return an IDR investor saw over the next `HORIZON` complete month ends, never across a
gap in its price series and never from a month still running on `today`:

- stocks: the JCI month-end close to the close `HORIZON` months later (`history.stock_forward`,
  the P51 stitch, as P66);
- bonds: `bond_returns` on the month-end 10Y (`history.bond_forward` over
  `history.ten_year_months`: the OECD proxy's monthly averages lagged one month, IGSYC closes as
  they stand; nothing across the 2025-01 → 2026-09 hole, as P66/P74);
- currency: the rupiah against the US dollar, USD/IDR(t) / USD/IDR(t+h) − 1 on the P65 splice
  (JISDOR from its first fixing, the MAS cross before), so a rupiah gain is positive.

`with_returns` joins them onto the rows (`OverrideRow.forward`).

`python -m assist.override_history [--today D] [--start D] [--rows] [--returns]` replays the
real stores (set ASSIST_SIBLINGS_ROOT) and prints the coverage per component and the summary.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

from assist.history import (
    HORIZON,
    _complete,
    _forward,
    bond_forward,
    last_month_end,
    month_ends,
    stock_forward,
    ten_year_months,
)
from assist.layers.bonds.idn import DURATION
from assist.layers.overrides import CLI, DBN_CPI, WEIGHTS, idn_overrides
from assist.layers.rules.idn_stocks import month_end_closes
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.bisfetcher import BI_RATE_M
from assist.sources.bpslooker import CPI_YOY, GDP_YOY, TRADE_BALANCE
from assist.sources.idxmethod import JCI
from assist.sources.idxscape import JISDOR

__all__ = [
    "ASSETS",
    "COMPONENTS",
    "FOREIGN",
    "FredVintage",
    "DURATION",
    "HORIZON",
    "ReturnSources",
    "complete_live",
    "currency_forward",
    "expected_components",
    "foreign_replay",
    "idn_build",
    "idn_returns",
    "with_returns",
    "SCHEMA",
    "START",
    "ComponentPoint",
    "OverrideHistory",
    "OverrideRow",
    "Preloaded",
    "last_month_end",
    "live_build",
    "month_ends",
    "replay",
]

SUBJECT = "IDN"
ASSETS = ("stocks", "bonds", "currency")
COMPONENTS = tuple(WEIGHTS)  # growth, cli, inflation, trade, bi_rate
SCHEMA = 2  # 2: forward returns per asset (S58)
START = date(2005, 1, 31)  # the MAS USD/IDR cross and BI rate (2005-07) start here
LOCK_TRIES, LOCK_WAIT = 4, 2.0  # a read that finds its store locked by another reader retries
# The series (and the store) each component reads, for its missing reason.
SERIES = {
    "growth": (GDP_YOY,),
    "cli": (CLI,),
    "inflation": (CPI_YOY, DBN_CPI),
    "trade": (TRADE_BALANCE,),
    "bi_rate": (BI_RATE_M,),
}
STORES = {"growth": ("bps-looker",), "cli": ("dbnomics",),
          "inflation": ("bps-looker", "dbnomics"), "trade": ("bps-looker",),
          "bi_rate": ("bisfetcher",)}
IDS = {"bps": [CPI_YOY, GDP_YOY, TRADE_BALANCE], "bisfetcher": [BI_RATE_M],
       "dbnomics": [CLI, DBN_CPI], "satudatascape": None}


# ---------------- one read per store ----------------


class Preloaded:
    """A store read once (`ids`, everything up to `end`) and sliced in memory, filtering as the
    adapters do (series ids, inclusive dates). An unavailable store raises the same
    `SourceUnavailable` on every call, so each month names it stale as a live read would."""

    def __init__(self, source: Source, ids: Sequence[str] | None, *, end: date,
                 start: date | None = None):
        self.source, self.ids, self.end = source, None if ids is None else list(ids), end
        self.start = start
        self.name = source.name
        self._rows: list[Row] | None = None
        self._error: SourceUnavailable | None = None
        self._loaded = False

    def _load(self) -> list[Row]:
        if not self._loaded:
            self._loaded = True
            for attempt in range(LOCK_TRIES):  # a store locked by another reader: retry
                try:
                    self._rows = sorted(self.source.rows(self.ids, start=self.start,
                                                         end=self.end),
                                        key=lambda r: (r.series_id, r.date))
                    break
                except SourceUnavailable as e:
                    self._error = e
                    if e.reason != "locked" or attempt == LOCK_TRIES - 1:
                        break
                    time.sleep(LOCK_WAIT * (attempt + 1))
            if self._rows is not None:
                self._error = None
        if self._error is not None:
            raise self._error
        return self._rows or []

    def rows(self, series_ids: Sequence[str] | None = None, start: date | None = None,
             end: date | None = None, **_kw) -> list[Row]:
        ids = None if series_ids is None else set(series_ids)
        return [r for r in self._load()
                if (ids is None or r.series_id in ids)
                and (start is None or r.date >= start) and (end is None or r.date <= end)]


# ---------------- rows ----------------


@dataclass(frozen=True)
class ComponentPoint:
    """One component on one month end: the change P17 measured, its direction under P17's band,
    the newest point it used and that point's series and store."""

    value: float
    direction: int
    last: date
    series_id: str
    source: str

    def to_dict(self) -> dict:
        return {"value": self.value, "direction": self.direction,
                "last": self.last.isoformat(), "series_id": self.series_id,
                "source": self.source}

    @classmethod
    def from_dict(cls, d: Mapping) -> ComponentPoint:
        return cls(d["value"], d["direction"], date.fromisoformat(d["last"]), d["series_id"],
                   d["source"])


@dataclass(frozen=True)
class OverrideRow:
    """P17 on one month end, as known that day."""

    as_of: date
    shift: Mapping[str, float]
    raw: Mapping[str, float]
    components: Mapping[str, ComponentPoint]
    missing: tuple[str, ...] = ()  # "component: reason"
    stale_inputs: tuple[str, ...] = ()
    # per asset, the forward return over the history's horizon (None: not known yet, a gap)
    forward: Mapping[str, float | None] = field(default_factory=dict)
    # the components of the market's spec (P17's five for IDN; a P28 market's own, S63)
    expected: tuple[str, ...] = COMPONENTS

    @property
    def complete(self) -> bool:
        """Every component of the market's spec was computed (choice 4)."""
        return all(c in self.components for c in self.expected)

    def to_dict(self) -> dict:
        return {"as_of": self.as_of.isoformat(), "shift": dict(self.shift),
                "raw": dict(self.raw),
                "components": {n: c.to_dict() for n, c in self.components.items()},
                "missing": list(self.missing), "stale_inputs": list(self.stale_inputs),
                "forward": dict(self.forward), "expected": list(self.expected)}

    @classmethod
    def from_dict(cls, d: Mapping) -> OverrideRow:
        return cls(date.fromisoformat(d["as_of"]), dict(d["shift"]), dict(d["raw"]),
                   {n: ComponentPoint.from_dict(c) for n, c in d["components"].items()},
                   tuple(d.get("missing", ())), tuple(d.get("stale_inputs", ())),
                   dict(d.get("forward", {})), tuple(d.get("expected", COMPONENTS)))


def _ym(d: date) -> str:
    return f"{d:%Y-%m}"


def _ranges(days: Sequence[date], months: Sequence[date]) -> list[list[str]]:
    """`days` (a subset of `months`, both month ends in order) as [first, last] month runs."""
    pos = {d: i for i, d in enumerate(months)}
    out: list[list[str]] = []
    prev = None
    for d in days:
        if prev is not None and pos[d] == pos[prev] + 1:
            out[-1][1] = _ym(d)
        else:
            out.append([_ym(d), _ym(d)])
        prev = d
    return out


@dataclass(frozen=True)
class OverrideHistory:
    """P17 for `subject` over its month ends."""

    subject: str
    rows: tuple[OverrideRow, ...]
    store_dates: Mapping[str, str | None] = field(default_factory=dict)
    horizon: int = HORIZON

    def row(self, as_of: date) -> OverrideRow:
        return next(r for r in self.rows if r.as_of == as_of)

    def coverage(self) -> dict[str, dict]:
        """Per component: first and last month computed, months computed and the holes
        (months without it between its first and last)."""
        months = [r.as_of for r in self.rows]
        out = {}
        for name in (self.rows[0].expected if self.rows else COMPONENTS):
            have = [r.as_of for r in self.rows if name in r.components]
            if not have:
                out[name] = {"first": None, "last": None, "months": 0, "holes": []}
                continue
            inside = [d for d in months if have[0] <= d <= have[-1] and d not in set(have)]
            series = sorted({r.components[name].series_id for r in self.rows
                             if name in r.components})
            out[name] = {"first": _ym(have[0]), "last": _ym(have[-1]), "months": len(have),
                         "holes": _ranges(inside, months), "series": series}
        return out

    def complete_from(self) -> date | None:
        """The first month end with every component."""
        return next((r.as_of for r in self.rows if r.complete), None)

    def incomplete_after_start(self) -> list[list[str]]:
        """Months after `complete_from` missing a component, as [first, last] runs."""
        first = self.complete_from()
        if first is None:
            return []
        months = [r.as_of for r in self.rows]
        return _ranges([r.as_of for r in self.rows if r.as_of > first and not r.complete],
                       months)

    def summary(self) -> dict:
        """Months, complete months, and the sign of each asset's shift on the complete months
        (descriptive: no forward return, no verdict)."""
        complete = [r for r in self.rows if r.complete]
        signs = {a: {"up": sum(r.shift[a] > 0 for r in complete),
                     "zero": sum(r.shift[a] == 0 for r in complete),
                     "down": sum(r.shift[a] < 0 for r in complete)} for a in ASSETS}
        first = self.complete_from()
        return {"subject": self.subject,
                "first": _ym(self.rows[0].as_of) if self.rows else None,
                "last": _ym(self.rows[-1].as_of) if self.rows else None,
                "months": len(self.rows), "complete": len(complete),
                "complete_from": _ym(first) if first else None,
                "incomplete_after": self.incomplete_after_start(),
                "shift_signs": signs}

    def return_coverage(self) -> dict[str, dict]:
        """Per asset: the first and last complete month with a forward return, and how many."""
        out = {}
        for a in ASSETS:
            have = [r.as_of for r in self.rows if r.complete and r.forward.get(a) is not None]
            out[a] = {"first": _ym(have[0]) if have else None,
                      "last": _ym(have[-1]) if have else None, "months": len(have)}
        return out

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "subject": self.subject, "horizon": self.horizon,
                "store_dates": dict(self.store_dates),
                "rows": [r.to_dict() for r in self.rows]}

    @classmethod
    def from_dict(cls, d: Mapping) -> OverrideHistory:
        return cls(d["subject"], tuple(OverrideRow.from_dict(r) for r in d["rows"]),
                   dict(d.get("store_dates", {})), d.get("horizon", HORIZON))


# ---------------- replay ----------------


def _missing(name: str, stale: Sequence[str]) -> str:
    keys = (*SERIES[name], *(f"{s} (" for s in STORES[name]))
    hits = [s for s in stale if any(k in s for k in keys)]
    return f"{name}: " + ("; ".join(dict.fromkeys(hits)) or "no data")


def replay(dates: Iterable[date], *, bps: Source, bisfetcher: Source, dbnomics: Source,
           satudatascape: Source, store_dates: Mapping[str, str | None] | None = None,
           progress: Callable[[date], None] | None = None) -> OverrideHistory:
    """P17 on each of `dates`, every store read once up to the last date."""
    days = sorted(dates)
    end = days[-1] if days else date.today()
    pre = {key: Preloaded(src, IDS[key], end=end) for key, src in (
        ("bps", bps), ("bisfetcher", bisfetcher), ("dbnomics", dbnomics),
        ("satudatascape", satudatascape))}
    rows = []
    for day in days:
        if progress is not None:
            progress(day)
        ov = idn_overrides(day, bps=pre["bps"], bisfetcher=pre["bisfetcher"],
                           dbnomics=pre["dbnomics"], satudatascape=pre["satudatascape"])
        comps = {c.name: ComponentPoint(c.value, c.direction, c.last.date, c.series_id, c.source)
                 for c in ov.components}
        missing = tuple(_missing(n, ov.stale_inputs) for n in COMPONENTS if n not in comps)
        rows.append(OverrideRow(day, {o.asset: o.delta for o in ov.overrides}, dict(ov.raw),
                                comps, missing, ov.stale_inputs))
    return OverrideHistory(SUBJECT, tuple(rows), dict(store_dates or {}))


# ---------------- forward returns (S58) ----------------

Month = tuple[int, int]


@dataclass(frozen=True)
class ReturnSources:
    """The price stores the IDN forward returns read (read-only): the JCI (`JciSource`, the P51
    stitch), dbnomics (the OECD 10Y proxy), PHEI (IGSYC) and the P65 USD/IDR splice."""

    jci: Source
    dbnomics: Source
    phei: Source
    usdidr: Source

    @classmethod
    def default(cls) -> ReturnSources:
        from assist.pipeline import IdnSources

        src = IdnSources.default()
        return cls(src.idxmethod, src.dbnomics, src.phei, src.usdidr)


def _read(source: Source, sid: str, end: date) -> list[Row]:
    try:
        return source.rows([sid], end=end)
    except SourceUnavailable:
        return []


def _fx_returns(run: Sequence[tuple[date, float]], h: int) -> list[tuple[date, float]]:
    """USD/IDR(t) / USD/IDR(t+h) − 1: the rupiah's return against the dollar."""
    return [(d, v / run[i + h][1] - 1.0) for i, (d, v) in enumerate(run[:max(0, len(run) - h)])]


def currency_forward(points: Iterable[tuple[date, float]], horizon: int,
                     today: date) -> dict[Month, float]:
    """The rupiah's return against the US dollar from each month-end USD/IDR close to the close
    `horizon` complete months later, only between consecutive months (never across a gap)."""
    return _forward(_complete(points, today), horizon, _fx_returns)


def idn_returns(src: ReturnSources, *, today: date,
                horizon: int = HORIZON) -> dict[str, dict[Month, float]]:
    """Per IDN asset, {(year, month): forward return} as known on `today` (phase L choice 2)."""
    end = today - timedelta(days=1)
    tens = ten_year_months(SimpleNamespace(dbnomics=src.dbnomics, phei=src.phei), end)
    return {"stocks": stock_forward(_read(src.jci, JCI, end), horizon, today),
            "bonds": bond_forward(tens, horizon, today),
            "currency": currency_forward(month_end_closes(_read(src.usdidr, JISDOR, end)),
                                         horizon, today)}


def with_returns(h: OverrideHistory, fwd: Mapping[str, Mapping[Month, float]],
                 horizon: int = HORIZON) -> OverrideHistory:
    """`h` with each row's forward return per asset joined on its month."""
    rows = tuple(dataclasses.replace(r, forward={
        a: fwd.get(a, {}).get((r.as_of.year, r.as_of.month)) for a in ASSETS}) for r in h.rows)
    return dataclasses.replace(h, rows=rows, horizon=horizon)


# ---------------- foreign input history (S63) ----------------

FOREIGN = ("USA", "JPN", "EMU", "AUS", "SGP")
# Choice 13: GDP is the one foreign input with vintages in a store (sec-edgar `fred_as_of`).
VINTAGE_IDS = ("GDPC1",)


def _aus_mas() -> Any:
    """P28's AUS market with IDR per AUD from the MAS cross (IDR per S$ × S$ per AUD), for the
    months before ausdata's RBA AUD/IDR (`FXRIR`, from 2023-01) has a 3-month base (choice 13).
    History only: live keeps RBA's rate."""
    from assist.layers import overrides_foreign as of
    from assist.sources.singstat import fx_id

    fx = of.FxSpec(of.IDR_PER_SGD, of.Ref("singstat", fx_id("AUD"), 1, of.MAS_DAILY),
                   local_per_base=False)
    return dataclasses.replace(of.market("AUS"), fx=fx)


class FredVintage:
    """sec-edgar FRED for the replay: `vintage_ids` (GDPC1) read per date at the vintage known
    on the read's `end` (`fred_as_of`), every other series read once (`Preloaded`; daily market
    series, not revised)."""

    def __init__(self, source: Source, ids: Iterable[str], vintage_ids: Iterable[str], *,
                 end: date, start: date | None = None):
        self.source, self.name = source, source.name
        self.vintage = set(vintage_ids)
        self.pre = Preloaded(source, sorted(set(ids) - self.vintage), end=end, start=start)

    def rows(self, series_ids: Sequence[str] | None = None, start: date | None = None,
             end: date | None = None, **_kw) -> list[Row]:
        ids = list(series_ids) if series_ids is not None else sorted(self.pre.ids or [])
        rest = [i for i in ids if i not in self.vintage]
        out = self.pre.rows(rest, start=start, end=end) if rest else []
        vint = [i for i in ids if i in self.vintage]
        if vint:
            out += self._vintage(vint, start, end)
        return sorted(out, key=lambda r: (r.series_id, r.date))

    def _vintage(self, ids: list[str], start: date | None, end: date | None) -> list[Row]:
        """One read per date; a store locked by another reader is retried (`LOCK_TRIES`)."""
        for attempt in range(LOCK_TRIES):
            try:
                return self.source.rows(ids, start, end, as_of=end)
            except SourceUnavailable as e:
                if e.reason != "locked" or attempt == LOCK_TRIES - 1:
                    raise
                time.sleep(LOCK_WAIT * (attempt + 1))
        return []


def _foreign_missing(m: Any, name: str, stale: Sequence[str],
                     names: Mapping[str, str]) -> str:
    refs = [r for s in m.specs if s.name == name for r in (*s.refs, *s.minus)]
    if name == "fx" and m.fx is not None:
        refs = list(m.fx.refs)
    keys = [*(r.series_id for r in refs), *(f"{r.source} (" for r in refs),
            *(f"{names[r.source]} (" for r in refs if r.source in names)]
    hits = [s for s in stale if any(k in s for k in keys)]
    return f"{name}: " + ("; ".join(dict.fromkeys(hits)) or "no data")


def foreign_replay(dates: Iterable[date], sources: Mapping[str, Source], *,
                   store_dates: Mapping[str, str | None] | None = None,
                   progress: Callable[[date], None] | None = None) -> dict[str, OverrideHistory]:
    """P28 unchanged on each of `dates` for USA, JPN, EMU, AUS and SGP. Every store is read once
    up to the last date (`Preloaded`), except FRED GDPC1 (its vintage per date, `FredVintage`)
    and ausdata (asked per date with `as_of`, as P28 asks it, so a period not yet over is
    skipped). AUS reads the MAS cross for `fx` where RBA's AUD/IDR has no 3-month base."""
    from assist.layers import overrides_foreign as of

    days = sorted(dates)
    end = days[-1] if days else date.today()
    # P28 reads READ_BACK before each date: nothing older is ever asked for
    start = (days[0] if days else end) - of.READ_BACK - timedelta(days=31)
    aus_mas = _aus_mas()
    markets = (*of.MARKETS, aus_mas)
    wanted: dict[str, set[str]] = {}
    for ref in of._all_refs(markets):
        wanted.setdefault(ref.source, set()).add(ref.series_id)
    wrapped: dict[str, Source] = {}
    for key, src in sources.items():
        if key == "fred":
            wrapped[key] = FredVintage(src, wanted.get(key, ()), VINTAGE_IDS, end=end,
                                       start=start)
        elif key == "ausdata":
            wrapped[key] = src
        else:
            wrapped[key] = Preloaded(src, sorted(wanted.get(key, ())), end=end, start=start)
    names = {k: getattr(v, "name", k) for k, v in sources.items()}
    rows: dict[str, list[OverrideRow]] = {s: [] for s in FOREIGN}
    for day in days:
        if progress is not None:
            progress(day)
        fo = of.foreign_overrides(day, wrapped, markets)
        by = {m.subject: mo for m, mo in zip(markets[:-1], fo.markets[:-1], strict=True)}
        if by["AUS"].component("fx") is None:
            by["AUS"] = fo.markets[-1]
        for subject in FOREIGN:
            mo, m = by[subject], of.market(subject)
            if subject == "AUS" and mo is fo.markets[-1]:
                m = aus_mas
            comps = {c.name: ComponentPoint(c.value, c.direction, c.last.date, c.series_id,
                                            c.source) for c in mo.components}
            expected = expected_components(subject)
            missing = tuple(_foreign_missing(m, n, mo.stale_inputs, names) for n in expected
                            if n not in comps)
            rows[subject].append(OverrideRow(day, {o.asset: o.delta for o in mo.overrides},
                                             dict(mo.raw), comps, missing, mo.stale_inputs,
                                             {}, expected))
    return {s: OverrideHistory(s, tuple(rows[s]), dict(store_dates or {})) for s in FOREIGN}


def idn_build(src, day: date) -> OverrideHistory:
    """The IDN override history on every month end `START` → `last_month_end(day)` with its
    forward returns as known on `day`, from a `pipeline.IdnSources` (read-only)."""
    h = replay(month_ends(START, last_month_end(day)), bps=src.bps, bisfetcher=src.bisfetcher,
               dbnomics=src.dbnomics, satudatascape=src.satudatascape)
    ret = ReturnSources(src.idxmethod, src.dbnomics, src.phei,
                        src.usdidr if src.usdidr is not None else src.idxscape)
    return with_returns(h, idn_returns(ret, today=day))


def live_build(subject: str, day: date) -> OverrideHistory:
    """The override history of `subject` on the real stores (read-only), for the gate."""
    if subject != SUBJECT:
        raise ValueError(f"no override history for {subject} yet")
    from assist.pipeline import IdnSources

    return idn_build(IdnSources.default(), day)


def expected_components(subject: str = SUBJECT) -> tuple[str, ...]:
    """Every component of the subject's override spec: P17's five for IDN; for a P28 market its
    specs plus `fx` when it has an FX leg (choice 4: a month missing one is a no_call)."""
    if subject == SUBJECT:
        return COMPONENTS
    from assist.layers.overrides_foreign import market

    m = market(subject)
    return (*(s.name for s in m.specs), *(("fx",) if m.fx is not None else ()))


def complete_live(components: Iterable[str], subject: str = SUBJECT) -> bool:
    """A live reading has every component of the subject's spec (choice 4)."""
    return set(expected_components(subject)) <= set(components)


def live_sources() -> dict[str, Source]:
    """The configured stores P17 reads (read-only)."""
    from assist.sources.bisfetcher import BisfetcherSource
    from assist.sources.bpslooker import BpsLookerSource
    from assist.sources.dbnomics import DbnomicsSource
    from assist.sources.satudatascape import SatudatascapeSource

    return {"bps": BpsLookerSource.from_config(), "bisfetcher": BisfetcherSource.from_config(),
            "dbnomics": DbnomicsSource.from_config(),
            "satudatascape": SatudatascapeSource.from_config()}


# ---------------- CLI (live check) ----------------


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assist.override_history",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--start", type=date.fromisoformat, default=START)
    ap.add_argument("--rows", action="store_true", help="print every row too")
    ap.add_argument("--json", type=str, default=None, help="write the history to this file")
    ap.add_argument("--returns", action="store_true",
                    help="join the forward returns per asset (S58)")
    ap.add_argument("--subject", default=SUBJECT, choices=(SUBJECT, *FOREIGN),
                    help="IDN (P17) or a P28 market (S63)")
    args = ap.parse_args(argv)
    dates = month_ends(args.start, last_month_end(args.today))
    if args.subject == SUBJECT:
        h = replay(dates, **live_sources())
    else:
        from assist.layers.overrides_foreign import default_sources

        h = foreign_replay(dates, default_sources(),
                           progress=lambda d: print(f"  {d}", file=sys.stderr, flush=True)
                           )[args.subject]
    report = {"coverage": h.coverage(), "summary": h.summary()}
    if args.returns and args.subject == SUBJECT:
        h = with_returns(h, idn_returns(ReturnSources.default(), today=args.today))
        report["returns"] = h.return_coverage()
    print(json.dumps(report, indent=1))
    if args.rows:
        for r in h.rows:
            sh = " ".join(f"{a[0]}{r.shift[a]:+.0f}" for a in ASSETS)
            dirs = " ".join(f"{n}{r.components[n].direction:+d}" if n in r.components
                            else f"{n}:-" for n in r.expected)
            fw = " ".join(f"{a[0]}{'-' if r.forward.get(a) is None else f'{r.forward[a]:+.3f}'}"
                          for a in ASSETS) if r.forward else ""
            print(f"{r.as_of} {sh:14} {dirs} {fw}  {' | '.join(r.missing)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(h.to_dict(), f, indent=1)
            f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
