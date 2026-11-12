"""The baseline board page (/frameworks, PLAN S94) and its .json twin.

Reads `app.out_dir/frameworks/IDN.json` as written by `assist frameworks` (never by `assist
run`). One row per screen or framework, ranked on the 3-month excess total return over the pool
(the window the pass test uses); each window's cell shows that excess, its rank in the window
and the independent windows behind it. A second table gives the excess over the JCI. Plumbing:
outside `journal.RULE_GLOBS`, so the model fingerprint does not change.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from assist import web
from assist.web import esc

FILE = "frameworks/IDN.json"
TITLE = "Assist frameworks"
RANK_WINDOW = "3m"
EMPTY = ("No board yet: out/frameworks/IDN.json is missing. Run `assist frameworks` (it reads "
         "idx-method read-only and takes a few minutes; `assist run` does not build it).")
GATE_TONE = {"passed": "good", "failed": "bad", "untested": "muted"}
STYLE = """<style>
.board td.num { white-space:nowrap; }
.board td.num small { display:block; color:var(--muted); font-size:11px; }
.board th.judge { color:var(--fg); }
.board ul { margin:6px 0 0; padding-left:18px; }
</style>"""


def load(out_dir: Path, cache: dict | None = None) -> tuple[dict | None, str | None]:
    """(payload, problem); the parsed file is cached per mtime in the app's view cache."""
    path = Path(out_dir) / FILE
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None, EMPTY
    key = ("frameworks", str(path))
    if cache is not None and (hit := cache.get(key)) and hit[0] == stamp:
        return hit[1], None
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{FILE} is not valid JSON ({e})"
    if not isinstance(p, dict) or not isinstance(p.get("frameworks"), list):
        return None, f"{FILE} has no frameworks list"
    if cache is not None:
        cache[key] = (stamp, p)
    return p, None


def _d(x: Any) -> Mapping:
    return x if isinstance(x, Mapping) else {}


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def rows(p: Mapping) -> list[dict]:
    """One row per entry, best 3m excess vs the pool first; no figure sorts last, by name."""
    out = []
    for e in p.get("frameworks") or []:
        e = _d(e)
        cells = {}
        for w in e.get("windows") or []:
            w = _d(w)
            cells[str(w.get("window"))] = {
                "excess_pool": _num(w.get("excess_pool")), "excess_jci": _num(w.get("excess_jci")),
                "total": _num(w.get("total")), "n_independent": w.get("n_independent") or 0,
                "n_starts": w.get("n_starts") or 0, "rank": w.get("rank_pool"),
                "verdict_window": bool(w.get("verdict_window"))}
        surv = _d(e.get("survivorship"))
        out.append({"name": str(e.get("name", "")), "kind": e.get("kind"),
                    "status": e.get("status"), "gate": _d(e.get("gate")).get("state"),
                    "gate_reason": _d(e.get("gate")).get("reason"), "basis": e.get("basis"),
                    "description": e.get("description"), "starts": e.get("starts"),
                    "first_start": e.get("first_start"), "last_start": e.get("last_start"),
                    "survivorship": surv.get("note"), "notes": list(e.get("notes") or []),
                    "cells": cells})

    def key(r: dict) -> tuple:
        x = r["cells"].get(RANK_WINDOW, {}).get("excess_pool")
        return (x is None, -(x or 0.0), r["name"])
    return sorted(out, key=key)


def _pt(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:+.1f}pt"


def _cell(c: Mapping | None, field: str) -> str:
    c = c or {}
    x = c.get(field)
    if x is None:
        return '<td class="num muted">–</td>'
    rank = f"#{c['rank']} · " if field == "excess_pool" and c.get("rank") else ""
    return (f'<td class="num">{esc(_pt(x))}<small>{rank}{int(c["n_independent"])} indep. of '
            f'{int(c["n_starts"])}</small></td>')


def _gate(r: Mapping) -> str:
    state = str(r.get("gate") or "untested")
    return web.chip(f"placebo {state}", GATE_TONE.get(state, "muted"))


