"""Telegram message text (PLAN phase R): what a phone shows, in plain words.

**Monday message** (`weekly`, T1, T2, T5, T6). In the user's six sections (T6, with the
user's 2026-11-13 wording):

- header: the title only, no disclaimer;
- **1 World mood**: the state, the warning signs that fired out of those counted
  (`out/layers/regime.json`), the dollar (strengthening, steady, weakening) with its meaning,
  whether orders are split;
- **2 Indonesia mood**: the home regime's warning points and the checks that gave them;
- **Buy Rp x, sell Rp y**: the totals of the lines below; the tranche dates once;
- **3 US stocks to buy**, **4 Indonesian stocks to buy**: that market's buy steps from the
  guide ("Buy: SBN Rp 15.90m", then "(1.8% of 30% target)"), else the leg's share of its
  target; then the passing screens' top 5 (`out/candidates`) as buy lines up to the 5%
  per-name cap, "to target" when held, "full" when new; names sold this week left out;
- **Other buys**: bonds and every other buy step, so no buy is dropped;
- **5 US stocks to sell**, **6 Indonesian stocks to sell**: one name a line, largest first,
  no reasons ("KLBF 2.4m", "PWON all", "XXXX trim 1.0m"): the guide's sell steps plus the held
  names whose business no longer passes (T2, `out/holdings/IDN.json`), listed even while
  `ACT_ON_VERDICTS` is off, so the home page may not show them yet.

The buy and sell steps come from the guide (`out/guide.json`); the value buys and the thesis
sells are added here, so the totals may exceed the guide's.

Lines are plain text at most `WIDTH` characters; a line starting with `# ` is a heading, which
`notify.send(..., heads=True)` turns bold (T5). Pure: no I/O.
"""

from __future__ import annotations

import re
import textwrap
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date

from assist import plain
from assist.layers import undervalued as _undervalued

__all__ = ["WIDTH", "morning", "regime_lines",
           "weekly", "wrap"]

WIDTH = 60  # a phone shows about this many characters a line
WORLD = {"risk_on": "calm", "neutral": "normal", "risk_off": "nervous"}
HOME = {"neutral": "calm", "risk_off": "nervous"}  # the home regime has no risk_on


# ---------------- small helpers ----------------


def wrap(text: str, first: str = "", rest: str = "  ") -> list[str]:
    """`text` in lines of at most `WIDTH`, the first prefixed `first`, the others `rest`."""
    return textwrap.wrap(text, WIDTH, initial_indent=first, subsequent_indent=rest,
                         break_long_words=True, break_on_hyphens=False) or [first.rstrip()]


def _m(idr: float) -> str:
    return f"{idr / 1e6:,.1f}m" if idr >= 0.05e6 else f"{idr / 1e6:.2f}m"


def _day(d: str | date) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.day} {d:%b}"


def _first_sentence(s: str | None) -> str:
    s = (s or "").strip()
    m = re.search(r"\.(\s|$)", s)
    return s[: m.start()] if m else s


# ---------------- sections ----------------


def _signs(fired: Sequence[str], of: int, at: int | None) -> list[str]:
    """'Warning signs: 1 of 5 (2 make it nervous): 10Y real yield 2.78%.'"""
    head = f"Warning signs: {len(fired)} of {of}" + (f" ({at} make it nervous)" if at else "")
    return wrap(head + (": " + "; ".join(fired) if fired else "") + ".", rest="")


