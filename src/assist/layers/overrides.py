"""Layer 2, IDN overrides: is the economy speeding up or slowing now? (PLAN S7)

Five hand-set momentum components, each a change in one series read point in time, with a
direction of +1 (rising), -1 (falling) or 0 (inside its dead band):

- `growth`: bps-looker `BPS_GDP_YOY`, latest real GDP y/y minus the mean of the 4 quarters before.
- `cli`: dbnomics `idn.cli` (OECD composite leading indicator), change over 3 months.
- `inflation`: bps-looker `BPS_CPI_YOY` (dbnomics `idn.cpi.yoy` when bps-looker has none),
  change in CPI y/y over 3 months; the detail sets the level against BI's 2.5 ± 1% target.
- `trade`: bps-looker `BPS_TRADE_BALANCE_USD_MN`, last 3 months' sum minus the 3 before.
- `bi_rate`: bisfetcher `WS_CBPOL.M.ID`, change over 6 months (+1 = hiking).

Each asset's shift is the sum of `WEIGHTS[component][asset] x direction`, clamped to ±10
(`MAX_OVERRIDE`); `apply` shifts a layer-1 score by it and keeps it in 0..100. The weights are
hand-set and must not move a stance until the rule using them beats its placebo.

A row counts as known on `as_of` if it was recorded by then (`Row.as_of`) or is older than the
series' publication lag (`LAG`): bps-looker stamps every month with the variable's last update
(all of 2024-2026 carry 2026-10-01, seen 2026-10-23) and dbnomics keeps no vintage at all, so
`Row.as_of` alone would leak or hide history in a backtest. A store that is missing or locked,
a series too short for its window and a newest point older than `MAX_AGE` are named in
`stale_inputs`, never raised. satudatascape holds no ready macro series yet: it is only probed,
so its absence shows in `stale_inputs`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from assist.layers.types import MAX_OVERRIDE, AssetScore, Override
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.bisfetcher import BI_RATE_M, BisfetcherSource
from assist.sources.bpslooker import CPI_YOY, GDP_YOY, TRADE_BALANCE, BpsLookerSource
from assist.sources.dbnomics import DbnomicsSource
from assist.sources.satudatascape import SatudatascapeSource

__all__ = [
    "BANDS",
    "CLI",
    "DBN_CPI",
    "WEIGHTS",
    "Component",
    "IdnOverrides",
    "apply",
    "idn_overrides",
]

SUBJECT = "IDN"
ASSETS = ("stocks", "bonds", "currency")
CLI, DBN_CPI = "idn.cli", "idn.cpi.yoy"
BI_TARGET = (1.5, 3.5)  # BI's 2.5 ± 1% CPI target

# Points of layer-1 score per unit of direction (+1 = the series is rising).
WEIGHTS = {
    "growth": {"stocks": 3, "bonds": -1, "currency": 1},
    "cli": {"stocks": 3, "bonds": -1, "currency": 1},
    "inflation": {"stocks": -1, "bonds": -3, "currency": -1},
    "trade": {"stocks": 1, "bonds": 1, "currency": 3},
    "bi_rate": {"stocks": -2, "bonds": -3, "currency": 1},
}
BANDS = {
    "growth": 0.25,  # pt of GDP y/y
    "cli": 0.2,  # index points
    "inflation": 0.3,  # pt of CPI y/y
    "trade": 1500.0,  # US$ mn over 3 months
    "bi_rate": 0.125,  # pt
}
# A row dated this long before `as_of` counts as published, whatever its recorded date says.
# Months and quarters are dated on their first day.
LAG = {
    CPI_YOY: timedelta(days=35),  # BPS releases CPI on the 1st working day after the month
    DBN_CPI: timedelta(days=45),
    TRADE_BALANCE: timedelta(days=50),  # mid-month after next
    GDP_YOY: timedelta(days=130),  # ~5 weeks after the quarter ends
    BI_RATE_M: timedelta(days=35),  # end-of-month rate
    CLI: timedelta(days=45),  # OECD releases ~2 weeks after the month
}
MAX_AGE = {
    CPI_YOY: timedelta(days=70),
    DBN_CPI: timedelta(days=80),
    TRADE_BALANCE: timedelta(days=100),
    GDP_YOY: timedelta(days=230),
    BI_RATE_M: timedelta(days=70),
    CLI: timedelta(days=90),
}
READ_BACK = timedelta(days=800)
LATEST = {"gdp_yoy": GDP_YOY, "cli": CLI, "trade_balance": TRADE_BALANCE, "bi_rate": BI_RATE_M}


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
class IdnOverrides:
    """Layer 2 for IDN: one Override per asset, the components behind them, the uncapped sums,
    the latest known value per input, the inputs missing or stale, and the stores read."""

    as_of: date
    overrides: tuple[Override, ...]
    components: tuple[Component, ...]
    raw: dict[str, float]
    inputs: dict[str, Row]
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def for_asset(self, asset: str) -> Override | None:
        return next((o for o in self.overrides if o.asset == asset), None)

    def component(self, name: str) -> Component | None:
        return next((c for c in self.components if c.name == name), None)

    def latest(self, name: str) -> Row | None:
        """Newest known point of `cpi_yoy`, `gdp_yoy`, `cli`, `trade_balance` or `bi_rate`."""
        return self.inputs.get(name)


def apply(score: AssetScore | float, override: Override | None) -> float:
    """The layer-1 score shifted by the override, kept in 0..100."""
    base = score.score if isinstance(score, AssetScore) else float(score)
    shift = override.delta if override is not None else 0.0
    return min(100.0, max(0.0, base + shift))


def _direction(value: float, band: float) -> int:
    return 1 if value > band else -1 if value < -band else 0


def _known(rows: Sequence[Row], as_of: date) -> dict[str, list[Row]]:
    """Rows with a value known on `as_of`, per series, oldest first."""
    out: dict[str, list[Row]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: (r.series_id, r.date)):
        recorded = r.as_of is not None and r.as_of <= as_of
        published = recorded or r.date + LAG[r.series_id] <= as_of
        if r.value is not None and r.date <= as_of and published:
            out[r.series_id].append(r)
    return out


def _months_back(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, m + 1, 1)


def _at(series: list[Row], when: date) -> Row | None:
    """The last point on or before `when`."""
    return next((r for r in reversed(series) if r.date <= when), None)


class _Builder:
    def __init__(self, as_of: date):
        self.as_of = as_of
        self.components: list[Component] = []
        self.inputs: dict[str, Row] = {}
        self.stale: list[str] = []
        self.sources: list[str] = []

    def read(self, source: Source, ids: Sequence[str]) -> dict[str, list[Row]] | None:
        try:
            rows = source.rows(list(ids), start=self.as_of - READ_BACK, end=self.as_of)
        except SourceUnavailable as e:
            self.stale.append(e.stale_input)
            return None
        self.sources.append(source.name)
        return _known(rows, self.as_of)

    def short(self, source: str, sid: str, series: list[Row]) -> None:
        what = f"history from {series[0].date}" if series else "no data"
        self.stale.append(f"{source} {sid} ({what})")

    def add(self, name: str, source: str, last: Row, value: float, detail: str) -> None:
        if self.as_of - last.date > MAX_AGE[last.series_id]:
            self.stale.append(f"{source} {last.series_id} (last {last.date})")
        self.components.append(Component(name, source, last.series_id, value,
                                         _direction(value, BANDS[name]), last, detail))

    def component_named(self, name: str) -> Component | None:
        return next((c for c in self.components if c.name == name), None)

    def change(self, name: str, source: str, sid: str, series: list[Row], months: int,
               fmt: str, note: str = "") -> None:
        """Latest point minus the one `months` back (or the last before it)."""
        last = series[-1] if series else None
        base = _at(series, _months_back(last.date, months)) if last else None
        if base is None:
            self.short(source, sid, series)
            return
        value = last.value - base.value
        self.add(name, source, last, value,
                 f"{fmt.format(last.value)} on {last.date}, {value:+.2f} since {base.date}{note}")


def _growth(b: _Builder, src: str, series: list[Row]) -> None:
    if len(series) < 5:
        b.short(src, GDP_YOY, series)
        return
    last, prior = series[-1], [r.value for r in series[-5:-1]]
    mean = sum(prior) / len(prior)
    b.add("growth", src, last, last.value - mean,
          f"GDP {last.value:.2f}% y/y in {last.date:%Y-%m} vs {mean:.2f}% the 4 quarters before")


def _trade(b: _Builder, src: str, series: list[Row]) -> None:
    if len(series) < 6 or series[-6].date < _months_back(series[-1].date, 5):
        b.short(src, TRADE_BALANCE, series)
        return
    now, before = sum(r.value for r in series[-3:]), sum(r.value for r in series[-6:-3])
    b.add("trade", src, series[-1], now - before,
          f"trade balance US$ {now:,.0f}mn over 3 months to {series[-1].date:%Y-%m}"
          f" vs {before:,.0f}mn the 3 before")


def _spans(series: list[Row], months: int) -> bool:
    """The series has a point `months` before its newest (a change can be measured)."""
    return bool(series) and _at(series, _months_back(series[-1].date, months)) is not None


def _inflation(b: _Builder, bps: dict | None, dbn: dict | None) -> None:
    """CPI y/y over 3 months: bps-looker, else dbnomics when bps-looker has none or too little
    for the 3-month window (P85, phase L choice 9: bps-looker's 2022=100 CPI starts 2024-01, so
    2024-02 → 04 had no change). The newest CPI level (`inputs["cpi_yoy"]`, the bonds rule's
    real yield) stays bps-looker's whenever it has one."""
    sid, src, series = CPI_YOY, "bps-looker", (bps or {}).get(CPI_YOY, [])
    if bps is not None and not _spans(series, 3):
        b.short(src, CPI_YOY, series)
    if series:
        b.inputs["cpi_yoy"] = series[-1]
    if not _spans(series, 3) and dbn is not None:
        dseries = dbn.get(DBN_CPI, [])
        if not dseries:
            b.short("dbnomics", DBN_CPI, dseries)
        if dseries or not series:
            sid, src, series = DBN_CPI, "dbnomics", dseries
    if not series:
        return
    b.inputs.setdefault("cpi_yoy", series[-1])
    lo, hi = BI_TARGET
    level = series[-1].value
    where = "above" if level > hi else "below" if level < lo else "inside"
    b.change("inflation", src, sid, series, 3, "CPI {:.2f}% y/y",
             f"; {where} BI's {lo}-{hi}% target")


