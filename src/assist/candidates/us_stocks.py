"""US single stocks (PLAN S21): the P36 dividend and P37 GARP engines on sec-edgar data, in USD,
then held to the P34 USA hurdle in unhedged IDR and to the IDN hurdle in IDR too.

**Inputs** (`sources/usfin_stocks`), turned into the engines' own types:
- `Bar(date, price, mktcap)`: price is the split-adjusted close (close × `split_factor`, no
  dividend adjustment, so yields stay yields); mktcap is the close as traded × the shares
  outstanding of the last share count filed by that day (dei `EntityCommonStockSharesOutstanding`,
  else `CommonStockSharesOutstanding`), rescaled for any split between its cover date and the bar.
  Before a share count is filed a bar has no mktcap and the engines skip it.
- Dividends: where `tr_factor / split_factor` steps between two sessions, the raw amount is the
  close before × (1 − the step) (sec-edgar's adjustment, inverted), restated on the
  split-adjusted basis. These are Alpaca's `cash_dividend` actions, specials included.
- `Fundamentals` per 10-K / 10-Q filing, **available on its filed date** (point in time as
  `xbrl_as_of`): TTM net income and CFO = year to date + the prior fiscal year − the prior year to
  date (a 10-K's annual figure as is), each from the newest version filed by that day; equity at
  the period end. A restatement is a later row for the same period. Period ends are snapped to the
  calendar month end (52/53-week years end on the last Saturday) so P37's same-quarter lookback
  finds the quarter 3 or 5 years earlier.
- A bank is a filer of `Deposits` (no SIC in the store): no CFO cover, NI-only realised growth.

**Gates** (US, in place of IDX's board / free-float / Rp100 / quality floors, which have no US
inputs): mktcap ≥ `min_mktcap` (US$2bn) and median daily value (close × volume, last
`med_sessions` sessions) ≥ `min_med_value` (US$20m), at the date judged, live and in the replay.
"Operating company" is a listed symbol joined to an EDGAR filer with net income facts; ETFs and
trusts rarely join and never carry them.

**Hurdles.** A USD return r is r_IDR = (1 + r)(1 + fx) − 1 (`Hurdle.idr_return`, P29's adverse FX
move). `margin_usa` = r_IDR − USA hurdle, `margin_idn` = r_IDR − IDN hurdle; `margin` = the lower,
so a US name must beat the IDN alternative, not only Treasuries. GARP discounts at the **USD bar**,
the higher of the USA hurdle in USD (`local_required`) and the IDN hurdle in USD
((1 + IDN) / (1 + fx) − 1), and its terminal growth is US nominal GDP growth.

**Replay**: quarter ends, the gates above point in time, P36's 3-month price-plus-dividend
forward return, top-minus-bottom quintile into the placebo (`dividend_value.evaluate_replay`,
`garp.evaluate_replay`, unchanged). The universe is today's listed names (sec-edgar joins
delisted symbols to no CIK), so the replay is survivorship-biased upwards; a verdict that passes
is still read with that in mind. Candidates need a passed verdict, both hurdles and a positive
margin (GARP also a gap of at least `min_gap_pt`). **No peers by SIC**: sec-edgar's
`edgar_company` has no SIC code, so every name is its own sector bucket.

`CONFIG` is hand-set and this module sits under `candidates/`, so the journal's model fingerprint
changes when it does.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import fmean, median, stdev

from assist.candidates import dividend_value as dv
from assist.candidates import garp
from assist.candidates.hurdle import Hurdle, margin
from assist.candidates.screens import MAX_PER_SECTOR, TOP_N, select
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_series import Bar, Fundamentals, quarter_ends
from assist.sources.usfin_stocks import FACT_TAGS, SOURCE, Fact, Listing, UsBar, UsStocks

__all__ = [
    "CONFIG",
    "STYLES",
    "UsData",
    "build",
    "dividends_from_bars",
    "engine_bars",
    "idr_margins",
    "is_bank",
    "load",
    "median_value",
    "quarters_from_facts",
    "rank_live",
    "replay_panel",
    "run",
    "run_live",
    "usd_bar",
    "values",
]

CONFIG = {
    "min_mktcap": 2e9,  # USD
    "min_med_value": 2e7,  # USD a day, median
    "med_sessions": 60,
    "max_bar_age_days": 10,  # a name with no session this close to the date is not judged
    "top": 10,
    "dividend": {**dv.CONFIG, "g_cap_pt": 4.5, "replay_min_mktcap": 2e9},  # US nominal GDP
    "garp": {**garp.CONFIG, "gdp_pt": 4.5, "replay_hurdle_pt": 10.0, "replay_min_mktcap": 2e9},
}
STYLES = ("dividend_value", "garp")
NO_SIC = f"{SOURCE} edgar_company has no SIC: no peer groups, every name its own sector"
_ANNUAL = (350, 380)  # days in a fiscal year (52/53 weeks)
_MIN_PERIOD = 80


# ---------------- bars ----------------


def _first(facts: Iterable[Fact], concept: str) -> list[Fact]:
    """The facts of the first tag of `concept` (FACT_TAGS order) that has any."""
    facts = list(facts)
    for _, tag in FACT_TAGS[concept]:
        found = [f for f in facts if f.tag == tag]
        if found:
            return found
    return []


def dividends_from_bars(bars: Sequence[UsBar]) -> list[dict]:
    """[{ex, value, raw}]: a dividend on each session where `tr_factor / split_factor` steps up;
    `raw` per share as paid, `value` on the split-adjusted price basis."""
    out = []
    for prev, cur in zip(bars, bars[1:], strict=False):
        if not (prev.split_factor and cur.split_factor and cur.tr_factor):
            continue
        step = (prev.tr_factor / prev.split_factor) / (cur.tr_factor / cur.split_factor)
        if 1 - step > 1e-6:
            raw = prev.close * (1 - step)
            out.append({"ex": cur.date.isoformat(), "value": raw * cur.split_factor, "raw": raw})
    return out


def _share_counts(facts: Iterable[Fact]) -> list[tuple[date, date, float]]:
    """[(filed, cover date, shares)] by filed date; classes filed together are summed."""
    by: dict[tuple[str, date], tuple[date, float]] = {}
    for f in _first(facts, "shares"):
        if f.unit != "shares" or f.value <= 0:
            continue
        filed, total = by.get((f.accn, f.period_end), (f.filed, 0.0))
        by[(f.accn, f.period_end)] = (min(filed, f.filed), total + f.value)
    latest: dict[str, tuple[date, date, float]] = {}
    for (accn, end), (filed, v) in by.items():
        if accn not in latest or end > latest[accn][1]:
            latest[accn] = (filed, end, v)
    return sorted(latest.values())


def engine_bars(bars: Sequence[UsBar], facts: Iterable[Fact]) -> list[Bar]:
    """Engine bars: split-adjusted price, mktcap from the share count filed by each date."""
    counts = _share_counts(facts)
    filed = [c[0] for c in counts]
    dates = [b.date for b in bars]
    out = []
    for b in bars:
        mktcap = None
        i = bisect_right(filed, b.date)
        if i:
            _, cover, shares = counts[i - 1]
            j = bisect_right(dates, cover)
            sf_then = bars[j - 1].split_factor if j else bars[0].split_factor
            if sf_then:
                mktcap = b.close * shares * b.split_factor / sf_then
        out.append(Bar(b.date, b.close * b.split_factor, mktcap))
    return out


def values(bars: Sequence[UsBar]) -> list[tuple[date, float]]:
    """[(date, close × volume)] in USD, sessions with a volume."""
    return [(b.date, b.close * b.volume) for b in bars if b.volume is not None]


def median_value(vals: Sequence[tuple[date, float]], d: date,
                 sessions: int = CONFIG["med_sessions"]) -> float | None:
    """Median daily value of the last `sessions` sessions on or before `d`; None with fewer
    than a third of them."""
    i = bisect_right(vals, (d, float("inf")))
    window = [v for _, v in vals[max(0, i - sessions):i]]
    if len(window) < max(1, sessions // 3):
        return None
    return median(window)


# ---------------- fundamentals ----------------


def _snap(d: date) -> date:
    """The calendar month end nearest a fiscal period end (the 15th and later: its own month)."""
    if d.day < 15:
        return d.replace(day=1) - timedelta(days=1)
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def _versions(facts: Iterable[Fact], by: date) -> dict[tuple[date, date], float]:
    """The newest value filed on or before `by` per (period_start, period_end)."""
    best: dict[tuple[date, date], tuple[date, str, float]] = {}
    for f in facts:
        if f.filed > by:
            continue
        k = (f.period_start, f.period_end)
        if k not in best or (f.filed, f.accn) > best[k][:2]:
            best[k] = (f.filed, f.accn, f.value)
    return {k: v[2] for k, v in best.items()}


def _ttm(p: date, known: Mapping[tuple[date, date], float]) -> float | None:
    """Trailing 12 months to `p` from duration facts: an annual figure as is, else
    year to date + the prior fiscal year − the prior year to date."""
    lo, hi = _ANNUAL
    ytd = None
    for (s, e), v in known.items():
        days = (e - s).days
        if e != p or days < _MIN_PERIOD:
            continue
        if lo <= days <= hi:
            return v
        if days < lo and (ytd is None or days > (ytd[1] - ytd[0]).days):
            ytd = (s, e, v)
    if ytd is None:
        return None
    s, e, v = ytd
    fy = next(((fs, fv) for (fs, fe), fv in known.items()
               if 0 < (s - fe).days <= 4 and lo <= (fe - fs).days <= hi), None)
    if fy is None:
        return None
    days = (e - s).days
    prior = next((pv for (ps, pe), pv in known.items()
                  if abs((ps - fy[0]).days) <= 3 and abs((pe - ps).days - days) <= 7), None)
    return None if prior is None else v + fy[1] - prior


def quarters_from_facts(facts: Iterable[Fact]) -> list[Fundamentals]:
    """One `Fundamentals` per 10-K / 10-Q filing with a TTM net income, available on its filed
    date, sorted by (period, available)."""
    facts = list(facts)
    ni = [f for f in _first(facts, "net_income") if f.unit == "USD"]
    cfo = [f for f in _first(facts, "cfo") if f.unit == "USD"]
    equity = [f for f in _first(facts, "equity") if f.unit == "USD"]
    filings: dict[str, tuple[date, date]] = {}
    for f in ni:
        if not f.form.startswith(("10-K", "10-Q")) or f.period_start == f.period_end:
            continue
        p, filed = filings.get(f.accn, (f.period_end, f.filed))
        filings[f.accn] = (max(p, f.period_end), min(filed, f.filed))
    out = []
    for p, filed in sorted(set(filings.values())):
        ni_ttm = _ttm(p, _versions(ni, filed))
        if ni_ttm is None:
            continue
        eq = _versions([f for f in equity if f.period_end == p], filed)
        out.append(Fundamentals(
            _snap(p), filed, _ttm(p, _versions(cfo, filed)), next(iter(eq.values()), None),
            None, ni_ttm, None, None, None, None, None,
        ))
    return sorted(out, key=lambda f: (f.period, f.available))


def is_bank(facts: Iterable[Fact]) -> bool:
    return any(f.tag == "Deposits" for f in facts)


# ---------------- data ----------------


@dataclass
class UsData:
    """The engines' inputs per symbol (USD), plus the listing and median-value series."""

    bars: dict[str, list[Bar]] = field(default_factory=dict)
    values: dict[str, list[tuple[date, float]]] = field(default_factory=dict)
    quarters: dict[str, list[Fundamentals]] = field(default_factory=dict)
    dividends: dict[str, list[dict]] = field(default_factory=dict)
    listings: dict[str, Listing] = field(default_factory=dict)
    banks: set[str] = field(default_factory=set)
    stale: list[str] = field(default_factory=list)


