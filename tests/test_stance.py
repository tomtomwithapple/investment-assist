"""Stance v0 (PLAN S5): layers 0 + 1 + 5 → one schema-valid stance payload. Fake layer outputs
only; nothing here reads a store."""

from __future__ import annotations

import json
import random
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


def test_overweight_adds_tilt_to_the_benchmark_and_lumps_when_not_risk_off():
    # S39: the target anchors on the benchmark (IDN bonds 32%), no longer on what is held
    out = valid(build(score=score(80.0), weights=weights(8.0)))
    assert out["stance"] == "overweight"
    tilt = st.TILT_PT["overweight"]
    bench = st.BENCHMARK_PCT[("IDN", "bonds")]
    assert out["portfolio"] == {"current_pct": 8.0, "target_pct": bench + tilt,
                                "benchmark_pct": bench,
                                "delta": f"+{bench + tilt - 8.0:.1f}pt lump",
                                "rebalance_pt": bench - 8.0, "tilt_pt": tilt}  # S42
    assert out["entry"] == {"style": "lump", "tranches": 1, "spacing_days": 0}
    assert f"benchmark {bench:g}%, tilt +{tilt:g}pt (overweight)" in out["drivers"]


def test_ladder_when_risk_off():
    out = valid(build(score=score(90.0), regime=regime("risk_off"), weights=weights(8.0)))
    assert out["stance"] == "overweight"
    assert out["entry"] == {"style": "ladder", "tranches": st.LADDER_TRANCHES,
                            "spacing_days": st.LADDER_SPACING_DAYS}
    assert out["portfolio"]["delta"].endswith(f"over {st.LADDER_TRANCHES} tranches")


def test_neutral_at_the_benchmark_holds():
    out = valid(build(score=score(50.0), weights=weights(32.0)))
    assert out["portfolio"]["target_pct"] == 32.0
    assert out["portfolio"]["delta"] == "0.0pt hold"
    assert out["entry"] == {"style": "none", "tranches": 0, "spacing_days": 0}


def test_underweight_trims_and_avoid_exits():
    under = valid(build(score=score(st.STANCE_BANDS[2][0] + 1), weights=weights(32.0)))
    assert under["stance"] == "underweight"
    assert under["portfolio"]["target_pct"] == 32.0 + st.TILT_PT["underweight"]
    assert under["portfolio"]["delta"] == "-5.0pt trim"
    assert under["entry"]["style"] == "none"
    avoid = valid(build(score=score(5.0), weights=weights(32.0)))
    assert avoid["stance"] == "avoid"
    assert avoid["portfolio"]["target_pct"] == 0
    assert avoid["portfolio"]["delta"] == "-32.0pt trim"


def test_target_never_below_zero():
    out = valid(build(score=score(st.STANCE_BANDS[2][0] + 1), weights=weights(1.0),
                      benchmark={("IDN", "bonds"): 2.0}))
    assert out["portfolio"]["target_pct"] == 0


def test_outside_the_mandate_keeps_its_view_targets_zero_and_trims_a_holding():
    key = ("JPN", "stocks")
    out = valid(build(score=score(80.0, subject="JPN", asset="stocks"),
                      weights=weights(6.0, key=key)))
    assert out["stance"] == "overweight" and out["score"] == 80.0
    assert out["portfolio"]["target_pct"] == 0
    assert out["portfolio"]["benchmark_pct"] == 0
    assert out["portfolio"]["delta"] == "-6.0pt trim"
    assert out["entry"]["style"] == "none"
    assert st.OUTSIDE_NOTE in out["drivers"] and "80/20 mandate" in st.OUTSIDE_NOTE
    unheld = valid(build(score=score(80.0, subject="JPN", asset="stocks")))
    assert unheld["portfolio"]["delta"] == "0.0pt hold"


def test_currency_is_a_view_not_an_allocation():
    out = valid(build(score=score(80.0, asset="currency"), weights=weights(8.0)))
    assert out["stance"] == "overweight"
    assert out["portfolio"]["target_pct"] == 0
    assert out["portfolio"]["delta"] == "0.0pt hold"
    assert st.CURRENCY_NOTE in out["drivers"]


