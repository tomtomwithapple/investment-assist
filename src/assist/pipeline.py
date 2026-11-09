"""`assist run`: read the layers, build the stances, write out/, journal, brief, notify.

Phase A (PLAN S5–S6) wires layers 0, 1 and 5:

    worldbankscape (layer 1) ─┐
    sec-edgar FRED → regime (0) ├─ stance.build_stance ─→ out/{SUBJECT}/{asset}.json
    financer → weights (5) ────┘        │                  journal/decisions.jsonl
                                        └─→ brief (data/briefs/<day>.md) → Telegram once a day

Every step that reads a store degrades instead of failing: a missing regime or portfolio is named
in `stale_inputs` (and lowers confidence inside the stance). Only a missing layer 1 stops the
run, because without a score there is no stance; out/ is then left as it was.

Phase B (F2) adds Indonesia's layers 2–4 when `Sources.idn` is set (`Sources.default` sets it):

    bps-looker, bisfetcher, dbnomics → overrides (2) ─┐
    idxscape, kseistat, TIC → signals (3) ────────────┼→ IDN bonds rule, IDN stocks rule
    PHEI/dbnomics 10Y, CPI, JISDOR, snapshots, JCI ───┘        │ gated_stance(verdict)
    idx-method screens + costs + entry levels → candidates (4) ┴→ RuleView → build_stance

The overrides shift every IDN score (`Layers.overrides`). Each rule's proposed stance goes
through its `gated_stance` with the effective verdict of its gate (`eval.gate`, P67): the placebo
verdict on the rule's point-in-time history (P66) with its journalled calls as the live monitor,
read from `out/rules/IDN-<asset>.json` and rebuilt there when missing, for another rule
fingerprint, or behind the newest month end (only the new month ends are rerun). The stocks rule's
macro input is layer 1 held at 50 plus P17's override, live as in its history (open question 4),
so the rule that is gated is the rule that runs; layer 1 still sets the band stance. Every rule
outcome, its gate (state, rule fingerprint) and the candidate list (with each screen's verdict)
are journalled.
The bonds rule's USD/IDR is `IdnSources.usdidr` (P65): JISDOR spliced on the MAS cross, the seam
and the overlap check in its drivers; the signals still read idxscape.

Phase K (S53, P72): with `Sources.idn` set the run also reads the home (IDN) regime
(`read_home`: P71's rule on P70's inputs, from the JCI, idxscape and the USD/IDR splice;
`home_sources`). `build_stance` takes it for IDN stocks and bonds: home risk_off ladders their
adds and trims, a score shift only if `home_regime.HOME_SHIFT_ADOPTED` (open question 8). It is
journalled as `home` in the run's `regime` record and written as `home` in
`out/layers/regime.json`; a failure is one run-level stale line, no block, never a failed run.

Phase C (F3) adds the foreign subjects when `Sources.foreign` is set (`Sources.default` sets it):

    sec-edgar, dbnomics, bisfetcher, jquantster, ausdata, singstat → foreign overrides (2, P28)
    dbnomics, idxscape, bisfetcher, ... → index valuations (4, P29) + IDR edges (P27 `fx_edge`)
                                          └→ RuleView (context only) → build_stance

P28's overrides shift the USA, JPN, AUS and SGP scores, and the euro-area (`EMU`) shift lands on
each worldbankscape member (DEU, FRA, ITA, ESP, NLD) under its own subject; as for Indonesia, a
shift may not carry a stance across a band until it beats a placebo. KOR and TWN have no
overrides and keep their layer-1 score. P29's index candidates reach the foreign stocks stances
as drivers and watch lines only (hand-set scoring, never moves a stance). Every foreign stance
states its IDR edge over one year, hedged against unhedged: stocks from P29's valuation, bonds
from the local 10Y against the IDN 10Y, currency from local cash against the BI rate, all
through P27's `fx_edge` with P29's adverse FX move. Each run journals one `overrides` record
per P28 market, one `candidates` record per P29 market and one `idr_edges` record.

Order of the side effects, fixed by the brief's diff and the journal's fingerprint check:
write out/ → journal → `brief.build_brief` → `brief.save_snapshot` → `notify.send`.

Ops (S14): the brief opens with the doctor (`Sources.doctor`) and carries P30's paper track
(`Sources.paper`, read after this run is journalled); either one failing becomes a line in its
section, never a failed run. `regime_check` is the daily job: layer 0 against the last
journalled regime, Telegram (kind `regime`) only when the state or dollar direction changed.

Phase F (F5, PLAN S20) adds the undervalued list when `Sources.undervalued` is set
(`Sources.default` sets it to `undervalued.gather_live`):

    P36 dividend + P37 GARP screens ─┐
    P35 sector tilt (if it passed) ──┼─ undervalued.assemble ─→ out/candidates/IDN.json
    P21 entry + costs, layer 5 ──────┤        (+ P38 sizes from the IDN stocks stance)
    IDN stocks stance (this run) ────┘        └→ brief *Undervalued candidates*, Telegram top 5

F6 (PLAN S21) adds the US list beside it when `Sources.undervalued_us` is set (`Sources.default`:
`undervalued.gather_live_usa`): P39's US dividend and GARP engines on sec-edgar, in IDR against the
binding USA or IDN hurdle, sized from the USA stocks stance, no tilt (S16 is IDN only) →
`out/candidates/USA.json`, the brief's USA block and Telegram. Each market is built on its own:
one failing leaves the other.

It runs after the stances are built (sizing reads each market's stocks stance) and never fails
the run: an error becomes a stale input and no file. Each run journals one `undervalued` record per
market (verdicts, sizing, config) and one `undervalued_row` record per row, each carrying the
config (tilt yaml hash, hurdle constants, sizing caps, screen CONFIGs) beside the model
fingerprint. Nothing here moves a stance.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from assist import brief, journal, layers_out, notify, stance
from assist.candidates import peers as peer_cmp
from assist.candidates import tiers_replay
from assist.eval import gate as rule_gate
from assist.eval.placebo import Verdict
from assist.fx import FxEdge, fx_edge
from assist.layers import candidates_foreign as cf
from assist.layers import home_regime, portfolio, regime, undervalued
from assist.layers.bonds import IdnBonds, idn_bonds
from assist.layers.bonds import gated_stance as bonds_gate
from assist.layers.bonds.idn import PROXY_10Y
from assist.layers.candidates import IdnCandidates, idn_candidates
from assist.layers.candidates_foreign import ForeignCandidates, IndexValuation, foreign_candidates
from assist.layers.home_inputs import HomeSources
from assist.layers.home_regime import HomeRegime
from assist.layers.overrides import IdnOverrides, idn_overrides
from assist.layers.overrides_foreign import EMU_MEMBERS, ForeignOverrides, foreign_overrides
from assist.layers.rules import IdnStocks, idn_stocks, month_end_closes
from assist.layers.rules import gated_stance as stocks_gate
from assist.layers.signals import IdnSignals, idn_signals
from assist.layers.types import (
    ASSETS,
    DISCLAIMER,
    AssetScore,
    Override,
    Regime,
    Weights,
    stance_validator,
)
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod import JCI
from assist.sources.idxscape_phei import IGSYC_10Y
from assist.sources.worldbankscape import Layer1

__all__ = [
    "ASSETS",
    "COUNTRIES",
    "EDGE_YEARS",
    "FOREIGN",
    "FOREIGN_ASSETS",
    "HOME",
    "RULE_ASSETS",
    "RULE_HORIZON",
    "ForeignLayers",
    "ForeignSources",
    "IdnLayers",
    "IdnSources",
    "IdrEdge",
    "Layers",
    "Paths",
    "RegimeCheck",
    "RunResult",
    "Sources",
    "build",
    "foreign_override_rows",
    "gather",
    "gather_foreign",
    "gather_idn",
    "home_sources",
    "read_home",
    "idr_edges_from",
    "in_scope",
    "rule_gates",
    "rule_prices",
    "last_regime",
    "live_doctor",
    "live_paper",
    "message",
    "peers_record",
    "regime_check",
    "regime_message",
    "rule_view",
    "run",
    "write_out",
    "write_peers",
    "write_tier_replay",
]

HOME = "IDN"
# CLAUDE.md scope: Indonesia, US, Japan, EU, Singapore, Australia, Korea/Taiwan. worldbankscape
# has no euro-area aggregate, so the EU is its five largest members.
COUNTRIES = ("IDN", "USA", "JPN", "DEU", "FRA", "ITA", "ESP", "NLD", "SGP", "AUS", "KOR", "TWN")
# ASSETS (stocks, bonds, currency, commodities) comes from the stance schema: worldbankscape's
# `business` and `property` classes have no stance. Every commodity subject is in scope.

_SUBJECT_DIR = re.compile(r"^[A-Z0-9_]+$")
RULE_HORIZON = rule_gate.HORIZON  # months: the forward window a rule's calls are judged on
RULE_ASSETS = ("bonds", "stocks")  # IDN assets with a rule; currency has overrides only
FOREIGN = tuple(c for c in COUNTRIES if c != HOME)
FOREIGN_ASSETS = ("stocks", "bonds", "currency")
EDGE_YEARS = 1.0  # horizon of every IDR edge, as P29's IDR test


# ---------------- configuration ----------------


@dataclass(frozen=True)
class Paths:
    """Where a run writes. All of it is gitignored (`out/`, `data/`, `journal/`)."""

    out: Path
    snapshots: Path
    briefs: Path
    journal: Path
    notify: Path

    @classmethod
    def under(cls, root: Path, notify_dir: Path | None = None) -> Paths:
        root = Path(root)
        return cls(out=root / "out", snapshots=root / "data" / "snapshots",
                   briefs=root / "data" / "briefs", journal=root / "journal",
                   notify=notify_dir or root / "data" / "notify")

    @classmethod
    def default(cls) -> Paths:
        return cls.under(journal.REPO_ROOT, notify_dir=notify.state_dir())


@dataclass
class IdnSources:
    """The stores Indonesia's layers 2–4 read (phase B), all read-only."""

    bps: Any
    bisfetcher: Any
    dbnomics: Any
    satudatascape: Any
    idxscape: Any
    kseistat: Any
    tic: Any
    phei: Any
    idxmethod: Any  # JCI: idxscape index_daily, idx-method CSV before 2021-10 (JciSource)
    snapshots: Any  # idx-method dated screener cross-sections (JCI earnings yield)
    stocks: Any  # idx-method stock files (screens, costs, entry levels)
    # USD/IDR for the bonds rule (P65): JISDOR spliced on the MAS cross; None → idxscape JISDOR
    usdidr: Any = None

    @classmethod
    def default(cls) -> IdnSources:
        from assist.layers.rules import FactorSnapshots
        from assist.sources.bisfetcher import BisfetcherSource
        from assist.sources.bpslooker import BpsLookerSource
        from assist.sources.dbnomics import DbnomicsSource
        from assist.sources.idxmethod import JciSource
        from assist.sources.idxmethod_stocks import IdxMethodStocks
        from assist.sources.idxscape import IdxscapeSource
        from assist.sources.idxscape_phei import PheiSource
        from assist.sources.kseistat import KseistatSource
        from assist.sources.satudatascape import SatudatascapeSource
        from assist.sources.singstat import SingstatSource
        from assist.sources.usdidr import UsdIdrSource
        from assist.sources.usfin_tic import TicSource

        idx = IdxscapeSource.from_config()
        return cls(bps=BpsLookerSource.from_config(), bisfetcher=BisfetcherSource.from_config(),
                   dbnomics=DbnomicsSource.from_config(),
                   satudatascape=SatudatascapeSource.from_config(),
                   idxscape=idx, kseistat=KseistatSource.from_config(),
                   tic=TicSource(), phei=PheiSource.from_config(),
                   idxmethod=JciSource.from_config(),
                   snapshots=FactorSnapshots.from_config(), stocks=IdxMethodStocks.from_config(),
                   usdidr=UsdIdrSource(idx, SingstatSource.from_config()))


