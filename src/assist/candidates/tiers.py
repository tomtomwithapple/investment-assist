"""Top tier per industry (S31): a 0-100 composite for each IDN name within its peers, and the
best few names of each industry marked Tier A or B.

Input is the S30 peers payload (`candidates.peers.build`) plus `extras`, sym → a row of the
inputs Stockbit's `/comparison` lacks: `days_traded_60`, `med_value_60d`, `mom_12_1`,
`near_52w_high` (`factors.derive` over idx-method's `cache/history/`), the screener's
`piotroski`, `altman_z`, `interest_cov`, `roe` and bank fields `car`, `npl_gross`/`npf_gross`,
`npl_cov`, `ldr` (`data/factors.json`), and `cfo_ttm` and `ni_ttm_years` (TTM net income now,
one and two years back) from `factor_series` when the store has it. The screener writes 0.0 for
a field it lacks, so 0 reads as missing for `car`, `npl_*`, `ldr`, `cfo_ttm` and `piotroski`.

- **Gates** (all of them checked; every failure is listed, a gate adds nothing to the score):
  liquidity (`days_traded_60` >= 30, `med_value_60d` >= IDR 1bn; no derived row is a fail,
  since `derive` leaves dormant names out), positive TTM net income and equity, the quality
  floor with `screens.QUALITY_FLOOR` (banks: `screens.BANK_FLOOR`) where the value is present,
  and D/E under the industry's `DER_CAP`. A floor field that is absent is listed in
  `missing` and does not fail the name; insurers and multifinance have no prudential fields in
  any store, so only Piotroski applies to them (Altman Z and interest cover do not read a
  balance-sheet lender or insurer).
- **Peer group.** The S30 industry; when fewer than `min_peer_group` of its names pass the gates,
  percentiles are taken over the gated names of the sector (each name's own `sector`). Tiers are
  still picked per industry.
- **Metrics.** A metric is the name's percentile among the gated peers with a value:
  (rank − 0.5) / n × 100, ties at the mid-rank, flipped where lower is better. Dropped for the
  group when fewer than `min_peers` have a value. Normalised PE = mktcap / min(TTM NI, mean of
  the TTM years available, up to three); a non-positive normalised base ranks last on PE, so a
  one-off gain cannot buy the top value rank. Without any TTM history Stockbit's PE stands in.
  EV/EBITDA, P/S and PBV at or below 0 are no value (negative EBITDA and net cash look alike).
  Growth and stability come from the S30 quarterly `financials` (one quarter each): revenue and
  NI TTM y/y need 8 quarters, the 2-year CAGRs 12, the stabilities (sample stdev of the
  quarterly operating margin or annualised ROE) at least `stability_min_quarters`.
  LDR scores lower-is-better (liquidity first; the floor caps it at 110 anyway).
- **Pillars** are the mean of their metric percentiles and need at least half of their metrics.
  Banks, insurers and multifinance (by industry label, or any name with a CAR) use the
  `financial` metric set. The composite is the weighted mean of the pillars present (weights
  rescaled), and needs `min_pillars` with Value and Quality among them.
- **Tiers.** k = max(1, floor(20% of the gated names in the industry)), at most 3 (5 when 40 or
  more pass). Tier A: the top k by composite that score >= 60. Tier B: the next up to k that
  score >= 50 (so an industry with no Tier A can still have a Tier B). Ties on market cap, then
  symbol.

Every gate, weight and cutoff is in `CONFIG`; `fingerprint()` is the sha256 of its canonical
JSON. Context only: nothing else reads the tiers until the S31 replay passes its placebo.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from assist.candidates.screens import BANK_FLOOR, QUALITY_FLOOR

__all__ = ["CONFIG", "DER_CAP", "DER_CAP_DEFAULT", "attach", "der_cap", "fingerprint",
           "gather_extras", "metric_values", "percentiles", "tier_size"]

# D/E cap per industry label (moved here from views/industries.py: it now decides which names get
# a score). The common cap is 1.0; the industries named here allow more (capital-heavy, or
# leverage is the business) or require less (asset-light). None: no D/E gate, because the
# industry's leverage is not read from D/E (deposits and policy reserves).
DER_CAP_DEFAULT = 1.0
DER_CAP: dict[str, float | None] = {
    "Bank": None,
    "Asuransi": None,
    "Jasa Pembiayaan": 5.0,  # multifinance gearing (OJK allows up to 10x)
    "Telekomunikasi": 1.5,
    "Utilitas": 1.5,
    "Infrastruktur Transportasi": 1.5,
    "Perusahaan Holding Multi Sektor": 1.5,  # consolidates finance arms (ASII)
    "Perangkat Lunak & Jasa TI": 0.5,
    "Media & Hiburan": 0.5,
    "Rokok": 0.5,
}

PILLARS = ("value", "quality", "growth", "health", "momentum")

CONFIG: dict[str, Any] = {
    "version": 1,
    "gates": {
        "min_days_traded_60": 30,
        "min_med_value_60d": 1e9,  # IDR/day
        "quality_floor": dict(QUALITY_FLOOR),
        "bank_floor": dict(BANK_FLOOR),
        "der_cap": DER_CAP,
        "der_cap_default": DER_CAP_DEFAULT,
    },
    "financial_labels": ["Bank", "Asuransi", "Jasa Pembiayaan"],
    "min_peer_group": 8,  # gated names an industry needs before it is its own peer group
    "weights": {"value": 30, "quality": 25, "growth": 15, "health": 15, "momentum": 15},
    "metrics": {
        "standard": {
            "value": ["pe_norm", "pbv", "ev_ebitda", "ps"],
            "quality": ["roe", "roic", "opm", "opm_stability", "cfo_ni"],
            "growth": ["revenue_yoy", "ni_yoy", "revenue_cagr2"],
            "health": ["der", "int_cover", "altman_z", "current"],
            "momentum": ["mom_12_1", "near_52w_high"],
        },
        "financial": {
            "value": ["pe_norm", "pbv"],
            "quality": ["roe", "roa", "roe_stability"],
            "growth": ["ni_yoy", "equity_cagr2"],
            "health": ["car", "npl", "npl_cov", "ldr"],
            "momentum": ["mom_12_1", "near_52w_high"],
        },
    },
    "lower_is_better": ["pe_norm", "pbv", "ev_ebitda", "ps", "opm_stability", "roe_stability",
                        "der", "npl", "ldr"],
    "coverage": {"min_peers": 5, "min_pillar_share": 0.5, "min_pillars": 3,
                 "required": ["value", "quality"]},
    "stability_min_quarters": 8,
    "tiers": {"share": 0.2, "min": 1, "max": 3, "max_large": 5, "large_n": 40,
              "a_min": 60.0, "b_min": 50.0},
}


def der_cap(label: Any, config: Mapping[str, Any] = CONFIG) -> float | None:
    """The D/E cap of an industry by its label: `DER_CAP`, else `DER_CAP_DEFAULT`."""
    g = config["gates"]
    return g["der_cap"].get(str(label), g["der_cap_default"])


def fingerprint(config: Mapping[str, Any] = CONFIG) -> str:
    text = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


# ---------------- metric values ----------------


def _f(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _pos(v: Any) -> float | None:
    """A value where 0 or less means the source has none."""
    x = _f(v)
    return x if x is not None and x > 0 else None


def _ttm(xs: Sequence[float | None], end: int) -> float | None:
    if end < 3 or end >= len(xs):
        return None
    win = xs[end - 3:end + 1]
    return None if any(v is None for v in win) else float(sum(win))  # type: ignore[arg-type]


def _newest(xs: Sequence[float | None]) -> int | None:
    return next((i for i in range(len(xs) - 1, -1, -1) if xs[i] is not None), None)


def _growth(now: float | None, base: float | None, years: float = 1.0) -> float | None:
    if now is None or base is None or base <= 0:
        return None
    if years == 1.0:
        return (now / base - 1) * 100
    return ((now / base) ** (1 / years) - 1) * 100 if now > 0 else None


def _stdev(xs: Sequence[float], n_min: int) -> float | None:
    return statistics.stdev(xs) if len(xs) >= max(2, n_min) else None


def _ni_years(fin: Mapping[str, Sequence], extra: Mapping) -> list[float]:
    """TTM net income now, a year back, two years back (as many as known, newest first)."""
    given = extra.get("ni_ttm_years")
    if isinstance(given, Sequence) and given and _f(given[0]) is not None:
        out = []
        for v in given[:3]:
            if _f(v) is None:
                break
            out.append(float(v))
        return out
    ni = list(fin.get("net_income") or [])
    e = _newest(ni)
    out = []
    if e is not None:
        for k in range(3):
            t = _ttm(ni, e - 4 * k)
            if t is None:
                break
            out.append(t)
    return out


def metric_values(stock: Mapping, extra: Mapping | None,
                  config: Mapping[str, Any] = CONFIG) -> dict[str, float | None]:
    """Every metric of both sets, plus `ni_ttm` and `equity` for the gates. `pe_norm` is
    `math.inf` when the normalised earnings base is not positive (it ranks last)."""
    extra = extra or {}
    v = stock.get("values") or {}
    fin = stock.get("financials") or {}
    cap = _pos(stock.get("mktcap"))
    n_stab = int(config["stability_min_quarters"])

    years = _ni_years(fin, extra)
    pe = _f(v.get("pe"))
    if years:
        ni_ttm: float | None = years[0]
    elif cap is not None and pe:
        ni_ttm = cap / pe
    else:
        ni_ttm = None
    if years and cap is not None:
        base = min(years[0], statistics.fmean(years))
        pe_norm: float | None = cap / base if base > 0 else math.inf
    else:
        pe_norm = pe if pe is not None and pe > 0 else (math.inf if pe is not None else None)

    eq = list(fin.get("equity") or [])
    ie = _newest(eq)
    pbv = _f(v.get("pbv"))
    if ie is not None:
        equity: float | None = eq[ie]
    elif cap is not None and pbv:
        equity = cap / pbv
    else:
        equity = None

    rev = list(fin.get("revenue") or [])
    op = list(fin.get("operating_profit") or [])
    ni = list(fin.get("net_income") or [])
    er = _newest(rev)
    revenue_yoy = revenue_cagr2 = None
    if er is not None:
        revenue_yoy = _growth(_ttm(rev, er), _ttm(rev, er - 4))
        revenue_cagr2 = _growth(_ttm(rev, er), _ttm(rev, er - 8), 2.0)
    margins = [o / r * 100 for r, o in zip(rev, op, strict=False)
               if r is not None and o is not None and r > 0]
    roes = [n * 4 / q * 100 for n, q in zip(ni, eq, strict=False)
            if n is not None and q is not None and q > 0]
    equity_cagr2 = None
    if ie is not None and ie >= 8:
        equity_cagr2 = _growth(eq[ie], eq[ie - 8], 2.0)

    cfo = _f(extra.get("cfo_ttm")) or None  # the screener's 0.0 is no value
    npl = _pos(extra.get("npl_gross")) or _pos(extra.get("npf_gross"))
    der = _f(v.get("der"))
    roe = _f(v.get("roe"))
    if roe is None:
        roe = _f(extra.get("roe"))
    altman = _f(v.get("altman_z"))
    if altman is None:
        altman = _f(extra.get("altman_z"))
    return {
        "ni_ttm": ni_ttm,
        "equity": equity,
        "pe_norm": pe_norm,
        "pbv": pbv if pbv is not None and pbv > 0 else None,
        "ev_ebitda": _pos(v.get("ev_ebitda")),
        "ps": _pos(v.get("ps")),
        "roe": roe,
        "roic": _f(v.get("roic")),
        "roa": _f(v.get("roa")),
        "opm": _f(v.get("opm")),
        "opm_stability": _stdev(margins, n_stab),
        "roe_stability": _stdev(roes, n_stab),
        "cfo_ni": cfo / ni_ttm if cfo is not None and ni_ttm and ni_ttm > 0 else None,
        "revenue_yoy": revenue_yoy,
        "ni_yoy": _growth(years[0], years[1]) if len(years) >= 2 else None,
        "revenue_cagr2": revenue_cagr2,
        "equity_cagr2": equity_cagr2,
        "der": der if der is not None and der >= 0 else None,
        "int_cover": _pos(v.get("int_cover")) or _pos(extra.get("interest_cov")),
        "altman_z": altman,
        "current": _pos(v.get("current")),
        "car": _pos(extra.get("car")),
        "npl": npl,
        "npl_cov": _pos(extra.get("npl_cov")),
        "ldr": _pos(extra.get("ldr")),
        "mom_12_1": _f(extra.get("mom_12_1")),
        "near_52w_high": _f(extra.get("near_52w_high")),
    }


# ---------------- gates ----------------


def _is_bank(label: str, m: Mapping, config: Mapping) -> bool:
    return label == "Bank" or m.get("car") is not None


def _metric_set(label: str, m: Mapping, config: Mapping) -> str:
    fin = label in config["financial_labels"] or _is_bank(label, m, config)
    return "financial" if fin else "standard"


def gates(stock: Mapping, extra: Mapping | None, label: str, m: Mapping,
          config: Mapping[str, Any] = CONFIG) -> dict:
    """{"pass", "fail": [reasons], "missing": [floor inputs not available]}."""
    extra = extra or {}
    g = config["gates"]
    fail: list[str] = []
    missing: list[str] = []
    dt, mv = _f(extra.get("days_traded_60")), _f(extra.get("med_value_60d"))
    if dt is None or mv is None:
        fail.append("no liquidity data")
    else:
        if dt < g["min_days_traded_60"]:
            fail.append("trades too rarely")
        if mv < g["min_med_value_60d"]:
            fail.append("liquidity")
    ni, eq = m.get("ni_ttm"), m.get("equity")
    if ni is None:
        fail.append("no TTM net income")
    elif ni <= 0:
        fail.append("TTM loss")
    if eq is None:
        fail.append("no equity")
    elif eq <= 0:
        fail.append("negative equity")

    def floor(key: str, value: float | None, ok: bool, reason: str) -> None:
        if value is None:
            missing.append(key)
        elif not ok:
            fail.append(reason)

    piotroski = _pos(extra.get("piotroski"))
    if _is_bank(label, m, config):
        b = g["bank_floor"]
        car, npl, cov, ldr, roe = (m.get(k) for k in ("car", "npl", "npl_cov", "ldr", "roe"))
        floor("car", car, car is not None and car >= b["min_car"], "CAR")
        floor("npl", npl, npl is not None and npl <= b["max_npl_gross"], "NPL")
        if npl is not None:
            floor("npl_cov", cov, cov is not None and cov >= b["min_npl_coverage"],
                  "NPL coverage")
        floor("ldr", ldr, ldr is not None and ldr <= b["max_ldr"], "LDR")
        floor("roe", roe, roe is not None and roe >= b["min_roe"], "bank ROE")
    else:
        q = g["quality_floor"]
        floor("piotroski", piotroski, piotroski is not None and piotroski >= q["min_piotroski"],
              "F-score")
        if label not in config["financial_labels"]:
            z = m.get("altman_z")
            floor("altman_z", z, z is not None and z >= q["min_altman_z"], "Altman Z")
            ic, der = m.get("int_cover"), m.get("der")
            if der is not None and der > 0.05:  # as screens: Stockbit's 0 means no interest
                floor("int_cover", ic, ic is not None and ic >= q["min_interest_cov"],
                      "interest cover")

    cap = der_cap(label, config)
    if cap is not None:
        der = _f((stock.get("values") or {}).get("der"))
        if der is None:
            missing.append("der")
        elif der < 0 or der >= cap:
            fail.append("D/E above cap" if der >= cap else "D/E below 0")
    return {"pass": not fail, "fail": fail, "missing": missing}


# ---------------- ranks ----------------


def percentiles(values: Mapping[str, float], lower_is_better: bool = False) -> dict[str, float]:
    """sym → (rank − 0.5) / n × 100, ties at the mid-rank; flipped when lower is better."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        mid = (i + j) / 2 + 1  # 1-based mid-rank
        pct = (mid - 0.5) / n * 100
        for k in range(i, j + 1):
            out[items[k][0]] = 100 - pct if lower_is_better else pct
        i = j + 1
    return out


