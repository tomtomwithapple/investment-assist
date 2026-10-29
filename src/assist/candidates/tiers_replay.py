"""Replay of the S31 top tier per industry (P50): does Tier A beat its industry's median?

At each quarter end from 2017 with a later one, a **reduced composite** is rebuilt from
idx-method's `factor_series` (`dividend_value.load`) and `cache/history/`, and Tier A is picked
per industry by the live model's own rules (`tiers.gates`, `tiers._pool_pcts`, `tiers._score`,
`tiers.tier_size`, `tiers.assign`; weights, cutoffs and coverage rules from `tiers.CONFIG`):

- Value: normalised PE (mktcap over the lower of TTM NI and the mean of the TTM years known, up
  to three; a non-positive base ranks last), PBV, EV/EBIT, P/CFO. Quality: ROE (`ni_ttm` /
  `equity`), CFO/NI. Growth: `ni_ttm` y/y. Health: net debt / equity. Momentum: `mom_12_1`,
  `near_52w_high` (`factors._signals` on the history bars up to the quarter end). Banks, insurers
  and multifinance (by industry label) use PE, PBV, ROE, NI y/y and momentum: CFO, EBIT and net
  debt do not read a lender, and their prudential fields have no history.
- Fundamentals are the quarters knowable on the date: period end + `screens.LAG_DAYS`, whatever
  the store says (idx-method V3, period end vs filing date, is still open).
- Gates: liquidity (`days_traded_60`, `med_value_60d` from the history), positive TTM NI and
  equity, D/E (`total_debt` / `equity`) under the industry's `DER_CAP`. The quality floor
  (Piotroski, Altman Z, interest cover, bank prudential fields) has no history: not replayed.
- Membership is **today's** S30 industries (`out/industries/IDN.json`), back-filled to every
  quarter: survivorship bias, flagged in every payload until idx-method V2 lands.

**Test.** Per quarter, the equal-weighted mean over industries (at least `min_industries` with a
Tier A) of Tier A's mean 3-month forward return (price plus dividends gone ex, to the next
quarter end) minus the median of the industry's gated names. **Placebo:** the same tiers picked
on composites shuffled within each industry (`placebo.block_shuffle`, seeded), `n_sets` times.
Each quarter gives two observations to `assist.eval.placebo.evaluate`: (True, the real excess),
(False, the mean placebo excess), so the verdict is the harness's (Welch t, return-shuffle
p-value, control rerun). It passes only if that verdict passes **and** the real mean beats the
mean of at least `1 − alpha` of the within-industry shuffle sets (`perm_p`). Fewer than
`min_quarters` scored quarters is an insufficient sample.

Weights are frozen (the live model's). Each pillar ranked alone is reported as a diagnostic and
decides nothing. A failing or insufficient verdict leaves the tiers context only; nothing reads
the tiers either way until a later decision lets a passing Tier A feed S20.
"""

from __future__ import annotations

import copy
import json
import math
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any

from assist.candidates import tiers
from assist.candidates.dividend_value import _bar_at
from assist.candidates.screens import LAG_DAYS
from assist.eval.placebo import ALPHA, SEED, block_shuffle, evaluate
from assist.sources.idxmethod_series import Bar, Fundamentals, multiples, quarter_ends

__all__ = ["CONFIG", "FILE", "FLAGS", "blocked", "evaluate_panel", "fingerprint",
           "journal_record", "known", "load", "members_from", "metrics_at", "replay_panel", "run",
           "run_live", "shuffle_panel", "signals_from_history", "tier_a", "write"]

SCHEMA_VERSION = 1
FILE = Path("industries") / "IDN.replay.json"
DISCLAIMER = "Heuristic, not investment advice."
SOURCE = ("idx-method factor_series (stockbiter.db), cache/history, "
          "out/industries/IDN.json (membership)")

REPLAY = {
    "version": 1,
    "start": "2017-01-01",
    "lag_days": LAG_DAYS,
    "bar_window_days": 10,  # a name with no bar this close before the quarter end sits it out
    "min_industries": 3,  # industries with a Tier A a quarter needs before it is scored
    "min_quarters": 10,  # scored quarters for a verdict (placebo.MIN_N)
    "n_sets": 200,  # within-industry shuffle sets (the placebo)
    "seed": SEED,
}

