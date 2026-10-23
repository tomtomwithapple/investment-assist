"""Phase B fan-in (F2): Indonesia's layers 2–4 wired into the stance and `assist run`.

Covers the stance side (override band hold, the gated rule view), layer 4's assembly (screen
edge net of round-trip cost, capacity drops, entry level), the rule verdicts built from the
journal, and a full run where every IDN store is missing (it must degrade, never fail). Fake
sources and fixtures only: nothing here reads a real store or reaches the network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from helpers import FIXTURES, make_sqlite
from test_run_e2e import FakeFred

from assist import cli, journal, pipeline
from assist import stance as st
from assist.candidates.costs import Cost
from assist.eval.placebo import Edge, Verdict
from assist.layers.bonds import IdnBonds
from assist.layers.candidates import IdnCandidates, ScreenSummary, assemble, idn_candidates
from assist.layers.overrides import IdnOverrides
from assist.layers.rules import FactorSnapshots, IdnStocks
from assist.layers.signals import IdnSignals
from assist.layers.types import AssetScore, Override, Regime, Weights, stance_validator
from assist.sources.base import SourceUnavailable
from assist.sources.financer import FinancerSource
from assist.sources.idxmethod_stocks import IdxMethodStocks
from assist.sources.worldbankscape import WorldbankscapeSource

DAY = date(2026, 10, 23)
BARS = date(2026, 10, 9)


def valid(payload: dict) -> dict:
    errors = list(stance_validator().iter_errors(payload))
    assert not errors, [e.message for e in errors]
    return payload


def score(value=58.0, asset="bonds") -> AssetScore:
    return AssetScore(subject="IDN", asset=asset, as_of=DAY, score=value, confidence=0.9)


def regime(state="neutral") -> Regime:
    return Regime(as_of=DAY, state=state, dollar="flat", sources=("sec-edgar",))


def weights(pct=8.0, key=("IDN", "bonds")) -> Weights:
    return Weights(as_of=DAY, weights={key: pct, ("IDN", "cash"): 100 - pct})


def verdict(passed: bool, reason: str | None = None) -> Verdict:
    e = Edge(12, 12, 0.02, 0.0, 0.02, 3.0 if passed else 0.5, True)
    return Verdict(passed, reason or ("beats placebo" if passed else "t-stat 0.50 below 2.0"),
                   e, e.t, 0.01 if passed else 0.4, 0.1, (0.1,), 1, 10, 2, 3, 3, 1, 2.0, 0.05)


# ---------------- stance: overrides and the rule view ----------------


def test_override_that_would_cross_a_band_is_held():
    ov = [Override("IDN", "bonds", DAY, 5.0, "CPI falling", ("bps-looker",))]
    out = valid(st.build_stance(score=score(57.0), regime=regime(), weights=weights(),
                                overrides=ov))
    assert out["score"] == 62.0  # the score carries the shift
    assert out["stance"] == "neutral"  # the band does not, until the overrides beat a placebo
    assert any("would move the stance to overweight" in d for d in out["drivers"])


def test_override_inside_the_band_needs_no_note():
    ov = [Override("IDN", "bonds", DAY, -2.0, "BI hiking", ("bisfetcher",))]
    out = st.build_stance(score=score(58.0), regime=regime(), weights=weights(), overrides=ov)
    assert out["stance"] == "neutral"
    assert not any("would move" in d for d in out["drivers"])


def test_base_stance_ignores_overrides_but_not_regime():
    assert st.base_stance(score(57.0), regime("risk_on")) == "overweight"
    assert st.base_stance(score(57.0), None) == "neutral"


def test_rule_view_without_a_stance_adds_context_only():
    rv = st.RuleView("IDN", "bonds", note="bonds rule: no call (no_call)", drivers=("real 3.7%",),
                     risks=("BI hiking",), watch=("candidate X",), stale_inputs=("p (missing)",),
                     sources=("dbnomics",))
    out = valid(st.build_stance(score=score(), regime=regime(), weights=weights(), rule=rv))
    assert out["stance"] == "neutral"
    assert "bonds rule: no call (no_call)" in out["drivers"] and "real 3.7%" in out["drivers"]
    assert out["risks"] == ["BI hiking"] and out["watch"] == ["candidate X"]
    assert "p (missing)" in out["stale_inputs"] and "dbnomics" in out["sources"]


def test_rule_view_with_a_passed_stance_replaces_the_band_and_uses_its_entry():
    ladder = {"style": "ladder", "tranches": 3, "spacing_days": 10}
    rv = st.RuleView("IDN", "bonds", note="applied", stance="overweight", entry=ladder)
    out = valid(st.build_stance(score=score(), regime=regime(), weights=weights(), rule=rv))
    assert out["stance"] == "overweight"
    assert out["entry"] == ladder
    assert out["portfolio"]["delta"] == "+5.0pt over 3 tranches"


def test_rule_view_for_another_key_raises():
    with pytest.raises(ValueError, match="rule is for"):
        st.build_stance(score=score(), regime=regime(), weights=weights(),
                        rule=st.RuleView("IDN", "stocks", note="x"))


# ---------------- layer 4: candidates ----------------


def cost(price=1000.0, rt=100.0, flags=()) -> Cost:
    half = (rt - 40.0) / 2  # fees 15 + 25 bps; the rest split as spread per side
    return Cost(price, 10000, price * 10000, 15.0, 25.0, half, 0.0, None, 0.01, tuple(flags))


def levels(typical=None, deep=800.0, status="wait"):
    return SimpleNamespace(entry_typical=typical, entry_deep=deep, status=status)


def screens(spread=0.0224, passed=True, names=("AAA", "BBB", "CCC", "DDD", "EEE")) -> dict:
    cands = [{"symbol": s, "score": 2.0 - i * 0.1, "sector": "Energy"}
             for i, s in enumerate(names)] if passed else []
    return {"as_of": BARS, "stale_inputs": [], "screens": {
        "momentum": {"passed": passed, "blocked": None if passed else "t 1.4 below 2.0",
                     "spread_mean": spread, "months": 48, "n_ranked": 65,
                     "verdict": {"passed": passed}, "candidates": cands},
        "dividend": {"passed": False, "blocked": "t-stat 1.42 below 2.0", "spread_mean": 0.0103,
                     "months": 48, "n_ranked": 65, "verdict": {"passed": False},
                     "candidates": []},
    }}


def plan() -> dict:
    return {
        "AAA": {"cost": cost(rt=90.0), "levels": levels(typical=900.0)},
        "BBB": {"cost": cost(rt=300.0, flags=("over_participation",)), "levels": levels()},
        "CCC": {"cost": cost(rt=260.0), "levels": levels()},  # 224bp edge − 260bp < 0
        "DDD": {"cost": None, "levels": None},
        "EEE": {"cost": cost(rt=120.0), "levels": None},
    }


def test_assemble_nets_cost_off_the_edge_and_drops_capacity_misses():
    out = assemble(screens(), plan(), order_idr=10e6)
    assert [c.symbol for c in out.candidates] == ["AAA", "EEE"]
    a, e = out.candidates
    assert a.entry_level == 900.0 and "entry typical 900" in a.detail
    assert "net edge +134bp/mo after 90bp round trip" in a.detail
    assert e.entry_level is None and "no entry levels" in e.detail
    assert a.as_of == BARS and a.subject == "IDN" and a.asset == "stocks"
    reasons = {sym: why for _, sym, why in out.dropped}
    assert reasons == {"BBB": "over_participation", "CCC": "round trip 260bp eats the edge",
                       "DDD": "no cost estimate"}
    mom = next(s for s in out.screens if s.name == "momentum")
    assert mom.passed and mom.n_named == 2 and mom.edge_bps == pytest.approx(224.0)


def test_entry_level_falls_back_to_the_deep_zone():
    p = {"AAA": {"cost": cost(rt=50.0), "levels": levels(typical=None, deep=777.0, status="deep")}}
    out = assemble(screens(names=("AAA",)), p)
    assert out.candidates[0].entry_level == 777.0
    assert "entry deep 777, deep" in out.candidates[0].detail


def test_blocked_screens_name_no_one_and_say_why():
    out = assemble(screens(passed=False), {})
    assert out.candidates == ()
    head = out.headline()
    assert "0 IDN stock candidate(s)" in head
    assert "dividend blocked (t-stat 1.42 below 2.0)" in head
    assert "Context only" in head


def test_watch_has_one_line_per_candidate():
    out = assemble(screens(), plan())
    assert out.watch()[0].startswith("candidate AAA (momentum): score 2.00")
    assert len(out.watch()) == 2
    assert "2 dropped" not in out.headline() and "3 dropped on cost or capacity" in out.headline()


def test_idn_candidates_prices_only_the_named_symbols():
    seen = {}

    def plan_fn(stocks, symbols, as_of, order_idr):
        seen.update(symbols=symbols, as_of=as_of, order_idr=order_idr)
        return plan(), ["idx-method dividends (missing)"]

    out = idn_candidates(DAY, stocks=object(), screens_fn=lambda s, d: screens(),
                         plan_fn=plan_fn)
    assert seen == {"symbols": ["AAA", "BBB", "CCC", "DDD", "EEE"], "as_of": DAY,
                    "order_idr": 10e6}
    assert "idx-method dividends (missing)" in out.stale_inputs


def test_idn_candidates_skips_pricing_when_no_screen_passes():
    def plan_fn(*a, **k):
        raise AssertionError("no candidates, nothing to price")

    out = idn_candidates(DAY, stocks=object(), screens_fn=lambda s, d: screens(passed=False),
                         plan_fn=plan_fn)
    assert out.candidates == ()


# ---------------- verdicts from the journal ----------------


def rule_rec(asset: str, day: date, call: str) -> dict:
    return {"kind": "rule", "subject": "IDN", "asset": asset, "as_of": day.isoformat(),
            "outputs": {"call": call}}


def test_journalled_calls_take_the_last_call_per_month_before_the_day():
    hist = [rule_rec("bonds", date(2026, 8, 3), "hold"), rule_rec("bonds", date(2026, 8, 28),
                                                                   "enter"),
            rule_rec("stocks", date(2026, 9, 1), "reduce"),
            rule_rec("bonds", DAY, "reduce"),  # today's own call never judges itself
            {"kind": "stance", "subject": "IDN", "asset": "bonds", "as_of": "2026-09-01"}]
    assert pipeline.journalled_calls(hist, "bonds", DAY) == {(2026, 8): "enter"}
    assert pipeline.journalled_calls(hist, "stocks", DAY) == {(2026, 9): "reduce"}


def test_journalled_verdict_is_insufficient_without_forward_returns():
    hist = [rule_rec("stocks", date(2026, 10, 1), "enter")]
    prices = [(date(2026, m, 28), 6000.0 + m) for m in range(1, 10)]  # JCI frozen at 2026-09
    v = pipeline.journalled_verdict(hist, "stocks", prices, DAY)
    assert not v.passed and "insufficient sample" in v.reason


def test_journalled_verdict_scores_calls_against_what_followed():
    # 40 months of calls: enter before rising months, reduce before falling ones
    months = [date(2022 + (m // 12), m % 12 + 1, 28) for m in range(40)]
    import random
    rng = random.Random(3)
    moves = [rng.choice((1, -1)) for _ in months]
    prices, level = [], 100.0
    for d, mv in zip(months, moves, strict=True):
        prices.append((d, level))
        level *= 1.03 if mv > 0 else 0.97
    hist = []
    for i, d in enumerate(months[:-3]):
        ahead = sum(moves[i:i + 3])
        hist.append(rule_rec("stocks", d, "enter" if ahead > 0 else "reduce"))
    v = pipeline.journalled_verdict(hist, "stocks", prices, DAY, horizon=3)
    assert v.rule.n_on + v.rule.n_off > 0 and v.rule.diff > 0


# ---------------- the rule view from IDN layers ----------------


def bonds_rule(call="enter", proposed="overweight") -> IdnBonds:
    entry = {"style": "lump", "tranches": 1, "spacing_days": 0}
    return IdnBonds(DAY, call, proposed, entry if call == "enter" else
                    {"style": "none", "tranches": 0, "spacing_days": 0}, (), 3.1, 82.0,
                    "120 months", 1.2, False, "idxscape_phei", "neutral",
                    ("real yield 3.1% (82nd pct)",), ("BI hiking",), (), ("idxscape_phei",))


def stocks_rule(call="no_call", proposed=None) -> IdnStocks:
    return IdnStocks(DAY, call, proposed, {"style": "none", "tranches": 0, "spacing_days": 0},
                     (), 6.0, 16.6, date(2026, 10, 12), -1.0, 3.7, 4.3, 6.2, 48.6, None,
                     "neutral", ("JCI earnings yield 6.02%",), (), ("idxscape_phei (missing)",),
                     ("idx-method",))


def idn_layers(bonds=None, stocks=None, verdicts=None, cands=None) -> pipeline.IdnLayers:
    ov = IdnOverrides(DAY, (), (), {}, {})
    cands = cands or assemble(screens(), plan())
    return pipeline.IdnLayers(ov, IdnSignals(DAY, ()), bonds or bonds_rule(),
                              stocks or stocks_rule(), cands, verdicts or {})


def layers_with(idn: pipeline.IdnLayers) -> pipeline.Layers:
    return pipeline.Layers(DAY, None, regime(), weights(), idn=idn)


def test_rule_view_keeps_the_band_when_the_verdict_fails():
    lay = layers_with(idn_layers(verdicts={"bonds": verdict(False)}))
    rv = pipeline.rule_view(score(), lay)
    assert rv.stance is None and rv.entry is None
    assert rv.note.startswith("bonds rule proposes overweight; not applied: t-stat 0.50")
    assert "verdict on its journalled calls: not passed" in rv.note
    assert "real yield 3.1% (82nd pct)" in rv.drivers


def test_rule_view_applies_the_proposal_when_the_verdict_passes():
    lay = layers_with(idn_layers(verdicts={"bonds": verdict(True)}))
    rv = pipeline.rule_view(score(), lay)
    assert rv.stance == "overweight" and rv.entry["style"] == "lump"
    out = valid(st.build_stance(score=score(), regime=regime(), weights=weights(), rule=rv))
    assert out["stance"] == "overweight" and out["entry"]["style"] == "lump"


def test_stocks_rule_view_carries_the_candidates():
    rv = pipeline.rule_view(score(53.6, "stocks"), layers_with(idn_layers()))
    assert rv.note == "stocks rule: no call (no_call)"
    assert any(d.startswith("layer 4: 2 IDN stock candidate(s)") for d in rv.drivers)
    assert [w.split(" (")[0] for w in rv.watch] == ["candidate AAA", "candidate EEE"]
    assert "idx-method" in rv.sources


def test_no_rule_view_outside_the_idn_rules():
    lay = layers_with(idn_layers())
    assert pipeline.rule_view(score(52.5, "currency"), lay) is None
    usa = AssetScore(subject="USA", asset="bonds", as_of=DAY, score=50.0, confidence=0.9)
    assert pipeline.rule_view(usa, lay) is None
    assert pipeline.rule_view(score(), pipeline.Layers(DAY, None, regime(), None)) is None


# ---------------- a full run with every IDN store missing ----------------


class Missing:
    """A store that is not there."""

    def __init__(self, name: str):
        self.name = name

    def rows(self, *a, **k):
        raise SourceUnavailable(self.name, "missing")


def missing_idn(tmp_path: Path) -> pipeline.IdnSources:
    nowhere = tmp_path / "nowhere"
    return pipeline.IdnSources(
        bps=Missing("bps-looker"), bisfetcher=Missing("bisfetcher"),
        dbnomics=Missing("dbnomics"), satudatascape=Missing("satudatascape"),
        idxscape=Missing("idxscape"), kseistat=Missing("kseistat"), tic=Missing("sec-edgar"),
        phei=Missing("idxscape_phei"), idxmethod=Missing("idx-method"),
        snapshots=FactorSnapshots(nowhere), stocks=IdxMethodStocks(nowhere))


@pytest.fixture
def sources(tmp_path: Path) -> pipeline.Sources:
    root = FIXTURES / "worldbankscape"
    fix = FIXTURES / "financer"
    ddl = (fix / "schema.sql").read_text() + (fix / "seed.sql").read_text()
    return pipeline.Sources(worldbankscape=WorldbankscapeSource(root / "out", root / "schema"),
                            fred=FakeFred(),
                            financer=FinancerSource(make_sqlite(tmp_path / "f.db", ddl)),
                            idn=missing_idn(tmp_path))


def _out_bytes(out: Path) -> dict[str, bytes]:
    return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob("*.json"))}


def test_run_with_idn_stores_missing_degrades_to_no_call(tmp_path, sources):
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert res.ok and res.idn is not None
    assert res.idn.bonds.call == "no_call" and res.idn.stocks.call == "no_call"
    assert res.idn.candidates.candidates == ()
    for asset in ("bonds", "stocks"):
        p = valid(json.loads((paths.out / "IDN" / f"{asset}.json").read_text()))
        assert p["stance"] == "neutral"
        assert f"{asset} rule: no call (no_call)" in p["drivers"]
        assert "idxscape_phei (missing)" in p["stale_inputs"]
        assert "bisfetcher (missing)" in p["stale_inputs"]  # via the overrides
    stocks = json.loads((paths.out / "IDN" / "stocks.json").read_text())
    assert any(d.startswith("layer 4: 0 IDN stock candidate(s)") for d in stocks["drivers"])
    assert stocks["watch"] == []
    assert "idxscape_phei (missing)" in res.stale_inputs

    j = journal.Journal(paths.journal)
    recs = list(j.read())
    rules = [r for r in recs if r["kind"] == "rule"]
    assert [(r["asset"], r["outputs"]["call"]) for r in rules] == [("bonds", "no_call"),
                                                                    ("stocks", "no_call")]
    assert all("insufficient sample" in r["outputs"]["verdict"]["reason"] for r in rules)
    assert sum(r["kind"] == "candidates" for r in recs) == 1
    assert j.verify() == len(recs)


def test_rerun_is_byte_identical_with_the_idn_layers(tmp_path, sources):
    paths = pipeline.Paths.under(tmp_path / "repo")
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    before = _out_bytes(paths.out)
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert _out_bytes(paths.out) == before


def test_cli_run_prints_the_idn_rules_and_candidates(tmp_path, sources, monkeypatch, capsys):
    paths = pipeline.Paths.under(tmp_path / "repo")
    monkeypatch.setattr(pipeline.Sources, "default", classmethod(lambda cls: sources))
    monkeypatch.setattr(pipeline.Paths, "default", classmethod(lambda cls: paths))
    assert cli.main(["run", "--today", DAY.isoformat(), "--no-send"]) == 0
    out = capsys.readouterr().out
    assert "IDN bonds: neutral" in out and "IDN stocks: neutral" in out
    assert "bonds rule: no_call, proposes None; verdict: insufficient sample" in out
    assert "layer 4: 0 IDN stock candidate(s)" in out


def test_idn_candidates_type_is_journalable():
    c = IdnCandidates(BARS, 10e6, (), (ScreenSummary("m", False, "x", None, 0, 0, 0, {}),), ())
    assert journal.canonical(c)
