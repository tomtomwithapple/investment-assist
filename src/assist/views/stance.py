"""The stance detail page (/stance/<SUBJECT>/<asset>): one stance's fields and the change since
the previous snapshot.

The (subject, asset) pair from the URL is matched exactly (case sensitive) against the stances
`brief.load_out(app.out_dir)` loaded; it is never turned into a path, so an unknown pair or a
decoded `..` is a 404. The previous stance comes from `brief.previous_snapshot(app.snapshots_dir,
before=as_of)`, loaded the same way and matched on the same pair. The .json twin is the stance
dict as written. The Drivers card links to `/signals/<SUBJECT>` when out/layers/ holds that
subject's file, the Portfolio card to `/portfolio`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from urllib.parse import quote

from assist import brief, web
from assist.stance import split_text
from assist.views import signals
from assist.views.overview import TONE
from assist.web import esc

SEVERITY = {"critical": "bad", "warn": "warn", "info": "muted"}
NO_SNAPSHOT = "no earlier snapshot"


def find(stances: Iterable[Mapping], subject: str, asset: str) -> dict | None:
    return next((dict(s) for s in stances if s["subject"] == subject and s["asset"] == asset),
                None)


def change(app: web.App, s: Mapping) -> dict | None:
    """{as_of, stance, score} of the same pair in the newest earlier snapshot; stance and score
    are None when the pair is not in it. None when there is no earlier snapshot."""
    prev = brief.previous_snapshot(app.snapshots_dir, before=s["as_of"])
    if prev is None:
        return None
    p = find(brief.load_out(prev).stances, s["subject"], s["asset"]) or {}
    return {"as_of": prev.name, "stance": p.get("stance"), "score": p.get("score")}


# ---------------- html ----------------


def _chip(stance: str) -> str:
    return web.chip(stance, TONE.get(stance, "muted"))


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{brief._num(x)}%"


def _card(cls: str, title: str, inner: str, link: tuple[str, str] | None = None) -> str:
    """link: (href, text) shown in the card's header, both escaped."""
    more = "" if link is None else f'<a class="more" href="{esc(link[0])}">{esc(link[1])}</a>'
    return (f'<section class="card {cls}"><header><h2>{esc(title)}</h2>{more}</header>'
            f"{inner}</section>")


def signals_href(app: web.App, subject: str) -> str | None:
    """`/signals/<SUBJECT>` when out/layers/ holds that subject's file, else None (no dead link:
    commodities and a run without layer files have none)."""
    return f"/signals/{quote(subject)}" if subject in signals.subjects(app.out_dir) else None


def _table(rows: Sequence[tuple[str, str]]) -> str:
    """rows of (label, html already escaped)."""
    return "<table>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</table>"


def _list(items: Sequence[str]) -> str:
    if not items:
        return '<p class="muted">none</p>'
    return "<ul>" + "".join(f"<li>{esc(str(x))}</li>" for x in items) + "</ul>"


def _summary(s: Mapping) -> str:
    layer1 = s.get("layer1_score")
    rows = [("Score", esc(brief._num(s["score"]))),
            ("Layer-1 score", "-" if layer1 is None else esc(brief._num(layer1))),
            ("Confidence", f"{float(s['confidence']):.2f}"),
            ("Regime", esc(s["regime"])),
            ("Dollar", esc(s.get("dollar") or "-")),
            ("Model", f"<code>{esc(brief._fingerprint(s['model_fingerprint']))}</code>"
                      + (f' <span class="muted">v{esc(s["model_version"])}</span>'
                         if s.get("model_version") else ""))]
    return (f'<section class="card summary"><header>{_chip(s["stance"])}'
            f'<span class="muted">As of {esc(s["as_of"])}</span></header>'
            f"{_table(rows)}</section>")


def _change(s: Mapping, c: Mapping | None) -> str:
    if c is None:
        inner = f'<p class="muted">{NO_SNAPSHOT}</p>'
    elif c["stance"] is None:
        inner = f'<p class="muted">not in the {esc(c["as_of"])} snapshot</p>'
    else:
        delta = float(s["score"]) - float(c["score"])
        inner = (f"<p>{esc(c['as_of'])}: {_chip(c['stance'])} {esc(brief._num(c['score']))}"
                 f" → now {_chip(s['stance'])} {esc(brief._num(s['score']))}"
                 f' <span class="muted">({esc(f"{delta:+.1f}")})</span></p>')
    return _card("change", "Change since last snapshot", inner)


def _entry(e: Mapping) -> str:
    return _table([("Style", esc(e["style"])), ("Tranches", esc(str(e["tranches"]))),
                   ("Spacing", f"{esc(str(e['spacing_days']))} days")])


def _portfolio(p: Mapping) -> str:
    rows = [("Current", esc(_pct(p["current_pct"]))),
            ("Target", esc(_pct(p["target_pct"]))), ("Delta", esc(p["delta"]))]
    if "benchmark_pct" in p:  # S39; absent in payloads before model 0.4.0
        b = p["benchmark_pct"]
        rows.insert(1, ("Benchmark", esc(_pct(b)) if b else "0% (outside the 80/20 mandate)"))
    split = split_text(p)  # S42; absent in payloads before schema 1.1.0
    if split:
        rows.append(("Rebalance vs tilt", esc(split)))
    if p.get("notes"):
        rows.append(("Notes", "<br>".join(esc(n) for n in p["notes"])))
    return _table(rows)


def _flags(flags: Sequence[Mapping]) -> str:
    if not flags:
        return '<p class="muted">none</p>'
    return "<table>" + "".join(
        f"<tr><td>{web.chip(f['severity'], SEVERITY.get(f['severity'], 'muted'))}</td>"
        f"<td><code>{esc(f['code'])}</code></td><td>{esc(f['message'])}</td></tr>"
        for f in flags) + "</table>"


def body(s: Mapping, c: Mapping | None, signals_link: str | None = None) -> str:
    return "".join([
        f'<h1>{esc(s["subject"])} {esc(s["asset"])}</h1>',
        _summary(s),
        _change(s, c),
        _card("drivers", "Drivers", _list(s["drivers"]),
              (signals_link, "Layer 2-3 signals →") if signals_link else None),
        _card("risks", "Risks", _list(s["risks"])),
        _card("watch", "Watch", _list(s["watch"])),
        _card("entry", "Entry", _entry(s["entry"])),
        _card("portfolio", "Portfolio", _portfolio(s["portfolio"]),
              ("/portfolio", "Whole portfolio →")),
        _card("flags", "Flags", _flags(s.get("flags") or [])),
        _card("stale", "Stale inputs", _list(s["stale_inputs"])),
        _card("sources", "Sources", _list(s["sources"])),
        _own_disclaimer(s),
    ])


def _own_disclaimer(s: Mapping) -> str:
    """The footer carries web.DISCLAIMER; the stance's own text only when it says more."""
    text = (s.get("disclaimer") or "").strip()
    return "" if not text or text == web.DISCLAIMER else f'<p class="muted">{esc(text)}</p>'


def page(app: web.App, m: re.Match[str]) -> web.View | None:
    s = find(brief.load_out(app.out_dir).stances, m.group(1), m.group(2))
    if s is None:
        return None
    html = body(s, change(app, s), signals_href(app, s["subject"]))
    return web.View(f"Assist {s['subject']} {s['asset']}", html, s)
