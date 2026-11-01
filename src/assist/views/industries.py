"""The industries page (/industries): each IDN name against Stockbit's industry average and the
sector median in valuation, dividend, profitability and solvency (S30, `candidates.peers`; there is
no industry median).

Reads `app.out_dir/industries/IDN.json` as written by `assist run` or `assist industries`; the page
never opens a store. `/industries` is one card per industry of the names that pass `rows`' filters
(PE and PBV each below the industry average, ROE above it, D/E below the industry's cap; dividend
not filtered), sorted by overall score (the mean of the category scores vs the industry average),
most positive first, each industry in its own tab (CSS radio tabs, no script, the first open): per
metric (PE, PBV, yield, ROE, D/E) a bar per name beside Stockbit's industry average, and the cap
marked on D/E. Below it in the same card, the financials of those names: per
statement (income statement, balance sheet) a timeline of small multiples, one line per name over
the last quarters in the file (each quarter on its own, not year-to-date), at most `MAX_LINES`
names, each panel on its own linear axis, then their profitability per quarter over the last
`YEARS` years (gross, operating and net margin, annualised ROE), clipped to ±`PCT_CLIP`. Names
on the S20 undervalued list (`out/candidates/IDN.json`) are starred. There is no page per
industry. Every value read from a file goes through `esc`.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from assist import web
from assist.web import esc

TITLE = "Assist Industries"
FILE = Path("industries") / "IDN.json"
CANDIDATES = Path("candidates") / "IDN.json"
DASH = "-"
EMPTY = "no peer comparison in out/industries/ yet: run `assist industries` or `assist run`"
PCT = {"div_yield", "payout", "roe", "roa", "roic", "npm", "opm", "gpm"}

# chart geometry (SVG user units; the SVG scales to the card's width)
ROW_H, HEAD_H, BAR_H = 18, 34, 10

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
.peers svg .hit { fill:transparent; }
.peers svg .hit:hover { fill:var(--line); fill-opacity:.5; }
.peers .legend { display:flex; gap:16px; flex-wrap:wrap; color:var(--muted); font-size:12px;
  margin:0 0 14px; align-items:center; }
.peers .key { display:inline-block; vertical-align:middle; margin-right:5px; }
.peers .key.bar { width:16px; height:8px; border-radius:2px; }
.peers .key.pos { background:var(--pos); } .peers .key.neg { background:var(--neg); }
.peers td.num, .peers th.num { text-align:right; white-space:nowrap; }
.peers td .dev { display:block; color:var(--muted); font-size:11px; }
.peers details summary { cursor:pointer; font-weight:600; }
.peers svg .bench { fill:var(--mid); }
.peers svg .lvl { fill:var(--mid); }
.peers svg .avgline { stroke:var(--fg); stroke-width:1; stroke-dasharray:3 3; opacity:.6; }
.peers svg .capline { stroke:var(--neg); stroke-width:1.5; }
.peers .key.bench { background:var(--mid); }
.peers section.industry header { display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; }
.peers section.industry h2 { margin:0 0 8px; }
.peers section.industry h3 { margin:18px 0 6px; }
.peers section.industry h4 { margin:10px 0 4px; }
.peers { --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300;
  --s7:#6250d6; --s8:#e34948; }
@media (prefers-color-scheme: dark) { .peers { --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --s4:#c98500; --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767; } }
.peers svg .line { fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
.peers svg .dot { stroke:var(--card); stroke-width:1.5; }
.peers svg g.pt:hover .dot { r:4.5; }
.peers .key.line { width:14px; height:3px; border-radius:2px; }
.peers .tabs { display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
.peers .tabs > input { position:absolute; opacity:0; pointer-events:none; }
.peers .tabs > label { order:0; cursor:pointer; padding:4px 10px; border:1px solid var(--line);
  border-radius:999px; font-size:13px; color:var(--muted); white-space:nowrap; }
.peers .tabs > label:hover { color:var(--fg); }
.peers .tabs > input:checked + label { color:var(--fg); background:var(--card); font-weight:600;
  border-color:var(--muted); }
.peers .tabs > input:focus-visible + label { outline:2px solid var(--pos); outline-offset:1px; }
.peers .tabs > section { order:1; width:100%; display:none; }
.peers .tabs > input:checked + label + section { display:block; }
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
        p = json.loads(path.read_text(encoding="utf-8"))
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
        p = json.loads((Path(out_dir) / CANDIDATES).read_text(encoding="utf-8"))
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
    quarters = [str(q) for q in p.get("periods") or []]
    stmts = [_d(s) for s in p.get("statements") or []]
    for ind, members in groups(table, p):
        cap = der_cap(ind.get("label"))
        cap_text = "no D/E cap" if cap is None else f"D/E cap {cap:g}"
        tab = f"ind-{len(cards)}"
        cards.append(f'<input type="radio" name="industry" id="{tab}"'
                     f'{" checked" if not cards else ""}><label for="{tab}">'
                     f'{esc(str(ind.get("label", "")))} <span class="muted">{len(members)}'
                     f'</span></label><section class="card chart industry" data-industry="'
                     f'{esc(str(ind.get("id", "")))}"><header><h2>'
                     f'{esc(str(ind.get("label", "")))}</h2><span class="muted">'
                     f'{esc(str(ind.get("sector", "")))} · {len(members)} of '
                     f'{esc(str(ind.get("n", DASH)))} names pass · {cap_text}</span></header>'
                     f"{industry_chart(ind, members, stars)}"
                     f"{financials(ind, members, quarters, stmts)}</section>")
    n = sum(len(_d(i).get("stocks") or []) for i in p["industries"])
    tabs = f'<div class="tabs">{"".join(cards)}</div>' if cards else web.notice("no name passes")
    body = (f'{STYLE}<div class="peers"><h1>Industries</h1>{_caption(p)}'
            f'<p class="muted">{len(table)} of {n} names in {len(cards)} of '
            f'{len(p["industries"])} industries pass: a PE and a PBV each below the industry '
            "average, an ROE above it, and a D/E from 0 up to the industry's cap (1 unless the "
            "card says otherwise; banks and insurers have none). Dividend is not filtered. A "
            "missing value or average fails. One tab per industry, the "
            "industry of the best overall score first and its names in that order. An industry "
            "is a Stockbit peer group, named by the IDX sub-sector it matches. Below each chart, "
            "the same names' quarterly income statement and balance sheet, each quarter on its "
            "own (not year-to-date), IDR, each panel on its own axis; hover a dot for its value. "
            "Profitability is per quarter over the last 3 years: gross, operating and net margin "
            "on revenue, and ROE as the quarter's net income × 4 on its equity, left out where "
            f"revenue or equity is zero or negative; the axis stops at ±{PCT_CLIP:.0f}% (hover "
            "for the real value). "
            "Total assets and liabilities are not shown: idx-method's items mix totals and "
            "non-current parts across names. A name that reports in USD can show near zero."
            f"</p>{INDEX_LEGEND}{tabs}</div>")
    return web.View(TITLE, body, {"as_of": p.get("as_of"), "rows": table, "industries": [
        {"id": ind.get("id"), "label": ind.get("label"), "sector": ind.get("sector"),
         "average": ind.get("average"), "der_cap": der_cap(ind.get("label")),
         "symbols": [r["symbol"] for r in members]} for ind, members in groups(table, p)]})


# ---------------- financials timelines ----------------

MAX_LINES = 8  # categorical slots: the first 8 passing names with statements, in chart order
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


PCT_CLIP = 100.0  # %: the axis stops here, so one tiny revenue does not flatten the rest
PROFITABILITY = {"key": "profitability", "label": "Profitability",
                 "items": [{"key": "gpm", "label": "Gross margin"},
                           {"key": "opm", "label": "Operating margin"},
                           {"key": "npm", "label": "Net margin"},
                           {"key": "roe", "label": "ROE (annualised)"}]}
YEARS = 3  # the profitability timeline: the last 3 years of quarters in the file


def ratio(num: Sequence[Any], den: Sequence[Any], scale: float = 100.0) -> list[float | None]:
    """Per quarter, num / den × `scale` in %: None where either is missing or den is at or below
    0 (a margin on no revenue, or a return on negative equity, has no sign that reads)."""
    out = []
    for a, b in zip(num, den, strict=False):
        a, b = _f(a), _f(b)
        out.append(None if a is None or b is None or b <= 0 else round(a / b * scale, 1))
    return out


def profitability(fin: Mapping) -> dict[str, list[float | None]]:
    """A name's quarterly margins on revenue (gross, operating, net) and ROE, the quarter's net
    income × 4 on the equity at its end."""
    rev, ni = fin.get("revenue") or [], fin.get("net_income") or []
    return {"gpm": ratio(fin.get("gross_profit") or [], rev),
            "opm": ratio(fin.get("operating_profit") or [], rev),
            "npm": ratio(ni, rev), "roe": ratio(ni, fin.get("equity") or [], 400.0)}


def _with_statements(ind: Mapping) -> list[Mapping]:
    """The names that carry statements, largest market cap first (the file's order)."""
    return [_d(s) for s in ind.get("stocks") or [] if _d(_d(s).get("financials"))]


def timeline(ind: Mapping, stmt: Mapping, quarters: Sequence[str],
             names: Sequence[Mapping], pct: bool = False) -> str:
    """One panel per item of `stmt`, sharing the quarters on x: a 2px line per name (a gap where
    a quarter is missing), a dot per quarter with its value on hover, a zero line when the axis
    crosses 0. `pct`: the values are percentages, the axis clipped to ±`PCT_CLIP` (a point past
    it is drawn on the edge, its hover gives the real value)."""
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
        if pct:
            series = [[None if v is None else max(-PCT_CLIP, min(PCT_CLIP, v)) for v in ser]
                      for ser in series]
            real = [[_f(v) for v in (_d(r.get("financials")).get(key) or [])][:n] for r in names]
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
                         f'text-anchor="end">{esc(f"{t:+.0f}%" if pct and t else compact(t))}'
                         "</text>")
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
                             f'{esc(f"{real[k][i]:,.1f}%" if pct else value(key, v))}'
                             f'</title><circle class="dot" cx="{x(i):.1f}" '
                             f'cy="{y(v):.1f}" r="3" fill="{color}"/></g>')
    parts.append("</svg>")
    return "".join(parts)


