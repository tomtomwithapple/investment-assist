"""Holding record (PLAN S86, phase P rules 2, 3 and 6): one record per held IDN stock that
answers the three questions apart, written to `out/holdings/IDN.json` and journalled.

- **Thesis** (fundamentals, pass / fail: the only sell trigger, phase P rule 2). The quality
  floor (`screens.passes_quality`: banks on `BANK_FLOOR`) and a style's own safety gates: the
  thesis holds when the floor passes and either the dividend screen's gates
  (`dividend_value.assess`) or GARP's quality gates (`garp.assess`) pass. Every gate failed is
  listed, the first is `gate`. A **hard** fail (`HARD`: dividend cut, negative equity, negative
  CFO) anywhere makes the fail hard; any other is **soft**. The structural gates
  (`screens.passes_gates`: free float, liquidity, price floor, ...) say whether new money may go
  in (`buy_gate`), never whether to sell.
- **Valuation** (price vs fair price: the only take-profit trigger). Fair price is
  `exits.fair_price` on the dividend legs at the hurdle plus the sector's applied tilt shift;
  `take_profit` is it on the tick grid, `review_price` the name's `entry_deep` below today's
  price (flags, never sells), `above_fair` price at or above fair.
- **Fit** (redundant group, the 5% cap: orders the cuts, never "beyond saving"), from the
  candidates payload's `diversification` and sizing's cap trims.

**Inputs judged**: the report period, the bar date and the last dividend's ex-date. **Cause of
change** against the previous record: `first` (no previous record), `rule_version` (another
model fingerprint), `data_fix` (the previous record was stale, or a thesis moved with no new
report), `new_filing` (a new report period or dividend record), `price_cross` (the price crossed
fair, or a size line), `holdings_change` (the fit moved because the held names changed); None
when no answer changed.

**Bad data holds** (rule 3): a run with `data_problems` keeps every previous verdict,
`stale: true`; a name with no previous record reads `unknown`. A same-day rerun keeps the
record it replaced as its previous, so reruns are byte-identical. `thesis` is today's raw verdict
beside the previous one; `acted` (S87, 1.2.0) is the verdict after phase P rule 4's hysteresis
(`candidates.hysteresis`: thesis re-judged only on a new report or dividend record, soft fails
after two reports in a row, take-profit re-armed 10% below fair), with its own `cause` and
`changed`. `valuation` is at the required return `acted` holds between reports, so a regime
toggle alone moves no fair price; `acted.valuation.required_live_pt` is today's. `sold` lists
the names the model sold on their thesis and no longer held (re-entry needs a margin).
`held_shares` (P135, 1.4.0) is the shares held over every account; with it a take-profit trim
stays open (`acted.valuation.trim`) until the shares are down to the half kept. The bank
Piotroski floor (S88) comes in through `passes_quality` (gate "bank F-score", soft); a bank's n/a
F is a `note`, not a fail. `context` carries phase Q's framework results from
`judged[sym]["context"]` (S96: bank residual income on held banks): context only, never compared
for a change or a verdict.
`watchlists` (S89, 1.1.0) names the user's Stockbit screeners a held name is on, from the
candidates payload's `watchlist` block: context only, never compared for a change or a verdict.
`answers` is the one place a name is judged: `build` calls it for held names and
`undervalued.assemble` for watchlist names, so membership cannot change an answer.

`judge_inputs` reads the screens' loaded data (live, from `undervalued.gather_live`); `build`
is pure. Hashed by `journal.RULE_GLOBS`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

from assist.candidates import dividend_value, exits, garp, hysteresis
from assist.candidates.hurdle import CONFIG as HURDLE_CONFIG
from assist.candidates.screens import bank_f_status, passes_gates, passes_quality
from assist.layers.types import DISCLAIMER, SCHEMA_DIR

__all__ = ["CAUSES", "HARD", "SCHEMA", "SCHEMA_VERSION", "answers", "build", "config", "fit",
           "judge_all", "judge_inputs", "load", "selling", "thesis", "validator", "valuation",
           "write"]

VERSION = "0.1.0"
SCHEMA = SCHEMA_DIR / "holdings.schema.json"
SCHEMA_VERSION = "1.4.0"  # 1.1 watchlists (S89); 1.2 acted, sold (S87); 1.3 baseline;
# 1.4 held_shares, acted.valuation.trim, acted cause holdings_change (P135)
OUT_DIR = "holdings"
HARD = ("cut", "negative CFO", "negative equity")  # phase P rule 4: these act at once
CAUSES = ("first", "rule_version", "data_fix", "new_filing", "price_cross", "holdings_change")
QUESTIONS = ("thesis", "valuation", "fit")


def config() -> dict:
    return {"holdings_version": VERSION, "hard_fails": list(HARD),
            "soft_fails": "every other gate failed (quality floor, bank floor, dividend gates)",
            "thesis": "quality floor, and the dividend or the GARP gates",
            "valuation": "fair price = dividend legs at the hurdle + sector tilt shift",
            "fit": "diversification group and the per-name cap",
            "causes": list(CAUSES), "bad_data": "previous verdict kept, stale",
            "hysteresis": hysteresis.config()}


@cache
def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(_schema())


def _iso(d: Any) -> str | None:
    return d.isoformat() if isinstance(d, date) else d


# ---------------- inputs (live) ----------------


def judge_inputs(sym: str, row: Mapping, data: dividend_value.DividendData, as_of: date, *,
                 hurdle_pt: float | None, flagged: Iterable[str] = (),
                 consensus: Mapping | None = None, levels: Any = None) -> dict:
    """One name's thesis and valuation inputs on `as_of`, as plain JSON: the quality floor, the
    structural gates, the dividend and GARP assessments, the inputs judged and the review
    level (`levels.entry_deep`)."""
    bank = bool(row.get("car"))
    q_ok, q_why = passes_quality(row)
    g_ok, g_why = passes_gates(sym, row, set(flagged))
    bars = data.bars.get(sym, [])
    quarters = data.quarters.get(sym, [])
    divs = data.dividends.get(sym, [])
    dv = dividend_value.assess(as_of, bars, quarters, divs, bank=bank)
    ga = garp.assess(as_of, bars, quarters, divs, hurdle_pt=hurdle_pt, bank=bank,
                     consensus=consensus)
    exs = [r["ex"] for r in divs if r.get("value") is not None and r["ex"] <= as_of.isoformat()]
    deep = getattr(levels, "entry_deep", None) if levels is not None else None
    return {
        "symbol": sym, "bank": bank, "sector": data.sectors.get(sym),
        "quality": {"ok": q_ok, "gate": q_why,
                    "note": ("bank F-score n/a (too few signals computable): not counted"
                             if bank_f_status(row) == "n/a" else None)},
        "buy_gate": None if g_ok else g_why,
        "dividend_value": None if dv is None else {
            "ok": dv.ok, "failed": list(dv.failed), "legs": dv.legs(), "price": dv.price},
        "garp": None if ga is None else {"ok": ga.ok, "failed": list(ga.failed)},
        "report_period": _iso(dv.period) if dv is not None else None,
        "bar_date": _iso(dv.bar_date) if dv is not None else None,
        "last_dividend_ex": max(exs) if exs else None,
        "review_at": None if deep is None else float(deep),
    }


def judge_all(table: Mapping[str, Mapping], data: dividend_value.DividendData, as_of: date, *,
              hurdle_pt: float | None, flagged: Iterable[str] = (),
              consensus: Mapping[str, Mapping] | None = None,
              levels: Mapping[str, Any] | None = None) -> dict[str, dict]:
    """`judge_inputs` for every name of P19's table (the run does not know yet which are
    held); a name that fails raises nothing, it is left out (and reads unknown)."""
    flagged, consensus, levels = set(flagged), consensus or {}, levels or {}
    out = {}
    for sym in sorted(table):
        try:
            out[sym] = judge_inputs(sym, table[sym], data, as_of, hurdle_pt=hurdle_pt,
                                    flagged=flagged, consensus=consensus.get(sym),
                                    levels=levels.get(sym))
        except (ArithmeticError, TypeError, ValueError):
            continue
    return out


# ---------------- the three questions ----------------


def thesis(j: Mapping | None) -> dict:
    """Pass / fail / unknown on fundamentals, with every gate failed and hard or soft."""
    if not j or j.get("dividend_value") is None:
        return {"status": "unknown", "gate": None, "severity": None, "failed": [],
                "basis": None, "buy_gate": (j or {}).get("buy_gate"),
                "bank": (j or {}).get("bank"),
                "note": "not in the screener" if not j else "no price history"}
    q, dv, ga = j["quality"], j["dividend_value"], j.get("garp") or {"ok": False, "failed": []}
    failed = [] if q["ok"] else [q["gate"]]
    style_ok = dv["ok"] or ga["ok"]
    if not style_ok:
        failed += dv["failed"]
    else:
        failed += [g for g in dv["failed"] if g in HARD]  # a dividend cut acts on any style
    failed = list(dict.fromkeys(failed))
    hard = any(g in HARD for g in failed)
    items = [{"gate": g, "severity": "hard" if g in HARD else "soft"} for g in failed]
    return {"status": "fail" if failed else "pass", "gate": failed[0] if failed else None,
            "severity": ("hard" if hard else "soft") if failed else None, "failed": items,
            "basis": None if failed else ("dividend_value" if dv["ok"] else "garp"),
            "buy_gate": j.get("buy_gate"), "bank": j.get("bank"), "note": q.get("note")}


def valuation(j: Mapping | None, price: float | None, required_pt: float | None) -> dict:
    """Price against the fair price of the dividend legs at `required_pt`."""
    dv = (j or {}).get("dividend_value") or {}
    fair = exits.fair_price("dividend_value", dv.get("price"), dv.get("legs"), required_pt)
    review = (j or {}).get("review_at")
    ok = bool(price and price > 0)
    return {"price": float(price) if ok else None, "fair_price": fair,
            "take_profit": exits._floor_tick(fair) if fair else None,
            "take_profit_action": exits.TP_ACTION,
            "review_price": review if ok and review and review < price else None,
            "above_fair": (price >= fair) if fair and ok else None,
            "required_pt": required_pt}


def fit(name: Mapping | None, over_cap: bool) -> dict:
    """The diversification verdict (`diversify.judge`) and the per-name cap."""
    n = name or {}
    group = ({"industry": n["industry"], "size": n["size"]}
             if n.get("industry") and n.get("size") else None)
    redundant, allowed = bool(n.get("redundant")), bool(n.get("allowed"))
    return {"group": group, "group_size": n.get("group_size"), "position": n.get("position"),
            "keeper": n.get("keeper"), "redundant": redundant, "allowed": allowed,
            "over_cap": over_cap, "ok": not (redundant and not allowed) and not over_cap}


# ---------------- change ----------------


def _key(q: str, r: Mapping) -> tuple:
    if q == "thesis":
        return (r["thesis"]["status"], r["thesis"]["gate"])
    if q == "valuation":
        return (r["valuation"]["above_fair"],)
    f = r["fit"]
    return (f["redundant"] and not f["allowed"], f["over_cap"])


def _cause(prev: Mapping | None, cur: Mapping, held_moved: bool) -> tuple[str | None, list[str]]:
    if prev is None:
        return "first", []
    changed = [q for q in QUESTIONS if _key(q, prev) != _key(q, cur)]
    if not changed:
        return None, []
    if prev.get("model_fingerprint") != cur["model_fingerprint"]:
        return "rule_version", changed
    if prev.get("stale"):
        return "data_fix", changed
    pi, ci = prev.get("inputs") or {}, cur["inputs"]
    filed = (pi.get("report_period") != ci["report_period"]
             or pi.get("last_dividend_ex") != ci["last_dividend_ex"])
    if "thesis" in changed:
        return ("new_filing" if filed else "data_fix"), changed
    if "valuation" in changed:
        return ("new_filing" if filed else "price_cross"), changed
    pg, cg = (prev.get("fit") or {}).get("group"), cur["fit"]["group"]
    if held_moved:
        return "holdings_change", changed
    return ("price_cross" if (pg or {}).get("size") != (cg or {}).get("size")
            else "data_fix"), changed


def _compact(r: Mapping) -> dict:
    out = {k: r[k] for k in ("judged_on", "model_fingerprint", "stale", "thesis", "valuation",
                             "fit", "inputs")}
    return out | ({"acted": r["acted"]} if r.get("acted") else {})


def _baseline(previous: Mapping | None, day: date) -> tuple[dict[str, dict], dict | None]:
    """(sym → the record to compare with, {as_of, held} of that run). A previous file written
    on `day` itself is a rerun: its own previous records are the baseline."""
    if not previous:
        return {}, None
    if previous.get("as_of") >= day.isoformat():
        base = {r["symbol"]: r["previous"] for r in previous.get("holdings") or []
                if r.get("previous") is not None}
        return base, previous.get("previous_run")
    base = {r["symbol"]: _compact(r) for r in previous.get("holdings") or []}
    return base, {"as_of": previous["as_of"], "held": sorted(base)}


def _acted(prev: Mapping | None, r: Mapping, j: Mapping | None, required: float | None,
           prev_shares: float | None = None) -> dict:
    """S87: the hysteresis verdict for record `r` (raw answers) against the previous record;
    P135: with the shares held now and on the previous record (an open trim)."""
    return hysteresis.act((prev or {}).get("acted"), r["thesis"], r["inputs"],
                          price=r["valuation"]["price"],
                          dv=(j or {}).get("dividend_value"), required_live=required,
                          shares=r.get("held_shares"), prev_shares=prev_shares)


def _prev_shares(previous: Mapping | None, day: date) -> dict[str, float | None]:
    """sym → shares held on the previous run's record (P135, for a record written before the
    trim was kept): its `held_shares`, else its IDR held over its price. Empty for a rerun."""
    if not previous or previous.get("as_of") >= day.isoformat():
        return {}
    out: dict[str, float | None] = {}
    for r in previous.get("holdings") or []:
        n = r.get("held_shares")
        price = (r.get("valuation") or {}).get("price")
        if n is None and price and r.get("held_idr"):
            n = float(round(r["held_idr"] / price))
        out[r["symbol"]] = n
    return out


def _required(candidates: Mapping, j: Mapping | None) -> float | None:
    hurdle_pt = (candidates.get("hurdle") or {}).get("required_pt")
    return None if hurdle_pt is None else hurdle_pt + _shift(candidates, (j or {}).get("sector"))


def _shift(candidates: Mapping, sector: str | None) -> float:
    sectors = {s["sector"]: s for s in (candidates.get("tilt") or {}).get("sectors") or []}
    x = float((sectors.get(sector) or {}).get("margin_shift_pt") or 0.0)
    cap = HURDLE_CONFIG["sector_shift_max_pt"]
    return max(-cap, min(cap, x))


def answers(candidates: Mapping, j: Mapping | None, sym: str, fit_name: Mapping | None = None,
            over_cap: bool = False) -> dict:
    """Thesis, valuation, fit and the inputs judged for one name, from the candidates payload
    (hurdle, tilt, average-down prices) and its `judge_inputs`. Pure."""
    required = _required(candidates, j)
    prices = {n["symbol"]: n.get("price")
              for n in (candidates.get("average_down") or {}).get("names") or []}
    price = prices.get(sym) or ((j or {}).get("dividend_value") or {}).get("price")
    return {"thesis": thesis(j), "valuation": valuation(j, price, required),
            "fit": fit(fit_name, over_cap),
            "inputs": {"report_period": (j or {}).get("report_period"),
                       "bar_date": (j or {}).get("bar_date"),
                       "last_dividend_ex": (j or {}).get("last_dividend_ex")}}


def selling(judged: Mapping[str, Mapping], holdings: Mapping[str, float], *, day: date,
            previous: Mapping | None = None, stale: bool = False) -> set[str]:
    """The held names `build` will call `sell_all` (P135), known before the candidates payload
    so a name the thesis sells is never the keeper of a duplicate group. The same acted thesis
    as `build`: re-judged only on a new report or dividend record; a stale run keeps the
    previous verdict. Empty while `hysteresis.ACT_ON_VERDICTS` is off (nothing is sold then)."""
    if not hysteresis.ACT_ON_VERDICTS:
        return set()
    base, _ = _baseline(previous, day)
    out = set()
    for sym, v in holdings.items():
        if not v or v <= 0:
            continue
        acted = (base.get(sym) or {}).get("acted")
        if stale:
            if (acted or {}).get("action") == "sell_all":
                out.add(sym)
            continue
        j = judged.get(sym)
        inputs = {"report_period": (j or {}).get("report_period"),
                  "last_dividend_ex": (j or {}).get("last_dividend_ex")}
        if hysteresis.thesis_now(acted, thesis(j), inputs).get("acts"):
            out.add(sym)
    return out


def _unknown(sym: str, held_idr: float, fp: str, previous: Mapping | None,
             shares: float | None = None) -> dict:
    r = {"symbol": sym, "held_idr": held_idr, "held_shares": shares, "judged_on": None,
         "model_fingerprint": fp,
         "stale": True, "cause": None, "changed": [], "thesis": thesis(None) | {
             "note": "inputs broken this run and no earlier verdict"},
         "valuation": valuation(None, None, None), "fit": fit(None, False),
         "inputs": {"report_period": None, "bar_date": None, "last_dividend_ex": None},
         "context": {}, "previous": previous}
    return r | {"acted": _acted(None, r, None, None)}


def build(candidates: Mapping, judged: Mapping[str, Mapping], *, day: date, fingerprint: str,
          holdings: Mapping[str, float], previous: Mapping | None = None,
          shares: Mapping[str, float] | None = None) -> dict:
    """Pure: the run's candidates payload (one market), `judge_inputs` per symbol, layer 5's
    IDR held per symbol, the shares held per symbol (P135; None: unknown) and the previous
    `out/holdings` payload → this run's payload."""
    held = {s: float(v) for s, v in holdings.items() if v and v > 0}
    count = {s: float(v) for s, v in (shares or {}).items() if v is not None}
    base, prev_run = _baseline(previous, day)
    before = _prev_shares(previous, day)
    problems = list(dict.fromkeys(candidates.get("data_problems") or []))
    stale = bool(problems)
    lists = (candidates.get("watchlist") or {}).get("members") or {}
    names = {n["symbol"]: n for n in (candidates.get("diversification") or {}).get("names") or []}
    capped = {t["symbol"] for t in (candidates.get("sizing") or {}).get("trims") or []
              if not str(t.get("reason", "")).startswith("trim in full")}
    hurdle_pt = (candidates.get("hurdle") or {}).get("required_pt")
    held_moved = prev_run is not None and sorted(held) != list(prev_run.get("held") or [])
    out = []
    for sym in sorted(held):
        prev = base.get(sym)
        if stale:
            r = (_unknown(sym, held[sym], fingerprint, prev, count.get(sym)) if prev is None
                 else {"symbol": sym, "held_idr": held[sym], "held_shares": count.get(sym),
                       **prev, "stale": True, "cause": None, "changed": [], "context": {},
                       "previous": prev})
            out.append(r | {"watchlists": list(lists.get(sym) or [])})
            continue
        j = judged.get(sym)
        r = {"symbol": sym, "held_idr": held[sym], "held_shares": count.get(sym),
             "judged_on": day.isoformat(),
             "model_fingerprint": fingerprint, "stale": False,
             **answers(candidates, j, sym, names.get(sym), sym in capped),
             "context": dict((j or {}).get("context") or {}), "previous": prev}
        r["acted"] = _acted(prev, r, j, _required(candidates, j), before.get(sym))
        # the fair price at the required return held between reports (S87, option a)
        r["valuation"] = valuation(j, r["valuation"]["price"],
                                   r["acted"]["valuation"]["required_pt"])
        r["cause"], r["changed"] = _cause(prev, r, held_moved)
        out.append(r | {"watchlists": list(lists.get(sym) or [])})
    return {
        "schema_version": SCHEMA_VERSION,
        "market": candidates["market"],
        "as_of": day.isoformat(),
        "bar_date": candidates.get("bar_date"),
        "model_fingerprint": fingerprint,
        "hurdle_pt": hurdle_pt,
        "stale": stale,
        "data_problems": problems,
        "previous_run": prev_run,
        "holdings": out,
        "sold": hysteresis.sold(
            [{"symbol": k, **v} for k, v in sorted(base.items())],
            (previous or {}).get("sold") or [], held=held,
            since=day.isoformat()),
        "config": config(),
        "sources": ["idx-method", "financer"],
        "disclaimer": DISCLAIMER,
    }


# ---------------- out/ ----------------


def write(payload: Mapping, out_dir: Path) -> Path:
    """`out/holdings/{MARKET}.json`, rewritten only when its bytes change."""
    path = Path(out_dir) / OUT_DIR / f"{payload['market']}.json"
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path


def load(out_dir: Path, market: str) -> dict | None:
    """The market's last payload, or None when missing, unreadable or off the schema (then the
    next run starts every record afresh: cause `first`)."""
    path = Path(out_dir) / OUT_DIR / f"{market}.json"
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return p if not list(validator().iter_errors(p)) else None
