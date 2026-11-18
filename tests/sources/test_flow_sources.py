"""Phase S adapters (S106, P127-flow-sources): per-name money flow read READ-ONLY.

- idxscape `stock_summary` per code as compact columns (`IdxscapeSource.stock_flows`),
- kseistat `holdings` per code and month by holder group (`KseistatSource.stock_composition`),
- idx-method `insider_history` parsed into market trades (`IdxMethodInsider.trades`).

Fixture stores are built from the siblings' own DDL (tests/fixtures/idxscape_flows,
tests/fixtures/kseistat) plus a few hand rows; nothing touches a real store."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES

from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_insider import IdxMethodInsider
from assist.sources.idxscape import IdxscapeSource
from assist.sources.kseistat import KseistatSource

D = {d: date(2026, 10, d) for d in (19, 20, 21, 22)}

# ---------------- idxscape ----------------


def _idxscape(path: Path, rows: list[tuple], trading_day: bool = True) -> Path:
    con = duckdb.connect(str(path))
    try:
        con.execute((FIXTURES / "idxscape_flows" / "schema.sql").read_text())
        con.executemany(
            "insert into stock_summary (trade_date, code, previous, high, low, close,"
            " volume_shares, value_idr, non_regular_value_idr, frequency, listed_shares,"
            " foreign_buy_shares, foreign_sell_shares, net_foreign_shares,"
            " net_foreign_value_est_idr) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
            rows)
        if trading_day:
            con.execute("insert into trading_day values"
                        " ('2026-10-19', true, 2, '2026-10-19 11:00:00+00'),"
                        " ('2026-10-20', true, 2, '2026-10-20 17:30:00+00')")
    finally:
        con.close()
    return path


ROWS = [
    # AAAA: foreigners buy, then a suspended day (no trade: high/low NULL, volume 0)
    (D[19], "AAAA", 1000, 1020, 990, 1010, 9_000, 9_090_000, 1_000_000, 10_000, 500, 100, 400,
     404_000),
    (D[20], "AAAA", 1010, None, None, 1010, 0, 0, None, 10_000, 0, 0, 0, 0),
    (D[21], "AAAA", 1010, 1050, 1000, 1040, 2_000, 2_080_000, 0, 10_000, 0, 300, -300,
     -312_000),
    # BBBB: no foreign trade at all
    (D[19], "BBBB", 200, 210, 195, 205, 1_000, 205_000, 0, 5_000, 0, 0, 0, 0),
]


def test_stock_flows_columns_per_code(tmp_path):
    src = IdxscapeSource(_idxscape(tmp_path / "i.duckdb", ROWS))
    flows = src.stock_flows()
    assert sorted(flows) == ["AAAA", "BBBB"]
    a = flows["AAAA"]
    assert [a.date(i) for i in range(len(a.days))] == [D[19], D[20], D[21]]
    assert list(a.previous) == [1000, 1010, 1010]
    assert list(a.close) == [1010, 1010, 1040]
    assert list(a.value) == [9_090_000, 0, 2_080_000]
    assert list(a.non_regular) == [1_000_000, 0, 0]  # NULL non-regular reads 0
    assert list(a.net_foreign) == [404_000, 0, -312_000]
    assert list(a.listed) == [10_000] * 3


def test_suspended_day_has_no_range(tmp_path):
    a = IdxscapeSource(_idxscape(tmp_path / "i.duckdb", ROWS)).stock_flows()["AAAA"]
    assert math.isnan(a.high[1]) and math.isnan(a.low[1])
    assert (a.high[0], a.low[0]) == (1020, 990)


def test_code_with_no_foreign_trade_is_kept(tmp_path):
    b = IdxscapeSource(_idxscape(tmp_path / "i.duckdb", ROWS)).stock_flows()["BBBB"]
    assert list(b.net_foreign) == [0] and list(b.value) == [205_000]


def test_recorded_is_the_wib_date_or_zero(tmp_path):
    a = IdxscapeSource(_idxscape(tmp_path / "i.duckdb", ROWS)).stock_flows()["AAAA"]
    # 10-20 17:30 UTC is 10-21 00:30 WIB; 10-21 has no trading_day row
    assert [date.fromordinal(x) if x else None for x in a.recorded] == [D[19], D[21], None]


def test_window_and_codes(tmp_path):
    src = IdxscapeSource(_idxscape(tmp_path / "i.duckdb", ROWS))
    got = src.stock_flows(start=D[20], end=D[21], codes=["AAAA"])
    assert list(got) == ["AAAA"] and len(got["AAAA"].days) == 2


def test_no_trading_day_table_reads_unknown_record(tmp_path):
    path = tmp_path / "i.duckdb"
    con = duckdb.connect(str(path))
    con.execute((FIXTURES / "idxscape_flows" / "schema.sql").read_text())
    con.execute("drop table trading_day")
    con.close()
    con = duckdb.connect(str(path))
    con.execute("insert into stock_summary (trade_date, code, previous, close, volume_shares,"
                " value_idr, frequency, listed_shares, foreign_buy_shares, foreign_sell_shares,"
                " net_foreign_shares, net_foreign_value_est_idr)"
                " values ('2026-10-19', 'AAAA', 1, 1, 1, 1, 1, 1, 0, 0, 0, 0)")
    con.close()
    assert list(IdxscapeSource(path).stock_flows()["AAAA"].recorded) == [0]


def test_stock_flows_missing_table(tmp_path):
    path = tmp_path / "i.duckdb"
    duckdb.connect(str(path)).close()
    with pytest.raises(SourceUnavailable) as e:
        IdxscapeSource(path).stock_flows()
    assert e.value.reason == "missing"


# ---------------- kseistat ----------------

AUG, SEP, OCT = date(2026, 8, 31), date(2026, 9, 30), date(2026, 10, 30)


def _kseistat(path: Path) -> Path:
    con = duckdb.connect(str(path))
    try:
        con.execute((FIXTURES / "kseistat" / "schema.sql").read_text())
        con.execute((FIXTURES / "kseistat" / "data.sql").read_text())
        # a third month with funds and no loads row
        con.executemany("insert into holdings values (?, 'AAAA', 200, 1200, ?, ?, ?)", [
            (OCT, "local", "ID", 40), (OCT, "local", "MF", 10), (OCT, "local", "PF", 5),
            (OCT, "local", "IS", 5), (OCT, "local", "CP", 10), (OCT, "foreign", "ID", 2),
            (OCT, "foreign", "CP", 28)])
    finally:
        con.close()
    return path


def test_stock_composition_groups(tmp_path):
    rows = KseistatSource(_kseistat(tmp_path / "k.duckdb")).stock_composition()
    by = {(r.code, r.date): r for r in rows}
    aug = by[("AAAA", AUG)]
    assert (aug.holdings, aug.foreign_inst, aug.foreign_ind, aug.local_funds,
            aug.local_ind) == (100, 20, 0, 0, 60)
    assert aug.sec_num == 200
    octo = by[("AAAA", OCT)]
    # local funds are MF + PF + IS; CP is neither a fund nor an individual
    assert (octo.holdings, octo.foreign_inst, octo.foreign_ind, octo.local_funds,
            octo.local_ind) == (100, 28, 2, 20, 40)


def test_stock_composition_loaded_or_none(tmp_path):
    rows = KseistatSource(_kseistat(tmp_path / "k.duckdb")).stock_composition()
    loaded = {(r.code, r.date): r.loaded for r in rows}
    assert loaded[("AAAA", AUG)] == date(2026, 9, 5)
    assert loaded[("AAAA", OCT)] is None  # a month without a loads row


def test_stock_composition_window_and_order(tmp_path):
    rows = KseistatSource(_kseistat(tmp_path / "k.duckdb")).stock_composition(start=SEP)
    assert [(r.code, r.date) for r in rows] == [("AAAA", SEP), ("AAAA", OCT), ("BBBB", SEP)]


def test_stock_composition_missing(tmp_path):
    path = tmp_path / "k.duckdb"
    duckdb.connect(str(path)).close()
    with pytest.raises(SourceUnavailable) as e:
        KseistatSource(path).stock_composition()
    assert e.value.reason == "missing"


# ---------------- idx-method insider ----------------


def _raw(name, action, source, change, after="1,000", price="100", badges=()):
    return json.dumps({
        "name": name, "action_type": action, "data_source": {"type": source},
        "changes": {"value": change}, "current": {"value": after},
        "price": {"raw": {"value": price}}, "badges": list(badges),
        "nationality": "NATIONALITY_TYPE_LOCAL"})


INSIDER = [
    ("k1", "2026-03-25", "AAAA", _raw("DIREKTUR A", "ACTION_TYPE_BUY", "SOURCE_TYPE_IDX",
                                     "+626,237", "1,720,729", "6982",
                                     ["SHAREHOLDER_BADGE_DIREKTUR"])),
    # the same trade reported again from KSEI: one trade, not two
    ("k2", "2026-03-25", "AAAA", _raw("DIREKTUR A", "ACTION_TYPE_BUY", "SOURCE_TYPE_KSEI",
                                     "+626,237", "1,720,729", "6982")),
    ("k3", "2026-04-01", "AAAA", _raw("HOLDER B", "ACTION_TYPE_SELL", "SOURCE_TYPE_KSEI",
                                     "-58,300,000")),
    ("k4", "2026-04-02", "AAAA", _raw("HOLDER B", "ACTION_TYPE_TRANSFER", "SOURCE_TYPE_KSEI",
                                     "-1,000")),
    # a sell whose change is positive: the label and the number disagree, so it is dropped
    ("k5", "2026-04-03", "AAAA", _raw("HOLDER C", "ACTION_TYPE_SELL", "SOURCE_TYPE_IDX", "+5")),
    ("k6", "2026-04-04", "BBBB", _raw("HOLDER D", "ACTION_TYPE_BUY", "SOURCE_TYPE_IDX", "n/a")),
    ("k7", "2026-04-05", "BBBB", "not json"),
]


def _stockbiter(root: Path, rows=INSIDER) -> Path:
    db = root / "store" / "data" / "stockbiter.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("create table insider_history (key text primary key, date text not null,"
                " symbol text, raw text not null)")
    con.executemany("insert into insider_history values (?, ?, ?, ?)", rows)
    con.commit()
    con.close()
    return root


def test_insider_market_trades_parsed_and_deduplicated(tmp_path):
    ins = IdxMethodInsider(_stockbiter(tmp_path)).trades()
    assert [(t.date, t.symbol, t.holder, t.action, t.shares) for t in ins.trades] == [
        (date(2026, 3, 25), "AAAA", "DIREKTUR A", "buy", 626_237),
        (date(2026, 4, 1), "AAAA", "HOLDER B", "sell", -58_300_000),
    ]
    first = ins.trades[0]
    assert first.sources == ("IDX", "KSEI") and first.price == 6982.0
    assert first.shares_after == 1_720_729 and first.badges == ("DIREKTUR",)


def test_insider_counts_what_it_left_out(tmp_path):
    ins = IdxMethodInsider(_stockbiter(tmp_path)).trades()
    assert ins.dropped == {"duplicate": 1, "not a market trade": 1, "sign disagrees": 1,
                           "no share change": 1, "unreadable": 1}


def test_insider_settlement_record_is_the_same_trade(tmp_path):
    rows = [
        ("a", "2026-10-29", "KETR", _raw("GEMA", "ACTION_TYPE_BUY", "SOURCE_TYPE_IDX",
                                        "+3,951,500", price="477")),
        # KSEI dates it at settlement, two trading days later: the same trade
        ("b", "2026-11-02", "KETR", _raw("GEMA", "ACTION_TYPE_BUY", "SOURCE_TYPE_KSEI",
                                        "+3,951,500", price="480")),
        # the same size again from the same source three days on: a second trade
        ("c", "2026-11-05", "KETR", _raw("GEMA", "ACTION_TYPE_BUY", "SOURCE_TYPE_IDX",
                                        "+3,951,500")),
        # KSEI two days after c: c's settlement record (a already has its own)
        ("d", "2026-11-07", "KETR", _raw("GEMA", "ACTION_TYPE_BUY", "SOURCE_TYPE_KSEI",
                                        "+3,951,500")),
        # KSEI again eight days after c: too far to be anyone's settlement record
        ("e", "2026-11-13", "KETR", _raw("GEMA", "ACTION_TYPE_BUY", "SOURCE_TYPE_KSEI",
                                        "+3,951,500")),
    ]
    ins = IdxMethodInsider(_stockbiter(tmp_path, rows)).trades()
    assert [(t.date, t.sources) for t in ins.trades] == [
        (date(2026, 10, 29), ("IDX", "KSEI")),
        (date(2026, 11, 5), ("IDX", "KSEI")),
        (date(2026, 11, 13), ("KSEI",)),
    ]
    assert ins.trades[0].price == 477.0 and ins.dropped == {"duplicate": 2}


def test_insider_window(tmp_path):
    ins = IdxMethodInsider(_stockbiter(tmp_path)).trades(start=date(2026, 3, 26))
    assert [t.symbol for t in ins.trades] == ["AAAA"] and ins.trades[0].action == "sell"


def test_insider_missing(tmp_path):
    with pytest.raises(SourceUnavailable) as e:
        IdxMethodInsider(tmp_path).trades()
    assert e.value.reason == "missing"
    db = tmp_path / "store" / "data" / "stockbiter.db"
    db.parent.mkdir(parents=True)
    sqlite3.connect(db).close()
    with pytest.raises(SourceUnavailable) as e:
        IdxMethodInsider(tmp_path).trades()
    assert e.value.reason == "missing"
