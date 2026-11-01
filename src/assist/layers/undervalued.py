"""Undervalued candidates, one ranked list per market (PLAN S20, with S20a's sizes).

Assembles, for one market (IDN; USA from F6, see *US* below):

- **Styles.** P36's dividend screen and P37's GARP screen (S15's value screen plugs in as one
  more entry in `UndervaluedInputs.screens`). A style whose placebo verdict failed is listed with
  its verdict and pool, and names no one. Within a style rows are ranked by margin over the
  hurdle; across styles nothing is ever ranked on a mixed score (`top` takes ranks in turn).
- **Tilt (S16).** Each row's required margin moves by its sector's applied shift (clamped by
  `hurdle.margin`'s ±2 pt), and the tilted sector caps go to sizing, only when the tilt's own
  verdict passed. Otherwise the shift is 0 and the cap the default 5. A name whose margin is no
  longer positive after the shift is dropped, and the reason kept.
- **Entry and costs**, as `layers.candidates.assemble` does: P21's cost at one planned tranche
  (`TRANCHE_IDR`); no estimate, `over_participation` or `below_one_lot` drops the name. The list
  is reviewed quarterly and a name held while it passes, so one round trip a year is charged
  against the annual margin (`net_margin_pt`); a round trip that eats the margin drops it. Entry
  level = `entry_typical`, else `entry_deep`.
- **Layer 5 and sizing (S20a).** Held or not, from financer's statement lines per symbol, and
  P38's `sizing.size` from the market's stocks stance (`target_pct` − `current_pct` × the
  portfolio value). A name in two styles is sized once, under the style where its margin is
  larger. Trims are only called when at least one style passed, and a full trim only for a held
  name a passing screen ranked (it passed the gates but its margin no longer clears): a held
  name no passing screen rated gets no trim call, only the per-name cap.

`assemble` is pure; `gather_live` reads the stores (read-only) through the screens' own loaders.
The payload (`schema/candidates.schema.json`) carries the run's model fingerprint plus `config`:
the tilt yaml's sha256, the hurdle constants, the sizing caps and each screen's CONFIG, so the
journal records exactly what produced each row. Context only: nothing here moves a stance, and
sizes stay paper until the user confirms the weight bands (PLAN Open questions).

**US (F6, PLAN S21).** `us_inputs` turns P39's `us_stocks.run` results into the same inputs, all
in IDR at the USD/IDR rate of the last session (JISDOR):
- `expected_pt` is the unhedged IDR return and the hurdle is the **binding** one, the higher of
  the USA and IDN hurdles in IDR, so `margin_pt` (P39's lower of the two margins) is still
  expected − hurdle. Prices, `med_value_60d` and sizes are in IDR; the USD price is a driver.
- **No tilt** (S16 is IDN only): no margin shift, default caps. sec-edgar has no SIC, so every
  name is its own sector bucket in sizing too (`sector_buckets=False`), as in P39's `select`.
- **Costs**: P21's model is IDX's (board lots, tick grid, IDX tax), so a hand-set `US_COST`
  stands in: broker fee and the IDR↔USD conversion per side, a large-cap half spread and P21's
  square-root impact; a tranche below one share is `below_one_lot`. No entry levels (P21 reads
  idx-method history): entry basis `none`.
- **Sizing**: P38's `size` counts IDX board lots of `costs.LOT` shares; a US lot is one share, so
  sizing sees the price ÷ `LOT` and its shares are divided back (`lot`, exact for whole shares).
- **Layer 5**: financer's lines are all IDR; `holdings_from(..., "USA")` maps none (layer 5's
  `classify` maps no USD line), so nothing is held and no trim is called.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

from assist.candidates import costs, sizing
from assist.candidates import hurdle as hurdle_mod
from assist.layers.portfolio import classify
from assist.layers.types import DISCLAIMER, SCHEMA_DIR, Regime

__all__ = [
    "SCHEMA",
    "SCHEMA_VERSION",
    "STYLES",
    "TRANCHE_IDR",
    "US_COST",
    "UndervaluedInputs",
    "assemble",
    "gather_live",
    "gather_live_usa",
    "holdings_from",
    "load_out",
    "telegram_lines",
    "top",
    "us_cost",
    "us_inputs",
    "validator",
    "vol_1y",
    "write",
]

SCHEMA = SCHEMA_DIR / "candidates.schema.json"
SCHEMA_VERSION = "1.0.0"
STYLES = ("dividend_value", "garp")  # S15's "value" joins here once idx-method V2/V3 land
TRANCHE_IDR = 10e6  # P21's DEFAULT_ORDER: the tranche costs and capacity are judged at
DROP_FLAGS = ("over_participation", "below_one_lot")
OUT_DIR = "candidates"
# Hand-set US execution costs (bps of notional), in the config of every USA row
US_COST = {
    "broker_bps": 10.0,  # per side, an IDR retail broker's US commission
    "fx_bps": 25.0,  # per side, IDR→USD in and USD→IDR out
    "half_spread_bps": 2.0,  # per side, a US$2bn+ name with US$20m+ a day
}
US_TILT_NOTE = "none for USA (S16 is IDN only)"


@dataclass
class UndervaluedInputs:
    """What one market's list is built from: each screen's `run` output by style, P35's tilt
    `run` output, P19's factor table (price, vol_1y, med_value_60d, amihud) and P21's
    `entry_plan` output (sym → {levels, cost}) for the screens' candidates."""

    market: str
    bar_date: date | None
    screens: dict[str, dict]
    tilt: dict | None
    factors: dict[str, dict] = field(default_factory=dict)
    plan: dict[str, dict] = field(default_factory=dict)
    order_idr: float = TRANCHE_IDR
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    tilt_note: str | None = None  # why there is no tilt, when that is by design (USA)
    lot: int = costs.LOT  # shares per board lot (US: 1)
    sector_buckets: bool = True  # False: every name its own sector (no SIC in sec-edgar)
    config: dict = field(default_factory=dict)  # market-specific settings for the journal