def build(listings: Iterable[Listing], raw_bars: Mapping[str, Sequence[UsBar]],
          facts: Mapping[int, Sequence[Fact]]) -> UsData:
    data = UsData()
    for lst in listings:
        data.listings[lst.symbol] = lst
        fs = facts.get(lst.cik, ())
        if is_bank(fs):
            data.banks.add(lst.symbol)
        bars = raw_bars.get(lst.symbol) or []
        if not bars:
            continue
        data.bars[lst.symbol] = engine_bars(bars, fs)
        data.values[lst.symbol] = values(bars)
        data.dividends[lst.symbol] = dividends_from_bars(bars)
        data.quarters[lst.symbol] = quarters_from_facts(fs)
    return data


def load(src: UsStocks | None = None, *, as_of: date | None = None,
         symbols: Iterable[str] | None = None, limit: int | None = None) -> UsData:
    """Universe, facts (point in time, filed by `as_of`) and bars from sec-edgar, read-only.
    Bars are read only for names with net income facts. A missing or locked store is a stale
    input and an empty result, never a crash."""
    src = src or UsStocks()
    stale: list[str] = []
    try:
        listings = src.universe()
    except SourceUnavailable as e:
        return UsData(stale=[f"{e.stale_input}: universe"])
    if not listings:
        return UsData(stale=[f"{SOURCE} universe empty: no Alpaca asset list or bars matched"
                             " to EDGAR in this store"])
    if symbols is not None:
        keep = set(symbols)
        listings = [x for x in listings if x.symbol in keep]
    if limit is not None:
        listings = listings[:limit]
    try:
        facts = src.facts_many(sorted({x.cik for x in listings}), as_of)
    except SourceUnavailable as e:
        data = build(listings, {}, {})
        data.stale = [f"{e.stale_input}: XBRL facts ({e.detail})",
                      "no fundamentals: bars not read, no name judged"]
        return data
    raw: dict[str, list[UsBar]] = {}
    for x in listings:
        if not _first(facts.get(x.cik, ()), "net_income"):
            continue  # not an operating company with earnings on file
        try:
            raw[x.symbol] = [b for b in src.bars(x.symbol) if as_of is None or b.date <= as_of]
        except SourceUnavailable as e:
            stale.append(f"{e.stale_input}: bars")
            break
    data = build(listings, raw, facts)
    data.stale = list(dict.fromkeys(stale))
    return data


