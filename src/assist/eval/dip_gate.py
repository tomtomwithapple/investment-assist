"""Placebo for gate 3 of the average-down rule (PLAN S69, P88): is an add made while a name sits
in `buy_zone` or `deep` better than an add on a random day for the same name?

`candidates/entry.py` measures its levels on the same history it describes, so its status may
not gate anything before this control. Here the levels are point in time and unchanged:

- **Dates.** Month ends (the last session of each calendar month across all names). At each one,
  `entry.measure` runs on the name's bars on or before it, so the 3-year high, the typical
  correction, the deep zone and the dip-buy record all come from the past. A name sits out with
  fewer than `MIN_BARS` bars, or when its last bar is more than `BAR_WINDOW_DAYS` old.
- **Add.** At the close of the name's first session after the month end (within the same
  window). Its return is the total return (price plus dividends, splits a zero return, as
  `entry.measure`) to the first session `horizon` months later. No full forward return, no add.
- **Real.** Per month, the mean forward return of the adds whose status is in `ZONES`; a month
  needs at least `MIN_NAMES` of them.
- **Placebo.** The same names, each added on a random day instead: any session with `MIN_BARS`
  bars before it and a full forward return. `n_sets` seeded draws; a month's placebo is their
  mean.
- **Verdict.** Phase K's gate numbers: only non-overlapping windows count (month ends `horizon`
  months apart), `MIN_N` 10 per side, Welch t at least 2.0, placebo p at most 0.05, the control
  rerun, and the seed. Each window gives `placebo.evaluate` two observations, (True, real) and
  (False, placebo), as `tiers_replay` does; it passes only if that verdict passes **and** the
  real mean beats the mean of at least `1 − alpha` of the random-day sets (`perm_p`).

A pass makes gate 3 binding. `insufficient` or `failed` leaves the entry status as context. The
all-month figures and the per-status table overlap in time and decide nothing.
"""

from __future__ import annotations

import bisect
import calendar
import json
import random
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from statistics import fmean, stdev
from typing import Any

from assist.candidates.entry import MIN_BARS, STATUSES, adjusted_closes, measure
from assist.eval.placebo import ALPHA, MIN_N, SEED, T_MIN, evaluate
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_stocks import IdxMethodStocks

__all__ = ["BAR_WINDOW_DAYS", "HORIZON", "MIN_NAMES", "N_SETS", "ZONES", "build_panel",
           "evaluate_panel", "gate_params", "month_ends", "months_on", "run", "total_return",
           "windows"]

HORIZON = 12  # months, the forward return of an add (PLAN S69)
ZONES = ("buy_zone", "deep")  # gate 3's statuses
MIN_NAMES = 5  # zone adds a month needs before it is scored
N_SETS = 200  # random-day sets (the placebo), as tiers_replay
BAR_WINDOW_DAYS = 10  # a name with no bar this close to the date sits it out, as tiers_replay
DISCLAIMER = "Heuristic, not investment advice."
SOURCE = "idx-method cache/history and cache/dividends"


def gate_params(horizon: int = HORIZON) -> dict:
    return {"horizon": horizon, "stride": horizon, "min_n": MIN_N, "t_min": T_MIN,
            "alpha": ALPHA, "seed": SEED, "min_names": MIN_NAMES, "n_sets": N_SETS,
            "zones": list(ZONES), "min_bars": MIN_BARS}


