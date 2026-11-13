"""Flip counter (PLAN S91, phase P rule 7): how often each held name's **acted** verdict changed
per calendar quarter, split by cause. Target: at most `TARGET_PER_QUARTER` (1) per name per
quarter; a flip caused by method or data is a bug.

**Record of truth: the journal**, kind `holding` (one record per held name per run, S86;
`pipeline._journal_holdings`). `out/holdings/IDN.json` keeps only the last run and its previous
record, so it cannot give a history; the journal is append-only and hash-chained. Records
without an `acted` block (journalled before S87) are skipped.

- **Verdict** is the replay's (`candidates.hysteresis_replay._acted`), so the live count and the
  S87 baseline measure the same thing: `sell` (the acted thesis `acts`), `take_profit` (the
  take-profit state `fired`), else `hold`. The step from `trim_to_half` to `stop_adding` is one
  take-profit, not a flip.
- **One record per name per day**: a same-day rerun replaces the earlier record of that day.
  Records are compared in date order per (market, symbol); a flip counts in the quarter of the
  later record. A name-quarter is a (market, symbol, quarter) with at least one record.
- **Cause** of a flip: the acted block's own `cause`, else the record's `cause`, else
  `rule_version` when the two records were judged by different models, else None. **Real**:
  `new_filing`, `price_cross`, `holdings_change`. **Method or data** (a bug, rule 7):
  `rule_version`, `data_fix`, None, and `first` after an earlier record (the holding record
  restarted, e.g. an unreadable `out/holdings` file).
- **Baseline**: S87's replay (`hysteresis_replay`, Fridays 2021-01 → 2026-11, dividend gates
  only), raw 0.56 → acted 0.26 flips per name-quarter.

A score of past decisions, never a decision: outside `journal.RULE_GLOBS`, so not hashed. Pure.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from statistics import fmean
from typing import Any

__all__ = ["BASELINE", "METHOD_OR_DATA", "REAL", "TARGET_PER_QUARTER", "count", "lines",
           "quarter", "verdict"]

TARGET_PER_QUARTER = 1  # phase P rule 7
REAL = ("new_filing", "price_cross", "holdings_change")
METHOD_OR_DATA = ("rule_version", "data_fix", "first", None)
# S87 Progress row: python -m assist.candidates.hysteresis_replay, regime premium on
BASELINE = {
    "source": "S87 hysteresis_replay (Fridays 2021-01 → 2026-11, 306 weeks, dividend gates "
              "only, base hurdle 13.87 + 1pt risk-off)",
    "name_quarters": 1862, "raw_flips": 1051, "acted_flips": 488,
    "raw_per_name_quarter": 0.56, "acted_per_name_quarter": 0.26,
    "raw_over_one": 272, "acted_over_one": 59, "raw_max": 7, "acted_max": 3,
}


def verdict(acted: Mapping | None) -> str | None:
    if not acted:
        return None
    if (acted.get("thesis") or {}).get("acts"):
        return "sell"
    return "take_profit" if (acted.get("valuation") or {}).get("state") == "fired" else "hold"


def quarter(d: date | str) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def _cause(prev: Mapping, cur: Mapping) -> str | None:
    a = cur["outputs"].get("acted") or {}
    c = a.get("cause") or cur["outputs"].get("cause")
    if c is None and prev["fingerprint"] != cur["fingerprint"]:
        return "rule_version"
    return c


def _series(records: Iterable[Mapping]) -> dict[tuple[str, str], list[dict]]:
    """(market, symbol) → one record per day (the last of the day), in date order."""
    per: dict[tuple[str, str], dict[str, dict]] = {}
    for r in records:
        outs = r.get("outputs") or {}
        if r.get("kind") != "holding" or not outs.get("acted") or not outs.get("symbol"):
            continue
        if not r.get("as_of"):
            continue
        per.setdefault((r.get("subject") or "", outs["symbol"]), {})[str(r["as_of"])[:10]] = {
            "as_of": str(r["as_of"])[:10], "fingerprint": r.get("fingerprint"),
            "outputs": outs}
    return {k: [v[d] for d in sorted(v)] for k, v in sorted(per.items())}


def count(records: Iterable[Mapping]) -> dict[str, Any]:
    """Journal records → flips per held name per quarter, the names over target, the bugs."""
    names: dict[tuple[str, str, str], dict] = {}
    events: list[dict] = []
    for (market, sym), rs in _series(records).items():
        for r in rs:
            names.setdefault((market, sym, quarter(r["as_of"])), {
                "market": market, "symbol": sym, "quarter": quarter(r["as_of"]),
                "flips": 0, "real": 0, "method_or_data": 0})
        for prev, cur in zip(rs, rs[1:], strict=False):
            v0, v1 = verdict(prev["outputs"]["acted"]), verdict(cur["outputs"]["acted"])
            if v0 == v1:
                continue
            c = _cause(prev, cur)
            kind = "real" if c in REAL else "method_or_data"
            q = quarter(cur["as_of"])
            n = names[(market, sym, q)]
            n["flips"] += 1
            n[kind] += 1
            events.append({"market": market, "symbol": sym, "as_of": cur["as_of"],
                           "quarter": q, "from": v0, "to": v1, "cause": c, "kind": kind})
    rows = list(names.values())
    over = [n for n in rows if n["flips"] > TARGET_PER_QUARTER]
    bugs = [e for e in events if e["kind"] == "method_or_data"]
    quarters: dict[str, dict] = {}
    for n in rows:
        b = quarters.setdefault(n["quarter"], {"names": 0, "flips": 0, "real": 0,
                                               "method_or_data": 0, "over_target": 0})
        b["names"] += 1
        for k in ("flips", "real", "method_or_data"):
            b[k] += n[k]
        b["over_target"] += n["flips"] > TARGET_PER_QUARTER
    return {
        "source": "journal kind holding (acted verdict: sell / take_profit / hold)",
        "target_per_quarter": TARGET_PER_QUARTER,
        "summary": {"name_quarters": len(rows), "flips": len(events),
                    "real": len(events) - len(bugs), "method_or_data": len(bugs),
                    "per_name_quarter": (round(fmean(n["flips"] for n in rows), 3)
                                         if rows else None),
                    "over_target": len(over), "bugs": len(bugs)},
        "quarters": dict(sorted(quarters.items())),
        "names": rows,
        "over_target": over,
        "flips": events,
        "bugs": bugs,
        "baseline": dict(BASELINE),
    }


def lines(flips: Mapping[str, Any]) -> list[str]:
    """The count in a few lines: totals, names over target, bugs, the S87 baseline."""
    s, b = flips["summary"], flips["baseline"]
    base = (f"Baseline (S87 replay): raw {b['raw_per_name_quarter']} → acted "
            f"{b['acted_per_name_quarter']} flips per name-quarter over "
            f"{b['name_quarters']:,} name-quarters ({b['acted_over_one']} over 1).")
    if not s["name_quarters"]:
        return ["Verdict flips: no holding records with an acted verdict in the journal yet.",
                base]
    out = [f"Verdict flips (acted, target <= {flips['target_per_quarter']} per name per "
           f"quarter): {s['name_quarters']} name-quarter(s), {s['flips']} flip(s) "
           f"({s['per_name_quarter']} per name-quarter): {s['real']} real, "
           f"{s['method_or_data']} method or data."]
    if flips["over_target"]:
        out.append(f"Over the target of {flips['target_per_quarter']} per quarter: " + ", ".join(
            f"{n['market']} {n['symbol']} {n['quarter']} ({n['flips']})"
            for n in flips["over_target"]) + ".")
    else:
        out.append("No name over the target.")
    if flips["bugs"]:
        out.append("Method or data flips (each a bug, phase P rule 7): " + "; ".join(
            f"{e['market']} {e['symbol']} {e['as_of']} {e['from']} → {e['to']} "
            f"({e['cause'] or 'no cause'})" for e in flips["bugs"]) + ".")
    return out + [base]
