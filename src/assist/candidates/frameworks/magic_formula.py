"""Greenblatt's Magic Formula (P115, PLAN S98; frameworks document §1.5). Context only: role
`context`, gate `untested`. The plan's "inside the quality floor" waits for a passed gate, the
user's adoption (S103) and a separate model change; `screens.passes_quality` is untouched, so
nothing here changes a stance, a size or a floor (phase Q decision 3: once adopted it may block
buys only, never sell a held name).

**Legs on date d** (point in time: the newest `factor_series` quarter knowable by d, period end
+ `LAG_DAYS` 120 through `Fundamentals.available`; mktcap from the last bar on or before d):

- Earnings yield EY = EBIT / EV, EBIT = `op_income_ttm`, EV = mktcap + `net_debt` (the
  `ev_ebit` that `idxmethod_series.multiples` derives, inverted, so a negative EBIT keeps its
  sign). Not Stockbit's daily `ev_ebit` item: it steps on the filing date, earlier than
  `LAG_DAYS`, and folds both parts into one ratio.
- Return on capital ROC = the quarter's `roce` (Stockbit's ROCE, EBIT TTM ÷ capital employed,
  total assets − current liabilities: ASII 2024Q4 42.4T / (471.4T − 130.5T) = 12.4% against its
  12.59%), not Greenblatt's EBIT ÷ (net working capital + net fixed assets): the store has no
  `ppe_net` (asked of idx-method in S101), so his denominator cannot be built.

**Universe.** Names passing `screens.passes_gates` (free float, liquidity, price floor,
volatility, trading days, flagged boards), not financial, with both legs. Financials are out
and flagged: banks (the screener reports a CAR), sector Keuangan in `factor_universe`, and,
for a name with no sector there (the delisted ones), a company name that says bank, finance,
insurance, securities or leasing. Utilities are not excluded: IDX-IC has no utilities sector
(Infrastruktur mixes them with telcos and toll roads).

**Ranks.** EY and ROC are each ranked best first (1 = highest, ties take the mean rank) across
the universe; combined = rank EY + rank ROC, ordered ascending, ties by the better EY rank
then symbol. `score` = 100 × (n − position) / (n − 1), the combined-rank percentile (100 best);
`signal` "top" for the top fifth (position <= n // 5, the replay's basket), "bottom" for the
bottom fifth, else "middle". A name outside the universe (a failed gate) is ranked against it,
flagged, and does not change anyone else's rank.

**Missing inputs** (§0.3, never imputed): no quarter knowable, no bar within 10 days, no EBIT,
no net debt, EV <= 0 (the document drops a denominator <= 0) or no roce → n/a with a flag. EBIT
<= 0 is ranked (its yield is negative) and flagged.

**Replay** (`MagicFormula.replay`, S94's board): at each calendar quarter end every
`factor_series` name, delisted ones included, is ranked as above; the board holds the top fifth.
The gate row is built point in time: price and vol_1y (`factors` definitions, corporate-action
jumps as zero) from `factor_series` bars; `med_value_60d` and `days_traded_60` from
`cache/history` where the name has 60 bars to the date (2021-11 on), else the dividend
replay's stand-in, mktcap >= IDR 1T; free float and special boards are today-only, so they are
not tested in the replay. Financials by today's CAR, the sector or the name. The placebo verdict
(top vs bottom quintile next-quarter return, `dividend_value.evaluate_replay`) is the gate, and
is reported, not used.

Hashed by `journal.RULE_GLOBS` (`candidates/**/*.py`).
"""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from assist.candidates.frameworks.base import Framework, FrameworkResult, inputs_for, register
from assist.candidates.frameworks.residual_income import BankRIInputs

__all__ = ["CONFIG", "NAME", "MagicFormula", "MagicInputs", "cross_section", "financial",
           "history_liquidity", "legs", "rank_cross_section", "replay_panel"]

