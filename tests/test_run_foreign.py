"""Phase C fan-in (F3): foreign subjects' layers 2 and 4 wired into the stance and `assist run`.

P28's foreign overrides shift the USA, JPN, AUS, SGP and euro-member scores (DEU, FRA, ITA, ESP and
NLD read the `EMU` market) but may not cross a band before they beat a placebo; KOR and TWN have
none and keep their layer-1 score. P29's index-level candidates reach the foreign stocks stances
as drivers and watch lines only. Every foreign stance names its IDR edge, hedged against
unhedged. Fake sources only: nothing here reads a real store or reaches the network."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from helpers import FIXTURES, make_sqlite
from test_run_e2e import FakeFred
from test_run_idn import Missing, missing_idn

from assist import cli, journal, pipeline
from assist import stance as st
from assist.layers.candidates_foreign import ForeignCandidates, assess, market
from assist.layers.overrides_foreign import ForeignOverrides, IdrTerms, MarketOverrides
from assist.layers.types import AssetScore, Override, Regime, Weights, stance_validator
from assist.sources.base import Row, SourceUnavailable
from assist.sources.financer import FinancerSource
from assist.sources.worldbankscape import Layer1

DAY = date(2026, 10, 23)


def valid(payload: dict) -> dict:
    errors = list(stance_validator().iter_errors(payload))
    assert not errors, [e.message for e in errors]
    return payload


def score(subject: str, asset: str, value: float = 55.0) -> AssetScore:
    return AssetScore(subject=subject, asset=asset, as_of=DAY, score=value, confidence=0.9)


def regime() -> Regime:
    return Regime(as_of=DAY, state="neutral", dollar="flat", sources=("sec-edgar",))


def weights() -> Weights:
    return Weights(as_of=DAY, weights={("IDN", "stocks"): 60.0, ("IDN", "cash"): 40.0})


# ---------------- hand-built layers ----------------


def market_overrides(subject: str, deltas: dict[str, float], carry: float = 0.0181
                     ) -> MarketOverrides:
    ovs = tuple(Override(subject, a, DAY, d, f"{subject} momentum ({a})", ("dbnomics",))
                for a, d in deltas.items())
    idr = IdrTerms("USD" if subject == "USA" else "EUR", 18052.0, date(2026, 10, 16), 0.001,
                   0.089, carry)
    return MarketOverrides(subject, DAY, ovs, (), dict(deltas), idr, (), ("dbnomics",))


def usa_valuation(edge_rich: bool = True):
    """The live P29 shape: S&P 500 CAPE EY 2.46%, far below its hurdle, IDR test survives
    hedged. `edge_rich=False` makes it cheap (a big score) to prove it still moves nothing."""
    ey = 1 / 40.71 if edge_rich else 0.20
    return assess(market("USA"), DAY, earnings_yield=ey, basis="CAPE", yield_10y=0.0499,
                  us_erp=0.037, crp=0.0023, inflation=0.0374, r_idr=0.0701, fx_move=-0.0074,
                  fx_basis="adverse 1y move", i_idr=0.0575, i_local=0.03875,
                  sources=("dbnomics", "idxscape", "bisfetcher"))


def foreign_layers(deltas_usa=None, deltas_emu=None, valuation=None) -> pipeline.ForeignLayers:
    fo = ForeignOverrides(DAY, (
        market_overrides("USA", deltas_usa or {"stocks": 3.0, "bonds": -4.0, "currency": 3.0}),
        market_overrides("EMU", deltas_emu or {"stocks": 2.0, "bonds": -9.0, "currency": -1.0}),
    ))
    fc = ForeignCandidates(DAY, (valuation or usa_valuation(),),
                           ("JPN stocks valuation: no source (jquantster would add it)",),
                           ("dbnomics",))
    edges = pipeline.idr_edges_from(fc, {})
    return pipeline.ForeignLayers(fo, fc, edges)


def layers_with(foreign: pipeline.ForeignLayers, scores: list[AssetScore]) -> pipeline.Layers:
    layer1 = Layer1(scores, [], {}, ["worldbankscape"], "x", "2026-10-23")
    return pipeline.Layers(DAY, layer1, regime(), weights(),
                           overrides=pipeline.foreign_override_rows(foreign),
                           foreign=foreign)


def stance_of(lay: pipeline.Layers, subject: str, asset: str) -> dict:
    out = {(p["subject"], p["asset"]): p for p in pipeline.build(lay, st.model_fingerprint())}
    return valid(out[(subject, asset)])


# ---------------- overrides ----------------


def test_euro_members_get_the_emu_override_under_their_own_subject():
    rows = pipeline.foreign_override_rows(foreign_layers())
    keyed = {(o.subject, o.asset): o.delta for o in rows}
    for member in ("DEU", "FRA", "ITA", "ESP", "NLD"):
        assert keyed[(member, "bonds")] == -9.0
    assert keyed[("USA", "stocks")] == 3.0
    assert not any(o.subject in ("EMU", "KOR", "TWN") for o in rows)


def test_foreign_override_moves_the_score_but_not_the_band():
    fl = foreign_layers(deltas_usa={"stocks": 8.0, "bonds": -4.0, "currency": 0.0})
    p = stance_of(layers_with(fl, [score("USA", "stocks", 55.0)]), "USA", "stocks")
    assert p["score"] == 63.0 and p["stance"] == "neutral"
    assert any("would move the stance to overweight" in d for d in p["drivers"])
    assert any(d.startswith("USA momentum (stocks)") for d in p["drivers"])


def test_euro_member_bonds_carry_the_emu_shift():
    p = stance_of(layers_with(foreign_layers(), [score("DEU", "bonds", 45.0)]), "DEU", "bonds")
    assert p["score"] == 36.0 and p["stance"] == "neutral"  # held: 36 would be underweight
    assert any("would move the stance to underweight" in d for d in p["drivers"])


@pytest.mark.parametrize("subject", ["KOR", "TWN"])
def test_korea_and_taiwan_keep_their_layer1_score_and_say_so(subject):
    p = stance_of(layers_with(foreign_layers(), [score(subject, "bonds", 47.0)]), subject,
                  "bonds")
    assert p["score"] == 47.0 == p["layer1_score"]
    assert any(d.startswith(f"no layer-2 overrides for {subject}") for d in p["drivers"])


# ---------------- layer 4 and the IDR edge ----------------


def test_usa_stocks_carry_the_index_candidate_as_context_only():
    p = stance_of(layers_with(foreign_layers(), [score("USA", "stocks", 55.0)]), "USA", "stocks")
    assert p["stance"] == "neutral"
    assert any(d.startswith("layer 4 (index level): S&P 500 score 17.7") for d in p["drivers"])
    assert any("does not pass" in d and "Context only" in d for d in p["drivers"])
    assert len(p["watch"]) == 1 and p["watch"][0].startswith("candidate SPX (index_valuation)")


def test_a_passing_candidate_still_moves_no_stance():
    fl = foreign_layers(valuation=usa_valuation(edge_rich=False))
    assert fl.candidates.valuations[0].passes and fl.candidates.valuations[0].score == 100.0
    p = stance_of(layers_with(fl, [score("USA", "stocks", 55.0)]), "USA", "stocks")
    assert p["stance"] == "neutral" and p["score"] == 58.0  # layer 1 + override +3 only


def test_stocks_without_an_index_valuation_say_why():
    p = stance_of(layers_with(foreign_layers(), [score("JPN", "stocks")]), "JPN", "stocks")
    assert any(d.startswith("layer 4 (index level): no TOPIX candidate") for d in p["drivers"])
    assert "JPN stocks valuation: no source (jquantster would add it)" in p["stale_inputs"]
    assert p["watch"] == []


def test_usa_stocks_idr_edge_names_hedged_and_unhedged():
    p = stance_of(layers_with(foreign_layers(), [score("USA", "stocks")]), "USA", "stocks")
    edge = [d for d in p["drivers"] if d.startswith("IDR edge, stocks")]
    assert len(edge) == 1
    assert "unhedged +5.41%" in edge[0] and "hedged +8.11%" in edge[0]
    assert "survives hedged" in edge[0]
    assert p["risks"] == list(st.LEG_RISKS[("USA", "stocks")])  # S39: estate tax


def test_an_edge_that_does_not_survive_is_a_risk_not_a_stance_change():
    fl = foreign_layers()
    fx = fl.edges[("USA", "stocks")].fx
    lost = pipeline.IdrEdge("USA", "bonds", "USD 10Y", type(fx)(0.04, 0.07, -0.01, 0.0296,
                                                                  None, 0.0, 1.0))
    fl.edges[("USA", "bonds")] = lost
    p = stance_of(layers_with(fl, [score("USA", "bonds", 65.0)]), "USA", "bonds")
    assert p["stance"] == "overweight"
    assert any(r.startswith("IDR edge -4.04% does not survive") for r in p["risks"])


def test_every_foreign_stance_states_its_idr_edge():
    subjects = [s for s in pipeline.COUNTRIES if s != "IDN"]
    scores = [score(s, a) for s in subjects for a in pipeline.FOREIGN_ASSETS]
    lay = layers_with(foreign_layers(), scores)
    for p in pipeline.build(lay, st.model_fingerprint()):
        valid(p)
        assert any(d.startswith(f"IDR edge, {p['asset']}") for d in p["drivers"]), p["subject"]


def test_euro_member_edge_is_na_but_shows_the_idr_terms():
    p = stance_of(layers_with(foreign_layers(), [score("FRA", "currency")]), "FRA", "currency")
    edge = next(d for d in p["drivers"] if d.startswith("IDR edge, currency"))
    assert "n/a" in edge and "hedge carry +1.81%/y" in edge


def test_no_foreign_view_without_foreign_layers():
    lay = pipeline.Layers(DAY, None, regime(), weights())
    assert pipeline.rule_view(score("USA", "bonds"), lay) is None


# ---------------- bonds and currency edges from the stores ----------------


class Fake:
    """A store holding rows in memory; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, rows or [], error

    def rows(self, series_ids=None, start=None, end=None, **kw):
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted((r for r in self._rows
                       if (series_ids is None or r.series_id in series_ids)
                       and (start is None or r.date >= start) and (end is None or r.date <= end)),
                      key=lambda r: (r.series_id, r.date))


