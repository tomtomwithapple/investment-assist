"""Layer 0, global regime: risk-on, neutral or risk-off? Dollar up or down? (PLAN S3)

A deliberately small hand-set rule on five FRED inputs from sec-edgar, each read point in time
(`fred_as_of`, so a backtest never sees a later vintage):

- `vix`: VIXCLS level. Risk-off point at ≥ 25, two at ≥ 35; risk-on point at ≤ 15.
- `hy_oas_d13w`: BAMLH0A0HYM2 change over 13 weeks, pt. Off ≥ +0.75, on ≤ −0.50. FRED keeps
  ICE data only from 2023-10-10, so before 2024-01 this input is absent (and named stale).
- `usd_d13w`: DTWEXBGS (broad dollar) change over 13 weeks, %. Off ≥ +3, on ≤ −3.
- `real_yield`: DFII10 level, %. Off ≥ 2.5, on ≤ 0.5.
- `nfci`: NFCI level. Off > 0 (tighter than average), on ≤ −0.5.

`net = off points − on points`: risk_off at net ≥ 2, risk_on at net ≤ −2, else neutral. The
dollar is `up` / `down` when DTWEXBGS moved more than ±2% over 13 weeks, else `flat`. A missing
input scores nothing and is named in `stale_inputs`; an unavailable store gives a neutral, flat
regime with the store named.

`CANDIDATES` (net liquidity Δ13w, EM corporate OAS Δ13w, term premium Δ13w, STLFSI4) are
computed but count only when listed in `ADOPTED`, which they join only after beating the P9
placebo walk-forward (`check`); see docs/results/P8-regime.md. None has so far.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from assist.eval.placebo import Verdict, align, evaluate
from assist.layers.types import Regime
from assist.sources.base import Row, SourceUnavailable
from assist.sources.usfin import NET_LIQUIDITY, NET_LIQUIDITY_INPUTS, FredSource, net_liquidity

__all__ = [
    "ADOPTED",
    "CANDIDATES",
    "CORE",
    "READ_BACK",
    "Inputs",
    "check",
    "classify",
    "entry_returns",
    "history",
    "inputs",
    "read_inputs",
    "regime",
    "weekly",
]

SOURCE = "sec-edgar"
CORE = ("VIXCLS", "BAMLH0A0HYM2", "DTWEXBGS", "DFII10", "NFCI")
EM_OAS, TERM_PREMIUM, STLFSI = "BAMLEMCBPIOAS", "THREEFYTP10", "STLFSI4"
CANDIDATE_SERIES = (EM_OAS, TERM_PREMIUM, STLFSI, *NET_LIQUIDITY_INPUTS)
WINDOW = timedelta(weeks=13)
READ_BACK = timedelta(days=140)  # 13 weeks plus slack for holidays and weekly series
STATE_AT = 2  # |net points| needed to leave neutral
DOLLAR_BAND = 2.0  # % over 13 weeks
MAX_ENTRY_GAP = timedelta(days=14)  # signal → first tradable price (Lebaran closes IDX ~10 days)

# feature: (series, kind, risk-off test, risk-on test, driver format)
# kind "level" = last value, "diff" = change over 13 weeks, "pct" = % change over 13 weeks.
RULES = {
    "vix": ("VIXCLS", "level", lambda v: 2 if v >= 35 else 1 if v >= 25 else 0,
            lambda v: v <= 15, "VIX {:.1f}"),
    "hy_oas_d13w": ("BAMLH0A0HYM2", "diff", lambda v: v >= 0.75, lambda v: v <= -0.5,
                    "HY OAS {:+.2f}pt/13w"),
    "usd_d13w": ("DTWEXBGS", "pct", lambda v: v >= 3.0, lambda v: v <= -3.0,
                 "broad dollar {:+.1f}%/13w"),
    "real_yield": ("DFII10", "level", lambda v: v >= 2.5, lambda v: v <= 0.5,
                   "10Y real yield {:.2f}%"),
    "nfci": ("NFCI", "level", lambda v: v > 0, lambda v: v <= -0.5, "NFCI {:.2f}"),
}
CANDIDATES = {
    "net_liquidity": (NET_LIQUIDITY, "pct", lambda v: v <= -3.0, lambda v: v >= 3.0,
                      "net liquidity {:+.1f}%/13w"),
    "em_oas": (EM_OAS, "diff", lambda v: v >= 0.5, lambda v: v <= -0.4,
               "EM corp OAS {:+.2f}pt/13w"),
    "term_premium": (TERM_PREMIUM, "diff", lambda v: v >= 0.4, lambda v: v <= -0.4,
                     "term premium {:+.2f}pt/13w"),
    "stlfsi": (STLFSI, "level", lambda v: v > 0, lambda v: v <= -0.5, "STLFSI4 {:.2f}"),
}
ADOPTED: tuple[str, ...] = ()
FEATURE = {"diff": "{}_d13w", "pct": "{}_d13w", "level": "{}"}
# Days after which the newest point is stale (weekly series are published with a lag).
MAX_AGE = defaultdict(lambda: timedelta(days=7),
                      {"NFCI": timedelta(days=14), STLFSI: timedelta(days=14),
                       NET_LIQUIDITY: timedelta(days=14), "DTWEXBGS": timedelta(days=10)})


def _feature_name(name: str, kind: str, candidate: bool) -> str:
    return FEATURE[kind].format(name) if candidate else name


ALL_FEATURES = {
    **RULES,
    **{_feature_name(k, v[1], True): v for k, v in CANDIDATES.items()},
}
CANDIDATE_FEATURE = {k: _feature_name(k, v[1], True) for k, v in CANDIDATES.items()}


@dataclass(frozen=True)
class Inputs:
    """Every feature known on `as_of` (None when absent), the newest date behind each, what is
    missing or stale, and the stores read."""

    as_of: date
    values: dict[str, float | None]
    last: dict[str, date] = field(default_factory=dict)
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


def _at(series: list[Row], when: date) -> Row | None:
    """The last point on or before `when` (series sorted by date)."""
    i = bisect_right([r.date for r in series], when)
    return series[i - 1] if i else None


def inputs(rows: Iterable[Row], as_of: date, sources: Sequence[str] = (SOURCE,)) -> Inputs:
    """Features from FRED rows already read point in time; points after `as_of` are ignored."""
    rows = list(rows)
    rows += net_liquidity(r for r in rows if r.series_id in NET_LIQUIDITY_INPUTS)
    by_id: dict[str, list[Row]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: (r.series_id, r.date)):
        if r.value is not None and r.date <= as_of:
            by_id[r.series_id].append(r)

    values: dict[str, float | None] = {}
    last: dict[str, date] = {}
    stale: list[str] = []
    for feat, (sid, kind, *_rest) in ALL_FEATURES.items():
        core = feat in RULES
        series = by_id.get(sid, [])
        values[feat] = None
        if not series:
            if core:
                stale.append(f"{SOURCE} {sid} (no data)")
            continue
        end = series[-1]
        last[feat] = end.date
        if core and as_of - end.date > MAX_AGE[sid]:
            stale.append(f"{SOURCE} {sid} (last {end.date})")
        if kind == "level":
            values[feat] = end.value
            continue
        base = _at(series, end.date - WINDOW)
        if base is None or end.date - base.date > WINDOW + timedelta(days=14):
            if core:
                stale.append(f"{SOURCE} {sid} (history from {series[0].date})")
            continue
        values[feat] = (end.value - base.value if kind == "diff"
                        else 100 * (end.value / base.value - 1))
    return Inputs(as_of, values, last, tuple(stale), tuple(sources))


def classify(inp: Inputs, extra: Sequence[str] = ADOPTED) -> Regime:
    """The hand-set rule (module docstring) on `inp`, plus any `extra` candidates."""
    rules = [(f, RULES[f]) for f in RULES] + [(CANDIDATE_FEATURE[c], CANDIDATES[c]) for c in extra]
    off = on = 0
    drivers = []
    for feat, (_sid, _kind, is_off, is_on, fmt) in rules:
        v = inp.values.get(feat)
        if v is None:
            continue
        pts = int(is_off(v))
        if pts:
            off += pts
            drivers.append(fmt.format(v) + " (risk-off)")
        elif is_on(v):
            on += 1
            drivers.append(fmt.format(v) + " (risk-on)")
    net = off - on
    state = "risk_off" if net >= STATE_AT else "risk_on" if net <= -STATE_AT else "neutral"
    usd = inp.values.get("usd_d13w")
    dollar = ("flat" if usd is None or abs(usd) <= DOLLAR_BAND else "up" if usd > 0 else "down")
    return Regime(inp.as_of, state, dollar, tuple(drivers), inp.stale_inputs, inp.sources)


def read_inputs(as_of: date, source=None) -> Inputs:
    """Read every core and candidate series as known on `as_of` (sec-edgar `fred_as_of`)."""
    try:
        src = source or FredSource()
        rows = src.rows([*CORE, *CANDIDATE_SERIES], start=as_of - READ_BACK, end=as_of,
                        as_of=as_of)
    except SourceUnavailable as e:
        return Inputs(as_of, dict.fromkeys(ALL_FEATURES), stale_inputs=(e.stale_input,))
    return inputs(rows, as_of, sources=(getattr(src, "name", SOURCE),))


def regime(as_of: date, source=None, extra: Sequence[str] = ADOPTED) -> Regime:
    """Layer 0 on `as_of`, point in time. Never raises for a missing or locked store."""
    return classify(read_inputs(as_of, source), extra)


def history(dates: Iterable[date], source=None) -> dict[date, Inputs]:
    """`read_inputs` on each date, each as known that day (for the walk-forward check)."""
    src = source or FredSource()
    return {d: read_inputs(d, src) for d in dates}


def weekly(start: date, end: date) -> list[date]:
    """Every Friday from `start` to `end`: FRED's week closes then, IDX trades next on Monday."""
    d = start + timedelta(days=(4 - start.weekday()) % 7)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(weeks=1)
    return out


