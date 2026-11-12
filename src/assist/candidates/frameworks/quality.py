"""Gross profitability (GP/A) and DuPont (P116, PLAN S99; frameworks document §4.3 and §2.4).
Context only: role `context`, gate `untested`; nothing here changes a stance, size, floor or
fair price.

**Point in time** (§0.3, as S95): on date d, t = the newest `factor_series` quarter knowable by
d (period end + `LAG_DAYS` 120, `Fundamentals.available`), t4 the quarter end a year earlier.
Flows are trailing twelve months: `ni_ttm` from `factor_series`; revenue, gross, operating and
pretax profit each the sum of four discrete `fundamentals` quarters to t (a missing quarter is
never filled in). `fundamentals` flows are as reported (USD for a USD reporter such as ADRO)
while its `equity` and `factor_series` are in IDR, so each quarter's flow is converted at that
quarter's `equity` / `equity_raw` (the store's own rate; 1 for an IDR reporter), flagged when
not IDR or unchecked (no `equity_raw`: read as IDR). Stocks are `factor_series` balance
sheets (`total_assets`, `equity`), never `fundamentals` `bs.assets`, which is not total assets.

**GP/A** (Novy-Marx; QMJ is skipped, phase Q decision 8) = gross profit TTM ÷ total assets at t.
Banks (a screener CAR) and other financials (sector `Keuangan`) are n/a with a flag: a bank's
"gross profit" is net interest income and an insurer's has no cost of goods. `signal`: "high"
in the top fifth of the same-date cross-section of computable names, "low" in the bottom
fifth, else "middle" (`components` `rank`, `n_cross`, `pct`). Replay (`GrossProfitability.
replay`, S94's board): each quarter end the top fifth by GP/A against the pool of non-financial
names with a bar in the last 10 days, price >= the screens' floor and mktcap >= IDR 1T; the
placebo (top vs bottom quintile next-quarter return) is reported, not used. `fundamentals`
holds no delisted name, so the pool is survivors only.

**DuPont.** With average equity E and average total assets A (t and t4; the ending value when
t4 is missing, flagged), NI = `ni_ttm` (to the parent, the same ROE S96 values):

    3-step  ROE = NI/Sales × Sales/A × A/E                (net margin, turnover, multiplier)
    5-step  ROE = NI/EBT × EBT/EBIT × EBIT/Sales × Sales/A × A/E

EBIT is `operating_profit`, EBT `pretax_profit`. The 5-step needs both, positive; else it is
flagged and the 3-step stands. NI is to the parent while EBT is the group's, so the tax burden
also carries the minority share; EBT above EBIT (associates' income, net interest income) gives
an interest burden above 1, flagged. Banks and financials get the 3-step only. ROE change
attribution (Δln ROE = Σ Δln component, 3-step) against the year before, when t4 and t8 are
both there.

**Leverage-driven ROE flag.** With r the IDN hurdle (the cost of equity S96 fades ROE to) and
M* the median multiplier of the name's peers on the same date:

    leverage-driven  ⇔  ROE > r  and  M > M*  and  ROA × M* < r

ROA × M* is the ROE the business would earn at its peers' typical leverage ("ROE ex leverage").
The flag says the excess return over the cost of equity exists only because the balance sheet
is more levered than its peers': at typical leverage it would not clear r. Peers are the
sector, because normal leverage is structural (a bank near 7x, a miner near 2x); banks are
compared with banks. A sector with fewer than `CONFIG["min_peers"]` names uses the market
median of non-banks, flagged (a bank short of bank peers is unrated). An ROE at or below r is
"below hurdle" whatever its leverage: there is no excess return to explain. `signal`:
"leverage-driven" | "operating" | "below hurdle" | "unrated" (no hurdle).

**Sustainable ROE** (feeds S96): ROA × M* when leverage-driven, else the DuPont ROE; None when
unrated. `residual_income.CONFIG["roe_source"]` = "dupont_sustainable" makes bank RI fade from
it; the default "ttm" keeps S96 as it was.

Hashed by `journal.RULE_GLOBS` (`candidates/**/*.py`).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any

from assist.candidates.frameworks.base import Framework, FrameworkResult, inputs_for, register
from assist.candidates.frameworks.piotroski import PiotroskiInputs, shift
from assist.candidates.frameworks.residual_income import BankRIInputs

__all__ = ["CONFIG", "DUPONT", "FINANCIAL_SECTOR", "GPA", "ITEMS", "DuPont",
           "GrossProfitability", "QualityInputs", "dupont", "gp_a", "leverage", "replay_panel",
           "sustainable_roe"]

VERSION = "0.1.0"
GPA = "gp_a"
DUPONT = "dupont"
FINANCIAL_SECTOR = "Keuangan"
ITEMS = ("revenue", "gross_profit", "operating_profit", "pretax_profit", "equity",
         "equity_raw")  # `fundamentals`; equity / equity_raw is the store's own FX rate
CONFIG = {
    "min_peers": 5,  # peers a sector needs for its own median multiplier
    "max_bar_age_days": 10,  # replay: no bar this close to the quarter end is out
    "replay_min_mktcap": 1e12,  # IDR, the dividend replay's liquidity stand-in
    "min_pool": 30,  # names a quarter needs before the board scores it (dividend_value's)
}


@dataclass(frozen=True)
class QualityInputs(BankRIInputs):
    """`BankRIInputs` (so S95 and S96 read the same object) plus sectors per symbol
    (`factor_universe`); `statements` should hold `ITEMS` for the DuPont 5-step."""

    sectors: Mapping[str, str] = field(default_factory=dict)


def _cache(inputs: Any) -> dict:
    return inputs.__dict__.setdefault("_quality_cache", {})


def _financial(sym: str, inputs: Any) -> str | None:
    if sym in inputs.banks:
        return "bank"
    if (getattr(inputs, "sectors", {}) or {}).get(sym) == FINANCIAL_SECTOR:
        return f"financial ({FINANCIAL_SECTOR})"
    return None


def _known(quarters: Sequence, d: date):
    known = [q for q in quarters if q.available <= d]
    if not known:
        return None, {}
    cur = max(known, key=lambda q: q.period)
    return cur, {q.period: q for q in known}


def _pos(x: float | None) -> bool:
    return x is not None and x > 0


def _rate(row: Mapping[str, float]) -> float | None:
    """IDR per unit of the quarter's reporting currency: `equity` (in IDR) / `equity_raw` (as
    reported), 1 within 2%; None when either is missing."""
    e, raw = row.get("equity"), row.get("equity_raw")
    if not e or not raw or (e > 0) != (raw > 0):
        return None
    k = e / raw
    return 1.0 if abs(k - 1) < 0.02 else k


def _ttm(st: Mapping[date, Mapping[str, float]], t: date, item: str) -> float | None:
    """Sum of the four discrete quarters to `t` in IDR (each at its own quarter's rate, 1 when
    unchecked); None when one is missing."""
    total = 0.0
    for k in range(4):
        row = st.get(shift(t, k)) or {}
        v = row.get(item)
        if v is None:
            return None
        total += v * (_rate(row) or 1.0)
    return total


def _fx(st: Mapping[date, Mapping[str, float]], t: date) -> tuple[float | None, list[str]]:
    rates = [_rate(st.get(shift(t, k)) or {}) for k in range(4)]
    if any(r is None for r in rates):
        return None, [f"statement currency unchecked (no equity_raw in a quarter to {t}): "
                      "flows read as IDR"]
    if any(r != 1.0 for r in rates):
        return rates[0], ["statements in a foreign currency: flows converted to IDR at the "
                          f"store's equity / equity_raw per quarter ({rates[0]:,.0f} at {t})"]
    return 1.0, []


# ---------------- GP/A ----------------


def gp_a(sym: str, quarters: Sequence, statements: Mapping[date, Mapping[str, float]] | None,
         d: date) -> FrameworkResult:
    """GP/A of `sym` as knowable on `d`, without its cross-sectional signal ("middle")."""
    fw = GrossProfitability()
    cur, _ = _known(quarters, d)
    if cur is None:
        return fw.missing(sym, None, f"no quarterly fundamentals available by {d}")
    t = cur.period
    if not _pos(cur.total_assets):
        return fw.missing(sym, cur.available, f"no total assets at {t}")
    st = statements or {}
    gp = _ttm(st, t, "gross_profit")
    if gp is None:
        return fw.missing(sym, cur.available, f"no four quarters of gross profit to {t}")
    rev = _ttm(st, t, "revenue")
    rate, flags = _fx(st, t)
    c: dict[str, float | None] = {"gross_profit_ttm": gp, "total_assets": cur.total_assets,
                                  "revenue_ttm": rev,
                                  "gross_margin": gp / rev if _pos(rev) else None,
                                  "fx_rate": rate}
    score = gp / cur.total_assets
    c["gp_a"] = score
    return fw.result(sym, cur.available, score, "middle", c, *flags)


def _cross_section(inputs: PiotroskiInputs, d: date) -> dict[str, float]:
    key = ("gpa", d)
    cache = _cache(inputs)
    if key not in cache:
        out = {}
        for s, qs in inputs.quarters.items():
            if _financial(s, inputs):
                continue
            r = gp_a(s, qs, inputs.statements.get(s), d)
            if r.score is not None:
                out[s] = r.score
        cache[key] = out
    return cache[key]


@register
class GrossProfitability(Framework):
    """Novy-Marx gross profitability: gross profit TTM over total assets."""

    name = GPA
    VERSION = VERSION

    def evaluate(self, sym: str, inputs) -> FrameworkResult:
        inputs = inputs_for(inputs, GPA)
        if not isinstance(inputs, PiotroskiInputs):
            return self.missing(sym, None, "no point-in-time IDN statements given")
        if sym not in inputs.quarters:
            return self.missing(sym, None, "no quarterly fundamentals for this name")
        fin = _financial(sym, inputs)
        if fin:
            return self.missing(sym, None, f"{fin}: gross profit is not a cost-of-goods margin"
                                " (a bank's is net interest income), GP/A not meaningful")
        res = gp_a(sym, inputs.quarters[sym], inputs.statements.get(sym), inputs.as_of)
        if res.score is None:
            return res
        cross = _cross_section(inputs, inputs.as_of)
        ranked = sorted(cross, key=lambda s: (-cross[s], s))
        n, rank = len(ranked), ranked.index(sym)
        cut = n // 5
        signal = ("high" if rank < cut else "low" if rank >= n - cut else "middle") if cut \
            else "middle"
        below = sum(v < res.score for v in cross.values())
        c = dict(res.components) | {"rank": float(rank + 1), "n_cross": float(n),
                                    "pct": below / (n - 1) if n > 1 else None}
        return self.result(sym, res.as_of, res.score, signal, c, *res.flags)

    def replay(self, ctx: Any) -> Any:
        """S94: the board's replay over the loaded stores (`framework_board.LiveContext`)."""
        from assist import framework_board as fb
        from assist.candidates import dividend_value as dv
        from assist.sources.idxmethod_series import IdxMethodSeries, quarter_ends

        data = ctx.dividend_data
        st = IdxMethodSeries(ctx.stocks.root).statements(
            ("revenue", "gross_profit", "equity", "equity_raw"))
        banks = {s for s, r in ctx.table.items() if r.get("car")}
        fin = {s for s, sec in data.sectors.items() if sec == FINANCIAL_SECTOR}
        syms = [s for s in st if s not in banks | fin and data.bars.get(s)]
        firsts = [data.bars[s][0].date for s in syms]
        qes = quarter_ends(min(firsts), ctx.bar_date) if firsts else []
        panel = replay_panel(data.bars, data.quarters, st, data.dividends, banks | fin, qes)
        scored = [(q, [{"symbol": x["symbol"], "expected_pt": x["gp_a"], "fwd": x["fwd"]}
                       for x in recs if x["fwd"] is not None]) for q, recs in panel]
        verdict = dv.evaluate_replay(scored, min_pool=CONFIG["min_pool"])
        sizes = [len(r) for _, r in panel if r]
        return fb.from_ranked(
            GPA, "Gross profitability (Novy-Marx): gross profit over total assets, high first.",
            "top quintile by GP/A (gross profit TTM ÷ total assets), non-financial names over "
            "IDR 1T", fb.ranked_by(panel, "gp_a"), CONFIG["min_pool"], verdict,
            kind="framework",
            notes=[f"banks (screener CAR, today's) and {FINANCIAL_SECTOR} are out: "
                   f"{len(banks | fin)} names",
                   f"pool {min(sizes, default=0)}–{max(sizes, default=0)} names a quarter; "
                   "gross profit from idx-method fundamentals, which hold no delisted name "
                   "(survivors only)",
                   "gate is the placebo on top vs bottom quintile next-quarter return; context "
                   "only"])


