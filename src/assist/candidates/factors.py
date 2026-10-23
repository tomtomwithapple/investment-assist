"""Liquidity and momentum columns derived from idx-method's `cache/history/` (layer 4 inputs).

idx-method's `enrich.py` used to fold these into `factors.json`; it was removed on 2026-10-14,
so they are derived here with the same definitions as its former `panel.load` and
`panel.signals` (idx-method git 9a0ea38^), so the screens rank on what its backtests measured:

- Bars are aligned on the union calendar of every loaded symbol. `close` is forward-filled so
  returns are computable, but a day with zero volume counts as untraded.
- `close` is not corporate-action adjusted: a 1-day move beyond ±40% (IDX auto-rejection caps
  real moves well below that) is a split or bonus and counts as a zero return.
- At the last bar on or before `as_of` (index i, needs i ≥ 252):
  `days_traded_60` traded days in the last 60 (fewer than 30 → dormant, nothing derived);
  `med_value_60d` median daily value (upper median, zero days included);
  `vol_1y` annualised stdev of the last 252 returns (needs 200);
  `amihud` mean |return| per IDR bn traded over the last 60 traded days;
  `mom_12_1` compounded return from t−252 to t−21; `near_52w_high` close / max close of the
  last 252 bars (unadjusted closes, as before).
"""

from __future__ import annotations

import math
from datetime import date

from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_stocks import IdxMethodStocks

__all__ = ["CORP_ACTION_JUMP", "DERIVED", "align", "derive", "enrich", "load_factors"]

DERIVED = ("vol_1y", "amihud", "med_value_60d", "days_traded_60", "mom_12_1", "near_52w_high")
CORP_ACTION_JUMP = 0.40  # |1-day return| above this is a split/bonus, not a price move
YEAR, MONTH, WINDOW = 252, 21, 60
MIN_TRADED, MIN_RETURNS = 30, 200


def align(
    history: dict[str, list[dict]], min_bars: int = 200
) -> tuple[list[date], dict[str, dict[str, list]]]:
    """→ (dates, data): data[sym] holds `close`, `value`, `traded`, `ret` aligned on `dates`.
    Symbols with fewer than `min_bars` bars are left out."""
    raw = {
        sym: {date.fromisoformat(b["date"]): b for b in bars}
        for sym, bars in history.items()
        if len(bars) >= min_bars
    }
    dates = sorted({d for bars in raw.values() for d in bars})
    idx = {d: i for i, d in enumerate(dates)}
    n = len(dates)
    data = {}
    for sym, bars in raw.items():
        close: list[float | None] = [None] * n
        value = [0.0] * n
        volume = [0.0] * n
        for d, b in bars.items():
            i = idx[d]
            close[i] = float(b["close"]) if b.get("close") else None
            value[i] = float(b.get("value") or 0)
            volume[i] = float(b.get("volume") or 0)
        traded = [v > 0 for v in volume]
        last = None
        for i in range(n):
            if close[i] is None or close[i] <= 0:
                close[i] = last
            else:
                last = close[i]
        ret: list[float | None] = [None] * n
        for i in range(1, n):
            a, b_ = close[i - 1], close[i]
            if a and b_:
                r = b_ / a - 1.0
                ret[i] = 0.0 if abs(r) > CORP_ACTION_JUMP else r
        data[sym] = {"close": close, "value": value, "traded": traded, "ret": ret}
    return dates, data


def _cum(ret: list[float | None], a: int, b: int) -> float | None:
    """Compound returns over (a, b]; None if any gap in coverage."""
    if a < 0:
        return None
    c = 1.0
    for i in range(a + 1, b + 1):
        if ret[i] is None:
            return None
        c *= 1 + ret[i]
    return c - 1


def _signals(d: dict[str, list], i: int) -> dict | None:
    close, value, traded, ret = d["close"], d["value"], d["traded"], d["ret"]
    if i < YEAR or close[i] is None:
        return None
    days_traded = sum(traded[i - WINDOW + 1 : i + 1])
    if days_traded < MIN_TRADED:
        return None
    r = [x for x in ret[i - YEAR + 1 : i + 1] if x is not None]
    if len(r) < MIN_RETURNS:
        return None
    mu = sum(r) / len(r)
    vol_1y = math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(YEAR)
    val60 = sorted(value[i - WINDOW + 1 : i + 1])
    amih = [
        abs(ret[j]) / (value[j] / 1e9)
        for j in range(i - WINDOW + 1, i + 1)
        if ret[j] is not None and value[j] > 0
    ]
    hi52 = max(x for x in close[i - YEAR + 1 : i + 1] if x)
    return {
        "price": close[i],
        "vol_1y": vol_1y,
        "amihud": sum(amih) / len(amih) if amih else None,
        "med_value_60d": val60[len(val60) // 2],
        "days_traded_60": days_traded,
        "mom_12_1": _cum(ret, i - YEAR, i - MONTH),
        "near_52w_high": close[i] / hi52 if hi52 else None,
    }


def derive(
    history: dict[str, list[dict]], as_of: date | None = None, min_bars: int = 200
) -> dict[str, dict]:
    """sym → {`date`, `price`, *DERIVED} at the last calendar bar on or before `as_of` (default:
    the last). Dormant, short or gappy names are left out."""
    dates, data = align(history, min_bars)
    if as_of is not None:
        dates = [d for d in dates if d <= as_of]
    if not dates:
        return {}
    i = len(dates) - 1
    out = {}
    for sym, d in sorted(data.items()):
        s = _signals(d, i)
        if s:
            out[sym] = {"date": dates[i], **s}
    return out


def enrich(factors: dict[str, dict], derived: dict[str, dict]) -> dict[str, dict]:
    """A copy of the screener cross-section with the DERIVED columns replaced. A name with no
    derived row gets None, never the stale value idx-method's last enrich left behind."""
    out = {}
    for sym, row in factors.items():
        d = derived.get(sym, {})
        out[sym] = {**row, **{k: d.get(k) for k in DERIVED}, "bar_date": d.get("date")}
    return out


def load_factors(
    stocks: IdxMethodStocks | None = None, as_of: date | None = None
) -> tuple[dict[str, dict], list[str]]:
    """`factors.json` enriched from `cache/history/` → (table, stale_inputs). An unavailable
    store gives an empty table and a `stale_inputs` entry, never a crash."""
    stocks = stocks or IdxMethodStocks.from_config()
    try:
        factors = stocks.factors()
        history = stocks.history(factors)
    except SourceUnavailable as e:
        return {}, [e.stale_input]
    return enrich(factors, derive(history, as_of)), []