@dataclass
class ForeignSources:
    """The stores the foreign layers read (phase C), keyed by store name as P28's and P29's
    `default_sources` key them."""

    overrides: Mapping[str, Any]
    candidates: Mapping[str, Any]

    @classmethod
    def default(cls) -> ForeignSources:
        from assist.layers import overrides_foreign

        return cls(overrides=overrides_foreign.default_sources(),
                   candidates=cf.default_sources())


@dataclass
class Sources:
    """The stores a run reads; each is built from `config/sources.yaml` by default. `idn` None
    skips Indonesia's layers 2–4 (phase B), `foreign` None the foreign layers (phase C).
    `doctor(day)` (a `doctor.SourceStatus` list) and `paper(day, journal)` (a
    `paper.PaperReport`) feed the brief's *Data health* and *Paper track* sections (S14); None
    leaves the section out. `undervalued(day, regime)` gives the inputs of the S20 list (IDN) and
    `undervalued_us(day, regime)` those of the US one (F6); None writes no file for it.
    `peers(day)` gives the S30 peer comparison (`out/industries/IDN.json`); None skips it.
    `tier_replay(day, out_dir)` gives the S31 replay verdict (`out/industries/IDN.replay.json`,
    P50); None skips it. `layers_out` writes each layer's result to `out/layers/` (S33, from
    `fred` and `idn` for the chart windows); False skips it. `rule_history(dates, day)` reruns
    the IDN rules on month ends (`history.build`, P66) when `out/rules/` needs it (P67); None
    never rebuilds (a missing or foreign-fingerprint file is then no verdict)."""

    worldbankscape: Any
    fred: Any
    financer: Any
    idn: IdnSources | None = None
    foreign: ForeignSources | None = None
    doctor: Callable[[date], Sequence[Any]] | None = None
    paper: Callable[[date, journal.Journal], Any] | None = None
    undervalued: Callable[[date, Regime], undervalued.UndervaluedInputs] | None = None
    undervalued_us: Callable[[date, Regime], undervalued.UndervaluedInputs] | None = None
    peers: Callable[[date], dict] | None = None
    tier_replay: Callable[[date, Path], dict] | None = None
    layers_out: bool = False
    rule_history: rule_gate.Build | None = None

    @classmethod
    def default(cls) -> Sources:
        from assist.sources.financer import FinancerSource
        from assist.sources.usfin import FredSource
        from assist.sources.worldbankscape import WorldbankscapeSource

        return cls(worldbankscape=WorldbankscapeSource.from_config(), fred=FredSource(),
                   financer=FinancerSource.from_config(), idn=IdnSources.default(),
                   foreign=ForeignSources.default(), doctor=live_doctor, paper=live_paper,
                   undervalued=undervalued.gather_live,
                   undervalued_us=undervalued.gather_live_usa, peers=peer_cmp.gather_live,
                   tier_replay=tiers_replay.run_live, layers_out=True,
                   rule_history=rule_gate.live_build)


def live_doctor(day: date) -> list[Any]:
    """`assist doctor` against the real stores (read-only; local HTTP servers only)."""
    import httpx

    from assist import doctor

    with httpx.Client(trust_env=False) as client:
        return doctor.run_doctor(doctor.load_sources(), day, http_client=client)


def live_paper(day: date, j: journal.Journal) -> Any:
    """P30's paper report up to `day`, from this run's journal and the live JCI and SBN legs."""
    from assist import paper

    return paper.paper_track(journal=j, until=day)


# ---------------- read ----------------


@dataclass
class IdnLayers:
    """Indonesia's layers 2–4 on one day, with each rule's placebo verdict."""

    overrides: IdnOverrides
    signals: IdnSignals
    bonds: IdnBonds
    stocks: IdnStocks
    candidates: IdnCandidates
    verdicts: dict[str, Verdict | None] = field(default_factory=dict)
    gates: dict[str, rule_gate.Gate] = field(default_factory=dict)

    def rule(self, asset: str) -> IdnBonds | IdnStocks:
        return self.bonds if asset == "bonds" else self.stocks

    @property
    def stale_inputs(self) -> list[str]:
        parts = (self.overrides, self.signals, self.bonds, self.stocks, self.candidates,
                 *self.gates.values())
        return [s for p in parts for s in p.stale_inputs]


