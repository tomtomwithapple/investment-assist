"""IDN stock screens (layer 4): dividend, value and momentum, each gated by a placebo control.

A fourth, S15's industry-relative value screen, lives in `candidates.industry_value` and joins
`run_screens`' results under the same gates, quality floor and placebo rule.

The rules are idx-method's former books, recovered from its git history (9a0ea38^) rather than
invented here:

- **dividend** (`paper/strategies.py` `Dividend`): trailing 12-month IDR dividends / price
  (`div_panel.trailing`, by ex-date, so point in time with no lag), one leg.
- **value**: book-to-price alone, the value leg idx-method found measured (`strategy.py`
  Tier 8 note; rank IC t 2.99 gated). Live from the screener's `pbv`; in the backtest from the
  last `bvps` knowable 120 days after its quarter end (`fundpanel.LAG_DAYS`).
- **momentum** (`Technical`): `mom_12_1` + `near_52w_high`, z-blended.

Order as `strategy.py` had it: structural gates first, then the solvency/quality floor (banks on
prudential metrics), then ranking: legs z-scored over the survivors, clipped at ±3, averaged;
the top 20 taken greedily with at most 5 names per sector.

**Placebo gate.** Each screen is replayed over month ends from `cache/history/` (point in time:
liquidity, price, volatility and trading-days gates, plus today's flagged boards as idx-method's
backtests did; the quality floor is current-only and is not replayed). Each month contributes
two observations: the top-quintile and the bottom-quintile mean next-month return, each in
excess of that month's pool mean. `assist.eval.placebo.evaluate` scores top vs bottom against
shuffled-return placebos and reruns the screen on shuffled returns as the control. A screen
whose verdict fails still runs and reports its ranking size, but names no candidate.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean, stdev

from assist.candidates.factors import YEAR, _cum, _signals, align, derive, enrich
from assist.eval.placebo import Verdict, evaluate
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_stocks import SOURCE, IdxMethodStocks

__all__ = [
    "BANK_FLOOR",
    "GATES",
    "LAG_DAYS",
    "MAX_PER_SECTOR",
    "MIN_POOL",
    "QEND",
    "QUALITY_FLOOR",
    "SCREENS",
    "TOP_N",
    "Screen",
    "blend",
    "book_per_share",
    "build_panel",
    "evaluate_screen",
    "passes_gates",
    "passes_quality",
    "rank_live",
    "run_screen",
    "run_screens",
    "screen_observations",
    "select",
    "trailing_dividend",
]

GATES = {
    "min_free_float": 15.0,  # %, IDX's own phased free-float rule
    "min_med_value_60d": 5e9,  # IDR/day, 60-day median (not the screener's 200-day mean)
    "min_price": 100.0,  # below this the tick grid dominates the spread
    "exclude_boards": ("FCA", "HSC", "NOTASI", "ABX"),
    "max_vol_1y": 0.96,  # ~80th pct: cut the wild tail, the vol/return relation is humped
    "min_days_traded_60": 45,
}
QUALITY_FLOOR = {"min_piotroski": 5, "min_altman_z": 1.8, "min_interest_cov": 1.5}
BANK_FLOOR = {"min_car": 14.0, "max_npl_gross": 5.0, "min_npl_coverage": 100.0,
              "max_ldr": 110.0, "min_roe": 5.0}
MAX_PER_SECTOR = 5
TOP_N = 20
MIN_POOL = 40  # names a month needs before it is scored (idx-method's backtests)
QUANTILES = 5
MIN_Z = 8  # values a leg needs before it is z-scored
LAG_DAYS = 120  # a quarter's book value is knowable this long after quarter end
QEND = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


@dataclass(frozen=True)
class Screen:
    name: str
    legs: tuple[tuple[str, int], ...]  # (key, sign): +1 means higher is better
    cadence: str
    description: str


SCREENS = {
    s.name: s
    for s in (
        Screen("dividend", (("div_yield_pit", 1),), "quarterly",
               "Trailing 12m IDR dividend yield alone (idx-method `dividend` book)."),
        Screen("value", (("bp", 1),), "quarterly",
               "Book-to-price alone, the value leg idx-method found measured."),
        Screen("momentum", (("mom_12_1", 1), ("near_52w_high", 1)), "monthly",
               "12-1 momentum + 52-week-high proximity (idx-method `technical` book)."),
    )
}


# ---------------- rule pieces ----------------


def passes_gates(sym: str, r: Mapping, flagged: Iterable[str]) -> tuple[bool, str | None]:
    """Structural gates, in idx-method's order; → (ok, first rule failed)."""
    if sym in flagged:
        return False, "flagged board"
    if (r.get("free_float") or 0) < GATES["min_free_float"]:
        return False, "free float"
    if (r.get("med_value_60d") or 0) < GATES["min_med_value_60d"]:
        return False, "liquidity"
    if (r.get("price") or 0) < GATES["min_price"]:
        return False, "price floor"
    if (r.get("vol_1y") or 0) > GATES["max_vol_1y"]:
        return False, "extreme volatility"
    if r.get("days_traded_60") is not None and r["days_traded_60"] < GATES["min_days_traded_60"]:
        return False, "trades too rarely"
    return True, None


