"""`assist run`: read the layers, build the stances, write out/, journal, brief, notify.

Phase A (PLAN S5–S6) wires layers 0, 1 and 5:

    worldbankscape (layer 1) ─┐
    sec-edgar FRED → regime (0) ├─ stance.build_stance ─→ out/{SUBJECT}/{asset}.json
    financer → weights (5) ────┘        │                  journal/decisions.jsonl
                                        └─→ brief (data/briefs/<day>.md) → Telegram once a day

Every step that reads a store degrades instead of failing: a missing regime or portfolio is named
in `stale_inputs` (and lowers confidence inside the stance). Only a missing layer 1 stops the
run, because without a score there is no stance; out/ is then left as it was.

Later layers plug in at `gather` (read) and `build` (combine): F2 adds the layer-2 overrides
(`Layers.overrides`, already passed through to `build_stance`), signals and the asset rules.

Order of the side effects, fixed by the brief's diff and the journal's fingerprint check:
write out/ → journal → `brief.build_brief` → `brief.save_snapshot` → `notify.send`.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from assist import brief, journal, notify, stance
from assist.layers import portfolio, regime
from assist.layers.types import (
    ASSETS,
    AssetScore,
    Override,
    Regime,
    Weights,
    stance_validator,
)
from assist.sources.base import SourceUnavailable
from assist.sources.worldbankscape import Layer1

__all__ = [
    "ASSETS",
    "COUNTRIES",
    "HOME",
    "Layers",
    "Paths",
    "RunResult",
    "Sources",
    "build",
    "gather",
    "in_scope",
    "message",
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
class Sources:
    """The stores a phase-A run reads; each is built from `config/sources.yaml` by default."""

    worldbankscape: Any
    fred: Any
    financer: Any

    @classmethod
    def default(cls) -> Sources:
        from assist.sources.financer import FinancerSource
        from assist.sources.usfin import FredSource
        from assist.sources.worldbankscape import WorldbankscapeSource

        return cls(worldbankscape=WorldbankscapeSource.from_config(), fred=FredSource(),
                   financer=FinancerSource.from_config())


# ---------------- read ----------------


@dataclass
class Layers:
    """What one run read. `layer1` is None when worldbankscape is unavailable."""

    day: date
    layer1: Layer1 | None
    regime: Regime
    weights: Weights | None
    overrides: tuple[Override, ...] = ()
    stale_inputs: list[str] = field(default_factory=list)

    @property
    def scores(self) -> list[AssetScore]:
        return [s for s in (self.layer1.scores if self.layer1 else []) if in_scope(s)]


def in_scope(s: AssetScore) -> bool:
    return s.asset in ASSETS and (s.asset == "commodities" or s.subject in COUNTRIES)


def gather(day: date, sources: Sources) -> Layers:
    """Read layers 0, 1 and 5 as of `day`. Never raises for a missing or locked store."""
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
    return Layers(day, layer1, reg, weights, stale_inputs=sorted(set(stale)))


# ---------------- combine ----------------


def build(layers: Layers, fingerprint: str) -> list[dict]:
    """One stance payload per in-scope score, in a stable order, each schema-valid."""
    v = stance_validator()
    out = []
    for s in sorted(layers.scores, key=lambda s: (s.subject, s.asset)):
        payload = stance.build_stance(score=s, regime=layers.regime, weights=layers.weights,
                                      overrides=layers.overrides, as_of=layers.day,
                                      fingerprint=fingerprint)
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
    return run_id


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


def run(day: date, *, paths: Paths | None = None, sources: Sources | None = None,
        send: bool = True, notify_kw: Mapping[str, Any] | None = None) -> RunResult:
    paths = paths or Paths.default()
    layers = gather(day, sources or Sources.default())
    res = RunResult(ok=False, day=day, regime=layers.regime, stale_inputs=layers.stale_inputs,
                    problems=dict(layers.layer1.problems) if layers.layer1 else {})
    if layers.layer1 is None or not layers.scores:
        return res  # no layer 1, no stance: leave out/ and the journal as they were

    j = journal.Journal(paths.journal)
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