VERSION = "0.1.0"
NAME = "magic_formula"
CONFIG = {
    "max_bar_age_days": 10,  # no bar this close to the date: not trading, n/a
    "echo_gap_days": 14,  # a last bar this long after the one before is the store's echo
    "replay_min_mktcap": 1e12,  # IDR, the replay's liquidity stand-in before cache/history
    "liquidity_window": 60,  # bars, as `factors` (med_value_60d, days_traded_60)
    "vol_bars": 252,
    "vol_min_returns": 200,
    "corp_action_jump": 0.40,
    "min_pool": 30,  # names a quarter needs before the board scores it (top fifth >= 6)
    "quantiles": 5,
}
FINANCIAL_SECTOR = "Keuangan"
_FINANCIAL_NAME = re.compile(
    r"\bbank\b|financ|finans|asuransi|insurance|sekuritas|securities|leasing", re.IGNORECASE)


@dataclass(frozen=True)
class MagicInputs(BankRIInputs):
    """`BankRIInputs` (so the F-score and bank RI read the same object) plus today's gate rows
    per symbol (the screener table with the derived liquidity columns), the flagged boards and
    `factor_universe` (name, sector, delisted)."""

    rows: Mapping[str, Mapping] = field(default_factory=dict)
    flagged: frozenset[str] = frozenset()
    universe: Mapping[str, Mapping] = field(default_factory=dict)
    cache: dict = field(default_factory=dict, compare=False, repr=False)


def financial(sym: str, banks: Iterable[str], universe: Mapping[str, Mapping]) -> str | None:
    """Why `sym` is a financial (and out), or None."""
    if sym in set(banks):
        return "bank (the screener reports a CAR): EBIT and capital employed are not " \
               "meaningful for a bank, see bank_ri"
    u = universe.get(sym) or {}
    if u.get("sector") == FINANCIAL_SECTOR:
        return f"financial (sector {FINANCIAL_SECTOR}): EBIT and capital employed are not " \
               "meaningful"
    if not u.get("sector") and _FINANCIAL_NAME.search(u.get("name") or ""):
        return f"financial by name ({u.get('name')}; no sector in factor_universe)"
    return None


def _quote(bars: Sequence, d: date, dates: Sequence[date] | None = None,
           cfg: Mapping = CONFIG) -> Any:
    """The last bar on or before `d` with a price and a mktcap, skipping the store's echo (a
    series' final bar more than `echo_gap_days` after the one before)."""
    dates = dates if dates is not None else [b.date for b in bars]
    i = bisect_right(dates, d)
    while i > 0:
        b = bars[i - 1]
        echo = (i == len(bars) and i >= 2
                and (b.date - bars[i - 2].date).days > cfg["echo_gap_days"])
        if not echo and b.price and b.mktcap and b.price > 0 and b.mktcap > 0:
            return b
        i -= 1
    return None


def legs(quarters: Sequence, bars: Sequence, d: date, *, dates: Sequence[date] | None = None,
         cfg: Mapping = CONFIG) -> tuple[dict[str, float], list[str], date | None, str | None]:
    """→ (components, flags, as_of, why n/a): EY and ROC of one name as knowable on `d`."""
    known = [q for q in quarters if q.available <= d]
    if not known:
        return {}, [], None, f"no quarterly fundamentals available by {d}"
    cur = max(known, key=lambda q: q.period)
    seen = cur.available
    bar = _quote(bars, d, dates, cfg)
    if bar is None or bar.date < d - timedelta(days=cfg["max_bar_age_days"]):
        return {}, [], seen, f"no bar with a price and mktcap within " \
                             f"{cfg['max_bar_age_days']} days of {d}"
    if cur.op_income_ttm is None:
        return {}, [], seen, f"no EBIT (op_income_ttm) at {cur.period}"
    if cur.net_debt is None:
        return {}, [], seen, f"no net debt at {cur.period}: no EV"
    ev = bar.mktcap + cur.net_debt
    c = {"ebit": cur.op_income_ttm, "mktcap": bar.mktcap, "net_debt": cur.net_debt, "ev": ev,
         "price": bar.price}
    if ev <= 0:
        return c, [], seen, f"EV {ev:,.0f} <= 0 (net cash above the mktcap): no earnings yield"
    if cur.roce is None:
        return c, [], seen, f"no roce at {cur.period}"
    c |= {"earnings_yield": cur.op_income_ttm / ev, "roce": cur.roce, "roc": cur.roce / 100}
    flags = []
    if cur.op_income_ttm <= 0:
        flags.append(f"EBIT {cur.op_income_ttm:,.0f} <= 0 at {cur.period}: ranked on its "
                     "negative yield")
    return c, flags, seen, None