# The live model with the reduced metric sets: weights, gates, coverage and tier rules are
# tiers.CONFIG's, so the replay picks by the same rules and changes with them.
CONFIG: dict[str, Any] = {
    **copy.deepcopy(tiers.CONFIG),
    "metrics": {
        "standard": {
            "value": ["pe_norm", "pbv", "ev_ebit", "p_cfo"],
            "quality": ["roe", "cfo_ni"],
            "growth": ["ni_yoy"],
            "health": ["nd_eq"],
            "momentum": ["mom_12_1", "near_52w_high"],
        },
        "financial": {
            "value": ["pe_norm", "pbv"],
            "quality": ["roe"],
            "growth": ["ni_yoy"],
            "health": [],
            "momentum": ["mom_12_1", "near_52w_high"],
        },
    },
    "lower_is_better": ["pe_norm", "pbv", "ev_ebit", "p_cfo", "nd_eq"],
    "replay": REPLAY,
}

FLAGS = (
    "survivorship: today's S30 industry membership back-filled to every quarter "
    "(until idx-method V2)",
    f"fundamentals lagged {LAG_DAYS} days from period end (idx-method V3 open)",
    "reduced composite: no revenue, EBITDA, margins, stability or interest cover before "
    "idx-method V1",
    "quality floor (Piotroski, Altman Z, interest cover, bank prudential) not replayed",
)

Signals = Callable[[str, date], Mapping[str, Any] | None]


def fingerprint(config: Mapping[str, Any] = CONFIG) -> str:
    return tiers.fingerprint(config)


# ---------------- point-in-time inputs ----------------


def known(quarters: Sequence[Fundamentals], d: date,
          lag_days: int = LAG_DAYS) -> list[Fundamentals]:
    """The quarters knowable on `d`: period end + `lag_days` <= d (and the store's own
    `available`, if later), oldest first."""
    lag = timedelta(days=lag_days)
    return [f for f in quarters if max(f.available, f.period + lag) <= d]


def _f(v: Any) -> float | None:
    return None if v is None or not math.isfinite(v) else float(v)


def _ratio(num: float | None, den: float | None) -> float | None:
    return None if num is None or den is None or den <= 0 else num / den


def metrics_at(bar: Bar, kn: Sequence[Fundamentals],
               sig: Mapping[str, Any] | None) -> dict[str, float | None]:
    """The reduced metrics on a bar from the quarters knowable then (`known`) and the history
    signals; plus `ni_ttm`, `equity` and `der` for the gates."""
    sig = sig or {}
    f = kn[-1] if kn else None
    cap = _f(bar.mktcap)
    m = multiples(cap, f)
    ni = _f(f.ni_ttm) if f else None
    eq = _f(f.equity) if f else None
    by_period = {q.period: q.ni_ttm for q in kn}
    years: list[float] = []
    if f is not None:
        for k in range(3):
            v = by_period.get(f.period.replace(year=f.period.year - k))
            if v is None:
                break
            years.append(float(v))
    pe_norm = None
    if years and cap is not None:
        base = min(years[0], fmean(years))
        pe_norm = cap / base if base > 0 else math.inf
    ni_yoy = None
    if len(years) >= 2 and years[1] > 0:
        ni_yoy = (years[0] / years[1] - 1) * 100
    cfo = _f(f.cfo_ttm) if f else None
    nd = _f(f.net_debt) if f else None
    td = _f(f.total_debt) if f else None
    return {
        "ni_ttm": ni,
        "equity": eq,
        "der": td / eq if td is not None and eq else None,
        "pe_norm": pe_norm,
        "pbv": m["pbv"],
        "ev_ebit": m["ev_ebit"],
        "p_cfo": m["p_cfo"],
        "roe": ni / eq * 100 if ni is not None and eq and eq > 0 else None,
        "cfo_ni": cfo / ni if cfo is not None and ni and ni > 0 else None,
        "ni_yoy": ni_yoy,
        "nd_eq": nd / eq if nd is not None and eq and eq > 0 else None,
        "mom_12_1": _f(sig.get("mom_12_1")),
        "near_52w_high": _f(sig.get("near_52w_high")),
    }


