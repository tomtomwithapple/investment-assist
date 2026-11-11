"""Layer 4, foreign candidates at index level (PLAN S12): one broad index per market (S&P 500,
TOPIX, ASX 200, STI, KOSPI, TAIEX), valued against a hurdle and tested in IDR.

For each market, as of a date (point in time: a row counts once it is recorded by `as_of`, or once
it is older than its publication lag):

- **Earnings yield** `EY`: 1 / CAPE or 1 / P/E (`INVERSE`), or a yield given directly.
- **Yield gap** = EY − local 10Y. **Hurdle** = US implied ERP (Damodaran, dbnomics
  `us.erp.implied`) + the country's rating-based CRP (dbnomics `<iso3>.crp`, Damodaran snapshots,
  published ~6 weeks after their date). **Valuation edge** = gap − hurdle: positive means the
  index pays more over its local bond than a US-style ERP plus country risk asks for.
- **IDR test** (CLAUDE.md: overweight only if the edge survives the expected FX move), with P27's
  `fx_edge` over one year: the local return is EY + local CPI y/y (earnings yield as a real return
  plus inflation); the IDR alternative is the IDN 10Y (PHEI curve, else dbnomics' OECD rate); the
  expected FX move is the adverse one, the 5th percentile of every 1-year change in IDR per local
  unit over the last 5 years (needs 2 years of history), else uncovered parity from the short
  rates; the hedge uses the policy or 3-month rates (BIS `WS_CBPOL`, SORA for SGP).
- **Score** (0–100, 50 neutral) = 50 + 5 points per percentage point of valuation edge, clamped,
  and capped at 50 when the IDR test fails. `passes` needs edge > 0 and an IDR test that
  survives; an unknown IDR test does not pass. The bands are hand-set: none of this may change a
  stance until it beats its placebo (P9).

An input is a list of `Ref`s tried in order (first one with a known value wins). Nothing is
invented: a missing store, series or value goes to `stale_inputs`, and a market without its
valuation inputs names no candidate. A value older than its `max_age_days` is still used and is
named stale. Inputs no store has yet are listed in `Market.gaps` with the fetcher that would add
them (docs/results/P29-candidates-foreign.md); live, only the US has a valuation (Shiller CAPE).
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from assist.doctor import DEFAULT_CONFIG
from assist.fx import FxEdge, cross, fx_edge, horizon_changes, level_at, uip_expected_move
from assist.layers.types import Candidate
from assist.sources import ausdata, idxscape, jquantster, openkrx, singstat
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.idxscape_phei import IGSYC_10Y, SUN_10Y, SUN_SOURCE

__all__ = [
    "FRACTION",
    "INDEX_YOY",
    "INVERSE",
    "LEVEL",
    "MARKETS",
    "PCT",
    "SCREEN",
    "ForeignCandidates",
    "FxSpec",
    "IndexValuation",
    "Market",
    "Ref",
    "assess",
    "default_sources",
    "expected_fx_move",
    "foreign_candidates",
    "market",
]

ASSET = "stocks"
SCREEN = "index_valuation"
YEARS = 1.0  # horizon of the IDR test
POINTS_PER_PP = 5.0  # score points per percentage point of valuation edge
HISTORY = timedelta(days=365 * 6)  # how far back each store is read
FX_WINDOW = timedelta(days=365 * 5)  # 1-year FX changes taken over this window
FX_MIN_HISTORY = timedelta(days=365 * 2)  # less than this → UIP instead of the adverse move
FX_QUANTILE = 0.05

# Units: how a stored value becomes what the layer uses.
PCT = "pct"  # percent per year (4.5) → fraction
FRACTION = "fraction"  # already a fraction (0.037)
INVERSE = "inverse"  # 1 / value: CAPE or P/E → earnings yield; S$ per IDR → IDR per S$
INDEX_YOY = "index_yoy"  # a price index → its change over 12 months
LEVEL = "level"  # as stored (index closes)


@dataclass(frozen=True)
class Ref:
    """One stored series feeding an input. A row dated d is known on d + `lag_days` (or once its
    store recorded it); a newest known row older than `max_age_days` is used but named stale."""

    source: str
    series_id: str
    unit: str = PCT
    lag_days: int = 0
    max_age_days: int = 100
    note: str = ""  # e.g. the valuation basis, "CAPE"

    @property
    def label(self) -> str:
        return f"{self.source} {self.series_id}"


@dataclass(frozen=True)
class FxSpec:
    """IDR per local unit: `base` is IDR per unit of a base currency (USD, SGD, or the local one
    itself); `leg` the local currency against that base, quoted local per base (USD/JPY) or base
    per local (`local_per_base=False`, S$ per KRW)."""

    base: Ref
    leg: Ref | None = None
    local_per_base: bool = True

    @property
    def refs(self) -> tuple[Ref, ...]:
        return (self.base,) if self.leg is None else (self.base, self.leg)


@dataclass(frozen=True)
class Market:
    """One foreign market's broad index and where each input comes from."""

    subject: str
    index: str
    symbol: str
    currency: str
    valuation: tuple[Ref, ...] = ()
    yield_10y: tuple[Ref, ...] = ()
    inflation: tuple[Ref, ...] = ()
    crp: tuple[Ref, ...] = ()
    short_rate: tuple[Ref, ...] = ()
    fx: FxSpec | None = None
    level: tuple[Ref, ...] = ()  # index close, context only
    gaps: tuple[tuple[str, str], ...] = ()  # input → which fetcher would add it


