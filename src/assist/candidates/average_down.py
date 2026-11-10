"""Average down on a held name (PLAN S68, phase M): a label on an add the model would make
anyway, never a signal.

Cost basis decides nothing. The test is "would the model buy this today if none were held",
plus room under the caps. A held name is called `average_down` only if it clears every gate, in
order; the first gate it stops at is reported with the reason:

1. **Underwater.** Its price is `UNDERWATER_PCT` (5%) or more below its average cost (choice 3;
   smaller gaps are the buy fee). A label only.
2. **Thesis intact.** A placebo-passing screen ranked and kept it (`net_margin_pt` > 0).
   Otherwise sizing's trim applies and is the reason.
3. **Not a falling knife.** `entry.py`'s status. **Context only** (choice 2): its placebo (S69,
   `eval/dip_gate.py`) came back insufficient, so the status is shown and stops nothing.
4. **Room.** Sizing's own conditions: `vol_1y`, a price and a turnover, a place among its
   sector's capped names by margin, and a holding below the per-name cap.
5. **Money.** The market's budget is above 0 and sizing sized the name. With no budget the name
   is `unfunded` and sized 0 (choice 1): it is not paid for from the same run's trims.
6. **Timing.** Sizing's schedule (a ladder on risk_off or when the stance asks for one, else one
   lump); the later tranches of an average down are limited at `entry_typical` where that is
   below today's price (`limit_tranches`).

`judge` is pure: it reads sizing's result and changes no size. `new_avg_cost` assumes every
tranche fills at today's price and counts the buy fee, as financer's `roll` does. This module is
hashed by `journal.RULE_GLOBS` and `config()` goes into the payload's `config`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from assist.candidates import sizing
from assist.candidates.costs import fee_bps

__all__ = ["GATE3", "GATES", "STATUSES", "UNDERWATER_PCT", "below_cost_pct", "config", "judge",
           "limit_tranches", "new_avg_cost"]

VERSION = "0.1.0"
UNDERWATER_PCT = 5.0  # % below the average cost (phase M choice 3, user 2026-11-10)
GATE3 = "context"  # S69's placebo: insufficient, so the entry status stops nothing (choice 2)
GATES = {1: "underwater", 2: "thesis", 3: "knife", 4: "room", 5: "money"}
STATUSES = ("average_down", "unfunded", "stopped")


def config() -> dict:
    return {"average_down_version": VERSION, "underwater_pct": UNDERWATER_PCT, "gate3": GATE3,
            "unfunded": "sized 0 when the market has no budget"}


def below_cost_pct(price: float | None, avg_cost: float | None) -> float | None:
    """Price against the average cost, % (negative = below cost)."""
    if not price or not avg_cost or price <= 0 or avg_cost <= 0:
        return None
    return 100 * (price / avg_cost - 1)


def new_avg_cost(avg_cost: float, quantity: float, size: Mapping | None) -> float | None:
    """The average cost after the sized tranches, all filled at today's price, buy fee included."""
    if not size:
        return None
    shares = sum(t["shares"] for t in size["tranches"])
    if shares <= 0:
        return None
    paid = sum(t["idr"] for t in size["tranches"]) * (1 + fee_bps("buy") / 1e4)
    return (avg_cost * quantity + paid) / (quantity + shares)


def limit_tranches(tranches: Sequence[Mapping], price: float | None,
                   entry_typical: float | None) -> list[dict]:
    """Gate 6: the first tranche at today's price, each later one limited at `entry_typical`
    when that is below today's price, else unlimited (no `entry_deep`, as P21b)."""
    lim = entry_typical if entry_typical and price and entry_typical < price else None
    return [{**t, "limit": None if i == 0 else lim} for i, t in enumerate(tranches)]