def _months(end: date, n: int) -> list[date]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def monthly(sid: str, value: float, source: str, end=date(2026, 9, 1), as_of=None) -> list[Row]:
    return [Row(sid, d, value, as_of, source) for d in _months(end, 3)]


def flat_daily(sid: str, value: float, source: str, years: float = 3.0) -> list[Row]:
    out, d, end = [], DAY - timedelta(days=int(365 * years)), date(2026, 10, 20)
    while d <= end:
        if d.weekday() < 5:
            out.append(Row(sid, d, value, d, source))
        d += timedelta(days=1)
    return out


def us_world() -> dict[str, Fake]:
    """US 10Y 5%, IDN 10Y 7% (PHEI), BI 5.75% vs Fed 4%, JISDOR flat for 3 years."""
    rows = {
        "dbnomics": monthly("usa.rate.long", 5.0, "dbnomics"),
        "idxscape": flat_daily("JISDOR", 18000.0, "idxscape"),
        "idxscape_phei": [Row("IGSYC.10", date(2026, 10, 20), 7.0, date(2026, 10, 20),
                              "idxscape_phei")],
        "bisfetcher": [*monthly("WS_CBPOL.M.ID", 5.75, "bisfetcher", as_of=date(2026, 10, 14)),
                       *monthly("WS_CBPOL.M.US", 4.0, "bisfetcher", as_of=date(2026, 10, 14))],
    }
    return {name: Fake(name, r) for name, r in rows.items()}