def _table(rs: list[dict], windows: list[Mapping], field: str) -> str:
    head = "".join(
        f'<th class="{"judge" if w.get("verdict_window") else ""}">{esc(str(w.get("window")))}'
        f'<br><span class="muted">{"can judge" if w.get("verdict_window") else "descriptive"}'
        "</span></th>" for w in windows)
    body = "".join(
        f"<tr><td><b>{esc(r['name'])}</b><br>{_gate(r)}</td>"
        + "".join(_cell(r["cells"].get(str(w.get("window"))), field) for w in windows)
        + "</tr>" for r in rs)
    return f"<table><tr><th>Screen or framework</th>{head}</tr>{body}</table>"


def _details(r: Mapping) -> str:
    bits = [f"<b>{esc(r['name'])}</b> {_gate(r)}"]
    if r.get("description"):
        bits.append(esc(str(r["description"])))
    meta = [f"held: {r['basis']}" if r.get("basis") else None,
            f"{r['starts']} quarter start(s), {r['first_start']} to {r['last_start']}"
            if r.get("starts") else "no start",
            f"placebo: {r['gate_reason']}" if r.get("gate_reason") else None,
            f"survivorship: {r['survivorship']}" if r.get("survivorship") else None,
            *r.get("notes", [])]
    items = "".join(f"<li>{esc(str(m))}</li>" for m in meta if m)
    return f"<li>{' — '.join(bits)}<ul>{items}</ul></li>"


def page(app: web.App, _m: re.Match[str]) -> web.View:
    p, problem = load(app.out_dir, app.cache)
    if p is None:
        body = f"<h1>Frameworks</h1>{web.notice(problem or EMPTY)}"
        return web.View(TITLE, body, {"rows": [], "problem": problem})
    rs = rows(p)
    windows = [_d(w) for w in p.get("windows") or []]
    stale = "".join(f"<li>{esc(str(s))}</li>" for s in p.get("stale_inputs") or [])
    skipped = "".join(f"<li>{esc(str(_d(s).get('name')))}: {esc(str(_d(s).get('reason')))}</li>"
                      for s in p.get("skipped") or [])
    body = (
        f'{STYLE}<div class="board"><h1>Frameworks</h1>'
        f'<p class="muted">How each screen\'s picks would have done, as of '
        f'{esc(str(p.get("as_of")))} (built {esc(str(p.get("built")))}). At every quarter end '
        "the screen's top fifth is bought equal-weighted and held for each window; it is "
        "compared with every name the screen could have picked that day (the pool) and with the "
        "JCI. A plus means the picks did better. Under each figure: its rank in that window and "
        "how many non-overlapping periods stand behind it, of all starts.</p>"
        f"{web.notice(str(p.get('verdict_note', '')))}"
        f'<section class="card"><header><h2>Beat the pool by</h2><span class="muted">ranked on '
        f"{RANK_WINDOW}</span></header>{_table(rs, windows, 'excess_pool')}</section>"
        '<section class="card"><header><h2>Beat the JCI by</h2></header>'
        f"{_table(rs, windows, 'excess_jci')}</section>"
        f'<section class="card"><header><h2>What each one holds</h2></header><ul>'
        f'{"".join(_details(r) for r in rs)}</ul>'
        f'<p class="muted">{esc(str(p.get("method", "")))}</p></section>'
        + (f'<section class="card"><header><h2>Skipped</h2></header><ul>{skipped}</ul></section>'
           if skipped else "")
        + (f'<section class="card"><header><h2>Stale inputs</h2></header><ul>{stale}</ul>'
           "</section>" if stale else "")
        + "</div>")
    return web.View(TITLE, body, {
        "as_of": p.get("as_of"), "built": p.get("built"), "verdict_note": p.get("verdict_note"),
        "windows": windows, "rank_window": RANK_WINDOW, "rows": rs,
        "ranking": p.get("ranking"), "skipped": p.get("skipped") or [],
        "stale_inputs": p.get("stale_inputs") or [], "problem": None})
