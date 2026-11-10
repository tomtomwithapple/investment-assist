"""Entry levels per IDX stock, from each name's own drawdown history (layer 4).

Ported from idx-method's former `entry_levels.py` (git 9a0ea38^). For every name: today's fall
from its 3-year high, and how that compares with the same measure over its own history. Three
numbers set its entry levels:

- **typical correction**: the median depth of its completed corrections, a correction being any
  fall past −15% from the 3-year high that later recovered to within −5% of it.
- **deep zone**: the 10th percentile of its daily drawdown.
- **dip-buy record**: the median 12-month total return (price plus dividends) from days it sat in
  the bottom quarter of its own drawdown range, against the median from all days. A name whose
  dips kept getting deeper (record below zero, or under half of them up) is `avoid`, because for
  it "cheap" has meant "falling".

Differences from idx-method, forced by the data: it read 10 years of Yahoo split-adjusted closes;
here the source is idx-method's `cache/history/` (about 5 years, unadjusted), so closes are
back-adjusted with P19's rule (a 1-day move beyond ±40% is a split or bonus, a zero return) and
the window is all the history there is, needing `MIN_BARS`. Entry prices are in today's price
terms, rounded down to the IDX tick grid. The percentile thresholds are measured on the same
history they are tested on, so the dip-buy record describes the past; it is not an
out-of-sample test, and no level here may change a stance before a placebo control.
"""

from __future__ import annotations

import bisect
import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from assist.candidates.costs import Cost, cost_for, tick_size
from assist.candidates.factors import CORP_ACTION_JUMP
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_stocks import IdxMethodStocks

__all__ = [
    "MIN_BARS",
    "STATUSES",
    "EntryLevels",
    "adjusted_closes",
    "classify",
    "corrections",
    "entry_plan",
    "measure",
    "percentile",
]

STATUSES = ("avoid", "deep", "buy_zone", "wait")
MIN_BARS = 750  # about 3 years of sessions, as idx-method required
HIGH_DAYS = 1096  # rolling 3-year high, calendar days
WARMUP_DAYS = 365  # drawdowns count once the high has a year behind it
START, END = -15.0, -5.0  # a correction opens below START% and completes above END%
DEFAULT_ORDER = 10e6  # IDR, one tranche


@dataclass(frozen=True)
class EntryLevels:
    """Percentages are drawdowns from the 3-year high (negative). Prices are today's terms."""

    symbol: str
    as_of: date
    price: float
    high_3y: float
    dd_now: float
    dd_rank_pct: float
    corrections: int
    typical_correction: float | None
    worst_correction: float | None
    deep_zone: float
    fwd12_all: float | None
    fwd12_after_dip: float | None
    dip_win_rate: float | None
    yield_ttm: float
    entry_typical: float | None
    entry_deep: float
    status: str


