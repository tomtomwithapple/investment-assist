"""The industries page (/industries): the S31 top tier per industry, and each IDN name against
Stockbit's industry average and the sector median (S30, `candidates.peers`; there is no industry
median).

Reads `app.out_dir/industries/IDN.json` as written by `assist run` or `assist industries`; the page
never opens a store. Every value read from a file goes through `esc`. There is no page per
industry.

Schema 4 (S31, `candidates.tiers`): the page opens with a table **Top tier by industry**, the
Tier A then Tier B names of each industry (Tier B muted) with their composite, five small pillar
bars (value, quality, growth, health, momentum; a missing pillar drawn as an empty dashed box),
cap tier and the S20 star (`out/candidates/IDN.json`). Industries are ordered by their best
composite. Above the table, the S31 replay (`out/industries/IDN.replay.json`,
`candidates.tiers_replay`): its status and verdict, Tier A's mean 3-month excess over the industry
median against the shuffled placebo, t, p, perm p and control t, the quarters, the flags
(survivorship first) and the per-pillar diagnostics, collapsed; a missing file says the replay has
not run. Below it one tab per industry with picks: its Tier A and B names, the peer group when
it fell back to the sector ("ranked within sector"), the gate failures counted by reason, then
the metric chart (PE, PBV, yield, ROE, D/E against Stockbit's industry average, the D/E cap
marked) and the financials timelines of the picks. The S30 filter (PE and PBV below the industry
average, ROE above it, D/E under the cap: `rows`) stays as a chip on each pick. Industries
without picks are listed compactly in one collapsed card.

Schema 3 (no tier fields): a notice, then the S30 view: one tab per industry of the names that
pass `rows`' filter, sorted by overall score (the mean of the category scores vs the industry
average), with the same chart and financials (per statement a timeline of small multiples, one
line per name over the last quarters in the file, each quarter on its own, at most `MAX_LINES`
names, each panel on its own linear axis, then profitability per quarter over the last `YEARS`
years, clipped to ±`PCT_CLIP`).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from assist import web
from assist.candidates import tiers_replay
from assist.candidates.tiers import DER_CAP, DER_CAP_DEFAULT, der_cap  # noqa: F401 - re-exported
from assist.web import esc

TITLE = "Assist Industries"
FILE = Path("industries") / "IDN.json"
CANDIDATES = Path("candidates") / "IDN.json"
DASH = "-"
EMPTY = "no peer comparison in out/industries/ yet: run `assist industries` or `assist run`"
PCT_CLIP = 100.0  # %: the axis stops here, so one tiny revenue does not flatten the rest
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
.peers table.top-tier td, .peers table.picks td { vertical-align:middle; }
.peers td.sym { white-space:nowrap; }
.peers td.grp { font-weight:600; }
.peers tr.tier-b td { color:var(--muted); }
.peers tr.tier-b svg.pillars { opacity:.5; }
.peers tr.grp-start td { border-top:2px solid var(--line); }
.peers svg.pillars { width:auto; min-width:0; display:inline-block; vertical-align:middle; }
.peers svg.pillars .track { fill:var(--grid); }
.peers svg.pillars .fill { fill:var(--pos); }
.peers svg.pillars .miss { fill:none; stroke:var(--muted); stroke-width:1;
  stroke-dasharray:2 2; }
.peers p.gates { font-size:12px; margin:8px 0 0; }
.peers details.no-picks ul { margin:8px 0 0; padding-left:18px; }
.peers details.no-picks li { margin:2px 0; }
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
# ... and with a D/E from 0 up to (not including) its industry's cap: `der_cap`, which lives in
# the tier model (`candidates.tiers`, S31) since it decides which names get a score there.


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


def passes_filter(ind: Mapping, s: Mapping) -> bool:
    """The S30 filter: PE and PBV each below the industry average (`BELOW`), ROE above it
    (`ABOVE`), D/E from 0 up to the industry's cap (`der_cap`). A value or average that is missing
    fails its filter, except D/E in an industry with no cap."""
    dev = _d(s.get("dev_industry"))
    return (all(_beats(dev.get(k), "lower") for k in BELOW)
            and all(_beats(dev.get(k), "higher") for k in ABOVE)
            and _under_cap(_d(s.get("values")).get("der"), der_cap(ind.get("label"))))


def _row(ind: Mapping, s: Mapping) -> dict:
    dev = _d(s.get("dev_industry"))
    return {"symbol": s.get("symbol"), "name": s.get("name"),
            "industry": ind.get("id"), "industry_label": ind.get("label"),
            "sector": s.get("sector") or ind.get("sector"), "tier": s.get("tier"),
            "mktcap": s.get("mktcap"), "score": overall(s),
            "score_industry": dict(_d(s.get("score_industry"))),
            "values": {k: _d(s.get("values")).get(k) for k, _, _ in METRIC_PANELS},
            "dev_industry": {k: dev.get(k) for k, _, _ in METRIC_PANELS}}


def rows(p: Mapping) -> list[dict]:
    """The names that pass every filter (`passes_filter`), most positive overall score first,
    ties by market cap. Dividend is not filtered."""
    out = [_row(ind, s) for ind in map(_d, p.get("industries") or [])
           for s in map(_d, ind.get("stocks") or []) if passes_filter(ind, s)]
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
             'yield, ROE and D/E of these names against the industry average">']
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
        pick = r.get("pick")
        note = (f"Tier {pick} {_num(r.get('composite'))}" if pick in TIERS
                else times(r.get("score")))
        cls = ' class="muted"' if pick == "B" else ""
        parts.append(f'<text x="0" y="{y + ROW_H - 5}"><tspan font-weight="600"{cls}>'
                     f'{esc(sym + star)}</tspan><tspan class="muted" dx="6">'
                     f'{esc(note)} · {esc(str(r.get("tier") or DASH))}'
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
    if tiered(p):
        return tier_index(p, stars, tiers_replay.load(app.out_dir))
    return filter_index(p, stars)


def filter_index(p: Mapping, stars: Mapping[str, list[str]]) -> web.View:
    """The S30 view, for a payload without tier fields (schema 3), behind a notice."""
    version = p.get("schema_version")
    msg = SCHEMA3.format(v=version if isinstance(version, int) else "unknown")
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
    body = (f'{STYLE}<div class="peers"><h1>Industries</h1>{web.notice(msg)}{_caption(p)}'
            f'<p class="muted">{len(table)} of {n} names in {len(cards)} of '
            f'{len(p["industries"])} industries pass: a PE and a PBV each below the industry '
            "average, an ROE above it, and a D/E from 0 up to the industry's cap (1 unless the "
            "card says otherwise; banks and insurers have none). Dividend is not filtered. A "
            "missing value or average fails. One tab per industry, the "
            "industry of the best overall score first and its names in that order. An industry "
            "is a Stockbit peer group, named by the IDX sub-sector it matches. Below each chart, "
            f"{FIN_NOTE}</p>{INDEX_LEGEND}{tabs}</div>")
    return web.View(TITLE, body, {
        "as_of": p.get("as_of"), "schema_version": version, "notice": msg, "rows": table,
        "industries": [{"id": ind.get("id"), "label": ind.get("label"),
                        "sector": ind.get("sector"), "average": ind.get("average"),
                        "der_cap": der_cap(ind.get("label")),
                        "symbols": [r["symbol"] for r in members]}
                       for ind, members in groups(table, p)]})


FIN_NOTE = ("the same names' quarterly income statement and balance sheet, each quarter on its "
            "own (not year-to-date), IDR, each panel on its own axis; hover a dot for its value. "
            "Profitability is per quarter over the last 3 years: gross, operating and net margin "
            "on revenue, and ROE as the quarter's net income × 4 on its equity, left out where "
            f"revenue or equity is zero or negative; the axis stops at ±{PCT_CLIP:.0f}% (hover "
            "for the real value). Total assets and liabilities are not shown: idx-method's items "
            "mix totals and non-current parts across names. A name that reports in USD can show "
            "near zero.")


# ---------------- /industries, schema 4: the top tier (S31) ----------------

TIERS = ("A", "B")
PILLAR_LABELS = (("value", "Value"), ("quality", "Quality"), ("growth", "Growth"),
                 ("health", "Health"), ("momentum", "Momentum"))
FILTER_CHIP = "beats the industry average on PE, PBV and ROE"
SCHEMA3 = ("out/industries/IDN.json predates the top tier (schema {v}): run `assist industries` "
           "to rebuild it. Showing the S30 view of the names past the PE/PBV/ROE filter.")
NO_PICKS = ("No industry has a top tier in this file: no name passed the gates and scored 50 or "
            "more. The gate failures per industry are listed below.")
P_W, P_GAP, P_H = 10, 3, 18  # pillar bar geometry (px)


def tiered(p: Mapping) -> bool:
    """A schema 4 payload: the tier fields are there to draw."""
    v = _f(p.get("schema_version"))
    return v is not None and v >= 4


def _num(x: Any, nd: int = 1) -> str:
    v = _f(x)
    return DASH if v is None or not math.isfinite(v) else f"{v:.{nd}f}"


def pillar_score(pillars: Any, key: str) -> float | None:
    v = _f(_d(_d(pillars).get(key)).get("score"))
    return v if v is not None and math.isfinite(v) else None


def pillar_bars(pillars: Any) -> str:
    """Five small vertical bars, 0-100, in `PILLAR_LABELS` order; a missing pillar is an empty
    dashed box. Each bar's value on hover."""
    width = len(PILLAR_LABELS) * P_W + (len(PILLAR_LABELS) - 1) * P_GAP
    scores = [(lb, pillar_score(pillars, k)) for k, lb in PILLAR_LABELS]
    aria = ", ".join(f"{lb} {_num(v)}" if v is not None else f"{lb} missing" for lb, v in scores)
    parts = [f'<svg class="pillars" width="{width}" height="{P_H}" viewBox="0 0 {width} {P_H}" '
             f'role="img" aria-label="{esc(aria)}">']
    for i, (lb, v) in enumerate(scores):
        x = i * (P_W + P_GAP)
        if v is None:
            parts.append(f'<g><title>{esc(lb)}: missing</title><rect class="miss" x="{x + .5}" '
                         f'y=".5" width="{P_W - 1}" height="{P_H - 1}" rx="1.5"/></g>')
            continue
        h = max(min(v, 100.0), 0.0) / 100 * P_H
        parts.append(f'<g><title>{esc(lb)} {_num(v)}</title><rect class="track" x="{x}" y="0" '
                     f'width="{P_W}" height="{P_H}" rx="1.5"/><rect class="fill" x="{x}" '
                     f'y="{P_H - h:.1f}" width="{P_W}" height="{max(h, 1):.1f}" rx="1.5"/></g>')
    parts.append("</svg>")
    return "".join(parts)