# ---------------- where the inputs live (as of 2026-10-23) ----------------

DAILY = 10  # max age for daily series, days
WEEKLY_DAILY = 21  # daily series refreshed weekly (singstat)
MONTHLY = 100  # monthly series dated at the start of their month


def _dbn(series_id: str, unit: str = PCT, lag: int = 35, max_age: int = MONTHLY) -> Ref:
    """dbnomics: OECD monthly averages dated at the month start, known after it ends."""
    return Ref("dbnomics", series_id, unit, lag, max_age)


def _cpi(iso3: str) -> Ref:
    return _dbn(f"{iso3}.cpi.yoy", lag=45, max_age=110)


def _crp(iso3: str) -> Ref:
    return Ref("dbnomics", f"{iso3}.crp", FRACTION, lag_days=45, max_age_days=450)


def _cbpol(iso2: str) -> Ref:
    return Ref("bisfetcher", f"WS_CBPOL.M.{iso2}", PCT, lag_days=31, max_age_days=MONTHLY)


US_ERP = (Ref("dbnomics", "us.erp.implied", FRACTION, 0, MONTHLY),)
IDR_10Y = (Ref("idxscape_phei", IGSYC_10Y, PCT, 0, DAILY), Ref(SUN_SOURCE, SUN_10Y, PCT, 0, DAILY),
           _dbn("idn.rate.long"))
IDR_SHORT = (_cbpol("ID"),)
JISDOR = Ref("idxscape", idxscape.JISDOR, LEVEL, 0, DAILY)
IDR_PER_SGD = Ref("singstat", singstat.fx_id("IDR"), INVERSE, 0, WEEKLY_DAILY)


def _mas(ccy: str) -> Ref:
    return Ref("singstat", singstat.fx_id(ccy), LEVEL, 0, WEEKLY_DAILY)


