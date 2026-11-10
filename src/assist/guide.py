"""This week's steps (PLAN S75, phase N): the run's stances, candidates and layer 5 turned into an
ordered list of orders a reader can follow without analysing anything.

For each leg of the benchmark (`stance.BENCHMARK_PCT`: IDN stocks, IDN bonds, USA stocks):

- **Sell steps.** Each of sizing's trims (a name over the per-name cap, or one its screen no
  longer rates), then, when those do not cover the leg's cut, `candidates.rebalance`: the
  redundant names in full first (`candidates.diversify`, phase O), then pro rata over the other
  held names (phase N choice 1), the names a passing screen keeps last.
- **Buy steps.** Each sized row, with its entry price per tranche, take-profit and stop
  (`candidates.exits`, choices 4–6).
- **Bucket steps** (choices 2 and 3) for money a leg must gain or lose that no name carries:
  "buy SBN", "buy a US broad-market index fund". The reader picks the product.

Every step has an amount, shares where a price is known, one dated tranche per part (choice 8:
the first on the next weekday after the run, the rest `spacing_days` apart, moved off a
weekend; IDX holidays are not known here), a strength (choice 7) and one plain sentence of why.
Sells come first (they fund the buys), strongest and largest first.

`build` is pure. Nothing here picks a name or an amount: those come from sizing and
`rebalance`, which are hashed. A wrong step is possible; a hidden one is not: each carries its
strength and a link to the page that shows the evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

from assist import plain
from assist.candidates import rebalance
from assist.candidates.costs import LOT
from assist.layers.types import DISCLAIMER, SCHEMA_DIR
from assist.stance import BENCHMARK_PCT

__all__ = ["FILE", "MIN_STEP_IDR", "SCHEMA", "SCHEMA_VERSION", "build", "lines", "load",
           "split_shares", "tranche_dates", "validator", "write"]

SCHEMA = SCHEMA_DIR / "guide.schema.json"
SCHEMA_VERSION = "1.0.0"
FILE = "guide.json"
MIN_STEP_IDR = 100_000.0  # a leg's leftover below this is not worth a step
BUCKET = {
    ("IDN", "bonds"): ("SBN (Indonesian government bonds)",
                       "Pick the product once: retail SBN, an FR series or a bond fund."),
    ("USA", "stocks"): ("a US broad-market index fund",
                        "No US stock passes a screen, so use a broad index fund."),
}
STRENGTH_ORDER = {"strong": 0, "medium": 1, "weak": 2}


@cache
def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(_schema())


# ---------------- dates and lots ----------------


def _weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def tranche_dates(day: date, n: int, spacing_days: int) -> list[date]:
    """Tranche 1 on the next weekday after `day`; tranche i `spacing_days` × i later, moved off
    a weekend."""
    first = _weekday(day + timedelta(days=1))
    return [_weekday(first + timedelta(days=i * spacing_days)) for i in range(max(1, n))]


def split_shares(shares: int, n: int, lot: int = LOT) -> list[int]:
    """`shares` over up to `n` tranches in whole lots, the earlier ones larger by at most one
    lot; an odd-lot remainder (a full exit) rides with the last tranche that has shares."""
    lots, odd = divmod(max(0, int(shares)), lot)
    n = max(1, n)
    out = [(lots // n + (1 if i < lots % n else 0)) * lot for i in range(n)]
    out = [x for x in out if x > 0]
    if odd:
        if out:
            out[-1] += odd
        else:
            out = [odd]
    return out


# ---------------- steps ----------------


def _schedule(st: Mapping | None) -> tuple[int, int]:
    e = (st or {}).get("entry") or {}
    n = int(e.get("tranches") or 1)
    return (n, int(e.get("spacing_days") or 0)) if n > 1 else (1, 0)


def _sell_tranches(shares: int | None, idr: float, price: float | None,
                   dates: Sequence[date]) -> list[dict]:
    if shares and price:
        parts = split_shares(shares, len(dates))
        return [{"date": d.isoformat(), "idr": x * price, "shares": x,
                 "price": {"type": "market", "at": None}}
                for d, x in zip(dates, parts, strict=False)]
    return [{"date": d.isoformat(), "idr": idr / len(dates), "shares": None,
             "price": {"type": "market", "at": None}} for d in dates]


def _bucket_tranches(idr: float, dates: Sequence[date]) -> list[dict]:
    return [{"date": d.isoformat(), "idr": idr / len(dates), "shares": None,
             "price": {"type": "market", "at": None}} for d in dates]


def _step(side: str, kind: str, market: str, asset: str, *, symbol: str | None, what: str,
          tranches: Sequence[Mapping], strength: str, why: str, detail: str,
          take_profit: Mapping | None = None, stop: Mapping | None = None,
          tags: Sequence[str] = ()) -> dict:
    shares = [t["shares"] for t in tranches]
    return {"side": side, "kind": kind, "market": market, "asset": asset, "symbol": symbol,
            "label": f"{'Sell' if side == 'sell' else 'Buy'} {what}",
            "idr": sum(t["idr"] for t in tranches),
            "shares": None if any(s is None for s in shares) else sum(shares),
            "tranches": [dict(t) for t in tranches], "take_profit": take_profit, "stop": stop,
            "strength": strength, "why": why, "detail": detail, "tags": list(tags)}


def _passing(p: Mapping) -> list[str]:
    return [plain.label("style", s["style"]) for s in p.get("styles") or [] if s.get("passed")]


def _held(p: Mapping) -> dict[str, dict]:
    """sym → {idr, price} for the market's held names, from the average-down block."""
    out = {}
    for n in ((p.get("average_down") or {}).get("names") or []):
        price, qty = n.get("price"), n.get("quantity")
        out[n["symbol"]] = {"price": price,
                            "idr": price * qty if price and qty else None, "quantity": qty}
    return out


