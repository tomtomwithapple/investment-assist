"""IDR hurdle per market (PLAN S17): the annual IDR return a name must beat before it can be a
candidate. One function serves the index and single names: every name in a market is held to its
market's hurdle, moved only by the S16 sector shift in `margin`.

- **IDN**: SBN 10Y + US implied ERP + IDN CRP. The 10Y is IGSYC 10Y (idxscape PHEI, P32), else
  dbnomics' OECD IDN long-term rate (`idn.rate.long`), flagged a proxy in drivers and
  stale_inputs. ERP and CRP are the series, lags and fallback of the IDN stocks rule
  (`layers/rules/idn_stocks`: `us.erp.implied` + `idn.crp`, else `idn.erp.hurdle`), imported, not
  copied.
- **Foreign** (USA, JPN, EMU, AUS, SGP where the stores have them): the local 10Y + US ERP + that
  country's CRP, from P29's market specs (`layers/candidates_foreign.MARKETS`). The euro area has
  no CRP series, so Germany's (`deu.crp`) stands in, named in drivers. The investor is IDR-based
  and unhedged (no hedge cost, user decision 2026-10-27): P29's `expected_fx_move` (the adverse
  5% quantile of 1-year moves in IDR per local unit, else UIP) is the haircut. A foreign name's
  expected IDR return is `idr_return(expected_local)` (`fx.unhedged_idr_return`) and is held to
  `required`; `local_required` is the same bar in the local currency, (1 + required) /
  (1 + fx_move) − 1, and `components["fx_haircut"]` the gap between the two. The haircut is
  applied once: to the return, or equivalently to the bar in local terms, never to both.
- **Risk-off**: a risk-off regime (P8) adds `CONFIG["risk_off_premium_pt"]`. An unknown regime
  adds nothing and says so.

Everything is point in time (a row counts once its publication lag has passed) and in percent
points per year. A missing or locked store goes to stale_inputs; a market without its 10Y or
its ERP + CRP has `required` None. `CONFIG` is hand-set; this module is hashed into the model
fingerprint (`journal.RULE_GLOBS` covers `candidates/*.py`), so a change segments the journal.

PHEI is for the owner's local use only: drivers carry the IDN total, ERP and CRP, never the raw
IGSYC 10Y (it stays in `components`, which is not sent off this Mac).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from assist.fx import unhedged_idr_return
from assist.layers.bonds.idn import PROXY_10Y
from assist.layers.candidates_foreign import (
    FRACTION,
    IDR_PER_SGD,
    IDR_SHORT,
    PCT,
    FxSpec,
    Market,
    Ref,
    _cbpol,
    _dbn,
    _mas,
    _Reader,
    default_sources,
    expected_fx_move,
)
from assist.layers.candidates_foreign import market as foreign_market
from assist.layers.rules.idn_stocks import (
    HURDLE,
    IDN_CRP,
    LAG,
    MAX_AGE,
    PHEI_NAME,
    PROXY_CALL_AGE,
    US_ERP,
)
from assist.layers.types import Regime
from assist.sources.base import Source
from assist.sources.idxscape_phei import IGSYC_10Y

__all__ = [
    "CONFIG",
    "ERP_REFS",
    "HURDLE",
    "IDN_CRP",
    "US_ERP",
    "Hurdle",
    "hurdle",
    "hurdles",
    "margin",
]

CONFIG = {
    "risk_off_premium_pt": 1.0,  # added to every hurdle in a risk-off regime
    "sector_shift_max_pt": 2.0,  # S16: a sector's required margin moves by at most this
    "markets": ("IDN", "USA", "JPN", "EMU", "AUS", "SGP"),
    "emu_crp": "deu.crp",  # no euro-area CRP series; Germany's stands in
}


def _days(sid: str, table: Mapping) -> int:
    return table[sid].days


ERP_REFS = (Ref("dbnomics", US_ERP, FRACTION, _days(US_ERP, LAG), _days(US_ERP, MAX_AGE)),)
IDN_CRP_REFS = (Ref("dbnomics", IDN_CRP, FRACTION, _days(IDN_CRP, LAG), _days(IDN_CRP, MAX_AGE)),)
IDN_HURDLE_REFS = (Ref("dbnomics", HURDLE, FRACTION, _days(HURDLE, LAG), _days(HURDLE, MAX_AGE)),)
IGSYC_REF = Ref(PHEI_NAME, IGSYC_10Y, PCT, 0, MAX_AGE["phei"].days)
PROXY_REF = Ref("dbnomics", PROXY_10Y, PCT, _days(PROXY_10Y, LAG), PROXY_CALL_AGE.days)

EMU = Market(
    "EMU", "Euro area", "EMU", "EUR",
    yield_10y=(_dbn("ea20.rate.long"),),
    crp=(Ref("dbnomics", CONFIG["emu_crp"], FRACTION, 45, 450,
             note="Germany's CRP stands in for the euro area"),),
    short_rate=(_cbpol("XM"),),
    fx=FxSpec(IDR_PER_SGD, _mas("eur"), local_per_base=False),
)


def _market(subject: str) -> Market | None:
    """The P29 spec for a foreign market (EMU defined here); None for IDN."""
    if subject == "IDN":
        return None
    if subject == "EMU":
        return EMU
    return foreign_market(subject)


@dataclass(frozen=True)
class Hurdle:
    """The required annual IDR return for `market` on `as_of`, in percent points. `required` is
    what a name's expected IDR return (after the FX haircut) must beat; `local_required` the same
    bar in the market's own currency. None when an input is missing (see `stale_inputs`)."""

    market: str
    as_of: date
    currency: str
    regime: str | None
    required: float | None
    local_required: float | None
    components: dict[str, float] = field(default_factory=dict)
    fx_move: float | None = None  # expected 1-year change in IDR per local unit, fraction
    fx_basis: str = ""
    ten_year_source: str | None = None  # "igsyc" | "proxy" | the series label
    drivers: tuple[str, ...] = ()
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    @property
    def stale(self) -> bool:
        return bool(self.stale_inputs)

    def idr_return(self, expected_local: float) -> float | None:
        """A local-currency expected return (pt) in IDR, unhedged, after the expected FX move."""
        if self.currency == "IDR":
            return expected_local
        if self.fx_move is None:
            return None
        return 100 * unhedged_idr_return(expected_local / 100, self.fx_move)


