"""The home page (/, PLAN S76): this week's steps from `out/guide.json` (`assist.guide`), laid
out by order date so it reads as "what to place on this day".

- The headline: the regime in plain words, and how many orders to sell and buy.
- The legs: each benchmark leg's held share, target and what closes the gap.
- One card per tranche date, the first open and the later ones folded: every order of that day
  with its shares, price instruction, amount, strength (its meaning on hover) and why.
- The buys' take-profit and stop, when there is a named buy.

A missing or schema-failing file is a notice and a pointer to `assist run`, never a 500. The
page opens no store and writes nothing. The `.json` twin is the file as read plus the problem.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from assist import guide, plain, web
from assist.web import esc

TITLE = "Assist This week"
STRENGTH_TONE = {"strong": "bad", "medium": "warn", "weak": "muted"}
REGIME_TONE = {"risk_on": "good", "neutral": "muted", "risk_off": "bad"}
COLUMNS = ("#", "Order", "Shares", "Price", "Amount", "Strength", "Why")

STYLE = """<style>
.guide .lead { font-size:16px; margin:6px 0 2px; }
.guide td.num, .guide th.num { text-align:right; white-space:nowrap; }
.guide td.order { white-space:nowrap; font-weight:600; }
.guide .sell { color:var(--bad); } .guide .buy { color:var(--good); }
.guide details.day { margin:0 0 12px; }
.guide details.day > summary { cursor:pointer; font-weight:600; padding:6px 0; }
.guide .tag { color:var(--muted); font-weight:400; font-size:12px; }
.guide .chip[title] { cursor:help; }
</style>"""


def _idr(x: Any) -> str:
    return "-" if not isinstance(x, (int, float)) or isinstance(x, bool) else f"Rp {x:,.0f}"


def _m(x: float) -> str:
    return f"Rp {x / 1e6:,.1f}m"


def _day(s: str) -> str:
    try:
        return date.fromisoformat(s).strftime("%a %d %b %Y")
    except ValueError:
        return s


def _price(t: Mapping) -> str:
    p = t.get("price") or {}
    at = p.get("at")
    if p.get("type") == "limit" and at is not None:
        return f"limit {at:,.0f} or lower"
    if p.get("type") == "market_cap" and at is not None:
        return f"at market, not above {at:,.0f}"
    return "at market"


def _strength(s: str) -> str:
    return (f'<span class="chip {STRENGTH_TONE.get(s, "muted")}" '
            f'title="{esc(plain.meaning("strength", s) or "")}">'
            f'{esc(plain.label("strength", s))}</span>')


def by_date(g: Mapping) -> list[tuple[str, list[dict]]]:
    """[(date, [order])]: each step's tranche on that date, in step order."""
    days: dict[str, list[dict]] = {}
    for s in g["steps"]:
        for i, t in enumerate(s["tranches"], 1):
            days.setdefault(t["date"], []).append({"step": s, "tranche": t, "part": i,
                                                   "parts": len(s["tranches"])})
    return sorted(days.items())


def _orders(orders: Sequence[Mapping]) -> str:
    head = "<tr>" + "".join(
        f'<th{" class=\"num\"" if c in ("Shares", "Amount") else ""}>{c}</th>'
        for c in COLUMNS) + "</tr>"
    rows = []
    for o in orders:
        s, t = o["step"], o["tranche"]
        part = f' <span class="tag">part {o["part"]} of {o["parts"]}</span>' if o["parts"] > 1 \
            else ""
        tags = "".join(f' <span class="tag">{esc(x)}</span>' for x in s.get("tags") or [])
        shares = "-" if t["shares"] is None else f"{t['shares']:,}"
        rows.append(
            f'<tr data-step="{s["n"]}"><td>{s["n"]}</td>'
            f'<td class="order {esc(s["side"])}">{esc(s["label"])}{part}{tags}</td>'
            f'<td class="num">{shares}</td><td>{esc(_price(t))}</td>'
            f'<td class="num">{esc(_idr(t["idr"]))}</td><td>{_strength(s["strength"])}</td>'
            f'<td>{esc(s["why"])} <a href="{esc(s["detail"])}">details</a></td></tr>')
    return f"<table>{head}{''.join(rows)}</table>"


def _days(g: Mapping) -> str:
    out = []
    for i, (d, orders) in enumerate(by_date(g)):
        sell = sum(o["tranche"]["idr"] for o in orders if o["step"]["side"] == "sell")
        buy = sum(o["tranche"]["idr"] for o in orders if o["step"]["side"] == "buy")
        summary = (f"{esc(_day(d))}: {len(orders)} order(s), sell {esc(_m(sell))}, "
                   f"buy {esc(_m(buy))}")
        out.append(f'<details class="day" data-date="{esc(d)}"{" open" if i == 0 else ""}>'
                   f"<summary>{summary}</summary>{_orders(orders)}</details>")
    return "".join(out)


