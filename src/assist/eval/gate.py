"""The IDN rule gate (PLAN S48, P67): a historical verdict plus a live monitor, in place of
`pipeline.journalled_verdict`.

- **Historical verdict.** `placebo.evaluate` on the P66 point-in-time history (`assist.history`):
  enter (on) against hold / reduce (off), no_call skipped, horizon `HORIZON` = 3 month ends,
  stride 3, block 3, `MIN_N` = 10 per side (open questions 1 and 2). The window runs from the
  first month with a call (every required input) to the last month with a full forward return.
- **Live monitor.** The same test on the rule's journalled calls (`kind` rule records carrying
  this rule's fingerprint, dated from `since`, the day this rule's verdict was first written,
  to the day before the run; the last call in a month stands for it), priced on the JCI
  month-end closes (stocks) or the 10Y return proxy (bonds), as `journalled_verdict` did.
- **State.** `revoked` when the historical or journal verdict passed but the live monitor has at
  least `REVOKE_N` = 5 windows per side and a signed t of `REVOKE_T` = −1.0 or lower (open
  question 3); else `passed` (historical verdict passed); else `live-passed` (the journal alone
  passes at 10 per side); else `none` when there is no history for this rule fingerprint (a file
  whose fingerprint differs counts as no verdict); else `insufficient` (fewer than 10 windows on
  a side) or `failed`. The effective `Verdict` goes to the rule's `gated_stance` unchanged in
  shape; `none` hands it None.

The **rule fingerprint** (`rule_fingerprint`) hashes, docstrings and formatting aside
(`journal.code_digest`), the modules that make the rule's calls (the rule, regime, overrides,
signals, types, the history plumbing and, for stocks, the bonds module it reads and the
factor_series EY provider) and the gate's numbers. It keys `out/rules/IDN-<asset>.json`, which
holds the history rows, so `refresh` rebuilds:
- everything when the file is missing or its fingerprint differs (or `rebuild`);
- only the new month ends when a month end has passed since the file's last row;
- nothing otherwise. A normal weekly run reads the file, refreshes the forward returns from the
  run's own month-end prices and the live monitor, and rewrites it only if it changed.
A failed build never raises: the cached verdict of the same rule stands (named stale), or there
is no verdict.

Nothing here changes a rule constant. Heuristic, not investment advice.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import jsonschema

from assist import journal
from assist.eval import placebo
from assist.eval.placebo import MIN_N, Edge, Verdict, align, edge, evaluate, forward_returns
from assist.history import (
    HORIZON,
    START,
    HistoryRow,
    RuleHistory,
    bond_forward,
    last_month_end,
    month_ends,
    stock_forward,
)
from assist.layers.bonds.idn import bond_returns
from assist.layers.rules.idn_stocks import ERP_BAND
from assist.layers.types import DISCLAIMER, SCHEMA_DIR
from assist.sources.base import Row
from assist.sources.idxmethod import JCI

__all__ = [
    "ASSETS",
    "REVOKE_N",
    "REVOKE_T",
    "RULE_FILES",
    "STATES",
    "Gate",
    "diagnostic",
    "evaluate_gate",
    "live_build",
    "live_calls",
    "refresh",
    "rule_fingerprint",
    "validator",
]

SUBJECT = "IDN"
ASSETS = ("bonds", "stocks")
SCHEMA_VERSION = "1.0.0"
RULES_SCHEMA = SCHEMA_DIR / "rules.schema.json"
REVOKE_N = 5  # live windows per side before the monitor may revoke (open question 3)
REVOKE_T = -1.0  # signed t at or below this revokes
STATES = ("passed", "insufficient", "failed", "revoked", "live-passed", "none")
FINGERPRINT_RE = journal.FINGERPRINT_RE
VARIANTS = ("valuation-only",)

_COMMON = ("history.py", "layers/regime.py", "layers/overrides.py", "layers/signals.py",
           "layers/types.py")
RULE_FILES = {
    "bonds": (*_COMMON, "layers/bonds/__init__.py", "layers/bonds/idn.py"),
    "stocks": (*_COMMON, "layers/rules/__init__.py", "layers/rules/idn_stocks.py",
               "layers/bonds/idn.py", "sources/idxmethod_series.py"),
}

Month = tuple[int, int]


# ---------------- rule fingerprint ----------------


def gate_params(horizon: int = HORIZON) -> dict:
    return {"horizon": horizon, "stride": horizon, "block": horizon, "min_n": MIN_N,
            "revoke_n": REVOKE_N, "revoke_t": REVOKE_T, "t_min": placebo.T_MIN,
            "alpha": placebo.ALPHA, "seed": placebo.SEED, "start": START.isoformat()}


def rule_fingerprint(asset: str, *, root: Path | None = None) -> str:
    """sha256 of the asset's rule modules (AST, docstrings removed) and the gate's numbers."""
    base = Path(root) if root is not None else journal.PACKAGE_DIR
    files = {rel: journal.code_digest((base / rel).read_bytes(), rel)
             for rel in sorted(RULE_FILES[asset])}
    body = {"subject": SUBJECT, "asset": asset, "files": files, "params": gate_params(),
            "method": journal.RULES_METHOD}
    return journal.fingerprint(body)


# ---------------- live calls ----------------


def _month(d: date) -> Month:
    return d.year, d.month


def live_calls(records: Sequence[Mapping], asset: str, fingerprint: str, *, since: date,
               before: date) -> dict[Month, str]:
    """{(year, month): call} from journal `rule` records of this rule fingerprint dated
    `since` ≤ as_of < `before`; the last call in a month stands for it."""
    calls: dict[Month, str] = {}
    for rec in records:
        if (rec.get("kind") != "rule" or rec.get("subject") != SUBJECT
                or rec.get("asset") != asset or not rec.get("as_of")):
            continue
        out = rec.get("outputs") or {}
        if out.get("rule_fingerprint") != fingerprint:
            continue
        d = date.fromisoformat(rec["as_of"])
        if since <= d < before:
            calls[_month(d)] = out["call"]
    return calls


def _returns(asset: str, prices: Sequence[tuple[date, float]], horizon: int):
    return bond_returns(prices, horizon) if asset == "bonds" else forward_returns(prices, horizon)


def _live_series(asset: str, calls: Mapping[Month, str], prices: Sequence[tuple[date, float]],
                 horizon: int) -> tuple[list, list[float]]:
    feats = {d: None if calls[_month(d)] == "no_call" else calls[_month(d)] == "enter"
             for d, _ in prices if _month(d) in calls}
    _, f, r = align(feats, _returns(asset, prices, horizon))
    return f, r


def _identity(fs, _rs):
    return list(fs)


def _verdict(feats: Sequence, rets: Sequence[float], horizon: int) -> Verdict:
    return evaluate(_identity, list(feats), list(rets), stride=horizon, block=horizon)


# ---------------- the gate ----------------


def window(rows: Sequence[HistoryRow]) -> tuple[HistoryRow, ...]:
    """First month with a call → last month with a forward return (open question 1)."""
    first = next((i for i, r in enumerate(rows) if r.call != "no_call"), None)
    last = next((i for i in range(len(rows) - 1, -1, -1)
                 if rows[i].forward_return is not None), None)
    if first is None or last is None or last < first:
        return ()
    return tuple(rows[first:last + 1])


def _sample(rows: Sequence[HistoryRow]) -> tuple[list, list[float]]:
    rs = [r for r in rows if r.forward_return is not None]
    return ([None if r.call == "no_call" else r.call == "enter" for r in rs],
            [r.forward_return for r in rs])


def _counts(feats: Sequence, horizon: int) -> dict[str, int]:
    picked = list(feats)[::horizon]
    on = sum(1 for f in picked if f is True)
    off = sum(1 for f in picked if f is False)
    return {"on": on, "off": off, "no_call": len(picked) - on - off}


def _short(n: int, need: int) -> int:
    return max(0, need - n)


def _ym(d: date | None) -> str | None:
    return None if d is None else f"{d:%Y-%m}"


@dataclass(frozen=True)
class Gate:
    """One IDN rule's gate on `as_of`. `verdict` is what `gated_stance` gets (None = none)."""

    asset: str
    as_of: date
    fingerprint: str
    since: date
    state: str
    verdict: Verdict | None
    historical: Verdict | None
    live: Verdict
    live_edge: Edge
    rows: tuple[HistoryRow, ...] | None
    window: tuple[date, date] | None
    sample: Mapping[str, Mapping[str, int]]
    distance: Mapping[str, Mapping[str, int]]
    why: Mapping[str, str]
    no_call: tuple[dict, ...]
    horizon: int = HORIZON
    stale_inputs: tuple[str, ...] = ()

    def line(self) -> str:
        h, lv = self.sample.get("historical"), self.sample["live"]
        hist = ("no history for this rule" if h is None else
                f"historical on {h['on']}/{MIN_N}, off {h['off']}/{MIN_N}"
                + (f" ({_ym(self.window[0])} → {_ym(self.window[1])})" if self.window else ""))
        return (f"{self.state}: {hist}; live on {lv['on']}/{MIN_N}, off {lv['off']}/{MIN_N}"
                f" since {self.since}")

    def journal(self) -> dict:
        """What a `rule` journal record carries (its rule fingerprint feeds the live monitor)."""
        return {"state": self.state, "since": self.since.isoformat(),
                "sample": {k: dict(v) for k, v in self.sample.items()},
                "distance": {k: dict(v) for k, v in self.distance.items()}}

    def to_dict(self) -> dict:
        rows = self.rows or ()
        calls: dict[str, int] = {}
        for r in rows:
            calls[r.call] = calls.get(r.call, 0) + 1

        def vd(v: Verdict | None) -> dict | None:
            return None if v is None else v.to_dict()

        return journal.jsonable({
            "schema_version": SCHEMA_VERSION, "subject": SUBJECT, "asset": self.asset,
            "as_of": self.as_of.isoformat(), "rule_fingerprint": self.fingerprint,
            "since": self.since.isoformat(), "state": self.state, "line": self.line(),
            "verdict": vd(self.verdict), "params": gate_params(self.horizon),
            "covers": {"first": _ym(rows[0].as_of) if rows else None,
                       "last": _ym(rows[-1].as_of) if rows else None,
                       "months": len(rows),
                       "with_return": sum(r.forward_return is not None for r in rows),
                       "window_first": _ym(self.window[0]) if self.window else None,
                       "window_last": _ym(self.window[1]) if self.window else None},
            "calls": calls,
            "sample": {k: dict(v) for k, v in self.sample.items()},
            "distance": {k: dict(v) for k, v in self.distance.items()},
            "why": dict(self.why), "no_call": [dict(n) for n in self.no_call],
            "historical": vd(self.historical), "live": vd(self.live),
            "live_edge": dataclasses.asdict(self.live_edge),
            "stale_inputs": list(self.stale_inputs),
            "rows": None if self.rows is None else [r.to_dict() for r in self.rows],
            "disclaimer": DISCLAIMER,
        })


