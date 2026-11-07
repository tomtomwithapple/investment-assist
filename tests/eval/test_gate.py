"""P67 (PLAN S48): the rule gate. The historical verdict on the P66 point-in-time history, the live
monitor on the journalled calls, the state, the distance to the gate per side, the rule
fingerprint, and `out/rules/` written and rebuilt only when a month end passed or the rule
changed. Tiny in-memory histories and journals: no store, no network."""

from __future__ import annotations

import dataclasses
import inspect
import json
import random
from datetime import date

import jsonschema
import pytest

from assist.eval import gate
from assist.eval.placebo import MIN_N
from assist.history import HistoryRow, RuleHistory, month_ends
from assist.layers.bonds import gated_stance as bonds_gate
from assist.layers.rules import gated_stance as stocks_gate

FP = "sha256:" + "a" * 64
OTHER_FP = "sha256:" + "b" * 64
DAY = date(2021, 1, 15)
SINCE = date(2016, 1, 1)


# ---------------- builders ----------------


def rows_from(calls: list[str], rets: list[float | None], start=date(2010, 1, 31),
              values=None) -> tuple[HistoryRow, ...]:
    days = month_ends(start, date(2100, 1, 1))[:len(calls)]
    out = []
    for i, (d, c, r) in enumerate(zip(days, calls, rets, strict=True)):
        miss = ("10Y: no 10Y",) if c == "no_call" else ()
        out.append(HistoryRow(d, c, None, miss, None, r, "neutral",
                              (values or {}).get(i, {})))
    return tuple(out)


