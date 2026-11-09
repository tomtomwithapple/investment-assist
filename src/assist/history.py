"""Point-in-time history of the IDN bonds and stocks rules (PLAN S47, P66).

Plumbing, not a rule: it calls `idn_bonds` and `idn_stocks` unchanged on every month end, each
time with the inputs as they were known that day, and records what each rule said:

- regime: `regime.classify(regime.read_inputs(day))`, FRED through `fred_as_of`;
- P17 overrides and P18 signals as of the day (their own publication lags);
- the bonds rule's USD/IDR from `IdnSources.usdidr` (P65: JISDOR spliced on the MAS cross);
- for stocks, the JCI earnings yield from `factor_series` daily PE and mktcap
  (`FactorSeriesEY`, the `FactorSnapshots` interface; EY = 100 / PE, loss makers kept) and the
  layer-1 macro input held at 50 (`held_score`, open question 4), shifted by P17's override as
  the rule does live;
- each rule reads its own stores with its own lags (PHEI by fetch date, CPI and the OECD 10Y
  proxy past their publication lags).

Each row: as_of, call, proposed stance, the inputs whose absence made it a no_call (with the
reason), the 10Y source, the regime, the numbers behind the call, the stale inputs, and the
forward return over `HORIZON` month ends (null until the target month is complete):
- stocks: JCI month-end close to the close `HORIZON` months later (`jci()`, stitched P51);
- bonds: `bond_returns` (carry − duration × Δyield) on the month-end 10Y, IGSYC where present,
  else dbnomics' OECD proxy (`ten_year_months`), only between months exactly `HORIZON` apart,
  never across the 2025-01 → 2026-09 hole. The proxy is a monthly average, centred mid-month:
  a month-end call is priced from the *next* month's average to the one `HORIZON` months after
  it (lagged one month, P74), so the measured return never starts before the call. The IGSYC
  month-end close is on the call date and is used as it stands.

Dates: every calendar month end from `START` (factor_series begins 2016-11-07) to the last one
before `today`. The first month with every input and the last with a forward return are the gate's
window (open question 1); rows outside it stay in the history so the missing inputs are visible.

The history is cached under `data/history/IDN-<asset>.json`, keyed by the model fingerprint,
each store's newest date (the doctor's), the dates and the horizon; any change rebuilds it.

`python -m assist.history [--today D] [--rebuild]` builds it on the real stores (set
ASSIST_SIBLINGS_ROOT) and prints the summary per rule.
"""

from __future__ import annotations

import argparse
import calendar
import dataclasses
import json
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from assist import journal
from assist.eval.placebo import edge, forward_returns
from assist.layers import regime as regime_layer
from assist.layers.bonds.idn import PROXY_10Y, IdnBonds, bond_returns, idn_bonds
from assist.layers.overrides import idn_overrides
from assist.layers.rules.idn_stocks import IdnStocks, idn_stocks, month_end_closes
from assist.layers.signals import idn_signals
from assist.layers.types import AssetScore
from assist.sources.base import Row, SourceUnavailable
from assist.sources.idxmethod import JCI
from assist.sources.idxscape_phei import IGSYC_10Y

__all__ = [
    "ASSETS",
    "CACHE_DIR",
    "HORIZON",
    "START",
    "HistoryRow",
    "HistorySources",
    "RuleHistory",
    "bond_forward",
    "build",
    "held_score",
    "history",
    "lag_monthly_averages",
    "last_month_end",
    "month_ends",
    "ten_year_months",
]

SUBJECT = "IDN"
ASSETS = ("bonds", "stocks")
HORIZON = 3  # months, = pipeline.RULE_HORIZON (the live gate's; stride and block alike)
START = date(2016, 11, 30)  # first month end of factor_series (2016-11-07)
CACHE_DIR = journal.REPO_ROOT / "data" / "history"
SCHEMA = 1
HELD_SCORE = 50.0  # open question 4: layer 1 held at 50 in history (no worldbankscape before)
HELD_SOURCE = "layer 1 held at 50"

Month = tuple[int, int]


# ---------------- dates ----------------


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def month_ends(start: date, end: date) -> list[date]:
    """Calendar month ends in [start, end]."""
    out, y, m = [], start.year, start.month
    while (d := _month_end(y, m)) <= end:
        if d >= start:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def last_month_end(today: date) -> date:
    """The newest month end strictly before `today` (the day itself is not over)."""
    return today.replace(day=1) - timedelta(days=1)


def _key(d: date) -> Month:
    return d.year, d.month


