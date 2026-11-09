"""Home (IDN) regime inputs, point in time (PLAN S51, P70). Inputs only: the points and the
state are P71's (`home_regime.py`, open question 7).

Four features, each read as known on `as_of` (a row dated on or before `as_of`, and recorded by
then or past its publication lag, `LAG`):

- `jci_drawdown_20d`: JCI (`idxmethod.jci()`: idxscape `index_daily` COMPOSITE from 2021-10-01,
  idx-method's frozen CSV before) close against the highest of its last 20 closes, today's
  included, in % (0 at a new 20-day high, negative below it). A close is known on its own date
  (the stores keep no vintage for it: `index_daily` has none, and the CSV's is its freeze date).
- `idx_foreign_z`: IDX market net foreign, IDR (idxscape `IDX_NET_FOREIGN_IDR`, the day's sum
  of `stock_summary.net_foreign_value_est_idr`, from 2021-10-01). The 20-day sum on the newest
  known day, as a z-score against the 250 20-day sums ending on the 250 days before it (mean and
  sample standard deviation; the current sum is not part of its own baseline). Needs 270 days.
  A day counts once recorded by `as_of` or one day after it traded (P18: the backfill recorded
  every day before 2026-10-12 on that date).
- `usdidr_20d`: USD/IDR (P65 `UsdIdrSource`: JISDOR spliced on the MAS cross) % change over 20
  fixings. A JISDOR fixing counts from the day idxscape recorded it; a MAS cross point, which
  has no vintage, one day after its date (as in the bonds rule).
- `sbn_non_resident_20d`: non-resident holdings of tradable SBN (idxscape
  `SBN.TOTAL.non_resident`, DJPPR, from 2021-01-04) % change over 20 DJPPR days (observations,
  as the other three). A day counts once its file was fetched by `as_of` or 40 days after its
  date (P18: DJPPR posts a month at a time), so in history it is mostly stale, and named so.

An input counts only if its newest known point is at most `MAX_AGE` (7 days) older than `as_of`
(open question 7). A stale input keeps its value in `values` and is named in `stale_inputs`;
`counted()` gives the values P71 may score. Too short a history gives None, named with how much
there is; an unavailable store gives None for its inputs, named, and never raises.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from assist.sources.base import Row, SourceUnavailable
from assist.sources.idxmethod import JCI
from assist.sources.idxscape import IDX_NET_FOREIGN_IDR, JISDOR, SBN_NON_RESIDENT

__all__ = [
    "FEATURES",
    "FLOW_DAYS",
    "MAX_AGE",
    "WINDOW",
    "Z_DAYS",
    "HomeInputs",
    "HomeSources",
    "history",
    "home_inputs",
    "inputs",
]

JCI_DD, FLOW_Z, USDIDR, SBN = (
    "jci_drawdown_20d", "idx_foreign_z", "usdidr_20d", "sbn_non_resident_20d")
FEATURES = (JCI_DD, FLOW_Z, USDIDR, SBN)
WINDOW = 20  # closes, IDX days, fixings, DJPPR days
FLOW_DAYS = WINDOW
Z_DAYS = 250  # 20-day sums in the z-score baseline
MAX_AGE = timedelta(days=7)


@dataclass(frozen=True)
class _Spec:
    store: str  # attribute of HomeSources
    series: str
    lag: timedelta | None  # None: known on its own date, whatever its recorded date says
    back: timedelta  # calendar read-back before as_of
    unit: str  # what `need` counts, for the stale line


SPECS = {
    JCI_DD: _Spec("jci", JCI, None, timedelta(days=60), "closes"),
    FLOW_Z: _Spec("idxscape", IDX_NET_FOREIGN_IDR, timedelta(days=1), timedelta(days=450),
                  "days"),
    USDIDR: _Spec("usdidr", JISDOR, timedelta(days=1), timedelta(days=60), "fixings"),
    SBN: _Spec("idxscape", SBN_NON_RESIDENT, timedelta(days=40), timedelta(days=110), "days"),
}
NEED = {JCI_DD: WINDOW, FLOW_Z: FLOW_DAYS + Z_DAYS, USDIDR: WINDOW + 1, SBN: WINDOW + 1}


@dataclass(frozen=True)
class HomeInputs:
    """As `regime.Inputs`: every feature on `as_of` (None when absent), the newest date behind
    each, what is missing or stale, and the stores read."""

    as_of: date
    values: dict[str, float | None]
    last: dict[str, date] = field(default_factory=dict)
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def fresh(self, feature: str) -> bool:
        """Its newest point is at most `MAX_AGE` old on `as_of`."""
        last = self.last.get(feature)
        return last is not None and self.as_of - last <= MAX_AGE

    def counted(self) -> dict[str, float | None]:
        """The values an input may score with: None where absent or stale."""
        return {f: v if self.fresh(f) else None for f, v in self.values.items()}


@dataclass
class HomeSources:
    """The stores behind the four inputs: JCI (`JciSource`), idxscape (flows and SBN) and the
    P65 USD/IDR splice."""

    jci: Any
    idxscape: Any
    usdidr: Any

    @classmethod
    def default(cls) -> HomeSources:
        from assist.sources.idxmethod import JciSource
        from assist.sources.idxscape import IdxscapeSource
        from assist.sources.singstat import SingstatSource
        from assist.sources.usdidr import UsdIdrSource

        idx = IdxscapeSource.from_config()
        return cls(jci=JciSource.from_config(), idxscape=idx,
                   usdidr=UsdIdrSource(idx, SingstatSource.from_config()))


def _known(rows: Iterable[Row], spec: _Spec, as_of: date) -> list[Row]:
    """`rows` of the spec's series known on `as_of` and inside its read-back, sorted by date
    (the read-back bound keeps `history` identical to one `home_inputs` per date)."""
    out = []
    for r in rows:
        if (r.series_id != spec.series or r.value is None or r.date > as_of
                or r.date < as_of - spec.back):
            continue
        if spec.lag is None:
            out.append(r)
            continue
        recorded = r.as_of is not None and r.as_of <= as_of
        if recorded or r.date + spec.lag <= as_of:
            out.append(r)
    return sorted(out, key=lambda r: r.date)


def _value(feature: str, vals: list[float]) -> float:
    if feature == JCI_DD:
        return 100 * (vals[-1] / max(vals[-WINDOW:]) - 1)
    if feature == FLOW_Z:
        sums = [sum(vals[i - FLOW_DAYS + 1:i + 1]) for i in range(len(vals) - Z_DAYS - 1,
                                                                   len(vals))]
        base = sums[:-1]
        sd = statistics.stdev(base)
        return (sums[-1] - statistics.fmean(base)) / sd if sd else 0.0
    return 100 * (vals[-1] / vals[-1 - WINDOW] - 1)


def inputs(series: Mapping[str, Sequence[Row]], as_of: date,
           names: Mapping[str, str] | None = None, unavailable: Sequence[str] = (),
           sources: Sequence[str] = ()) -> HomeInputs:
    """The four features from rows already read (keyed by feature; later or not yet known rows
    are dropped here). `names` gives each feature's store name for the stale line; features
    whose store was unavailable are None and covered by the `unavailable` lines."""
    names = names or {}
    values: dict[str, float | None] = dict.fromkeys(FEATURES)
    last: dict[str, date] = {}
    stale: list[str] = list(unavailable)
    for feat in FEATURES:
        if feat not in series:
            continue
        spec = SPECS[feat]
        label = f"{names.get(feat, spec.store)} {spec.series}"
        known = _known(series[feat], spec, as_of)
        if not known:
            stale.append(f"{label} (no data)")
            continue
        last[feat] = known[-1].date
        if as_of - known[-1].date > MAX_AGE:
            stale.append(f"{label} (last {known[-1].date})")
        if len(known) < NEED[feat]:
            stale.append(f"{label} ({len(known)} of {NEED[feat]} {spec.unit})")
            continue
        values[feat] = _value(feat, [r.value for r in known])
    return HomeInputs(as_of, values, last, tuple(stale), tuple(sources))


def _read(sources: HomeSources, start_of, end: date):
    """Each store read once over the widest window its features need."""
    series: dict[str, list[Row]] = {}
    names: dict[str, str] = {}
    unavailable: list[str] = []
    read: list[str] = []
    for store in dict.fromkeys(s.store for s in SPECS.values()):
        feats = [f for f, s in SPECS.items() if s.store == store]
        src = getattr(sources, store)
        start = min(start_of(SPECS[f]) for f in feats)
        try:
            rows = src.rows([SPECS[f].series for f in feats], start=start, end=end)
        except SourceUnavailable as e:
            unavailable.append(e.stale_input)
            continue
        name = src.name
        read.append(name)
        for f in feats:
            series[f] = [r for r in rows if r.series_id == SPECS[f].series]
            names[f] = name
    return series, names, unavailable, read


def home_inputs(as_of: date, sources: HomeSources | None = None) -> HomeInputs:
    """The four inputs on `as_of`, point in time. Never raises for a missing or locked store."""
    sources = sources or HomeSources.default()
    series, names, unavailable, read = _read(sources, lambda s: as_of - s.back, as_of)
    return inputs(series, as_of, names, unavailable, read)


def history(dates: Iterable[date], sources: HomeSources | None = None) -> dict[date, HomeInputs]:
    """`home_inputs` on each date, each as known that day, reading each store once."""
    dates = list(dates)
    if not dates:
        return {}
    sources = sources or HomeSources.default()
    first, end = min(dates), max(dates)
    series, names, unavailable, read = _read(sources, lambda s: first - s.back, end)
    return {d: inputs(series, d, names, unavailable, read) for d in dates}