@dataclass(frozen=True)
class IdrEdge:
    """One foreign subject × asset held a year by an IDR investor, hedged against unhedged
    (P27's `fx_edge`): `basis` says what the local return is, `fx` is None when an input is
    missing (named in `missing`)."""

    subject: str
    asset: str
    basis: str = ""
    fx: FxEdge | None = None
    fx_basis: str = ""
    missing: tuple[str, ...] = ()
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def line(self) -> str:
        head = f"IDR edge, {self.asset} ({EDGE_YEARS:g}y)"
        if self.fx is None:
            return f"{head}: n/a (missing {', '.join(self.missing) or 'inputs'})"
        text = f"{head}: {self.basis}; {self.fx.detail()}"
        return text + (f" [fx: {self.fx_basis}]" if self.fx_basis else "")


@dataclass
class ForeignLayers:
    """The foreign subjects' layer 2 (P28), layer 4 (P29) and IDR edges on one day."""

    overrides: ForeignOverrides
    candidates: ForeignCandidates
    edges: dict[tuple[str, str], IdrEdge] = field(default_factory=dict)

    def valuation(self, subject: str) -> IndexValuation | None:
        return next((v for v in self.candidates.valuations if v.market.subject == subject), None)

    @property
    def stale_inputs(self) -> list[str]:
        edges = [s for e in self.edges.values() for s in e.stale_inputs]
        return [*self.overrides.stale_inputs, *self.candidates.stale_inputs, *edges]


@dataclass
class Layers:
    """What one run read. `layer1` is None when worldbankscape is unavailable. `regime_inputs`,
    `portfolio` (None when financer is unavailable), `statements` and `portfolio_stale` are what
    `regime` and `weights` were built from, kept for `out/layers/` (S33)."""

    day: date
    layer1: Layer1 | None
    regime: Regime
    weights: Weights | None
    overrides: tuple[Override, ...] = ()
    stale_inputs: list[str] = field(default_factory=list)
    idn: IdnLayers | None = None
    foreign: ForeignLayers | None = None
    regime_inputs: regime.Inputs | None = None
    portfolio: portfolio.Portfolio | None = None
    statements: tuple[Any, ...] = ()
    portfolio_stale: tuple[str, ...] = ()
    home: HomeRegime | None = None  # the home (IDN) regime (S53); None without IDN sources

    @property
    def scores(self) -> list[AssetScore]:
        return [s for s in (self.layer1.scores if self.layer1 else []) if in_scope(s)]


def in_scope(s: AssetScore) -> bool:
    return s.asset in ASSETS and (s.asset == "commodities" or s.subject in COUNTRIES)


def gather(day: date, sources: Sources, history: Sequence[Mapping] = (),
           rules_dir: Path | None = None) -> Layers:
    """Read layers 0, 1 and 5 as of `day`, plus Indonesia's layers 2–4 when `sources.idn` is
    set and the foreign layers when `sources.foreign` is; `history` is the journal so far (the
    rules' live monitor), `rules_dir` the rule gates' `out/rules/` (None: in memory, no
    history). Never raises for a missing or locked store."""
    stale: list[str] = []
    try:
        layer1 = sources.worldbankscape.load()
        stale += layer1.stale_inputs
    except SourceUnavailable as e:
        layer1 = None
        stale.append(e.stale_input)
    inputs = regime.read_inputs(day, sources.fred)  # regime.regime, keeping its inputs
    reg = regime.classify(inputs)
    stale += reg.stale_inputs
    pf, statements, w_stale = _portfolio(sources.financer)  # as portfolio.current_weights
    weights = pf.weights() if pf is not None else None
    stale += w_stale
    home = None
    if sources.idn is not None:
        home, h_stale = read_home(day, sources.idn)
        stale += h_stale
    idn, overrides = None, ()
    if sources.idn is not None and layer1 is not None:
        scores = {(s.subject, s.asset): s for s in layer1.scores}
        idn = gather_idn(day, reg, sources.idn, score=scores.get((HOME, "stocks")),
                         worldbankscape=sources.worldbankscape, history=history,
                         rules_dir=rules_dir, rule_history=sources.rule_history)
        overrides = idn.overrides.overrides
        stale += idn.stale_inputs
    foreign = None
    if sources.foreign is not None and layer1 is not None:
        foreign = gather_foreign(day, sources.foreign)
        overrides = (*overrides, *foreign_override_rows(foreign))
        stale += foreign.stale_inputs
    return Layers(day, layer1, reg, weights, overrides=tuple(overrides),
                  stale_inputs=sorted(set(stale)), idn=idn, foreign=foreign,
                  regime_inputs=inputs, portfolio=pf, statements=statements,
                  portfolio_stale=tuple(w_stale), home=home)


def home_sources(src: IdnSources) -> HomeSources:
    """The home regime's stores from the run's IDN sources: the JCI, idxscape (flows, SBN) and
    the P65 USD/IDR splice (idxscape JISDOR when the splice is not set)."""
    return HomeSources(jci=src.idxmethod, idxscape=src.idxscape,
                       usdidr=src.usdidr if src.usdidr is not None else src.idxscape)


def read_home(day: date, src: IdnSources) -> tuple[HomeRegime | None, list[str]]:
    """The home (IDN) regime on `day` (P71's rule on P70's inputs) and the run-level stale lines:
    its stale inputs, or one failure line and None (never raises; a missing store is a stale
    input inside the regime, not a failure)."""
    try:
        home = home_regime.home_regime(day, home_sources(src))
    except Exception as e:  # noqa: BLE001 - the home regime never fails the run
        first = str(e).splitlines()[0][:160] if str(e) else ""
        return None, [f"home regime failed: {type(e).__name__}: {first}"]
    return home, list(home.stale_inputs)


def _portfolio(source: Any) -> tuple[portfolio.Portfolio | None, tuple[Any, ...], list[str]]:
    """Layer 5 as `portfolio.current_weights` builds it, keeping the portfolio and the
    statements: (portfolio, statements, stale inputs); a missing or locked store gives
    (None, (), ["financer (missing)"])."""
    try:
        statements = tuple(source.statements())
        pf = portfolio.build_portfolio(statements)
    except SourceUnavailable as e:
        return None, (), [e.stale_input]
    return pf, statements, list(pf.stale_inputs)


def gather_idn(day: date, reg: Regime, src: IdnSources, *, score: AssetScore | None = None,
               worldbankscape: Any = None, history: Sequence[Mapping] = (),
               rules_dir: Path | None = None,
               rule_history: rule_gate.Build | None = None) -> IdnLayers:
    """Indonesia's layers 2–4 on `day` (P17 overrides, P18 signals, P31 bonds rule, P22 stocks
    rule, layer-4 candidates) and each rule's gate (`rule_gates`). The stocks rule's macro input
    is `history.held_score` (layer 1 held at 50, open question 4), as in the history its gate is
    judged on; `score` and `worldbankscape` are kept for callers and no longer read by it."""
    from assist.history import held_score

    ov = idn_overrides(day, bps=src.bps, bisfetcher=src.bisfetcher, dbnomics=src.dbnomics,
                       satudatascape=src.satudatascape)
    sig = idn_signals(day, idxscape=src.idxscape, kseistat=src.kseistat, tic=src.tic)
    bonds = idn_bonds(day, reg, ov, sig, phei=src.phei, dbnomics=src.dbnomics, bps=src.bps,
                      idxscape=src.usdidr or src.idxscape)
    if src.usdidr is not None:
        bonds = _with_fx_seam(bonds, src.usdidr)
    stocks = idn_stocks(day, reg, ov, sig, held_score(day), phei=src.phei, dbnomics=src.dbnomics,
                        bps=src.bps, idxmethod=src.idxmethod, snapshots=src.snapshots)
    cands = idn_candidates(day, stocks=src.stocks)
    gates = rule_gates(day, history, rule_prices(src, day), rules_dir, rule_history)
    verdicts = {a: g.verdict for a, g in gates.items()}
    return IdnLayers(ov, sig, bonds, stocks, cands, verdicts, gates)


