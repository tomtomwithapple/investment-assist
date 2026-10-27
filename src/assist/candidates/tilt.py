"""IDN macro sector tilt (PLAN S16): a hand-set sensitivity table of the IDX-IC sectors against
the drivers layers 0-2 already read, with a quarterly placebo replay.

- **Table** (`config/sector_tilt.yaml`): per sector (named as in idx-method's
  `data/sectors.json`), signed sensitivities to the drivers below. Its sha256 is the tilt's
  `fingerprint`; this module is also hashed into the journal's model fingerprint
  (`journal.RULE_GLOBS` covers `candidates/*.py`).
- **Drivers**, each a direction clip((reading − center) / scale, −1, +1), read point in time:
  - `coal`, `nickel`, `palm_oil`: worldbankscape commodity scores (`COAL_AUS`, `NICKEL`,
    `PALM_OIL`, Pink Sheet). worldbankscape publishes today's score only, so these are **live
    only**: the replay runs without them and says so.
  - `china`: dbnomics `cn.pmi.mfg` level (50 = no change).
  - `bi_rate`: bisfetcher `WS_CBPOL.M.ID`, change over 6 months (+ = hiking).
  - `real_yield`: BI rate minus CPI y/y (+ = tight).
  - `credit_gap`: bisfetcher `WS_CREDIT_GAP.Q.ID.P.A.C` (+ = credit above trend).
  - `usd_idr`: JISDOR % change over 3 months (idxscape, from 2021-10), else minus the IDR REER's
    (bisfetcher `WS_EER.M.R.B.ID`); + = IDR weaker.
  - `inflation`: CPI y/y change over 3 months (bps-looker `BPS_CPI_YOY`, else dbnomics
    `idn.cpi.yoy`).
  - `consumer`: dbnomics `idn.cci` (OECD consumer confidence, long-term average = 100).
  - `regime`: layer 0 (P8), risk_on +1, neutral 0, risk_off −1. An unknown regime is a missing
    driver, never neutral.
  A row counts once its publication lag has passed (or its store recorded it); a newest row older
  than its max age is used but named stale; a missing driver adds 0 and is named per sector.
- **Tilt** = clip(Σ sensitivity × direction, −1, +1) per sector → `SectorTilt`. Two mappings
  (PLAN S16, S20): required-margin shift = −2 pt × tilt (a tailwind needs less discount) and
  sector cap = round(5 + 2 × tilt) names, in 3..7. `applied` gives (0, 5) unless the verdict
  passed.

**Replay.** At each quarter end with a later one in `factor_series` (P33), the tilts as known
that day against each sector's next-quarter return: Σ mktcap at the next quarter end / Σ mktcap
now − 1 over the sector's names with a bar near both ends (mktcap-weighted, and immune to the
unadjusted prices' splits). Per quarter with a tilt spread, the top-k tilt sectors' mean excess
return (vs all sectors) is an "on" observation and the bottom-k's an "off" one, into
`assist.eval.placebo.evaluate` (shuffled tilts against returns as the placebo and control).
Sectors are today's (`factor_universe`): there is no membership history.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import fmean, stdev

import yaml

from assist.eval.placebo import Verdict, evaluate
from assist.layers.candidates_foreign import LEVEL, Ref, _known
from assist.layers.types import DISCLAIMER, Regime
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.bisfetcher import BI_RATE_M, IDN_CREDIT_GAP, IDR_REER_M
from assist.sources.bpslooker import CPI_YOY
from assist.sources.idxmethod_series import Bar, quarter_ends
from assist.sources.idxscape import JISDOR

__all__ = [
    "CONFIG_PATH",
    "Driver",
    "SectorTilt",
    "Table",
    "applied",
    "direction",
    "drivers_at",
    "evaluate_replay",
    "load_table",
    "margin_shift_pt",
    "observations",
    "read_rows",
    "replay_panel",
    "run",
    "run_live",
    "sector_cap",
    "sector_returns",
    "sector_tilts",
]

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "sector_tilt.yaml"

BI = Ref("bisfetcher", BI_RATE_M, LEVEL, 35, 100)
CREDIT_GAP = Ref("bisfetcher", IDN_CREDIT_GAP, LEVEL, 190, 400)  # BIS publishes ~6 months on
REER = Ref("bisfetcher", IDR_REER_M, LEVEL, 35, 100)
FX = Ref("idxscape", JISDOR, LEVEL, 0, 10)
CPI = (Ref("bps-looker", CPI_YOY, LEVEL, 35, 70), Ref("dbnomics", "idn.cpi.yoy", LEVEL, 45, 80))
CHINA_PMI = Ref("dbnomics", "cn.pmi.mfg", LEVEL, 35, 100)
CCI = Ref("dbnomics", "idn.cci", LEVEL, 45, 120)
REFS = (BI, CREDIT_GAP, REER, FX, *CPI, CHINA_PMI, CCI)
COMMODITIES = {"coal": "COAL_AUS", "nickel": "NICKEL", "palm_oil": "PALM_OIL"}
REGIME = {"risk_on": 1.0, "neutral": 0.0, "risk_off": -1.0}
MAX_BASE_GAP = 35  # days a change's base point may lie before its target date


@dataclass(frozen=True)
class Table:
    drivers: dict[str, dict]
    sectors: dict[str, dict[str, float]]
    apply: dict
    replay: dict
    fingerprint: str


@dataclass(frozen=True)
class Driver:
    name: str
    direction: float
    reading: str


@dataclass(frozen=True)
class SectorTilt:
    sector: str
    tilt: float
    drivers: tuple[str, ...]
    stale: tuple[str, ...]


def load_table(path: Path | str = CONFIG_PATH) -> Table:
    raw = Path(path).read_bytes()
    cfg = yaml.safe_load(raw)
    sectors = {s: {k: float(w) for k, w in sens.items()} for s, sens in cfg["sectors"].items()}
    for s, sens in sectors.items():
        unknown = set(sens) - set(cfg["drivers"])
        if unknown:
            raise ValueError(f"{path}: sector {s} names unknown drivers {sorted(unknown)}")
    return Table(cfg["drivers"], sectors, cfg["apply"], cfg["replay"],
                 hashlib.sha256(raw).hexdigest())


# ---------------- mappings ----------------


def margin_shift_pt(tilt: float, table: Table) -> float:
    return table.apply["margin_pt_per_tilt"] * tilt


def sector_cap(tilt: float, table: Table) -> int:
    a = table.apply
    lo, hi = a["cap_bounds"]
    off = a["cap_per_tilt"] * tilt
    step = int(abs(off) + 0.5 + 1e-9)  # half away from 0, so ±0.25 gives 6 and 4 alike
    return max(lo, min(hi, a["cap_base"] + (step if off >= 0 else -step)))


def applied(t: SectorTilt | None, *, passed: bool, table: Table) -> tuple[float, int]:
    """(required-margin shift in pt, sector cap): nothing moves until the verdict passed."""
    if t is None or not passed:
        return 0.0, table.apply["cap_base"]
    return margin_shift_pt(t.tilt, table), sector_cap(t.tilt, table)


def direction(value: float, spec: Mapping) -> float:
    return max(-1.0, min(1.0, (value - spec["center"]) / spec["scale"]))


# ---------------- drivers ----------------


def read_rows(sources: Mapping[str, Source], start: date, end: date
              ) -> tuple[dict[str, list[Row]], list[str]]:
    """Every series the drivers need, keyed by `Ref.label`; a missing or locked store is named in
    the stale list, never raised."""
    wanted: dict[str, set[str]] = {}
    for ref in REFS:
        wanted.setdefault(ref.source, set()).add(ref.series_id)
    rows: dict[str, list[Row]] = {}
    stale: list[str] = []
    for name in sorted(wanted):
        src = sources.get(name)
        if src is None:
            stale.append(f"{name} (not configured)")
            continue
        try:
            found = src.rows(sorted(wanted[name]), start, end)
        except SourceUnavailable as e:
            stale.append(e.stale_input)
            continue
        for r in found:
            rows.setdefault(f"{name} {r.series_id}", []).append(r)
    return rows, stale


def _months_back(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, m + 1, min(d.day, 28))


class _At:
    """The drivers' series as known on one date."""

    def __init__(self, d: date, rows: Mapping[str, list[Row]]):
        self.d, self.rows = d, rows
        self.stale: list[str] = []

    def series(self, ref: Ref) -> list[Row]:
        return _known(self.rows.get(ref.label, []), ref, self.d)

    def pick(self, refs: Sequence[Ref]) -> tuple[list[Row], Ref | None]:
        for ref in refs:
            s = self.series(ref)
            if s:
                if (self.d - s[-1].date).days > ref.max_age_days:
                    self.stale.append(f"{ref.label} (stale, last {s[-1].date})")
                return s, ref
        self.stale.append(f"{' / '.join(r.label for r in refs)} (no data by {self.d})")
        return [], None

    def change(self, series: list[Row], months: int, ref: Ref) -> tuple[Row, Row] | None:
        """(latest, the point `months` before it), or None with too short a history."""
        last = series[-1]
        target = _months_back(last.date, months)
        i = bisect_right([r.date for r in series], target)
        if not i or (target - series[i - 1].date).days > MAX_BASE_GAP:
            self.stale.append(f"{ref.label} (history from {series[0].date})")
            return None
        return last, series[i - 1]


