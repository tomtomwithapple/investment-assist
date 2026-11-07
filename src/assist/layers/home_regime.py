"""Home (IDN) regime: an Indonesia-only shock the global regime cannot see (PLAN S52, P71).

A hand-set rule on the four P70 inputs (`home_inputs.py`), with the points of open question 7
(fixed 2026-11-07; they change only through an agent review):

- `jci_drawdown_20d`: JCI 7% or more below its 20-day high, 1 point; 12% or more, 2 points.
- `idx_foreign_z`: IDX net foreign 20-day sum, z-score against the trailing 250 days, ≤ −1.5,
  1 point.
- `usdidr_20d`: USD/IDR (JISDOR spliced on the MAS cross) +2% or more over 20 fixings, 1 point;
  +4% or more, 2 points.
- `sbn_non_resident_20d`: non-resident SBN −1.5% or more over 20 DJPPR days, 1 point.

`risk_off` at 2 points or more, else `neutral`: there is no home risk_on. An input counts only if
its newest point is at most 7 days old on `as_of` (`HomeInputs.counted`); a stale or absent input
scores nothing and is `None` in `by_input`, its value kept for the pages.

What the state does (open question 8, P72): home risk_off ladders the adds and trims of IDN
stocks and IDN bonds; a −5pt score shift only if `HOME_SHIFT_ADOPTED`, which is True only once
`check` passes on JCI 20d (`shift_adopted`). The walk-forward of 2026-11-07 did not pass
(insufficient sample: 5 risk_off windows against `MIN_N` 10; docs/results/P71-home-regime.md),
so it is False.

`history`, `check` and `weekly` follow `regime.py`; `ladder_vs_lump` and `input_counts` (and
`classify(..., drop=...)`) are diagnostics only and change nothing.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from assist.eval.placebo import Verdict
from assist.layers import home_inputs as hi
from assist.layers import regime as global_regime
from assist.layers.home_inputs import FEATURES, MAX_AGE, HomeInputs, HomeSources

__all__ = [
    "FLOW_Z_AT",
    "HOME_SHIFT_ADOPTED",
    "JCI_POINTS",
    "MAX_AGE",
    "SBN_AT",
    "STATES",
    "STATE_AT",
    "USDIDR_POINTS",
    "HomeRegime",
    "check",
    "classify",
    "history",
    "home_regime",
    "input_counts",
    "ladder_vs_lump",
    "points",
    "shift_adopted",
    "weekly",
]

JCI_DD, FLOW_Z, USDIDR, SBN = FEATURES
# Open question 7, fixed. (threshold, points), most severe first.
JCI_POINTS = ((-12.0, 2), (-7.0, 1))  # drawdown vs 20-day high, % (≤)
FLOW_Z_AT = -1.5  # z ≤, 1 point
USDIDR_POINTS = ((4.0, 2), (2.0, 1))  # % over 20 fixings (≥)
SBN_AT = -1.5  # % over 20 DJPPR days (≤), 1 point
STATE_AT = 2
STATES = ("risk_off", "neutral")
# Open question 8: the −5pt shift waits on a passing JCI walk-forward (2026-11-07: insufficient
# sample, on 5 / off 61).
HOME_SHIFT_ADOPTED = False

FORMAT = {
    JCI_DD: "JCI {:.1f}% vs 20d high",
    FLOW_Z: "IDX foreign 20d z {:.2f}",
    USDIDR: "USD/IDR {:+.1f}%/20 fixings",
    SBN: "non-resident SBN {:+.1f}%/20d",
}

weekly = global_regime.weekly


def points(feature: str, value: float) -> int:
    """The points one input scores on its value (open question 7)."""
    if feature == JCI_DD:
        return next((p for at, p in JCI_POINTS if value <= at), 0)
    if feature == USDIDR:
        return next((p for at, p in USDIDR_POINTS if value >= at), 0)
    if feature == FLOW_Z:
        return int(value <= FLOW_Z_AT)
    if feature == SBN:
        return int(value <= SBN_AT)
    raise KeyError(feature)


@dataclass(frozen=True)
class HomeRegime:
    """The home state on `as_of`: total points, each input's points (None when not counted:
    absent, stale or dropped), its value and newest date, the scoring drivers, what is stale."""

    as_of: date
    state: str
    points: int
    by_input: dict[str, int | None]
    values: dict[str, float | None] = field(default_factory=dict)
    last: dict[str, date] = field(default_factory=dict)
    drivers: tuple[str, ...] = ()
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def __post_init__(self):
        if self.state not in STATES:
            raise ValueError(f"home regime state {self.state!r} not in {STATES}")


def classify(inp: HomeInputs, drop: Sequence[str] = ()) -> HomeRegime:
    """The rule (module docstring) on `inp`. `drop` leaves inputs out (diagnostic only)."""
    counted = inp.counted()
    by_input: dict[str, int | None] = {}
    drivers = []
    for feat in FEATURES:
        v = counted.get(feat)
        if v is None or feat in drop:
            by_input[feat] = None
            continue
        p = by_input[feat] = points(feat, v)
        if p:
            drivers.append(f"{FORMAT[feat].format(v)} ({p})")
    total = sum(p for p in by_input.values() if p)
    state = "risk_off" if total >= STATE_AT else "neutral"
    return HomeRegime(inp.as_of, state, total, by_input, dict(inp.values), dict(inp.last),
                      tuple(drivers), inp.stale_inputs, inp.sources)


def home_regime(as_of: date, sources: HomeSources | None = None) -> HomeRegime:
    """The home regime on `as_of`, point in time. Never raises for a missing or locked store."""
    return classify(hi.home_inputs(as_of, sources))


def history(dates: Iterable[date], sources: HomeSources | None = None) -> dict[date, HomeInputs]:
    """The inputs on each date, each as known that day (each store read once)."""
    return hi.history(dates, sources)


def check(risk_off: Mapping[date, bool], prices: Iterable[tuple[date, float]], *,
          horizon: int = 20, invert: bool = False, stride: int = 4, block: int = 4,
          n_shuffles: int = 1000, n_controls: int = 20) -> Verdict:
    """Does home `risk_off` precede weaker returns? `regime.check` (the P9 harness,
    `direction=-1`) on the home states; `invert` for USD/IDR into the IDR's own return."""
    return global_regime.check(risk_off, prices, horizon=horizon, invert=invert, stride=stride,
                               block=block, n_shuffles=n_shuffles, n_controls=n_controls)


