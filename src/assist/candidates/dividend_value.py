"""Undervalued dividend screen, IDN (PLAN S18): the dividend return beats the hurdle and is safe.

- **Expected return** (Gordon, in pt a year) = forward yield + sustainable growth. The forward
  yield is the trailing 12-month IDR dividend by ex-date over price (`screens.trailing_dividend`);
  g = ROE × (1 − payout), floored at 0 and capped at IDN nominal GDP growth
  (`CONFIG["g_cap_pt"]`). ROE = `ni_ttm` / `equity` and payout = dividends paid / `ni_ttm`, from
  the last quarter P33 makes available by the date (period end + `LAG_DAYS`).
- **Safety gates**: payout below 90% of `ni_ttm`; dividends covered by `cfo_ttm` (not for banks,
  whose CFO swings with deposits: they are judged on `screens.BANK_FLOOR` instead); paid in at
  least 4 of the last 5 years; no cut in the last 2 years unless `ni_ttm` is above its level a
  year earlier. Live, `screens.passes_gates` and `passes_quality` run first, and a name whose
  sector map marks it a holding company is skipped.
- **Cheapness leg**: today's yield as a percentile of the name's own quarter-end yields over the
  last 5 years (1 = the highest it has been). Reported, not ranked on.
- **Margin** = expected return − the P34 IDN hurdle (`hurdle.margin`). Within the screen names
  are ranked by margin (PLAN S20: never by a mixed score).

**Splits.** The store's dividends are as paid while `factor_series` prices are split-adjusted
(BBCA paid 432 in 2021-04 against an adjusted price near 7,000). `adjust_dividends` rescales each
dividend by real shares (idx-method `fundamentals` `shares`, for the quarter of the ex-date) over
adjusted shares (`mktcap / price` on the ex-date); drift inside `split_band` is left alone. A name
with no share counts keeps its dividends as paid, so a past split there inflates its old yields.

**Replay.** At each quarter end with a later one: every name that passes the safety gates
point in time and the replay size floor (`replay_min_mktcap`, a stand-in for the liquidity gate,
which `factor_series` cannot replay before `cache/history/` starts) is ranked by expected return.
That is the same order as by margin, since every name faces the same hurdle on a date. Its
3-month forward return is price plus dividends gone ex in the quarter. The top and bottom
quintile mean excess returns feed `assist.eval.placebo.evaluate` as `screens.evaluate_screen`
does. A failed verdict still reports the ranking, but names no candidate. Banks in the replay are
today's (a `car` in the screener), as `screens` replays today's flagged boards.

`CONFIG` is hand-set, and this module sits under `candidates/`, so the journal's model
fingerprint (`journal.RULE_GLOBS`) changes when it does.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import fmean, stdev

from assist.candidates.hurdle import Hurdle, margin
from assist.candidates.screens import (
    GATES,
    MAX_PER_SECTOR,
    QEND,
    QUANTILES,
    TOP_N,
    passes_gates,
    passes_quality,
    select,
    trailing_dividend,
)
from assist.eval.placebo import Verdict, evaluate
from assist.sources.base import SourceUnavailable, sqlite_ro
from assist.sources.idxmethod_series import Bar, Fundamentals, IdxMethodSeries, quarter_ends
from assist.sources.idxmethod_stocks import SOURCE, IdxMethodStocks

__all__ = [
    "CONFIG",
    "Assessment",
    "DividendData",
    "adjust_dividends",
    "assess",
    "evaluate_replay",
    "expected_return",
    "load",
    "observations",
    "own_yield_percentile",
    "quarter_ends",
    "rank_live",
    "replay_panel",
    "run",
    "run_live",
]

CONFIG = {
    "g_cap_pt": 8.0,  # IDN nominal GDP growth, % a year: the most growth a dividend may assume
    "max_payout": 0.90,  # of ni_ttm
    "min_paid_years": 4,
    "paid_years": 5,
    "cut_years": 2,
    "cut_tol": 0.10,  # a 12-month total this much below the year before is a cut
    "own_years": 5,  # cheapness: the name's own quarter-end yields over this many years
    "min_own_obs": 8,
    "split_band": (0.8, 1.25),  # real / adjusted shares inside this is drift, not a split
    "replay_min_mktcap": 1e12,  # IDR; the replay's liquidity stand-in
    "min_pool": 30,  # names a quarter needs before it is scored
}
YEAR_DAYS = 365


# ---------------- pieces ----------------


def _bar_at(bars: Sequence[Bar], d: date, dates: Sequence[date] | None = None) -> Bar | None:
    """The last bar on or before `d` with both a price and a mktcap."""
    dates = dates if dates is not None else [b.date for b in bars]
    i = bisect_right(dates, d)
    while i > 0:
        b = bars[i - 1]
        if b.price and b.mktcap:
            return b
        i -= 1
    return None


def _quarter_of(d: date) -> date:
    q = (d.month - 1) // 3 + 1
    m, day = QEND[q]
    return date(d.year, m, day)


def _years_before(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year - n)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - n, day=28)


def adjust_dividends(
    recs: Iterable[Mapping],
    bars: Sequence[Bar],
    shares: Mapping[date, float],
    band: tuple[float, float] = CONFIG["split_band"],
) -> list[dict]:
    """Dividends per share rescaled to the split-adjusted price basis, each with its
    `split_factor` (real shares in the ex-date's quarter / `mktcap / price` on the ex-date)."""
    dates = [b.date for b in bars]
    periods = sorted(shares)
    out = []
    for r in recs:
        ex = date.fromisoformat(r["ex"])
        factor = 1.0
        real = shares.get(_quarter_of(ex))
        if real is None and periods:
            real = shares[min(periods, key=lambda p: abs((p - ex).days))]
        bar = _bar_at(bars, ex, dates) or next((b for b in bars if b.price and b.mktcap), None)
        if real and bar is not None:
            f = real / (bar.mktcap / bar.price)
            if not band[0] <= f <= band[1]:
                factor = f
        value = r["value"] * factor if r.get("value") is not None else None
        out.append({**r, "value": value, "split_factor": factor})
    return out


def expected_return(
    yld: float, roe: float | None, payout: float | None, g_cap_pt: float = CONFIG["g_cap_pt"]
) -> tuple[float, float, float]:
    """(yield, g, yield + g) in pt; g = ROE × (1 − payout), floored at 0, capped at `g_cap_pt`.
    No ROE or payout means no growth is assumed."""
    g = 0.0
    if roe is not None and payout is not None:
        g = max(0.0, min(g_cap_pt, 100 * roe * (1 - payout)))
    return 100 * yld, g, 100 * yld + g


def own_yield_percentile(
    current: float | None, history: Sequence[float], min_obs: int = CONFIG["min_own_obs"]
) -> float | None:
    """Share of the name's past yields at or below today's; None with too little history."""
    if current is None or len(history) < min_obs:
        return None
    return sum(h <= current for h in history) / len(history)


@dataclass(frozen=True)
class Assessment:
    """One name on one date. Yields and returns in pt; payout and CFO cover as ratios."""

    date: date
    bar_date: date
    price: float
    mktcap: float
    period: date | None
    yield_pt: float
    roe_pt: float | None
    payout: float | None
    g_pt: float
    expected_pt: float
    cfo_cover: float | None
    paid_years: int
    cut: bool
    recovered: bool
    own_yield_pct: float | None = None
    own_yield_n: int = 0
    failed: tuple[str, ...] = ()  # gate keys, in order
    reasons: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed

    def legs(self) -> dict:
        return {
            "yield_pt": self.yield_pt, "g_pt": self.g_pt, "roe_pt": self.roe_pt,
            "payout": self.payout, "cfo_cover": self.cfo_cover, "paid_years": self.paid_years,
            "cut": self.cut, "recovered": self.recovered, "own_yield_pct": self.own_yield_pct,
            "own_yield_n": self.own_yield_n,
        }


def _recovered(known: Sequence[Fundamentals]) -> bool:
    """`ni_ttm` of the latest quarter above that of the quarter a year before it."""
    if not known or known[-1].ni_ttm is None:
        return False
    cutoff = known[-1].period - timedelta(days=YEAR_DAYS - 5)
    prior = next((f for f in reversed(known) if f.period <= cutoff), None)
    return prior is not None and prior.ni_ttm is not None and known[-1].ni_ttm > prior.ni_ttm


def assess(
    d: date,
    bars: Sequence[Bar],
    quarters: Sequence[Fundamentals],
    divs: Sequence[Mapping],
    *,
    bank: bool = False,
    own: bool = True,
    bar_dates: Sequence[date] | None = None,
    cfg: Mapping = CONFIG,
) -> Assessment | None:
    """The legs and safety gates of one name on `d`, point in time; None with no bar by `d`."""
    bar = _bar_at(bars, d, bar_dates)
    if bar is None:
        return None
    known = [f for f in quarters if f.available <= d]
    f = known[-1] if known else None
    divs = [r for r in divs if r.get("value") is not None]
    yld = trailing_dividend(divs, d) / bar.price
    paid_total = yld * bar.mktcap
    ni = f.ni_ttm if f else None
    equity = f.equity if f else None
    cfo = f.cfo_ttm if f else None
    payout = paid_total / ni if ni and ni > 0 else None
    roe = ni / equity if ni is not None and equity and equity > 0 else None
    y_pt, g_pt, exp_pt = expected_return(yld, roe, payout, cfg["g_cap_pt"])
    cover = cfo / paid_total if cfo is not None and paid_total > 0 else None

    annual = [trailing_dividend(divs, d - timedelta(days=YEAR_DAYS * k))
              for k in range(max(cfg["paid_years"], cfg["cut_years"] + 1))]
    paid = sum(a > 0 for a in annual[: cfg["paid_years"]])
    cut = any(annual[k] < (1 - cfg["cut_tol"]) * annual[k + 1] for k in range(cfg["cut_years"]))
    recovered = _recovered(known)

    failed: list[str] = []
    reasons: list[str] = []

    def fail(key: str, why: str) -> None:
        failed.append(key)
        reasons.append(why)

    if yld <= 0:
        fail("no dividend", "no dividend in the last 12 months")
    if payout is None:
        fail("no earnings", "no positive earnings (ni_ttm) to pay from")
    elif payout >= cfg["max_payout"]:
        fail("payout", f"payout {payout:.0%} of ni_ttm, limit {cfg['max_payout']:.0%}")
    if not bank and (cover is None or cover < 1):
        fail("cfo cover", "dividends not covered by CFO (cfo_ttm)")
    if paid < cfg["min_paid_years"]:
        fail("paid years", f"paid {paid} of {cfg['paid_years']} years")
    if cut and not recovered:
        fail("cut", f"dividend cut in the last {cfg['cut_years']} years, ni_ttm not recovered")

    own_pct, own_n = None, 0
    if own:
        lo = _years_before(d, cfg["own_years"])
        hist = []
        for q in quarter_ends(lo, d - timedelta(days=1)):
            b = _bar_at(bars, q, bar_dates)
            if b is not None:
                hist.append(trailing_dividend(divs, q) / b.price)
        own_pct, own_n = own_yield_percentile(yld, hist, cfg["min_own_obs"]), len(hist)

    return Assessment(
        date=d, bar_date=bar.date, price=bar.price, mktcap=bar.mktcap,
        period=f.period if f else None, yield_pt=y_pt,
        roe_pt=None if roe is None else 100 * roe, payout=payout, g_pt=g_pt,
        expected_pt=exp_pt, cfo_cover=cover, paid_years=paid, cut=cut, recovered=recovered,
        own_yield_pct=own_pct, own_yield_n=own_n, failed=tuple(failed), reasons=tuple(reasons),
    )


# ---------------- replay ----------------


def replay_panel(
    bars: Mapping[str, Sequence[Bar]],
    quarters: Mapping[str, Sequence[Fundamentals]],
    dividends: Mapping[str, Sequence[Mapping]],
    banks: Iterable[str] = (),
    *,
    min_mktcap: float = CONFIG["replay_min_mktcap"],
    cfg: Mapping = CONFIG,
) -> list[tuple[date, list[dict]]]:
    """→ [(quarter end, [{symbol, expected_pt, fwd}])]: the names passing the safety gates and
    size floor on that date, with the price-plus-dividend return to the next quarter end."""
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
            a = assess(q, bs, quarters.get(sym, ()), divs, bank=sym in banks, own=False,
                       bar_dates=dates[sym], cfg=cfg)
            if a is None or not a.ok or a.mktcap < min_mktcap or a.price < GATES["min_price"]:
                continue
            if a.bar_date < q - timedelta(days=10):
                continue  # no trading near the quarter end
            end = _bar_at(bs, q1, dates[sym])
            if end is None or end.date <= q:
                continue
            paid = sum(r["value"] for r in divs if r.get("value") is not None
                       and a.bar_date < date.fromisoformat(r["ex"]) <= end.date)
            recs.append({"symbol": sym, "expected_pt": a.expected_pt,
                         "fwd": (end.price + paid) / a.price - 1})
        panel.append((q, recs))
    return panel


def observations(
    panel: Sequence[tuple[date, list[dict]]], min_pool: int = CONFIG["min_pool"]
) -> tuple[list[bool], list[float], list[float]]:
    """→ (features, returns, quarterly spreads), as `screens.screen_observations`: per scored
    quarter, (True, top-quintile mean excess return) and (False, bottom-quintile's)."""
    feats: list[bool] = []
    rets: list[float] = []
    spreads: list[float] = []
    for _, recs in panel:
        if len(recs) < min_pool:
            continue
        ranked = sorted(recs, key=lambda r: (-r["expected_pt"], r["symbol"]))
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


# ---------------- data ----------------


@dataclass
class DividendData:
    """Everything the screen reads from idx-method, dividends already split-adjusted."""

    bars: dict[str, list[Bar]] = field(default_factory=dict)
    quarters: dict[str, list[Fundamentals]] = field(default_factory=dict)
    dividends: dict[str, list[dict]] = field(default_factory=dict)
    shares: dict[str, dict[date, float]] = field(default_factory=dict)
    sectors: dict[str, str] = field(default_factory=dict)
    stale: list[str] = field(default_factory=list)


def _period_end(period: str) -> date:
    m, d = QEND[int(period[-1])]
    return date(int(period[:4]), m, d)


def _shares(series: IdxMethodSeries) -> dict[str, dict[date, float]] | None:
    """Real shares outstanding per quarter (`fundamentals` `is.shares`, else `bs.shares_bs`);
    None when the store has no `fundamentals` table."""
    with sqlite_ro(series.db, series.name) as con:
        if not con.execute("select 1 from sqlite_master where type='table'"
                           " and name='fundamentals'").fetchone():
            return None
        rows = con.execute(
            "select symbol, period, item, value from fundamentals where"
            " item in ('shares', 'shares_bs') and value > 0 and period like '____Q_'"
            " order by item desc"  # shares_bs first, so `shares` overwrites it
        ).fetchall()
    out: dict[str, dict[date, float]] = {}
    for sym, period, _, v in rows:
        out.setdefault(sym, {})[_period_end(period)] = float(v)
    return out


def load(series: IdxMethodSeries | None = None) -> DividendData:
    """Bars, quarters, split-adjusted dividends, share counts and sectors. A missing store is a
    stale input and an empty result, never a crash."""
    series = series or IdxMethodSeries.from_config()
    data = DividendData()
    try:
        data.bars = series.daily()
        data.quarters = series.quarterly()
        raw = series.dividends()
        data.sectors = {s: u["sector"] for s, u in series.universe().items() if u.get("sector")}
        shares = _shares(series)
    except SourceUnavailable as e:
        return DividendData(stale=[e.stale_input])
    if shares is None:
        data.stale.append(f"{SOURCE} fundamentals (no table: dividends not split-adjusted)")
        shares = {}
    data.shares = shares
    data.dividends = {s: adjust_dividends(recs, data.bars.get(s, []), shares.get(s, {}))
                      for s, recs in raw.items()}
    return data


# ---------------- live ----------------


def _holding(sym: str, sectors: Mapping[str, str], holdings: Iterable[str]) -> bool:
    return sym in set(holdings) or "holding" in (sectors.get(sym) or "").lower()


def rank_live(
    table: Mapping[str, Mapping],
    data: DividendData,
    as_of: date,
    hurdle: Hurdle | None,
    *,
    flagged: Iterable[str] = (),
    holdings: Iterable[str] = (),
    cfg: Mapping = CONFIG,
) -> tuple[list[dict], Counter]:
    """Gate and rank today's cross-section → (rows best margin first, rejects by first rule
    failed). Without a hurdle, rows are ranked by expected return and carry no margin."""
    flagged, holdings = set(flagged), set(holdings)
    rows, rejects = [], Counter()
    for sym, r in sorted(table.items()):
        ok, why = passes_gates(sym, r, flagged)
        if ok:
            ok, why = passes_quality(r)
        if ok and _holding(sym, data.sectors, holdings):
            ok, why = False, "holding company"
        if not ok:
            rejects[why] += 1
            continue
        a = assess(as_of, data.bars.get(sym, []), data.quarters.get(sym, []),
                   data.dividends.get(sym, []), bank=bool(r.get("car")), cfg=cfg)
        if a is None:
            rejects["no price history"] += 1
            continue
        if not a.ok:
            rejects[a.failed[0]] += 1
            continue
        rows.append({
            "symbol": sym, "sector": data.sectors.get(sym), "bank": bool(r.get("car")),
            "expected_pt": a.expected_pt, "margin_pt": margin(a.expected_pt, hurdle),
            "legs": a.legs(), "price": a.price, "mktcap": a.mktcap, "bar_date": a.bar_date,
            "period": a.period, "reasons": list(a.reasons),
        })
    rows.sort(key=lambda x: (-(x["margin_pt"] if x["margin_pt"] is not None
                               else x["expected_pt"]), x["symbol"]))
    return rows, rejects


def run(
    data: DividendData,
    table: Mapping[str, Mapping],
    *,
    as_of: date,
    hurdle: Hurdle | None,
    panel: Sequence[tuple[date, list[dict]]] | None = None,
    flagged: Iterable[str] = (),
    holdings: Iterable[str] = (),
    cfg: Mapping = CONFIG,
    **kw,
) -> dict:
    """The screen: replay verdict, today's ranking, and candidates only when the verdict passed,
    the hurdle is known and the margin is positive. `kw` goes to `evaluate`."""
    stale = list(data.stale)
    required = hurdle.required if hurdle is not None else None
    if hurdle is not None:
        stale += list(hurdle.stale_inputs)
    if required is None:
        stale.append("IDN hurdle unavailable: ranked by expected return, no candidate")
    banks = {s for s, r in table.items() if r.get("car")}
    if panel is None:
        panel = replay_panel(data.bars, data.quarters, data.dividends, banks, cfg=cfg)
    min_pool = kw.pop("min_pool", cfg["min_pool"])
    verdict = evaluate_replay(panel, min_pool=min_pool, **kw)
    _, _, spreads = observations(panel, min_pool)
    rows, rejects = rank_live(table, data, as_of, hurdle, flagged=flagged, holdings=holdings,
                              cfg=cfg)
    candidates: list[dict] = []
    if verdict.passed and required is not None:
        above = [(r["margin_pt"], {}, r) for r in rows if r["margin_pt"] > 0]
        candidates = list(select(above, TOP_N, data.sectors, MAX_PER_SECTOR))
    return {
        "screen": "dividend_value",
        "as_of": as_of,
        "passed": verdict.passed,
        "blocked": None if verdict.passed else verdict.reason,
        "verdict": {k: v for k, v in verdict.to_dict().items() if k != "control_ts"},
        "quarters": len(spreads),
        "spread_mean": fmean(spreads) if spreads else None,
        "spread_t": (fmean(spreads) / (stdev(spreads) / len(spreads) ** 0.5)
                     if len(spreads) > 2 and stdev(spreads) > 0 else None),
        "hurdle_pt": required,
        "hurdle_drivers": list(hurdle.drivers) if hurdle is not None else [],
        "pool": len(rows),
        "rejects": dict(rejects),
        "ranking": rows,
        "candidates": candidates,
        "fingerprint": dict(cfg),
        "stale_inputs": list(dict.fromkeys(stale)),
    }


def run_live(as_of: date | None = None, regime=None, **kw) -> dict:
    """The screen over the real stores (read-only): idx-method's `factor_series` and screener,
    and the P34 IDN hurdle on the screener's last bar date under `regime` (default: P8's)."""
    from assist.candidates.factors import load_factors
    from assist.candidates.hurdle import hurdle as idn_hurdle

    stocks = IdxMethodStocks.from_config()
    data = load()
    table, stale = load_factors(stocks, as_of)
    data.stale += stale
    bar_dates = [r["bar_date"] for r in table.values() if r.get("bar_date")]
    as_of = max(bar_dates) if bar_dates else (as_of or date.today())
    flagged: set[str] = set()
    try:
        with (stocks.root / "data" / "special_boards.json").open(encoding="utf-8") as f:
            boards = json.load(f)
        flagged = {s for b in GATES["exclude_boards"] for s in boards.get(b, [])}
    except (OSError, ValueError):
        data.stale.append(f"{SOURCE} special_boards.json (missing)")
    if regime is None:
        from assist.layers.regime import regime as current_regime

        regime = current_regime(as_of)
    h = idn_hurdle("IDN", as_of, regime)
    return run(data, table, as_of=as_of, hurdle=h, flagged=flagged, **kw)