def signals_from_history(history: Mapping[str, list[dict]]) -> Signals:
    """sym, date → `factors._signals` at the last calendar bar on or before the date (liquidity
    and momentum from bars up to then only); None for a dormant, short or gappy name."""
    from bisect import bisect_right

    from assist.candidates.factors import _signals, align

    dates, data = align(dict(history))
    cache: dict[tuple[str, int], Mapping | None] = {}

    def at(sym: str, d: date) -> Mapping[str, Any] | None:
        i = bisect_right(dates, d) - 1
        if sym not in data or i < 0:
            return None
        key = (sym, i)
        if key not in cache:
            cache[key] = _signals(data[sym], i)
        return cache[key]

    return at


# ---------------- the panel ----------------


def _mset(label: str, config: Mapping[str, Any]) -> str:
    return "financial" if label in config["financial_labels"] else "standard"


def replay_panel(
    bars: Mapping[str, Sequence[Bar]],
    quarters: Mapping[str, Sequence[Fundamentals]],
    members: Mapping[str, Mapping[str, Any]],
    signals: Signals | None = None,
    dividends: Mapping[str, Sequence[Mapping]] | None = None,
    *,
    as_of: date | None = None,
    config: Mapping[str, Any] = CONFIG,
) -> list[dict]:
    """→ [{"date", "industries": {id: {"n_gated", "recs": [{symbol, mktcap, composite,
    pillars, fwd}]}}}] per quarter end with a later one (both on or before `as_of`). `members`
    maps a symbol to today's {"industry", "label", "sector"}; only gated names are kept, with
    `fwd` None when no bar follows."""
    rp = config["replay"]
    signals = signals or (lambda _s, _d: None)
    dividends = dividends or {}
    syms = sorted(s for s in members if bars.get(s))
    if not syms:
        return []
    last = max(bars[s][-1].date for s in syms)
    if as_of is not None:
        last = min(last, as_of)
    qes = quarter_ends(date.fromisoformat(rp["start"]), last)
    dates = {s: [b.date for b in bars[s]] for s in syms}
    window = timedelta(days=int(rp["bar_window_days"]))
    panel = []
    for q, q1 in zip(qes, qes[1:], strict=False):
        metrics: dict[str, dict] = {}
        fwd: dict[str, float | None] = {}
        caps: dict[str, float] = {}
        for sym in syms:
            mem = members[sym]
            bar = _bar_at(bars[sym], q, dates[sym])
            if bar is None or bar.date < q - window:
                continue
            sig = signals(sym, q)
            m = metrics_at(bar, known(quarters.get(sym, ()), q, int(rp["lag_days"])), sig)
            g = tiers.gates({"values": {"der": m["der"]}}, sig,
                            str(mem.get("label") or ""), m, config)
            if not g["pass"]:
                continue
            metrics[sym], caps[sym] = m, bar.mktcap or 0.0
            end = _bar_at(bars[sym], q1, dates[sym])
            if end is None or end.date <= q:
                fwd[sym] = None
                continue
            paid = sum(r["value"] for r in dividends.get(sym, ()) if r.get("value") is not None
                       and bar.date < date.fromisoformat(r["ex"]) <= end.date)
            fwd[sym] = (end.price + paid) / bar.price - 1
        by_ind: dict[str, list[str]] = {}
        by_sec: dict[str, list[str]] = {}
        for sym in metrics:
            by_ind.setdefault(str(members[sym]["industry"]), []).append(sym)
            by_sec.setdefault(str(members[sym].get("sector") or ""), []).append(sym)
        sector_pcts: dict[str, dict] = {}
        industries = {}
        for ind, gated in sorted(by_ind.items()):
            if len(gated) >= config["min_peer_group"]:
                pcts = tiers._pool_pcts(gated, metrics, config)
            else:
                sec = str(members[gated[0]].get("sector") or "")
                if sec not in sector_pcts:
                    sector_pcts[sec] = tiers._pool_pcts(by_sec[sec], metrics, config)
                pcts = sector_pcts[sec]
            recs = []
            for sym in sorted(gated):
                label = str(members[sym].get("label") or "")
                pillars, comp = tiers._score(sym, _mset(label, config), pcts, config)
                recs.append({"symbol": sym, "mktcap": caps[sym], "composite": comp,
                             "pillars": {p: v["score"] for p, v in pillars.items()},
                             "fwd": fwd[sym]})
            industries[ind] = {"n_gated": len(gated), "recs": recs}
        panel.append({"date": q, "industries": industries})
    return panel


