"""financer adapter, schema 9 (P53, PLAN S32): each account's latest loaded statement rolled
forward through the loaded `trades` documents dated after it, with the document's owner.

Fixture: `tests/fixtures/financer/` (made-up accounts; expected numbers in `seed.sql`)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from helpers import FIXTURES, make_sqlite

from assist.sources.financer import FinancerSource, Statement

FIX = FIXTURES / "financer"


def _db(tmp_path: Path, *files: str, extra: str = "") -> FinancerSource:
    ddl = "".join((FIX / f).read_text() for f in files) + extra
    return FinancerSource(make_sqlite(tmp_path / "financer.db", ddl))


@pytest.fixture
def got(tmp_path: Path) -> dict[str, Statement]:
    src = _db(tmp_path, "schema.sql", "seed.sql")
    return {s.account: s for s in src.statements()}


def _held(s: Statement) -> dict[str, tuple[str, float]]:
    return {h.symbol: (h.quantity, h.value) for h in s.holdings}


def test_account_with_trades_only_starts_from_nothing(got):
    pris = got["SB-PRIS"]
    assert pris.issuer == "stockbit" and pris.owner == "priskila"
    assert pris.rolled_from is None
    assert pris.trade_docs == 2  # the superseded confirmation is not one of them
    assert pris.as_of == date(2026, 10, 20)
    # BBRI 100 + 100 at the last price 4,200; GOTO bought and sold to zero is dropped;
    # the superseded document's 9,900 BBRI never count
    assert _held(pris) == {"BBRI": ("200", 840_000.0)}
    assert pris.priced_at_trade == ("BBRI",)
    assert pris.stated_value_idr is None and pris.cash_idr is None


def test_sell_below_zero_is_kept_apart(got):
    pris = got["SB-PRIS"]
    assert [(h.symbol, h.quantity, h.value) for h in pris.unheld] == [("ADRO", "-100", -250_000.0)]
    assert pris.holdings_idr == 840_000


def test_statement_rolled_through_later_dailies(got):
    two = got["AJ-TWO"]
    assert two.owner == "tommy"
    assert two.rolled_from == date(2026, 9, 30)
    assert two.as_of == date(2026, 10, 3)
    # the 09-30 daily is on the statement date, so already in it: 2 documents, not 3
    assert two.trade_docs == 2
    assert _held(two) == {"UNVR": ("200", 420_000.0)}  # ARNA sold to zero, gone
    assert two.priced_at_trade == ("UNVR",)
    assert two.stated_value_idr == 700_000
    assert two.statement_holdings_idr == 700_000  # the statement's own lines, before rolling


def test_unchanged_line_keeps_the_statement_value(tmp_path):
    extra = """
    INSERT INTO documents (id, sha256, file_name, issuer, parser_id, doc_type, statement_date,
        currency, number_locale, opening_minor, closing_minor, reconciled, status, account_ref,
        account_kind) VALUES
    (30, 'x1', 'x.pdf', 'ajaib', 'ajaib_daily_v1', 'trades', '2026-10-05', 'IDR', 'id',
        0, 0, 1, 'loaded', 'AJ-TEST', 'asset');
    INSERT INTO trades (document_id, trade_date, reference, symbol, side, board, quantity,
        price_minor, gross_minor, net_minor, fees_minor, currency, dedup_key) VALUES
    (30, '2026-10-05', 'X', 'TLKM', 'buy', 'RG', '100', 300000, 30000000, 30000000, 0, 'IDR', 'x');
    """
    src = _db(tmp_path, "schema.sql", "seed.sql", extra=extra)
    aj = {s.account: s for s in src.statements()}["AJ-TEST"]
    held = _held(aj)
    assert held["BBCA"] == ("100", 600_000.0)  # unchanged: the statement's value
    assert held["TLKM"] == ("100", 300_000.0)  # new: last trade price
    assert aj.priced_at_trade == ("TLKM",)
    assert aj.doc_type == "portfolio"


def test_accounts_without_trades_are_as_before(got):
    aj = got["AJ-TEST"]
    assert aj.owner == "tommy" and aj.trade_docs == 0 and aj.rolled_from is None
    assert aj.priced_at_trade == () and aj.unheld == ()
    assert aj.as_of == date(2026, 9, 30) and aj.holdings_idr == 850_000


def test_schema8_falls_back_to_tommy(tmp_path):
    src = _db(tmp_path, "schema.sql", "seed.sql", "schema8.sql")
    sts = src.statements()
    assert {s.owner for s in sts} == {"tommy"}
    assert {s.account: s for s in sts}["SB-PRIS"].holdings_idr == 840_000


def test_store_without_a_trades_table_reads_statements_only(tmp_path):
    src = _db(tmp_path, "schema.sql", "seed.sql", "schema8.sql", extra="DROP TABLE trades;")
    by = {s.account: s for s in src.statements()}
    assert "SB-PRIS" not in by
    assert by["AJ-TWO"].trade_docs == 0
    assert {h.symbol for h in by["AJ-TWO"].holdings} == {"ARNA", "UNVR"}


def test_rows_include_rolled_holdings(tmp_path):
    src = _db(tmp_path, "schema.sql", "seed.sql")
    by_id = {r.series_id: r for r in src.rows()}
    assert by_id["HOLDING.BBRI"].value == 840_000
    assert by_id["HOLDING.BBRI"].date == date(2026, 10, 20)
    assert by_id["HOLDING.UNVR"].value == 420_000
    assert "HOLDING.ARNA" not in by_id and "HOLDING.ADRO" not in by_id


def test_positional_statement_still_builds():
    """Callers that build a Statement by position (layer-4 tests) keep working."""
    s = Statement("ajaib", "A", "portfolio", date(2026, 9, 30), None, None, None, ())
    assert s.owner == "tommy" and s.trade_docs == 0 and s.unheld == ()


# ---------------- movements (PLAN S38, P58-flows) ----------------

FLOWS = FIXTURES / "flows"


def _flows(tmp_path: Path) -> FinancerSource:
    extra = (FLOWS / "transactions.sql").read_text() + (FLOWS / "seed.sql").read_text()
    return _db(tmp_path, "schema.sql", extra=extra)


def test_movements_read_loaded_documents_only(tmp_path):
    ms = _flows(tmp_path).movements()
    docs = {m.document_id for m in ms}
    assert docs == {101, 102, 103, 105, 106, 107, 108, 109, 110}  # 104 and 111 superseded
    assert all(m.amount_minor > 0 for m in ms)
    assert ms == sorted(ms, key=lambda m: (m.date, m.document_id, m.ref or 0))


def test_trades_document_is_one_settlement_not_its_fee_rows(tmp_path):
    ms = _flows(tmp_path).movements()
    aj = [m for m in ms if m.document_id == 105]
    assert len(aj) == 1
    m = aj[0]
    assert (m.date, m.issuer, m.account, m.owner, m.doc_type) == (
        date(2026, 10, 7), "ajaib", "AJ-3333", "tommy", "trades")
    # minus closing_minor: a buy's payment due is money the broker account receives
    assert (m.direction, m.amount_minor, m.amount, m.ref) == ("credit", 50_005_000, 500_050.0, None)
    sb = [m for m in ms if m.document_id == 110]
    assert [(m.date, m.direction, m.amount) for m in sb] == [
        (date(2026, 10, 20), "credit", 1_234_567.89)]


def test_movement_fields(tmp_path):
    ms = _flows(tmp_path).movements()
    m = next(m for m in ms if m.date == date(2026, 10, 14))
    assert (m.issuer, m.account, m.owner, m.doc_type, m.direction, m.amount) == (
        "bca_tahapan", "SAV-1111", "tommy", "savings_statement", "debit", 4_000_000.0)
    assert m.description == "TRSF E-BANKING DB 1410"
    assert "Sari Contoh" in m.raw_description
    assert isinstance(m.ref, int)


def test_movements_window(tmp_path):
    ms = _flows(tmp_path).movements(date(2026, 10, 1), date(2026, 10, 31))
    assert ms and all(date(2026, 10, 1) <= m.date <= date(2026, 10, 31) for m in ms)
    assert 101 not in {m.document_id for m in ms}


def test_movements_without_a_transactions_table(tmp_path):
    """The S32 fixture has no transactions table and trade documents with a zero closing."""
    assert _db(tmp_path, "schema.sql", "seed.sql").movements() == []


def test_ledgers_and_owner_map(tmp_path):
    src = _flows(tmp_path)
    led = {(x.issuer, x.account, x.statement_date): x for x in src.ledgers()}
    sav = led[("bca_tahapan", "SAV-1111", date(2026, 10, 31))]
    assert (sav.owner, sav.opening, sav.closing, sav.period_start) == (
        "tommy", 11_000_000.0, 9_000_000.0, date(2026, 10, 1))
    assert ("bca_rdn", "RDN-2222", date(2026, 10, 31)) in led
    assert not any(x.doc_type == "trades" for x in led.values())
    assert sum(1 for x in led.values() if x.account == "RDN-2222") == 1  # superseded skipped
    assert ("bca_rdn", "RDN-9999", "priskila") in src.owner_map()
