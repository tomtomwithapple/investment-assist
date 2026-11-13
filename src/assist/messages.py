"""Telegram message text (PLAN phase R): what a phone shows, in plain words.

**Monday message** (`weekly`, T1, T2, T5). The guide (`out/guide.json`) is the only source of
its numbers, so the message cannot disagree with the home page:

- header: title and one disclaimer line;
- markets in words: the world mood, the dollar, Indonesia's own mood (with why, when nervous);
- **This week**: buy total first, then sell; the tranche dates once;
- **Buy**: every buy step, never cut, with the first sentence of its `why`;
- **Sell**: grouped by reason (`SELL_GROUPS`, from the step's tags and question), largest group
  first, each with its count, total and top `TOP_PER_GROUP` names by amount;
- **Business no longer passes** (T2): the held names whose acted thesis sells
  (`out/holdings/IDN.json`), "not acted on yet" while `ACT_ON_VERDICTS` is off;
- **Best value now**: the IDN screens that pass their test, top 5, held or not.

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

__all__ = ["DISCLAIMER_LINE", "SELL_GROUPS", "TOP_PER_GROUP", "WIDTH", "morning", "regime_lines",
           "weekly", "wrap"]

WIDTH = 60  # a phone shows about this many characters a line
TOP_PER_GROUP = 3  # user 2026-11-13
DISCLAIMER_LINE = "Paper only. Heuristic, not investment advice."
SELL_GROUPS = (  # (key, plain label), matched in this order
    ("thesis", "Business no longer passes"),
    ("cap", "Over the 5% cap"),
    ("valuation", "Price above its fair value"),
    ("redundant", "Same industry and size held twice"),
    ("rebalance", "Share of the cut to the target"),
    ("other", "Other"),
)
WORLD = {"risk_on": "calm", "neutral": "normal", "risk_off": "nervous"}
DOLLAR = {"up": "dollar rising", "flat": "dollar steady", "down": "dollar falling"}
HOME = {"neutral": "calm", "risk_off": "nervous"}  # the home regime has no risk_on


# ---------------- small helpers ----------------


def wrap(text: str, first: str = "", rest: str = "  ") -> list[str]:
    """`text` in lines of at most `WIDTH`, the first prefixed `first`, the others `rest`."""
    return textwrap.wrap(text, WIDTH, initial_indent=first, subsequent_indent=rest,
                         break_long_words=True, break_on_hyphens=False) or [first.rstrip()]


def _m(idr: float) -> str:
    return f"{idr / 1e6:,.1f}m"


def _day(d: str | date) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.day} {d:%b}"


def _first_sentence(s: str | None) -> str:
    s = (s or "").strip()
    m = re.search(r"\.(\s|$)", s)
    return s[: m.start()] if m else s


def _group(step: Mapping) -> str:
    tags = set(step.get("tags") or ())
    q = step.get("question")
    if q == "thesis":
        return "thesis"
    if "down to the 5% cap" in tags:
        return "cap"
    if q == "valuation":
        return "valuation"
    if "redundant" in tags:
        return "redundant"
    if "rebalance" in tags:
        return "rebalance"
    return "other"


# ---------------- sections ----------------


def _markets(guide_payload: Mapping | None, stances: Sequence[Mapping]) -> list[str]:
    idn = next((s for s in stances if s.get("subject") == "IDN"), None) or {}
    world = (guide_payload or {}).get("regime") or idn.get("regime")
    parts = [WORLD.get(world, str(world or "unknown").replace("_", " "))]
    if idn.get("dollar") in DOLLAR:
        parts.append(DOLLAR[idn["dollar"]])
    home = idn.get("home_regime") or {}
    if home.get("state") == "risk_off":
        why = "; ".join(re.sub(r"\s*\(\d+\)$", "", d) for d in home.get("drivers") or ())
        parts.append("Indonesia nervous" + (f" ({why})" if why else ""))
    elif home.get("state"):
        parts.append("Indonesia calm")
    out = wrap("Markets: " + "; ".join(parts) + ".", rest="")
    if home.get("state") == "risk_off":
        out += wrap("Indonesian buys and sells are spread out.", rest="")
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


def _buys(steps: Sequence[Mapping]) -> list[str]:
    out = []
    for s in steps:
        name = re.sub(r"^Buy\s+", "", s["label"])
        name = name[:1].upper() + name[1:]
        out += wrap(f"{name} Rp {_m(s['idr'])}:", first="• ")
        why = _first_sentence(s.get("why"))
        if why:
            out += wrap(why, first="  ")
    return out


def _sells(steps: Sequence[Mapping]) -> list[str]:
    groups: dict[str, list[Mapping]] = {}
    for s in steps:
        groups.setdefault(_group(s), []).append(s)
    label = dict(SELL_GROUPS)
    order = sorted(groups, key=lambda k: (-sum(s["idr"] for s in groups[k]), k))
    out = []
    for k in order:
        g = sorted(groups[k], key=lambda s: (-s["idr"], s.get("symbol") or ""))
        out += wrap(f"{label[k]} ({len(g)}, Rp {_m(sum(s['idr'] for s in g))}):", first="• ")
        names = [f"{s.get('symbol') or s['label']} {_m(s['idr'])}" for s in g[:TOP_PER_GROUP]]
        if len(g) > TOP_PER_GROUP:
            names.append(f"+{len(g) - TOP_PER_GROUP} more")
        out += wrap(", ".join(names), first="  ")
    return out


def _thesis(holdings: Mapping | None) -> list[str]:
    if not holdings:
        return []
    fails = sorted(h["symbol"] for h in holdings.get("holdings") or ()
                   if ((h.get("acted") or {}).get("thesis") or {}).get("acts"))
    if not fails:
        return []
    on = ((holdings.get("config") or {}).get("hysteresis") or {}).get("act_on_verdicts")
    note = ("Sold in the steps above." if on
            else "Paper: not acted on yet (the switch is off).")
    return ["", f"# Business no longer passes ({len(fails)})",
            *wrap(" ".join(fails), rest=""), *wrap(note, rest="")]


def _best(payloads: Sequence[Mapping]) -> list[str]:
    p = next((x for x in payloads if x.get("market") == "IDN"), None)
    if p is None:
        return []
    passing = [plain.label("style", s["style"]) for s in p.get("styles") or () if s["passed"]]
    rows = _undervalued.top(p, 5)
    if not passing or not rows:
        return ["", "# Best value now", "No stock screen passes its test this week."]
    names = " ".join(r["symbol"] for r in rows)
    new = [r["symbol"] for r in rows if not r.get("held")]
    held = (", all held" if not new else ", none held" if len(new) == len(rows)
            else f", {' '.join(new)} not held")
    return ["", f"# Best value now ({' and '.join(passing)})", *wrap(names + held, rest="")]


# ---------------- the message ----------------


def weekly(*, day: date, guide_payload: Mapping | None, stances: Sequence[Mapping] = (),
           undervalued: Sequence[Mapping] = (), holdings: Mapping | None = None) -> str:
    """The Monday message (module docstring), lines of at most `WIDTH` characters."""
    lines = [f"# investment-assist, {day:%a} {day.day} {day:%b %Y}", DISCLAIMER_LINE, "",
             *_markets(guide_payload, stances)]
    g = guide_payload
    if g is None:
        lines += ["", "No steps this run: the guide is missing. Open the home page."]
    elif g.get("held_for_data"):
        lines += ["", *wrap("No orders this week: some inputs are broken, so last week's "
                            "holdings stand.", rest="")]
        lines += [x for h in g["held_for_data"] for x in wrap(h, first="• ")]
    elif not g.get("steps"):
        lines += ["", "Nothing to do this week: every leg is at its target."]
    else:
        steps = g["steps"]
        buys = [s for s in steps if s["side"] == "buy"]
        sells = [s for s in steps if s["side"] == "sell"]
        t = g["totals"]
        head = ", ".join(x for x in (f"buy Rp {_m(t['buy_idr'])}" if buys else "",
                                      f"sell Rp {_m(t['sell_idr'])}" if sells else "") if x)
        lines += ["", f"# This week: {head}", *_dates(steps)]
        if buys:
            lines += ["", "# Buy", *_buys(buys)]
        if sells:
            lines += ["", f"# Sell ({len(sells)}, Rp {_m(t['sell_idr'])})", *_sells(sells)]
    lines += _thesis(holdings)
    lines += _best(undervalued)
    return "\n".join(lines)


# ---------------- the 07:00 message (T3) ----------------


DOLLAR_WORD = {"up": "rising", "flat": "steady", "down": "falling"}


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
    """The one 07:00 message: mood changes, holding changes, data health; one disclaimer."""
    lines = [f"# investment-assist morning, {day:%a} {day.day} {day:%b %Y}", DISCLAIMER_LINE]
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
