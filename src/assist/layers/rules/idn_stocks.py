"""IDN stocks market rule (PLAN S10a): the market stance for Indonesian equities, for an
IDR-based investor. Names come later, from P20's screens; this rule only says whether to own
the market.

Three inputs, each read point in time (rows dated on or before `as_of` and known by then):

- **valuation**: the JCI earnings yield, cap-weighted over idx-method's screener cross-section
  (Σ mktcap × EY / Σ mktcap, loss makers included, as an index P/E counts them), from the
  newest `data/snapshots/<date>.json.gz` on or before `as_of` (`factors.json` when there are no
  snapshots). It is compared two ways:
  - `ey_vs_sbn`: EY − SBN 10Y (the classic yield gap). Context only.
  - `implied_erp_vs_hurdle`: implied ERP = EY + `G_REAL` (long-run real earnings growth, so EY
    stands for a real return) − the real 10Y (10Y − CPI y/y), against the hurdle US ERP + IDN
    CRP (dbnomics `us.erp.implied` + `idn.crp`, each known only past its publication lag;
    `idn.erp.hurdle` when either is missing). ≥ +`ERP_BAND` is cheap (+1), ≤ −`ERP_BAND` rich
    (−1). This gates the call. The local yield already carries some country risk, so adding
    the CRP is conservative.
  The 10Y is IGSYC 10Y (idxscape PHEI, P32), else dbnomics' OECD IDN long-term rate
  (`idn.rate.long`, monthly average) labelled a proxy in drivers and stale_inputs. A proxy older
  than `PROXY_CALL_AGE` (90 days, as in P31) still reports the numbers but makes no call.
- **flows**: P18's `idx_foreign_flow` (required) + `ksei_foreign_share` (optional), netted.
  `tic_us_equity_net` is a driver only (it lags ~2 months).
- **macro**: worldbankscape's layer-1 IDN stocks score shifted by P17's stocks override;
  ≥ `MACRO_HIGH` is a tailwind, ≤ `MACRO_LOW` a headwind.

`decide`: **enter** (overweight) when the market is cheap against the hurdle and neither flows
nor macro are against it; **reduce** (underweight) when it is rich and flows or macro are against
it; **hold** (neutral) otherwise; **no_call** when an input is missing. An enter is laddered when
the regime is risk-off (or not given). The JCI level (idx-method, frozen at 2026-09-30, no
fetcher) is context and the placebo's return series; its age is named in stale_inputs. The
thresholds are hand-set: `gated_stance` lets the call change a stance only with a passing placebo
verdict (`rule_verdict`, P9 harness).

PHEI is for the owner's local use only: drivers and details carry derived numbers (EY − 10Y, the
real yield, the implied ERP), never the raw IGSYC 10Y.
"""

from __future__ import annotations

import gzip
import json
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from assist.doctor import DEFAULT_CONFIG
from assist.eval.placebo import Verdict, align, evaluate, forward_returns
from assist.layers.bonds.idn import LAG as BOND_LAG
from assist.layers.bonds.idn import PROXY_10Y, _cpi
from assist.layers.overrides import DBN_CPI, IdnOverrides, apply
from assist.layers.signals import IdnSignals, idn_signals
from assist.layers.types import AssetScore, Regime, Signal
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.bpslooker import CPI_YOY, BpsLookerSource
from assist.sources.dbnomics import DbnomicsSource
from assist.sources.idxmethod import JCI, IdxMethodIndexSource
from assist.sources.idxmethod_stocks import IdxMethodStocks
from assist.sources.idxscape_phei import IGSYC_10Y, PheiSource
from assist.sources.worldbankscape import WorldbankscapeSource
from assist.stance import LADDER_SPACING_DAYS, LADDER_TRANCHES

__all__ = [
    "HURDLE",
    "IDN_CRP",
    "US_ERP",
    "FactorSnapshots",
    "IdnStocks",
    "decide",
    "gated_stance",
    "idn_stocks",
    "market_earnings_yield",
    "month_end_closes",
    "rule_verdict",
]

