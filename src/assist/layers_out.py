"""Layer files (PLAN S33): each layer's structured result in `out/layers/`, for the UI pages.

The stance JSONs carry only the final fields and text drivers, and the UI never reads a store,
so `assist run` also writes what layers 0, 2, 3 and 5 computed:

- `regime.json`: the layer-0 call (state, dollar, drivers, risk-off and risk-on points) and
  every input of `assist.layers.regime` (counted rules and the not-adopted candidates): value,
  newest date, its vote as `classify` counts it, and a 1-year weekly line (each Friday: the
  series' last point on or before it, and the input as `regime.inputs` computes it that day,
  both from the run day's vintage). Since schema 1.1.0 (S53, P72) it also carries `home`, the
  home (IDN) regime (P71's rule on P70's inputs): state, points, the rule's numbers, and each of
  the four inputs with its points, value, newest date and a 1-year weekly line (each Friday: the
  input as `home_inputs` computes it that day). No home regime this run, no `home` block.
- `<SUBJECT>.json` for every subject the run builds layer-2 overrides for (IDN, and the
  foreign markets of P28: USA, JPN, EMU, AUS, SGP): the components, each asset's capped shift
  and uncapped raw sum, and for IDN the layer-3 signals and the chart windows (IDX net foreign
  IDR and USD over 60 IDX days, JISDOR over 60 rate days with BI's carried-forward days flagged
  and IDX days without a rate listed as gaps, JCI daily over a year, the IGSYC curve on its
  newest day and about 4 weeks before, non-resident SBN holdings over a year).
- `portfolio.json`: layer 5 (buckets, owners, each account's rolled statement with account
  numbers masked to their last 4 characters, unmapped lines, statement checks, notes) and each
  stance's current/target/delta and entry.

Everything here serialises objects the run already built; the only new reads are the chart
windows and the layer-0 history, through the same adapters, read-only. Every file carries
`as_of`, `schema_version`, `model_fingerprint`, `sources`, `stale_inputs` and the disclaimer,
and is checked against `schema/layers/`. Nothing here raises into the run: a failing read is a
stale input in its file, a failing builder (or a payload the schema rejects) writes a stub with
`error`. A rerun on the same day writes the same bytes.
"""

from __future__ import annotations

import json
import math
import os
import sys
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

from assist.layers import home_inputs as hi
from assist.layers import home_regime
from assist.layers import overrides as idn_ov
from assist.layers import overrides_foreign as fo
from assist.layers import regime as rg
from assist.layers.portfolio import Portfolio, classify
from assist.layers.types import DISCLAIMER, MAX_OVERRIDE, SCHEMA_DIR
from assist.sources.base import Row, SourceUnavailable
from assist.sources.idxmethod import jci
from assist.sources.idxscape import (
    IDX_NET_FOREIGN_IDR,
    IDX_NET_FOREIGN_USD,
    JISDOR,
    SBN_NON_RESIDENT,
)
from assist.sources.usfin import net_liquidity
from assist.stance import HOME_SHIFT_PT, mandate_summary

__all__ = ["DIR", "SCHEMA_VERSION", "SCHEMA_VERSIONS", "home_block", "home_history",
           "portfolio_payload", "regime_payload", "subject_payload",
           "idn_charts", "validator", "write_layers"]

SCHEMA_VERSION = "1.0.0"  # the subject and portfolio files
# Per kind; regime 1.1.0 adds the optional `home` block (S53).
SCHEMA_VERSIONS = {"regime": "1.1.0", "subject": SCHEMA_VERSION, "portfolio": SCHEMA_VERSION}
DIR = "layers"
KINDS = ("regime", "subject", "portfolio")
HISTORY_WEEKS = 52  # layer-0 sparkline
HISTORY_MAX_GAP = timedelta(days=14)  # a weekly point older than this is no point
FLOW_DAYS = 60  # IDX days of net foreign flow
FLOW_READ_BACK = timedelta(days=150)  # covers 60 IDX days plus Lebaran
JISDOR_DAYS = 60  # JISDOR rate days
YEAR = timedelta(days=365)  # JCI and non-resident SBN
CURVE_BACK = timedelta(weeks=4)  # the earlier IGSYC curve


