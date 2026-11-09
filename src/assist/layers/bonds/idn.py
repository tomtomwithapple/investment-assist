"""IDN bonds rule (PLAN S9): when to buy SBN, for an IDR-based investor.

Four inputs, each read point in time (only rows dated on or before `as_of` and known by then),
plus the global regime:

- `real_yield`: IGSYC 10Y (idxscape PHEI, P32) minus the newest CPI y/y (bps-looker, from P17's
  `IdnOverrides.inputs` when given; dbnomics `idn.cpi.yoy` when bps-looker has none). It is
  ranked against its own monthly history (10Y at month end − that month's CPI y/y) over up to
  `WINDOW_MONTHS`; the window used is named in `real_window` and the detail. Shorter than
  `MIN_HISTORY` months, it is judged on absolute levels instead. The monthly history takes PHEI
  month ends where it has them and dbnomics' OECD IDN long-term rate (`idn.rate.long`, a monthly
  average) elsewhere, since PHEI history is short.
- `curve_slope`: IGSYC 10Y − 2Y on the newest day with both, as idxscape J8 builds it. Context
  only; it does not gate the call.
- `sbn_non_resident_change`: P18's signal (DJPPR non-resident SBN holdings, 4 weeks).
- `jisdor_trend`: JISDOR % change over `TREND_DAYS` fixings; a breakout is a new high over the
  previous `HIGH_DAYS` fixings (~6 months) or a rise of `JUMP_PCT` or more over `TREND_DAYS`.

`decide` turns them into a call: **enter** (overweight) when the real yield is high, foreign
holdings are stable or rising and USD/IDR is not breaking out; **reduce** (underweight) when the
real yield is low and foreigners sell or USD/IDR breaks out; **hold** (neutral) otherwise; and
**no_call** when an input is missing. An enter is laddered when the regime is risk-off (or not
given), bought in one go otherwise. The thresholds are hand-set: `gated_stance` lets an enter
change a stance only with a passing placebo verdict (`rule_verdict`, P9 harness), a reduce only
with a passing reduce-side verdict (P74), a hold never.

When the store has no PHEI tables, the 10Y falls back to dbnomics' `idn.rate.long`, labelled a
proxy in `drivers` and `stale_inputs`; the slope is then unavailable. A proxy older than
`PROXY_CALL_AGE` still gives a real yield but no call.

PHEI is for the owner's local use only: drivers, risks and signal details carry derived numbers
(real yield, its percentile, the slope), never a raw curve point.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from assist.eval.placebo import Verdict, align, evaluate
from assist.layers.overrides import DBN_CPI, IdnOverrides
from assist.layers.signals import IdnSignals, idn_signals
from assist.layers.types import Regime, Signal
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.bpslooker import CPI_YOY, BpsLookerSource
from assist.sources.dbnomics import DbnomicsSource
from assist.sources.idxscape import JISDOR, IdxscapeSource
from assist.sources.idxscape_phei import IGSYC_2Y, IGSYC_10Y, PheiSource
from assist.stance import LADDER_SPACING_DAYS, LADDER_TRANCHES

__all__ = [
    "PROXY_10Y",
    "IdnBonds",
    "bond_returns",
    "decide",
    "gated_stance",
    "idn_bonds",
    "rule_verdict",
]

SUBJECT, ASSET = "IDN", "bonds"
PROXY_10Y = "idn.rate.long"  # OECD IRLT for IDN via dbnomics, monthly average
PHEI_NAME = "idxscape_phei"

WINDOW_MONTHS = 120  # real-yield percentile window
MIN_HISTORY = 24  # months; fewer → absolute thresholds
HIGH_PCT, LOW_PCT = 200 / 3, 100 / 3  # top / bottom third of its own history
HIGH_ABS, LOW_ABS = 3.0, 1.5  # % real yield, when the history is too short
SLOPE_STEEP, SLOPE_FLAT = 0.75, 0.0  # pt, 10Y − 2Y
TREND_DAYS = 20  # JISDOR fixings
HIGH_DAYS = 120  # ~6 months of fixings
MIN_FX_DAYS = 60
TREND_BAND_PCT = 1.0  # JISDOR change beyond this sets the trend direction
JUMP_PCT = 2.0  # JISDOR rise over TREND_DAYS that counts as a breakout
DURATION = 7.0  # years, a 10Y SBN's modified duration, for the return proxy

# A row dated this long before `as_of` counts as published, whatever its recorded date says.
# PHEI's `as_of` is the page's fetch date, a real vintage, so PHEI has no lag fallback.
LAG = {
    CPI_YOY: timedelta(days=35),
    DBN_CPI: timedelta(days=45),
    PROXY_10Y: timedelta(days=45),
    JISDOR: timedelta(days=1),
}
MAX_AGE = {"phei": timedelta(days=7), "cpi": timedelta(days=70), "jisdor": timedelta(days=7)}
PROXY_CALL_AGE = timedelta(days=90)  # an older proxy 10Y gives no call
READ_BACK = {"monthly": timedelta(days=31 * (WINDOW_MONTHS + 2)), "fx": timedelta(days=250)}

NO_ENTRY = {"style": "none", "tranches": 0, "spacing_days": 0}
LUMP = {"style": "lump", "tranches": 1, "spacing_days": 0}
LADDER = {"style": "ladder", "tranches": LADDER_TRANCHES, "spacing_days": LADDER_SPACING_DAYS}
CALL_STANCE = {"enter": "overweight", "hold": "neutral", "reduce": "underweight"}


@dataclass(frozen=True)
class IdnBonds:
    """The IDN bonds rule on `as_of`: the call, the stance it proposes (None = no call), the
    entry plan, the inputs behind it and what was missing. `proposed_stance` changes nothing
    until `gated_stance` sees a passing placebo verdict."""

    as_of: date
    call: str
    proposed_stance: str | None
    entry: dict
    signals: tuple[Signal, ...]
    real_yield: float | None
    real_yield_pct: float | None
    real_window: str
    slope: float | None
    breakout: bool | None
    ten_year_source: str | None
    regime: str | None
    drivers: tuple[str, ...]
    risks: tuple[str, ...]
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    local_only: bool = field(default=False)  # derived numbers only: safe to send

    def signal(self, name: str) -> Signal | None:
        return next((s for s in self.signals if s.name == name), None)


def decide(real: int | None, foreign: int | None, breakout: bool | None) -> tuple[str, str | None]:
    """(call, proposed stance) from the real-yield direction, the foreign SBN flow direction and
    the USD/IDR breakout flag; any input None → no call."""
    if real is None or foreign is None or breakout is None:
        return "no_call", None
    if real > 0 and foreign >= 0 and not breakout:
        call = "enter"
    elif real < 0 and (foreign < 0 or breakout):
        call = "reduce"
    else:
        call = "hold"
    return call, CALL_STANCE[call]


def gated_stance(base: str, bonds: IdnBonds, verdict: Verdict | None, *,
                 reduce_verdict: Verdict | None = None) -> tuple[str, str]:
    """The stance after the rule: `base` unless the rule made a call that its own side's
    placebo verdict backs. `verdict` (enter vs hold + reduce) backs only an enter; a reduce needs
    `reduce_verdict` (reduce vs enter + hold, P74), and a hold claims no edge, so it never moves
    `base`. The note says which, for the journal."""
    p, call = bonds.proposed_stance, bonds.call
    if p is None:
        return base, f"bonds rule: no call ({call})"
    if call == "hold":
        return base, f"bonds rule proposes {p}; not applied: a hold claims no edge"
    if call == "reduce":
        if reduce_verdict is None:
            return base, f"bonds rule proposes {p}; not applied: reduce side untested"
        if not reduce_verdict.passed:
            reason = reduce_verdict.reason.removeprefix("reduce side: ")
            return base, f"bonds rule proposes {p}; not applied: reduce side {reason}"
        return p, f"bonds rule applied: {p} ({reduce_verdict.reason})"
    if verdict is None:
        return base, f"bonds rule proposes {p}; not applied: no placebo verdict"
    if not verdict.passed:
        return base, f"bonds rule proposes {p}; not applied: {verdict.reason}"
    return p, f"bonds rule applied: {p} ({verdict.reason})"


def bond_returns(yields: Sequence[tuple[date, float]], horizon: int = 3,
                 duration: float = DURATION) -> list[tuple[date, float]]:
    """Return proxy of a 10Y SBN held `horizon` periods (months): carry − duration × Δyield.
    Yields in %; the tail without a forward point is dropped."""
    pts = sorted(yields)
    return [(d, y / 100 * horizon / 12 - duration * (pts[i + horizon][1] - y) / 100)
            for i, (d, y) in enumerate(pts[:max(0, len(pts) - horizon)])]


def rule_verdict(calls: Mapping[date, str], yields: Sequence[tuple[date, float]],
                 horizon: int = 3, duration: float = DURATION, **kw) -> Verdict:
    """Placebo verdict for the calls (keyed on the dates of `yields`): does an enter precede a
    better bond return than a hold or reduce? no_call dates are skipped. `stride` and `block`
    default to `horizon` so overlapping returns don't inflate the t-stat."""
    feats = {d: None if c == "no_call" else c == "enter" for d, c in calls.items()}
    _, f, r = align(feats, bond_returns(yields, horizon, duration))
    kw.setdefault("stride", horizon)
    kw.setdefault("block", horizon)
    return evaluate(lambda fs, _rs: list(fs), f, r, **kw)