def best(ind: Mapping) -> float | None:
    """An industry's best composite, None when no name has one."""
    xs = [v for s in ind.get("stocks") or [] if (v := _f(_d(s).get("composite"))) is not None]
    return max(xs) if xs else None


def _picks(ind: Mapping) -> list[tuple[str, Mapping]]:
    """(tier, name) for the industry's Tier A then Tier B symbols that are in its stocks."""
    by_sym = {str(_d(s).get("symbol")): _d(s) for s in ind.get("stocks") or []}
    picks = _d(ind.get("picks"))
    out = []
    for t in TIERS:
        syms = picks.get(t)
        for sym in syms if isinstance(syms, list) else []:
            if str(sym) in by_sym:
                out.append((t, by_sym[str(sym)]))
    return out


def ordered(p: Mapping) -> list[Mapping]:
    """The industries, the best composite first; those without one last, by label."""
    inds = [_d(i) for i in p.get("industries") or []]
    return sorted(inds, key=lambda i: (best(i) is None, -(best(i) or 0.0),
                                       str(i.get("label", "")), str(i.get("id", ""))))


def tier_rows(p: Mapping, stars: Mapping[str, list[str]]) -> list[dict]:
    """The top tier table: per industry in `ordered` order, Tier A then Tier B."""
    out = []
    for ind in ordered(p):
        group = _d(ind.get("peer_group"))
        for t, s in _picks(ind):
            sym = str(s.get("symbol", ""))
            out.append({**_row(ind, s), "pick": t, "rank": s.get("rank"),
                        "composite": _f(s.get("composite")),
                        "pillars": {k: pillar_score(s.get("pillars"), k)
                                    for k, _ in PILLAR_LABELS},
                        "starred": sym in stars, "styles": list(stars.get(sym, [])),
                        "beats_average": passes_filter(ind, s),
                        "peer_group": group.get("level")})
    return out