SUBJECT, ASSET = "IDN", "stocks"
PHEI_NAME = "idxscape_phei"
US_ERP, IDN_CRP, HURDLE = "us.erp.implied", "idn.crp", "idn.erp.hurdle"  # fractions

G_REAL = 2.0  # % long-run real earnings growth added to the EY
ERP_BAND = 1.0  # pt, implied ERP − hurdle
GAP_BAND = 0.5  # pt, EY − 10Y (context signal)
MACRO_HIGH, MACRO_LOW = 55.0, 45.0

# A row dated this long before `as_of` counts as published, whatever its recorded date says.
# Damodaran posts the month's ERP in its first days; a CRP snapshot ~6 weeks after its date.
LAG = {**BOND_LAG, US_ERP: timedelta(days=10), IDN_CRP: timedelta(days=45),
       HURDLE: timedelta(days=45)}
MAX_AGE = {"phei": timedelta(days=7), "factors": timedelta(days=14), "jci": timedelta(days=7),
           US_ERP: timedelta(days=70), HURDLE: timedelta(days=70), IDN_CRP: timedelta(days=450)}
PROXY_CALL_AGE = timedelta(days=90)  # an older proxy 10Y gives no call (as P31)
READ_BACK = {"monthly": timedelta(days=800), "crp": timedelta(days=900),
             "jci": timedelta(days=60)}

NO_ENTRY = {"style": "none", "tranches": 0, "spacing_days": 0}
LUMP = {"style": "lump", "tranches": 1, "spacing_days": 0}
LADDER = {"style": "ladder", "tranches": LADDER_TRANCHES, "spacing_days": LADDER_SPACING_DAYS}
CALL_STANCE = {"enter": "overweight", "hold": "neutral", "reduce": "underweight"}


@dataclass(frozen=True)
class IdnStocks:
    """The IDN stocks market rule on `as_of`: the call, the stance it proposes (None = no
    call), the entry plan, the inputs behind it and what was missing. `proposed_stance` changes
    nothing until `gated_stance` sees a passing placebo verdict. Percent units throughout."""

    as_of: date
    call: str
    proposed_stance: str | None
    entry: dict
    signals: tuple[Signal, ...]
    earnings_yield: float | None
    pe: float | None
    factors_date: date | None
    ey_gap: float | None
    real_yield: float | None
    implied_erp: float | None
    hurdle: float | None
    macro_score: float | None
    ten_year_source: str | None
    regime: str | None
    drivers: tuple[str, ...]
    risks: tuple[str, ...]
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def signal(self, name: str) -> Signal | None:
        return next((s for s in self.signals if s.name == name), None)


def decide(valuation: int | None, flows: int | None,
           macro: int | None) -> tuple[str, str | None]:
    """(call, proposed stance) from the valuation, net foreign flow and macro directions; any
    input None → no call."""
    if valuation is None or flows is None or macro is None:
        return "no_call", None
    if valuation > 0 and flows >= 0 and macro >= 0:
        call = "enter"
    elif valuation < 0 and (flows < 0 or macro < 0):
        call = "reduce"
    else:
        call = "hold"
    return call, CALL_STANCE[call]


def gated_stance(base: str, stocks: IdnStocks, verdict: Verdict | None) -> tuple[str, str]:
    """The stance after the rule: `base` unless the rule made a call and its placebo verdict
    passed. The note says which, for the journal."""
    p = stocks.proposed_stance
    if p is None:
        return base, f"stocks rule: no call ({stocks.call})"
    if verdict is None:
        return base, f"stocks rule proposes {p}; not applied: no placebo verdict"
    if not verdict.passed:
        return base, f"stocks rule proposes {p}; not applied: {verdict.reason}"
    return p, f"stocks rule applied: {p} ({verdict.reason})"


def month_end_closes(rows: Iterable[Row]) -> list[tuple[date, float]]:
    """The last non-empty close of each month, oldest first (JCI rows → `rule_verdict` prices)."""
    last: dict[tuple[int, int], tuple[date, float]] = {}
    for r in sorted((r for r in rows if r.value is not None), key=lambda r: r.date):
        last[(r.date.year, r.date.month)] = (r.date, r.value)
    return [last[k] for k in sorted(last)]