# ---------------- reading ----------------


def _month(d: date) -> date:
    return d.replace(day=1)


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _direction(value: float, band: float) -> int:
    return 1 if value > band else -1 if value < -band else 0


class _Builder:
    def __init__(self, as_of: date):
        self.as_of = as_of
        self.stale: list[str] = []
        self.sources: list[str] = []
        self.drivers: list[str] = []
        self.risks: list[str] = []
        self.signals: list[Signal] = []

    def read(self, source: Source, ids: Sequence[str], back: timedelta) -> dict | None:
        try:
            rows = source.rows(list(ids), start=self.as_of - back, end=self.as_of)
        except SourceUnavailable as e:
            self.stale.append(e.stale_input)
            return None
        self.sources.append(source.name)
        out: dict[str, list[Row]] = defaultdict(list)
        for r in sorted(rows, key=lambda r: (r.series_id, r.date)):
            if r.value is None or r.date > self.as_of:
                continue
            recorded = r.as_of is None or r.as_of <= self.as_of
            lag = LAG.get(r.series_id)
            if r.series_id in LAG and r.as_of is None:
                recorded = False  # no vintage at all: known only past its lag
            if recorded or (lag is not None and r.date + lag <= self.as_of):
                out[r.series_id].append(r)
        return out

    def add(self, name: str, value: float | None, direction: int, source: str, detail: str):
        self.signals.append(Signal(SUBJECT, ASSET, self.as_of, name, value, direction, source,
                                   detail))


