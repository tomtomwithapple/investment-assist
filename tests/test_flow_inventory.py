"""S105 (P126-flow-inventory): the per-name money-flow inventory reads each sibling store
read-only, reports a missing store instead of failing, and judges each leg on fixed minimums."""

import json
import sqlite3
from datetime import date, timedelta

import duckdb

from assist import flow_inventory as fi

DAYS = [date(2026, 1, 5) + timedelta(days=i) for i in range(5)]


def idxscape_db(path):
    con = duckdb.connect(str(path))
    con.execute(
        "create table stock_summary (trade_date date, code varchar, value_idr bigint,"
        " non_regular_value_idr bigint, foreign_buy_shares bigint, foreign_sell_shares bigint,"
        " net_foreign_shares bigint, net_foreign_value_est_idr bigint)"
    )
    for i, d in enumerate(DAYS):
        # AAAA: foreigners buy every day; BBBB: no foreign trade; CCCC: sells, one crossing day
        con.execute("insert into stock_summary values (?, 'AAAA', 1000, 0, 10, 0, 10, 500)", [d])
        con.execute("insert into stock_summary values (?, 'BBBB', 1000, null, 0, 0, 0, 0)", [d])
        con.execute("insert into stock_summary values (?, 'CCCC', 1000, ?, 0, 5, -5, -200)",
                    [d, 900 if i == 0 else 0])
    con.close()


def stockbiter_db(path, *, flip="CCCC"):
    con = sqlite3.connect(path)
    con.executescript(
        "create table bars (run_id integer, symbol text, date text, close real, value real,"
        " net_foreign real, raw text);"
        "create table insider_history (key text primary key, date text, symbol text, raw text);"
        "create table api_raw (date text, endpoint text, symbol text, params text,"
        " fetched_at text, body blob);"
        "create table screener_preset (date text, screener_id integer, category text, name text);"
        "create table screener_member (date text, screener_id integer, rank integer, symbol text);"
    )
    for d in DAYS:
        con.execute("insert into bars values (1, 'AAAA', ?, 1, 1000, 480, '{}')", [d.isoformat()])
        # CCCC disagrees in sign with idxscape on every day
        con.execute("insert into bars values (1, ?, ?, 1, 1000, 210, '{}')", [flip, d.isoformat()])
    rows = [
        ("k1", "2025-03-01", "AAAA", {"action_type": "ACTION_TYPE_BUY",
                                      "changes": {"value": "+1,000"},
                                      "data_source": {"type": "KSEI"}}),
        ("k2", "2026-01-06", "AAAA", {"action_type": "ACTION_TYPE_SELL",
                                      "changes": {"value": "-50"}, "data_source": {"type": "IDX"}}),
        ("k3", "2026-01-07", "CCCC", {"action_type": "ACTION_TYPE_MESOP_OPTION",
                                      "changes": {"value": "n/a"}, "data_source": {"type": "IDX"}}),
    ]
    con.executemany("insert into insider_history values (?, ?, ?, ?)",
                    [(k, d, s, json.dumps(r)) for k, d, s, r in rows])
    for d in ("2026-11-10", "2026-11-11"):
        con.execute("insert into api_raw values (?, 'broker_top', '', '', ?, x'00')", [d, d])
    con.execute("insert into screener_preset values ('2026-11-12', 7, 'Foreign Flow', 'Net buy')")
    con.execute("insert into screener_preset values ('2026-11-12', 8, 'Dividend', 'Yield')")
    con.execute("insert into screener_member values ('2026-11-12', 7, 1, 'AAAA')")
    con.execute("insert into screener_member values ('2026-11-12', 8, 1, 'BBBB')")
    con.commit()
    con.close()


def ksei_db(path):
    con = duckdb.connect(str(path))
    con.execute("create table holdings (date date, code varchar, sec_num bigint, price bigint,"
                " origin varchar, investor_type varchar, shares bigint)")
    con.execute("create table loads (date date, filename varchar, sha256 varchar, rows integer,"
                " stocks integer, loaded_at timestamp)")
    con.execute("create view v_stock_composition as select date, code from holdings")
    for m in (date(2026, 8, 31), date(2026, 9, 30)):
        for code in ("AAAA", "BBBB"):
            con.execute("insert into holdings values (?, ?, 100, 10, 'local', 'ID', 60)", [m, code])
            con.execute("insert into holdings values (?, ?, 100, 10, 'foreign', 'IB', 40)",
                        [m, code])
    con.execute("insert into loads values ('2026-09-30', 'f', 'h', 4, 2, '2026-10-05 05:15:00')")
    con.close()


def stores(tmp_path):
    idxm = tmp_path / "idx-method"
    (idxm / "store" / "data").mkdir(parents=True)
    (idxm / "data").mkdir()
    idxscape_db(tmp_path / "idxscape.duckdb")
    stockbiter_db(idxm / "store" / "data" / "stockbiter.db")
    ksei_db(tmp_path / "ksei.duckdb")
    (idxm / "data" / "composition.json").write_text(json.dumps({
        "AAAA": {"report_date": "2026-10-30", "window": ["2026-03-31", "2026-10-30"],
                 "holders": {"Individual": 60.0, "Mutual Funds": 40.0}},
        "BBBB": {"report_date": "2026-09-30", "window": ["2026-03-31", "2026-09-30"],
                 "holders": {"Individual": 100.0}},
    }))
    return fi.Stores(tmp_path / "idxscape.duckdb", tmp_path / "ksei.duckdb", idxm)


