"""What each decision layer hands to the next, and the stance contract they end in.

Layer 0 → `Regime`, 1 → `AssetScore`, 2 → `Override`, 3 → `Signal`, 4 → `Candidate`,
5 → `Weights`. All are frozen and check their own ranges, so a bad value fails where it is made.
The stance JSON (`schema/stance.schema.json`) extends worldbankscape's `score.schema.json`,
vendored in `schema/worldbankscape/`; `stance_validator` and `score_validator` resolve it locally.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path

import jsonschema
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schema"
STANCE_SCHEMA = SCHEMA_DIR / "stance.schema.json"
SCORE_SCHEMA = SCHEMA_DIR / "worldbankscape" / "score.schema.json"

STANCES = ("overweight", "neutral", "underweight", "avoid")
REGIME_STATES = ("risk_on", "neutral", "risk_off")
DOLLAR_DIRECTIONS = ("up", "flat", "down")
ASSETS = ("stocks", "bonds", "currency", "commodities")
ENTRY_STYLES = ("lump", "ladder", "none")
DISCLAIMER = "Heuristic, not investment advice."
MAX_OVERRIDE = 10.0  # layer 2 shifts the layer-1 score by at most this many points
WEIGHT_TOLERANCE = 0.5  # percentage points of rounding allowed around 100


def _check(ok: bool, msg: str) -> None:
    if not ok:
        raise ValueError(msg)


def _one_of(value: str, allowed: tuple[str, ...], what: str) -> None:
    _check(value in allowed, f"{what} must be one of {allowed}, got {value!r}")


@dataclass(frozen=True)
class Regime:
    """Layer 0: global risk regime and broad-dollar direction."""

    as_of: date
    state: str
    dollar: str
    drivers: tuple[str, ...] = ()
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def __post_init__(self):
        _one_of(self.state, REGIME_STATES, "regime state")
        _one_of(self.dollar, DOLLAR_DIRECTIONS, "dollar direction")


@dataclass(frozen=True)
class AssetScore:
    """Layer 1: worldbankscape's structural score (0–100, 50 neutral) for subject × asset."""

    subject: str
    asset: str
    as_of: date
    score: float
    confidence: float
    raw_score: float | None = None
    coverage: float | None = None
    flags: tuple[dict, ...] = ()
    stale_inputs: tuple[str, ...] = ()
    source: str = "worldbankscape"

    def __post_init__(self):
        _check(0 <= self.score <= 100, f"score must be 0..100, got {self.score}")
        _check(0 <= self.confidence <= 1, f"confidence must be 0..1, got {self.confidence}")


@dataclass(frozen=True)
class Override:
    """Layer 2: fresh macro momentum, a bounded shift of the layer-1 score."""

    subject: str
    asset: str
    as_of: date
    delta: float
    reason: str
    sources: tuple[str, ...]
    stale_inputs: tuple[str, ...] = ()

    def __post_init__(self):
        _check(
            abs(self.delta) <= MAX_OVERRIDE,
            f"override delta must be within ±{MAX_OVERRIDE}, got {self.delta}",
        )


@dataclass(frozen=True)
class Signal:
    """Layer 3: one market signal (flows, curve, valuation); direction −1, 0 or +1."""

    subject: str
    asset: str
    as_of: date
    name: str
    value: float | None
    direction: int
    source: str
    detail: str = ""

    def __post_init__(self):
        _check(self.direction in (-1, 0, 1), f"direction must be -1, 0 or 1, got {self.direction}")


@dataclass(frozen=True)
class Candidate:
    """Layer 4: an instrument a screen names. A screen names nothing until it beats its placebo."""

    subject: str
    asset: str
    as_of: date
    symbol: str
    screen: str
    score: float
    source: str
    entry_level: float | None = None
    detail: str = ""


@dataclass(frozen=True)
class Weights:
    """Layer 5: current holdings as % of the portfolio per (subject, asset); cash is an asset.
    Positions that map to nothing are listed in `unmapped`, never guessed."""

    as_of: date
    weights: dict[tuple[str, str], float]
    unmapped: tuple[str, ...] = ()
    sources: tuple[str, ...] = ("financer",)
    stale_inputs: tuple[str, ...] = ()
    total_idr: float | None = field(default=None)

    def __post_init__(self):
        total = sum(self.weights.values())
        _check(
            not self.weights or abs(total - 100) <= WEIGHT_TOLERANCE,
            f"weights must add up to 100, got {total:.2f}",
        )

    def pct(self, subject: str, asset: str) -> float | None:
        return self.weights.get((subject, asset))


# ---------------- JSON Schema ----------------


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def _registry() -> Registry:
    resources = [Resource.from_contents(_load(p)) for p in (STANCE_SCHEMA, SCORE_SCHEMA)]
    return Registry().with_resources((r.id(), r) for r in resources)


def _validator(path: Path) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(
        _load(path),
        registry=_registry(),
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )


def stance_validator() -> jsonschema.Draft202012Validator:
    return _validator(STANCE_SCHEMA)


def score_validator() -> jsonschema.Draft202012Validator:
    """worldbankscape's layer-1 payload contract (`out/{SUBJECT}/{asset_class}.json`)."""
    return _validator(SCORE_SCHEMA)
