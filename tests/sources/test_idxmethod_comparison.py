"""idx-method peer comparison adapter (S30): Stockbit display strings parsed to floats, the newest
`comparison_*` date read from a temp `api_raw` (zlib bodies, as endpoints_pull stores them),
industries keyed by identical `industry` blocks, an undecodable body skipped, and a missing db,
table or pull raised as SourceUnavailable. No real store, no network."""

from __future__ import annotations

import json
import sqlite3
import zlib
from datetime import date
from pathlib import Path

import pytest

from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_comparison import IdxMethodComparison, block_key, parse_value

METRICS = {"data": [{"fitem_id": 53, "fitem_name": "Current Valuation", "child": [
    {"fitem_id": 2891, "fitem_name": "Current PE Ratio (TTM)", "child": []}]}]}
BANKS = [{"fitem_id": 2891, "value": "7.60"}, {"fitem_id": 1461, "value": "8.90%"}]
MINERS = [{"fitem_id": 2891, "value": "14.82"}, {"fitem_id": 1461, "value": "14.29%"}]
SECTOR = [{"fitem_id": 2891, "value": "9.92"}]


@pytest.mark.parametrize(("raw", "want"), [
    ("16.00%", 16.0), ("-14.19%", -14.19), ("129,422 B", 1.29422e14), ("(47,342 B)", -4.7342e13),
    ("(1.5%)", -1.5), ("2,347.00", 2347.0), ("-9", -9.0), ("12 T", 1.2e13), ("3 M", 3e6),
    ("0.05", 0.05), (7, 7.0), ("-", None), ("N/A", None), ("25 Mar 26", None), ("", None),
    (None, None), (True, None)])
def test_parse_value(raw, want):
    assert parse_value(raw) == (pytest.approx(want) if want is not None else None)


def _body(data: object, *, compress: bool = True) -> bytes:
    raw = json.dumps({"message": "ok", "data": data}).encode()
    return zlib.compress(raw) if compress else raw


def _store(root: Path, rows: list[tuple], universe: bool = True) -> Path:
    db = root / "store" / "data" / "stockbiter.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("create table api_raw (date text, endpoint text, symbol text default '', "
                "params text default '{}', status integer, fetched_at text, body blob)")
    con.executemany("insert into api_raw (date, endpoint, symbol, body) values (?, ?, ?, ?)", rows)
    if universe:
        con.execute("create table factor_universe (symbol text primary key, name text, "
                    "sector text, status text, delisted integer)")
        con.executemany("insert into factor_universe values (?, ?, ?, 'A', 0)", [
            ("BBNI", "Bank Negara", "Keuangan"), ("BMRI", "Bank Mandiri", "Keuangan"),
            ("ADRO", "Adaro", "Energi"), ("ZZZZ", "Not compared", "Energi")])
    con.commit()
    con.close()
    return root


def _ind(industry: list, sector: list = SECTOR, comp: tuple = ()) -> dict:
    return {"competitor": [{"symbol": c} for c in comp], "industry": industry, "sector": sector}


@pytest.fixture
def root(tmp_path) -> Path:
    day, old = "2026-10-26", "2026-10-23"
    return _store(tmp_path, [
        (day, "comparison_metrics", "", _body(METRICS["data"])),
        (day, "comparison_ratios", "BBNI", _body({"symbol": "BBNI", "data_value": [
            {"fitem_id": 2891, "value": "6.25"}, {"fitem_id": 2892, "value": "129,422 B"},
            {"fitem_id": 1484, "value": "-"}]})),
        (day, "comparison_ratios", "BMRI", _body({"symbol": "BMRI", "data_value": [
            {"fitem_id": 2891, "value": "5.69"}]}, compress=False)),
        (day, "comparison_ratios", "ADRO", b"\x78\x9cnot zlib"),
        (day, "comparison_industries", "BBNI", _body(_ind(BANKS, comp=("BBNI", "BMRI")))),
        (day, "comparison_industries", "BMRI", _body(_ind(BANKS))),
        (day, "comparison_industries", "ADRO", _body(_ind(MINERS))),
        (day, "comparison_industries", "EMPT", _body(_ind([]))),
        (old, "comparison_industries", "OLDX", _body(_ind(BANKS))),
    ])