def _add(k: Month, n: int) -> Month:
    y, m = divmod(k[0] * 12 + k[1] - 1 + n, 12)
    return y, m + 1


# ---------------- rows ----------------


@dataclass(frozen=True)
class HistoryRow:
    """One rule on one month end, as known that day."""

    as_of: date
    call: str
    proposed_stance: str | None
    missing: tuple[str, ...]  # "input: reason", the inputs that made it a no_call
    ten_year_source: str | None
    forward_return: float | None
    regime: str | None = None
    values: Mapping[str, float | None] = field(default_factory=dict)
    stale_inputs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"as_of": self.as_of.isoformat(), "call": self.call,
                "proposed_stance": self.proposed_stance, "missing": list(self.missing),
                "ten_year_source": self.ten_year_source, "forward_return": self.forward_return,
                "regime": self.regime, "values": dict(self.values),
                "stale_inputs": list(self.stale_inputs)}

    @classmethod
    def from_dict(cls, d: Mapping) -> HistoryRow:
        return cls(date.fromisoformat(d["as_of"]), d["call"], d["proposed_stance"],
                   tuple(d["missing"]), d["ten_year_source"], d["forward_return"],
                   d.get("regime"), dict(d.get("values", {})), tuple(d.get("stale_inputs", ())))


@dataclass(frozen=True)
class RuleHistory:
    """The IDN `asset` rule over its month ends, with what the cache was keyed on."""

    asset: str
    rows: tuple[HistoryRow, ...]
    horizon: int = HORIZON
    fingerprint: str | None = None
    store_dates: Mapping[str, str | None] = field(default_factory=dict)

    def row(self, as_of: date) -> HistoryRow:
        return next(r for r in self.rows if r.as_of == as_of)

    def calls(self) -> dict[date, str]:
        return {r.as_of: r.call for r in self.rows}

    def returns(self) -> dict[date, float]:
        return {r.as_of: r.forward_return for r in self.rows if r.forward_return is not None}

    def sample(self, stride: int | None = None) -> dict[str, int]:
        """Non-overlapping windows as the gate counts them (`rule_verdict` → `placebo.edge`):
        the month ends with a forward return, every `stride`-th, split into on (enter), off
        (hold / reduce) and no_call."""
        stride = stride or self.horizon
        rows = [r for r in self.rows if r.forward_return is not None]
        feats = [None if r.call == "no_call" else r.call == "enter" for r in rows]
        e = edge(feats, [r.forward_return for r in rows], stride=stride, min_n=0)
        return {"on": e.n_on, "off": e.n_off, "no_call": len(rows[::stride]) - e.n_on - e.n_off}

    def summary(self) -> dict:
        """First and last month, calls by type, months with each missing input, the window
        with a call and the non-overlapping on/off sample."""
        calls: dict[str, int] = {}
        missing: dict[str, int] = {}
        for r in self.rows:
            calls[r.call] = calls.get(r.call, 0) + 1
            for m in r.missing:
                name = m.split(":")[0]
                missing[name] = missing.get(name, 0) + 1
        called = [r.as_of for r in self.rows if r.call != "no_call"]
        return {"asset": self.asset,
                "first": f"{self.rows[0].as_of:%Y-%m}" if self.rows else None,
                "last": f"{self.rows[-1].as_of:%Y-%m}" if self.rows else None,
                "months": len(self.rows), "calls": calls, "missing": missing,
                "called_first": f"{called[0]:%Y-%m}" if called else None,
                "called_last": f"{called[-1]:%Y-%m}" if called else None,
                "with_return": len(self.returns()), "sample": self.sample()}

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "subject": SUBJECT, "asset": self.asset,
                "horizon": self.horizon, "fingerprint": self.fingerprint,
                "store_dates": dict(self.store_dates),
                "rows": [r.to_dict() for r in self.rows]}

    @classmethod
    def from_dict(cls, d: Mapping) -> RuleHistory:
        return cls(d["asset"], tuple(HistoryRow.from_dict(r) for r in d["rows"]),
                   d.get("horizon", HORIZON), d.get("fingerprint"), dict(d.get("store_dates", {})))


# ---------------- sources ----------------


@dataclass
class HistorySources:
    """`idn`: a `pipeline.IdnSources` whose `snapshots` serves `factors_on(as_of)` on any date
    (`FactorSeriesEY` live); `fred`: the FRED source `regime.read_inputs` takes."""

    idn: Any
    fred: Any

    @classmethod
    def default(cls) -> HistorySources:
        from assist.pipeline import IdnSources
        from assist.sources.idxmethod_series import FactorSeriesEY
        from assist.sources.usfin import FredSource

        idn = dataclasses.replace(IdnSources.default(), snapshots=FactorSeriesEY.from_config())
        return cls(idn=idn, fred=FredSource())


