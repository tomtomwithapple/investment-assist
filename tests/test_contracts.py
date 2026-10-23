"""S1 contracts: tidy Row, Source protocol, read-only openers, layer types, stance schema."""

from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import duckdb
import httpx
import jsonschema
import pytest
from helpers import hold_duckdb_lock, load_stances, make_duckdb, make_sqlite

from assist.layers import types as lt
from assist.sources import base
from assist.sources.base import Row, SourceUnavailable

REPO = Path(__file__).resolve().parents[1]
OBS_DDL = "create table observations (series_id varchar, date date, value double)"
OBS_ROWS = {"observations": [("A", date(2026, 10, 1), 1.5), ("A", date(2026, 10, 2), 2.5)]}

# The output contract in CLAUDE.md, plus the fields the slice adds (sources, versions).
CLAUDE_EXAMPLE = {
    "subject": "IDN", "asset": "bonds", "as_of": "2026-10-13",
    "stance": "overweight", "score": 68, "confidence": 0.74,
    "regime": "neutral", "drivers": ["real yield 3.1% (82nd pct)", "foreign SBN +Rp4.2T/4w"],
    "risks": ["USD/IDR at 6m high"], "watch": ["BI meeting 2026-10-22", "US CPI 2026-10-15"],
    "entry": {"style": "ladder", "tranches": 3, "spacing_days": 10},
    "portfolio": {"current_pct": 8, "target_pct": 15, "delta": "+7pt over 3 tranches"},
    "stale_inputs": [], "disclaimer": "Heuristic, not investment advice.",
}  # fmt: skip
ADDED = {
    "schema_version": "1.0.0",
    "model_fingerprint": "sha256:" + "0" * 64,
    "sources": ["worldbankscape"],
}


# ---------------- Row ----------------


def test_row_is_a_frozen_tidy_record():
    r = Row("VIXCLS", date(2026, 10, 1), 17.2, date(2026, 10, 2), "sec-edgar")
    assert r._fields == ("series_id", "date", "value", "as_of", "source")
    assert r.value == 17.2
    with pytest.raises(AttributeError):
        r.value = 1.0  # type: ignore[misc]


def test_row_value_and_as_of_may_be_missing():
    r = Row("X", date(2026, 1, 1), None, None, "s")
    assert r.value is None and r.as_of is None


# ---------------- Source protocol ----------------


class _FakeSource:
    name = "fake"

    def rows(self, series_ids=None, start=None, end=None):
        return [Row("A", date(2026, 1, 1), 1.0, None, self.name)]


class _DownSource:
    name = "down"

    def rows(self, series_ids=None, start=None, end=None):
        raise SourceUnavailable("down", "locked", "held by refresh")


def test_any_object_with_name_and_rows_is_a_source():
    assert isinstance(_FakeSource(), base.Source)
    assert not isinstance(object(), base.Source)


def test_read_rows_turns_unavailable_into_stale_inputs():
    rows, stale = base.read_rows(_FakeSource())
    assert len(rows) == 1 and stale == []
    rows, stale = base.read_rows(_DownSource())
    assert rows == [] and stale == ["down (locked)"]


def test_read_rows_does_not_swallow_bugs():
    class Buggy:
        name = "buggy"

        def rows(self, series_ids=None, start=None, end=None):
            raise KeyError("a bug, not an outage")

    with pytest.raises(KeyError):
        base.read_rows(Buggy())


def test_source_unavailable_carries_source_and_reason():
    e = SourceUnavailable("dbnomics", "locked", "Could not set lock on file")
    assert e.source == "dbnomics" and e.reason == "locked"
    assert e.stale_input == "dbnomics (locked)"
    assert "Could not set lock" in str(e)
    with pytest.raises(ValueError):
        SourceUnavailable("x", "broken")


# ---------------- DuckDB ----------------


def test_duckdb_ro_reads_and_refuses_writes(tmp_path):
    db = make_duckdb(tmp_path / "s.duckdb", OBS_DDL, OBS_ROWS)
    with base.duckdb_ro(db, "x") as con:
        assert con.execute("select count(*) from observations").fetchone()[0] == 2
        with pytest.raises(duckdb.Error):
            con.execute("insert into observations values ('B', '2026-10-03', 1)")