@cache
def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(_schema())


# ---------------- layer 5 ----------------


def holdings_from(statements: Iterable[Any], market: str = "IDN") -> dict[str, float]:
    """IDR held per ticker of `market`'s stocks over financer's latest statements (layer 5's own
    mapping)."""
    out: dict[str, float] = {}
    for s in statements:
        for h in s.holdings:
            if classify(h.symbol, h.currency) == (market, "stocks"):
                out[h.symbol] = out.get(h.symbol, 0.0) + float(h.value)
    return dict(sorted(out.items()))


# ---------------- assembly ----------------


def _tilt_view(t: Mapping | None, note: str | None = None) -> tuple[bool, dict[str, dict], dict]:
    """(passed, sector → applied {margin_shift_pt, cap}, the payload's tilt block)."""
    if not t:
        return False, {}, {"passed": False, "verdict": note or "no tilt (unavailable)",
                           "fingerprint": None, "sectors": []}
    passed = bool(t.get("passed"))
    sectors = {}
    for r in t.get("tilts") or []:
        shift, cap = (float(r["margin_shift_pt"]), int(r["cap"])) if passed else (0.0, 5)
        sectors[r["sector"]] = {"sector": r["sector"], "tilt": float(r["tilt"]),
                                "margin_shift_pt": shift, "cap": cap}
    verdict = (t.get("verdict") or {}).get("reason") or t.get("blocked") or (
        "passed" if passed else "failed")
    return passed, sectors, {"passed": passed, "verdict": verdict,
                             "fingerprint": t.get("fingerprint"),
                             "sectors": [sectors[k] for k in sorted(sectors)]}


def _clamp_shift(x: float) -> float:
    cap = hurdle_mod.CONFIG["sector_shift_max_pt"]
    return max(-cap, min(cap, x))


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)


