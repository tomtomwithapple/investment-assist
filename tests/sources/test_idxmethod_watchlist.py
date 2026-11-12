"""PLAN S89 (P107-watchlist): idx-method's Stockbit screeners (`screener_preset`,
`screener_member` in `store/data/stockbiter.db`) read as a watchlist, read-only. A built SQLite
file only; nothing reads the real store."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_watchlist import (
    DEFAULT_WATCHLIST,
    IdxMethodWatchlist,
    load_config,
)

D = date.fromisoformat
DAY = D("2026-11-16")

SCHEMA = """
create table screener_preset (date text not null, screener_id integer not null, category text,
  grp text, name text, description text, rules text, universe text, sort text, totalrows integer,
  fetched integer, primary key (date, screener_id));
create table screener_member (date text not null, screener_id integer not null,
  rank integer not null, symbol text not null, results text,
  primary key (date, screener_id, symbol));
"""

PRESETS = [  # (id, category, name, members)
    (7377506, "Custom", "Cheap Big Caps with Dividend", ["ADRO", "ANTM", "BBNI"]),
    (7377507, "Custom", "Cheap Mid Caps with Dividend", ["BBNI", "ELSA"]),
    (5, "Dividend", "High Dividend Yield", ["ITMG", "PTBA"]),
]


def make_db(root: Path, dates=("2026-11-12", "2026-11-13"), presets=PRESETS,
            tables=True) -> Path:
    db = root / "store" / "data" / "stockbiter.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    if tables:
        con.executescript(SCHEMA)
        for d in dates:
            for sid, cat, name, members in presets:
                con.execute("insert into screener_preset values (?,?,?,?,?,?,?,?,?,?,?)",
                            (d, sid, cat, None, name, "", "[]", "{}", "{}", len(members),
                             len(members)))
                for rank, sym in enumerate(members, 1):
                    con.execute("insert into screener_member values (?,?,?,?,?)",
                                (d, sid, rank, sym, json.dumps({"Dividend Yield": 5.0})))
    else:
        con.execute("create table bars (date text)")
    con.commit()
    con.close()
    return root


def test_default_reads_every_custom_screener_on_the_newest_date(tmp_path):
    w = IdxMethodWatchlist(make_db(tmp_path)).latest(DAY)
    assert w["as_of"] == "2026-11-13" and w["stale"] is None and w["missing"] == []
    assert [s["name"] for s in w["screeners"]] == ["Cheap Big Caps with Dividend",
                                                   "Cheap Mid Caps with Dividend"]
    assert w["screeners"][0]["members"] == ["ADRO", "ANTM", "BBNI"]  # in rank order
    assert w["members"] == {
        "ADRO": ["Cheap Big Caps with Dividend"], "ANTM": ["Cheap Big Caps with Dividend"],
        "BBNI": ["Cheap Big Caps with Dividend", "Cheap Mid Caps with Dividend"],
        "ELSA": ["Cheap Mid Caps with Dividend"]}
    assert "ITMG" not in w["members"]  # a Stockbit preset outside `Custom`


def test_config_selects_screeners_by_id_or_name_and_names_the_missing(tmp_path):
    root = make_db(tmp_path)
    w = IdxMethodWatchlist(root, {"screeners": [5, "Cheap Mid Caps with Dividend", 99]}
                           ).latest(DAY)
    assert [s["id"] for s in w["screeners"]] == [5, 7377507]
    assert w["missing"] == ["99"]
    assert set(w["members"]) == {"BBNI", "ELSA", "ITMG", "PTBA"}


def test_a_future_date_is_ignored_and_an_old_one_is_stale_not_an_error(tmp_path):
    root = make_db(tmp_path, dates=("2026-11-05", "2026-12-01"))
    w = IdxMethodWatchlist(root).latest(DAY)
    assert w["as_of"] == "2026-11-05"
    assert w["stale"] and "11d old" in w["stale"]
    assert w["members"]  # still read: a stale watchlist is a stale input, never a failure


def test_missing_db_or_tables_is_source_unavailable(tmp_path):
    with pytest.raises(SourceUnavailable) as e:
        IdxMethodWatchlist(tmp_path).latest(DAY)
    assert e.value.reason == "missing"
    root = make_db(tmp_path / "x", tables=False)
    with pytest.raises(SourceUnavailable) as e:
        IdxMethodWatchlist(root).latest(DAY)
    assert e.value.reason == "missing" and "no table screener_" in e.value.detail
    root = make_db(tmp_path / "y", dates=())
    with pytest.raises(SourceUnavailable) as e:
        IdxMethodWatchlist(root).latest(DAY)
    assert "no screener_member" in e.value.detail


def test_reading_leaves_the_store_unchanged(tmp_path):
    root = make_db(tmp_path)
    db = root / "store" / "data" / "stockbiter.db"
    before = db.read_bytes()
    IdxMethodWatchlist(root).latest(DAY)
    assert db.read_bytes() == before
    assert sorted(p.name for p in db.parent.iterdir()) == ["stockbiter.db"]


def test_shipped_config_defaults_to_every_custom_screener():
    cfg = load_config(DEFAULT_WATCHLIST)
    assert cfg["category"] == "Custom" and cfg["screeners"] == []
    assert cfg["max_age_days"] > 0
