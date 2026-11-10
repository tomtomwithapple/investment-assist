"""Entry price, take-profit and stop-loss of a candidate row (PLAN S74, phase N choices 4–6).

Execution guidance on a row the screens already rated: none of it changes which names are
bought or how much.

- **Entry cap** (choice 4): the first tranche is bought at market, but not above the last close
  plus `ENTRY_CAP_PCT`. Later tranches keep sizing's limit (`entry_typical` where below the
  price).
- **Take-profit** (choice 5): the **fair price**, where the row's margin over its required
  return reaches 0. For the dividend screen expected = yield + growth, and the yield falls as
  the price rises, so fair price = price × yield ÷ (required − growth), with required = hurdle +
  the sector's tilt shift. Reaching it means `TP_ACTION`, never "sell all". A style with no
  closed form (GARP's reverse DCF) has no take-profit yet.
- **Stop-loss** (choice 6), two parts. The **thesis stop** is always on: the name fails its
  screen and sizing trims it. The **review price** is `entry_deep`, the name's own
  deep-drawdown level, where below today's price: reaching it flags the name and sells
  nothing, because a price stop that sells has no passed placebo (S69: 1 window of 10).

Hashed by `journal.RULE_GLOBS`; `config()` goes into the payload's `config`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from assist.candidates.costs import tick_size

__all__ = ["ENTRY_CAP_PCT", "THESIS_STOP", "TP_ACTION", "config", "exits", "fair_price"]

VERSION = "0.1.0"
ENTRY_CAP_PCT = 1.0  # % above the last close the first tranche may pay (choice 4, default)
TP_ACTION = "stop adding and trim to half"  # choice 5 (user 2026-11-10)
THESIS_STOP = "sell when it fails its screen"  # choice 6 (user 2026-11-10)
REVIEW_NOTE = "review, do not sell: a price stop has no passed placebo"


def config() -> dict:
    return {"exits_version": VERSION, "entry_cap_pct": ENTRY_CAP_PCT, "take_profit": "fair price",
            "take_profit_action": TP_ACTION, "thesis_stop": THESIS_STOP,
            "review_at": "entry_deep, never sells"}


def _floor_tick(price: float) -> float:
    t = tick_size(price)
    return float(max(t, math.floor(price / t) * t))


def fair_price(style: str, price: float | None, legs: Mapping | None,
               required_pt: float | None) -> float | None:
    """The price at which the row's expected return equals `required_pt`; None when the style
    has no closed form or an input is missing."""
    if style != "dividend_value" or not price or price <= 0 or required_pt is None:
        return None
    legs = legs or {}
    y, g = legs.get("yield_pt"), legs.get("g_pt")
    if y is None or g is None or y <= 0 or required_pt - g <= 0:
        return None
    return price * y / (required_pt - g)


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)


def exits(style: str, price: float | None, legs: Mapping | None, required_pt: float | None,
          levels: Any = None) -> dict:
    """The row's `exits` block. Prices are floored to the IDX tick grid."""
    fair = fair_price(style, price, legs, required_pt)
    deep = _get(levels, "entry_deep") if levels is not None else None
    ok = bool(price and price > 0)
    return {
        "entry_cap": _floor_tick(price * (1 + ENTRY_CAP_PCT / 100)) if ok else None,
        "take_profit": _floor_tick(fair) if fair and ok and fair > price else None,
        "take_profit_basis": "fair_price" if fair and ok and fair > price else "none",
        "take_profit_action": TP_ACTION,
        "thesis_stop": THESIS_STOP,
        "review_at": float(deep) if ok and deep and deep < price else None,
        "review_note": REVIEW_NOTE,
    }