def _pick_rows(rs: Sequence[Mapping], stars: Mapping[str, list[str]], top: bool) -> str:
    """Table rows of picks; `top`: the page's table (an industry column, its name on the first
    row of each industry), else an industry card (the old filter chip)."""
    out, last = [], None
    for r in rs:
        sym = str(r.get("symbol", ""))
        star = " ★" if sym in stars else ""
        tier = str(r["pick"])
        cls = f"tier-{tier.lower()}"
        first = top and r.get("industry") != last
        last = r.get("industry")
        cells = []
        if top:
            grp = esc(str(r.get("industry_label") or "")) if first else ""
            cells.append(f'<td class="grp">{grp}</td>')
        else:
            cells.append(f'<td class="num">{esc(_num(r.get("rank"), 0))}</td>')
        chip = web.chip(FILTER_CHIP, "good") if not top and r.get("beats_average") else ""
        cells += [f'<td>{web.chip(f"Tier {tier}", "good" if tier == "A" else "muted")}</td>',
                  f'<td class="sym"><b>{esc(sym + star)}</b></td>',
                  f'<td>{esc(str(r.get("name") or ""))}{" " + chip if chip else ""}</td>',
                  f'<td class="num">{esc(_num(r.get("composite")))}</td>',
                  f'<td>{pillar_bars({k: {"score": v} for k, v in r["pillars"].items()})}</td>',
                  f'<td>{esc(str(r.get("tier") or DASH))}</td>']
        row_cls = f"{cls} grp-start" if first and out else cls
        out.append(f'<tr class="{row_cls}" data-symbol="{esc(sym)}">{"".join(cells)}</tr>')
    return "".join(out)


