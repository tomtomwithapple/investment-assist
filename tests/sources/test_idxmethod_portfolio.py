"""idx-method's live Stockbit portfolios over financer (`sources.idxmethod_portfolio`).

A live `portfolio/<account>/latest.json` replaces financer's statement of the same Stockbit
account when it is at least as new, is added when financer has none, and is ignored when older.
Its cash counts unless financer already has a loaded RDN statement of the same owner. Made-up
numbers; the file shape is idx-method `securities.py` schema 1."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from assist.layers.portfolio import build_portfolio
from assist.sources.financer import Holding, Statement
from assist.sources.idxmethod_portfolio import LivePortfolioSource, read_live


def _live(root: Path, name: str = "priskila", as_of: str = "2026-11-18", **kw) -> Path:
    doc = {"schema": 1, "account": name, "as_of": as_of, "broker_account": "4848825",
           "portfolio_name": "PRISKILA", "cash_idr": 1000.0, "equity_idr": 4000.0,
           "positions": [
               {"symbol": "ICBP", "name": "Indofood CBP", "shares": 300, "avg_price": 5000.0,
                "last_price": 7050.0, "invested_idr": 1500000.0, "market_value_idr": 2115000.0},
               {"symbol": "ACES", "name": "Ace", "shares": 1100, "avg_price": 330.495,
                "last_price": 350.0, "invested_idr": 363544.5, "market_value_idr": 385000.0},
               {"symbol": "XXXX", "shares": 0, "market_value_idr": 0.0}]}
    doc.update(kw)
    d = root / "portfolio" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(doc))
    return root


class Fin:
    def __init__(self, statements, owners=()):
        self._s, self._o = list(statements), list(owners)

    def statements(self):
        return list(self._s)

    def owner_map(self):
        return self._o

    def movements(self):
        return ["passed through"]


TRADES = Statement("stockbit", "4848825", "trades", date(2026, 10, 30), None, None, None,
                   (Holding("BBNI", "", "200", 600000.0, "IDR"),), owner="priskila",
                   trade_docs=8, priced_at_trade=("BBNI",))
MANDIRI = Statement("mandiri_consolidated", "6353", "savings_statement", date(2026, 9, 30),
                    2663.15, None, None, (), owner="priskila")
OWNERS = [("stockbit", "4848825", "priskila")]


def test_live_replaces_financer_account(tmp_path: Path):
    src = LivePortfolioSource(Fin([TRADES, MANDIRI], OWNERS), _live(tmp_path))
    got = {s.account: s for s in src.statements()}
    live = got["4848825"]
    assert (live.doc_type, live.source, live.owner) == ("live", "idx-method", "priskila")
    assert [h.symbol for h in live.holdings] == ["ACES", "ICBP"]  # zero line dropped
    assert live.holdings_idr == 2500000.0
    assert live.cash_idr == 1000.0 and live.broker_cash_idr is None
    icbp = next(h for h in live.holdings if h.symbol == "ICBP")
    assert (icbp.avg_cost, icbp.cost_value) == (5000.0, 1500000.0)
    assert got["6353"] is MANDIRI


def test_older_live_file_leaves_financer(tmp_path: Path):
    src = LivePortfolioSource(Fin([TRADES], OWNERS), _live(tmp_path, as_of="2026-10-01"))
    assert src.statements() == [TRADES]


def test_unknown_account_is_added_with_the_file_owner(tmp_path: Path):
    src = LivePortfolioSource(Fin([MANDIRI]), _live(tmp_path))
    live = {s.account: s for s in src.statements()}["4848825"]
    assert live.owner == "priskila"


def test_cash_not_counted_when_owner_has_an_rdn_statement(tmp_path: Path):
    rdn = Statement("bca_rdn", "4750", "savings_statement", date(2026, 10, 31), 1000.0, None,
                    None, (), owner="priskila")
    src = LivePortfolioSource(Fin([TRADES, rdn], OWNERS), _live(tmp_path))
    live = {s.account: s for s in src.statements()}["4848825"]
    assert live.cash_idr is None and live.broker_cash_idr == 1000.0


def test_no_files_is_financer_alone(tmp_path: Path):
    assert LivePortfolioSource(Fin([TRADES]), tmp_path).statements() == [TRADES]
    assert LivePortfolioSource(Fin([TRADES]), None).statements() == [TRADES]


def test_bad_or_other_schema_files_are_skipped(tmp_path: Path):
    _live(tmp_path, schema=2)
    (tmp_path / "portfolio" / "x").mkdir()
    (tmp_path / "portfolio" / "x" / "latest.json").write_text("{not json")
    assert read_live(tmp_path) == []


def test_other_calls_pass_through(tmp_path: Path):
    assert LivePortfolioSource(Fin([]), tmp_path).movements() == ["passed through"]


def test_layer5_notes_and_sources(tmp_path: Path):
    src = LivePortfolioSource(Fin([TRADES, MANDIRI], OWNERS), _live(tmp_path))
    p = build_portfolio(src.statements())
    assert p.buckets_idr[("IDN", "stocks")] == 2500000.0
    assert round(p.buckets_idr[("IDN", "cash")], 2) == 3663.15
    assert "idx-method stockbit (priskila): live from Stockbit on 2026-11-18" in p.notes
    assert not any("last trade price" in n for n in p.notes)
    assert p.weights().sources == ("financer", "idx-method")