def replay_panel(bars: Mapping[str, Sequence], quarters: Mapping[str, Sequence],
                 statements: Mapping[str, Mapping[date, Mapping[str, float]]],
                 dividends: Mapping[str, Sequence[Mapping]], excluded: set[str] | frozenset,
                 qends: Sequence[date], *, cfg: Mapping = CONFIG
                 ) -> list[tuple[date, list[dict]]]:
    """→ [(quarter end, [{symbol, gp_a, fwd}])]: the non-excluded names with a recent bar,
    price >= the screens' floor and mktcap >= `replay_min_mktcap`, and the price-plus-dividend
    return to the next quarter end (None on the last). An n/a GP/A is left out."""
    from assist.candidates.screens import GATES

    syms = sorted(s for s in statements if s not in excluded and bars.get(s)
                  and quarters.get(s))
    good = {s: [b for b in bars[s] if b.price and b.mktcap and b.price > 0 and b.mktcap > 0]
            for s in syms}
    dates = {s: [b.date for b in good[s]] for s in syms}

    def bar_at(s: str, d: date):
        i = bisect_right(dates[s], d)
        return good[s][i - 1] if i else None

    out = []
    for i, q in enumerate(qends):
        q1 = qends[i + 1] if i + 1 < len(qends) else None
        recs = []
        for s in syms:
            bar = bar_at(s, q)
            if (bar is None or bar.date < q - timedelta(days=cfg["max_bar_age_days"])
                    or bar.mktcap < cfg["replay_min_mktcap"] or bar.price < GATES["min_price"]):
                continue
            res = gp_a(s, quarters[s], statements.get(s), q)
            if res.score is None:
                continue
            fwd = None
            end = bar_at(s, q1) if q1 else None
            if end is not None and end.date > bar.date:
                paid = sum(r["value"] for r in dividends.get(s) or () if r.get("value")
                           is not None and bar.date < date.fromisoformat(r["ex"]) <= end.date)
                fwd = (end.price + paid) / bar.price - 1
            recs.append({"symbol": s, "gp_a": res.score, "fwd": fwd})
        out.append((q, recs))
    return out


