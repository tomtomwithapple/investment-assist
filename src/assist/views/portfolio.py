"""The portfolio page (/portfolio, PLAN S36): layer 5 as `assist run` wrote it to
`app.out_dir/layers/portfolio.json` (S33), plus the trims and adds of every candidate list.

Sections: totals and dates; weights per asset class and per stance against its target (current,
target, delta split into rebalance to the benchmark and tilt (S42), entry, with stdlib SVG
bars); holdings per owner; every account (masked number, statement age, statement check, trade
roll-forward, cash) with its holding lines, `unheld` lines and the lines valued at a trade
price; unmapped value; trims and adds read from `out/candidates/*.json` through
`views.candidates.load`. The page never opens a store.

A missing file, invalid JSON, a non-object or a builder stub (`error`) is a notice, never a 500;
a payload the schema rejects is a notice and still renders. Every field is read with `.get`, so an
absent one shows "-". Account numbers stay masked: anything longer than the file's "…1234" form is
cut to its last 4 characters again. Every value read from a file goes through `esc`. The `.json`
twin is {portfolio, problem, candidates}.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from assist import web
from assist.stance import mandate_summary, split_text
from assist.views import candidates as cand
from assist.views.overview import TONE
from assist.web import esc

TITLE = "Assist Portfolio"
FILE = Path("layers") / "portfolio.json"
DASH = "-"
EMPTY = "no out/layers/portfolio.json yet: run `assist run`"
STALE_DAYS, OLD_DAYS = 40, 100  # statement age: warn above, bad above
BAR_W, BAR_H = 160, 12

STYLE = """<style>
.pf { --cur:#2a78d6; --tgt:#1d1d1b; --track:#ecebe7; }
@media (prefers-color-scheme: dark) { .pf { --cur:#5a9de8; --tgt:#ececea; --track:#2a2a27; } }
.pf td.num, .pf th.num { text-align:right; white-space:nowrap; }
.pf svg.bar { display:inline-block; vertical-align:middle; }
.pf svg.bar .track { fill:var(--track); }
.pf svg.bar .cur { fill:var(--cur); }
.pf svg.bar .tgt { stroke:var(--tgt); stroke-width:2; }
.pf .legend { display:flex; gap:16px; flex-wrap:wrap; color:var(--muted); font-size:12px;
  margin:6px 0 0; }
.pf .key { display:inline-block; width:14px; height:10px; vertical-align:middle;
  margin-right:5px; background:var(--cur); border-radius:2px; }
.pf .key.tgt { width:2px; height:12px; background:var(--tgt); border-radius:0; }
.pf details { margin:8px 0 0; }
.pf summary { cursor:pointer; color:var(--muted); }
.pf h3 { font-size:13px; margin:14px 0 0; }
.pf .accounts td:nth-child(-n+4) { white-space:nowrap; }
</style>"""


# ---------------- file ----------------


def load(out_dir: Path) -> tuple[dict | None, str | None]:
    """(payload, problem). A payload with a problem still renders (schema mismatch); None with a
    problem is a notice only."""
    path = Path(out_dir) / FILE
    if not path.is_file():
        return None, EMPTY
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{FILE} is not valid JSON ({e})"
    if not isinstance(p, dict):
        return None, f"{FILE} is not a JSON object"
    if p.get("error"):
        return None, f"layer 5 failed in the last run: {p['error']}"
    for key in ("accounts", "checks"):  # never show or serve more than the last 4 characters
        for row in p.get(key) if isinstance(p.get(key), list) else []:
            if isinstance(row, dict) and "account" in row:
                row["account"] = mask(row["account"])
    from assist import layers_out  # jsonschema; only when a file is found
    err = next(iter(layers_out.validator("portfolio").iter_errors(p)), None)
    # the path and the failed keyword only: the message would quote the value
    where = None if err is None else f"{err.json_path} ({err.validator})"
    return p, None if err is None else f"{FILE} does not match the schema at {where}"


# ---------------- formatting (every helper returns escaped HTML) ----------------


def _d(x: Any) -> Mapping:
    return x if isinstance(x, Mapping) else {}


def _l(x: Any) -> list[Mapping]:
    return [i for i in x if isinstance(i, Mapping)] if isinstance(x, list) else []


def _isnum(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def idr(x: Any) -> str:
    return f"{x:,.0f}" if _isnum(x) else DASH


def pct(x: Any) -> str:
    return f"{x:.2f}%" if _isnum(x) else DASH


def _t(x: Any) -> str:
    return DASH if x is None or x == "" else esc(str(x))


def mask(account: Any) -> str:
    """The account as the file has it ("…1234"), cut again to its last 4 if it is longer."""
    a = "" if account is None else str(account)
    return a if len(a) <= 5 else "…" + a[-4:]


def _acct(a: Mapping) -> str:
    m = mask(a.get("account"))
    return esc(f"{a.get('issuer', '')}{' ·' + m if m else ''}")


def _date(x: Any) -> date | None:
    try:
        return date.fromisoformat(str(x))
    except ValueError:
        return None


def age_days(run_day: Any, as_of: Any) -> int | None:
    a, b = _date(run_day), _date(as_of)
    return None if a is None or b is None else (a - b).days


def _age(days: int | None) -> str:
    if days is None:
        return DASH
    tone = "bad" if days > OLD_DAYS else "warn" if days > STALE_DAYS else None
    text = f"{days} d"
    return web.chip(text, tone) if tone else esc(text)


def _check(c: Mapping | None) -> str:
    if c is None:
        return '<span class="muted">no check</span>'
    m = c.get("matches")
    if m is True:
        return web.chip("matches", "good")
    if m is False:
        return (web.chip("differs", "bad")
                + f' <span class="muted">lines {idr(c.get("holdings_idr"))}'
                f" vs stated {idr(c.get('stated_idr'))}</span>")
    return web.chip("no stated total", "muted")


def bar(current: Any, target: Any, scale: float = 100.0) -> str:
    """An inline SVG bar: the current weight filled, the target as a tick; both on 0..scale."""
    def x(v: Any) -> float:
        return 0.0 if not _isnum(v) or scale <= 0 else max(0.0, min(1.0, v / scale)) * BAR_W
    tip = f"current {pct(current)}, target {pct(target)}"
    tick = "" if not _isnum(target) else (
        f'<line class="tgt" x1="{x(target):.1f}" x2="{x(target):.1f}" y1="0" y2="{BAR_H}"/>')
    return (f'<svg class="bar" width="{BAR_W}" height="{BAR_H}" viewBox="0 0 {BAR_W} {BAR_H}" '
            f'role="img" aria-label="{esc(tip)}"><title>{esc(tip)}</title>'
            f'<rect class="track" x="0" y="2" width="{BAR_W}" height="{BAR_H - 4}" rx="2"/>'
            f'<rect class="cur" x="0" y="2" width="{x(current):.1f}" height="{BAR_H - 4}" rx="2"/>'
            f"{tick}</svg>")


def _card(cls: str, title: str, inner: str) -> str:
    return (f'<section class="card {cls}"><header><h2>{esc(title)}</h2></header>'
            f"{inner}</section>")


def _table(head: Sequence[str], rows: Sequence[str], empty: str = "none") -> str:
    if not rows:
        return f'<p class="muted">{esc(empty)}</p>'
    ths = "".join(f'<th{" class=\"num\"" if h.endswith(("IDR", "%")) else ""}>{esc(h)}</th>'
                  for h in head)
    return f"<table><tr>{ths}</tr>{''.join(rows)}</table>"


def _num_td(s: str) -> str:
    return f'<td class="num">{s}</td>'


# ---------------- weights ----------------


def mandate(p: Mapping) -> dict:
    """The file's `mandate` block (S39), or the same sums worked out from its stance rows when
    the file predates it."""
    m = _d(p.get("mandate"))
    if _isnum(m.get("target_sum_pct")) and _isnum(m.get("cash_pct")):
        return {"benchmark_pct": dict(_d(m.get("benchmark_pct"))),
                "targets_pct": dict(_d(m.get("targets_pct"))),
                "target_sum_pct": m["target_sum_pct"], "cash_pct": m["cash_pct"]}
    rows = [s for s in _l(p.get("stances")) if "subject" in s and "asset" in s]
    return mandate_summary(rows)


def _mandate_note(p: Mapping) -> str:
    m = mandate(p)
    bm = {str(k): v for k, v in m["benchmark_pct"].items() if _isnum(v)}
    legs = " + ".join(f"{k.replace('/', ' ')} {pct(v)}" for k, v in sorted(m["targets_pct"].items())
                      if _isnum(v))
    bench = " / ".join(f"{k.replace('/', ' ')} {v:g}%" for k, v in sorted(bm.items()))
    return (f'<p class="muted mandate">Targets: {esc(legs or DASH)} = '
            f"<b>{esc(pct(m['target_sum_pct']))}</b> of the household; cash rest "
            f"<b>{esc(pct(m['cash_pct']))}</b>. Benchmark {esc(bench or DASH)}, each leg tilted "
            "±5 pt by its stance and scaled down pro rata if they pass 100%; every other stance "
            "is outside the 80/20 mandate and targets 0%.</p>")


def asset_classes(p: Mapping) -> list[dict]:
    """Per asset class: current % (layer 5 buckets) and target % (sum of the stances' targets;
    for cash, the cash rest the mandate leaves below 100%)."""
    out: dict[str, dict] = {}
    for b in _l(p.get("buckets")):
        a = out.setdefault(str(b.get("asset")), {"asset": str(b.get("asset")), "idr": 0.0,
                                                 "current_pct": 0.0, "target_pct": None})
        a["idr"] += b["idr"] if _isnum(b.get("idr")) else 0.0
        a["current_pct"] += b["pct"] if _isnum(b.get("pct")) else 0.0
    for s in _l(p.get("stances")):
        a = out.setdefault(str(s.get("asset")), {"asset": str(s.get("asset")), "idr": 0.0,
                                                 "current_pct": 0.0, "target_pct": None})
        if _isnum(s.get("target_pct")):
            a["target_pct"] = (a["target_pct"] or 0.0) + s["target_pct"]
    if _l(p.get("stances")) and "cash" not in {str(s.get("asset")) for s in _l(p.get("stances"))}:
        cash = out.setdefault("cash", {"asset": "cash", "idr": 0.0, "current_pct": 0.0,
                                       "target_pct": None})
        cash["target_pct"] = mandate(p)["cash_pct"]
    return sorted(out.values(), key=lambda a: (-a["current_pct"], a["asset"]))


def _active(s: Mapping) -> bool:
    cur, tgt = s.get("current_pct"), s.get("target_pct")
    return (_isnum(cur) and cur > 0) or (_isnum(tgt) and tgt > 0) or _d(
        s.get("entry")).get("style") not in (None, "none")


def _entry(e: Mapping) -> str:
    style = e.get("style")
    if style in (None, "none"):
        return '<span class="muted">none</span>'
    n, gap = e.get("tranches"), e.get("spacing_days")
    every = f", every {_t(gap)} d" if _isnum(gap) and gap else ""
    return f"{_t(style)} · {_t(n)} tranche{'' if n == 1 else 's'}{every}"


def _stance_rows(rows: Sequence[Mapping], scale: float) -> list[str]:
    return [
        f'<tr><td><a href="/stance/{esc(str(s.get("subject")))}/{esc(str(s.get("asset")))}">'
        f"{_t(s.get('subject'))} {_t(s.get('asset'))}</a></td>"
        f"<td>{web.chip(str(s.get('stance')), TONE.get(str(s.get('stance')), 'muted'))}</td>"
        + _num_td(_t(s.get("score"))) + _num_td(pct(s.get("current_pct")))
        + _num_td(pct(s.get("target_pct")))
        + f"<td>{bar(s.get('current_pct'), s.get('target_pct'), scale)}</td>"
        f"<td>{_delta(s)}</td><td>{_entry(_d(s.get('entry')))}</td></tr>"
        for s in rows]


def _delta(s: Mapping) -> str:
    """The delta, and under it the S42 split (rebalance to the benchmark vs the model's tilt)
    when the row carries it."""
    split = split_text(s) if s.get("rebalance_pt") or s.get("tilt_pt") else None
    return _t(s.get("delta")) + ("" if split is None
                                  else f'<br><span class="muted">{esc(split)}</span>')


def weights(p: Mapping) -> str:
    legend = ('<div class="legend"><span><span class="key"></span>current</span>'
              '<span><span class="key tgt"></span>target</span><span>bars on 0–100% of the '
              "household</span></div>")
    ac = [f"<tr><td>{_t(a['asset'])}</td>" + _num_td(idr(a["idr"]))
          + _num_td(pct(a["current_pct"])) + _num_td(pct(a["target_pct"]))
          + f"<td>{bar(a['current_pct'], a['target_pct'])}</td></tr>" for a in asset_classes(p)]
    buckets = [f"<tr><td>{_t(b.get('subject'))}</td><td>{_t(b.get('asset'))}</td>"
               + _num_td(idr(b.get("idr"))) + _num_td(pct(b.get("pct"))) + "</tr>"
               for b in _l(p.get("buckets"))]
    stances = sorted(_l(p.get("stances")), key=lambda s: (str(s.get("subject")),
                                                          str(s.get("asset"))))
    active = [s for s in stances if _active(s)]
    idle = [s for s in stances if not _active(s)]
    head = ("Stance", "Call", "Score", "Current %", "Target %", "", "Delta", "Entry")
    rest = "" if not idle else (
        f"<details><summary>{len(idle)} more at 0% with nothing to do</summary>"
        + _table(head, _stance_rows(idle, 100.0)) + "</details>")
    return _card("weights", "Weights against the stances' targets", (
        "<h3>Per asset class</h3>"
        + _table(("Asset class", "Value IDR", "Current %", "Target %", ""), ac, "no buckets")
        + _mandate_note(p) + legend + "<h3>Per subject (layer 5 buckets)</h3>"
        + _table(("Subject", "Asset", "Value IDR", "Weight %"), buckets, "no buckets")
        + f"<h3>Per stance ({len(active)} with a weight, a target or an entry)</h3>"
        + _table(head, _stance_rows(active, 100.0), "no stance holds or targets anything")
        + rest))


# ---------------- owners and accounts ----------------


def owners(p: Mapping) -> str:
    total = p.get("total_idr")
    rows = []
    for o in sorted(_l(p.get("by_owner")), key=lambda o: str(o.get("owner"))):
        t = o.get("total_idr")
        share = t / total * 100 if _isnum(t) and _isnum(total) and total else None
        parts = ", ".join(f"{b.get('subject', '')} {b.get('asset', '')} {idr(b.get('idr'))}"
                          for b in _l(o.get("buckets")))
        rows.append(f"<tr><td>{_t(o.get('owner'))}</td>" + _num_td(idr(t)) + _num_td(pct(share))
                    + f"<td>{esc(parts) or DASH}</td></tr>")
    return _card("owners", "By owner",
                 _table(("Owner", "Total IDR", "Share %", "Buckets (IDR)"), rows, "no owners"))


def _holding_rows(lines: Sequence[Mapping], total: Any, at_trade: set[str]) -> list[str]:
    out = []
    for h in lines:
        v = h.get("value")
        w = v / total * 100 if _isnum(v) and _isnum(total) and total else None
        sym = str(h.get("symbol", ""))
        mark = ' <span class="muted" title="valued at its last trade price">†</span>' \
            if sym in at_trade else ""
        bucket = h.get("bucket")
        out.append(f"<tr><td>{_t(sym)}{mark}</td><td>{_t(h.get('name'))}</td>"
                   + _num_td(_t(h.get("quantity"))) + _num_td(idr(v)) + _num_td(pct(w))
                   + f"<td>{_t(bucket) if bucket else web.chip('unmapped', 'warn')}</td></tr>")
    return out


def accounts(p: Mapping) -> str:
    run_day, total = p.get("as_of"), p.get("total_idr")
    checks = {(str(c.get("issuer")), mask(c.get("account"))): c for c in _l(p.get("checks"))}
    accts = _l(p.get("accounts"))
    by_owner: dict[str, list[Mapping]] = {}
    for a in accts:
        by_owner.setdefault(str(a.get("owner")), []).append(a)
    head = ("Account", "Type", "As of", "Age", "Rolled forward", "Cash IDR", "Holdings IDR",
            "Stated IDR", "Broker cash IDR", "Check")
    parts = []
    for owner in sorted(by_owner):
        rows, lines = [], []
        for a in sorted(by_owner[owner], key=lambda a: (str(a.get("issuer")),
                                                          mask(a.get("account")))):
            n = a.get("trade_docs")
            rolled = '<span class="muted">no</span>' if not a.get("rolled_from") and not n else (
                f"from {_t(a.get('rolled_from') or 'nothing')} through {_t(n)} trade "
                f"doc{'' if n == 1 else 's'}")
            check = checks.get((str(a.get("issuer")), mask(a.get("account"))))
            rows.append(
                f"<tr><td>{_acct(a)}</td><td>{_t(a.get('doc_type'))}</td><td>{_t(a.get('as_of'))}"
                f"</td><td>{_age(age_days(run_day, a.get('as_of')))}</td><td>{rolled}</td>"
                + _num_td(idr(a.get("cash_idr"))) + _num_td(idr(a.get("holdings_idr")))
                + _num_td(idr(a.get("stated_value_idr"))) + _num_td(idr(a.get("broker_cash_idr")))
                + f"<td>{_check(check)}</td></tr>")
            held, unheld = _l(a.get("holdings")), _l(a.get("unheld"))
            if not held and not unheld:
                continue
            at_trade = {str(s) for s in a.get("priced_at_trade") or []}
            note = "" if not at_trade else (
                f'<p class="muted">† {len(at_trade)} line{"" if len(at_trade) == 1 else "s"} '
                "valued at the last trade price (no statement price yet).</p>")
            hl = _table(("Symbol", "Name", "Quantity", "Value IDR", "Weight %", "Bucket"),
                        _holding_rows(held, total, at_trade), "no lines held")
            ul = "" if not unheld else (
                web.notice(f"{len(unheld)} line{'' if len(unheld) == 1 else 's'} sold below "
                           "zero (unheld): more sold than the statement and trades show held; "
                           "kept out of the totals")
                + _table(("Symbol", "Name", "Quantity", "Value IDR", "Weight %", "Bucket"),
                         _holding_rows(unheld, total, set())))
            extra = f", {len(unheld)} unheld" if unheld else ""
            lines.append(f"<details{' open' if unheld else ''}><summary>{_acct(a)}: "
                         f"{len(held)} line{'' if len(held) == 1 else 's'}, IDR "
                         f"{idr(a.get('holdings_idr'))}{extra}</summary>{note}{hl}{ul}</details>")
        parts.append(f"<h3>{esc(owner)}</h3>" + _table(head, rows) + "".join(lines))
    age = (f'<p class="muted">Age is days from the run ({_t(run_day)}) back to the statement or '
           f"last trade document; over {STALE_DAYS} days is flagged.</p>")
    return _card("accounts", "Accounts and holdings",
                 (age + "".join(parts)) if parts else '<p class="muted">no accounts</p>')


def unmapped(p: Mapping) -> str:
    rows = [f"<tr><td>{_t(u.get('label'))}</td>" + _num_td(idr(u.get("idr"))) + "</tr>"
            for u in _l(p.get("unmapped"))]
    head = f'<p>Unmapped value: <strong>IDR {idr(p.get("unmapped_idr"))}</strong> ' \
           '<span class="muted">(lines no rule maps to a bucket; never in the weights)</span></p>'
    return _card("unmapped", "Unmapped", head + _table(("Line", "IDR"), rows, "no unmapped lines"))


# ---------------- trims and adds ----------------


def trades(markets: Sequence[cand.Market]) -> tuple[str, list[dict]]:
    data, parts = [], []
    for m in markets:
        p = m.payload or {}
        sz = _d(p.get("sizing"))
        trims = [{"symbol": t.get("symbol"), "idr": t.get("idr"), "reason": t.get("reason")}
                 for t in _l(sz.get("trims"))]
        adds = []
        for style in _l(p.get("styles")):
            for r in _l(style.get("rows")):
                size = _d(r.get("size"))
                if r.get("action") == "add" and size:
                    adds.append({"symbol": r.get("symbol"), "name": r.get("name"),
                                 "style": style.get("style"), "idr": size.get("idr"),
                                 "tranches": len(_l(size.get("tranches"))),
                                 "reason": size.get("reason")})
        data.append({"market": m.key, "problem": m.problem, "trims": trims, "adds": adds,
                     "budget_idr": sz.get("budget_idr"), "unspent_idr": sz.get("unspent_idr")})
        tr = [f"<tr><td>{_t(t['symbol'])}</td>" + _num_td(idr(t["idr"]))
              + f"<td>{_t(t['reason'])}</td></tr>" for t in trims]
        ad = [f"<tr><td>{_t(a['symbol'])}{' ' + _t(a['name']) if a['name'] else ''}</td>"
              f"<td>{_t(a['style'])}</td>" + _num_td(idr(a["idr"])) + _num_td(_t(a["tranches"]))
              + f"<td>{_t(a['reason'])}</td></tr>" for a in adds]
        problem = web.notice(f"{m.file}: {m.problem}") if m.problem else ""
        parts.append(
            f'<h3><a href="/candidates/{esc(m.key)}">{esc(m.key)}</a></h3>{problem}'
            f'<p class="muted">Budget IDR {idr(sz.get("budget_idr"))}, unspent IDR '
            f"{idr(sz.get('unspent_idr'))}.</p>"
            + "<p><strong>Trims</strong></p>"
            + _table(("Name", "Amount IDR", "Reason"), tr, "no trims")
            + "<p><strong>Adds</strong></p>"
            + _table(("Name", "Style", "Amount IDR", "Tranches", "Reason"), ad, "no adds"))
    if not parts:
        return _card("trades", "Trims and adds", f'<p class="muted">{esc(cand.EMPTY)}</p>'), data
    return _card("trades", "Trims and adds from the candidate lists", "".join(parts)), data


# ---------------- page ----------------


def _summary(p: Mapping) -> str:
    fp = p.get("model_fingerprint")
    rows = [("Total", f"IDR {idr(p.get('total_idr'))}"),
            ("Run", _t(p.get("as_of"))),
            ("Newest statement or trade", _t(p.get("statement_as_of"))),
            ("Broker cash (not in the weights)", f"IDR {idr(p.get('broker_cash_idr'))}"),
            ("Unmapped", f"IDR {idr(p.get('unmapped_idr'))}"),
            ("Model", f"<code>{esc(fp[:19])}</code>" if isinstance(fp, str) else DASH)]
    notes = [str(n) for n in p.get("notes") or []]
    if notes:
        rows.append(("Notes", "<br>".join(esc(n) for n in notes)))
    return _card("summary", "Summary", "<table>" + "".join(
        f"<tr><th>{esc(k)}</th><td>{v}</td></tr>" for k, v in rows) + "</table>"
        '<p class="muted">Money moving between the accounts: <a href="/flows">/flows</a>.</p>')


def body(p: Mapping | None, problem: str | None, trades_html: str) -> str:
    head = "<h1>Portfolio</h1>"
    if p is None:
        return f'{STYLE}<div class="pf">{head}{web.notice(problem or EMPTY)}{trades_html}</div>'
    stale = "".join(web.notice(f"stale input: {s}") for s in p.get("stale_inputs") or [])
    return "".join([
        STYLE, '<div class="pf">', head,
        web.notice(problem) if problem else "", stale,
        _summary(p), weights(p), owners(p), accounts(p), unmapped(p), trades_html,
        _card("sources", "Sources", esc(", ".join(str(s) for s in p.get("sources") or []))
              or DASH),
        f'<p class="muted">{_t(p.get("disclaimer"))}</p>' if p.get("disclaimer") else "",
        "</div>"])


def page(app: web.App, _m: re.Match[str]) -> web.View:
    p, problem = load(app.out_dir)
    trades_html, trades_data = trades(cand.load(app.out_dir))
    data = {"portfolio": p, "problem": problem, "candidates": trades_data}
    return web.View(TITLE, body(p, problem, trades_html), data)
