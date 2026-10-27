"""Undervalued growth screen, GARP, IDN (PLAN S19): growth at a price the hurdle allows.

- **Reverse DCF** (`implied_growth`): the constant 10-year growth of earnings that makes their
  present value equal today's mktcap, discounted at the P34 IDN hurdle. Each year pays out
  earnings × payout (trailing 12-month dividends over `ni_ttm`, clamped to [0, 1]); after year 10
  a terminal value of the next year's earnings over (hurdle − nominal GDP growth,
  `CONFIG["gdp_pt"]`). Solved by bisection inside `CONFIG["g_bounds"]` (an answer outside them
  is clamped to the bound). `implied_return` is the inverse: the IRR at a given growth.
- **Realised growth**: the 5-year CAGR of `ni_ttm` and of `cfo_ttm` (P33, the quarter 5 years
  before the latest one known), each needing positive values at both ends; realised = the lower
  of the two. A bank's CFO swings with deposits, so a bank's realised growth is `ni_ttm`'s alone.
- **Consensus** (`consensus_growth`): EPS CAGR from the last actual year to the furthest estimate
  in idx-method's `data/consensus.json`, plus forward PE (consensus price / next-year EPS) and PEG
  (forward PE / growth in pt) as the cross-check. Live only: there is no consensus history.
- **Gap** = min(realised, consensus) − implied, in pt (realised alone where there is no
  consensus); the live ranking is by gap. `realised_gap_pt` is realised − implied.
  **Expected return** = the IRR at that growth (capped at `CONFIG["growth_cap_pt"]`), and the
  margin is that minus the hurdle (`hurdle.margin`), for S20.
- **Quality gates**: positive `ni_ttm`; realised growth known; ROE (`ni_ttm` / `equity`) or
  `roce` not more than `stable_tol_pt` below its level 3 years earlier; `cfo_ttm` / `ni_ttm` ≥ 0.8
  (not for banks); equity dilution under 5% a year, from the share-count proxy `mktcap / price`
  3 years apart. Live, `screens.passes_gates` and `passes_quality` (or `BANK_FLOOR`) run first.

**Replay.** At each quarter end with a later one, every name passing the gates point in time and
the size floor (`replay_min_mktcap`) is ranked by its **realised** gap only: the consensus leg is
journalled live but never ranks in a replayed verdict (PLAN S19). The hurdle is one number for
the whole replay (`hurdle_pt`: today's, else `CONFIG["replay_hurdle_pt"]`), since P34 is not
replayed per quarter. Forward return, quintiles and placebo are those of P36
(`dividend_value`): price plus dividends gone ex in the quarter, top and bottom quintile mean
excess returns into `assist.eval.placebo.evaluate`. A failed verdict still reports the ranking,
but names no candidate. Candidates need a passed verdict, a hurdle, and a gap of at least
`min_gap_pt` ("clearly below").

`CONFIG` is hand-set, and this module sits under `candidates/`, so the journal's model
fingerprint (`journal.RULE_GLOBS`) changes when it does.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean, stdev

from assist.candidates.dividend_value import DividendData, _bar_at, _years_before, load
from assist.candidates.hurdle import Hurdle, margin
from assist.candidates.screens import (
    GATES,
    MAX_PER_SECTOR,
    QUANTILES,
    TOP_N,
    passes_gates,
    passes_quality,
    select,
    trailing_dividend,
)
from assist.eval.placebo import Verdict, evaluate
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_series import Bar, Fundamentals, quarter_ends
from assist.sources.idxmethod_stocks import SOURCE, IdxMethodStocks

__all__ = [
    "CONFIG",
    "Assessment",
    "assess",
    "cagr",
    "consensus_growth",
    "evaluate_replay",
    "implied_growth",
    "implied_return",
    "load",
    "observations",
    "pv",
    "rank_live",
    "realised_growth",
    "replay_panel",
    "run",
    "run_live",
]

CONFIG = {
    "years": 10,  # explicit growth years in the reverse DCF
    "gdp_pt": 8.0,  # IDN nominal GDP growth, % a year: the terminal growth
    "min_spread_pt": 1.0,  # hurdle − terminal growth below this: no reverse DCF
    "g_bounds": (-0.5, 1.0),  # bisection range for growth, fraction a year
    "growth_cap_pt": 25.0,  # the most growth the expected return may assume
    "cagr_years": 5,
    "quality_years": 3,
    "stable_tol_pt": 2.0,  # ROE / ROCE may fall this much and still count as stable
    "min_cfo_ni": 0.8,
    "max_dilution": 0.05,  # a year, share-count proxy
    "min_gap_pt": 2.0,  # implied growth "clearly below" realised and consensus
    "replay_hurdle_pt": 13.0,  # replay hurdle when today's is unknown
    "replay_min_mktcap": 1e12,  # IDR; the replay's liquidity stand-in
    "min_pool": 30,  # names a quarter needs before it is scored
}
_ITER = 80


# ---------------- reverse DCF ----------------


def pv(e0: float, payout: float, g: float, r: float, *, years: int = CONFIG["years"],
       g_terminal: float = CONFIG["gdp_pt"] / 100) -> float:
    """Present value at `r` of `years` of payouts on earnings growing at `g`, plus a terminal
    value of year `years + 1` earnings over (r − g_terminal). Fractions, not pt."""
    total, e, k = 0.0, e0, 1.0
    for _ in range(years):
        e *= 1 + g
        k /= 1 + r
        total += payout * e * k
    return total + e * (1 + g_terminal) / (r - g_terminal) * k


def _bisect(f: Callable[[float], float], lo: float, hi: float) -> float:
    """The root of an increasing `f` in [lo, hi], clamped to the bounds."""
    if f(lo) >= 0:
        return lo
    if f(hi) <= 0:
        return hi
    for _ in range(_ITER):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _terminal(r_pt: float | None, cfg: Mapping) -> float | None:
    if r_pt is None or r_pt - cfg["gdp_pt"] < cfg["min_spread_pt"]:
        return None
    return cfg["gdp_pt"] / 100


def implied_growth(mktcap: float, e0: float | None, payout: float, hurdle_pt: float | None,
                   cfg: Mapping = CONFIG) -> float | None:
    """The 10-year growth (pt) the price implies at the hurdle; None with no positive earnings,
    no hurdle, or a hurdle within `min_spread_pt` of nominal GDP growth."""
    gt = _terminal(hurdle_pt, cfg)
    if gt is None or e0 is None or e0 <= 0 or mktcap <= 0:
        return None
    r = hurdle_pt / 100
    lo, hi = cfg["g_bounds"]
    g = _bisect(lambda x: pv(e0, payout, x, r, years=cfg["years"], g_terminal=gt) - mktcap,
                lo, hi)
    return 100 * g


def implied_return(mktcap: float, e0: float | None, payout: float, growth_pt: float | None,
                   cfg: Mapping = CONFIG) -> float | None:
    """The discount rate (pt) at which earnings growing at `growth_pt` are worth `mktcap`."""
    if growth_pt is None or e0 is None or e0 <= 0 or mktcap <= 0:
        return None
    gt = cfg["gdp_pt"] / 100
    g = growth_pt / 100
    lo, hi = gt + cfg["min_spread_pt"] / 100, 1.0
    r = _bisect(lambda x: mktcap - pv(e0, payout, g, x, years=cfg["years"], g_terminal=gt),
                lo, hi)
    return 100 * r


# ---------------- growth legs ----------------


def cagr(first: float | None, last: float | None, years: float) -> float | None:
    """Compound growth in pt a year; None unless both ends are positive."""
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return 100 * ((last / first) ** (1 / years) - 1)


def _back(known: Sequence[Fundamentals], years: int) -> Fundamentals | None:
    """The quarter `years` before the latest known one (same quarter end)."""
    if not known:
        return None
    want = _years_before(known[-1].period, years)
    return next((f for f in reversed(known) if f.period == want), None)


def realised_growth(known: Sequence[Fundamentals], years: int = CONFIG["cagr_years"]
                    ) -> tuple[float | None, float | None]:
    """(`ni_ttm` CAGR, `cfo_ttm` CAGR) in pt over `years` to the latest known quarter."""
    then = _back(known, years)
    if then is None:
        return None, None
    now = known[-1]
    return cagr(then.ni_ttm, now.ni_ttm, years), cagr(then.cfo_ttm, now.cfo_ttm, years)


def consensus_growth(entry: Mapping | None) -> dict | None:
    """From one `consensus.json` entry → {growth_pt, fwd_eps, fwd_pe, peg, years}; None when it
    has no EPS forecast. Growth is the EPS CAGR from the last actual year to the furthest
    estimate (None unless both are positive)."""
    eps = sorted((entry or {}).get("forecast", {}).get("EPS") or [], key=lambda x: x["year"])
    actual = [x for x in eps if not x.get("est") and x.get("num") is not None]
    est = [x for x in eps if x.get("est") and x.get("num") is not None]
    if not actual or not est:
        return None
    a, nxt, far = actual[-1], est[0], est[-1]
    years = far["year"] - a["year"]
    growth = cagr(a["num"], far["num"], years)
    price = entry.get("price")
    fwd_pe = price / nxt["num"] if price and nxt["num"] > 0 else None
    peg = fwd_pe / growth if fwd_pe is not None and growth and growth > 0 else None
    return {"growth_pt": growth, "fwd_eps": nxt["num"], "fwd_pe": fwd_pe, "peg": peg,
            "years": years}


# ---------------- assess ----------------


@dataclass(frozen=True)
class Assessment:
    """One name on one date. Growth, gaps and returns in pt; ratios as fractions."""

    date: date
    bar_date: date
    price: float
    mktcap: float
    period: date | None
    ni_ttm: float | None
    payout: float
    implied_pt: float | None
    ni_cagr_pt: float | None
    cfo_cagr_pt: float | None
    realised_pt: float | None
    consensus_pt: float | None
    fwd_pe: float | None
    peg: float | None
    gap_pt: float | None
    realised_gap_pt: float | None
    expected_pt: float | None
    roe_pt: float | None
    roe_then_pt: float | None
    roce_pt: float | None
    roce_then_pt: float | None
    cfo_ni: float | None
    dilution_pt: float | None
    failed: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed

    def legs(self) -> dict:
        keys = ("payout", "implied_pt", "ni_cagr_pt", "cfo_cagr_pt", "realised_pt",
                "consensus_pt", "fwd_pe", "peg", "roe_pt", "roe_then_pt", "roce_pt",
                "roce_then_pt", "cfo_ni", "dilution_pt")
        return {k: getattr(self, k) for k in keys}


def _roe(f: Fundamentals | None) -> float | None:
    if f is None or f.ni_ttm is None or not f.equity or f.equity <= 0:
        return None
    return 100 * f.ni_ttm / f.equity


def _stable(now: float | None, then: float | None, tol: float) -> bool:
    return now is not None and then is not None and now >= then - tol


def assess(
    d: date,
    bars: Sequence[Bar],
    quarters: Sequence[Fundamentals],
    divs: Sequence[Mapping],
    *,
    hurdle_pt: float | None,
    bank: bool = False,
    consensus: Mapping | None = None,
    bar_dates: Sequence[date] | None = None,
    cfg: Mapping = CONFIG,
) -> Assessment | None:
    """The legs and quality gates of one name on `d`, point in time; None with no bar by `d`.
    `consensus` is a `consensus_growth` dict (live only)."""
    bar = _bar_at(bars, d, bar_dates)
    if bar is None:
        return None
    known = [f for f in quarters if f.available <= d]
    f = known[-1] if known else None
    ni = f.ni_ttm if f else None
    divs = [r for r in divs if r.get("value") is not None]
    paid = trailing_dividend(divs, d) / bar.price * bar.mktcap
    payout = max(0.0, min(1.0, paid / ni)) if ni and ni > 0 else 0.0

    implied = implied_growth(bar.mktcap, ni, payout, hurdle_pt, cfg)
    ni_g, cfo_g = realised_growth(known, cfg["cagr_years"])
    realised = ni_g if bank else (min(ni_g, cfo_g) if ni_g is not None and cfo_g is not None
                                  else None)
    cons = (consensus or {}).get("growth_pt")
    growth = realised if cons is None or realised is None else min(realised, cons)
    gap = None if growth is None or implied is None else growth - implied
    realised_gap = None if realised is None or implied is None else realised - implied
    expected = None
    if growth is not None and _terminal(hurdle_pt, cfg) is not None:
        expected = implied_return(bar.mktcap, ni, payout, min(growth, cfg["growth_cap_pt"]),
                                  cfg)

    then = _back(known, cfg["quality_years"])
    roe, roe_then = _roe(f), _roe(then)
    roce, roce_then = (f.roce if f else None), (then.roce if then else None)
    cfo_ni = f.cfo_ttm / ni if f and f.cfo_ttm is not None and ni and ni > 0 else None
    dilution = None
    old = _bar_at(bars, _years_before(d, cfg["quality_years"]), bar_dates)
    if old is not None and old.date < bar.date:
        ratio = (bar.mktcap / bar.price) / (old.mktcap / old.price)
        dilution = 100 * (ratio ** (1 / cfg["quality_years"]) - 1)

    failed: list[str] = []
    reasons: list[str] = []

    def fail(key: str, why: str) -> None:
        failed.append(key)
        reasons.append(why)

    if ni is None or ni <= 0:
        fail("no earnings", "no positive earnings (ni_ttm)")
    elif implied is None:
        fail("no hurdle", "no hurdle (or one within reach of nominal GDP growth)")
    if realised is None:
        fail("realised growth",
             f"no {cfg['cagr_years']}-year CAGR with ni_ttm{'' if bank else ' and cfo_ttm'}"
             " positive at both ends")
    tol = cfg["stable_tol_pt"]
    if not (_stable(roe, roe_then, tol) or _stable(roce, roce_then, tol)):
        fail("returns trend", f"ROE and ROCE not stable or rising over {cfg['quality_years']}y")
    if not bank and (cfo_ni is None or cfo_ni < cfg["min_cfo_ni"]):
        fail("accruals", f"cfo_ttm / ni_ttm below {cfg['min_cfo_ni']}")
    if dilution is not None and dilution >= 100 * cfg["max_dilution"]:
        fail("dilution", f"share count up {dilution:.1f}% a year")

    return Assessment(
        date=d, bar_date=bar.date, price=bar.price, mktcap=bar.mktcap,
        period=f.period if f else None, ni_ttm=ni, payout=payout, implied_pt=implied,
        ni_cagr_pt=ni_g, cfo_cagr_pt=cfo_g, realised_pt=realised, consensus_pt=cons,
        fwd_pe=(consensus or {}).get("fwd_pe"), peg=(consensus or {}).get("peg"), gap_pt=gap,
        realised_gap_pt=realised_gap, expected_pt=expected, roe_pt=roe, roe_then_pt=roe_then,
        roce_pt=roce, roce_then_pt=roce_then, cfo_ni=cfo_ni, dilution_pt=dilution,
        failed=tuple(failed), reasons=tuple(reasons),
    )


# ---------------- replay ----------------


def replay_panel(
    bars: Mapping[str, Sequence[Bar]],
    quarters: Mapping[str, Sequence[Fundamentals]],
    dividends: Mapping[str, Sequence[Mapping]],
    banks: Iterable[str] = (),
    *,
    hurdle_pt: float = CONFIG["replay_hurdle_pt"],
    min_mktcap: float = CONFIG["replay_min_mktcap"],
    cfg: Mapping = CONFIG,
) -> list[tuple[date, list[dict]]]:
    """→ [(quarter end, [{symbol, gap_pt, fwd}])]: the names passing the gates and size floor
    on that date, ranked on realised growth only, with the price-plus-dividend return to the
    next quarter end."""
    firsts = [b[0].date for b in bars.values() if b]
    lasts = [b[-1].date for b in bars.values() if b]
    if not firsts:
        return []
    qes = quarter_ends(min(firsts), max(lasts))
    banks = set(banks)
    dates = {s: [b.date for b in bs] for s, bs in bars.items()}
    panel = []
    for q, q1 in zip(qes, qes[1:], strict=False):
        recs = []
        for sym, bs in bars.items():
            divs = dividends.get(sym) or []
            a = assess(q, bs, quarters.get(sym, ()), divs, hurdle_pt=hurdle_pt,
                       bank=sym in banks, bar_dates=dates[sym], cfg=cfg)
            if a is None or not a.ok or a.mktcap < min_mktcap or a.price < GATES["min_price"]:
                continue
            if a.bar_date < q - timedelta(days=10):
                continue  # no trading near the quarter end
            end = _bar_at(bs, q1, dates[sym])
            if end is None or end.date <= q:
                continue
            paid = sum(r["value"] for r in divs if r.get("value") is not None
                       and a.bar_date < date.fromisoformat(r["ex"]) <= end.date)
            recs.append({"symbol": sym, "gap_pt": a.realised_gap_pt,
                         "fwd": (end.price + paid) / a.price - 1})
        panel.append((q, recs))
    return panel


def observations(
    panel: Sequence[tuple[date, list[dict]]], min_pool: int = CONFIG["min_pool"]
) -> tuple[list[bool], list[float], list[float]]:
    """→ (features, returns, quarterly spreads), as `dividend_value.observations` but ranked by
    gap: per scored quarter, (True, top-quintile mean excess return), (False, bottom's)."""
    feats: list[bool] = []
    rets: list[float] = []
    spreads: list[float] = []
    for _, recs in panel:
        if len(recs) < min_pool:
            continue
        ranked = sorted(recs, key=lambda r: (-r["gap_pt"], r["symbol"]))
        cut = len(ranked) // QUANTILES
        mean = fmean(r["fwd"] for r in ranked)
        top = fmean(r["fwd"] for r in ranked[:cut]) - mean
        bot = fmean(r["fwd"] for r in ranked[-cut:]) - mean
        feats += [True, False]
        rets += [top, bot]
        spreads.append(top - bot)
    return feats, rets, spreads


def evaluate_replay(panel: Sequence[tuple[date, list[dict]]],
                    min_pool: int = CONFIG["min_pool"], **kw) -> Verdict:
    """The placebo verdict on the top-minus-bottom quintile edge; `kw` goes to `evaluate`."""
    feats, rets, _ = observations(panel, min_pool)
    return evaluate(lambda f, _r: list(f), feats, rets, **kw)


# ---------------- live ----------------


def rank_live(
    table: Mapping[str, Mapping],
    data: DividendData,
    as_of: date,
    hurdle: Hurdle | None,
    *,
    consensus: Mapping[str, Mapping] | None = None,
    flagged: Iterable[str] = (),
    cfg: Mapping = CONFIG,
) -> tuple[list[dict], Counter]:
    """Gate and rank today's cross-section → (rows biggest gap first, rejects by first rule
    failed). `consensus` maps a symbol to its `consensus_growth` dict."""
    flagged = set(flagged)
    consensus = consensus or {}
    required = hurdle.required if hurdle is not None else None
    rows, rejects = [], Counter()
    for sym, r in sorted(table.items()):
        ok, why = passes_gates(sym, r, flagged)
        if ok:
            ok, why = passes_quality(r)
        if not ok:
            rejects[why] += 1
            continue
        a = assess(as_of, data.bars.get(sym, []), data.quarters.get(sym, []),
                   data.dividends.get(sym, []), hurdle_pt=required, bank=bool(r.get("car")),
                   consensus=consensus.get(sym), cfg=cfg)
        if a is None:
            rejects["no price history"] += 1
            continue
        if not a.ok:
            rejects[a.failed[0]] += 1
            continue
        risks = []
        if a.consensus_pt is None:
            risks.append("no consensus: realised growth only")
        elif a.consensus_pt < a.realised_pt:
            risks.append(f"consensus {a.consensus_pt:.1f}% below realised {a.realised_pt:.1f}%")
        rows.append({
            "symbol": sym, "sector": data.sectors.get(sym), "bank": bool(r.get("car")),
            "gap_pt": a.gap_pt, "realised_gap_pt": a.realised_gap_pt,
            "expected_pt": a.expected_pt, "margin_pt": margin(a.expected_pt, hurdle),
            "legs": a.legs(), "price": a.price, "mktcap": a.mktcap, "bar_date": a.bar_date,
            "period": a.period, "risks": risks, "reasons": list(a.reasons),
        })
    rows.sort(key=lambda x: (-x["gap_pt"], x["symbol"]))
    return rows, rejects


def run(
    data: DividendData,
    table: Mapping[str, Mapping],
    *,
    as_of: date,
    hurdle: Hurdle | None,
    consensus: Mapping[str, Mapping] | None = None,
    panel: Sequence[tuple[date, list[dict]]] | None = None,
    flagged: Iterable[str] = (),
    cfg: Mapping = CONFIG,
    **kw,
) -> dict:
    """The screen: replay verdict (realised growth only), today's ranking, and candidates only
    when the verdict passed, the hurdle is known and the gap is at least `min_gap_pt`. `kw`
    goes to `evaluate`."""
    stale = list(data.stale)
    required = hurdle.required if hurdle is not None else None
    if hurdle is not None:
        stale += list(hurdle.stale_inputs)
    if required is None:
        stale.append("IDN hurdle unavailable: no reverse DCF, no candidate")
    if not consensus:
        stale.append(f"{SOURCE} consensus.json (missing or empty): realised growth only")
    banks = {s for s, r in table.items() if r.get("car")}
    if panel is None:
        h = required if required is not None else cfg["replay_hurdle_pt"]
        panel = replay_panel(data.bars, data.quarters, data.dividends, banks, hurdle_pt=h,
                             cfg=cfg)
    min_pool = kw.pop("min_pool", cfg["min_pool"])
    verdict = evaluate_replay(panel, min_pool=min_pool, **kw)
    _, _, spreads = observations(panel, min_pool)
    rows, rejects = rank_live(table, data, as_of, hurdle, consensus=consensus, flagged=flagged,
                              cfg=cfg)
    candidates: list[dict] = []
    if verdict.passed and required is not None:
        clear = [(r["gap_pt"], {}, r) for r in rows if r["gap_pt"] >= cfg["min_gap_pt"]]
        candidates = list(select(clear, TOP_N, data.sectors, MAX_PER_SECTOR))
    return {
        "screen": "garp",
        "as_of": as_of,
        "passed": verdict.passed,
        "blocked": None if verdict.passed else verdict.reason,
        "verdict": {k: v for k, v in verdict.to_dict().items() if k != "control_ts"},
        "replay_basis": "realised growth only",
        "quarters": len(spreads),
        "spread_mean": fmean(spreads) if spreads else None,
        "spread_t": (fmean(spreads) / (stdev(spreads) / len(spreads) ** 0.5)
                     if len(spreads) > 2 and stdev(spreads) > 0 else None),
        "hurdle_pt": required,
        "hurdle_drivers": list(hurdle.drivers) if hurdle is not None else [],
        "consensus_names": len(consensus or {}),
        "pool": len(rows),
        "rejects": dict(rejects),
        "ranking": rows,
        "candidates": candidates,
        "fingerprint": dict(cfg),
        "stale_inputs": list(dict.fromkeys(stale)),
    }


def run_live(as_of: date | None = None, regime=None, **kw) -> dict:
    """The screen over the real stores (read-only): idx-method's `factor_series`, screener and
    `consensus.json`, and the P34 IDN hurdle on the screener's last bar date under `regime`
    (default: P8's)."""
    from assist.candidates.factors import load_factors
    from assist.candidates.hurdle import hurdle as idn_hurdle

    stocks = IdxMethodStocks.from_config()
    data = load()
    table, stale = load_factors(stocks, as_of)
    data.stale += stale
    bar_dates = [r["bar_date"] for r in table.values() if r.get("bar_date")]
    as_of = max(bar_dates) if bar_dates else (as_of or date.today())
    consensus: dict[str, dict] = {}
    try:
        for sym, entry in stocks.consensus().items():
            c = consensus_growth(entry)
            if c is not None:
                consensus[sym] = c
    except SourceUnavailable as e:
        data.stale.append(e.stale_input)
    flagged: set[str] = set()
    try:
        with (stocks.root / "data" / "special_boards.json").open() as f:
            boards = json.load(f)
        flagged = {s for b in GATES["exclude_boards"] for s in boards.get(b, [])}
    except (OSError, ValueError):
        data.stale.append(f"{SOURCE} special_boards.json (missing)")
    if regime is None:
        from assist.layers.regime import regime as current_regime

        regime = current_regime(as_of)
    h = idn_hurdle("IDN", as_of, regime)
    return run(data, table, as_of=as_of, hurdle=h, consensus=consensus, flagged=flagged, **kw)