def held_score(day: date) -> AssetScore:
    """The stocks rule's layer-1 input in history: 50 (open question 4)."""
    return AssetScore(SUBJECT, "stocks", day, HELD_SCORE, 0.0, source=HELD_SOURCE)


# ---------------- missing inputs ----------------


def _reason(stale: Sequence[str], keys: Sequence[str], default: str) -> str:
    hits = [s for s in stale if any(k in s for k in keys)]
    return "; ".join(dict.fromkeys(hits)) or default


def _too_old(sig) -> str | None:
    if sig is not None and "too old to call" in sig.detail:
        return sig.detail.rsplit("; ", 1)[-1]
    return None


def _ten_missing(rule, sig_name: str) -> list[str]:
    stale = rule.stale_inputs
    if rule.ten_year_source is None:
        return ["10Y: " + _reason(stale, (IGSYC_10Y, PROXY_10Y, "idxscape_phei (", "dbnomics ("),
                                  "no 10Y")]
    old = _too_old(rule.signal(sig_name))
    return [f"10Y: {old}"] if old else []


def _bonds_missing(b: IdnBonds) -> tuple[str, ...]:
    if b.call != "no_call":
        return ()
    out = _ten_missing(b, "real_yield")
    if b.ten_year_source is not None and b.real_yield is None:
        out.append("CPI: " + _reason(b.stale_inputs, ("cpi", "CPI", "bps-looker ("), "no CPI"))
    if b.signal("sbn_non_resident_change") is None:
        out.append("foreign SBN: " + _reason(b.stale_inputs, ("SBN", "idxscape ("),
                                             "no signal"))
    if b.breakout is None:
        out.append("USD/IDR: " + _reason(b.stale_inputs, ("JISDOR", "USD/IDR"), "no fixings"))
    return tuple(out)


def _stocks_missing(s: IdnStocks) -> tuple[str, ...]:
    if s.call != "no_call":
        return ()
    stale = s.stale_inputs
    out = []
    if s.earnings_yield is None:
        out.append("earnings yield: " + _reason(stale, ("factor", "idx-method ("), "no EY"))
    out += _ten_missing(s, "implied_erp_vs_hurdle")
    if s.earnings_yield is not None and s.ten_year_source is not None:
        if s.real_yield is None and s.hurdle is not None:
            out.append("CPI: " + _reason(stale, ("cpi", "CPI", "bps-looker ("), "no CPI"))
        if s.hurdle is None:
            out.append("hurdle: " + _reason(stale, ("erp", "crp", "dbnomics ("), "no hurdle"))
    if s.signal("idx_foreign_flow") is None:
        out.append("foreign flow: " + _reason(stale, ("IDX_NET_FOREIGN", "idxscape ("),
                                              "no signal"))
    if s.macro_score is None:
        out.append("macro: " + _reason(stale, ("overrides", "layer 1"), "no score"))
    return tuple(out)


def _value(rule, name: str) -> float | None:
    sig = rule.signal(name)
    return None if sig is None else sig.value


def _bonds_values(b: IdnBonds) -> dict[str, float | None]:
    return {"real_yield": b.real_yield, "real_yield_pct": b.real_yield_pct, "slope": b.slope,
            "sbn_non_resident_change": _value(b, "sbn_non_resident_change"),
            "jisdor_trend": _value(b, "jisdor_trend"),
            "breakout": None if b.breakout is None else float(b.breakout)}


def _stocks_values(s: IdnStocks) -> dict[str, float | None]:
    return {"earnings_yield": s.earnings_yield, "ey_gap": s.ey_gap, "real_yield": s.real_yield,
            "implied_erp": s.implied_erp, "hurdle": s.hurdle,
            "erp_vs_hurdle": _value(s, "implied_erp_vs_hurdle"),
            "idx_foreign_flow": _value(s, "idx_foreign_flow"),
            "ksei_foreign_share": _value(s, "ksei_foreign_share"),
            "macro_score": s.macro_score}


# ---------------- forward returns ----------------


def _runs(points: Mapping[Month, tuple[date, float]]) -> list[list[tuple[date, float]]]:
    """Month-end points split into runs of consecutive months."""
    runs: list[list[tuple[date, float]]] = []
    prev: Month | None = None
    for k in sorted(points):
        if prev is None or k != _add(prev, 1):
            runs.append([])
        runs[-1].append(points[k])
        prev = k
    return runs


