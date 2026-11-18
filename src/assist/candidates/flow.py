"""Money flow per IDN name (PLAN S107, phase S): four legs, each a `FrameworkResult`, pure and
point in time. Context only (`role` context, `gate` untested) until S108's replay passes and the
user adopts a leg (S112); it names buys only and never sells a held name (phase S rule 2).

**Point in time** (rule 4). A day's flow is known the next trading day, so a leg read on day `d`
uses the days strictly before `d` (`window_end`); the replay buys at `d`'s close. A KSEI month
is known at the earlier of its `loaded` date and month end + `ksei_lag_days` (S105: 36 of 37
months were backfilled on one day, the live one took 3 days). An insider trade is known
`insider_lag_days` after its date: Stockbit's feed carries the trade date, not the filing date,
so the lag is a conservative stand-in.

**Legs** (`LEGS`: each ranks on the equal-weight z blend of its components, `screens.blend`; no
weights are fitted, rule 3):

- `accumulation` (the frameworks document §6.1 step 5, Wyckoff's bandarmology overlay, with
  foreign investors standing in for the operator): net foreign IDR ÷ traded IDR over 20 and 60
  days (−1 … +1), and the share of net-buy days among the 60 days with a foreign net. Counted only
  while every close of the 60 days stays within `flat_band` of the window's first close, on the
  path chained from IDX's adjusted `previous` (so a split is no move): bought, not yet marked
  up. A window with more than `non_regular_max` of its value on the negotiated market is flagged
  and left out. Flow is IDR value, so a split needs no adjustment.
- `supply_demand` (§3.3, CAN SLIM's S): traded IDR on up days ÷ up + down days over 50 days,
  up and down by close vs IDX's adjusted previous; unchanged days do not count.
- `ownership` (§3.3, CAN SLIM's I): the share of foreign institutions and local funds (MF, PF,
  IS) in all KSEI holdings, in pt, and its change over 1 and 3 months (`owners`, phase S choice
  2). Both earlier months must be loaded. The base is the whole register, not institutions plus
  local individuals as planned: a controlling holder moving shares from his own name into a
  company (BYAN 2026-10: 10.75bn shares left "local individual", nobody bought) moved that ratio
  32pt. A local-individual move over `reclass_pt` in a month is flagged, context only.
- `insider`: net shares bought on the market by insiders and major holders (`IdxMethodInsider`:
  buys and sells only) over 90 days of known filings ÷ listed shares, in bp. A single filing of
  `insider_block_pct` of listed shares or more is a corporate deal (takeover, restructuring:
  KETR 56.5%, SGER 50.1% in 2026), not market buying, and is left out and counted.

`score` is the leg's headline component (`HEADLINE`); `rank` blends every component over the
names given. **Flags** on the accumulation result, context only: `effort without result` (§6.1
step 4: 20-day traded value ≥ `effort_ratio` × the 60 days before, price within
`effort_result`), `thin market` (below the screens' liquidity gate). The S105 cross-check
against idx-method's `bars.net_foreign` is not carried as a flag: the two agree in sign on
99.7% of name-days because Stockbit relays IDX.

**Pool** (rule 5): `eligible` applies the screens' liquidity gates (`GATES`: 60-day median
value, days traded in 60, price floor) on the same definitions as `factors.derive`; the special
boards and the hard thesis fail are applied by the caller. Hashed by `journal.RULE_GLOBS`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from math import isnan

from assist.candidates.frameworks.base import FrameworkResult
from assist.candidates.screens import GATES, blend
from assist.sources.idxmethod_insider import InsiderTrade
from assist.sources.idxscape import FlowSeries
from assist.sources.kseistat import StockHolders

__all__ = ["CONFIG", "HEADLINE", "LEGS", "VERSION", "accumulation", "config", "effort_vs_result",
           "eligible", "insider", "known_ksei", "liquidity", "name_legs", "ownership", "rank",
           "supply_demand", "window_end"]

VERSION = "0.1.0"
CONFIG = {
    "accumulation_days": (20, 60),
    "flat_band": 0.10,  # every close of the window within ±10% of its first
    "non_regular_max": 0.5,  # more of the window's value on the negotiated market: left out
    "supply_demand_days": 50,
    "ownership_months": (1, 3),
    "owners": ("foreign_inst", "local_funds"),  # against local individuals (choice 2)
    "ksei_lag_days": 10,
    "insider_days": 90,
    "insider_lag_days": 10,
    "insider_block_pct": 5.0,  # a single filing this share of listed shares or more: a deal
    "reclass_pt": 10.0,  # local individuals' share moving more in a month: flagged
    "effort_days": 20,
    "effort_ratio": 1.5,
    "effort_result": 0.03,
    "liquidity_days": 60,
}
LEGS: dict[str, tuple[tuple[str, int], ...]] = {
    "accumulation": (("nf_20d", 1), ("nf_60d", 1), ("buy_days_60d", 1)),
    "supply_demand": (("up_value_share_50d", 1),),
    "ownership": (("inst_shift_1m", 1), ("inst_shift_3m", 1)),
    "insider": (("insider_net_bp_90d", 1),),
}
HEADLINE = {"accumulation": "nf_60d", "supply_demand": "up_value_share_50d",
            "ownership": "inst_shift_3m", "insider": "insider_net_bp_90d"}
NEUTRAL = {"supply_demand": 0.5}  # the score that means neither buying nor selling


def config() -> dict:
    out = {k: list(v) if isinstance(v, tuple) else v for k, v in CONFIG.items()}
    return {"version": VERSION, **out, "legs": {k: [c for c, _ in v] for k, v in LEGS.items()}}


def _result(leg: str, code: str, as_of: date | None, comps: Mapping[str, float | None],
            flags: Sequence[str] = (), counted: bool = True) -> FrameworkResult:
    score = comps.get(HEADLINE[leg]) if counted else None
    if counted and any(comps.get(k) is None for k, _ in LEGS[leg]):
        score = None
    flags = tuple(flags)
    if score is None and not flags:
        flags = (f"{leg}: not computable",)
    mid = NEUTRAL.get(leg, 0.0)
    signal = "n/a" if score is None else "buying" if score > mid else "selling" if score < mid \
        else "even"
    return FrameworkResult(framework=f"flow_{leg}", ticker=code, as_of=as_of, score=score,
                           signal=signal, components=comps, flags=flags, version=VERSION)


# ---------------- daily legs ----------------


def window_end(s: FlowSeries, d: date) -> int | None:
    """Index of the last day strictly before `d` (its flow is known on `d`), None if none."""
    lo, hi, x = 0, len(s.days), d.toordinal()
    while lo < hi:
        mid = (lo + hi) // 2
        if s.days[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1 if lo else None


def _path(s: FlowSeries, first: int, end: int) -> list[float]:
    """Adjusted price relative to `first`'s close, chained on IDX's adjusted previous."""
    p, out = 1.0, [1.0]
    for i in range(first + 1, end + 1):
        prev = s.previous[i]
        p *= s.close[i] / prev if prev > 0 else 1.0
        out.append(p)
    return out


def liquidity(s: FlowSeries, end: int) -> dict[str, float | None]:
    """60-day median value (upper, zero days included), days traded, price, Amihud (mean |return|
    per IDR bn over the traded days), as `factors.derive` defines them."""
    n = CONFIG["liquidity_days"]
    lo = max(0, end - n + 1)
    vals = sorted(s.value[lo:end + 1])
    amih = []
    for i in range(max(1, lo), end + 1):
        if s.value[i] > 0 and s.previous[i] > 0:
            amih.append(abs(s.close[i] / s.previous[i] - 1) / (s.value[i] / 1e9))
    return {
        "med_value_60d": vals[len(vals) // 2] if end - lo + 1 >= n else None,
        "days_traded_60": float(sum(1 for v in s.value[lo:end + 1] if v > 0)),
        "price": s.close[end],
        "amihud": sum(amih) / len(amih) if amih else None,
    }


def eligible(liq: Mapping[str, float | None]) -> bool:
    return ((liq.get("med_value_60d") or 0) >= GATES["min_med_value_60d"]
            and (liq.get("days_traded_60") or 0) >= GATES["min_days_traded_60"]
            and (liq.get("price") or 0) >= GATES["min_price"])


def effort_vs_result(s: FlowSeries, end: int) -> bool | None:
    """§6.1 step 4: traded value up sharply over the last `effort_days` while the price held."""
    k, n = CONFIG["effort_days"], CONFIG["liquidity_days"]
    if end - k - n + 1 < 0:
        return None
    recent = sum(s.value[end - k + 1:end + 1]) / k
    before = sum(s.value[end - k - n + 1:end - k + 1]) / n
    if before <= 0:
        return None
    move = _path(s, end - k, end)[-1] - 1.0
    return recent >= CONFIG["effort_ratio"] * before and abs(move) <= CONFIG["effort_result"]


def accumulation(s: FlowSeries, d: date) -> FrameworkResult:
    short, long_ = CONFIG["accumulation_days"]
    end = window_end(s, d)
    comps: dict[str, float | None] = {k: None for k in (
        "nf_20d", "nf_60d", "buy_days_60d", "move_60d", "non_regular_60d")}
    if end is None or end + 1 < long_:
        return _result("accumulation", s.code, d, comps,
                       [f"short history: {0 if end is None else end + 1} days, needs {long_}"])
    flags: list[str] = []
    lo = end - long_ + 1
    for days, key in ((short, "nf_20d"), (long_, "nf_60d")):
        value = sum(s.value[end - days + 1:end + 1])
        comps[key] = sum(s.net_foreign[end - days + 1:end + 1]) / value if value > 0 else None
    nets = [x for x in s.net_foreign[lo:end + 1] if x != 0]
    comps["buy_days_60d"] = sum(1 for x in nets if x > 0) / len(nets) if nets else None
    path = _path(s, lo, end)
    comps["move_60d"] = max(abs(p - 1.0) for p in path)
    value = sum(s.value[lo:end + 1])
    comps["non_regular_60d"] = sum(s.non_regular[lo:end + 1]) / value if value > 0 else None
    liq = liquidity(s, end)
    comps["amihud_60d"] = liq["amihud"]
    effort = effort_vs_result(s, end)
    if effort:
        flags.append("effort without result: value up, price held (20 days)")
    if not eligible(liq):
        flags.append("thin market: below the screens' liquidity gate")
    counted = True
    if comps["move_60d"] > CONFIG["flat_band"] + 1e-12:
        counted = False
        flags.append(f"price left the ±{CONFIG['flat_band']:.0%} band in 60 days: not counted")
    if (comps["non_regular_60d"] or 0) > CONFIG["non_regular_max"]:
        counted = False
        flags.append("non-regular market over half the 60-day value: left out")
    if nets == [] and counted:
        flags.append("no foreign net in 60 days")
    return _result("accumulation", s.code, d, comps, flags, counted)


def supply_demand(s: FlowSeries, d: date) -> FrameworkResult:
    n = CONFIG["supply_demand_days"]
    end = window_end(s, d)
    if end is None or end + 1 < n:
        return _result("supply_demand", s.code, d, {"up_value_share_50d": None},
                       [f"short history: {0 if end is None else end + 1} days, needs {n}"])
    up = down = 0.0
    for i in range(end - n + 1, end + 1):
        if s.close[i] > s.previous[i]:
            up += s.value[i]
        elif s.close[i] < s.previous[i]:
            down += s.value[i]
    share = up / (up + down) if up + down > 0 else None
    flags = [] if share is not None else ["no traded up or down day in 50 days"]
    return _result("supply_demand", s.code, d, {"up_value_share_50d": share}, flags)


# ---------------- ownership ----------------


def known_ksei(row: StockHolders) -> date:
    lagged = row.date + timedelta(days=CONFIG["ksei_lag_days"])
    return min(row.loaded, lagged) if row.loaded else lagged


def _month(d: date) -> int:
    return d.year * 12 + d.month - 1


def _inst_share(r: StockHolders) -> float | None:
    inst = sum(getattr(r, k) for k in CONFIG["owners"])
    return 100.0 * inst / r.holdings if r.holdings > 0 else None


def _ind_share(r: StockHolders) -> float | None:
    return 100.0 * r.local_ind / r.holdings if r.holdings > 0 else None


def ownership(rows: Iterable[StockHolders], d: date) -> FrameworkResult:
    """`rows`: one code's months, any order; only those known by `d` are read."""
    known = sorted((r for r in rows if known_ksei(r) <= d), key=lambda r: r.date)
    keys = ("inst_share", "inst_month", "inst_shift_1m", "inst_shift_3m", "local_ind_shift_1m")
    comps: dict[str, float | None] = dict.fromkeys(keys)
    code = known[-1].code if known else "?"
    if not known:
        return _result("ownership", code, None, comps, ["no KSEI month known yet"])
    last = known[-1]
    by_month = {_month(r.date): r for r in known}
    share = _inst_share(last)
    comps["inst_share"], comps["inst_month"] = share, float(last.date.toordinal())
    flags = []
    for k in CONFIG["ownership_months"]:
        prev = by_month.get(_month(last.date) - k)
        before = _inst_share(prev) if prev else None
        key = f"inst_shift_{k}m"
        if share is None or before is None:
            flags.append(f"no KSEI month {k} before {last.date.isoformat()}")
        else:
            comps[key] = share - before
        if k == 1 and prev is not None:
            ind, ind_before = _ind_share(last), _ind_share(prev)
            if ind is not None and ind_before is not None:
                comps["local_ind_shift_1m"] = ind - ind_before
                if abs(ind - ind_before) > CONFIG["reclass_pt"]:
                    flags.append(f"local individuals moved {ind - ind_before:+.1f}pt in a month:"
                                 " a holder likely reclassified")
    counted = all(comps[k] is not None for k, _ in LEGS["ownership"])
    return _result("ownership", code, known_ksei(last), comps, flags, counted)


