"""S105 (P126-flow-inventory): what the sibling stores hold on money flow per IDN name.

Read-only and never fatal: a store or table that is missing or locked gives that section
`status: missing | locked | error` and the legs that need it the verdict `no data`. Nothing here
is hashed by `journal.RULE_GLOBS` and `assist run` never calls it; `assist flow-inventory` prints
the report and writes `docs/results/P126-flow-inventory.md`.

Sections, by store:

- `foreign_flow`: idxscape `stock_summary`, the foreign buy / sell columns per code and day.
- `cross_check`: the same net foreign flow from idx-method `bars.net_foreign` (Stockbit), by
  sign per name and day, and the names that agree least.
- `bars`: idx-method daily bars (traded value on up and down days).
- `ownership`: kseistat `holdings` per stock, origin and investor type, and how long after
  month end each file was loaded (the point-in-time lag).
- `insider`: idx-method `insider_history`, action types and how many rows are market trades
  with a parseable share change.
- `register`, `broker_top`, `screeners`: context sources too short to test.

`verdicts` judges phase S's four legs against fixed minimums (constants below): `usable`,
`too short`, `check first` (the two foreign-flow sources disagree) or `no data`.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median_low

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import SourceUnavailable, duckdb_ro, sqlite_ro

__all__ = ["Stores", "build", "markdown", "verdicts"]

DB = "store/data/stockbiter.db"
COMPOSITION = "data/composition.json"
MIN_FLOW_DAYS = 750  # ~3 years of sessions: 12 independent 3-month windows
MIN_KSEI_MONTHS = 36
MIN_INSIDER_TRADES = 1000
MIN_SIGN_AGREEMENT = 0.80
MIN_NAME_DAYS = 100  # a name needs this many overlapping days to be ranked in `worst`
MARKET_ACTIONS = ("ACTION_TYPE_BUY", "ACTION_TYPE_SELL", "BUY", "SELL")
FLOW_CATEGORIES = ("foreign flow", "bandarmology")
_NUM = re.compile(r"^[+-]?[\d,.]+$")


@dataclass(frozen=True)
class Stores:
    idxscape: Path
    kseistat: Path
    idx_method: Path

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> Stores:
        env = {**os.environ, **(env or {})}
        loc = {s.name: s.location for s in load_sources(config, env=env)}
        return cls(Path(loc["idxscape"]), Path(loc["kseistat"]), Path(loc["idx-method"]))


def _guard(fn: Callable[[], dict]) -> dict:
    try:
        return {"status": "present", **fn()}
    except SourceUnavailable as e:
        return {"status": e.reason, "detail": str(e)}


def _need(have: set[str], source: str, *tables: str) -> None:
    for t in tables:
        if t not in have:
            raise SourceUnavailable(source, "missing", f"no table {t}")


def _iso(d) -> str | None:
    return None if d is None else str(d)[:10]


def _sqlite_tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}


def _duck_tables(con) -> set[str]:
    return {r[0] for r in con.execute(
        "select table_name from information_schema.tables").fetchall()}


# ---------------- idxscape ----------------


def _foreign_flow(path: Path) -> dict:
    with duckdb_ro(path, "idxscape") as con:
        _need(_duck_tables(con), "idxscape", "stock_summary")
        traded = "(foreign_buy_shares + foreign_sell_shares) > 0"
        r = con.execute(
            "select min(trade_date), max(trade_date), count(distinct trade_date),"
            " count(distinct code), count(*),"
            f" count(*) filter (where {traded}),"
            f" count(distinct code) filter (where {traded}),"
            " count(*) filter (where net_foreign_shares <> 0 and net_foreign_value_est_idr = 0),"
            " sum(coalesce(non_regular_value_idr, 0))::double / nullif(sum(value_idr), 0),"
            " count(*) filter (where coalesce(non_regular_value_idr, 0) * 2 > value_idr)"
            " from stock_summary"
        ).fetchone()
        years = con.execute(
            "select year(trade_date), count(distinct trade_date) from stock_summary"
            " group by 1 order by 1").fetchall()
    return {
        "first": _iso(r[0]), "last": _iso(r[1]), "days": r[2], "codes": r[3], "rows": r[4],
        "rows_with_foreign_trade": r[5], "codes_with_foreign_trade": r[6],
        "net_value_zero_when_shares_nonzero": r[7],
        "non_regular_share_of_value": None if r[8] is None else round(r[8], 4),
        "name_days_non_regular_over_half": r[9],
        "days_by_year": {str(y): n for y, n in years},
    }


def _idxscape_net(path: Path) -> dict[tuple[str, str], float]:
    with duckdb_ro(path, "idxscape") as con:
        _need(_duck_tables(con), "idxscape", "stock_summary")
        return {(c, _iso(d)): float(v) for c, d, v in con.execute(
            "select code, trade_date, net_foreign_value_est_idr from stock_summary").fetchall()}


# ---------------- idx-method ----------------


def _bars(root: Path) -> tuple[dict, dict[tuple[str, str], float]]:
    with sqlite_ro(root / DB, "idx-method") as con:
        _need(_sqlite_tables(con), "idx-method", "bars")
        net: dict[tuple[str, str], float] = {}
        days: set[str] = set()
        with_value = 0
        # the newest run wins where a day was stored by more than one
        for sym, d, value, nf in con.execute(
                "select symbol, date, value, net_foreign from bars order by run_id"):
            days.add(d)
            with_value += value is not None
            if nf is not None:
                net[(sym, d[:10])] = float(nf)
    info = {"first": min(days, default=None), "last": max(days, default=None), "days": len(days),
            "names": len({k[0] for k in net}), "rows_with_net_foreign": len(net),
            "rows_with_value": with_value}
    return info, net


def _cross_check(a: dict[tuple[str, str], float], b: dict[tuple[str, str], float],
                 min_days: int) -> dict:
    per: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # code -> [both nonzero, same sign]
    ratios: list[float] = []
    both = 0
    keys = a.keys() & b.keys()
    for k in keys:
        x, y = a[k], b[k]
        if x and y:
            both += 1
            per[k[0]][0] += 1
            per[k[0]][1] += (x > 0) == (y > 0)
            ratios.append(round(abs(y) / abs(x), 4))
    agree = sum(v[1] for v in per.values())
    ranked = sorted(((c, n, s / n) for c, (n, s) in per.items() if n >= min_days),
                    key=lambda t: (t[2], t[0]))
    days = sorted({k[1] for k in keys})
    return {
        "first": days[0] if days else None, "last": days[-1] if days else None,
        "names": len({k[0] for k in keys}), "name_days": len(keys), "both_nonzero": both,
        "sign_agreement": round(agree / both, 4) if both else None,
        "median_abs_ratio": median_low(ratios) if ratios else None,
        "names_below_80pct": sum(1 for t in ranked if t[2] < MIN_SIGN_AGREEMENT),
        "worst": [{"code": c, "days": n, "sign_agreement": round(s, 4)} for c, n, s in ranked[:10]],
    }


def _insider(root: Path) -> dict:
    actions: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    symbols: set[str] = set()
    dates: list[str] = []
    market = parsed = 0
    with sqlite_ro(root / DB, "idx-method") as con:
        _need(_sqlite_tables(con), "idx-method", "insider_history")
        for d, sym, raw in con.execute("select date, symbol, raw from insider_history"):
            try:
                r = json.loads(raw)
            except (TypeError, ValueError):
                r = {}
            act = str(r.get("action_type") or "unknown")
            actions[act] += 1
            sources[str((r.get("data_source") or {}).get("type") or "unknown")] += 1
            dates.append(d)
            if sym:
                symbols.add(sym)
            if act in MARKET_ACTIONS:
                market += 1
                parsed += bool(_NUM.match(str((r.get("changes") or {}).get("value") or "")))
    by_year = Counter(d[:4] for d in dates)
    return {"rows": len(dates), "first": min(dates, default=None), "last": max(dates, default=None),
            "symbols": len(symbols), "actions": dict(sorted(actions.items())),
            "sources": dict(sorted(sources.items())), "market_trades": market,
            "changes_parsed": parsed, "rows_by_year": dict(sorted(by_year.items()))}


def _broker_top(root: Path) -> dict:
    with sqlite_ro(root / DB, "idx-method") as con:
        _need(_sqlite_tables(con), "idx-method", "api_raw")
        n, first, last = con.execute(
            "select count(distinct date), min(date), max(date) from api_raw"
            " where endpoint = 'broker_top'").fetchone()
    return {"days": n, "first": first, "last": last}


def _screeners(root: Path) -> dict:
    marks = ",".join("?" * len(FLOW_CATEGORIES))
    with sqlite_ro(root / DB, "idx-method") as con:
        _need(_sqlite_tables(con), "idx-method", "screener_preset", "screener_member")
        where = f"lower(category) in ({marks})"
        days, first, last = con.execute(
            f"select count(distinct date), min(date), max(date) from screener_preset where {where}",
            FLOW_CATEGORIES).fetchone()
        names = [f"{c}: {n}" for c, n in con.execute(
            f"select distinct category, name from screener_preset where {where} and date = ?"
            " order by 1, 2", (*FLOW_CATEGORIES, last))]
        members = con.execute(
            "select count(distinct m.symbol) from screener_member m join screener_preset p"
            " on p.date = m.date and p.screener_id = m.screener_id"
            f" where {where.replace('category', 'p.category')} and m.date = ?",
            (*FLOW_CATEGORIES, last)).fetchone()[0]
    return {"days": days, "first": first, "last": last, "screeners": names,
            "names_latest": members}


def _register(root: Path) -> dict:
    path = root / COMPOSITION
    if not path.is_file():
        raise SourceUnavailable("idx-method", "missing", f"no {path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise SourceUnavailable("idx-method", "error", f"{path}: {e}") from e
    rows = [v for v in doc.values() if isinstance(v, dict) and "holders" in v]
    labels = Counter(k for v in rows for k in v["holders"])
    windows = [v["window"] for v in rows if v.get("window")]
    return {"names": len(rows),
            "report_dates": dict(sorted(Counter(v.get("report_date") for v in rows).items())),
            "window_first": min((w[0] for w in windows), default=None),
            "window_last": max((w[1] for w in windows), default=None),
            "labels": dict(labels.most_common(12))}


# ---------------- kseistat ----------------


def _ownership(path: Path) -> dict:
    with duckdb_ro(path, "kseistat") as con:
        have = _duck_tables(con)
        _need(have, "kseistat", "holdings")
        months, first, last = con.execute(
            "select count(distinct date), min(date), max(date) from holdings").fetchone()
        codes = con.execute(
            "select count(distinct code) from holdings where date = ?", [last]).fetchone()[0]
        types: dict[str, list[str]] = defaultdict(list)
        for o, t in con.execute(
                "select distinct origin, investor_type from holdings order by 1, 2").fetchall():
            types[o].append(t)
        lags: list[int] = []
        if "loads" in have:
            lags = [r[0] for r in con.execute(
                "select date_diff('day', l.date, cast(l.loaded_at as date)) from loads l"
                " where l.loaded_at is not null and l.date in (select distinct date from holdings)"
            ).fetchall()]
    return {"months": months, "first": _iso(first), "last": _iso(last), "codes_latest": codes,
            "investor_types": dict(types), "months_with_load_date": len(lags),
            "median_load_lag_days": median_low(lags) if lags else None,
            "max_load_lag_days": max(lags, default=None),
            "stock_view": "v_stock_composition" in have}


# ---------------- report ----------------


def _leg(verdict: str, why: str) -> dict:
    return {"verdict": verdict, "why": why}


def _short(sec: dict | None, key: str, need: int, unit: str) -> dict | None:
    """None when the section holds enough; else the `no data` / `too short` verdict."""
    if not sec or sec.get("status") != "present":
        return _leg("no data", (sec or {}).get("detail") or "store not read")
    have = sec.get(key) or 0
    if have < need:
        return _leg("too short", f"{have} {unit}, needs {need}")
    return None


def verdicts(inv: dict) -> dict[str, dict]:
    """Phase S's four legs against the fixed minimums."""
    out: dict[str, dict] = {}
    ff, cc = inv.get("foreign_flow"), inv.get("cross_check") or {}
    acc = _short(ff, "days", MIN_FLOW_DAYS, "trading days")
    if acc is None:
        agree = cc.get("sign_agreement")
        if agree is not None and agree < MIN_SIGN_AGREEMENT:
            acc = _leg("check first", f"idx-method agrees in sign on {agree:.0%} of name-days, "
                                      f"needs {MIN_SIGN_AGREEMENT:.0%}")
        else:
            note = "no cross-check" if agree is None else f"sign agreement {agree:.0%}"
            acc = _leg("usable", f"{ff['days']} trading days; {note}")
    out["accumulation"] = acc
    bars = inv.get("bars")
    out["supply_demand"] = _short(bars, "days", MIN_FLOW_DAYS, "trading days") or _leg(
        "usable", f"{bars['days']} trading days of bars")
    own = inv.get("ownership")
    out["ownership"] = _short(own, "months", MIN_KSEI_MONTHS, "months") or _leg(
        "usable", f"{own['months']} months")
    ins = inv.get("insider")
    leg = _short(ins, "market_trades", MIN_INSIDER_TRADES, "market trades")
    if leg is None and ins["changes_parsed"] < MIN_INSIDER_TRADES:
        leg = _leg("too short", f"{ins['changes_parsed']} trades with a readable share change, "
                                f"needs {MIN_INSIDER_TRADES}")
    out["insider"] = leg or _leg("usable", f"{ins['market_trades']} market trades")
    return out