# ---------------- DuPont ----------------


def _core(quarters: Sequence, d: date) -> tuple[Any, dict, list[str], str | None]:
    """ROE, ROA and the multiplier on `d`: (t's quarter, components, flags, n/a reason)."""
    cur, by = _known(quarters, d)
    if cur is None:
        return None, {}, [], f"no quarterly fundamentals available by {d}"
    t = cur.period
    if cur.ni_ttm is None:
        return cur, {}, [], f"no NI TTM at {t}"
    if cur.equity is None or cur.equity <= 0:
        return cur, {}, [], (f"no book equity at {t}" if cur.equity is None else
                              f"book equity {cur.equity:,.0f} <= 0 at {t}: no ROE")
    if not _pos(cur.total_assets):
        return cur, {}, [], f"no total assets at {t}"
    prior = by.get(shift(t, 4))
    flags = []
    if prior is not None and _pos(prior.equity):
        e = (cur.equity + prior.equity) / 2
    else:
        e = cur.equity
        flags.append(f"no equity a year before {t}: ROE on ending equity")
    if prior is not None and _pos(prior.total_assets):
        a = (cur.total_assets + prior.total_assets) / 2
    else:
        a = cur.total_assets
        flags.append(f"no total assets a year before {t}: turnover on ending assets")
    ni = cur.ni_ttm
    return cur, {"ni_ttm": ni, "avg_equity": e, "avg_assets": a, "roe": ni / e,
                 "roa": ni / a, "equity_multiplier": a / e}, flags, None