def test_foreign_flow_counts(tmp_path):
    f = fi.build(stores(tmp_path))["foreign_flow"]
    assert (f["status"], f["first"], f["last"], f["days"], f["codes"]) == (
        "present", "2026-01-05", "2026-01-09", 5, 3)
    assert f["rows"] == 15 and f["rows_with_foreign_trade"] == 10
    assert f["codes_with_foreign_trade"] == 2
    assert f["net_value_zero_when_shares_nonzero"] == 0
    assert f["non_regular_share_of_value"] == round(900 / 15000, 4)
    assert f["name_days_non_regular_over_half"] == 1


def test_cross_check_sign_agreement_and_worst_names(tmp_path):
    c = fi.build(stores(tmp_path), min_days=3)["cross_check"]
    assert (c["names"], c["name_days"], c["both_nonzero"]) == (2, 10, 10)
    assert c["sign_agreement"] == 0.5
    assert c["median_abs_ratio"] == 0.96  # |idx-method| / |idxscape|, lower median
    assert c["worst"][0] == {"code": "CCCC", "days": 5, "sign_agreement": 0.0}
    assert c["names_below_80pct"] == 1


def test_kseistat_months_types_and_load_lag(tmp_path):
    k = fi.build(stores(tmp_path))["ownership"]
    assert (k["months"], k["first"], k["last"]) == (2, "2026-08-31", "2026-09-30")
    assert k["codes_latest"] == 2
    assert k["investor_types"] == {"foreign": ["IB"], "local": ["ID"]}
    assert k["months_with_load_date"] == 1 and k["median_load_lag_days"] == 5
    assert k["stock_view"] is True


def test_insider_actions_and_parse_share(tmp_path):
    i = fi.build(stores(tmp_path))["insider"]
    assert (i["rows"], i["first"], i["last"], i["symbols"]) == (3, "2025-03-01", "2026-01-07", 2)
    assert i["actions"] == {"ACTION_TYPE_BUY": 1, "ACTION_TYPE_MESOP_OPTION": 1,
                            "ACTION_TYPE_SELL": 1}
    assert i["market_trades"] == 2 and i["changes_parsed"] == 2
    assert i["sources"] == {"IDX": 2, "KSEI": 1}


def test_register_broker_top_and_screeners(tmp_path):
    out = fi.build(stores(tmp_path))
    r = out["register"]
    assert (r["names"], r["report_dates"]) == (2, {"2026-09-30": 1, "2026-10-30": 1})
    assert r["labels"]["Individual"] == 2
    assert out["broker_top"] == {"status": "present", "days": 2, "first": "2026-11-10",
                                 "last": "2026-11-11"}
    s = out["screeners"]
    assert (s["days"], s["screeners"], s["names_latest"]) == (1, ["Foreign Flow: Net buy"], 1)


def test_missing_stores_are_reported_not_fatal(tmp_path):
    out = fi.build(fi.Stores(tmp_path / "no.duckdb", tmp_path / "no2.duckdb", tmp_path / "none"))
    for leg in ("foreign_flow", "cross_check", "ownership", "insider", "register", "broker_top",
                "screeners"):
        assert out[leg]["status"] == "missing", leg
    assert {v["verdict"] for v in out["legs"].values()} == {"no data"}


def test_leg_verdicts_use_fixed_minimums(tmp_path):
    legs = fi.build(stores(tmp_path))["legs"]
    assert legs["accumulation"]["verdict"] == "too short"  # 5 days against MIN_FLOW_DAYS
    assert legs["ownership"]["verdict"] == "too short"
    assert legs["insider"]["verdict"] == "too short"
    assert legs["supply_demand"]["verdict"] == "too short"
    ok = fi.verdicts({"foreign_flow": {"status": "present", "days": fi.MIN_FLOW_DAYS},
                      "cross_check": {"status": "present", "sign_agreement": 0.95},
                      "bars": {"status": "present", "days": fi.MIN_FLOW_DAYS},
                      "ownership": {"status": "present", "months": fi.MIN_KSEI_MONTHS},
                      "insider": {"status": "present", "market_trades": fi.MIN_INSIDER_TRADES,
                                  "changes_parsed": fi.MIN_INSIDER_TRADES}})
    assert {v["verdict"] for v in ok.values()} == {"usable"}
    bad = fi.verdicts({"foreign_flow": {"status": "present", "days": fi.MIN_FLOW_DAYS},
                       "cross_check": {"status": "present", "sign_agreement": 0.6}})
    assert bad["accumulation"]["verdict"] == "check first"


def test_markdown_names_every_section(tmp_path):
    md = fi.markdown(fi.build(stores(tmp_path), min_days=3), date(2026, 11, 17))
    for head in ("# P126", "## Legs", "## Foreign flow", "## Cross-check", "## Ownership",
                 "## Insider", "## Shareholder register", "## Broker top", "## Screeners"):
        assert head in md
    assert "CCCC" in md.split("## Cross-check")[1].split("## ")[0]


def test_cli_writes_the_report_and_exits_zero_without_stores(tmp_path, capsys):
    from assist import cli

    out = tmp_path / "P126.md"
    assert cli.main(["--siblings-root", str(tmp_path), "flow-inventory", "--out", str(out)]) == 0
    assert "## Legs" in out.read_text()
    assert "accumulation: no data" in capsys.readouterr().out