def financials(ind: Mapping, members: Sequence[Mapping], quarters: Sequence[str],
               stmts: Sequence[Mapping]) -> str:
    """One timeline per statement under an industry's chart, for its passing names (`members`,
    in chart order) that carry statements, at most `MAX_LINES`."""
    fin = {str(_d(s).get("symbol")): _d(s) for s in _with_statements(ind)}
    lines = [fin[sym] for r in members if (sym := str(r.get("symbol"))) in fin][:MAX_LINES]
    if not quarters or not stmts or not lines:
        return web.notice("no quarterly statements for these names (idx-method fundamentals)")
    legend = "".join(f'<span><span class="key line" style="background:var(--s{k + 1})"></span>'
                     f'{esc(str(r.get("symbol", "")))}</span>' for k, r in enumerate(lines))
    charts = "".join(f'<div data-statement="{esc(str(s.get("key", "")))}">'
                     f'<h4>{esc(str(s.get("label", "")))}</h4>'
                     f"{timeline(ind, s, quarters, lines)}</div>" for s in stmts)
    recent = list(quarters[-YEARS * 4:])
    off = len(quarters) - len(recent)
    prof = [{"symbol": r.get("symbol"), "financials": {
        k: v[off:] for k, v in profitability(_d(r.get("financials"))).items()}} for r in lines]
    charts += (f'<div data-statement="profitability"><h4>{PROFITABILITY["label"]}, '
               f"{esc(recent[0])} to {esc(recent[-1])}</h4>"
               f"{timeline(ind, PROFITABILITY, recent, prof, pct=True)}</div>")
    return (f'<h3>Financials, {esc(quarters[0])} to {esc(quarters[-1])}</h3>'
            f'<p class="legend">{legend}</p>{charts}')
