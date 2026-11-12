"""Baseline board (PLAN S94, phase Q rules 3–4): every screen's replay picks through S92's report.

For each existing IDN screen with a replay (`dividend_value`, `garp`, `industry_value`, and
`screens`' `dividend`, `value` and `momentum`) the names its replay would have held at each
quarter end are fed to `eval.picks_report.report`, with the same date's eligible pool (every
name the replay ranked that date) as the comparator. The held names are the **top quintile**
by the screen's own ranking, the very basket its placebo scores (`len(pool) // QUANTILES`, ties
by symbol), on dates whose pool reaches the screen's `min_pool`. A monthly replay contributes
its March, June, September and December month ends only. Start dates are calendar month ends
(user decision 5): a replay dated on the last trading day of a month starts on that month's last
calendar day, and the report prices it at the last bar on or before it.

Weights are n/a for every start (user decision 6: replay picks were never held, so financer
statements cover none of them), so only the equal-weighted leg is reported. The gate state is
the screen's existing placebo verdict on its own replay (`evaluate_replay` / `evaluate_screen`,
default arguments): `passed` or `failed` with the verdict's reason. Only windows of
`VERDICT_MONTHS` or less (1m, 3m, 6m) may carry a verdict (decision 4); 1y–5y are descriptive.

Every registered framework (`candidates.frameworks.registered()`) is listed too. One that
defines `replay(ctx) -> Replay` (ctx: `LiveContext`, the loaded stores) is reported like a
screen; one without it is listed as `no replay` with its own gate, so S95–S100 appear on the
board as soon as they register.

**Survivorship.** Each entry counts the `factor_universe` names flagged delisted that ever enter
its pool and its picks, and the picks held at their last bar (`stopped`). `screens`' replays read
`cache/history/` for today's screener names only, so they hold no delisted name.

The board is reporting, not a rule: this module and the `/frameworks` view sit outside
`journal.RULE_GLOBS`, so the model fingerprint does not change. `assist run` never calls it;
`assist frameworks` writes `out/frameworks/IDN.json`. `build` and its helpers are pure; `live`
is the thin reader (read-only on the stores).
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import fmean
from typing import Any

import jsonschema

from assist.eval.picks_report import WINDOWS, PicksData, report
from assist.layers.types import DISCLAIMER, SCHEMA_DIR

__all__ = ["OUT_DIR", "QUANTILES", "SCHEMA", "SCHEMA_VERSION", "VERDICT_MONTHS", "VERDICT_NOTE",
           "LiveContext", "Replay", "build", "gate_of", "live", "quarter_start", "ranked_blend",
           "ranked_by", "survivorship", "top_quintile", "validator", "write"]

SCHEMA = SCHEMA_DIR / "frameworks.schema.json"
SCHEMA_VERSION = "1.0.0"
OUT_DIR = "frameworks"
MARKET = "IDN"
QUANTILES = 5  # as every screen's placebo (screens.QUANTILES)
VERDICT_MONTHS = 6  # decision 4: a verdict needs non-overlapping 3-month windows; 1y-5y describe
QUARTER_MONTHS = (3, 6, 9, 12)
VERDICT_NOTE = ("Only 1m, 3m and 6m can carry a verdict (the pass test is the placebo on "
                "non-overlapping 3-month windows); 1y, 3y and 5y have too few independent "
                "windows and are descriptive only.")
SOURCES = ["idx-method stockbiter.db (factor_series, fundamentals, dividends, "
           "industry_membership, factor_universe)", "idx-method cache/history/ (daily closes)",
           "idx-method jkse_daily.csv / idxscape IDX.COMPOSITE (JCI)"]


# ---------------- replays ----------------


@dataclass(frozen=True)
class Replay:
    """One screen's or framework's replay: the held names and the eligible pool per start."""

    name: str
    kind: str  # screen | framework
    description: str
    basis: str  # how the held names are chosen
    picks: Mapping[date, Sequence[str]]
    pools: Mapping[date, Sequence[str]]
    gate: str = "untested"  # untested | failed | passed
    gate_reason: str | None = None
    cadence: str = "quarterly"
    notes: tuple[str, ...] = ()


def quarter_start(d: date) -> date | None:
    """The calendar month end of `d` when it falls in a quarter-end month, else None."""
    if d.month not in QUARTER_MONTHS:
        return None
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def ranked_by(panel: Sequence[tuple[date, Sequence[Mapping]]], key: str
              ) -> list[tuple[date, list[str]]]:
    """Each date's symbols best first by `key` (higher first, ties by symbol), as the screens'
    `observations` rank them; a record without the key is left out."""
    return [(d, [r["symbol"] for r in sorted((r for r in recs if r.get(key) is not None),
                                             key=lambda r: (-r[key], r["symbol"]))])
            for d, recs in panel]


def ranked_blend(panel: Sequence[tuple[date, Sequence[Mapping]]],
                 legs: Sequence[tuple[str, int]]) -> list[tuple[date, list[str]]]:
    """`screens.blend` order per date (the names holding every leg)."""
    from assist.candidates.screens import blend

    return [(d, [r["symbol"] for _, _, r in blend(list(recs), legs)]) for d, recs in panel]


def top_quintile(ranked: Iterable[tuple[date, Sequence[str]]], min_pool: int,
                 quantiles: int = QUANTILES
                 ) -> tuple[dict[date, list[str]], dict[date, list[str]]]:
    """→ (picks, pools) per quarter start: the top `len // quantiles` of each ranked date whose
    pool holds at least `min_pool` names, and that pool."""
    picks: dict[date, list[str]] = {}
    pools: dict[date, list[str]] = {}
    for d, syms in ranked:
        q = quarter_start(d)
        syms = list(dict.fromkeys(syms))
        cut = len(syms) // quantiles
        if q is None or len(syms) < min_pool or cut == 0:
            continue
        picks[q], pools[q] = syms[:cut], syms
    return picks, pools


def gate_of(verdict: Any) -> tuple[str, str | None]:
    """A placebo `Verdict` → (`passed` | `failed`, its reason)."""
    if verdict is None:
        return "untested", None
    return ("passed" if verdict.passed else "failed"), verdict.reason


def from_ranked(name: str, description: str, basis: str,
                ranked: Iterable[tuple[date, Sequence[str]]], min_pool: int, verdict: Any, *,
                kind: str = "screen", cadence: str = "quarterly",
                notes: Iterable[str] = ()) -> Replay:
    picks, pools = top_quintile(ranked, min_pool)
    state, reason = gate_of(verdict)
    return Replay(name, kind, description, basis, picks, pools, state, reason, cadence,
                  tuple(notes))


# ---------------- the board ----------------


def survivorship(rep: Replay, universe: Mapping[str, Mapping], stopped: Iterable[str] = ()
                 ) -> dict:
    """Delisted coverage of one replay: `factor_universe` names flagged delisted that enter its
    pool and its picks, and the picks held at their last bar."""
    delisted = {s for s, u in universe.items() if (u or {}).get("delisted")}
    pooled = {s for syms in rep.pools.values() for s in syms}
    picked = {s for syms in rep.picks.values() for s in syms}
    stopped = sorted(set(stopped))
    in_pool, in_picks = sorted(delisted & pooled), sorted(delisted & picked)
    if not universe:
        note = "delisted coverage unknown: factor_universe not read"
    else:
        note = (f"{len(in_pool)} of {len(delisted)} delisted names ever enter the pool, "
                f"{len(in_picks)} are ever held; {len(stopped)} held name(s) stopped trading "
                "inside a window and are held at their last bar")
    return {"delisted_known": len(delisted), "delisted_in_pool": len(in_pool),
            "delisted_picked": len(in_picks), "pool_names": len(pooled),
            "picked_names": len(picked), "stopped": stopped, "note": note}


def _as_of(replays: Sequence[Replay], data: PicksData) -> date | None:
    """The earlier of the last JCI bar and the newest bar of any held name (S92's default)."""
    held = {s for r in replays for syms in r.picks.values() for s in syms}
    ends = [data.prices[s][-1][0] for s in held if data.prices.get(s)]
    last = [d for d in (data.jci[-1][0] if data.jci else None, max(ends) if ends else None)
            if d is not None]
    return min(last) if last else None


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 6)


