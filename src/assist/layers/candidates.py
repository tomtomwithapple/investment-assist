"""Layer 4, IDN stock candidates: which names to buy, net of what buying them costs (PLAN S10).

Assembles P20's screens (`candidates.screens.run_screens`) with P21's cost model and entry
levels (`candidates.entry.entry_plan`) for one planned tranche:

- Only a screen whose placebo verdict passed names anyone (P20 keeps `candidates` empty
  otherwise); its verdict is kept here for the journal either way.
- **Edge net of cost.** A screen's edge is its measured monthly top-minus-bottom quintile
  spread (`spread_mean`, in bps). Every screen rebalances at least monthly, so a name pays its
  full modelled round trip (`Cost.round_trip_bps` at the tranche size) against one month of
  edge. A name whose round trip eats the whole edge is dropped. The long-short spread is an
  optimistic stand-in for what a long-only book earns, so a positive net edge is a floor to
  pass, not a forecast.
- **Capacity.** A name flagged `over_participation` (the tranche is more than 10% of its 60-day
  median value) or `below_one_lot` at the tranche size is dropped; so is one with no cost
  estimate (no price).
- **Entry level** = `EntryLevels.entry_typical`, or `entry_deep` when the name has no completed
  correction in its window; None when its history is shorter than `entry.MIN_BARS`.

Nothing here changes a stance: candidates are context under the IDN stocks stance until paper
tracking (S13) has a record. The stance schema has no candidates slot, so the pipeline puts the
headline in `drivers` and one line per name in `watch`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date

from assist.candidates.entry import DEFAULT_ORDER, entry_plan
from assist.candidates.screens import run_screens
from assist.layers.types import Candidate
from assist.sources.idxmethod_stocks import SOURCE, IdxMethodStocks

__all__ = [
    "TRANCHE_IDR",
    "IdnCandidates",
    "ScreenSummary",
    "assemble",
    "idn_candidates",
]

SUBJECT, ASSET = "IDN", "stocks"
TRANCHE_IDR = DEFAULT_ORDER  # IDR per name per tranche, the size costs and capacity are judged at
DROP_FLAGS = ("over_participation", "below_one_lot")


@dataclass(frozen=True)
class ScreenSummary:
    """One screen's verdict and yield: `edge_bps` is its monthly top − bottom spread."""

    name: str
    passed: bool
    blocked: str | None
    edge_bps: float | None
    months: int
    n_ranked: int
    n_named: int
    verdict: dict
    flags: tuple[str, ...] = ()  # what the replay could not reproduce point in time


@dataclass(frozen=True)
class IdnCandidates:
    """Layer 4 for IDN stocks: the names kept, the ones dropped and why, each screen's verdict,
    the tranche size they were judged at, and what was missing."""

    as_of: date | None
    order_idr: float
    candidates: tuple[Candidate, ...]
    screens: tuple[ScreenSummary, ...]
    dropped: tuple[tuple[str, str, str], ...]  # (screen, symbol, reason)
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = (SOURCE,)

    def headline(self) -> str:
        """One line for the stance's drivers."""
        bars = f"bars {self.as_of}" if self.as_of else "no bars"
        size = f"IDR {self.order_idr / 1e6:,.0f}m tranche"
        parts = []
        for s in self.screens:
            if s.passed:
                parts.append(f"{s.name} {s.n_named} named")
            else:
                parts.append(f"{s.name} blocked ({s.blocked})")
        n_drop = len(self.dropped)
        drop = f", {n_drop} dropped on cost or capacity" if n_drop else ""
        return (f"layer 4: {len(self.candidates)} IDN stock candidate(s) ({size}, {bars}{drop});"
                f" {'; '.join(parts) or 'no screens'}. Context only: no stance change")

    def watch(self) -> list[str]:
        """One line per candidate, best first."""
        return [f"candidate {c.symbol} ({c.screen}): {c.detail}" for c in self.candidates]


def _fmt_price(x: float | None) -> str:
    return "n/a" if x is None else f"{x:,.0f}"