def _stock_steps(p: Mapping, st: Mapping | None, gap_idr: float, day: date) -> list[dict]:
    market = p["market"]
    detail = f"/candidates/{market}"
    n, spacing = _schedule(st)
    dates = tranche_dates(day, n, spacing)
    port = (st or {}).get("portfolio") or {}
    cur, tgt = port.get("current_pct"), port.get("target_pct")
    leg = plain.leg(market, "stocks")
    screens = " and ".join(_passing(p)) or "screen"
    held = _held(p)
    steps: list[dict] = []

    trims = (p.get("sizing") or {}).get("trims") or []
    for t in trims:
        h = held.get(t["symbol"]) or {}
        price, qty = h.get("price"), h.get("quantity")
        full = str(t["reason"]).startswith("trim in full")
        shares = None
        if price:
            shares = int(qty) if full and qty else int(t["idr"] / price // LOT) * LOT
        if full:
            strength, why = "medium", (f"The {screens} no longer rates it a buy, so the model "
                                       "would not hold it.")
        else:
            strength, why = "strong", ("It is more than 5% of your portfolio; no single stock "
                                       "should be. Sell down to 5%.")
        if shares == 0:
            continue  # under one lot: nothing to place
        steps.append(_step("sell", "name", market, "stocks", symbol=t["symbol"],
                           what=t["symbol"], tranches=_sell_tranches(shares, t["idr"], price,
                                                                     dates),
                           strength=strength, why=why, detail=detail,
                           tags=["all of it"] if full else ["down to the 5% cap"]))

    buys: list[dict] = []
    seen: set[str] = set()
    for s in p.get("styles") or []:
        for r in s.get("rows") or []:
            z = r.get("size")
            if not z or r["symbol"] in seen:
                continue
            seen.add(r["symbol"])
            ex = r.get("exits") or {}
            tr = []
            for i, x in enumerate(z["tranches"]):
                d = _weekday(dates[0] + timedelta(days=int(x["day"])))
                if i == 0:
                    price = {"type": "market_cap", "at": ex.get("entry_cap")}
                elif x.get("limit") is not None:
                    price = {"type": "limit", "at": x["limit"]}
                else:
                    price = {"type": "market", "at": None}
                tr.append({"date": d.isoformat(), "idr": x["idr"], "shares": x["shares"],
                           "price": price})
            down = r.get("action") == "average_down"
            screen = plain.label("style", s["style"])
            why = (f"Passes the {screen} with {r['margin_pt']:+.1f} points over the required "
                   "return.")
            if down:
                below = (r.get("cost_basis") or {}).get("below_cost_pct")
                why += (" You already hold it" + ("" if below is None
                                                  else f" {-below:.0f}% below your cost")
                        + ": this buy lowers your average cost.")
            tp = None
            if ex.get("take_profit") is not None:
                tp = {"at": ex["take_profit"], "action": ex.get("take_profit_action"),
                      "basis": "fair price: above it the stock no longer beats the required "
                               "return"}
            stop = {"rule": ex.get("thesis_stop") or "sell when it fails its screen",
                    "review_at": ex.get("review_at"),
                    "note": "At the review price, look again; do not sell on price alone."}
            buys.append(_step("buy", "name", market, "stocks", symbol=r["symbol"],
                              what=r["symbol"], tranches=tr, strength="medium", why=why,
                              detail=detail, take_profit=tp, stop=stop,
                              tags=["average down"] if down else []))

    named_sells = sum(s["idr"] for s in steps)
    named_buys = sum(b["idr"] for b in buys)
    if gap_idr < 0:
        need = -gap_idr - named_sells + named_buys
        if need >= MIN_STEP_IDR:
            prices = {s: h["price"] for s, h in held.items()}
            values = {s: h["idr"] for s, h in held.items() if h["idr"]}
            trimmed = {t["symbol"] for t in trims}
            div = {v["symbol"]: v for v in (p.get("diversification") or {}).get("names") or []}
            red = sorted((v for v in div.values() if v["redundant"] and not v["allowed"]
                          and v["symbol"] in values and v["symbol"] not in trimmed),
                         key=lambda v: (-v["position"], values[v["symbol"]], v["symbol"]))
            keep = {v["symbol"] for v in div.values()
                    if v["basis"] == "kept by a passing screen"
                    and not (v["redundant"] and not v["allowed"])}
            sales = rebalance.ordered_sales(
                values, prices, need, exclude=trimmed, redundant=[v["symbol"] for v in red],
                protected=keep, quantities={s: h["quantity"] for s, h in held.items()})
            share = "" if cur is None or tgt is None else (
                f" {leg[0].upper() + leg[1:]} are {cur:.1f}% of your portfolio against a "
                f"{tgt:.0f}% target.")
            for x in sales:
                v = div.get(x["symbol"]) or {}
                if x["tier"] == "redundant":
                    why = (f"You hold {v['group_size']} {v['size']} companies in the same "
                           f"industry ({v['industry']}); {v['keeper']} is the one to keep. "
                           "Selling this one cuts the leg without losing a kind of business.")
                    tags = ["redundant", "all of it"] if x["full"] else ["redundant"]
                elif x["tier"] == "protected":
                    why = ("Its share of the cut after everything else was sold; the screen "
                           "still rates it." + share)
                    tags = ["rebalance"]
                else:
                    why, tags = "Its share of the cut, not a view on the stock." + share, [
                        "rebalance"]
                steps.append(_step(
                    "sell", "name", market, "stocks", symbol=x["symbol"], what=x["symbol"],
                    tranches=_sell_tranches(x["shares"], x["idr"], prices[x["symbol"]], dates),
                    strength="medium", detail="/portfolio", tags=tags, why=why))
            left = need - sum(x["idr"] for x in sales)
            if left >= MIN_STEP_IDR and not sales:
                steps.append(_step(
                    "sell", "bucket", market, "stocks", symbol=None, what=f"more {leg}",
                    tranches=_bucket_tranches(left, dates), strength="medium",
                    detail="/portfolio", tags=["rebalance"],
                    why=f"No price is known to pick the names.{share}"))
    elif gap_idr - named_buys >= MIN_STEP_IDR:
        left = gap_idr - named_buys
        what, how = BUCKET.get((market, "stocks"), (f"{leg} (your choice of fund)", ""))
        share = "" if cur is None or tgt is None else (
            f"{leg[0].upper() + leg[1:]} are {cur:.1f}% of your portfolio against a {tgt:.0f}% "
            "target. ")
        buys.append(_step("buy", "bucket", market, "stocks", symbol=None, what=what,
                          tranches=_bucket_tranches(left, dates), strength="medium",
                          why=(share + how).strip(), detail=f"/stance/{market}/stocks"))
    return steps + buys


def _bucket_leg(market: str, asset: str, st: Mapping | None, gap_idr: float,
                day: date) -> list[dict]:
    if abs(gap_idr) < MIN_STEP_IDR:
        return []
    n, spacing = _schedule(st)
    dates = tranche_dates(day, n, spacing)
    port = (st or {}).get("portfolio") or {}
    cur, tgt = port.get("current_pct"), port.get("target_pct")
    leg = plain.leg(market, asset)
    what, how = BUCKET.get((market, asset), (leg, ""))
    share = "" if cur is None or tgt is None else (
        f"{leg[0].upper() + leg[1:]} are {cur:.1f}% of your portfolio against a {tgt:.0f}% "
        "target. ")
    side = "buy" if gap_idr > 0 else "sell"
    return [_step(side, "bucket", market, asset, symbol=None, what=what,
                  tranches=_bucket_tranches(abs(gap_idr), dates), strength="medium",
                  why=(share + (how if side == "buy" else "")).strip(),
                  detail=f"/stance/{market}/{asset}")]


def build(day: date, stances: Sequence[Mapping], candidates: Sequence[Mapping],
          fingerprint: str | None = None) -> dict:
    """The guide payload for one run. `stances` are the run's stance payloads, `candidates` its
    `out/candidates` payloads (IDN, USA)."""
    by_key = {(s["subject"], s["asset"]): s for s in stances}
    cands = {p["market"]: p for p in candidates}
    value = next((p["sizing"]["portfolio_value_idr"] for p in candidates
                  if (p.get("sizing") or {}).get("portfolio_value_idr")), None)
    notes: list[str] = []
    legs, steps = [], []
    for (market, asset), bench in BENCHMARK_PCT.items():
        st = by_key.get((market, asset))
        port = (st or {}).get("portfolio") or {}
        cur, tgt = port.get("current_pct"), port.get("target_pct")
        gap = None if value is None or cur is None or tgt is None else (tgt - cur) / 100 * value
        legs.append({"market": market, "asset": asset, "label": plain.leg(market, asset),
                     "stance": (st or {}).get("stance"), "benchmark_pct": bench,
                     "current_pct": cur, "target_pct": tgt, "gap_idr": gap})
        if gap is None:
            notes.append(f"{plain.leg(market, asset)}: no stance or portfolio value, no steps")
            continue
        if asset == "stocks" and market in cands:
            steps += _stock_steps(cands[market], st, gap, day)
        else:
            if asset == "stocks":
                notes.append(f"{plain.leg(market, asset)}: no candidate list this run")
            steps += _bucket_leg(market, asset, st, gap, day)
    steps.sort(key=lambda s: (s["side"] != "sell", STRENGTH_ORDER[s["strength"]], -s["idr"],
                              s["symbol"] or ""))
    for i, s in enumerate(steps, 1):
        s["n"] = i
    regime = next((s.get("regime") for s in stances if s.get("regime")), None)
    split = max((len(s["tranches"]) for s in steps), default=1)
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": day.isoformat(),
        "model_fingerprint": fingerprint,
        "regime": regime,
        "headline": plain.label("regime", regime) if regime else "No regime read this run",
        "headline_note": (plain.meaning("regime", regime) or "") if regime else "",
        "split": split,
        "portfolio_value_idr": value,
        "legs": legs,
        "steps": steps,
        "totals": {"sell_idr": sum(s["idr"] for s in steps if s["side"] == "sell"),
                   "buy_idr": sum(s["idr"] for s in steps if s["side"] == "buy"),
                   "sells": sum(s["side"] == "sell" for s in steps),
                   "buys": sum(s["side"] == "buy" for s in steps)},
        "config": {"rebalance": rebalance.config(), "min_step_idr": MIN_STEP_IDR,
                   "dates": "next weekday after the run, then every spacing_days; IDX holidays "
                            "not known"},
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }


