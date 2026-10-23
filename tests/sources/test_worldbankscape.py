"""worldbankscape adapter (P1): layer-1 scores from `out/index.json` + `out/{SUBJECT}/{asset}.json`,
each file validated against worldbankscape's own JSON Schemas (read from its `schema/` at runtime).

The fixture (tests/fixtures/worldbankscape/) is a trimmed copy of a real export (2026-10-23, two
components per payload) with its `schema/` copied alongside, so the default schema dir
(`out/../schema`) resolves the same way it does in the sibling repo."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from helpers import FIXTURES

from assist.layers.types import AssetScore
from assist.sources.base import Row, SourceUnavailable, read_rows
from assist.sources.worldbankscape import (
    SOURCE,
    WorldbankscapeSource,
    ranked,
    series_id,
)

FIX = FIXTURES / "worldbankscape"
AS_OF = date(2026, 10, 23)
ALL = {
    ("BRN", "bonds"),
    ("GOLD", "commodities"),
    ("IDN", "bonds"),
    ("IDN", "stocks"),
    ("MMR", "stocks"),
}


@pytest.fixture
def repo(tmp_path) -> Path:
    """A writable copy of the fixture repo (`out/` + `schema/`)."""
    shutil.copytree(FIX, tmp_path / "worldbankscape")
    return tmp_path / "worldbankscape"


@pytest.fixture
def src(repo) -> WorldbankscapeSource:
    return WorldbankscapeSource(repo / "out")


def _rewrite(repo: Path, rel: str, edit, fix_sha: bool = True) -> None:
    """Edit one payload; re-hash it into the index unless `fix_sha` is False."""
    p = repo / "out" / rel
    payload = json.loads(p.read_text())
    edit(payload)
    data = (json.dumps(payload, indent=2) + "\n").encode()
    p.write_bytes(data)
    if fix_sha:
        idx_path = repo / "out" / "index.json"
        idx = json.loads(idx_path.read_text())
        for e in idx["entries"]:
            if e["path"] == rel:
                e["sha256"] = hashlib.sha256(data).hexdigest()
        idx_path.write_text(json.dumps(idx, indent=2))


def test_loads_every_listed_score(src):
    layer = src.load()
    assert {(s.subject, s.asset) for s in layer.scores} == ALL
    assert layer.stale_inputs == []
    assert all(isinstance(s, AssetScore) and s.source == SOURCE for s in layer.scores)
    assert layer.generated_at == "2026-10-22T21:01:59Z"
    assert "World Bank Pink Sheet (CC BY 4.0)" in layer.attribution
    assert len(layer.attribution) == len(set(layer.attribution))
    assert "not investment advice" in layer.disclaimer


def test_score_fields(src):
    by = {(s.subject, s.asset): s for s in src.load().scores}
    idn = by["IDN", "bonds"]
    assert (idn.as_of, idn.score, idn.confidence) == (AS_OF, 58.0, 0.97)
    assert (idn.raw_score, idn.coverage) == (58.5, 0.97)
    assert idn.flags == ()
    assert idn.stale_inputs == ("yield_spread (missing)",)
    brn = by["BRN", "bonds"]
    assert brn.flags == ({"code": "large_fiscal_deficit", "severity": "critical",
                          "message": "Fiscal balance -17.7% of GDP (< -8%) [2025]"},)
    mmr = by["MMR", "stocks"]
    assert mmr.confidence == 0.231
    assert [f["code"] for f in mmr.flags] == ["high_inflation", "data_gaps"]


def test_filters(src):
    layer = src.load(subjects=["IDN"])
    assert {(s.subject, s.asset) for s in layer.scores} == {("IDN", "bonds"), ("IDN", "stocks")}
    layer = src.load(assets=["stocks"])
    assert {s.subject for s in layer.scores} == {"IDN", "MMR"}
    assert src.load(subjects=["IDN"], assets=["currency"]).scores == []


def test_score_lookup(src):
    assert src.score("IDN", "bonds").score == 58.0
    assert src.score("TLS", "bonds") is None  # not applicable (no entry), never an imputed 50


def test_ignores_files_not_in_index(src, repo):
    (repo / "out" / "XXX").mkdir()
    (repo / "out" / "XXX" / "bonds.json").write_text("{not json")
    (repo / "out" / ".tmp-run1").mkdir()
    assert {(s.subject, s.asset) for s in src.load().scores} == ALL


def test_invalid_payload_is_skipped_and_reported(src, repo):
    _rewrite(repo, "IDN/bonds.json", lambda p: p.update(score=120))
    layer = src.load()
    assert ("IDN", "bonds") not in {(s.subject, s.asset) for s in layer.scores}
    assert len(layer.scores) == 4
    assert layer.stale_inputs == ["worldbankscape IDN/bonds.json (error)"]
    assert "120" in layer.problems["IDN/bonds.json"]


def test_unknown_field_fails_schema(src, repo):
    _rewrite(repo, "GOLD/commodities.json", lambda p: p.update(extra=1))
    assert src.load().stale_inputs == ["worldbankscape GOLD/commodities.json (error)"]


def test_sha_mismatch_is_reported(src, repo):
    _rewrite(repo, "IDN/stocks.json", lambda p: p.update(score=54.0), fix_sha=False)
    layer = src.load()
    assert layer.stale_inputs == ["worldbankscape IDN/stocks.json (error)"]
    assert "sha256" in layer.problems["IDN/stocks.json"]


def test_sha_mismatch_rereads_index_once(src, repo, monkeypatch):
    """A file newer than the index read just before a publish finished: re-read index.json."""
    _rewrite(repo, "IDN/stocks.json", lambda p: p.update(score=54.0), fix_sha=False)
    stale_index = (repo / "out" / "index.json").read_text()
    _rewrite(repo, "IDN/stocks.json", lambda p: None)  # the publish's new index
    fresh_index = (repo / "out" / "index.json").read_text()
    reads = [stale_index, fresh_index]
    monkeypatch.setattr(src, "_read_index_text", lambda: reads.pop(0))
    layer = src.load()
    assert reads == []  # the index was read twice
    assert layer.stale_inputs == []
    assert {s.subject for s in layer.scores if s.asset == "stocks"} == {"IDN", "MMR"}
    by = {(s.subject, s.asset): s for s in layer.scores}
    assert by["IDN", "stocks"].score == 54.0


def test_payload_must_match_its_entry(src, repo):
    _rewrite(repo, "IDN/stocks.json", lambda p: p.update(subject="MYS"))
    assert src.load().stale_inputs == ["worldbankscape IDN/stocks.json (error)"]


def test_listed_file_missing(src, repo):
    (repo / "out" / "MMR" / "stocks.json").unlink()
    layer = src.load()
    assert layer.stale_inputs == ["worldbankscape MMR/stocks.json (missing)"]
    assert len(layer.scores) == 4


def test_missing_out_dir(tmp_path):
    with pytest.raises(SourceUnavailable) as e:
        WorldbankscapeSource(tmp_path / "nope" / "out").load()
    assert e.value.reason == "missing"


def test_missing_schema_is_unavailable(repo):
    shutil.rmtree(repo / "schema")
    with pytest.raises(SourceUnavailable) as e:
        WorldbankscapeSource(repo / "out").load()
    assert e.value.reason == "missing" and "schema" in e.value.detail


def test_explicit_schema_dir(repo, tmp_path):
    shutil.move(repo / "schema", tmp_path / "elsewhere")
    layer = WorldbankscapeSource(repo / "out", schema_dir=tmp_path / "elsewhere").load()
    assert len(layer.scores) == 5


def test_invalid_index_is_error(src, repo):
    idx_path = repo / "out" / "index.json"
    idx = json.loads(idx_path.read_text())
    del idx["entries"][0]["path"]
    idx_path.write_text(json.dumps(idx))
    with pytest.raises(SourceUnavailable) as e:
        src.load()
    assert e.value.reason == "error"


def test_rows_protocol(src):
    rows = src.rows()
    assert len(rows) == 5 * 4
    assert Row(series_id("IDN", "bonds", "score"), AS_OF, 58.0, AS_OF, SOURCE) in rows
    assert Row("WBS.IDN.bonds.confidence", AS_OF, 0.97, AS_OF, SOURCE) in rows
    assert rows == sorted(rows, key=lambda r: (r.series_id, r.date))
    got = src.rows(["WBS.MMR.stocks.confidence", "WBS.IDN.bonds.raw_score", "junk"])
    assert [(r.series_id, r.value) for r in got] == [
        ("WBS.IDN.bonds.raw_score", 58.5), ("WBS.MMR.stocks.confidence", 0.231)]
    assert src.rows(start=date(2026, 10, 24)) == []
    assert len(src.rows(end=AS_OF)) == 20


def test_read_rows_turns_missing_into_stale(tmp_path):
    rows, stale = read_rows(WorldbankscapeSource(tmp_path / "out"))
    assert rows == [] and stale == ["worldbankscape (missing)"]


def test_ranked():
    s = AssetScore("VNM", "property", AS_OF, 54.8, 0.225)
    assert ranked(s) == pytest.approx(51.08)
    assert ranked(AssetScore("IDN", "property", AS_OF, 66.2, 1.0)) == pytest.approx(66.2)


def test_from_config(repo):
    s = WorldbankscapeSource.from_config(env={"ASSIST_WORLDBANKSCAPE_OUT": str(repo / "out")})
    assert s.out_dir == repo / "out"
    assert len(s.load().scores) == 5


def test_never_writes(src, repo):
    before = {p: p.stat().st_mtime_ns for p in repo.rglob("*")}
    src.load()
    src.rows()
    assert {p: p.stat().st_mtime_ns for p in repo.rglob("*")} == before
