"""P54 (PLAN S33): `assist run` writes each layer's structured result to `out/layers/`.

`out/layers/regime.json` (layer 0 with every input, its vote and a 1-year weekly line),
`out/layers/<SUBJECT>.json` (layers 2-3, plus IDN's chart windows) and
`out/layers/portfolio.json` (layer 5 and each stance's current/target/delta). Each file carries
as_of, schema_version, the model fingerprint, sources, stale inputs and the disclaimer, and is
valid against `schema/layers/`. A layer that fails is a stale input in its file, never a failed
run, and the stances and brief stay byte-identical. Fixture stores and fakes only."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES, make_sqlite
from test_run_e2e import FakeFred
from test_run_foreign import Wbs, missing_foreign
from test_run_idn import missing_idn

from assist import journal, layers_out, pipeline
from assist.layers import regime as rg
from assist.layers.overrides import Component, IdnOverrides
from assist.layers.signals import IdnSignals
from assist.layers.types import DISCLAIMER, Override, Signal
from assist.sources.base import Row, SourceUnavailable
from assist.sources.financer import FinancerSource
from assist.sources.idxmethod import IdxMethodIndexSource, JciSource
from assist.sources.idxscape import IdxscapeSource
from assist.sources.idxscape_phei import PheiSource
from assist.sources.worldbankscape import WorldbankscapeSource

DAY = date(2026, 10, 23)
FP = "sha256:" + "a" * 64


class HistoryFred:
    """Two years of FRED lines for every layer-0 series: VIX climbs 0.02 a day to 22.6 on DAY,
    HY OAS flat, the broad dollar up 4% over the last 13 weeks (dollar up, one risk-off point),
    real yield 1.5, NFCI -0.6 (one risk-on point); the candidates are flat."""

    name = "sec-edgar"

    def __init__(self):
        self.calls: list[dict] = []

    def level(self, sid: str, d: date) -> float:
        age = (DAY - d).days
        if sid == "VIXCLS":
            return round(22.6 - 0.02 * age, 4)
        if sid == "DTWEXBGS":
            return 104.0 if age < 7 else 100.0
        return {"BAMLH0A0HYM2": 3.0, "DFII10": 1.5, "NFCI": -0.6, "WALCL": 7e6,
                "WTREGEN": 8e5, "RRPONTSYD": 100.0}.get(sid, 1.0)

    def rows(self, series_ids=None, start=None, end=None, as_of=None):
        self.calls.append({"ids": list(series_ids or []), "start": start, "end": end,
                           "as_of": as_of})
        out = []
        for sid in series_ids or []:
            for i in range(730):
                d = DAY - timedelta(days=i)
                if (start is None or d >= start) and (end is None or d <= end):
                    out.append(Row(sid, d, self.level(sid, d), d, self.name))
        return sorted(out, key=lambda r: (r.series_id, r.date))


def _store(tmp_path: Path) -> Path:
    """One idxscape store with the flows, PHEI and index fixtures and P54's extra rows."""
    path = tmp_path / "idxscape.duckdb"
    con = duckdb.connect(str(path))
    try:
        for f in ("idxscape_flows/schema.sql", "idxscape_flows/data.sql",
                  "idxscape_phei/schema.sql", "idxscape_phei/data.sql",
                  "idxscape/index_daily.sql", "layers/extra.sql"):
            con.execute((FIXTURES / f).read_text())
    finally:
        con.close()
    return path


def _financer(tmp_path: Path) -> FinancerSource:
    fix = FIXTURES / "financer"
    ddl = (fix / "schema.sql").read_text() + (fix / "seed.sql").read_text()
    return FinancerSource(make_sqlite(tmp_path / "financer.db", ddl))


def _idn(tmp_path: Path, store: Path | None = None) -> pipeline.IdnSources:
    src = missing_idn(tmp_path)
    if store is not None:
        src.idxscape = IdxscapeSource(store)
        src.phei = PheiSource(store)
        src.idxmethod = JciSource(IdxscapeSource(store), IdxMethodIndexSource(tmp_path / "no"))
    return src


