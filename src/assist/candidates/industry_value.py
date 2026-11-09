"""Industry-relative value screen, IDN (PLAN S15): undervalued against what fundamentals justify.

The fourth screen beside `screens.value` (B/P alone): a name is ranked against its peers, never
the market, so structurally cheap industries (banks, plantations, coal, property) do not fill
the list. It runs behind the same gates, quality floor and placebo control as the other three
and reports in `screens.run_screen`'s shape, so `layers.candidates` journals its verdict.

**Peers.** The IDX-IC sub-industry when it holds at least `CONFIG["min_peers"]` names in that
month's pool, else the sector (`peer_group`). Membership is idx-method's dated
`industry_membership`: the latest snapshot on or before the date, else the first one
back-filled (flagged; the store's first record is 2026-11-06, so every replayed month is
back-filled today). A name with no membership falls back to `factor_universe.sector` (a
sector-only peer group); one with neither, most delisted names, is left out and counted.

**Leg 1, fitted gap.** Within each peer group and month, the log multiple is regressed (OLS) on
the fundamental that justifies it, and a name's gap is its residual (`fit_residuals`):

- log PBV on ROE (normalised earnings / book);
- log PE (on normalised earnings) on earnings growth (`growth_years` CAGR of TTM earnings) and
  payout (trailing 12-month dividends / TTM earnings);
- log EV/EBITDA on ROIC (`roce` from the quarterly series, lagged `screens.LAG_DAYS`).

Financials (sector Keuangan: banks, insurers, multifinance, holding and investment) use log PE
and log PBV on ROE only: no EV leg, and no cost of credit (no store holds it, flagged). A group
with fewer than `min_fit` names holding a leg's inputs, or a degenerate fit, falls back to the
log gap to the peer median (computed here; Stockbit's industry means are never read). Inputs
are clipped to `CONFIG["clip"]`. Deviations are logs, ranked as peer percentiles, never percent.

**Normalised earnings.** TTM earnings are mktcap / PE on the daily row (the store's multiples
step on the filing date, checked 2026-11-09: BBCA's Q2 2025 earnings enter on 2025-07-30). The
PE leg and ROE use the lower of TTM earnings and their median over the last `norm_years` TTM
years (month ends 12 months apart, the current one included), so a one-off gain (BMTR PE 2,
2026-10-26) cannot rank first. The median, not the mean S31 uses: a 3-year mean still keeps 7/3
of a 5× one-off. A non-positive base gives no PE leg.

**Leg 2, own history.** log PE (normalised) and log PBV against the name's own median over the
last `own_months` month ends, needing `min_own` of them.

**Score.** Each sub-leg becomes a percentile within the peer group (cheaper is higher, groups
smaller than `min_group` give none); a leg is the mean of its sub-legs; the score is
`CONFIG["weights"]` over the two legs, both required. `score` is that percentile centred and
scaled to unit variance (`(pct − 50) / PCT_SD`) so it reads on the other screens' z scale in
`layers.candidates`. Quality is a gate and does not score: live, `screens.passes_gates` and
`passes_quality` (or `BANK_FLOOR`) decide who may be named; the fit pool itself is every name
that clears the point-in-time pool gates (price floor, `min_mktcap`, positive book, a fresh bar).

**Replay.** At every month end with a later one: the same scores over the pool, then
`screens`' test: the top- and bottom-quintile mean next-month return (price plus dividends gone
ex), in excess of the pool mean, into `assist.eval.placebo.evaluate`. A month needs `min_pool`
ranked names. The quality floor has no history and is not replayed (flagged). A failed verdict
still reports the ranking size, but names no candidate.

`CONFIG` is hand-set; this module sits under `candidates/`, so the journal's model fingerprint
changes when it does.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import fmean, median, stdev
from typing import NamedTuple

from assist.candidates.screens import (
    GATES,
    LAG_DAYS,
    MAX_PER_SECTOR,
    QUANTILES,
    TOP_N,
    passes_gates,
    passes_quality,
    select,
    trailing_dividend,
)
from assist.candidates.tiers import percentiles
from assist.eval.placebo import Verdict, evaluate
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_series import Bar, IdxMethodSeries
from assist.sources.idxmethod_stocks import SOURCE

__all__ = [
    "CONFIG",
    "FLAGS",
    "NAME",
    "PCT_SD",
    "IndustryData",
    "Member",
    "Row",
    "cross_section",
    "evaluate_replay",
    "fit_residuals",
    "load",
    "member_at",
    "month_end",
    "month_index",
    "observations",
    "ols",
    "peer_groups",
    "replay_panel",
    "run",
    "run_live",
]

NAME = "industry_value"
DESCRIPTION = ("Undervalued within its IDX-IC peers: log multiples vs what ROE, growth, payout "
               "and ROIC justify, plus PE and PBV vs the name's own 5-year median.")
FINANCIAL_SECTOR = "Keuangan"

# Hand-set. The numbers the spec leaves open are marked (choice) for the user to confirm.
CONFIG = {
    "min_peers": 8,  # PLAN S15: a sub-industry needs this many pool names, else the sector
    "min_fit": 8,  # (choice) names with a leg's inputs a group needs for the OLS fit
    "min_group": 5,  # (choice) names a leg needs in a group before its percentiles count
    "norm_years": 3,  # (choice) TTM years whose median normalises earnings (PLAN: 3–5)
    "growth_years": 3,  # (choice) span of the TTM earnings CAGR the PE leg is fitted on
    "own_months": 60,  # PLAN S15: own 5-year median
    "min_own": 24,  # (choice) month ends of own history the own leg needs
    "weights": {"fit": 0.5, "own": 0.5},  # (choice) fitted gap vs own history
    "clip": {  # (choice) regressor bounds, fractions
        "roe": (-0.5, 0.6),
        "growth": (-0.5, 0.5),
        "payout": (0.0, 1.0),
        "roic": (-0.5, 0.6),
    },
    "min_mktcap": 1e12,  # IDR, the replay's liquidity stand-in (as dividend_value, garp)
    "bar_window_days": 10,  # a bar this close before the date, else the name sits out
    "min_pool": 40,  # ranked names a month needs before it is scored (screens.MIN_POOL)
    "lag_days": LAG_DAYS,  # roce from period end + this
}
PCT_SD = 100 / math.sqrt(12)  # sd of a uniform percentile on 0–100
SCAN_FROM_DAY = 18  # month-end rows are read from this day of the month on
ECHO_GAP = timedelta(days=14)  # a lone row this far from the last one is an echo, not a quote

LEGS = {  # leg → (multiple, regressors)
    "standard": {"pbv": ("pbv", ("roe",)), "pe": ("pe_norm", ("growth", "payout")),
                 "ev": ("ev_ebitda", ("roic",))},
    "financial": {"pbv": ("pbv", ("roe",)), "pe": ("pe_norm", ("roe",))},
}
OWN = {"own_pe": "pe_norm", "own_pbv": "pbv"}

FLAGS = (
    "membership: idx-method industry_membership's first snapshot back-filled to earlier month "
    "ends (survivorship)",
    "delisted names without a recorded sector have no peer group and sit out",
    f"roce (ROIC proxy) lagged {LAG_DAYS} days from period end; PE, PBV and EV/EBITDA step on "
    "filing in the store",
    "banks: no cost of credit in any store; no P/FCF leg (no capex in the store)",
    "quality floor (Piotroski, Altman Z, interest cover, bank prudential) not replayed",
    "EV/EBITDA starts 2018-03 in the store",
)


class Row(NamedTuple):
    """One name's daily row used for a date (`date` is the row's own date)."""

    date: date
    price: float | None
    mktcap: float | None
    pe: float | None
    pbv: float | None
    ev_ebitda: float | None


@dataclass(frozen=True)
class Member:
    sector: str | None
    sub_industry_id: int | None = None
    sub_industry: str | None = None
    industry: str | None = None
    source: str = "recorded"  # recorded | back-filled | sector only


@dataclass
class IndustryData:
    """What the screen reads from idx-method's store, by symbol."""

    months: dict[str, dict[int, Row]] = field(default_factory=dict)
    live: dict[str, Row] = field(default_factory=dict)
    roce: dict[str, list[tuple[date, float]]] = field(default_factory=dict)
    dividends: dict[str, list[dict]] = field(default_factory=dict)
    snapshots: list[tuple[date, dict[str, Member]]] = field(default_factory=list)
    sectors: dict[str, str] = field(default_factory=dict)  # factor_universe fallback
    last_date: date | None = None
    stale: list[str] = field(default_factory=list)