def drivers_at(
    d: date,
    rows: Mapping[str, list[Row]],
    table: Table,
    *,
    regime: Regime | str | None = None,
    commodities: Mapping[str, float] | None = None,
) -> tuple[dict[str, Driver], list[str]]:
    """Every driver known on `d` → ({name: Driver}, stale). `commodities` maps `coal`, `nickel`,
    `palm_oil` to today's worldbankscape score (None in a replay: there is no history)."""
    at = _At(d, rows)
    spec = table.drivers
    out: dict[str, Driver] = {}

    def put(name: str, value: float, reading: str) -> None:
        out[name] = Driver(name, direction(value, spec[name]), reading)

    if commodities is None:
        at.stale.append("worldbankscape commodity scores (live only, no history): "
                        + ", ".join(COMMODITIES) + " off")
    else:
        for name, subject in COMMODITIES.items():
            if commodities.get(name) is None:
                at.stale.append(f"worldbankscape {subject} (no score): {name} off")
            else:
                put(name, commodities[name], f"worldbankscape {subject} score "
                                             f"{commodities[name]:.1f}")

    pmi, ref = at.pick((CHINA_PMI,))
    if ref:
        put("china", pmi[-1].value, f"China mfg PMI {pmi[-1].value:.1f} ({pmi[-1].date:%Y-%m})")

    bi, bi_ref = at.pick((BI,))
    if bi_ref and (ch := at.change(bi, 6, bi_ref)):
        last, base = ch
        put("bi_rate", last.value - base.value, f"BI rate {last.value:.2f}% ({last.date:%Y-%m}),"
                                                 f" {last.value - base.value:+.2f}pt over 6 months")

    cpi, cpi_ref = at.pick(CPI)
    if cpi_ref and (ch := at.change(cpi, 3, cpi_ref)):
        last, base = ch
        put("inflation", last.value - base.value,
            f"CPI {last.value:.2f}% y/y ({last.date:%Y-%m}, {cpi_ref.source}),"
            f" {last.value - base.value:+.2f}pt over 3 months")
    if bi_ref and cpi_ref:
        real = bi[-1].value - cpi[-1].value
        put("real_yield", real, f"real policy rate {real:.2f}% (BI {bi[-1].value:.2f}% − CPI"
                                f" {cpi[-1].value:.2f}%)")

    gap, ref = at.pick((CREDIT_GAP,))
    if ref:
        g = gap[-1]
        put("credit_gap", g.value, f"credit-to-GDP gap {g.value:+.1f}pt "
                                   f"({g.date.year}Q{(g.date.month - 1) // 3 + 1})")

    fx, ref = at.pick((FX,))
    if ref and (ch := at.change(fx, 3, ref)):
        last, base = ch
        pct = 100 * (last.value / base.value - 1)
        put("usd_idr", pct, f"USD/IDR (JISDOR) {last.value:,.0f} on {last.date}, {pct:+.1f}%"
                            " over 3 months")
    else:
        reer, ref = at.pick((REER,))
        if ref and (ch := at.change(reer, 3, ref)):
            last, base = ch
            pct = 100 * (last.value / base.value - 1)
            put("usd_idr", -pct, f"IDR REER {last.value:.1f} ({last.date:%Y-%m}), {pct:+.1f}%"
                                 " over 3 months")

    cci, ref = at.pick((CCI,))
    if ref:
        put("consumer", cci[-1].value, f"IDN consumer confidence {cci[-1].value:.1f}"
                                       f" ({cci[-1].date:%Y-%m})")

    state = regime.state if isinstance(regime, Regime) else regime
    if state in REGIME:
        put("regime", REGIME[state], f"regime {state}")
    else:
        at.stale.append("regime unknown: regime driver off")
    return out, list(dict.fromkeys(at.stale))


