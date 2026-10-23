"""Layer 3, IDN market signals: who is buying Indonesian stocks and bonds (PLAN S8).

Each signal is a hand-set rule on one series, read point in time: only rows dated on or before
`as_of` and known by then, i.e. recorded by `as_of` (`Row.as_of`) or older than the series'
normal publication lag (`LAG`). The lag matters because the stores were backfilled: every IDX
flow day carries 2026-10-06, DJPPR 2026-10-08, KSEI 2026-10-07 and TIC 2026-10-14 (seen
2026-10-23), so `Row.as_of` alone would hide all history from a backtest. For the same reason TIC
is read as latest, not through sec-edgar's `tic_as_of` vintage (empty before its backfill).
Directions are +1 (inflow), -1 (outflow), 0 (inside
the dead band); the bands are hand-set and stay so until a rule using them beats its placebo.

- `idx_foreign_flow` (stocks): idxscape `IDX_NET_FOREIGN_IDR`, IDR sum over the last 20 IDX
  days; the detail adds the USD sum (`IDX_NET_FOREIGN_USD`, same-day JISDOR).
- `sbn_non_resident_change` (bonds): idxscape `SBN.TOTAL.non_resident` (DJPPR), IDR change over
  4 weeks; the detail adds the non-resident share of tradable SBN (`SBN.TOTAL.total`).
- `ksei_foreign_share` (stocks): kseistat `KSEI.sum.foreign_pct`, pt change over 3 month-ends;
  the detail adds the equal-weight view.
- `tic_us_equity_net` (stocks), `tic_us_bond_net` (bonds): sec-edgar TIC `us_lt_eqty_net_42218`
  and `us_lt_bond_net_42218`, US investors' net purchases in US$ mn over the last 3 months.

The IDX flow is idxscape's estimate (net foreign shares x close), and its USD sum skips days with
no JISDOR rate (counted as gaps, never filled), as idxscape's J8 overlay does. A series too short
for its window gives no signal; one whose newest point is older than its freshness limit still
gives one. Both, like an unavailable store, are named in `stale_inputs`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from assist.layers.types import Signal
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.idxscape import (
    IDX_NET_FOREIGN_IDR,
    IDX_NET_FOREIGN_USD,
    SBN_NON_RESIDENT,
    SBN_TOTAL,
    IdxscapeSource,
)
from assist.sources.kseistat import FOREIGN_PCT_EQUAL, FOREIGN_PCT_SUM, KseistatSource
from assist.sources.usfin_tic import INDONESIA, TicSource

__all__ = [
    "FLOW_BAND_IDR",
    "FLOW_DAYS",
    "KSEI_BAND_PT",
    "SBN_BAND_IDR",
    "TIC_BAND_USD_MN",
    "IdnSignals",
    "idn_signals",
]

SUBJECT = "IDN"
FLOW_DAYS = 20  # IDX trading days
FLOW_BAND_IDR = 1e12  # IDR 1T over 20 days
SBN_LOOKBACK = timedelta(weeks=4)
SBN_BAND_IDR = 2e12  # IDR 2T over 4 weeks
KSEI_LOOKBACK = timedelta(days=85)  # three month-ends back
KSEI_BAND_PT = 0.25  # percentage points over 3 months
TIC_MONTHS = 3
TIC_BAND_USD_MN = 50.0  # US$ 50mn over 3 months
TIC_EQUITY, TIC_BOND = f"us_lt_eqty_net_{INDONESIA}", f"us_lt_bond_net_{INDONESIA}"

# Newest point older than this on `as_of` → named in stale_inputs. KSEI files land ~1 week after
# month end; TIC is published ~6-7 weeks after its month, which is dated the 1st.
# DJPPR posts SBN holdings in monthly files, so a month-old day is its normal cadence.
MAX_AGE = {"daily": timedelta(days=7), "sbn": timedelta(days=47), "ksei": timedelta(days=75),
           "tic": timedelta(days=130)}
# A row dated this long before `as_of` counts as published, whatever its recorded date says.
LAG = {
    IDX_NET_FOREIGN_IDR: timedelta(days=1),  # recorded the same evening
    IDX_NET_FOREIGN_USD: timedelta(days=1),
    SBN_NON_RESIDENT: timedelta(days=40),  # DJPPR files cover a month, posted ~a week after
    SBN_TOTAL: timedelta(days=40),
    FOREIGN_PCT_SUM: timedelta(days=14),  # KSEI month-end file, loaded ~a week after
    FOREIGN_PCT_EQUAL: timedelta(days=14),
    TIC_EQUITY: timedelta(days=80),  # month dated the 1st, released ~7 weeks after its end
    TIC_BOND: timedelta(days=80),
}
READ_BACK = {"daily": timedelta(days=120), "monthly": timedelta(days=500)}


@dataclass(frozen=True)
class IdnSignals:
    """Layer 3 for IDN: the signals, the inputs missing or stale, and the stores read."""

    as_of: date
    signals: tuple[Signal, ...]
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def for_asset(self, asset: str) -> list[Signal]:
        return [s for s in self.signals if s.asset == asset]

    def tally(self, asset: str) -> int:
        """Net direction of the asset's signals (inflows minus outflows)."""
        return sum(s.direction for s in self.for_asset(asset))


