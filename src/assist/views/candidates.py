"""The candidates pages (/candidates and /candidates/<MKT>): one market's undervalued list per
section, from every `app.out_dir/candidates/*.json` (IDN first, then by name).

Each file is globbed and json-loaded here, not through `undervalued.load_out` (which skips an
invalid file silently): a file that is not JSON or not an object is a notice; one that parses
but does not match schema/candidates.schema.json is a notice and still renders. Every field is
read with `.get`, so an absent one shows "-", never a KeyError. The <MKT> from the URL is matched
exactly against the file stems found; it is never turned into a path, so anything else is a 404.
The .json twins are {markets, problems} and the market's payload as written.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from assist import brief, web
from assist.views.overview import TONE
from assist.web import esc

TITLE = "Assist Candidates"
HOME = "IDN"
DIR = "candidates"
DASH = "-"
EMPTY = "no candidate lists in out/candidates/ yet: run `assist run`"
COLUMNS = ("#", "Symbol", "Sector", "Action", "Expected", "Margin", "Tilt shift", "Net of cost",
           "Round trip bps", "Entry", "Held", "Avg cost", "vs cost", "Size")
DOWN_COLUMNS = ("Symbol", "Status", "Avg cost", "Price", "vs cost", "New avg cost", "Entry status",
                "Reason")


@dataclass
class Market:
    key: str  # the file stem: what /candidates/<MKT> matches
    file: str
    payload: dict | None  # None when the file is not a JSON object
    problem: str | None


def load(out_dir: Path) -> list[Market]:
    d = Path(out_dir) / DIR
    files = sorted(d.glob("*.json"), key=lambda f: (f.stem != HOME, f.stem)) if d.is_dir() else []
    validator = None
    out = []
    for f in files:
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(Market(f.stem, f.name, None, f"invalid JSON ({e})"))
            continue
        if not isinstance(p, dict):
            out.append(Market(f.stem, f.name, None, "not a JSON object"))
            continue
        if validator is None:
            from assist.layers import undervalued  # jsonschema; only when a file is found
            validator = undervalued.validator()
        err = next(iter(validator.iter_errors(p)), None)
        problem = None if err is None else f"does not match the schema: {err.message}"
        out.append(Market(f.stem, f.name, p, problem))
    return out


# ---------------- formatting (every helper returns escaped HTML) ----------------


def _d(m: Mapping | None) -> Mapping:
    return m if isinstance(m, Mapping) else {}


def _l(x: Any) -> list:
    return x if isinstance(x, list) else []


def _num(x: Any, fmt: str) -> str:
    return DASH if not isinstance(x, (int, float)) or isinstance(x, bool) else format(x, fmt)


def _text(x: Any) -> str:
    return DASH if x is None or x == "" else esc(str(x))


def _idr(x: Any) -> str:
    return DASH if _num(x, ",.0f") == DASH else f"IDR {x:,.0f}"


def _pct(x: Any) -> str:
    return DASH if _num(x, ".2f") == DASH else f"{x:.2f}%"


def _pt(x: Any) -> str:
    return DASH if _num(x, "+.2f") == DASH else f"{x:+.2f}pt"


def _pct1(x: Any) -> str:
    return DASH if _num(x, "g") == DASH else esc(brief._pct(x))


def _pct1s(x: Any) -> str:
    return _num(x, "+.1f") + ("%" if _num(x, "f") != DASH else "")


def _verdict_chip(passed: Any) -> str:
    if passed is None:
        return web.chip("unknown", "muted")
    return web.chip("passed", "good") if passed else web.chip("failed", "bad")


def _card(cls: str, title: str, inner: str) -> str:
    return (f'<section class="card {cls}"><header><h2>{esc(title)}</h2></header>'
            f"{inner}</section>")


def _kv(rows: Sequence[tuple[str, str]]) -> str:
    return "<table>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</table>"


def _list(items: Sequence[Any]) -> str:
    if not items:
        return '<p class="muted">none</p>'
    return "<ul>" + "".join(f"<li>{_text(x)}</li>" for x in items) + "</ul>"


def _rows(head: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return '<p class="muted">none</p>'
    return ("<table><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
            + "</table>")


# ---------------- sections ----------------


def _summary(p: Mapping) -> str:
    st = _d(p.get("stance"))
    stance = st.get("stance")
    chip = DASH if stance is None else web.chip(stance, TONE.get(stance, "muted"))
    return _card("summary", "Summary", _kv([
        ("As of", _text(p.get("as_of"))), ("Bars", _text(p.get("bar_date"))),
        ("Currency", _text(p.get("currency"))), ("Regime", _text(p.get("regime"))),
        ("Hurdle", _pct(_d(p.get("hurdle")).get("required_pt"))),
        ("Stocks stance",
         f"{chip} {_pct1(st.get('current_pct'))} → {_pct1(st.get('target_pct'))}"),
        ("Model", f"<code>{esc(brief._fingerprint(p['model_fingerprint']))}</code>"
         if isinstance(p.get("model_fingerprint"), str) else DASH)]))


def _tilt(t: Mapping) -> str:
    sectors = _l(t.get("sectors"))
    if t.get("passed"):
        chip, note = _verdict_chip(True), "margins shifted and sector caps set"
    elif t.get("fingerprint") is None and not sectors:  # no tilt run at all (USA, by design)
        chip, note = web.chip("none", "muted"), "no margin shift, default caps"
    else:
        chip, note = _verdict_chip(False), "no margin shift, default caps"
    rows = [[_text(_d(s).get("sector")), _num(_d(s).get("tilt"), "g"),
             _pt(_d(s).get("margin_shift_pt")), _num(_d(s).get("cap"), "d")]
            for s in sectors]
    table = _rows(("Sector", "Tilt", "Margin shift", "Cap"), rows) if rows else ""
    return _card("tilt", "Sector tilt",
                 f"<p>{chip} {_text(t.get('verdict'))} "
                 f'<span class="muted">({note})</span></p>{table}')


def _entry(e: Mapping) -> str:
    level = _num(e.get("level"), ",.0f")
    tags = ", ".join(esc(str(e[k])) for k in ("basis", "status") if e.get(k))
    if level == DASH:
        return DASH if not tags else f"{DASH} ({tags})"
    return f"{level} ({tags})" if tags else level


def _held(r: Mapping) -> str:
    if r.get("held") is None:
        return DASH
    return _idr(r.get("held_idr")) if r["held"] else "no"


def _size(z: Any) -> str:
    z = _d(z)
    if _num(z.get("idr"), "f") == DASH:
        return DASH
    n = len(_l(z.get("tranches")))
    return f"{_idr(z['idr'])} in {n} tranche{'' if n == 1 else 's'}"


def _tranches(r: Mapping) -> str:
    z = _d(r.get("size"))
    tranches = _l(z.get("tranches"))
    if not tranches and not z.get("reason"):
        return ""
    items = "".join(
        f"<li>day {_num(_d(x).get('day'), 'd')}: {_idr(_d(x).get('idr'))}, "
        f"{_num(_d(x).get('shares'), ',d')} shares, limit {_num(_d(x).get('limit'), ',.0f')}</li>"
        for x in tranches)
    reason = f'<span class="muted">{_text(z.get("reason"))}</span>'
    return (f'<tr class="tranches" data-symbol="{esc(str(r.get("symbol", "")))}">'
            f'<td></td><td colspan="{len(COLUMNS) - 1}">{reason}<ul>{items}</ul></td></tr>')


def _row(r: Mapping) -> str:
    cells = [_num(r.get("rank"), "d"), _text(r.get("symbol")), _text(r.get("sector")),
             _text(r.get("action")), _pct(r.get("expected_pt")), _pt(r.get("margin_pt")),
             _pt(r.get("margin_shift_pt")), _pt(r.get("net_margin_pt")),
             _num(_d(r.get("cost")).get("round_trip_bps"), ".0f"), _entry(_d(r.get("entry"))),
             _held(r), _num(_d(r.get("cost_basis")).get("avg_cost"), ",.0f"),
             _pct1s(_d(r.get("cost_basis")).get("below_cost_pct")), _size(r.get("size"))]
    return (f'<tr data-symbol="{esc(str(r.get("symbol", "")))}">'
            + "".join(f"<td>{c}</td>" for c in cells) + "</tr>" + _tranches(r))


def _style(s: Mapping) -> str:
    rows = [_d(r) for r in _l(s.get("rows"))]
    judged = s.get("quarters") != 0  # a replay with no quarters has no t or p to show (as brief)
    stats = [x for x in (None if s.get("t") is None or not judged else f"t {_num(s['t'], '.2f')}",
                         None if s.get("p") is None or not judged else f"p {_num(s['p'], '.3f')}",
                         None if s.get("quarters") is None
                         else f"{_num(s['quarters'], 'd')} quarters",
                         f"pool {_num(s.get('pool'), 'd')}",
                         f"{len(rows)} name(s)" if rows else "no names") if x]
    head = (f"<header><h2>{_text(s.get('style'))}</h2>{_verdict_chip(s.get('passed'))}</header>"
            f"<p>{_text(s.get('verdict'))}</p>"
            f'<p class="muted">{" · ".join(stats)}</p>')
    table = ""
    if rows:
        table = ("<table><tr>" + "".join(f"<th>{esc(c)}</th>" for c in COLUMNS) + "</tr>"
                 + "".join(_row(r) for r in rows) + "</table>")
    dropped = [_d(x) for x in _l(s.get("dropped"))]
    drop = ""
    if dropped:
        drop = ('<div class="dropped"><p class="muted">Dropped</p><ul>'
                + "".join(f"<li>{_text(x.get('symbol'))}: {_text(x.get('reason'))}</li>"
                          for x in dropped) + "</ul></div>")
    return (f'<section class="card style" data-style="{esc(str(s.get("style", "")))}">'
            f"{head}{table}{drop}</section>")


def _average_down(p: Mapping) -> str:
    """PLAN S70: the held names 5% or more below cost and where each stopped (S68's block)."""
    v = brief.average_down_view(p)
    if v is None:
        return ""
    rows = []
    for n in [*v["funded"], *v["unfunded"], *v["stopped"]]:
        status = _text(str(n.get("status", "")).replace("_", " "))
        if n.get("status") == "stopped":
            status += f" (gate {_num(n.get('gate'), 'd')})"
        elif n.get("idr") is not None:
            status += f" {_idr(n['idr'])}"
        rows.append([_text(n.get("symbol")), status, _num(n.get("avg_cost"), ",.0f"),
                     _num(n.get("price"), ",.0f"), _pct1s(n.get("below_cost_pct")),
                     _num(n.get("new_avg_cost"), ",.0f"), _text(n.get("entry_status")),
                     _text(n.get("reason"))])
    note = (f'<p class="muted">{v["underwater"]} of {v["held"]} held names are '
            f'{_num(v["underwater_pct"], "g")}% or more below their average cost. Cost basis is '
            f"a label: it changes no size. Entry status is {_text(v['gate3'])} "
            "(its placebo has too little history).</p>")
    return _card("average-down", "Average down", note + _rows(DOWN_COLUMNS, rows))


def _sizing(z: Mapping) -> str:
    return "".join([
        _card("sizing", "Sizing", _kv([("Portfolio", _idr(z.get("portfolio_value_idr"))),
                                       ("Budget", _idr(z.get("budget_idr"))),
                                       ("Unspent", _idr(z.get("unspent_idr")))])),
        _card("trims", "Trims", _rows(("Symbol", "IDR", "Reason"), [
            [_text(_d(x).get("symbol")), _idr(_d(x).get("idr")), _text(_d(x).get("reason"))]
            for x in _l(z.get("trims"))])),
        _card("excluded", "Excluded", _rows(("Symbol", "Reason"), [
            [_text(_d(x).get("symbol")), _text(_d(x).get("reason"))]
            for x in _l(z.get("excluded"))])),
    ])


def market(m: Market) -> str:
    parts = [f'<section class="market" id="{esc(m.key)}">',
             f'<h2><a href="/candidates/{quote(m.key)}">{esc(m.key)}</a></h2>']
    if m.problem:
        parts.append(web.notice(f"{m.file}: {m.problem}"))
    if m.payload is not None:
        p = m.payload
        parts += [_summary(p),
                  _card("hurdle", "Hurdle", _list(_l(_d(p.get("hurdle")).get("drivers")))),
                  _tilt(_d(p.get("tilt"))),
                  *(_style(_d(s)) for s in _l(p.get("styles"))),
                  _sizing(_d(p.get("sizing"))),
                  _average_down(p),
                  _card("stale", "Stale inputs", _list(_l(p.get("stale_inputs")))),
                  _card("sources", "Sources", _list(_l(p.get("sources"))))]
    parts.append("</section><!-- /market -->")
    return "".join(parts)


# ---------------- pages ----------------


def _problems(markets: Sequence[Market]) -> list[dict]:
    return [{"file": m.file, "error": m.problem} for m in markets if m.problem]


def index(app: web.App, _m: re.Match[str]) -> web.View:
    markets = load(app.out_dir)
    if not markets:
        return web.View(TITLE, "<h1>Candidates</h1>" + web.notice(EMPTY),
                        {"markets": [], "problems": []})
    data = {"markets": [m.payload for m in markets if m.payload is not None],
            "problems": _problems(markets)}
    # an unreadable file is a notice at the top; a schema mismatch is a notice in its section
    body = ("<h1>Candidates</h1>"
            + "".join(web.notice(f"{m.file}: {m.problem}") for m in markets if m.payload is None)
            + '<p class="muted">Ranked within each style by margin over the hurdle; all in IDR.</p>'
            + "".join(market(m) for m in markets if m.payload is not None))
    return web.View(TITLE, body, data)


def page(app: web.App, m: re.Match[str]) -> web.View | None:
    found = next((x for x in load(app.out_dir) if x.key == m.group(1)), None)
    if found is None:
        return None
    data = found.payload if found.payload is not None else {"file": found.file,
                                                            "error": found.problem}
    return web.View(f"{TITLE} {found.key}", f"<h1>Candidates {esc(found.key)}</h1>"
                    + market(found), data)
