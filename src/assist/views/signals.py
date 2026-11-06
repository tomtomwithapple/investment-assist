"""The signals pages (/signals, /signals/<SUBJECT>, PLAN S35): one subject's layer-2 overrides and
layer-3 signals, and for IDN the chart windows.

Reads `app.out_dir/layers/<SUBJECT>.json` as written by `assist run` (S33,
`schema/layers/subject.schema.json`); the page never opens a store. The subject from the URL is
matched exactly (case sensitive) against the file names found in `out/layers/` (upper-case stems
only, so `regime.json` and `portfolio.json` are never subjects); it is never turned into a path,
so an unknown subject or a decoded `..` is a 404. A file that is not valid JSON, not a subject file
or a stub with `error` is a notice on the page, never a 500. Every value read from a file goes
through `esc`.

The page: a summary (as of, model, stale inputs, sources), the layer-2 table (component, newest
value and date, change over its window, direction, weights, source, detail), the per-asset shift
with the uncapped raw sum and the cap, the foreign IDR terms and gaps, and the layer-3 table with
its tally. IDN also gets inline SVG charts: net foreign flow in IDR and in USD (60 IDX days; a day
without JISDOR has no USD bar, it is marked, never filled), JISDOR (60 days; BI's carried-forward
days and IDX days without a fixing marked), the IGSYC curve today against ~4 weeks earlier, the
non-resident SBN holdings and the JCI (1 year). Foreign subjects have tables only. The `.json`
twin is the file as written.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from assist import web
from assist.web import esc

TITLE = "Assist Signals"
DIR = "layers"
SUBJECT_RX = re.compile(r"^[A-Z0-9_]+$")
DASH = "-"
EMPTY = "no subject files in out/layers/ yet: run `assist run`"
ASSETS = ("stocks", "bonds", "currency")

# chart geometry (SVG user units; the SVG scales to the card's width)
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 720, 190, 64, 14, 10, 24

STYLE = """<style>
.signals { --s1:#2a78d6; --s2:#eb6834; --pos:#2a78d6; --neg:#e34948; --mid:#c9c8c3;
  --grid:#e3e3df; --cf:#c77700; }
@media (prefers-color-scheme: dark) { .signals { --s1:#3987e5; --s2:#d95926; --pos:#3987e5;
  --neg:#e66767; --mid:#55554f; --grid:#33332f; --cf:#f0c46a; } }
.signals svg.chart { width:100%; min-width:560px; height:auto; display:block; margin-top:6px; }
.signals svg text { fill:var(--muted); font-size:11px; }
.signals svg .grid { stroke:var(--grid); stroke-width:1; }
.signals svg .zero { stroke:var(--mid); stroke-width:1.5; }
.signals svg .line { fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
.signals svg .line.s1 { stroke:var(--s1); } .signals svg .line.s2 { stroke:var(--s2); }
.signals svg .line.dash { stroke-dasharray:5 4; }
.signals svg .dot { stroke:var(--card); stroke-width:1.5; }
.signals svg .dot.s1 { fill:var(--s1); } .signals svg .dot.s2 { fill:var(--s2); }
.signals svg .dot.hollow { fill:var(--card); stroke-width:2; }
.signals svg .dot.hollow.s1 { stroke:var(--s1); } .signals svg .dot.hollow.s2 { stroke:var(--s2); }
.signals svg .dot.cf { fill:var(--card); stroke:var(--cf); stroke-width:2.5; }
.signals svg .pos { fill:var(--pos); } .signals svg .neg { fill:var(--neg); }
.signals svg .gap { stroke:var(--muted); stroke-width:1.5; stroke-dasharray:2 2; }
.signals svg .hit { fill:transparent; }
.signals svg g.pt:hover .hit { fill:var(--line); fill-opacity:.6; }
.signals .legend { display:flex; gap:16px; flex-wrap:wrap; color:var(--muted); font-size:12px;
  margin:6px 0 0; align-items:center; }
.signals .key { display:inline-block; vertical-align:middle; margin-right:5px; }
.signals .key.line { width:14px; height:3px; border-radius:2px; }
.signals .key.bar { width:12px; height:8px; border-radius:2px; }
.signals .key.s1 { background:var(--s1); } .signals .key.s2 { background:var(--s2); }
.signals .key.pos { background:var(--pos); } .signals .key.neg { background:var(--neg); }
.signals .key.ring { width:8px; height:8px; border-radius:50%; border:2px solid var(--cf); }
.signals .key.hollow { width:7px; height:7px; border-radius:50%; border:2px solid var(--s1); }
.signals .key.gap { width:2px; height:10px; border-left:2px dotted var(--muted); }
.signals td.num, .signals th.num { text-align:right; white-space:nowrap; }
.signals td.date { white-space:nowrap; }
.signals td.reason { font-size:12px; color:var(--muted); }
.signals h3 { font-size:13px; margin:16px 0 0; }
.signals .grid2 { display:grid; grid-template-columns:repeat(auto-fit, minmax(380px, 1fr));
  gap:0 18px; }
</style>"""


# ---------------- loading ----------------


def subjects(out_dir: Path) -> dict[str, Path]:
    """SUBJECT → its file, for every upper-case `out/layers/<SUBJECT>.json` present."""
    try:
        entries = sorted(Path(out_dir, DIR).iterdir())
    except OSError:
        return {}
    return {p.stem: p for p in entries
            if p.suffix == ".json" and SUBJECT_RX.match(p.stem) and p.is_file()}


def load(path: Path, cache: dict | None = None) -> tuple[dict | None, str | None]:
    """(payload, problem). The payload is None only when the file cannot be read as an object; a
    stub with `error` or a wrong `kind` comes back with its problem. Cached per mtime."""
    name = f"{DIR}/{path.name}"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None, f"{name} is missing"
    key = ("signals", str(path))
    if cache is not None and (hit := cache.get(key)) and hit[0] == stamp:
        return hit[1]
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        res: tuple[dict | None, str | None] = (None, f"{name} is not valid JSON ({e})")
    else:
        if not isinstance(p, dict):
            res = (None, f"{name} is not a JSON object")
        elif p.get("kind") != "subject":
            res = (p, f"{name} is not a subject file (kind {p.get('kind')!r})")
        elif p.get("error"):
            res = (p, f"the run could not build {name}: {p['error']}")
        elif not isinstance(p.get("layer2"), Mapping):
            res = (p, f"{name} has no layer2 object")
        else:
            res = (p, None)
    if cache is not None:
        cache[key] = (stamp, res)
    return res


# ---------------- formatting ----------------


def _d(x: Any) -> Mapping:
    return x if isinstance(x, Mapping) else {}


def _l(x: Any) -> list:
    return list(x) if isinstance(x, list) else []


def _f(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def num(x: Any, signed: bool = False) -> str:
    """A compact number: T/B/M above a million, else 4 significant digits; n/a when absent."""
    v = _f(x)
    if v is None:
        return "n/a"
    sign = "+" if signed and v > 0 else ""
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"{sign}{v / div:,.2f}{suf}"
    if abs(v) >= 1000:
        return f"{sign}{v:,.0f}"
    return f"{sign}{v:.4g}"


def _s(x: Any) -> str:
    return esc(DASH if x is None or x == "" else str(x))


DIR_TEXT = {1: "up", -1: "down", 0: "flat"}


def direction(x: Any, tone: bool = False) -> str:
    """A component's direction as a muted chip; a signal's vote (tone=True) as good/bad."""
    d = x if isinstance(x, int) and not isinstance(x, bool) else None
    if d not in DIR_TEXT:
        return web.chip("n/a", "muted")
    if tone:
        return web.chip(f"{d:+d}", {1: "good", -1: "bad"}.get(d, "muted"))
    return web.chip(DIR_TEXT[d], "muted")


def _table(head: Sequence[tuple[str, bool]], rows: Sequence[str], empty: str) -> str:
    if not rows:
        return f'<p class="muted">{esc(empty)}</p>'
    th = "".join(f'<th{" class=\"num\"" if n else ""}>{esc(h)}</th>' for h, n in head)
    return f"<table><tr>{th}</tr>{''.join(rows)}</table>"


def _card(cls: str, title: str, inner: str) -> str:
    return f'<section class="card {cls}"><h2>{esc(title)}</h2>{inner}</section>'


def _list(items: Sequence[Any]) -> str:
    if not items:
        return '<span class="muted">none</span>'
    return ", ".join(esc(str(x)) for x in items)


# ---------------- tables ----------------


def _weights(w: Any) -> str:
    w = _d(w)
    return esc(" ".join(f"{a} {w[a]:+d}" for a in ASSETS
                        if isinstance(w.get(a), int) and not isinstance(w.get(a), bool))
               or DASH)


def components_table(comps: Sequence[Any]) -> str:
    rows = []
    for c in map(_d, comps):
        last = _d(c.get("last"))
        series = f'<br><code>{_s(c.get("series_id"))}</code>' if c.get("series_id") else ""
        rows.append(
            f"<tr><td><b>{_s(c.get('name'))}</b></td>"
            f'<td class="num">{esc(num(last.get("value")))}</td>'
            f'<td class="date">{_s(last.get("date"))}</td>'
            f'<td class="num">{esc(num(c.get("value"), signed=True))}</td>'
            f"<td>{direction(c.get('direction'))}</td><td>{_weights(c.get('weights'))}</td>"
            f"<td>{_s(c.get('source'))}{series}</td><td>{_s(c.get('detail'))}</td></tr>")
    head = (("Component", False), ("Newest value", True), ("Date", False),
            ("Change over window", True), ("Direction", False), ("Weights", False),
            ("Source", False), ("Detail", False))
    return _table(head, rows, "no components")


def assets_table(assets: Sequence[Any]) -> str:
    rows = []
    for a in map(_d, assets):
        capped = a.get("capped") is True
        rows.append(
            f"<tr><td><b>{_s(a.get('asset'))}</b></td>"
            f'<td class="num">{esc(num(a.get("shift"), signed=True))}</td>'
            f'<td class="num">{esc(num(a.get("raw"), signed=True))}</td>'
            f'<td class="num">±{esc(num(a.get("cap")))}</td>'
            f"<td>{web.chip('capped', 'warn') if capped else web.chip('no', 'muted')}</td>"
            f'<td class="reason">{_s(a.get("reason"))}</td></tr>')
    head = (("Asset", False), ("Shift", True), ("Raw (uncapped)", True), ("Cap", True),
            ("Capped", False), ("Reason", False))
    return _table(head, rows, "no per-asset shift")


def pct(x: Any) -> str:
    """A fraction as a signed percentage."""
    v = _f(x)
    return DASH if v is None else f"{v * 100:+.1f}%"


def idr_terms(t: Any) -> str:
    t = _d(t)
    if not t:
        return ""
    lvl = _f(t.get("level"))
    rows = [("Currency", _s(t.get("currency"))),
            ("IDR per unit", f"{esc(DASH if lvl is None else f'{lvl:,.2f}')} on {_s(t.get('on'))}"),
            ("Change 3m / 12m", f"{esc(pct(t.get('change_3m')))} / "
                                f"{esc(pct(t.get('change_12m')))}"),
            ("Hedge carry", esc(pct(t.get("carry")) + " a year")),
            ("Detail", _s(t.get("detail")))]
    return ("<h3>IDR terms</h3><table>"
            + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</table>")


def gaps(g: Sequence[Any]) -> str:
    if not g:
        return ""
    items = "".join(f"<li><b>{_s(_d(x).get('input'))}</b>: {_s(_d(x).get('why'))}</li>"
                    for x in g)
    return f"<h3>Gaps</h3><ul>{items}</ul>"


def signals_table(sig: Sequence[Any]) -> str:
    rows = [f"<tr><td><b>{_s(s.get('name'))}</b></td><td>{_s(s.get('asset'))}</td>"
            f'<td class="num">{esc(num(s.get("value"), signed=True))}</td>'
            f"<td>{direction(s.get('direction'), tone=True)}</td><td>{_s(s.get('source'))}</td>"
            f"<td>{_s(s.get('detail'))}</td></tr>" for s in map(_d, sig)]
    head = (("Signal", False), ("Asset", False), ("Value", True), ("Vote", False),
            ("Source", False), ("Detail", False))
    return _table(head, rows, "no signals")


def tally(t: Any) -> str:
    t = _d(t)
    if not t:
        return ""
    parts = " · ".join(f"{esc(str(k))} {esc(num(v, signed=True))}" for k, v in sorted(t.items()))
    return f'<p class="muted">Tally: {parts}</p>'


# ---------------- charts ----------------


def ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    """Round tick values covering [lo, hi]."""
    if hi <= lo:
        lo, hi = lo - 1, hi + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    out, v = [], start
    while v <= hi + step * 1e-9:
        out.append(round(v, 10))
        v += step
    if out[-1] < hi:
        out.append(round(out[-1] + step, 10))
    return out


class Frame:
    """Maps data to SVG coordinates for one chart."""

    def __init__(self, xlo: float, xhi: float, ys: Sequence[float], zero: bool = False):
        lo, hi = (min(ys), max(ys)) if ys else (0.0, 1.0)
        if zero:
            lo, hi = min(lo, 0.0), max(hi, 0.0)
        self.yt = ticks(lo, hi)
        self.ylo, self.yhi = self.yt[0], self.yt[-1]
        self.xlo, self.xhi = xlo, xhi if xhi > xlo else xlo + 1

    def x(self, v: float) -> float:
        return PAD_L + (v - self.xlo) / (self.xhi - self.xlo) * (W - PAD_L - PAD_R)

    def y(self, v: float) -> float:
        return PAD_T + (self.yhi - v) / (self.yhi - self.ylo) * (H - PAD_T - PAD_B)

    def grid(self, fmt: Callable[[float], str], xlabels: Sequence[tuple[float, str]]) -> str:
        parts = []
        for t in self.yt:
            y = self.y(t)
            parts.append(f'<line class="{"zero" if t == 0 else "grid"}" x1="{PAD_L}" '
                         f'x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}"/>'
                         f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end">'
                         f"{esc(fmt(t))}</text>")
        for k, (xv, lab) in enumerate(xlabels):
            anchor = "start" if k == 0 else "end" if k == len(xlabels) - 1 else "middle"
            parts.append(f'<text x="{self.x(xv):.1f}" y="{H - 6}" text-anchor="{anchor}">'
                         f"{esc(lab)}</text>")
        return "".join(parts)


def _svg(label: str, inner: str) -> str:
    return (f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(label)}">'
            f"{inner}</svg>")


def _date_labels(dates: Sequence[str]) -> list[tuple[float, str]]:
    n = len(dates)
    if n == 0:
        return []
    idx = sorted({0, n // 2, n - 1})
    return [(float(i), dates[i]) for i in idx]


def _path(points: Sequence[tuple[float, float | None]], fr: Frame) -> str:
    """One `d` per run of non-null points: a null breaks the line, it is never bridged."""
    runs, cur = [], []
    for xv, yv in points:
        if yv is None:
            if cur:
                runs.append(cur)
            cur = []
        else:
            cur.append(f"{fr.x(xv):.1f},{fr.y(yv):.1f}")
    if cur:
        runs.append(cur)
    return " ".join("M" + " L".join(r) for r in runs if r)


def _pt(cx: float, cy: float, title: str, dot: str = "", r: float = 3.5) -> str:
    vis = f'<circle class="dot {dot}" cx="{cx:.1f}" cy="{cy:.1f}" r="{r}"/>' if dot else ""
    return (f'<g class="pt"><circle class="hit" cx="{cx:.1f}" cy="{cy:.1f}" r="7"/>{vis}'
            f"<title>{esc(title)}</title></g>")


def line_chart(label: str, dates: Sequence[str], values: Sequence[float | None],
               fmt: Callable[[float], str], dots: bool = False) -> str:
    """One series over its points (x = point index); a null value is a break in the line."""
    pts = [(float(i), v) for i, v in enumerate(values)]
    fr = Frame(0, max(len(values) - 1, 1), [v for v in values if v is not None])
    d = _path(pts, fr)
    marks = "".join(_pt(fr.x(i), fr.y(v), f"{dates[int(i)]}: {fmt(v)}", "s1" if dots else "", 3)
                    for i, v in pts if v is not None)
    return _svg(label, fr.grid(fmt, _date_labels(dates))
                + (f'<path class="line s1" d="{d}"/>' if d else "") + marks)


def bar_chart(label: str, dates: Sequence[str], values: Sequence[float | None],
              fmt: Callable[[float], str], missing: str) -> str:
    """Bars from zero, blue up and red down; a null is a dotted tick at zero, never a bar."""
    n = len(values)
    fr = Frame(-0.5, n - 0.5, [v for v in values if v is not None], zero=True)
    slot = (W - PAD_L - PAD_R) / max(n, 1)
    bw = max(slot - 2, 1)  # 2px surface gap between bars
    z = fr.y(0)
    parts = [fr.grid(fmt, [(float(i), lab) for i, lab in _date_labels(dates)])]
    for i, v in enumerate(values):
        cx = fr.x(i)
        if v is None:
            parts.append(f'<g class="pt"><rect class="hit" x="{cx - slot / 2:.1f}" y="{PAD_T}" '
                         f'width="{slot:.1f}" height="{H - PAD_T - PAD_B}"/>'
                         f'<line class="gap" x1="{cx:.1f}" x2="{cx:.1f}" y1="{z - 6:.1f}" '
                         f'y2="{z + 6:.1f}"/><title>{esc(dates[i])}: {esc(missing)}</title></g>')
            continue
        y = fr.y(v)
        top, h = min(y, z), max(abs(z - y), 1)
        parts.append(f'<g class="pt"><rect class="hit" x="{cx - slot / 2:.1f}" y="{PAD_T}" '
                     f'width="{slot:.1f}" height="{H - PAD_T - PAD_B}"/>'
                     f'<rect class="{"pos" if v >= 0 else "neg"}" x="{cx - bw / 2:.1f}" '
                     f'y="{top:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="1"/>'
                     f"<title>{esc(dates[i])}: {esc(fmt(v))}</title></g>")
    return _svg(label, "".join(parts))


def _legend(*items: tuple[str, str]) -> str:
    return ('<p class="legend">' + "".join(f'<span><span class="key {k}"></span>{esc(t)}</span>'
                                           for k, t in items) + "</p>")


def _idr_t(v: float) -> str:
    return f"{v / 1e12:,.1f}T" if abs(v) >= 1e11 or v == 0 else f"{v / 1e9:,.0f}B"


def _whole(v: float) -> str:
    return f"{v:,.0f}"


def _yield(v: float) -> str:
    return f"{v:.2f}%"


def _usd_m(v: float) -> str:
    return f"${v / 1e6:,.0f}M"


def _chart_card(cls: str, title: str, sub: str, inner: str) -> str:
    return (f'<section class="card chart {cls}"><h2>{esc(title)}</h2>'
            f'<p class="muted">{sub}</p>{inner}</section>')


def _points(x: Any) -> list[Mapping]:
    return [p for p in map(_d, _l(x)) if isinstance(p.get("date"), str)]


def net_foreign_chart(c: Any) -> str:
    c = _d(c)
    pts = _points(c.get("points"))
    if not pts:
        return _chart_card("net-foreign", "Net foreign flow", "", web.notice("no flow points"))
    dates = [str(p["date"]) for p in pts]
    idr = [_f(p.get("idr")) for p in pts]
    usd = [_f(p.get("usd")) for p in pts]
    no_usd = sum(v is None for v in usd)
    sub = (f"{len(pts)} IDX days, {esc(dates[0])} to {esc(dates[-1])}. Net foreign buying in "
           f"the IDX market, daily.")
    usd_note = (f"USD at that day's JISDOR; {no_usd} of {len(pts)} days have no JISDOR rate and "
                f"no USD bar (a gap, never filled)." if no_usd else "USD at that day's JISDOR.")
    inner = (f"<h3>IDR</h3>{bar_chart('Net foreign flow, IDR', dates, idr, _idr_t, 'no value')}"
             f"<h3>USD</h3><p class=\"muted\">{esc(usd_note)}</p>"
             f"{bar_chart('Net foreign flow, USD', dates, usd, _usd_m, 'no JISDOR: no USD')}"
             + _legend(("bar pos", "net buy"), ("bar neg", "net sell"),
                       ("gap", "no JISDOR rate")))
    return _chart_card("net-foreign", "Net foreign flow", sub, inner)


def jisdor_chart(c: Any) -> str:
    c = _d(c)
    pts = _points(c.get("points"))
    gap_days = [str(g) for g in _l(c.get("gaps")) if isinstance(g, str)]
    if not pts:
        return _chart_card("jisdor", "JISDOR", "", web.notice("no JISDOR points"))
    rows = {str(p["date"]): p for p in pts}
    dates = sorted(set(rows) | set(gap_days))
    vals = [_f(rows[d].get("value")) if d in rows else None for d in dates]
    fr = Frame(0, max(len(dates) - 1, 1), [v for v in vals if v is not None])
    fmt = _whole
    d = _path([(float(i), v) for i, v in enumerate(vals)], fr)
    parts = [fr.grid(fmt, _date_labels(dates)), f'<path class="line s1" d="{d}"/>' if d else ""]
    for i, day in enumerate(dates):
        v = vals[i]
        if v is None:
            parts.append(f'<g class="pt"><line class="gap" x1="{fr.x(i):.1f}" x2="{fr.x(i):.1f}" '
                         f'y1="{PAD_T}" y2="{H - PAD_B}"/><circle class="hit" cx="{fr.x(i):.1f}" '
                         f'cy="{H - PAD_B - 8}" r="7"/><title>{esc(day)}: IDX day without a '
                         f"JISDOR rate</title></g>")
            continue
        cf = rows[day].get("carried_forward") is True
        parts.append(_pt(fr.x(i), fr.y(v), f"{day}: {fmt(v)}"
                         + (" (BI carried forward D-1 data)" if cf else ""),
                         "cf" if cf else "s1", 4 if cf else 3))
    n_cf = sum(rows[d].get("carried_forward") is True for d in rows)
    sub = (f"{len(pts)} fixings, {esc(dates[0])} to {esc(dates[-1])}, {_s(c.get('unit'))}; "
           f"{n_cf} carried forward, {len(gap_days)} IDX days without a fixing in the window.")
    inner = _svg("JISDOR", "".join(parts)) + _legend(
        ("line s1", "JISDOR"), ("ring", "BI carried forward D-1 data"),
        ("gap", "IDX day without a fixing"))
    return _chart_card("jisdor", "JISDOR", sub, inner)


def _curve(x: Any) -> list[tuple[float, float, bool]]:
    out = []
    for p in map(_d, _l(x)):
        t, y = _f(p.get("tenor_y")), _f(p.get("yield_pct"))
        if t is not None and y is not None:
            out.append((t, y, p.get("from_yesterday_column") is True))
    return sorted(out)


TENOR_TICKS = (1, 2, 5, 10, 15, 20, 30)


def igsyc_chart(c: Any) -> str:
    c = _d(c)
    latest, earlier = _d(c.get("latest")), _d(c.get("earlier"))
    a, b = _curve(latest.get("points")), _curve(earlier.get("points"))
    if not a and not b:
        return _chart_card("igsyc", "IGSYC curve", "", web.notice("no curve points"))
    xs = [t for t, _, _ in a + b]
    fr = Frame(0, max(xs), [y for _, y, _ in a + b])
    fmt = _yield
    xl = [(0.0, "0y")] + [(float(t), f"{t}y") for t in TENOR_TICKS if t <= max(xs)]
    parts = [fr.grid(fmt, [])]
    for xv, lab in xl:
        parts.append(f'<text x="{fr.x(xv):.1f}" y="{H - 6}" text-anchor="middle">{esc(lab)}</text>')
    for pts, cls, extra, day in ((b, "s2", " dash", earlier.get("as_of")),
                                 (a, "s1", "", latest.get("as_of"))):
        d = _path([(t, y) for t, y, _ in pts], fr)
        if d:
            parts.append(f'<path class="line {cls}{extra}" d="{d}"/>')
        for t, y, yest in pts:
            parts.append(_pt(fr.x(t), fr.y(y), f"{day} {t:g}y: {y:.3f}%"
                             + (" (from the yesterday column)" if yest else ""),
                             f"{cls} hollow" if yest else cls, 3))
    e_day = earlier.get("as_of")
    e_text = (f"{_s(e_day)} (target {_s(earlier.get('target'))})" if e_day
              else f"none on or before {_s(earlier.get('target'))}")
    sub = (f"Yield by tenor, {_s(c.get('unit'))}: {_s(latest.get('as_of'))} "
           f"({len(a)} tenors) against {e_text} ({len(b)} tenors).")
    inner = _svg("IGSYC curve", "".join(parts)) + _legend(
        ("line s1", f"{latest.get('as_of') or 'latest'}"),
        ("line s2", f"{e_day or 'earlier'} (dashed)"),
        ("hollow", "taken from the yesterday column"))
    return _chart_card("igsyc", "IGSYC curve, today vs ~4 weeks earlier", sub, inner)


def series_chart(cls: str, title: str, c: Any, fmt: Callable[[float], str]) -> str:
    c = _d(c)
    pts = _points(c.get("points"))
    if not pts:
        return _chart_card(cls, title, "", web.notice("no points"))
    dates = [str(p["date"]) for p in pts]
    vals = [_f(p.get("value")) for p in pts]
    have = [v for v in vals if v is not None]
    last = next((v for v in reversed(vals) if v is not None), None)
    first = next((v for v in vals if v is not None), None)
    chg = (f", {(last / first - 1) * 100:+.1f}% over the window"
           if first not in (None, 0) and last is not None else "")
    src = c.get("source") or c.get("series_id")
    sub = (f"{len(pts)} days, {esc(dates[0])} to {esc(dates[-1])}, {_s(c.get('unit'))}"
           + (f" ({_s(src)})" if src else "")
           + (f"; latest {esc(fmt(last))}{esc(chg)}" if have else "") + ".")
    return _chart_card(cls, title, sub, line_chart(title, dates, vals, fmt))


def charts(c: Any) -> str:
    """The IDN chart cards; a chart the run could not build (null) is a notice."""
    c = _d(c)
    if not c:
        return ""
    parts = [
        ("net_foreign", "net foreign flow", net_foreign_chart),
        ("jisdor", "JISDOR", jisdor_chart),
        ("igsyc", "IGSYC curve", igsyc_chart),
        ("sbn_non_resident", "non-resident SBN",
         lambda x: series_chart("sbn", "Non-resident SBN holdings", x, _idr_t)),
        ("jci", "JCI", lambda x: series_chart("jci", "JCI", x, _whole)),
    ]
    out = ['<h2 style="margin-top:20px">Charts</h2>']
    for key, label, draw in parts:
        out.append(draw(c[key]) if c.get(key) is not None
                   else web.notice(f"{label}: no chart in this run (see stale inputs)"))
    return "".join(out)


# ---------------- page ----------------


def _summary(p: Mapping) -> str:
    fp = str(p.get("model_fingerprint") or "")
    members = _l(p.get("members"))
    rows = [("As of", _s(p.get("as_of"))),
            ("Model", f"<code>{esc(fp[:len('sha256:') + 12] or DASH)}</code>")]
    if members:
        rows.append(("Members", _list(members)))
    rows += [("Stale inputs", _list(_l(p.get("stale_inputs")))),
             ("Sources", _list(_l(p.get("sources"))))]
    return ('<section class="card summary"><table>'
            + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</table></section>")


def render(subject: str, p: Mapping | None, problem: str | None) -> str:
    head = f"<h1>Signals: {esc(subject)}</h1>"
    if p is None or problem:
        return (f'{STYLE}<div class="signals">{head}{web.notice(problem or "no data")}'
                + (_summary(p) if p else "") + "</div>")
    l2 = _d(p.get("layer2"))
    layer2 = (components_table(_l(l2.get("components")))
              + "<h3>Shift per asset</h3>" + assets_table(_l(l2.get("assets")))
              + idr_terms(l2.get("idr_terms")) + gaps(_l(l2.get("gaps"))))
    l3 = p.get("layer3")
    if isinstance(l3, Mapping):
        layer3 = signals_table(_l(l3.get("signals"))) + tally(l3.get("tally"))
    else:
        layer3 = '<p class="muted">no layer-3 signals for this subject (IDN only)</p>'
    return "".join([
        STYLE, '<div class="signals">', head,
        '<p class="muted">Layer 2 adjusts the layer-1 score by the fresh macro; layer 3 reads '
        "who is buying and what the curve says. As computed by the last run.</p>",
        _summary(p),
        _card("layer2", "Layer 2: fresh macro overrides", layer2),
        _card("layer3", "Layer 3: market signals", layer3),
        charts(p.get("charts")),
        "</div>"])


def index(app: web.App, _m: re.Match[str]) -> web.View:
    found = subjects(app.out_dir)
    if not found:
        return web.View(TITLE, f"<h1>Signals</h1>{web.notice(EMPTY)}", {"subjects": []})
    rows, data = [], []
    for s, path in found.items():
        p, problem = load(path, app.cache)
        shifts = {str(_d(a).get("asset")): _d(a).get("shift")
                  for a in _l(_d(_d(p).get("layer2")).get("assets"))}
        n_sig = len(_l(_d(_d(p).get("layer3")).get("signals")))
        data.append({"subject": s, "as_of": _d(p).get("as_of"), "shifts": shifts,
                     "signals": n_sig, "problem": problem})
        cells = "".join(f'<td class="num">{esc(num(shifts.get(a), signed=True))}</td>'
                        for a in ASSETS)
        rows.append(f'<tr><td><a href="/signals/{esc(s)}">{esc(s)}</a></td>'
                    f"<td>{_s(_d(p).get('as_of'))}</td>{cells}"
                    f'<td class="num">{n_sig or DASH}</td>'
                    f"<td>{web.chip('problem', 'warn') + ' ' + esc(problem) if problem else ''}"
                    f"</td></tr>")
    head = (("Subject", False), ("As of", False), *((f"{a} shift", True) for a in ASSETS),
            ("Signals", True), ("", False))
    body = (f'{STYLE}<div class="signals"><h1>Signals</h1><section class="card">'
            f"{_table(head, rows, '')}</section></div>")
    return web.View(TITLE, body, {"subjects": data})


def page(app: web.App, m: re.Match[str]) -> web.View | None:
    found = subjects(app.out_dir)
    subject = m.group(1)
    if subject not in found:
        return None
    p, problem = load(found[subject], app.cache)
    data = p if p is not None and problem is None else {"subject": subject, "problem": problem,
                                                        "file": p}
    return web.View(f"{TITLE} {subject}", render(subject, p, problem), data)