# ---------------- calendar ----------------


def month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def month_end(k: int) -> date:
    y, m = divmod(k, 12)
    nxt = date(y + (m + 1) // 12, (m + 1) % 12 + 1, 1)
    return nxt - timedelta(days=1)


# ---------------- membership ----------------


def member_at(data: IndustryData, sym: str, d: date) -> Member | None:
    """The latest snapshot holding `sym` on or before `d`, else its first one (back-filled),
    else its `factor_universe` sector (sector only), else None."""
    held = [(sd, snap[sym]) for sd, snap in data.snapshots if sym in snap]
    if held:
        on = [m for sd, m in held if sd <= d]
        if on:
            return on[-1]
        m = held[0][1]
        return Member(m.sector, m.sub_industry_id, m.sub_industry, m.industry, "back-filled")
    sec = data.sectors.get(sym)
    return Member(sec, source="sector only") if sec else None


def peer_groups(members: Mapping[str, Member],
                min_peers: int = CONFIG["min_peers"]) -> dict[str, tuple[str, str]]:
    """sym → (group key, level): its sub-industry when that holds `min_peers` of `members`,
    else its sector."""
    counts = Counter(m.sub_industry_id for m in members.values() if m.sub_industry_id is not None)
    out = {}
    for sym, m in members.items():
        if m.sub_industry_id is not None and counts[m.sub_industry_id] >= min_peers:
            out[sym] = (f"sub:{m.sub_industry_id}", "sub_industry")
        else:
            out[sym] = (f"sec:{m.sector}", "sector")
    return out


# ---------------- the fit ----------------


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c], strict=True)]
    return [m[i][n] / m[i][i] for i in range(n)]