# ---------------- hurdles ----------------


def usd_bar(usa: Hurdle | None, idn: Hurdle | None) -> tuple[float | None, str | None]:
    """(the USD return a US name needs, which market binds): the higher of the USA hurdle in
    USD and the IDN hurdle in USD at the same FX move."""
    if usa is None or usa.local_required is None:
        return None, None
    bar, binding = usa.local_required, "USA"
    if idn is not None and idn.required is not None and usa.fx_move is not None:
        idn_usd = 100 * ((1 + idn.required / 100) / (1 + usa.fx_move) - 1)
        if idn_usd > bar:
            bar, binding = idn_usd, "IDN"
    return bar, binding


def idr_margins(expected_usd: float | None, usa: Hurdle | None, idn: Hurdle | None) -> dict:
    """The USD expected return in unhedged IDR and its margins over both hurdles; `margin_pt`
    is the lower, None unless both are known."""
    idr = usa.idr_return(expected_usd) if usa is not None and expected_usd is not None else None
    m_usa, m_idn = margin(idr, usa), margin(idr, idn)
    both = None if m_usa is None or m_idn is None else min(m_usa, m_idn)
    return {"expected_idr_pt": idr, "margin_usa_pt": m_usa, "margin_idn_pt": m_idn,
            "margin_pt": both}