def _peak_erp(rows: Sequence[HistoryRow]) -> tuple[float, date] | None:
    pts = [(r.values.get("erp_vs_hurdle"), r.as_of) for r in rows if r.call != "no_call"]
    pts = [(v, d) for v, d in pts if v is not None]
    return max(pts) if pts else None


def _why(asset: str, rows: Sequence[HistoryRow] | None, win: Sequence[HistoryRow],
         counts: Mapping[str, int] | None, horizon: int) -> dict[str, str]:
    if rows is None or counts is None:
        return {"on": "no historical verdict for this rule fingerprint",
                "off": "no historical verdict for this rule fingerprint"}
    out = {}
    called = [r for r in rows if r.call != "no_call"]
    for side, names in (("on", ("enter",)), ("off", ("hold", "reduce"))):
        n = counts[side]
        if n >= MIN_N:
            out[side] = f"{side} side reaches {MIN_N} ({n} windows)"
            continue
        hits = [r for r in win if r.call in names]
        label = "/".join(names)
        if not hits:
            span = (f" ({_ym(called[0].as_of)} → {_ym(called[-1].as_of)})" if called else "")
            text = f"no {label} call in {len(called)} called month(s){span}"
        else:
            with_ret = sum(r.forward_return is not None for r in hits)
            text = (f"{len(hits)} {label} month(s) in the window, {with_ret} with a "
                    f"{horizon}-month return")
        text += (f"; {n} on the stride-{horizon} windows, {_short(n, MIN_N)} short of {MIN_N}"
                 f"; {counts['no_call']} window(s) fell on no_call months")
        if asset == "stocks" and side == "on" and (peak := _peak_erp(called)) is not None:
            v, d = peak
            text += (f"; implied ERP − hurdle peaks at {v:+.2f}pt ({_ym(d)}) vs ERP_BAND "
                     f"{ERP_BAND:.1f}")
            if v < ERP_BAND:
                text += ": valuation never reads cheap, so enter is unreachable on this history"
        out[side] = text
    return out


