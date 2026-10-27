"""The industries pages (/industries and /industries/<id>): each IDN name against its industry and
sector median in valuation, dividend, profitability and solvency (S30, `candidates.peers`).

Reads `app.out_dir/industries/IDN.json` as written by `assist run` or `assist industries`; the
page never opens a store. `/industries` lists the industries by sector with their size by cap
tier and the industry median beside Stockbit's average. `/industries/<id>` draws one chart of
four small multiples (a row per name, grouped big / mid / small cap by market cap): the bar is
the category score against the industry median, the ring against the sector median, both on a
log axis from 1/4x to 4x, right (blue) better and left (red) worse, so direction carries the
sign without colour. Below it, a table per category gives every value with its deviation, and
the benchmarks (medians, then Stockbit's averages) as the first rows. Names on the S20
undervalued list (`out/candidates/IDN.json`) are starred. <id> is matched exactly against the
ids in the file and never becomes a path. Every value read from a file goes through `esc`.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

from assist import web
from assist.web import esc

TITLE = "Assist Industries"
FILE = Path("industries") / "IDN.json"
CANDIDATES = Path("candidates") / "IDN.json"
DASH = "-"
EMPTY = "no peer comparison in out/industries/ yet: run `assist industries` or `assist run`"
TIERS = (("big", "Big cap (≥ IDR 10T)"), ("mid", "Mid cap (IDR 1–10T)"),
         ("small", "Small cap (< IDR 1T)"), (None, "No market cap"))
PCT = {"div_yield", "payout", "roe", "roa", "roic", "npm", "opm", "gpm"}
INDEX_METRICS = (("pe", "PE"), ("pbv", "PBV"), ("div_yield", "Yield %"), ("roe", "ROE %"),
                 ("der", "D/E"))

# chart geometry (SVG user units; the SVG scales to the card's width)
LABEL_W, PANEL_W, GAP, ROW_H, HEAD_H, BAR_H = 112, 200, 30, 18, 34, 10
TICKS = ((0.25, "¼×"), (0.5, "½×"), (1.0, "1×"), (2.0, "2×"), (4.0, "4×"))

STYLE = """<style>
.peers { --pos:#2a78d6; --neg:#e34948; --mid:#c9c8c3; --grid:#e3e3df; }
@media (prefers-color-scheme: dark) { .peers { --pos:#3987e5; --neg:#e66767; --mid:#55554f;
  --grid:#33332f; } }
.peers svg { width:100%; min-width:720px; height:auto; display:block; }
.peers svg text { fill:var(--fg); font-size:11px; }
.peers svg .axis text, .peers svg text.muted { fill:var(--muted); }
.peers svg .grid { stroke:var(--grid); stroke-width:1; }
.peers svg .zero { stroke:var(--mid); stroke-width:1.5; }
.peers svg .pos { fill:var(--pos); }
.peers svg .neg { fill:var(--neg); }
.peers svg .ring { fill:var(--card); stroke:var(--fg); stroke-width:1.5; }
.peers svg .hit { fill:transparent; }
.peers svg .hit:hover { fill:var(--line); fill-opacity:.5; }
.peers .legend { display:flex; gap:16px; flex-wrap:wrap; color:var(--muted); font-size:12px;
  margin:0 0 14px; align-items:center; }
.peers .key { display:inline-block; vertical-align:middle; margin-right:5px; }
.peers .key.bar { width:16px; height:8px; border-radius:2px; }
.peers .key.ring { width:8px; height:8px; border-radius:50%; border:1.5px solid var(--fg); }
.peers .key.pos { background:var(--pos); } .peers .key.neg { background:var(--neg); }
.peers td.num, .peers th.num { text-align:right; white-space:nowrap; }
.peers td .dev { display:block; color:var(--muted); font-size:11px; }
.peers tr.bench td { color:var(--muted); }
.peers details summary { cursor:pointer; font-weight:600; }
</style>"""


def load(out_dir: Path, cache: dict | None = None) -> tuple[dict | None, str | None]:
    """(payload, problem). The parsed file is cached per mtime in the app's view cache."""
    path = Path(out_dir) / FILE
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None, EMPTY
    key = ("industries", str(path))
    if cache is not None and (hit := cache.get(key)) and hit[0] == stamp:
        return hit[1], None
    try:
        p = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return None, f"{FILE} is not valid JSON ({e})"
    if not isinstance(p, dict) or not isinstance(p.get("industries"), list):
        return None, f"{FILE} has no industries list"
    if cache is not None:
        cache[key] = (stamp, p)
    return p, None


def starred(out_dir: Path) -> dict[str, list[str]]:
    """symbol → the S20 styles that list it; empty when there is no readable candidates file."""
    try:
        p = json.loads((Path(out_dir) / CANDIDATES).read_text())
    except (OSError, ValueError):
        return {}
    out: dict[str, list[str]] = {}
    for s in p.get("styles") or [] if isinstance(p, dict) else []:
        for r in s.get("rows") or []:
            if isinstance(r, Mapping) and r.get("symbol"):
                out.setdefault(str(r["symbol"]), []).append(str(s.get("style", "")))
    return out


def _d(x: Any) -> Mapping:
    return x if isinstance(x, Mapping) else {}


def _f(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def value(key: str, x: Any) -> str:
    v = _f(x)
    if v is None:
        return DASH
    if abs(v) >= 1e12:
        return f"IDR {v / 1e12:,.1f}T"
    if abs(v) >= 1e9:
        return f"IDR {v / 1e9:,.0f}B"
    return f"{v:,.2f}%" if key in PCT else f"{v:,.2f}"


def times(dev: Any) -> str:
    """A log deviation as a multiple of the benchmark: 0.4055 → '1.50×'."""
    d = _f(dev)
    return DASH if d is None else f"{math.exp(d):.2f}×"


def _better(score: Any) -> str:
    s = _f(score)
    if s is None:
        return "no comparable metric"
    m = math.exp(abs(s))
    return "level" if m < 1.005 else f"{m:.2f}× {'better' if s > 0 else 'worse'}"


def _caption(p: Mapping) -> str:
    stale = [str(s) for s in p.get("stale_inputs") or []]
    note = "".join(web.notice(s) for s in stale)
    return (f'<p class="muted">As of {esc(str(p.get("as_of", DASH)))} (built '
            f'{esc(str(p.get("built", DASH)))}), {esc(str(p.get("source", "")))}. Scored against '
            "the industry and sector medians computed here; Stockbit's averages are means that "
            "loss-makers can drag below zero, shown as a cross-check.</p>" + note)


# ---------------- /industries ----------------


def _tier_counts(ind: Mapping) -> str:
    counts = {t: 0 for t, _ in TIERS}
    for s in ind.get("stocks") or []:
        t = _d(s).get("tier")
        counts[t if t in counts else None] += 1
    return " / ".join(str(counts[t]) for t in ("big", "mid", "small"))


def index(app: web.App, _m: re.Match[str]) -> web.View:
    p, problem = load(app.out_dir, app.cache)
    if p is None:
        body = f"<h1>Industries</h1>{web.notice(problem or EMPTY)}"
        return web.View(TITLE, body, {"industries": [], "problem": problem})
    by_sector: dict[str, list[Mapping]] = {}
    for ind in p["industries"]:
        if isinstance(ind, Mapping):
            by_sector.setdefault(str(ind.get("sector") or "Unknown sector"), []).append(ind)
    cards = []
    for sector, inds in by_sector.items():
        head = "".join(f'<th class="num">{esc(lb)}<br><span class="muted">median · avg</span></th>'
                       for _, lb in INDEX_METRICS)
        rows = []
        for ind in inds:
            avg, med = _d(ind.get("average")), _d(ind.get("median"))
            cells = "".join(f'<td class="num">{esc(value(k, med.get(k)))}<span class="dev">'
                            f"{esc(value(k, avg.get(k)))}</span></td>" for k, _ in INDEX_METRICS)
            href = "/industries/" + quote(str(ind.get("id", "")), safe="")
            leaders = ", ".join(str(x) for x in ind.get("leaders") or [])
            rows.append(f'<tr><td><a href="{href}">{esc(leaders or str(ind.get("id")))}</a></td>'
                        f'<td class="num">{esc(str(ind.get("n", DASH)))}</td>'
                        f'<td class="num">{esc(_tier_counts(ind))}</td>{cells}</tr>')
        cards.append(f'<section class="card sector"><header><h2>{esc(sector)}</h2>'
                     f'<span class="muted">{len(inds)} industr{"y" if len(inds) == 1 else "ies"}'
                     f'</span></header><table><tr><th>Industry (largest names)</th>'
                     f'<th class="num">Names</th><th class="num">Big / mid / small</th>{head}</tr>'
                     f'{"".join(rows)}</table></section>')
    n = sum(int(_d(i).get("n") or 0) for i in p["industries"])
    body = (f'{STYLE}<div class="peers"><h1>Industries</h1>{_caption(p)}'
            f'<p class="muted">{len(p["industries"])} industries, {n} names. An industry is the '
            "set of names Stockbit gives the same industry average; it has no name in the data, so "
            f'it is labelled by its largest names.</p>{"".join(cards)}</div>')
    data = {"as_of": p.get("as_of"), "industries": [
        {k: _d(i).get(k) for k in ("id", "label", "sector", "n", "leaders", "average", "median")}
        for i in p["industries"]]}
    return web.View(TITLE, body, data)


# ---------------- /industries/<id> ----------------


def _x(score: float, cx: float) -> float:
    lim = math.log(TICKS[-1][0])
    return cx + max(-1.0, min(1.0, score / lim)) * (PANEL_W / 2 - 6)


def chart(ind: Mapping, cats: Sequence[Mapping], stars: Mapping[str, list[str]]) -> str:
    """Four small multiples sharing the name rows: bar = score vs industry, ring = vs sector."""
    groups = [(lb, [s for s in ind.get("stocks") or [] if _d(s).get("tier") == t])
              for t, lb in TIERS]
    groups = [(lb, ss) for lb, ss in groups if ss]
    n_rows = sum(len(ss) + 1 for _, ss in groups)
    width = LABEL_W + len(cats) * PANEL_W + (len(cats) - 1) * GAP
    height = HEAD_H + n_rows * ROW_H + 6
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="'
             f'{esc(str(ind.get("label", "")))}: category scores vs industry and sector median">']
    bottom = height - 4
    for c, cat in enumerate(cats):
        x0 = LABEL_W + c * (PANEL_W + GAP)
        cx = x0 + PANEL_W / 2
        parts.append(f'<text x="{cx:.1f}" y="12" text-anchor="middle" font-weight="600">'
                     f'{esc(str(cat.get("label", "")))}</text><g class="axis">')
        for t, lb in TICKS:
            x = _x(math.log(t), cx)
            cls = "zero" if t == 1.0 else "grid"
            parts.append(f'<line class="{cls}" x1="{x:.1f}" x2="{x:.1f}" y1="{HEAD_H - 6}" '
                         f'y2="{bottom}"/><text x="{x:.1f}" y="{HEAD_H - 10}" '
                         f'text-anchor="middle">{lb}</text>')
        parts.append("</g>")
    y = HEAD_H
    for label, stocks in groups:
        parts.append(f'<text class="muted" x="0" y="{y + ROW_H - 5}" font-weight="600">'
                     f"{esc(label)}</text>")
        y += ROW_H
        for s in stocks:
            s = _d(s)
            sym = str(s.get("symbol", ""))
            star = " ★" if sym in stars else ""
            parts.append(f'<text x="0" y="{y + ROW_H - 5}">{esc(sym + star)}</text>')
            for c, cat in enumerate(cats):
                key = str(cat.get("key", ""))
                x0 = LABEL_W + c * (PANEL_W + GAP)
                cx = x0 + PANEL_W / 2
                si = _f(_d(s.get("score_industry")).get(key))
                ss = _f(_d(s.get("score_sector")).get(key))
                used = _d(s.get("scored_metrics")).get(key, 0)
                tip = (f"{sym} {cat.get('label', '')}: {_better(si)} than the industry median, "
                       f"{_better(ss)} than the sector median ({used} metric"
                       f"{'' if used == 1 else 's'})")
                parts.append(f'<g><title>{esc(tip)}</title><rect class="hit" x="{x0}" y="{y}" '
                             f'width="{PANEL_W}" height="{ROW_H}"/>')
                if si is not None:
                    x = _x(si, cx)
                    left, w = (cx, x - cx) if x >= cx else (x, cx - x)
                    cls = "pos" if si > 0 else "neg"
                    parts.append(f'<rect class="{cls}" x="{left:.1f}" y="{y + (ROW_H - BAR_H) / 2}"'
                                 f' width="{max(w, 1.5):.1f}" height="{BAR_H}" rx="2"/>')
                if ss is not None:
                    parts.append(f'<circle class="ring" cx="{_x(ss, cx):.1f}" '
                                 f'cy="{y + ROW_H / 2}" r="3.5"/>')
                parts.append("</g>")
            y += ROW_H
    parts.append("</svg>")
    return "".join(parts)


LEGEND = ('<p class="legend"><span><span class="key bar pos"></span><span class="key bar neg">'
          "</span>bar: score vs the industry median</span><span><span class=\"key ring\"></span>"
          "ring: vs the sector median</span><span>right of 1× is better (cheaper, higher yield, "
          "more profitable, more solvent), left is worse; log axis, capped at 4×</span>"
          "<span>★ on the S20 undervalued list</span></p>")


def _table(ind: Mapping, sector: Mapping, cat: Mapping, stars: Mapping[str, list[str]],
           open_: bool) -> str:
    metrics = [_d(m) for m in cat.get("metrics") or []]
    head = "".join(f'<th class="num">{esc(str(m.get("label", "")))}'
                   f'{"" if m.get("better") else "<br><span class=muted>not scored</span>"}</th>'
                   for m in metrics)
    bench_rows = []
    for label, src in (("Industry median (benchmark)", ind.get("median")),
                       ("Industry average (Stockbit)", ind.get("average")),
                       ("Sector median (benchmark)", sector.get("median")),
                       ("Sector average (Stockbit)", sector.get("average"))):
        cells = "".join(f'<td class="num">{esc(value(str(k), _d(src).get(k)))}</td>'
                        for k in (m.get("key") for m in metrics))
        bench_rows.append(f'<tr class="bench"><td>{esc(label)}</td><td></td><td></td>{cells}</tr>')
    rows = []
    key = str(cat.get("key", ""))
    for s in ind.get("stocks") or []:
        s = _d(s)
        sym = str(s.get("symbol", ""))
        vals, di, ds = _d(s.get("values")), _d(s.get("dev_industry")), _d(s.get("dev_sector"))
        cells = "".join(
            f'<td class="num">{esc(value(str(m.get("key")), vals.get(m.get("key"))))}'
            f'<span class="dev">{esc(times(di.get(m.get("key"))))} ind · '
            f'{esc(times(ds.get(m.get("key"))))} sec</span></td>' for m in metrics)
        star = f' <span class="muted">★ {esc(", ".join(stars[sym]))}</span>' if sym in stars else ""
        score = _d(s.get("score_industry")).get(key)
        rows.append(f'<tr><td><strong>{esc(sym)}</strong>{star}<span class="dev">'
                    f'{esc(str(s.get("name", "")))}</span></td>'
                    f'<td>{esc(str(s.get("tier") or DASH))}</td>'
                    f'<td class="num">{esc(times(score))}</td>{cells}</tr>')
    return (f'<details class="card table" data-category="{esc(key)}"{" open" if open_ else ""}>'
            f'<summary>{esc(str(cat.get("label", "")))}</summary><table><tr><th>Name</th>'
            f'<th>Tier</th><th class="num">Score vs ind</th>{head}</tr>{"".join(bench_rows)}'
            f'{"".join(rows)}</table></details>')


def page(app: web.App, m: re.Match[str]) -> web.View | None:
    p, _problem = load(app.out_dir, app.cache)
    if p is None:
        return None
    ind = next((i for i in p["industries"]
                if isinstance(i, Mapping) and str(i.get("id")) == m.group(1)), None)
    if ind is None:
        return None
    cats = [_d(c) for c in p.get("categories") or []]
    stars = starred(app.out_dir)
    sector = _d(_d(p.get("sectors")).get(str(ind.get("sector", ""))))
    tables = "".join(_table(ind, sector, c, stars, i == 0) for i, c in enumerate(cats))
    body = (f'{STYLE}<div class="peers"><p><a href="/industries">← Industries</a></p>'
            f'<h1>{esc(str(ind.get("label", "")))}</h1>{_caption(p)}'
            f'<p class="muted">{esc(str(ind.get("sector", "")))} · {esc(str(ind.get("n", DASH)))}'
            f' names · industry id <code>{esc(str(ind.get("id", "")))}</code></p>'
            f'<section class="card chart">{LEGEND}{chart(ind, cats, stars)}</section>'
            f"{tables}</div>")
    return web.View(f"{TITLE} {ind.get('id', '')}", body, {**ind, "sector_benchmarks": sector})