def margin(expected_idr: float | None, hurdle: Hurdle | float | None,
           sector_shift_pt: float = 0.0) -> float | None:
    """Expected IDR return − (hurdle + sector shift), in pt. The shift (S16) is clamped to
    ±`CONFIG["sector_shift_max_pt"]`. None when either side is unknown."""
    required = hurdle.required if isinstance(hurdle, Hurdle) else hurdle
    if expected_idr is None or required is None:
        return None
    cap = CONFIG["sector_shift_max_pt"]
    return expected_idr - required - max(-cap, min(cap, sector_shift_pt))


def _regime_state(regime: Regime | str | None) -> str | None:
    return regime.state if isinstance(regime, Regime) else regime


def _refs(subjects: Sequence[str]) -> list[Ref]:
    refs = [*ERP_REFS, *IDR_SHORT]
    for s in subjects:
        m = _market(s)
        if m is None:
            refs += [IGSYC_REF, PROXY_REF, *IDN_CRP_REFS, *IDN_HURDLE_REFS]
            continue
        refs += [*m.yield_10y, *m.crp, *m.short_rate]
        if m.fx is not None:
            refs += m.fx.refs
    return refs


class _Build:
    """One market's hurdle as it is put together."""

    def __init__(self, rd: _Reader, subject: str):
        self.rd, self.subject = rd, subject
        self.components: dict[str, float] = {}
        self.drivers: list[str] = []
        self.stale: list[str] = []
        self.used: set[str] = set()

    def pick(self, refs: Sequence[Ref]):
        """(newest known row, its ref) of the first ref with data, named stale if too old."""
        for ref in refs:
            rows = self.rd.series(ref)
            if rows:
                last = rows[-1]
                if (self.rd.as_of - last.date).days > ref.max_age_days:
                    self.stale.append(f"{ref.label} (stale, last {last.date})")
                self.used.add(ref.source)
                return last, ref
        return None, None

    def missing(self, what: str, refs: Sequence[Ref]) -> None:
        self.stale.append(f"{self.subject} {what}: no data ({', '.join(r.label for r in refs)})")