def _entry(rep: Replay, data: PicksData, universe: Mapping[str, Mapping], as_of: date | None,
           windows: Sequence[tuple[str, int]]) -> dict:
    starts = sorted(rep.picks)
    rows = []
    stopped: set[str] = set()
    if starts:
        res = report({d: [(s, None) for s in rep.picks[d]] for d in starts}, data.prices,
                     data.dividends, data.jci, pools=rep.pools, windows=windows, as_of=as_of)
        for w in res.windows:
            stopped.update(w.stopped)
        for s in res.summary:
            rows.append({
                "window": s.window, "months": s.months, "verdict_window": s.months
                <= VERDICT_MONTHS, "n_starts": s.n_starts, "n_independent": s.n_independent,
                "total": _r(s.equal_total), "price": _r(s.equal_price),
                "dividend": _r(s.equal_dividend), "jci": _r(s.jci),
                "pool_total": _r(s.pool_total), "excess_jci": _r(s.excess_jci),
                "excess_pool": _r(s.excess_pool), "rank_pool": None})
        missing = sum(1 for w in res.windows if w.status == "ok" and w.equal is None)
    else:
        rows = [{"window": lb, "months": m, "verdict_window": m <= VERDICT_MONTHS,
                 "n_starts": 0, "n_independent": 0, "total": None, "price": None,
                 "dividend": None, "jci": None, "pool_total": None, "excess_jci": None,
                 "excess_pool": None, "rank_pool": None} for lb, m in windows]
        missing = 0
    notes = list(rep.notes)
    if missing:
        notes.append(f"{missing} start × window basket(s) n/a: a held name had no bar on or "
                     "before the start (never filled in)")
    return {
        "name": rep.name, "kind": rep.kind, "description": rep.description, "basis": rep.basis,
        "cadence": rep.cadence, "status": "ok" if starts else "no picks",
        "gate": {"state": rep.gate, "reason": rep.gate_reason},
        "starts": len(starts),
        "first_start": starts[0].isoformat() if starts else None,
        "last_start": starts[-1].isoformat() if starts else None,
        "mean_picks": _r(fmean(len(rep.picks[d]) for d in starts)) if starts else None,
        "mean_pool": _r(fmean(len(rep.pools.get(d) or ()) for d in starts)) if starts else None,
        "survivorship": survivorship(rep, universe, stopped),
        "windows": rows, "notes": notes,
    }