def ols(ys: Sequence[float], xs: Sequence[Sequence[float]]) -> list[float] | None:
    """[intercept, b1, ...] of y on x by least squares; None when a regressor does not vary or
    the design is singular."""
    n, k = len(ys), len(xs[0]) if xs else 0
    if n <= k + 1:
        return None
    for j in range(k):
        col = [x[j] for x in xs]
        if max(col) - min(col) < 1e-9:
            return None
    rows = [[1.0, *x] for x in xs]
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(k + 1)] for i in range(k + 1)]
    aty = [sum(r[i] * y for r, y in zip(rows, ys, strict=True)) for i in range(k + 1)]
    beta = _solve(ata, aty)
    if beta is None or not all(math.isfinite(b) for b in beta):
        return None
    return beta


def fit_residuals(obs: Mapping[str, tuple[float, Sequence[float]]],
                  min_fit: int = CONFIG["min_fit"]) -> tuple[dict[str, float], str]:
    """sym → residual of y on x within one peer group, and the method ("fit" or "median").
    Fewer than `min_fit` names or a degenerate fit → the gap to the group median of y."""
    if not obs:
        return {}, "none"
    syms = sorted(obs)
    ys = [obs[s][0] for s in syms]
    if len(syms) >= min_fit:
        beta = ols(ys, [list(obs[s][1]) for s in syms])
        if beta is not None:
            return ({s: y - beta[0] - sum(b * x for b, x in zip(beta[1:], obs[s][1], strict=True))
                     for s, y in zip(syms, ys, strict=True)}, "fit")
    med = median(ys)
    return {s: y - med for s, y in zip(syms, ys, strict=True)}, "median"


# ---------------- point-in-time metrics ----------------


def _clip(v: float | None, key: str, cfg: Mapping) -> float | None:
    if v is None:
        return None
    lo, hi = cfg["clip"][key]
    return max(lo, min(hi, v))


def _log(v: float | None) -> float | None:
    return math.log(v) if v is not None and v > 0 and math.isfinite(v) else None


def _earnings(r: Row | None) -> float | None:
    if r is None or r.mktcap is None or not r.pe:
        return None
    return r.mktcap / r.pe


