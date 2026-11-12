"""Framework results on candidate rows and in the journal (P110, PLAN S93): context only, they
never change a size, a rank or a verdict, and with none registered the payload is unchanged."""

from __future__ import annotations

import copy
import json
from datetime import date

import pytest
from test_run_undervalued import DAY, DIV, FP, GARP, REGIME, inputs, screen, stance, valid

from assist import journal, pipeline
from assist.candidates import frameworks as fw
from assist.candidates.frameworks import base
from assist.layers import undervalued as uv

KNOWN = date(2026, 5, 1)


class Size(fw.Framework):
    """Scores a name by the length of its symbol; n/a for ELSA."""

    name = "size_toy"
    VERSION = "0.1.0"

    def evaluate(self, sym, inputs):
        if sym in (inputs or {}).get("no_data", ()):
            return self.missing(sym, None, "no fundamentals")
        return self.result(sym, KNOWN, float(len(sym)), "pass", {"len": float(len(sym))})


class Excl(fw.Framework):
    name = "excl_toy"
    VERSION = "0.1.0"
    role = "exclusion"

    def evaluate(self, sym, inputs):
        return self.result(sym, KNOWN, 0.0, "fail", {})


@pytest.fixture
def registry(monkeypatch):
    reg: dict = {}
    monkeypatch.setattr(base, "REGISTRY", reg)
    return reg


def payload(framework_inputs=None, holdings=None):
    inp = inputs({"dividend_value": screen("dividend_value", cands=DIV),
                  "garp": screen("garp", cands=GARP)})
    inp.framework_inputs = framework_inputs
    return valid(uv.assemble(inp, day=DAY, stance=stance("overweight", 10.0, 20.0),
                             portfolio_value_idr=1e9, holdings=holdings or {"BMRI": 20e6},
                             regime=REGIME, fingerprint=FP))


def strip(p):
    q = copy.deepcopy(p)
    for s in q["styles"]:
        for r in s["rows"]:
            r.pop("frameworks", None)
    return q


def test_schema_version_is_1_5_0():
    assert uv.SCHEMA_VERSION == "1.5.0"
    assert payload()["schema_version"] == "1.5.0"


def test_with_nothing_registered_no_row_has_frameworks(registry):
    p = payload()
    rows = [r for s in p["styles"] for r in s["rows"]]
    assert rows and not any("frameworks" in r for r in rows)
    assert "frameworks" not in p["config"]


def test_context_results_ride_on_rows_and_change_nothing_else(registry):
    bare = payload({"no_data": ["ELSA"]})
    fw.register(Size())
    fw.register(Excl())
    p = payload({"no_data": ["ELSA"]})
    # sizes, ranks, verdicts, sizing and the guide inputs are byte-identical
    assert uv._dumps(strip(p)) == uv._dumps(bare)
    rows = {(s["style"], r["symbol"]): r for s in p["styles"] for r in s["rows"]}
    assert rows
    for (_, sym), r in rows.items():
        (res,) = r["frameworks"]  # the exclusion is not attached: not adopted (rule 2)
        assert res["framework"] == "size_toy" and res["role"] == "context"
        assert res["gate"] == "untested"
        if sym == "ELSA":
            assert (res["score"], res["signal"], res["flags"]) == (None, "n/a",
                                                                   ["no fundamentals"])
        else:
            assert res["score"] == float(len(sym)) and res["as_of"] == "2026-05-01"


def test_schema_refuses_a_bad_framework_entry(registry):
    fw.register(Size())
    p = payload()
    r = p["styles"][0]["rows"][0]
    r["frameworks"][0]["role"] = "verdict"
    assert list(uv.validator().iter_errors(p))
    r["frameworks"][0] = {"framework": "x"}
    assert list(uv.validator().iter_errors(p))


def test_row_with_frameworks_round_trips_through_the_journal(registry, tmp_path):
    fw.register(Size())
    p = payload({"no_data": ["ELSA"]})
    j = journal.Journal(tmp_path / "journal")
    fp = j.register_model()
    p["model_fingerprint"] = fp
    pipeline._journal_undervalued(j, [p], fp, "run-1")
    recs = [r for r in j.read() if r["kind"] == "undervalued_row"]
    want = [r for s in p["styles"] for r in s["rows"]]
    assert [r["outputs"] for r in recs] == json.loads(json.dumps(want))
    for rec, row in zip(recs, want, strict=True):
        got = [fw.FrameworkResult.from_dict(d) for d in rec["outputs"]["frameworks"]]
        assert [x.to_dict() for x in got] == row["frameworks"]
    assert j.verify() == len(list(j.read()))
    assert {r["kind"] for r in j.read()} == {"undervalued", "undervalued_row"}  # no new kind
    model = j.model(fp)
    assert "assist/candidates/frameworks/base.py" in model["rules"]