def rule_verdict(calls: Mapping[date, str], prices: Sequence[tuple[date, float]],
                 horizon: int = 3, **kw) -> Verdict:
    """Placebo verdict for the calls (keyed on the dates of `prices`, e.g. JCI month ends): does
    an enter precede a better JCI return over `horizon` periods than a hold or reduce? no_call
    dates are skipped; `stride` and `block` default to `horizon`."""
    feats = {d: None if c == "no_call" else c == "enter" for d, c in calls.items()}
    _, f, r = align(feats, forward_returns(prices, horizon))
    kw.setdefault("stride", horizon)
    kw.setdefault("block", horizon)
    return evaluate(lambda fs, _rs: list(fs), f, r, **kw)


def market_earnings_yield(factors: Mapping[str, Mapping]) -> tuple[float | None, int, float]:
    """(cap-weighted earnings yield %, names used, total cap) over names with a positive
    `mktcap` and an `earnings_yield` (%)."""
    cap = earn = 0.0
    n = 0
    for r in factors.values():
        m, ey = r.get("mktcap"), r.get("earnings_yield")
        if not m or m <= 0 or ey is None:
            continue
        cap += m
        earn += m * ey
        n += 1
    return (earn / cap if cap else None), n, cap


class FactorSnapshots:
    """idx-method's dated screener cross-sections, read-only: `data/snapshots/<date>.json.gz`
    (archived each weekday since 2026-08-30, `{"date", "factors", ...}`), else
    `data/factors.json` dated by its file time. `IdxMethodStocks` reads only today's file, so the
    dated archive is read here."""

    name = "idx-method"

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None):
        return cls(IdxMethodStocks.from_config(config, env).root)

    def _dated(self) -> list[tuple[date, Path]]:
        if not self.root.is_dir():
            raise SourceUnavailable(self.name, "missing", f"no directory at {self.root}")
        out = []
        folder = self.root / "data" / "snapshots"
        for p in folder.glob("*.json.gz") if folder.is_dir() else ():
            try:
                out.append((date.fromisoformat(p.name.removesuffix(".json.gz")), p))
            except ValueError:
                continue
        return sorted(out)

    def _load(self, path: Path) -> dict:
        try:
            with gzip.open(path, "rt") as f:
                return json.load(f)
        except (OSError, ValueError, EOFError) as e:
            raise SourceUnavailable(self.name, "error", f"{path}: {e}") from e

    def factors_on(self, as_of: date) -> tuple[date, dict]:
        """(snapshot date, factors) of the newest cross-section known on `as_of`."""
        known = [(d, p) for d, p in self._dated() if d <= as_of]
        if known:
            d, p = known[-1]
            snap = self._load(p)
            return date.fromisoformat(snap.get("date", d.isoformat())), snap["factors"]
        path = self.root / "data" / "factors.json"
        if path.is_file():
            written = datetime.fromtimestamp(os.path.getmtime(path)).date()
            if written <= as_of:
                return written, IdxMethodStocks(self.root).factors()
        raise SourceUnavailable(self.name, "missing",
                                f"no factors snapshot on or before {as_of} under {self.root}")

    def history(self) -> list[tuple[date, float]]:
        """(snapshot date, cap-weighted EY %) for every snapshot, oldest first."""
        out = []
        for d, p in self._dated():
            ey, _, _ = market_earnings_yield(self._load(p)["factors"])
            if ey is not None:
                out.append((d, ey))
        return out


# ---------------- reading ----------------


def _direction(value: float, band: float) -> int:
    return 1 if value >= band else -1 if value <= -band else 0


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
            lag = LAG.get(r.series_id)
            recorded = (r.as_of is not None or lag is None) and (
                r.as_of is None or r.as_of <= self.as_of)
            if recorded or (lag is not None and r.date + lag <= self.as_of):
                out[r.series_id].append(r)
        return out

    def add(self, name: str, value: float | None, direction: int, source: str, detail: str):
        self.signals.append(Signal(SUBJECT, ASSET, self.as_of, name, value, direction, source,
                                   detail))

    def last(self, rows: dict | None, sid: str, src: str, max_age: timedelta) -> Row | None:
        series = (rows or {}).get(sid, [])
        if not series:
            if rows is not None:
                self.stale.append(f"{src} {sid} (no data)")
            return None
        r = series[-1]
        if self.as_of - r.date > max_age:
            self.stale.append(f"{src} {sid} (last {r.date})")
        return r


