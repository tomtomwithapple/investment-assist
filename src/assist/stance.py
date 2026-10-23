"""Stance v0 (PLAN S5): layers 0 + 1 + 5 → one stance payload per subject × asset.

A pure function over the layer types: the layer-1 score (worldbankscape), shifted by the layer-0
regime and any layer-2 overrides, falls into a stance band; the stance tilts a target weight away
from its anchor (the benchmark weight when one is given, else the current holding); the gap to the
current holding (layer 5, financer) is the delta, bought lump-sum, or in a ladder when the regime
is risk_off. A missing regime or holdings is named in `stale_inputs` and lowers the confidence,
never raises. `dumps` writes sorted keys and rounded floats, so identical inputs give identical
bytes.

Every number below is hand-set and stays so until a rule using it beats its placebo control.
TODO(PLAN.md, Open questions): the target weight bands (`TILT_PT`, `BENCHMARK_PCT`) need the
user's risk limits and benchmark choice confirmed. Until then the tilts are placeholders, no
position cap or portfolio-level limit is applied, and with no benchmark the current holding is
the anchor, so a stance only says which way and how far to move from what is held.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date

from assist.layers.types import (
    DISCLAIMER,
    MAX_OVERRIDE,
    AssetScore,
    Override,
    Regime,
    Weights,
)

__all__ = [
    "BENCHMARK_PCT",
    "DISCLAIMER",
    "LADDER_SPACING_DAYS",
    "LADDER_TRANCHES",
    "MODEL_CONFIG",
    "REGIME_SHIFT",
    "SCHEMA_VERSION",
    "STALE_PENALTY",
    "STANCE_BANDS",
    "TILT_PT",
    "build_stance",
    "dumps",
    "model_fingerprint",
    "stance_for",
]

SCHEMA_VERSION = "1.0.0"
MODEL_VERSION = "0.1.0"

# Layer-0 shift of the layer-1 score, in points (same for every asset in v0).
REGIME_SHIFT = {"risk_on": 5.0, "neutral": 0.0, "risk_off": -5.0}

# (lowest score, stance), checked top down; anything below the last band is "avoid".
STANCE_BANDS = ((60.0, "overweight"), (40.0, "neutral"), (25.0, "underweight"))

# TODO(open question): placeholder tilts in percentage points of the portfolio, not risk limits.
TILT_PT = {"overweight": 5.0, "neutral": 0.0, "underweight": -5.0}  # "avoid" targets 0
# TODO(open question): benchmark weight per (subject, asset); empty until the user sets it.
BENCHMARK_PCT: dict[tuple[str, str], float] = {}

LADDER_TRANCHES = 3
LADDER_SPACING_DAYS = 10
STALE_PENALTY = 0.9  # confidence multiplier per stale or missing input

MODEL_CONFIG = {
    "model_version": MODEL_VERSION,
    "regime_shift": REGIME_SHIFT,
    "stance_bands": [list(b) for b in STANCE_BANDS],
    "tilt_pt": TILT_PT,
    "benchmark_pct": {f"{s}/{a}": v for (s, a), v in sorted(BENCHMARK_PCT.items())},
    "ladder": {"tranches": LADDER_TRANCHES, "spacing_days": LADDER_SPACING_DAYS},
    "stale_penalty": STALE_PENALTY,
    "max_override": MAX_OVERRIDE,
}


def model_fingerprint(config: Mapping | None = None) -> str:
    """sha256 of the canonical JSON of the stance config; any change segments the journal."""
    blob = json.dumps(MODEL_CONFIG if config is None else config, sort_keys=True,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def stance_for(score: float) -> str:
    for floor, stance in STANCE_BANDS:
        if score >= floor:
            return stance
    return "avoid"


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return min(hi, max(lo, x))


def _r(x: float, nd: int = 1) -> float:
    return float(round(x, nd)) + 0.0  # + 0.0 turns -0.0 into 0.0


def build_stance(
    *,
    score: AssetScore,
    regime: Regime | None,
    weights: Weights | None,
    overrides: Sequence[Override] = (),
    benchmark: Mapping[tuple[str, str], float] | None = None,
    subject: str | None = None,
    asset: str | None = None,
    as_of: date | None = None,
    fingerprint: str | None = None,
) -> dict:
    """Stance payload (schema/stance.schema.json) for `score.subject` × `score.asset`.

    `regime` or `weights` may be None (store missing or locked): the regime is then taken as
    neutral, holdings as unknown, and each is named in `stale_inputs`."""
    key = (score.subject, score.asset)
    if (subject and subject != key[0]) or (asset and asset != key[1]):
        raise ValueError(f"score is for {key}, asked for {(subject, asset)}")

    stale: set[str] = set(score.stale_inputs)
    sources: set[str] = {score.source}
    drivers = [f"layer-1 score {score.score:.1f}"]
    risks: list[str] = []

    state, dollar = "neutral", None
    if regime is None:
        stale.add("regime")
    else:
        state, dollar = regime.state, regime.dollar
        stale.update(regime.stale_inputs)
        sources.update(regime.sources)
    shift = REGIME_SHIFT[state]
    if shift:
        drivers.append(f"regime {state} ({shift:+.1f}pt)")
    if state == "risk_off":
        risks.append("global regime risk_off")
    if dollar == "up":
        risks.append("broad dollar rising")

    mine = [o for o in overrides if (o.subject, o.asset) == key]
    for o in mine:
        drivers.append(f"{o.reason} ({o.delta:+.1f}pt)")
        stale.update(o.stale_inputs)
        sources.update(o.sources)
    override = _clip(sum(o.delta for o in mine), -MAX_OVERRIDE, MAX_OVERRIDE)
    if regime is not None:
        drivers.extend(regime.drivers)

    final = _r(_clip(score.score + shift + override))
    stance = stance_for(final)

    current: float | None = None
    if weights is None:
        stale.add("financer")
    else:
        current = _r(weights.pct(*key) or 0.0)
        stale.update(weights.stale_inputs)
        sources.update(weights.sources)
        if weights.unmapped:
            risks.append(f"{len(weights.unmapped)} unmapped holding(s) not counted")

    bench = (BENCHMARK_PCT if benchmark is None else benchmark).get(key)
    anchor = bench if bench is not None else (current or 0.0)
    target = 0.0 if stance == "avoid" else _r(_clip(anchor + TILT_PT[stance]))

    if current is None:
        delta_text = "n/a (holdings unavailable)"
        entry = {"style": "none", "tranches": 0, "spacing_days": 0}
    else:
        gap = _r(target - current)
        if gap > 0 and state == "risk_off":
            delta_text = f"+{gap:.1f}pt over {LADDER_TRANCHES} tranches"
            entry = {"style": "ladder", "tranches": LADDER_TRANCHES,
                     "spacing_days": LADDER_SPACING_DAYS}
        elif gap > 0:
            delta_text = f"+{gap:.1f}pt lump"
            entry = {"style": "lump", "tranches": 1, "spacing_days": 0}
        else:
            delta_text = f"{gap:.1f}pt trim" if gap < 0 else "0.0pt hold"
            entry = {"style": "none", "tranches": 0, "spacing_days": 0}

    dates = [d for d in (score.as_of, regime and regime.as_of, weights and weights.as_of) if d]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "subject": key[0],
        "asset": key[1],
        "as_of": (as_of or max(dates)).isoformat(),
        "model_version": MODEL_VERSION,
        "model_fingerprint": fingerprint or model_fingerprint(),
        "stance": stance,
        "score": final,
        "layer1_score": _r(score.score),
        "confidence": _r(score.confidence * STALE_PENALTY ** len(stale), 2),
        "regime": state,
        "drivers": drivers,
        "risks": risks,
        "watch": [],
        "entry": entry,
        "portfolio": {"current_pct": current, "target_pct": target, "delta": delta_text},
        "flags": [dict(f) for f in score.flags],
        "stale_inputs": sorted(stale),
        "sources": sorted(sources),
        "disclaimer": DISCLAIMER,
    }
    if dollar is not None:
        payload["dollar"] = dollar
    return payload


def dumps(payload: Mapping) -> str:
    """Canonical text of a payload: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
