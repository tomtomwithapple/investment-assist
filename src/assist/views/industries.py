"""The industries pages (/industries and /industries/<id>): each IDN name against Stockbit's
industry average and the sector median in valuation, dividend, profitability and solvency (S30,
`candidates.peers`; there is no industry median).

Reads `app.out_dir/industries/IDN.json` as written by `assist run` or `assist industries`; the page
never opens a store. `/industries` is one chart per industry of the names that pass `rows`' filters
(PE and PBV each below the industry average, ROE above it, D/E below the industry's cap; dividend
not filtered), sorted by overall score (the mean of the category scores vs the industry average),
most positive first: per metric (PE, PBV, yield, ROE, D/E) a bar per name beside Stockbit's industry
average, and the cap marked on D/E. `/industries/<id>` draws one chart of four small multiples (a
row per name, grouped big / mid / small cap by market cap): the bar is the category score against
the industry average, the ring against the sector median, both on a log axis from 1/4x to 4x, right
(blue) better and left (red) worse, so direction carries the sign without colour. Below it, a table
per category gives every value with its deviation, and the benchmarks (industry average, sector
median, sector average) as the first rows. Between the chart and the tables, the financials: per
statement (income statement, balance sheet) a timeline of small multiples, one line per competitor
over the last quarters in the file (each quarter on its own, not year-to-date), for the
`MAX_LINES` largest names that have statements, each panel on its own linear axis; a table gives
every name's latest quarter and its change on a year earlier. Names on the S20 undervalued list
(`out/candidates/IDN.json`) are starred. <id> is matched exactly against the ids in the file and
never becomes a path. Every value read from a file goes through `esc`.
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
.peers svg .bench { fill:var(--mid); }
.peers svg .lvl { fill:var(--mid); }
.peers svg .avgline { stroke:var(--fg); stroke-width:1; stroke-dasharray:3 3; opacity:.6; }
.peers svg .capline { stroke:var(--neg); stroke-width:1.5; }
.peers .key.bench { background:var(--mid); }
.peers section.industry header { display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; }
.peers section.industry h2 { margin:0 0 8px; }
.peers { --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300;
  --s7:#6250d6; --s8:#e34948; }
@media (prefers-color-scheme: dark) { .peers { --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --s4:#c98500; --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767; } }
.peers svg .line { fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
.peers svg .dot { stroke:var(--card); stroke-width:1.5; }
.peers svg g.pt:hover .dot { r:4.5; }
.peers .key.line { width:14px; height:3px; border-radius:2px; }
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
            "Stockbit's industry average and the sector median computed here. The industry "
            "average is a mean that loss-makers can drag to zero or below; a metric whose "
            "average is not positive scores nobody in that industry.</p>" + note)


# ---------------- /industries ----------------


def overall(s: Mapping) -> float | None:
    """The mean of a name's category scores vs its industry average; None when none is scored."""
    xs = [v for v in map(_f, _d(s.get("score_industry")).values()) if v is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


LEVEL = 0.005  # a deviation within this of 0 (about 1.00x) is level: drawn grey, passes nothing
BELOW = ("pe", "pbv")  # the ranked list keeps a name below its industry average on each of these
ABOVE = ("roe",)  # ... and above it on each of these
# ... and with a D/E from 0 up to (not including) its industry's cap. The common cap is 1.0; the
# industries named here allow more (capital-heavy, or leverage is the business) or require less
# (asset-light). None: no D/E filter, because the industry's leverage is not read from D/E
# (deposits and policy reserves; most banks and insurers have no D/E on Stockbit).
DER_CAP_DEFAULT = 1.0
DER_CAP: dict[str, float | None] = {
    "Bank": None,
    "Asuransi": None,
    "Jasa Pembiayaan": 5.0,  # multifinance gearing (OJK allows up to 10x)
    "Telekomunikasi": 1.5,
    "Utilitas": 1.5,
    "Infrastruktur Transportasi": 1.5,
    "Perusahaan Holding Multi Sektor": 1.5,  # consolidates finance arms (ASII)
    "Perangkat Lunak & Jasa TI": 0.5,
    "Media & Hiburan": 0.5,
    "Rokok": 0.5,
}


def der_cap(label: Any) -> float | None:
    """The D/E cap of an industry by its label: `DER_CAP`, else `DER_CAP_DEFAULT`."""
    return DER_CAP.get(str(label), DER_CAP_DEFAULT)


def _beats(dev: Any, better: str) -> bool:
    """A deviation better than the industry average by more than `LEVEL`."""
    v = _f(dev)
    return v is not None and (v <= -LEVEL if better == "lower" else v >= LEVEL)


def _under_cap(der: Any, cap: float | None) -> bool:
    v = _f(der)
    return cap is None or (v is not None and 0 <= v < cap)


# one panel per metric on the /industries charts: (key, label, better)
METRIC_PANELS = (("pe", "PE", "lower"), ("pbv", "PBV", "lower"),
                 ("div_yield", "Yield %", "higher"), ("roe", "ROE %", "higher"),
                 ("der", "D/E", "lower"))
M_LABEL_W, M_PANEL_W, M_GAP, M_TEXT_W = 150, 150, 22, 40


def rows(p: Mapping) -> list[dict]:
    """The names that pass every filter, most positive overall score first, ties by market cap.

    Kept only when PE and PBV are each below the industry average (`BELOW`), ROE is above it
    (`ABOVE`), and D/E is at least 0 and below the industry's cap (`der_cap`). Dividend is not
    filtered. A value or average that is missing (shown as -) fails its filter, except D/E in an
    industry with no cap.
    """
    out = []
    for ind in p.get("industries") or []:
        ind = _d(ind)
        cap = der_cap(ind.get("label"))
        for s in ind.get("stocks") or []:
            s = _d(s)
            cats, dev = _d(s.get("score_industry")), _d(s.get("dev_industry"))
            if (not all(_beats(dev.get(k), "lower") for k in BELOW)
                    or not all(_beats(dev.get(k), "higher") for k in ABOVE)
                    or not _under_cap(_d(s.get("values")).get("der"), cap)):
                continue
            score = overall(s)
            out.append({"symbol": s.get("symbol"), "name": s.get("name"),
                        "industry": ind.get("id"), "industry_label": ind.get("label"),
                        "sector": s.get("sector") or ind.get("sector"), "tier": s.get("tier"),
                        "mktcap": s.get("mktcap"), "score": score,
                        "score_industry": dict(cats),
                        "values": {k: _d(s.get("values")).get(k) for k, _, _ in METRIC_PANELS},
                        "dev_industry": {k: dev.get(k) for k, _, _ in METRIC_PANELS}})
    out.sort(key=lambda r: (-(r["score"] or 0), -(_f(r["mktcap"]) or 0), str(r["symbol"])))
    return out


def groups(table: Sequence[Mapping], p: Mapping) -> list[tuple[Mapping, list[Mapping]]]:
    """(industry, its passing names) for every industry with one, the industry of the best
    overall score first; `table` is `rows(p)`, already sorted."""
    by_id = {str(_d(i).get("id")): _d(i) for i in p.get("industries") or []}
    out: dict[str, list[Mapping]] = {}
    for r in table:
        out.setdefault(str(r["industry"]), []).append(r)
    return [(by_id[i], rs) for i, rs in out.items() if i in by_id]


def _bench_label(key: str, x: Any) -> str:
    v = _f(x)
    return "no value" if v is None else value(key, v)


def industry_chart(ind: Mapping, members: Sequence[Mapping],
                   stars: Mapping[str, list[str]]) -> str:
    """Small multiples, one panel per `METRIC_PANELS` metric, sharing the rows: Stockbit's
    industry average (grey) on top, then each passing name, blue when better than the average
    and red when worse. Each panel has its own linear axis from 0 to the largest member, average
    or cap value; the dashed line is the average, the solid red line on D/E the industry's cap
    (none where `der_cap` is None). A value at or below 0, or
    missing, has no bar and is written out; a bar past the axis end is cut and marked »."""
    avg = _d(ind.get("average"))
    cap = der_cap(ind.get("label"))
    bench = (("Industry avg (Stockbit)", avg),)
    n_rows = len(bench) + len(members)
    width = M_LABEL_W + len(METRIC_PANELS) * M_PANEL_W + (len(METRIC_PANELS) - 1) * M_GAP
    height = HEAD_H - 14 + n_rows * ROW_H + 8
    label = esc(str(ind.get("label", "")))
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{label}: PE, PBV, '
             'yield, ROE and D/E of the passing names against the industry average">']
    top, bottom = HEAD_H - 14, height - 4
    for c, (key, lb, better) in enumerate(METRIC_PANELS):
        x0 = M_LABEL_W + c * (M_PANEL_W + M_GAP)
        vals = [v for r in members if (v := _f(_d(r.get("values")).get(key))) is not None]
        m = _f(avg.get(key))
        limit = cap if key == "der" else None
        vmax = max([v for v in [*vals, m, limit] if v is not None and v > 0], default=1.0)
        span = M_PANEL_W - M_TEXT_W

        def x(v: float, x0: float = x0, vmax: float = vmax, span: float = span) -> float:
            return x0 + min(v, vmax) / vmax * span

        hint = "lower is better" if better == "lower" else "higher is better"
        parts.append(f'<text x="{x0}" y="12" font-weight="600">{esc(lb)}</text>'
                     f'<text class="muted" x="{x0 + M_PANEL_W}" y="12" text-anchor="end">'
                     f"{hint}</text>"
                     f'<line class="zero" x1="{x0}" x2="{x0}" y1="{top}" y2="{bottom}"/>')
        if m is not None and m > 0:
            parts.append(f'<line class="avgline" x1="{x(m):.1f}" x2="{x(m):.1f}" y1="{top}" '
                         f'y2="{bottom}"/>')
        if limit is not None:
            parts.append(f'<line class="capline" x1="{x(limit):.1f}" x2="{x(limit):.1f}" '
                         f'y1="{top}" y2="{bottom}"><title>D/E cap {limit:g}</title></line>')
        y = top
        for i, (name, src) in enumerate([*bench, *((None, r) for r in members)]):
            if name is None:
                r = _d(src)
                v = _f(_d(r.get("values")).get(key))
                d = _f(_d(r.get("dev_industry")).get(key))
                good = d is not None and (d < 0 if better == "lower" else d > 0)
                cls = "pos" if good else "neg" if d is not None and abs(d) >= LEVEL else "lvl"
                tip = (f"{r.get('symbol')} {lb}: {_bench_label(key, v)}, {times(d)} the "
                       f"industry average ({_bench_label(key, m)})")
            else:
                v, cls = _f(_d(src).get(key)), "bench"
                tip = f"{name} {lb}: {_bench_label(key, v)}"
            parts.append(f'<g><title>{esc(tip)}</title><rect class="hit" x="{x0}" y="{y}" '
                         f'width="{M_PANEL_W}" height="{ROW_H}"/>')
            if v is not None and v > 0:
                end = x(v)
                cut = v > vmax
                parts.append(f'<rect class="{cls}" x="{x0}" y="{y + (ROW_H - BAR_H) / 2}" '
                             f'width="{max(end - x0, 1.5):.1f}" height="{BAR_H}" rx="2"/>'
                             f'<text x="{end + 4:.1f}" y="{y + ROW_H - 5}">'
                             f'{"» " if cut else ""}{esc(value(key, v))}</text>')
            else:
                parts.append(f'<text class="muted" x="{x0 + 4}" y="{y + ROW_H - 5}">'
                             f'{esc(DASH if v is None else value(key, v))}</text>')
            parts.append("</g>")
            y += ROW_H
            if i == len(bench) - 1:
                parts.append(f'<line class="grid" x1="{x0}" x2="{x0 + M_PANEL_W}" y1="{y}" '
                             f'y2="{y}"/>')
    y = top
    for name, _src in bench:
        parts.append(f'<text class="muted" x="0" y="{y + ROW_H - 5}">{esc(name)}</text>')
        y += ROW_H
    for r in members:
        sym = str(r.get("symbol", ""))
        star = " ★" if sym in stars else ""
        parts.append(f'<text x="0" y="{y + ROW_H - 5}"><tspan font-weight="600">'
                     f'{esc(sym + star)}</tspan><tspan class="muted" dx="6">'
                     f'{esc(times(r.get("score")))} · {esc(str(r.get("tier") or DASH))}'
                     "</tspan></text>")
        y += ROW_H
    parts.append("</svg>")
    return "".join(parts)