def _with_fx_seam(bonds: IdnBonds, fx: Any) -> IdnBonds:
    """The bonds rule read the spliced USD/IDR (P65): add the seam line to its drivers, the
    legs' stale inputs to its own, and attribute the legs' stores instead of the splice."""
    drivers = [*bonds.drivers, fx.seam_line()]
    sources = [s for s in bonds.sources if s != fx.name] + fx.sources
    return dataclasses.replace(
        bonds, drivers=tuple(dict.fromkeys(drivers)),
        stale_inputs=tuple(dict.fromkeys([*bonds.stale_inputs, *fx.stale_inputs])),
        sources=tuple(dict.fromkeys(sources)))


def gather_foreign(day: date, src: ForeignSources) -> ForeignLayers:
    """The foreign layers on `day`: P28's overrides, P29's index valuations, and the IDR edge of
    stocks, bonds and currency in every market P29 covers."""
    fo = foreign_overrides(day, src.overrides)
    fc = foreign_candidates(day, src.candidates)
    return ForeignLayers(fo, fc, idr_edges_from(fc, src.candidates, day))


def foreign_override_rows(foreign: ForeignLayers) -> tuple[Override, ...]:
    """P28's overrides under each in-scope subject: the `EMU` shift is copied to every euro-area
    member worldbankscape scores. KOR and TWN have none."""
    out = []
    for subject in FOREIGN:
        for asset in FOREIGN_ASSETS:
            o = foreign.overrides.for_asset(subject, asset)
            if o is not None:
                out.append(dataclasses.replace(o, subject=subject))
    return tuple(out)


def _value(rd: Any, refs: Sequence[cf.Ref]) -> tuple[float | None, cf.Ref | None, list[str]]:
    """(value, ref, stale lines it added) of the first ref with a known value."""
    n = len(rd.stale)
    hit = rd.value(refs) if refs else None
    value, ref = hit if hit is not None else (None, None)
    return value, ref, rd.stale[n:]


def _edge(subject: str, asset: str, basis: str, r_local: float | None, r_idr: float | None,
          fx_move: float | None, i_idr: float | None, i_local: float | None, *,
          names: tuple[str, str], fx_basis: str, stale: Sequence[str],
          sources: Sequence[str]) -> IdrEdge:
    missing = tuple(n for n, v in ((names[0], r_local), (names[1], r_idr), ("FX move", fx_move))
                    if v is None)
    if missing:
        return IdrEdge(subject, asset, missing=missing)
    hedge = i_idr is not None and i_local is not None
    fx = fx_edge(r_local, r_idr, fx_move, i_idr if hedge else None, i_local if hedge else None,
                 EDGE_YEARS)
    return IdrEdge(subject, asset, basis, fx, fx_basis, (), tuple(dict.fromkeys(stale)),
                   tuple(dict.fromkeys(sources)))


def idr_edges_from(fc: ForeignCandidates, sources: Mapping[str, Any],
                   day: date | None = None) -> dict[tuple[str, str], IdrEdge]:
    """IDR edge over `EDGE_YEARS` of stocks, bonds and currency in every P29 market:

    - stocks: P29's own IDR test (index EY + local CPI against the IDN 10Y) when it valued the
      index, else n/a;
    - bonds: the local 10Y held a year (its yield, no duration effect) against the IDN 10Y;
    - currency: local cash at the short rate against IDR cash at the BI rate, unhedged only:
      hedged it earns exactly the BI rate (covered parity), so it has no edge by construction.

    Same inputs as P29 (its `Ref`s, its adverse 1-year FX move, the policy-rate hedge), read
    point in time with P29's reader; a missing input makes the edge n/a, never an error."""
    day = day or fc.as_of
    rd = cf._Reader(sources, day, cf._all_refs(cf.MARKETS))
    r_idr, r_ref, r_stale = _value(rd, cf.IDR_10Y)
    i_idr, i_ref, i_stale = _value(rd, cf.IDR_SHORT)
    out: dict[tuple[str, str], IdrEdge] = {}
    for m in cf.MARKETS:
        y, y_ref, y_stale = _value(rd, m.yield_10y)
        i_local, s_ref, s_stale = _value(rd, m.short_rate)
        fx_move, fx_basis, fx_src = None, "", []
        if m.fx is not None:
            fx_move, fx_basis = cf.expected_fx_move(rd.fx(m.fx), day, i_idr, i_local)
            fx_src = [r.source for r in m.fx.refs]
        rates = [r.source for r in (i_ref, s_ref) if r is not None]

        v = next((v for v in fc.valuations if v.market.subject == m.subject), None)
        if v is not None and v.fx is not None:
            out[(m.subject, "stocks")] = IdrEdge(
                m.subject, "stocks",
                f"{m.index} {v.basis} EY + CPI {v.r_local:.2%} in {m.currency}", v.fx,
                v.fx_basis, (), tuple(dict.fromkeys([*r_stale, *i_stale, *s_stale])), v.sources)
        else:
            missing = ("index valuation",) if v is None else tuple(
                n for n, x in (("local CPI", v.inflation), ("IDN 10Y", v.r_idr),
                               ("FX move", v.fx_move)) if x is None)
            out[(m.subject, "stocks")] = IdrEdge(m.subject, "stocks", missing=missing)
        out[(m.subject, "bonds")] = _edge(
            m.subject, "bonds", f"{m.currency} 10Y {y or 0:.2%} held 1y (yield, no duration)",
            y, r_idr, fx_move, i_idr, i_local, names=("local 10Y", "IDN 10Y"),
            fx_basis=fx_basis, stale=[*y_stale, *r_stale, *i_stale, *s_stale],
            sources=[r.source for r in (y_ref, r_ref) if r is not None] + rates + fx_src)
        out[(m.subject, "currency")] = _edge(  # no hedge leg: it would earn the BI rate exactly
            m.subject, "currency",
            f"{m.currency} cash at {i_local or 0:.2%} (hedged it earns the BI rate, no edge)",
            i_local, i_idr, fx_move, None, None, names=("local short rate", "BI rate"),
            fx_basis=fx_basis, stale=[*i_stale, *s_stale], sources=rates + fx_src)
    return out


# ---------------- rule verdicts from the journal ----------------


def _month(d: date) -> tuple[int, int]:
    return d.year, d.month


def _jci_months(src: IdnSources, day: date) -> list[tuple[date, float]]:
    try:
        return month_end_closes(src.idxmethod.rows([JCI], end=day))
    except SourceUnavailable:
        return []


def _ten_year_months(src: IdnSources, day: date) -> list[tuple[date, float]]:
    """Month-end 10Y: IGSYC 10Y (PHEI) where it exists, dbnomics' OECD proxy elsewhere, spliced
    as the bonds rule's percentile window splices them."""
    out: dict[tuple[int, int], tuple[date, float]] = {}
    for source, sid in ((src.dbnomics, PROXY_10Y), (src.phei, IGSYC_10Y)):
        try:
            rows = source.rows([sid], end=day)
        except SourceUnavailable:
            continue
        for d, v in month_end_closes(rows):
            out[_month(d)] = (d, v)
    return [out[k] for k in sorted(out)]


def rule_prices(src: IdnSources, day: date) -> dict[str, list[tuple[date, float]]]:
    """Month-end prices each rule's calls are judged on, as known on `day`: the 10Y (bonds) and
    the JCI close (stocks)."""
    return {"bonds": _ten_year_months(src, day), "stocks": _jci_months(src, day)}


