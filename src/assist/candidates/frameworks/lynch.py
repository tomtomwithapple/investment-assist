"""Lynch categories and the Lynch ratio (P117, PLAN S100; frameworks document §3.2). Context
only: role `context`, gate `untested`; it changes no stance, size, rank or hurdle. The
two-minute drill is a human's job and is not built.

**Inputs on date d** (point in time, `LAG_DAYS` 120 through `Fundamentals.available`):

- t = the newest `factor_series` quarter knowable by d. EPS at t − 4k quarters (k = 0..5) =
  `ni_ttm` ÷ shares, shares = `mktcap / price` of the last bar on or before that period end
  (the split-adjusted basis the bars and the store's dividends share, as `residual_income`), so
  a split never moves EPS growth and a rights issue dilutes it, as it should.
- The window is the longest run of 5, 4 or 3 whole years back from t with an EPS in every year
  (k = 0..K); fewer than 3 → n/a (§0.3, never imputed).
- g = EPS CAGR over the window, (EPS_t / EPS_{t−4K})^(1/K) − 1, in %; undefined when either end
  is <= 0. Stability: `declines`, the years in the window whose EPS fell, and `sharp_declines`,
  those where it fell by 20% or more.
- PE = mktcap(d) ÷ NI TTM(t); P/B = mktcap(d) ÷ equity(t); dividend yield = split-adjusted
  dividends gone ex in the year to d ÷ price(d); net cash = −`net_debt`(t), not for banks (a
  bank's net debt is its funding, not spare cash).
- Sector: idx-method `industry_membership` (IDX-IC), which holds only today's snapshot (from
  2026-11-06), so every past date reads today's industry, flagged in the replay. A name with no
  membership (most delisted names) falls back to `factor_universe` sector, flagged.

**Category** — the first rule that holds, in this order:

| # | category | rule |
|---|---|---|
| 1 | turnaround | EPS <= 0 now or in any year of the window, or EPS fell >= 50% in the last year |
| 2 | cyclical | an IDX-IC cyclical industry (below), or `sharp_declines` >= 2 (the pattern) |
| 3 | asset_play | P/B <= 0.7, or (not a bank) net cash >= 50% of mktcap |
| 4 | fast_grower | g >= 20% |
| 5 | stalwart | 5% <= g < 20% |
| 6 | slow_grower | g < 5% |

Thresholds are the document's (slow < 5%, stalwart from 5%, fast >= 20%); its gap between 12%
and 20% is given to the stalwart, since Lynch's own stalwarts run 10–12% and his fast growers
from 20%, and nothing here asks a stalwart to be large (on IDX a size line would leave a handful
of names). Turnaround comes first because a loss or a halved EPS makes the growth rate
meaningless; cyclical before asset play because a cyclical at its trough is cheap on book for a
reason (Lynch: a cyclical's P/E is low at the peak, its P/B at the bottom).

**Cyclical industries (IDX-IC)**: Batu Bara (coal), Minyak & Gas (oil and gas producers and
refiners, but not its sub-industry Penyimpanan & Distribusi Migas: PGAS's and AKRA's gas toll
and fuel distribution margins do not follow the commodity price), Pendukung Minyak, Gas & Batu
Bara (drilling and mining services, paid on miners' capex), Logam & Mineral (nickel, gold,
copper, tin, steel, aluminium), Barang Kimia (petrochemicals and fertiliser chemicals price off
oil and gas), Perhutanan & Kertas (pulp and paper) and the sub-industry Pertanian (plantations:
CPO). That is mining, coal, energy and chemicals, as the brief asks, plus the two other IDX
commodity earners. Cement (Material Konstruksi), packaging, autos and airlines are left out:
their margins follow domestic demand and input costs, not one traded price; a name among them
whose EPS swings is still caught by the earnings pattern. With no membership the fallback is
sector Energi only (Barang Baku also holds cement and packaging).

**Ratio.** Lynch ratio = (g + dividend yield) / PE (both in %): < 1 poor, ~1.5 acceptable, >= 2
attractive. PEG = PE / g (None when g <= 0) in `components`. `score` = the Lynch ratio (None,
flagged, when PE <= 0 or g is undefined), `signal` = the category.

**Replay** (`Lynch.replay`, measured on S94's board): at each quarter end, every `factor_series`
name (delisted included) with a bar in the last 10 days, price >= the screens' floor and mktcap
>= IDR 1T, classed slow grower or stalwart (the principle's dividend payers) with a Lynch ratio,
ranked by the ratio; the board holds the top fifth. The placebo (top vs bottom quintile
next-quarter return, `dividend_value.evaluate_replay`) is reported, not used.

Hashed by `journal.RULE_GLOBS` (`candidates/**/*.py`).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from assist.candidates.frameworks.base import Framework, FrameworkResult, register
from assist.candidates.frameworks.piotroski import shift
from assist.candidates.frameworks.residual_income import BankRIInputs, _trailing

__all__ = ["CATEGORIES", "CONFIG", "CYCLICAL_INDUSTRIES", "NAME", "POOL", "Lynch",
           "LynchBetaInputs", "is_cyclical", "load_industries", "lynch", "replay_panel"]

VERSION = "0.1.0"
NAME = "lynch"
CATEGORIES = ("turnaround", "cyclical", "asset_play", "fast_grower", "stalwart", "slow_grower")
POOL = ("slow_grower", "stalwart")  # the replay's dividend payers
CONFIG = {
    "max_years": 5,
    "min_years": 3,
    "slow_below_pct": 5.0,
    "fast_from_pct": 20.0,
    "sharp_decline": 0.5,  # EPS fell by at least this share in the last year → turnaround
    "cyclical_fall": 0.2,  # a year whose EPS fell by at least this share is a sharp decline
    "cyclical_declines": 2,  # sharp declines in the window → cyclical by pattern
    "asset_pb": 0.7,
    "asset_net_cash": 0.5,  # net cash ÷ mktcap
    "max_bar_age_days": 10,
    "replay_min_mktcap": 1e12,
    "min_pool": 10,
}
CYCLICAL_INDUSTRIES = frozenset({
    "Batu Bara", "Minyak & Gas", "Pendukung Minyak, Gas & Batu Bara", "Logam & Mineral",
    "Barang Kimia", "Perhutanan & Kertas"})
CYCLICAL_SUB_INDUSTRIES = frozenset({"Pertanian"})
NOT_CYCLICAL_SUB_INDUSTRIES = frozenset({"Penyimpanan & Distribusi Migas"})
CYCLICAL_SECTORS = frozenset({"Energi"})  # fallback when a name has no IDX-IC industry


@dataclass(frozen=True)
class LynchBetaInputs(BankRIInputs):
    """`BankRIInputs` (so the F-score and bank RI read the same object) plus the JCI as (date,
    close), today's IDX-IC membership {sym: {sector, industry, sub_industry}} and the
    `factor_universe` sector per symbol (the fallback)."""

    jci: Sequence[tuple[date, float]] = ()
    industries: Mapping[str, Mapping[str, str | None]] = field(default_factory=dict)
    sectors: Mapping[str, str] = field(default_factory=dict)


def is_cyclical(industry: Mapping[str, str | None] | None, sector: str | None
                ) -> tuple[bool, str | None]:
    """(cyclical by sector?, a flag when only the sector was known)."""
    if industry and (industry.get("industry") or industry.get("sub_industry")):
        sub = industry.get("sub_industry")
        if sub in NOT_CYCLICAL_SUB_INDUSTRIES:
            return False, None
        return (industry.get("industry") in CYCLICAL_INDUSTRIES
                or sub in CYCLICAL_SUB_INDUSTRIES), None
    sec = (industry or {}).get("sector") or sector
    if not sec:
        return False, "no IDX-IC industry or sector: cyclical only by earnings pattern"
    return sec in CYCLICAL_SECTORS, f"no IDX-IC industry: cyclical by sector only ({sec})"


def _bar_at(bars: Sequence, d: date, dates: Sequence[date] | None = None) -> Any:
    i = bisect_right(dates if dates is not None else [b.date for b in bars], d)
    while i > 0:
        b = bars[i - 1]
        if b.price and b.mktcap and b.price > 0 and b.mktcap > 0:
            return b
        i -= 1
    return None


def lynch(sym: str, quarters: Sequence, bars: Sequence, divs: Sequence[Mapping], d: date, *,
          industry: Mapping[str, str | None] | None = None, sector: str | None = None,
          bank: bool = False, cfg: Mapping = CONFIG, dates: Sequence[date] | None = None
          ) -> FrameworkResult:
    """`sym`'s Lynch category and ratio as knowable on `d` (module docstring). `dates` is
    `[b.date for b in bars]`, passed by a caller that has it already."""
    fw = Lynch()
    dates = dates if dates is not None else [b.date for b in bars]
    known = [q for q in quarters if q.available <= d]
    if not known:
        return fw.missing(sym, None, f"no quarterly fundamentals available by {d}")
    cur = max(known, key=lambda q: q.period)
    t = cur.period
    bar = _bar_at(bars, d, dates)
    if bar is None:
        return fw.missing(sym, cur.available, f"no bar with a price and mktcap by {d}")
    by = {q.period: q for q in known}
    eps: list[float] = []
    for k in range(cfg["max_years"] + 1):
        q = by.get(shift(t, 4 * k))
        b = _bar_at(bars, shift(t, 4 * k), dates) if q is not None else None
        if q is None or q.ni_ttm is None or b is None:
            break
        eps.append(q.ni_ttm / (b.mktcap / b.price))
    years = len(eps) - 1
    if years < cfg["min_years"]:
        return fw.missing(sym, cur.available, f"EPS for only {max(years, 0)} whole years back "
                          f"from {t}: needs {cfg['min_years']} years in a row")
    flags: list[str] = []
    e0, base = eps[0], eps[years]
    declines = sum(1 for j in range(years) if eps[j] < eps[j + 1])
    sharp = sum(1 for j in range(years)
                if eps[j + 1] > 0 and eps[j] <= (1 - cfg["cyclical_fall"]) * eps[j + 1])
    g = ((e0 / base) ** (1 / years) - 1) * 100 if e0 > 0 and base > 0 else None
    pe = bar.mktcap / cur.ni_ttm if cur.ni_ttm else None
    pb = bar.mktcap / cur.equity if cur.equity and cur.equity > 0 else None
    dy = _trailing(divs, d) / bar.price * 100
    net_cash = (None if bank or cur.net_debt is None else -cur.net_debt / bar.mktcap)
    cyc_sector, cyc_flag = is_cyclical(industry, sector)
    if cyc_flag:
        flags.append(cyc_flag)
    c: dict[str, float | None] = {f"eps_y{k}": e for k, e in enumerate(eps)}
    c |= {"growth_years": float(years), "growth_pct": g, "declines": float(declines),
          "sharp_declines": float(sharp),
          "pe": pe, "pb": pb, "dividend_yield_pct": dy, "net_cash_to_mktcap": net_cash,
          "mktcap": bar.mktcap, "price": bar.price, "cyclical_industry": float(cyc_sector)}

    if min(eps) <= 0 or (eps[1] > 0 and e0 <= (1 - cfg["sharp_decline"]) * eps[1]):
        cat = "turnaround"
    elif cyc_sector or sharp >= cfg["cyclical_declines"]:
        cat = "cyclical"
        if not cyc_sector:
            flags.append(f"cyclical by earnings pattern: EPS fell 20% or more in {sharp} of "
                         f"{years} years")
        flags.append("cyclical: Lynch's P/E is lowest at the cycle peak, so the ratio "
                     "flatters a cyclical at its top")
    elif (pb is not None and pb <= cfg["asset_pb"]) or (
            net_cash is not None and net_cash >= cfg["asset_net_cash"]):
        cat = "asset_play"
    elif g >= cfg["fast_from_pct"]:
        cat = "fast_grower"
    elif g >= cfg["slow_below_pct"]:
        cat = "stalwart"
    else:
        cat = "slow_grower"
    if bank:
        flags.append("bank: net debt is funding, not net cash; asset play by P/B only")

    c["peg"] = pe / g if pe is not None and pe > 0 and g is not None and g > 0 else None
    if g is None:
        flags.append(f"EPS growth undefined: EPS <= 0 at an end of the window (now {e0:.2f}, "
                     f"base year {base:.2f})")
    if pe is None or pe <= 0:
        flags.append("PE <= 0 or undefined: no Lynch ratio")
    ratio = (g + dy) / pe if g is not None and pe is not None and pe > 0 else None
    c["lynch_ratio"] = ratio
    if g is not None and g > 50:
        flags.append(f"EPS growth {g:.0f}% a year: Lynch distrusts growth above 50%")
    return fw.result(sym, cur.available, ratio, cat, c, *flags)


def replay_panel(bars: Mapping[str, Sequence], quarters: Mapping[str, Sequence],
                 dividends: Mapping[str, Sequence[Mapping]], *,
                 industries: Mapping[str, Mapping], sectors: Mapping[str, str],
                 banks: frozenset[str] | set[str], qends: Sequence[date], cfg: Mapping = CONFIG
                 ) -> list[tuple[date, list[dict]]]:
    """→ [(quarter end, [{symbol, category, lynch_ratio, fwd}])]: the slow growers and
    stalwarts with a Lynch ratio on that date, with the price-plus-dividend return to the next
    quarter end (None on the last)."""
    from assist.candidates.screens import GATES

    idx = {s: [b.date for b in bs] for s, bs in bars.items()}
    out = []
    for i, q in enumerate(qends):
        q1 = qends[i + 1] if i + 1 < len(qends) else None
        recs = []
        for sym in sorted(quarters):
            bs = bars.get(sym) or []
            ds = idx.get(sym) or []
            bar = _bar_at(bs, q, ds)
            if (bar is None or bar.date < q - timedelta(days=cfg["max_bar_age_days"])
                    or bar.mktcap < cfg["replay_min_mktcap"] or bar.price < GATES["min_price"]):
                continue
            divs = dividends.get(sym) or []
            res = lynch(sym, quarters[sym], bs, divs, q, industry=industries.get(sym),
                        sector=sectors.get(sym), bank=sym in banks, cfg=cfg, dates=ds)
            if res.signal not in POOL or res.score is None:
                continue
            fwd = None
            end = _bar_at(bs, q1, ds) if q1 else None
            if end is not None and end.date > bar.date:
                paid = sum(r["value"] for r in divs if r.get("value") is not None
                           and bar.date < date.fromisoformat(r["ex"]) <= end.date)
                fwd = (end.price + paid) / bar.price - 1
            recs.append({"symbol": sym, "category": res.signal, "lynch_ratio": res.score,
                         "fwd": fwd})
        out.append((q, recs))
    return out


def load_industries(series: Any) -> dict[str, dict[str, str | None]]:
    """The newest `industry_membership` snapshot {sym: {sector, industry, sub_industry}},
    read-only; {} when the table is missing."""
    import sqlite3

    from assist.sources.base import SourceUnavailable

    try:
        with series._con("industry_membership") as con:
            rows = con.execute(
                "select symbol, sector, industry, sub_industry from industry_membership"
                " where date = (select max(date) from industry_membership)").fetchall()
    except (sqlite3.Error, SourceUnavailable):
        return {}
    return {s: {"sector": sec, "industry": ind, "sub_industry": sub}
            for s, sec, ind, sub in rows}


@register
class Lynch(Framework):
    """Lynch: category from EPS growth, stability, sector and P/B; ratio (g + yield) / PE."""

    name = NAME
    VERSION = VERSION

    def evaluate(self, sym: str, inputs) -> FrameworkResult:
        if not isinstance(inputs, LynchBetaInputs):
            return self.missing(sym, None, "no point-in-time Lynch inputs given")
        if sym not in inputs.quarters:
            return self.missing(sym, None, "no quarterly fundamentals for this name")
        return lynch(sym, inputs.quarters[sym], inputs.bars.get(sym) or (),
                     inputs.dividends.get(sym) or (), inputs.as_of,
                     industry=inputs.industries.get(sym), sector=inputs.sectors.get(sym),
                     bank=sym in inputs.banks)

    def replay(self, ctx: Any) -> Any:
        """S94: the board's replay over the loaded stores (`framework_board.LiveContext`)."""
        from assist import framework_board as fb
        from assist.candidates import dividend_value as dv
        from assist.sources.idxmethod_series import IdxMethodSeries, quarter_ends

        data = ctx.dividend_data
        banks = frozenset(s for s, r in ctx.table.items() if r.get("car"))
        industries = load_industries(IdxMethodSeries(ctx.stocks.root))
        firsts = [bs[0].date for bs in data.bars.values() if bs]
        qes = quarter_ends(min(firsts), ctx.bar_date) if firsts else []
        panel = replay_panel(data.bars, data.quarters, data.dividends, industries=industries,
                             sectors=data.sectors, banks=banks, qends=qes)
        scored = [(q, [x for x in recs if x["fwd"] is not None]) for q, recs in panel]
        verdict = dv.evaluate_replay([(q, [{"symbol": x["symbol"],
                                            "expected_pt": x["lynch_ratio"], "fwd": x["fwd"]}
                                           for x in recs]) for q, recs in scored],
                                     min_pool=CONFIG["min_pool"])
        sizes = [len(r) for _, r in panel if r]
        return fb.from_ranked(
            NAME, "Lynch ratio (EPS growth + dividend yield) / PE among slow growers and "
            "stalwarts.", "top quintile by Lynch ratio of slow growers and stalwarts, names "
            "over IDR 1T", fb.ranked_by(panel, "lynch_ratio"), CONFIG["min_pool"], verdict,
            kind="framework",
            notes=[f"pool {min(sizes, default=0)}–{max(sizes, default=0)} slow growers and "
                   "stalwarts a quarter",
                   "industry is today's IDX-IC snapshot on every date (membership starts "
                   "2026-11-06); names without one fall back to factor_universe sector",
                   "banks are today's (screener CAR); context only, gate reported not used"])