def test_attach_ro_attaches_under_an_alias(tmp_path):
    db = make_duckdb(tmp_path / "s.duckdb", OBS_DDL, OBS_ROWS)
    con = duckdb.connect()
    try:
        base.attach_ro(con, db, "bis", "bisfetcher")
        assert con.execute("select sum(value) from bis.observations").fetchone()[0] == 4.0
        with pytest.raises(duckdb.Error):
            con.execute("delete from bis.observations")
    finally:
        con.close()


def test_duckdb_missing_file_is_unavailable(tmp_path):
    with pytest.raises(SourceUnavailable) as e, base.duckdb_ro(tmp_path / "no.duckdb", "x"):
        pass
    assert e.value.reason == "missing"
    con = duckdb.connect()
    with pytest.raises(SourceUnavailable) as e:
        base.attach_ro(con, tmp_path / "no.duckdb", "a", "x")
    assert e.value.reason == "missing"
    assert not (tmp_path / "no.duckdb").exists()  # never created by a read


def test_duckdb_locked_by_another_process_is_unavailable(tmp_path):
    db = make_duckdb(tmp_path / "s.duckdb", OBS_DDL, OBS_ROWS)
    with hold_duckdb_lock(db):
        with pytest.raises(SourceUnavailable) as e, base.duckdb_ro(db, "bisfetcher"):
            pass
        assert e.value.reason == "locked" and e.value.source == "bisfetcher"
        con = duckdb.connect()
        with pytest.raises(SourceUnavailable) as e:
            base.attach_ro(con, db, "bis", "bisfetcher")
        assert e.value.reason == "locked"


def test_open_query_close_releases_the_file(tmp_path):
    """dbnomics' lock is mutual: a reader blocks `dbn refresh`, so nothing stays open."""
    db = make_duckdb(tmp_path / "dbn.duckdb", OBS_DDL, OBS_ROWS)
    cols, rows = base.open_query_close(
        db,
        "select series_id, value from observations where value > ? order by value",
        [2.0],
        "dbnomics",
    )
    assert cols == ["series_id", "value"] and rows == [("A", 2.5)]
    rw = duckdb.connect(str(db))  # a writer can open straight after
    rw.close()


def test_open_query_close_locked_is_unavailable(tmp_path):
    db = make_duckdb(tmp_path / "dbn.duckdb", OBS_DDL, OBS_ROWS)
    with hold_duckdb_lock(db), pytest.raises(SourceUnavailable) as e:
        base.open_query_close(db, "select 1", source="dbnomics")
    assert e.value.reason == "locked"


# ---------------- SQLite ----------------


def test_sqlite_ro_reads_and_refuses_writes(tmp_path):
    db = make_sqlite(
        tmp_path / "f.db",
        "create table holdings (as_of text, value real);",
        {"holdings": [("2026-10-01", 10.0)]},
    )
    with base.sqlite_ro(db, "financer") as con:
        assert con.execute("select max(as_of) from holdings").fetchone()[0] == "2026-10-01"
        with pytest.raises(sqlite3.OperationalError):
            con.execute("insert into holdings values ('2026-10-02', 1)")


def test_sqlite_missing_and_locked_are_unavailable(tmp_path):
    with pytest.raises(SourceUnavailable) as e, base.sqlite_ro(tmp_path / "no.db", "financer"):
        pass
    assert e.value.reason == "missing"
    assert not (tmp_path / "no.db").exists()

    db = make_sqlite(tmp_path / "f.db", "create table t (x int);")
    writer = sqlite3.connect(db)
    writer.execute("begin exclusive")
    try:
        with pytest.raises(SourceUnavailable) as e, base.sqlite_ro(db, "financer"):
            pass
        assert e.value.reason == "locked"
    finally:
        writer.rollback()
        writer.close()


# ---------------- Postgres ----------------