def months_on(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def month_ends(days: Sequence[date]) -> list[date]:
    """The last session of each calendar month (the newest month's may still move)."""
    last: dict[tuple[int, int], date] = {}
    for d in days:
        k = (d.year, d.month)
        if k not in last or d > last[k]:
            last[k] = d
    return sorted(last.values())


def total_return(bars: Sequence[Mapping], dividends: Sequence[Mapping]
                 ) -> tuple[list[date], list[float]]:
    """Session dates and a total-return index starting at 1.0, built as `entry.measure` builds
    its own: back-adjusted closes, IDR dividends gone ex in (previous bar, this bar] over the
    previous raw close."""
    rows = sorted((date.fromisoformat(b["date"]), float(b["close"]))
                  for b in bars if b.get("close") and float(b["close"]) > 0)
    dates = [d for d, _ in rows]
    raw = [c for _, c in rows]
    adj = adjusted_closes(raw)
    n = len(rows)
    div_by_day: dict[date, float] = {}
    for dv in dividends:
        if (dv.get("ccy", "CURRENCY_IDR") != "CURRENCY_IDR" or not dv.get("value")
                or not dv.get("ex")):
            continue
        k = bisect.bisect_left(dates, date.fromisoformat(dv["ex"]))
        if 0 < k < n:
            div_by_day[dates[k]] = div_by_day.get(dates[k], 0.0) + float(dv["value"])
    tr = [1.0] * n
    for i in range(1, n):
        tr[i] = tr[i - 1] * (adj[i] / adj[i - 1] + div_by_day.get(dates[i], 0.0) / raw[i - 1])
    return dates, tr


def build_panel(history: Mapping[str, Sequence[Mapping]],
                dividends: Mapping[str, Sequence[Mapping]], horizon: int = HORIZON) -> dict:
    """`months`: per month end, every name's add with its point-in-time status and forward
    return; `pools`: per name, the forward returns of every eligible random day."""
    series = {s: total_return(bars, dividends.get(s, [])) for s, bars in history.items()}
    ends = month_ends(sorted({d for dates, _ in series.values() for d in dates}))
    window = timedelta(days=BAR_WINDOW_DAYS)

    def fwd(dates: list[date], tr: list[float], i: int) -> float | None:
        e = bisect.bisect_left(dates, months_on(dates[i], horizon))
        return 100 * (tr[e] / tr[i] - 1) if e < len(dates) else None

    pools: dict[str, list[float]] = {}
    by_month: dict[date, list[dict]] = {}
    for sym in sorted(series):
        dates, tr = series[sym]
        if len(dates) <= MIN_BARS:
            continue
        pool = [r for i in range(MIN_BARS, len(dates)) if (r := fwd(dates, tr, i)) is not None]
        if not pool:
            continue
        pools[sym] = pool
        for d in ends:
            i = bisect.bisect_right(dates, d)  # the first session after the month end
            if i < MIN_BARS or i >= len(dates):
                continue
            if d - dates[i - 1] > window or dates[i] - d > window:
                continue
            r = fwd(dates, tr, i)
            if r is None:
                continue
            levels = measure(history[sym], dividends.get(sym, []), as_of=d, symbol=sym)
            if levels is None:
                continue
            by_month.setdefault(d, []).append(
                {"symbol": sym, "status": levels.status, "add_date": dates[i], "fwd": r})
    return {"months": [{"date": d, "adds": by_month[d]} for d in sorted(by_month)],
            "pools": pools, "horizon": horizon}


def windows(days: Sequence[date], horizon: int) -> list[date]:
    """Month ends at least `horizon` months apart, from the first: forward returns that do not
    overlap."""
    out: list[date] = []
    for d in sorted(days):
        if not out or (d.year * 12 + d.month) - (out[-1].year * 12 + out[-1].month) >= horizon:
            out.append(d)
    return out


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


def evaluate_panel(panel: Mapping[str, Any], n_sets: int = N_SETS, **kw) -> dict:
    """The verdict on a panel (see the module docstring); `kw` goes to `placebo.evaluate`."""
    horizon = int(panel.get("horizon", HORIZON))
    pools = panel["pools"]
    seed = kw.setdefault("seed", SEED)
    alpha = kw.get("alpha", ALPHA)
    kw.setdefault("min_n", MIN_N)

    scored: dict[date, list[dict]] = {}
    for m in panel["months"]:
        zone = sorted((a for a in m["adds"] if a["status"] in ZONES), key=lambda a: a["symbol"])
        if len(zone) >= MIN_NAMES:
            scored[m["date"]] = zone
    real = {d: fmean(a["fwd"] for a in zone) for d, zone in scored.items()}

    sets: list[dict[date, float]] = []
    for s in range(n_sets):
        rng = random.Random(f"{seed}:dip-gate:{s}")
        sets.append({d: fmean(rng.choice(pools[a["symbol"]]) for a in scored[d])
                     for d in sorted(scored)})
    plac = {d: fmean(st[d] for st in sets) if sets else 0.0 for d in scored}

    win = windows(list(scored), horizon)
    feats: list[bool] = []
    rets: list[float] = []
    for d in win:
        feats += [True, False]
        rets += [real[d], plac[d]]
    v = evaluate(lambda f, _r: list(f), feats, rets, **kw)
    mean_real = fmean(real[d] for d in win) if win else None
    set_means = [fmean(st[d] for d in win) for st in sets] if win else []
    perm_p = ((1 + sum(m >= mean_real for m in set_means)) / (1 + len(set_means))
              if win and set_means else None)

    n = len(win)
    min_n = kw["min_n"]
    if n < min_n:
        status, reason = "insufficient", (
            f"insufficient sample: {n} non-overlapping {horizon}-month window(s) with at least "
            f"{MIN_NAMES} zone adds (needs {min_n})")
    elif not v.passed:
        status, reason = "failed", v.reason
    elif perm_p is None or perm_p > alpha:
        status, reason = "failed", (f"zone adds do not beat random-day adds "
                                    f"(perm p {perm_p:.3f} > {alpha})")
    else:
        status, reason = "passed", f"{v.reason}; perm p {perm_p:.3f}"

    # diagnostics on every scored month: forward returns overlap, so these decide nothing
    diffs = [real[d] - plac[d] for d in sorted(scored)]
    naive_t = (fmean(diffs) / (stdev(diffs) / len(diffs) ** 0.5)
               if len(diffs) > 1 and stdev(diffs) > 0 else None)
    by_status = {}
    for st in STATUSES:
        xs = [a["fwd"] for m in panel["months"] for a in m["adds"] if a["status"] == st]
        by_status[st] = {"adds": len(xs), "mean_fwd": _r(fmean(xs)) if xs else None,
                         "win_rate": _r(100 * sum(x > 0 for x in xs) / len(xs), 1) if xs else None}
    return {
        "status": status,
        "passed": status == "passed",
        "binding": status == "passed",
        "verdict": reason,
        "horizon": horizon,
        "windows": n,
        "windows_short": max(0, min_n - n),
        "window_dates": [d.isoformat() for d in win],
        "mean_real": _r(mean_real),
        "mean_placebo": _r(fmean(plac[d] for d in win)) if win else None,
        "t": _r(v.rule.t, 2),
        "p": _r(v.p_value),
        "perm_p": _r(perm_p),
        "control_t": _r(v.control_t, 2),
        "months": len(scored),
        "first_month": min(scored).isoformat() if scored else None,
        "last_month": max(scored).isoformat() if scored else None,
        "zone_adds": sum(len(z) for z in scored.values()),
        "all_months": {
            "note": "overlapping forward returns: a diagnostic, decides nothing",
            "mean_real": _r(fmean(real.values())) if scored else None,
            "mean_placebo": _r(fmean(plac.values())) if scored else None,
            "mean_diff": _r(fmean(diffs)) if diffs else None,
            "months_ahead": sum(x > 0 for x in diffs),
            "naive_t": _r(naive_t, 2),
        },
        "by_status": by_status,
        "per_month": [{"month": d.isoformat(), "zone_adds": len(scored[d]),
                       "real": _r(real[d]), "placebo": _r(plac[d])} for d in sorted(scored)],
        "params": {**gate_params(horizon), "n_sets": n_sets, "seed": seed,
                   "n_shuffles": v.n_shuffles, "n_controls": v.n_controls},
    }


def run(stocks: IdxMethodStocks | None = None, horizon: int = HORIZON,
        n_sets: int = N_SETS, **kw) -> dict:
    """The verdict on idx-method's history. A missing store gives a `blocked` result, never an
    exception."""
    stocks = stocks or IdxMethodStocks.from_config()
    base = {"source": SOURCE, "disclaimer": DISCLAIMER, "horizon": horizon}
    try:
        history = stocks.history()
        dividends = stocks.dividends(history)
    except SourceUnavailable as e:
        return {**base, "status": "blocked", "passed": False, "binding": False,
                "verdict": f"blocked: {e.reason}", "stale_inputs": [e.stale_input]}
    panel = build_panel(history, dividends, horizon)
    last = max((b["date"] for bars in history.values() for b in bars), default=None)
    return {**base, **evaluate_panel(panel, n_sets, **kw), "names": len(panel["pools"]),
            "history_to": last, "stale_inputs": []}


if __name__ == "__main__":  # uv run python -m assist.eval.dip_gate [horizon]
    import sys

    print(json.dumps(run(horizon=int(sys.argv[1]) if len(sys.argv) > 1 else HORIZON),
                     indent=1, default=str))
