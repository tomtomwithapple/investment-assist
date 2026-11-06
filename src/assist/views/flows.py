"""The flows page (/flows, /flows/<YYYY-MM>, PLAN S38): where the household's money moved in a
month.

Reads `app.out_dir/flows/index.json` and the month files it lists, as written by `assist flows`;
the page never opens a store. `/flows` shows the index's latest month, `/flows/<YYYY-MM>` a month
the index lists: the file name comes from the index entry (checked against `YYYY-MM`), never from
the URL, so a month not in the index is a 404. Every value read from a file goes through `esc`.

The page: links to every month, a summary, then a stdlib SVG diagram (one column of accounts per
owner, an arrow per account pair of matched transfers whose width follows the amount, and dashed
arrows to or from a "no statement" box per owner for the unmatched named debits and settlements),
then tables of the matched transfers, the unmatched items with their reason, external totals per
account and owner, and the accounts with their statement balances. The `.json` twin is the month
file as written.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from assist import web
from assist.flows import INDEX, MONTH_RX, OUT_DIR
from assist.web import esc

TITLE = "Assist Flows"
EMPTY = "no flows in out/flows/ yet: run `assist flows`"
NO_MONTHS = "no months in out/flows/index.json"
DASH = "-"

# diagram geometry (SVG user units; the SVG scales to the card's width)
COL_W, COL_GAP, BOX_H, ROW_GAP, HEAD, PAD, LOOP = 210, 170, 34, 18, 34, 14, 46
W_MIN, W_MAX = 1.5, 14.0

STYLE = """<style>
.flows { --flow:#2a78d6; --gap:#c77700; --box:#c9c8c3; }
@media (prefers-color-scheme: dark) { .flows { --flow:#5a9de8; --gap:#f0c46a; --box:#55554f; } }
.flows svg { width:100%; min-width:640px; height:auto; display:block; }
.flows svg text { fill:var(--fg); font-size:12px; }
.flows svg text.muted, .flows svg text.owner { fill:var(--muted); }
.flows svg text.owner { font-size:12px; font-weight:600; text-transform:uppercase;
  letter-spacing:.04em; }
.flows svg rect.box { fill:var(--card); stroke:var(--box); stroke-width:1; }
.flows svg rect.box.gap { stroke:var(--gap); stroke-dasharray:4 3; }
.flows svg path.arrow { fill:none; stroke-linecap:round; opacity:.85; }
.flows svg path.arrow.matched { stroke:var(--flow); }
.flows svg path.arrow.unmatched { stroke:var(--gap); stroke-dasharray:7 5; }
.flows svg path.arrow:hover { opacity:1; }
.flows svg marker path { stroke:none; }
.flows svg #head-m path { fill:var(--flow); } .flows svg #head-u path { fill:var(--gap); }
.flows .months { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0 0; }
.flows .months a { padding:2px 9px; border:1px solid var(--line); border-radius:999px;
  text-decoration:none; color:var(--muted); font-size:13px; }
.flows .months a.active { color:var(--fg); border-color:var(--muted); font-weight:600; }
.flows td .tail { display:block; }
.flows td.num, .flows th.num { text-align:right; white-space:nowrap; }
.flows .legend { display:flex; gap:16px; flex-wrap:wrap; color:var(--muted); font-size:12px;
  margin:4px 0 8px; }
.flows .key { display:inline-block; width:18px; height:0; vertical-align:middle;
  margin-right:5px; border-top:3px solid var(--flow); }
.flows .key.gap { border-top:3px dashed var(--gap); }
</style>"""

KIND = {"transfer": "transfer", "settlement": "broker settlement", "card_payment": "card payment"}


# ---------------- files ----------------


def _read(path: Path, cache: dict | None) -> tuple[Any, str | None]:
    """(parsed JSON, problem); cached per mtime in the app's view cache."""
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None, "missing"
    key = ("flows", str(path))
    if cache is not None and (hit := cache.get(key)) and hit[0] == stamp:
        return hit[1], None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{OUT_DIR / path.name} is not valid JSON ({e})"
    if cache is not None:
        cache[key] = (stamp, data)
    return data, None


def months(index: Any) -> list[str]:
    """The index's months that are well formed (`YYYY-MM` and file `YYYY-MM.json`), in order."""
    out = []
    for m in (index.get("months") if isinstance(index, Mapping) else None) or []:
        if not isinstance(m, Mapping):
            continue
        month = m.get("month")
        if isinstance(month, str) and MONTH_RX.match(month) and m.get("file") == f"{month}.json":
            out.append(month)
    return out


def load_index(out_dir: Path, cache: dict | None = None) -> tuple[dict | None, str | None]:
    data, problem = _read(Path(out_dir) / OUT_DIR / INDEX, cache)
    if problem == "missing":
        return None, EMPTY
    if problem:
        return None, problem
    if not isinstance(data, dict):
        return None, NO_MONTHS
    return data, None


def load_month(out_dir: Path, month: str, cache: dict | None = None) -> tuple[dict | None, str]:
    """`month` must come from `months(index)`."""
    data, problem = _read(Path(out_dir) / OUT_DIR / f"{month}.json", cache)
    if problem == "missing":
        return None, f"{OUT_DIR}/{month}.json is listed in the index but missing"
    if problem:
        return None, problem
    if not isinstance(data, dict):
        return None, f"{OUT_DIR}/{month}.json is not a month of flows"
    return data, ""


# ---------------- formatting ----------------


def idr(x: Any) -> str:
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x):
        return DASH
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"


def _s(x: Any) -> str:
    return esc(DASH if x is None else str(x))


def _list(p: Mapping, key: str) -> list[Mapping]:
    return [x for x in p.get(key) or [] if isinstance(x, Mapping)]


def _accounts(p: Mapping) -> dict[str, Mapping]:
    return {str(a.get("id")): a for a in _list(p, "accounts")}


def account_label(a: Mapping | None, with_owner: bool = True) -> str:
    """`issuer ·1234 (owner)`, escaped."""
    if a is None:
        return DASH
    acct = str(a.get("account") or "")
    owner = f" ({a.get('owner')})" if with_owner else ""
    return esc(f"{a.get('issuer', '')}{' ·' + acct if acct else ''}{owner}")


# ---------------- diagram ----------------


def arrow_widths(amounts: Sequence[float]) -> list[float]:
    """Stroke width per arrow, linear in the amount: the largest is `W_MAX`, none below `W_MIN`."""
    top = max((a for a in amounts if a > 0), default=0)
    return [W_MIN if top <= 0 else max(W_MIN, W_MAX * a / top) for a in amounts]


def _edges(src: tuple[float, float], dst: tuple[float, float], same: bool) -> str:
    (sx, sy), (dx, dy) = src, dst
    if same:  # both in one column: loop out to the right
        x0, x1 = sx + COL_W, sx + COL_W + LOOP
        return f"M{x0:.1f},{sy:.1f} C{x1:.1f},{sy:.1f} {x1:.1f},{dy:.1f} {x0 + 6:.1f},{dy:.1f}"
    if dx > sx:
        x0, x1 = sx + COL_W, dx - 6
    else:
        x0, x1 = sx, dx + COL_W + 6
    mid = (x0 + x1) / 2
    return f"M{x0:.1f},{sy:.1f} C{mid:.1f},{sy:.1f} {mid:.1f},{dy:.1f} {x1:.1f},{dy:.1f}"


def diagram(p: Mapping) -> str:
    accts = _accounts(p)
    named, settles = _list(p, "unmatched_named"), _list(p, "unmatched_settlements")
    owners = sorted({str(a.get("owner")) for a in accts.values()}
                    | {str(u.get("to_owner")) for u in named})
    gap_owner: dict[str, bool] = {o: False for o in owners}
    for u in named:
        gap_owner[str(u.get("to_owner"))] = True
    for u in settles:
        a = accts.get(str(u.get("account")))
        if a is not None:
            gap_owner[str(a.get("owner"))] = True
    pos: dict[str, tuple[float, float]] = {}  # node id → (x of box, y of its middle)
    col_of: dict[str, int] = {}
    boxes, rows = [], 0
    for i, owner in enumerate(owners):
        x = PAD + i * (COL_W + COL_GAP)
        boxes.append(f'<text class="owner" x="{x}" y="{PAD + 12}">{esc(owner)}</text>')
        members = sorted((a for a in accts.values() if str(a.get("owner")) == owner),
                         key=lambda a: (str(a.get("issuer")), str(a.get("account"))))
        nodes = [(str(a.get("id")), account_label(a, with_owner=False), "box") for a in members]
        if gap_owner.get(owner):
            nodes.append((f"gap:{owner}", "no statement in financer", "box gap"))
        for j, (nid, label, cls) in enumerate(nodes):
            y = PAD + HEAD + j * (BOX_H + ROW_GAP)
            pos[nid], col_of[nid] = (x, y + BOX_H / 2), i
            boxes.append(f'<g><rect class="{cls}" x="{x}" y="{y}" width="{COL_W}" '
                         f'height="{BOX_H}" rx="6"/><text x="{x + 10}" y="{y + 21}">{label}'
                         "</text></g>")
        rows = max(rows, len(nodes))
    # matched transfers, one arrow per account pair
    pairs: dict[tuple[str, str], list[float]] = {}
    for t in _list(p, "transfers"):
        k = (str(t.get("from")), str(t.get("to")))
        if k[0] in pos and k[1] in pos and isinstance(t.get("amount"), (int, float)):
            pairs.setdefault(k, []).append(float(t["amount"]))
    gaps: dict[tuple[str, str], list[tuple[float, str]]] = {}  # one dashed arrow per pair
    for u in named:
        src, dst = str(u.get("from")), f"gap:{u.get('to_owner')}"
        if src in pos and dst in pos and isinstance(u.get("amount"), (int, float)):
            gaps.setdefault((src, dst), []).append((float(u["amount"]), str(u.get("reason"))))
    for u in settles:
        a = accts.get(str(u.get("account")))
        if a is None or not isinstance(u.get("amount"), (int, float)):
            continue
        box, acct = f"gap:{a.get('owner')}", str(a.get("id"))
        src, dst = (box, acct) if u.get("direction") == "credit" else (acct, box)
        gaps.setdefault((src, dst), []).append((float(u["amount"]), str(u.get("reason"))))
    widths = arrow_widths([sum(v) for v in pairs.values()]
                          + [sum(a for a, _ in v) for v in gaps.values()])
    arrows = []
    for ((src, dst), amts), w in zip(pairs.items(), widths, strict=False):
        tip = (f"{_plain(accts.get(src))} → {_plain(accts.get(dst))}: IDR {idr(sum(amts))}"
               f" ({_n(len(amts), 'transfer')})")
        arrows.append(_arrow("matched", src, dst, w, tip, pos, col_of))
    for ((src, dst), items), w in zip(gaps.items(), widths[len(pairs):], strict=False):
        reasons = "; ".join(dict.fromkeys(r for _, r in items))
        tip = f"IDR {idr(sum(a for a, _ in items))} ({_n(len(items), 'item')}): {reasons}"
        arrows.append(_arrow("unmatched", src, dst, w, tip, pos, col_of))
    width = PAD * 2 + len(owners) * COL_W + max(0, len(owners) - 1) * COL_GAP + LOOP + 10
    height = PAD * 2 + HEAD + rows * (BOX_H + ROW_GAP)
    defs = ("<defs>" + "".join(
        f'<marker id="head-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" '
        f'markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z"/></marker>' for k in ("m", "u")) + "</defs>")
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Money moved between '
            f'the household\'s accounts">{defs}{"".join(arrows)}{"".join(boxes)}</svg>')


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _plain(a: Mapping | None) -> str:
    if a is None:
        return DASH
    return f"{a.get('issuer', '')} ·{a.get('account', '')} ({a.get('owner', '')})"


def _arrow(cls: str, src: str, dst: str, w: float, tip: str,
           pos: Mapping[str, tuple[float, float]], col_of: Mapping[str, int]) -> str:
    d = _edges(pos[src], pos[dst], col_of[src] == col_of[dst])
    head = "m" if cls == "matched" else "u"
    return (f'<path class="arrow {cls}" d="{d}" stroke-width="{w:.1f}" '
            f'marker-end="url(#head-{head})"><title>{esc(tip)}</title></path>')


# ---------------- page ----------------


def _month_links(ms: Sequence[str], current: str) -> str:
    links = "".join(f'<a href="/flows/{esc(m)}"{" class=\"active\"" if m == current else ""}>'
                    f"{esc(m)}</a>" for m in reversed(ms))
    return f'<nav class="months" aria-label="Months">{links}</nav>'


def _table(head: Sequence[str], rows: Sequence[str], empty: str) -> str:
    if not rows:
        return f'<p class="muted">{esc(empty)}</p>'
    ths = "".join(f'<th{" class=\"num\"" if h.endswith("IDR") else ""}>{esc(h)}</th>'
                  for h in head)
    return f"<table><tr>{ths}</tr>{''.join(rows)}</table>"


def render(p: Mapping, ms: Sequence[str], month: str) -> str:
    accts = _accounts(p)
    tot = p.get("totals") if isinstance(p.get("totals"), Mapping) else {}

    def t(key: str) -> tuple[str, str]:
        x = tot.get(key) if isinstance(tot.get(key), Mapping) else {}
        return _s(x.get("n", 0)), idr(x.get("amount"))

    stale = "".join(web.notice(str(s)) for s in p.get("stale_inputs") or [])
    tn, ta = t("transfers")
    nn, na = t("unmatched_named")
    sn, sa = t("unmatched_settlements")
    summary = (f'<p class="muted">As of {_s(p.get("as_of"))}. {tn} matched transfers (IDR {ta}),'
               f" {nn} named debits unmatched (IDR {na}), {sn} broker settlements unmatched "
               f"(IDR {sa}). Matched: equal to the rupiah, at most "
               f"{_s((p.get('rules') or {}).get('max_gap_days'))} days apart, one to one.</p>")
    legend = ('<div class="legend"><span><span class="key"></span>matched transfer (width '
              'follows the amount)</span><span><span class="key gap"></span>unmatched: the other '
              "side has no statement</span></div>")
    transfers = [
        f"<tr><td>{_s(x.get('date'))}"
        f"{'' if x.get('date_to') == x.get('date') else ' → ' + _s(x.get('date_to'))}</td>"
        f"<td>{account_label(accts.get(str(x.get('from'))))}"
        f'<span class="tail">{_s(x.get("from_description"))}</span></td>'
        f"<td>{account_label(accts.get(str(x.get('to'))))}"
        f'<span class="tail">{_s(x.get("to_description"))}</span></td>'
        f"<td>{esc(KIND.get(str(x.get('kind')), str(x.get('kind'))))}</td>"
        f"<td class=\"num\">{_s(x.get('gap_days'))}</td>"
        f'<td class="num">{idr(x.get("amount"))}</td></tr>' for x in _list(p, "transfers")]
    named = [
        f"<tr><td>{_s(x.get('date'))}</td><td>{account_label(accts.get(str(x.get('from'))))}"
        f'<span class="tail">{_s(x.get("description"))}</span></td>'
        f"<td>{_s(x.get('reason'))}</td><td class=\"num\">{idr(x.get('amount'))}</td></tr>"
        for x in _list(p, "unmatched_named")]
    settles = [
        f"<tr><td>{_s(x.get('date'))}</td><td>{account_label(accts.get(str(x.get('account'))))}"
        f"</td><td>{_s(x.get('reason'))}</td><td class=\"num\">{idr(x.get('amount'))}</td></tr>"
        for x in _list(p, "unmatched_settlements")]
    ext = p.get("external") if isinstance(p.get("external"), Mapping) else {}
    ext_rows = [
        f"<tr><td>{account_label(accts.get(str(x.get('account'))))}</td>"
        f'<td class="num">{idr(x.get("in"))} <span class="muted">({_s(x.get("n_in"))})</span>'
        f'</td><td class="num">{idr(x.get("out"))} <span class="muted">({_s(x.get("n_out"))})'
        "</span></td></tr>" for x in _list(ext, "accounts")]
    owner_rows = [f"<tr><td>{_s(x.get('owner'))}</td><td class=\"num\">{idr(x.get('in'))}</td>"
                  f"<td class=\"num\">{idr(x.get('out'))}</td></tr>" for x in _list(ext, "owners")]
    acct_rows = [
        f"<tr><td>{account_label(a, with_owner=False)}</td><td>{_s(a.get('owner'))}</td>"
        f"<td>{_s(a.get('kind'))}</td><td class=\"num\">{idr(a.get('opening'))}</td>"
        f"<td class=\"num\">{idr(a.get('closing'))}</td>"
        f"<td>{esc(', '.join(str(s) for s in a.get('statements') or []) or DASH)}</td></tr>"
        for a in accts.values()]
    return (
        f'{STYLE}<div class="flows"><h1>Flows {esc(month)}</h1>{_month_links(ms, month)}'
        f"{summary}{stale}"
        f'<section class="card"><header><h2>Where the money moved</h2></header>{legend}'
        f"{diagram(p)}</section>"
        '<section class="card"><header><h2>Matched transfers</h2></header>'
        + _table(("Date", "From", "To", "Kind", "Gap (days)", "Amount IDR"), transfers,
                 "no transfer matched this month")
        + '</section><section class="card"><header><h2>Unmatched</h2></header>'
        '<h3>Named debits</h3>'
        + _table(("Date", "From", "Why", "Amount IDR"), named, "none")
        + "<h3>Broker settlements</h3>"
        + _table(("Settles", "Account", "Why", "Amount IDR"), settles, "none")
        + '</section><section class="card"><header><h2>External in and out</h2></header>'
        + _table(("Account", "In IDR", "Out IDR"), ext_rows, "no external movements")
        + _table(("Owner", "In IDR", "Out IDR"), owner_rows, "")
        + '</section><section class="card"><header><h2>Accounts</h2></header>'
        + _table(("Account", "Owner", "Kind", "Opening IDR", "Closing IDR", "Statements"),
                 acct_rows, "no accounts")
        + "</section></div>")


def _month_view(app: web.App, index: Mapping, month: str) -> web.View:
    ms = months(index)
    p, problem = load_month(app.out_dir, month, app.cache)
    if p is None:
        body = f"<h1>Flows {esc(month)}</h1>{_month_links(ms, month)}{web.notice(problem)}"
        return web.View(f"{TITLE} {month}", body, {"month": month, "problem": problem})
    return web.View(f"{TITLE} {month}", render(p, ms, month), p)


def index(app: web.App, _m: re.Match[str]) -> web.View:
    idx, problem = load_index(app.out_dir, app.cache)
    ms = months(idx) if idx is not None else []
    if not ms:
        msg = problem or NO_MONTHS
        return web.View(TITLE, f"<h1>Flows</h1>{web.notice(msg)}",
                        {"months": [], "problem": msg})
    latest = idx.get("latest")
    return _month_view(app, idx, latest if latest in ms else ms[-1])


def page(app: web.App, m: re.Match[str]) -> web.View | None:
    idx, _ = load_index(app.out_dir, app.cache)
    ms = months(idx) if idx is not None else []
    month = next((x for x in ms if x == m.group(1)), None)
    return None if month is None else _month_view(app, idx, month)
