"""Dimson beta (P117, PLAN S100) on synthetic weekly series with a known lag.

The market's weekly return m_t is a fixed pseudo-random draw. A stock that answers half the
market move in the same week and 0.8 of it a week late (r_t = 0.5·m_t + 0.8·m_{t−1}, a thinly
traded name) has a raw beta near 0.5 but a Dimson beta of exactly 0.5 + 0.8 = 1.3 (the lead
beta is 0), with R² = 1.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from assist.candidates import frameworks as fw
from assist.candidates.frameworks import dimson_beta as db
from assist.candidates.frameworks.lynch import LynchBetaInputs
from assist.sources.idxmethod_series import Bar

FRI0 = date(2022, 1, 7)  # a Friday
WEEKS = 170


def market(seed=7, n=WEEKS):
    rng = random.Random(seed)
    return [rng.gauss(0.002, 0.025) for _ in range(n)]


def series(rets, start=1000.0):
    out, p = [start], start
    for r in rets:
        p *= 1 + r
        out.append(p)
    return out


def fridays(n):
    return [FRI0 + timedelta(weeks=k) for k in range(n)]


def lagged(m, now=0.5, lag=0.8):
    return [now * m[t] + (lag * m[t - 1] if t else 0.0) for t in range(len(m))]


def as_inputs(stock_px, jci_px, d):
    ds = fridays(len(stock_px))
    bars = [Bar(x, p, p * 1e9) for x, p in zip(ds, stock_px, strict=True)]
    jci = list(zip(ds, jci_px, strict=True))
    return bars, jci, d


def test_ols_recovers_a_known_lag():
    m = market()
    r = lagged(m)
    est = db.dimson_ols(r[1:], m[1:])  # aligned weekly returns
    assert est["dimson_beta"] == pytest.approx(1.3, abs=1e-9)
    assert est["beta_lag"] == pytest.approx(0.8, abs=1e-9)
    assert est["beta_lead"] == pytest.approx(0.0, abs=1e-9)
    assert est["r2"] == pytest.approx(1.0, abs=1e-9)
    assert est["raw_beta"] < 0.7  # the lag biases the plain beta down
    assert est["n"] == len(m) - 1 - 2  # one week lost at each end to the lag and the lead


def test_dimson_from_bars_and_jci():
    m = market()
    bars, jci, _ = as_inputs(series(lagged(m)), series(m), None)
    d = bars[-1].date
    res = db.dimson("XXXX", bars, jci, d)
    assert res.framework == "dimson_beta" and (res.role, res.gate) == ("context", "untested")
    c = res.components
    assert res.score == pytest.approx(1.3, abs=1e-6) == c["dimson_beta"]
    assert c["r2"] == pytest.approx(1.0, abs=1e-6)
    assert c["n"] == db.CONFIG["weeks"] - 2
    assert set(c) >= {"raw_beta", "dimson_beta", "r2", "n", "beta_lag", "beta_lead"}
    assert res.signal == "high"


def test_market_tracker_and_thin_trading_flag():
    m = market()
    bars, jci, _ = as_inputs(series(m), series(m), None)
    res = db.dimson("XXXX", bars, jci, bars[-1].date)
    assert res.score == pytest.approx(1.0, abs=1e-9) and res.signal == "market"
    flat = [0.0 if t % 2 else 0.8 * m[t] for t in range(len(m))]  # no trade every other week
    bars, jci, _ = as_inputs(series(flat), series(m), None)
    thin = db.dimson("XXXX", bars, jci, bars[-1].date)
    assert thin.components["zero_weeks"] == pytest.approx(0.5, abs=0.02)
    assert any("thin" in f for f in thin.flags)


def test_missing_data_is_na_with_a_flag():
    m = market(n=40)
    bars, jci, _ = as_inputs(series(m), series(m), None)
    short = db.dimson("XXXX", bars, jci, bars[-1].date)
    assert short.signal == "n/a" and short.score is None
    assert any("weeks" in f for f in short.flags)
    assert db.dimson("XXXX", [], jci, bars[-1].date).signal == "n/a"
    nojci = db.dimson("XXXX", bars, [], bars[-1].date)
    assert nojci.signal == "n/a" and any("JCI" in f for f in nojci.flags)


def test_point_in_time():
    m = market()
    bars, jci, _ = as_inputs(series(lagged(m)), series(m), None)
    d = bars[-20].date
    base = db.dimson("XXXX", bars[:-19], jci[:-19], d)
    full = db.dimson("XXXX", bars, jci, d)
    assert base.to_dict() == full.to_dict()
    assert full.as_of == d


def test_registered_and_evaluate():
    assert "dimson_beta" in {f.name for f in fw.registered()}
    m = market()
    bars, jci, _ = as_inputs(series(m), series(m), None)
    inp = LynchBetaInputs(bars[-1].date, {}, bars={"XXXX": bars}, jci=jci)
    (r,) = [x for x in fw.evaluate("XXXX", inp) if x.framework == "dimson_beta"]
    assert r.score == pytest.approx(1.0, abs=1e-9)
    (na,) = [x for x in fw.evaluate("XXXX", None) if x.framework == "dimson_beta"]
    assert na.signal == "n/a"


def test_never_in_the_hurdle():
    import inspect

    from assist.candidates import hurdle

    assert "beta" not in inspect.getsource(hurdle).lower()  # one hurdle per market