def test_usa_stocks_names_the_estate_tax_risk():
    out = valid(build(score=score(50.0, subject="USA", asset="stocks"),
                      weights=weights(0.0, key=("USA", "stocks"))))
    assert out["portfolio"]["target_pct"] == 20.0
    assert any("estate tax" in r and "US$60k" in r and "not tax advice" in r
               for r in out["risks"])
    assert not any("estate tax" in r for r in build(score=score(50.0))["risks"])


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


# ---------------- portfolio pass: the 100% rule (S39) ----------------

LEGS = (("IDN", "stocks"), ("IDN", "bonds"), ("USA", "stocks"))
SCORE_FOR = {"overweight": 80.0, "neutral": 50.0, "underweight": 30.0, "avoid": 5.0}


def _stances(calls: dict, held: dict | None = None, regime_state="neutral") -> list[dict]:
    held = dict(held or {})
    w = Weights(as_of=D, weights={**held, ("IDN", "cash"): 100.0 - sum(held.values())})
    return [st.build_stance(score=score(SCORE_FOR[c], subject=k[0], asset=k[1]),
                            regime=regime(regime_state), weights=w)
            for k, c in calls.items()]


def _by(stances, subject, asset):
    return next(p for p in stances if (p["subject"], p["asset"]) == (subject, asset))


def test_all_three_legs_overweight_scale_115_to_100_pro_rata():
    out = _stances({k: "overweight" for k in LEGS}, {("IDN", "stocks"): 96.9})
    summary = st.apply_limits(out)
    for p in out:
        valid(p)
    t = {k: _by(out, *k)["portfolio"]["target_pct"] for k in LEGS}
    # 53 / 37 / 25 × 100/115 = 46.09 / 32.17 / 21.74, 0.1 pt steps by largest remainder
    assert t == {("IDN", "stocks"): 46.1, ("IDN", "bonds"): 32.2, ("USA", "stocks"): 21.7}
    assert summary["target_sum_pct"] == 100.0 and summary["cash_pct"] == 0.0
    assert summary["scale"] == round(100 / 115, 4)
    idn = _by(out, "IDN", "stocks")
    # S39 transition: both moves are above TRANSITION_PT, so both are laddered
    assert idn["portfolio"]["delta"] == "-50.8pt trim over 3 tranches"
    assert idn["entry"]["style"] == "ladder"
    usa = _by(out, "USA", "stocks")
    assert usa["portfolio"]["delta"] == "+21.7pt over 3 tranches"
    assert usa["entry"]["style"] == "ladder"
    assert any("scaled ×0.870 pro rata" in d for d in usa["drivers"])


def test_scaled_ladder_keeps_its_tranches():
    out = _stances({k: "overweight" for k in LEGS}, {("IDN", "bonds"): 25.0}, "risk_off")
    st.apply_limits(out)
    bonds = _by(out, "IDN", "bonds")
    assert bonds["portfolio"]["target_pct"] == 32.2
    # 7.2pt is under TRANSITION_PT: the ladder comes from risk_off and survives the scaling
    assert bonds["portfolio"]["delta"] == f"+7.2pt over {st.LADDER_TRANCHES} tranches"
    assert bonds["entry"]["style"] == "ladder"
    assert not any("laddered over" in d for d in bonds["drivers"])


LADDER = {"style": "ladder", "tranches": st.LADDER_TRANCHES, "spacing_days": st.LADDER_SPACING_DAYS}


@pytest.mark.parametrize(
    ("key", "held", "delta", "entry"),
    [(("IDN", "bonds"), 3.3, "+28.7pt over 3 tranches", LADDER),
     (("IDN", "stocks"), 99.2, "-51.2pt trim over 3 tranches", LADDER),
     (("USA", "stocks"), 10.1, "+9.9pt lump", {"style": "lump", "tranches": 1,
                                               "spacing_days": 0}),
     (("USA", "stocks"), 29.9, "-9.9pt trim", {"style": "none", "tranches": 0,
                                               "spacing_days": 0}),
     (("USA", "stocks"), 30.0, "-10.0pt trim", {"style": "none", "tranches": 0,
                                                "spacing_days": 0})],
)
def test_moves_above_transition_pt_are_laddered_adds_and_trims(key, held, delta, entry):
    """S39 (user, 2026-11-06): a leg more than TRANSITION_PT from its target ladders, both ways;
    at or under it the per-stance entry stands (neutral regime: lump add, trim with none)."""
    assert st.TRANSITION_PT == 10.0 and st.MODEL_CONFIG["transition_pt"] == 10.0
    out = _stances({key: "neutral"}, {key: held})
    st.apply_limits(out)
    p = valid(out[0])
    assert p["portfolio"]["delta"] == delta
    assert p["entry"] == entry
    assert any("laddered over 3 tranches" in d for d in p["drivers"]) == (entry == LADDER)