def _world(regime: Mapping | None, guide_payload: Mapping | None,
           stances: Sequence[Mapping]) -> list[str]:
    """1 World mood: its state, the warning signs that fired, the dollar, the order split."""
    idn = next((s for s in stances if s.get("subject") == "IDN"), None) or {}
    r = regime or {}
    state = r.get("state") or (guide_payload or {}).get("regime") or idn.get("regime")
    dollar = r.get("dollar") or idn.get("dollar")
    out = ["", f"# 1. World mood: {WORLD.get(state, str(state or 'unknown').replace('_', ' '))}"]
    counted = [i for i in r.get("inputs") or () if i.get("counted")]
    if counted:
        fired = [i["label"] for i in counted if i.get("direction") == "risk_off"]
        calm = [i["label"] for i in counted if i.get("direction") == "risk_on"]
        out += _signs(fired, len(counted), (r.get("rule") or {}).get("state_at"))
        if calm:
            out += wrap("Calm signs: " + "; ".join(calm) + ".", rest="")
    elif state == "risk_off" and r.get("drivers"):
        out += wrap("Why: " + "; ".join(_drop_points(r["drivers"])) + ".", rest="")
    if dollar in plain.DOLLAR:
        meaning = plain.meaning("dollar", dollar) or ""
        out += wrap(f"{plain.label('dollar', dollar)}: {meaning[:1].lower()}{meaning[1:]}",
                    rest="")
    if state in ("risk_on", "neutral"):
        out.append("Orders go in one go.")
    elif state == "risk_off":
        out += wrap("Every order is split into parts; new buys need a higher return.", rest="")
    return out


def _home(regime: Mapping | None, stances: Sequence[Mapping]) -> list[str]:
    """2 Indonesia mood: its state and the warning points behind it."""
    idn = next((s for s in stances if s.get("subject") == "IDN"), None) or {}
    h = (regime or {}).get("home") or idn.get("home_regime") or {}
    state = h.get("state")
    out = ["", f"# 2. Indonesia mood: {HOME.get(state, str(state or 'unknown'))}"]
    counted = [i for i in h.get("inputs") or () if i.get("counted")]
    at = (h.get("rule") or {}).get("state_at")
    if counted:
        fired = [i["label"] + (f" ({i['points']} pts)" if i.get("points", 0) > 1 else "")
                 for i in counted if i.get("points")]
        out += wrap(f"Warning points: {h.get('points', 0)} from {len(counted)} checks"
                    + (f" ({at} make it nervous)" if at else "")
                    + (": " + "; ".join(fired) if fired else "") + ".", rest="")
    elif h.get("drivers"):
        out += wrap("Why: " + "; ".join(_drop_points(h["drivers"])) + ".", rest="")
    if state == "risk_off":
        out += wrap("Indonesian stock and bond orders are split into parts.", rest="")
    elif state is None:
        out.append("Not measured this run.")
    return out


def _dates(steps: Sequence[Mapping]) -> list[str]:
    plans = Counter(tuple(t["date"] for t in s["tranches"]) for s in steps if s.get("tranches"))
    if not plans:
        return []
    common = plans.most_common(1)[0][0]
    if len(common) == 1:
        out = wrap(f"In one go on {_day(common[0])}, at market.", rest="")
    else:
        out = wrap(f"In {len(common)} parts: " + ", ".join(_day(d) for d in common)
                   + ", at market.", rest="")
    if len(plans) > 1:
        out.append("Smaller orders go in fewer parts.")
    return out


def _pct(x: float) -> str:
    return f"{x:.1f}".removesuffix(".0")


def _buys(steps: Sequence[Mapping], g: Mapping) -> list[str]:
    """'Buy: SBN Rp 15.90m' and, under it, the leg's share against its target (user
    2026-11-13); a named stock gets the first sentence of its `why` instead."""
    out = []
    for s in steps:
        name = re.sub(r"\s*\(.*\)$", "", re.sub(r"^Buy\s+(an?\s+)?", "", s["label"]))
        name = re.sub(r"\bbroad-market\s+", "", name)
        out += wrap(f"Buy: {name} Rp {s['idr'] / 1e6:,.2f}m", rest="  ")
        leg = next((x for x in g.get("legs") or ()
                    if (x.get("market"), x.get("asset")) == (s.get("market"), s.get("asset"))),
                   None)
        if s.get("kind") == "bucket" and leg and leg.get("current_pct") is not None:
            who = "" if s.get("asset") == "bonds" else f"{plain.leg(s['market'], s['asset'])} "
            out += wrap(f"({who}{_pct(leg['current_pct'])}% of "
                        f"{leg['target_pct']:.0f}% target)", rest="  ")
        elif _first_sentence(s.get("why")):
            out += wrap(f"({_first_sentence(s.get('why'))})", rest="  ")
    return out