MARKETS: tuple[Market, ...] = (
    Market(
        "USA", "S&P 500", "SPX", "USD",
        valuation=(Ref("dbnomics", "us.cape", INVERSE, 0, MONTHLY, note="CAPE"),),
        yield_10y=(_dbn("usa.rate.long"),),
        inflation=(_cpi("usa"),),
        crp=(_crp("usa"),),
        short_rate=(_cbpol("US"),),
        fx=FxSpec(JISDOR),
    ),
    Market(
        "JPN", "TOPIX", "TOPIX", "JPY",
        yield_10y=(Ref("jquantster", jquantster.JGB_10Y, PCT, 0, DAILY), _dbn("jpn.rate.long")),
        crp=(_crp("jpn"),),
        short_rate=(_cbpol("JP"), Ref("jquantster", jquantster.CALL_RATE, PCT, 0, DAILY)),
        fx=FxSpec(JISDOR, Ref("jquantster", jquantster.USDJPY, LEVEL, 0, DAILY)),
        gaps=(
            ("valuation", "jquantster has per-stock bars and EPS only (J-Quants Free plan); "
                          "jquantster would add a TOPIX level with index EPS or P/E"),
            ("inflation", "dbnomics has no jpn.cpi.yoy (OECD CPI covers USA, AUS, KOR, IDN, "
                          "CHN) and jquantster has no CPI; dbnomics would add it"),
        ),
    ),
    Market(
        "AUS", "S&P/ASX 200", "XJO", "AUD",
        yield_10y=(Ref("ausdata", ausdata.AGS_10Y, PCT, 0, DAILY), _dbn("aus.rate.long")),
        inflation=(_cpi("aus"), Ref("ausdata", ausdata.CPI_YY_M, PCT, 45, 110)),
        crp=(_crp("aus"),),
        short_rate=(_cbpol("AU"), Ref("ausdata", ausdata.CASH_RATE, PCT, 0, DAILY)),
        fx=FxSpec(Ref("ausdata", ausdata.AUD_IDR, LEVEL, 0, DAILY)),
        gaps=(("valuation", "no store has an ASX 200 level or P/E; ausdata would add one"),),
    ),
    Market(
        "SGP", "Straits Times Index", "STI", "SGD",
        yield_10y=(Ref("singstat", singstat.SGS_10Y, PCT, 0, WEEKLY_DAILY),),
        inflation=(Ref("singstat", singstat.CPI, INDEX_YOY, 30, 110),),
        crp=(_crp("sgp"),),
        short_rate=(Ref("singstat", singstat.SORA_3M, PCT, 0, WEEKLY_DAILY),),
        fx=FxSpec(IDR_PER_SGD),
        gaps=(("valuation", "singstat holds no STI level or P/E; singstat (or an SGX "
                            "fetcher) would add one"),),
    ),
    Market(
        "KOR", "KOSPI", "KOSPI", "KRW",
        yield_10y=(_dbn("kor.rate.long"),),
        inflation=(_cpi("kor"),),
        crp=(_crp("kor"),),
        short_rate=(_cbpol("KR"),),
        fx=FxSpec(IDR_PER_SGD, _mas("krw"), local_per_base=False),
        level=(Ref("openkrx", openkrx.KOSPI, LEVEL, 0, DAILY),),
        gaps=(("valuation", "openkrx has no index Parquet yet and its krx_index_daily (spec "
                            "§4) has closes only; openkrx would add KRX index PER"),),
    ),
    Market(
        "TWN", "TAIEX", "TAIEX", "TWD",
        crp=(_crp("twn"),),
        fx=FxSpec(IDR_PER_SGD, _mas("twd"), local_per_base=False),
        level=(Ref("openkrx", openkrx.TAIEX, LEVEL, 0, DAILY),),
        gaps=(
            ("valuation", "openkrx tw_index (TWSE MI_INDEX) has closes only, not yet on disk; "
                          "openkrx would add TWSE index P/E"),
            ("yield_10y", "no store has a Taiwan 10Y (not in OECD); openkrx or dbnomics "
                          "would add it"),
            ("inflation", "no store has Taiwan CPI (not in OECD); dbnomics would add it"),
            ("short_rate", "no store has the CBC policy rate (not in BIS WS_CBPOL); "
                           "bisfetcher or dbnomics would add it"),
        ),
    ),
)


def market(subject: str) -> Market:
    for m in MARKETS:
        if m.subject == subject:
            return m
    raise KeyError(subject)


# ---------------- the pure core ----------------


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


