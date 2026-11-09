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

`python -m assist.override_history [--today D] [--start D] [--rows]` replays the real stores
(set ASSIST_SIBLINGS_ROOT) and prints the coverage per component and the summary.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from assist.history import last_month_end, month_ends
from assist.layers.overrides import CLI, DBN_CPI, WEIGHTS, idn_overrides
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.bisfetcher import BI_RATE_M
from assist.sources.bpslooker import CPI_YOY, GDP_YOY, TRADE_BALANCE

__all__ = [
    "ASSETS",
    "COMPONENTS",
    "SCHEMA",
    "START",
    "ComponentPoint",
    "OverrideHistory",
    "OverrideRow",
    "Preloaded",
    "last_month_end",
    "month_ends",
    "replay",
]

SUBJECT = "IDN"
ASSETS = ("stocks", "bonds", "currency")
COMPONENTS = tuple(WEIGHTS)  # growth, cli, inflation, trade, bi_rate
SCHEMA = 1
START = date(2005, 1, 31)  # the MAS USD/IDR cross and BI rate (2005-07) start here
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

    def __init__(self, source: Source, ids: Sequence[str] | None, *, end: date):
        self.source, self.ids, self.end = source, None if ids is None else list(ids), end
        self.name = source.name
        self._rows: list[Row] | None = None
        self._error: SourceUnavailable | None = None
        self._loaded = False

    def _load(self) -> list[Row]:
        if not self._loaded:
            self._loaded = True
            try:
                self._rows = sorted(self.source.rows(self.ids, start=None, end=self.end),
                                    key=lambda r: (r.series_id, r.date))
            except SourceUnavailable as e:
                self._error = e
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

    @property
    def complete(self) -> bool:
        """Every P17 component was computed."""
        return all(c in self.components for c in COMPONENTS)

    def to_dict(self) -> dict:
        return {"as_of": self.as_of.isoformat(), "shift": dict(self.shift),
                "raw": dict(self.raw),
                "components": {n: c.to_dict() for n, c in self.components.items()},
                "missing": list(self.missing), "stale_inputs": list(self.stale_inputs)}

    @classmethod
    def from_dict(cls, d: Mapping) -> OverrideRow:
        return cls(date.fromisoformat(d["as_of"]), dict(d["shift"]), dict(d["raw"]),
                   {n: ComponentPoint.from_dict(c) for n, c in d["components"].items()},
                   tuple(d.get("missing", ())), tuple(d.get("stale_inputs", ())))


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

    def row(self, as_of: date) -> OverrideRow:
        return next(r for r in self.rows if r.as_of == as_of)

    def coverage(self) -> dict[str, dict]:
        """Per component: first and last month computed, months computed and the holes
        (months without it between its first and last)."""
        months = [r.as_of for r in self.rows]
        out = {}
        for name in COMPONENTS:
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

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "subject": self.subject, "store_dates": dict(self.store_dates),
                "rows": [r.to_dict() for r in self.rows]}

    @classmethod
    def from_dict(cls, d: Mapping) -> OverrideHistory:
        return cls(d["subject"], tuple(OverrideRow.from_dict(r) for r in d["rows"]),
                   dict(d.get("store_dates", {})))


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
    args = ap.parse_args(argv)
    h = replay(month_ends(args.start, last_month_end(args.today)), **live_sources())
    print(json.dumps({"coverage": h.coverage(), "summary": h.summary()}, indent=1))
    if args.rows:
        for r in h.rows:
            sh = " ".join(f"{a[0]}{r.shift[a]:+.0f}" for a in ASSETS)
            dirs = " ".join(f"{n}{r.components[n].direction:+d}" if n in r.components
                            else f"{n}:-" for n in COMPONENTS)
            print(f"{r.as_of} {sh:14} {dirs}  {' | '.join(r.missing)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(h.to_dict(), f, indent=1)
            f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
