"""Portfolio, layer 5 (P4, PLAN S4; P53, PLAN S32): financer's latest statement per account,
rolled forward through the trade documents after it → weights by country × asset class. IDX
tickers → IDN stocks, SBN codes → IDN bonds, RDN/bank cash → IDN cash; anything else is listed
as unmapped, never guessed.

The adapter runs over a tiny SQLite store built from `tests/fixtures/financer/` (the real
`documents` and `holdings` schema, made-up statements). Expected numbers are in `seed.sql`."""

from __future__ import annotations

import os
import stat
from datetime import date
from pathlib import Path

import pytest
from helpers import FIXTURES, make_sqlite

from assist.layers.portfolio import (
    build_portfolio,
    classify,
    current_weights,
)
from assist.layers.types import Weights
from assist.sources.base import Row, Source, SourceUnavailable
from assist.sources.financer import FinancerSource, Holding, Statement

FIX = FIXTURES / "financer"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    ddl = (FIX / "schema.sql").read_text() + (FIX / "seed.sql").read_text()
    return make_sqlite(tmp_path / "financer.db", ddl)


@pytest.fixture
def src(db: Path) -> FinancerSource:
    return FinancerSource(db)


def _by_account(statements: list[Statement]) -> dict[str, Statement]:
    return {s.account: s for s in statements}


# ---------------- classify ----------------


@pytest.mark.parametrize(
    "symbol, expected",
    [
        ("BBCA", ("IDN", "stocks")),
        ("TLKM", ("IDN", "stocks")),
        ("INCO-R", ("IDN", "stocks")),  # IDX rights issue
        ("BUKA-W", ("IDN", "stocks")),  # IDX warrant
        ("FR0081", ("IDN", "bonds")),
        ("FR0040", ("IDN", "bonds")),
        ("PBS036", ("IDN", "bonds")),
        ("ORI025T3", ("IDN", "bonds")),
        ("SR018T3", ("IDN", "bonds")),
        ("ST012T2", ("IDN", "bonds")),
        ("SBR013T2", ("IDN", "bonds")),
        ("SPN12260101", ("IDN", "bonds")),
        ("VR0031", ("IDN", "bonds")),
        ("IDR", ("IDN", "cash")),
        ("", None),  # mutual fund printed without a code
        ("AAPL1", None),
        ("BBCA.JK", None),
        ("bbca", None),
        ("FR", None),
    ],
)
def test_classify(symbol, expected):
    assert classify(symbol) == expected


def test_classify_refuses_foreign_currency():
    assert classify("BBCA", "USD") is None
    assert classify("IDR", "USD") is None


# ---------------- adapter ----------------


def test_source_protocol(src):
    assert isinstance(src, Source)
    assert src.name == "financer"


def test_latest_loaded_statement_per_account(src):
    got = _by_account(src.statements())
    # no credit card; SB-PRIS has trade documents only
    assert set(got) == {"AJ-TEST", "AJ-TWO", "RDN-TEST", "MS-TEST", "SB-TEST", "BN-TEST",
                        "SB-PRIS"}
    assert got["AJ-TEST"].as_of == date(2026, 9, 30)
    # the superseded October statement is ignored
    assert got["RDN-TEST"].as_of == date(2026, 9, 30)
    assert got["RDN-TEST"].cash_idr == 300_000
    # sold out: the latest statement holds nothing, so older holdings do not carry forward
    assert got["MS-TEST"].as_of == date(2026, 9, 30)
    assert got["MS-TEST"].holdings == ()


def test_money_is_minor_units_over_100(src):
    aj = _by_account(src.statements())["AJ-TEST"]
    assert aj.holdings[0] == Holding("BBCA", "BANK CENTRAL ASIA Tbk", "100", 600_000.0, "IDR")
    assert aj.stated_value_idr == 850_000
    assert aj.holdings_idr == 850_000