PICK_HEAD = ('<th>Tier</th><th>Symbol</th><th>Name</th><th class="num">Composite</th>'
             '<th>Pillars <span class="muted">V Q G H M</span></th><th>Cap</th>')


def _peer_text(ind: Mapping) -> str:
    g = _d(ind.get("peer_group"))
    n = esc(_num(g.get("n"), 0))
    if g.get("level") == "sector":
        return f"ranked within sector {esc(str(g.get('label') or ''))} ({n} names past the gates)"
    return f"ranked within the industry ({n} names past the gates)"


def _failures(ind: Mapping) -> list[tuple[str, int]]:
    fails = _d(ind.get("gate_failures"))
    xs = [(str(k), int(v)) for k, v in fails.items() if _f(v) is not None and v > 0]
    return sorted(xs, key=lambda kv: (-kv[1], kv[0]))


def _failure_text(ind: Mapping) -> str:
    return " · ".join(f"{esc(k)} {v}" for k, v in _failures(ind))


def tier_card(ind: Mapping, members: Sequence[Mapping], stars: Mapping[str, list[str]],
              quarters: Sequence[str], stmts: Sequence[Mapping], tab: str, first: bool) -> str:
    cap = der_cap(ind.get("label"))
    cap_text = "no D/E cap" if cap is None else f"D/E cap {cap:g}"
    label = esc(str(ind.get("label", "")))
    fails = _failure_text(ind)
    gates = (f'<p class="gates muted">Gate failures, by reason (a name can fail several): '
             f"{fails}</p>" if fails else '<p class="gates muted">No name failed a gate.</p>')
    n_a = sum(r["pick"] == "A" for r in members)
    return (f'<input type="radio" name="industry" id="{tab}"{" checked" if first else ""}>'
            f'<label for="{tab}">{label} <span class="muted">{len(members)}</span></label>'
            f'<section class="card chart industry" data-industry="'
            f'{esc(str(ind.get("id", "")))}"><header><h2>{label}</h2><span class="muted">'
            f'{esc(str(ind.get("sector", "")))} · {n_a} Tier A, {len(members) - n_a} Tier B · '
            f'{esc(_num(ind.get("gated"), 0))} of {esc(_num(ind.get("n"), 0))} names past the '
            f"gates · {_peer_text(ind)} · {cap_text}</span></header>"
            f'<table class="picks"><tr><th class="num">Rank</th>{PICK_HEAD}</tr>'
            f"{_pick_rows(members, stars, top=False)}</table>{gates}"
            f"<h3>Against the industry average</h3>{industry_chart(ind, members, stars)}"
            f"{financials(ind, members, quarters, stmts)}</section>")


