"""Journal + model fingerprint (PLAN S5/S13, CLAUDE.md Rules): every decision is journalled with
the fingerprint of the model that made it, so a rule change segments the record."""

import json
from datetime import date

import pytest

from assist import journal as jr
from assist import stance as st
from assist.layers.types import AssetScore, Regime, Weights

FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64


def _model(tmp_path, rules="X = 1\n", cfg="w: 1\n", config=None):
    pkg = tmp_path / "pkg"
    (pkg / "layers").mkdir(parents=True, exist_ok=True)
    (pkg / "stance.py").write_text(rules)
    (pkg / "layers" / "rule.py").write_text("Y = 2\n")
    cfgdir = tmp_path / "config"
    cfgdir.mkdir(exist_ok=True)
    (cfgdir / "model.yaml").write_text(cfg)
    (cfgdir / "sources.yaml").write_text("paths: here\n")
    return jr.fingerprint_inputs(
        config=config if config is not None else {"tilt": 5},
        rule_files=[pkg / "stance.py", pkg / "layers" / "rule.py"],
        config_files=[cfgdir / "model.yaml"],
        root=tmp_path,
    )


# ---------------- fingerprint ----------------


def test_fingerprint_is_stable_and_well_formed(tmp_path):
    a, b = _model(tmp_path), _model(tmp_path)
    assert jr.fingerprint(a) == jr.fingerprint(b)
    assert jr.FINGERPRINT_RE.fullmatch(jr.fingerprint(a))


def test_fingerprint_changes_with_rules(tmp_path):
    base = jr.fingerprint(_model(tmp_path))
    assert jr.fingerprint(_model(tmp_path, rules="X = 2\n")) != base


def test_fingerprint_changes_with_config_file(tmp_path):
    base = jr.fingerprint(_model(tmp_path))
    assert jr.fingerprint(_model(tmp_path, cfg="w: 2\n")) != base


def test_fingerprint_changes_with_weights(tmp_path):
    base = jr.fingerprint(_model(tmp_path))
    assert jr.fingerprint(_model(tmp_path, config={"tilt": 6})) != base


def test_fingerprint_ignores_key_order_and_absolute_paths(tmp_path):
    a = _model(tmp_path / "one", config={"a": 1, "b": 2})
    b = _model(tmp_path / "two", config={"b": 2, "a": 1})
    assert jr.fingerprint(a) == jr.fingerprint(b)
    assert all(not k.startswith("/") for k in a["rules"])


def test_fingerprint_inputs_reject_missing_rule_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        jr.fingerprint_inputs(config={}, rule_files=[tmp_path / "nope.py"], config_files=[],
                              root=tmp_path)


def test_default_model_fingerprint_covers_stance_config_and_rule_modules():
    inputs = jr.fingerprint_inputs()
    assert inputs["config"] == json.loads(json.dumps(st.MODEL_CONFIG))
    assert "assist/stance.py" in inputs["rules"]
    assert any(k.startswith("assist/layers/") for k in inputs["rules"])
    assert not any(k.startswith("assist/sources/") for k in inputs["rules"])  # plumbing
    assert "config/sources.yaml" not in inputs["config_files"]  # plumbing, not model
    assert jr.model_fingerprint() == jr.model_fingerprint() == jr.fingerprint(inputs)


# ---------------- journal ----------------


def test_record_appends_one_line_per_decision(tmp_path):
    j = jr.Journal(tmp_path / "journal")
    j.record(kind="stance", fingerprint=FP_A, inputs={"score": 58}, outputs={"stance": "neutral"},
             subject="IDN", asset="bonds", as_of=date(2026, 10, 23), run_id="r1")
    j.record(kind="stance", fingerprint=FP_A, inputs={"score": 61},
             outputs={"stance": "overweight"}, subject="IDN", asset="stocks", run_id="r1")
    lines = j.path.read_text().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["fingerprint"] == FP_A
    assert rec["inputs"] == {"score": 58} and rec["outputs"] == {"stance": "neutral"}
    assert rec["subject"] == "IDN" and rec["asset"] == "bonds" and rec["as_of"] == "2026-10-23"
    assert rec["kind"] == "stance" and rec["run_id"] == "r1" and rec["seq"] == 0
    assert json.loads(lines[1])["seq"] == 1


def test_record_is_append_only_across_instances(tmp_path):
    root = tmp_path / "journal"
    jr.Journal(root).record(kind="stance", fingerprint=FP_A, inputs={}, outputs={})
    before = (root / jr.DECISIONS).read_bytes()
    jr.Journal(root).record(kind="stance", fingerprint=FP_B, inputs={}, outputs={})
    after = (root / jr.DECISIONS).read_bytes()
    assert after.startswith(before) and len(after) > len(before)
    assert [r["seq"] for r in jr.Journal(root).read()] == [0, 1]