def test_broker_cash_is_not_counted_as_cash(src):
    """A broker statement's closing balance is the RDN, which the bank statement already counts."""
    got = _by_account(src.statements())
    assert got["AJ-TEST"].cash_idr is None
    assert got["AJ-TEST"].broker_cash_idr == 300_000


def test_rows_are_tidy(src):
    rows = src.rows()
    assert all(isinstance(r, Row) and r.source == "financer" for r in rows)
    by_id = {r.series_id: r for r in rows}
    assert by_id["HOLDING.BBCA"].value == 600_000
    assert by_id["HOLDING.BBCA"].date == date(2026, 9, 30)
    assert by_id["CASH.IDR"].value == 300_000
    assert "HOLDING.ASII" not in by_id
    assert src.rows(series_ids=["CASH.IDR"]) == [by_id["CASH.IDR"]]
    recent = {r.series_id for r in src.rows(start=date(2026, 7, 1))}
    assert "HOLDING.TLKM" not in recent and "HOLDING.BBCA" in recent


def test_missing_store(tmp_path):
    with pytest.raises(SourceUnavailable) as e:
        FinancerSource(tmp_path / "nope.db").statements()
    assert e.value.reason == "missing"


def test_reads_a_read_only_file_without_writing(db):
    os.chmod(db, stat.S_IRUSR)
    before = db.stat().st_mtime_ns
    try:
        assert FinancerSource(db).statements()
    finally:
        os.chmod(db, stat.S_IRUSR | stat.S_IWUSR)
    assert db.stat().st_mtime_ns == before
    assert sorted(p.name for p in db.parent.iterdir()) == ["financer.db"]


# ---------------- layer 5 ----------------


def test_buckets_and_weights(src):
    p = build_portfolio(src.statements())
    assert p.as_of == date(2026, 10, 20)  # the latest trade document
    assert p.buckets_idr == {
        ("IDN", "stocks"): 1_960_000,
        ("IDN", "bonds"): 299_000,
        ("IDN", "cash"): 301_000,
    }
    assert p.total_idr == 2_560_000
    w = p.weights()
    assert isinstance(w, Weights)
    assert w.total_idr == 2_560_000
    assert sum(w.weights.values()) == pytest.approx(100)
    assert w.pct("IDN", "stocks") == pytest.approx(1960 / 25.6)
    assert w.pct("IDN", "bonds") == pytest.approx(299 / 25.6)
    assert w.pct("IDN", "cash") == pytest.approx(301 / 25.6)
    assert w.pct("USA", "stocks") is None


def test_unmapped_listed_not_counted(src):
    p = build_portfolio(src.statements())
    w = p.weights()
    assert len(w.unmapped) == 2
    fund = next(u for u in w.unmapped if "REKSA DANA" in u)
    assert "REKSA DANA INDEKS BNI AM INDEKS IDX30" in fund and "ajaib" in fund
    assert "(Rp50,000)" in fund


def test_statement_totals_match_broker(src):
    checks = {c.account: c for c in build_portfolio(src.statements()).checks}
    assert checks["AJ-TEST"].matches is True
    assert checks["SB-TEST"].matches is True
    assert checks["BN-TEST"].matches is None  # no stated total on the statement


def test_stale_account_still_holding_is_flagged(src):
    p = build_portfolio(src.statements())
    assert p.stale_inputs == ("financer bnisek (statement 2026-06-30)",)
    assert p.weights().stale_inputs == p.stale_inputs


def test_old_empty_account_is_not_stale():
    s = [
        Statement("ajaib", "A", "portfolio", date(2026, 9, 30), None, 100.0, 0.0,
                  (Holding("BBCA", "x", "1", 100.0, "IDR"),)),
        Statement("bnisek", "B", "broker_soa", date(2026, 1, 31), None, None, 0.0, ()),
    ]
    assert build_portfolio(s).stale_inputs == ()


def test_empty_portfolio():
    p = build_portfolio([])
    assert p.total_idr == 0
    assert p.weights().weights == {}