def _no_replay(fw: Any, windows: Sequence[tuple[str, int]], why: str) -> dict:
    return {
        "name": fw.name, "kind": "framework", "description": (type(fw).__doc__ or "").strip()
        .split("\n")[0], "basis": why, "cadence": None, "status": "no replay",
        "gate": {"state": fw.gate, "reason": None}, "starts": 0, "first_start": None,
        "last_start": None, "mean_picks": None, "mean_pool": None, "survivorship": None,
        "windows": [{"window": lb, "months": m, "verdict_window": m <= VERDICT_MONTHS,
                     "n_starts": 0, "n_independent": 0, "total": None, "price": None,
                     "dividend": None, "jci": None, "pool_total": None, "excess_jci": None,
                     "excess_pool": None, "rank_pool": None} for lb, m in windows],
        "notes": [why],
    }


def build(replays: Sequence[Replay], data: PicksData, *, day: date,
          universe: Mapping[str, Mapping] | None = None, as_of: date | None = None,
          windows: Sequence[tuple[str, int]] = WINDOWS, frameworks: Sequence[Any] = (),
          skipped: Sequence[Mapping] = (), stale: Iterable[str] = ()) -> dict:
    """The board payload (schema `frameworks.schema.json`). `frameworks` are registered
    frameworks with no replay; `skipped` names screens left out and why. Pure."""
    universe = universe or {}
    as_of = as_of or _as_of(replays, data)
    entries = [_entry(r, data, universe, as_of, windows) for r in replays]
    entries += [_no_replay(f, windows, "no replay yet: listed, not measured")
                for f in frameworks]
    ranking: dict[str, list[dict]] = {}
    for i, (label, _) in enumerate(windows):
        ok = [e for e in entries if e["windows"][i]["excess_pool"] is not None]
        ok.sort(key=lambda e: (-e["windows"][i]["excess_pool"], e["name"]))
        for k, e in enumerate(ok, 1):
            e["windows"][i]["rank_pool"] = k
        ranking[label] = [{"name": e["name"], "excess_pool": e["windows"][i]["excess_pool"],
                           "excess_jci": e["windows"][i]["excess_jci"],
                           "n_independent": e["windows"][i]["n_independent"]} for e in ok]
    return {
        "schema_version": SCHEMA_VERSION, "market": MARKET, "built": day.isoformat(),
        "as_of": as_of.isoformat() if as_of else None,
        "windows": [{"window": lb, "months": m, "verdict_window": m <= VERDICT_MONTHS}
                    for lb, m in windows],
        "verdict_note": VERDICT_NOTE,
        "method": ("Held names: each replay's top quintile at each quarter end (calendar month "
                   "end), equal-weighted; pool: every name the replay ranked that date, "
                   "equal-weighted; JCI: price index. Total = price + dividends gone ex in the "
                   "window, not reinvested. Means over complete starts; n_independent counts "
                   "the non-overlapping windows behind each mean."),
        "ranking": ranking, "frameworks": entries, "skipped": [dict(s) for s in skipped],
        "stale_inputs": list(dict.fromkeys(list(stale) + list(data.stale))),
        "sources": list(SOURCES), "disclaimer": DISCLAIMER,
    }


def validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def write(payload: Mapping, out_dir: Path) -> Path:
    """Schema-check and write `out/frameworks/IDN.json`."""
    errors = list(validator().iter_errors(payload))
    if errors:
        raise ValueError(f"frameworks payload fails the schema: {errors[0].message}")
    path = Path(out_dir) / OUT_DIR / f"{payload['market']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return path


# ---------------- live ----------------


@dataclass
class LiveContext:
    """The stores, each read once on first use (read-only); what a framework's `replay` gets."""

    day: date
    cache: dict = field(default_factory=dict)
    stale: list[str] = field(default_factory=list)

    def _get(self, key: str, fn: Callable[[], Any]) -> Any:
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]

    @property
    def stocks(self):
        from assist.sources.idxmethod_stocks import IdxMethodStocks

        return self._get("stocks", IdxMethodStocks.from_config)

    @property
    def table(self) -> dict[str, dict]:
        def load():
            from assist.candidates.factors import load_factors

            table, st = load_factors(self.stocks, self.day)
            self.stale.extend(st)
            return table
        return self._get("table", load)

    @property
    def bar_date(self) -> date:
        ds = [r["bar_date"] for r in self.table.values() if r.get("bar_date")]
        return max(ds) if ds else self.day

    @property
    def dividend_data(self):
        def load():
            from assist.candidates import dividend_value

            d = dividend_value.load()
            self.stale.extend(d.stale)
            return d
        return self._get("dividend_data", load)

    @property
    def universe(self) -> dict[str, dict]:
        def load():
            from assist.sources.base import SourceUnavailable
            from assist.sources.idxmethod_series import IdxMethodSeries

            try:
                return IdxMethodSeries(self.stocks.root).universe()
            except SourceUnavailable as e:
                self.stale.append(e.stale_input)
                return {}
        return self._get("universe", load)


def _hurdle_pt(ctx: LiveContext) -> tuple[float, str]:
    """GARP's replay hurdle as its screen sets it: today's IDN hurdle, else the fallback."""
    from assist.candidates import garp
    from assist.candidates import hurdle as hurdle_mod
    from assist.layers.regime import regime

    try:
        h = hurdle_mod.hurdle("IDN", ctx.bar_date, regime(ctx.bar_date))
        if h.required is not None:
            return h.required, f"today's IDN hurdle {h.required:.2f}%"
    except Exception as e:  # noqa: BLE001 - context only
        ctx.stale.append(f"IDN hurdle failed: {type(e).__name__}: {e}"[:200])
    pt = garp.CONFIG["replay_hurdle_pt"]
    return pt, f"fallback hurdle {pt:.2f}% (today's unknown)"


