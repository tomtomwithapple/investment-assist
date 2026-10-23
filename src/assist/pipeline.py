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
through its `gated_stance` with a placebo verdict built from the rule's own journalled calls
(`journalled_verdict`: calls recorded before the run day against the forward return that
followed), so a rule earns the right to move a stance only on calls it made in the open. Every
rule outcome, its verdict and the candidate list (with each screen's verdict) are journalled.

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
"""

from __future__ import annotations

import dataclasses
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from assist import brief, journal, notify, stance
from assist.eval.placebo import Verdict
from assist.fx import FxEdge, fx_edge
from assist.layers import candidates_foreign as cf
from assist.layers import portfolio, regime
from assist.layers.bonds import IdnBonds, idn_bonds
from assist.layers.bonds import gated_stance as bonds_gate
from assist.layers.bonds import rule_verdict as bonds_verdict
from assist.layers.bonds.idn import PROXY_10Y
from assist.layers.candidates import IdnCandidates, idn_candidates
from assist.layers.candidates_foreign import ForeignCandidates, IndexValuation, foreign_candidates
from assist.layers.overrides import IdnOverrides, idn_overrides
from assist.layers.overrides_foreign import EMU_MEMBERS, ForeignOverrides, foreign_overrides
from assist.layers.rules import IdnStocks, idn_stocks, month_end_closes
from assist.layers.rules import gated_stance as stocks_gate
from assist.layers.rules import rule_verdict as stocks_verdict
from assist.layers.signals import IdnSignals, idn_signals
from assist.layers.types import (
    ASSETS,
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
    "RunResult",
    "Sources",
    "build",
    "foreign_override_rows",
    "gather",
    "gather_foreign",
    "gather_idn",
    "idr_edges_from",
    "in_scope",
    "journalled_calls",
    "journalled_verdict",
    "message",
    "rule_view",
    "run",
    "write_out",
]

HOME = "IDN"
# CLAUDE.md scope: Indonesia, US, Japan, EU, Singapore, Australia, Korea/Taiwan. worldbankscape
# has no euro-area aggregate, so the EU is its five largest members.
COUNTRIES = ("IDN", "USA", "JPN", "DEU", "FRA", "ITA", "ESP", "NLD", "SGP", "AUS", "KOR", "TWN")
# ASSETS (stocks, bonds, currency, commodities) comes from the stance schema: worldbankscape's
# `business` and `property` classes have no stance. Every commodity subject is in scope.

_SUBJECT_DIR = re.compile(r"^[A-Z0-9_]+$")
RULE_HORIZON = 3  # months: the forward window a rule's journalled calls are judged on
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
    idxmethod: Any  # idx-method index CSVs (JCI)
    snapshots: Any  # idx-method dated screener cross-sections (JCI earnings yield)
    stocks: Any  # idx-method stock files (screens, costs, entry levels)

    @classmethod
    def default(cls) -> IdnSources:
        from assist.layers.rules import FactorSnapshots
        from assist.sources.bisfetcher import BisfetcherSource
        from assist.sources.bpslooker import BpsLookerSource
        from assist.sources.dbnomics import DbnomicsSource
        from assist.sources.idxmethod import IdxMethodIndexSource
        from assist.sources.idxmethod_stocks import IdxMethodStocks
        from assist.sources.idxscape import IdxscapeSource
        from assist.sources.idxscape_phei import PheiSource
        from assist.sources.kseistat import KseistatSource
        from assist.sources.satudatascape import SatudatascapeSource
        from assist.sources.usfin_tic import TicSource

        return cls(bps=BpsLookerSource.from_config(), bisfetcher=BisfetcherSource.from_config(),
                   dbnomics=DbnomicsSource.from_config(),
                   satudatascape=SatudatascapeSource.from_config(),
                   idxscape=IdxscapeSource.from_config(), kseistat=KseistatSource.from_config(),
                   tic=TicSource(), phei=PheiSource.from_config(),
                   idxmethod=IdxMethodIndexSource.from_config(),
                   snapshots=FactorSnapshots.from_config(), stocks=IdxMethodStocks.from_config())


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
    skips Indonesia's layers 2–4 (phase B), `foreign` None the foreign layers (phase C)."""

    worldbankscape: Any
    fred: Any
    financer: Any
    idn: IdnSources | None = None
    foreign: ForeignSources | None = None

    @classmethod
    def default(cls) -> Sources:
        from assist.sources.financer import FinancerSource
        from assist.sources.usfin import FredSource
        from assist.sources.worldbankscape import WorldbankscapeSource

        return cls(worldbankscape=WorldbankscapeSource.from_config(), fred=FredSource(),
                   financer=FinancerSource.from_config(), idn=IdnSources.default(),
                   foreign=ForeignSources.default())


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

    def rule(self, asset: str) -> IdnBonds | IdnStocks:
        return self.bonds if asset == "bonds" else self.stocks

    @property
    def stale_inputs(self) -> list[str]:
        parts = (self.overrides, self.signals, self.bonds, self.stocks, self.candidates)
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
    """What one run read. `layer1` is None when worldbankscape is unavailable."""

    day: date
    layer1: Layer1 | None
    regime: Regime
    weights: Weights | None
    overrides: tuple[Override, ...] = ()
    stale_inputs: list[str] = field(default_factory=list)
    idn: IdnLayers | None = None
    foreign: ForeignLayers | None = None

    @property
    def scores(self) -> list[AssetScore]:
        return [s for s in (self.layer1.scores if self.layer1 else []) if in_scope(s)]


def in_scope(s: AssetScore) -> bool:
    return s.asset in ASSETS and (s.asset == "commodities" or s.subject in COUNTRIES)


def gather(day: date, sources: Sources, history: Sequence[Mapping] = ()) -> Layers:
    """Read layers 0, 1 and 5 as of `day`, plus Indonesia's layers 2–4 when `sources.idn` is
    set and the foreign layers when `sources.foreign` is; `history` is the journal so far (for
    the rules' verdicts). Never raises for a missing or locked store."""
    stale: list[str] = []
    try:
        layer1 = sources.worldbankscape.load()
        stale += layer1.stale_inputs
    except SourceUnavailable as e:
        layer1 = None
        stale.append(e.stale_input)
    reg = regime.regime(day, source=sources.fred)
    stale += reg.stale_inputs
    weights, w_stale = portfolio.current_weights(sources.financer)
    stale += w_stale
    idn, overrides = None, ()
    if sources.idn is not None and layer1 is not None:
        scores = {(s.subject, s.asset): s for s in layer1.scores}
        idn = gather_idn(day, reg, sources.idn, score=scores.get((HOME, "stocks")),
                         worldbankscape=sources.worldbankscape, history=history)
        overrides = idn.overrides.overrides
        stale += idn.stale_inputs
    foreign = None
    if sources.foreign is not None and layer1 is not None:
        foreign = gather_foreign(day, sources.foreign)
        overrides = (*overrides, *foreign_override_rows(foreign))
        stale += foreign.stale_inputs
    return Layers(day, layer1, reg, weights, overrides=tuple(overrides),
                  stale_inputs=sorted(set(stale)), idn=idn, foreign=foreign)


def gather_idn(day: date, reg: Regime, src: IdnSources, *, score: AssetScore | None = None,
               worldbankscape: Any = None, history: Sequence[Mapping] = ()) -> IdnLayers:
    """Indonesia's layers 2–4 on `day` (P17 overrides, P18 signals, P31 bonds rule, P22 stocks
    rule, layer-4 candidates) and each rule's verdict from its journalled calls."""
    ov = idn_overrides(day, bps=src.bps, bisfetcher=src.bisfetcher, dbnomics=src.dbnomics,
                       satudatascape=src.satudatascape)
    sig = idn_signals(day, idxscape=src.idxscape, kseistat=src.kseistat, tic=src.tic)
    bonds = idn_bonds(day, reg, ov, sig, phei=src.phei, dbnomics=src.dbnomics, bps=src.bps,
                      idxscape=src.idxscape)
    stocks = idn_stocks(day, reg, ov, sig, score, phei=src.phei, dbnomics=src.dbnomics,
                        bps=src.bps, idxmethod=src.idxmethod, snapshots=src.snapshots,
                        worldbankscape=worldbankscape)
    cands = idn_candidates(day, stocks=src.stocks)
    verdicts: dict[str, Verdict | None] = {
        "bonds": journalled_verdict(history, "bonds", _ten_year_months(src, day), day),
        "stocks": journalled_verdict(history, "stocks", _jci_months(src, day), day),
    }
    return IdnLayers(ov, sig, bonds, stocks, cands, verdicts)


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


def journalled_calls(history: Sequence[Mapping], asset: str,
                     before: date) -> dict[tuple[int, int], str]:
    """{(year, month): call} of the IDN `asset` rule from journal `rule` records dated before
    `before`; the last call in a month stands for the month."""
    calls: dict[tuple[int, int], str] = {}
    for rec in history:
        if (rec.get("kind") != "rule" or rec.get("subject") != HOME
                or rec.get("asset") != asset or not rec.get("as_of")):
            continue
        d = date.fromisoformat(rec["as_of"])
        if d < before:
            calls[_month(d)] = rec["outputs"]["call"]
    return calls


def journalled_verdict(history: Sequence[Mapping], asset: str,
                       prices: Sequence[tuple[date, float]], day: date,
                       horizon: int = RULE_HORIZON) -> Verdict:
    """Placebo verdict on the IDN `asset` rule's journalled calls made before `day`: does an
    enter precede a better forward return over `horizon` months (JCI for stocks, the 10Y return
    proxy for bonds) than a hold or reduce? Only calls made in the open count, so there is no
    look-ahead, and a same-day rerun sees the same calls. Until enough months have a forward
    return the verdict is an insufficient sample."""
    calls = journalled_calls(history, asset, day)
    keyed = {d: calls[_month(d)] for d, _ in prices if _month(d) in calls}
    fn = bonds_verdict if asset == "bonds" else stocks_verdict
    return fn(keyed, prices, horizon=horizon)


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
    gated, note = gate(stance.base_stance(score, layers.regime), rule, verdict)
    if rule.proposed_stance is not None:
        note += f" (verdict on its journalled calls: {_verdict_text(verdict)})"
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
    """One stance payload per in-scope score, in a stable order, each schema-valid."""
    v = stance_validator()
    out = []
    for s in sorted(layers.scores, key=lambda s: (s.subject, s.asset)):
        payload = stance.build_stance(score=s, regime=layers.regime, weights=layers.weights,
                                      overrides=layers.overrides, as_of=layers.day,
                                      fingerprint=fingerprint, rule=rule_view(s, layers))
        errors = sorted(v.iter_errors(payload), key=lambda e: list(e.absolute_path))
        if errors:  # a bug in this repo, not a data problem: stop before writing anything
            raise ValueError(f"{s.subject}/{s.asset} stance fails the schema: {errors[0].message}")
        out.append(payload)
    return out


# ---------------- write ----------------


def _write_if_changed(path: Path, text: str) -> None:
    if path.is_file() and path.read_text() == text:
        return  # keep the mtime of an unchanged file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
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
    j.record(kind="regime", fingerprint=fp, inputs={"day": layers.day}, outputs=layers.regime,
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
        p = stances.get((HOME, asset))
        j.record(kind="rule", fingerprint=fp, subject=HOME, asset=asset, as_of=layers.day,
                 run_id=run_id, inputs=rule,
                 outputs={"call": rule.call, "proposed_stance": rule.proposed_stance,
                          "stance": p["stance"] if p else None,
                          "verdict": None if verdict is None else
                          {k: v for k, v in verdict.to_dict().items() if k != "control_ts"}})
    j.record(kind="candidates", fingerprint=fp, subject=HOME, asset="stocks", as_of=layers.day,
             run_id=run_id, inputs={"order_idr": idn.candidates.order_idr},
             outputs=idn.candidates)


# ---------------- notify ----------------


def message(stances: Sequence[Mapping], *, regime: str | None, day: date,
            brief_path: Path | None) -> str:
    """The Telegram text: every home-market stance plus every non-neutral one elsewhere, so the
    message stays one Telegram part; the rest is counted and left to the brief."""
    shown = [s for s in stances if s.get("subject") == HOME or s.get("stance") != "neutral"]
    hidden = len(stances) - len(shown)
    text = notify.summary(shown, regime=regime, day=day)
    notes = []
    if hidden:
        notes.append(f"{hidden} neutral stance(s) elsewhere not shown")
    if brief_path is not None:
        notes.append(f"brief: {brief_path.name}")
    if notes:
        body, _, tail = text.rpartition("\n\n")  # keep the disclaimer last
        text = "\n".join([body, "", *notes, "", tail])
    return text


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


def run(day: date, *, paths: Paths | None = None, sources: Sources | None = None,
        send: bool = True, notify_kw: Mapping[str, Any] | None = None) -> RunResult:
    paths = paths or Paths.default()
    j = journal.Journal(paths.journal)
    layers = gather(day, sources or Sources.default(), history=list(j.read()))
    res = RunResult(ok=False, day=day, regime=layers.regime, stale_inputs=layers.stale_inputs,
                    problems=dict(layers.layer1.problems) if layers.layer1 else {},
                    idn=layers.idn, foreign=layers.foreign)
    if layers.layer1 is None or not layers.scores:
        return res  # no layer 1, no stance: leave out/ and the journal as they were

    fp = j.register_model()
    if fp != journal.model_fingerprint():  # cannot happen unless the model changes mid-run
        raise RuntimeError("model fingerprint changed during the run")
    res.fingerprint = fp
    res.stances = build(layers, fp)
    res.files = write_out(res.stances, paths.out)
    res.run_id = _journal(j, layers, res.stances, fp)

    text = brief.build_brief(paths.out, paths.snapshots)
    res.brief_path = paths.briefs / f"{day.isoformat()}.md"
    _write_if_changed(res.brief_path, text)
    brief.save_snapshot(paths.out, paths.snapshots, day.isoformat())
    res.ok = True

    if send:
        msg = message(res.stances, regime=f"{layers.regime.state}, dollar {layers.regime.dollar}",
                      day=day, brief_path=res.brief_path)
        res.notify = notify.send(msg, kind="brief", day=day, state_dir=paths.notify,
                                 **dict(notify_kw or {}))
    return res