INDEX_LEGEND = ('<p class="legend"><span><span class="key bar bench"></span>Stockbit\'s industry '
                "average</span><span><span class=\"key bar pos\"></span>"
                "better than the average</span><span><span class=\"key bar neg\"></span>worse"
                "</span><span>dashed line: the average</span><span>red line on D/E: the industry's "
                "cap</span><span>beside each name: its overall "
                "score (multiple of the average) and cap tier</span><span>★ on the S20 "
                "undervalued list</span></p>")


def index(app: web.App, _m: re.Match[str]) -> web.View:
    p, problem = load(app.out_dir, app.cache)
    if p is None:
        body = f"<h1>Industries</h1>{web.notice(problem or EMPTY)}"
        return web.View(TITLE, body, {"rows": [], "problem": problem})
    stars = starred(app.out_dir)
    table = rows(p)
    cards = []
    for ind, members in groups(table, p):
        href = "/industries/" + quote(str(ind.get("id", "")), safe="")
        cap = der_cap(ind.get("label"))
        cap_text = "no D/E cap" if cap is None else f"D/E cap {cap:g}"
        cards.append(f'<section class="card chart industry" data-industry="'
                     f'{esc(str(ind.get("id", "")))}"><header><h2><a href="{href}">'
                     f'{esc(str(ind.get("label", "")))}</a></h2><span class="muted">'
                     f'{esc(str(ind.get("sector", "")))} · {len(members)} of '
                     f'{esc(str(ind.get("n", DASH)))} names pass · {cap_text}</span></header>'
                     f"{industry_chart(ind, members, stars)}</section>")
    n = sum(len(_d(i).get("stocks") or []) for i in p["industries"])
    body = (f'{STYLE}<div class="peers"><h1>Industries</h1>{_caption(p)}'
            f'<p class="muted">{len(table)} of {n} names in {len(cards)} of '
            f'{len(p["industries"])} industries pass: a PE and a PBV each below the industry '
            "average, an ROE above it, and a D/E from 0 up to the industry's cap (1 unless the "
            "card says otherwise; banks and insurers have none). Dividend is not filtered. A "
            "missing value or average fails. One chart per industry, the "
            "industry of the best overall score first and its names in that order. An industry "
            "is a Stockbit peer group, named by the IDX sub-sector it matches; open one for every "
            f"name.</p>{INDEX_LEGEND}{''.join(cards) or web.notice('no name passes')}</div>")
    return web.View(TITLE, body, {"as_of": p.get("as_of"), "rows": table, "industries": [
        {"id": ind.get("id"), "label": ind.get("label"), "sector": ind.get("sector"),
         "average": ind.get("average"), "der_cap": der_cap(ind.get("label")),
         "symbols": [r["symbol"] for r in members]} for ind, members in groups(table, p)]})


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
             f'{esc(str(ind.get("label", "")))}: category scores vs industry average and sector '
             'median">']
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
                tip = (f"{sym} {cat.get('label', '')}: {_better(si)} than the industry average, "
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
          "</span>bar: score vs the industry average</span><span><span class=\"key ring\"></span>"
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
    for label, src in (("Industry average (Stockbit, benchmark)", ind.get("average")),
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
            f"{financials(p, ind)}{tables}</div>")
    return web.View(f"{TITLE} {ind.get('id', '')}", body, {**ind, "sector_benchmarks": sector})


# ---------------- /industries/<id>: financials timelines ----------------

MAX_LINES = 8  # categorical slots: the 8 largest names with statements, colour by size rank
T_PANEL_W, T_PANEL_H, T_GAP, T_AXIS_W, T_HEAD, T_FOOT = 220, 150, 26, 46, 22, 20
T_SLOTS = 4  # panels per row the SVG is sized for


def compact(x: Any) -> str:
    """IDR as an axis label: 3.2e13 → '32T', 4.5e11 → '450B', -2e10 → '-20B'."""
    v = _f(x)
    if v is None:
        return DASH
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            q = v / div
            return f"{q:,.0f}{unit}" if q == round(q) or abs(q) >= 10 else f"{q:,.1f}{unit}"
    return f"{v:,.0f}"


def nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    """Round ticks (1, 2, 2.5, 5 × 10^k) covering lo..hi, 0 included."""
    lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        hi = lo + 1.0
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    out, t = [], start
    while t < hi + step * 0.999:
        out.append(round(t, 6))
        t += step
    return out


def _with_statements(ind: Mapping) -> list[Mapping]:
    """The names that carry statements, largest market cap first (the file's order)."""
    return [_d(s) for s in ind.get("stocks") or [] if _d(_d(s).get("financials"))]


def timeline(ind: Mapping, stmt: Mapping, quarters: Sequence[str],
             names: Sequence[Mapping]) -> str:
    """One panel per item of `stmt`, sharing the quarters on x: a 2px line per name (a gap where
    a quarter is missing), a dot per quarter with its value on hover, a zero line when the axis
    crosses 0."""
    items = [_d(i) for i in stmt.get("items") or []]
    n = len(quarters)
    slots = max(len(items), T_SLOTS)  # same panel size on every statement
    width = slots * (T_AXIS_W + T_PANEL_W) + (slots - 1) * T_GAP
    height = T_HEAD + T_PANEL_H + T_FOOT
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="'
             f'{esc(str(ind.get("label", "")))}: {esc(str(stmt.get("label", "")))} by quarter, '
             f'{esc(", ".join(str(r.get("symbol", "")) for r in names))}">']
    bottom = T_HEAD + T_PANEL_H
    for c, item in enumerate(items):
        key, label = str(item.get("key", "")), str(item.get("label", ""))
        x0 = c * (T_AXIS_W + T_PANEL_W + T_GAP) + T_AXIS_W
        series = [[_f(v) for v in (_d(r.get("financials")).get(key) or [])][:n] for r in names]
        vals = [v for ser in series for v in ser if v is not None]
        if not vals:
            parts.append(f'<text x="{x0 - T_AXIS_W}" y="12" font-weight="600">{esc(label)}</text>'
                         f'<text class="muted" x="{x0}" y="{T_HEAD + T_PANEL_H / 2}">'
                         "no values for these names</text>")
            continue
        ticks = nice_ticks(min(vals), max(vals))
        lo, hi = ticks[0], ticks[-1]

        def y(v: float, lo: float = lo, hi: float = hi) -> float:
            return bottom - (v - lo) / (hi - lo) * T_PANEL_H

        def x(i: int, x0: float = x0) -> float:
            return x0 + 6 + i * (T_PANEL_W - 12) / max(n - 1, 1)

        parts.append(f'<text x="{x0 - T_AXIS_W}" y="12" font-weight="600">{esc(label)}</text>'
                     '<g class="axis">')
        for t in ticks:
            cls = "zero" if t == 0 else "grid"
            parts.append(f'<line class="{cls}" x1="{x0}" x2="{x0 + T_PANEL_W}" y1="{y(t):.1f}" '
                         f'y2="{y(t):.1f}"/><text x="{x0 - 4}" y="{y(t) + 4:.1f}" '
                         f'text-anchor="end">{esc(compact(t))}</text>')
        for i, q in enumerate(quarters):
            # a label a year (at its Q4) and the latest quarter; a year too close to it is dropped
            if (q.endswith("Q4") and i < n - 3) or i == n - 1:
                anchor = "end" if i == n - 1 else "middle"
                parts.append(f'<text x="{x(i) + (4 if i == n - 1 else 0):.1f}" y="{bottom + 14}" '
                             f'text-anchor="{anchor}">{esc(q if i == n - 1 else q[:4])}</text>')
        parts.append("</g>")
        for k, (r, ser) in enumerate(zip(names, series, strict=True)):
            color = f"var(--s{k + 1})"
            d, pen = [], "M"
            for i, v in enumerate(ser):
                if v is None:
                    pen = "M"
                    continue
                d.append(f"{pen}{x(i):.1f},{y(v):.1f}")
                pen = "L"
            if d:
                parts.append(f'<path class="line" stroke="{color}" d="{" ".join(d)}"/>')
            sym = str(r.get("symbol", ""))
            for i, v in enumerate(ser):
                if v is None or i >= n:
                    continue
                parts.append(f'<g class="pt"><title>{esc(f"{sym} {quarters[i]} {label}: ")}'
                             f'{esc(value(key, v))}</title><circle class="dot" cx="{x(i):.1f}" '
                             f'cy="{y(v):.1f}" r="3" fill="{color}"/></g>')
    parts.append("</svg>")
    return "".join(parts)