# ---------------- judging one name ----------------


def _judge(style: str, data: UsData, sym: str, d: date, hurdle_pt: float | None,
           cfg: Mapping, own: bool = True) -> tuple[object | None, str | None]:
    """(engine assessment, None) or (None, the first gate failed) for `sym` on `d`."""
    bars = data.bars.get(sym) or []
    bar = dv._bar_at(bars, d)
    if bar is None:
        return None, "no price"
    if bar.date < d - timedelta(days=cfg["max_bar_age_days"]):
        return None, "no recent session"
    if bar.mktcap < cfg["min_mktcap"]:
        return None, "mktcap"
    med = median_value(data.values.get(sym) or [], d, cfg["med_sessions"])
    if med is None or med < cfg["min_med_value"]:
        return None, "liquidity"
    bank = sym in data.banks
    quarters = data.quarters.get(sym) or []
    divs = data.dividends.get(sym) or []
    if style == "dividend_value":
        a = dv.assess(d, bars, quarters, divs, bank=bank, own=own, cfg=cfg["dividend"])
    else:
        a = garp.assess(d, bars, quarters, divs, hurdle_pt=hurdle_pt, bank=bank,
                        cfg=cfg["garp"])
    if a is None:
        return None, "no price"
    if not a.ok:
        return None, a.failed[0]
    return a, None