def _passes_bank(r: Mapping) -> tuple[bool, str | None]:
    if (r.get("car") or 0) < BANK_FLOOR["min_car"]:
        return False, "CAR"
    npl = r.get("npl_gross") or r.get("npf_gross") or 0
    if npl > BANK_FLOOR["max_npl_gross"]:
        return False, "NPL"
    if npl > 0 and (r.get("npl_cov") or 0) < BANK_FLOOR["min_npl_coverage"]:
        return False, "NPL coverage"
    if (r.get("ldr") or 0) > BANK_FLOOR["max_ldr"]:
        return False, "LDR"
    if (r.get("roe") or 0) < BANK_FLOOR["min_roe"]:
        return False, "bank ROE"
    return True, None


def passes_quality(r: Mapping) -> tuple[bool, str | None]:
    """Solvency/quality floor; a bank (it reports a CAR) is judged on prudential metrics."""
    if r.get("car"):
        return _passes_bank(r)
    if (r.get("piotroski") or 0) < QUALITY_FLOOR["min_piotroski"]:
        return False, "F-score"
    if (r.get("altman_z") or -99) < QUALITY_FLOOR["min_altman_z"]:
        return False, "Altman Z"
    if (r.get("cfo_ttm") or 0) <= 0:
        return False, "negative CFO"
    der, ic = r.get("der") or 0, r.get("interest_cov")
    if der < 0:
        return False, "negative equity"
    if der > 0.05 and ic and ic < QUALITY_FLOOR["min_interest_cov"]:
        return False, "interest cover"
    return True, None


def trailing_dividend(recs: Iterable[Mapping], as_of: date, days: int = 365) -> float:
    """Sum of IDR dividends with ex-date in (as_of − days, as_of]."""
    lo = as_of - timedelta(days=days)
    return sum(
        r["value"]
        for r in recs
        if r.get("ccy") in (None, "CURRENCY_IDR") and lo < date.fromisoformat(r["ex"]) <= as_of
    )


def _available(period: str) -> date:
    m, d = QEND[int(period[-1])]
    return date(int(period[:4]), m, d) + timedelta(days=LAG_DAYS)


def book_per_share(fund: Mapping, as_of: date) -> float | None:
    """The latest `bvps` whose quarter was knowable on `as_of` (LAG_DAYS after quarter end)."""
    periods = (fund.get("periods") or {}).get("bs") or []
    vals = ((fund.get("items") or {}).get("bs") or {}).get("bvps") or []
    for p, v in reversed(list(zip(periods, vals, strict=False))):
        if v is not None and _available(p) <= as_of:
            return v
    return None


def _z(rows: Sequence[Mapping], key: str, sign: int) -> dict[str, float]:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if len(vals) < MIN_Z:
        return {}
    m, sd = fmean(vals), stdev(vals)
    if sd <= 0:
        return {}
    return {r["symbol"]: max(-3.0, min(3.0, sign * (r[key] - m) / sd))
            for r in rows if r.get(key) is not None}


def blend(rows: Sequence[Mapping], legs: Sequence[tuple[str, int]]) -> list[tuple]:
    """[(score, {leg: z}, row)] best first; a name missing any leg is left out."""
    zs = [_z(rows, k, s) for k, s in legs]
    out = []
    for r in rows:
        v = [z.get(r["symbol"]) for z in zs]
        if any(x is None for x in v):
            continue
        out.append((fmean(v), {k: v[i] for i, (k, _) in enumerate(legs)}, r))
    out.sort(key=lambda x: (-x[0], x[2]["symbol"]))
    return out


def _sector(sym: str, sectors: Mapping[str, str]) -> str:
    return sectors.get(sym) or "?" + sym  # no sector → its own bucket, never a shared one


def select(ranked: Sequence[tuple], top_n: int = TOP_N, sectors: Mapping[str, str] | None = None,
           max_per_sector: int | None = MAX_PER_SECTOR) -> list[Mapping]:
    """The best `top_n`, greedily, with no sector supplying more than `max_per_sector`."""
    sectors = sectors or {}
    picks: list[Mapping] = []
    counts: Counter = Counter()
    for _, _, r in ranked:
        s = _sector(r["symbol"], sectors)
        if max_per_sector and counts[s] >= max_per_sector:
            continue
        picks.append(r)
        counts[s] += 1
        if len(picks) >= top_n:
            break
    return picks