def _direction(value: float, band: float) -> int:
    return 1 if value > band else -1 if value < -band else 0


def _known(rows: Sequence[Row], as_of: date) -> dict[str, list[Row]]:
    """Rows known on `as_of` (recorded by then, or past their publication lag), per series."""
    out: dict[str, list[Row]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: (r.series_id, r.date)):
        recorded = r.as_of is None or r.as_of <= as_of
        if r.date <= as_of and (recorded or r.date + LAG[r.series_id] <= as_of):
            out[r.series_id].append(r)
    return out


def _base(series: list[Row], before: date) -> Row | None:
    """The last point on or before `before`."""
    return next((r for r in reversed(series) if r.date <= before and r.value is not None), None)


class _Builder:
    def __init__(self, as_of: date):
        self.as_of = as_of
        self.signals: list[Signal] = []
        self.stale: list[str] = []
        self.sources: list[str] = []

    def read(self, source: Source, ids: Sequence[str], back: timedelta) -> dict | None:
        try:
            rows = source.rows(ids, start=self.as_of - back, end=self.as_of)
        except SourceUnavailable as e:
            self.stale.append(e.stale_input)
            return None
        self.sources.append(source.name)
        return _known(rows, self.as_of)

    def fresh(self, source: str, sid: str, last: date, kind: str) -> None:
        if self.as_of - last > MAX_AGE[kind]:
            self.stale.append(f"{source} {sid} (last {last})")

    def short(self, source: str, sid: str, series: list[Row], what: str | None = None) -> None:
        if what is None:
            what = f"history from {series[0].date}" if series else "no data"
        self.stale.append(f"{source} {sid} ({what})")

    def add(self, asset: str, name: str, value: float, band: float, source: str, detail: str):
        self.signals.append(Signal(SUBJECT, asset, self.as_of, name, value,
                                   _direction(value, band), source, detail))


def _idx(b: _Builder, src: Source) -> None:
    found = b.read(src, [IDX_NET_FOREIGN_IDR, IDX_NET_FOREIGN_USD, SBN_NON_RESIDENT, SBN_TOTAL],
                   READ_BACK["daily"])
    if found is None:
        return
    name = src.name
    flow = [r for r in found[IDX_NET_FOREIGN_IDR] if r.value is not None]
    if len(flow) < FLOW_DAYS:
        b.short(name, IDX_NET_FOREIGN_IDR, flow, f"{len(flow)} of {FLOW_DAYS} days")
    else:
        window = flow[-FLOW_DAYS:]
        b.fresh(name, IDX_NET_FOREIGN_IDR, window[-1].date, "daily")
        idr = sum(r.value for r in window)
        usd_by_day = {r.date: r.value for r in found[IDX_NET_FOREIGN_USD]}
        usd = [usd_by_day.get(r.date) for r in window]
        gaps = sum(v is None for v in usd)
        detail = (f"IDR {idr / 1e12:+.2f}T (US$ {sum(v for v in usd if v is not None) / 1e6:+,.0f}m"
                  f", {gaps} JISDOR gaps) net foreign over {FLOW_DAYS} IDX days to"
                  f" {window[-1].date}")
        b.add("stocks", "idx_foreign_flow", idr, FLOW_BAND_IDR, name, detail)

    held = found[SBN_NON_RESIDENT]
    last = next((r for r in reversed(held) if r.value is not None), None)
    base = _base(held, last.date - SBN_LOOKBACK) if last else None
    if base is None:
        b.short(name, SBN_NON_RESIDENT, held)
        return
    b.fresh(name, SBN_NON_RESIDENT, last.date, "sbn")
    change = last.value - base.value
    total = {r.date: r.value for r in found[SBN_TOTAL]}.get(last.date)
    share = f", {100 * last.value / total:.2f}% of tradable SBN" if total else ""
    detail = (f"IDR {change / 1e12:+.2f}T non-resident SBN since {base.date};"
              f" IDR {last.value / 1e12:,.0f}T held on {last.date}{share}")
    b.add("bonds", "sbn_non_resident_change", change, SBN_BAND_IDR, name, detail)