def _check(style: str) -> None:
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}, got {style!r}")


# ---------------- replay ----------------


def replay_panel(style: str, data: UsData, *, hurdle_pt: float | None = None,
                 cfg: Mapping = CONFIG) -> list[tuple[date, list[dict]]]:
    """→ [(quarter end, [{symbol, expected_pt | gap_pt, fwd}])]: the names passing the gates on
    that date (P36's ranking key for dividends, P37's realised gap at `hurdle_pt` in USD for
    GARP) with the price-plus-dividend return to the next quarter end."""
    _check(style)
    if style == "garp" and hurdle_pt is None:
        hurdle_pt = cfg["garp"]["replay_hurdle_pt"]
    firsts = [b[0].date for b in data.bars.values() if b]
    lasts = [b[-1].date for b in data.bars.values() if b]
    if not firsts:
        return []
    qes = quarter_ends(min(firsts), max(lasts))
    panel = []
    for q, q1 in zip(qes, qes[1:], strict=False):
        recs = []
        for sym, bs in data.bars.items():
            a, _ = _judge(style, data, sym, q, hurdle_pt, cfg, own=False)
            if a is None:
                continue
            end = dv._bar_at(bs, q1)
            if end is None or end.date <= q:
                continue
            paid = sum(r["value"] for r in data.dividends.get(sym) or []
                       if a.bar_date < date.fromisoformat(r["ex"]) <= end.date)
            rec = {"symbol": sym, "fwd": (end.price + paid) / a.price - 1}
            if style == "dividend_value":
                rec["expected_pt"] = a.expected_pt
            else:
                rec["gap_pt"] = a.realised_gap_pt
            recs.append(rec)
        panel.append((q, recs))
    return panel


# ---------------- live ----------------


def rank_live(style: str, data: UsData, as_of: date, usa: Hurdle | None, idn: Hurdle | None,
              cfg: Mapping = CONFIG) -> tuple[list[dict], Counter]:
    """Gate and rank today's names → (rows, rejects by first rule failed). Dividends rank by
    margin (by USD expected return without one), GARP by gap."""
    _check(style)
    bar_pt, _ = usd_bar(usa, idn)
    rows, rejects = [], Counter()
    for sym in sorted(data.bars):
        a, why = _judge(style, data, sym, as_of, bar_pt, cfg)
        if a is None:
            rejects[why] += 1
            continue
        lst = data.listings.get(sym)
        row = {
            "symbol": sym, "cik": lst.cik if lst else None, "title": lst.title if lst else None,
            "sector": None, "bank": sym in data.banks, "style": style,
            "expected_usd_pt": a.expected_pt, **idr_margins(a.expected_pt, usa, idn),
            "legs": a.legs(), "price": a.price, "mktcap": a.mktcap,
            "med_value": median_value(data.values.get(sym) or [], as_of, cfg["med_sessions"]),
            "bar_date": a.bar_date, "period": a.period, "reasons": list(a.reasons),
        }
        if style == "garp":
            row |= {"gap_pt": a.gap_pt, "realised_gap_pt": a.realised_gap_pt,
                    "risks": ["no consensus: realised growth only"]}
        rows.append(row)
    if style == "garp":
        rows.sort(key=lambda x: (-x["gap_pt"], x["symbol"]))
    else:
        rows.sort(key=lambda x: (-(x["margin_pt"] if x["margin_pt"] is not None
                                   else x["expected_usd_pt"]), x["symbol"]))
    return rows, rejects