class _Base:
    """Per-name month-end bases (normalised PE, PBV), cached for the own-history leg."""

    def __init__(self, data: IndustryData, cfg: Mapping):
        self.data, self.cfg = data, cfg
        self._cache: dict[tuple[str, int], tuple[float | None, float | None]] = {}

    def e(self, sym: str, k: int) -> float | None:
        return _earnings(self.data.months.get(sym, {}).get(k))

    def norm(self, sym: str, k: int, row: Row) -> tuple[float | None, float | None]:
        """(normalised earnings, TTM earnings) on `row`, taken as month `k`."""
        e0 = _earnings(row)
        if e0 is None:
            return None, None
        years = [e0]
        for y in range(1, self.cfg["norm_years"]):
            v = self.e(sym, k - 12 * y)
            if v is None:
                break
            years.append(v)
        return min(e0, median(years)), e0

    def at(self, sym: str, k: int) -> tuple[float | None, float | None]:
        """(normalised PE, PBV) at month end `k` from the stored month row."""
        key = (sym, k)
        if key not in self._cache:
            r = self.data.months.get(sym, {}).get(k)
            pe = pbv = None
            if r is not None and r.mktcap:
                base, _ = self.norm(sym, k, r)
                pe = r.mktcap / base if base and base > 0 else None
                pbv = r.pbv if r.pbv and r.pbv > 0 else None
            self._cache[key] = (pe, pbv)
        return self._cache[key]


def _roic(data: IndustryData, sym: str, d: date) -> float | None:
    known = [v for avail, v in data.roce.get(sym, ()) if avail <= d]
    return known[-1] / 100 if known else None


def metrics(base: _Base, sym: str, k: int, row: Row, d: date) -> dict[str, float | None]:
    """The multiples and their regressors for one name on `d` (month `k`), point in time."""
    cfg, data = base.cfg, base.data
    enorm, e0 = base.norm(sym, k, row)
    cap = row.mktcap
    pe_norm = cap / enorm if cap and enorm and enorm > 0 else None
    pbv = row.pbv if row.pbv and row.pbv > 0 else None
    book = cap / pbv if cap and pbv else None
    roe = enorm / book if enorm is not None and book else None
    growth = None
    e_then = base.e(sym, k - 12 * cfg["growth_years"])
    if e0 and e0 > 0 and e_then and e_then > 0:
        growth = (e0 / e_then) ** (1 / cfg["growth_years"]) - 1
    payout = None
    if e0 and e0 > 0 and row.price and cap:
        div = trailing_dividend(data.dividends.get(sym) or [], d)
        payout = div * (cap / row.price) / e0
    own: dict[str, float | None] = {}
    for leg, key in OWN.items():
        now = pe_norm if key == "pe_norm" else pbv
        hist = [v for j in range(k - cfg["own_months"], k)
                if (v := base.at(sym, j)[0 if key == "pe_norm" else 1]) is not None]
        own[leg] = (math.log(now / median(hist))
                    if now is not None and len(hist) >= cfg["min_own"] else None)
    return {
        "pe_norm": pe_norm, "pbv": pbv,
        "ev_ebitda": row.ev_ebitda if row.ev_ebitda and row.ev_ebitda > 0 else None,
        "pe_ttm": row.pe, "roe": _clip(roe, "roe", cfg), "growth": _clip(growth, "growth", cfg),
        "payout": _clip(payout, "payout", cfg), "roic": _clip(_roic(data, sym, d), "roic", cfg),
        **own,
    }


def _in_pool(row: Row | None, d: date, cfg: Mapping) -> bool:
    return (
        row is not None
        and row.date >= d - timedelta(days=cfg["bar_window_days"])
        and (row.price or 0) >= GATES["min_price"]
        and (row.mktcap or 0) >= cfg["min_mktcap"]
        and (row.pbv or 0) > 0
    )