def _multipliers(inputs: PiotroskiInputs, d: date) -> dict[str, float]:
    key = ("mult", d)
    cache = _cache(inputs)
    if key not in cache:
        out = {}
        for s, qs in inputs.quarters.items():
            _, c, _, err = _core(qs, d)
            if err is None:
                out[s] = c["equity_multiplier"]
        cache[key] = out
    return cache[key]


def _peer_median(sym: str, inputs: PiotroskiInputs, d: date
                 ) -> tuple[float | None, int, str | None]:
    mult = _multipliers(inputs, d)
    k = CONFIG["min_peers"]
    if sym in inputs.banks:
        peers = [m for s, m in mult.items() if s in inputs.banks]
        if len(peers) < k:
            return None, len(peers), (f"only {len(peers)} banks with a multiplier on {d} "
                                      f"(minimum {k}): leverage flag not computed")
        return median(peers), len(peers), None
    sectors = getattr(inputs, "sectors", {}) or {}
    sec = sectors.get(sym)
    peers = [m for s, m in mult.items() if s not in inputs.banks and sec
             and sectors.get(s) == sec]
    if len(peers) >= k:
        return median(peers), len(peers), None
    market = [m for s, m in mult.items() if s not in inputs.banks]
    if len(market) < k:
        return None, len(market), f"only {len(market)} names with a multiplier on {d}: " \
            "leverage flag not computed"
    why = f"sector {sec!r} has {len(peers)} peers" if sec else "no sector"
    return median(market), len(market), (f"{why} (minimum {k}): peer multiplier is the market "
                                         "median of non-banks")