def entry_returns(signal_dates: Iterable[date], prices: Iterable[tuple[date, float]],
                  horizon: int, invert: bool = False) -> dict[date, float]:
    """Return from the first price strictly after each signal date to `horizon` observations
    later (FRED as of 23:59 New York is after the Jakarta close). `invert` turns USD/IDR into
    the IDR's own return. Dates without a price within `MAX_ENTRY_GAP` or without a full horizon
    are dropped (a signal before the series starts must not borrow its first price)."""
    pts = sorted(p for p in prices if p[1] is not None)
    days = [d for d, _ in pts]
    out = {}
    for d in signal_dates:
        i = bisect_right(days, d)
        if i + horizon < len(pts) and days[i] - d <= MAX_ENTRY_GAP:
            a, b = pts[i][1], pts[i + horizon][1]
            out[d] = a / b - 1 if invert else b / a - 1
    return out


def check(risk_off: Mapping[date, bool], prices: Iterable[tuple[date, float]], *,
          horizon: int = 20, invert: bool = False, stride: int = 4, block: int = 4,
          n_shuffles: int = 1000, n_controls: int = 20) -> Verdict:
    """Does `risk_off` precede weaker returns? The P9 harness on weekly signals: the rule is
    hand-set (no fitting), so the procedure passes the signal through unchanged, and `stride` /
    `block` (in signal dates) keep overlapping horizons from inflating t."""
    rets = entry_returns(risk_off, prices, horizon, invert)
    _dates, feats, returns = align(risk_off, rets)
    return evaluate(lambda f, _r: list(f), feats, returns, direction=-1, stride=stride,
                    block=block, n_shuffles=n_shuffles, n_controls=n_controls)