def percentile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (numpy's default)."""
    s = sorted(xs)
    k = (len(s) - 1) * q / 100
    lo = math.floor(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _median(xs: Sequence[float]) -> float | None:
    return percentile(xs, 50) if xs else None


def corrections(
    dd: Sequence[float],
    start: float = START,
    end: float = END,
    highs: Sequence[float] | None = None,
) -> tuple[list[float], float | None]:
    """Depths of completed corrections, and the depth so far of one still open.

    With `highs` (the rolling high each `dd` was measured from), a correction's depth and its
    completion are measured against the peak it fell from, not the rolling high: once an old
    peak leaves the 3-year window the rolling high drops and the drawdown shrinks without any
    recovery (P21: BSML's −96% crash from 1805 read as "completed" at 575)."""
    out, open_, depth, peak = [], False, 0.0, 0.0
    for i, x in enumerate(dd):
        if highs is not None:
            px = highs[i] * (1 + x / 100)
            if not open_ and x < start:
                open_, peak = True, highs[i]
                depth = 100 * (px / peak - 1)
            elif open_:
                rel = 100 * (px / peak - 1)
                depth = min(depth, rel)
                if rel > end:
                    out.append(depth)
                    open_ = False
            continue
        if not open_ and x < start:
            open_, depth = True, x
        elif open_:
            depth = min(depth, x)
            if x > end:
                out.append(depth)
                open_ = False
    return out, (depth if open_ else None)


def adjusted_closes(raw: Sequence[float]) -> list[float]:
    """Back-adjust a split or bonus (|1-day move| > CORP_ACTION_JUMP) so it is a zero return;
    the last close is unchanged."""
    n = len(raw)
    adj = [0.0] * n
    f = 1.0
    for i in range(n - 1, -1, -1):
        if i < n - 1 and abs(raw[i + 1] / raw[i] - 1) > CORP_ACTION_JUMP:
            f *= raw[i + 1] / raw[i]
        adj[i] = raw[i] * f
    return adj


def classify(
    dd_now: float,
    typical_correction: float | None,
    deep_zone: float,
    fwd12_after_dip: float | None,
    dip_win_rate: float | None,
) -> str:
    if (fwd12_after_dip is not None and fwd12_after_dip < 0) or (
        dip_win_rate is not None and dip_win_rate < 50
    ):
        return "avoid"
    if dd_now <= deep_zone:
        return "deep"
    if typical_correction is not None and dd_now <= typical_correction:
        return "buy_zone"
    return "wait"


def _year_on(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year + 1, day=28)


def _floor_tick(price: float) -> float:
    t = tick_size(price)
    return float(max(t, math.floor(price / t) * t))


def measure(
    bars: list[dict], dividends: list[dict], as_of: date | None = None, symbol: str = ""
) -> EntryLevels | None:
    """Entry levels at the last bar on or before `as_of`; None with fewer than MIN_BARS closes."""
    rows = [
        (date.fromisoformat(b["date"]), float(b["close"]))
        for b in bars
        if b.get("close") and float(b["close"]) > 0
    ]
    rows.sort()
    if as_of is not None:
        rows = [r for r in rows if r[0] <= as_of]
    if len(rows) < MIN_BARS:
        return None
    dates = [d for d, _ in rows]
    raw = [c for _, c in rows]
    adj = adjusted_closes(raw)
    n = len(rows)

    # rolling 3-year high over (d - HIGH_DAYS, d], monotonic deque
    hi: list[float] = [0.0] * n
    q: deque[int] = deque()
    for i in range(n):
        while q and adj[q[-1]] <= adj[i]:
            q.pop()
        q.append(i)
        while dates[q[0]] <= dates[i] - timedelta(days=HIGH_DAYS):
            q.popleft()
        hi[i] = adj[q[0]]
    dd: list[float | None] = [
        100 * (adj[i] / hi[i] - 1) if (dates[i] - dates[0]).days >= WARMUP_DAYS else None
        for i in range(n)
    ]

    # total-return index: dividends paid in (prev bar, this bar] over the previous raw close
    div_by_day: dict[date, float] = {}
    for dv in dividends:
        if (
            dv.get("ccy", "CURRENCY_IDR") != "CURRENCY_IDR"
            or not dv.get("value")
            or not dv.get("ex")
        ):
            continue
        ex = date.fromisoformat(dv["ex"])
        k = bisect.bisect_left(dates, ex)
        if 0 < k < n:
            div_by_day[dates[k]] = div_by_day.get(dates[k], 0.0) + float(dv["value"])
    tr = [1.0] * n
    for i in range(1, n):
        tr[i] = tr[i - 1] * (adj[i] / adj[i - 1] + div_by_day.get(dates[i], 0.0) / raw[i - 1])

    w = [x for x in dd if x is not None]
    done, _ = corrections(w, highs=[hi[i] for i in range(n) if dd[i] is not None])
    f12: list[tuple[float, float]] = []  # (dd, forward 12m total return %)
    for i in range(n):
        if dd[i] is None:
            continue
        e = bisect.bisect_left(dates, _year_on(dates[i]))
        if e < n:
            f12.append((dd[i], 100 * (tr[e] / tr[i] - 1)))
    p25, p10 = percentile(w, 25), percentile(w, 10)
    after_dip = [r for d_, r in f12 if d_ <= p25]

    last = dates[-1]
    ttm = sum(
        float(dv["value"])
        for dv in dividends
        if dv.get("ccy", "CURRENCY_IDR") == "CURRENCY_IDR"
        and dv.get("value")
        and last - timedelta(days=365) < date.fromisoformat(dv["ex"]) <= last
    )
    dd_now = dd[-1]
    typical = _median(done)
    fwd_dip = _median(after_dip)
    win = 100 * sum(r > 0 for r in after_dip) / len(after_dip) if after_dip else None
    return EntryLevels(
        symbol=symbol,
        as_of=last,
        price=raw[-1],
        high_3y=hi[-1],
        dd_now=dd_now,
        dd_rank_pct=100 * sum(x < dd_now for x in w) / len(w),
        corrections=len(done),
        typical_correction=typical,
        worst_correction=min(done) if done else None,
        deep_zone=p10,
        fwd12_all=_median([r for _, r in f12]),
        fwd12_after_dip=fwd_dip,
        dip_win_rate=win,
        yield_ttm=100 * ttm / raw[-1],
        entry_typical=_floor_tick(hi[-1] * (1 + typical / 100)) if typical is not None else None,
        entry_deep=_floor_tick(hi[-1] * (1 + p10 / 100)),
        status=classify(dd_now, typical, p10, fwd_dip, win),
    )


def entry_plan(
    stocks: IdxMethodStocks | None = None,
    symbols: Iterable[str] | None = None,
    factors: dict[str, dict] | None = None,
    as_of: date | None = None,
    order_idr: float = DEFAULT_ORDER,
) -> tuple[dict[str, dict], list[str]]:
    """sym → {`levels`: EntryLevels | None, `cost`: Cost | None} for every symbol with a history
    file, and stale_inputs. `factors` is P19's enriched table (`load_factors`), loaded when not
    given; the cost is priced at the history's last close on or before `as_of`. An unavailable
    store gives an empty plan and a stale_inputs entry, never a crash."""
    stocks = stocks or IdxMethodStocks.from_config()
    stale: list[str] = []
    try:
        if factors is None:
            from assist.candidates.factors import load_factors

            factors, stale = load_factors(stocks, as_of)
        history = stocks.history(symbols)
        divs = stocks.dividends(history)
    except SourceUnavailable as e:
        return {}, [e.stale_input]
    out: dict[str, dict] = {}
    for sym, bars in sorted(history.items()):
        levels = measure(bars, divs.get(sym, []), as_of, symbol=sym)
        last = [
            float(b["close"])
            for b in bars
            if b.get("close") and (as_of is None or date.fromisoformat(b["date"]) <= as_of)
        ]
        row = {**factors.get(sym, {}), "price": last[-1] if last else None}
        cost: Cost | None = cost_for(row, order_idr)
        out[sym] = {"levels": levels, "cost": cost}
    return out, stale