def _why_none(ind: Mapping) -> str:
    gated = _f(ind.get("gated")) or 0
    fails = _failure_text(ind)
    if gated <= 0:
        return f"no name passes the gates ({fails})" if fails else "no name passes the gates"
    b = best(ind)
    if b is None:
        return f"{_num(gated, 0)} past the gates, none with enough pillars for a composite"
    return f"{_num(gated, 0)} past the gates, best composite {esc(_num(b))} (under 50)"


def no_picks(inds: Sequence[Mapping]) -> str:
    if not inds:
        return ""
    k = len(inds)
    items = "".join(f"<li><b>{esc(str(i.get('label', '')))}</b> <span class=\"muted\">"
                    f"{esc(str(i.get('sector', '')))} · {_why_none(i)}</span></li>"
                    for i in inds)
    return (f'<details class="card no-picks"><summary>{k} '
            f'{"industry" if k == 1 else "industries"} without a top tier</summary>'
            f"<ul>{items}</ul></details>")


TIER_CHART_LEGEND = INDEX_LEGEND.replace(
    "its overall score (multiple of the average)", "its tier and composite")
TIER_LEGEND = ('<p class="legend"><span><span class="key bar pos"></span>pillar score '
               "(0-100, percentile among peers)</span><span>dashed box: pillar missing (weights "
               "rescaled)</span><span>muted rows: Tier B</span><span>★ on the S20 undervalued "
               "list</span></p>")


REPLAY_KEYS = ("status", "verdict", "quarters", "first_quarter", "last_quarter", "mean_excess",
               "mean_placebo", "t", "p", "perm_p", "control_t", "context_only", "flags",
               "fingerprint", "as_of", "built")


def _pt(x: Any) -> str:
    """A return as a fraction → signed percentage points ("+1.23 pt")."""
    v = _f(x)
    return DASH if v is None else f"{v * 100:+.2f} pt"


def replay_card(r: Mapping | None) -> str:
    """The S31 replay verdict above the top tier table; a notice when it has not run."""
    if r is None:
        return web.notice("top tier replay has not run (out/industries/IDN.replay.json missing): "
                          "the tiers are context only")
    status = str(r.get("status") or DASH)
    tone = "good" if status == "passed" else "bad" if status == "failed" else "warn"
    q = (f"{_num(r.get('quarters'), 0)} quarters, {esc(str(r.get('first_quarter') or DASH))} to "
         f"{esc(str(r.get('last_quarter') or DASH))}")
    stats = (f"Tier A minus industry median, 3-month forward: {esc(_pt(r.get('mean_excess')))} "
             f"vs placebo {esc(_pt(r.get('mean_placebo')))} · t {esc(_num(r.get('t'), 2))} · "
             f"p {esc(_num(r.get('p'), 3))} · perm p {esc(_num(r.get('perm_p'), 3))} · control t "
             f"{esc(_num(r.get('control_t'), 2))}")
    flags = sorted((str(f) for f in r.get("flags") or []),
                   key=lambda f: not f.startswith("survivorship"))
    ctx = ("<p><b>Context only:</b> the tiers move no screen, list, size or stance.</p>"
           if r.get("context_only", True) else "")
    pil = _d(r.get("pillars"))
    prow = "".join(f"<tr><td>{esc(lb)}</td><td>{_num(_d(pil.get(k)).get('quarters'), 0)}</td>"
                   f"<td>{esc(_pt(_d(pil.get(k)).get('mean_excess')))}</td>"
                   f"<td>{esc(_num(_d(pil.get(k)).get('t'), 2))}</td></tr>"
                   for k, lb in PILLAR_LABELS if k in pil)
    pillars = (f"<details><summary>Per pillar (diagnostics, decides nothing)</summary><table>"
               f"<tr><th>Pillar</th><th>Quarters</th><th>Mean excess</th><th>t</th></tr>{prow}"
               f"</table></details>" if prow else "")
    items = "".join(f"<li>{esc(f)}</li>" for f in flags)
    ul = f'<ul class="muted">{items}</ul>' if items else ""
    return (f'<section class="card replay"><h2>Top tier replay {web.chip(status, tone)}</h2>'
            f"<p>{esc(str(r.get('verdict') or DASH))}</p>"
            f'<p class="muted">{q}. {stats}</p>{ctx}'
            f"{ul}{pillars}</section>")


