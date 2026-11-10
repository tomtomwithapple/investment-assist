"""Which held names pay for a leg's cut when the screens name too few (PLAN S75, phase N
choice 1, user 2026-11-10): **pro rata**.

A market's stocks may sit far above their target (IDN stocks 96.9% against 48%) while sizing's
trims, which need a screen's verdict, cover only part of the gap. The rest is taken pro rata
from the held names that have no trim call: each sells the same fraction of its holding, in
whole board lots; what rounding leaves over goes one lot at a time to the largest holdings
first, never past the amount needed and never past what is held. It takes no view on any name:
it is a rebalance, and the guide labels it so.

Pure, and hashed by `journal.RULE_GLOBS`: this decides which names are sold and how much.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from assist.candidates.costs import LOT

__all__ = ["config", "ordered_sales", "pro_rata_sales"]

VERSION = "0.2.0"  # 0.2.0: redundant names first, kept names last (S83)


def config() -> dict:
    return {"rebalance_version": VERSION, "rule": "redundant names in full first; then pro rata "
            "over held names with no trim call that no passing screen keeps, whole lots, "
            "leftover to the largest holdings first; kept names last", "lot": LOT}


def pro_rata_sales(held: Mapping[str, float], prices: Mapping[str, float | None],
                   need_idr: float, exclude: Iterable[str] = (), lot: int = LOT) -> list[dict]:
    """[{symbol, shares, idr}] summing to at most `need_idr`, by symbol. `held` is IDR held per
    symbol, `prices` today's price; a name with no price, or less than one lot, sells nothing."""
    skip = set(exclude)
    pool = {}
    for sym, idr in held.items():
        price = prices.get(sym)
        if sym in skip or not price or price <= 0 or idr <= 0:
            continue
        lots = int(idr / price // lot)
        if lots > 0:
            pool[sym] = (float(price), lots, float(idr))
    total = sum(v[2] for v in pool.values())
    if need_idr <= 0 or total <= 0:
        return []
    f = min(1.0, need_idr / total)
    sell = {s: min(lots, int(f * idr / price // lot)) for s, (price, lots, idr) in pool.items()}
    left = need_idr - sum(sell[s] * lot * pool[s][0] for s in pool)
    order = sorted(pool, key=lambda s: (-pool[s][2], s))
    moved = True
    while moved:
        moved = False
        for s in order:
            price, lots, _ = pool[s]
            if sell[s] < lots and price * lot <= left:
                sell[s] += 1
                left -= price * lot
                moved = True
    return [{"symbol": s, "shares": sell[s] * lot, "idr": sell[s] * lot * pool[s][0]}
            for s in sorted(pool) if sell[s] > 0]


def ordered_sales(held: Mapping[str, float], prices: Mapping[str, float | None],
                  need_idr: float, *, exclude: Iterable[str] = (),
                  redundant: Iterable[str] = (), protected: Iterable[str] = (),
                  quantities: Mapping[str, float | None] | None = None,
                  lot: int = LOT) -> list[dict]:
    """The cut in the order the principle asks for (PLAN S83), as [{symbol, shares, idr, tier,
    full}] summing to at most `need_idr`:

    1. `redundant` names (`candidates.diversify`), in the order given, each sold **in full**
       (its whole quantity, odd lot included) while the need lasts; the one that would
       overshoot is sold in whole lots up to the need.
    2. `pro_rata_sales` over the other names, `protected` ones left out.
    3. `pro_rata_sales` over the `protected` names (those a passing screen keeps), only for
       what is still needed.
    """
    skip = set(exclude)
    quantities = quantities or {}
    left = float(need_idr)
    out: list[dict] = []
    done: set[str] = set()
    for sym in redundant:
        price, idr = prices.get(sym), held.get(sym)
        if sym in skip or sym in done or not price or price <= 0 or not idr or idr <= 0:
            continue
        done.add(sym)
        if left <= 0:
            continue
        qty = int(quantities.get(sym) or round(idr / price))
        if qty * price <= left:
            shares, full = qty, True
        else:
            shares, full = int(left / price // lot) * lot, False
        if shares <= 0:
            continue
        out.append({"symbol": sym, "shares": shares, "idr": shares * price,
                    "tier": "redundant", "full": full})
        left -= shares * price
    guarded = set(protected)
    for tier, names in (("rebalance", [s for s in held if s not in guarded]),
                        ("protected", [s for s in held if s in guarded])):
        if left <= 0:
            break
        pool = {s: held[s] for s in names if s not in done}
        for x in pro_rata_sales(pool, prices, left, exclude=skip, lot=lot):
            out.append({**x, "tier": tier, "full": False})
            left -= x["idr"]
    return out