def leverage(sym: str, inputs: PiotroskiInputs, d: date | None = None
             ) -> tuple[Any, dict[str, float | None], list[str], str | None]:
    """ROE, ROA, multiplier and the leverage-driven flag of `sym` on `d` (default
    `inputs.as_of`): (t's quarter, components, flags, n/a reason). Needs no revenue."""
    d = d or inputs.as_of
    cur, c, flags, err = _core(inputs.quarters.get(sym) or (), d)
    if err:
        return cur, c, flags, err
    med, n, why = _peer_median(sym, inputs, d)
    req = getattr(inputs, "required_pt", None)
    r = None if req is None else req / 100
    c |= {"r": r, "peer_median_multiplier": med, "n_peers": float(n),
          "roe_ex_leverage": None if med is None else c["roa"] * med,
          "leverage_driven": None, "sustainable_roe": None}
    if why:
        flags.append(why)
    if r is None:
        flags.append("no IDN hurdle: leverage flag not computed")
    elif med is not None:
        driven = c["roe"] > r and c["equity_multiplier"] > med and c["roa"] * med < r
        c["leverage_driven"] = 1.0 if driven else 0.0
        c["sustainable_roe"] = c["roa"] * med if driven else c["roe"]
        if driven:
            flags.append(f"leverage-driven ROE: {c['roe']:.1%} clears the hurdle {r:.1%} only "
                         f"on a {c['equity_multiplier']:.2f}x multiplier; at the peer median "
                         f"{med:.2f}x it is {c['roa'] * med:.1%}")
    return cur, c, flags, None


def sustainable_roe(sym: str, inputs: PiotroskiInputs, d: date | None = None) -> float | None:
    """ROA × peer median multiplier when the ROE is leverage-driven, else the DuPont ROE; None
    when it cannot be rated (S96's `roe_source` switch)."""
    _, c, _, err = leverage(sym, inputs, d)
    return None if err else c.get("sustainable_roe")