def _cpi(b: _Builder, bps: dict | None, dbn: dict | None,
         overrides: IdnOverrides | None) -> tuple[Row | None, dict[date, float]]:
    """The newest CPI y/y and the monthly history (bps-looker over dbnomics)."""
    hist = {_month(r.date): r.value for r in (dbn or {}).get(DBN_CPI, [])}
    bps_series = (bps or {}).get(CPI_YOY, [])
    hist.update({_month(r.date): r.value for r in bps_series})
    latest = overrides.latest("cpi_yoy") if overrides is not None else None
    if latest is None and bps_series:
        latest = bps_series[-1]
    if latest is None:
        if bps is not None:
            b.stale.append(f"bps-looker {CPI_YOY} (no data)")
        dbn_series = (dbn or {}).get(DBN_CPI, [])
        if dbn_series:
            latest = dbn_series[-1]
        elif dbn is not None:
            b.stale.append(f"dbnomics {DBN_CPI} (no data)")
    if latest is not None and b.as_of - latest.date > MAX_AGE["cpi"]:
        b.stale.append(f"{latest.source} {latest.series_id} (last {latest.date})")
    return latest, hist


def _real_yield(b: _Builder, ten: Row | None, proxy: bool, cpi: Row | None,
                tens: dict[date, float], cpis: dict[date, float]) -> tuple[float | None,
                                                                            float | None, str,
                                                                            int | None]:
    if ten is None or cpi is None:
        return None, None, "", None
    real = ten.value - cpi.value
    months = sorted(m for m in tens if m < _month(ten.date) and m in cpis)[-WINDOW_MONTHS:]
    hist = [tens[m] - cpis[m] for m in months]
    window = (f"{len(months)} months {months[0]:%Y-%m}..{months[-1]:%Y-%m}" if months
              else "no history")
    if len(hist) >= MIN_HISTORY:
        pct = 100 * sum(h <= real for h in hist) / len(hist)
        direction = 1 if pct >= HIGH_PCT else -1 if pct <= LOW_PCT else 0
        rank = f"{_ordinal(round(pct))} pct of {window}"
    else:
        pct = None
        direction = 1 if real >= HIGH_ABS else -1 if real < LOW_ABS else 0
        rank = f"absolute: high ≥ {HIGH_ABS}%, low < {LOW_ABS}%; only {window}"
    ten_label = "10Y proxy (dbnomics, monthly avg)" if proxy else "IGSYC 10Y"
    detail = (f"{ten_label} on {ten.date} − CPI {cpi.value:.2f}% y/y ({cpi.date:%Y-%m}); "
              f"{rank}")
    call_dir: int | None = direction
    if proxy and b.as_of - ten.date > PROXY_CALL_AGE:
        call_dir = None
        detail += f"; proxy from {ten.date:%Y-%m} too old to call"
        b.risks.append(f"real yield rests on a 10Y proxy from {ten.date:%Y-%m}")
    b.add("real_yield", real, direction if call_dir is not None else 0,
          PHEI_NAME if not proxy else "dbnomics", detail)
    pct_text = rank if pct is None else f"{_ordinal(round(pct))} pct, {window}"
    b.drivers.append(f"real yield {real:.2f}% ({pct_text})")
    return real, pct, window, call_dir