def _sells(steps: Sequence[Mapping]) -> list[str]:
    """One name a line, largest first: 'KLBF 2.4m', or 'PWON all' when the whole position goes
    (user 2026-11-13: no reasons)."""
    out = []
    for s in sorted(steps, key=lambda s: (-s["idr"], s.get("symbol") or "")):
        tags = s.get("tags") or ()
        amount = ("all" if "all of it" in tags else f"trim {_m(s['idr'])}" if "trim" in tags
                  else _m(s["idr"]))
        name = s.get("symbol") or re.sub(r"^Sell\s+", "", s.get("label", ""))
        out += wrap(f"{name} {amount}", rest="  ")
    return out


def _thesis_sells(holdings: Mapping | None, sells: Sequence[Mapping]) -> list[dict]:
    """The held names whose business no longer passes (T2), as sell lines (user 2026-11-13:
    "in Sell, with trim or all"): `sell_all` sells the whole holding, `trim_to_half` half. A
    name this week's steps already sell is upgraded to "all" when its verdict sells it all.
    Listed whether or not `ACT_ON_VERDICTS` is on, so the guide may not have them yet."""
    out = []
    by_symbol = {s.get("symbol"): s for s in sells}
    for h in (holdings or {}).get("holdings") or ():
        acted = h.get("acted") or {}
        if not (acted.get("thesis") or {}).get("acts"):
            continue
        whole = acted.get("action") != "trim_to_half"
        if h["symbol"] in by_symbol:
            if whole:
                step = by_symbol[h["symbol"]]
                step["tags"] = [*(step.get("tags") or ()), "all of it"]
                step["idr"] = max(step["idr"], float(h.get("held_idr") or 0))
            continue
        idr = float(h.get("held_idr") or 0) * (1 if whole else 0.5)
        out.append({"symbol": h["symbol"], "idr": idr, "side": "sell", "market": "IDN",
                    "asset": "stocks", "tags": ["all of it"] if whole else ["trim"]})
    return out


def _value(payloads: Sequence[Mapping], market: str, sold: Sequence[str],
           portfolio_idr: float | None) -> tuple[list[str], float] | None:
    """The passing screens' top 5 for `market` as buy lines (user 2026-11-13: "Best value in
    Buy, with target or full"): a held name up to the per-name cap ("to target"), a new name
    a full position at the cap ("full"). Names this week's steps sell, and names already at
    the cap, are left out. Returns (lines, total), or None when no screen passes."""
    p = next((x for x in payloads if x.get("market") == market), None)
    if p is None:
        return None
    passing = [s for s in p.get("styles") or () if s["passed"]]
    rows: list[Mapping] = []
    for r in _undervalued.top(p, 10):  # a name two screens pass is listed once
        if len(rows) < 5 and r["symbol"] not in {x["symbol"] for x in rows}:
            rows.append(r)
    if not passing or not rows:
        return None
    cap_pct = (((p.get("config") or {}).get("caps") or {}).get("name_pct")) or 5.0
    cap = portfolio_idr * cap_pct / 100 if portfolio_idr else None
    out, total = [], 0.0
    for r in rows:
        if r["symbol"] in sold:
            continue
        held = float(r.get("held_idr") or 0) if r.get("held") else 0.0
        kind = "to target" if r.get("held") else "full"
        if cap is None:
            out += wrap(f"Buy: {r['symbol']} ({kind})", rest="  ")
            continue
        idr = cap - held
        if idr <= 0:
            continue
        total += idr
        out += wrap(f"Buy: {r['symbol']} Rp {idr / 1e6:,.2f}m ({kind})", rest="  ")
    return out, total