def sector_tilts(drivers: Mapping[str, Driver], table: Table) -> list[SectorTilt]:
    out = []
    for sector, sens in table.sectors.items():
        parts, missing, total = [], [], 0.0
        for name, w in sens.items():
            drv = drivers.get(name)
            if drv is None:
                missing.append(f"{name} (missing)")
                continue
            c = w * drv.direction
            total += c
            parts.append((-abs(c), name, f"{name} {drv.direction:+.2f} x {w:+.2f} = {c:+.2f}:"
                                         f" {drv.reading}"))
        out.append(SectorTilt(sector, max(-1.0, min(1.0, total)),
                              tuple(p[2] for p in sorted(parts)), tuple(missing)))
    return out


# ---------------- replay ----------------


def _bar(bars: Sequence[Bar], dates: Sequence[date], d: date) -> Bar | None:
    i = bisect_right(dates, d)
    while i > 0:
        if bars[i - 1].mktcap:
            return bars[i - 1]
        i -= 1
    return None


def sector_returns(
    bars: Mapping[str, Sequence[Bar]],
    sectors: Mapping[str, str],
    q: date,
    q1: date,
    table: Table,
    dates: Mapping[str, Sequence[date]] | None = None,
) -> dict[str, float]:
    """Per sector, Σ mktcap on q1 / Σ mktcap on q − 1 over the names with a bar within
    `max_bar_gap_days` before both; sectors with fewer than `min_names` names are left out."""
    gap = table.replay["max_bar_gap_days"]
    sums: dict[str, list[float]] = {}
    for sym, bs in bars.items():
        sec = sectors.get(sym)
        if sec not in table.sectors or not bs:
            continue
        ds = dates[sym] if dates is not None else [b.date for b in bs]
        b0, b1 = _bar(bs, ds, q), _bar(bs, ds, q1)
        if b0 is None or b1 is None or b1.date <= q:
            continue
        if (q - b0.date).days > gap or (q1 - b1.date).days > gap:
            continue
        s = sums.setdefault(sec, [0.0, 0.0, 0])
        s[0] += b0.mktcap
        s[1] += b1.mktcap
        s[2] += 1
    return {sec: m1 / m0 - 1 for sec, (m0, m1, n) in sums.items()
            if n >= table.replay["min_names"]}


