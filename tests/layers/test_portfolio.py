"""Portfolio, layer 5 (P4, PLAN S4): financer's latest statement per account → weights by
country × asset class. IDX tickers → IDN stocks, SBN codes → IDN bonds, RDN/bank cash → IDN cash;
anything else is listed as unmapped, never guessed.

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


def _by_issuer(statements: list[Statement]) -> dict[str, Statement]:
    return {s.issuer: s for s in statements}


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
    got = _by_issuer(src.statements())
    assert set(got) == {"ajaib", "bca_rdn", "mandirisek", "stockbit", "bnisek"}  # no credit card
    assert got["ajaib"].as_of == date(2026, 9, 30)
    # the superseded October statement is ignored
    assert got["bca_rdn"].as_of == date(2026, 9, 30)
    assert got["bca_rdn"].cash_idr == 300_000
    # sold out: the latest statement holds nothing, so older holdings do not carry forward
    assert got["mandirisek"].as_of == date(2026, 9, 30)
    assert got["mandirisek"].holdings == ()


def test_money_is_minor_units_over_100(src):
    aj = _by_issuer(src.statements())["ajaib"]
    assert aj.holdings[0] == Holding("BBCA", "BANK CENTRAL ASIA Tbk", "100", 600_000.0, "IDR")
    assert aj.stated_value_idr == 850_000
    assert aj.holdings_idr == 850_000


def test_broker_cash_is_not_counted_as_cash(src):
    """A broker statement's closing balance is the RDN, which the bank statement already counts."""
    got = _by_issuer(src.statements())
    assert got["ajaib"].cash_idr is None
    assert got["ajaib"].broker_cash_idr == 300_000


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
    assert p.as_of == date(2026, 9, 30)
    assert p.buckets_idr == {
        ("IDN", "stocks"): 700_000,
        ("IDN", "bonds"): 299_000,
        ("IDN", "cash"): 301_000,
    }
    assert p.total_idr == 1_300_000
    w = p.weights()
    assert isinstance(w, Weights)
    assert w.total_idr == 1_300_000
    assert sum(w.weights.values()) == pytest.approx(100)
    assert w.pct("IDN", "stocks") == pytest.approx(700 / 13)
    assert w.pct("IDN", "bonds") == pytest.approx(299 / 13)
    assert w.pct("IDN", "cash") == pytest.approx(301 / 13)
    assert w.pct("USA", "stocks") is None


def test_unmapped_listed_not_counted(src):
    p = build_portfolio(src.statements())
    assert p.unmapped_idr == 50_000
    w = p.weights()
    assert len(w.unmapped) == 1
    assert "REKSA DANA INDEKS BNI AM INDEKS IDX30" in w.unmapped[0]
    assert "ajaib" in w.unmapped[0]


def test_statement_totals_match_broker(src):
    checks = {c.issuer: c for c in build_portfolio(src.statements()).checks}
    assert checks["ajaib"].matches is True
    assert checks["stockbit"].matches is True
    assert checks["bnisek"].matches is None  # no stated total on the statement


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
    assert w is not None and w.total_idr == 1_300_000
    assert stale == ["financer bnisek (statement 2026-06-30)"]
