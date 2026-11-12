"""FrameworkResult, the Framework base and the registry (P110, PLAN S93, phase Q rule 1)."""

from __future__ import annotations

import dataclasses
import json
from datetime import date

import pytest

from assist import journal as jr
from assist.candidates import frameworks as fw
from assist.candidates.frameworks import base

DAY = date(2026, 5, 1)


def result(**kw):
    args = {"framework": "toy", "ticker": "BBRI", "as_of": DAY, "score": 7.0, "signal": "pass",
            "components": {"roa": 0.031, "cfo_gt_ni": 1.0}, "flags": ("bank: 2 of 9 n/a",),
            "version": "0.1.0"} | kw
    return fw.FrameworkResult(**args)


class Toy(fw.Framework):
    name = "toy"
    VERSION = "0.1.0"

    def evaluate(self, sym, inputs):
        row = (inputs or {}).get(sym)
        if row is None:
            return self.missing(sym, None, "no fundamentals")
        return self.result(sym, row["available"], float(row["x"]),
                           "pass" if row["x"] >= 5 else "fail", {"x": float(row["x"])})


class Boom(fw.Framework):
    name = "boom"
    VERSION = "0.0.1"

    def evaluate(self, sym, inputs):
        raise KeyError("ebit")


class Gate(fw.Framework):
    name = "gate"
    VERSION = "0.1.0"
    role = "exclusion"

    def evaluate(self, sym, inputs):
        return self.result(sym, DAY, 1.0, "pass", {})


@pytest.fixture
def registry(monkeypatch):
    reg: dict = {}
    monkeypatch.setattr(base, "REGISTRY", reg)
    return reg


# ---------------- the dataclass ----------------


def test_defaults_are_context_and_untested_and_it_is_frozen():
    r = result()
    assert (r.role, r.gate) == ("context", "untested")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.score = 1.0  # type: ignore[misc]


def test_to_dict_from_dict_round_trip_through_json():
    r = result(role="quality", gate="passed", components={"a": 1.5, "b": None})
    d = r.to_dict()
    assert list(d) == ["framework", "ticker", "as_of", "score", "signal", "components", "flags",
                       "version", "role", "gate"]
    assert d["as_of"] == "2026-05-01" and d["flags"] == ["bank: 2 of 9 n/a"]
    back = fw.FrameworkResult.from_dict(json.loads(json.dumps(d)))
    assert back == r
    assert jr.jsonable(r) == d  # the journal sees the same plain form


@pytest.mark.parametrize("kw", [
    {"role": "verdict"},  # never a second verdict source (phase P rule 1)
    {"gate": "maybe"},
    {"score": float("nan")},
    {"components": {"x": float("inf")}},
    {"score": None, "flags": ()},  # missing data must say why
    {"framework": ""},
    {"ticker": ""},
])
def test_invalid_results_raise(kw):
    with pytest.raises(ValueError):
        result(**kw)


def test_missing_never_imputes_and_needs_a_flag():
    m = fw.missing("toy", "BBRI", DAY, "no cfo", version="0.1.0")
    assert (m.score, m.signal, m.flags, m.as_of) == (None, fw.NA, ("no cfo",), DAY)
    assert m.components == {} and m.role == "context"
    with pytest.raises(ValueError):
        fw.missing("toy", "BBRI", DAY, version="0.1.0")


# ---------------- base and registry ----------------


def test_register_and_evaluate_in_name_order(registry):
    fw.register(Toy())
    fw.register(Boom)  # a class is instantiated
    assert [f.name for f in fw.registered()] == ["boom", "toy"]
    inputs = {"BBRI": {"available": DAY, "x": 7}}
    out = fw.evaluate("BBRI", inputs)
    assert [r.framework for r in out] == ["boom", "toy"]
    assert out[1] == fw.FrameworkResult("toy", "BBRI", DAY, 7.0, "pass", {"x": 7.0}, (),
                                        "0.1.0")
    # a framework that raises is n/a with the error flagged, never a guess
    assert out[0].score is None and out[0].signal == fw.NA
    assert out[0].flags == ("error: KeyError: 'ebit'",) and out[0].version == "0.0.1"
    assert fw.evaluate("TLKM", inputs)[1].flags == ("no fundamentals",)


def test_duplicate_or_bad_framework_is_refused(registry):
    fw.register(Toy())
    with pytest.raises(ValueError):
        fw.register(Toy())

    class NoName(fw.Framework):
        VERSION = "1"

    with pytest.raises(ValueError):
        fw.register(NoName())

    class BadRole(Toy):
        name = "bad"
        role = "verdict"

    with pytest.raises(ValueError):
        fw.register(BadRole())


def test_evaluate_keeps_only_the_roles_asked_for(registry):
    fw.register(Toy())
    fw.register(Gate())
    assert [r.framework for r in fw.evaluate("BBRI", {})] == ["toy"]  # context by default
    assert [r.framework for r in fw.evaluate("BBRI", {}, roles=("exclusion",))] == ["gate"]


def test_a_result_for_another_name_or_framework_is_refused(registry):
    class Liar(Toy):
        name = "liar"

        def evaluate(self, sym, inputs):
            return result(framework="liar", ticker="XXXX", version=self.VERSION)

    fw.register(Liar())
    (r,) = fw.evaluate("BBRI", {})
    assert r.score is None and r.flags[0].startswith("error: ValueError")


def test_registered_today():
    assert [(f.name, f.role, f.gate) for f in fw.registered()] == [
        ("bank_ri", "context", "untested"),  # S96
        ("graham", "context", "untested"),  # S97
        ("piotroski_f", "context", "untested")]  # S95


def test_inputs_for_unwraps_a_bundle_by_name():
    assert fw.inputs_for({"toy": 1, "other": 2}, "toy") == 1
    assert fw.inputs_for({"other": 2}, "toy") == {"other": 2}
    assert fw.inputs_for(None, "toy") is None


def test_base_is_hashed_into_the_model_fingerprint(tmp_path):
    rules = jr.fingerprint_inputs()["rules"]
    assert {"assist/candidates/frameworks/__init__.py",
            "assist/candidates/frameworks/base.py"} <= set(rules)
    import shutil
    pkg = tmp_path / "assist"
    shutil.copytree(jr.PACKAGE_DIR, pkg, ignore=shutil.ignore_patterns("__pycache__"))

    def fp():
        files = sorted({p for g in jr.RULE_GLOBS for p in pkg.glob(g) if p.is_file()})
        return jr.fingerprint(jr.fingerprint_inputs(rule_files=files, config_files=[],
                                                    root=tmp_path))

    before = fp()
    b = pkg / "candidates" / "frameworks" / "base.py"
    b.write_text(b.read_text().replace('NA = "n/a"', 'NA = "na"'))
    assert fp() != before