def _leg(g: Mapping, market: str) -> Mapping | None:
    return next((x for x in g.get("legs") or ()
                 if (x.get("market"), x.get("asset")) == (market, "stocks")), None)


def _leg_note(g: Mapping, market: str) -> list[str]:
    """Why a stock leg has no buy: its share against its target."""
    leg = _leg(g, market)
    if leg is None or leg.get("current_pct") is None or leg.get("target_pct") is None:
        return []
    return wrap(f"({plain.leg(market, 'stocks')} {_pct(leg['current_pct'])}% of "
                f"{leg['target_pct']:.0f}% target)", rest="")


def _is(s: Mapping, market: str, asset: str = "stocks") -> bool:
    return (s.get("market"), s.get("asset")) == (market, asset)


# ---------------- the message ----------------


def weekly(*, day: date, guide_payload: Mapping | None, stances: Sequence[Mapping] = (),
           undervalued: Sequence[Mapping] = (), holdings: Mapping | None = None,
           regime: Mapping | None = None) -> str:
    """The Monday message in the user's six sections (T6), lines of at most `WIDTH`."""
    lines = [f"# investment-assist, {day:%a} {day.day} {day:%b %Y}",
             *_world(regime, guide_payload, stances), *_home(regime, stances)]
    g = guide_payload
    steps = list((g or {}).get("steps") or ())
    buys = [s for s in steps if s["side"] == "buy"]
    sells = [dict(s) for s in steps if s["side"] == "sell"]
    orders = g is not None and not g.get("held_for_data")
    if orders:
        sells += _thesis_sells(holdings, sells)
    sold = {s.get("symbol") for s in sells if s.get("symbol")}
    value = {m: _value(undervalued, m, sold, (g or {}).get("portfolio_value_idr")) if orders
             else None for m in ("USA", "IDN")}
    buy_idr = sum(s["idr"] for s in buys) + sum(v[1] for v in value.values() if v)
    sell_idr = sum(s["idr"] for s in sells)
    if g is None:
        lines += ["", "No steps this run: the guide is missing. Open the home page."]
    elif g.get("held_for_data"):
        lines += ["", *wrap("No orders this week: some inputs are broken, so last week's "
                            "holdings stand.", rest="")]
        lines += [x for h in g["held_for_data"] for x in wrap(h, first="• ")]
    elif not (buy_idr or sells):
        lines += ["", "Nothing to do this week: every leg is at its target."]
    else:
        head = ", ".join(x for x in (f"buy Rp {_m(buy_idr)}" if buy_idr else "",
                                      f"sell Rp {_m(sell_idr)}" if sells else "") if x)
        lines += ["", f"# {head[:1].upper()}{head[1:]}", *_dates(steps)]

    for n, market in ((3, "USA"), (4, "IDN")):
        mine = [s for s in buys if _is(s, market)]
        if not orders:
            continue
        lines += ["", f"# {n}. {plain.MARKET[market]} stocks to buy"]
        if mine:
            lines += _buys(mine, g or {})
        elif orders and g is not None:
            lines += _leg_note(g, market)
        v = value[market]
        if v and v[0]:
            lines += v[0]
        elif orders:
            lines += wrap(f"No {plain.MARKET[market]} stock passes a value screen this week.",
                          rest="")
    other = [s for s in buys if not (_is(s, "USA") or _is(s, "IDN"))]
    if other:
        lines += ["", "# Other buys", *_buys(other, g or {})]

    for n, market in ((5, "USA"), (6, "IDN")):
        mine = [s for s in sells if _is(s, market)]
        if not mine and not orders:
            continue
        body = _sells(mine)
        if not mine:
            leg = (_leg(g, market) if g else None) or {}
            body = [f"None: no {plain.MARKET[market]} stocks held."
                    if leg.get("current_pct") == 0 else "None this week."]
        total = f" ({len(mine)}, Rp {_m(sum(s['idr'] for s in mine))})" if mine else ""
        lines += ["", f"# {n}. {plain.MARKET[market]} stocks to sell{total}", *body]
    rest = [s for s in sells if not (_is(s, "USA") or _is(s, "IDN"))]
    if rest:
        lines += ["", "# Other sells", *_sells(rest)]
    return "\n".join(lines)