def replay_panel(
    bars: Mapping[str, Sequence[Bar]],
    sectors: Mapping[str, str],
    rows: Mapping[str, list[Row]],
    regimes: Mapping[date, Regime | str | None],
    table: Table,
) -> list[tuple[date, list[dict]]]:
    """→ [(quarter end, [{sector, tilt, ret}])]: the tilts known on each quarter end (no
    commodity drivers: no history) and each sector's return to the next quarter end."""
    firsts = [b[0].date for b in bars.values() if b]
    if not firsts:
        return []
    qes = quarter_ends(min(firsts), max(b[-1].date for b in bars.values() if b))
    dates = {s: [b.date for b in bs] for s, bs in bars.items()}
    panel = []
    for q, q1 in zip(qes, qes[1:], strict=False):
        drv, _ = drivers_at(q, rows, table, regime=regimes.get(q))
        rets = sector_returns(bars, sectors, q, q1, table, dates)
        panel.append((q, [{"sector": t.sector, "tilt": t.tilt, "ret": rets[t.sector]}
                          for t in sector_tilts(drv, table) if t.sector in rets]))
    return panel


def observations(panel: Sequence[tuple[date, list[dict]]], table: Table
                 ) -> tuple[list[bool], list[float], list[float]]:
    """→ (features, returns, quarterly spreads): per quarter whose top-k and bottom-k tilts differ
    by `min_spread`, (True, top-k mean excess return) and (False, bottom-k's)."""
    k, min_spread = table.replay["k"], table.replay["min_spread"]
    feats: list[bool] = []
    rets: list[float] = []
    spreads: list[float] = []
    for _, recs in panel:
        if len(recs) < 2 * k:
            continue
        ranked = sorted(recs, key=lambda r: (-r["tilt"], r["sector"]))
        top, bot = ranked[:k], ranked[-k:]
        if fmean(r["tilt"] for r in top) - fmean(r["tilt"] for r in bot) < min_spread:
            continue
        mean = fmean(r["ret"] for r in ranked)
        t = fmean(r["ret"] for r in top) - mean
        b = fmean(r["ret"] for r in bot) - mean
        feats += [True, False]
        rets += [t, b]
        spreads.append(t - b)
    return feats, rets, spreads


def evaluate_replay(panel: Sequence[tuple[date, list[dict]]], table: Table, **kw) -> Verdict:
    """The placebo verdict on the top-minus-bottom tilt edge; `kw` goes to `evaluate`."""
    feats, rets, _ = observations(panel, table)
    return evaluate(lambda f, _r: list(f), feats, rets, **kw)


# ---------------- run ----------------


