"""Placebo-control walk-forward harness: a rule passes only if it beats its shuffled-date
control AND the same procedure run on shuffled dates shows no edge of its own."""

import random
from datetime import date, timedelta

import pytest

from assist.eval.placebo import (
    SEED,
    Edge,
    align,
    block_shuffle,
    edge,
    evaluate,
    forward_returns,
    walk_forward,
)

START = date(2020, 1, 1)


def _days(n):
    return [START + timedelta(days=i) for i in range(n)]


def _panel(n=400, effect=0.0, seed=7):
    """Feature x ~ N(0,1); next return = effect * (x < -0.5 ? -1 : 0) + noise."""
    rng = random.Random(seed)
    xs = [rng.gauss(0, 1) for _ in range(n)]
    rets = [(-effect if x < -0.5 else 0.0) + rng.gauss(0, 0.01) for x in xs]
    return xs, rets


def fixed_rule(feats, rets):
    return [x < -0.5 for x in feats]


def peeking_rule(feats, rets):
    """Fits noise: it looks at the very returns it is scored on."""
    return [r < 0 for r in rets]


# --- primitives -------------------------------------------------------------------------------

def test_forward_returns_simple_and_drops_tail():
    d = _days(4)
    prices = list(zip(d, [100.0, 110.0, 99.0, 99.0], strict=True))
    out = forward_returns(prices, horizon=1)
    assert [x[0] for x in out] == d[:3]
    assert out[0][1] == pytest.approx(0.10)
    assert out[1][1] == pytest.approx(-0.10)
    assert forward_returns(prices, horizon=2)[0][1] == pytest.approx(-0.01)


def test_forward_returns_sorts_input():
    d = _days(3)
    prices = [(d[2], 121.0), (d[0], 100.0), (d[1], 110.0)]
    assert forward_returns(prices, horizon=2) == [(d[0], pytest.approx(0.21))]


def test_align_inner_joins_on_date():
    d = _days(4)
    dates, feats, rets = align({d[0]: "a", d[1]: "b", d[3]: "d"}, [(d[1], 0.1), (d[2], 0.2),
                                                                     (d[3], 0.3)])
    assert dates == [d[1], d[3]]
    assert feats == ["b", "d"]
    assert rets == [0.1, 0.3]


def test_edge_welch_t():
    sig = [True, True, True, False, False, False]
    rets = [1.0, 2.0, 3.0, 0.0, 1.0, 2.0]
    e = edge(sig, rets, min_n=2)
    assert isinstance(e, Edge)
    assert (e.n_on, e.n_off) == (3, 3)
    assert e.diff == pytest.approx(1.0)
    # Welch: var 1 each side -> se = sqrt(1/3 + 1/3)
    assert e.t == pytest.approx(1.0 / (2 / 3) ** 0.5)
    assert edge(sig, rets, direction=-1, min_n=2).t == pytest.approx(-e.t)


def test_edge_skips_none_and_strides():
    sig = [True, None, False, True, None, False]
    rets = [1.0, 99.0, 0.0, 3.0, 99.0, 2.0]
    e = edge(sig, rets, min_n=1)
    assert (e.n_on, e.n_off) == (2, 2)
    assert e.mean_on == pytest.approx(2.0)
    e2 = edge(sig, rets, stride=3, min_n=1)  # keeps indexes 0 and 3
    assert (e2.n_on, e2.n_off) == (2, 0)
    assert e2.t == 0.0 and not e2.ok


def test_edge_insufficient_sample_not_ok():
    e = edge([True, False, False], [1.0, 0.0, 0.1], min_n=2)
    assert not e.ok and e.t == 0.0


def test_block_shuffle_is_a_seeded_permutation_keeping_blocks():
    vals = list(range(12))
    a = block_shuffle(vals, random.Random(1), block=3)
    b = block_shuffle(vals, random.Random(1), block=3)
    assert a == b and sorted(a) == vals and a != vals
    blocks = [a[i:i + 3] for i in range(0, 12, 3)]
    assert all(blk == list(range(blk[0], blk[0] + 3)) for blk in blocks)