# ---------------- insider ----------------


def insider(trades: Iterable[InsiderTrade], listed: float, d: date) -> FrameworkResult:
    """`trades`: one symbol's market trades; those known in the 90 days to `d` count."""
    lag, n = CONFIG["insider_lag_days"], CONFIG["insider_days"]
    lo, hi = d - timedelta(days=lag + n), d - timedelta(days=lag)
    window = [t for t in trades if lo < t.date <= hi]
    code = window[0].symbol if window else "?"
    comps: dict[str, float | None] = {"insider_net_bp_90d": None,
                                      "trades_90d": float(len(window)), "blocks_90d": 0.0}
    if not window:
        return _result("insider", code, d, comps, ["no insider market trade in 90 days"])
    if not listed or listed <= 0 or isnan(listed):
        return _result("insider", code, d, comps, ["no listed shares"])
    cut = CONFIG["insider_block_pct"] / 100 * listed
    market = [t for t in window if abs(t.shares) < cut]
    blocks = len(window) - len(market)
    comps["trades_90d"], comps["blocks_90d"] = float(len(market)), float(blocks)
    flags = [f"{blocks} block(s) of {CONFIG['insider_block_pct']:g}%+ of listed shares left out"
             " as corporate deals"] if blocks else []
    if not market:
        return _result("insider", code, d, comps, flags or ["no market trade"])
    comps["insider_net_bp_90d"] = sum(t.shares for t in market) / listed * 1e4
    return _result("insider", code, d, comps, flags)