def _midranks(vals: Mapping[str, float]) -> dict[str, float]:
    order = sorted(vals, key=lambda s: -vals[s])
    out: dict[str, float] = {}
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for s in order[i:j + 1]:
            out[s] = (i + j) / 2 + 1
        i = j + 1
    return out


def rank_cross_section(xs: Mapping[str, tuple[float, float]], quantiles: int = 5
                       ) -> dict[str, dict[str, Any]]:
    """{sym: (EY, ROC)} → {sym: rank_ey, rank_roc, combined_rank, position, pct, n_universe,
    signal}. Pure."""
    rey = _midranks({s: v[0] for s, v in xs.items()})
    rroc = _midranks({s: v[1] for s, v in xs.items()})
    order = sorted(xs, key=lambda s: (rey[s] + rroc[s], rey[s], s))
    n = len(order)
    cut = n // quantiles
    out = {}
    for pos, s in enumerate(order, 1):
        signal = "top" if pos <= cut else "bottom" if pos > n - cut else "middle"
        out[s] = {"rank_ey": rey[s], "rank_roc": rroc[s], "combined_rank": rey[s] + rroc[s],
                  "position": pos, "pct": 100.0 * (n - pos) / (n - 1) if n > 1 else 100.0,
                  "n_universe": n, "signal": signal}
    return out


def _gate(sym: str, inputs: MagicInputs) -> str | None:
    from assist.candidates.screens import passes_gates

    row = inputs.rows.get(sym)
    if row is None:
        return "not in today's screener rows"
    ok, why = passes_gates(sym, row, inputs.flagged)
    return None if ok else why


def cross_section(inputs: MagicInputs) -> dict[str, tuple[dict, list[str], date | None]]:
    """The eligible universe on `inputs.as_of`: {sym: (components, flags, as_of)}, cached."""
    if "xs" not in inputs.cache:
        xs = {}
        for sym in sorted(inputs.rows):
            if financial(sym, inputs.banks, inputs.universe) or _gate(sym, inputs):
                continue
            c, flags, seen, why = legs(inputs.quarters.get(sym) or (),
                                       inputs.bars.get(sym) or (), inputs.as_of)
            if why is None:
                xs[sym] = (c, flags, seen)
        inputs.cache["xs"] = xs
        inputs.cache["ranks"] = rank_cross_section(
            {s: (v[0]["earnings_yield"], v[0]["roc"]) for s, v in xs.items()})
    return inputs.cache["xs"]


def _vol_1y(bars: Sequence, d: date, dates: Sequence[date], cfg: Mapping) -> float | None:
    """vol_1y on `d` from the bars' prices (`factors` definition), None when too short."""
    i = bisect_right(dates, d)
    px = [b.price for b in bars[max(0, i - cfg["vol_bars"] - 1):i] if b.price]
    rets = []
    for a, b in zip(px, px[1:], strict=False):
        r = b / a - 1
        rets.append(0.0 if abs(r) > cfg["corp_action_jump"] else r)
    if len(rets) < cfg["vol_min_returns"]:
        return None
    mu = sum(rets) / len(rets)
    return math.sqrt(sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)) * math.sqrt(252)