def _summary(name: str, res: Mapping) -> ScreenSummary:
    spread = res.get("spread_mean")
    return ScreenSummary(
        name=name, passed=bool(res.get("passed")), blocked=res.get("blocked"),
        edge_bps=None if spread is None else spread * 1e4, months=int(res.get("months") or 0),
        n_ranked=int(res.get("n_ranked") or 0), n_named=0, verdict=dict(res.get("verdict") or {}),
        flags=tuple(res.get("flags") or ()),
    )


def assemble(screens: Mapping, plan: Mapping[str, Mapping], order_idr: float = TRANCHE_IDR,
             as_of: date | None = None) -> IdnCandidates:
    """Pure: `run_screens` output + `entry_plan` output (sym → {levels, cost}) → IdnCandidates.
    A symbol named by two screens is kept once, under the screen with the larger net edge."""
    as_of = screens.get("as_of") or as_of
    kept: dict[str, tuple[float, Candidate]] = {}
    dropped: list[tuple[str, str, str]] = []
    summaries = []
    for name, res in sorted((screens.get("screens") or {}).items()):
        summ = _summary(name, res)
        named = 0
        for c in res.get("candidates") or []:
            sym = c["symbol"]
            entry = plan.get(sym) or {}
            cost, levels = entry.get("cost"), entry.get("levels")
            if cost is None:
                dropped.append((name, sym, "no cost estimate"))
                continue
            flags = [f for f in DROP_FLAGS if f in cost.flags]
            if flags:
                dropped.append((name, sym, ", ".join(flags)))
                continue
            rt = cost.round_trip_bps
            net = None if summ.edge_bps is None else summ.edge_bps - rt
            if net is None or net <= 0:
                dropped.append((name, sym, f"round trip {rt:.0f}bp eats the edge"))
                continue
            level, which = None, "none"
            if levels is not None:
                level, which = ((levels.entry_typical, "typical") if levels.entry_typical
                                is not None else (levels.entry_deep, "deep"))
            status = levels.status if levels is not None else "no entry levels"
            detail = (f"score {c['score']:.2f}, net edge {net:+.0f}bp/mo after {rt:.0f}bp round"
                      f" trip; price {_fmt_price(cost.price)}, entry {which}"
                      f" {_fmt_price(level)}, {status}")
            if c.get("sector"):
                detail += f"; {c['sector']}"
            cand = Candidate(subject=SUBJECT, asset=ASSET, as_of=as_of, symbol=sym, screen=name,
                             score=float(c["score"]), source=SOURCE, entry_level=level,
                             detail=detail)
            named += 1
            if sym not in kept or net > kept[sym][0]:
                kept[sym] = (net, cand)
        summaries.append(replace(summ, n_named=named))
    order = sorted(kept.values(), key=lambda t: (-t[1].score, t[1].symbol))
    return IdnCandidates(as_of=as_of, order_idr=order_idr,
                         candidates=tuple(c for _, c in order), screens=tuple(summaries),
                         dropped=tuple(dropped),
                         stale_inputs=tuple(dict.fromkeys(screens.get("stale_inputs") or ())))


def idn_candidates(
    as_of: date,
    stocks: IdxMethodStocks | None = None,
    order_idr: float = TRANCHE_IDR,
    *,
    screens_fn: Callable[..., dict] = run_screens,
    plan_fn: Callable[..., tuple[dict, list[str]]] = entry_plan,
) -> IdnCandidates:
    """Layer 4 for IDN stocks on `as_of` from idx-method's files (read-only). A missing store
    gives no candidates and a `stale_inputs` entry, never a crash."""
    stocks = stocks or IdxMethodStocks.from_config()
    screens = screens_fn(stocks, as_of)
    syms = sorted({c["symbol"] for r in screens["screens"].values() for c in r["candidates"]})
    plan, stale = ({}, [])
    if syms:
        plan, stale = plan_fn(stocks, symbols=syms, as_of=as_of, order_idr=order_idr)
    out = assemble(screens, plan, order_idr, as_of)
    return replace(out, stale_inputs=tuple(dict.fromkeys([*out.stale_inputs, *stale])))
