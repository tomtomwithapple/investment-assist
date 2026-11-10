"""Phase A end to end (F1): worldbankscape + regime + financer fixtures → stance JSONs in out/,
journal, brief and a Telegram summary sent once. Every store is a fixture, FRED is a fake source
and Telegram is a mock transport; nothing here reads a real store or reaches the network."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from helpers import FIXTURES, make_sqlite

from assist import cli, journal, notify, pipeline
from assist.layers.types import stance_validator
from assist.sources.base import Row, SourceUnavailable
from assist.sources.financer import FinancerSource
from assist.sources.worldbankscape import WorldbankscapeSource

DAY = date(2026, 10, 23)
CREDS = notify.Credentials(chat="987654", token="123456:SECRET-token", source="env")


class FakeFred:
    """Flat, calm FRED lines for the five core regime inputs → neutral regime, dollar flat."""

    name = "sec-edgar"
    LEVELS = {"VIXCLS": 18.0, "BAMLH0A0HYM2": 3.0, "DTWEXBGS": 100.0, "DFII10": 1.5,
              "NFCI": -0.3}

    def __init__(self, error: SourceUnavailable | None = None):
        self.error = error

    def rows(self, series_ids=None, start=None, end=None, as_of=None):
        if self.error:
            raise self.error
        out = []
        for sid, v in self.LEVELS.items():
            if series_ids is not None and sid not in series_ids:
                continue
            for i in range(150):
                d = DAY - timedelta(days=i)
                if (start is None or d >= start) and (end is None or d <= end):
                    out.append(Row(sid, d, v, d, self.name))
        return sorted(out, key=lambda r: (r.series_id, r.date))


@pytest.fixture
def wbs() -> WorldbankscapeSource:
    root = FIXTURES / "worldbankscape"
    return WorldbankscapeSource(root / "out", root / "schema")


@pytest.fixture
def financer(tmp_path: Path) -> FinancerSource:
    fix = FIXTURES / "financer"
    ddl = (fix / "schema.sql").read_text() + (fix / "seed.sql").read_text()
    return FinancerSource(make_sqlite(tmp_path / "financer.db", ddl))


@pytest.fixture
def paths(tmp_path: Path) -> pipeline.Paths:
    return pipeline.Paths.under(tmp_path / "repo")


@pytest.fixture
def telegram():
    log: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        log.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(log)}})

    return log, httpx.Client(transport=httpx.MockTransport(handle))


def _run(paths, wbs, financer, telegram=None, fred=None, send=True):
    sources = pipeline.Sources(worldbankscape=wbs, fred=fred or FakeFred(), financer=financer)
    notify_kw = {}
    if telegram is not None:
        notify_kw = {"creds": CREDS, "client": telegram[1]}
    return pipeline.run(DAY, paths=paths, sources=sources, send=send, notify_kw=notify_kw)


def _out_bytes(out: Path) -> dict[str, bytes]:
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*.json"))}


# ---------------- scope ----------------


def test_in_scope_keeps_target_countries_and_all_commodities(wbs):
    layer1 = wbs.load()
    kept = sorted((s.subject, s.asset) for s in layer1.scores if pipeline.in_scope(s))
    # the fixture holds BRN bonds, MMR stocks (out of scope), IDN bonds and stocks, GOLD
    assert kept == [("GOLD", "commodities"), ("IDN", "bonds"), ("IDN", "stocks")]


def test_scope_has_no_business_or_property():
    assert set(pipeline.ASSETS) == {"stocks", "bonds", "currency", "commodities"}
    assert "IDN" in pipeline.COUNTRIES and "USA" in pipeline.COUNTRIES


# ---------------- run ----------------


def test_run_writes_valid_stances_journal_brief_and_sends_once(paths, wbs, financer, telegram):
    res = _run(paths, wbs, financer, telegram)
    assert res.ok
    files = _out_bytes(paths.out)
    assert sorted(files) == ["GOLD/commodities.json", "IDN/bonds.json", "IDN/stocks.json",
                             "guide.json"]  # S75: this week's steps
    fp = journal.model_fingerprint()
    v = stance_validator()
    for name, blob in files.items():
        payload = json.loads(blob)
        assert payload["model_fingerprint"] == fp
        assert payload["as_of"] == DAY.isoformat()
        assert payload["regime"] == "neutral"
        if name == "guide.json":  # the guide has its own schema (tests/test_guide.py)
            continue
        assert not list(v.iter_errors(payload))
        assert "regime" not in payload["stale_inputs"]
        assert "financer" not in payload["stale_inputs"]

    j = journal.Journal(paths.journal)
    assert j.verify() == len(files) + 1  # one regime record + one per stance and the guide
    kinds = [r["kind"] for r in j.read()]
    assert kinds.count("stance") == 3 and kinds.count("regime") == 1
    assert j.fingerprints() == [fp]
    assert j.model(fp)  # the model's inputs are stored for later diffing

    assert res.brief_path == paths.briefs / f"{DAY}.md"
    brief = res.brief_path.read_text()
    assert "not investment advice" in brief and "IDN" in brief
    assert (paths.snapshots / DAY.isoformat() / "IDN" / "bonds.json").is_file()

    assert res.notify["sent"] is True
    assert len(telegram[0]) == 1
    assert notify.already_sent("brief", DAY, state_dir=paths.notify)


def test_rerun_with_unchanged_inputs_is_byte_identical_and_send_is_skipped(
        paths, wbs, financer, telegram):
    first = _run(paths, wbs, financer, telegram)
    before = _out_bytes(paths.out)
    brief_before = first.brief_path.read_bytes()

    second = _run(paths, wbs, financer, telegram)
    assert _out_bytes(paths.out) == before
    assert second.brief_path.read_bytes() == brief_before
    assert second.notify["skipped"] is True
    assert len(telegram[0]) == 1  # no second HTTP call
    assert journal.Journal(paths.journal).verify() == 10  # every run is journalled (+ guide)


def test_stale_out_files_from_an_earlier_run_are_removed(paths, wbs, financer):
    old = paths.out / "MMR" / "stocks.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}")
    keep = paths.out / "README.txt"
    keep.write_text("not a stance")
    _run(paths, wbs, financer, send=False)
    assert not old.exists()
    assert keep.exists()


def test_missing_financer_and_regime_degrade_never_fail(paths, wbs, tmp_path):
    fin = FinancerSource(tmp_path / "nope.db")
    fred = FakeFred(error=SourceUnavailable("sec-edgar", "locked"))
    res = _run(paths, wbs, fin, fred=fred, send=False)
    assert res.ok
    p = json.loads((paths.out / "IDN" / "bonds.json").read_text())
    assert "financer" in p["stale_inputs"]
    assert "sec-edgar (locked)" in p["stale_inputs"]
    assert p["portfolio"]["current_pct"] is None
    assert any("financer" in s for s in res.stale_inputs)
    assert res.notify is None


def test_missing_layer1_writes_nothing_and_sends_nothing(paths, financer, tmp_path, telegram):
    wbs = WorldbankscapeSource(tmp_path / "no-out")
    res = _run(paths, wbs, financer, telegram)
    assert not res.ok
    assert "worldbankscape (missing)" in res.stale_inputs
    assert not paths.out.exists() or not _out_bytes(paths.out)
    assert telegram[0] == []


def test_message_is_undervalued_and_trades_only():
    def row(sym, rank, size=None):
        return {"symbol": sym, "rank": rank, "style": "dividend_value", "margin_pt": 1.0,
                "held": False, "size": None if size is None else {"idr": size}}
    idn = {"market": "IDN", "styles": [{"style": "dividend_value", "passed": True,
                                        "rows": [row("BMRI", 1, 4e6), row("BBRI", 2)]},
                                       {"style": "garp", "passed": False, "rows": []}],
           "sizing": {"budget_idr": 4e6, "trims": [
               {"symbol": "PWON", "idr": 2.7e6, "reason": "trim in full: fails its screen"},
               {"symbol": "BMRI", "idr": 1.9e6, "reason": "trim to the per-name cap of 5%"}]}}
    usa = {"market": "USA", "styles": [{"style": "garp", "passed": False, "rows": []}],
           "sizing": {"budget_idr": 13.2e6, "trims": []}}
    text = pipeline.message(day=DAY, brief_path=None, undervalued=[idn, usa])
    assert "Undervalued IDN" in text and "Undervalued USA" in text
    assert "IDN to sell (2, IDR 4.6m):\n  PWON    2.7m  trim in full" in text
    assert "IDN to buy (1, IDR 4.0m):\n  BMRI    4.0m  dividend_value #1" in text
    assert "USA to sell: none" in text and "USA to buy: none (IDR 13.2m budget unspent)" in text
    assert "regime" not in text and "overweight" not in text
    assert text.endswith("not investment advice.") and len(notify.chunks(text)) == 1


def test_message_without_candidates_says_so():
    text = pipeline.message(day=DAY, brief_path=None)
    assert "no market read" in text and "to sell" not in text



# ---------------- CLI ----------------


def test_cli_run_regime_journal(paths, wbs, financer, monkeypatch, capsys):
    sources = pipeline.Sources(worldbankscape=wbs, fred=FakeFred(), financer=financer)
    monkeypatch.setattr(pipeline.Sources, "default", classmethod(lambda cls: sources))
    monkeypatch.setattr(pipeline.Paths, "default", classmethod(lambda cls: paths))

    assert cli.main(["run", "--today", DAY.isoformat(), "--no-send"]) == 0
    out = capsys.readouterr().out
    assert "3 stance(s)" in out and "telegram: not sent (--no-send)" in out

    assert cli.main(["regime", "--today", DAY.isoformat()]) == 0
    assert "neutral" in capsys.readouterr().out

    assert cli.main(["brief"]) == 0
    assert "# Investment brief" in capsys.readouterr().out

    assert cli.main(["journal"]) == 0
    out = capsys.readouterr().out
    assert "5 record(s)" in out and "chain ok" in out  # 3 stances, regime, guide