def _change(now: Any, before: Any) -> str:
    a, b = _f(now), _f(before)
    if a is None or b is None or b == 0:
        return DASH
    return f"{(a - b) / abs(b) * 100:+.0f}%"


def _statement_table(stmt: Mapping, quarters: Sequence[str], names: Sequence[Mapping],
                     colors: Mapping[str, int]) -> str:
    """Every name's latest quarter per item, and its change on the same quarter a year earlier."""
    items = [_d(i) for i in stmt.get("items") or []]
    last, prev = len(quarters) - 1, len(quarters) - 5
    q = quarters[last] if quarters else DASH
    head = "".join(f'<th class="num">{esc(str(i.get("label", "")))}<br>'
                   f'<span class="muted">{esc(q)} · y/y</span></th>' for i in items)
    rows = []
    for r in names:
        fin, sym = _d(r.get("financials")), str(r.get("symbol", ""))
        key = (f'<span class="key line" style="background:var(--s{colors[sym] + 1})"></span>'
               if sym in colors else "")
        cells = []
        for i in items:
            ser = list(fin.get(str(i.get("key"))) or [])
            now = ser[last] if 0 <= last < len(ser) else None
            before = ser[prev] if 0 <= prev < len(ser) else None
            cells.append(f'<td class="num">{esc(value("", now))}'
                         f'<span class="dev">{esc(_change(now, before))}</span></td>')
        rows.append(f'<tr><td>{key}<strong>{esc(sym)}</strong><span class="dev">'
                    f'{esc(str(r.get("tier") or DASH))}</span></td>{"".join(cells)}</tr>')
    return (f'<details class="card table" data-statement="{esc(str(stmt.get("key", "")))}">'
            f'<summary>{esc(str(stmt.get("label", "")))}: latest quarter, every name</summary>'
            f'<table><tr><th>Name</th>{head}</tr>{"".join(rows)}</table></details>')


