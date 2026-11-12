"""The paper and journal pages (/paper, /journal).

/paper: `app.paper(until=app.today())`, each model segment's allocation vs the IDR benchmark
(48% JCI / 32% SBN leg / 20% US stocks in IDR since S40; the legacy 60/40 beside it, for the
segments journalled before S39), worded as `brief.paper_lines`. Below
`paper.MIN_ANNUALISE_WEEKS` scored weeks the annualised cell reads "after 12 scored weeks" and the
JSON twin's `annualized_note` says so (S41). Each leg names its source. The
worst week is the minimum of `m.benchmark` over the report's scored benchmark marks, computed
here (the report has no such field). Stale reasons are
`report.stale_inputs` plus every distinct `mark.stale`. The paper callable reads sibling stores
(dbnomics' lock is mutual), so any exception is a notice and the page still renders. A report is
cached on the App per (day, journal mtime), so reloads and HEAD do not reopen the stores; an
error is not cached, so the next reload tries again.

/paper also shows the verdict flips (S91, `flips.count` on the journal's holding records):
per quarter, the names over the target of one flip, the method or data flips as bugs, and S87's
replay as the baseline.

/journal: as `assist journal` does: `verify()` gives the record count or raises ValueError
(chain BROKEN: reason), then `segments()` per model (records, stances, span of as_of). Neither
page writes the journal. The .json twins are the report without marks plus what this page
computed, and the chain check with one row per model.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from assist import brief, web
from assist.journal import Journal, jsonable
from assist.paper import annualized_note
from assist.web import esc

TITLE = "Assist Paper"
JOURNAL_TITLE = "Assist Journal"
NA = "n/a"
CACHE_KEY = "paper"
SEG_COLUMNS = ("Model", "Vs", "Span", "Until", "Decisions", "Weeks", "Stale weeks",
               "Portfolio", "Benchmark", "Active", "Hit rate", "")
LEG_ROWS = {"stocks": "Stocks leg", "bonds": "Bonds leg", "usa": "US stocks leg"}
MODEL_COLUMNS = ("Model", "Records", "Stances", "Span")
_LOCK = threading.Lock()  # one paper build at a time; the others wait for its cached report


@dataclass
class Built:
    key: tuple
    report: Any
    built_at: datetime


# ---------------- helpers (every one returns escaped HTML) ----------------


def _signed(x: Any) -> str:
    return esc(brief._signed(x))


def _vol(x: Any) -> str:
    return NA if x is None else f"{x * 100:.1f}%"


def _short(fp: Any) -> str:
    return f"<code>{esc(brief._fingerprint(str(fp)))}</code>"


def _card(cls: str, title: str, inner: str) -> str:
    return (f'<section class="card {cls}"><header><h2>{esc(title)}</h2></header>'
            f"{inner}</section>")


def _kv(rows: Sequence[tuple[str, str]]) -> str:
    return "<table>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</table>"


def _rows(head: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    return ("<table><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
            + "</table>")


def _list(items: Iterable[Any]) -> str:
    items = list(items)
    if not items:
        return '<p class="muted">none</p>'
    return "<ul>" + "".join(f"<li>{esc(str(x))}</li>" for x in items) + "</ul>"


def _span(first: Any, last: Any) -> str:
    return f"{esc(str(first))} … {esc(str(last))}"


# ---------------- /paper ----------------


def journal_mtime(app: web.App) -> int | None:
    try:
        return os.stat(Journal(app.journal_path).path).st_mtime_ns
    except OSError:
        return None


def report_for(app: web.App, day: date) -> tuple[Built | None, str | None]:
    """The cached report for (day, journal mtime), built on a miss; (None, error) on failure."""
    with _LOCK:
        key = (day, journal_mtime(app))
        hit = app.cache.get(CACHE_KEY)
        if hit is not None and hit.key == key:
            return hit, None
        try:
            rep = app.paper(day)
        except Exception as e:  # noqa: BLE001 - a locked or missing store is a notice, not a 500
            return None, f"{type(e).__name__}: {e}"
        built = Built(key, rep, datetime.now())
        app.cache[CACHE_KEY] = built
        return built, None


def worst_week(rep: Any) -> dict | None:
    """{week_end, benchmark} of the lowest scored benchmark week, or None if none is scored."""
    scored = [m for m in rep.benchmark if m.benchmark is not None]
    if not scored:
        return None
    m = min(scored, key=lambda m: m.benchmark)
    return {"week_end": m.week_end, "benchmark": m.benchmark}


def stale_reasons(rep: Any) -> list[str]:
    """report.stale_inputs, then each distinct mark.stale (benchmark marks, then segments')."""
    marks = [*rep.benchmark, *(m for s in rep.segments for m in (s.marks or []))]
    out: list[str] = []
    for x in [*rep.stale_inputs, *(x for m in marks for x in (m.stale or []))]:
        if x not in out:
            out.append(x)
    return out


def _annualised(summary: Mapping) -> str:
    """The annualised return, or "after N scored weeks" below paper.MIN_ANNUALISE_WEEKS."""
    note = annualized_note(summary)
    return esc(note.removeprefix("annualised ")) if note else _signed(summary["annualized"])


def _pct(pct: Any) -> str:
    return esc(brief._pct_text(pct or {}))


def _mix_name(pct: Any) -> str:
    return "/".join(format(v, "g") for v in (pct or {}).values()) or NA


def _summary(rep: Any) -> str:
    pct, bs = rep.benchmark_pct, rep.benchmark_summary
    ww = worst_week(rep)
    worst = NA if ww is None else (f"{_signed(ww['benchmark'])} "
                                   f"(week ending {esc(str(ww['week_end']))})")
    scored = [m for m in rep.benchmark if m.benchmark is not None]
    last = ""
    if scored:
        m = scored[-1]
        last = (f"<p>Last scored week ends {esc(str(m.week_end))}: benchmark "
                f"{_signed(m.benchmark)} ({esc(brief.mark_legs(m))}).</p>")
    head = (f"<p>Benchmark {_pct(pct)}, rebalanced weekly, from "
            f"{esc(str(rep.start or NA))} to {esc(str(rep.as_of))}.</p>")
    legs = [(f"{name} ({esc(format(pct[k], 'g'))}%)", esc(str(rep.legs.get(k, NA))))
            for k, name in LEG_ROWS.items() if k in pct]
    return _card("summary", f"IDR benchmark {_mix_name(pct)}", head + _kv([
        ("Weeks scored", esc(str(bs["weeks"]))), ("Stale weeks", esc(str(bs["stale_weeks"]))),
        ("Cumulative", _signed(bs["cumulative"])), ("Annualised", _annualised(bs)),
        ("Volatility", _vol(bs["volatility"])),
        ("Worst week", worst + (' <span class="muted">(computed here from the weekly marks)'
                                "</span>" if ww else "")),
        *legs,
        ("Bond series", esc(str(rep.bond_series)))]) + last
        + '<p class="muted">A stale week is counted, never filled in.</p>')


def _legacy(rep: Any) -> str:
    """The pre-S39 60/40 benchmark beside the current one (never chained)."""
    pct, ls = getattr(rep, "legacy_benchmark_pct", None), getattr(rep, "legacy_summary", None)
    if not pct or ls is None:
        return ""
    return _card("legacy", f"Legacy benchmark {_mix_name(pct)}", (
        f"<p>{_pct(pct)}, from {esc(str(getattr(rep, 'legacy_start', None) or NA))}: scores the "
        "model segments journalled before S39. Shown beside the current benchmark, never "
        "chained to it.</p>") + _kv([
            ("Weeks scored", esc(str(ls["weeks"]))),
            ("Stale weeks", esc(str(ls["stale_weeks"]))),
            ("Cumulative", _signed(ls["cumulative"])),
            ("Annualised", _annualised(ls))]))


def _seg_row(s: Any) -> list[str]:
    scored = bool(s.weeks)
    hit = NA if s.hit_rate is None else f"{s.hit_rate * 100:.0f}%"
    pct = getattr(s, "benchmark_pct", None)
    return [_short(s.fingerprint), esc(_mix_name(pct)) if pct else NA,
            _span(s.first_as_of, s.last_as_of),
            "current" if s.until is None else esc(str(s.until)), esc(str(s.decisions)),
            esc(str(s.weeks)), esc(str(s.stale_weeks)), _signed(s.portfolio_return),
            _signed(s.benchmark_return), _signed(s.active_return), esc(hit),
            "" if scored else '<span class="muted">nothing scored yet</span>']


def _segments(rep: Any) -> str:
    if not rep.segments:
        inner = '<p class="muted">No stance history in the journal yet: benchmark marks only.</p>'
    else:
        notes = [f"{brief._fingerprint(str(s.fingerprint))}: {n}" for s in rep.segments
                 for n in (s.notes or [])]
        inner = (_rows(SEG_COLUMNS, [_seg_row(s) for s in rep.segments])
                 + '<p class="muted">Each segment is scored on its own weeks only, against the '
                   'benchmark in its Vs column; "until" is the next model\'s first decision.</p>'
                 + (_list(notes) if notes else ""))
    return _card("segments", "Model segments", inner)


FLIP_COLUMNS = ("Quarter", "Names", "Flips", "Real", "Method or data", "Over target")
FLIP_NAME_COLUMNS = ("Market", "Name", "Quarter", "Flips", "Real", "Method or data")
BUG_COLUMNS = ("Market", "Name", "Date", "From", "To", "Cause")


def _flips(rep: Any) -> str:
    """S91: acted verdict flips per held name per quarter, names over the target, method or
    data flips flagged as bugs, and S87's replay as the baseline. Absent on an older report."""
    fl = getattr(rep, "flips", None)
    if not fl:
        return ""
    s, b = fl["summary"], fl["baseline"]
    base = (f'<p class="muted">Baseline (S87 replay, {esc(b["source"])}): raw '
            f'{esc(str(b["raw_per_name_quarter"]))} → acted '
            f'{esc(str(b["acted_per_name_quarter"]))} flips per name-quarter over '
            f'{b["name_quarters"]:,} name-quarters; {esc(str(b["acted_over_one"]))} acted '
            "name-quarters over 1.</p>")
    if not s["name_quarters"]:
        return _card("flips", "Verdict flips", '<p class="muted">No holding records with an '
                     "acted verdict in the journal yet (no holding records).</p>" + base)
    head = (f"<p>Acted verdict (sell / take-profit / hold) per held name, target at most "
            f"{esc(str(fl['target_per_quarter']))} flip per name per quarter: "
            f"{esc(str(s['name_quarters']))} name-quarter(s), {esc(str(s['flips']))} flip(s) "
            f"({esc(str(s['per_name_quarter']))} per name-quarter), {esc(str(s['real']))} "
            f"real, {esc(str(s['method_or_data']))} method or data.</p>")
    qs = _rows(FLIP_COLUMNS, [[esc(q), *(esc(str(v[k])) for k in (
        "names", "flips", "real", "method_or_data", "over_target"))]
        for q, v in fl["quarters"].items()])
    over = ("<h3>Names over target</h3>" + _rows(FLIP_NAME_COLUMNS, [
        [esc(n["market"]), esc(n["symbol"]), esc(n["quarter"]), esc(str(n["flips"])),
         esc(str(n["real"])), web.chip(str(n["method_or_data"]),
                                       "bad" if n["method_or_data"] else "good")]
        for n in fl["over_target"]]) if fl["over_target"]
        else '<p class="muted">No name over target.</p>')
    bugs = ("<h3>Method or data flips (each a bug)</h3>" + _rows(BUG_COLUMNS, [
        [esc(e["market"]), esc(e["symbol"]), esc(e["as_of"]), esc(e["from"]), esc(e["to"]),
         web.chip(e["cause"] or "no cause", "bad")] for e in fl["bugs"]]) if fl["bugs"]
        else '<p class="muted">No method or data flip.</p>')
    return _card("flips", "Verdict flips", head + qs + over + bugs + base)


def _data(rep: Any) -> Any:
    return rep.to_dict(marks=False) if hasattr(rep, "to_dict") else jsonable(rep)


def page(app: web.App, _m: re.Match[str]) -> web.View:
    day = app.today()
    built, error = report_for(app, day)
    head = ('<h1>Paper track</h1><p class="muted">Each model\'s allocation vs the IDR benchmark '
            "(48/32/20 since S39; the legacy 60/40 for the segments before it).</p>")
    if built is None:
        body = head + web.notice(f"paper track unavailable: {error}")
        return web.View(TITLE, body, {"as_of": day, "error": error, "report": None,
                                      "worst_week": None, "stale_reasons": [],
                                      "annualized_note": None})
    rep = built.report
    try:
        reasons = stale_reasons(rep)
        body = (head + _summary(rep) + _legacy(rep) + _segments(rep) + _flips(rep)
                + _card("stale", "Stale reasons", _list(reasons))
                + _card("notes", "Notes", _list(rep.notes))
                + f'<p class="muted">Report for {esc(str(day))}, built '
                  f"{built.built_at:%H:%M:%S}; cached until the day or the journal changes.</p>")
        data = {"as_of": day, "error": None, "report": _data(rep),
                "worst_week": worst_week(rep), "stale_reasons": reasons,
                "annualized_note": annualized_note(rep.benchmark_summary)}
    except (AttributeError, KeyError, TypeError) as e:  # not a PaperReport: a notice, not a 500
        error = f"unreadable paper report: {type(e).__name__}: {e}"
        body = head + web.notice(error)
        data = {"as_of": day, "error": error, "report": None, "worst_week": None,
                "stale_reasons": [], "annualized_note": None}
    return web.View(TITLE, body, data)


# ---------------- /journal ----------------


def _models(segs: Mapping[str, list[dict]]) -> list[dict]:
    out = []
    for fp, recs in segs.items():
        days = sorted({str(r["as_of"]) for r in recs if r.get("as_of")})
        out.append({"fingerprint": fp, "records": len(recs),
                    "stances": sum(1 for r in recs if r.get("kind") == "stance"),
                    "first_as_of": days[0] if days else None,
                    "last_as_of": days[-1] if days else None})
    return out


def _lines(j: Journal) -> int:
    try:
        return sum(1 for line in j.path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def journal(app: web.App, _m: re.Match[str]) -> web.View:
    j = Journal(app.journal_path)
    problems = []
    try:
        n, chain = j.verify(), "chain ok"
    except ValueError as e:
        n, chain = None, f"chain BROKEN: {e}"
    try:
        models = _models(j.segments())
    except (ValueError, KeyError, TypeError) as e:
        models = []
        problems.append(f"records per model unavailable: {type(e).__name__}: {e}")
    if n is None:
        n = _lines(j)
    ok = chain == "chain ok"
    body = "<h1>Journal</h1>"
    if not j.path.exists():
        body += web.notice(f"no journal yet at {j.path}: run `assist run`")
    body += "".join(web.notice(p) for p in problems)
    body += _card("chain", "Chain check",
                  f"<p>{web.chip(chain, 'good' if ok else 'bad')}</p>"
                  f"<p>{esc(str(j.path))}: {n} record(s), {len(models)} model(s)</p>")
    rows = [[_short(m["fingerprint"]), esc(str(m["records"])), esc(str(m["stances"])),
             "-" if m["first_as_of"] is None else _span(m["first_as_of"], m["last_as_of"])]
            for m in models]
    body += _card("models", "Records per model",
                  _rows(MODEL_COLUMNS, rows) if rows else '<p class="muted">none</p>')
    return web.View(JOURNAL_TITLE, body, {"path": j.path, "records": n, "chain": chain,
                                          "chain_ok": ok, "models": models,
                                          "problems": problems})