def _sources(tmp_path: Path, *, layers_out: bool = True, store: bool = True,
             fred=None, financer=None, foreign: bool = False) -> pipeline.Sources:
    root = FIXTURES / "worldbankscape"
    wbs = Wbs() if foreign else WorldbankscapeSource(root / "out", root / "schema")
    return pipeline.Sources(
        worldbankscape=wbs, fred=fred or HistoryFred(),
        financer=financer or _financer(tmp_path),
        idn=_idn(tmp_path, _store(tmp_path) if store else None),
        foreign=missing_foreign() if foreign else None, layers_out=layers_out)


def _read(out: Path, name: str) -> dict:
    return json.loads((out / "layers" / f"{name}.json").read_text())


def _valid(kind: str, payload: dict) -> dict:
    errors = list(layers_out.validator(kind).iter_errors(payload))
    assert not errors, [f"{list(e.absolute_path)}: {e.message}" for e in errors]
    return payload


def _common(p: dict, fp: str) -> None:
    assert p["as_of"] == DAY.isoformat()
    assert p["schema_version"] == layers_out.SCHEMA_VERSION
    assert p["model_fingerprint"] == fp
    assert p["disclaimer"] == DISCLAIMER
    assert isinstance(p["sources"], list) and isinstance(p["stale_inputs"], list)


@pytest.fixture
def run(tmp_path):
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=_sources(tmp_path), send=False)
    assert res.ok
    return res, paths


# ---------------- the run writes three kinds of file ----------------


def test_run_writes_regime_subject_and_portfolio_files(run):
    res, paths = run
    names = sorted(p.name for p in (paths.out / "layers").glob("*.json"))
    assert names == ["IDN.json", "portfolio.json", "regime.json"]
    assert [p.name for p in res.layer_files] == ["regime.json", "IDN.json", "portfolio.json"]
    fp = journal.model_fingerprint()
    _common(_valid("regime", _read(paths.out, "regime")), fp)
    _common(_valid("subject", _read(paths.out, "IDN")), fp)
    _common(_valid("portfolio", _read(paths.out, "portfolio")), fp)


def test_layer_files_are_off_unless_asked(tmp_path):
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=_sources(tmp_path, layers_out=False),
                       send=False)
    assert res.ok and res.layer_files == []
    assert not (paths.out / "layers").exists()


def test_default_sources_turn_layer_files_on():
    assert pipeline.Sources(worldbankscape=None, fred=None, financer=None).layers_out is False
    import inspect

    assert "layers_out=True" in inspect.getsource(pipeline.Sources.default)


def test_stances_brief_and_journal_kinds_unchanged_by_layer_files(tmp_path):
    def one(sub: str, on: bool):
        paths = pipeline.Paths.under(tmp_path / sub)
        sources = _sources(tmp_path / sub, layers_out=on)
        res = pipeline.run(DAY, paths=paths, sources=sources, send=False)
        stances = {p.relative_to(paths.out).as_posix(): p.read_bytes()
                    for p in sorted(paths.out.glob("[A-Z]*/*.json"))}
        kinds = [r["kind"] for r in journal.Journal(paths.journal).read()]
        return stances, res.brief_path.read_bytes(), kinds

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert one("a", False) == one("b", True)


def test_rerun_same_day_is_byte_identical(tmp_path):
    paths = pipeline.Paths.under(tmp_path / "repo")
    sources = _sources(tmp_path)
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    before = {p.name: p.read_bytes() for p in (paths.out / "layers").glob("*.json")}
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    after = {p.name: p.read_bytes() for p in (paths.out / "layers").glob("*.json")}
    assert before == after


def test_old_subject_files_are_removed(tmp_path):
    paths = pipeline.Paths.under(tmp_path / "repo")
    old = paths.out / "layers" / "XYZ.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}")
    keep = paths.out / "layers" / "notes.txt"
    keep.write_text("not ours")
    pipeline.run(DAY, paths=paths, sources=_sources(tmp_path), send=False)
    assert not old.exists() and keep.exists()


# ---------------- layer 0 ----------------