def test_postgres_unreachable_is_unavailable():
    """Nothing listens on port 1; whether or not the extension is installed, the read becomes
    unavailable instead of crashing the run."""
    with (
        pytest.raises(SourceUnavailable) as e,
        base.postgres_ro("postgresql://bps:secret@127.0.0.1:1/bps", "bps-looker"),
    ):
        pass
    assert e.value.source == "bps-looker"
    assert "secret" not in str(e.value)


# ---------------- HTTP CSV ----------------


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_http_csv_returns_dict_rows():
    def handler(request):
        assert request.url.params["format"] == "csv"
        return httpx.Response(200, text="date,value\n2026-10-01,17.2\n2026-10-02,\n")

    with _client(handler) as c:
        rows = base.http_csv(c, "http://127.0.0.1:8660/series/fred/VIXCLS", "sec-edgar")
    assert rows == [{"date": "2026-10-01", "value": "17.2"}, {"date": "2026-10-02", "value": ""}]


def test_http_csv_refuses_non_localhost():
    with _client(lambda r: httpx.Response(200)) as c, pytest.raises(ValueError):
        base.http_csv(c, "https://example.com/x", "sec-edgar")


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused", request=r)), "missing"),
        (lambda r: httpx.Response(503, text="refresh running"), "locked"),
        (lambda r: httpx.Response(500, text="boom"), "error"),
    ],
)
def test_http_csv_server_down_or_busy_is_unavailable(handler, reason):
    with _client(handler) as c, pytest.raises(SourceUnavailable) as e:
        base.http_csv(c, "http://127.0.0.1:8770/api/latest", "dbnomics")
    assert e.value.reason == reason


def test_http_csv_404_is_a_bug_not_an_outage():
    with _client(lambda r: httpx.Response(404)) as c, pytest.raises(httpx.HTTPStatusError):
        base.http_csv(c, "http://127.0.0.1:8770/api/series/nope", "dbnomics")


# ---------------- layer types ----------------


def test_layer_types_are_frozen_and_checked():
    reg = lt.Regime(date(2026, 10, 13), "risk_off", "up", ("VIX 31",), (), ("sec-edgar",))
    with pytest.raises(FrozenInstanceError):
        reg.state = "neutral"  # type: ignore[misc]
    with pytest.raises(ValueError):
        lt.Regime(date(2026, 10, 13), "panic", "up")
    with pytest.raises(ValueError):
        lt.Regime(date(2026, 10, 13), "neutral", "sideways")

    s = lt.AssetScore("IDN", "bonds", date(2026, 10, 23), 58.0, 0.97)
    assert s.source == "worldbankscape" and s.flags == ()
    with pytest.raises(ValueError):
        lt.AssetScore("IDN", "bonds", date(2026, 10, 23), 101.0, 0.9)
    with pytest.raises(ValueError):
        lt.AssetScore("IDN", "bonds", date(2026, 10, 23), 50.0, 1.5)

    o = lt.Override("IDN", "bonds", date(2026, 10, 23), -4.0, "CPI cooling", ("bps-looker",))
    assert o.delta == -4.0
    with pytest.raises(ValueError):
        lt.Override("IDN", "bonds", date(2026, 10, 23), 12.0, "too big", ("bps-looker",))

    sig = lt.Signal("IDN", "stocks", date(2026, 10, 23), "foreign_flow_4w", -1.1e12, -1, "idxscape")
    assert sig.direction == -1
    with pytest.raises(ValueError):
        lt.Signal("IDN", "stocks", date(2026, 10, 23), "x", 1.0, 2, "idxscape")

    w = lt.Weights(date(2026, 10, 1), {("IDN", "stocks"): 60.0, ("IDN", "cash"): 40.0})
    assert w.pct("IDN", "stocks") == 60.0 and w.pct("USA", "bonds") is None
    with pytest.raises(ValueError):
        lt.Weights(date(2026, 10, 1), {("IDN", "stocks"): 70.0, ("IDN", "cash"): 40.0})

    c = lt.Candidate("IDN", "stocks", date(2026, 10, 23), "BBCA", "dividend", 0.8, "idx-method")
    assert c.entry_level is None