def _reason(asset: str, b: _Builder, raw: float, delta: float) -> str:
    parts = []
    for name, w in WEIGHTS.items():
        c = b.component_named(name)
        if c is None:
            parts.append(f"{name} n/a")
        else:
            parts.append(f"{name} {c.direction * w[asset]:+d} ({c.detail})")
    total = f"shift {delta:+.0f}" + (f" (raw {raw:+.0f}, capped)" if raw != delta else "")
    return "; ".join(parts) + f". {total}"


def idn_overrides(
    as_of: date,
    bps: Source | None = None,
    bisfetcher: Source | None = None,
    dbnomics: Source | None = None,
    satudatascape: Source | None = None,
) -> IdnOverrides:
    """Layer-2 overrides for IDN stocks, bonds and currency on `as_of`. Sources default to the
    configured stores; one that is missing or locked drops its components and is named in
    `stale_inputs`, never raised."""
    b = _Builder(as_of)
    bps_rows = b.read(bps or BpsLookerSource.from_config(), [CPI_YOY, GDP_YOY, TRADE_BALANCE])
    bis_rows = b.read(bisfetcher or BisfetcherSource.from_config(), [BI_RATE_M])
    dbn_rows = b.read(dbnomics or DbnomicsSource.from_config(), [CLI, DBN_CPI])
    satu = satudatascape or SatudatascapeSource.from_config()
    try:
        satu.rows(start=as_of - READ_BACK, end=as_of)
    except SourceUnavailable as e:
        b.stale.append(e.stale_input)

    for name, rows in (("bps-looker", bps_rows), ("bisfetcher", bis_rows), ("dbnomics", dbn_rows)):
        for key, sid in LATEST.items():
            if rows is not None and rows.get(sid):
                b.inputs[key] = rows[sid][-1]
        if rows is None:
            continue
        if name == "bps-looker":
            _growth(b, name, rows.get(GDP_YOY, []))
            _trade(b, name, rows.get(TRADE_BALANCE, []))
        elif name == "bisfetcher":
            b.change("bi_rate", name, BI_RATE_M, rows.get(BI_RATE_M, []), 6, "BI rate {:.2f}%")
        else:
            b.change("cli", name, CLI, rows.get(CLI, []), 3, "OECD CLI {:.2f}")
    _inflation(b, bps_rows, dbn_rows)

    raw = {a: float(sum(c.direction * WEIGHTS[c.name][a] for c in b.components)) for a in ASSETS}
    stale, sources = tuple(dict.fromkeys(b.stale)), tuple(dict.fromkeys(b.sources))
    overrides = []
    for a in ASSETS:
        delta = max(-MAX_OVERRIDE, min(MAX_OVERRIDE, raw[a]))
        overrides.append(Override(SUBJECT, a, as_of, delta, _reason(a, b, raw[a], delta),
                                  sources, stale))
    order = {n: i for i, n in enumerate(WEIGHTS)}
    components = tuple(sorted(b.components, key=lambda c: order[c.name]))
    return IdnOverrides(as_of, tuple(overrides), components, raw, dict(b.inputs), stale, sources)
