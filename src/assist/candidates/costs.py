"""IDX execution cost model for layer-4 candidates: fees + tax + spread + impact, in bps.

Ported from idx-method's former `paper/costs.py` (git 9a0ea38^), which replaced three
inconsistent cost answers with one structural model. Only its structural prior is kept: the
fitting code never had real fills to fit on (simulated fills fill at the open print and so fit a
cost of zero), and this repo places no orders.

- **fees** are the published retail online schedule, never fitted: 0.15% buy, 0.15% sell plus
  the 0.10% final sales tax on IDX share sales.
- **spread** is quantised to the IDX tick grid: half the quoted width per side, the book assumed
  one tick wide at `REF_VALUE` daily turnover and `widen` ticks wider per decade below it
  (continuous, no bucket edges). A name at IDR 105 (tick 1) pays ~48bp per side for one tick
  while one at IDR 4,000 (tick 10) pays 12.5bp.
- **impact** is the square-root law on participation, `coef × daily vol × sqrt(order / ADV)`,
  with `med_value_60d` as ADV and `vol_1y` from P19's factors. Without `vol_1y` it falls back to
  Amihud's linear price impact, `amihud × order in IDR bn` (|return| per IDR bn traded), which is
  also reported for every name as a cross-check.

Two changes from idx-method: an unknown turnover is charged as thin (`FLOOR_VALUE`) rather than
spread-free, and an order above `MAX_PARTICIPATION` of ADV is flagged, since the square-root law
understates impact well past that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "FEE_BUY",
    "FEE_SELL",
    "FLOOR_VALUE",
    "LOT",
    "MAX_PARTICIPATION",
    "PRIOR",
    "REF_VALUE",
    "TAX_SELL",
    "Cost",
    "amihud_bps",
    "cost_for",
    "fee_bps",
    "impact_bps",
    "lot_shares",
    "round_trip_bps",
    "spread_bps",
    "tick_bps",
    "tick_size",
]

FEE_BUY = 0.0015
TAX_SELL = 0.001  # final sales tax on IDX share sales
FEE_SELL = 0.0015 + TAX_SELL
REF_VALUE = 20e9  # daily turnover (IDR) at which a name quotes about one tick wide
FLOOR_VALUE = 1e8  # turnover assumed when none is known
MAX_PARTICIPATION = 0.10  # order / ADV above this is flagged
LOT = 100  # IDX board lot, shares
YEAR = 252

PRIOR = {
    "ticks_crossed": 1.0,  # ticks wide at REF_VALUE turnover
    "widen": 0.5,  # extra ticks per decade of turnover below REF_VALUE
    "impact_coef": 1.0,  # Y in Y × sigma × sqrt(participation)
}


def tick_size(price: float) -> int:
    """IDX price fraction for regular-board equities."""
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2000:
        return 5
    if price < 5000:
        return 10
    return 25


def tick_bps(price: float) -> float:
    """One tick in bps of price."""
    if not price or price <= 0:
        return 0.0
    return 1e4 * tick_size(price) / price


def fee_bps(side: str) -> float:
    return 1e4 * (FEE_BUY if side.lower() == "buy" else FEE_SELL)


def _ticks_wide(med_value: float | None, p: dict) -> float:
    mv = med_value if med_value and med_value > 0 else FLOOR_VALUE
    decades_thin = max(0.0, math.log10(REF_VALUE / mv))
    return p["ticks_crossed"] * (1.0 + p["widen"] * decades_thin)


def spread_bps(price: float, med_value: float | None, p: dict = PRIOR) -> float:
    """Half the assumed quoted width, per side."""
    return 0.5 * _ticks_wide(med_value, p) * tick_bps(price)


def amihud_bps(notional: float, amihud: float | None) -> float | None:
    """Linear price impact from Amihud illiquidity (|return| per IDR bn traded)."""
    if amihud is None or not notional:
        return None
    return 1e4 * amihud * notional / 1e9


def impact_bps(
    notional: float,
    med_value: float | None,
    vol_1y: float | None,
    amihud: float | None = None,
    p: dict = PRIOR,
) -> float:
    """Square-root impact; Amihud's linear impact when `vol_1y` is unknown; else zero."""
    if not notional or notional <= 0:
        return 0.0
    if vol_1y is not None and med_value and med_value > 0:
        daily_vol_bps = 1e4 * vol_1y / math.sqrt(YEAR)
        return p["impact_coef"] * daily_vol_bps * math.sqrt(notional / med_value)
    return amihud_bps(notional, amihud) or 0.0


def lot_shares(order_idr: float, price: float) -> int:
    """Shares buyable with `order_idr`, rounded down to whole board lots."""
    if not price or price <= 0:
        return 0
    return int(order_idr // (price * LOT)) * LOT


@dataclass(frozen=True)
class Cost:
    """One order's modelled cost; every component in bps of notional so it can be explained."""

    price: float
    shares: int
    notional: float
    fee_buy_bps: float
    fee_sell_bps: float
    spread_bps: float
    impact_bps: float
    amihud_impact_bps: float | None
    participation: float | None
    flags: tuple[str, ...] = ()

    @property
    def buy_bps(self) -> float:
        return self.fee_buy_bps + self.spread_bps + self.impact_bps

    @property
    def sell_bps(self) -> float:
        return self.fee_sell_bps + self.spread_bps + self.impact_bps

    @property
    def round_trip_bps(self) -> float:
        return self.buy_bps + self.sell_bps


def cost_for(row: dict, order_idr: float, p: dict = PRIOR) -> Cost | None:
    """Cost of buying (and later selling) about `order_idr` of one candidate. `row` carries
    `price`, `med_value_60d`, `vol_1y` and `amihud` (P19's factor columns). None without a price."""
    price = row.get("price")
    if not price or price <= 0:
        return None
    mv, vol, amih = row.get("med_value_60d"), row.get("vol_1y"), row.get("amihud")
    shares = lot_shares(order_idr, price)
    notional = shares * price
    flags = []
    if not mv or mv <= 0:
        flags.append("no_turnover")
    participation = notional / mv if mv and mv > 0 else None
    if participation is not None and participation > MAX_PARTICIPATION:
        flags.append("over_participation")
    if shares == 0:
        flags.append("below_one_lot")
    return Cost(
        price=float(price),
        shares=shares,
        notional=float(notional),
        fee_buy_bps=fee_bps("buy"),
        fee_sell_bps=fee_bps("sell"),
        spread_bps=spread_bps(price, mv, p),
        impact_bps=impact_bps(notional, mv, vol, amih, p),
        amihud_impact_bps=amihud_bps(notional, amih),
        participation=participation,
        flags=tuple(flags),
    )


def round_trip_bps(row: dict, order_idr: float, p: dict = PRIOR) -> float | None:
    c = cost_for(row, order_idr, p)
    return c.round_trip_bps if c else None