# ---------------- picks and the statistic ----------------


def _score_of(r: Mapping, key: str) -> float | None:
    return r["composite"] if key == "composite" else (r.get("pillars") or {}).get(key)


def tier_a(recs: Sequence[Mapping], n_gated: int, config: Mapping[str, Any] = CONFIG,
           key: str = "composite") -> list[Mapping]:
    """Tier A by `tiers.assign` on `key` (the composite, or one pillar for the diagnostics)."""
    scored = [{**r, "composite": _score_of(r, key)} for r in recs
              if _score_of(r, key) is not None]
    scored.sort(key=tiers.rank_key)
    picks = tiers.assign([r["composite"] for r in scored], tiers.tier_size(n_gated, config),
                         config)
    return [r for r, p in zip(scored, picks, strict=True) if p == "A"]


def _excess(industries: Mapping[str, Mapping], config: Mapping[str, Any],
            key: str = "composite") -> tuple[float, int, int] | None:
    """(mean over industries of Tier A minus industry median forward return, industries, picks);
    None when fewer than `min_industries` industries have a Tier A with a return."""
    rows, n_picks = [], 0
    for ind in sorted(industries):
        block = industries[ind]
        fwds = [r["fwd"] for r in block["recs"] if r["fwd"] is not None]
        picks = [r["fwd"] for r in tier_a(block["recs"], block["n_gated"], config, key)
                 if r["fwd"] is not None]
        if not picks or not fwds:
            continue
        rows.append(fmean(picks) - statistics.median(fwds))
        n_picks += len(picks)
    if len(rows) < int(config["replay"]["min_industries"]):
        return None
    return fmean(rows), len(rows), n_picks


def _shuffled(industries: Mapping[str, Mapping], rng: random.Random) -> dict[str, dict]:
    """The composites (and pillars with them) permuted among each industry's scored names."""
    out = {}
    for ind in sorted(industries):
        block = industries[ind]
        recs = [dict(r) for r in block["recs"]]
        idx = [i for i, r in enumerate(recs) if r["composite"] is not None]
        perm = block_shuffle([(recs[i]["composite"], recs[i]["pillars"]) for i in idx], rng)
        for i, (c, p) in zip(idx, perm, strict=True):
            recs[i]["composite"], recs[i]["pillars"] = c, p
        out[ind] = {"n_gated": block["n_gated"], "recs": recs}
    return out


def shuffle_panel(panel: Sequence[Mapping], seed: Any = SEED) -> list[dict]:
    """The panel with composites shuffled within each industry once (a rule with no skill)."""
    rng = random.Random(f"{seed}:shuffle-panel")
    return [{"date": q["date"], "industries": _shuffled(q["industries"], rng)} for q in panel]


def _t(xs: Sequence[float]) -> float | None:
    if len(xs) < 3:
        return None
    sd = statistics.stdev(xs)
    return fmean(xs) / (sd / len(xs) ** 0.5) if sd > 0 else None


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None or not math.isfinite(x) else round(x, nd)


