"""Position sizing (PLAN S20a): an IDR amount for each candidate that passes, top-down.

- **Budget.** The layer-5 `target_pct` minus `current_pct` of the market's stocks stance (S5),
  times the portfolio value (financer). Since S39 the target is the benchmark leg (IDN stocks
  48%, USA stocks 20%) plus the tilt, after the pro-rata 100% cap; a market outside the mandate
  targets 0%, so it only trims. An `underweight` or `avoid` stance, or a target at or
  below the holding, gives no new money: only trims.
- **Split.** Inside the budget, weight ∝ `margin_pt` ÷ `vol_1y`, so a cheaper, calmer name gets
  more. A name that fails its screen, has a margin ≤ 0 or no `vol_1y` gets nothing.
- **Caps.** Per name `CAPS["name_pct"]` of the portfolio, counting what is already held. Per
  sector `CAPS["sector_names"]` names (an int, or a dict by sector such as S16's tilted caps,
  the default for the rest), the best margins kept. Liquidity: each tranche stays under
  `max_participation` of `med_value_60d`, checked with `costs.cost_for` (a name flagged
  `over_participation` or `below_one_lot` is dropped, as is one with no turnover). The excess
  over a cap is redistributed once, by weight, to the names still under theirs; what is left
  after that is unspent.
- **Timing.** A ladder when the stance's entry is one or the regime is risk_off (S5's
  `LADDER_TRANCHES` × `LADDER_SPACING_DAYS` unless the stance names its own), else one lump.
  Tranches are whole board lots at today's price; with `entry.entry_plan` levels the later
  tranches carry its typical then deep entry price as a limit, where below today's price.
- **Trims.** A held name that is not in the list, fails it, or whose margin is ≤ 0 is trimmed
  in full; one above the per-name cap is trimmed back to it.

A pure function: no store is read. `CAPS` are hand-set starting values pending the user's weight
bands (PLAN Open questions); they go into the model fingerprint (`config`), and this module is
hashed by `journal.RULE_GLOBS`, so a change segments the journal. Sizes are paper until then.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from assist.candidates.costs import MAX_PARTICIPATION, cost_for, lot_shares
from assist.layers.types import Regime
from assist.stance import LADDER_SPACING_DAYS, LADDER_TRANCHES, model_fingerprint

__all__ = ["CAPS", "Sizing", "Size", "Tranche", "Trim", "config", "fingerprint", "size"]

VERSION = "0.1.0"
# TODO(PLAN.md, Open questions): starting values until the user confirms the weight bands.
CAPS = {
    "name_pct": 5.0,  # % of the portfolio per name, held value included
    "sector_names": 5,  # names per sector; a dict by sector overrides (S16 tilt: 3..7)
    "max_participation": MAX_PARTICIPATION,  # each tranche / med_value_60d
}
NO_ADDS = ("underweight", "avoid")


@dataclass(frozen=True)
class Tranche:
    day: int  # days after the first tranche
    idr: float
    shares: int
    limit: float | None = None  # entry level from entry.entry_plan; None = at today's price


@dataclass(frozen=True)
class Size:
    symbol: str
    idr: float
    tranches: tuple[Tranche, ...]
    reason: str


@dataclass(frozen=True)
class Trim:
    symbol: str
    idr: float
    reason: str


@dataclass(frozen=True)
class Sizing:
    budget_idr: float
    unspent_idr: float
    sizes: list[Size] = field(default_factory=list)
    trims: list[Trim] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)
    fingerprint: str = ""


def _caps(caps: Mapping | None) -> dict:
    return {**CAPS, **(caps or {})}


def config(caps: Mapping | None = None) -> dict:
    return {"sizing_version": VERSION, "caps": _caps(caps),
            "ladder": {"tranches": LADDER_TRANCHES, "spacing_days": LADDER_SPACING_DAYS}}


def fingerprint(caps: Mapping | None = None) -> str:
    return model_fingerprint(config(caps))


def _sector_cap(sector: str | None, caps: dict) -> int:
    s = caps["sector_names"]
    if isinstance(s, Mapping):
        return int(s.get(sector, CAPS["sector_names"]))
    return int(s)


def _schedule(stance: Mapping, state: str | None) -> tuple[int, int]:
    e = stance.get("entry") or {}
    if e.get("style") == "ladder" and int(e.get("tranches") or 0) > 1:
        return int(e["tranches"]), int(e.get("spacing_days") or LADDER_SPACING_DAYS)
    if state == "risk_off":
        return LADDER_TRANCHES, LADDER_SPACING_DAYS
    return 1, 0


def _limits(levels, price: float, n: int) -> list[float | None]:
    out: list[float | None] = [None] * n
    if levels is None or n < 2:
        return out
    get = levels.get if isinstance(levels, Mapping) else lambda k: getattr(levels, k, None)
    below = [p for p in (get("entry_typical"), get("entry_deep")) if p and p < price]
    for i in range(1, n):
        out[i] = below[min(i - 1, len(below) - 1)] if below else None
    return out


def _fails(r: Mapping) -> str | None:
    if not r.get("passes", True):
        return "fails its screen"
    m = r.get("margin_pt")
    if m is None or m <= 0:
        return f"margin {m if m is None else f'{m:.1f}pt'} not above the hurdle"
    return None


def size(
    candidates: Sequence[Mapping],
    stance: Mapping,
    portfolio_value_idr: float,
    holdings: Mapping[str, float],
    regime: Regime | str | None,
    caps: Mapping | None = None,
    entry: Mapping[str, Mapping] | None = None,
) -> Sizing:
    """Sizes and trims for one market's stocks. `candidates` are S20's rows with P19's factor
    columns; `stance` is the market's stocks stance payload; `holdings` is IDR held per symbol in
    that market; `entry` is `entry.entry_plan`'s output (optional)."""
    c = _caps(caps)
    state = regime.state if isinstance(regime, Regime) else regime
    V = float(portfolio_value_idr or 0.0)
    name_cap = c["name_pct"] / 100 * V
    rows = {r["symbol"]: r for r in candidates}

    trims: list[Trim] = []
    for sym, held in sorted(holdings.items()):
        if held <= 0:
            continue
        r = rows.get(sym)
        why = "not in the candidate list (no longer passes)" if r is None else _fails(r)
        if why:
            trims.append(Trim(sym, float(held), f"trim in full: {why}"))
        elif held > name_cap:
            trims.append(Trim(sym, held - name_cap,
                              f"trim to the per-name cap of {c['name_pct']:g}%"))

    port = stance.get("portfolio") or {}
    gap = (port.get("target_pct") or 0.0) - (port.get("current_pct") or 0.0)
    budget = 0.0 if stance.get("stance") in NO_ADDS else max(0.0, gap) / 100 * V
    fp = fingerprint(caps)
    if budget <= 0:
        return Sizing(0.0, 0.0, [], trims, [], fp)

    n, spacing = _schedule(stance, state)
    excluded: list[tuple[str, str]] = []
    ok: list[Mapping] = []
    for sym, r in sorted(rows.items()):
        why = _fails(r)
        if why is None and not (r.get("vol_1y") or 0) > 0:
            why = "no vol_1y"
        if why is None and not (r.get("price") or 0) > 0:
            why = "no price"
        if why is None and not (r.get("med_value_60d") or 0) > 0:
            why = "no turnover (med_value_60d), liquidity unknown"
        if why:
            excluded.append((sym, why))
        else:
            ok.append(r)

    ok.sort(key=lambda r: (-r["margin_pt"], r["symbol"]))
    per_sector: dict[str | None, int] = {}
    kept: list[Mapping] = []
    for r in ok:
        k = r.get("sector")
        if per_sector.get(k, 0) >= _sector_cap(k, c):
            excluded.append((r["symbol"], f"sector cap of {_sector_cap(k, c)} names ({k})"))
            continue
        per_sector[k] = per_sector.get(k, 0) + 1
        kept.append(r)

    w = {r["symbol"]: r["margin_pt"] / r["vol_1y"] for r in kept}
    cap: dict[str, tuple[float, str]] = {}
    for r in kept:
        s = r["symbol"]
        room = max(0.0, name_cap - float(holdings.get(s, 0.0)))
        liq = n * c["max_participation"] * r["med_value_60d"]
        cap[s] = (room, "per-name cap") if room <= liq else (liq, "liquidity cap")

    def spread(names: list[str], amount: float) -> dict[str, float]:
        tw = sum(w[s] for s in names)
        return {s: amount * w[s] / tw for s in names} if tw > 0 else {}

    alloc = spread(list(w), budget)
    hit = {s for s, a in alloc.items() if a >= cap[s][0]}
    excess = sum(alloc[s] - cap[s][0] for s in hit)
    for s in hit:
        alloc[s] = cap[s][0]
    for s, extra in spread([s for s in alloc if s not in hit], excess).items():
        if alloc[s] + extra >= cap[s][0]:
            hit.add(s)
        alloc[s] = min(cap[s][0], alloc[s] + extra)

    sizes: list[Size] = []
    for r in kept:
        s, price = r["symbol"], float(r["price"])
        per = alloc.get(s, 0.0) / n
        cost = cost_for(r, per)
        shares = lot_shares(per, price)
        if cost is None or "below_one_lot" in cost.flags or shares == 0:
            excluded.append((s, f"below one lot (IDR {per:,.0f} per tranche)"))
            continue
        if "over_participation" in cost.flags:
            excluded.append((s, "tranche over the participation limit"))
            continue
        levels = (entry or {}).get(s, {}).get("levels")
        tr = tuple(Tranche(i * spacing, shares * price, shares, lim)
                   for i, lim in enumerate(_limits(levels, price, n)))
        bits = [f"margin {r['margin_pt']:.1f}pt / vol {100 * r['vol_1y']:.0f}%"]
        if s in hit:
            bits.append(cap[s][1])
        bits.append("lump" if n == 1 else f"ladder {n}×{spacing}d")
        sizes.append(Size(s, sum(t.idr for t in tr), tr, "; ".join(bits)))

    sizes.sort(key=lambda z: z.symbol)
    excluded.sort()
    spent = sum(z.idr for z in sizes)
    return Sizing(budget, budget - spent, sizes, trims, excluded, fp)