def test_transition_ladder_is_fingerprinted():
    cfg = {**st.MODEL_CONFIG, "transition_pt": 20.0}
    assert st.model_fingerprint(cfg) != st.model_fingerprint()


def test_outside_the_mandate_trims_are_not_laddered():
    out = _stances({("JPN", "stocks"): "overweight"}, {("JPN", "stocks"): 40.0})
    st.apply_limits(out)
    assert out[0]["portfolio"]["delta"] == "-40.0pt trim"
    assert out[0]["entry"]["style"] == "none"


def test_idn_stocks_underweight_alone_leaves_5pt_cash():
    calls = {("IDN", "stocks"): "underweight", ("IDN", "bonds"): "neutral",
             ("USA", "stocks"): "neutral"}
    out = _stances(calls)
    summary = st.apply_limits(out)
    assert summary["targets_pct"] == {"IDN/bonds": 32.0, "IDN/stocks": 43.0, "USA/stocks": 20.0}
    assert summary["target_sum_pct"] == 95.0 and summary["cash_pct"] == 5.0
    assert summary["scale"] == 1.0
    assert not any("scaled" in d for p in out for d in p["drivers"])


def test_mandate_summary_reads_layer_rows_too():
    rows = [{"subject": "IDN", "asset": "stocks", "target_pct": 48.0},
            {"subject": "JPN", "asset": "stocks", "target_pct": 0.0},
            {"subject": "IDN", "asset": "cash", "target_pct": None}]
    s = st.mandate_summary(rows)
    assert s["target_sum_pct"] == 48.0 and s["cash_pct"] == 52.0
    assert s["targets_pct"] == {"IDN/stocks": 48.0}


def test_targets_never_sum_past_100_for_any_mix():
    rng = random.Random(39)
    outside = [("JPN", "stocks"), ("DEU", "bonds"), ("GOLD", "commodities"), ("IDN", "currency"),
               ("USA", "bonds")]
    for _ in range(400):
        calls = {k: rng.choice(tuple(SCORE_FOR)) for k in LEGS}
        calls.update({k: "overweight" for k in outside})
        held = {k: rng.choice((0.0, 3.0, 12.0)) for k in (*LEGS, *outside)}
        out = _stances(calls, held, rng.choice(("risk_on", "neutral", "risk_off")))
        summary = st.apply_limits(out)
        targets = [p["portfolio"]["target_pct"] for p in out]
        assert 0 <= sum(targets) <= 100 + 1e-9, (calls, targets)
        assert all(0 <= t <= 100 for t in targets)
        for k in outside:
            p = _by(out, *k)
            assert p["portfolio"]["target_pct"] == 0 and p["stance"] == "overweight"
            assert p["portfolio"]["delta"] == {12.0: "-12.0pt trim", 3.0: "-3.0pt trim",
                                               0.0: "0.0pt hold"}[held[k]]
        legs = {calls[k] for k in LEGS}
        if {"underweight", "avoid"} & legs and "overweight" not in legs:
            assert summary["cash_pct"] > 0, calls  # nothing tilts up to fill the gap
        for p in out:
            valid(p)
            gap = round(p["portfolio"]["target_pct"] - p["portfolio"]["current_pct"], 1)
            leg = (p["subject"], p["asset"]) in LEGS
            if leg and abs(gap) > st.TRANSITION_PT:  # S39 transition: ladder, add or trim
                assert p["entry"] == LADDER, p["portfolio"]
                assert p["portfolio"]["delta"].endswith("over 3 tranches")
            else:
                assert (p["entry"]["style"] == "none") == (gap <= 0), p["portfolio"]


# ---------------- rebalance vs tilt (S42) ----------------