def _ksei(b: _Builder, src: Source) -> None:
    found = b.read(src, [FOREIGN_PCT_SUM, FOREIGN_PCT_EQUAL], READ_BACK["monthly"])
    if found is None:
        return
    series = [r for r in found[FOREIGN_PCT_SUM] if r.value is not None]
    last = series[-1] if series else None
    base = _base(series, last.date - KSEI_LOOKBACK) if last else None
    if base is None:
        b.short(src.name, FOREIGN_PCT_SUM, series)
        return
    b.fresh(src.name, FOREIGN_PCT_SUM, last.date, "ksei")
    change = last.value - base.value
    detail = f"{last.value:.2f}% foreign on {last.date} ({change:+.2f}pt since {base.date}"
    eq = found[FOREIGN_PCT_EQUAL]
    eq_last = next((r for r in eq if r.date == last.date), None)
    eq_base = next((r for r in eq if r.date == base.date), None)
    if eq_last and eq_base and None not in (eq_last.value, eq_base.value):
        detail += f"; equal-weight {eq_last.value:.2f}%, {eq_last.value - eq_base.value:+.2f}pt"
    b.add("stocks", "ksei_foreign_share", change, KSEI_BAND_PT, src.name, detail + ")")


def _month_start(d: date, back: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - back, 12)
    return date(y, m + 1, 1)


def _tic(b: _Builder, src: Source) -> None:
    found = b.read(src, [TIC_EQUITY, TIC_BOND], READ_BACK["monthly"])
    if found is None:
        return
    for sid, asset, name in ((TIC_EQUITY, "stocks", "tic_us_equity_net"),
                             (TIC_BOND, "bonds", "tic_us_bond_net")):
        series = found[sid]
        first = _month_start(series[-1].date, TIC_MONTHS - 1) if series else None
        if first is None or series[0].date > first:
            b.short(src.name, sid, series)
            continue
        window = [r.value for r in series if r.date >= first and r.value is not None]
        if not window:
            b.short(src.name, sid, series, f"no value since {first}")
            continue
        b.fresh(src.name, sid, series[-1].date, "tic")
        total = sum(window)
        detail = (f"US investors' net purchases {total:+,.0f} US$ mn over {first:%b}–"
                  f"{series[-1].date:%b %Y} ({len(window)} of {TIC_MONTHS} months)")
        b.add(asset, name, total, TIC_BAND_USD_MN, src.name, detail)


def idn_signals(
    as_of: date,
    idxscape: Source | None = None,
    kseistat: Source | None = None,
    tic: Source | None = None,
) -> IdnSignals:
    """Layer-3 signals for IDN on `as_of`. Sources default to the configured stores; one that is
    missing or locked drops its signals and is named in `stale_inputs`, never raised."""
    b = _Builder(as_of)
    steps: list[tuple[Callable[[_Builder, Source], None], Callable[[], Source], Source | None]] = [
        (_idx, IdxscapeSource.from_config, idxscape),
        (_ksei, KseistatSource.from_config, kseistat),
        (_tic, TicSource, tic),
    ]
    for step, default, source in steps:
        step(b, source if source is not None else default())
    return IdnSignals(as_of, tuple(b.signals), tuple(b.stale), tuple(b.sources))