def rule_gates(day: date, history: Sequence[Mapping],
               prices: Mapping[str, Sequence[tuple[date, float]]], rules_dir: Path | None,
               build: rule_gate.Build | None = None, *,
               rebuild: bool = False) -> dict[str, rule_gate.Gate]:
    """Both IDN rule gates (`eval.gate.refresh`) on `day`. Never raises: a gate that cannot be
    read, built or written is computed in memory from the journal alone and says why."""
    try:
        return rule_gate.refresh(day, rules_dir, records=history, prices=prices, build=build,
                                 rebuild=rebuild)
    except Exception as e:  # noqa: BLE001 - a run never fails on its gate
        first = str(e).splitlines()[0][:200] if str(e) else ""
        gates = rule_gate.refresh(day, None, records=history, prices=prices, build=None)
        line = f"rule gate failed: {type(e).__name__}: {first}"
        return {a: dataclasses.replace(g, stale_inputs=(*g.stale_inputs, line))
                for a, g in gates.items()}


# ---------------- combine ----------------


def _verdict_text(v: Verdict | None) -> str:
    return "none" if v is None else ("passed" if v.passed else "not passed") + f", {v.reason}"


def rule_view(score: AssetScore, layers: Layers) -> stance.RuleView | None:
    """What layers 2–4 add to one stance beyond the overrides: an IDN rule (`_idn_view`) or a
    foreign subject's IDR edge and index candidate (`_foreign_view`)."""
    if score.subject == HOME:
        return _idn_view(score, layers)
    if (layers.foreign is not None and score.subject in FOREIGN
            and score.asset in FOREIGN_ASSETS):
        return _foreign_view(score, layers.foreign)
    return None


def _foreign_view(score: AssetScore, f: ForeignLayers) -> stance.RuleView:
    """A foreign stance's context, never its stance: the IDR edge as the note (with P28's IDR
    terms when the edge is n/a), a line when the subject has no overrides, and for stocks P29's
    index candidate in the drivers and watch (hand-set: context until it beats a placebo)."""
    subject, asset = score.subject, score.asset
    mo = f.overrides.market(subject)
    edge = f.edges.get((subject, asset))
    note = edge.line() if edge is not None else (
        f"IDR edge, {asset} ({EDGE_YEARS:g}y): n/a (P29 values no euro-area market)")
    if (edge is None or edge.fx is None) and mo is not None and mo.idr is not None:
        note += f"; {mo.idr.detail()} (unhedged takes the FX move, hedged earns the carry)"
    drivers, watch, risks = [], [], []
    if edge is not None and edge.fx is not None and not edge.fx.survives:
        risks.append(f"IDR edge {edge.fx.edge:+.2%} does not survive the expected FX move"
                     " (CLAUDE.md: overweight only if it does; not enforced before a placebo)")
    stale = list(edge.stale_inputs) if edge else []
    sources = list(edge.sources) if edge else []
    if mo is None:
        drivers.append(f"no layer-2 overrides for {subject} (P28 covers USA, JPN, EMU, AUS,"
                       " SGP): layer-1 score stands")
    if asset == "stocks":
        v = f.valuation(subject)
        if v is not None:
            c = v.candidate()
            drivers.append(
                f"layer 4 (index level): {v.market.index} score {v.score:.1f}, valuation edge"
                f" {v.edge:+.2%}, {'passes' if v.passes else 'does not pass'}. Context only:"
                " hand-set scoring, no stance change before it beats a placebo")
            watch.append(f"candidate {c.symbol} ({c.screen}): score {c.score:.1f}; {c.detail}")
            sources += v.sources
        else:
            try:
                m = cf.market(subject)
                gap = dict(m.gaps).get("valuation", "valuation inputs missing")
                drivers.append(f"layer 4 (index level): no {m.index} candidate ({gap})")
            except KeyError:
                drivers.append(f"layer 4 (index level): no index for {subject}"
                               " (P29 covers no euro-area market)")
        stale += [s for s in f.candidates.stale_inputs if s.startswith(f"{subject} ")]
    return stance.RuleView(subject=subject, asset=asset, note=note, drivers=tuple(drivers),
                           risks=tuple(risks), watch=tuple(watch),
                           stale_inputs=tuple(dict.fromkeys(stale)),
                           sources=tuple(dict.fromkeys(sources)))


def _idn_view(score: AssetScore, layers: Layers) -> stance.RuleView | None:
    """The IDN bonds or stocks rule as it reaches the stance: the gated stance (only with a
    passing verdict), the gate's note, drivers, risks and stale inputs; for stocks also the
    layer-4 headline in the drivers and one watch line per candidate."""
    idn = layers.idn
    if idn is None or score.subject != HOME or score.asset not in RULE_ASSETS:
        return None
    rule, verdict = idn.rule(score.asset), idn.verdicts.get(score.asset)
    gate = bonds_gate if score.asset == "bonds" else stocks_gate
    gated, note = gate(stance.base_stance(score, layers.regime, layers.home), rule, verdict)
    g = idn.gates.get(score.asset)
    if rule.proposed_stance is not None:
        note += (f" (rule gate {g.line()})" if g is not None
                 else f" (verdict: {_verdict_text(verdict)})")
    applied = rule.proposed_stance is not None and verdict is not None and verdict.passed
    drivers, watch = list(rule.drivers), []
    stale, sources = list(rule.stale_inputs), list(rule.sources)
    if score.asset == "stocks":
        c = idn.candidates
        drivers.append(c.headline())
        watch = c.watch()
        stale += c.stale_inputs
        sources += c.sources
    return stance.RuleView(subject=HOME, asset=score.asset, note=note,
                           stance=gated if applied else None,
                           entry=rule.entry if applied else None, drivers=tuple(drivers),
                           risks=tuple(rule.risks), watch=tuple(watch),
                           stale_inputs=tuple(dict.fromkeys(stale)),
                           sources=tuple(dict.fromkeys(sources)))


def build(layers: Layers, fingerprint: str) -> list[dict]:
    """One stance payload per in-scope score, in a stable order, each schema-valid. The
    portfolio pass (`stance.apply_limits`, S39) runs over all of them before validation, so the
    targets sum to at most 100%."""
    v = stance_validator()
    out = [stance.build_stance(score=s, regime=layers.regime, weights=layers.weights,
                               overrides=layers.overrides, as_of=layers.day,
                               fingerprint=fingerprint, rule=rule_view(s, layers),
                               home=layers.home)
           for s in sorted(layers.scores, key=lambda s: (s.subject, s.asset))]
    stance.apply_limits(out)
    for p in out:
        errors = sorted(v.iter_errors(p), key=lambda e: list(e.absolute_path))
        if errors:  # a bug in this repo, not a data problem: stop before writing anything
            raise ValueError(f"{p['subject']}/{p['asset']} stance fails the schema: "
                             f"{errors[0].message}")
    return out


# ---------------- write ----------------


def _write_if_changed(path: Path, text: str) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return  # keep the mtime of an unchanged file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_out(stances: Sequence[Mapping], out_dir: Path) -> list[Path]:
    """Write `out/{SUBJECT}/{asset}.json` and drop stance files this run did not produce, so
    out/ always holds exactly one run. Files outside subject directories are left alone."""
    out_dir = Path(out_dir)
    written = []
    for p in stances:
        path = out_dir / p["subject"] / f"{p['asset']}.json"
        _write_if_changed(path, stance.dumps(p))
        written.append(path)
    keep = set(written)
    if out_dir.is_dir():
        for d in sorted(out_dir.iterdir()):
            if not (d.is_dir() and _SUBJECT_DIR.match(d.name)):
                continue
            for f in d.glob("*.json"):
                if f not in keep:
                    f.unlink()
            if not any(d.iterdir()):
                d.rmdir()
    return written