def _split_sums(p: dict) -> None:
    pf = p["portfolio"]
    gap = round(pf["target_pct"] - pf["current_pct"], 1)
    assert round(pf["rebalance_pt"] + pf["tilt_pt"], 1) == gap, pf


def test_split_of_a_mandate_leg_unscaled():
    """No pro-rata scaling: rebalance = benchmark − current, tilt = the stance's tilt."""
    calls = {("IDN", "stocks"): "underweight", ("IDN", "bonds"): "neutral",
             ("USA", "stocks"): "neutral"}
    out = _stances(calls, {("IDN", "stocks"): 96.9, ("IDN", "bonds"): 3.1})
    st.apply_limits(out)
    idn = valid(_by(out, "IDN", "stocks"))["portfolio"]
    assert idn["rebalance_pt"] == -48.9 and idn["tilt_pt"] == -5.0
    bonds = _by(out, "IDN", "bonds")["portfolio"]
    assert bonds["rebalance_pt"] == 28.9 and bonds["tilt_pt"] == 0.0
    usa = _by(out, "USA", "stocks")["portfolio"]
    assert usa["rebalance_pt"] == 20.0 and usa["tilt_pt"] == 0.0
    for p in out:
        _split_sums(p)


def test_split_under_pro_rata_scaling_uses_the_scaled_benchmark():
    """IDN stocks and bonds neutral, USA overweight: 48 + 32 + 25 = 105 → ×100/105. A neutral
    leg's whole move is a rebalance (tilt 0); the USA tilt is its +5 scaled, 4.8."""
    calls = {("IDN", "stocks"): "neutral", ("IDN", "bonds"): "neutral",
             ("USA", "stocks"): "overweight"}
    out = _stances(calls, {("IDN", "stocks"): 96.9, ("IDN", "bonds"): 3.1})
    st.apply_limits(out)
    idn = valid(_by(out, "IDN", "stocks"))["portfolio"]
    assert idn["target_pct"] == 45.7 and idn["delta"] == "-51.2pt trim over 3 tranches"
    assert idn["rebalance_pt"] == -51.2 and idn["tilt_pt"] == 0.0
    bonds = _by(out, "IDN", "bonds")["portfolio"]
    assert bonds["tilt_pt"] == 0.0 and bonds["rebalance_pt"] == round(bonds["target_pct"] - 3.1, 1)
    usa = _by(out, "USA", "stocks")["portfolio"]
    assert usa["target_pct"] == 23.8
    assert usa["rebalance_pt"] == 19.0 and usa["tilt_pt"] == 4.8  # 20 and 5, × 100/105
    for p in out:
        _split_sums(p)


def test_split_outside_the_mandate_is_all_rebalance():
    out = _stances({("JPN", "stocks"): "overweight"}, {("JPN", "stocks"): 40.0})
    st.apply_limits(out)
    pf = valid(out[0])["portfolio"]
    assert pf["rebalance_pt"] == -40.0 and pf["tilt_pt"] == 0.0


def test_split_is_null_without_holdings():
    p = valid(build(weights=None))
    assert p["portfolio"]["rebalance_pt"] is None and p["portfolio"]["tilt_pt"] is None


def test_split_leaves_targets_delta_and_entry_unchanged():
    out = _stances({k: "overweight" for k in LEGS}, {("IDN", "stocks"): 96.9})
    st.apply_limits(out)
    idn = _by(out, "IDN", "stocks")
    assert idn["portfolio"]["target_pct"] == 46.1
    assert idn["portfolio"]["delta"] == "-50.8pt trim over 3 tranches"
    assert idn["entry"]["style"] == "ladder"
    assert idn["portfolio"]["tilt_pt"] == 4.3  # +5 × 100/115
    for p in out:
        _split_sums(p)


def test_split_sums_to_the_gap_for_any_mix():
    rng = random.Random(42)
    outside = [("JPN", "stocks"), ("IDN", "currency")]
    for _ in range(300):
        calls = {k: rng.choice(tuple(SCORE_FOR)) for k in (*LEGS, *outside)}
        held = {k: rng.choice((0.0, 3.3, 12.7, 19.9)) for k in (*LEGS, *outside)}
        out = _stances(calls, held, rng.choice(("risk_on", "neutral", "risk_off")))
        st.apply_limits(out)
        for p in out:
            valid(p)
            _split_sums(p)
            key = (p["subject"], p["asset"])
            if key not in LEGS or calls[key] == "neutral":
                assert p["portfolio"]["tilt_pt"] == 0.0, (key, p["portfolio"])


