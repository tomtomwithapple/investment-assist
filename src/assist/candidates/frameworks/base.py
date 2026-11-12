"""FrameworkResult, the Framework base and the registry (PLAN S93, phase Q rules 1 and 2).

Every framework of phase Q (Piotroski, bank residual income, Graham, Magic Formula, ...) returns
one `FrameworkResult` per name: the frameworks document's §0.2 fields plus

- `role`: what the result may do. `context` (the default) is shown and journalled and changes
  nothing. `exclusion` (blocks buys only, never sells a held name), `quality` and `valuation`
  are reached only through a passed placebo, the user's adoption and a separate model change
  (rule 2). A framework is never a second verdict source (phase P rule 1), so there is no
  verdict role.
- `gate`: its placebo state, `untested | failed | passed`.

Never impute (§0.3): a result that cannot be computed has `score=None`, `signal="n/a"` and at
least one flag saying why; `missing` builds it, and the dataclass refuses a None score without a
flag, or a NaN or infinite number anywhere. `as_of` is the date the signal could first be known
(the `Fundamentals.available` date it read), None only when nothing was read.

A framework module subclasses `Framework` and calls `register` on it; `__init__` imports every
module of this package, so adding a framework is adding one file. `evaluate` runs the
registered frameworks of the asked roles over one name, in name order, and turns an exception
into an n/a result with the error flagged, so one broken framework never breaks a run.

Hashed by `journal.RULE_GLOBS` (`candidates/**/*.py`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar

__all__ = ["GATES", "NA", "REGISTRY", "ROLES", "Framework", "FrameworkResult", "evaluate",
           "missing", "register", "registered"]

VERSION = "0.1.0"
ROLES = ("context", "exclusion", "quality", "valuation")
GATES = ("untested", "failed", "passed")
NA = "n/a"


def _finite(x: Any, what: str) -> float | None:
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(f"{what} must be a finite number or None, got {x!r}")
    return float(x)


@dataclass(frozen=True)
class FrameworkResult:
    framework: str  # "piotroski_f", "bank_ri", ...
    ticker: str
    as_of: date | None  # the date the signal could have been known
    score: float | None  # None when not computable (then flags say why)
    signal: str  # "pass" | "fail" | "safe" | "grey" | ... | "n/a"
    components: Mapping[str, float | None] = field(default_factory=dict)  # every input, audit
    flags: tuple[str, ...] = ()  # data gaps, sector exclusions, warnings
    version: str = ""  # the framework's VERSION
    role: str = "context"
    gate: str = "untested"

    def __post_init__(self) -> None:
        if not self.framework or not self.ticker or not self.signal or not self.version:
            raise ValueError("framework, ticker, signal and version are required")
        if self.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}, got {self.role!r}")
        if self.gate not in GATES:
            raise ValueError(f"gate must be one of {GATES}, got {self.gate!r}")
        if self.as_of is not None and not isinstance(self.as_of, date):
            raise ValueError(f"as_of must be a date or None, got {self.as_of!r}")
        object.__setattr__(self, "score", _finite(self.score, "score"))
        object.__setattr__(self, "components", {
            str(k): _finite(v, f"component {k}") for k, v in dict(self.components).items()})
        object.__setattr__(self, "flags", tuple(str(f) for f in self.flags))
        if self.score is None and not self.flags:
            raise ValueError("a result with no score needs a flag saying why (never impute)")

    def to_dict(self) -> dict:
        return {"framework": self.framework, "ticker": self.ticker,
                "as_of": None if self.as_of is None else self.as_of.isoformat(),
                "score": self.score, "signal": self.signal,
                "components": dict(self.components), "flags": list(self.flags),
                "version": self.version, "role": self.role, "gate": self.gate}

    @classmethod
    def from_dict(cls, d: Mapping) -> FrameworkResult:
        a = d.get("as_of")
        return cls(framework=d["framework"], ticker=d["ticker"],
                   as_of=date.fromisoformat(a) if isinstance(a, str) else a,
                   score=d.get("score"), signal=d["signal"],
                   components=dict(d.get("components") or {}),
                   flags=tuple(d.get("flags") or ()), version=d["version"],
                   role=d.get("role", "context"), gate=d.get("gate", "untested"))


def missing(name: str, ticker: str, as_of: date | None, *flags: str, version: str,
            role: str = "context", gate: str = "untested",
            components: Mapping[str, float | None] | None = None) -> FrameworkResult:
    """The n/a result: `score=None`, `signal="n/a"`, and the flags (at least one) saying why."""
    if not flags:
        raise ValueError("missing() needs at least one flag saying why")
    return FrameworkResult(name, ticker, as_of, None, NA, dict(components or {}), tuple(flags),
                           version, role, gate)


class Framework:
    """Base of one framework: set `name`, `VERSION` (and `role`, `gate` once earned) and write
    `evaluate(sym, inputs) -> FrameworkResult`, building it with `result` or `missing`."""

    name: ClassVar[str] = ""
    VERSION: ClassVar[str] = ""
    role: ClassVar[str] = "context"
    gate: ClassVar[str] = "untested"

    def evaluate(self, sym: str, inputs: Any) -> FrameworkResult:
        raise NotImplementedError

    def result(self, sym: str, as_of: date | None, score: float | None, signal: str,
               components: Mapping[str, float | None], *flags: str) -> FrameworkResult:
        return FrameworkResult(self.name, sym, as_of, score, signal, dict(components),
                               tuple(flags), self.VERSION, self.role, self.gate)

    def missing(self, sym: str, as_of: date | None, *flags: str,
                components: Mapping[str, float | None] | None = None) -> FrameworkResult:
        return missing(self.name, sym, as_of, *flags, version=self.VERSION, role=self.role,
                       gate=self.gate, components=components)


REGISTRY: dict[str, Framework] = {}


def register(fw: Framework | type[Framework]) -> Any:
    """Add a framework (an instance, or a class, which is instantiated); usable as a class
    decorator. Returns its argument."""
    inst = fw() if isinstance(fw, type) else fw
    if not inst.name or not inst.VERSION:
        raise ValueError(f"{type(inst).__name__}: name and VERSION are required")
    if inst.role not in ROLES or inst.gate not in GATES:
        raise ValueError(f"{inst.name}: role {inst.role!r} or gate {inst.gate!r} unknown")
    if inst.name in REGISTRY:
        raise ValueError(f"framework {inst.name!r} is already registered")
    REGISTRY[inst.name] = inst
    return fw


def registered() -> list[Framework]:
    return [REGISTRY[k] for k in sorted(REGISTRY)]


def evaluate(sym: str, inputs: Any, *, roles: Iterable[str] = ("context",)
             ) -> list[FrameworkResult]:
    """Every registered framework whose role is in `roles`, over `sym`, in name order."""
    want = set(roles)
    out = []
    for f in registered():
        if f.role not in want:
            continue
        try:
            r = f.evaluate(sym, inputs)
            if (r.framework, r.ticker, r.version, r.role) != (f.name, sym, f.VERSION, f.role):
                raise ValueError(f"result {r.framework}/{r.ticker} v{r.version} ({r.role}) "
                                 f"is not {f.name}/{sym} v{f.VERSION} ({f.role})")
        except Exception as e:  # noqa: BLE001 - one broken framework never breaks a run
            r = f.missing(sym, None, f"error: {type(e).__name__}: {e}")
        out.append(r)
    return out