# ---------------- one name, the cross-section ----------------


def name_legs(s: FlowSeries, holders: Iterable[StockHolders], trades: Iterable[InsiderTrade],
              d: date) -> dict[str, FrameworkResult]:
    end = window_end(s, d)
    listed = s.listed[end] if end is not None else 0.0
    out = {
        "accumulation": accumulation(s, d),
        "supply_demand": supply_demand(s, d),
        "ownership": ownership(holders, d),
        "insider": insider(trades, listed, d),
    }
    # the result carries the series' code even where no KSEI or insider row was read
    return {k: (v if v.ticker == s.code else FrameworkResult.from_dict({**v.to_dict(),
                                                                        "ticker": s.code}))
            for k, v in out.items()}


def rank(legs: Mapping[str, Mapping[str, FrameworkResult]], leg: str,
         pool: Iterable[str] | None = None) -> list[tuple]:
    """`screens.blend` over the leg's components: [(score, {component: z}, row)] best first. A
    name whose leg is not counted (score None) is left out, as is one outside `pool`."""
    keep = None if pool is None else set(pool)
    rows = []
    for code, results in sorted(legs.items()):
        r = results.get(leg)
        if r is None or r.score is None or (keep is not None and code not in keep):
            continue
        rows.append({"symbol": code, **r.components})
    return blend(rows, LEGS[leg])