def test_bonds_and_currency_edges_from_the_stores():
    fc = ForeignCandidates(DAY, ())
    edges = pipeline.idr_edges_from(fc, us_world(), DAY)
    bonds = edges[("USA", "bonds")]
    assert bonds.fx is not None
    assert bonds.fx.unhedged == pytest.approx(0.05)  # flat FX, adverse move 0
    prem = 1.0575 / 1.04 - 1
    assert bonds.fx.hedged == pytest.approx(1.05 * (1 + prem) - 1)
    assert bonds.fx.r_idr == pytest.approx(0.07)
    assert "does not survive" in bonds.line()  # 5% + carry < 7% IDN 10Y
    cur = edges[("USA", "currency")]
    assert cur.fx.unhedged == pytest.approx(0.04) and cur.fx.r_idr == pytest.approx(0.0575)
    assert cur.fx.hedged is None  # hedged USD cash earns the BI rate exactly: no edge to show
    assert "hedged it earns the BI rate" in cur.line() and "does not survive" in cur.line()
    jpn = edges[("JPN", "bonds")]
    assert jpn.fx is None and "n/a" in jpn.line()


def test_unavailable_stores_give_na_edges_not_a_crash():
    world = {n: Fake(n, error="missing") for n in ("dbnomics", "idxscape", "bisfetcher")}
    edges = pipeline.idr_edges_from(ForeignCandidates(DAY, ()), world, DAY)
    assert all(e.fx is None for e in edges.values())
    assert "n/a" in edges[("USA", "bonds")].line()