def evaluate_panel(panel: Sequence[Mapping], config: Mapping[str, Any] = CONFIG,
                   **kw) -> dict:
    """The verdict on a panel (see the module docstring); `kw` goes to `placebo.evaluate`."""
    rp = config["replay"]
    seed = rp["seed"]
    alpha = kw.get("alpha", ALPHA)
    real: list[tuple[date, float, int, int]] = []
    for q in panel:
        e = _excess(q["industries"], config)
        if e is not None:
            real.append((q["date"], *e))
    scored = {d for d, *_ in real}
    by_date = {q["date"]: q["industries"] for q in panel if q["date"] in scored}

    n_sets = int(rp["n_sets"])
    placebo: dict[date, list[float]] = {d: [] for d in scored}
    set_means: list[float] = []
    for s in range(n_sets):
        rng = random.Random(f"{seed}:tiers-replay:{s}")
        vals = []
        for d in sorted(by_date):
            e = _excess(_shuffled(by_date[d], rng), config)
            v = e[0] if e is not None else 0.0  # same composites, same Tier A count
            placebo[d].append(v)
            vals.append(v)
        if vals:
            set_means.append(fmean(vals))

    feats: list[bool] = []
    rets: list[float] = []
    per_quarter = []
    for d, x, n_ind, n_picks in real:
        pl = fmean(placebo[d]) if placebo[d] else 0.0
        feats += [True, False]
        rets += [x, pl]
        per_quarter.append({"quarter": d.isoformat(), "excess": _r(x), "placebo": _r(pl),
                            "industries": n_ind, "picks": n_picks})
    kw.setdefault("min_n", int(rp["min_quarters"]))
    kw.setdefault("seed", seed)
    v = evaluate(lambda f, _r: list(f), feats, rets, **kw)
    mean_real = fmean(x for _, x, *_ in real) if real else None
    perm_p = ((1 + sum(m >= mean_real for m in set_means)) / (1 + len(set_means))
              if real and set_means else None)

    n = len(real)
    if n < int(rp["min_quarters"]):
        status, reason = "insufficient", (
            f"insufficient sample: {n} quarter(s) with a Tier A in at least "
            f"{rp['min_industries']} industries (needs {rp['min_quarters']})")
    elif not v.passed:
        status, reason = "failed", v.reason
    elif perm_p is None or perm_p > alpha:
        status, reason = "failed", (f"Tier A does not beat within-industry shuffles "
                                    f"(perm p {perm_p:.3f} > {alpha})")
    else:
        status, reason = "passed", f"{v.reason}; perm p {perm_p:.3f}"

    pillars = {}
    for p in tiers.PILLARS:
        xs = [e[0] for q in panel if (e := _excess(q["industries"], config, p)) is not None]
        pillars[p] = {"quarters": len(xs), "mean_excess": _r(fmean(xs)) if xs else None,
                      "t": _r(_t(xs), 2)}
    return {
        "status": status,
        "passed": status == "passed",
        "verdict": reason,
        "quarters": n,
        "first_quarter": real[0][0].isoformat() if real else None,
        "last_quarter": real[-1][0].isoformat() if real else None,
        "mean_excess": _r(mean_real),
        "mean_placebo": _r(fmean(rets[1::2])) if real else None,
        "t": _r(v.rule.t, 2),
        "p": _r(v.p_value),
        "perm_p": _r(perm_p),
        "control_t": _r(v.control_t, 2),
        "industries_mean": _r(fmean(r[2] for r in real), 2) if real else None,
        "picks": sum(r[3] for r in real),
        "pillars": pillars,
        "per_quarter": per_quarter,
        "evaluate": {k: val for k, val in v.to_dict().items() if k != "control_ts"},
    }


# ---------------- payload ----------------


def run(
    bars: Mapping[str, Sequence[Bar]],
    quarters: Mapping[str, Sequence[Fundamentals]],
    members: Mapping[str, Mapping[str, Any]],
    signals: Signals | None = None,
    dividends: Mapping[str, Sequence[Mapping]] | None = None,
    *,
    day: date,
    as_of: date | None = None,
    stale: Sequence[str] = (),
    config: Mapping[str, Any] = CONFIG,
    **kw,
) -> dict:
    """The replay payload (`out/industries/IDN.replay.json`, the journal and the brief)."""
    panel = replay_panel(bars, quarters, members, signals, dividends, as_of=as_of,
                         config=config)
    res = evaluate_panel(panel, config, **kw)
    return _payload(day, res, members=len(members), stale=stale, config=config,
                    as_of=panel[-1]["date"].isoformat() if panel else None)


def _payload(day: date, res: Mapping, *, members: int, stale: Sequence[str],
             config: Mapping[str, Any], as_of: str | None, blocked: str | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "market": "IDN",
        "as_of": as_of,
        "built": day.isoformat(),
        "source": SOURCE,
        **res,
        "blocked": blocked,
        "context_only": not res.get("passed"),
        "members": members,
        "flags": list(FLAGS),
        "fingerprint": fingerprint(config),
        "tier_fingerprint": tiers.fingerprint(),
        "weights": dict(config["weights"]),
        "config": json.loads(json.dumps(config)),
        "stale_inputs": sorted(set(stale)),
        "disclaimer": DISCLAIMER,
    }