def test_latest_reads_the_newest_date_only(root):
    c = IdxMethodComparison(root).latest()
    assert c.date == date(2026, 10, 26)
    assert set(c.industry) == {"BBNI", "BMRI", "ADRO"}  # OLDX is older, EMPT has no industry


def test_industries_are_identical_industry_blocks(root):
    c = IdxMethodComparison(root).latest()
    assert c.industry["BBNI"] == c.industry["BMRI"] == block_key(BANKS)
    assert c.industry["ADRO"] == block_key(MINERS) != c.industry["BBNI"]
    assert c.sector_key["BBNI"] == c.sector_key["ADRO"] == block_key(SECTOR)


def test_values_averages_competitors_names_and_catalogue(root):
    c = IdxMethodComparison(root).latest()
    assert c.ratios["BBNI"] == {2891: 6.25, 2892: 1.29422e14, 1484: None}
    assert c.ratios["BMRI"] == {2891: 5.69}  # an uncompressed body reads too
    assert c.industry_avg["BBNI"] == {2891: 7.6, 1461: 8.9}
    assert c.sector_avg["ADRO"] == {2891: 9.92}
    assert c.competitors["BBNI"] == ["BBNI", "BMRI"]
    assert c.names == {"BBNI": "Bank Negara", "BMRI": "Bank Mandiri", "ADRO": "Adaro"}
    assert c.sectors["ADRO"] == "Energi"
    assert c.metrics == {2891: ("Current Valuation", "Current PE Ratio (TTM)")}


def test_an_undecodable_body_skips_that_symbol_only(root):
    c = IdxMethodComparison(root).latest()
    assert "ADRO" not in c.ratios and "ADRO" in c.industry


def test_missing_db_table_or_pull(tmp_path):
    with pytest.raises(SourceUnavailable):
        IdxMethodComparison(tmp_path / "nowhere").latest()
    (tmp_path / "a" / "store" / "data").mkdir(parents=True)
    sqlite3.connect(tmp_path / "a" / "store" / "data" / "stockbiter.db").execute(
        "create table x (y)").connection.close()
    with pytest.raises(SourceUnavailable, match="no table api_raw"):
        IdxMethodComparison(tmp_path / "a").latest()
    empty = _store(tmp_path / "b", [("2026-10-26", "broker_top", "", _body({}))], universe=False)
    with pytest.raises(SourceUnavailable, match="no comparison_industries"):
        IdxMethodComparison(empty).latest()


def _fundamentals(root: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(root / "store" / "data" / "stockbiter.db")
    con.execute("create table fundamentals (symbol text, stmt text, item text, period text, "
                "value real, currency text)")
    con.executemany("insert into fundamentals values (?, ?, ?, ?, ?, 'IDR')", rows)
    con.commit()
    con.close()


def test_statements_of_compared_names_and_listed_items_only(root):
    _fundamentals(root, [
        ("BBNI", "is", "revenue", "2026Q2", 2e13), ("BBNI", "is", "revenue", "2026Q1", 1.9e13),
        ("BBNI", "bs", "equity", "2026Q2", 1.6e14), ("BBNI", "bs", "cash", "2026Q2", None),
        ("BBNI", "bs", "assets", "2026Q2", 3e13),  # not listed: mixes totals and parts
        ("BBNI", "is", "eps", "2026Q2", 100.0),
        ("ZZZZ", "is", "revenue", "2026Q2", 1e12),  # not compared
    ])
    c = IdxMethodComparison(root).latest()
    assert c.statements == {"BBNI": {"revenue": {"2026Q2": 2e13, "2026Q1": 1.9e13},
                                     "equity": {"2026Q2": 1.6e14}, "cash": {"2026Q2": None}}}


def test_no_fundamentals_table_means_no_statements(root):
    assert IdxMethodComparison(root).latest().statements == {}
