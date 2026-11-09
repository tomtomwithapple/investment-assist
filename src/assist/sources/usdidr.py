"""USD/IDR for the IDN bonds rule (PLAN S46, P65): JISDOR spliced on the MAS cross.

One series, served as rows under the id `JISDOR` so the rule reads it as it read idxscape:

- JISDOR (idxscape `fx_rate`, BI's daily fixing) from its first fixing, with its own vintage
  (`as_of` = the day idxscape recorded it);
- before that, the MAS cross USD/SGD ÷ IDR/SGD (singstat, daily since 2005), `as_of` None, so
  the rule takes a point only past its one-day lag;
- a JISDOR gap after its first fixing stays a gap: the MAS cross is never borrowed for it.
  idxscape's carried-forward days pass through `carried_forward()` unchanged.

The splice is `paper.usd_idr` (the paper US leg uses the same one); this module only keeps the
legs' vintages, says which leg each point came from (`points()`), and measures the overlap,
the days after the seam on which both legs have a value. The overlap is reported (`seam_line`),
never used. `name` says which legs were used: `MAS+JISDOR`, `JISDOR`, `MAS`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, NamedTuple

from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.idxscape import JISDOR

__all__ = ["FxPoint", "Overlap", "UsdIdrSource"]

NAME = "USD/IDR"
LEG_SOURCE = {"MAS": "singstat", "JISDOR": "idxscape"}


class FxPoint(NamedTuple):
    date: date
    value: float
    leg: str  # "MAS" or "JISDOR"


@dataclass(frozen=True)
class Overlap:
    """Days after the seam with both a JISDOR fixing and a MAS cross, and how far apart."""

    days: int
    max_abs_pct: float | None
    mean_pct: float | None  # JISDOR over MAS, signed


class _Tap:
    """Passes `rows()` through and keeps what it returned (vintages, the MAS legs)."""

    def __init__(self, source: Source):
        self.source, self.name, self.seen = source, source.name, []

    def rows(self, *a, **k) -> list[Row]:
        rows = self.source.rows(*a, **k)
        self.seen = list(rows)
        return rows


class UsdIdrSource:
    """The spliced daily USD/IDR as a `Source` of `JISDOR` rows. The stores are read once, on
    first use; a leg that is missing or locked is named in `stale_inputs`, and only when both
    are does `rows` raise `SourceUnavailable`."""

    def __init__(self, idxscape: Source | None = None, singstat: Source | None = None):
        self._idx, self._sg = idxscape, singstat
        self._built: dict[str, Any] | None = None

    @classmethod
    def from_config(cls) -> UsdIdrSource:
        from assist.sources.idxscape import IdxscapeSource
        from assist.sources.singstat import SingstatSource

        return cls(IdxscapeSource.from_config(), SingstatSource.from_config())

    # ---------------- build ----------------

    def _build(self) -> dict[str, Any]:
        if self._built is not None:
            return self._built
        from assist.paper import usd_idr
        from assist.sources.idxscape import IdxscapeSource
        from assist.sources.singstat import SingstatSource, fx_id

        idx = _Tap(self._idx or IdxscapeSource.from_config())
        sg = _Tap(self._sg or SingstatSource.from_config())
        pts, pieces, stale = usd_idr(idx, sg)
        seam = next((p.first for p in pieces if p.name == "JISDOR"), None)
        vintage = {r.date: r.as_of for r in idx.seen if r.series_id == JISDOR and r.value}
        points = [FxPoint(d, v, "JISDOR" if seam is not None and d >= seam else "MAS")
                  for d, v in pts]
        usd_id, idr_id = fx_id("USD"), fx_id("IDR")
        legs: dict[str, dict[date, float]] = {usd_id: {}, idr_id: {}}
        for r in sg.seen:
            if r.value and r.series_id in legs:
                legs[r.series_id][r.date] = r.value
        cross = {d: v / legs[idr_id][d] for d, v in legs[usd_id].items() if d in legs[idr_id]}
        diffs = [100 * (p.value / cross[p.date] - 1) for p in points
                 if p.leg == "JISDOR" and p.date in cross]
        overlap = Overlap(len(diffs), max(map(abs, diffs)) if diffs else None,
                          sum(diffs) / len(diffs) if diffs else None)
        self._built = {"points": points, "pieces": pieces, "stale": stale, "seam": seam,
                       "vintage": vintage, "overlap": overlap}
        return self._built

    # ---------------- what it is ----------------

    @property
    def name(self) -> str:
        legs = [p.name for p in self.pieces]
        return "+".join(legs) or NAME

    @property
    def pieces(self) -> list:
        """`paper.FxPiece`s, oldest first: name, label, first, last, days."""
        return list(self._build()["pieces"])

    @property
    def seam(self) -> date | None:
        """JISDOR's first fixing (None without JISDOR)."""
        return self._build()["seam"]

    @property
    def overlap(self) -> Overlap:
        return self._build()["overlap"]

    @property
    def stale_inputs(self) -> list[str]:
        return list(self._build()["stale"])

    @property
    def sources(self) -> list[str]:
        """The stores behind the legs used, for attribution."""
        return [LEG_SOURCE[p.name] for p in self.pieces]

    def seam_line(self) -> str:
        """One driver line: the legs, their dates and the overlap check."""
        pieces = self.pieces
        if not pieces:
            return "USD/IDR: no MAS cross and no JISDOR"
        legs = []
        for i, p in enumerate(pieces):
            what = "MAS cross" if p.name == "MAS" else "JISDOR"
            legs.append(f"{'then ' if i else ''}{what} {p.first} → {p.last} ({p.days} days)")
        line = "USD/IDR: " + ", ".join(legs)
        ov = self.overlap
        if ov.days:
            line += (f"; overlap {ov.days} days, JISDOR vs MAS cross max |Δ| "
                     f"{ov.max_abs_pct:.2f}%")
        return line

    def points(self, start: date | None = None, end: date | None = None) -> list[FxPoint]:
        """The spliced series with each point's leg."""
        return [p for p in self._build()["points"]
                if (start is None or p.date >= start) and (end is None or p.date <= end)]

    def carried_forward(self, *a, **k) -> set[date]:
        """idxscape's days BI fixed on D-1 data, unchanged."""
        fn = getattr(self._idx, "carried_forward", None)
        return set(fn(*a, **k)) if fn is not None else set()

    # ---------------- Source ----------------

    def rows(self, series_ids: Sequence[str] | None = None, start: date | None = None,
             end: date | None = None) -> list[Row]:
        if series_ids is not None and JISDOR not in series_ids:
            return []
        b = self._build()
        if not b["points"]:
            stale = b["stale"]
            reasons = {s.rsplit("(", 1)[-1].rstrip(")") for s in stale}
            reason = next((r for r in ("locked", "error") if r in reasons), "missing")
            raise SourceUnavailable(NAME, reason, "; ".join(stale) or "no rows")
        vintage = b["vintage"]
        return [Row(JISDOR, p.date, p.value, vintage.get(p.date) if p.leg == "JISDOR" else None,
                    LEG_SOURCE[p.leg])
                for p in self.points(start, end)]