def run(style: str, data: UsData, *, as_of: date, usa: Hurdle | None, idn: Hurdle | None,
        panel: Sequence[tuple[date, list[dict]]] | None = None, cfg: Mapping = CONFIG,
        **kw) -> dict:
    """One style: replay verdict, today's ranking, the top `cfg["top"]`, and candidates only
    when the verdict passed and a name beats both hurdles. `kw` goes to `evaluate`."""
    _check(style)
    engine = dv if style == "dividend_value" else garp
    scfg = cfg["dividend" if style == "dividend_value" else "garp"]
    stale = list(data.stale)
    for h in (usa, idn):
        if h is not None:
            stale += list(h.stale_inputs)
    bar_pt, binding = usd_bar(usa, idn)
    if bar_pt is None or idn is None or idn.required is None:
        stale.append("USA or IDN hurdle unavailable: no candidate")
    stale.append(NO_SIC)
    if panel is None:
        panel = replay_panel(style, data, hurdle_pt=bar_pt, cfg=cfg)
    min_pool = kw.pop("min_pool", scfg["min_pool"])
    verdict = engine.evaluate_replay(panel, min_pool=min_pool, **kw)
    _, _, spreads = engine.observations(panel, min_pool)
    rows, rejects = rank_live(style, data, as_of, usa, idn, cfg)
    candidates: list = []
    if verdict.passed:
        ok = [r for r in rows if r["margin_pt"] is not None and r["margin_pt"] > 0
              and (style != "garp" or r["gap_pt"] >= scfg["min_gap_pt"])]
        key = "gap_pt" if style == "garp" else "margin_pt"
        candidates = list(select([(r[key], {}, r) for r in ok], TOP_N, {}, MAX_PER_SECTOR))
    return {
        "screen": f"us_{style}",
        "as_of": as_of,
        "passed": verdict.passed,
        "blocked": None if verdict.passed else verdict.reason,
        "verdict": {k: v for k, v in verdict.to_dict().items() if k != "control_ts"},
        "replay_basis": ("today's listed names (survivorship-biased)"
                         + ("; realised growth only" if style == "garp" else "")),
        "quarters": len(spreads),
        "spread_mean": fmean(spreads) if spreads else None,
        "spread_t": (fmean(spreads) / (stdev(spreads) / len(spreads) ** 0.5)
                     if len(spreads) > 2 and stdev(spreads) > 0 else None),
        "hurdle_pt": usa.required if usa is not None else None,
        "idn_hurdle_pt": idn.required if idn is not None else None,
        "usd_bar_pt": bar_pt,
        "binding": binding,
        "hurdle_drivers": [*(usa.drivers if usa else ()), *(idn.drivers if idn else ())],
        "universe": len(data.listings),
        "with_bars": len(data.bars),
        "pool": len(rows),
        "rejects": dict(rejects),
        "ranking": rows,
        "top": rows[: cfg["top"]],
        "candidates": candidates,
        "fingerprint": {k: v for k, v in cfg.items() if k not in ("dividend", "garp")}
        | {"engine": dict(scfg)},
        "stale_inputs": list(dict.fromkeys(stale)),
    }


def run_live(as_of: date | None = None, regime=None, *, limit: int | None = None,
             src: UsStocks | None = None, **kw) -> dict:
    """Both styles over the real stores (read-only): sec-edgar through `usfin serve` or a
    read-only ATTACH, and the P34 USA and IDN hurdles on the last session under `regime`
    (default: P8's)."""
    from assist.candidates.hurdle import hurdles

    data = load(src, as_of=as_of, limit=limit)
    lasts = [b[-1].date for b in data.bars.values() if b]
    as_of = max(lasts) if lasts else (as_of or date.today())
    if regime is None:
        from assist.layers.regime import regime as current_regime

        regime = current_regime(as_of)
    usa, idn = hurdles(["USA", "IDN"], as_of, regime)
    return {
        "as_of": as_of,
        "universe": len(data.listings),
        "with_bars": len(data.bars),
        "stale_inputs": list(data.stale),
        **{s: run(s, data, as_of=as_of, usa=usa, idn=idn, **dict(kw)) for s in STYLES},
    }