def cross_section(
    data: IndustryData,
    d: date,
    rows: Mapping[str, Row],
    cfg: Mapping = CONFIG,
    base: _Base | None = None,
) -> tuple[dict[str, dict], dict]:
    """Score every pool name on `d` within its peers → ({sym: rec}, info). A rec holds
    `score_pct`, `score`, `fit_pct`, `own_pct`, each leg's gap and percentile, the peer
    group, its level and the membership source; a name missing a leg has `score` None.
    `info` counts the pool, the names with no peer group and the back-filled members."""
    base = base or _Base(data, cfg)
    k = month_index(d)
    members: dict[str, Member] = {}
    info = Counter()
    for sym, r in rows.items():
        if not _in_pool(r, d, cfg):
            continue
        m = member_at(data, sym, d)
        if m is None or not m.sector:
            info["no peer group"] += 1
            continue
        members[sym] = m
        info[m.source] += 1
    groups = peer_groups(members, cfg["min_peers"])
    recs: dict[str, dict] = {}
    for sym, m in members.items():
        fin = m.sector == FINANCIAL_SECTOR
        key, level = groups[sym]
        recs[sym] = {"symbol": sym, "group": key, "level": level, "financial": fin,
                     "sector": m.sector, "sub_industry": m.sub_industry, "membership": m.source,
                     "price": rows[sym].price, "mktcap": rows[sym].mktcap,
                     "bar_date": rows[sym].date, **metrics(base, sym, k, rows[sym], d)}
    by_group: dict[str, list[str]] = {}
    for sym, r in recs.items():
        by_group.setdefault(r["group"], []).append(sym)
    for syms in by_group.values():
        _score_group([recs[s] for s in syms], cfg)
    info["pool"] = len(recs)
    info["groups"] = len(by_group)
    info["sub_industry groups"] = len({recs[s]["group"] for s in recs
                                       if recs[s]["level"] == "sub_industry"})
    return recs, dict(info)


def _score_group(recs: list[dict], cfg: Mapping) -> None:
    pcts: dict[str, dict[str, float]] = {}
    for leg_set in ("standard", "financial"):
        part = [r for r in recs if r["financial"] == (leg_set == "financial")]
        if not part:
            continue
        for leg, (y_key, x_keys) in LEGS[leg_set].items():
            obs = {}
            for r in part:
                y = _log(r[y_key])
                xs = [r[x] for x in x_keys]
                if y is not None and all(x is not None for x in xs):
                    obs[r["symbol"]] = (y, xs)
            if len(obs) < cfg["min_group"]:
                continue
            gaps, method = fit_residuals(obs, cfg["min_fit"])
            for r in part:
                if r["symbol"] in gaps:
                    r[f"{leg}_gap"] = gaps[r["symbol"]]
                    r[f"{leg}_method"] = method
            pcts[leg] = percentiles(gaps, lower_is_better=True)
        for leg in OWN:
            vals = {r["symbol"]: r[leg] for r in part if r.get(leg) is not None}
            if len(vals) >= cfg["min_group"]:
                pcts[leg] = percentiles(vals, lower_is_better=True)
    w = cfg["weights"]
    for r in recs:
        s = r["symbol"]
        legs = LEGS["financial" if r["financial"] else "standard"]
        fit = [pcts[leg][s] for leg in legs if s in pcts.get(leg, {})]
        own = [pcts[leg][s] for leg in OWN if s in pcts.get(leg, {})]
        for leg in (*legs, *OWN):
            r[f"{leg}_pct"] = pcts.get(leg, {}).get(s)
        r["fit_pct"] = fmean(fit) if fit else None
        r["own_pct"] = fmean(own) if own else None
        if fit and own:
            r["score_pct"] = (w["fit"] * r["fit_pct"] + w["own"] * r["own_pct"]) / (
                w["fit"] + w["own"])
            r["score"] = (r["score_pct"] - 50) / PCT_SD
        else:
            r["score_pct"] = r["score"] = None
            r["unscored"] = "no fitted leg" if not fit else "no own history"


# ---------------- replay ----------------


def _fwd(data: IndustryData, sym: str, r0: Row, k1: int, cfg: Mapping) -> float | None:
    r1 = data.months.get(sym, {}).get(k1)
    if r1 is None or not r1.price or not r0.price or r1.date <= r0.date:
        return None
    if r1.date < month_end(k1) - timedelta(days=cfg["bar_window_days"]):
        return None
    paid = sum(x["value"] for x in data.dividends.get(sym) or ()
               if x.get("value") is not None
               and r0.date < date.fromisoformat(x["ex"]) <= r1.date)
    return (r1.price + paid) / r0.price - 1