def _room(sym: str, size_rows: Sequence[Mapping], held: Mapping[str, float], value: float,
          caps: Mapping | None) -> str | None:
    """Why sizing would have no room for `sym`, before any budget is split; None = room."""
    c = sizing._caps(caps)
    ok = []
    me = None
    for r in size_rows:
        why = sizing._fails(r)
        if why is None and not (r.get("vol_1y") or 0) > 0:
            why = "no vol_1y"
        if why is None and not (r.get("price") or 0) > 0:
            why = "no price"
        if why is None and not (r.get("med_value_60d") or 0) > 0:
            why = "no turnover (med_value_60d), liquidity unknown"
        if r["symbol"] == sym:
            me = r
            if why:
                return why
        if why is None:
            ok.append(r)
    if me is None:
        return "not a sizing row"
    ok.sort(key=lambda r: (-r["margin_pt"], r["symbol"]))
    sector = me.get("sector")
    cap = sizing._sector_cap(sector, c)
    ahead = [r["symbol"] for r in ok if r.get("sector") == sector][:cap]
    if sym not in ahead:
        return f"sector cap of {cap} names ({sector})"
    if not value > 0:
        return "portfolio value unknown: no per-name cap"
    if held.get(sym, 0.0) >= c["name_pct"] / 100 * value:
        return f"at or over the per-name cap of {c['name_pct']:g}%"
    return None


def _no_budget(stance: Mapping | None) -> str:
    st = stance or {}
    cur, tgt = st.get("current_pct"), st.get("target_pct")
    if st.get("stance") in sizing.NO_ADDS:
        return f"no budget: the stance is {st['stance']}"
    if cur is None or tgt is None:
        return "no budget: no stance or target for this market"
    return f"no budget: {cur:.1f}% held against a target of {tgt:.1f}%"


def judge(*, held: Mapping[str, float], basis: Mapping[str, Any],
          prices: Mapping[str, float | None], kept: Mapping[str, Mapping],
          size_rows: Sequence[Mapping], sizes: Mapping[str, Mapping],
          trims: Sequence[Mapping] = (), excluded: Sequence[Mapping] = (),
          budget_idr: float = 0.0, portfolio_value_idr: float | None = None,
          caps: Mapping | None = None, entry_status: Mapping[str, str] | None = None,
          any_passed: bool = True, stance: Mapping | None = None) -> list[dict]:
    """One verdict per held name, by symbol. `held` is IDR held per symbol; `basis` is
    `undervalued.cost_basis_from` (sym → (avg_cost, quantity)); `prices` today's price; `kept`
    the best row per symbol a passing screen kept; `size_rows`, `sizes`, `trims`, `excluded` and
    `budget_idr` are sizing's inputs and result; `stance` the payload's stance block."""
    value = float(portfolio_value_idr or 0.0)
    trim_why = {t["symbol"]: t["reason"] for t in trims}
    excl_why = {e["symbol"]: e["reason"] for e in excluded}
    status = entry_status or {}
    out = []
    for sym in sorted(held):
        b = basis.get(sym)
        avg, qty = (float(b[0]), float(b[1])) if b else (None, None)
        price = prices.get(sym)
        below = below_cost_pct(price, avg)
        v = {"symbol": sym, "status": "stopped", "gate": 1, "reason": "",
             "avg_cost": avg, "quantity": qty, "price": price, "below_cost_pct": below,
             "new_avg_cost": None, "entry_status": status.get(sym)}
        out.append(v)
        if below is None:
            v["reason"] = "no cost basis" if avg is None else "no price"
            continue
        if below > -UNDERWATER_PCT:
            v["reason"] = (f"{-below:.1f}% below cost (needs {UNDERWATER_PCT:g}%)" if below < 0
                           else f"{below:.1f}% above cost")
            continue
        v["gate"] = 2
        if sym not in kept:
            if not any_passed:
                v["reason"] = "no screen passed its placebo"
            else:
                v["reason"] = trim_why.get(sym) or excl_why.get(sym) or (
                    "not kept by a passing screen")
            continue
        if not kept[sym].get("net_margin_pt", 0.0) > 0:
            v["reason"] = "net margin not above 0"
            continue
        # gate 3 is context: the entry status rides along in `entry_status`
        v["gate"] = 4
        why = _room(sym, size_rows, held, value, caps)
        if why:
            v["reason"] = why
            continue
        if sym in sizes:
            v.update(status="average_down", gate=None,
                     reason=f"{-below:.1f}% below cost; {sizes[sym].get('reason', 'sized')}",
                     new_avg_cost=new_avg_cost(avg, qty, sizes[sym]))
            continue
        if budget_idr > 0:
            if sym in excl_why:
                v["reason"] = excl_why[sym]
            else:
                v.update(gate=5, reason="not sized: the budget went to other names")
            continue
        v.update(status="unfunded", gate=5, reason=_no_budget(stance))
    return out