@dataclass(frozen=True)
class IndexValuation:
    """One market's index valued against its hurdle, with the IDR test when its inputs exist.
    Rates and yields are fractions."""

    market: Market
    as_of: date
    earnings_yield: float
    basis: str
    yield_10y: float
    us_erp: float
    crp: float
    inflation: float | None = None
    r_idr: float | None = None
    fx_move: float | None = None
    fx_basis: str = ""
    i_idr: float | None = None
    i_local: float | None = None
    level: float | None = None
    sources: tuple[str, ...] = ()

    @property
    def gap(self) -> float:
        return self.earnings_yield - self.yield_10y

    @property
    def hurdle(self) -> float:
        return self.us_erp + self.crp

    @property
    def edge(self) -> float:
        return self.gap - self.hurdle

    @property
    def r_local(self) -> float | None:
        return None if self.inflation is None else self.earnings_yield + self.inflation

    @property
    def fx(self) -> FxEdge | None:
        if self.r_local is None or self.r_idr is None or self.fx_move is None:
            return None
        hedge = self.i_idr is not None and self.i_local is not None
        return fx_edge(self.r_local, self.r_idr, self.fx_move,
                       self.i_idr if hedge else None, self.i_local if hedge else None, YEARS)

    @property
    def score(self) -> float:
        s = _clamp(50 + POINTS_PER_PP * self.edge * 100)
        fx = self.fx
        return min(s, 50.0) if fx is not None and not fx.survives else s

    @property
    def passes(self) -> bool:
        fx = self.fx
        return self.edge > 0 and fx is not None and fx.survives

    def detail(self) -> str:
        m = self.market
        text = (
            f"{m.index}: {self.basis} earnings yield {self.earnings_yield:.2%} − 10Y"
            f" {self.yield_10y:.2%} = gap {self.gap:+.2%} vs hurdle {self.hurdle:.2%}"
            f" (US ERP {self.us_erp:.2%} + CRP {self.crp:.2%}): edge {self.edge:+.2%}"
        )
        fx = self.fx
        if fx is None:
            missing = [n for n, v in (("local CPI", self.inflation), ("IDR 10Y", self.r_idr),
                                      ("FX move", self.fx_move)) if v is None]
            text += f"; IDR edge unknown (missing {', '.join(missing)})"
        else:
            text += f"; {m.currency} return EY + CPI {fx.r_local:.2%}, {fx.detail()}"
            text += f" [fx: {self.fx_basis}]"
        if self.level is not None:
            text += f"; level {self.level:,.2f}"
        return text

    def candidate(self) -> Candidate:
        return Candidate(
            subject=self.market.subject,
            asset=ASSET,
            as_of=self.as_of,
            symbol=self.market.symbol,
            screen=SCREEN,
            score=round(self.score, 1),
            source="+".join(self.sources) or "assist",
            detail=self.detail(),
        )


def assess(
    market: Market,
    as_of: date,
    *,
    earnings_yield: float,
    basis: str,
    yield_10y: float,
    us_erp: float,
    crp: float,
    inflation: float | None = None,
    r_idr: float | None = None,
    fx_move: float | None = None,
    fx_basis: str = "",
    i_idr: float | None = None,
    i_local: float | None = None,
    level: float | None = None,
    sources: Sequence[str] = (),
) -> IndexValuation:
    """Value one index from inputs already read (fractions)."""
    return IndexValuation(
        market, as_of, earnings_yield, basis, yield_10y, us_erp, crp, inflation, r_idr,
        fx_move, fx_basis, i_idr, i_local, level, tuple(sources),
    )


def _quantile(values: list[float], q: float) -> float:
    """Linear interpolation between order statistics (numpy's default)."""
    s = sorted(values)
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def expected_fx_move(
    idr_per_local: Sequence[Row],
    as_of: date,
    i_idr: float | None = None,
    i_local: float | None = None,
) -> tuple[float | None, str]:
    """(expected 1-year change in IDR per local unit, how it was set). The adverse case, the 5th
    percentile of every 1-year change over the last 5 years, when there are 2 years of history;
    else uncovered parity from the short rates; else (None, "")."""
    rows = [r for r in idr_per_local
            if r.value is not None and as_of - FX_WINDOW <= r.date <= as_of]
    if rows and min(r.date for r in rows) <= as_of - FX_MIN_HISTORY:
        changes = horizon_changes(rows, 365)
        if changes:
            first = min(r.date for r in rows)
            basis = f"adverse 1y move, 5th pct of {len(changes)} since {first}"
            return _quantile(changes, FX_QUANTILE), basis
    if i_idr is not None and i_local is not None:
        return (uip_expected_move(i_idr, i_local, YEARS),
                f"UIP (IDR {i_idr:.2%} vs local {i_local:.2%})")
    return None, ""


# ---------------- reading the stores ----------------