def _ten_year(b: _Builder, phei: dict | None, dbn: dict | None, phei_src: Source):
    """(newest 10Y row, proxy?, monthly 10Y history, slope) from PHEI, else the dbnomics proxy."""
    tens: dict[date, float] = {_month(r.date): r.value for r in (dbn or {}).get(PROXY_10Y, [])}
    t10 = (phei or {}).get(IGSYC_10Y, [])
    for r in t10:
        tens[_month(r.date)] = r.value  # month end wins: rows are oldest first
    if phei is not None and not t10:
        b.stale.append(f"{PHEI_NAME} {IGSYC_10Y} (no data)")
    if t10:
        ten = t10[-1]
        if b.as_of - ten.date > MAX_AGE["phei"]:
            b.stale.append(f"{PHEI_NAME} {IGSYC_10Y} (last {ten.date})")
        two = {r.date: r.value for r in phei.get(IGSYC_2Y, [])}
        day = next((r for r in reversed(t10) if r.date in two), None)
        slope = None
        if day is not None:
            slope = day.value - two[day.date]
            gap_days = getattr(phei_src, "yesterday_column_days", None)
            if gap_days is not None:
                try:
                    if day.date in gap_days():
                        b.stale.append(f"{PHEI_NAME} IGSYC {day.date} (gap-filled from a later"
                                       " page's Yesterday column)")
                except SourceUnavailable:
                    pass
            direction = 1 if slope >= SLOPE_STEEP else -1 if slope < SLOPE_FLAT else 0
            b.add("curve_slope", slope, direction, PHEI_NAME,
                  f"IGSYC 10Y−2Y on {day.date}" + (", inverted" if slope < 0 else ""))
            b.drivers.append(f"IGSYC 10Y−2Y slope {slope:+.2f}pt")
        else:
            b.stale.append(f"curve slope (no {IGSYC_2Y} on a 10Y day)")
        return ten, False, tens, slope
    proxy = (dbn or {}).get(PROXY_10Y, [])
    b.stale.append("curve slope (slope unavailable without the IGSYC curve)")
    if not proxy:
        if dbn is not None:
            b.stale.append(f"dbnomics {PROXY_10Y} (no data)")
        return None, True, tens, None
    ten = proxy[-1]
    b.stale.append(f"dbnomics {PROXY_10Y} (proxy for IGSYC 10Y, last {ten.date})")
    b.drivers.append(f"10Y is a proxy: OECD IDN long-term rate via dbnomics ({PROXY_10Y}),"
                     f" monthly average for {ten.date:%Y-%m}; no IGSYC curve")
    return ten, True, tens, None


def _jisdor(b: _Builder, idx: dict | None, name: str) -> bool | None:
    if idx is None:
        return None
    fx = idx.get(JISDOR, [])
    if len(fx) < MIN_FX_DAYS:
        b.stale.append(f"{name} {JISDOR} ({len(fx)} of {MIN_FX_DAYS} fixings)")
        return None
    last, base = fx[-1], fx[-1 - TREND_DAYS]
    if b.as_of - last.date > MAX_AGE["jisdor"]:
        b.stale.append(f"{name} {JISDOR} (last {last.date})")
    change = 100 * (last.value / base.value - 1)
    prior = [r.value for r in fx[-1 - HIGH_DAYS:-1]]
    high = last.value > max(prior)
    jump = change >= JUMP_PCT
    # USD/IDR rising = IDR weakening = a headwind for an IDR bond held by a foreigner
    b.add("jisdor_trend", change, -_direction(change, TREND_BAND_PCT), name,
          f"JISDOR {change:+.1f}% over {TREND_DAYS} fixings to {last.date}"
          f"{'; 6m high' if high else ''}")
    b.drivers.append(f"JISDOR {change:+.1f}% over {TREND_DAYS} fixings")
    if high:
        b.risks.append(f"USD/IDR at 6m high ({last.date})")
    if jump:
        b.risks.append(f"USD/IDR {change:+.1f}% over {TREND_DAYS} days")
    return high or jump