# ---------------- the point-in-time monthly panel ----------------


def _month_ends(dates: Sequence[date]) -> list[int]:
    """Indices of each month's last bar; a month with no later bar is still open, so left out."""
    return [i for i in range(len(dates) - 1) if dates[i + 1].month != dates[i].month]


def _pit_gate(s: Mapping) -> bool:
    return (
        (s.get("med_value_60d") or 0) >= GATES["min_med_value_60d"]
        and (s.get("price") or 0) >= GATES["min_price"]
        and (s.get("vol_1y") or 0) <= GATES["max_vol_1y"]
        and (s.get("days_traded_60") or 0) >= GATES["min_days_traded_60"]
    )


def build_panel(
    history: dict[str, list[dict]],
    dividends: Mapping[str, list] | None = None,
    fundamentals: Mapping[str, Mapping] | None = None,
    flagged: Iterable[str] = (),
    as_of: date | None = None,
    min_bars: int = 200,
) -> list[tuple[date, list[dict]]]:
    """→ [(month end, [rec])]: each gated name's signals at that month end plus `fwd`, its
    return to the next month end. Nothing after `as_of` is formed or used as a return.
    `div_yield_pit` / `bp` are None for a name the dividend / fundamentals cache doesn't hold."""
    dates, data = align(history, min_bars)
    flagged = set(flagged)
    dividends, fundamentals = dividends or {}, fundamentals or {}
    me = [i for i in _month_ends(dates) if as_of is None or dates[i] <= as_of]
    panel = []
    for i, j in zip(me, me[1:], strict=False):
        if i < YEAR:
            continue
        d = dates[i]
        recs = []
        for sym, series in data.items():
            if sym in flagged:
                continue
            s = _signals(series, i)
            if not s or not _pit_gate(s):
                continue
            fwd = _cum(series["ret"], i, j)
            if fwd is None:
                continue
            px = s["price"]
            divs = dividends.get(sym)
            bvps = book_per_share(fundamentals[sym], d) if sym in fundamentals else None
            recs.append({
                "symbol": sym, **s, "fwd": fwd,
                "div_yield_pit": trailing_dividend(divs, d) / px if divs is not None else None,
                "bp": bvps / px if bvps else None,
            })
        panel.append((d, recs))
    return panel


def screen_observations(
    screen: Screen, panel: Sequence[tuple[date, list[dict]]], min_pool: int = MIN_POOL
) -> tuple[list[bool], list[float], list[float]]:
    """→ (features, returns, monthly spreads). Per scored month: (True, top-quintile mean excess
    return), (False, bottom-quintile mean excess return); excess over the month's pool mean."""
    feats: list[bool] = []
    rets: list[float] = []
    spreads: list[float] = []
    for _, recs in panel:
        ranked = blend(recs, screen.legs)
        if len(ranked) < min_pool:
            continue
        cut = len(ranked) // QUANTILES
        mean = fmean(r["fwd"] for _, _, r in ranked)
        top = fmean(r["fwd"] for _, _, r in ranked[:cut]) - mean
        bot = fmean(r["fwd"] for _, _, r in ranked[-cut:]) - mean
        feats += [True, False]
        rets += [top, bot]
        spreads.append(top - bot)
    return feats, rets, spreads


def evaluate_screen(screen: Screen, panel: Sequence[tuple[date, list[dict]]],
                    min_pool: int = MIN_POOL, **kw) -> Verdict:
    """The placebo verdict on the screen's top-minus-bottom quintile edge. The screen is a fixed
    rule, so the procedure is its own signal; `kw` goes to `placebo.evaluate`."""
    feats, rets, _ = screen_observations(screen, panel, min_pool)
    return evaluate(lambda f, _r: list(f), feats, rets, **kw)


# ---------------- live ranking ----------------


def rank_live(
    screen: Screen,
    table: Mapping[str, Mapping],
    dividends: Mapping[str, list] | None,
    flagged: Iterable[str],
    as_of: date,
) -> tuple[list[tuple], Counter]:
    """Gate, floor and rank today's cross-section → (ranked, rejects by first rule failed)."""
    flagged = set(flagged)
    rows, rejects = [], Counter()
    for sym, r in sorted(table.items()):
        ok, why = passes_gates(sym, r, flagged)
        if ok:
            ok, why = passes_quality(r)
        if not ok:
            rejects[why] += 1
            continue
        rec = {**r, "symbol": sym}
        pbv, px = r.get("pbv"), r.get("price")
        rec["bp"] = 1.0 / pbv if pbv and pbv > 0 else None
        divs = (dividends or {}).get(sym)
        rec["div_yield_pit"] = (trailing_dividend(divs, as_of) / px
                                if divs is not None and px else None)
        rows.append(rec)
    return blend(rows, screen.legs), rejects