def test_schema_takes_old_payloads_without_the_split():
    p = build()
    for k in ("rebalance_pt", "tilt_pt", "benchmark_pct"):
        p["portfolio"].pop(k)
    p["schema_version"] = "1.0.0"
    valid(p)
    assert build()["schema_version"] == st.SCHEMA_VERSION


def test_split_text():
    pf = {"current_pct": 96.9, "target_pct": 45.7, "rebalance_pt": -48.9, "tilt_pt": -2.3}
    assert st.split_text(pf) == "-51.2pt = -48.9pt rebalance to benchmark, -2.3pt tilt"
    usa = {"current_pct": 0.0, "target_pct": 23.8, "rebalance_pt": 19.0, "tilt_pt": 4.8}
    assert st.split_text(usa) == "+23.8pt = +19.0pt rebalance to benchmark, +4.8pt tilt"
    assert st.split_text({"rebalance_pt": None, "tilt_pt": None}) is None
    assert st.split_text({"current_pct": 1.0, "target_pct": 1.0}) is None


# ---------------- home (IDN) regime (S53, P72; open question 8) ----------------

HOME_LADDER = {"style": "ladder", "tranches": st.LADDER_TRANCHES,
               "spacing_days": st.LADDER_SPACING_DAYS}


def home(state="risk_off", points=2, **kw):
    from assist.layers.home_regime import HomeRegime

    by = {"jci_drawdown_20d": points, "idx_foreign_z": 0, "usdidr_20d": 0,
          "sbn_non_resident_20d": None}
    args = {"drivers": ("JCI -18.8% vs 20d high (2)",) if points else (),
            "stale_inputs": ("idxscape SBN.TOTAL.non_resident (last 2026-09-04)",),
            "sources": ("idxscape",)}
    args.update(kw)
    return HomeRegime(D, state, points, by, **args)


def test_home_risk_off_with_neutral_global_ladders_an_idn_add_within_10pt():
    # IDN bonds neutral: target 32, held 25, a +7pt add, under TRANSITION_PT
    base = build(score=score(50.0), weights=weights(25.0))
    assert base["entry"]["style"] == "lump"
    out = valid(build(score=score(50.0), weights=weights(25.0), home=home()))
    st.apply_limits([out])
    valid(out)
    assert out["regime"] == "neutral"
    assert out["entry"] == HOME_LADDER
    assert out["portfolio"]["delta"] == f"+7.0pt over {st.LADDER_TRANCHES} tranches"
    # an entry style, not a stance change: stance, score and target as without it
    for k in ("stance", "score", "layer1_score", "confidence"):
        assert out[k] == base[k], k
    assert out["portfolio"]["target_pct"] == base["portfolio"]["target_pct"]
    assert out["home_regime"] == {
        "state": "risk_off", "points": 2, "drivers": ["JCI -18.8% vs 20d high (2)"],
        "stale_inputs": ["idxscape SBN.TOTAL.non_resident (last 2026-09-04)"]}
    assert "home (IDN) regime risk_off" in out["risks"]
    assert any(d.startswith("home (IDN) regime risk_off (2 points)") for d in out["drivers"])
    assert not any("move of" in d for d in out["drivers"])  # not the S39 transition ladder


def test_home_risk_off_ladders_an_idn_stocks_trim_within_10pt():
    w = weights(55.0, key=("IDN", "stocks"))
    base = build(score=score(50.0, asset="stocks"), weights=w)
    assert base["entry"]["style"] == "none" and base["portfolio"]["delta"] == "-7.0pt trim"
    out = build(score=score(50.0, asset="stocks"), weights=w, home=home())
    st.apply_limits([out])
    valid(out)
    assert out["entry"] == HOME_LADDER
    assert out["portfolio"]["delta"] == f"-7.0pt trim over {st.LADDER_TRANCHES} tranches"