def _legs(g: Mapping) -> str:
    rows = []
    for leg in g["legs"]:
        gap = leg.get("gap_idr")
        if gap is None:
            todo = "-"
        elif abs(gap) < guide.MIN_STEP_IDR:
            todo = "at target"
        else:
            todo = f"{'buy' if gap > 0 else 'sell'} {_m(abs(gap))}"
        st = leg.get("stance")
        stance = "-" if not st else (f'<span title="{esc(plain.meaning("stance", st) or "")}">'
                                     f'{esc(plain.label("stance", st))}</span>')
        cur, tgt = leg.get("current_pct"), leg.get("target_pct")
        rows.append(f"<tr><td>{esc(leg['label'][0].upper() + leg['label'][1:])}</td>"
                    f'<td class="num">{"-" if cur is None else f"{cur:.1f}%"}</td>'
                    f'<td class="num">{"-" if tgt is None else f"{tgt:.1f}%"}</td>'
                    f"<td>{stance}</td><td>{esc(todo)}</td></tr>")
    return ('<section class="card legs"><header><h2>Your portfolio against its usual shares'
            "</h2></header><table><tr><th>Part</th><th class=\"num\">You hold</th>"
            '<th class="num">Target</th><th>View</th><th>To do</th></tr>'
            + "".join(rows) + "</table>"
            f'<p class="muted">Portfolio {esc(_idr(g.get("portfolio_value_idr")))}. '
            'Holdings: <a href="/portfolio">Portfolio</a>.</p></section>')


def _exits(g: Mapping) -> str:
    buys = [s for s in g["steps"] if s["side"] == "buy" and s["kind"] == "name"]
    if not buys:
        return ""
    rows = []
    for s in buys:
        tp, stop = s.get("take_profit") or {}, s.get("stop") or {}
        tp_text = "-" if tp.get("at") is None else f"{tp['at']:,.0f}: {tp.get('action') or ''}"
        review = "-" if stop.get("review_at") is None else f"{stop['review_at']:,.0f}"
        rows.append(f"<tr><td>{esc(str(s['symbol']))}</td><td>{esc(tp_text)}</td>"
                    f"<td>{esc(stop.get('rule') or '-')}</td><td>{esc(review)}</td></tr>")
    return ('<section class="card exits"><header><h2>After you buy</h2></header>'
            "<table><tr><th>Stock</th><th>Take profit at</th><th>Sell when</th>"
            "<th>Look again at</th></tr>" + "".join(rows) + "</table>"
            '<p class="muted">Take profit is the fair price: above it the stock no longer beats '
            "the required return. \"Look again at\" is a warning level, not a sell order.</p>"
            "</section>")


def body(g: Mapping | None, problem: str | None) -> str:
    parts = [STYLE, '<div class="guide"><h1>This week</h1>']
    if problem:
        parts.append(web.notice(problem))
    if g is not None:
        t = g["totals"]
        tone = REGIME_TONE.get(str(g.get("regime")), "muted")
        parts.append(
            f'<p class="lead">{web.chip(g["headline"], tone)} '
            f'<span class="muted">{esc(g["headline_note"])}</span></p>')
        if g["steps"]:
            parts.append(
                f'<p class="lead">Sell {t["sells"]} ({esc(_m(t["sell_idr"]))}) and buy '
                f'{t["buys"]} ({esc(_m(t["buy_idr"]))})'
                + (f", each in up to {g['split']} parts." if g["split"] > 1 else ".") + "</p>")
        else:
            parts.append('<p class="lead">Nothing to do this week: every part of the portfolio '
                         "is at its target.</p>")
        parts += [f'<p class="muted">Run of {esc(str(g["as_of"]))}. Paper only, not an order. '
                  "Sells come first: they pay for the buys. Dates skip weekends, not IDX "
                  "holidays.</p>", _legs(g)]
        if g["steps"]:
            parts.append('<section class="card orders"><header><h2>Orders by date</h2></header>'
                         + _days(g) + "</section>")
        parts.append(_exits(g))
        if g.get("notes"):
            parts.append('<section class="card notes"><header><h2>Notes</h2></header><ul>'
                         + "".join(f"<li>{esc(n)}</li>" for n in g["notes"]) + "</ul></section>")
    parts.append('<p class="muted">Why these steps: <a href="/candidates">Candidates</a>, '
                 '<a href="/regime">Regime</a>, <a href="/signals">Signals</a>. Countries and '
                 'commodities outside your benchmark: <a href="/background">Background</a>.</p>')
    parts.append("</div>")
    return "".join(parts)


def page(app: web.App, _m: re.Match[str]) -> web.View:
    g, problem = guide.load(app.out_dir)
    return web.View(TITLE, body(g, problem), {"guide": g, "problem": problem})