def tier_size(n_gated: int, config: Mapping[str, Any] = CONFIG) -> int:
    """How many names Tier A (and again Tier B) may hold for `n_gated` names passing the gates."""
    t = config["tiers"]
    if n_gated <= 0:
        return 0
    cap = t["max_large"] if n_gated >= t["large_n"] else t["max"]
    return min(cap, max(t["min"], math.floor(n_gated * t["share"])))


def _pool_pcts(pool: Sequence[str], metrics: Mapping[str, Mapping[str, Any]],
               config: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """metric → sym → percentile over `pool`; a metric with fewer than `min_peers` values is
    left out (dropped for the group)."""
    keys = sorted({k for s in config["metrics"].values() for ks in s.values() for k in ks})
    lower = set(config["lower_is_better"])
    n_min = int(config["coverage"]["min_peers"])
    out = {}
    for k in keys:
        vals = {s: metrics[s][k] for s in pool if metrics[s].get(k) is not None}
        if len(vals) >= n_min:
            out[k] = percentiles(vals, k in lower)
    return out


def _score(sym: str, mset: str, pcts: Mapping[str, Mapping[str, float]],
           config: Mapping[str, Any]) -> tuple[dict, float | None]:
    cov = config["coverage"]
    pillars, present = {}, {}
    for p in PILLARS:
        ks = config["metrics"][mset][p]
        got = {k: round(pcts[k][sym], 2) for k in ks if k in pcts and sym in pcts[k]}
        ok = bool(got) and len(got) >= cov["min_pillar_share"] * len(ks)
        score = round(statistics.fmean(got.values()), 2) if ok else None
        pillars[p] = {"score": score, "metrics": len(got), "of": len(ks), "pct": got}
        if score is not None:
            present[p] = score
    if len(present) < cov["min_pillars"] or any(r not in present for r in cov["required"]):
        return pillars, None
    w = config["weights"]
    total = sum(w[p] for p in present)
    return pillars, round(sum(w[p] * s for p, s in present.items()) / total, 2)


def _out(v: float | None) -> float | None:
    return None if v is None or not math.isfinite(v) else round(v, 4)


def attach(payload: dict, extras: Mapping[str, Mapping] | None,
           config: Mapping[str, Any] = CONFIG) -> dict:
    """Adds the tier fields to a peers payload in place (and returns it): `fingerprint` and
    `tier_config` on the payload, `peer_group`, `picks`, `gated`, `gate_failures` on each
    industry, `metrics`, `gates`, `pillars`, `composite`, `rank`, `pick` on each name."""
    extras = extras or {}
    metrics: dict[str, dict] = {}
    labels: dict[str, str] = {}
    gated_by_sector: dict[str, list[str]] = {}
    for ind in payload["industries"]:
        label = str(ind.get("label") or "")
        for s in ind["stocks"]:
            sym = s["symbol"]
            m = metric_values(s, extras.get(sym), config)
            metrics[sym], labels[sym] = m, label
            s["gates"] = gates(s, extras.get(sym), label, m, config)
            if s["gates"]["pass"]:
                gated_by_sector.setdefault(s.get("sector") or "", []).append(sym)

    sector_pcts: dict[str, dict] = {}
    for ind in payload["industries"]:
        stocks = ind["stocks"]
        gated = [s["symbol"] for s in stocks if s["gates"]["pass"]]
        if len(gated) >= config["min_peer_group"]:
            pool, group = gated, {"level": "industry", "label": ind.get("label"), "n": len(gated)}
            pcts = _pool_pcts(pool, metrics, config)
        else:
            sec = ind.get("sector") or ""
            pool = sorted(gated_by_sector.get(sec, []))
            group = {"level": "sector", "label": sec, "n": len(pool)}
            if sec not in sector_pcts:
                sector_pcts[sec] = _pool_pcts(pool, metrics, config)
            pcts = sector_pcts[sec]
        scored = []
        for s in stocks:
            sym = s["symbol"]
            m = metrics[sym]
            s["metrics"] = {k: _out(v) for k, v in sorted(m.items())}
            s["pillars"], s["composite"], s["rank"], s["pick"] = {}, None, None, None
            if not s["gates"]["pass"]:
                continue
            s["pillars"], s["composite"] = _score(sym, _metric_set(labels[sym], m, config),
                                                  pcts, config)
            if s["composite"] is not None:
                scored.append(s)
        scored.sort(key=lambda s: (-s["composite"], -(s.get("mktcap") or 0), s["symbol"]))
        k = tier_size(len(gated), config)
        t = config["tiers"]
        picks: dict[str, list[str]] = {"A": [], "B": []}
        for r, s in enumerate(scored, 1):
            s["rank"] = r
            if len(picks["A"]) < k and not picks["B"] and s["composite"] >= t["a_min"]:
                s["pick"] = "A"
            elif len(picks["B"]) < k and s["composite"] >= t["b_min"]:
                s["pick"] = "B"
            if s["pick"]:
                picks[s["pick"]].append(s["symbol"])
        fails = Counter(r for s in stocks for r in s["gates"]["fail"])
        ind["peer_group"] = group
        ind["gated"] = len(gated)
        ind["picks"] = picks
        ind["gate_failures"] = dict(sorted(fails.items()))

    payload["fingerprint"] = fingerprint(config)
    payload["tier_config"] = json.loads(json.dumps(config))
    return payload


# ---------------- live inputs ----------------


def gather_extras(as_of: date) -> tuple[dict[str, dict], list[str]]:
    """sym → extras row from idx-method (read-only): `factors.load_factors` at `as_of`, then
    `cfo_ttm` and `ni_ttm_years` from `factor_series` where the store has them. Each missing
    source is a stale input, never an exception."""
    from assist.candidates.factors import load_factors

    stale: list[str] = []
    try:
        table, stale = load_factors(as_of=as_of)
    except Exception as e:  # noqa: BLE001 - tiers degrade to "no liquidity data"
        table, stale = {}, [f"tier factors failed: {type(e).__name__}"]
    out = {s: dict(r) for s, r in table.items()}
    try:
        from assist.sources.idxmethod_series import IdxMethodSeries

        quarterly = IdxMethodSeries.from_config().quarterly()
    except Exception as e:  # noqa: BLE001
        first = str(e).splitlines()[0][:120] if str(e) else ""
        stale.append(f"factor_series unavailable for tiers ({type(e).__name__}: {first}): "
                     "cfo_ttm from factors.json, TTM NI from the quarterly statements")
        return out, stale
    for sym, qs in quarterly.items():
        qs = [q for q in qs if q.period <= as_of]
        if not qs:
            continue
        row = out.setdefault(sym, {})
        last = qs[-1]
        if last.cfo_ttm is not None:
            row["cfo_ttm"] = last.cfo_ttm
        by_period = {q.period: q.ni_ttm for q in qs}
        years = []
        for k in range(3):
            p = last.period.replace(year=last.period.year - k)
            if by_period.get(p) is None:
                break
            years.append(by_period[p])
        if years:
            row["ni_ttm_years"] = years
    return out, stale