def _forward(points: Mapping[Month, tuple[date, float]], horizon: int,
             fn: Callable[[list[tuple[date, float]], int], list[tuple[date, float]]]
             ) -> dict[Month, float]:
    out: dict[Month, float] = {}
    for run in _runs(points):
        out.update({_key(d): r for d, r in fn(run, horizon)})
    return out


def _complete(points: Iterable[tuple[date, float]], today: date) -> dict[Month, tuple[date, float]]:
    """Month-end points keyed by month, the month still running on `today` left out."""
    return {_key(d): (d, v) for d, v in points if _month_end(d.year, d.month) < today}


def stock_forward(jci_rows: Iterable[Row], horizon: int, today: date) -> dict[Month, float]:
    """JCI month-end close to the close `horizon` complete months later."""
    return _forward(_complete(month_end_closes(jci_rows), today), horizon, forward_returns)


def lag_monthly_averages(tens: Iterable[tuple[date, float]]) -> list[tuple[date, float]]:
    """The 10Y points a month-end call is priced from, at or after the call (P74).

    A point dated the 1st of its month is a period-dated monthly average (dbnomics' OECD
    `idn.rate.long`; a daily month-end close is never dated the 1st): it is centred mid-month,
    so it stands for the *previous* month's end, re-dated there. The call on month end M thus
    starts on M+1's average and ends on M+1+horizon's: lagged one month, never before the call.
    Any other point is a daily month-end close (IGSYC), on the call date, kept as it stands and
    preferred over a lagged average for the same month."""
    out: dict[Month, tuple[date, float]] = {}
    pts = list(tens)
    for d, v in pts:
        if d.day == 1:
            prev = d - timedelta(days=1)
            out.setdefault(_key(prev), (prev, v))
    for d, v in pts:
        if d.day != 1:
            out[_key(d)] = (d, v)
    return [out[k] for k in sorted(out)]


def bond_forward(tens: Iterable[tuple[date, float]], horizon: int,
                 today: date | None = None) -> dict[Month, float]:
    """`bond_returns` on month-end 10Y yields, only between months exactly `horizon` apart;
    monthly averages are lagged one month first (`lag_monthly_averages`), so each return starts
    at or after its call."""
    pts = lag_monthly_averages(tens)
    keyed = _complete(pts, today) if today is not None else {_key(d): (d, v) for d, v in pts}
    return _forward(keyed, horizon, lambda run, h: bond_returns(run, h))


def _rows(source: Any, sid: str, end: date) -> list[Row]:
    try:
        return source.rows([sid], end=end)
    except SourceUnavailable:
        return []


def ten_year_months(idn: Any, end: date) -> list[tuple[date, float]]:
    """Month-end 10Y as stored: IGSYC month-end closes where they exist, the OECD proxy (monthly
    averages dated the 1st) elsewhere. `bond_forward` lags the averages one month (P74); this is
    the series `pipeline.rule_prices` should take for bonds instead of its own copy."""
    out: dict[Month, tuple[date, float]] = {}
    for source, sid in ((idn.dbnomics, PROXY_10Y), (idn.phei, IGSYC_10Y)):
        for d, v in month_end_closes(_rows(source, sid, end)):
            out[_key(d)] = (d, v)
    return [out[k] for k in sorted(out)]


# ---------------- build ----------------


def rules_on(day: date, src: HistorySources) -> tuple[IdnBonds, IdnStocks]:
    """Both rules on `day`, with every input as known that day (as `pipeline.gather_idn`)."""
    idn = src.idn
    reg = regime_layer.classify(regime_layer.read_inputs(day, src.fred))
    ov = idn_overrides(day, bps=idn.bps, bisfetcher=idn.bisfetcher, dbnomics=idn.dbnomics,
                       satudatascape=idn.satudatascape)
    sig = idn_signals(day, idxscape=idn.idxscape, kseistat=idn.kseistat, tic=idn.tic)
    bonds = idn_bonds(day, reg, ov, sig, phei=idn.phei, dbnomics=idn.dbnomics, bps=idn.bps,
                      idxscape=idn.usdidr or idn.idxscape)
    stocks = idn_stocks(day, reg, ov, sig, held_score(day), phei=idn.phei, dbnomics=idn.dbnomics,
                        bps=idn.bps, idxmethod=idn.idxmethod, snapshots=idn.snapshots)
    return bonds, stocks