# ---------------- helpers ----------------


def _num(v: Any) -> float | int | None:
    """A JSON number (None for a missing or non-finite value); ints stay ints."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    f = float(v)
    if not math.isfinite(f):
        return None
    return round(f, 6)


def _iso(d: date | None) -> str | None:
    return None if d is None else d.isoformat()


def _uniq(items) -> list[str]:
    return list(dict.fromkeys(str(i) for i in items if i))


def _failure(what: str, e: Exception) -> str:
    if isinstance(e, SourceUnavailable):
        return f"{what}: {e.stale_input}"
    first = str(e).splitlines()[0][:160] if str(e) else ""
    return f"{what} failed: {type(e).__name__}: {first}"


def _head(kind: str, as_of: date, fingerprint: str) -> dict:
    return {"schema_version": SCHEMA_VERSIONS[kind], "kind": kind, "as_of": as_of.isoformat(),
            "model_fingerprint": fingerprint}


def _tail(payload: dict, stale: Sequence[str], sources: Sequence[str]) -> dict:
    payload["stale_inputs"] = _uniq(stale)
    payload["sources"] = _uniq(sources)
    payload["disclaimer"] = DISCLAIMER
    return payload


def _mask(account: str) -> str:
    """An account number cut to its last 4 characters ("…1234"), the issuer stays readable."""
    return account if len(account) <= 4 else "…" + account[-4:]


# ---------------- schemas ----------------


@cache
def _schema(kind: str) -> dict:
    return json.loads((SCHEMA_DIR / DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))


def validator(kind: str) -> jsonschema.Draft202012Validator:
    """The `schema/layers/{kind}.schema.json` validator (kind: regime, subject, portfolio)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    return jsonschema.Draft202012Validator(
        _schema(kind), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


# ---------------- layer 0 ----------------


def _vote(feature: str, value: float | None) -> tuple[int | None, str]:
    """(points, direction) of one input as `regime.classify` scores it: risk-off points
    (1 or 2), -1 for a risk-on point, 0 inside both bands; (None, "missing") without a value."""
    if value is None:
        return None, "missing"
    _sid, _kind, is_off, is_on, _fmt = rg.ALL_FEATURES[feature]
    pts = int(is_off(value))
    if pts:
        return pts, "risk_off"
    if is_on(value):
        return -1, "risk_on"
    return 0, "neutral"


def _weekly(rows: Sequence[Row], day: date) -> dict[str, list[dict]]:
    """{feature: [{date, series_value, value}]} on each Friday of the last `HISTORY_WEEKS`."""
    rows = [r for r in rows if r.value is not None and r.date <= day]
    rows += net_liquidity([r for r in rows if r.series_id in rg.NET_LIQUIDITY_INPUTS])
    by_id: dict[str, list[Row]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: (r.series_id, r.date)):
        by_id[r.series_id].append(r)
    days_by_id = {k: [r.date for r in v] for k, v in by_id.items()}
    fridays = rg.weekly(day - timedelta(weeks=HISTORY_WEEKS) + timedelta(days=1), day)
    out: dict[str, list[dict]] = {f: [] for f in rg.ALL_FEATURES}
    # net liquidity once, not per Friday: each point uses only data dated on or before it
    weekly_rows = [r for r in rows if r.series_id not in rg.NET_LIQUIDITY_INPUTS]
    for friday in fridays:
        values = rg.inputs(weekly_rows, friday).values
        for feat, (sid, *_rest) in rg.ALL_FEATURES.items():
            i = bisect_right(days_by_id.get(sid, []), friday)
            pt = by_id[sid][i - 1] if i else None
            level = pt.value if pt is not None and friday - pt.date <= HISTORY_MAX_GAP else None
            if level is None and values.get(feat) is None:
                continue
            out[feat].append({"date": friday.isoformat(), "series_value": _num(level),
                              "value": _num(values.get(feat))})
    return out


def regime_history(day: date, fred: Any) -> tuple[dict[str, list[dict]], list[str]]:
    """The 1-year weekly line of every layer-0 input, read as known on `day`."""
    if fred is None:
        return {f: [] for f in rg.ALL_FEATURES}, []
    try:
        rows = fred.rows([*rg.CORE, *rg.CANDIDATE_SERIES],
                         start=day - timedelta(weeks=HISTORY_WEEKS) - rg.READ_BACK, end=day,
                         as_of=day)
    except Exception as e:  # noqa: BLE001 - a sparkline never fails the run
        return {f: [] for f in rg.ALL_FEATURES}, [_failure("regime history", e)]
    return _weekly(rows, day), []


def regime_payload(day: date, fingerprint: str, regime: Any, inputs: Any = None,
                   history: Mapping[str, list[dict]] | None = None,
                   history_stale: Sequence[str] = ()) -> dict:
    """`regime.json`: the call, the points, and every input with its vote and weekly line."""
    adopted = {rg.CANDIDATE_FEATURE[c] for c in rg.ADOPTED}
    values = inputs.values if inputs is not None else {}
    last = inputs.last if inputs is not None else {}
    rows, off, on = [], 0, 0
    for feat, (sid, kind, *_r, fmt) in rg.ALL_FEATURES.items():
        value = values.get(feat)
        points, direction = _vote(feat, value)
        counted = feat in rg.RULES or feat in adopted
        if counted and points is not None:
            off += max(points, 0)
            on += 1 if points < 0 else 0
        rows.append({"feature": feat, "series_id": sid, "kind": kind, "counted": counted,
                     "label": fmt.format(value) if value is not None else None,
                     "value": _num(value), "last": _iso(last.get(feat)), "vote": points,
                     "direction": direction, "history": list((history or {}).get(feat, []))})
    p = _head("regime", day, fingerprint)
    p.update({"state": regime.state, "dollar": regime.dollar, "drivers": list(regime.drivers),
              "points": {"off": off, "on": on, "net": off - on},
              "rule": {"state_at": rg.STATE_AT, "dollar_band_pct": rg.DOLLAR_BAND,
                       "dollar_input": "usd_d13w", "window_weeks": rg.WINDOW.days // 7,
                       "adopted": list(rg.ADOPTED)},
              "history_weeks": HISTORY_WEEKS, "inputs": rows})
    stale = [*regime.stale_inputs, *(inputs.stale_inputs if inputs is not None else ()),
             *history_stale]
    return _tail(p, stale, regime.sources)


def home_history(day: date, sources: Any) -> tuple[dict[str, list[dict]], list[str]]:
    """The 1-year weekly line of each home input ({feature: [{date, value}]}), each Friday's
    value as `home_inputs` computes it that day. Never raises: a failure is one stale line."""
    empty = {f: [] for f in hi.FEATURES}
    if sources is None:
        return empty, []
    fridays = rg.weekly(day - timedelta(weeks=HISTORY_WEEKS) + timedelta(days=1), day)
    try:
        by_day = home_regime.history(fridays, sources)
    except Exception as e:  # noqa: BLE001 - a sparkline never fails the run
        return empty, [_failure("home history", e)]
    out: dict[str, list[dict]] = {f: [] for f in hi.FEATURES}
    for friday in sorted(by_day):
        values = by_day[friday].values
        for feat in hi.FEATURES:
            v = _num(values.get(feat))
            if v is not None:
                out[feat].append({"date": friday.isoformat(), "value": v})
    return out, []


def home_block(home: Any, history: Mapping[str, list[dict]] | None = None) -> dict:
    """`regime.json` `home`: the home regime, its rule's numbers and each input's line."""
    rows = []
    for feat in hi.FEATURES:
        value = home.values.get(feat)
        pts = home.by_input.get(feat)
        rows.append({"feature": feat, "counted": pts is not None, "points": pts,
                     "label": home_regime.FORMAT[feat].format(value) if value is not None
                     else None,
                     "value": _num(value), "last": _iso(home.last.get(feat)),
                     "history": list((history or {}).get(feat, []))})
    return {"as_of": home.as_of.isoformat(), "state": home.state, "points": home.points,
            "drivers": list(home.drivers), "stale_inputs": list(home.stale_inputs),
            "rule": {"state_at": home_regime.STATE_AT,
                     "jci_points": [list(x) for x in home_regime.JCI_POINTS],
                     "flow_z_at": home_regime.FLOW_Z_AT,
                     "usdidr_points": [list(x) for x in home_regime.USDIDR_POINTS],
                     "sbn_at": home_regime.SBN_AT,
                     "max_age_days": home_regime.MAX_AGE.days,
                     "shift_pt": HOME_SHIFT_PT, "shift_adopted": home_regime.HOME_SHIFT_ADOPTED},
            "history_weeks": HISTORY_WEEKS, "inputs": rows}


# ---------------- layers 2-3 ----------------


def _component(c: Any, weights: Mapping[str, Mapping[str, int]]) -> dict:
    return {"name": c.name, "source": c.source, "series_id": c.series_id, "value": _num(c.value),
            "direction": c.direction,
            "last": {"date": c.last.date.isoformat(), "value": _num(c.last.value)},
            "detail": c.detail, "weights": dict(weights.get(c.name, {}))}


def _layer2(ov: Any, weights: Mapping[str, Mapping[str, int]]) -> dict:
    assets = []
    for o in ov.overrides:
        raw = ov.raw.get(o.asset, o.delta)
        assets.append({"asset": o.asset, "shift": _num(o.delta), "raw": _num(raw),
                       "cap": MAX_OVERRIDE, "capped": raw != o.delta, "reason": o.reason})
    idr = getattr(ov, "idr", None)
    return {"components": [_component(c, weights) for c in ov.components], "assets": assets,
            "idr_terms": None if idr is None else {
                "currency": idr.currency, "level": _num(idr.level), "on": idr.on.isoformat(),
                "change_3m": _num(idr.change_3m), "change_12m": _num(idr.change_12m),
                "carry": _num(idr.carry), "detail": idr.detail()},
            "gaps": [{"input": k, "why": v} for k, v in getattr(ov, "gaps", ())]}


def subject_payload(subject: str, day: date, fingerprint: str, *, overrides: Any,
                    signals: Any = None, charts: Mapping | None = None,
                    chart_stale: Sequence[str] = (), chart_sources: Sequence[str] = (),
                    members: Sequence[str] = ()) -> dict:
    """`<SUBJECT>.json`: layer 2 (IDN's `IdnOverrides` or a foreign `MarketOverrides`), layer 3
    (`IdnSignals`, IDN only) and, for IDN, the chart windows."""
    weights = idn_ov.WEIGHTS if subject == "IDN" else fo.WEIGHTS
    layer3 = None
    if signals is not None:
        assets = list(dict.fromkeys([*idn_ov.ASSETS[:2], *(s.asset for s in signals.signals)]))
        layer3 = {"signals": [{"asset": s.asset, "name": s.name, "value": _num(s.value),
                               "direction": s.direction, "source": s.source,
                               "detail": s.detail} for s in signals.signals],
                  "tally": {a: signals.tally(a) for a in assets}}
    p = _head("subject", day, fingerprint)
    p.update({"subject": subject, "members": list(members),
              "layer2": _layer2(overrides, weights), "layer3": layer3,
              "charts": dict(charts) if charts is not None else None})
    stale = [*overrides.stale_inputs, *(signals.stale_inputs if signals else ()), *chart_stale]
    sources = [*overrides.sources, *(signals.sources if signals else ()), *chart_sources]
    return _tail(p, stale, sources)


def _points(rows: Sequence[Row]) -> list[dict]:
    """[{date, value}] one per date (the last row of a date wins), oldest first."""
    by_day = {r.date: r.value for r in sorted(rows, key=lambda r: r.date)}
    return [{"date": d.isoformat(), "value": _num(v)} for d, v in sorted(by_day.items())]


def _flows(day: date, idxscape: Any) -> tuple[dict, dict]:
    rows = idxscape.rows([IDX_NET_FOREIGN_IDR, IDX_NET_FOREIGN_USD, JISDOR],
                         start=day - FLOW_READ_BACK, end=day)
    by: dict[str, dict[date, float | None]] = defaultdict(dict)
    for r in sorted(rows, key=lambda r: r.date):
        by[r.series_id][r.date] = r.value
    idx_days = sorted(by[IDX_NET_FOREIGN_IDR])
    window = idx_days[-FLOW_DAYS:]
    flows = {"days": FLOW_DAYS, "unit_idr": "IDR", "unit_usd": "USD",
             "points": [{"date": d.isoformat(), "idr": _num(by[IDX_NET_FOREIGN_IDR][d]),
                         "usd": _num(by[IDX_NET_FOREIGN_USD].get(d))} for d in window]}
    rates = sorted((d, v) for d, v in by[JISDOR].items() if v is not None)[-JISDOR_DAYS:]
    carried = idxscape.carried_forward() if rates else set()
    have = {d for d, _ in rates}
    since = rates[0][0] if rates else day
    gaps = [d.isoformat() for d in idx_days if since <= d <= day and d not in have]
    jisdor = {"days": JISDOR_DAYS, "unit": "IDR per USD",
              "points": [{"date": d.isoformat(), "value": _num(v),
                          "carried_forward": d in carried} for d, v in rates],
              "gaps": gaps}
    return flows, jisdor


def _curve(points: Sequence[Any]) -> list[dict]:
    return [{"tenor_y": _num(p.tenor_y), "yield_pct": _num(p.yield_pct),
             "from_yesterday_column": bool(p.from_yesterday_column)} for p in points]


def _igsyc(day: date, phei: Any) -> dict:
    latest = phei.curve(day, on_or_before=True)
    if not latest:
        raise SourceUnavailable(getattr(phei, "name", "idxscape_phei"), "missing",
                                f"no IGSYC curve on or before {day}")
    newest = latest[0].as_of
    target = newest - CURVE_BACK
    earlier = phei.curve(target, on_or_before=True)
    return {"latest": {"as_of": newest.isoformat(), "points": _curve(latest)},
            "earlier": {"target": target.isoformat(),
                        "as_of": earlier[0].as_of.isoformat() if earlier else None,
                        "points": _curve(earlier)},
            "unit": "% a year"}


def idn_charts(day: date, src: Any) -> tuple[dict, list[str], list[str]]:
    """IDN's chart windows → (charts, stale inputs, sources). Each chart is read on its own: one
    that fails is None in `charts` and named in the stale inputs."""
    charts: dict[str, Any] = dict.fromkeys(
        ("net_foreign", "jisdor", "jci", "igsyc", "sbn_non_resident"))
    stale: list[str] = []
    sources: list[str] = []

    def guard(names: Sequence[str], source: Any, fn: Callable[[], Any]) -> None:
        try:
            got = fn()
        except Exception as e:  # noqa: BLE001 - a chart never fails the run
            stale.append(_failure(f"chart {names[0]}", e))
            return
        got = got if len(names) > 1 else (got,)
        for n, g in zip(names, got, strict=True):
            charts[n] = g
        sources.append(getattr(source, "name", ""))

    guard(("net_foreign", "jisdor"), src.idxscape, lambda: _flows(day, src.idxscape))
    guard(("jci",), src.idxmethod, lambda: {
        "unit": "index", "source": getattr(src.idxmethod, "name", ""),
        "points": _points(jci(day - YEAR, day, source=src.idxmethod))})
    guard(("igsyc",), src.phei, lambda: _igsyc(day, src.phei))
    guard(("sbn_non_resident",), src.idxscape, lambda: {
        "unit": "IDR", "series_id": SBN_NON_RESIDENT,
        "points": _points(src.idxscape.rows([SBN_NON_RESIDENT], start=day - YEAR, end=day))})
    return charts, stale, sources


# ---------------- layer 5 ----------------


def _bucket_key(subject: str, asset: str) -> str:
    return f"{subject}/{asset}"


def _holding(h: Any) -> dict:
    key = classify(h.symbol, h.currency)
    return {"symbol": h.symbol, "name": h.name, "quantity": str(h.quantity),
            "value": _num(h.value), "currency": h.currency,
            "bucket": _bucket_key(*key) if key else None}


def _account(s: Any) -> dict:
    return {"issuer": s.issuer, "account": _mask(s.account), "owner": s.owner,
            "doc_type": s.doc_type, "as_of": s.as_of.isoformat(),
            "rolled_from": _iso(s.rolled_from), "trade_docs": s.trade_docs,
            "cash_idr": _num(s.cash_idr), "holdings_idr": _num(s.holdings_idr),
            "stated_value_idr": _num(s.stated_value_idr),
            "broker_cash_idr": _num(s.broker_cash_idr),
            "priced_at_trade": list(s.priced_at_trade),
            "holdings": [_holding(h) for h in s.holdings],
            "unheld": [_holding(h) for h in s.unheld]}


def _stance_row(p: Mapping) -> dict:
    pf = p.get("portfolio") or {}
    return {"subject": p["subject"], "asset": p["asset"], "stance": p["stance"],
            "score": p["score"], "current_pct": pf.get("current_pct"),
            "target_pct": pf.get("target_pct"), "benchmark_pct": pf.get("benchmark_pct"),
            "delta": pf.get("delta"), "rebalance_pt": pf.get("rebalance_pt"),
            "tilt_pt": pf.get("tilt_pt"), "entry": dict(p["entry"])}


def portfolio_payload(day: date, fingerprint: str, portfolio: Portfolio | None,
                      statements: Sequence[Any] = (), stances: Sequence[Mapping] = (),
                      stale: Sequence[str] = ()) -> dict:
    """`portfolio.json`: layer 5 as the run built it and each stance's portfolio terms."""
    p = _head("portfolio", day, fingerprint)
    pf = portfolio
    total = pf.total_idr if pf is not None else None
    buckets = []
    if pf is not None:
        for (subject, asset), v in sorted(pf.buckets_idr.items()):
            buckets.append({"subject": subject, "asset": asset, "idr": _num(v),
                            "pct": _num(100 * v / total) if total else None})
    owners = []
    for owner, b in sorted((pf.by_owner if pf is not None else {}).items()):
        owners.append({"owner": owner, "total_idr": _num(sum(b.values())),
                       "buckets": [{"subject": s, "asset": a, "idr": _num(v)}
                                   for (s, a), v in sorted(b.items())]})
    p.update({
        "statement_as_of": _iso(pf.as_of) if pf is not None else None,
        "currency": "IDR",
        "total_idr": _num(total),
        "unmapped_idr": _num(pf.unmapped_idr) if pf is not None else None,
        "broker_cash_idr": _num(pf.broker_cash_idr) if pf is not None else None,
        "buckets": buckets,
        "by_owner": owners,
        "accounts": [_account(s) for s in statements] if pf is not None else [],
        "unmapped": [{"label": label, "idr": _num(v)} for label, v in pf.unmapped]
        if pf is not None else [],
        "checks": [{"issuer": c.issuer, "account": _mask(c.account), "as_of": c.as_of.isoformat(),
                    "holdings_idr": _num(c.holdings_idr), "stated_idr": _num(c.stated_idr),
                    "cash_idr": _num(c.cash_idr), "matches": c.matches}
                   for c in pf.checks] if pf is not None else [],
        "notes": list(pf.notes) if pf is not None else [],
        "stances": [_stance_row(s) for s in sorted(stances,
                                                   key=lambda s: (s["subject"], s["asset"]))],
        "mandate": mandate_summary(stances),
    })
    own = list(pf.stale_inputs) if pf is not None else []
    return _tail(p, [*stale, *own], list(pf.sources) if pf is not None else ["financer"])


# ---------------- write ----------------


def _write_if_changed(path: Path, text: str) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return  # keep the mtime of an unchanged file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _stub(kind: str, name: str, day: date, fingerprint: str, error: str) -> dict:
    p = _head(kind, day, fingerprint)
    if kind == "subject":
        p["subject"] = name
    p["error"] = error
    return _tail(p, [f"layer file {name} failed: {error}"], [])


def _safe(kind: str, name: str, day: date, fingerprint: str, build: Callable[[], dict]) -> dict:
    """`build()`, schema-checked; an exception or a schema error gives a stub with `error`."""
    try:
        payload = build()
        errors = sorted(validator(kind).iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            e = errors[0]
            where = "/".join(str(x) for x in e.absolute_path)
            raise ValueError(f"schema: {where}: {e.message}"[:200])
    except Exception as e:  # noqa: BLE001 - a layer file never fails the run
        first = str(e).splitlines()[0][:160] if str(e) else ""
        return _stub(kind, name, day, fingerprint, f"{type(e).__name__}: {first}")
    return payload


def _dumps(payload: Mapping) -> str:
    return json.dumps(payload, sort_keys=True, indent=1, ensure_ascii=False,
                      allow_nan=False) + "\n"


def write_layers(layers: Any, stances: Sequence[Mapping], fingerprint: str, out_dir: Path, *,
                 fred: Any = None, idn: Any = None, home_sources: Any = None) -> list[Path]:
    """Write `out/layers/{regime,<SUBJECT>,portfolio}.json` from the run's `layers` (a
    `pipeline.Layers`) and drop subject files this run did not produce. `fred` and `idn` (the
    run's FRED source and `IdnSources`) serve the history and chart reads, `home_sources` (a
    `HomeSources`) the home inputs' weekly lines. Never raises."""
    day = layers.day
    d = Path(out_dir) / DIR
    files: list[tuple[str, dict]] = []

    def regime_file() -> dict:
        hist, h_stale = regime_history(day, fred)
        p = regime_payload(day, fingerprint, layers.regime, layers.regime_inputs, hist,
                           h_stale)
        home = getattr(layers, "home", None)
        if home is not None:
            h_hist, hh_stale = home_history(day, home_sources)
            p["home"] = home_block(home, h_hist)
            p["stale_inputs"] = _uniq([*p["stale_inputs"], *hh_stale])
            p["sources"] = _uniq([*p["sources"], *home.sources])
        return p

    files.append(("regime", _safe("regime", "regime", day, fingerprint, regime_file)))

    if layers.idn is not None:
        def idn_file() -> dict:
            charts, c_stale, c_src = (idn_charts(day, idn) if idn is not None
                                      else (None, [], []))
            return subject_payload("IDN", day, fingerprint, overrides=layers.idn.overrides,
                                   signals=layers.idn.signals, charts=charts,
                                   chart_stale=c_stale, chart_sources=c_src)

        files.append(("IDN", _safe("subject", "IDN", day, fingerprint, idn_file)))
    if layers.foreign is not None:
        for m in layers.foreign.overrides.markets:
            members = fo.EMU_MEMBERS if m.subject == "EMU" else ()
            files.append((m.subject, _safe(
                "subject", m.subject, day, fingerprint,
                lambda m=m, members=members: subject_payload(
                    m.subject, day, fingerprint, overrides=m, members=members))))

    def portfolio_file() -> dict:
        return portfolio_payload(day, fingerprint, layers.portfolio, layers.statements,
                                 stances, layers.portfolio_stale)

    files.append(("portfolio", _safe("portfolio", "portfolio", day, fingerprint,
                                     portfolio_file)))

    written = []
    for name, payload in files:
        path = d / f"{name}.json"
        try:
            _write_if_changed(path, _dumps(payload))
        except Exception as e:  # noqa: BLE001 - e.g. a full disk: the stances are written
            print(f"layer file {name} not written: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        written.append(path)
    keep = set(written)
    if d.is_dir():
        for f in d.glob("*.json"):
            if f not in keep:
                f.unlink()
    return written