def test_current_weights_turns_missing_store_into_stale(tmp_path, src):
    w, stale = current_weights(FinancerSource(tmp_path / "nope.db"))
    assert w is None and stale == ["financer (missing)"]
    w, stale = current_weights(src)
    assert w is not None and w.total_idr == 2_560_000
    assert stale == ["financer bnisek (statement 2026-06-30)"]


# ---------------- S32: trade documents and owners ----------------


def test_by_owner_splits_the_household_and_adds_up(src):
    p = build_portfolio(src.statements())
    assert p.by_owner == {
        "tommy": {("IDN", "stocks"): 1_120_000, ("IDN", "bonds"): 299_000,
                  ("IDN", "cash"): 301_000},
        "priskila": {("IDN", "stocks"): 840_000},
    }
    assert sum(sum(b.values()) for b in p.by_owner.values()) == pytest.approx(p.total_idr)


def test_sold_out_line_is_gone_and_new_lines_count(src):
    p = build_portfolio(src.statements())
    assert not any("ARNA" in u for u in p.weights().unmapped)
    held = {h.symbol for s in src.statements() for h in s.holdings}
    assert "ARNA" not in held and {"UNVR", "BBRI"} <= held


def test_negative_line_is_unmapped_never_subtracted(src):
    p = build_portfolio(src.statements())
    adro = [(label, v) for label, v in p.unmapped if label.startswith("ADRO")]
    assert len(adro) == 1
    label, value = adro[0]
    assert value == -250_000 and "stockbit" in label and "-100" in label
    assert p.buckets_idr[("IDN", "stocks")] == 1_960_000  # ADRO not subtracted


def test_rolled_check_compares_the_statement_before_rolling(src):
    checks = {c.account: c for c in build_portfolio(src.statements()).checks}
    two = checks["AJ-TWO"]
    assert two.as_of == date(2026, 9, 30)
    assert two.holdings_idr == 700_000 and two.stated_idr == 700_000 and two.matches is True
    assert "SB-PRIS" not in checks  # no statement, nothing to check


def test_notes_name_lines_valued_at_trade_price(src):
    p = build_portfolio(src.statements())
    assert p.notes == (
        "financer ajaib (tommy): valued at last trade price: 1 lines",
        "financer stockbit (priskila): valued at last trade price: 1 lines",
    )
    w = p.weights()
    assert w.notes == p.notes
    assert not any("trade price" in x for x in w.stale_inputs)


def test_statement_only_numbers_are_unchanged(src):
    """Accounts with no trades after their statement give the same numbers as before S32."""
    only = [s for s in src.statements() if s.trade_docs == 0]
    p = build_portfolio(only)
    assert p.buckets_idr == {("IDN", "stocks"): 700_000, ("IDN", "bonds"): 299_000,
                             ("IDN", "cash"): 301_000}
    assert p.notes == ()


def test_schema8_store_falls_back_to_one_owner(tmp_path):
    ddl = "".join((FIX / f).read_text() for f in ("schema.sql", "seed.sql", "schema8.sql"))
    p = build_portfolio(FinancerSource(make_sqlite(tmp_path / "f8.db", ddl)).statements())
    assert set(p.by_owner) == {"tommy"}
    assert p.total_idr == 2_560_000


def test_rerun_gives_byte_identical_stance_json(src):
    from assist.layers.types import AssetScore
    from assist.stance import build_stance, dumps

    score = AssetScore(subject="IDN", asset="stocks", as_of=date(2026, 10, 20), score=55.0,
                       confidence=0.9, source="worldbankscape")
    texts = [dumps(build_stance(score=score, regime=None,
                                weights=build_portfolio(src.statements()).weights(),
                                fingerprint="sha256:" + "0" * 64))
             for _ in range(2)]
    assert texts[0] == texts[1]
    assert "valued at last trade price" in texts[0]