def build(src: HistorySources, dates: Sequence[date], *, today: date,
          horizon: int = HORIZON, fingerprint: str | None = None,
          store_dates: Mapping[str, str | None] | None = None,
          progress: Callable[[date], None] | None = None) -> dict[str, RuleHistory]:
    """Both rules on each of `dates`, with their forward returns as known on `today`."""
    dates = sorted(dates)
    horizon_end = today - timedelta(days=1)
    stock_fwd = stock_forward(_rows(src.idn.idxmethod, JCI, horizon_end), horizon, today)
    bond_fwd = bond_forward(ten_year_months(src.idn, horizon_end), horizon, today)
    rows: dict[str, list[HistoryRow]] = {a: [] for a in ASSETS}
    for day in dates:
        if progress is not None:
            progress(day)
        b, s = rules_on(day, src)
        rows["bonds"].append(HistoryRow(day, b.call, b.proposed_stance, _bonds_missing(b),
                                        b.ten_year_source, bond_fwd.get(_key(day)), b.regime,
                                        _bonds_values(b), b.stale_inputs))
        rows["stocks"].append(HistoryRow(day, s.call, s.proposed_stance, _stocks_missing(s),
                                         s.ten_year_source, stock_fwd.get(_key(day)), s.regime,
                                         _stocks_values(s), s.stale_inputs))
    return {a: RuleHistory(a, tuple(rows[a]), horizon, fingerprint, dict(store_dates or {}))
            for a in ASSETS}


# ---------------- cache ----------------


def cache_path(cache_dir: Path, asset: str) -> Path:
    return Path(cache_dir) / f"{SUBJECT}-{asset}.json"


def _cache_key(fingerprint: str, store_dates: Mapping, start: date, end: date,
               horizon: int) -> dict:
    return {"schema": SCHEMA, "fingerprint": fingerprint, "store_dates": dict(store_dates),
            "start": start.isoformat(), "end": end.isoformat(), "horizon": horizon}


def _load(cache_dir: Path, key: Mapping) -> dict[str, RuleHistory] | None:
    out = {}
    for a in ASSETS:
        p = cache_path(cache_dir, a)
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if doc.get("key") != key:
            return None
        out[a] = RuleHistory.from_dict(doc)
    return out


def live_store_dates(today: date) -> dict[str, str | None]:
    """Each store's newest date, as `assist doctor` reads it (read-only)."""
    from assist.pipeline import live_doctor

    return {s.name: s.newest.isoformat() if s.newest else None for s in live_doctor(today)}


def history(sources: HistorySources | None = None, *, today: date, start: date = START,
            horizon: int = HORIZON, cache_dir: Path = CACHE_DIR, fingerprint: str | None = None,
            store_dates: Mapping[str, str | None] | None = None, rebuild: bool = False,
            progress: Callable[[date], None] | None = None) -> dict[str, RuleHistory]:
    """The cached history of both rules over the month ends `start` → `last_month_end(today)`;
    rebuilt (and rewritten) when the fingerprint, a store's newest date, the dates or the
    horizon changed. `sources` defaults to the real stores, built only on a miss."""
    fingerprint = fingerprint or journal.model_fingerprint()
    store_dates = dict(store_dates if store_dates is not None else live_store_dates(today))
    end = last_month_end(today)
    key = _cache_key(fingerprint, store_dates, start, end, horizon)
    if not rebuild and (hit := _load(cache_dir, key)) is not None:
        return hit
    src = sources if sources is not None else HistorySources.default()
    out = build(src, month_ends(start, end), today=today, horizon=horizon,
                fingerprint=fingerprint, store_dates=store_dates, progress=progress)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    for a, h in out.items():
        doc = {**h.to_dict(), "key": key, "built": today.isoformat()}
        tmp = cache_path(cache_dir, a).with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        tmp.replace(cache_path(cache_dir, a))
    return out


# ---------------- CLI (live check) ----------------


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assist.history", description=__doc__.split(
        "\n")[0])
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--start", type=date.fromisoformat, default=START)
    ap.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--rows", action="store_true", help="print every row too")
    args = ap.parse_args(argv)
    out = history(today=args.today, start=args.start, cache_dir=args.cache_dir,
                  rebuild=args.rebuild,
                  progress=lambda d: print(f"  {d}", file=sys.stderr, flush=True))
    for h in out.values():
        print(json.dumps(h.summary(), indent=1))
        if args.rows:
            for r in h.rows:
                print(f"{r.as_of} {r.call:8} {r.ten_year_source or '-':16} "
                      f"{'' if r.forward_return is None else f'{r.forward_return:+.4f}':8} "
                      f"{' | '.join(r.missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