def test_home_ladder_survives_the_pro_rata_scale():
    w = Weights(as_of=D, weights={("IDN", "stocks"): 52.0, ("IDN", "cash"): 48.0})
    out = [st.build_stance(score=score(SCORE_FOR["overweight"], subject=s, asset=a),
                           regime=regime(), weights=w,
                           home=home() if s == "IDN" else None) for s, a in LEGS]
    st.apply_limits(out)
    stocks = _by(out, "IDN", "stocks")
    assert stocks["portfolio"]["target_pct"] == 46.1  # 53 scaled ×0.870
    assert stocks["portfolio"]["delta"] == f"-5.9pt trim over {st.LADDER_TRANCHES} tranches"
    assert stocks["entry"] == HOME_LADDER


def test_home_neutral_changes_no_entry_and_carries_its_block():
    base = build(score=score(50.0), weights=weights(25.0))
    out = valid(build(score=score(50.0), weights=weights(25.0),
                      home=home("neutral", 1, drivers=("JCI -7.3% vs 20d high (1)",))))
    assert out["entry"] == base["entry"] == {"style": "lump", "tranches": 1, "spacing_days": 0}
    assert out["home_regime"]["state"] == "neutral" and out["home_regime"]["points"] == 1
    assert {k: v for k, v in out.items() if k not in ("home_regime", "sources")} == \
        {k: v for k, v in base.items() if k not in ("home_regime", "sources")}


@pytest.mark.parametrize("key", [("USA", "stocks"), ("IDN", "currency"), ("JPN", "bonds")])
def test_home_regime_leaves_other_stances_unchanged(key):
    w = weights(5.0, key=key)
    args = {"score": score(50.0, subject=key[0], asset=key[1]), "weights": w}
    assert build(**args, home=home()) == build(**args)


def test_home_shift_not_adopted_moves_no_score():
    from assist.layers import home_regime as hr

    assert hr.HOME_SHIFT_ADOPTED is False
    assert st.MODEL_CONFIG["home_regime"]["shift_adopted"] is False
    out = build(score=score(62.0), weights=weights(30.0), home=home())
    assert out["score"] == 62.0 and out["stance"] == "overweight"
    assert not any("pt)" in d and d.startswith("home") for d in out["drivers"])


@pytest.mark.parametrize(("global_state", "expected"),
                         [("neutral", 57.0), ("risk_off", 57.0), ("risk_on", 62.0)])
def test_home_shift_if_adopted_is_minus_5_not_minus_10(monkeypatch, global_state, expected):
    from assist.layers import home_regime as hr

    monkeypatch.setattr(hr, "HOME_SHIFT_ADOPTED", True)
    out = valid(build(score=score(62.0), regime=regime(global_state), weights=weights(30.0),
                      home=home()))
    assert out["score"] == expected  # global risk_off and home risk_off: -5, not -10
    assert out["stance"] == st.stance_for(expected)
    assert st.base_stance(score(62.0), regime(global_state), home()) == out["stance"]
    if global_state != "risk_off":
        assert "home (IDN) regime risk_off (-5.0pt)" in out["drivers"]
    # a USA stance takes no home shift
    usa = build(score=score(62.0, subject="USA", asset="stocks"), regime=regime(global_state),
                weights=weights(30.0, key=("USA", "stocks")), home=home())
    assert usa["score"] == 62.0 + st.REGIME_SHIFT[global_state]


def test_home_config_is_fingerprinted_and_versions_bumped():
    cfg = st.MODEL_CONFIG["home_regime"]
    assert cfg["assets"] == ["IDN/bonds", "IDN/stocks"]
    assert cfg["shift_pt"] == -5.0 and cfg["ladder"] == "risk_off"
    changed = {**st.MODEL_CONFIG, "home_regime": {**cfg, "shift_adopted": True}}
    assert st.model_fingerprint(changed) != st.model_fingerprint()
    assert st.MODEL_VERSION == "0.5.0" and st.SCHEMA_VERSION == "1.2.0"


def test_schema_takes_1_1_payloads_without_home_regime():
    p = build(home=home())
    assert p["schema_version"] == "1.2.0" and "home_regime" in p
    valid(p)
    p.pop("home_regime")
    p["schema_version"] = "1.1.0"
    valid(p)
    bad = build(home=home())
    bad["home_regime"]["state"] = "risk_on"  # there is no home risk_on
    assert list(stance_validator().iter_errors(bad))