def test_regime_file_has_every_input_with_value_date_vote_and_history(run):
    res, paths = run
    p = _read(paths.out, "regime")
    assert (p["state"], p["dollar"]) == (res.regime.state, res.regime.dollar)
    assert p["drivers"] == list(res.regime.drivers)
    by = {i["feature"]: i for i in p["inputs"]}
    assert set(by) == set(rg.ALL_FEATURES)
    vix = by["vix"]
    assert vix["series_id"] == "VIXCLS" and vix["counted"] is True
    assert vix["value"] == pytest.approx(22.6) and vix["last"] == DAY.isoformat()
    assert (vix["vote"], vix["direction"]) == (0, "neutral")
    usd = by["usd_d13w"]
    assert usd["value"] == pytest.approx(4.0)
    assert (usd["vote"], usd["direction"]) == (1, "risk_off")
    assert (by["nfci"]["vote"], by["nfci"]["direction"]) == (-1, "risk_on")
    assert by["net_liquidity_d13w"]["counted"] is False  # a candidate, not adopted
    assert p["points"] == {"off": 1, "on": 1, "net": 0}
    assert p["state"] == "neutral" and p["dollar"] == "up"
    hist = vix["history"]
    assert 52 <= len(hist) <= 53
    days = [date.fromisoformat(h["date"]) for h in hist]
    assert all(d.weekday() == 4 for d in days) and days == sorted(days)
    assert days[-1] <= DAY and days[0] >= DAY - timedelta(days=366)
    assert hist[-1]["series_value"] == pytest.approx(22.6 - 0.02 * (DAY - days[-1]).days)
    assert hist[-1]["value"] == hist[-1]["series_value"]  # a level input
    # a 13-week change has its own line next to the level it is computed from
    assert days[-1] == DAY  # a Friday
    assert by["usd_d13w"]["history"][-1]["series_value"] == pytest.approx(104.0)
    assert by["usd_d13w"]["history"][-1]["value"] == pytest.approx(4.0)
    assert by["usd_d13w"]["history"][0]["value"] == pytest.approx(0.0)


def test_regime_history_read_uses_run_day_vintage(tmp_path):
    fred = HistoryFred()
    paths = pipeline.Paths.under(tmp_path / "repo")
    pipeline.run(DAY, paths=paths, sources=_sources(tmp_path, fred=fred), send=False)
    hist = [c for c in fred.calls if c["start"] and c["start"] < DAY - timedelta(days=365)]
    assert hist and all(c["as_of"] == DAY and c["end"] == DAY for c in hist)


def test_regime_store_down_is_stale_and_run_ok(tmp_path):
    fred = FakeFred(error=SourceUnavailable("sec-edgar", "locked", "held"))
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=_sources(tmp_path, fred=fred), send=False)
    assert res.ok
    p = _valid("regime", _read(paths.out, "regime"))
    assert "sec-edgar (locked)" in p["stale_inputs"]
    assert all(i["value"] is None and i["direction"] == "missing" for i in p["inputs"])
    assert all(i["history"] == [] for i in p["inputs"])


# ---------------- layers 2-3 ----------------