def _journal(j: journal.Journal, layers: Layers, stances: Sequence[Mapping], fp: str) -> str:
    run_id = uuid.uuid4().hex
    outputs = journal.jsonable(layers.regime)
    if layers.idn is not None or layers.home is not None:  # S53: the home regime rides along
        outputs["home"] = journal.jsonable(layers.home)
    j.record(kind="regime", fingerprint=fp, inputs={"day": layers.day}, outputs=outputs,
             as_of=layers.day, run_id=run_id)
    scores = {(s.subject, s.asset): s for s in layers.scores}
    for p in stances:
        key = (p["subject"], p["asset"])
        j.record(kind="stance", fingerprint=fp, subject=key[0], asset=key[1], as_of=layers.day,
                 run_id=run_id, outputs=p,
                 inputs={"score": scores[key], "regime": layers.regime,
                         "weights": layers.weights,
                         "overrides": [o for o in layers.overrides
                                       if (o.subject, o.asset) == key]})
    keyed = {(p["subject"], p["asset"]): p for p in stances}
    if layers.idn is not None:
        _journal_idn(j, layers, keyed, fp, run_id)
    if layers.foreign is not None:
        _journal_foreign(j, layers, keyed, fp, run_id)
    return run_id


def _journal_foreign(j: journal.Journal, layers: Layers, stances: Mapping, fp: str,
                     run_id: str) -> None:
    """One `overrides` record per P28 market (its components, the shift per asset and, for each
    stance it reached, whether the band was held), one `candidates` record per P29 market (the
    valuation or none; it never moves a stance) and one `idr_edges` record."""
    f = layers.foreign
    for m in f.overrides.markets:
        members = EMU_MEMBERS if m.subject == "EMU" else (m.subject,)
        reached = {}
        for s in members:
            for a in FOREIGN_ASSETS:
                p = stances.get((s, a))
                if p is not None:
                    reached[f"{s}/{a}"] = {
                        "stance": p["stance"], "score": p["score"],
                        "layer1_score": p["layer1_score"],
                        "held": stance.stance_for(p["score"]) != p["stance"]}
        j.record(kind="overrides", fingerprint=fp, subject=m.subject, as_of=layers.day,
                 run_id=run_id, inputs=m,
                 outputs={"deltas": {o.asset: o.delta for o in m.overrides}, "raw": m.raw,
                          "stances": reached, "moves_band": False})
    for m in cf.MARKETS:
        v = f.valuation(m.subject)
        p = stances.get((m.subject, "stocks"))
        j.record(kind="candidates", fingerprint=fp, subject=m.subject, asset="stocks",
                 as_of=layers.day, run_id=run_id,
                 inputs={"index": m.index, "gaps": dict(m.gaps)},
                 outputs={"valuation": v, "candidate": v.candidate() if v else None,
                          "passes": bool(v and v.passes), "stance": p["stance"] if p else None,
                          "moves_stance": False})
    j.record(kind="idr_edges", fingerprint=fp, as_of=layers.day, run_id=run_id,
             inputs=f.edges,
             outputs={f"{s}/{a}": {"line": e.line(), "best": e.fx.best if e.fx else None,
                                   "edge": e.fx.edge if e.fx else None}
                      for (s, a), e in sorted(f.edges.items())})


def _journal_idn(j: journal.Journal, layers: Layers, stances: Mapping, fp: str,
                 run_id: str) -> None:
    """One `rule` record per IDN rule (its call, the proposal, the stance written and the
    verdict, with the rule's inputs) and one `candidates` record (names, drops and every
    screen's verdict). The `rule` records are what later verdicts are built from."""
    idn = layers.idn
    for asset in RULE_ASSETS:
        rule, verdict = idn.rule(asset), idn.verdicts.get(asset)
        g = idn.gates.get(asset)
        p = stances.get((HOME, asset))
        j.record(kind="rule", fingerprint=fp, subject=HOME, asset=asset, as_of=layers.day,
                 run_id=run_id, inputs=rule,
                 outputs={"call": rule.call, "proposed_stance": rule.proposed_stance,
                          "stance": p["stance"] if p else None,
                          "rule_fingerprint": g.fingerprint if g else None,
                          "gate": g.journal() if g else None,
                          "verdict": None if verdict is None else
                          {k: v for k, v in verdict.to_dict().items() if k != "control_ts"}})
    j.record(kind="candidates", fingerprint=fp, subject=HOME, asset="stocks", as_of=layers.day,
             run_id=run_id, inputs={"order_idr": idn.candidates.order_idr},
             outputs=idn.candidates)


# ---------------- notify ----------------


def message(*, day: date, brief_path: Path | None, undervalued: Sequence[Mapping] = (),
            stances: Sequence[Mapping] = ()) -> str:
    """The Telegram text: `notify.header` (title, disclaimer, paper-only line, S42), per market
    (IDN, then USA) the undervalued top 5, then the names sized to sell or buy (`sizing`), each
    market's list labelled with its stocks leg's rebalance vs tilt (`notify.leg_line`). On a
    home (IDN) risk_off one line after the header (S54). Stances, regime and the portfolio legs
    are in the brief."""
    lines = notify.header(day)
    home = brief.home_message_line(stances)  # S54: one line on a home risk_off
    if home:
        lines += [home, ""]
    lines += _undervalued_lines(undervalued) or ["Undervalued: no market read this run"]
    trades = trade_lines(undervalued, stances)
    if trades:
        lines += ["", *trades]
    if brief_path is not None:
        lines += ["", f"brief: {brief_path.name}"]
    lines += ["", "Heuristic, not investment advice."]
    return "\n".join(lines)


def _m(idr: float) -> str:
    return f"{idr / 1e6:,.1f}m"


def trade_lines(payloads: Sequence[Mapping], stances: Sequence[Mapping] = ()) -> list[str]:
    """Per market: its leg's rebalance vs tilt label when its stance is given (S42), every name
    sized to sell (`sizing.trims`, largest first, with its reason), then every name sized to buy
    (a row's `size`), or one line saying there is none."""
    lines: list[str] = []
    for p in payloads:
        mkt, sizing = p["market"], p.get("sizing") or {}
        label = notify.leg_line(stances, mkt)
        if label:
            lines.append(label)
        trims = sorted(sizing.get("trims") or (), key=lambda t: (-t["idr"], t["symbol"]))
        if trims:
            lines.append(f"{mkt} to sell ({len(trims)}, IDR {_m(sum(t['idr'] for t in trims))}):")
            lines += [f"  {t['symbol']:<5} {_m(t['idr']):>6}  {t['reason']}" for t in trims]
        else:
            lines.append(f"{mkt} to sell: none")
        buys, seen = [], set()
        for st in p.get("styles") or ():
            for r in st.get("rows") or ():
                if r.get("size") and r["symbol"] not in seen:
                    seen.add(r["symbol"])
                    buys.append((r, st["style"]))
        if buys:
            total = sum(r["size"]["idr"] for r, _ in buys)
            lines.append(f"{mkt} to buy ({len(buys)}, IDR {_m(total)}):")
            lines += [f"  {r['symbol']:<5} {_m(r['size']['idr']):>6}  {style} #{r['rank']}"
                      for r, style in buys]
        else:
            budget = sizing.get("budget_idr")
            why = "" if not budget else f" (IDR {_m(budget)} budget unspent)"
            lines.append(f"{mkt} to buy: none{why}")
    return lines


def _undervalued_lines(payloads: Sequence[Mapping]) -> list[str]:
    return undervalued.telegram_lines(payloads) if payloads else []


# ---------------- undervalued (F5) ----------------


def _undervalued(day: date, sources: Sources, layers: Layers, stances: Sequence[Mapping],
                 fp: str, paths: Paths) -> tuple[list[dict], list[str]]:
    """The S20 list per market (IDN, then USA) → (payloads written to out/candidates, stale
    inputs). Never raises: the stances are already written; one market failing skips only it."""
    gathers = [(m, fn) for m, fn in (("IDN", sources.undervalued), ("USA", sources.undervalued_us))
               if fn is not None]
    if not gathers:
        return [], []
    try:
        statements = list(sources.financer.statements())
    except SourceUnavailable:
        statements = []
    payloads, stale = [], []
    for market, fn in gathers:
        try:
            payload = _undervalued_one(fn(day, layers.regime), day, statements, layers,
                                       stances, fp)
        except Exception as e:  # noqa: BLE001 - a candidates failure never fails the run
            first = str(e).splitlines()[0][:160] if str(e) else ""
            label = "undervalued" if market == "IDN" else f"undervalued {market}"
            stale.append(f"{label} candidates failed: {type(e).__name__}: {first}")
            continue
        undervalued.write(payload, paths.out)
        payloads.append(payload)
    return payloads, stale