def financials(p: Mapping, ind: Mapping) -> str:
    """The financials section of an industry page: legend, one timeline per statement, tables."""
    quarters = [str(q) for q in p.get("periods") or []]
    stmts = [_d(s) for s in p.get("statements") or []]
    have = _with_statements(ind)
    if not quarters or not stmts or not have:
        return ('<h2>Financials</h2>' + web.notice("no quarterly statements for this industry "
                                                    "in out/industries/ (idx-method fundamentals)"))
    lines = have[:MAX_LINES]
    colors = {str(r.get("symbol", "")): k for k, r in enumerate(lines)}
    legend = "".join(f'<span><span class="key line" style="background:var(--s{k + 1})"></span>'
                     f'{esc(str(r.get("symbol", "")))}</span>' for k, r in enumerate(lines))
    n = len(_d(ind).get("stocks") or [])
    note = (f"{len(lines)} largest by market cap of the {len(have)} names with statements "
            f"({n} in the industry)" if len(have) > len(lines)
            else f"{len(have)} of {n} names have statements")
    charts = "".join(f'<section class="card chart" data-statement="{esc(str(s.get("key", "")))}">'
                     f'<h3>{esc(str(s.get("label", "")))}</h3>'
                     f"{timeline(ind, s, quarters, lines)}</section>" for s in stmts)
    tables = "".join(_statement_table(s, quarters, have, colors) for s in stmts)
    return (f'<h2>Financials</h2><p class="muted">Quarterly, {esc(quarters[0])} to '
            f"{esc(quarters[-1])}, each quarter on its own (not year-to-date), IDR; {note}. "
            "Each panel has its own axis; hover a dot for its value. Total assets and liabilities "
            "are not shown: idx-method's items mix totals and non-current parts across names. "
            "A name that reports in USD can show near zero.</p>"
            f'<p class="legend">{legend}</p>{charts}{tables}')
