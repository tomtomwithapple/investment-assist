"""Stance v0 (PLAN S5): layers 0 + 1 + 5 → one schema-valid stance payload. Fake layer outputs
only; nothing here reads a store."""

from __future__ import annotations

import json
from datetime import date

import pytest

from assist import stance as st
from assist.layers.types import AssetScore, Override, Regime, Weights, stance_validator

D = date(2026, 10, 23)


def regime(state="neutral", dollar="flat", **kw) -> Regime:
    return Regime(as_of=D, state=state, dollar=dollar, sources=("sec-edgar FRED",), **kw)


def score(value=58.0, subject="IDN", asset="bonds", confidence=0.9, **kw) -> AssetScore:
    return AssetScore(subject=subject, asset=asset, as_of=D, score=value, confidence=confidence,
                      **kw)


def weights(pct=8.0, key=("IDN", "bonds")) -> Weights:
    w = {key: pct, ("IDN", "cash"): 100 - pct} if pct < 100 else {key: 100.0}
    return Weights(as_of=D, weights=w)


def build(**kw) -> dict:
    args = {"score": score(), "regime": regime(), "weights": weights()}
    args.update(kw)
    return st.build_stance(**args)


def valid(payload: dict) -> dict:
    errors = list(stance_validator().iter_errors(payload))
    assert not errors, [e.message for e in errors]
    return payload


# ---------------- score and band ----------------


@pytest.mark.parametrize(
    ("state", "expected"),
    [("risk_on", 58.0 + st.REGIME_SHIFT["risk_on"]), ("neutral", 58.0),
     ("risk_off", 58.0 + st.REGIME_SHIFT["risk_off"])],
)
def test_score_is_layer1_shifted_by_regime(state, expected):
    out = valid(build(regime=regime(state)))
    assert out["layer1_score"] == 58.0
    assert out["score"] == expected
    assert out["regime"] == state


def test_risk_off_lowers_and_risk_on_raises():
    assert st.REGIME_SHIFT["risk_off"] < 0 < st.REGIME_SHIFT["risk_on"]
    assert st.REGIME_SHIFT["neutral"] == 0


def test_score_is_clipped_to_0_100():
    assert build(score=score(99.0), regime=regime("risk_on"))["score"] == 100
    assert build(score=score(1.0), regime=regime("risk_off"))["score"] == 0


def test_overrides_add_bounded_shift():
    ov = [Override(subject="IDN", asset="bonds", as_of=D, delta=8, reason="CPI falling",
                   sources=("bps-looker",)),
          Override(subject="IDN", asset="bonds", as_of=D, delta=7, reason="BI cutting",
                   sources=("bisfetcher",))]
    out = valid(build(overrides=ov))
    assert out["score"] == 58.0 + 10  # summed overrides capped at ±MAX_OVERRIDE
    assert "bps-looker" in out["sources"] and "bisfetcher" in out["sources"]


def test_overrides_for_other_subject_are_ignored():
    ov = [Override(subject="USA", asset="bonds", as_of=D, delta=9, reason="x", sources=("y",))]
    assert build(overrides=ov)["score"] == 58.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [(80, "overweight"), (st.STANCE_BANDS[0][0], "overweight"),
     (st.STANCE_BANDS[0][0] - 0.1, "neutral"), (50, "neutral"),
     (st.STANCE_BANDS[1][0] - 0.1, "underweight"), (st.STANCE_BANDS[2][0] - 0.1, "avoid"),
     (0, "avoid")],
)
def test_stance_bands(value, expected):
    assert st.stance_for(value) == expected


# ---------------- target, delta, entry ----------------


def test_overweight_adds_tilt_and_lumps_when_not_risk_off():
    out = valid(build(score=score(80.0), weights=weights(8.0)))
    assert out["stance"] == "overweight"
    tilt = st.TILT_PT["overweight"]
    assert out["portfolio"] == {"current_pct": 8.0, "target_pct": 8.0 + tilt,
                                "delta": f"+{tilt:.1f}pt lump"}
    assert out["entry"] == {"style": "lump", "tranches": 1, "spacing_days": 0}


def test_ladder_when_risk_off():
    out = valid(build(score=score(90.0), regime=regime("risk_off"), weights=weights(8.0)))
    assert out["stance"] == "overweight"
    assert out["entry"] == {"style": "ladder", "tranches": st.LADDER_TRANCHES,
                            "spacing_days": st.LADDER_SPACING_DAYS}
    assert out["portfolio"]["delta"].endswith(f"over {st.LADDER_TRANCHES} tranches")