def _entry(levels: Any) -> dict:
    if levels is None:
        return {"level": None, "basis": "none", "status": "no entry levels"}
    typical, deep = _get(levels, "entry_typical"), _get(levels, "entry_deep")
    if typical is not None:
        return {"level": float(typical), "basis": "typical", "status": str(_get(levels, "status"))}
    if deep is not None:
        return {"level": float(deep), "basis": "deep", "status": str(_get(levels, "status"))}
    return {"level": None, "basis": "none", "status": str(_get(levels, "status"))}


def _drivers(style: str, r: Mapping, hurdle_pt: float | None, shift: float) -> list[str]:
    legs = r.get("legs") or {}
    out = [f"expected {r['expected_pt']:.2f}% vs hurdle "
           + ("n/a" if hurdle_pt is None else f"{hurdle_pt:.2f}%")
           + (f" {shift:+.2f}pt sector tilt" if shift else "")]
    if style == "dividend_value":
        y, g = legs.get("yield_pt"), legs.get("g_pt")
        if y is not None and g is not None:
            out.append(f"yield {y:.2f}% + growth {g:.2f}%")
        own = legs.get("own_yield_pct")
        if own is not None:
            out.append(f"yield at the {100 * own:.0f}th pct of its own "
                       f"{legs.get('own_yield_n', 0)} quarters")
    elif style == "garp":
        imp, real = legs.get("implied_pt"), legs.get("realised_pt")
        if imp is not None and real is not None:
            line = f"price implies {imp:.1f}% growth vs realised {real:.1f}%"
            cons = legs.get("consensus_pt")
            if cons is not None:
                line += f", consensus {cons:.1f}%"
            out.append(line)
    if r.get("bank"):
        out.append("bank (BANK_FLOOR)")
    return out + list(r.get("extra_drivers") or [])