def build(stores: Stores, min_days: int = MIN_NAME_DAYS) -> dict:
    inv: dict = {"foreign_flow": _guard(lambda: _foreign_flow(stores.idxscape))}
    nets: dict = {}

    def bars() -> dict:
        info, nets["b"] = _bars(stores.idx_method)
        return info

    inv["bars"] = _guard(bars)

    def cross() -> dict:
        if "b" not in nets:
            b = inv["bars"]
            raise SourceUnavailable("idx-method", b["status"], b.get("detail", ""))
        return _cross_check(_idxscape_net(stores.idxscape), nets["b"], min_days)

    inv["cross_check"] = _guard(cross)
    inv["ownership"] = _guard(lambda: _ownership(stores.kseistat))
    inv["insider"] = _guard(lambda: _insider(stores.idx_method))
    inv["register"] = _guard(lambda: _register(stores.idx_method))
    inv["broker_top"] = _guard(lambda: _broker_top(stores.idx_method))
    inv["screeners"] = _guard(lambda: _screeners(stores.idx_method))
    inv["legs"] = verdicts(inv)
    return inv


TITLES = (("foreign_flow", "Foreign flow (idxscape `stock_summary`)"),
          ("cross_check", "Cross-check (idx-method `bars.net_foreign` vs idxscape)"),
          ("bars", "Daily bars (idx-method `bars`)"),
          ("ownership", "Ownership (kseistat `holdings`)"),
          ("insider", "Insider and major holders (idx-method `insider_history`)"),
          ("register", "Shareholder register (idx-method `composition.json`)"),
          ("broker_top", "Broker top (idx-method `api_raw`)"),
          ("screeners", "Screeners (idx-method Foreign Flow and Bandarmology)"))


