"""Graham's Defensive Investor screen and the Graham Number (P114, PLAN S97; frameworks document
§1.1). Context only: role `context`, gate `untested`; it changes no stance, size or floor. If its
gate ever passes and the user adopts it, it may only block buys, never sell a held name (phase Q
decision 3). Net-net is not built (decision 8).

On date d the newest quarter t is the newest `fundamentals` quarter knowable by d (period end +
`LAG_DAYS` 120). A "year" is four discrete quarters trailing from t (year 0 = the four to t,
year k ends k years earlier), so a fiscal year that is not the calendar year is still whole;
a year with a missing quarter is unknown, never filled in. A quarter's earnings are `eps` ×
`shares` (`is.shares`, else `shares_bs`), in IDR: idx-method stores `net_income_parent`,
current assets and current liabilities of its 48 USD reporters (ADRO, ITMG, KKGI and others) in
USD, while EPS, equity, total debt and working capital are in IDR (checked 2026-11-12). A
quarter without EPS (about 900 quarters of 230 names) reads net income × the nearest known
quarter's EPS × shares / net income (about 1 for an IDR reporter, the FX rate for a USD one),
at most `convert_days` away and flagged; with no such quarter it stays unknown.

Criteria (each pass / fail / n/a) — adapted to IDX:

1. Size: market cap on d >= `size_floor_idr` IDR 5T, `diversify.SIZE_LINES["mid"]`: Graham
   keeps out small companies; 5T is where this repo's mid caps start (about the top 150 of
   ~950 listed names), so the screen reads "mid or large cap". Nominal, not inflation-indexed.
2. Current ratio >= 2: current assets / current liabilities at t.
3. Debt: total debt <= net current assets (`working_capital`, IDR, else CA − CL) at t. The
   store has no long-term debt item, so `total_debt` (short-term borrowings included) stands
   in: stricter than Graham's, flagged.
4. Earnings stability: positive earnings in each of the last 10 years. A known loss year fails
   even when older years are unknown; all known positive but fewer than 10 known is n/a.
5. Dividend record: a dividend gone ex (value > 0, ex <= d) in each of the last 17 calendar
   years before d's year. The document says 20; the store's dividends start in 2009, so 17
   (2009–2025 on 2026 dates) is all it can show, flagged. Before 2026 the window is clipped to
   the store's first year, flagged. Years before the name's first statement are unknown: an
   unpaid year after it fails, a full record that starts too late is n/a.
6. Earnings growth >= 1/3: the 3-year average EPS of years 0–2 against years 10–12 (midpoints
   10 years apart, as Graham's 1950s-to-1960s test). EPS is split-adjusted: a share count that
   is a whole multiple (x2 or more, or 1/x, within 1%) of the quarter before is a split and
   earlier EPS is restated to t's basis, flagged; a rights issue stays as dilution. A base
   average <= 0 fails (no positive base to grow from).
7. P/E <= 15 on 3-year average earnings: market cap / mean earnings of years 0–2 (price over the
   average EPS at today's share count; share-free, so no split can distort it). Average
   earnings <= 0 fail.
8. P/B <= 1.5, or P/E (criterion 7's) × P/B <= 22.5. P/B = market cap / `common_equity` (equity
   to the parent, else `equity`) at t.

Banks and other financials (a CAR on the screener, or `factor_universe` sector Keuangan) skip
2 and 3, flagged: a financial's balance sheet has no current ratio or working capital (§0.3).

`score` = criteria met / criteria computable. `signal` is "pass" only when every computable
criterion passes and at least `min_computable` (6, a financial's full set) are computable,
"fail" when any computable one fails (flagged when fewer than 6 were computable: a known
failure still fails), else n/a with score None and the count kept as `met_partial`.

Graham Number = sqrt(22.5 × EPS × BVPS) with TTM EPS (year 0 / shares at t) and BVPS (equity /
shares at t), only when both are positive; `price_to_graham` = sqrt(P/E TTM × P/B / 22.5), the
same ratio from market cap (price / Graham Number at t's share count), and `margin_of_safety`
= 1 − that.

Market cap is the last `factor_series` daily bar on or before d, at most `price_window_days`
(14) old, else size, P/E and P/B are n/a.

`replay(ctx)`: at each calendar quarter end the names passing the screen are held; where fewer
than `min_picks` (10, Graham's lower bound for a defensive portfolio) pass, the cheapest of the
other pool names by price ÷ Graham Number fill up to 10, and the board notes say on how many
dates. The pool is every name judged that date at or over the size floor (criterion 1): what a
defensive investor picks from. All judged names would let a few micro-cap multi-baggers set
the comparator (the equal-weighted pool of ~350 names gained ~410% over 5y on 2026-11-12).

Hashed by `journal.RULE_GLOBS` (`candidates/**/*.py`).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import fmean
from typing import Any

from assist.candidates.diversify import SIZE_LINES
from assist.candidates.frameworks.base import NA, Framework, FrameworkResult, inputs_for, register
from assist.candidates.frameworks.piotroski import banks_from, shift
from assist.candidates.screens import LAG_DAYS

__all__ = ["CONFIG", "CRITERIA", "FINANCIAL_SECTORS", "STATEMENT_ITEMS", "Graham",
           "GrahamInputs", "defensive", "financials_from", "first_dividend_year", "picks_on"]

VERSION = "0.1.0"
NAME = "graham"
CRITERIA = ("c1_size", "c2_current", "c3_debt", "c4_stability", "c5_dividends", "c6_growth",
            "c7_pe", "c8_pb")
CONFIG = {
    "size_floor_idr": SIZE_LINES["mid"],
    "current_ratio_min": 2.0,
    "stability_years": 10,
    "dividend_years": 17,  # the document's 20; the store reaches 17 (2009-2025)
    "growth_gap_years": 10,  # midpoints of the two 3-year averages
    "avg_years": 3,
    "growth_min": 1 / 3,
    "pe_max": 15.0,
    "pb_max": 1.5,
    "pe_x_pb_max": 22.5,
    "min_computable": 6,
    "price_window_days": 14,
    "split_tolerance": 0.01,
    "max_split": 20,  # IDX splits run 1:2 to 1:10; a larger jump is a pre-listing count
    "convert_days": 400,  # a quarter without EPS converts at a ratio at most ~a year away
    "min_picks": 10,
}
STATEMENT_ITEMS = ("eps", "net_income_parent", "shares", "shares_bs", "common_equity", "equity",
                   "current_assets", "current_liabilities", "working_capital", "total_debt")
FINANCIAL_SECTORS = ("Keuangan",)
_EPS = 1e-9
LAG = timedelta(days=LAG_DAYS)


@dataclass(frozen=True)
class GrahamInputs:
    """What the screen reads on `as_of`: `fundamentals` statements per symbol {period end: {item:
    value}} (`IdxMethodSeries.statements(STATEMENT_ITEMS)`), `factor_series` daily bars per
    symbol, dividends per symbol ({ex, value}; None when the source is unavailable, a symbol
    absent from a given mapping paid none), the financials, and the dividend store's first
    year."""

    as_of: date
    statements: Mapping[str, Mapping[date, Mapping[str, float]]] = field(default_factory=dict)
    bars: Mapping[str, Sequence] = field(default_factory=dict)
    dividends: Mapping[str, Sequence[Mapping]] | None = field(default_factory=dict)
    financials: frozenset[str] = frozenset()
    div_first_year: int | None = None


def financials_from(factors: Mapping[str, Mapping], sectors: Mapping[str, str]
                    ) -> frozenset[str]:
    """Banks (a CAR on the screener) and every name of a financial `factor_universe` sector."""
    return banks_from(factors) | {s for s, sec in sectors.items() if sec in FINANCIAL_SECTORS}


def first_dividend_year(dividends: Mapping[str, Iterable[Mapping]] | None) -> int | None:
    """The first calendar year of the dividend store (2009 today)."""
    years = [int(r["ex"][:4]) for recs in (dividends or {}).values() for r in recs
             if r.get("ex")]
    return min(years) if years else None


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b <= 0:
        return None
    return a / b


def _bit(ok: bool) -> float:
    return 1.0 if ok else 0.0


def _shares(row: Mapping[str, float] | None) -> float | None:
    row = row or {}
    v = row.get("shares_bs") or row.get("shares")
    return v if v is not None and v > 0 else None


def _whole(ratio: float, tol: float) -> int | None:
    k = round(ratio)
    return k if k >= 2 and abs(ratio - k) <= tol * k else None


def _split_basis(st: Mapping[date, Mapping[str, float]], known: Sequence[date], tol: float,
                 max_split: float, flags: list[str]) -> dict[date, float]:
    """Per quarter, the factor that puts its share count on t's basis (splits only). A jump
    above `max_split` is no split: the quarters before it get no basis (unknown EPS)."""
    have = [(p, _shares(st.get(p))) for p in known]
    have = [(p, s) for p, s in have if s is not None]
    out: dict[date, float] = {}
    cum = 1.0
    for i in range(len(have) - 1, -1, -1):
        p, s = have[i]
        out[p] = cum
        if i == 0:
            break
        prev_p, prev_s = have[i - 1]
        r = s / prev_s
        if max(r, 1 / r) > max_split:
            flags.append(f"share count x{r:.3g} between {prev_p} and {p} (pre-listing or a"
                         " restatement, not a split): EPS before it on an unknown basis")
            break
        if (k := _whole(r, tol)) is not None:
            cum *= k
            flags.append(f"split x{k} between {prev_p} and {p}: earlier EPS restated")
        elif r < 1 and (k := _whole(1 / r, tol)) is not None:
            cum /= k
            flags.append(f"reverse split 1/{k} between {prev_p} and {p}: earlier EPS restated")
    return out


def _mktcap(bars: Sequence, d: date, window: int) -> tuple[float | None, float | None]:
    i = bisect_right(bars, d, key=lambda b: b.date)
    for b in reversed(bars[max(0, i - 40):i]):
        if b.mktcap is not None:
            if (d - b.date).days > window:
                return None, None
            return b.mktcap, b.price
    return None, None


def defensive(sym: str, statements: Mapping[date, Mapping[str, float]] | None,
              bars: Sequence | None, dividends: Sequence[Mapping] | None, d: date, *,
              financial: bool = False, div_first_year: int | None = None,
              cfg: Mapping[str, Any] = CONFIG) -> FrameworkResult:
    """The defensive screen of `sym` as knowable on `d` (see the module docstring).
    `dividends` None means no dividend source; an empty sequence means none paid."""
    fw = Graham()
    st = statements or {}
    known = sorted(p for p in st if p + LAG <= d)
    if not known:
        return fw.missing(sym, None, f"no quarterly statements available by {d}")
    t, first = known[-1], known[0]
    as_of = t + LAG
    stk = {p: st[p] for p in known}
    now = stk[t]
    c: dict[str, float | None] = dict.fromkeys(CRITERIA)
    flags: list[str] = []

    def quarters(k: int) -> list[date]:
        return [shift(t, 4 * k + j) for j in range(4)]

    def shares_of(p: date) -> float | None:
        row = stk.get(p) or {}
        sh = row.get("shares") or row.get("shares_bs")
        return sh if sh and sh > 0 else None

    # eps × shares / net income per quarter: ~1 for an IDR reporter, the FX rate for a USD one
    ratios = {p: stk[p]["eps"] * shares_of(p) / stk[p]["net_income_parent"] for p in known
              if stk[p].get("eps") is not None and shares_of(p)
              and stk[p].get("net_income_parent")}
    converted: set[date] = set()

    def eps_of(p: date) -> float | None:
        row = stk.get(p) or {}
        if row.get("eps") is not None:
            return row["eps"]
        ni, sh = row.get("net_income_parent"), shares_of(p)
        near = [q for q in ratios if abs((q - p).days) <= cfg["convert_days"]]
        if ni is None or sh is None or not near:
            return None
        converted.add(p)
        return ni * ratios[min(near, key=lambda q: (abs((q - p).days), q))] / sh

    def earnings(p: date) -> float | None:
        eps, sh = eps_of(p), shares_of(p)
        return None if eps is None or sh is None else eps * sh

    def year_ni(k: int) -> float | None:
        vals = [earnings(p) for p in quarters(k)]
        return None if any(v is None for v in vals) else sum(vals)

    basis = _split_basis(stk, known, cfg["split_tolerance"], cfg["max_split"], flags)

    def year_eps(k: int) -> float | None:
        ps = quarters(k)
        vals = [eps_of(p) if p in basis else None for p in ps]
        if any(v is None for v in vals):
            return None
        return sum(v / basis[p] for v, p in zip(vals, ps, strict=True))

    mktcap, price = _mktcap(bars or (), d, cfg["price_window_days"])
    c |= {"mktcap": mktcap, "price": price}
    if mktcap is None:
        flags.append(f"no market cap within {cfg['price_window_days']} days of {d}: size, P/E"
                     " and P/B not computable")

    # 1. size
    if mktcap is not None:
        c["c1_size"] = _bit(mktcap >= cfg["size_floor_idr"])

    # 2-3. current ratio and debt (not for financials)
    if financial:
        flags.append("financial: c2 current ratio and c3 debt test not meaningful for a bank or"
                     " other financial, not counted")
    else:
        ca, cl, debt = (now.get(k) for k in ("current_assets", "current_liabilities",
                                             "total_debt"))
        cr = _div(ca, cl)
        c["current_ratio"] = cr
        if cr is None:
            flags.append(f"c2: no current assets or liabilities at {t}")
        else:
            c["c2_current"] = _bit(cr >= cfg["current_ratio_min"])
        nca = now.get("working_capital")
        if nca is None and ca is not None and cl is not None:
            nca = ca - cl
        c |= {"net_current_assets": nca, "total_debt": debt}
        if nca is None or debt is None:
            flags.append(f"c3: no total debt or net current assets at {t}")
        else:
            c["c3_debt"] = _bit(debt <= nca)
            flags.append("c3: total debt stands in for long-term debt (no long-term debt item),"
                         " stricter than Graham's")

    # 4. earnings stability
    n_st = cfg["stability_years"]
    years = [year_ni(k) for k in range(n_st)]
    seen = [v for v in years if v is not None]
    c["positive_years"] = float(sum(v > 0 for v in seen))
    if any(v <= 0 for v in seen):
        c["c4_stability"] = 0.0
    elif len(seen) == n_st:
        c["c4_stability"] = 1.0
    else:
        flags.append(f"c4: only {len(seen)} of {n_st} years of earnings known by {d}")

    # 5. dividend record
    end_y = d.year - 1
    start_y = end_y - cfg["dividend_years"] + 1
    if dividends is None:
        flags.append("c5: no dividend source")
    else:
        if div_first_year is not None and start_y < div_first_year:
            start_y = div_first_year
            flags.append(f"c5: dividend record over {end_y - start_y + 1} years: the store "
                         f"starts {div_first_year}")
        else:
            flags.append(f"c5: dividend record over {cfg['dividend_years']} years, not the "
                         "document's 20 (the store's dividends start 2009)")
        paid = {int(r["ex"][:4]) for r in dividends
                if r.get("ex") and r["ex"] <= d.isoformat() and (r.get("value") or 0) > 0}
        window = range(start_y, end_y + 1)
        c |= {"dividend_years": float(sum(y in paid for y in window)),
              "dividend_years_required": float(len(window))}
        lo = max(start_y, first.year)
        if any(y not in paid for y in range(lo, end_y + 1)):
            c["c5_dividends"] = 0.0
        elif first.year > start_y:
            flags.append(f"c5: statements start {first}, the record before is unknown")
        else:
            c["c5_dividends"] = 1.0

    # 6. earnings growth
    a, gap = cfg["avg_years"], cfg["growth_gap_years"]
    end_eps = [year_eps(k) for k in range(a)]
    start_eps = [year_eps(k) for k in range(gap, gap + a)]
    if any(v is None for v in end_eps + start_eps):
        flags.append(f"c6: EPS of years 0-{a - 1} or {gap}-{gap + a - 1} not known by {d}")
    else:
        e0, e1 = fmean(start_eps), fmean(end_eps)
        c |= {"eps_avg_start": e0, "eps_avg_end": e1}
        if e0 <= 0:
            c["c6_growth"] = 0.0
            flags.append("c6: start average EPS not positive, no base to grow from")
        else:
            g = e1 / e0 - 1
            c["eps_growth"] = g
            c["c6_growth"] = _bit(g >= cfg["growth_min"] - _EPS)

    # 7. P/E on 3-year average earnings
    ni3 = [year_ni(k) for k in range(a)]
    pe3 = None
    pe3_negative = False
    if mktcap is not None:
        if any(v is None for v in ni3):
            flags.append(f"c7: earnings of years 0-{a - 1} not known by {d}")
        elif fmean(ni3) <= 0:
            pe3_negative = True
            c["c7_pe"] = 0.0
            flags.append("c7: 3-year average earnings not positive")
        else:
            pe3 = mktcap / fmean(ni3)
            c["c7_pe"] = _bit(pe3 <= cfg["pe_max"] + _EPS)
    c["pe3"] = pe3

    # 8. P/B, or P/E x P/B
    equity = now.get("common_equity")
    if equity is None:
        equity = now.get("equity")
    pb = None
    if mktcap is not None:
        if equity is None:
            flags.append(f"c8: no equity at {t}")
        elif equity <= 0:
            c["c8_pb"] = 0.0
            flags.append(f"c8: equity not positive at {t}")
        else:
            pb = mktcap / equity
            if pb <= cfg["pb_max"] + _EPS:
                c["c8_pb"] = 1.0
            elif pe3 is not None:
                c["c8_pb"] = _bit(pe3 * pb <= cfg["pe_x_pb_max"] + _EPS)
            elif pe3_negative:
                c["c8_pb"] = 0.0
            else:
                flags.append("c8: P/B above 1.5 and P/E unknown")
    c |= {"pb": pb, "pe_x_pb": None if pe3 is None or pb is None else pe3 * pb}

    # Graham Number
    sh_t = _shares(now)
    ni_ttm = year_ni(0)
    eps_ttm = _div(ni_ttm, sh_t) if ni_ttm is not None else None
    bvps = _div(equity, sh_t) if equity is not None else None
    c |= {"eps_ttm": eps_ttm, "bvps": bvps, "graham_number": None, "price_to_graham": None,
          "margin_of_safety": None}
    if eps_ttm is not None and bvps is not None and eps_ttm > 0 and bvps > 0:
        c["graham_number"] = math.sqrt(22.5 * eps_ttm * bvps)
        if mktcap is not None:
            ptg = math.sqrt((mktcap / ni_ttm) * (mktcap / equity) / 22.5)
            c |= {"price_to_graham": ptg, "margin_of_safety": 1 - ptg}
    else:
        flags.append("graham number: needs positive TTM EPS and book value per share")

    if converted:
        flags.append(f"earnings: {len(converted)} quarter(s) without EPS read as net income × "
                     "the nearest quarter's EPS × shares / net income (currency)")
    done = [c[k] for k in CRITERIA if c[k] is not None]
    n, met = len(done), sum(done)
    c |= {"computable": float(n)}
    few = f"only {n} of {len(CRITERIA)} criteria computable (minimum {cfg['min_computable']})"
    if n < cfg["min_computable"] and met == n:
        c["met_partial"] = float(met)
        return fw.missing(sym, as_of, few, *flags, components=c)
    c["met"] = float(met)
    if n < cfg["min_computable"]:
        flags.insert(0, few + ": a known failure still fails")
    return fw.result(sym, as_of, met / n, "pass" if met == n else "fail", c, *flags)


def _run(inputs: GrahamInputs, sym: str, d: date) -> FrameworkResult:
    divs = None if inputs.dividends is None else inputs.dividends.get(sym, ())
    return defensive(sym, inputs.statements.get(sym), inputs.bars.get(sym), divs, d,
                     financial=sym in inputs.financials, div_first_year=inputs.div_first_year)


def picks_on(inputs: GrahamInputs, d: date, *, min_picks: int = CONFIG["min_picks"]
             ) -> tuple[list[str], list[str], int]:
    """→ (held, pool, filled) on `d`: the names passing the screen (by symbol), then, when
    fewer than `min_picks` pass, the cheapest of the other pool names by price ÷ Graham Number
    up to `min_picks` (`filled` of them). The pool is every judged name over the size floor
    (criterion 1 passed): what a defensive investor chooses from."""
    res = {s: _run(inputs, s, d) for s in sorted(inputs.statements)}
    pool = [s for s, r in res.items() if r.signal != NA and r.components["c1_size"] == 1.0]
    passed = [s for s in pool if res[s].signal == "pass"]
    fill: list[str] = []
    if len(passed) < min_picks:
        rest = sorted((res[s].components["price_to_graham"], s) for s in pool
                      if res[s].signal != "pass"
                      and res[s].components.get("price_to_graham") is not None)
        fill = [s for _, s in rest[:min_picks - len(passed)]]
    return passed + fill, pool, len(fill)


@register
class Graham(Framework):
    """Graham's Defensive Investor screen (IDX-adapted) and the Graham Number."""

    name = NAME
    VERSION = VERSION

    def evaluate(self, sym: str, inputs) -> FrameworkResult:
        inputs = inputs_for(inputs, NAME)
        if not isinstance(inputs, GrahamInputs):
            return self.missing(sym, None, "no point-in-time IDN statements given")
        if sym not in inputs.statements:
            return self.missing(sym, None, "no statements for this name")
        return _run(inputs, sym, inputs.as_of)

    def replay(self, ctx) -> Any:
        """The S94 board's replay: the screen at every calendar quarter end the bars cover."""
        from assist.framework_board import Replay
        from assist.sources.idxmethod_series import IdxMethodSeries, quarter_ends

        data = ctx.dividend_data
        st = IdxMethodSeries(ctx.stocks.root).statements(STATEMENT_ITEMS)
        firsts = [b[0].date for b in data.bars.values() if b]
        if not firsts or not st:
            raise ValueError("no factor_series bars or fundamentals statements")
        inp = GrahamInputs(ctx.bar_date, st, data.bars, data.dividends,
                           financials_from(ctx.table, data.sectors),
                           first_dividend_year(data.dividends))
        k = CONFIG["min_picks"]
        picks: dict[date, list[str]] = {}
        pools: dict[date, list[str]] = {}
        filled = passed_only = 0
        passing: list[int] = []
        for q in quarter_ends(min(firsts), ctx.bar_date):
            held, pool, n_fill = picks_on(inp, q, min_picks=k)
            if len(pool) < k:
                continue
            picks[q], pools[q] = held, pool
            filled += n_fill > 0
            passed_only += n_fill == 0
            passing.append(len(held) - n_fill)
        spread = (f"{min(passing)}-{max(passing)}, mean {fmean(passing):.1f}" if passing
                  else "none")
        return Replay(
            NAME, "framework", "Graham's Defensive Investor screen, IDX-adapted: size, current"
            " ratio, debt, 10-year earnings, 17-year dividends, growth, P/E and P/B.",
            f"names passing every computable criterion (6+ of 8); where fewer than {k} pass, "
            f"filled to {k} with the cheapest pool names by price / Graham Number",
            picks, pools, self.gate, None, "quarterly",
            (f"{passed_only} of {len(picks)} quarter ends held passing names only; {filled} "
             f"were filled with the cheapest by price / Graham Number (names passing per "
             f"date: {spread})",
             "pool: every judged name at or over the IDR 5T size floor that date",
             "fundamentals hold no delisted name: survivorship-biased",
             f"dividend record clipped to the store start ({inp.div_first_year}) before 2026",
             "financials are today's (screener CAR) plus factor_universe sector Keuangan"))