def test_neutral_holds():
    out = valid(build(score=score(50.0)))
    assert out["portfolio"]["target_pct"] == 8.0
    assert out["portfolio"]["delta"] == "0.0pt hold"
    assert out["entry"] == {"style": "none", "tranches": 0, "spacing_days": 0}


def test_underweight_trims_and_avoid_exits():
    under = valid(build(score=score(st.STANCE_BANDS[2][0] + 1)))
    assert under["stance"] == "underweight"
    assert under["portfolio"]["target_pct"] == 8.0 + st.TILT_PT["underweight"]
    assert under["portfolio"]["delta"].endswith("trim")
    assert under["entry"]["style"] == "none"
    avoid = valid(build(score=score(5.0)))
    assert avoid["stance"] == "avoid"
    assert avoid["portfolio"]["target_pct"] == 0
    assert avoid["portfolio"]["delta"] == "-8.0pt trim"


def test_target_never_below_zero():
    out = valid(build(score=score(st.STANCE_BANDS[2][0] + 1), weights=weights(1.0)))
    assert out["portfolio"]["target_pct"] == 0


def test_benchmark_anchors_target_when_given():
    out = valid(build(score=score(80.0), weights=weights(8.0),
                      benchmark={("IDN", "bonds"): 40.0}))
    assert out["portfolio"]["target_pct"] == 40.0 + st.TILT_PT["overweight"]


def test_unheld_asset_is_zero_not_unknown():
    out = valid(build(score=score(80.0), weights=weights(8.0, key=("IDN", "stocks"))))
    assert out["portfolio"]["current_pct"] == 0


def test_missing_holdings_are_stale_not_fatal():
    full = build(score=score(80.0))
    out = valid(build(score=score(80.0), weights=None))
    assert out["portfolio"]["current_pct"] is None
    assert "financer" in out["stale_inputs"]
    assert out["entry"]["style"] == "none"
    assert out["confidence"] < full["confidence"]


def test_missing_regime_is_neutral_and_stale():
    out = valid(build(regime=None))
    assert out["regime"] == "neutral"
    assert out["score"] == 58.0
    assert "regime" in out["stale_inputs"]


def test_stale_inputs_are_merged_and_lower_confidence():
    clean = build()
    out = valid(build(regime=regime(stale_inputs=("NFCI",)),
                      score=score(stale_inputs=("cpi",))))
    assert out["stale_inputs"] == ["NFCI", "cpi"]
    assert out["confidence"] == round(clean["confidence"] * st.STALE_PENALTY ** 2, 2)


# ---------------- contract and determinism ----------------


def test_payload_carries_contract_fields():
    out = valid(build(regime=regime("risk_off", "up", drivers=("VIX 31",))))
    assert out["disclaimer"] == st.DISCLAIMER
    assert out["schema_version"] == st.SCHEMA_VERSION
    assert out["as_of"] == "2026-10-23"
    assert out["dollar"] == "up"
    assert "VIX 31" in out["drivers"]
    assert out["risks"]
    assert out["sources"] == sorted(set(out["sources"]))
    assert {"worldbankscape", "sec-edgar FRED", "financer"} <= set(out["sources"])
    assert out["model_fingerprint"] == st.model_fingerprint()


def test_fingerprint_changes_with_config():
    base = st.model_fingerprint()
    assert base == st.model_fingerprint()
    assert base != st.model_fingerprint({**st.MODEL_CONFIG, "tilt_pt": {"overweight": 1}})


def test_flags_pass_through():
    flag = {"code": "stale", "severity": "warn", "message": "old"}
    out = build(score=score(flags=(flag,)))
    assert out["flags"] == [flag]


def test_mismatched_inputs_are_rejected():
    with pytest.raises(ValueError):
        st.build_stance(score=score(), regime=regime(), weights=weights(), subject="USA")


def test_dumps_is_byte_identical_and_sorted():
    a = st.dumps(build())
    b = st.dumps(build())
    assert a == b
    assert a.endswith("\n")
    keys = list(json.loads(a).keys())
    assert keys == sorted(keys)
    assert a.encode() == st.dumps(json.loads(a)).encode()


def test_dumps_fixed_float_format():
    out = st.dumps(build(score=score(58.123456), weights=weights(8.333333)))
    data = json.loads(out)
    assert data["layer1_score"] == 58.1
    assert data["portfolio"]["current_pct"] == 8.3
    assert data["score"] == 58.1