def replay_panel(data: IndustryData, as_of: date | None = None,
                 cfg: Mapping = CONFIG) -> tuple[list[tuple[date, list[dict]]], dict]:
    """→ ([(month end, [{symbol, score, fwd, group}])], info): every month end whose next
    month end is on or before `as_of` (default: the store's last date). Nothing after `as_of`
    is read. `info` sums the pool and membership counts over the months."""
    last = as_of or data.last_date
    ks = sorted({k for m in data.months.values() for k in m})
    if not ks or last is None:
        return [], {}
    base = _Base(data, cfg)
    panel, info = [], Counter()
    for k in range(ks[0], ks[-1]):
        d, d1 = month_end(k), month_end(k + 1)
        if d1 > last:
            break
        rows = {s: m[k] for s, m in data.months.items() if k in m}
        recs, inf = cross_section(data, d, rows, cfg, base)
        info.update({k_: v for k_, v in inf.items() if isinstance(v, int)})
        out = []
        for sym, r in sorted(recs.items()):
            if r["score"] is None:
                continue
            fwd = _fwd(data, sym, rows[sym], k + 1, cfg)
            if fwd is not None:
                out.append({"symbol": sym, "score": r["score"], "fwd": fwd, "group": r["group"]})
        panel.append((d, out))
    return panel, dict(info)


def observations(panel: Sequence[tuple[date, list[dict]]], min_pool: int = CONFIG["min_pool"]
                 ) -> tuple[list[bool], list[float], list[float], list[date]]:
    """→ (features, returns, monthly spreads, scored month ends), as
    `screens.screen_observations`: per scored month (True, top-quintile mean excess return),
    (False, bottom-quintile's), excess over the month's pool mean."""
    feats: list[bool] = []
    rets: list[float] = []
    spreads: list[float] = []
    scored: list[date] = []
    for d, recs in panel:
        if len(recs) < min_pool:
            continue
        ranked = sorted(recs, key=lambda r: (-r["score"], r["symbol"]))
        cut = len(ranked) // QUANTILES
        mean = fmean(r["fwd"] for r in ranked)
        top = fmean(r["fwd"] for r in ranked[:cut]) - mean
        bot = fmean(r["fwd"] for r in ranked[-cut:]) - mean
        feats += [True, False]
        rets += [top, bot]
        spreads.append(top - bot)
        scored.append(d)
    return feats, rets, spreads, scored


def evaluate_replay(panel: Sequence[tuple[date, list[dict]]],
                    min_pool: int = CONFIG["min_pool"], **kw) -> Verdict:
    """The placebo verdict on the top-minus-bottom quintile edge; `kw` goes to `evaluate`."""
    feats, rets, _, _ = observations(panel, min_pool)
    return evaluate(lambda f, _r: list(f), feats, rets, **kw)


# ---------------- the screen ----------------


def _t(xs: Sequence[float]) -> float | None:
    if len(xs) > 2 and stdev(xs) > 0:
        return fmean(xs) / (stdev(xs) / len(xs) ** 0.5)
    return None


def _round(v, nd: int = 4):
    return round(v, nd) if isinstance(v, float) else v


LEG_KEYS = ("pbv_gap", "pe_gap", "ev_gap", "own_pe", "own_pbv", "fit_pct", "own_pct",
            "score_pct")