# ---------------- a full run ----------------


class Wbs:
    """worldbankscape stand-in: one IDN and every foreign country × asset at 50."""

    name = "worldbankscape"

    def load(self) -> Layer1:
        subjects = pipeline.COUNTRIES
        scores = [score(s, a, 50.0) for s in subjects for a in ("stocks", "bonds", "currency")]
        return Layer1(scores, [], {}, ["worldbankscape"], "x", "2026-10-23")


def missing_foreign() -> pipeline.ForeignSources:
    names = ("fred", "tic", "dbnomics", "bisfetcher", "jquantster", "ausdata", "singstat",
             "usdidr")
    cand = ("dbnomics", "idxscape", "idxscape_phei", "bisfetcher", "jquantster", "ausdata",
            "singstat", "openkrx")
    return pipeline.ForeignSources(overrides={n: Missing(n) for n in names},
                                   candidates={n: Missing(n) for n in cand})


@pytest.fixture
def sources(tmp_path: Path) -> pipeline.Sources:
    fix = FIXTURES / "financer"
    ddl = (fix / "schema.sql").read_text() + (fix / "seed.sql").read_text()
    return pipeline.Sources(worldbankscape=Wbs(), fred=FakeFred(),
                            financer=FinancerSource(make_sqlite(tmp_path / "f.db", ddl)),
                            idn=missing_idn(tmp_path), foreign=missing_foreign())


def _out_bytes(out: Path) -> dict[str, bytes]:
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*.json"))}


def test_run_with_foreign_stores_missing_degrades(tmp_path, sources):
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert res.ok and res.foreign is not None
    foreign = [p for p in res.stances if p["subject"] != "IDN"]
    assert len(foreign) == 11 * 3
    for p in foreign:
        valid(p)
        assert p["stance"] == "neutral" and p["score"] == 50.0
        assert any(d.startswith(f"IDR edge, {p['asset']}") for d in p["drivers"])
    assert "bisfetcher (missing)" in res.stale_inputs

    recs = list(journal.Journal(paths.journal).read())
    ov = [r for r in recs if r["kind"] == "overrides"]
    # P77: IDN journals its own overrides record first; every record carries the live monitor's
    # fields (override fingerprint, completeness, the CLI's direction)
    assert [r["subject"] for r in ov] == ["IDN", "USA", "JPN", "EMU", "AUS", "SGP"]
    assert all(r["outputs"]["override_fingerprint"].startswith("sha256:")
               and r["outputs"]["complete"] is False for r in ov)
    emu = ov[3]["outputs"]
    assert set(emu["stances"]) == {f"{m}/{a}" for m in ("DEU", "FRA", "ITA", "ESP", "NLD")
                                   for a in ("stocks", "bonds", "currency")}
    assert all(v["held"] is False for v in emu["stances"].values())
    cands = [r for r in recs if r["kind"] == "candidates" and r["subject"] != "IDN"]
    assert [r["subject"] for r in cands] == ["USA", "JPN", "AUS", "SGP", "KOR", "TWN"]
    assert all(r["outputs"]["valuation"] is None and r["outputs"]["moves_stance"] is False
               for r in cands)
    assert sum(r["kind"] == "idr_edges" for r in recs) == 1
    assert journal.Journal(paths.journal).verify() == len(recs)


def test_rerun_is_byte_identical_with_the_foreign_layers(tmp_path, sources):
    paths = pipeline.Paths.under(tmp_path / "repo")
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    before = _out_bytes(paths.out)
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert _out_bytes(paths.out) == before


def test_cli_run_prints_the_foreign_layers(tmp_path, sources, monkeypatch, capsys):
    paths = pipeline.Paths.under(tmp_path / "repo")
    monkeypatch.setattr(pipeline.Sources, "default", classmethod(lambda cls: sources))
    monkeypatch.setattr(pipeline.Paths, "default", classmethod(lambda cls: paths))
    assert cli.main(["run", "--today", DAY.isoformat(), "--no-send"]) == 0
    out = capsys.readouterr().out
    assert "foreign overrides USA: stocks +0, bonds +0, currency +0" in out
    assert "foreign layer 4: 0 index candidate(s)" in out
    assert "KOR, TWN: no layer-2 overrides" in out


def test_foreign_layers_are_journalable():
    assert journal.canonical(foreign_layers())
    assert json.loads(journal.canonical(foreign_layers().edges))