def _undervalued_one(inp: undervalued.UndervaluedInputs, day: date, statements: Sequence[Any],
                     layers: Layers, stances: Sequence[Mapping], fp: str) -> dict:
    held = undervalued.holdings_from(statements, inp.market)
    st = next((s for s in stances if (s["subject"], s["asset"]) == (inp.market, "stocks")), None)
    value = layers.weights.total_idr if layers.weights is not None else None
    payload = undervalued.assemble(inp, day=day, stance=st, portfolio_value_idr=value,
                                   holdings=held, regime=layers.regime, fingerprint=fp)
    payload = journal.jsonable(payload)
    errors = list(undervalued.validator().iter_errors(payload))
    if errors:
        raise ValueError(f"candidates payload fails the schema: {errors[0].message}")
    return payload


def _journal_undervalued(j: journal.Journal, payloads: Sequence[Mapping], fp: str,
                         run_id: str | None) -> None:
    """One `undervalued` record per market and one `undervalued_row` record per row."""
    for p in payloads:
        cfg = p["config"]
        j.record(kind="undervalued", fingerprint=fp, subject=p["market"], asset="stocks",
                 as_of=p["as_of"], run_id=run_id,
                 inputs={"config": cfg, "hurdle": p["hurdle"], "stance": p["stance"],
                         "tilt": p["tilt"], "bar_date": p["bar_date"]},
                 outputs={"styles": {s["style"]: {k: v for k, v in s.items() if k != "rows"}
                                     | {"names": [r["symbol"] for r in s["rows"]]}
                                     for s in p["styles"]},
                          "sizing": p["sizing"], "stale_inputs": p["stale_inputs"],
                          "moves_stance": False})
        for s in p["styles"]:
            for r in s["rows"]:
                j.record(kind="undervalued_row", fingerprint=fp, subject=p["market"],
                         asset="stocks", as_of=p["as_of"], run_id=run_id,
                         inputs={"style": s["style"], "verdict": s["verdict"],
                                 "hurdle_pt": p["hurdle"]["required_pt"], "config": cfg},
                         outputs=r)


# ---------------- run ----------------


@dataclass
class RunResult:
    ok: bool
    day: date
    regime: Regime | None = None
    stances: list[dict] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    brief_path: Path | None = None
    run_id: str | None = None
    fingerprint: str | None = None
    notify: dict | None = None
    stale_inputs: list[str] = field(default_factory=list)
    problems: dict[str, str] = field(default_factory=dict)
    idn: IdnLayers | None = None
    foreign: ForeignLayers | None = None
    undervalued: list[dict] = field(default_factory=list)
    peers: Path | None = None
    tier_replay: Path | None = None
    layer_files: list[Path] = field(default_factory=list)
    home: HomeRegime | None = None


def write_peers(day: date, gather: Callable[[date], dict] | None,
                out_dir: Path) -> tuple[Path | None, list[str]]:
    """The S30 peer comparison → (`out/industries/IDN.json`, stale inputs). Never raises: an
    unreadable store leaves the previous file and names itself as a stale input."""
    if gather is None:
        return None, []
    try:
        payload = gather(day)
    except Exception as e:  # noqa: BLE001 - context only, never fails the run
        first = str(e).splitlines()[0][:160] if str(e) else ""
        return None, [f"peer comparison failed: {type(e).__name__}: {first}"]
    return peer_cmp.write(payload, out_dir), list(payload.get("stale_inputs") or [])


def peers_record(payload: Mapping) -> tuple[dict, dict]:
    """(inputs, outputs) of the `industries` journal record (S31): the tier fingerprint and
    config; per industry its peer group and picks; per gated name its pillars and composite."""
    picks, names = {}, {}
    for ind in payload.get("industries") or []:
        picks[ind["id"]] = {"label": ind.get("label"), "peer_group": ind.get("peer_group"),
                            "gated": ind.get("gated"), **(ind.get("picks") or {"A": [], "B": []})}
        for s in ind.get("stocks") or []:
            if (s.get("gates") or {}).get("pass"):
                names[s["symbol"]] = {
                    "industry": ind["id"], "composite": s.get("composite"),
                    "rank": s.get("rank"), "pick": s.get("pick"),
                    "pillars": {k: v.get("score") for k, v in (s.get("pillars") or {}).items()}}
    inputs = {"as_of": payload.get("as_of"), "tier_fingerprint": payload.get("fingerprint"),
              "tier_config": payload.get("tier_config")}
    outputs = {"tier_fingerprint": payload.get("fingerprint"), "picks": picks, "names": names,
               "stale_inputs": payload.get("stale_inputs") or [], "moves_stance": False}
    return inputs, outputs


def _journal_peers(j: journal.Journal, path: Path | None, fp: str, run_id: str | None) -> None:
    """One `industries` record per run from the file `write_peers` wrote. Never raises: the tiers
    are context only."""
    if path is None:
        return
    try:
        payload = json.loads(Path(path).read_text())
        inputs, outputs = peers_record(payload)
        j.record(kind="industries", fingerprint=fp, subject=payload.get("market"),
                 asset="stocks", as_of=payload.get("as_of"), run_id=run_id, inputs=inputs,
                 outputs=outputs)
    except Exception as e:  # noqa: BLE001 - context only, never fails the run
        print(f"industries journal skipped: {type(e).__name__}: {e}", file=sys.stderr)


def write_tier_replay(day: date, gather: Callable[[date, Path], dict] | None,
                      out_dir: Path) -> tuple[Path | None, list[str]]:
    """The S31 replay verdict (P50) → (`out/industries/IDN.replay.json`, stale inputs). Never
    raises: a failure names itself as a stale input and leaves the tiers context only."""
    if gather is None:
        return None, []
    try:
        payload = gather(day, out_dir)
        return tiers_replay.write(payload, out_dir), list(payload.get("stale_inputs") or [])
    except Exception as e:  # noqa: BLE001 - context only, never fails the run
        first = str(e).splitlines()[0][:160] if str(e) else ""
        return None, [f"tier replay failed: {type(e).__name__}: {first}"]


def _journal_tier_replay(j: journal.Journal, path: Path | None, fp: str,
                         run_id: str | None) -> None:
    """One `tier_replay` record per run from the file `write_tier_replay` wrote. Never raises."""
    if path is None:
        return
    try:
        payload = json.loads(Path(path).read_text())
        inputs, outputs = tiers_replay.journal_record(payload)
        j.record(kind="tier_replay", fingerprint=fp, subject=payload.get("market"),
                 asset="stocks", as_of=payload.get("as_of") or payload.get("built"),
                 run_id=run_id, inputs=inputs, outputs=outputs)
    except Exception as e:  # noqa: BLE001 - context only, never fails the run
        print(f"tier replay journal skipped: {type(e).__name__}: {e}", file=sys.stderr)