def tier_index(p: Mapping, stars: Mapping[str, list[str]],
               replay: Mapping | None = None) -> web.View:
    """The schema 4 page: the replay verdict, the top tier table, a tab per industry with picks,
    the rest listed."""
    table = tier_rows(p, stars)
    by_ind: dict[str, list[dict]] = {}
    for r in table:
        by_ind.setdefault(str(r["industry"]), []).append(r)
    inds = ordered(p)
    quarters = [str(q) for q in p.get("periods") or []]
    stmts = [_d(s) for s in p.get("statements") or []]
    cards = [tier_card(ind, by_ind[str(ind.get("id"))], stars, quarters, stmts, f"ind-{k}", k == 0)
             for k, ind in enumerate(i for i in inds if str(i.get("id")) in by_ind)]
    rest = [i for i in inds if str(i.get("id")) not in by_ind]
    if table:
        top = (f'<section class="card"><h2>Top tier by industry</h2><table class="top-tier">'
               f"<tr><th>Industry</th>{PICK_HEAD}</tr>{_pick_rows(table, stars, top=True)}"
               f"</table></section>")
    else:
        top = f"<h2>Top tier by industry</h2>{web.notice(NO_PICKS)}"
    n = sum(len(i.get("stocks") or []) for i in inds)
    fp = str(p.get("fingerprint") or "")
    w = _d(_d(p.get("tier_config")).get("weights"))
    weights = ", ".join(f"{lb.lower()} {esc(_num(w.get(k), 0))}" for k, lb in PILLAR_LABELS)
    a_n = sum(r["pick"] == "A" for r in table)
    body = (f'{STYLE}<div class="peers"><h1>Industries</h1>{_caption(p)}'
            f'<p class="muted">{a_n} Tier A and {len(table) - a_n} Tier B names in '
            f"{len(cards)} of {len(inds)} industries ({n} names). A name past the gates "
            "(liquidity, positive TTM net income and equity, the quality floor, D/E under the "
            "industry's cap) gets a composite from 0 to 100: the weighted mean of five pillars "
            f"({weights}), each the mean of its metrics' percentiles among the peers. Peers are "
            "the industry, or the sector when fewer than 8 of its names pass the gates. Tier A is "
            "the top 20% of an industry's gated names (1 to 3, 5 from 40) scoring 60 or more, "
            "Tier B as many again scoring 50 or more. Industries are ordered by their best "
            "composite. Context only: no stance reads the tiers until the S31 replay passes its "
            f'placebo. Model <code>{esc(fp[:19] or DASH)}</code>.</p>{replay_card(replay)}'
            f'{TIER_LEGEND}{top}'
            f'<p class="muted">One tab per industry with a top tier: its picks, the old S30 '
            f"filter as a chip ({FILTER_CHIP}), the gate failures, then the picks' metrics "
            f"against Stockbit's industry average and below the chart {FIN_NOTE}</p>"
            f'{TIER_CHART_LEGEND}<div class="tabs">{"".join(cards)}</div>{no_picks(rest)}</div>')
    twin_keys = ("industry", "industry_label", "sector", "symbol", "name", "pick", "rank",
                 "composite", "pillars", "tier", "mktcap", "starred", "styles", "beats_average",
                 "peer_group")
    return web.View(TITLE, body, {
        "as_of": p.get("as_of"), "schema_version": p.get("schema_version"),
        "fingerprint": p.get("fingerprint"),
        "replay": {k: replay.get(k) for k in REPLAY_KEYS} if replay else None,
        "rows": [{k: r.get(k) for k in twin_keys} for r in table],
        "industries": [{"id": i.get("id"), "label": i.get("label"), "sector": i.get("sector"),
                        "n": i.get("n"), "gated": i.get("gated"),
                        "peer_group": i.get("peer_group"), "picks": i.get("picks"),
                        "gate_failures": i.get("gate_failures"), "best": best(i),
                        "der_cap": der_cap(i.get("label"))} for i in inds]})


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