def _premium(b: _Build, state: str | None) -> float:
    if state is None:
        b.drivers.append("regime unknown: no risk-off premium")
        return 0.0
    if state == "risk_off":
        p = CONFIG["risk_off_premium_pt"]
        b.drivers.append(f"risk-off regime: +{p:.2f}pt")
        return p
    return 0.0


def _erp(b: _Build) -> float | None:
    row, _ = b.pick(ERP_REFS)
    if row is None:
        return None
    b.components["us_erp"] = 100 * row.value
    return 100 * row.value


def _idn(b: _Build, state: str | None) -> Hurdle:
    rd = b.rd
    ten, ref = b.pick((IGSYC_REF,))
    source = "igsyc"
    if ten is None:
        b.stale.append(f"{PHEI_NAME} {IGSYC_10Y} (no data)")
        ten, ref = b.pick((PROXY_REF,))
        source = "proxy"
        if ten is not None:
            b.stale.append(f"dbnomics {PROXY_10Y} (proxy for IGSYC 10Y, last {ten.date})")
            b.drivers.append("10Y is a proxy: OECD IDN long-term rate via dbnomics "
                             f"({PROXY_10Y}, {ten.date:%Y-%m})")
    if ten is None:
        b.missing("10Y", (IGSYC_REF, PROXY_REF))
    else:
        b.components["ten_year"] = 100 * ten.value

    erp = _erp(b)
    crp_row, _ = b.pick(IDN_CRP_REFS)
    premium_text = ""
    if erp is not None and crp_row is not None:
        b.components["crp"] = 100 * crp_row.value
        premium_text = (f"US ERP {erp:.2f}% + IDN CRP {100 * crp_row.value:.2f}% "
                        f"({crp_row.date:%Y-%m})")
    else:
        b.stale += [f"dbnomics {sid} (no data)"
                    for sid, v in ((US_ERP, erp), (IDN_CRP, crp_row)) if v is None]
        b.components.pop("us_erp", None)
        h_row, _ = b.pick(IDN_HURDLE_REFS)
        if h_row is not None:
            b.components["erp_hurdle"] = 100 * h_row.value
            premium_text = f"ERP + CRP {100 * h_row.value:.2f}% (dbnomics {HURDLE})"
        else:
            b.missing("ERP + CRP", (*ERP_REFS, *IDN_CRP_REFS, *IDN_HURDLE_REFS))

    b.components["risk_off"] = _premium(b, state)
    required = None
    if ten is not None and premium_text:
        required = sum(b.components.values())
        b.drivers.insert(0, f"IDN hurdle {required:.2f}% = SBN 10Y ({source}) + {premium_text}"
                            " (Damodaran via dbnomics)")
    return Hurdle(
        market="IDN", as_of=rd.as_of, currency="IDR", regime=state, required=required,
        local_required=required, components=b.components, fx_move=None, fx_basis="",
        ten_year_source=source if ten is not None else None, drivers=tuple(b.drivers),
        stale_inputs=tuple(dict.fromkeys(b.stale)), sources=tuple(sorted(b.used)),
    )


