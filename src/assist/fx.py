"""IDR returns of foreign assets, hedged vs unhedged. Pure functions over `Row` series; no I/O.

CLAUDE.md: foreign stocks and bonds are overweight only if the edge survives the expected FX move.
`fx_edge` is that test. Conventions:

- An FX series is a price of one foreign unit in the other currency: JISDOR is IDR per USD.
  `cross` builds IDR per local unit through USD when there is no direct IDR quote
  (IDR/USD ÷ local/USD, or × USD/local for EUR, AUD, GBP-style quotes, `local_per_usd=False`).
- `fx_move` is the change in IDR per local unit over the horizon: +5% means the local currency
  gained 5% against IDR, which adds to an unhedged IDR return.
- Returns and rates are fractions (0.0575), over the horizon for returns and per year for rates.
  Rate `Row`s are percent per year as the stores publish them (BIS `5.75`); `hedge_carry`
  divides by 100.
- Unhedged: (1 + r_local)(1 + fx_move) − 1.
- Hedged (covered interest parity, simple interest for the horizon): selling the local currency
  forward earns the forward premium (1 + i_IDR·T)/(1 + i_local·T) − 1, so the hedged return is
  (1 + r_local)(1 + premium) − 1 ≈ r_local + (i_IDR − i_local)·T. It assumes the whole end value
  is hedged at the start, i.e. r_local is known; for a risky asset it is an approximation.
- Uncovered parity says the same premium is the expected local appreciation (`uip_expected_move`):
  with no FX view, hedged and unhedged are equal in expectation, and the hedge removes the variance.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from assist.sources.base import Row

__all__ = [
    "MAX_GAP_DAYS",
    "FxEdge",
    "breakeven_fx_move",
    "cross",
    "forward_premium",
    "fx_change",
    "fx_edge",
    "hedge_carry",
    "hedged_idr_return",
    "horizon_changes",
    "level_at",
    "to_idr",
    "uip_expected_move",
    "unhedged_idr_return",
]

MAX_GAP_DAYS = 7  # a leg older than this on the other leg's date is no match (doctor's stale limit)


# ---------------- series helpers ----------------


class _Series:
    """Non-null rows of one series sorted by date, for as-of lookups."""

    def __init__(self, rows: Sequence[Row]):
        self.rows = sorted((r for r in rows if r.value is not None), key=lambda r: r.date)
        self.dates = [r.date for r in self.rows]

    def at(self, d: date, max_age_days: int | None = None) -> Row | None:
        i = bisect.bisect_right(self.dates, d) - 1
        if i < 0:
            return None
        r = self.rows[i]
        if max_age_days is not None and (d - r.date).days > max_age_days:
            return None
        return r


def level_at(rows: Sequence[Row], d: date, max_age_days: int | None = None) -> float | None:
    """The last non-null value on or before `d` (None if none, or older than `max_age_days`)."""
    r = _Series(rows).at(d, max_age_days)
    return None if r is None else r.value


def fx_change(rows: Sequence[Row], start: date, end: date) -> float | None:
    """level(end) / level(start) − 1, levels as of each date; None if either is unknown."""
    s = _Series(rows)
    a, b = s.at(start), s.at(end)
    if a is None or b is None or not a.value:
        return None
    return b.value / a.value - 1


def horizon_changes(rows: Sequence[Row], days: int) -> list[float]:
    """Every overlapping `days`-calendar-day change in the series (for an adverse-move quantile).
    The end level is the last one on or before d + days; pairs past the last date are left out."""
    s = _Series(rows)
    if not s.rows:
        return []
    last = s.dates[-1]
    out = []
    for r in s.rows:
        end = r.date + timedelta(days=days)
        if end > last or not r.value:
            continue
        out.append(s.at(end).value / r.value - 1)
    return out


def _join(base: Sequence[Row], other: Sequence[Row], max_gap_days: int) -> list[tuple[Row, Row]]:
    o = _Series(other)
    pairs = []
    for b in _Series(base).rows:
        m = o.at(b.date, max_gap_days)
        if m is not None:
            pairs.append((b, m))
    return pairs


def _as_of(a: Row, b: Row) -> date | None:
    known = [d for d in (a.as_of, b.as_of) if d is not None]
    return max(known) if known else None


def cross(
    idr_per_usd: Sequence[Row],
    local_vs_usd: Sequence[Row],
    series_id: str = "IDR_PER_LOCAL",
    local_per_usd: bool = True,
    max_gap_days: int = MAX_GAP_DAYS,
) -> list[Row]:
    """IDR per local unit via USD, on the dates of `idr_per_usd` (e.g. JISDOR). The local leg is
    taken as of each date, at most `max_gap_days` old. `local_per_usd=False` for USD-per-local
    quotes (EUR, AUD). `as_of` is the later of the two legs'."""
    out = []
    for a, b in _join(idr_per_usd, local_vs_usd, max_gap_days):
        if not b.value:
            continue
        v = a.value / b.value if local_per_usd else a.value * b.value
        out.append(Row(series_id, a.date, v, _as_of(a, b), f"{a.source}+{b.source}"))
    return out


