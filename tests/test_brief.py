"""Markdown brief (PLAN S6a): built only from stance payloads (tests/fixtures/stance/) and a
previous out/ snapshot (tests/fixtures/brief/previous/). Nothing here reads a store."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from helpers import FIXTURES, load_stances

from assist import brief
from assist.layers.types import DISCLAIMER

PREVIOUS = FIXTURES / "brief" / "previous"
EXPECTED = FIXTURES / "brief" / "expected.md"


def write_out(root: Path, stances: list[dict]) -> Path:
    for s in stances:
        p = root / s["subject"] / f"{s['asset']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")
    return root


def current() -> list[dict]:
    return load_stances()


def previous() -> list[dict]:
    return brief.load_out(PREVIOUS).stances


def section(md: str, title: str) -> str:
    """Body of the `## title` section, up to the next `## ` heading."""
    head = f"## {title}"
    assert head in md, f"missing section {title!r}"
    body = md.split(head, 1)[1]
    return body.split("\n## ", 1)[0]


# ---------------- loading ----------------

def test_load_out_reads_subject_asset_layout(tmp_path):
    out = write_out(tmp_path / "out", current())
    loaded = brief.load_out(out)
    assert [(s["subject"], s["asset"]) for s in loaded.stances] == [
        ("IDN", "stocks"), ("IDN", "bonds"), ("USA", "bonds")]
    assert loaded.problems == []


def test_load_out_skips_invalid_files_and_reports_them(tmp_path):
    out = write_out(tmp_path / "out", current())
    (out / "IDN" / "currency.json").write_text("{not json")
    bad = copy.deepcopy(current()[0])
    bad.update(subject="SGP", stance="buy")
    write_out(out, [bad])
    (out / "SGP.json").write_text("{}")  # not under a subject dir: ignored, not a problem
    loaded = brief.load_out(out)
    assert len(loaded.stances) == 3
    assert any("IDN/currency.json" in p for p in loaded.problems)
    assert any("SGP/bonds.json" in p for p in loaded.problems)


def test_load_out_ignores_non_subject_dirs(tmp_path):
    out = write_out(tmp_path / "out", current())
    brief.save_snapshot(out, out / "_snapshots", "2026-10-13")
    assert len(brief.load_out(out).stances) == 3


def test_missing_out_dir_is_empty_not_an_error(tmp_path):
    loaded = brief.load_out(tmp_path / "nope")
    assert loaded.stances == [] and loaded.problems == []
    md = brief.render([])
    assert DISCLAIMER in md and "No stances" in md


# ---------------- rendering ----------------

def test_disclaimer_top_and_bottom_and_source_attribution():
    md = brief.render(current())
    lines = md.strip().splitlines()
    assert lines[0].startswith("# ")
    assert DISCLAIMER in "\n".join(lines[:4])
    assert DISCLAIMER in lines[-1]
    srcs = section(md, "Sources")
    for name in ("worldbankscape", "sec-edgar FRED", "idxscape", "kseistat", "bisfetcher",
                 "financer"):
        assert name in srcs


def test_title_and_regime_from_payloads():
    md = brief.render(current())
    assert md.startswith("# Investment brief 2026-10-13")
    reg = section(md, "Global regime")
    assert "neutral" in reg
    # dollar differs across payloads: both values are shown with their subjects
    assert "up" in reg and "flat" in reg


def test_stance_table_rows_in_order():
    md = brief.render(current())
    table = section(md, "Stances")
    rows = [line for line in table.splitlines() if line.startswith("| ") and "---" not in line]
    assert rows[0].startswith("| Subject")
    body = rows[1:]
    assert [r.split("|")[1].strip() + " " + r.split("|")[2].strip() for r in body] == [
        "IDN stocks", "IDN bonds", "USA bonds"]
    idn_bonds = body[1]
    for cell in ("overweight", "68", "0.74", "ladder 3×10d", "8% → 15%", "+7pt over 3 tranches"):
        assert cell in idn_bonds
    assert "n/a → 0%" in body[2]


def test_details_render_drivers_risks_watch_generically():
    s = copy.deepcopy(current())
    s[0]["drivers"].append("a brand-new layer-3 driver | with a pipe")
    s[0]["watch"].append("FOMC 2026-10-28")
    md = brief.render(s)
    det = section(md, "Details")
    assert "a brand-new layer-3 driver | with a pipe" in det
    assert "real yield 3.1% (82nd pct)" in det
    assert "USD/IDR at 6m high" in det
    assert "JCI daily series frozen at 2026-09-30" in det  # flags shown too
    watch = section(md, "Watch")
    assert watch.count("BI meeting 2026-10-22") == 1  # merged across stances
    assert "IDN stocks, IDN bonds" in watch
    assert "FOMC 2026-10-28" in watch


def test_table_cells_escape_pipes():
    s = copy.deepcopy(current())
    s[0]["portfolio"]["delta"] = "+7pt | 3 tranches"
    table = section(brief.render(s), "Stances")
    assert "+7pt \\| 3 tranches" in table


def test_stale_inputs_listed_with_their_stances():
    stale = section(brief.render(current()), "Stale inputs")
    assert "financer (locked)" in stale and "USA bonds" in stale
    assert "idx-method jkse_daily.csv" in stale and "IDN stocks" in stale
    fresh = [s for s in current() if not s["stale_inputs"]]
    assert "None" in section(brief.render(fresh), "Stale inputs")


def test_problems_section_only_when_there_are_problems():
    assert "## Problems" not in brief.render(current())
    md = brief.render(current(), problems=["out/IDN/currency.json: not JSON"])
    assert "out/IDN/currency.json: not JSON" in section(md, "Problems")


def test_render_is_deterministic_and_order_free():
    a = brief.render(current(), previous())
    b = brief.render(list(reversed(current())), list(reversed(previous())))
    assert a == b


# ---------------- changes since last run ----------------

def test_first_run_has_no_changes():
    ch = section(brief.render(current()), "Changes since last run")
    assert "First run" in ch


def test_changes_vs_previous_snapshot():
    lines = brief.diff(previous(), current())
    text = "\n".join(lines)
    assert "Regime: risk_off → neutral" in text
    assert "IDN bonds: stance neutral → overweight" in text
    assert "score 55 → 68" in text
    assert "target 8% → 15%" in text
    assert "USA bonds: new (underweight, score 41)" in text
    assert "JPN stocks: dropped (was neutral)" in text
    assert "IDN stocks" not in text  # unchanged
    assert "lump" not in text  # IDN bonds entry style unchanged (ladder → ladder)


def test_changes_show_new_and_cleared_stale_inputs_and_model_change():
    prev = previous()
    cur = copy.deepcopy(current())
    for s in cur:
        if (s["subject"], s["asset"]) == ("IDN", "stocks"):
            s["stale_inputs"] = ["bps-looker (locked)"]
            s["model_fingerprint"] = "sha256:" + "1" * 64
    text = "\n".join(brief.diff(prev, cur))
    assert "IDN stocks: stale +bps-looker (locked), -idx-method jkse_daily.csv" in text
    assert "Model changed" in text


def test_no_changes_message():
    prev = [s for s in current()]
    ch = section(brief.render(current(), prev), "Changes since last run")
    assert "No changes" in ch


def test_small_score_moves_are_not_changes():
    cur = copy.deepcopy(current())
    cur[0]["score"] += 0.4
    assert brief.diff(current(), cur) == []


def test_holdings_notes_listed_once_under_the_stance_table():
    """PLAN S32: lines valued at a trade price are named in the brief, not in stale inputs."""
    stances = copy.deepcopy(current())
    note = "financer stockbit (priskila): valued at last trade price: 63 lines"
    for s in stances:
        s["portfolio"]["notes"] = [note]
    body = section(brief.render(stances), "Stances")
    assert body.count(note) == 1 and "Holdings: " in body
    assert "Holdings: " not in section(brief.render(current()), "Stances")


def test_stance_table_splits_rebalance_and_tilt():
    """PLAN S42: the delta cell names the benchmark part a rebalance, the rest a tilt, and a
    line under the table says the move to the benchmark is not a model call."""
    stances = copy.deepcopy(current())
    for s in stances:
        if (s["subject"], s["asset"]) == ("IDN", "stocks"):
            s["portfolio"].update(current_pct=96.9, target_pct=45.7, benchmark_pct=48.0,
                                  delta="-51.2pt trim over 3 tranches",
                                  rebalance_pt=-51.2, tilt_pt=0.0)
        if (s["subject"], s["asset"]) == ("IDN", "bonds"):
            s["portfolio"].update(current_pct=3.1, target_pct=30.5, benchmark_pct=32.0,
                                  delta="+27.4pt over 3 tranches", rebalance_pt=27.4,
                                  tilt_pt=0.0)
    body = section(brief.render(stances), "Stances")
    row = next(r for r in body.splitlines() if r.startswith("| IDN | stocks"))
    assert "-51.2pt trim over 3 tranches; -51.2pt = -51.2pt rebalance to benchmark, " \
           "+0.0pt tilt" in row
    assert "Rebalance vs tilt: IDN stocks -51.2pt rebalance, +0.0pt tilt; IDN bonds " \
           "+27.4pt rebalance, +0.0pt tilt." in body
    assert "a move to the 48/32/20 benchmark, not a model call" in body
    # payloads before S42 have no split: no line, no cell suffix
    plain = section(brief.render(current()), "Stances")
    assert "rebalance" not in plain.lower()


# ---------------- snapshots + whole brief ----------------

def test_snapshot_roundtrip_and_previous_lookup(tmp_path):
    out = write_out(tmp_path / "out", current())
    snaps = tmp_path / "snaps"
    shutil.copytree(PREVIOUS, snaps / "2026-10-06")
    shutil.copytree(PREVIOUS, snaps / "2026-09-29")
    path = brief.save_snapshot(out, snaps, "2026-10-13")
    assert path == snaps / "2026-10-13"
    assert len(brief.load_out(path).stances) == 3
    assert brief.previous_snapshot(snaps, before="2026-10-13") == snaps / "2026-10-06"
    assert brief.previous_snapshot(snaps, before="2026-10-06") == snaps / "2026-09-29"
    assert brief.previous_snapshot(snaps, before="2026-09-29") is None
    assert brief.previous_snapshot(tmp_path / "none", before="2026-10-13") is None
    # re-saving the same day replaces, never merges
    (out / "USA" / "bonds.json").unlink()
    brief.save_snapshot(out, snaps, "2026-10-13")
    assert len(brief.load_out(snaps / "2026-10-13").stances) == 2


def test_build_brief_diffs_against_latest_earlier_snapshot(tmp_path):
    out = write_out(tmp_path / "out", current())
    snaps = tmp_path / "snaps"
    shutil.copytree(PREVIOUS, snaps / "2026-10-06")
    brief.save_snapshot(out, snaps, "2026-10-13")  # today's own snapshot is not "previous"
    md = brief.build_brief(out, snaps)
    ch = section(md, "Changes since last run")
    assert "2026-10-06" in ch and "IDN bonds: stance neutral → overweight" in ch


def test_golden_brief_matches_fixture():
    md = brief.render(current(), previous(), previous_as_of="2026-10-06")
    if not EXPECTED.exists():  # pragma: no cover - regenerate by deleting the file
        EXPECTED.write_text(md)
        pytest.fail("wrote expected.md; review it and rerun")
    assert md == EXPECTED.read_text(encoding="utf-8")


# ---------------- paper lines: annualised only from 12 scored weeks (S41) ----------------


def _paper_rep(weeks: int, annualized):
    from datetime import date as _date

    from assist.paper import PaperReport
    summ = {"weeks": weeks, "stale_weeks": 0, "cumulative": -0.077, "annualized": annualized,
            "volatility": None, "annualize_min_weeks": 12}
    return PaperReport(as_of=_date(2026, 11, 6), start=_date(2026, 10, 9),
                       legs={"stocks": "JCI"}, bond_series="igsyc.10y",
                       benchmark_pct={"stocks": 48.0, "bonds": 32.0, "usa": 20.0},
                       stale_inputs=[], benchmark_summary=summ, benchmark=[], segments=[],
                       notes=[], legacy_benchmark_pct={"stocks": 60.0, "bonds": 40.0},
                       legacy_start=_date(2026, 10, 9), legacy_summary=dict(summ))


def test_paper_lines_hide_annualised_below_12_scored_weeks():
    from assist import brief as _brief
    lines = _brief.paper_lines(_paper_rep(1, None))
    assert "cumulative -7.7%" in lines[0]
    assert "annualised after 12 scored weeks" in lines[0]
    assert "annualised -" not in lines[0] and "annualised n/a" not in lines[0]
    legacy = [x for x in lines if x.startswith("Legacy")][0]
    assert "annualised after 12 scored weeks" in legacy


def test_paper_lines_show_annualised_from_12_scored_weeks():
    from assist import brief as _brief
    lines = _brief.paper_lines(_paper_rep(12, -0.29))
    assert "annualised -29.0%" in lines[0] and "after 12" not in lines[0]


def test_paper_lines_carry_the_flip_count():
    from assist import brief as _brief
    from assist import flips as _flips
    rep = _paper_rep(1, None)
    rep.flips = _flips.count([])
    lines = _brief.paper_lines(rep)
    assert any(x.startswith("Verdict flips: no holding records") for x in lines)
    assert any("S87 replay" in x and "0.26" in x for x in lines)


def test_paper_lines_old_report_without_flips():
    from assist import brief as _brief
    lines = _brief.paper_lines(_paper_rep(1, None))
    assert not any("flips" in x.lower() for x in lines)


# ---------------- home (IDN) regime line (S54, P73) ----------------


HOME_OFF = {"state": "risk_off", "points": 2, "drivers": ["JCI -17.5% vs 20d high (2)"],
            "stale_inputs": []}


def _with_home(home: dict) -> list[dict]:
    out = copy.deepcopy(current())
    for s in out:
        if s["subject"] == "IDN" and s["asset"] in ("stocks", "bonds"):
            s["home_regime"] = copy.deepcopy(home)
    return out


def test_home_regime_line_under_the_global_regime():
    md = brief.render(_with_home(HOME_OFF))
    reg = section(md, "Global regime")
    assert ("- Home regime (IDN): risk_off, 2 points (JCI -17.5% vs 20d high (2)); IDN stocks "
            "and bonds adds and trims laddered") in reg


def test_home_regime_neutral_and_stale_inputs():
    home = {"state": "neutral", "points": 1, "drivers": ["USD/IDR +2.1%/20 fixings (1)"],
            "stale_inputs": ["idxscape SBN.TOTAL.non_resident (last 2026-09-25)"]}
    line = brief.home_line(_with_home(home))
    assert line == ("- Home regime (IDN): neutral, 1 point (USD/IDR +2.1%/20 fixings (1)); "
                    "stale: idxscape SBN.TOTAL.non_resident (last 2026-09-25)")


def test_no_home_regime_no_line():
    assert brief.home_line(current()) is None
    assert "Home regime" not in brief.render(current())


def test_golden_brief_changes_only_by_the_home_line():
    md = brief.render(_with_home(HOME_OFF), previous(), previous_as_of="2026-10-06")
    lines = md.splitlines()
    home = [x for x in lines if x.startswith("- Home regime (IDN)")]
    assert len(home) == 1
    lines.remove(home[0])
    assert "\n".join(lines) + ("\n" if md.endswith("\n") else "") == EXPECTED.read_text(
        encoding="utf-8")


# ---------------- layer-2 override gate (S61, P79) ----------------


def _with_layer2(blocks: dict) -> list[dict]:
    out = copy.deepcopy(current())
    for s in out:
        if (s["subject"], s["asset"]) in blocks:
            s["layer2"] = copy.deepcopy(blocks[(s["subject"], s["asset"])])
    return out


def _l2(shift, up="failed", down="failed", passed=(), crossed=False, held=False):
    return {"shift": shift, "gate": {"up": up, "down": down}, "passed": list(passed),
            "crossed": crossed, "held": held}


def test_override_gate_line_when_no_side_passed():
    stances = _with_layer2({("IDN", "bonds"): _l2(-4.0, held=False),
                            ("IDN", "stocks"): _l2(-5.0, held=True)})
    line = brief.override_gate_line(stances)
    assert line == ("- Layer-2 override gate: no side passed (2 gated stance(s)); overrides move "
                    "scores, never bands; held at the band: IDN stocks")
    assert line in section(brief.render(stances), "Global regime")


def test_override_gate_line_names_passes_and_crossings():
    stances = _with_layer2({("IDN", "bonds"): _l2(-6.0, down="passed", passed=("down",),
                                                  crossed=True),
                            ("IDN", "stocks"): _l2(3.0, up="insufficient")})
    line = brief.override_gate_line(stances)
    assert "passed: IDN bonds down" in line
    assert "crossed: IDN bonds → " in line


def test_no_layer2_no_override_gate_line():
    assert brief.override_gate_line(current()) is None


# ---------------- average down (P89, PLAN S70) ----------------


def _down_payload(names, rows=()):
    return {"market": "IDN", "styles": [{"style": "dividend_value", "passed": True,
                                         "rows": list(rows)}],
            "sizing": {"trims": [], "budget_idr": 0.0},
            "average_down": {"underwater_pct": 5.0, "gate3": "context", "names": list(names)}}


def _down_name(sym, status, gate, below, reason="r", avg=1000.0, new=None):
    return {"symbol": sym, "status": status, "gate": gate, "reason": reason, "avg_cost": avg,
            "quantity": 100.0, "price": avg * (1 + below / 100), "below_cost_pct": below,
            "new_avg_cost": new, "entry_status": None}


def test_average_down_lines_none_with_where_the_names_stopped():
    from assist import brief, pipeline

    p = _down_payload([_down_name("AMRT", "stopped", 2, -35.0),
                       _down_name("BMRI", "stopped", 4, -15.2),
                       _down_name("KLBF", "stopped", 2, -18.6),
                       _down_name("BBCA", "stopped", 1, -0.2)])
    line = ("none: 3 of 4 held names are 5% or more below cost "
            "(2 not kept by a passing screen, 1 no room under the caps)")
    assert brief.average_down_lines(p) == [line]
    assert [n["symbol"] for n in brief.average_down_view(p)["stopped"]] == [
        "AMRT", "KLBF", "BMRI"]  # deepest first
    assert f"IDN to average down: {line}" in pipeline.trade_lines([p])


def test_average_down_lines_funded_and_unfunded():
    from assist import brief, pipeline

    row = {"symbol": "BMRI", "rank": 1, "action": "average_down",
           "size": {"idr": 3e6, "tranches": [], "reason": "x"}}
    p = _down_payload([_down_name("BMRI", "average_down", None, -15.2, avg=4244.0, new=4180.0),
                       _down_name("TLKM", "unfunded", 5, -8.0, reason="no budget: x"),
                       _down_name("AMRT", "stopped", 2, -35.0)], rows=[row])
    assert brief.average_down_lines(p) == [
        "BMRI IDR 3,000,000 (-15.2% vs cost, average cost 4,244 → 4,180)",
        "TLKM unfunded (-8.0% vs cost): no budget: x",
        "3 of 3 held names are 5% or more below cost (1 not kept by a passing screen)"]
    text = "\n".join(pipeline.trade_lines([p]))
    assert "IDN to average down (2):\n  BMRI IDR 3,000,000" in text
    assert "IDN to buy (1, IDR 3.0m)" in text  # the average down is still a buy


def test_average_down_lines_nothing_held_or_nothing_underwater():
    from assist import brief, pipeline

    assert brief.average_down_lines(_down_payload([])) == []
    assert brief.average_down_lines({"market": "USA", "styles": []}) == []
    assert not any("average down" in x for x in pipeline.trade_lines([_down_payload([])]))
    p = _down_payload([_down_name("BBCA", "stopped", 1, -0.2)])
    assert brief.average_down_lines(p) == ["none: no held name is 5% or more below cost (1 held)"]