def _ten_year(b: _Builder, phei: dict | None, dbn: dict | None) -> tuple[Row | None, bool]:
    """(newest 10Y row, proxy?): IGSYC 10Y, else dbnomics' OECD IDN long-term rate."""
    t10 = (phei or {}).get(IGSYC_10Y, [])
    if phei is not None and not t10:
        b.stale.append(f"{PHEI_NAME} {IGSYC_10Y} (no data)")
    if t10:
        ten = t10[-1]
        if b.as_of - ten.date > MAX_AGE["phei"]:
            b.stale.append(f"{PHEI_NAME} {IGSYC_10Y} (last {ten.date})")
        b.drivers.append(f"SBN 10Y from the IGSYC curve on {ten.date}")
        return ten, False
    proxy = (dbn or {}).get(PROXY_10Y, [])
    if not proxy:
        if dbn is not None:
            b.stale.append(f"dbnomics {PROXY_10Y} (no data)")
        return None, True
    ten = proxy[-1]
    b.stale.append(f"dbnomics {PROXY_10Y} (proxy for IGSYC 10Y, last {ten.date})")
    b.drivers.append(f"10Y is a proxy: OECD IDN long-term rate via dbnomics ({PROXY_10Y}),"
                     f" monthly average for {ten.date:%Y-%m}; no IGSYC curve")
    return ten, True


def _hurdle(b: _Builder, dbn: dict | None) -> float | None:
    """US ERP + IDN CRP in %, from their newest known points; `idn.erp.hurdle` as fallback."""
    if dbn is None:
        return None
    erp = (dbn.get(US_ERP) or [None])[-1]
    crp = (dbn.get(IDN_CRP) or [None])[-1]
    if erp is not None and crp is not None:
        for r, sid in ((erp, US_ERP), (crp, IDN_CRP)):
            if b.as_of - r.date > MAX_AGE[sid]:
                b.stale.append(f"dbnomics {sid} (last {r.date})")
        h = 100 * (erp.value + crp.value)
        b.drivers.append(f"hurdle {h:.2f}% (US ERP {100 * erp.value:.2f}% {erp.date:%Y-%m} + "
                         f"IDN CRP {100 * crp.value:.2f}% {crp.date:%Y-%m}; "
                         "Damodaran via dbnomics)")
        return h
    missing = [sid for sid, r in ((US_ERP, erp), (IDN_CRP, crp)) if r is None]
    der = b.last(dbn, HURDLE, "dbnomics", MAX_AGE[HURDLE])
    b.stale += [f"dbnomics {sid} (no data)" for sid in missing]
    if der is None:
        return None
    h = 100 * der.value
    b.drivers.append(f"hurdle {h:.2f}% (dbnomics {HURDLE} {der.date:%Y-%m})")
    return h