def _known(rows: Sequence[Row], ref: Ref, as_of: date) -> list[Row]:
    """Non-null rows of `ref` known on `as_of`, by date."""
    lag = timedelta(days=ref.lag_days)
    return sorted(
        (r for r in rows
         if r.value is not None and r.date <= as_of
         and (r.date + lag <= as_of or (r.as_of is not None and r.as_of <= as_of))),
        key=lambda r: r.date,
    )


def _convert(ref: Ref, rows: list[Row]) -> list[Row]:
    if ref.unit == PCT:
        return [r._replace(value=r.value / 100) for r in rows]
    if ref.unit == INVERSE:
        return [r._replace(value=1 / r.value) for r in rows if r.value]
    if ref.unit == INDEX_YOY:
        out = []
        for r in rows:
            d = r.date
            try:
                back = d.replace(year=d.year - 1)
            except ValueError:  # 29 February
                back = d.replace(year=d.year - 1, day=28)
            base = level_at(rows, back, max_age_days=31)
            if base:
                out.append(r._replace(value=r.value / base - 1))
        return out
    return rows


class _Reader:
    """Reads each store once (every series any market needs), then answers per `Ref`."""

    def __init__(self, sources: Mapping[str, Source], as_of: date, refs: Sequence[Ref]):
        self.as_of = as_of
        self.stale: list[str] = []
        self.read: list[str] = []
        self.rows: dict[str, list[Row]] = defaultdict(list)
        wanted: dict[str, set[str]] = defaultdict(set)
        for ref in refs:
            wanted[ref.source].add(ref.series_id)
        for name in sorted(wanted):
            src = sources.get(name)
            if src is None:
                self.stale.append(f"{name} (not configured)")
                continue
            try:
                found = src.rows(sorted(wanted[name]), as_of - HISTORY, as_of)
            except SourceUnavailable as e:
                self.stale.append(e.stale_input)
                continue
            self.read.append(name)
            for r in found:
                self.rows[f"{name}\0{r.series_id}"].append(r)

    def series(self, ref: Ref) -> list[Row]:
        """The ref's known rows, converted to its unit."""
        rows = self.rows.get(f"{ref.source}\0{ref.series_id}", [])
        return _convert(ref, _known(rows, ref, self.as_of))

    def value(self, refs: Sequence[Ref]) -> tuple[float, Ref] | None:
        """The newest known value of the first ref that has one; stale if too old."""
        for ref in refs:
            rows = self.series(ref)
            if rows:
                last = rows[-1]
                if (self.as_of - last.date).days > ref.max_age_days:
                    self.stale.append(f"{ref.label} (stale, last {last.date})")
                return last.value, ref
        return None

    def fx(self, spec: FxSpec) -> list[Row]:
        base = self.series(spec.base)
        if spec.leg is None:
            return base
        return cross(base, self.series(spec.leg), local_per_usd=spec.local_per_base)


def _all_refs(markets: Sequence[Market]) -> list[Ref]:
    refs = [*US_ERP, *IDR_10Y, *IDR_SHORT]
    for m in markets:
        refs += [*m.valuation, *m.yield_10y, *m.inflation, *m.crp, *m.short_rate, *m.level]
        if m.fx is not None:
            refs += m.fx.refs
    return refs


