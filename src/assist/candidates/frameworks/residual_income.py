"""Bank residual income (P113, PLAN S96; frameworks document §1.4, Ohlson / Penman). Context
only: role `context`, gate `untested`. Valuation context beside the Gordon fair price
(`exits.fair_price`); phase Q decision 2's take-profit at the lower of the two waits for a passed
gate and a separate model change, so nothing here changes a stance, size or take-profit.

**Who.** Banks only, as `screens.passes_quality` tells them: the screener reports a CAR
(`piotroski.banks_from`). A non-bank gets an n/a result flagged `not a bank` (FCFF and the
Gordon form serve it), so every row carries the same framework list.

**Inputs on date d** (point in time, `LAG_DAYS` 120 through `Fundamentals.available`):

- t = the newest `factor_series` quarter knowable by d; B = its `equity`, NI = its `ni_ttm`.
- Shares = `mktcap / price` of the last bar on or before d (the split-adjusted basis the bars
  and the store's dividends share), so B0 = B / shares = price / P/B, and price ÷ fair is
  mktcap ÷ total value, whatever splits came between t and d.
- ROE0 = NI TTM / average equity (t and the quarter a year before). With no equity a year
  before, the ending equity stands in, flagged.
- Payout = trailing 12-month dividends by ex-date × shares / NI, held for every forecast year,
  capped at 1 (flagged). A bank with NI <= 0 has no payout ratio: it is taken as 0 (it retains
  everything while it recovers), flagged.
- r = the IDN hurdle (`hurdle.hurdle("IDN", ...).required`, the same r the Gordon fair price
  uses, before the sector tilt shift), in pt.

**Path.** Year t = 1..N: ROE_t = ROE0 + (r − ROE0) × t / N, a straight line that reaches r at
year N; NI_t = ROE_t × B_{t−1}; B_t = B_{t−1} + NI_t × (1 − payout) (clean surplus);
RI_t = (ROE_t − r) × B_{t−1}; V0 = B0 + Σ RI_t / (1 + r)^t.

**Terminal value: none.** Residual income is 0 from year N on (ROE has faded to r): competition
and regulation (OJK capital rules, deposit competition) are assumed to remove a bank's excess
return within N years, the frameworks document's fade form with ω = 0 after year N.

**N = 10** (`CONFIG["years"]`). Abnormal ROE mean-reverts at roughly 0.6–0.8 persistence a year
in US data (Nissim and Penman 2001), so most of it is gone within 5–10 years; IDX's large banks
have earned ROE above an IDN cost of equity for over a decade on their deposit franchises, so 5
years would value them near book. Ten years of linear fade and no terminal value is the
conservative middle: it credits N/2 years of today's excess return, undiscounted.

**Missing inputs** (§0.3, never imputed): no quarter knowable, no or non-positive equity, no NI,
no bar with price and mktcap, or no hurdle → n/a with a flag. Negative earnings are valued (the
path recovers to r; V0 < B0) and flagged.

`score` = price ÷ RI fair value; `signal` "cheap" below 1, "rich" at or above. Every
intermediate is in `components` (per year: roe_yK, b_yK, ri_yK, pv_ri_yK).

**Replay** (`BankRI.replay`, measured on S94's board): at each quarter end, today's banks with a
bar in the last 10 days, price >= the screens' floor and mktcap >= IDR 1T are ranked by price ÷
RI fair, cheapest first; the board holds the top quintile. r is today's IDN hurdle on every
date, as GARP's replay. The pool is 29–44 banks a quarter (36 on average, 2017-06 → 2026-09),
so the top quintile is about 7 names; the gate's placebo verdict (top vs bottom quintile
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
from assist.candidates.frameworks.piotroski import PiotroskiInputs, shift

__all__ = ["CONFIG", "NAME", "BankRI", "BankRIInputs", "attach_context", "bank_ri", "path",
           "replay_panel"]

VERSION = "0.1.0"
NAME = "bank_ri"
CONFIG = {
    "years": 10,  # N: ROE fades linearly to r over this many years (see the docstring)
    "max_bar_age_days": 10,  # replay: a bank with no bar this close to the quarter end is out
    "replay_min_mktcap": 1e12,  # IDR, the dividend replay's liquidity stand-in
    "min_pool": 10,  # banks a quarter needs before the board scores it (top quintile >= 2)
}


@dataclass(frozen=True)
class BankRIInputs(PiotroskiInputs):
    """`PiotroskiInputs` (so the F-score reads the same object) plus the bars and split-adjusted
    dividends per symbol (`dividend_value.DividendData`) and the IDN hurdle in pt."""

    bars: Mapping[str, Sequence] = field(default_factory=dict)
    dividends: Mapping[str, Sequence[Mapping]] = field(default_factory=dict)
    required_pt: float | None = None
    years: int = CONFIG["years"]


def path(b0: float, roe0: float, payout: float, r: float, years: int) -> dict[str, float]:
    """The fade table and value per share (ratios as fractions). Pure."""
    c: dict[str, float] = {}
    b, pv_sum = b0, 0.0
    for t in range(1, years + 1):
        roe = roe0 + (r - roe0) * t / years
        ri = (roe - r) * b
        pv = ri / (1 + r) ** t
        b_next = b + roe * b * (1 - payout)
        c |= {f"roe_y{t}": roe, f"ri_y{t}": ri, f"pv_ri_y{t}": pv, f"b_y{t}": b_next}
        pv_sum += pv
        b = b_next
    v0 = b0 + pv_sum
    return c | {"sum_pv_ri": pv_sum, "fair_value": v0, "justified_pb": v0 / b0}


def _bar_at(bars: Sequence, d: date) -> Any:
    i = bisect_right([b.date for b in bars], d)
    while i > 0:
        b = bars[i - 1]
        if b.price and b.mktcap and b.price > 0 and b.mktcap > 0:
            return b
        i -= 1
    return None


def _trailing(divs: Sequence[Mapping], d: date) -> float:
    lo = d - timedelta(days=365)
    return sum(r["value"] for r in divs if r.get("value") is not None
               and r.get("ccy") in (None, "CURRENCY_IDR")
               and lo < date.fromisoformat(r["ex"]) <= d)


def bank_ri(sym: str, quarters: Sequence, bars: Sequence, divs: Sequence[Mapping], d: date,
            required_pt: float | None, *, years: int = CONFIG["years"]) -> FrameworkResult:
    """The residual-income value of bank `sym` as knowable on `d` (module docstring)."""
    fw = BankRI()
    known = [q for q in quarters if q.available <= d]
    if not known:
        return fw.missing(sym, None, f"no quarterly fundamentals available by {d}")
    cur = max(known, key=lambda q: q.period)
    if required_pt is None:
        return fw.missing(sym, cur.available, "no IDN hurdle: no cost of equity r")
    if cur.equity is None:
        return fw.missing(sym, cur.available, f"no book equity at {cur.period}")
    if cur.equity <= 0:
        return fw.missing(sym, cur.available, f"book equity {cur.equity:,.0f} <= 0 at "
                          f"{cur.period}: residual income needs a positive book")
    if cur.ni_ttm is None:
        return fw.missing(sym, cur.available, f"no NI TTM at {cur.period}")
    bar = _bar_at(bars, d)
    if bar is None:
        return fw.missing(sym, cur.available, f"no bar with a price and mktcap by {d}")
    flags: list[str] = []
    prior = next((q for q in known if q.period == shift(cur.period, 4)), None)
    if prior is not None and prior.equity is not None and prior.equity > 0:
        avg = (cur.equity + prior.equity) / 2
    else:
        avg = cur.equity
        flags.append(f"no equity a year before {cur.period}: ROE on ending equity")
    roe0 = cur.ni_ttm / avg
    shares = bar.mktcap / bar.price
    dps = _trailing(divs, d)
    if cur.ni_ttm <= 0:
        payout = 0.0
        flags.append(f"negative earnings (NI TTM {cur.ni_ttm:,.0f}): payout taken as 0, ROE "
                     "assumed to recover linearly to r")
    else:
        payout = dps * shares / cur.ni_ttm
        if payout > 1:
            flags.append(f"payout {payout:.0%} of NI TTM capped at 100%")
            payout = 1.0
    r = required_pt / 100
    b0 = cur.equity / shares
    c: dict[str, float | None] = {
        "equity": cur.equity, "equity_prior": prior.equity if prior else None,
        "avg_equity": avg, "ni_ttm": cur.ni_ttm, "shares": shares, "price": bar.price,
        "mktcap": bar.mktcap, "b0": b0, "pb": bar.price / b0, "roe0": roe0, "dps_ttm": dps,
        "payout": payout, "r": r, "years": float(years)}
    c |= path(b0, roe0, payout, r, years)
    fair = c["fair_value"]
    if fair <= 0:
        return fw.missing(sym, cur.available, f"RI fair value {fair:,.2f} <= 0", *flags,
                          components=c)
    ptf = bar.price / fair
    c["price_to_fair"] = ptf
    return fw.result(sym, cur.available, ptf, "cheap" if ptf < 1 else "rich", c, *flags)


def replay_panel(bars: Mapping[str, Sequence], quarters: Mapping[str, Sequence],
                 dividends: Mapping[str, Sequence[Mapping]], banks: Sequence[str],
                 required_pt: float, qends: Sequence[date], *, cfg: Mapping = CONFIG
                 ) -> list[tuple[date, list[dict]]]:
    """→ [(quarter end, [{symbol, cheap, price_to_fair, fwd}])]: the banks valued on that date
    (`cheap` = −price ÷ fair, higher is cheaper) with the price-plus-dividend return to the
    next quarter end (None on the last). A bank with an n/a result is left out."""
    from assist.candidates.screens import GATES

    out = []
    for i, q in enumerate(qends):
        q1 = qends[i + 1] if i + 1 < len(qends) else None
        recs = []
        for sym in sorted(banks):
            bs = bars.get(sym) or []
            bar = _bar_at(bs, q)
            if (bar is None or bar.date < q - timedelta(days=cfg["max_bar_age_days"])
                    or bar.mktcap < cfg["replay_min_mktcap"] or bar.price < GATES["min_price"]):
                continue
            divs = dividends.get(sym) or []
            res = bank_ri(sym, quarters.get(sym) or (), bs, divs, q, required_pt,
                          years=cfg["years"])
            if res.score is None:
                continue
            fwd = None
            end = _bar_at(bs, q1) if q1 else None
            if end is not None and end.date > bar.date:
                paid = sum(r["value"] for r in divs if r.get("value") is not None
                           and bar.date < date.fromisoformat(r["ex"]) <= end.date)
                fwd = (end.price + paid) / bar.price - 1
            recs.append({"symbol": sym, "cheap": -res.score, "price_to_fair": res.score,
                         "fwd": fwd})
        out.append((q, recs))
    return out


def attach_context(judged: dict[str, dict], inputs: BankRIInputs) -> None:
    """S86's holding record: each bank's (`judged[sym]["bank"]`) RI result as
    `judged[sym]["context"]["bank_ri"]`, which `holdings.build` carries as the record's
    context. Non-banks are left alone."""
    fw = BankRI()
    for sym, j in judged.items():
        if j.get("bank"):
            j.setdefault("context", {})[NAME] = fw.evaluate(sym, inputs).to_dict()


@register
class BankRI(Framework):
    """Bank residual income: B0 plus ROE faded to the IDN hurdle over N years, no terminal."""

    name = NAME
    VERSION = VERSION

    def evaluate(self, sym: str, inputs) -> FrameworkResult:
        if not isinstance(inputs, BankRIInputs):
            return self.missing(sym, None, "no point-in-time bank inputs given")
        if sym not in inputs.banks:
            return self.missing(sym, None, "not a bank (no CAR): residual income is for banks")
        return bank_ri(sym, inputs.quarters.get(sym) or (), inputs.bars.get(sym) or (),
                       inputs.dividends.get(sym) or (), inputs.as_of, inputs.required_pt,
                       years=inputs.years)

    def replay(self, ctx: Any) -> Any:
        """S94: the board's replay over the loaded stores (`framework_board.LiveContext`)."""
        from assist import framework_board as fb
        from assist.candidates import dividend_value as dv
        from assist.sources.idxmethod_series import quarter_ends

        data = ctx.dividend_data
        banks = sorted(s for s, r in ctx.table.items() if r.get("car"))
        h, basis = fb._hurdle_pt(ctx)
        firsts = [data.bars[s][0].date for s in banks if data.bars.get(s)]
        qes = quarter_ends(min(firsts), ctx.bar_date) if firsts else []
        panel = replay_panel(data.bars, data.quarters, data.dividends, banks, h, qes)
        scored = [(q, [x for x in recs if x["fwd"] is not None]) for q, recs in panel]
        verdict = dv.evaluate_replay([(q, [{"symbol": x["symbol"], "expected_pt": x["cheap"],
                                            "fwd": x["fwd"]} for x in recs])
                                      for q, recs in scored], min_pool=CONFIG["min_pool"])
        sizes = [len(r) for _, r in panel if r]
        return fb.from_ranked(
            NAME, "Bank residual income: price below B0 plus ROE faded to the IDN hurdle over "
            f"{CONFIG['years']} years.", "top quintile of banks by price ÷ RI fair (cheapest "
            "first), banks over IDR 1T", fb.ranked_by(panel, "cheap"), CONFIG["min_pool"],
            verdict, kind="framework",
            notes=[f"replay on {basis}; banks are today's (screener CAR), {len(banks)} of them",
                   f"pool {min(sizes, default=0)}–{max(sizes, default=0)} banks a quarter: the "
                   "top quintile is a handful of names, so even 3m windows are thin",
                   "gate is the placebo on top vs bottom quintile next-quarter return; context "
                   "only, never a take-profit yet"])