def blocked(day: date, reason: str, stale: Sequence[str] = (),
            config: Mapping[str, Any] = CONFIG) -> dict:
    """The payload when an input is missing: no verdict, the tiers stay context only."""
    res = {"status": "blocked", "passed": False, "verdict": f"blocked: {reason}",
           "quarters": 0, "first_quarter": None, "last_quarter": None, "mean_excess": None,
           "mean_placebo": None, "t": None, "p": None, "perm_p": None, "control_t": None,
           "industries_mean": None, "picks": 0, "pillars": {}, "per_quarter": [],
           "evaluate": None}
    return _payload(day, res, members=0, stale=[*stale, reason], config=config, as_of=None,
                    blocked=reason)


def members_from(peers_payload: Mapping) -> dict[str, dict]:
    """sym → {"industry", "label", "sector"} from an S30 payload (today's membership)."""
    out = {}
    for ind in peers_payload.get("industries") or []:
        for s in ind.get("stocks") or []:
            out[s["symbol"]] = {"industry": str(ind["id"]), "label": ind.get("label"),
                                "sector": s.get("sector") or ind.get("sector")}
    return out


def run_live(day: date, out_dir: Path) -> dict:
    """The replay over the real stores (read-only): membership from `out/industries/IDN.json`,
    bars, quarters and dividends from `factor_series`, signals from `cache/history/`. A missing
    input gives a `blocked` payload, never an exception."""
    from assist.candidates.dividend_value import load as load_series
    from assist.sources.base import SourceUnavailable
    from assist.sources.idxmethod_stocks import IdxMethodStocks

    path = Path(out_dir) / "industries" / "IDN.json"
    try:
        members = members_from(json.loads(path.read_text()))
    except (OSError, ValueError) as e:
        return blocked(day, f"no S30 membership ({path.name}: {type(e).__name__})")
    if not members:
        return blocked(day, "no S30 membership (no industries in IDN.json)")
    data = load_series()
    if not data.bars:
        return blocked(day, "factor_series unavailable", data.stale)
    stale = list(data.stale)
    try:
        stocks = IdxMethodStocks.from_config()
        history = stocks.history(members)
        signals = signals_from_history(history)
        if len(history) < len(members):
            stale.append(f"cache/history holds {len(history)} of {len(members)} member names: "
                         "the rest fail the liquidity gate")
    except SourceUnavailable as e:
        signals = None
        stale.append(e.stale_input)
    return run(data.bars, data.quarters, members, signals, data.dividends, day=day,
               stale=stale)


def write(payload: Mapping, out_dir: Path) -> Path:
    """`out/industries/IDN.replay.json`, rewritten only when its bytes change."""
    path = Path(out_dir) / FILE
    text = json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text() == text:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text)
    tmp.replace(path)
    return path


def load(out_dir: Path) -> dict | None:
    """The last replay payload under `out_dir`, or None (missing or unreadable). For the brief
    and the `/industries` page."""
    try:
        p = json.loads((Path(out_dir) / FILE).read_text())
    except (OSError, ValueError):
        return None
    return p if isinstance(p, dict) and "status" in p else None


def journal_record(payload: Mapping) -> tuple[dict, dict]:
    """(inputs, outputs) of the `tier_replay` journal record."""
    inputs = {"as_of": payload.get("as_of"), "fingerprint": payload.get("fingerprint"),
              "tier_fingerprint": payload.get("tier_fingerprint"),
              "config": payload.get("config"), "flags": payload.get("flags"),
              "members": payload.get("members")}
    keys = ("status", "passed", "verdict", "quarters", "first_quarter", "last_quarter",
            "mean_excess", "mean_placebo", "t", "p", "perm_p", "control_t", "industries_mean",
            "picks", "pillars", "blocked", "stale_inputs")
    outputs = {k: payload.get(k) for k in keys} | {"moves_stance": False,
                                                    "context_only": payload.get("context_only")}
    return inputs, outputs