def run(day: date, *, paths: Paths | None = None, sources: Sources | None = None,
        send: bool = True, notify_kw: Mapping[str, Any] | None = None) -> RunResult:
    paths = paths or Paths.default()
    sources = sources or Sources.default()
    j = journal.Journal(paths.journal)
    layers = gather(day, sources, history=list(j.read()), rules_dir=paths.out / "rules")
    res = RunResult(ok=False, day=day, regime=layers.regime, stale_inputs=layers.stale_inputs,
                    problems=dict(layers.layer1.problems) if layers.layer1 else {},
                    idn=layers.idn, foreign=layers.foreign, home=layers.home)
    if layers.layer1 is None or not layers.scores:
        return res  # no layer 1, no stance: leave out/ and the journal as they were

    fp = j.register_model()
    if fp != journal.model_fingerprint():  # cannot happen unless the model changes mid-run
        raise RuntimeError("model fingerprint changed during the run")
    res.fingerprint = fp
    res.stances = build(layers, fp)
    res.files = write_out(res.stances, paths.out)
    if sources.layers_out:  # S33: never raises, never changes a stance
        res.layer_files = layers_out.write_layers(
            layers, res.stances, fp, paths.out, fred=sources.fred, idn=sources.idn,
            home_sources=home_sources(sources.idn) if sources.idn is not None else None)
    res.undervalued, uv_stale = _undervalued(day, sources, layers, res.stances, fp, paths)
    res.peers, peer_stale = write_peers(day, sources.peers, paths.out)
    res.tier_replay, tr_stale = write_tier_replay(day, sources.tier_replay, paths.out)
    res.stale_inputs = sorted({*res.stale_inputs, *uv_stale, *peer_stale, *tr_stale})
    res.run_id = _journal(j, layers, res.stances, fp)
    _journal_undervalued(j, res.undervalued, fp, res.run_id)
    _journal_peers(j, res.peers, fp, res.run_id)
    _journal_tier_replay(j, res.tier_replay, fp, res.run_id)

    health = _never_fail("doctor", sources.doctor, brief.health_lines, day)
    paper_track = _never_fail("paper tracking", sources.paper, brief.paper_lines, day, j)
    text = brief.build_brief(paths.out, paths.snapshots, health=health, paper=paper_track)
    res.brief_path = paths.briefs / f"{day.isoformat()}.md"
    _write_if_changed(res.brief_path, text)
    brief.save_snapshot(paths.out, paths.snapshots, day.isoformat())
    res.ok = True

    if send:
        msg = message(day=day, brief_path=res.brief_path, undervalued=res.undervalued,
                      stances=res.stances)
        res.notify = notify.send(msg, kind="brief", day=day, state_dir=paths.notify,
                                 **dict(notify_kw or {}))
    return res


def _never_fail(name: str, fn: Callable | None, fmt: Callable[[Any], list[str]],
                *args: Any) -> list[str] | None:
    """`fmt(fn(*args))`, or one line naming the failure: a brief section never stops a run."""
    if fn is None:
        return None
    try:
        return fmt(fn(*args))
    except Exception as e:  # noqa: BLE001 - the stances are already written
        first = str(e).splitlines()[0][:200] if str(e) else ""
        return [f"{name} failed: {type(e).__name__}: {first}"]


# ---------------- daily regime check (S14) ----------------


def last_regime(records: Iterable[Mapping], day: date) -> dict | None:
    """The newest journalled regime (`kind` regime, from a weekly run or a daily check) dated on
    or before `day`, as {"as_of", "state", "dollar", "home"}; the later record wins a tie.
    `home` is the home (IDN) state journalled with it (S54), None when the record has none."""
    best = None
    for rec in records:
        out = rec.get("outputs") or {}
        as_of = str(rec.get("as_of") or out.get("as_of") or "")[:10]
        if rec.get("kind") != "regime" or not as_of or as_of > day.isoformat():
            continue
        if "state" not in out or "dollar" not in out:
            continue
        if best is None or as_of >= best["as_of"]:
            home = out.get("home") if isinstance(out.get("home"), Mapping) else {}
            best = {"as_of": as_of, "state": out["state"], "dollar": out["dollar"],
                    "home": home.get("state")}
    return best


@dataclass
class RegimeCheck:
    """One daily check: today's regime against the last journalled one."""

    day: date
    regime: Regime
    previous: dict | None
    available: bool
    changed: bool
    notify: dict | None = None
    journalled: bool = False
    home: HomeRegime | None = None  # the home (IDN) regime read with it (S54); None: no reading

    @property
    def home_changed(self) -> bool:
        """The home state differs from the one journalled last (a record without one is no
        comparison: the check journals a home baseline instead)."""
        prev = (self.previous or {}).get("home")
        return self.home is not None and prev is not None and prev != self.home.state

    def changes(self) -> list[str]:
        if not self.changed or self.previous is None:
            return []
        out = []
        if self.previous["state"] != self.regime.state:
            out.append(f"Regime: {self.previous['state']} → {self.regime.state}")
        if self.previous["dollar"] != self.regime.dollar:
            out.append(f"Dollar: {self.previous['dollar']} → {self.regime.dollar}")
        if self.home_changed:
            out.append(f"Home regime (IDN): {self.previous['home']} → {self.home.state}")
        return out


def regime_message(chk: RegimeCheck) -> str:
    """The Telegram text for a regime change: what changed since when, the drivers, stale
    inputs and the disclaimer last."""
    reg = chk.regime
    lines = [f"investment-assist regime {chk.day.isoformat()}", *chk.changes()]
    if chk.previous is not None:
        lines.append(f"(since {chk.previous['as_of']})")
    lines += [""] + [f"- {d}" for d in reg.drivers]
    if chk.home is not None:
        lines += [f"- home: {d}" for d in chk.home.drivers]
    if reg.stale_inputs:
        lines += ["", "stale: " + ", ".join(reg.stale_inputs)]
    lines += ["", "Stances move on the weekly run; this is a heads-up only.", "", DISCLAIMER]
    return "\n".join(lines)


def _home_reading(day: date, home_source: Any) -> HomeRegime | None:
    """The home regime for the daily check, or None: no source, a failure, or no store read."""
    if home_source is None:
        return None
    try:
        home = home_regime.home_regime(day, home_source)
    except Exception:  # noqa: BLE001 - the home regime never fails the check
        return None
    return home if home.sources else None


def regime_check(day: date, *, paths: Paths | None = None, source: Any = None,
                 send: bool = True, notify_kw: Mapping[str, Any] | None = None,
                 home_source: Any = None) -> RegimeCheck:
    """Daily job: compute layer 0 for `day` and compare it with the last journalled regime.

    - Telegram (kind `regime`, send-once per day) goes out only when the state or the dollar
      direction changed. A first check with nothing journalled records a baseline and sends
      nothing.
    - The new regime is journalled (kind `regime`) on a baseline, or on a change whose message
      was sent or already sent today. A failed send journals nothing, so the next check finds
      the same change and retries.
    - `send=False` is a dry check: it writes nothing at all.
    - A regime read without any source (FRED missing or locked) is no reading: no change, no
      write, no message.
    - With `home_source` (a `HomeSources`, S54) the home (IDN) regime is read too and rides in
      the journalled record as `home`. A home state change is a change like the others (one
      message). The first check whose last record has no home state journals a home baseline
      and sends nothing; an unreadable home regime is no home change.
    """
    paths = paths or Paths.default()
    j = journal.Journal(paths.journal)
    reg = regime.regime(day, source=source if source is not None else Sources.default().fred)
    prev = last_regime(j.read(), day)
    available = bool(reg.sources)
    home = _home_reading(day, home_source) if available else None
    chk = RegimeCheck(day=day, regime=reg, previous=prev, available=available, changed=False,
                      home=home)
    chk.changed = available and prev is not None and (
        (prev["state"], prev["dollar"]) != (reg.state, reg.dollar) or chk.home_changed)
    if not send or not available:
        return chk
    if chk.changed:
        chk.notify = notify.send(regime_message(chk), kind="regime", day=day,
                                 state_dir=paths.notify, **dict(notify_kw or {}))
    home_baseline = home is not None and prev is not None and prev.get("home") is None
    if prev is None or home_baseline or (
            chk.changed and (chk.notify["sent"] or chk.notify["skipped"])):
        fp = j.register_model()
        outputs = journal.jsonable(reg)
        if home is not None:
            outputs["home"] = journal.jsonable(home)
        j.record(kind="regime", fingerprint=fp, inputs={"day": day, "job": "regime"},
                 outputs=outputs, as_of=day, run_id=uuid.uuid4().hex)
        chk.journalled = True
    return chk