def _state(hist: Verdict | None, live: Verdict, live_edge: Edge) -> str:
    ok = (hist is not None and hist.passed) or live.passed
    if (ok and live_edge.n_on >= REVOKE_N and live_edge.n_off >= REVOKE_N
            and live_edge.t <= REVOKE_T):
        return "revoked"
    if hist is not None and hist.passed:
        return "passed"
    if live.passed:
        return "live-passed"
    if hist is None:
        return "none"
    return "insufficient" if not hist.rule.ok else "failed"


def evaluate_gate(asset: str, rows: Sequence[HistoryRow] | None, *, records: Sequence[Mapping],
                  prices: Sequence[tuple[date, float]], day: date, fingerprint: str,
                  since: date, horizon: int = HORIZON,
                  stale_inputs: Sequence[str] = ()) -> Gate:
    """The gate from the history rows (None: no history for this rule fingerprint), the
    journal and the month-end prices known on `day`."""
    rows = None if rows is None else tuple(rows)
    win = window(rows) if rows is not None else ()
    hist = hcounts = None
    if rows is not None:
        feats, rets = _sample(win)
        hist = _verdict(feats, rets, horizon)
        hcounts = _counts(feats, horizon)
    calls = live_calls(records, asset, fingerprint, since=since, before=day)
    lf, lr = _live_series(asset, calls, prices, horizon)
    live = _verdict(lf, lr, horizon)
    live_edge = edge(lf, lr, stride=horizon, min_n=REVOKE_N)
    lcounts = _counts(lf, horizon)
    state = _state(hist, live, live_edge)

    sample = {"live": lcounts}
    distance = {"live": {"on": _short(lcounts["on"], MIN_N), "off": _short(lcounts["off"], MIN_N)},
                "revoke": {"on": _short(lcounts["on"], REVOKE_N),
                           "off": _short(lcounts["off"], REVOKE_N)}}
    if hcounts is not None:
        sample["historical"] = hcounts
        distance["historical"] = {"on": _short(hcounts["on"], MIN_N),
                                  "off": _short(hcounts["off"], MIN_N)}
    span = (win[0].as_of, win[-1].as_of) if win else None
    g = Gate(asset, day, fingerprint, since, state, None, hist, live, live_edge, rows, span,
             sample, distance, _why(asset, rows, win, hcounts, horizon),
             tuple({"month": _ym(r.as_of), "missing": list(r.missing)}
                   for r in rows or () if r.call == "no_call"),
             horizon, tuple(dict.fromkeys(stale_inputs)))
    return dataclasses.replace(g, verdict=_effective(g))


