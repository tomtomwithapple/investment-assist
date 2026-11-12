"""S94 baseline board (P111): screens' replay picks through S92's report, side by side.

Picks are each replay's top quintile at quarter-end months (calendar month ends), the pool is
the date's ranked names; the board's windows, excess returns, independent windows, ranking,
gate state, survivorship counts, registered frameworks without a replay, the schema and the
CLI writer. Synthetic month-end prices only; no store, no network."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from assist import cli, pipeline
from assist import framework_board as fb
from assist.candidates.frameworks import base as fw_base
from assist.eval.picks_report import PicksData, add_months

D = date.fromisoformat
STARTS = [D("2024-03-31"), D("2024-06-30"), D("2024-09-30"), D("2024-12-31")]


def month_ends(first: str, n: int) -> list[date]:
    return [add_months(D(first), k) for k in range(n)]


def path(rate: float, n: int = 30) -> list[tuple[date, float]]:
    return [(d, 100 * (1 + rate) ** k) for k, d in enumerate(month_ends("2023-12-31", n))]


def data() -> PicksData:
    """A grows 2% a month, B is flat, C falls 1% a month; the JCI is flat to 2026-05-31."""
    return PicksData(prices={"AAA": path(0.02), "BBB": path(0.0), "CCC": path(-0.01)},
                     dividends={"BBB": [{"ex": "2024-05-15", "value": 3.0}]},
                     jci=[(d, 1000.0) for d in month_ends("2023-12-31", 30)])


def replay(name: str, held: str, gate: str = "failed") -> fb.Replay:
    pool = ["AAA", "BBB", "CCC"]
    return fb.Replay(name, "screen", f"{name} screen", "top quintile", {d: [held] for d in STARTS},
                     {d: pool for d in STARTS}, gate, "rule t below 2" if gate == "failed"
                     else "rule beats placebo")


def win(entry: dict, label: str) -> dict:
    return next(w for w in entry["windows"] if w["window"] == label)


# ---------------- picks per quarter ----------------


def test_top_quintile_keeps_quarter_months_on_calendar_month_ends():
    syms = [f"S{i:02d}" for i in range(10)]
    ranked = [(D("2024-03-28"), syms), (D("2024-04-30"), syms), (D("2024-06-28"), syms[:4])]
    picks, pools = fb.top_quintile(ranked, min_pool=5)
    assert list(picks) == [D("2024-03-31")]  # April is not a quarter end; June's pool is short
    assert picks[D("2024-03-31")] == ["S00", "S01"]  # 10 // 5
    assert pools[D("2024-03-31")] == syms


def test_ranked_by_orders_best_first_ties_by_symbol_and_drops_missing():
    panel = [(D("2024-03-31"), [{"symbol": "B", "x": 1.0}, {"symbol": "A", "x": 1.0},
                                {"symbol": "C", "x": 2.0}, {"symbol": "D", "x": None}])]
    assert fb.ranked_by(panel, "x") == [(D("2024-03-31"), ["C", "A", "B"])]


def test_ranked_blend_is_the_screens_blend_order():
    recs = [{"symbol": f"S{i:02d}", "bp": float(i)} for i in range(10)]
    out = fb.ranked_blend([(D("2024-03-29"), recs)], (("bp", 1),))
    assert out[0][1][:3] == ["S09", "S08", "S07"]


def test_gate_of_maps_the_placebo_verdict():
    assert fb.gate_of(SimpleNamespace(passed=True, reason="ok")) == ("passed", "ok")
    assert fb.gate_of(SimpleNamespace(passed=False, reason="n")) == ("failed", "n")
    assert fb.gate_of(None) == ("untested", None)


# ---------------- the board ----------------


def test_board_excess_vs_pool_and_jci_with_independent_windows():
    p = fb.build([replay("alpha", "AAA", "passed"), replay("beta", "CCC")], data(),
                 day=D("2026-11-12"))
    assert p["as_of"] == "2026-05-31"
    a, b = p["frameworks"]
    w3 = win(a, "3m")
    assert w3["n_starts"] == 4 and w3["n_independent"] == 4
    assert w3["total"] == pytest.approx(1.02 ** 3 - 1, abs=1e-6)
    assert w3["jci"] == pytest.approx(0.0)
    assert w3["excess_jci"] == pytest.approx(1.02 ** 3 - 1, abs=1e-6)
    # BBB's 3.0 goes ex in the 2024-03-31 start only: a third of it, in one start of four
    pool = (1.02 ** 3 - 1 + 0.99 ** 3 - 1) / 3 + 0.03 / 3 / 4
    assert w3["pool_total"] == pytest.approx(pool, abs=1e-6)
    assert w3["excess_pool"] == pytest.approx(w3["total"] - w3["pool_total"], abs=1e-6)
    w1y = win(a, "1y")
    assert (w1y["n_starts"], w1y["n_independent"]) == (4, 1)
    assert not w1y["verdict_window"] and w3["verdict_window"] and win(a, "6m")["verdict_window"]
    w3y = win(a, "3y")
    assert (w3y["n_starts"], w3y["total"], w3y["excess_pool"]) == (0, None, None)  # open
    assert a["gate"] == {"state": "passed", "reason": "rule beats placebo"}
    assert b["gate"]["state"] == "failed"
    assert (a["starts"], a["first_start"], a["last_start"]) == (4, "2024-03-31", "2024-12-31")
    assert a["mean_picks"] == 1 and a["mean_pool"] == 3


def test_ranking_orders_by_excess_vs_pool_per_window():
    p = fb.build([replay("beta", "CCC"), replay("alpha", "AAA")], data(), day=D("2026-11-12"))
    assert [r["name"] for r in p["ranking"]["3m"]] == ["alpha", "beta"]
    assert p["ranking"]["3y"] == []
    by = {e["name"]: e for e in p["frameworks"]}
    assert win(by["alpha"], "3m")["rank_pool"] == 1 and win(by["beta"], "3m")["rank_pool"] == 2
    assert win(by["alpha"], "5y")["rank_pool"] is None
    assert p["ranking"]["3m"][0]["n_independent"] == 4
    assert "Only 1m, 3m and 6m can carry a verdict" in p["verdict_note"]
    assert [w["verdict_window"] for w in p["windows"]] == [True, True, True, False, False, False]


def test_survivorship_counts_delisted_names_in_pool_and_picks():
    rep = replay("alpha", "AAA")
    s = fb.survivorship(rep, {"AAA": {"delisted": False}, "CCC": {"delisted": True},
                              "ZZZ": {"delisted": True}}, stopped=["CCC"])
    assert (s["delisted_known"], s["delisted_in_pool"], s["delisted_picked"]) == (2, 1, 0)
    assert s["stopped"] == ["CCC"]
    assert "1 of 2 delisted names ever enter the pool, 0 are ever held" in s["note"]
    assert "unknown" in fb.survivorship(rep, {})["note"]


def test_a_delisted_pick_is_held_at_its_last_bar_and_counted():
    d = data()
    d.prices["DDD"] = path(0.01, 5)  # last bar 2024-04-30
    rep = fb.Replay("gamma", "screen", "", "", {STARTS[0]: ["DDD"]}, {STARTS[0]: ["DDD", "AAA"]})
    p = fb.build([rep], d, day=D("2026-11-12"), universe={"DDD": {"delisted": True}},
                 as_of=D("2026-05-31"))  # by default as_of stops at the held name's last bar
    e = p["frameworks"][0]
    assert e["survivorship"]["stopped"] == ["DDD"]
    assert e["survivorship"]["delisted_picked"] == 1
    assert win(e, "3m")["total"] == pytest.approx(0.01, abs=1e-6)


def test_registered_framework_without_replay_is_listed_untested(monkeypatch):
    class Dummy(fw_base.Framework):
        """Dummy framework for the board."""
        name, VERSION = "dummy", "0.0.1"

    p = fb.build([replay("alpha", "AAA")], data(), day=D("2026-11-12"), frameworks=[Dummy()],
                 skipped=[{"name": "garp", "reason": "boom"}])
    e = p["frameworks"][-1]
    assert (e["name"], e["kind"], e["status"], e["gate"]["state"]) == (
        "dummy", "framework", "no replay", "untested")
    assert all(w["total"] is None for w in e["windows"])
    assert [r["name"] for r in p["ranking"]["3m"]] == ["alpha"]
    assert p["skipped"] == [{"name": "garp", "reason": "boom"}]


def test_no_picks_entry_and_missing_start_bar():
    empty = fb.Replay("none", "screen", "", "", {}, {})
    late = fb.Replay("late", "screen", "", "", {STARTS[0]: ["NEW"]}, {STARTS[0]: ["NEW"]})
    d = data()
    d.prices["NEW"] = [(D("2025-01-31"), 10.0), (D("2025-02-28"), 11.0)]
    p = fb.build([empty, late], d, day=D("2026-11-12"))
    assert p["frameworks"][0]["status"] == "no picks"
    assert win(p["frameworks"][1], "3m")["n_starts"] == 0
    assert any("n/a" in n for n in p["frameworks"][1]["notes"])


def sample_payload() -> dict:
    """A schema-valid board (also the e2e fixture of /frameworks)."""
    return fb.build([replay("alpha", "AAA", "passed"), replay("beta", "CCC")], data(),
                    day=D("2026-11-12"), universe={"CCC": {"delisted": True}})


def test_payload_validates_and_writes(tmp_path):
    p = sample_payload()
    assert not list(fb.validator().iter_errors(p))
    out = fb.write(p, tmp_path)
    assert out == tmp_path / "frameworks" / "IDN.json"
    assert json.loads(out.read_text())["schema_version"] == "1.0.0"
    bad = dict(p, frameworks=[dict(p["frameworks"][0], status="maybe")])
    with pytest.raises(ValueError, match="schema"):
        fb.write(bad, tmp_path)


# ---------------- CLI ----------------


def test_cli_frameworks_writes_the_board(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline.Paths, "default",
                        classmethod(lambda cls: pipeline.Paths.under(tmp_path, tmp_path / "n")))
    monkeypatch.setattr(fb, "live", lambda day: sample_payload())
    assert cli.main(["frameworks", "--today", "2026-11-12"]) == 0
    p = json.loads((tmp_path / "out" / "frameworks" / "IDN.json").read_text())
    assert [e["name"] for e in p["frameworks"]] == ["alpha", "beta"]
    printed = capsys.readouterr().out
    assert "alpha" in printed and "3m" in printed and "n_ind" in printed


def test_run_does_not_build_the_board():
    from pathlib import Path

    assert "framework_board" not in Path(pipeline.__file__).read_text(encoding="utf-8")