def history_liquidity(history: Mapping[str, Sequence[Mapping]], qends: Iterable[date],
                      window: int = CONFIG["liquidity_window"]
                      ) -> dict[str, dict[date, tuple[float, int]]]:
    """{sym: {quarter end: (med_value_60d, days_traded_60)}} from `cache/history`, as `factors`
    defines them, where the name has `window` bars to that date. Pure."""
    from assist.candidates.factors import align

    dates, data = align(dict(history), window)
    firsts = {s: min(date.fromisoformat(b["date"]) for b in bs)
              for s, bs in history.items() if bs and s in data}
    out: dict[str, dict[date, tuple[float, int]]] = {}
    for q in qends:
        i = bisect_right(dates, q) - 1
        if i < window - 1 or dates[i] < q - timedelta(days=CONFIG["max_bar_age_days"]):
            continue
        lo = i - window + 1
        for sym, d in data.items():
            if firsts[sym] > dates[lo]:
                continue
            vals = sorted(d["value"][lo:i + 1])
            out.setdefault(sym, {})[q] = (vals[len(vals) // 2], sum(d["traded"][lo:i + 1]))
    return out


def replay_panel(bars: Mapping[str, Sequence], quarters: Mapping[str, Sequence],
                 dividends: Mapping[str, Sequence[Mapping]], universe: Mapping[str, Mapping],
                 qends: Sequence[date], *, banks: Iterable[str] = (),
                 liquidity: Mapping[str, Mapping[date, tuple[float, int]]] | None = None,
                 min_mktcap: float = CONFIG["replay_min_mktcap"], cfg: Mapping = CONFIG
                 ) -> list[tuple[date, list[dict]]]:
    """→ [(quarter end, [{symbol, position, pct, earnings_yield, roc, liquidity, fwd}] best
    first)]: every name passing the point-in-time gates on that date, delisted ones included,
    with its price-plus-dividend return to the next quarter end (held at its last bar if it
    stopped trading; None on the last quarter end)."""
    from assist.candidates.screens import GATES, passes_gates

    banks = set(banks)
    liquidity = liquidity or {}
    syms = sorted(s for s in bars if not financial(s, banks, universe))
    dates = {s: [b.date for b in bars[s]] for s in syms}
    out = []
    for k, q in enumerate(qends):
        q1 = qends[k + 1] if k + 1 < len(qends) else None
        xs: dict[str, dict] = {}
        for sym in syms:
            bs = bars[sym]
            c, _, _, why = legs(quarters.get(sym) or (), bs, q, dates=dates[sym], cfg=cfg)
            if why is not None:
                continue
            liq = (liquidity.get(sym) or {}).get(q)
            if liq is not None:
                med, traded, src = liq[0], liq[1], "history"
            else:
                med = GATES["min_med_value_60d"] if c["mktcap"] >= min_mktcap else 0.0
                traded, src = None, "mktcap"
            row = {"free_float": GATES["min_free_float"], "price": c["price"],
                   "med_value_60d": med, "days_traded_60": traded,
                   "vol_1y": _vol_1y(bs, q, dates[sym], cfg)}
            if not passes_gates(sym, row, ())[0]:
                continue
            fwd = None
            start = _quote(bs, q, dates[sym], cfg)
            end = _quote(bs, q1, dates[sym], cfg) if q1 else None
            if end is not None and end.date > start.date:
                paid = sum(r["value"] for r in dividends.get(sym) or ()
                           if r.get("value") is not None
                           and start.date < date.fromisoformat(r["ex"]) <= end.date)
                fwd = (end.price + paid) / start.price - 1
            xs[sym] = {"symbol": sym, "earnings_yield": c["earnings_yield"], "roc": c["roc"],
                       "liquidity": src, "fwd": fwd}
        ranks = rank_cross_section({s: (x["earnings_yield"], x["roc"]) for s, x in xs.items()},
                                   cfg["quantiles"])
        recs = [xs[s] | {"position": r["position"], "pct": r["pct"]}
                for s, r in sorted(ranks.items(), key=lambda kv: kv[1]["position"])]
        out.append((q, recs))
    return out


@register
class MagicFormula(Framework):
    """Greenblatt's Magic Formula: EBIT/EV and return on capital ranks, financials out."""

    name = NAME
    VERSION = VERSION

    def evaluate(self, sym: str, inputs) -> FrameworkResult:
        inputs = inputs_for(inputs, NAME)
        if not isinstance(inputs, MagicInputs):
            return self.missing(sym, None, "no point-in-time Magic Formula inputs given")
        why = financial(sym, inputs.banks, inputs.universe)
        if why:
            return self.missing(sym, None, why)
        c, flags, seen, na = legs(inputs.quarters.get(sym) or (), inputs.bars.get(sym) or (),
                                  inputs.as_of)
        if na:
            return self.missing(sym, seen, na, *flags, components=c)
        xs = cross_section(inputs)
        if sym in xs:
            r = inputs.cache["ranks"][sym]
        else:
            gate = _gate(sym, inputs)
            flags.append(f"not in the eligible universe ({gate}): ranked against it")
            pairs = {s: (v[0]["earnings_yield"], v[0]["roc"]) for s, v in xs.items()}
            r = rank_cross_section(pairs | {sym: (c["earnings_yield"], c["roc"])})[sym]
            r = r | {"n_universe": len(xs)}
        c |= {k: float(v) for k, v in r.items() if k != "signal"}
        return self.result(sym, seen, r["pct"], r["signal"], c, *flags)

    def replay(self, ctx: Any) -> Any:
        """S94: the board's replay over the loaded stores (`framework_board.LiveContext`)."""
        from assist import framework_board as fb
        from assist.candidates import dividend_value as dv
        from assist.sources.base import SourceUnavailable
        from assist.sources.idxmethod_series import quarter_ends

        data = ctx.dividend_data
        universe = ctx.universe
        banks = sorted(s for s, r in ctx.table.items() if r.get("car"))
        firsts = [b[0].date for b in data.bars.values() if b]
        qes = quarter_ends(min(firsts), ctx.bar_date) if firsts else []
        try:
            history = ctx.stocks.history()
        except SourceUnavailable as e:
            ctx.stale.append(e.stale_input)
            history = {}
        liq = history_liquidity(history, qes)
        panel = replay_panel(data.bars, data.quarters, data.dividends, universe, qes,
                             banks=banks, liquidity=liq)
        verdict = dv.evaluate_replay([(q, [{"symbol": x["symbol"], "expected_pt":
                                            -x["position"], "fwd": x["fwd"]}
                                           for x in recs if x["fwd"] is not None])
                                      for q, recs in panel], min_pool=CONFIG["min_pool"])
        ranked = [(q, [x["symbol"] for x in recs]) for q, recs in panel]
        return fb.from_ranked(
            NAME, "Greenblatt's Magic Formula: earnings yield (EBIT/EV) rank plus return on "
            "capital (roce) rank, financials out.", "top fifth by combined rank (EY + ROC), "
            "point-in-time gated names, delisted included", ranked, CONFIG["min_pool"],
            verdict, kind="framework", notes=_notes(panel, data, universe, banks))


def _notes(panel: Sequence[tuple[date, list[dict]]], data: Any,
           universe: Mapping[str, Mapping], banks: Sequence[str]) -> list[str]:
    delisted = {s for s, u in universe.items() if u.get("delisted")}
    with_bars = delisted & {s for s, b in data.bars.items() if b}
    with_items = {s for s in with_bars if any(
        q.op_income_ttm is not None and q.net_debt is not None and q.roce is not None
        for q in data.quarters.get(s) or ())}
    fin = {s for s in with_bars if financial(s, banks, universe)}
    pooled = delisted & {x["symbol"] for _, recs in panel for x in recs}
    nq = [x["liquidity"] for _, recs in panel for x in recs]
    hist = sum(1 for x in nq if x == "history")
    sizes = [len(r) for _, r in panel if r]
    return [
        f"delisted coverage: {len(with_bars)} of {len(delisted)} delisted names in "
        f"factor_universe have factor_series bars, {len(with_items)} of them have EBIT, net "
        f"debt and roce, {len(fin)} are financials (out), {len(pooled)} ever enter the pool",
        f"liquidity: {hist} of {len(nq)} pool name-quarters from cache/history "
        "(med_value_60d), the rest on the mktcap >= IDR 1T stand-in; free float and special "
        "boards are today-only, not tested in the replay",
        f"pool {min(sizes, default=0)}–{max(sizes, default=0)} names a quarter; ROC is "
        "Stockbit's roce (EBIT ÷ total assets − current liabilities), not EBIT ÷ (NWC + net "
        "fixed assets): no ppe_net in the store",
        "gate is the placebo on top vs bottom quintile next-quarter return; context only, "
        "not inside the quality floor until adopted (S103)"]