# --- walk-forward -----------------------------------------------------------------------------

def test_walk_forward_only_uses_past_data():
    seen = []

    def fit(train_feats, train_rets):
        seen.append(len(train_feats))
        cut = sorted(train_feats)[len(train_feats) // 2]
        return lambda x: x < cut

    proc = walk_forward(fit, train=10, test=5)
    feats = list(range(30))
    sig = proc(feats, [0.0] * 30)
    assert sig[:10] == [None] * 10
    assert all(s is not None for s in sig[10:])
    assert seen == [10, 15, 20, 25]  # expanding window refit every `test` steps


def test_walk_forward_rolling_window():
    seen = []

    def fit(train_feats, train_rets):
        seen.append((train_feats[0], len(train_feats)))
        return lambda x: True

    walk_forward(fit, train=10, test=5, expanding=False)(list(range(30)), [0.0] * 30)
    assert seen == [(0, 10), (5, 10), (10, 10), (15, 10)]


# --- verdict ----------------------------------------------------------------------------------

def test_real_rule_passes():
    xs, rets = _panel(effect=0.01)
    v = evaluate(fixed_rule, xs, rets, direction=-1, n_shuffles=200, n_controls=10)
    assert v.rule.diff < 0  # raw diff: weaker returns when active; t is signed by direction
    assert v.score_t >= 2.0
    assert v.p_value <= 0.05
    assert abs(v.control_t) < 2.0
    assert v.passed, v.reason


def test_noise_rule_fails_on_beating_placebo():
    xs, rets = _panel(effect=0.0)
    v = evaluate(fixed_rule, xs, rets, direction=-1, n_shuffles=200, n_controls=10)
    assert not v.passed
    assert "placebo" in v.reason or "t-stat" in v.reason


def test_peeking_procedure_fails_because_control_shows_edge():
    xs, rets = _panel(effect=0.0)
    v = evaluate(peeking_rule, xs, rets, direction=-1, n_shuffles=200, n_controls=10)
    assert v.score_t >= 2.0  # looks great on real data...
    assert v.control_t >= 2.0  # ...and just as great on shuffled dates
    assert not v.passed
    assert "fitting noise" in v.reason


def test_walk_forward_procedure_end_to_end():
    xs, rets = _panel(n=600, effect=0.01)

    def fit(train_feats, train_rets):
        lo = sorted(train_feats)[len(train_feats) // 4]  # learned threshold
        return lambda x: x < lo

    v = evaluate(walk_forward(fit, train=200, test=50), xs, rets, direction=-1,
                 n_shuffles=200, n_controls=10)
    assert v.passed, v.reason
    assert v.rule.n_on + v.rule.n_off == 400


def test_deterministic_with_default_seed():
    xs, rets = _panel(effect=0.004)
    a = evaluate(fixed_rule, xs, rets, direction=-1, n_shuffles=100, n_controls=5)
    b = evaluate(fixed_rule, xs, rets, direction=-1, n_shuffles=100, n_controls=5)
    assert a == b and a.seed == SEED
    c = evaluate(fixed_rule, xs, rets, direction=-1, n_shuffles=100, n_controls=5, seed=SEED + 1)
    assert c.p_value != a.p_value or c.control_t != a.control_t


def test_insufficient_sample_fails_with_reason():
    v = evaluate(fixed_rule, [-1.0, 1.0, -1.0], [0.0, 0.1, 0.0], n_shuffles=10, n_controls=2)
    assert not v.passed and "insufficient" in v.reason


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        evaluate(fixed_rule, [1.0, 2.0], [0.1])


def test_to_dict_is_journal_ready():
    xs, rets = _panel(effect=0.01)
    d = evaluate(fixed_rule, xs, rets, direction=-1, n_shuffles=50, n_controls=3).to_dict()
    for key in ("passed", "reason", "rule", "score_t", "p_value", "control_t", "seed",
                "n_shuffles", "n_controls", "block", "stride", "direction", "t_min", "alpha"):
        assert key in d
    assert set(d["rule"]) >= {"n_on", "n_off", "mean_on", "mean_off", "diff", "t"}