# ---------------- text (brief, Telegram) ----------------


def _m(idr: float) -> str:
    return f"Rp {idr / 1e6:,.1f}m"


def _price(t: Mapping) -> str:
    p = t["price"]
    if p["type"] == "limit" and p["at"] is not None:
        return f"at {p['at']:,.0f} or lower"
    if p["type"] == "market_cap" and p["at"] is not None:
        return f"at market, not above {p['at']:,.0f}"
    return "at market"


def lines(g: Mapping, limit: int | None = None) -> list[str]:
    """The steps as plain lines: one per step, with its tranches when there is more than one."""
    out = [f"{g['headline']}. " + (f"Orders are split in {g['split']}." if g["split"] > 1
                                   else "Orders go in one go.")]
    steps = g["steps"]
    if not steps:
        return [*out, "Nothing to do this week: every leg is at its target."]
    t = g["totals"]
    out.append(f"{t['sells']} to sell ({_m(t['sell_idr'])}), {t['buys']} to buy "
               f"({_m(t['buy_idr'])}).")
    shown = steps if limit is None else steps[:limit]
    for s in shown:
        tr = s["tranches"]
        shares = "" if s["shares"] is None else f", {s['shares']:,} shares"
        when = (f"{tr[0]['date']}" if len(tr) == 1
                else f"{len(tr)} parts from {tr[0]['date']} to {tr[-1]['date']}")
        extra = ""
        if s.get("take_profit"):
            extra += f"; take profit {s['take_profit']['at']:,.0f}"
        if (s.get("stop") or {}).get("review_at"):
            extra += f"; review at {s['stop']['review_at']:,.0f}"
        out.append(f"{s['n']}. {s['label']} {_m(s['idr'])}{shares}, {when}, {_price(tr[0])}"
                   f"{extra} [{s['strength']}]")
    if len(shown) < len(steps):
        out.append(f"... and {len(steps) - len(shown)} more steps on the home page")
    return out


# ---------------- out/ ----------------


def write(payload: Mapping, out_dir: Path) -> Path:
    path = Path(out_dir) / FILE
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path


def load(out_dir: Path) -> tuple[dict | None, str | None]:
    """(payload, problem): None with the reason when the file is missing, unreadable or fails
    the schema."""
    path = Path(out_dir) / FILE
    if not path.is_file():
        return None, "no out/guide.json yet: run `assist run`"
    try:
        p: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"guide.json unreadable: {type(e).__name__}: {e}"
    errors = sorted(validator().iter_errors(p), key=lambda e: list(e.path))
    if errors:
        return None, f"guide.json fails the schema: {errors[0].message}"
    return p, None