def _foreign(b: _Builder, sig: IdnSignals) -> int | None:
    b.stale += [s for s in sig.stale_inputs
                if "SBN" in s or "us_lt_bond" in s or s.startswith(("idxscape (", "sec-edgar ("))]
    b.sources += [s for s in sig.sources if s in ("idxscape", "sec-edgar")]
    found = None
    for s in sig.for_asset(ASSET):
        b.signals.append(s)
        b.drivers.append(s.detail)
        if s.name == "sbn_non_resident_change":
            found = s.direction
    if found is None:
        b.stale.append("foreign SBN holdings (no sbn_non_resident_change signal)")
    elif found < 0:
        b.risks.append("non-resident SBN holdings falling")
    return found


def idn_bonds(
    as_of: date,
    regime: Regime | None = None,
    overrides: IdnOverrides | None = None,
    signals: IdnSignals | None = None,
    *,
    phei: Source | None = None,
    dbnomics: Source | None = None,
    bps: Source | None = None,
    idxscape: Source | None = None,
) -> IdnBonds:
    """The IDN bonds rule on `as_of`. Sources default to the configured stores; `signals`
    defaults to P18's `idn_signals` over the same idxscape. A store that is missing or locked is
    named in `stale_inputs`, never raised; a missing input makes it a no_call."""
    b = _Builder(as_of)
    phei_src = phei or PheiSource.from_config()
    idx_src = idxscape or IdxscapeSource.from_config()
    phei_rows = b.read(phei_src, [IGSYC_10Y, IGSYC_2Y], READ_BACK["monthly"])
    dbn_rows = b.read(dbnomics or DbnomicsSource.from_config(), [PROXY_10Y, DBN_CPI],
                      READ_BACK["monthly"])
    bps_rows = b.read(bps or BpsLookerSource.from_config(), [CPI_YOY], READ_BACK["monthly"])
    fx_rows = b.read(idx_src, [JISDOR], READ_BACK["fx"])

    ten, proxy, tens, slope = _ten_year(b, phei_rows, dbn_rows, phei_src)
    cpi, cpis = _cpi(b, bps_rows, dbn_rows, overrides)
    real, pct, window, real_dir = _real_yield(b, ten, proxy, cpi, tens, cpis)
    foreign = _foreign(b, signals if signals is not None else idn_signals(as_of, idxscape=idx_src))
    breakout = _jisdor(b, fx_rows, idx_src.name)

    if overrides is not None and (bi := overrides.component("bi_rate")) is not None:
        b.drivers.append(bi.detail)
        if bi.direction > 0:
            b.risks.append("BI hiking")
    if regime is None:
        b.stale.append("regime (not given)")
    else:
        if regime.state == "risk_off":
            b.risks.append("global regime risk-off: ladder the entry")
        if regime.dollar == "up":
            b.risks.append("broad dollar rising")

    call, stance = decide(real_dir, foreign, breakout)
    if call != "enter":
        entry = dict(NO_ENTRY)
    elif regime is None or regime.state == "risk_off":
        entry = dict(LADDER)
    else:
        entry = dict(LUMP)
    return IdnBonds(
        as_of=as_of, call=call, proposed_stance=stance, entry=entry, signals=tuple(b.signals),
        real_yield=real, real_yield_pct=pct, real_window=window, slope=slope,
        breakout=breakout, ten_year_source=None if ten is None else (
            "dbnomics proxy" if proxy else PHEI_NAME),
        regime=None if regime is None else regime.state,
        drivers=tuple(dict.fromkeys(b.drivers)), risks=tuple(dict.fromkeys(b.risks)),
        stale_inputs=tuple(dict.fromkeys(b.stale)), sources=tuple(dict.fromkeys(b.sources)),
    )