def _valuation(b: _Builder, ey: float | None, ten: Row | None, proxy: bool, cpi: Row | None,
               hurdle: float | None) -> tuple[int | None, dict]:
    out: dict = {"gap": None, "real": None, "implied": None}
    if ey is None or ten is None:
        return None, out
    gap = ey - ten.value
    out["gap"] = gap
    label = "10Y proxy" if proxy else "IGSYC 10Y"
    b.add("ey_vs_sbn", gap, _direction(gap, GAP_BAND), "dbnomics" if proxy else PHEI_NAME,
          f"JCI EY − {label} ({ten.date})")
    b.drivers.append(f"JCI EY − SBN 10Y {gap:+.2f}pt ({'proxy' if proxy else 'IGSYC'})")
    if cpi is None or hurdle is None:
        return None, out
    real = ten.value - cpi.value
    implied = ey + G_REAL - real
    diff = implied - hurdle
    out.update(real=real, implied=implied)
    direction = _direction(diff, ERP_BAND)
    detail = (f"implied ERP {implied:.2f}% = EY {ey:.2f}% + {G_REAL:.1f}% real growth − real "
              f"10Y {real:.2f}% (CPI {cpi.value:.2f}% {cpi.date:%Y-%m}); vs hurdle {hurdle:.2f}%")
    call_dir: int | None = direction
    if proxy and b.as_of - ten.date > PROXY_CALL_AGE:
        call_dir = None
        detail += f"; proxy from {ten.date:%Y-%m} too old to call"
        b.risks.append(f"valuation rests on a 10Y proxy from {ten.date:%Y-%m}")
    b.add("implied_erp_vs_hurdle", diff, direction if call_dir is not None else 0,
          "dbnomics" if proxy else PHEI_NAME, detail)
    word = {1: "cheap", 0: "fair", -1: "rich"}[direction]
    b.drivers.append(f"implied ERP {implied:.2f}% vs hurdle {hurdle:.2f}%: {diff:+.2f}pt ({word})")
    if direction < 0:
        b.risks.append("JCI rich against the US ERP + IDN CRP hurdle")
    return call_dir, out


def _earnings_yield(b: _Builder, snaps) -> tuple[float | None, float | None, date | None]:
    try:
        on, f = snaps.factors_on(b.as_of)
    except SourceUnavailable as e:
        b.stale.append(e.stale_input)
        return None, None, None
    b.sources.append(snaps.name)
    ey, n, cap = market_earnings_yield(f)
    if b.as_of - on > MAX_AGE["factors"]:
        b.stale.append(f"{snaps.name} factors snapshot (last {on})")
    if ey is None:
        b.stale.append(f"{snaps.name} factors snapshot {on} (no earnings yields)")
        return None, None, on
    pe = 100 / ey if ey > 0 else None
    pe_text = f"P/E {pe:.1f}" if pe else "negative aggregate earnings"
    b.drivers.append(f"JCI earnings yield {ey:.2f}% ({pe_text}; cap-weighted over {n} names, "
                     f"Rp {cap / 1e12:,.0f}T, idx-method snapshot {on})")
    return ey, pe, on


def _flows(b: _Builder, sig: IdnSignals) -> int | None:
    b.stale += [s for s in sig.stale_inputs if "SBN" not in s and "us_lt_bond" not in s]
    b.sources += list(sig.sources)
    got: dict[str, Signal] = {}
    for s in sig.for_asset(ASSET):
        b.signals.append(s)
        if s.detail:
            b.drivers.append(s.detail)
        got[s.name] = s
    idx, ksei = got.get("idx_foreign_flow"), got.get("ksei_foreign_share")
    if ksei is None:
        b.stale.append("foreign flow (no ksei_foreign_share signal)")
    elif ksei.direction < 0:
        b.risks.append("KSEI foreign ownership share falling")
    if idx is None:
        b.stale.append("foreign flow (no idx_foreign_flow signal)")
        return None
    if idx.direction < 0:
        b.risks.append("foreign investors net selling IDX stocks")
    net = idx.direction + (ksei.direction if ksei is not None else 0)
    return (net > 0) - (net < 0)


def _macro(b: _Builder, score: AssetScore | None, wbs, overrides: IdnOverrides | None
           ) -> tuple[int | None, float | None]:
    if score is None:
        try:
            score = (wbs or WorldbankscapeSource.from_config()).score(SUBJECT, ASSET)
        except SourceUnavailable as e:
            b.stale.append(e.stale_input)
            return None, None
        if score is None:
            b.stale.append(f"worldbankscape {SUBJECT} {ASSET} (no score)")
            return None, None
    if score.as_of > b.as_of:
        b.stale.append(f"{score.source} {SUBJECT} {ASSET} (as_of {score.as_of} after {b.as_of})")
        return None, None
    b.sources.append(score.source)
    b.stale += list(score.stale_inputs)
    ov = overrides.for_asset(ASSET) if overrides is not None else None
    if overrides is None:
        b.stale.append("overrides (not given)")
    elif ov is not None:
        b.stale += list(ov.stale_inputs)
    adjusted = apply(score, ov)
    direction = 1 if adjusted >= MACRO_HIGH else -1 if adjusted <= MACRO_LOW else 0
    shift = f" {ov.delta:+.0f} override" if ov is not None else ""
    detail = f"macro {adjusted:.1f} = layer-1 {score.score:.1f}{shift}"
    b.add("macro", adjusted, direction, score.source, detail)
    b.drivers.append(detail)
    if direction < 0:
        b.risks.append(f"macro headwind ({adjusted:.1f})")
    return direction, adjusted