def _three(quarters: Sequence, st: Mapping, t: date) -> dict | None:
    """3-step components at quarter `t` with strict averages (attribution only)."""
    by = {q.period: q for q in quarters}
    q, p = by.get(t), by.get(shift(t, 4))
    rev = _ttm(st, t, "revenue")
    if (q is None or p is None or not _pos(q.ni_ttm) or not _pos(rev)
            or not all(_pos(x) for x in (q.equity, p.equity, q.total_assets, p.total_assets))):
        return None
    e, a = (q.equity + p.equity) / 2, (q.total_assets + p.total_assets) / 2
    return {"roe": q.ni_ttm / e, "net_margin": q.ni_ttm / rev, "asset_turnover": rev / a,
            "equity_multiplier": a / e}


def dupont(sym: str, inputs: PiotroskiInputs, d: date | None = None) -> FrameworkResult:
    """The DuPont decomposition and leverage flag of `sym` as knowable on `d` (docstring)."""
    fw = DuPont()
    cur, c, flags, err = leverage(sym, inputs, d)
    if err:
        return fw.missing(sym, None if cur is None else cur.available, err, *flags,
                          components=c)
    t = cur.period
    st = {p: v for p, v in (inputs.statements.get(sym) or {}).items() if p <= t}
    rev = _ttm(st, t, "revenue")
    if not _pos(rev):
        why = (f"no four quarters of revenue to {t}" if rev is None
               else f"revenue TTM {rev:,.0f} <= 0 at {t}")
        return fw.missing(sym, cur.available, f"{why}: no DuPont decomposition", *flags,
                          components=c)
    ni, a, roe = c["ni_ttm"], c["avg_assets"], c["roe"]
    rate, fx_flags = _fx(st, t)
    flags += fx_flags
    c |= {"revenue_ttm": rev, "net_margin": ni / rev, "asset_turnover": rev / a,
          "fx_rate": rate}
    fin = _financial(sym, inputs)
    if fin:
        flags.append(f"{fin}: 3-step only (operating and pretax profit are not an EBIT for a "
                     "lender or insurer)")
    else:
        ebt, ebit = _ttm(st, t, "pretax_profit"), _ttm(st, t, "operating_profit")
        if ebt is None or ebit is None:
            flags.append(f"5-step n/a: no four quarters of pretax or operating profit to {t}")
        elif ebt <= 0 or ebit <= 0:
            flags.append(f"5-step n/a: EBT {ebt:,.0f} or EBIT {ebit:,.0f} <= 0")
        else:
            c |= {"ebt_ttm": ebt, "ebit_ttm": ebit, "tax_burden": ni / ebt,
                  "interest_burden": ebt / ebit, "ebit_margin": ebit / rev}
            if ebt > ebit:
                flags.append("EBT above EBIT: non-operating income (associates, interest "
                             "income) exceeds interest expense, interest burden above 1")
    now, then = _three(inputs.quarters.get(sym) or (), st, t), None
    if now is not None:
        then = _three(inputs.quarters.get(sym) or (), st, shift(t, 4))
    if now is None or then is None:
        flags.append(f"no ROE change attribution: the year to {shift(t, 4)} needs positive NI, "
                     "revenue and both balance sheets (t4, t8)")
    else:
        c["roe_prior"] = then["roe"]
        for k in ("roe", "net_margin", "asset_turnover", "equity_multiplier"):
            c[f"dln_{k}"] = math.log(now[k] / then[k])
    lev = c["leverage_driven"]
    signal = ("unrated" if lev is None else "leverage-driven" if lev else
              "below hurdle" if roe <= c["r"] else "operating")
    return fw.result(sym, cur.available, roe, signal, c, *flags)


@register
class DuPont(Framework):
    """DuPont ROE decomposition (3-step, and 5-step where EBIT and EBT exist) and the
    leverage-driven ROE flag."""

    name = DUPONT
    VERSION = VERSION

    def evaluate(self, sym: str, inputs) -> FrameworkResult:
        inputs = inputs_for(inputs, DUPONT)
        if not isinstance(inputs, PiotroskiInputs):
            return self.missing(sym, None, "no point-in-time IDN statements given")
        if sym not in inputs.quarters:
            return self.missing(sym, None, "no quarterly fundamentals for this name")
        return dupont(sym, inputs)
