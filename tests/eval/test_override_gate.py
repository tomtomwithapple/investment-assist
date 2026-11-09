"""P77 (PLAN S59): the override gate. Per subject × asset × side (up: shift > 0 against ≤ 0; down:
shift < 0 against ≥ 0), the placebo verdict on the point-in-time override history (complete months
only), Holm over the subject's tests, the CLI-zeroed check, the live monitor on the journalled
`overrides` records of this override fingerprint, revocation, and `out/overrides/<SUBJECT>.json`
rebuilt only when a month end passed or the override changed. Tiny in-memory histories: no store,
no network."""

from __future__ import annotations

import dataclasses
import json
import random
from datetime import date

import jsonschema
import pytest

from assist.eval import override_gate as og
from assist.eval.placebo import ALPHA, MIN_N
from assist.history import month_ends
from assist.override_history import COMPONENTS, ComponentPoint, OverrideHistory, OverrideRow

FP = "sha256:" + "a" * 64
OTHER_FP = "sha256:" + "b" * 64
DAY = date(2021, 1, 15)
SINCE = date(2016, 1, 1)
ASSETS = ("stocks", "bonds", "currency")


# ---------------- builders ----------------


def _comp(name: str, direction: int, d: date) -> ComponentPoint:
    return ComponentPoint(float(direction), direction, d, name, "test")


def row(d: date, shift: dict, fwd: dict, *, cli: int = 0, complete: bool = True,
        raw: dict | None = None) -> OverrideRow:
    comps = {n: _comp(n, cli if n == "cli" else 0, d) for n in COMPONENTS}
    if not complete:
        comps.pop("trade")
    return OverrideRow(d, dict(shift), dict(raw if raw is not None else shift), comps,
                       () if complete else ("trade: no data",), (), dict(fwd))


def history(rows) -> OverrideHistory:
    return OverrideHistory("IDN", tuple(rows))