def _effective(g: Gate) -> Verdict | None:
    hist, live, e = g.historical, g.live, g.live_edge
    if g.state == "none":
        return None
    if g.state == "passed":
        return dataclasses.replace(hist, reason=f"gate passed: historical {hist.reason}")
    if g.state == "live-passed":
        return dataclasses.replace(live, reason=f"gate live-passed: journal {live.reason}")
    if g.state == "revoked":
        base = hist if hist is not None and hist.passed else live
        return dataclasses.replace(base, passed=False, reason=(
            f"gate revoked: live t {e.t:.2f} <= {REVOKE_T} on {e.n_on} on / {e.n_off} off"
            f" since {g.since}"))
    if g.state == "insufficient":
        h = g.sample["historical"]
        return dataclasses.replace(hist, reason=(
            f"insufficient sample (historical on {h['on']}/{MIN_N}, off {h['off']}/{MIN_N})"))
    return dataclasses.replace(hist, reason=f"gate failed: historical {hist.reason}")


# ---------------- out/rules ----------------


def path_for(rules_dir: Path, asset: str) -> Path:
    return Path(rules_dir) / f"{SUBJECT}-{asset}.json"


@cache
def _schema() -> dict:
    return json.loads(RULES_SCHEMA.read_text(encoding="utf-8"))


def validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(
        _schema(), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


def _load(rules_dir: Path | None, asset: str) -> dict | None:
    if rules_dir is None:
        return None
    try:
        doc = json.loads(path_for(rules_dir, asset).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("rows"), list) else None


def _write(rules_dir: Path, g: Gate) -> Path:
    doc = g.to_dict()
    validator().validate(doc)
    text = json.dumps(doc, indent=1, ensure_ascii=False, allow_nan=False) + "\n"
    p = path_for(rules_dir, g.asset)
    if p.is_file() and p.read_text(encoding="utf-8") == text:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(p)
    return p


def _with_returns(asset: str, rows: Sequence[HistoryRow], prices: Sequence[tuple[date, float]],
                  horizon: int, day: date) -> tuple[HistoryRow, ...]:
    """The rows with their forward returns as the month-end `prices` give them on `day`; no
    prices (the store missing this run) keeps the rows' own."""
    if not prices:
        return tuple(rows)
    fwd = _forward(asset, prices, horizon, day)
    return tuple(dataclasses.replace(r, forward_return=fwd.get(_month(r.as_of))) for r in rows)


def _forward(asset: str, prices: Sequence[tuple[date, float]], horizon: int,
             day: date) -> dict[Month, float]:
    if asset == "bonds":
        return bond_forward(prices, horizon, day)
    return stock_forward([Row(JCI, d, v, None, "jci") for d, v in prices], horizon, day)


Build = Callable[[Sequence[date], date], Mapping[str, RuleHistory]]


def refresh(day: date, rules_dir: Path | None, *, records: Sequence[Mapping],
            prices: Mapping[str, Sequence[tuple[date, float]]], build: Build | None,
            fingerprints: Mapping[str, str] | None = None, rebuild: bool = False,
            horizon: int = HORIZON) -> dict[str, Gate]:
    """Both IDN rule gates on `day`, read from and written to `rules_dir` (None: in memory).
    `build(dates, day)` reruns both rules on month ends (`history.build`); it is called for
    every month end when a file is missing or its fingerprint differs (or `rebuild`), for the
    new month ends only when one has passed, and not at all otherwise. Never raises for a
    failed build."""
    fps = dict(fingerprints) if fingerprints else {a: rule_fingerprint(a) for a in ASSETS}
    dates = month_ends(START, last_month_end(day))
    docs = {a: _load(rules_dir, a) for a in ASSETS}
    cached: dict[str, tuple[HistoryRow, ...] | None] = {}
    since: dict[str, date] = {}
    why_missing: dict[str, str] = {}
    for a in ASSETS:
        doc = docs[a]
        if doc is not None and doc.get("rule_fingerprint") == fps[a]:
            cached[a] = tuple(HistoryRow.from_dict(r) for r in doc["rows"])
            since[a] = date.fromisoformat(doc["since"])
        else:
            cached[a] = None
            since[a] = day
            why_missing[a] = ("no out/rules file" if doc is None
                              else "out/rules file is for another rule fingerprint")
    full = rebuild or any(c is None for c in cached.values())
    if full:
        todo = list(dates)
    else:
        last = min((c[-1].as_of for c in cached.values() if c), default=None)
        todo = [d for d in dates if last is None or d > last]

    built, fail = None, None
    if todo:
        if build is None:
            fail = "no rule history builder"
        else:
            try:
                built = build(todo, day)
            except Exception as e:  # noqa: BLE001 - the run goes on with what is cached
                first = str(e).splitlines()[0][:200] if str(e) else ""
                fail = f"rebuild failed: {type(e).__name__}: {first}"

    gates = {}
    for a in ASSETS:
        stale: list[str] = []
        rows = cached[a]
        if built is not None:
            new = tuple(r for r in built[a].rows if r.as_of in set(todo))
            rows = new if full else (*(rows or ()), *new)
        elif rows is not None and todo:
            stale.append(f"rule history IDN {a}: covers to {_ym(rows[-1].as_of) if rows else '-'}"
                         f", newest month end {_ym(dates[-1])} ({fail})")
        elif rows is None:
            stale.append(f"rule history IDN {a}: no verdict for this rule ({why_missing[a]}; "
                         f"{fail})")
        if rows is not None:
            rows = _with_returns(a, rows, prices.get(a) or (), horizon, day)
        g = evaluate_gate(a, rows, records=records, prices=prices.get(a) or (), day=day,
                          fingerprint=fps[a], since=since[a], horizon=horizon,
                          stale_inputs=stale)
        if rules_dir is not None and rows is not None:
            _write(rules_dir, g)
        gates[a] = g
    return gates


def live_build(dates: Sequence[date], today: date) -> dict[str, RuleHistory]:
    """`history.build` on the real stores (read-only), with one progress line per month end on
    stderr."""
    from assist.history import HistorySources, build

    t0 = time.monotonic()
    print(f"rule history: rerunning both IDN rules on {len(dates)} month end(s)",
          file=sys.stderr, flush=True)
    out = build(HistorySources.default(), dates, today=today,
                progress=lambda d: print(f"  {d}", file=sys.stderr, flush=True))
    print(f"rule history: built in {time.monotonic() - t0:.0f} s", file=sys.stderr, flush=True)
    return out


# ---------------- diagnostics (never gate) ----------------

_VALUATION_INPUTS = ("10Y", "earnings yield", "CPI", "hurdle")


def _valuation_feat(r: HistoryRow) -> bool | None:
    v = r.values.get("erp_vs_hurdle")
    if v is None or any(m.split(":")[0] in _VALUATION_INPUTS for m in r.missing):
        return None
    return v >= ERP_BAND


def diagnostic(asset: str, rows: Sequence[HistoryRow], *, prices: Sequence[tuple[date, float]],
               day: date, horizon: int = HORIZON, variant: str | None = None) -> dict:
    """The verdict on another horizon or a variant of the calls (open question 5), as a
    diagnostic: it never gates a stance. `valuation-only` (stocks): on when implied ERP −
    hurdle ≥ ERP_BAND, off otherwise, wherever the valuation inputs exist."""
    if variant is not None and variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; known: {', '.join(VARIANTS)}")
    if variant == "valuation-only" and asset != "stocks":
        raise ValueError("valuation-only is a stocks variant")
    fwd = _forward(asset, prices, horizon, day) if prices else {}
    pts = []
    for r in rows:
        feat = (_valuation_feat(r) if variant == "valuation-only"
                else None if r.call == "no_call" else r.call == "enter")
        pts.append((r.as_of, feat, fwd.get(_month(r.as_of)) if prices else r.forward_return))
    first = next((i for i, p in enumerate(pts) if p[1] is not None), None)
    last = next((i for i in range(len(pts) - 1, -1, -1) if pts[i][2] is not None), None)
    win = pts[first:last + 1] if first is not None and last is not None and last >= first else []
    win = [p for p in win if p[2] is not None]
    feats, rets = [p[1] for p in win], [p[2] for p in win]
    v = _verdict(feats, rets, horizon)
    counts = _counts(feats, horizon)
    return {"gates": False, "subject": SUBJECT, "asset": asset, "as_of": day.isoformat(),
            "horizon": horizon, "variant": variant,
            "window": [_ym(win[0][0]), _ym(win[-1][0])] if win else None,
            "sample": counts,
            "distance": {"on": _short(counts["on"], MIN_N), "off": _short(counts["off"], MIN_N)},
            "verdict": journal.jsonable(v.to_dict()),
            "note": "diagnostic only (open question 5): never gates a stance",
            "disclaimer": DISCLAIMER}