def run(
    data: IndustryData,
    table: Mapping[str, Mapping],
    *,
    as_of: date,
    flagged: Iterable[str] = (),
    sectors: Mapping[str, str] | None = None,
    panel: Sequence[tuple[date, list[dict]]] | None = None,
    cfg: Mapping = CONFIG,
    **kw,
) -> dict:
    """The screen in `screens.run_screen`'s shape: replay verdict, today's ranking over the
    pool, and candidates (passing `passes_gates` and `passes_quality` on the screener `table`)
    only if the verdict passed. `kw` goes to `evaluate` (`min_pool` too)."""
    flagged = set(flagged)
    sectors = sectors or {}
    info: dict = {}
    if panel is None:
        panel, info = replay_panel(data, as_of, cfg)
    min_pool = kw.pop("min_pool", cfg["min_pool"])
    verdict = evaluate_replay(panel, min_pool=min_pool, **kw)
    _, _, spreads, scored = observations(panel, min_pool)

    live_rows = {s: r for s, r in data.live.items() if r.date <= as_of}
    recs, live_info = cross_section(data, as_of, live_rows, cfg) if live_rows else ({}, {})
    ranked, rejects = [], Counter()
    for sym, r in sorted(recs.items()):
        if r["score"] is None:
            rejects[r["unscored"]] += 1
            continue
        t = table.get(sym)
        if t is None:
            rejects["not in screener"] += 1
            continue
        ok, why = passes_gates(sym, t, flagged)
        if ok:
            ok, why = passes_quality(t)
        if not ok:
            rejects[why] += 1
            continue
        ranked.append((r["score"], {}, {**r, "med_value_60d": t.get("med_value_60d")}))
    ranked.sort(key=lambda x: (-x[0], x[2]["symbol"]))
    candidates = []
    if verdict.passed:
        sec = {r["symbol"]: r.get("sector") or sectors.get(r["symbol"]) for _, _, r in ranked}
        for r in select(ranked, TOP_N, sec, MAX_PER_SECTOR):
            candidates.append({
                "symbol": r["symbol"], "score": r["score"], "z": {"score_pct": r["score_pct"]},
                "sector": r.get("sector"), "sub_industry": r.get("sub_industry"),
                "peer_level": r["level"], "membership": r["membership"],
                **{k: _round(r.get(k)) for k in LEG_KEYS},
                "price": r.get("price"), "med_value_60d": r.get("med_value_60d"),
            })
    back = info.get("back-filled", 0) + live_info.get("back-filled", 0)
    flags = [f for f in FLAGS if back or not f.startswith("membership")]
    return {
        "screen": NAME,
        "description": DESCRIPTION,
        "legs": [["fit", cfg["weights"]["fit"]], ["own", cfg["weights"]["own"]]],
        "cadence": "monthly",
        "passed": verdict.passed,
        "blocked": None if verdict.passed else verdict.reason,
        "verdict": {k: v for k, v in verdict.to_dict().items() if k != "control_ts"},
        "months": len(spreads),
        "window": [scored[0].isoformat(), scored[-1].isoformat()] if scored else None,
        "month_ends": len(panel),
        "spread_mean": fmean(spreads) if spreads else None,
        "spread_t": _t(spreads),
        "n_ranked": len(ranked),
        "rejects": dict(rejects),
        "candidates": candidates,
        "replay": info,
        "live": live_info,
        "flags": flags,
        "fingerprint": dict(cfg),
        "stale_inputs": list(dict.fromkeys(data.stale)),
    }


# ---------------- data ----------------


def _f(v) -> float | None:
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


_ITEMS = ("price", "mktcap", "pe", "pbv", "ev_ebitda")


def _rows(con, where: str, params: Sequence) -> dict[str, dict[date, dict[str, float | None]]]:
    sql = (f"select symbol, date, item, value from factor_series where freq = 'daily'"
           f" and item in ({', '.join('?' for _ in _ITEMS)}) and {where}")
    out: dict[str, dict[date, dict]] = {}
    for sym, d, item, v in con.execute(sql, [*_ITEMS, *params]):
        out.setdefault(sym, {}).setdefault(date.fromisoformat(d), {})[item] = _f(v)
    return out


def _row(d: date, items: Mapping) -> Row:
    return Row(d, *(items.get(k) for k in _ITEMS))


def _month_rows(raw: Mapping[str, Mapping[date, Mapping]]) -> dict[str, dict[int, Row]]:
    """The last row with a price and mktcap in each month's scanned tail; a month whose tail
    holds a single row is an echo or a stray quote and is skipped."""
    out: dict[str, dict[int, Row]] = {}
    for sym, by_date in raw.items():
        per: dict[int, list[date]] = {}
        for d, items in by_date.items():
            if items.get("price") and items.get("mktcap"):
                per.setdefault(month_index(d), []).append(d)
        for k, ds in per.items():
            if len(ds) < 2:
                continue
            d = max(ds)
            out.setdefault(sym, {})[k] = _row(d, by_date[d])
    return out