def run(
    as_of: date,
    bars: Mapping[str, Sequence[Bar]],
    sectors: Mapping[str, str],
    rows: Mapping[str, list[Row]],
    regimes: Mapping[date, Regime | str | None],
    table: Table,
    *,
    commodities: Mapping[str, float] | None = None,
    regime: Regime | str | None = None,
    stale: Sequence[str] = (),
    **kw,
) -> dict:
    """Today's tilts, the replay verdict and what S20 may apply (nothing unless it passed).
    `kw` goes to `evaluate`."""
    panel = replay_panel(bars, sectors, rows, regimes, table)
    verdict = evaluate_replay(panel, table, **kw)
    _, _, spreads = observations(panel, table)
    drv, live_stale = drivers_at(as_of, rows, table, regime=regime, commodities=commodities)
    tilts = []
    for t in sector_tilts(drv, table):
        shift, cap = applied(t, passed=verdict.passed, table=table)
        tilts.append({
            "sector": t.sector, "tilt": round(t.tilt, 4),
            "margin_shift_pt": shift, "cap": cap,
            "raw_margin_shift_pt": margin_shift_pt(t.tilt, table),
            "raw_cap": sector_cap(t.tilt, table),
            "drivers": list(t.drivers), "stale": list(t.stale),
        })
    tilts.sort(key=lambda r: (-r["tilt"], r["sector"]))
    return {
        "as_of": as_of,
        "passed": verdict.passed,
        "blocked": None if verdict.passed else verdict.reason,
        "verdict": {k: v for k, v in verdict.to_dict().items() if k != "control_ts"},
        "quarters": len(spreads),
        "panel_quarters": len(panel),
        "spread_mean": fmean(spreads) if spreads else None,
        "spread_t": (fmean(spreads) / (stdev(spreads) / len(spreads) ** 0.5)
                     if len(spreads) > 2 and stdev(spreads) > 0 else None),
        "replay_basis": "no commodity drivers (worldbankscape keeps no history); "
                        "today's sector membership",
        "drivers": {n: {"direction": round(d.direction, 4), "reading": d.reading}
                    for n, d in drv.items()},
        "tilts": tilts,
        "fingerprint": table.fingerprint,
        "stale_inputs": list(dict.fromkeys([*stale, *live_stale])),
        "disclaimer": DISCLAIMER,
    }


def _regime_state(inputs) -> str | None:
    """P8's state, or None when no core input was known (P8 would call that neutral)."""
    from assist.layers.regime import RULES, classify

    if all(inputs.values.get(f) is None for f in RULES):
        return None
    return classify(inputs).state


def run_live(as_of: date | None = None, **kw) -> dict:
    """The tilt over the real stores (read-only): idx-method `factor_series` for the replay,
    bisfetcher, dbnomics, idxscape and bps-looker for the drivers, P8's regime per quarter end
    and today, and worldbankscape's commodity scores for today."""
    from assist.layers.candidates_foreign import default_sources
    from assist.layers.regime import read_inputs
    from assist.sources.bpslooker import BpsLookerSource
    from assist.sources.idxmethod_series import IdxMethodSeries
    from assist.sources.usfin import FredSource
    from assist.sources.worldbankscape import WorldbankscapeSource

    as_of = as_of or date.today()
    table = load_table()
    stale: list[str] = []
    bars: dict[str, list[Bar]] = {}
    sectors: dict[str, str] = {}
    try:
        series = IdxMethodSeries.from_config()
        bars = series.daily(end=as_of)
        sectors = {s: u["sector"] for s, u in series.universe().items() if u.get("sector")}
    except SourceUnavailable as e:
        stale.append(e.stale_input)

    sources = {k: v for k, v in default_sources().items()
               if k in {"bisfetcher", "dbnomics", "idxscape"}}
    sources["bps-looker"] = BpsLookerSource.from_config()
    rows, st = read_rows(sources, date(2010, 1, 1), as_of)
    stale += st

    fred = FredSource()
    firsts = [b[0].date for b in bars.values() if b]
    qes = quarter_ends(min(firsts), as_of) if firsts else []
    regimes = {q: _regime_state(read_inputs(q, fred)) for q in qes}
    known = sum(v is not None for v in regimes.values())
    if known < len(qes):
        stale.append(f"sec-edgar FRED (regime known at {known} of {len(qes)} quarter ends)")
    today = read_inputs(as_of, fred)
    stale += today.stale_inputs
    regime = _regime_state(today)

    commodities: dict[str, float] | None = None
    try:
        wbs = WorldbankscapeSource.from_config().load(
            subjects=list(COMMODITIES.values()), assets=["commodities"])
        by_subject = {s.subject: s.score for s in wbs.scores}
        commodities = {n: by_subject.get(subj) for n, subj in COMMODITIES.items()}
        stale += wbs.stale_inputs
    except SourceUnavailable as e:
        stale.append(e.stale_input)
    return run(as_of, bars, sectors, rows, regimes, table, commodities=commodities,
               regime=regime, stale=stale, **kw)
