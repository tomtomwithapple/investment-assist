"""Dimson beta against the JCI (P117, PLAN S100; frameworks document §4.1). Context only: role
`context`, gate `untested`. **Never used in the hurdle**: the required return stays one per
market by design (`candidates/hurdle.py`), so this beta changes no hurdle, stance, size or rank.
It says how much of a name's move is the market's, beside its other context.

**Returns.** Weekly simple returns over the 3 years (156 weeks) to d: the price on each Friday
is the last bar in the week to that Friday (`factor_series` daily `price`, split-adjusted, from
2016-11; the JCI from `sources.idxmethod.jci`); a week with no bar for the name or the JCI has
no return and is left out (never filled in). Only bars and JCI closes dated on or before d are
read, so the beta is point in time.

**Why weekly, 3 years.** Many IDX names trade thinly: on a day with no trade the store carries
the last price, so daily returns are zeros followed by a catch-up, the non-synchronous trading
that biases a beta toward 0 (Scholes and Williams 1977, Dimson 1979). Weekly returns absorb a
few missing days within the week and the lag and lead terms absorb a catch-up into the next
week; daily data would need several lags and lose more to noise. Weekly over 2 years is the
document's choice; 3 years (~154 regression weeks) has half again as many points, so the
estimate's variance is about two thirds of a 2-year one, while staying inside one IDX cycle
(`factor_series` runs from 2016-11). Monthly over 5 years would give only 60 points.

**Regression.** r_t = α + β₋₁·m_{t−1} + β₀·m_t + β₊₁·m_{t+1} + ε over the weeks where all four
returns exist (one week lost at each end); Dimson beta = β₋₁ + β₀ + β₊₁. The raw beta is the
plain OLS of r_t on m_t over the same weeks. No risk-free rate is subtracted: on weekly data it
moves a beta by less than its standard error. No Blume adjustment.

`components`: raw_beta, dimson_beta, beta_lag, beta_now, beta_lead, r2 (of the Dimson
regression), r2_raw, n (regression weeks), zero_weeks (share of the name's weekly returns that
are exactly 0; above 25% flagged as thin trading). Fewer than 52 regression weeks → n/a.
`signal`: "low" below 0.8, "high" above 1.2, else "market"; `score` = the Dimson beta.

Hashed by `journal.RULE_GLOBS` (`candidates/**/*.py`).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from assist.candidates.frameworks.base import Framework, FrameworkResult, inputs_for, register
from assist.candidates.frameworks.lynch import LynchBetaInputs

__all__ = ["CONFIG", "NAME", "DimsonBeta", "dimson", "dimson_ols", "weekly_closes"]

VERSION = "0.1.0"
NAME = "dimson_beta"
CONFIG = {
    "weeks": 156,  # weekly returns in the window (3 years)
    "min_weeks": 52,  # regression weeks below this → n/a
    "thin_zero_share": 0.25,
    "low_below": 0.8,
    "high_above": 1.2,
}
FRIDAY = 4


def weekly_closes(rows: Sequence[tuple[date, float | None]], ends: Sequence[date]
                  ) -> list[float | None]:
    """The last positive value dated in (end − 7 days, end] for each week end, else None."""
    ds = [r[0] for r in rows]
    out: list[float | None] = []
    for e in ends:
        i = bisect_right(ds, e)
        v = None
        while i > 0 and rows[i - 1][0] > e - timedelta(days=7):
            x = rows[i - 1][1]
            if x is not None and x > 0:
                v = x
                break
            i -= 1
        out.append(v)
    return out


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        p = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[p][col]) < 1e-14:
            return None
        m[col], m[p] = m[p], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col], strict=True)]
    return [m[i][n] / m[i][i] for i in range(n)]


def _ols(y: Sequence[float], xs: Sequence[Sequence[float]]) -> tuple[list[float], float] | None:
    """OLS with an intercept: (coefficients without the intercept, R²); None if singular."""
    cols = [[1.0] * len(y), *xs]
    k = len(cols)
    xtx = [[sum(a * b for a, b in zip(cols[i], cols[j], strict=True)) for j in range(k)]
           for i in range(k)]
    xty = [sum(a * b for a, b in zip(cols[i], y, strict=True)) for i in range(k)]
    beta = _solve(xtx, xty)
    if beta is None:
        return None
    mean = sum(y) / len(y)
    sst = sum((v - mean) ** 2 for v in y)
    if sst <= 0:
        return None
    fit = [sum(beta[i] * cols[i][t] for i in range(k)) for t in range(len(y))]
    ssr = sum((v - f) ** 2 for v, f in zip(y, fit, strict=True))
    return beta[1:], 1 - ssr / sst


def dimson_ols(r: Sequence[float | None], m: Sequence[float | None]) -> dict[str, float] | None:
    """Aligned weekly returns of the name and the market (None where missing) → raw and Dimson
    betas, R² and n over the weeks t with r_t, m_{t−1}, m_t and m_{t+1} all present; None when
    no week qualifies or the regression is singular."""
    rows = [t for t in range(1, len(r) - 1)
            if None not in (r[t], m[t - 1], m[t], m[t + 1])]
    if len(rows) < 5:
        return None
    y = [r[t] for t in rows]
    lag, now, lead = ([m[t + k] for t in rows] for k in (-1, 0, 1))
    d = _ols(y, [lag, now, lead])
    raw = _ols(y, [now])
    if d is None or raw is None:
        return None
    (b_lag, b_now, b_lead), r2 = d
    return {"raw_beta": raw[0][0], "r2_raw": raw[1], "dimson_beta": b_lag + b_now + b_lead,
            "beta_lag": b_lag, "beta_now": b_now, "beta_lead": b_lead, "r2": r2,
            "n": float(len(rows))}


def _returns(px: Sequence[float | None]) -> list[float | None]:
    return [None if a is None or b is None else b / a - 1 for a, b in zip(px, px[1:], strict=False)]


def dimson(sym: str, bars: Sequence, jci: Sequence[tuple[date, float]], d: date, *,
           cfg: Any = CONFIG) -> FrameworkResult:
    """`sym`'s Dimson beta against the JCI over the weeks to `d` (module docstring)."""
    fw = DimsonBeta()
    if not jci:
        return fw.missing(sym, None, "no JCI closes")
    if not bars:
        return fw.missing(sym, None, "no daily bars for this name")
    last_fri = d - timedelta(days=(d.weekday() - FRIDAY) % 7)
    ends = [last_fri - timedelta(weeks=k) for k in range(cfg["weeks"], -1, -1)]
    stock = weekly_closes([(b.date, b.price) for b in bars if b.date <= d], ends)
    mkt = weekly_closes([(x, v) for x, v in jci if x <= d], ends)
    r, m = _returns(stock), _returns(mkt)
    have = [x for x in r if x is not None]
    zero = sum(1 for x in have if x == 0) / len(have) if have else None
    est = dimson_ols(r, m)
    c: dict[str, float | None] = {"weeks": float(cfg["weeks"]), "zero_weeks": zero}
    if est is None or est["n"] < cfg["min_weeks"]:
        n = 0 if est is None else int(est["n"])
        return fw.missing(sym, d, f"only {n} regression weeks in the {cfg['weeks']} to {d} "
                          f"(minimum {cfg['min_weeks']}, or no price movement)",
                          components=c | (est or {}))
    c |= est
    flags = []
    if zero is not None and zero > cfg["thin_zero_share"]:
        flags.append(f"thin trading: {zero:.0%} of weeks with no price change; the lag term "
                     "carries part of the beta")
    b = est["dimson_beta"]
    signal = ("low" if b < cfg["low_below"] else "high" if b > cfg["high_above"]
              else "market")
    return fw.result(sym, d, b, signal, c, *flags)


@register
class DimsonBeta(Framework):
    """Dimson beta: weekly returns against the JCI with one lag and one lead, summed."""

    name = NAME
    VERSION = VERSION

    def evaluate(self, sym: str, inputs) -> FrameworkResult:
        inputs = inputs_for(inputs, NAME)
        if not isinstance(inputs, LynchBetaInputs):
            return self.missing(sym, None, "no bars and JCI given")
        return dimson(sym, inputs.bars.get(sym) or (), inputs.jci, inputs.as_of)
