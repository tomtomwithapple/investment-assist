"""The layer-0 page (/regime): the regime and dollar call, every input with its vote and a 1-year
weekly line, and the regime history from the journal.

Reads `out/layers/regime.json` (S33, `layers_out.regime_payload`), checked against
`schema/layers/regime.schema.json`; a missing, unreadable or schema-failing file, or a stub with
`error`, is a notice and the history still shows. An input is marked stale when it has no value,
when its newest point is more than `STALE_DAYS` older than the file's `as_of`, or when one of the
file's `stale_inputs` names its feature or series id. The line per input draws `value` (the
input as the rule sees it: a level, or its 13-week change) over the file's weekly history; a
null week is a gap, never filled.

Home (IDN) regime (S54): the file's `home` block (schema 1.1.0, S53) as its own card: the state,
points, drivers and the rule's numbers, and each of the four inputs with its points, value,
newest date and 1-year weekly line. A file without the block (1.0.0, or a run with no IDN
sources) shows one line saying so, not a notice.

History: every journal record of kind `regime`, one per weekly run (`assist run` journals the
regime before its stances, which carry the same regime) and one per daily check that changed or
set the baseline (`inputs.job` = "regime"). Newest first; a row whose state or dollar differs
from the one before it is marked. An unreadable journal is a notice. Nothing is written. The
.json twin is the file as read plus the history used and the problems.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from assist import brief, web
from assist.journal import Journal
from assist.web import esc

TITLE = "Assist Regime"
FILE = ("layers", "regime.json")
STALE_DAYS = 14
TONE = {"risk_on": "good", "neutral": "muted", "risk_off": "bad", "missing": "warn"}
DOLLAR_TONE = {"up": "warn", "flat": "muted", "down": "good"}
COLUMNS = ("Input", "Value", "Newest", "Direction", "Vote", "52 weeks")
HOME_COLUMNS = ("Input", "Value", "Newest", "Points", "52 weeks")
HOME_KIND = {"jci_drawdown_20d": "pct", "idx_foreign_z": "level", "usdidr_20d": "pct",
             "sbn_non_resident_20d": "pct"}
NO_HOME = ("no home (IDN) regime in this file (schema 1.0.0, or the run had no IDN sources)")
HIST_COLUMNS = ("As of", "Regime", "Dollar", "From", "Drivers", "Model")
NO_FILE = "no out/layers/regime.json yet: run `assist run`"

# Hover text per input: (what it is and why it matters, when it votes). The thresholds repeat
# `layers.regime.RULES` / `CANDIDATES` in words; tests/test_view_regime.py holds them together.
EXPLAIN = {
    "vix": ("Expected swings in US stocks over the next month, the market's fear gauge. High "
            "means investors are paying up for protection.",
            "Risk-off point at 25 or higher, two points at 35. Risk-on point at 15 or lower."),
    "hy_oas_d13w": ("Extra yield investors demand to hold US junk bonds instead of Treasuries, "
                    "as its change over 13 weeks. Widening means credit stress is building.",
                    "Risk-off point at +0.75pt or more. Risk-on point at -0.50pt or less."),
    "usd_d13w": ("The US dollar against a broad basket of trading-partner currencies, % change "
                 "over 13 weeks. A rising dollar pressures the rupiah and emerging markets.",
                 "Risk-off point at +3% or more. Risk-on point at -3% or less. It also sets the "
                 "dollar call: up past +2%, down past -2%."),
    "real_yield": ("US 10-year Treasury yield after inflation (TIPS). High real yields pull "
                   "money out of risky and emerging-market assets.",
                   "Risk-off point at 2.5% or higher. Risk-on point at 0.5% or lower."),
    "nfci": ("Chicago Fed index of US financial conditions (credit, leverage, risk). 0 is "
             "average; above 0 is tighter than average.",
             "Risk-off point above 0. Risk-on point at -0.5 or lower."),
    "net_liquidity_d13w": ("Fed balance sheet minus the Treasury's cash account and reverse "
                           "repo: dollars available to markets, % change over 13 weeks. Falling "
                           "means liquidity is draining.",
                           "Would be risk-off at -3% or less, risk-on at +3% or more."),
    "em_oas_d13w": ("Extra yield on emerging-market corporate bonds over Treasuries, as its "
                    "change over 13 weeks. Widening means stress in emerging markets.",
                    "Would be risk-off at +0.50pt or more, risk-on at -0.40pt or less."),
    "term_premium_d13w": ("Extra yield investors demand for holding a 10-year Treasury instead "
                          "of rolling short bills, as its change over 13 weeks. Rising means "
                          "bond investors want more compensation.",
                          "Would be risk-off at +0.40pt or more, risk-on at -0.40pt or less."),
    "stlfsi": ("St. Louis Fed index of US financial stress. 0 is average; above 0 is more "
               "stress than average.",
               "Would be risk-off above 0, risk-on at -0.5 or lower."),
}
CANDIDATE_NOTE = "Candidate: shown, never counted until it beats a placebo test."
HOME_EXPLAIN = {
    "jci_drawdown_20d": "How far the Jakarta Composite index is below its highest close of the "
                        "last 20 sessions. A fast fall is the clearest sign of stress at home.",
    "idx_foreign_z": "Foreign investors' net buying of IDX stocks over 20 days, compared with "
                     "the past 250 days (a z-score). Strongly negative means unusually heavy "
                     "foreign selling.",
    "usdidr_20d": "Change in the rupiah per US dollar (JISDOR) over 20 fixings. A rise means "
                  "the rupiah is weakening.",
    "sbn_non_resident_20d": "Change in foreign holdings of Indonesian government bonds (SBN) "
                            "over 20 days. A fall means foreigners are leaving the bond market.",
}

# sparkline geometry (SVG user units)
SP_W, SP_H, SP_PAD = 160, 34, 3

STYLE = """<style>
.regime { --spark:#2a78d6; --spark-zero:#c9c8c3; }
@media (prefers-color-scheme: dark) { .regime { --spark:#3987e5; --spark-zero:#55554f; } }
.regime svg.spark { display:block; width:160px; height:34px; }
.regime svg.spark .ln { fill:none; stroke:var(--spark); stroke-width:1.5;
  stroke-linejoin:round; stroke-linecap:round; }
.regime svg.spark .zero { stroke:var(--spark-zero); stroke-width:1; stroke-dasharray:2 2; }
.regime svg.spark .end { fill:var(--spark); }
.regime td.num { text-align:right; white-space:nowrap; }
.regime tr.candidate td { opacity:.75; }
.regime tr.changed td:first-child { font-weight:600; }
.regime .sub { display:block; color:var(--muted); font-size:11px; }
.regime .call { font-size:16px; margin:6px 0; }
.regime .tip { position:relative; cursor:help; border-bottom:1px dotted var(--muted);
  outline:none; }
.regime .tip:hover::after, .regime .tip:focus::after { content:attr(data-tip);
  position:absolute; left:0; top:calc(100% + 6px); z-index:5; width:min(340px, 80vw);
  padding:8px 10px; border-radius:6px; background:#1f1f1d; color:#f4f3ee; font-size:12px;
  font-weight:400; line-height:1.45; white-space:pre-line; text-align:left;
  box-shadow:0 2px 10px rgba(0,0,0,.25); }
</style>"""


# ---------------- reading ----------------


def load(app: web.App) -> tuple[dict | None, list[str]]:
    """(the regime file, problems). None when it is missing, unreadable, fails the schema or is
    a stub with `error`."""
    path = app.out_dir.joinpath(*FILE)
    if not path.exists():
        return None, [NO_FILE]
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return None, [f"layers/regime.json unreadable: {type(e).__name__}: {e}"]
    from assist import layers_out  # heavy (adapters); only when there is a file to check
    errors = sorted(layers_out.validator("regime").iter_errors(d), key=lambda e: list(e.path))
    if errors:
        where = "/".join(str(p) for p in errors[0].path) or "(root)"
        return None, [f"layers/regime.json fails the schema at {where}: {errors[0].message}"]
    if d.get("error"):
        return None, [f"layers/regime.json holds no layer data: {d['error']}"]
    return d, []


def history(app: web.App) -> tuple[list[dict], list[str]]:
    """The journal's regime records, newest first, each with `changed` against the record before
    it in time; (rows, problems)."""
    j = Journal(app.journal_path)
    rows = []
    try:
        for rec in j.read():
            if rec.get("kind") != "regime":
                continue
            out = rec.get("outputs") if isinstance(rec.get("outputs"), dict) else {}
            ins = rec.get("inputs") if isinstance(rec.get("inputs"), dict) else {}
            rows.append({"as_of": str(rec.get("as_of") or out.get("as_of") or "")[:10],
                         "state": out.get("state"), "dollar": out.get("dollar"),
                         "drivers": [str(x) for x in out.get("drivers") or []],
                         "stale_inputs": [str(x) for x in out.get("stale_inputs") or []],
                         "job": "daily check" if ins.get("job") == "regime" else "run",
                         "fingerprint": str(rec.get("fingerprint") or ""),
                         "seq": rec.get("seq"), "recorded_at": rec.get("recorded_at")})
    except (OSError, ValueError, TypeError, AttributeError) as e:
        return [], [f"journal unreadable: {type(e).__name__}: {e}"]
    rows.sort(key=lambda r: (r["as_of"], r["seq"] if isinstance(r["seq"], int) else -1))
    prev = None
    for r in rows:
        r["changed"] = prev is not None and (prev["state"], prev["dollar"]) != (
            r["state"], r["dollar"])
        prev = r
    return rows[::-1], []


def _day(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def stale_reason(inp: Mapping, d: Mapping) -> str | None:
    """Why an input is stale, or None."""
    if inp.get("value") is None or inp.get("direction") == "missing":
        return "no value"
    named = [s for s in d.get("stale_inputs") or []
             if inp["feature"] in s or inp["series_id"] in s]
    if named:
        return "; ".join(named)
    last, as_of = _day(inp.get("last")), _day(d.get("as_of"))
    if last and as_of and (as_of - last).days > STALE_DAYS:
        return f"newest point {last.isoformat()} is {(as_of - last).days} days before the run"
    return None


# ---------------- html ----------------


def _fmt(v: Any, kind: str) -> str:
    if v is None:
        return "n/a"
    v = float(v)
    if kind == "pct":
        return f"{v:+.2f}%"
    if kind == "diff":
        return f"{v:+.2f}pt"
    return f"{v:,.2f}" if abs(v) < 1e5 else f"{v:,.0f}"


def _tip(h: Mapping, kind: str) -> str:
    sv = h.get("series_value")
    level = "" if kind == "level" or sv is None else f" (series {_fmt(sv, 'level')})"
    return f"{h.get('date')}: {_fmt(h.get('value'), kind)}{level}"


def spark(inp: Mapping) -> str:
    """A 160x34 line of the input's weekly `value`; a null week breaks the line; a dashed zero
    line when the range crosses 0; the last point dotted. Escaped; empty text without points."""
    hist = [h for h in inp.get("history") or [] if isinstance(h, Mapping)]
    vals = [h.get("value") for h in hist]
    nums = [float(v) for v in vals if isinstance(v, (int, float))]
    if not nums:
        return '<span class="muted">no history</span>'
    kind = str(inp.get("kind"))
    lo, hi = min(nums), max(nums)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    n = len(hist)

    def x(i: int) -> float:
        return SP_PAD + i * (SP_W - 2 * SP_PAD) / max(n - 1, 1)

    def y(v: float) -> float:
        return SP_PAD + (hi - v) / (hi - lo) * (SP_H - 2 * SP_PAD)

    d, pen, end = [], "M", None
    for i, v in enumerate(vals):
        if not isinstance(v, (int, float)):
            pen = "M"
            continue
        d.append(f"{pen}{x(i):.1f},{y(float(v)):.1f}")
        pen, end = "L", i
    first, last = hist[0], hist[end]
    label = (f"{inp.get('feature')} weekly, {_tip(first, kind)} to {_tip(last, kind)}; "
             f"low {_fmt(min(nums), kind)}, high {_fmt(max(nums), kind)}")
    parts = [f'<svg class="spark" viewBox="0 0 {SP_W} {SP_H}" role="img" '
             f'aria-label="{esc(label)}"><title>{esc(label)}</title>']
    if lo < 0 < hi:
        parts.append(f'<line class="zero" x1="0" x2="{SP_W}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    if len(d) == 1:
        d.append(d[0].replace("M", "L"))
    parts.append(f'<path class="ln" d="{" ".join(d)}"/>')
    parts.append(f'<circle class="end" cx="{x(end):.1f}" cy="{y(float(vals[end])):.1f}" r="2"/>')
    parts.append("</svg>")
    return "".join(parts)


def explain(feature: str, counted: bool = True) -> str | None:
    """The hover text of a global layer-0 input, or None for one with no entry."""
    e = EXPLAIN.get(feature)
    if e is None:
        return None
    return "\n".join([*e, *([] if counted else [CANDIDATE_NOTE])])


def explain_home(feature: str, rule: Mapping) -> str | None:
    """The hover text of a home (IDN) input, with its thresholds read from the file's rule."""
    what = HOME_EXPLAIN.get(feature)
    if what is None:
        return None

    def steps(pairs: Any, fmt: str) -> str:
        return ", ".join(f"{p} point{'s' if p != 1 else ''} at {fmt.format(t)}"
                         for t, p in pairs)

    try:
        when = {
            "jci_drawdown_20d": steps(rule["jci_points"], "{:g}% below") + ".",
            "idx_foreign_z": f"1 point at {rule['flow_z_at']:g} or lower.",
            "usdidr_20d": steps(rule["usdidr_points"], "+{:g}%") + ".",
            "sbn_non_resident_20d": f"1 point at {rule['sbn_at']:g}% or lower.",
        }[feature]
        when += (f" Counts only if its newest value is at most {rule['max_age_days']} days "
                 f"old. Home risk-off at {rule['state_at']} points in total.")
    except (KeyError, TypeError, ValueError):
        return what
    return f"{what}\n{when}"


def _tipped(label: str, tip: str | None) -> str:
    """The label, with its explanation on hover, keyboard focus or tap when there is one."""
    if not tip:
        return esc(label)
    return (f'<span class="tip" tabindex="0" data-tip="{esc(tip)}" '
            f'aria-label="{esc(label + ". " + tip)}">{esc(label)}</span>')


def _card(cls: str, title: str, inner: str) -> str:
    return (f'<section class="card {cls}"><header><h2>{esc(title)}</h2></header>'
            f"{inner}</section>")


def _vote(inp: Mapping) -> str:
    v = inp.get("vote")
    text = "-" if v is None else (f"{v:+d}" if v else "0")
    if not inp.get("counted"):
        return f'{esc(text)} <span class="sub">candidate, not counted</span>'
    return f'{esc(text)} <span class="sub">counted</span>'


def _input_row(inp: Mapping, d: Mapping) -> str:
    kind = str(inp.get("kind"))
    stale = stale_reason(inp, d)
    stale_chip = (f' <span class="chip warn" title="{esc(stale)}">stale</span>' if stale else "")
    direction = str(inp.get("direction"))
    label = inp.get("label") or inp["feature"]
    cls = "" if inp.get("counted") else ' class="candidate"'
    return (f'<tr{cls} data-feature="{esc(str(inp["feature"]))}">'
            f'<td>{_tipped(str(label), explain(str(inp["feature"]), bool(inp.get("counted"))))}'
            f'<span class="sub"><code>{esc(str(inp["series_id"]))}</code> '
            f'{esc(str(inp["feature"]))} · {esc(kind)}</span></td>'
            f'<td class="num">{esc(_fmt(inp.get("value"), kind))}</td>'
            f'<td>{esc(str(inp.get("last") or "n/a"))}{stale_chip}</td>'
            f"<td>{web.chip(direction.replace('_', '-'), TONE.get(direction, 'muted'))}</td>"
            f"<td>{_vote(inp)}</td><td>{spark(inp)}</td></tr>")


def _call(d: Mapping) -> str:
    state, dollar = str(d["state"]), str(d["dollar"])
    pts, rule = d["points"], d["rule"]
    dollar_inp = next((i for i in d["inputs"] if i["feature"] == rule["dollar_input"]), None)
    dollar_why = ""
    if dollar_inp is not None:
        dollar_why = (f" ({esc(str(dollar_inp.get('label') or dollar_inp['feature']))}; up past "
                      f"+{esc(brief._num(rule['dollar_band_pct']))}%, down past "
                      f"-{esc(brief._num(rule['dollar_band_pct']))}% over "
                      f"{esc(str(rule['window_weeks']))} weeks)")
    adopted = ", ".join(str(a) for a in rule.get("adopted") or []) or "none"
    stale = d.get("stale_inputs") or []
    rows = [("Points", f"risk-off {esc(str(pts['off']))}, risk-on {esc(str(pts['on']))}, net "
                       f"{esc(str(pts['net']))} <span class=\"muted\">(risk-off at net &ge; "
                       f"{esc(str(rule['state_at']))}, risk-on at &le; "
                       f"-{esc(str(rule['state_at']))})</span>"),
            ("Drivers", esc("; ".join(str(x) for x in d.get("drivers") or [])) or "none"),
            ("Adopted candidates", esc(adopted)),
            ("Sources", esc(", ".join(str(x) for x in d.get("sources") or [])) or "none"),
            ("Stale inputs", esc("; ".join(str(x) for x in stale)) or "none"),
            ("Model", f"<code>{esc(brief._fingerprint(str(d['model_fingerprint'])))}</code>")]
    table = "<table>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</table>"
    return (f'<section class="card call-card"><header><h2>As of {esc(str(d["as_of"]))}</h2>'
            "</header>"
            f'<p class="call">Regime {web.chip(state.replace("_", "-"), TONE.get(state, "muted"))}'
            f" · Dollar {web.chip(dollar, DOLLAR_TONE.get(dollar, 'muted'))}"
            f'<span class="muted">{dollar_why}</span></p>{table}</section>')


def _inputs(d: Mapping) -> str:
    head = "<tr>" + "".join(f"<th>{h}</th>" for h in COLUMNS) + "</tr>"
    inputs = sorted(d["inputs"], key=lambda i: not i.get("counted"))  # counted first, stable
    rows = "".join(_input_row(i, d) for i in inputs)
    note = (f'<p class="muted">Diff and pct inputs are 13-week changes; the line is the input as '
            f"the rule sees it, each Friday over {esc(str(d['history_weeks']))} weeks (a gap is a "
            f"week without a point). Stale: no value, newest point more than {STALE_DAYS} days "
            "before the run, or named in the file's stale inputs. Candidates are shown, never "
            "counted. Hover, focus or tap an input's name for what it measures and when it "
            "votes.</p>")
    return _card("inputs", "Layer-0 inputs", f'<table class="inputs">{head}{rows}</table>{note}')


def _home_row(inp: Mapping, home: Mapping) -> str:
    feat = str(inp["feature"])
    kind = HOME_KIND.get(feat, "level")
    named = [x for x in home.get("stale_inputs") or [] if feat in x]
    stale = "; ".join(named) or ("not counted: no fresh value" if not inp.get("counted")
                                 else "")
    chip = f' <span class="chip warn" title="{esc(stale)}">stale</span>' if stale else ""
    pts = inp.get("points")
    pts_cell = ("-" + ' <span class="sub">not counted</span>' if pts is None
                else esc(str(pts)) + ' <span class="sub">counted</span>')
    return (f'<tr data-home-feature="{esc(feat)}">'
            f'<td>{_tipped(str(inp.get("label") or feat), explain_home(feat, _rule(home)))}'
            f'<span class="sub">{esc(feat)}</span></td>'
            f'<td class="num">{esc(_fmt(inp.get("value"), kind))}</td>'
            f'<td>{esc(str(inp.get("last") or "n/a"))}{chip}</td>'
            f"<td>{pts_cell}</td><td>{spark({**inp, 'kind': kind})}</td></tr>")


def _rule(home: Mapping) -> Mapping:
    r = home.get("rule")
    return r if isinstance(r, Mapping) else {}


def _home(d: Mapping) -> str:
    home = d.get("home")
    if not isinstance(home, Mapping):
        return _card("home-card", "Home regime (IDN)", f'<p class="muted">{esc(NO_HOME)}</p>')
    state, rule = str(home["state"]), home["rule"]
    jci = ", ".join(f"{p} at {t:g}%" for t, p in rule["jci_points"])
    usd = ", ".join(f"{p} at +{t:g}%" for t, p in rule["usdidr_points"])
    shift = (f"{rule['shift_pt']:+g}pt on IDN stocks and bonds"
             if rule["shift_adopted"] else
             f"{rule['shift_pt']:+g}pt not adopted (its walk-forward has not passed)")
    rows = [("Points", f"{esc(str(home['points']))} points <span class=\"muted\">(risk-off at "
                       f"&ge; {esc(str(rule['state_at']))}; there is no home risk-on)</span>"),
            ("Drivers", esc("; ".join(str(x) for x in home.get("drivers") or [])) or "none"),
            ("On risk-off", "IDN stocks and bonds adds and trims laddered"),
            ("Score shift", esc(shift)),
            ("Rule", esc(f"JCI vs 20-day high: {jci}; IDX foreign 20d z <= "
                         f"{rule['flow_z_at']:g}: 1; USD/IDR over 20 fixings: {usd}; "
                         f"non-resident SBN 20d <= {rule['sbn_at']:g}%: 1; an input counts "
                         f"only if at most {rule['max_age_days']} days old")),
            ("Stale inputs", esc("; ".join(str(x) for x in home.get("stale_inputs") or []))
             or "none")]
    table = "<table>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</table>"
    head = "<tr>" + "".join(f"<th>{h}</th>" for h in HOME_COLUMNS) + "</tr>"
    inputs = "".join(_home_row(i, home) for i in home.get("inputs") or [])
    note = (f'<p class="muted">Each line is the input as the home rule sees it, each Friday over '
            f"{esc(str(home['history_weeks']))} weeks.</p>")
    call = (f'<p class="call">Home regime '
            f'{web.chip(state.replace("_", "-"), TONE.get(state, "muted"))}</p>')
    return _card("home-card", "Home regime (IDN)",
                 f'{call}{table}<table class="inputs">{head}{inputs}</table>{note}')


def _history(rows: Sequence[Mapping]) -> str:
    if not rows:
        return _card("history", "Regime history",
                     '<p class="muted">no regime records in the journal yet</p>')
    head = "<tr>" + "".join(f"<th>{h}</th>" for h in HIST_COLUMNS) + "</tr>"
    body = []
    for r in rows:
        state, dollar = str(r["state"]), str(r["dollar"])
        mark = ' <span class="chip warn">changed</span>' if r["changed"] else ""
        body.append(
            f'<tr{" class=\"changed\"" if r["changed"] else ""}>'
            f"<td>{esc(r['as_of'])}{mark}</td>"
            f"<td>{web.chip(state.replace('_', '-'), TONE.get(state, 'muted'))}</td>"
            f"<td>{web.chip(dollar, DOLLAR_TONE.get(dollar, 'muted'))}</td>"
            f"<td>{esc(r['job'])}</td><td>{esc('; '.join(r['drivers'])) or '-'}</td>"
            f"<td><code>{esc(brief._fingerprint(r['fingerprint']))}</code></td></tr>")
    note = ('<p class="muted">Journal records of kind regime: one per weekly run, and one per '
            "daily check that set the baseline or saw a change. Newest first.</p>")
    return _card("history", "Regime history",
                 f'<table class="history">{head}{"".join(body)}</table>{note}')


def body(d: dict | None, hist: Sequence[Mapping], problems: Sequence[str]) -> str:
    parts = [STYLE, '<div class="regime"><h1>Regime</h1>',
             '<p class="muted">Layer 0: the global risk regime and the dollar call, from FRED '
             "via sec-edgar.</p>", *(web.notice(p) for p in problems)]
    if d is not None:
        parts += [_call(d), _inputs(d), _home(d)]
    parts += [_history(hist), "</div>"]
    return "".join(parts)


def page(app: web.App, _m: re.Match[str]) -> web.View:
    d, problems = load(app)
    hist, hist_problems = history(app)
    problems = [*problems, *hist_problems]
    data = {"regime": d, "history": hist, "problems": problems}
    return web.View(TITLE, body(d, hist, problems), data)