# ---------------- the 07:00 message (T3) ----------------


DOLLAR_WORD = {"up": "strengthening", "flat": "steady", "down": "weakening"}  # user 2026-11-13


def _drop_points(drivers: Sequence[str]) -> list[str]:
    """'JCI -12.8% vs 20d high (2)' and '10Y real yield 2.78% (risk-off)' without the tail."""
    return [re.sub(r"\s*\((\d+|risk-off|risk-on)\)$", "", d) for d in drivers]


def regime_lines(previous: Mapping, *, world: str, dollar: str, drivers: Sequence[str],
                 home: str | None, home_drivers: Sequence[str]) -> list[str]:
    """What changed since the last journalled regime, why, and what it means for Monday. A mood
    that cleared says what cleared (the previous record's warning signs). Only changed parts."""
    out: list[str] = []

    def mood(name: str, before: str, now: str, why_now: Sequence[str], why_before: Sequence[str],
             monday_on: str, monday_off: str, words: Mapping[str, str] = WORLD) -> None:
        out.extend(wrap(f"{name}: {words.get(before, before)} → {words.get(now, now)}.", rest=""))
        if now == "risk_off" and why_now:
            out.extend(wrap("Why: " + "; ".join(_drop_points(why_now)) + ".", rest=""))
        elif before == "risk_off" and why_before:
            out.extend(wrap("Cleared: " + "; ".join(_drop_points(why_before)) + ".", rest=""))
        if now == "risk_off":
            out.extend(wrap(monday_on, rest=""))
        elif before == "risk_off":
            out.extend(wrap(monday_off, rest=""))

    if previous["state"] != world:
        mood("World", previous["state"], world, drivers, previous.get("drivers") or (),
             "Monday: orders split in 3, new buys need a higher return.",
             "Monday: the extra caution for the world mood ends.")
    if previous["dollar"] != dollar:
        out.extend(wrap(f"Dollar: {DOLLAR_WORD.get(previous['dollar'], previous['dollar'])} → "
                        f"{DOLLAR_WORD.get(dollar, dollar)}.", rest=""))
        meaning = plain.meaning("dollar", dollar)
        if meaning:
            out.extend(wrap(meaning, rest=""))
    if home is not None and previous.get("home") is not None and previous["home"] != home:
        mood("Indonesia", previous["home"], home, home_drivers,
             previous.get("home_drivers") or (),
             "Monday: Indonesian stock and bond orders split in 3.",
             "Monday: the extra caution for Indonesia ends.", HOME)
    return ["# Mood changed", *out] if out else []


def _health_lines(health: Sequence[str]) -> list[str]:
    out: list[str] = []
    for line in health:
        if line.startswith("- "):
            out += wrap(line[2:], first="• ")
        elif line.startswith("Data health"):
            head, _, rest = line.partition(":")
            out += ["", f"# {head}"] + (wrap(rest.strip(), rest="") if rest.strip() else [])
        else:
            out += wrap(line, rest="")
    return out


def morning(day: date, *, regime: Sequence[str], holdings: Sequence[str],
            health: Sequence[str], act_on: bool | None) -> str:
    """The one 07:00 message: mood changes, holding changes, data health; no disclaimer."""
    lines = [f"# investment-assist morning, {day:%a} {day.day} {day:%b %Y}"]
    if regime:
        lines += ["", *regime]
    if holdings:
        lines += ["", "# Holdings"]
        if act_on is False:
            lines += wrap("Paper: not acted on yet (the switch is off).", rest="")
        for h in holdings:
            lines += wrap(re.sub(r"^Holdings:\s*", "", h), first="• ")
    lines += _health_lines(health)
    return "\n".join(lines)