def shift_adopted(jci: Verdict, idr: Verdict | None = None) -> bool:
    """Open question 8: the −5pt shift is adopted only when the JCI walk-forward passes. The IDR
    verdict is reported beside it and decides nothing."""
    del idr
    return bool(jci.passed)


def ladder_vs_lump(signal_dates: Iterable[date], prices: Iterable[tuple[date, float]], *,
                   tranches: int = 3, spacing_days: int = 10) -> dict[date, float]:
    """Diagnostic: for each signal, the average buy fill of `tranches` equal-IDR tranches
    `spacing_days` calendar days apart against one lump, in % (negative: the ladder bought
    cheaper). The lump and the first tranche fill at the first price strictly after the signal
    (as `regime.entry_returns`); tranche k at the first price on or after that day + k ×
    spacing. Equal IDR per tranche, so the fill is the harmonic mean of the prices; for a trim
    the sign reads the other way. A signal without its last tranche within `MAX_ENTRY_GAP` is
    dropped."""
    pts = sorted(p for p in prices if p[1] is not None)
    days = [d for d, _ in pts]
    gap = global_regime.MAX_ENTRY_GAP
    out = {}
    for s in signal_dates:
        i = bisect_right(days, s)
        if i >= len(pts) or days[i] - s > gap:
            continue
        entry = days[i]
        fills = []
        for k in range(tranches):
            want = entry + timedelta(days=k * spacing_days)
            j = bisect_left(days, want)
            if j >= len(pts) or days[j] - want > gap:
                break
            fills.append(pts[j][1])
        if len(fills) < tranches:
            continue
        fill = len(fills) / sum(1 / p for p in fills)
        out[s] = 100 * (fill / pts[i][1] - 1)
    return out


def input_counts(regimes: Iterable[HomeRegime]) -> dict[str, dict[str, int]]:
    """Diagnostic: per input, on how many dates it was counted (fresh) and how often it scored
    1 and 2 points."""
    out = {f: {"counted": 0, "1": 0, "2": 0} for f in FEATURES}
    for r in regimes:
        for f, p in r.by_input.items():
            if p is None:
                continue
            out[f]["counted"] += 1
            if p:
                out[f][str(p)] += 1
    return out
