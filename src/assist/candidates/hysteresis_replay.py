"""Flip-rate replay of the holding verdict (PLAN S87, phase P rule 7): verdict flips per held-style
name per quarter, raw (S86, judged afresh each week) against acted (S87's hysteresis).

Every Friday (`fridays`) each name is judged point in time from idx-method's `factor_series`
and dividends (`dividend_value.load`): the dividend screen's safety gates (`dividend_value.assess`,
`own=False`) give the thesis through `holdings.thesis` (the quality floor and GARP have no
history: not replayed, so the quality floor's F-score and Altman Z soft fails are missing), and
the fair price at the week's required return gives take-profit. The **verdict** is the action
it implies: `sell` (raw: any thesis fail, as sizing's trim in full; acted: the thesis `acts`),
`take_profit` (raw: price at or above fair; acted: take-profit `fired`), else `hold`.

The required return is a fixed base (today's IDN hurdle before its risk-off premium) plus
`hurdle.CONFIG["risk_off_premium_pt"]` on the weeks the point-in-time regime
(`layers.regime.regime`) is risk-off: the regime toggle is the one hurdle move replayed; the
10Y, ERP, CRP and tilt are held. A name counts in a quarter (`held_style`) when its raw or acted
thesis passes at its first Friday in that quarter and its market cap clears `min_mktcap`. A flip
is a change between consecutive Fridays, counted in the quarter of the later one.

`replay` and `count` are pure; `main` reads the stores read-only and prints JSON (no file).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from statistics import fmean

from assist.candidates import dividend_value, holdings, hysteresis
from assist.candidates.hurdle import CONFIG as HURDLE_CONFIG

__all__ = ["count", "fridays", "replay"]

Row = tuple[date, str, str]  # (Friday, raw verdict, acted verdict)


def fridays(start: date, end: date) -> list[date]:
    d = start + timedelta(days=(4 - start.weekday()) % 7)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(weeks=1)
    return out


def _quarter(d: date) -> str:
    m = ((d.month - 1) // 3 + 1) * 3
    end = date(d.year, m, 30 if m in (6, 9) else 31)
    return end.isoformat()


def _raw(t: Mapping, v_above: bool | None) -> str:
    return "sell" if t["status"] == "fail" else "take_profit" if v_above else "hold"


def _acted(a: Mapping) -> str:
    if a["thesis"]["acts"]:
        return "sell"
    return "take_profit" if a["valuation"]["state"] == "fired" else "hold"


def _name(bars, quarters, divs, *, bank: bool, dates: Sequence[date],
          required: Mapping[date, float | None], min_mktcap: float
          ) -> tuple[list[Row], set[str]]:
    rows: list[Row] = []
    held: set[str] = set()
    seen_q: set[str] = set()
    bar_dates = [b.date for b in bars]
    vdivs = [r for r in divs if r.get("value") is not None]
    prev = None
    for d in dates:
        a = dividend_value.assess(d, bars, quarters, divs, bank=bank, own=False,
                                  bar_dates=bar_dates)
        if a is None or a.bar_date < d - timedelta(days=10):
            continue
        j = {"quality": {"ok": True, "gate": None}, "bank": bank, "buy_gate": None,
             "dividend_value": {"ok": a.ok, "failed": list(a.failed), "legs": a.legs(),
                                "price": a.price},
             "garp": None}
        t = holdings.thesis(j)
        exs = [r["ex"] for r in vdivs if r["ex"] <= d.isoformat()]
        inputs = {"report_period": a.period.isoformat() if a.period else None,
                  "last_dividend_ex": max(exs) if exs else None}
        req = required.get(d)
        v = holdings.valuation(j, a.price, req)
        prev = hysteresis.act(prev, t, inputs, price=a.price, dv=j["dividend_value"],
                              required_live=req)
        q = _quarter(d)
        if q not in seen_q:
            seen_q.add(q)
            if a.mktcap >= min_mktcap and (t["status"] == "pass"
                                           or prev["thesis"]["status"] == "pass"):
                held.add(q)
        rows.append((d, _raw(t, v["above_fair"]), _acted(prev)))
    return rows, held


def count(rows: Mapping[str, Sequence[Row]], held: Iterable[tuple[str, str]]) -> dict:
    """Flips per (name, quarter) over the held-style name-quarters → per quarter and summary."""
    held = set(held)
    per: dict[tuple[str, str], list[int]] = {k: [0, 0] for k in held}
    for sym, rs in rows.items():
        for (_, r0, a0), (d1, r1, a1) in zip(rs, rs[1:], strict=False):
            k = (sym, _quarter(d1))
            if k in per:
                per[k][0] += r0 != r1
                per[k][1] += a0 != a1
    quarters: dict[str, dict] = {}
    for (_, q), (r, a) in sorted(per.items(), key=lambda x: (x[0][1], x[0][0])):
        b = quarters.setdefault(q, {"names": 0, "raw_flips": 0, "acted_flips": 0})
        b["names"] += 1
        b["raw_flips"] += r
        b["acted_flips"] += a
    raw = [v[0] for v in per.values()]
    act = [v[1] for v in per.values()]
    n = len(per)
    return {"quarters": dict(sorted(quarters.items())), "summary": {
        "name_quarters": n,
        "raw_flips": sum(raw), "acted_flips": sum(act),
        "raw_per_name_quarter": round(fmean(raw), 3) if n else None,
        "acted_per_name_quarter": round(fmean(act), 3) if n else None,
        "raw_over_one": sum(x > 1 for x in raw), "acted_over_one": sum(x > 1 for x in act),
        "raw_max": max(raw, default=0), "acted_max": max(act, default=0)}}


def replay(bars: Mapping[str, Sequence], quarters: Mapping[str, Sequence],
           dividends: Mapping[str, Sequence[Mapping]], *, banks: Iterable[str],
           dates: Sequence[date], required: Mapping[date, float | None],
           min_mktcap: float = dividend_value.CONFIG["replay_min_mktcap"]) -> dict:
    """Raw and acted verdict flips per held-style name per quarter over `dates`."""
    banks = set(banks)
    rows, held = {}, set()
    for sym in sorted(bars):
        rs, hq = _name(bars[sym], quarters.get(sym, ()), dividends.get(sym) or [],
                       bank=sym in banks, dates=dates, required=required,
                       min_mktcap=min_mktcap)
        rows[sym] = rs
        held |= {(sym, q) for q in hq}
    return count(rows, held)


# ---------------- live (read-only) ----------------


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - live stores
    from assist.layers import regime as rg
    from assist.sources.idxmethod_series import IdxMethodSeries

    ap = argparse.ArgumentParser(prog="python -m assist.candidates.hysteresis_replay")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--base", type=float, required=True,
                    help="IDN required return before the risk-off premium, pt")
    ap.add_argument("--regimes", help="JSON {date: state} cache; read, else built and written")
    args = ap.parse_args(argv)
    dates = fridays(date.fromisoformat(args.start), date.fromisoformat(args.end))
    states: dict[str, str] = {}
    if args.regimes:
        try:
            with open(args.regimes, encoding="utf-8") as f:
                states = json.load(f)
        except OSError:
            states = {}
    for d in dates:
        if d.isoformat() not in states:
            states[d.isoformat()] = rg.regime(d).state
    if args.regimes:
        with open(args.regimes, "w", encoding="utf-8") as f:
            json.dump(states, f)
    prem = HURDLE_CONFIG["risk_off_premium_pt"]
    from assist.sources.idxmethod_stocks import IdxMethodStocks

    data = dividend_value.load(IdxMethodSeries.from_config())
    banks = {s for s, r in IdxMethodStocks.from_config().factors().items() if r.get("car")}
    out = {}
    for label, req in (
            ("regime_premium", {d: args.base + (prem if states[d.isoformat()] == "risk_off"
                                                else 0.0) for d in dates}),
            ("no_regime", dict.fromkeys(dates, args.base))):
        res = replay(data.bars, data.quarters, data.dividends, banks=banks, dates=dates,
                     required=req)
        out[label] = res["summary"]
        if label == "regime_premium":
            out["quarters"] = res["quarters"]
    out["risk_off_weeks"] = sum(s == "risk_off" for s in states.values())
    out["weeks"] = len(dates)
    out["banks"] = len(banks)
    json.dump(out, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