def test_idn_file_has_components_shifts_and_signals():
    row = Row("WS_CBPOL.M.ID", date(2026, 9, 1), 5.75, None, "bisfetcher")
    comp = Component("bi_rate", "bisfetcher", "WS_CBPOL.M.ID", 1.0, 1, row, "BI rate 5.75%")
    ov = IdnOverrides(DAY, (Override("IDN", "stocks", DAY, -10.0, "why", ("bisfetcher",)),
                            Override("IDN", "bonds", DAY, -3.0, "why", ("bisfetcher",))),
                      (comp,), {"stocks": -12.0, "bonds": -3.0}, {"bi_rate": row},
                      ("bps-looker (missing)",), ("bisfetcher",))
    sig = IdnSignals(DAY, (Signal("IDN", "stocks", DAY, "idx_foreign_flow", -1.6e13, -1,
                                  "idxscape", "IDR -16.09T over 20 IDX days"),),
                     ("kseistat (missing)",), ("idxscape",))
    p = layers_out.subject_payload("IDN", DAY, FP, overrides=ov, signals=sig)
    _valid("subject", p)
    c = p["layer2"]["components"][0]
    assert c == {"name": "bi_rate", "source": "bisfetcher", "series_id": "WS_CBPOL.M.ID",
                 "value": 1.0, "direction": 1, "last": {"date": "2026-09-01", "value": 5.75},
                 "detail": "BI rate 5.75%",
                 "weights": {"stocks": -2, "bonds": -3, "currency": 1}}
    stocks = next(a for a in p["layer2"]["assets"] if a["asset"] == "stocks")
    assert stocks == {"asset": "stocks", "shift": -10.0, "raw": -12.0, "cap": 10.0,
                      "capped": True, "reason": "why"}
    assert p["layer3"]["signals"] == [{
        "asset": "stocks", "name": "idx_foreign_flow", "value": -1.6e13, "direction": -1,
        "source": "idxscape", "detail": "IDR -16.09T over 20 IDX days"}]
    assert p["layer3"]["tally"] == {"stocks": -1, "bonds": 0}
    assert p["stale_inputs"] == ["bps-looker (missing)", "kseistat (missing)"]
    assert p["sources"] == ["bisfetcher", "idxscape"]
    assert p["charts"] is None


def test_idn_charts_cut_to_their_windows(run):
    _res, paths = run
    ch = _read(paths.out, "IDN")["charts"]
    flows = ch["net_foreign"]
    assert flows["days"] == 60
    assert [(x["date"], x["idr"]) for x in flows["points"]] == [
        ("2026-10-19", 3.2e9), ("2026-10-20", -1.61e9), ("2026-10-21", 5e8)]
    assert flows["points"][0]["usd"] == pytest.approx(3.2e9 / 16000)
    assert flows["points"][2]["usd"] is None  # no JISDOR that day: a gap, not filled
    jis = ch["jisdor"]
    assert [(x["date"], x["value"], x["carried_forward"]) for x in jis["points"]] == [
        ("2026-10-16", 15950.0, False), ("2026-10-19", 16000.0, False),
        ("2026-10-20", 16100.0, False), ("2026-10-22", 16100.0, True)]
    assert jis["gaps"] == ["2026-10-21"]
    jci = ch["jci"]
    assert [x["date"] for x in jci["points"]] == ["2026-09-29", "2026-09-30", "2026-10-01"]
    assert jci["source"] == "idxscape+idx-method"
    cur = ch["igsyc"]
    assert cur["latest"]["as_of"] == "2026-10-12"
    assert [x["tenor_y"] for x in cur["latest"]["points"]] == [0.1, 1, 2, 10, 30]
    assert cur["earlier"]["target"] == "2026-09-14"
    assert cur["earlier"]["as_of"] == "2026-09-11"
    assert [x["yield_pct"] for x in cur["earlier"]["points"]] == [5.1, 5.4, 6.2]
    sbn = ch["sbn_non_resident"]
    assert [(x["date"], x["value"]) for x in sbn["points"]] == [
        ("2026-10-19", 9.2044e14), ("2026-10-20", 9.1807e14), ("2026-10-21", 9.1441e14)]


def test_chart_read_failing_is_a_stale_input_not_a_failed_run(tmp_path, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(layers_out, "_flows", broken)
    sources = _sources(tmp_path)
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert res.ok
    p = _valid("subject", _read(paths.out, "IDN"))
    assert p["charts"]["net_foreign"] is None and p["charts"]["jisdor"] is None
    assert any(s.startswith("chart net_foreign failed: RuntimeError") for s in p["stale_inputs"])
    assert p["charts"]["igsyc"] is not None  # the PHEI read still stands


def test_idn_stores_missing_still_write_the_file(tmp_path):
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=_sources(tmp_path, store=False), send=False)
    assert res.ok
    p = _valid("subject", _read(paths.out, "IDN"))
    assert p["layer2"]["components"] == [] and p["layer3"]["signals"] == []
    assert "chart net_foreign: idxscape (missing)" in p["stale_inputs"]
    assert "bps-looker (missing)" in p["stale_inputs"]