def _foreign(b: _Build, m: Market, state: str | None, i_idr: float | None) -> Hurdle:
    rd = b.rd
    ten, ten_ref = b.pick(m.yield_10y) if m.yield_10y else (None, None)
    if ten is None:
        b.missing("10Y", m.yield_10y)
    else:
        b.components["ten_year"] = 100 * ten.value
    erp = _erp(b)
    if erp is None:
        b.missing("US ERP", ERP_REFS)
    crp, crp_ref = b.pick(m.crp) if m.crp else (None, None)
    if crp is None:
        b.missing("CRP", m.crp)
    else:
        b.components["crp"] = 100 * crp.value
        if crp_ref.note:
            b.drivers.append(f"{crp_ref.note} ({crp_ref.label})")
    b.components["risk_off"] = _premium(b, state)

    fx_move, fx_basis = None, ""
    if m.fx is not None:
        short, _ = b.pick(m.short_rate) if m.short_rate else (None, None)
        fx_move, fx_basis = expected_fx_move(rd.fx(m.fx), rd.as_of, i_idr,
                                             None if short is None else short.value)
    if fx_move is None:
        b.missing("fx", m.fx.refs if m.fx is not None else ())
    elif fx_basis.startswith("adverse"):
        b.used |= {r.source for r in m.fx.refs}

    required = local_required = None
    if ten is not None and erp is not None and crp is not None:
        required = sum(b.components.values())
        b.drivers.insert(0, f"{m.subject} hurdle {required:.2f}% = 10Y {100 * ten.value:.2f}%"
                            f" ({ten_ref.label}, {ten.date}) + US ERP {erp:.2f}%"
                            f" + CRP {100 * crp.value:.2f}%")
        if fx_move is not None:
            local_required = 100 * ((1 + required / 100) / (1 + fx_move) - 1)
            b.components["fx_haircut"] = local_required - required
            b.drivers.append(f"FX haircut: {m.currency} {fx_move:+.2%} vs IDR ({fx_basis}); "
                             f"{m.currency} return needed {local_required:.2f}%")
    return Hurdle(
        market=m.subject, as_of=rd.as_of, currency=m.currency, regime=state, required=required,
        local_required=local_required, components=b.components, fx_move=fx_move,
        fx_basis=fx_basis, ten_year_source=None if ten_ref is None else ten_ref.label,
        drivers=tuple(b.drivers), stale_inputs=tuple(dict.fromkeys(b.stale)),
        sources=tuple(sorted(b.used)),
    )


def hurdles(
    markets: Sequence[str] = CONFIG["markets"],
    as_of: date | None = None,
    regime: Regime | str | None = None,
    *,
    sources: Mapping[str, Source] | None = None,
) -> list[Hurdle]:
    """The hurdle of each market in `markets`, reading every store once."""
    if as_of is None:
        raise ValueError("as_of is required")
    subjects = list(markets)
    specs = {s: _market(s) for s in subjects}  # KeyError on an unknown market
    rd = _Reader(default_sources() if sources is None else sources, as_of, _refs(subjects))
    state = _regime_state(regime)
    shared = _Build(rd, "IDN")
    idr_short, _ = shared.pick(IDR_SHORT)
    i_idr = None if idr_short is None else idr_short.value
    out = []
    for s in subjects:
        b = _Build(rd, s)
        own = {r.source for r in _refs([s])}
        b.stale += [e for e in rd.stale if e.split(" ", 1)[0] in own]  # stores not read
        m = specs[s]
        out.append(_idn(b, state) if m is None else _foreign(b, m, state, i_idr))
    return out


def hurdle(
    market: str,
    as_of: date,
    regime: Regime | str | None = None,
    *,
    sources: Mapping[str, Source] | None = None,
) -> Hurdle:
    """The required annual IDR return for `market` ("IDN", "USA", "JPN", "EMU", "AUS", "SGP")."""
    return hurdles([market], as_of, regime, sources=sources)[0]