def _live_rows(raw: Mapping[str, Mapping[date, Mapping]], as_of: date) -> dict[str, Row]:
    out = {}
    for sym, by_date in raw.items():
        ds = sorted(d for d, it in by_date.items() if d <= as_of and it.get("price")
                    and it.get("mktcap"))
        if len(ds) < 2 or ds[-1] - ds[-2] > ECHO_GAP:
            continue  # an echo of a delisted name, or a first quote after a long gap
        out[sym] = _row(ds[-1], by_date[ds[-1]])
    return out


def _snapshots(con) -> list[tuple[date, dict[str, Member]]]:
    rows = con.execute("select date, symbol, sector, sub_industry_id, sub_industry, industry"
                       " from industry_membership order by date, symbol")
    snaps: dict[date, dict[str, Member]] = {}
    for d, sym, sec, sid, sub, ind in rows:
        snaps.setdefault(date.fromisoformat(d), {})[sym] = Member(sec, sid, sub, ind)
    return sorted(snaps.items())


def load(series: IdxMethodSeries | None = None, as_of: date | None = None,
         cfg: Mapping = CONFIG) -> IndustryData:
    """Month-end multiples, the live rows on `as_of` (default: the store's last date), lagged
    roce, split-adjusted dividends, dated membership and the sector fallback, read-only. A
    missing store or table is a stale input and an empty result, never a crash."""
    from assist.candidates.dividend_value import _shares, adjust_dividends

    series = series or IdxMethodSeries.from_config()
    data = IndustryData()
    try:
        with series._con("factor_series", "industry_membership") as con:
            raw = _rows(con, f"cast(substr(date, 9, 2) as integer) >= {SCAN_FROM_DAY}", ())
            last = con.execute("select max(date) from factor_series where freq = 'daily'"
                               " and item = 'price'").fetchone()[0]
            data.last_date = date.fromisoformat(last) if last else None
            live_day = as_of or data.last_date
            live_raw = (_rows(con, "date > ? and date <= ?",
                              ((live_day - 2 * ECHO_GAP).isoformat(), live_day.isoformat()))
                        if live_day else {})
            data.snapshots = _snapshots(con)
        data.months = _month_rows(raw)
        data.live = _live_rows(live_raw, live_day) if live_day else {}
        data.sectors = {s: u["sector"] for s, u in series.universe().items() if u.get("sector")}
        lag = timedelta(days=cfg["lag_days"])
        data.roce = {s: [(q.period + lag, q.roce) for q in qs if q.roce is not None]
                     for s, qs in series.quarterly().items()}
        shares = _shares(series)
    except SourceUnavailable as e:
        return IndustryData(stale=[f"{SOURCE} factor_series / industry_membership ({e.reason})"])
    if as_of is not None and data.last_date is not None:
        data.last_date = min(data.last_date, as_of)
    try:
        divs = series.dividends()
    except SourceUnavailable as e:
        data.stale.append(f"{SOURCE} dividends ({e.reason}): payout read as 0")
        divs = {}
    if shares is None:
        data.stale.append(f"{SOURCE} fundamentals (no table: dividends not split-adjusted)")
        shares = {}
    for sym, recs in divs.items():
        bars = [Bar(r.date, r.price, r.mktcap) for _, r in sorted(data.months.get(sym, {}).items())]
        data.dividends[sym] = adjust_dividends(recs, bars, shares.get(sym, {})) if bars else recs
    return data


def run_live(as_of: date | None = None, **kw) -> dict:
    """The screen over the real stores (read-only), against idx-method's screener table."""
    import json

    from assist.candidates.factors import load_factors
    from assist.sources.idxmethod_stocks import IdxMethodStocks

    stocks = IdxMethodStocks.from_config()
    table, stale = load_factors(stocks, as_of)
    bar_dates = [r["bar_date"] for r in table.values() if r.get("bar_date")]
    day = max(bar_dates) if bar_dates else (as_of or date.today())
    data = load(IdxMethodSeries(stocks.root), day)
    data.stale += stale
    flagged: set[str] = set()
    try:
        with (stocks.root / "data" / "special_boards.json").open(encoding="utf-8") as f:
            boards = json.load(f)
        flagged = {s for b in GATES["exclude_boards"] for s in boards.get(b, [])}
    except (OSError, ValueError):
        data.stale.append(f"{SOURCE} special_boards.json (missing)")
    return run(data, table, as_of=day, flagged=flagged, **kw)