def _value_market(m: Market, rd: _Reader, common: dict) -> IndexValuation | None:
    used: set[str] = set()
    got: dict[str, float | None] = {}
    basis = ""
    for name in ("valuation", "yield_10y", "crp", "inflation", "short_rate", "level"):
        refs: tuple[Ref, ...] = getattr(m, name)
        if not refs:
            if name != "level":
                gap = dict(m.gaps).get(name, "no store has it")
                rd.stale.append(f"{m.subject} {ASSET} {name}: no source ({gap})")
            got[name] = None
            continue
        hit = rd.value(refs)
        if hit is None:
            if name != "level":
                labels = ", ".join(r.label for r in refs)
                rd.stale.append(f"{m.subject} {ASSET} {name}: no data ({labels})")
            got[name] = None
            continue
        got[name], ref = hit
        used.add(ref.source)
        if name == "valuation":
            basis = ref.note or ref.series_id

    i_idr, i_local = common["i_idr"], got["short_rate"]
    fx_move, fx_basis = None, ""
    if m.fx is not None:
        fx_rows = rd.fx(m.fx)
        fx_move, fx_basis = expected_fx_move(fx_rows, rd.as_of, i_idr, i_local)
        if fx_move is None:
            labels = ", ".join(r.label for r in m.fx.refs)
            rd.stale.append(f"{m.subject} {ASSET} fx: no data ({labels})")
        elif fx_basis.startswith("adverse"):
            used |= {r.source for r in m.fx.refs}

    required = {"valuation": got["valuation"], "yield_10y": got["yield_10y"],
                "us_erp": common["us_erp"], "crp": got["crp"]}
    if any(v is None for v in required.values()):
        return None
    for key in ("us_erp", "r_idr", "i_idr"):
        if common[key] is not None:
            used.add(common[f"{key}_source"])
    return assess(
        m, rd.as_of,
        earnings_yield=got["valuation"], basis=basis, yield_10y=got["yield_10y"],
        us_erp=common["us_erp"], crp=got["crp"], inflation=got["inflation"],
        r_idr=common["r_idr"], fx_move=fx_move, fx_basis=fx_basis,
        i_idr=i_idr, i_local=i_local, level=got["level"], sources=sorted(used),
    )


@dataclass(frozen=True)
class ForeignCandidates:
    """Layer 4 abroad: one valuation per market that has its inputs, the inputs missing or
    stale, and the stores read."""

    as_of: date
    valuations: tuple[IndexValuation, ...]
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        return tuple(v.candidate() for v in self.valuations)

    def ranked(self) -> list[Candidate]:
        """Candidates by score, then edge, best first."""
        order = sorted(self.valuations, key=lambda v: (v.score, v.edge), reverse=True)
        return [v.candidate() for v in order]

    def passing(self) -> list[Candidate]:
        return [v.candidate() for v in self.valuations if v.passes]

    def for_subject(self, subject: str) -> list[Candidate]:
        return [c for c in self.candidates if c.subject == subject]


def foreign_candidates(
    as_of: date,
    sources: Mapping[str, Source],
    markets: Sequence[Market] = MARKETS,
) -> ForeignCandidates:
    """Value each market's index as of `as_of` from the stores in `sources` (keyed by store
    name: dbnomics, idxscape, idxscape_phei, bisfetcher, jquantster, ausdata, singstat, openkrx).
    A store not given is reported `(not configured)`."""
    rd = _Reader(sources, as_of, _all_refs(markets))
    common: dict = {}
    for key, what, refs in (("us_erp", "US ERP", US_ERP), ("r_idr", "IDN 10Y", IDR_10Y),
                            ("i_idr", "IDN short rate", IDR_SHORT)):
        hit = rd.value(refs)
        common[key] = None if hit is None else hit[0]
        common[f"{key}_source"] = None if hit is None else hit[1].source
        if hit is None:
            rd.stale.append(f"{what}: no data ({', '.join(r.label for r in refs)})")
    valuations = [v for m in markets if (v := _value_market(m, rd, common)) is not None]
    return ForeignCandidates(
        as_of=as_of,
        valuations=tuple(valuations),
        stale_inputs=tuple(dict.fromkeys(rd.stale)),
        sources=tuple(rd.read),
    )


def default_sources(config: Path = DEFAULT_CONFIG, env: dict | None = None) -> dict[str, Source]:
    """Every store this layer reads, built from `config/sources.yaml`."""
    from assist.sources.ausdata import AusdataSource
    from assist.sources.bisfetcher import BisfetcherSource
    from assist.sources.dbnomics import DbnomicsSource
    from assist.sources.idxscape import IdxscapeSource
    from assist.sources.idxscape_phei import PheiSource
    from assist.sources.jquantster import JquantsterSource
    from assist.sources.openkrx import OpenkrxSource
    from assist.sources.singstat import SingstatSource

    env = {**os.environ, **(env or {})}
    out: dict[str, Source] = {}
    for cls in (DbnomicsSource, IdxscapeSource, PheiSource, BisfetcherSource, JquantsterSource,
                AusdataSource, SingstatSource, OpenkrxSource):
        src = cls.from_config(config=config, env=env)
        out[src.name] = src
    out[SUN_SOURCE] = out[PheiSource.name]  # the SUN 10Y, read apart (migration 11)
    return out
