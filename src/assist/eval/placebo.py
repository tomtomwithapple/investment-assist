"""Placebo-control walk-forward harness.

A *procedure* turns aligned features and forward returns into one signal per date (truthy =
rule active, falsy = inactive, None = no call, e.g. walk-forward warm-up). Its edge is the
difference in mean forward return between active and inactive dates, with a Welch t-stat,
signed by `direction` (−1 when the rule predicts weaker returns, as `risk_off` does).

`evaluate` runs it twice over:

- **rule vs placebo**: the real signal against `n_shuffles` block-shuffled-date permutations
  of the returns; `p_value` is the share of permutations scoring at least as well.
- **control**: the whole procedure rerun `n_controls` times on shuffled dates. A procedure that
  still finds an edge there (mean control t ≥ `t_min`) is fitting noise or peeking, so it fails
  however good it looks on the real dates.

Verdict = rule beats placebo AND the control shows no edge. Everything is seeded (`SEED`), so a
rerun with the same inputs gives the same verdict. Overlapping forward returns inflate t-stats:
pass `stride=horizon` to score non-overlapping dates and `block≈horizon` to keep their
autocorrelation in the shuffles.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from statistics import fmean, variance
from typing import Any

SEED = 20261023
T_MIN = 2.0
ALPHA = 0.05
MIN_N = 10

Signal = Any  # truthy / falsy / None
Procedure = Callable[[Sequence[Any], Sequence[float]], Sequence[Signal]]
Fit = Callable[[Sequence[Any], Sequence[float]], Callable[[Any], Signal]]


@dataclass(frozen=True)
class Edge:
    """Active-minus-inactive mean forward return; `t` is Welch's t, signed by direction."""

    n_on: int
    n_off: int
    mean_on: float
    mean_off: float
    diff: float
    t: float
    ok: bool


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str
    rule: Edge
    score_t: float  # direction * rule.t: positive means the rule works as claimed
    p_value: float
    control_t: float
    control_ts: tuple[float, ...]
    seed: int
    n_shuffles: int
    n_controls: int
    block: int
    stride: int
    direction: int
    t_min: float
    alpha: float

    def to_dict(self) -> dict:
        return asdict(self)


def forward_returns(prices: Iterable[tuple[date, float]], horizon: int) -> list[tuple[date, float]]:
    """Simple return from each date to `horizon` observations later; the tail is dropped."""
    pts = sorted(prices)
    return [(d, pts[i + horizon][1] / p - 1.0) for i, (d, p) in enumerate(pts[:-horizon] if
                                                                           horizon else pts)]


def align(
    features: Mapping[date, Any] | Iterable[tuple[date, Any]],
    returns: Mapping[date, float] | Iterable[tuple[date, float]],
) -> tuple[list[date], list[Any], list[float]]:
    """Inner-join features and forward returns on date, in date order."""
    f = dict(features.items() if isinstance(features, Mapping) else features)
    r = dict(returns.items() if isinstance(returns, Mapping) else returns)
    dates = sorted(f.keys() & r.keys())
    return dates, [f[d] for d in dates], [r[d] for d in dates]


def edge(
    signal: Sequence[Signal],
    returns: Sequence[float],
    *,
    direction: int = 1,
    stride: int = 1,
    min_n: int = MIN_N,
) -> Edge:
    on: list[float] = []
    off: list[float] = []
    for i in range(0, len(signal), stride):
        if signal[i] is not None:
            (on if signal[i] else off).append(returns[i])
    mean_on = fmean(on) if on else 0.0
    mean_off = fmean(off) if off else 0.0
    diff = mean_on - mean_off
    t = 0.0
    ok = len(on) >= max(min_n, 2) and len(off) >= max(min_n, 2)
    if ok:
        se = (variance(on) / len(on) + variance(off) / len(off)) ** 0.5
        ok = se > 0
        t = direction * diff / se if ok else 0.0
    return Edge(len(on), len(off), mean_on, mean_off, diff, t, ok)


def block_shuffle(values: Sequence[Any], rng: random.Random, block: int = 1) -> list[Any]:
    """Permute `values` in contiguous blocks (the last may be short), keeping order inside each."""
    blocks = [list(values[i:i + block]) for i in range(0, len(values), block)]
    rng.shuffle(blocks)
    return [v for b in blocks for v in b]


def walk_forward(fit: Fit, *, train: int, test: int, gap: int = 0,
                 expanding: bool = True) -> Procedure:
    """Refit every `test` dates on the past only, then call the next `test` dates out of sample.

    `gap` drops the last training dates whose forward returns overlap the test window (use
    horizon − 1). Dates before the first fit get None.
    """

    def procedure(feats: Sequence[Any], rets: Sequence[float]) -> list[Signal]:
        sig: list[Signal] = [None] * len(feats)
        for start in range(train, len(feats), test):
            hi = start - gap
            lo = 0 if expanding else max(0, start - train)
            predict = fit(feats[lo:hi], rets[lo:hi])
            for i in range(start, min(start + test, len(feats))):
                sig[i] = predict(feats[i])
        return sig

    return procedure


def evaluate(
    procedure: Procedure,
    features: Sequence[Any],
    returns: Sequence[float],
    *,
    direction: int = 1,
    n_shuffles: int = 1000,
    n_controls: int = 20,
    seed: int = SEED,
    block: int = 1,
    stride: int = 1,
    t_min: float = T_MIN,
    alpha: float = ALPHA,
    min_n: int = MIN_N,
) -> Verdict:
    if len(features) != len(returns):
        raise ValueError(f"features ({len(features)}) and returns ({len(returns)}) differ")
    returns = list(returns)
    signal = list(procedure(features, returns))
    rule = edge(signal, returns, direction=direction, stride=stride, min_n=min_n)

    def score(e: Edge) -> float:
        return direction * e.diff

    perm_rng = random.Random(f"{seed}:placebo")
    beaten = sum(
        score(edge(signal, block_shuffle(returns, perm_rng, block), stride=stride, min_n=0))
        >= score(rule)
        for _ in range(n_shuffles)
    )
    p_value = (1 + beaten) / (1 + n_shuffles)

    ctrl_rng = random.Random(f"{seed}:control")
    control_ts = []
    for _ in range(n_controls):
        shuffled = block_shuffle(returns, ctrl_rng, block)
        ctrl = procedure(features, shuffled)
        control_ts.append(edge(ctrl, shuffled, direction=direction, stride=stride,
                               min_n=min_n).t)
    control_t = fmean(control_ts) if control_ts else 0.0

    if not rule.ok:
        passed, reason = False, f"insufficient sample (on {rule.n_on}, off {rule.n_off})"
    elif control_t >= t_min:
        passed, reason = False, (f"control shows an edge (mean t {control_t:.2f} on shuffled "
                                 "dates): the procedure is fitting noise")
    elif rule.t < t_min:
        passed, reason = False, f"t-stat {rule.t:.2f} below {t_min}"
    elif p_value > alpha:
        passed, reason = False, f"does not beat placebo (p {p_value:.3f} > {alpha})"
    else:
        passed, reason = True, (f"beats placebo (t {rule.t:.2f}, p {p_value:.3f}); "
                                f"control t {control_t:.2f}")

    return Verdict(passed, reason, rule, rule.t, p_value, control_t, tuple(control_ts), seed,
                   n_shuffles, n_controls, block, stride, direction, t_min, alpha)