def good_rows(n=120, seed=1, start=date(2010, 1, 31), asset="stocks", up=0.05, off=-0.02,
              noise=0.01) -> list[OverrideRow]:
    """3-month blocks alternate up (+4) and down (−4) shifts on every asset; `asset`'s up
    blocks precede `up`, the rest `off`; the other assets see noise."""
    rng = random.Random(seed)
    out = []
    for i, d in enumerate(month_ends(start, date(2100, 1, 1))[:n]):
        s = 4.0 if (i // 3) % 2 == 0 else -4.0
        fwd = {a: rng.gauss(0, 0.03) for a in ASSETS}
        fwd[asset] = (up if s > 0 else off) + rng.gauss(0, noise)
        out.append(row(d, {a: s for a in ASSETS}, fwd))
    return out


def gate_of(rows, records=(), day=DAY, fp=FP, since=SINCE) -> og.OverrideGate:
    return og.evaluate_subject("IDN", tuple(rows), records=records, day=day, fingerprint=fp,
                               since=since)


# ---------------- sides ----------------


def test_sides_are_up_and_down_with_their_direction():
    assert og.SIDES == {"up": 1, "down": -1}


def test_feature_on_complete_months_only():
    d = date(2015, 1, 31)
    up, zero, down = (row(d, {a: v for a in ASSETS}, {}) for v in (3.0, 0.0, -2.0))
    assert [og.feature(r, "stocks", "up") for r in (up, zero, down)] == [True, False, False]
    assert [og.feature(r, "stocks", "down") for r in (up, zero, down)] == [False, False, True]
    part = row(d, {a: 3.0 for a in ASSETS}, {}, complete=False)
    assert og.feature(part, "stocks", "up") is None


def test_cli_zeroed_feature_removes_the_cli_points_before_the_cap():
    d = date(2015, 1, 31)
    # stocks: cli +1 carries WEIGHTS cli stocks = 3 points; raw 3 → zeroed 0
    r = row(d, {"stocks": 3.0, "bonds": -1.0, "currency": 1.0}, {}, cli=1,
            raw={"stocks": 3.0, "bonds": -1.0, "currency": 1.0})
    assert og.feature(r, "stocks", "up") is True
    assert og.feature(r, "stocks", "up", cli_zeroed=True) is False
    assert og.feature(r, "bonds", "down", cli_zeroed=True) is False
    capped = row(d, {"stocks": 10.0, "bonds": 0.0, "currency": 0.0}, {}, cli=1,
                 raw={"stocks": 14.0, "bonds": 0.0, "currency": 0.0})
    assert og.zeroed_shift(capped, "stocks") == 10.0  # 14 − 3 = 11, capped at 10


# ---------------- Holm ----------------


def test_holm_steps_down_from_the_smallest_p():
    out = og.holm([0.004, 0.009, 0.2, 0.013, 0.5, 0.03])
    by = {o["index"]: o for o in out}
    assert by[0]["rank"] == 1 and by[0]["threshold"] == pytest.approx(ALPHA / 6)
    assert by[0]["passed"] is True
    assert by[1]["threshold"] == pytest.approx(ALPHA / 5) and by[1]["passed"] is True
    assert by[3]["threshold"] == pytest.approx(ALPHA / 4) and by[3]["passed"] is False
    assert not any(by[i]["passed"] for i in (2, 4, 5))  # step-down stops at the first miss


def test_holm_blocks_a_lone_p_of_0_03():
    out = og.holm([0.03, 0.6, 0.7, 0.8, 0.9, 1.0])
    assert not any(o["passed"] for o in out)


def test_a_placebo_pass_that_fails_holm_is_failed():
    hist = og.evaluate_subject("IDN", tuple(good_rows()), records=(), day=DAY, fingerprint=FP,
                               since=SINCE).test("stocks", "up").placebo
    assert hist.passed
    weak = dataclasses.replace(hist, p_value=0.03)
    combined = og.combine(weak, {"passed": False, "rank": 1, "m": 6,
                                 "threshold": ALPHA / 6, "p": 0.03},
                          hist, {"passed": True, "rank": 1, "m": 6, "threshold": ALPHA / 6,
                                 "p": hist.p_value})
    assert combined.passed is False and "Holm" in combined.reason


# ---------------- verdicts ----------------


def test_passed_on_a_history_that_beats_its_placebo():
    g = gate_of(good_rows())
    t = g.test("stocks", "up")
    assert t.state == "passed" and t.verdict.passed
    assert t.holm["passed"] and t.cli_holm["passed"]
    assert t.sample["historical"]["on"] >= MIN_N and t.sample["historical"]["off"] >= MIN_N
    assert g.passed_sides("stocks") >= {"up"}
    # down on stocks: the down blocks precede −2%: weaker returns, as a down claims
    assert g.test("stocks", "down").state == "passed"
    assert g.test("bonds", "up").state == "failed"  # noise
    assert g.passed_sides("bonds") == frozenset()


def test_insufficient_when_a_side_has_fewer_than_ten_windows():
    rows = good_rows(n=45)  # 15 windows: 8 up, 7 down
    t = gate_of(rows).test("stocks", "up")
    assert t.state == "insufficient"
    assert t.distance["historical"]["off"] == MIN_N - t.sample["historical"]["off"] > 0


def test_incomplete_months_are_no_calls_and_open_the_window():
    rows = good_rows()
    rows[:6] = [dataclasses.replace(r, components={k: v for k, v in r.components.items()
                                                   if k != "trade"}) for r in rows[:6]]
    t = gate_of(rows).test("stocks", "up")
    assert t.window[0] == rows[6].as_of


def test_a_cli_zeroed_fail_blocks_a_pass():
    """Every up shift is the CLI's alone (raw 3 = cli 3): with it zeroed nothing is up."""
    rng = random.Random(3)
    rows = []
    for i, d in enumerate(month_ends(date(2010, 1, 31), date(2100, 1, 1))[:120]):
        up = (i // 3) % 2 == 0
        s = 3.0 if up else -1.0
        cli = 1 if up else 0
        fwd = {a: rng.gauss(0, 0.03) for a in ASSETS}
        fwd["stocks"] = (0.05 if up else -0.02) + rng.gauss(0, 0.01)
        rows.append(row(d, {"stocks": s, "bonds": 0.0, "currency": 0.0}, fwd, cli=cli,
                        raw={"stocks": s, "bonds": 0.0, "currency": 0.0}))
    t = gate_of(rows).test("stocks", "up")
    assert t.placebo.passed and t.holm["passed"]
    assert not t.cli_zeroed.passed
    assert t.state == "failed" and not t.verdict.passed
    assert "cli zeroed" in t.verdict.reason


def test_no_history_is_no_verdict():
    g = og.evaluate_subject("IDN", None, records=(), day=DAY, fingerprint=FP, since=DAY)
    for a in ASSETS:
        for side in og.SIDES:
            assert g.test(a, side).state == "none" and g.test(a, side).verdict is None
    assert g.passed_sides("stocks") == frozenset()


# ---------------- live monitor ----------------


def rec(d: date, deltas: dict, *, fp=FP, subject="IDN", complete=True, cli=0) -> dict:
    return {"kind": "overrides", "subject": subject, "as_of": d.isoformat(),
            "outputs": og.journal_outputs(deltas, deltas, complete, cli, fp)}


def test_live_calls_count_only_this_fingerprint_since_the_verdict():
    recs = [rec(date(2020, 3, 2), {"stocks": 4.0}), rec(date(2020, 3, 20), {"stocks": -4.0}),
            rec(date(2020, 4, 6), {"stocks": 4.0}, fp=OTHER_FP),
            rec(date(2019, 12, 2), {"stocks": 4.0}),
            rec(date(2020, 5, 4), {"stocks": 4.0}, subject="USA"),
            rec(date(2020, 6, 1), {"stocks": 4.0}, complete=False)]
    calls = og.live_calls(recs, "IDN", FP, since=date(2020, 1, 1), before=date(2021, 1, 1))
    assert set(calls) == {(2020, 3), (2020, 6)}
    assert calls[(2020, 3)]["deltas"]["stocks"] == -4.0  # the last call in a month stands
    assert og.live_feature(calls[(2020, 6)], "stocks", "up") is None


def test_revoked_when_the_live_calls_go_the_wrong_way():
    rows = good_rows(n=120, start=date(2008, 1, 31), noise=0.005)  # 2008-01 → 2017-12
    since = date(2015, 7, 1)
    # the last 30 months (10 windows) went the other way, and the journal carries their shifts
    rows = [r if r.as_of < since else dataclasses.replace(
        r, forward={**r.forward, "stocks": -r.forward["stocks"]}) for r in rows]
    recs = [rec(r.as_of.replace(day=2), dict(r.shift)) for r in rows if r.as_of >= since]
    g = gate_of(rows, records=recs, day=date(2018, 1, 15), since=since)
    t = g.test("stocks", "up")
    assert t.historical.passed  # the whole history still beats its placebo
    assert t.live_edge.n_on >= og.REVOKE_N and t.live_edge.t <= og.REVOKE_T
    assert t.state == "revoked" and not t.verdict.passed
    assert "up" not in g.passed_sides("stocks")


# ---------------- fingerprint and out/overrides ----------------


def test_override_fingerprint_hashes_the_override_modules_and_the_numbers(tmp_path):
    from assist import journal

    root = tmp_path / "assist"
    for rel in {*og.FILES["IDN"], *og.FILES["USA"]}:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((journal.PACKAGE_DIR / rel).read_bytes())
    base = og.override_fingerprint("IDN", root=root)
    assert base == og.override_fingerprint("IDN")
    usa = og.override_fingerprint("USA", root=root)
    assert usa != base and og.override_fingerprint("EMU", root=root) != usa
    (root / "layers/overrides.py").write_text(
        (root / "layers/overrides.py").read_text() + "\nX_EXTRA = 1\n")
    assert og.override_fingerprint("IDN", root=root) != base
    assert og.override_fingerprint("USA", root=root) == usa  # P28 untouched
    edited = og.override_fingerprint("IDN", root=root)
    (root / "layers/overrides.py").write_text(
        (root / "layers/overrides.py").read_text() + "\n# a comment only\n")
    assert og.override_fingerprint("IDN", root=root) == edited


class Builder:
    def __init__(self, rows, fail=False):
        self.rows, self.fail, self.calls = rows, fail, []

    def __call__(self, subject: str, day: date) -> OverrideHistory:
        self.calls.append((subject, day))
        if self.fail:
            raise RuntimeError("store locked")
        return history([r for r in self.rows if r.as_of < day])


def test_refresh_builds_a_missing_file_and_writes_valid_json(tmp_path):
    b = Builder(good_rows(n=132))
    g = og.refresh(DAY, tmp_path, "IDN", records=(), build=b, fingerprint=FP)
    assert b.calls == [("IDN", DAY)]
    doc = json.loads((tmp_path / "IDN.json").read_text())
    og.validator().validate(doc)
    assert doc["override_fingerprint"] == FP and doc["since"] == DAY.isoformat()
    assert doc["tests"]["stocks"]["up"]["state"] == g.test("stocks", "up").state == "passed"
    assert doc["disclaimer"]


def test_schema_rejects_an_unknown_state(tmp_path):
    og.refresh(DAY, tmp_path, "IDN", records=(), build=Builder(good_rows(n=132)),
               fingerprint=FP)
    doc = json.loads((tmp_path / "IDN.json").read_text())
    doc["tests"]["stocks"]["up"]["state"] = "maybe"
    with pytest.raises(jsonschema.ValidationError):
        og.validator().validate(doc)


def test_refresh_within_the_month_reads_the_file_and_builds_nothing(tmp_path):
    b = Builder(good_rows(n=132))
    og.refresh(DAY, tmp_path, "IDN", records=(), build=b, fingerprint=FP)
    g = og.refresh(date(2021, 1, 28), tmp_path, "IDN", records=(), build=b, fingerprint=FP)
    assert len(b.calls) == 1 and g.since == DAY
    og.refresh(date(2021, 2, 3), tmp_path, "IDN", records=(), build=b, fingerprint=FP)
    assert len(b.calls) == 2  # a month end passed
    doc = json.loads((tmp_path / "IDN.json").read_text())
    assert doc["since"] == DAY.isoformat()  # the monitor keeps counting from the first write


def test_a_file_for_another_fingerprint_counts_as_no_verdict(tmp_path):
    og.refresh(DAY, tmp_path, "IDN", records=(), build=Builder(good_rows(n=132)),
               fingerprint=OTHER_FP)
    g = og.refresh(DAY, tmp_path, "IDN", records=(), build=None, fingerprint=FP)
    assert g.test("stocks", "up").state == "none"
    assert any("another override fingerprint" in s for s in g.stale_inputs)


def test_a_failed_rebuild_never_raises_and_keeps_the_cached_verdict(tmp_path):
    og.refresh(DAY, tmp_path, "IDN", records=(), build=Builder(good_rows(n=132)),
               fingerprint=FP)
    g = og.refresh(date(2021, 3, 2), tmp_path, "IDN", records=(),
                   build=Builder(good_rows(n=132), fail=True), fingerprint=FP)
    assert g.test("stocks", "up").state == "passed"
    assert any("rebuild failed" in s and "store locked" in s for s in g.stale_inputs)


def test_rebuild_flag_forces_a_build(tmp_path):
    b = Builder(good_rows(n=132))
    og.refresh(DAY, tmp_path, "IDN", records=(), build=b, fingerprint=FP)
    og.refresh(DAY, tmp_path, "IDN", records=(), build=b, fingerprint=FP, rebuild=True)
    assert len(b.calls) == 2


def test_refresh_without_a_directory_writes_nothing(tmp_path):
    g = og.refresh(DAY, None, "IDN", records=(), build=Builder(good_rows(n=132)),
                   fingerprint=FP)
    assert g.test("stocks", "up").state == "passed"
    assert not list(tmp_path.iterdir())