def _style(style: str, res: Mapping, sectors: Mapping[str, dict],
           plan: Mapping[str, Mapping], order_idr: float) -> dict:
    verdict = res.get("verdict") or {}
    passed = bool(res.get("passed"))
    out = {"style": style, "passed": passed,
           "verdict": verdict.get("reason") or res.get("blocked") or (
               "passed" if passed else "failed"),
           # placebo.Verdict.to_dict names them score_t and p_value
           "t": verdict.get("t", verdict.get("score_t")),
           "p": verdict.get("p", verdict.get("p_value")), "quarters": res.get("quarters"),
           "pool": int(res.get("pool") or 0), "rows": [], "dropped": []}
    if not passed:
        return out
    hurdle_pt = res.get("hurdle_pt")
    rows, dropped = [], []
    for c in res.get("candidates") or []:
        sym = c["symbol"]
        if c.get("margin_pt") is None or c.get("expected_pt") is None:
            dropped.append({"symbol": sym, "reason": "no margin (hurdle unknown)"})
            continue
        shift = _clamp_shift((sectors.get(c.get("sector")) or {}).get("margin_shift_pt", 0.0))
        m = float(c["margin_pt"]) - shift
        if m <= 0:
            why = (f"margin {m:+.2f}pt after the sector tilt ({shift:+.2f}pt)" if shift
                   else f"margin {m:+.2f}pt not above the hurdle")
            dropped.append({"symbol": sym, "reason": why})
            continue
        e = plan.get(sym) or {}
        cost = e.get("cost")
        if cost is None:
            dropped.append({"symbol": sym, "reason": "no cost estimate"})
            continue
        flags = [f for f in DROP_FLAGS if f in cost.flags]
        if flags:
            dropped.append({"symbol": sym, "reason": ", ".join(flags)})
            continue
        rt = float(cost.round_trip_bps)
        net = m - rt / 100
        if net <= 0:
            dropped.append({"symbol": sym,
                            "reason": f"round trip {rt:.0f}bp eats the {m:.2f}pt margin"})
            continue
        rows.append({
            "symbol": sym, "style": style, "sector": c.get("sector"),
            "expected_pt": float(c["expected_pt"]), "margin_pt": m, "margin_shift_pt": shift,
            "net_margin_pt": net, "drivers": _drivers(style, c, hurdle_pt, shift),
            "risks": list(c.get("risks") or []),
            "price": None if cost.price is None else float(cost.price),
            "entry": _entry(e.get("levels")),
            "cost": {"order_idr": float(order_idr), "round_trip_bps": rt,
                     "flags": list(cost.flags)},
            "held": False, "held_idr": 0.0, "action": "watch", "size": None,
        })
    rows.sort(key=lambda r: (-r["margin_pt"], r["symbol"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    out["rows"], out["dropped"] = rows, dropped
    return out


def _size_rows(styles: Sequence[dict], factors: Mapping[str, Mapping],
               held: Mapping[str, float], ranking: Mapping[str, Mapping]) -> list[dict]:
    """One sizing row per symbol (its best margin across styles), plus every held name that a
    passing screen ranked but did not keep, marked as failing, so its trim says why."""
    best: dict[str, dict] = {}
    for s in styles:
        for r in s["rows"]:
            if r["symbol"] not in best or r["margin_pt"] > best[r["symbol"]]["margin_pt"]:
                best[r["symbol"]] = r
    out = [{**factors.get(sym, {}), "symbol": sym, "sector": r["sector"],
            "margin_pt": r["margin_pt"], "passes": True, "price": r["price"]
            or (factors.get(sym) or {}).get("price"), "style": r["style"]}
           for sym, r in best.items()]
    for sym in held:
        if sym not in best and sym in ranking:
            out.append({**factors.get(sym, {}), "symbol": sym, "passes": False,
                        "margin_pt": ranking[sym].get("margin_pt"),
                        "sector": ranking[sym].get("sector")})
    return out


def config(tilt_fp: str | None, caps: Mapping | None, screens: Mapping[str, Mapping],
           market: Mapping | None = None) -> dict:
    """What the payload and every journalled row carry besides the model fingerprint."""
    out = {"tilt_fingerprint": tilt_fp, "hurdle": dict(hurdle_mod.CONFIG),
           "sizing": sizing.config(caps), "tranche_idr": TRANCHE_IDR,
           "round_trips_per_year": 1,
           "screens": {k: dict(v.get("fingerprint") or {}) for k, v in sorted(screens.items())}}
    if market:
        out["market"] = dict(market)
    return out


def assemble(inp: UndervaluedInputs, *, day: date, stance: Mapping | None,
             portfolio_value_idr: float | None, holdings: Mapping[str, float],
             regime: Regime | str | None, fingerprint: str) -> dict:
    """Pure: one market's inputs + its stocks stance + layer 5 → the candidates payload."""
    t_passed, sectors, tilt_block = _tilt_view(inp.tilt, inp.tilt_note)
    order = [s for s in STYLES if s in inp.screens] + sorted(set(inp.screens) - set(STYLES))
    styles = [_style(s, inp.screens[s], sectors, inp.plan, inp.order_idr) for s in order]
    any_passed = any(s["passed"] for s in styles)

    ranking = {r["symbol"]: r for s in order if inp.screens[s].get("passed")
               for r in inp.screens[s].get("ranking") or []}
    caps = ({"sector_names": {k: v["cap"] for k, v in sectors.items()}} if t_passed else None)
    held = {k: float(v) for k, v in holdings.items() if v and v > 0}
    rows = _size_rows(styles, inp.factors, held, ranking)
    scale = costs.LOT // inp.lot  # P38 counts IDX lots: a lot of `inp.lot` shares is one share
    for r in rows:
        if scale != 1 and r.get("price"):
            r["price"] = r["price"] / scale
        if not inp.sector_buckets:
            r["sector"] = r.get("sector") or r["symbol"]
    plan = {k: {"levels": v.get("levels")} for k, v in inp.plan.items()}
    st = stance or {}
    sz = sizing.size(rows, st, portfolio_value_idr or 0.0, held if any_passed else {},
                     regime, caps=caps, entry=plan)
    # a held name no passing screen ranked has no rating here: no trim call, only the cap
    unrated = {x.symbol for x in sz.trims if x.symbol not in ranking and x.symbol not in
               {r["symbol"] for r in rows} and x.reason.startswith("trim in full")}
    trims = [x for x in sz.trims if x.symbol not in unrated]
    excluded = [*sz.excluded, *((sym, "held, not rated by any passing screen: no trim call")
                                for sym in sorted(unrated))]
    sized = {z.symbol: z for z in sz.sizes}
    sized_style = {r["symbol"]: r["style"] for r in rows if r.get("passes")}
    for s in styles:
        for r in s["rows"]:
            sym = r["symbol"]
            r["held"], r["held_idr"] = sym in held, held.get(sym, 0.0)
            z = sized.get(sym)
            if z is not None and sized_style.get(sym) == s["style"]:
                r["action"] = "add"
                r["size"] = {"idr": z.idr, "reason": z.reason,
                             "tranches": [{"day": x.day, "idr": x.idr,
                                           "shares": x.shares // scale,
                                           "limit": None if x.limit is None
                                           else x.limit * scale} for x in z.tranches]}
            else:
                r["action"] = "hold" if r["held"] else "watch"
                if z is not None:
                    r["drivers"].append(f"sized under {sized_style[sym]}")
    port = st.get("portfolio") or {}
    stale = list(inp.stale_inputs)
    for s in order:
        stale += inp.screens[s].get("stale_inputs") or []
    if inp.tilt is None and inp.tilt_note is None:
        stale.append("sector tilt (unavailable): no shift, default caps")
    elif inp.tilt is not None:
        stale += inp.tilt.get("stale_inputs") or []
    hurdles = [inp.screens[s] for s in order if inp.screens[s].get("hurdle_pt") is not None]
    h = hurdles[0] if hurdles else {}
    state = regime.state if isinstance(regime, Regime) else regime
    return {
        "schema_version": SCHEMA_VERSION,
        "market": inp.market,
        "as_of": day.isoformat(),
        "bar_date": inp.bar_date.isoformat() if inp.bar_date else None,
        "currency": "IDR",
        "model_fingerprint": fingerprint,
        "regime": state,
        "hurdle": {"required_pt": h.get("hurdle_pt"),
                   "drivers": list(h.get("hurdle_drivers") or [])},
        "stance": {"stance": st.get("stance"), "current_pct": port.get("current_pct"),
                   "target_pct": port.get("target_pct")},
        "tilt": tilt_block,
        "styles": styles,
        "sizing": {"portfolio_value_idr": portfolio_value_idr, "budget_idr": sz.budget_idr,
                   "unspent_idr": sz.unspent_idr,
                   "trims": [{"symbol": x.symbol, "idr": x.idr, "reason": x.reason}
                             for x in trims],
                   "excluded": [{"symbol": a, "reason": b} for a, b in excluded],
                   "fingerprint": sz.fingerprint},
        "config": config(tilt_block["fingerprint"], caps, inp.screens, inp.config),
        "stale_inputs": list(dict.fromkeys(stale)),
        "sources": list(dict.fromkeys([*inp.sources, "financer"])) or ["idx-method"],
        "disclaimer": DISCLAIMER,
    }


def top(payload: Mapping, n: int = 5) -> list[dict]:
    """Up to `n` rows taking each passing style's ranks in turn (rank 1 of every style, then
    rank 2, ...): the styles' margins are never compared with each other."""
    lists = [s["rows"] for s in payload["styles"] if s["passed"]]
    out: list[dict] = []
    for i in range(max((len(x) for x in lists), default=0)):
        for rows in lists:
            if i < len(rows) and len(out) < n:
                out.append(rows[i])
    return out


def telegram_lines(payloads: Sequence[Mapping], n: int = 5) -> list[str]:
    """A few lines per market for the Telegram summary: each style's verdict, then the top `n`."""
    lines: list[str] = []
    for p in payloads:
        verdicts = "; ".join(
            f"{s['style']} {len(s['rows'])}" if s["passed"] else f"{s['style']} failed"
            for s in p["styles"])
        lines.append(f"Undervalued {p['market']} ({verdicts}):")
        for r in top(p, n):
            size = f", add IDR {r['size']['idr'] / 1e6:,.1f}m" if r["size"] else ""
            held = ", held" if r["held"] else ""
            lines.append(f"  {r['symbol']:<5} {r['style']} #{r['rank']} margin "
                         f"{r['margin_pt']:+.1f}pt{held}{size}")
        if not top(p, n):
            lines.append("  no names")
    return lines


# ---------------- out/ ----------------


def _dumps(payload: Mapping) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write(payload: Mapping, out_dir: Path) -> Path:
    """`out/candidates/{MARKET}.json`, rewritten only when its bytes change."""
    path = Path(out_dir) / OUT_DIR / f"{payload['market']}.json"
    text = _dumps(payload)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path


def load_out(out_dir: Path) -> list[dict]:
    """Every schema-valid `out/candidates/*.json`, by market; invalid files are skipped."""
    d = Path(out_dir) / OUT_DIR
    if not d.is_dir():
        return []
    v = validator()
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not list(v.iter_errors(p)):
            out.append(p)
    return out


# ---------------- live ----------------


def gather_live(day: date, regime: Regime | str | None) -> UndervaluedInputs:
    """IDN's inputs from the real stores (read-only): idx-method's `factor_series`, screener,
    consensus and history through P36/P37's loaders (loaded once for both), the P34 hurdle on the
    screener's last bar date under this run's regime, P35's tilt as of `day`, and P21's entry
    plan for the screens' candidates. Each piece that fails becomes a stale input."""
    from assist.candidates import dividend_value, garp, tilt
    from assist.candidates.entry import entry_plan
    from assist.candidates.factors import load_factors
    from assist.candidates.screens import GATES
    from assist.sources.base import SourceUnavailable
    from assist.sources.idxmethod_stocks import SOURCE, IdxMethodStocks

    stale: list[str] = []
    stocks = IdxMethodStocks.from_config()
    data = dividend_value.load()
    table, st = load_factors(stocks, day)
    stale += st
    bar_dates = [r["bar_date"] for r in table.values() if r.get("bar_date")]
    as_of = max(bar_dates) if bar_dates else day
    flagged: set[str] = set()
    try:
        with (stocks.root / "data" / "special_boards.json").open(encoding="utf-8") as f:
            boards = json.load(f)
        flagged = {s for b in GATES["exclude_boards"] for s in boards.get(b, [])}
    except (OSError, ValueError):
        stale.append(f"{SOURCE} special_boards.json (missing)")
    consensus: dict[str, dict] = {}
    try:
        for sym, entry in stocks.consensus().items():
            c = garp.consensus_growth(entry)
            if c is not None:
                consensus[sym] = c
    except SourceUnavailable as e:
        stale.append(e.stale_input)
    h = hurdle_mod.hurdle("IDN", as_of, regime)
    screens: dict[str, dict] = {}
    for name, fn in (
        ("dividend_value", lambda: dividend_value.run(data, table, as_of=as_of, hurdle=h,
                                                      flagged=flagged)),
        ("garp", lambda: garp.run(data, table, as_of=as_of, hurdle=h, consensus=consensus,
                                  flagged=flagged)),
    ):
        try:
            screens[name] = fn()
        except Exception as e:  # noqa: BLE001 - one screen failing must not stop the run
            stale.append(f"undervalued {name} failed: {type(e).__name__}: {e}"[:200])
    t = None
    try:
        t = tilt.run_live(day)
    except Exception as e:  # noqa: BLE001
        stale.append(f"sector tilt failed: {type(e).__name__}: {e}"[:200])
    syms = sorted({c["symbol"] for s in screens.values() for c in s.get("candidates") or []})
    plan: dict[str, dict] = {}
    if syms:
        plan, st = entry_plan(stocks, symbols=syms, factors=table, as_of=as_of,
                              order_idr=TRANCHE_IDR)
        stale += st
    return UndervaluedInputs(
        market="IDN", bar_date=as_of, screens=screens, tilt=t,
        factors={s: table[s] for s in syms if s in table} | {
            s: table[s] for s in (r["symbol"] for x in screens.values()
                                  for r in x.get("ranking") or []) if s in table},
        plan=plan, stale_inputs=tuple(stale),
        sources=(SOURCE, "dbnomics", "idxscape", "bisfetcher", "bps-looker", "worldbankscape",
                 "sec-edgar"))


# ---------------- US (F6, PLAN S21) ----------------


def us_cost(row: Mapping, order_idr: float) -> costs.Cost | None:
    """One US tranche of about `order_idr` (row in IDR: price, med_value_60d, vol_1y): whole
    shares, `US_COST` fees and spread, P21's square-root impact. None without a price."""
    price = row.get("price")
    if not price or price <= 0:
        return None
    mv, vol = row.get("med_value_60d"), row.get("vol_1y")
    shares = int(order_idr // price)
    notional = shares * price
    flags = []
    if not mv or mv <= 0:
        flags.append("no_turnover")
    participation = notional / mv if mv and mv > 0 else None
    if participation is not None and participation > costs.MAX_PARTICIPATION:
        flags.append("over_participation")
    if shares == 0:
        flags.append("below_one_lot")
    fee = US_COST["broker_bps"] + US_COST["fx_bps"]
    return costs.Cost(price=float(price), shares=shares, notional=float(notional),
                      fee_buy_bps=fee, fee_sell_bps=fee, spread_bps=US_COST["half_spread_bps"],
                      impact_bps=costs.impact_bps(notional, mv, vol), amihud_impact_bps=None,
                      participation=participation, flags=tuple(flags))


def vol_1y(bars: Sequence[Any], as_of: date, sessions: int = 252) -> float | None:
    """Annualised stdev of daily log returns over the last `sessions` bars up to `as_of`
    (P39's split-adjusted engine bars); None with fewer than half a year of returns."""
    from math import log, sqrt
    from statistics import stdev

    px = [b.price for b in bars if b.date <= as_of and b.price and b.price > 0][-(sessions + 1):]
    rets = [log(b / a) for a, b in zip(px, px[1:], strict=False)]
    if len(rets) < sessions // 2:
        return None
    return stdev(rets) * sqrt(costs.YEAR)


def _us_row(r: Mapping, fx: float | None) -> dict:
    price = r.get("price")
    out = {**r, "expected_pt": r.get("expected_idr_pt"),
           "price": None if fx is None or price is None else price * fx}
    usd, m_usa, m_idn = r.get("expected_usd_pt"), r.get("margin_usa_pt"), r.get("margin_idn_pt")
    extra = []
    if price is not None:
        extra.append(f"US${price:,.2f} a share" + ("" if fx is None else f" at IDR {fx:,.0f}"))
    if usd is not None:
        line = f"expected {usd:.2f}% in USD"
        if m_usa is not None and m_idn is not None:
            line += f"; margin vs USA hurdle {m_usa:+.2f}pt, vs IDN {m_idn:+.2f}pt"
        extra.append(line)
    out["extra_drivers"] = extra
    return out


def us_inputs(results: Mapping[str, Mapping], *, idr_per_usd: float | None,
              vols: Mapping[str, float | None], bar_date: date | None,
              stale: Sequence[str] = (), sources: Sequence[str] = ()) -> UndervaluedInputs:
    """P39's `us_stocks.run` output per style → the USA list's inputs, in IDR (see *US* above).
    `vols` is `vol_1y` per symbol; `idr_per_usd` the rate on the last session."""
    fx = idr_per_usd
    screens: dict[str, dict] = {}
    factors: dict[str, dict] = {}
    for style, res in results.items():
        usa, idn = res.get("hurdle_pt"), res.get("idn_hurdle_pt")
        binding = None if usa is None or idn is None else max(usa, idn)
        drivers = list(res.get("hurdle_drivers") or [])
        if binding is not None:
            drivers.append(f"binding: {'IDN' if idn >= usa else 'USA'} {binding:.2f}% in IDR"
                           + ("" if res.get("usd_bar_pt") is None
                              else f" (a US name needs {res['usd_bar_pt']:.2f}% in USD)"))
        ranking = [_us_row(r, fx) for r in res.get("ranking") or []]
        screens[style] = {**res, "hurdle_pt": binding, "hurdle_drivers": drivers,
                          "ranking": ranking,
                          "candidates": [_us_row(r, fx) for r in res.get("candidates") or []]}
        for r in ranking:
            med = r.get("med_value")
            factors[r["symbol"]] = {
                "price": r["price"], "vol_1y": vols.get(r["symbol"]),
                "med_value_60d": None if fx is None or med is None else med * fx}
    syms = sorted({c["symbol"] for s in screens.values() for c in s["candidates"]})
    plan = {s: {"levels": None, "cost": us_cost(factors.get(s) or {}, TRANCHE_IDR)}
            for s in syms}
    st = list(stale)
    if fx is None:
        st.append("USD/IDR rate (JISDOR) unavailable: no US price in IDR, no name judged")
    return UndervaluedInputs(
        market="USA", bar_date=bar_date, screens=screens, tilt=None, factors=factors, plan=plan,
        stale_inputs=tuple(st), sources=tuple(sources), tilt_note=US_TILT_NOTE, lot=1,
        sector_buckets=False,
        config={"idr_per_usd": fx, "us_cost": dict(US_COST), "lot": 1,
                "sector_buckets": "one per name (no SIC in sec-edgar)"})


def _idr_per_usd(as_of: date) -> tuple[float | None, list[str]]:
    """JISDOR on or before `as_of` (idxscape, read-only), as P29 reads it."""
    from assist.layers import candidates_foreign as cf

    rd = cf._Reader(cf.default_sources(), as_of, [cf.JISDOR])
    rows = rd.series(cf.JISDOR)
    if not rows:
        return None, [*rd.stale, f"{cf.JISDOR.label}: no data"]
    stale = list(rd.stale)
    if (as_of - rows[-1].date).days > cf.JISDOR.max_age_days:
        stale.append(f"{cf.JISDOR.label} (stale, last {rows[-1].date})")
    return rows[-1].value, stale


def gather_live_usa(day: date, regime: Regime | str | None) -> UndervaluedInputs:
    """USA's inputs from the real stores (read-only): P39's universe, bars and point-in-time XBRL
    from sec-edgar, both styles against the P34 USA and IDN hurdles on the last session under
    this run's regime, and JISDOR for IDR. A missing store is a stale input, never a crash."""
    from assist.candidates import us_stocks
    from assist.candidates.hurdle import hurdles

    data = us_stocks.load(as_of=day)
    lasts = [b[-1].date for b in data.bars.values() if b]
    as_of = max(lasts) if lasts else day
    usa, idn = hurdles(["USA", "IDN"], as_of, regime)
    results = {s: us_stocks.run(s, data, as_of=as_of, usa=usa, idn=idn) for s in us_stocks.STYLES}
    fx, stale = _idr_per_usd(as_of)
    syms = {r["symbol"] for res in results.values() for r in res["ranking"]}
    vols = {s: vol_1y(data.bars.get(s) or [], as_of) for s in sorted(syms)}
    return us_inputs(results, idr_per_usd=fx, vols=vols, bar_date=max(lasts) if lasts else None,
                     stale=[*data.stale, *stale],
                     sources=tuple(dict.fromkeys(["sec-edgar", "idxscape", *usa.sources,
                                                  *idn.sources])))