def _jci(b: _Builder, src: Source) -> None:
    rows = b.read(src, [JCI], READ_BACK["jci"])
    if rows is None:
        return
    last = b.last(rows, JCI, src.name, timedelta.max)
    if last is None:
        return
    if b.as_of - last.date > MAX_AGE["jci"]:
        b.stale.append(f"{src.name} {JCI} (frozen, last {last.date})")
    b.drivers.append(f"JCI {last.value:,.0f} on {last.date}")


def idn_stocks(
    as_of: date,
    regime: Regime | None = None,
    overrides: IdnOverrides | None = None,
    signals: IdnSignals | None = None,
    score: AssetScore | None = None,
    *,
    phei: Source | None = None,
    dbnomics: Source | None = None,
    bps: Source | None = None,
    idxmethod: Source | None = None,
    snapshots: FactorSnapshots | None = None,
    worldbankscape: WorldbankscapeSource | None = None,
) -> IdnStocks:
    """The IDN stocks market rule on `as_of`. Sources default to the configured stores;
    `signals` defaults to P18's `idn_signals`, `score` to worldbankscape's IDN stocks. A store
    that is missing or locked is named in `stale_inputs`, never raised; a missing input makes it
    a no_call."""
    b = _Builder(as_of)
    phei_rows = b.read(phei or PheiSource.from_config(), [IGSYC_10Y], READ_BACK["monthly"])
    dbn_rows = b.read(dbnomics or DbnomicsSource.from_config(),
                      [PROXY_10Y, DBN_CPI, US_ERP, IDN_CRP, HURDLE], READ_BACK["crp"])
    bps_rows = b.read(bps or BpsLookerSource.from_config(), [CPI_YOY], READ_BACK["monthly"])

    ey, pe, on = _earnings_yield(b, snapshots or FactorSnapshots.from_config())
    ten, proxy = _ten_year(b, phei_rows, dbn_rows)
    cpi, _ = _cpi(b, bps_rows, dbn_rows, overrides)
    hurdle = _hurdle(b, dbn_rows)
    valuation, v = _valuation(b, ey, ten, proxy, cpi, hurdle)
    flows = _flows(b, signals if signals is not None else idn_signals(as_of))
    macro, adjusted = _macro(b, score, worldbankscape, overrides)
    _jci(b, idxmethod or IdxMethodIndexSource.from_config())

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

    call, stance = decide(valuation, flows, macro)
    if call != "enter":
        entry = dict(NO_ENTRY)
    elif regime is None or regime.state == "risk_off":
        entry = dict(LADDER)
    else:
        entry = dict(LUMP)
    return IdnStocks(
        as_of=as_of, call=call, proposed_stance=stance, entry=entry, signals=tuple(b.signals),
        earnings_yield=ey, pe=pe, factors_date=on, ey_gap=v["gap"], real_yield=v["real"],
        implied_erp=v["implied"], hurdle=hurdle, macro_score=adjusted,
        ten_year_source=None if ten is None else ("dbnomics proxy" if proxy else PHEI_NAME),
        regime=None if regime is None else regime.state,
        drivers=tuple(dict.fromkeys(b.drivers)), risks=tuple(dict.fromkeys(b.risks)),
        stale_inputs=tuple(dict.fromkeys(b.stale)), sources=tuple(dict.fromkeys(b.sources)),
    )