def test_record_requires_fingerprint(tmp_path):
    j = jr.Journal(tmp_path)
    for bad in ("", "abc", "sha256:xyz", None):
        with pytest.raises(ValueError):
            j.record(kind="stance", fingerprint=bad, inputs={}, outputs={})
    assert not j.path.exists()


def test_record_rejects_output_from_another_model(tmp_path):
    j = jr.Journal(tmp_path)
    with pytest.raises(ValueError, match="fingerprint"):
        j.record(kind="stance", fingerprint=FP_A, inputs={},
                 outputs={"model_fingerprint": FP_B, "stance": "neutral"})


def test_records_segment_by_fingerprint(tmp_path):
    j = jr.Journal(tmp_path)
    for fp, n in ((FP_A, 2), (FP_B, 1), (FP_A, 1)):
        for _ in range(n):
            j.record(kind="stance", fingerprint=fp, inputs={}, outputs={})
    segs = j.segments()
    assert list(segs) == [FP_A, FP_B]  # first appearance order
    assert [r["seq"] for r in segs[FP_A]] == [0, 1, 3]
    assert [r["seq"] for r in segs[FP_B]] == [2]
    assert [r["seq"] for r in j.read(fingerprint=FP_B)] == [2]
    assert j.fingerprints() == [FP_A, FP_B]


def test_register_model_stores_inputs_once(tmp_path):
    j = jr.Journal(tmp_path / "journal")
    inputs = _model(tmp_path)
    fp = j.register_model(inputs)
    assert fp == jr.fingerprint(inputs)
    assert j.register_model(inputs) == fp  # idempotent
    assert j.model(fp) == json.loads(json.dumps(inputs))
    assert len(list((tmp_path / "journal" / "models").iterdir())) == 1


def test_register_model_refuses_to_overwrite_a_different_model(tmp_path):
    j = jr.Journal(tmp_path)
    fp = j.register_model({"config": {"a": 1}, "rules": {}, "config_files": {}})
    hexpart = fp.split(":", 1)[1]
    (tmp_path / "models" / f"{hexpart}.json").write_text('{"config": {"a": 2}}')
    with pytest.raises(ValueError, match="differs"):
        j.register_model({"config": {"a": 1}, "rules": {}, "config_files": {}})


def test_verify_chain_detects_edits(tmp_path):
    j = jr.Journal(tmp_path)
    for i in range(3):
        j.record(kind="stance", fingerprint=FP_A, inputs={"i": i}, outputs={})
    assert j.verify() == 3
    lines = j.path.read_text().splitlines()
    lines[1] = lines[1].replace('"i":1', '"i":9')
    j.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="seq 1"):
        j.verify()


def test_layer_types_are_journalled_as_json(tmp_path):
    j = jr.Journal(tmp_path)
    score = AssetScore(subject="IDN", asset="bonds", as_of=date(2026, 10, 1), score=58.0,
                       confidence=0.8)
    regime = Regime(as_of=date(2026, 10, 22), state="risk_off", dollar="up", drivers=("vix",))
    weights = Weights(as_of=date(2026, 10, 20), weights={("IDN", "bonds"): 40.0,
                                                         ("IDN", "cash"): 60.0})
    fp = jr.model_fingerprint()
    out = st.build_stance(score=score, regime=regime, weights=weights, fingerprint=fp)
    rec = j.record(kind="stance", fingerprint=fp, subject="IDN", asset="bonds",
                   inputs={"score": score, "regime": regime, "weights": weights}, outputs=out)
    back = next(j.read())
    assert back == rec
    assert back["inputs"]["regime"]["as_of"] == "2026-10-22"
    assert back["inputs"]["regime"]["drivers"] == ["vix"]
    assert back["inputs"]["weights"]["weights"] == {"IDN/bonds": 40.0, "IDN/cash": 60.0}
    assert back["outputs"]["stance"] == out["stance"]


def test_unjsonable_input_fails_before_writing(tmp_path):
    j = jr.Journal(tmp_path)
    with pytest.raises(TypeError):
        j.record(kind="stance", fingerprint=FP_A, inputs={"x": object()}, outputs={})
    assert not j.path.exists()


def test_empty_journal_reads_empty(tmp_path):
    j = jr.Journal(tmp_path / "none")
    assert list(j.read()) == [] and j.segments() == {} and j.verify() == 0