def to_idr(
    prices: Sequence[Row], idr_per_local: Sequence[Row], max_gap_days: int = MAX_GAP_DAYS
) -> list[Row]:
    """A local-currency price series in IDR (`<series_id>_IDR`), on the price dates, with the
    rate as of each date at most `max_gap_days` old."""
    return [
        Row(
            f"{p.series_id}_IDR",
            p.date,
            p.value * fxr.value,
            _as_of(p, fxr),
            f"{p.source}+{fxr.source}",
        )
        for p, fxr in _join(prices, idr_per_local, max_gap_days)
    ]


# ---------------- returns ----------------


def unhedged_idr_return(r_local: float, fx_move: float) -> float:
    """(1 + r_local)(1 + fx_move) − 1, `fx_move` the change in IDR per local unit."""
    return (1 + r_local) * (1 + fx_move) - 1


def forward_premium(i_idr: float, i_local: float, years: float) -> float:
    """What a forward sale of the local currency earns over `years` (simple interest, fractions):
    (1 + i_IDR·T)/(1 + i_local·T) − 1 ≈ (i_IDR − i_local)·T. Negative when IDR rates are lower."""
    return (1 + i_idr * years) / (1 + i_local * years) - 1


def uip_expected_move(i_idr: float, i_local: float, years: float) -> float:
    """Uncovered parity: the local currency is expected to gain the rate gap against IDR."""
    return forward_premium(i_idr, i_local, years)


def hedged_idr_return(r_local: float, i_idr: float, i_local: float, years: float) -> float:
    """(1 + r_local)(1 + forward premium) − 1 ≈ r_local + (i_IDR − i_local)·T."""
    return (1 + r_local) * (1 + forward_premium(i_idr, i_local, years)) - 1


def hedge_carry(
    idr_rate: Sequence[Row], local_rate: Sequence[Row], as_of: date, years: float
) -> float | None:
    """The forward premium from two policy-rate series in percent per year (e.g. BIS
    `WS_CBPOL.M.ID` vs `WS_CBPOL.M.US`), each as of `as_of`. None if either is unknown."""
    i_idr, i_local = level_at(idr_rate, as_of), level_at(local_rate, as_of)
    if i_idr is None or i_local is None:
        return None
    return forward_premium(i_idr / 100, i_local / 100, years)


def breakeven_fx_move(r_local: float, r_idr: float) -> float:
    """The fx_move at which the unhedged return equals the IDR alternative:
    (1 + r_idr)/(1 + r_local) − 1. A local fall worse than this kills the unhedged edge."""
    return (1 + r_idr) / (1 + r_local) - 1


# ---------------- the overweight test ----------------


@dataclass(frozen=True)
class FxEdge:
    """A foreign asset's IDR return, hedged and unhedged, against an IDR alternative (e.g. the
    SBN yield over the same horizon). `hedged` is None when no rates were given."""

    r_local: float
    r_idr: float
    expected_fx_move: float
    unhedged: float
    hedged: float | None
    margin: float
    years: float

    @property
    def best(self) -> str | None:
        """`hedged` or `unhedged`, whichever returns more and beats r_idr + margin; else None."""
        options = [("unhedged", self.unhedged)]
        if self.hedged is not None:
            options.append(("hedged", self.hedged))
        name, value = max(options, key=lambda o: o[1])
        return name if value - self.r_idr > self.margin else None

    @property
    def survives(self) -> bool:
        return self.best is not None

    @property
    def edge(self) -> float:
        """The better IDR return minus the IDR alternative."""
        best = self.unhedged if self.hedged is None else max(self.unhedged, self.hedged)
        return best - self.r_idr

    @property
    def breakeven_fx_move(self) -> float:
        return breakeven_fx_move(self.r_local, self.r_idr)

    def detail(self) -> str:
        hedged = "n/a" if self.hedged is None else f"{self.hedged:+.2%}"
        verdict = f"survives {self.best}" if self.survives else "does not survive"
        return (
            f"IDR return unhedged {self.unhedged:+.2%} (fx {self.expected_fx_move:+.2%}),"
            f" hedged {hedged} vs IDR {self.r_idr:+.2%}: edge {self.edge:+.2%}, {verdict}"
            f" (breakeven fx {self.breakeven_fx_move:+.2%})"
        )


def fx_edge(
    r_local: float,
    r_idr: float,
    expected_fx_move: float,
    i_idr: float | None = None,
    i_local: float | None = None,
    years: float = 1.0,
    margin: float = 0.0,
) -> FxEdge:
    """Does a foreign asset's edge over the IDR alternative survive the expected FX move?

    `r_local` and `r_idr` are returns over the horizon (`years`), `expected_fx_move` the expected
    change in IDR per local unit over it, `i_idr`/`i_local` per-year rates for the hedge (give
    both or neither). The edge survives when the better of hedged and unhedged beats
    `r_idr + margin`."""
    if (i_idr is None) != (i_local is None):
        raise ValueError("give both i_idr and i_local, or neither")
    hedged = None if i_idr is None else hedged_idr_return(r_local, i_idr, i_local, years)
    return FxEdge(
        r_local=r_local,
        r_idr=r_idr,
        expected_fx_move=expected_fx_move,
        unhedged=unhedged_idr_return(r_local, expected_fx_move),
        hedged=hedged,
        margin=margin,
        years=years,
    )