def _undervalued(ctx: LiveContext) -> list[Replay]:
    from assist.candidates import dividend_value as dv
    from assist.candidates import garp

    data = ctx.dividend_data
    banks = {s for s, r in ctx.table.items() if r.get("car")}
    panel = dv.replay_panel(data.bars, data.quarters, data.dividends, banks,
                            bank_f=dv.replay_bank_f(data, banks))
    out = [from_ranked("dividend_value", "Dividend return (yield + sustainable growth) above the "
                       "hurdle, with safe payout, CFO cover and dividend record.",
                       "top quintile by expected return (Gordon), gated names over IDR 1T",
                       ranked_by(panel, "expected_pt"), dv.CONFIG["min_pool"],
                       dv.evaluate_replay(panel),
                       notes=["banks are today's (screener CAR), as the screen replays; "
                              "banks below the point-in-time F floor are out (S88)"])]
    h, basis = _hurdle_pt(ctx)
    gpanel = garp.replay_panel(data.bars, data.quarters, data.dividends, banks, hurdle_pt=h)
    out.append(from_ranked("garp", "Growth at a reasonable price: realised growth clearly above "
                           "the growth the price implies (reverse DCF).",
                           "top quintile by realised growth gap, gated names over IDR 1T",
                           ranked_by(gpanel, "gap_pt"), garp.CONFIG["min_pool"],
                           garp.evaluate_replay(gpanel),
                           notes=[f"replay on {basis}; consensus never ranks a replay"]))
    return out


def _industry(ctx: LiveContext) -> list[Replay]:
    from assist.candidates import industry_value as iv
    from assist.sources.idxmethod_series import IdxMethodSeries

    data = iv.load(IdxMethodSeries(ctx.stocks.root), ctx.bar_date)
    ctx.stale.extend(data.stale)
    panel, _ = iv.replay_panel(data, ctx.bar_date)
    return [from_ranked(iv.NAME, iv.DESCRIPTION, "top quintile by peer-relative score at "
                        "quarter-end months", ranked_by(panel, "score"), iv.CONFIG["min_pool"],
                        iv.evaluate_replay(panel), cadence="monthly replay, quarterly starts",
                        notes=[f for f in iv.FLAGS if "membership" in f or "delisted" in f])]


def _screens(ctx: LiveContext) -> list[Replay]:
    from assist.candidates import screens as sc
    from assist.sources.base import SourceUnavailable

    stocks = ctx.stocks
    factors = stocks.factors()
    history = stocks.history(factors)
    dividends = fundamentals = None
    try:
        dividends = stocks.dividends(factors)
    except SourceUnavailable as e:
        ctx.stale.append(e.stale_input)
    try:
        fundamentals = stocks.fundamentals(factors)
    except SourceUnavailable as e:
        ctx.stale.append(e.stale_input)
    boards = sc._data_json(stocks, "special_boards.json", ctx.stale) or {}
    flagged = {s for b in sc.GATES["exclude_boards"] for s in boards.get(b, [])}
    panel = sc.build_panel(history, dividends, fundamentals, flagged)
    out = []
    for s in sc.SCREENS.values():
        legs = " + ".join(k for k, _ in s.legs)
        out.append(from_ranked(
            s.name, s.description, f"top quintile by {legs} (z-blend) at quarter-end months",
            ranked_blend(panel, s.legs), sc.MIN_POOL, sc.evaluate_screen(s, panel),
            cadence=f"{s.cadence} screen, monthly replay, quarterly starts",
            notes=["replay over cache/history/ (from 2021-11, today's screener names only: "
                   "no delisted name)"]))
    return out


def live(day: date | None = None) -> dict:
    """The board over the real stores, read-only. A screen that cannot be replayed is listed
    under `skipped` with the error, never a crash."""
    from assist.candidates import frameworks as fw_pkg
    from assist.eval import picks_report

    day = day or date.today()
    ctx = LiveContext(day)
    replays: list[Replay] = []
    skipped: list[dict] = []
    for label, fn in (("dividend_value, garp", _undervalued), ("industry_value", _industry),
                      ("dividend, value, momentum", _screens)):
        try:
            replays += fn(ctx)
        except Exception as e:  # noqa: BLE001 - one screen failing must not stop the board
            skipped.append({"name": label, "reason": f"{type(e).__name__}: {e}"[:200]})
    pending = []
    for f in fw_pkg.registered():
        fn = getattr(f, "replay", None)
        if not callable(fn):
            pending.append(f)
            continue
        try:
            replays.append(fn(ctx))
        except Exception as e:  # noqa: BLE001 - one framework failing must not stop the board
            skipped.append({"name": f.name, "reason": f"{type(e).__name__}: {e}"[:200]})
    syms = {s for r in replays for d in r.picks for s in (*r.picks[d], *r.pools.get(d, ()))}
    data = picks_report.load(syms)
    return build(replays, data, day=day, universe=ctx.universe, frameworks=pending,
                 skipped=skipped, stale=ctx.stale)