def _cell(v) -> str:
    if isinstance(v, dict):
        return ", ".join(f"{k} {_cell(x)}" for k, x in v.items()) or "none"
    if isinstance(v, list):
        return ", ".join(map(str, v)) or "none"
    return "n/a" if v is None else str(v)


def markdown(inv: dict, day: date) -> str:
    out = ["# P126 flow inventory", "",
           f"Read-only inventory of per-name money-flow data, run {day.isoformat()} by "
           "`assist flow-inventory` (S105). Minimums: "
           f"{MIN_FLOW_DAYS} trading days, {MIN_KSEI_MONTHS} KSEI months, "
           f"{MIN_INSIDER_TRADES} insider market trades, {MIN_SIGN_AGREEMENT:.0%} sign agreement.",
           "", "## Legs", "", "| Leg | Verdict | Why |", "|---|---|---|"]
    out += [f"| {k} | {v['verdict']} | {v['why']} |" for k, v in inv["legs"].items()]
    for key, title in TITLES:
        sec = inv[key]
        out += ["", f"## {title}", ""]
        if sec["status"] != "present":
            out.append(f"{sec['status']}: {sec.get('detail', '')}".rstrip())
            continue
        out += ["| Field | Value |", "|---|---|"]
        out += [f"| {k} | {_cell(v)} |" for k, v in sec.items() if k not in ("status", "worst")]
        if sec.get("worst"):
            out += ["", "Names that agree least:", "", "| Code | Days | Sign agreement |",
                    "|---|---|---|"]
            out += [f"| {w['code']} | {w['days']} | {w['sign_agreement']:.0%} |"
                    for w in sec["worst"]]
    return "\n".join(out) + "\n"