def run_screen(
    screen: Screen,
    table: Mapping[str, Mapping],
    panel: Sequence[tuple[date, list[dict]]],
    *,
    dividends: Mapping[str, list] | None = None,
    flagged: Iterable[str] = (),
    sectors: Mapping[str, str] | None = None,
    as_of: date,
    **kw,
) -> dict:
    """One screen: its placebo verdict, and candidates only if that verdict passed."""
    verdict = evaluate_screen(screen, panel, **kw)
    _, _, spreads = screen_observations(screen, panel, kw.get("min_pool", MIN_POOL))
    ranked, rejects = rank_live(screen, table, dividends, flagged, as_of)
    sectors = sectors or {}
    candidates = []
    if verdict.passed:
        by_sym = {r["symbol"]: (sc, z) for sc, z, r in ranked}
        for r in select(ranked, TOP_N, sectors, MAX_PER_SECTOR):
            sc, z = by_sym[r["symbol"]]
            candidates.append({
                "symbol": r["symbol"], "score": sc, "z": z,
                "sector": sectors.get(r["symbol"]),
                **{k: r.get(k) for k, _ in screen.legs},
                "price": r.get("price"), "med_value_60d": r.get("med_value_60d"),
            })
    return {
        "screen": screen.name,
        "description": screen.description,
        "legs": [list(leg) for leg in screen.legs],
        "cadence": screen.cadence,
        "passed": verdict.passed,
        "blocked": None if verdict.passed else verdict.reason,
        "verdict": {k: v for k, v in verdict.to_dict().items() if k != "control_ts"},
        "months": len(spreads),
        "spread_mean": fmean(spreads) if spreads else None,
        "spread_t": (fmean(spreads) / (stdev(spreads) / len(spreads) ** 0.5)
                     if len(spreads) > 2 and stdev(spreads) > 0 else None),
        "n_ranked": len(ranked),
        "rejects": dict(rejects),
        "candidates": candidates,
    }


def _optional(what: str, fn, stale: list[str]):
    try:
        return fn()
    except SourceUnavailable as e:
        stale.append(f"{e.source} {what} ({e.reason})")
        return None


def _data_json(stocks: IdxMethodStocks, name: str, stale: list[str]):
    path = stocks.root / "data" / name
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        stale.append(f"{SOURCE} {name} (missing)")
    except (OSError, ValueError):
        stale.append(f"{SOURCE} {name} (error)")
    return None


def run_screens(
    stocks: IdxMethodStocks | None = None,
    as_of: date | None = None,
    screens: Iterable[Screen] | None = None,
    *,
    industry: bool = True,
    **kw,
) -> dict:
    """Every screen over idx-method's files → {`as_of`, `screens`: {name: result},
    `stale_inputs`}. A missing input is a `stale_inputs` entry, never a crash; a screen whose
    inputs are missing fails its placebo on sample size and names no one. `industry` adds the
    fourth screen, S15's `industry_value`, over idx-method's `stockbiter.db` (read-only)."""
    stocks = stocks or IdxMethodStocks.from_config()
    screens = list(screens or SCREENS.values())
    stale: list[str] = []
    try:
        factors = stocks.factors()
        history = stocks.history(factors)
    except SourceUnavailable as e:
        factors, history = {}, {}
        stale.append(e.stale_input)
    dividends = fundamentals = boards = sectors = None
    if factors:
        dividends = _optional("dividends", lambda: stocks.dividends(factors), stale)
        fundamentals = _optional("fundamentals", lambda: stocks.fundamentals(factors), stale)
        boards = _data_json(stocks, "special_boards.json", stale)
        sectors = _data_json(stocks, "sectors.json", stale)
    flagged = {s for b in GATES["exclude_boards"] for s in (boards or {}).get(b, [])}
    table = enrich(factors, derive(history, as_of))
    bar_dates = [r["bar_date"] for r in table.values() if r.get("bar_date")]
    live_as_of = max(bar_dates) if bar_dates else as_of
    panel = build_panel(history, dividends, fundamentals, flagged, as_of) if history else []
    results = {
        s.name: run_screen(s, table, panel, dividends=dividends, flagged=flagged,
                           sectors=sectors, as_of=live_as_of or date.today(), **kw)
        for s in screens
    }
    if industry:
        from assist.candidates import industry_value
        from assist.sources.idxmethod_series import IdxMethodSeries

        day = live_as_of or as_of or date.today()
        data = (industry_value.load(IdxMethodSeries(stocks.root), day) if factors
                else industry_value.IndustryData())
        stale += [x for x in data.stale if x not in stale]
        results[industry_value.NAME] = industry_value.run(
            data, table, as_of=day, flagged=flagged, sectors=sectors, **kw)
    return {"as_of": live_as_of, "screens": results, "stale_inputs": stale}