def test_stance_constants_match_the_schema():
    schema = json.loads((REPO / "schema" / "stance.schema.json").read_text())
    props = schema["properties"]
    assert tuple(props["stance"]["enum"]) == lt.STANCES
    assert tuple(props["regime"]["enum"]) == lt.REGIME_STATES
    assert tuple(props["asset"]["enum"]) == lt.ASSETS
    assert tuple(props["entry"]["properties"]["style"]["enum"]) == lt.ENTRY_STYLES
    assert lt.STANCES == ("overweight", "neutral", "underweight", "avoid")


# ---------------- stance schema ----------------


def test_stance_schema_is_a_valid_draft_2020_12_schema():
    for name in ("stance.schema.json", "worldbankscape/score.schema.json"):
        jsonschema.Draft202012Validator.check_schema(
            json.loads((REPO / "schema" / name).read_text())
        )


def test_three_fixture_stances_are_valid():
    stances = load_stances()
    assert len(stances) == 3
    v = lt.stance_validator()
    for s in stances:
        v.validate(s)
    assert {s["stance"] for s in stances} == {"overweight", "neutral", "underweight"}


def test_claude_md_output_contract_validates_with_the_added_fields():
    lt.stance_validator().validate({**CLAUDE_EXAMPLE, **ADDED})


@pytest.mark.parametrize("field", ["sources", "disclaimer", "stance", "stale_inputs", "entry"])
def test_required_fields(field):
    doc = {**CLAUDE_EXAMPLE, **ADDED}
    del doc[field]
    with pytest.raises(jsonschema.ValidationError):
        lt.stance_validator().validate(doc)


@pytest.mark.parametrize(
    ("path", "bad"),
    [
        (("stance",), "buy"),
        (("score",), 120),
        (("confidence",), 1.2),
        (("regime",), "panic"),
        (("asset",), "property"),
        (("as_of",), "13/10/2026"),
        (("sources",), []),
        (("disclaimer",), "Trust me."),
        (("entry", "style"), "yolo"),
        (("entry", "tranches"), -1),
        (("portfolio", "target_pct"), 140),
        (("schema_version",), "1"),
        (("extra_field",), 1),
    ],
)
def test_invalid_values_are_rejected(path, bad):
    doc = copy.deepcopy({**CLAUDE_EXAMPLE, **ADDED})
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad
    with pytest.raises(jsonschema.ValidationError):
        lt.stance_validator().validate(doc)


def test_stance_reuses_worldbankscape_defs():
    """Extends score.schema.json: date, semver and flag come from its $defs, not a copy."""
    text = (REPO / "schema" / "stance.schema.json").read_text()
    assert "worldbankscape/schema/score.schema.json#/$defs/date" in text
    assert "worldbankscape/schema/score.schema.json#/$defs/flag" in text
    doc = {**CLAUDE_EXAMPLE, **ADDED, "flags": [{"code": "x", "severity": "loud", "message": "m"}]}
    with pytest.raises(jsonschema.ValidationError):
        lt.stance_validator().validate(doc)


def test_score_validator_accepts_a_worldbankscape_payload():
    payload = {
        "schema_version": "1.2.0", "subject": "IDN", "subject_type": "country",
        "asset_class": "bonds", "as_of": "2026-10-23", "model_version": "0.3.0",
        "score": 58.0, "confidence": 0.97, "components": [], "flags": [],
        "stale_inputs": [], "attribution": ["World Bank WDI"],
        "disclaimer": "Heuristic macro context, not investment advice.",
    }  # fmt: skip
    lt.score_validator().validate(payload)


def test_vendored_score_schema_matches_worldbankscape():
    """The copy in schema/worldbankscape/ must track the sibling's contract (read-only check)."""
    sibling = REPO.parent / "worldbankscape" / "schema" / "score.schema.json"
    if not sibling.is_file():
        pytest.skip("worldbankscape checkout not present")
    vendored = REPO / "schema" / "worldbankscape" / "score.schema.json"
    assert json.loads(vendored.read_text()) == json.loads(sibling.read_text())