def good_rows(n=72, seed=1) -> tuple[HistoryRow, ...]:
    """Windows (every 3rd month) alternate enter / hold; enters precede +5%, holds −2%."""
    rng = random.Random(seed)
    calls = ["enter" if (i // 3) % 2 == 0 else "hold" for i in range(n)]
    rets = [(0.05 if c == "enter" else -0.02) + rng.gauss(0, 0.01) for c in calls]
    return rows_from(calls, rets)


def noise_rows(n=72, seed=2) -> tuple[HistoryRow, ...]:
    rng = random.Random(seed)
    calls = ["enter" if (i // 3) % 2 == 0 else "hold" for i in range(n)]
    return rows_from(calls, [rng.gauss(0, 0.03) for _ in calls])


def few_rows() -> tuple[HistoryRow, ...]:
    """Called only from month 12; 4 on-windows, the rest hold; the tail has no return yet."""
    calls = ["no_call"] * 12 + ["enter" if i in (0, 3, 6, 9) else "hold" for i in range(48)]
    rets = [0.01] * 57 + [None] * 3
    return rows_from(calls, rets)


def prices(first=date(2010, 1, 31), months=140, path=None) -> list[tuple[date, float]]:
    days = month_ends(first, date(2100, 1, 1))[:months]
    level, out = 100.0, []
    for i, d in enumerate(days):
        out.append((d, level))
        level *= 1.0 + (path(i) if path else 0.0)
    return out


def rec(day: date, call: str, fp: str | None = FP, asset="stocks") -> dict:
    out = {"call": call}
    if fp is not None:
        out["rule_fingerprint"] = fp
    return {"kind": "rule", "subject": "IDN", "asset": asset, "as_of": day.isoformat(),
            "outputs": out}


def journal_months(first: date, n: int, call_of) -> list[dict]:
    days = month_ends(first, date(2100, 1, 1))[:n]
    return [rec(d, call_of(i)) for i, d in enumerate(days)]


def run_gate(rows, records=(), px=None, asset="stocks", **kw):
    return gate.evaluate_gate(asset, rows, records=list(records), prices=px or prices(),
                              day=kw.pop("day", DAY), fingerprint=FP,
                              since=kw.pop("since", SINCE), **kw)


# ---------------- the states ----------------


def test_passed_on_a_history_that_beats_its_placebo():
    g = run_gate(good_rows())
    assert g.state == "passed"
    assert g.historical.passed and g.historical.rule.n_on >= MIN_N
    assert g.verdict is not None and g.verdict.passed
    assert g.verdict.reason.startswith("gate passed")
    assert g.distance["historical"] == {"on": 0, "off": 0}


def test_insufficient_names_the_distance_per_side():
    g = run_gate(few_rows())
    assert g.state == "insufficient"
    assert not g.verdict.passed and g.verdict.reason.startswith("insufficient sample")
    s = g.sample["historical"]
    assert s["on"] == 4 and s["off"] == 11  # 45 months with a return from month 12, stride 3
    assert g.distance["historical"] == {"on": MIN_N - 4, "off": 0}
    assert g.window == (date(2011, 1, 31), date(2014, 9, 30))  # first call → last return
    assert "6 short of 10" in g.why["on"]


def test_failed_when_the_sample_is_full_but_the_edge_is_noise():
    g = run_gate(noise_rows())
    assert g.historical.rule.ok and not g.historical.passed
    assert g.state == "failed"
    assert g.verdict.reason.startswith("gate failed")


def test_revoked_when_the_live_calls_go_the_wrong_way():
    # live: from 2016-01, enters precede −4% months, holds +4% ones (an edge the wrong way)
    first = date(2016, 1, 31)
    n = 36

    def call(i):
        return "enter" if (i // 3) % 2 == 0 else "hold"

    k0 = month_ends(date(2010, 1, 31), first).index(first)
    rng = random.Random(4)
    noise = [rng.gauss(0, 0.002) for _ in range(200)]

    def path(i):  # month i of the price series; the window of month i − k0 sets the sign
        j = i - k0
        if 0 <= j < n:
            return (-0.015 if call(j) == "enter" else 0.015) + noise[i]
        return 0.0

    recs = journal_months(first, n, call)
    g = run_gate(good_rows(), recs, prices(path=path), day=date(2020, 1, 15))
    e = g.live_edge
    assert e.n_on >= gate.REVOKE_N and e.n_off >= gate.REVOKE_N and e.t <= gate.REVOKE_T
    assert g.state == "revoked"
    assert not g.verdict.passed and g.verdict.reason.startswith("gate revoked")


def test_live_passed_when_the_journal_alone_reaches_ten_per_side():
    first = date(2016, 1, 31)
    n = 72

    def call(i):
        return "enter" if (i // 3) % 2 == 0 else "hold"

    k0 = month_ends(date(2010, 1, 31), first).index(first)
    rng = random.Random(5)
    noise = [rng.gauss(0, 0.002) for _ in range(200)]

    def path(i):
        j = i - k0
        if 0 <= j < n:
            return (0.017 if call(j) == "enter" else -0.007) + noise[i]
        return 0.0

    recs = journal_months(first, n, call)
    g = run_gate(few_rows(), recs, prices(months=160, path=path), day=date(2023, 1, 15))
    assert g.live.rule.n_on >= MIN_N and g.live.rule.n_off >= MIN_N
    assert g.state == "live-passed"
    assert g.verdict.passed and g.verdict.reason.startswith("gate live-passed")


def test_no_history_and_no_journal_is_no_verdict():
    g = run_gate(None)
    assert g.state == "none" and g.verdict is None
    assert g.historical is None


def test_live_calls_count_only_this_rule_fingerprint_since_the_verdict():
    recs = [rec(date(2016, 2, 29), "enter"), rec(date(2016, 3, 31), "hold", fp=OTHER_FP),
            rec(date(2016, 4, 30), "hold", fp=None), rec(date(2015, 12, 31), "enter"),
            rec(date(2016, 5, 31), "reduce"), rec(DAY, "enter"),  # the day's own call: no
            rec(date(2016, 6, 30), "enter", asset="bonds")]
    calls = gate.live_calls(recs, "stocks", FP, since=SINCE, before=DAY)
    assert calls == {(2016, 2): "enter", (2016, 5): "reduce"}


# ---------------- distance and why ----------------


def test_stocks_why_names_the_valuation_peak_against_erp_band():
    calls = ["hold"] * 45
    vals = {i: {"erp_vs_hurdle": -2.0 + 0.01 * i} for i in range(45)}
    vals[20] = {"erp_vs_hurdle": 0.19}
    rows = rows_from(calls, [0.01] * 45, values=vals)
    g = run_gate(rows)
    assert g.sample["historical"]["on"] == 0
    assert g.distance["historical"]["on"] == MIN_N
    assert "no enter call" in g.why["on"]
    assert "+0.19pt" in g.why["on"] and "ERP_BAND 1.0" in g.why["on"]
    assert g.why["off"] == "off side reaches 10 (15 windows)"


def test_no_call_months_are_listed_with_their_reason():
    g = run_gate(few_rows())
    assert len(g.no_call) == 12
    assert g.no_call[0] == {"month": "2010-01", "missing": ["10Y: no 10Y"]}


# ---------------- gated_stance keeps its signature ----------------


def test_gated_stance_keeps_its_signature():
    assert list(inspect.signature(bonds_gate).parameters) == ["base", "bonds", "verdict"]
    assert list(inspect.signature(stocks_gate).parameters) == ["base", "stocks", "verdict"]


# ---------------- the rule fingerprint ----------------


def test_rule_fingerprint_covers_the_rule_and_not_the_other(tmp_path):
    src = tmp_path / "assist"
    for rel in {p for a in gate.ASSETS for p in gate.RULE_FILES[a]}:
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'"""doc"""\nX = {len(rel)}\n')
    before = {a: gate.rule_fingerprint(a, root=src) for a in gate.ASSETS}
    assert before["bonds"] != before["stocks"]
    (src / "layers/rules/idn_stocks.py").write_text('"""doc"""\nX = 999\n')
    after = {a: gate.rule_fingerprint(a, root=src) for a in gate.ASSETS}
    assert after["stocks"] != before["stocks"] and after["bonds"] == before["bonds"]
    (src / "layers/rules/idn_stocks.py").write_text('"""new doc"""\nX = 999\n')
    assert gate.rule_fingerprint("stocks", root=src) == after["stocks"]


def test_rule_fingerprint_of_the_checkout_is_stable():
    assert gate.rule_fingerprint("bonds") == gate.rule_fingerprint("bonds")
    assert gate.FINGERPRINT_RE.fullmatch(gate.rule_fingerprint("stocks"))


# ---------------- out/rules: write, read, rebuild ----------------


class FakeBuild:
    """history.build's shape: both rules over `dates`; counts the calls and the dates asked."""

    def __init__(self, fail=False):
        self.calls: list[list[date]] = []
        self.fail = fail

    def __call__(self, dates, today):
        self.calls.append(list(dates))
        if self.fail:
            raise RuntimeError("store locked")
        out = {}
        for a in gate.ASSETS:
            rows = tuple(HistoryRow(d, "hold", "neutral", (), "dbnomics", None, "neutral", {})
                         for d in dates)
            out[a] = RuleHistory(a, rows)
        return out


def refresh(tmp_path, day, build, **kw):
    px = {"bonds": [(d, 6.5) for d in month_ends(date(2016, 11, 30), day)],
          "stocks": prices(date(2016, 11, 30), 60)}
    return gate.refresh(day, tmp_path / "rules", records=kw.pop("records", []), prices=px,
                        build=build, fingerprints=kw.pop("fingerprints", None), **kw)


def test_refresh_builds_a_missing_file_and_writes_valid_json(tmp_path):
    b = FakeBuild()
    gates = refresh(tmp_path, date(2017, 3, 10), b)
    assert b.calls == [month_ends(date(2016, 11, 30), date(2017, 2, 28))]
    v = gate.validator()
    for a in gate.ASSETS:
        doc = json.loads((tmp_path / "rules" / f"IDN-{a}.json").read_text())
        v.validate(doc)
        assert doc["rule_fingerprint"] == gates[a].fingerprint
        assert doc["since"] == "2017-03-10"
        assert doc["disclaimer"].endswith("not investment advice.")
        assert doc["state"] == gates[a].state


def test_schema_rejects_an_unknown_state(tmp_path):
    refresh(tmp_path, date(2017, 3, 10), FakeBuild())
    doc = json.loads((tmp_path / "rules" / "IDN-bonds.json").read_text())
    doc["state"] = "maybe"
    with pytest.raises(jsonschema.ValidationError):
        gate.validator().validate(doc)


def test_refresh_within_the_month_reads_the_file_and_builds_nothing(tmp_path):
    b = FakeBuild()
    refresh(tmp_path, date(2017, 3, 10), b)
    refresh(tmp_path, date(2017, 3, 27), b)
    assert len(b.calls) == 1
    doc = json.loads((tmp_path / "rules" / "IDN-stocks.json").read_text())
    assert doc["since"] == "2017-03-10"  # carried: the monitor starts at the first verdict
    assert doc["as_of"] == "2017-03-27" and doc["covers"]["last"] == "2017-02"


def test_a_new_month_end_builds_only_the_new_month(tmp_path):
    b = FakeBuild()
    refresh(tmp_path, date(2017, 3, 10), b)
    gates = refresh(tmp_path, date(2017, 4, 3), b)
    assert b.calls[1] == [date(2017, 3, 31)]
    assert gates["bonds"].rows[-1].as_of == date(2017, 3, 31)
    assert len(gates["bonds"].rows) == 5


def test_a_changed_rule_fingerprint_rebuilds_everything(tmp_path):
    b = FakeBuild()
    refresh(tmp_path, date(2017, 3, 10), b)
    fps = {"bonds": gate.rule_fingerprint("bonds"), "stocks": OTHER_FP}
    gates = refresh(tmp_path, date(2017, 3, 12), b, fingerprints=fps)
    assert len(b.calls) == 2 and len(b.calls[1]) == 4
    assert gates["stocks"].fingerprint == OTHER_FP
    assert gates["stocks"].since == date(2017, 3, 12)  # a new rule starts a new monitor
    assert gates["bonds"].since == date(2017, 3, 10)


def test_a_file_whose_fingerprint_differs_counts_as_no_verdict(tmp_path):
    refresh(tmp_path, date(2017, 3, 10), FakeBuild())
    fps = {"bonds": OTHER_FP, "stocks": OTHER_FP}
    gates = refresh(tmp_path, date(2017, 3, 12), None, fingerprints=fps)  # cannot rebuild
    for g in gates.values():
        assert g.state == "none" and g.verdict is None and g.historical is None
        assert any("rule history" in s for s in g.stale_inputs)


def test_a_failed_rebuild_never_raises_and_keeps_the_cached_verdict(tmp_path):
    refresh(tmp_path, date(2017, 3, 10), FakeBuild())
    gates = refresh(tmp_path, date(2017, 4, 3), FakeBuild(fail=True))
    g = gates["stocks"]
    assert g.historical is not None  # same rule: the month-old verdict still stands
    assert g.rows[-1].as_of == date(2017, 2, 28)
    assert any("store locked" in s for s in g.stale_inputs)


def test_refresh_without_a_directory_writes_nothing(tmp_path):
    px = {"bonds": [], "stocks": []}
    gates = gate.refresh(DAY, None, records=[], prices=px, build=None)
    assert all(g.state == "none" for g in gates.values())
    assert not (tmp_path / "rules").exists()


def test_rebuild_flag_forces_a_full_build(tmp_path):
    b = FakeBuild()
    refresh(tmp_path, date(2017, 3, 10), b)
    refresh(tmp_path, date(2017, 3, 11), b, rebuild=True)
    assert len(b.calls) == 2 and len(b.calls[1]) == 4


def test_forward_returns_are_refreshed_from_the_prices(tmp_path):
    b = FakeBuild()
    gates = refresh(tmp_path, date(2017, 6, 10), b)
    st = gates["stocks"]
    with_ret = [r.as_of for r in st.rows if r.forward_return is not None]
    # JCI flat (prices() default): 2016-11 → 2017-02 have a 3-month return by 2017-06-10
    assert with_ret == [date(2016, 11, 30), date(2016, 12, 31), date(2017, 1, 31),
                        date(2017, 2, 28)]


# ---------------- diagnostics ----------------


def test_diagnostic_valuation_only_counts_cheap_months_as_on():
    calls = ["no_call"] * 30
    vals = {i: {"erp_vs_hurdle": 1.5 if (i // 3) % 2 == 0 else -0.5} for i in range(30)}
    rows = tuple(dataclasses.replace(r, missing=("foreign flow: no signal",))
                 for r in rows_from(calls, [0.0] * 30, values=vals))
    px = prices(months=40)
    d = gate.diagnostic("stocks", rows, prices=px, day=date(2013, 6, 1), horizon=1,
                        variant="valuation-only")
    assert d["gates"] is False and d["horizon"] == 1 and d["variant"] == "valuation-only"
    assert d["sample"]["on"] + d["sample"]["off"] == 30
    assert d["sample"]["on"] == 15