def test_foreign_markets_each_get_a_file(tmp_path):
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=_sources(tmp_path, foreign=True), send=False)
    assert res.ok
    names = sorted(p.stem for p in (paths.out / "layers").glob("*.json"))
    assert names == ["AUS", "EMU", "IDN", "JPN", "SGP", "USA", "portfolio", "regime"]
    emu = _valid("subject", _read(paths.out, "EMU"))
    assert emu["members"] == ["DEU", "FRA", "ITA", "ESP", "NLD"]
    assert emu["layer3"] is None and emu["charts"] is None
    assert [a["asset"] for a in emu["layer2"]["assets"]] == ["stocks", "bonds", "currency"]
    assert emu["layer2"]["idr_terms"] is None
    assert all(set(g) == {"input", "why"} for g in emu["layer2"]["gaps"])


def test_builder_bug_writes_an_error_stub_and_never_fails(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise KeyError("oops")

    monkeypatch.setattr(layers_out, "regime_payload", boom)
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=_sources(tmp_path), send=False)
    assert res.ok
    p = _valid("regime", _read(paths.out, "regime"))
    assert p["error"].startswith("KeyError")
    assert p["stale_inputs"] == ["layer file regime failed: KeyError: 'oops'"]
    _valid("subject", _read(paths.out, "IDN"))  # the other files are still written


# ---------------- layer 5 ----------------


def test_portfolio_file_has_buckets_owners_accounts_and_stance_targets(run):
    res, paths = run
    p = _read(paths.out, "portfolio")
    total = sum(b["idr"] for b in p["buckets"])
    assert p["total_idr"] == pytest.approx(total)
    assert sum(b["pct"] for b in p["buckets"]) == pytest.approx(100.0)
    assert {o["owner"] for o in p["by_owner"]} >= {"tommy"}
    assert sum(o["total_idr"] for o in p["by_owner"]) == pytest.approx(total)
    assert p["accounts"], "every account's statement is listed"
    for a in p["accounts"]:
        assert set(a) >= {"issuer", "account", "owner", "doc_type", "as_of", "holdings",
                          "unheld", "cash_idr", "rolled_from", "trade_docs"}
        assert len(a["account"]) <= 5  # masked: last 4 characters only
    stances = {(s["subject"], s["asset"]): s for s in p["stances"]}
    assert set(stances) == {(s["subject"], s["asset"]) for s in res.stances}
    for s in res.stances:
        got = stances[(s["subject"], s["asset"])]
        assert got["current_pct"] == s["portfolio"]["current_pct"]
        assert got["target_pct"] == s["portfolio"]["target_pct"]
        assert got["delta"] == s["portfolio"]["delta"]
        assert got["entry"] == s["entry"] and got["stance"] == s["stance"]
        assert got["benchmark_pct"] == s["portfolio"]["benchmark_pct"]
    assert p["statement_as_of"] is not None
    # S39: the mandate block sums every target and names the cash rest
    m = p["mandate"]
    total = sum(s["portfolio"]["target_pct"] for s in res.stances)
    assert m["target_sum_pct"] == pytest.approx(total, abs=0.05) and total <= 100
    assert m["cash_pct"] == pytest.approx(100 - total, abs=0.05)
    assert set(m["benchmark_pct"]) == {"IDN/stocks", "IDN/bonds", "USA/stocks"}


def test_portfolio_store_missing_is_stale(tmp_path):
    fin = FinancerSource(tmp_path / "nope.db")
    paths = pipeline.Paths.under(tmp_path / "repo")
    res = pipeline.run(DAY, paths=paths, sources=_sources(tmp_path, financer=fin), send=False)
    assert res.ok
    p = _valid("portfolio", _read(paths.out, "portfolio"))
    assert "financer (missing)" in p["stale_inputs"]
    assert p["buckets"] == [] and p["accounts"] == [] and p["total_idr"] is None
    assert all(s["current_pct"] is None for s in p["stances"])
