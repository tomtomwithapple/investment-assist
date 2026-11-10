"""financer adapter: the user's broker, RDN and bank statements in `~/.financer/financer.db`.

Opened read-only (`mode=ro` URI through `sqlite_ro`); financer's bot and ingest jobs may hold the
file, and nothing here ever writes to it. Schema as found on 2026-10-23 (financer schema version
8), which differs from the sketch in financer's PLAN.md §3: there is no `accounts` table and
`holdings` has no account id. The account is `documents.account_ref` (with `issuer`), and a
holding belongs to the statement (`document_id`) that printed it.

- One `Statement` per account: its **latest loaded** statement (`status = 'loaded'`; superseded
  ones are skipped). Holdings come from that statement only, so an account that sold out shows
  nothing even though an older statement listed positions.
- Broker statements (`portfolio`, `broker_soa`) give holdings; savings statements give cash
  (`closing_minor`). A broker statement's own closing balance is its RDN, which the RDN's bank
  statement already counts, so it is kept apart as `broker_cash_idr` and never added as cash.
  Credit-card statements are liabilities, not holdings, and are not read.
- Money is integer minor units at scale 100 (financer `money.MINOR_SCALE`); values here are IDR.

Since PLAN S32 (financer slices 12-13, schema 9) an account's holdings are **rolled forward**
from its latest loaded broker statement through the loaded `trades` documents (Stockbit trade
confirmations, Ajaib dailies) with a `statement_date` after that statement's; an account with
trade documents and no statement starts from nothing. financer marks a `trades` document
`superseded` once an SOA of the same account prints all its orders, so `status = 'loaded'`
already leaves out every trade a statement states. A buy adds `quantity` (shares), a sell
subtracts it; a changed or new line is valued at the last trade price of the symbol in those
documents (there is no price feed here), an unchanged line keeps the statement's value. A line
that reaches zero is dropped; one below zero (a sell of a position no statement shows) is kept
apart in `unheld`, never in `holdings`. Each `Statement` carries the document's `owner`
(`documents.owner`; `'tommy'` on a schema-8 store without the column).

Since PLAN S38 (`assist.flows`) `movements()` reads the money that moved: every row of
`transactions` of a loaded document of any type, except that a `trades` document (a Stockbit TC,
an Ajaib daily) yields **one** movement, its settlement: minus `closing_minor` (a buy's payment
due is a credit to the broker account, a sale's proceeds a debit) dated on its trades'
`settle_date`; its fee rows are parts of that payment. `ledgers()` gives each loaded statement's
opening and closing, and `owner_map()` financer's `account_owners`. An account is
`coalesce(nullif(account_ref, ''), card_last4, '')`, so a card with no account ref is its last 4.

Since PLAN S67 a `Holding` carries its cost basis: `avg_cost` (per unit) and `cost_value`, from
the statement's `avg_cost_minor` and `cost_value_minor`; a printed average of 0 (an SBN line, a
right) is no cost at all, so both are None. `roll` carries it through the trades: a buy adds its
`net_minor` (the amount paid, fees included) to the cost, a sell takes cost out in proportion to
the quantity sold, so the average stays. A position the trades open gets its cost from its buys.
The cost stays None when any statement line of the symbol has none, and becomes None once the
line was sold below zero (what was sold had a cost nobody printed). Nothing reads it yet.

`rows()` gives the tidy view: `HOLDING.<symbol>` (market value of IDR lines, summed across
accounts) and `CASH.IDR`, dated by the statement (or its latest trade document). Layer 5
(`assist.layers.portfolio`) uses `statements()`.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, sqlite_ro

__all__ = ["BROKER_DOC_TYPES", "CARD_DOC_TYPE", "CASH_DOC_TYPES", "DEFAULT_OWNER", "SOURCE",
           "TRADE_DOC_TYPE", "FinancerSource", "Holding", "Ledger", "Movement", "Statement"]

SOURCE = "financer"
MINOR_SCALE = 100
BROKER_DOC_TYPES = ("portfolio", "broker_soa")
CASH_DOC_TYPES = ("savings_statement",)
TRADE_DOC_TYPE = "trades"
CARD_DOC_TYPE = "credit_card_statement"
DEFAULT_OWNER = "tommy"  # financer schema 8 has no documents.owner: every document is his
UNKNOWN_OWNER = "unknown"  # owner NULL: financer could not tell (held for review there)

_LATEST = """
with ranked as (
    select d.*, row_number() over (
        partition by d.issuer, coalesce(d.account_ref, '') order by d.statement_date desc, d.id desc
    ) as rn
    from documents d
    where d.status = 'loaded'
      and d.doc_type in ({types})
)
select id, issuer, coalesce(account_ref, ''), doc_type, statement_date, currency,
       closing_minor, portfolio_value_minor, {owner}
from ranked where rn = 1
order by issuer, account_ref
""".replace("{types}", ", ".join(f"'{t}'" for t in BROKER_DOC_TYPES + CASH_DOC_TYPES))

_TRADE_DOCS = f"""
select id, issuer, coalesce(account_ref, ''), statement_date, {{owner}}
from documents where status = 'loaded' and doc_type = '{TRADE_DOC_TYPE}'
order by issuer, coalesce(account_ref, ''), statement_date, id
"""

_TRADES = """
select document_id, symbol, side, quantity, price_minor, currency, net_minor
from trades where document_id in ({marks}) order by trade_date, document_id, id
"""

_HOLDINGS = """
select document_id, symbol, name, quantity, market_value_minor, currency, avg_cost_minor,
       cost_value_minor
from holdings where document_id in ({marks}) order by document_id, line_no
"""


_ACCOUNT = "coalesce(nullif(d.account_ref, ''), d.card_last4, '')"

_MOVEMENTS = f"""
select t.txn_date, d.issuer, {_ACCOUNT}, {{owner}}, d.doc_type, d.id, t.direction,
       t.amount_minor, t.description, t.raw_description, t.id
from transactions t join documents d on d.id = t.document_id
where d.status = 'loaded' and d.doc_type <> '{TRADE_DOC_TYPE}' and t.amount_minor <> 0
"""

_SETTLEMENTS = f"""
select coalesce((select max(coalesce(tr.settle_date, tr.trade_date)) from trades tr
                 where tr.document_id = d.id), d.statement_date),
       d.issuer, {_ACCOUNT}, {{owner}}, d.doc_type, d.id, d.closing_minor
from documents d
where d.status = 'loaded' and d.doc_type = '{TRADE_DOC_TYPE}' and d.closing_minor <> 0
"""

_LEDGERS = f"""
select d.issuer, {_ACCOUNT}, {{owner}}, d.doc_type, d.statement_date, d.period_start,
       d.opening_minor, d.closing_minor, d.id
from documents d
where d.status = 'loaded' and d.doc_type <> '{TRADE_DOC_TYPE}'
order by d.issuer, 2, d.statement_date, d.id
"""


class Movement(NamedTuple):
    """Money that moved in or out of one account (PLAN S38). `amount_minor` is positive, in minor
    units (scale 100); `direction` is `debit` (out) or `credit` (in). `ref` is the transactions
    row id, None for a trades document's settlement."""

    date: date
    issuer: str
    account: str
    owner: str
    doc_type: str
    document_id: int
    direction: str
    amount_minor: int
    description: str
    raw_description: str
    ref: int | None

    @property
    def amount(self) -> float:
        return self.amount_minor / MINOR_SCALE


class Ledger(NamedTuple):
    """One loaded statement's balances (not a trades document): `opening` and `closing` in IDR."""

    issuer: str
    account: str
    owner: str
    doc_type: str
    statement_date: date
    period_start: date | None
    opening: float
    closing: float


class Holding(NamedTuple):
    """One line of a broker's holdings table; `value` is the market value in `currency`.
    `avg_cost` (per unit) and `cost_value` are the cost basis (PLAN S67), None when the statement
    printed an average cost of 0 or the cost cannot be known."""

    symbol: str
    name: str
    quantity: str
    value: float
    currency: str
    avg_cost: float | None = None
    cost_value: float | None = None


class Statement(NamedTuple):
    """An account's latest loaded statement, rolled forward through its later trade documents.
    `cash_idr` is set for bank/RDN statements only; `stated_value_idr` is the portfolio total the
    broker printed (None if it printed none).

    S32 fields: `owner` of the latest document read; `rolled_from` the date of the broker
    statement the holdings start from when trades were applied (None when none were, or when the
    account has no statement); `trade_docs` how many trade documents were applied;
    `priced_at_trade` the symbols valued at a trade price; `unheld` the lines sold below zero
    (never in `holdings`); `statement_holdings_idr` the statement's own lines before rolling
    (None when nothing was rolled)."""

    issuer: str
    account: str
    doc_type: str
    as_of: date
    cash_idr: float | None
    stated_value_idr: float | None
    broker_cash_idr: float | None
    holdings: tuple[Holding, ...]
    owner: str = DEFAULT_OWNER
    rolled_from: date | None = None
    trade_docs: int = 0
    priced_at_trade: tuple[str, ...] = ()
    unheld: tuple[Holding, ...] = ()
    statement_holdings_idr: float | None = None

    @property
    def holdings_idr(self) -> float:
        return sum(h.value for h in self.holdings if h.currency == "IDR")


class Trade(NamedTuple):
    """`net` is the amount paid (buy) or received (sell), fees included; None: quantity × price."""

    symbol: str
    side: str
    quantity: Decimal
    price: float
    currency: str
    net: float | None = None


def _idr(minor: int | None) -> float | None:
    return None if minor is None else minor / MINOR_SCALE


def _qty(text: str) -> Decimal:
    q = Decimal(text)
    return q.quantize(Decimal(1)) if q == q.to_integral_value() else q.normalize()


def roll(base: Statement | None, issuer: str, account: str, owner: str, as_of: date,
         trades: Sequence[Trade], docs: int) -> Statement:
    """`base` (None: start from nothing) plus `trades` in order (PLAN S32). A symbol no trade
    touches keeps its statement lines as printed, and so does one whose trades net to nothing.

    Cost basis (PLAN S67): a symbol's lines pool their cost; a buy adds its net amount, a sell
    takes cost out in proportion (the average stays). None when a line has no cost, and from the
    moment the quantity goes below zero."""
    base_lines = base.holdings if base else ()
    traded = list(dict.fromkeys(t.symbol for t in trades))
    start = {s: sum((Decimal(h.quantity) for h in base_lines if h.symbol == s), Decimal(0))
             for s in traded}
    qty = dict(start)
    cost: dict[str, float | None] = {}
    for s in traded:
        printed = [h.cost_value for h in base_lines if h.symbol == s]
        cost[s] = None if None in printed else float(sum(printed))
    last: dict[str, Trade] = {}
    for t in trades:
        before = qty[t.symbol]
        buy = t.side == "buy"
        qty[t.symbol] = after = before + (t.quantity if buy else -t.quantity)
        last[t.symbol] = t
        c = cost[t.symbol]
        if after < 0:
            cost[t.symbol] = None
        elif c is not None and buy:
            cost[t.symbol] = c + (float(t.quantity) * t.price if t.net is None else t.net)
        elif c is not None:
            cost[t.symbol] = c * float(after / before) if before > 0 else 0.0
    held = [h for h in base_lines if h.symbol not in qty or qty[h.symbol] == start[h.symbol]]
    unheld, priced = [], []
    for sym in traded:
        q = qty[sym]
        if q == start[sym] or q == 0:
            continue  # unchanged (kept above) or sold to zero (dropped)
        t = last[sym]
        name = next((h.name for h in base_lines if h.symbol == sym), "")
        c = cost[sym] if q > 0 else None
        h = Holding(sym, name, str(_qty(str(q))), float(q) * t.price, t.currency,
                    None if c is None else c / float(q), c)
        if q < 0:
            unheld.append(h)
        else:
            held.append(h)
            priced.append(sym)
    if base is None:
        return Statement(issuer, account, TRADE_DOC_TYPE, as_of, None, None, None, tuple(held),
                         owner=owner, trade_docs=docs, priced_at_trade=tuple(sorted(priced)),
                         unheld=tuple(unheld))
    return base._replace(as_of=as_of, holdings=tuple(held), owner=owner,
                         rolled_from=base.as_of, trade_docs=docs,
                         priced_at_trade=tuple(sorted(priced)), unheld=tuple(unheld),
                         statement_holdings_idr=base.holdings_idr)


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}


def _owner_expr(con) -> str:
    """`documents.owner` (NULL read as unknown), or 'tommy' on a schema-8 store without it."""
    cols = {r[1] for r in con.execute("pragma table_info(documents)")}
    return (f"coalesce(d.owner, '{UNKNOWN_OWNER}')" if "owner" in cols
            else f"'{DEFAULT_OWNER}'")


class FinancerSource:
    """financer's SQLite store, opened read-only."""

    name = SOURCE

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> FinancerSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    def movements(self, start: date | None = None, end: date | None = None) -> list[Movement]:
        """Every movement of a loaded document dated in [start, end], ordered by date, document
        and row (PLAN S38)."""
        with sqlite_ro(self.path, self.name) as con:
            owner = _owner_expr(con)
            tables = _tables(con)
            raw = (con.execute(_MOVEMENTS.replace("{owner}", owner)).fetchall()
                   if "transactions" in tables else [])
            settled = (con.execute(_SETTLEMENTS.replace("{owner}", owner)).fetchall()
                       if "trades" in tables else [])
        out = [Movement(date.fromisoformat(d), iss, acct, own, dt, doc, direction, amt, desc,
                        rawd, ref)
               for d, iss, acct, own, dt, doc, direction, amt, desc, rawd, ref in raw]
        out += [Movement(date.fromisoformat(d), iss, acct, own, dt, doc,
                         "credit" if closing < 0 else "debit", abs(closing), "settlement",
                         "settlement", None)
                for d, iss, acct, own, dt, doc, closing in settled]
        out = [m for m in out if (start is None or m.date >= start)
               and (end is None or m.date <= end)]
        return sorted(out, key=lambda m: (m.date, m.document_id, m.ref or 0))

    def ledgers(self) -> list[Ledger]:
        """Opening and closing of every loaded statement, trades documents left out."""
        with sqlite_ro(self.path, self.name) as con:
            rows = con.execute(_LEDGERS.replace("{owner}", _owner_expr(con))).fetchall()
        return [Ledger(iss, acct, own, dt, date.fromisoformat(sd),
                       date.fromisoformat(ps) if ps else None, op / MINOR_SCALE,
                       cl / MINOR_SCALE)
                for iss, acct, own, dt, sd, ps, op, cl, _ in rows]

    def owner_map(self) -> list[tuple[str, str, str]]:
        """financer's `account_owners` as (issuer, account_ref, owner); empty before schema 9."""
        with sqlite_ro(self.path, self.name) as con:
            if "account_owners" not in _tables(con):
                return []
            return [tuple(r) for r in con.execute(
                "select issuer, account_ref, owner from account_owners order by 1, 2")]

    def statements(self) -> list[Statement]:
        with sqlite_ro(self.path, self.name) as con:
            owner = _owner_expr(con).replace("d.owner", "owner")
            docs = con.execute(_LATEST.replace("{owner}", owner)).fetchall()
            ids = [d[0] for d in docs]
            held: dict[int, list[Holding]] = defaultdict(list)
            if ids:
                sql = _HOLDINGS.format(marks=", ".join("?" for _ in ids))
                for doc_id, symbol, name, qty, value, ccy, avg, cost in con.execute(sql, ids):
                    known = bool(avg)  # a printed average of 0 is no cost basis
                    held[doc_id].append(Holding(symbol, name, qty, value / MINOR_SCALE, ccy,
                                                avg / MINOR_SCALE if known else None,
                                                cost / MINOR_SCALE if known else None))
            has_trades = con.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'trades'").fetchone()
            trade_docs = (con.execute(_TRADE_DOCS.replace("{owner}", owner)).fetchall()
                          if has_trades else [])
            trades: dict[int, list[Trade]] = defaultdict(list)
            if trade_docs:
                tids = [d[0] for d in trade_docs]
                sql = _TRADES.format(marks=", ".join("?" for _ in tids))
                for doc_id, symbol, side, qty, price, ccy, net in con.execute(sql, tids):
                    trades[doc_id].append(Trade(symbol, side, Decimal(qty), price / MINOR_SCALE,
                                                ccy, _idr(net)))
        out: dict[tuple[str, str], Statement] = {}
        for doc_id, issuer, account, doc_type, as_of, ccy, closing, stated, own in docs:
            is_cash = doc_type in CASH_DOC_TYPES
            if is_cash and ccy != "IDR":
                # foreign-currency cash: kept as a holding so layer 5 lists it as unmapped
                held[doc_id].append(Holding(ccy, f"{issuer} cash", "1", _idr(closing), ccy))
                closing = None
            out[(issuer, account)] = Statement(
                issuer=issuer,
                account=account,
                doc_type=doc_type,
                as_of=date.fromisoformat(as_of),
                cash_idr=_idr(closing) if is_cash else None,
                stated_value_idr=_idr(stated),
                broker_cash_idr=None if is_cash else _idr(closing),
                holdings=tuple(held[doc_id]),
                owner=own,
            )
        by_account: dict[tuple[str, str], list[tuple]] = defaultdict(list)
        for d in trade_docs:
            by_account[(d[1], d[2])].append(d)
        for key, tdocs in by_account.items():
            base = out.get(key)
            if base is not None and base.doc_type in CASH_DOC_TYPES:
                continue  # a bank account has no holdings to roll
            after = [d for d in tdocs
                     if base is None or date.fromisoformat(d[3]) > base.as_of]
            if not after:
                continue
            flat = [t for d in after for t in trades[d[0]]]
            out[key] = roll(base, key[0], key[1], after[-1][4],
                            date.fromisoformat(after[-1][3]), flat, len(after))
        return [out[k] for k in sorted(out)]

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        sums: dict[tuple[str, date], float] = defaultdict(float)
        for s in self.statements():
            if s.cash_idr is not None:
                sums[("CASH.IDR", s.as_of)] += s.cash_idr
            for h in s.holdings:
                if h.currency == "IDR":
                    sums[(f"HOLDING.{h.symbol or h.name}", s.as_of)] += h.value
        rows = [
            Row(sid, d, v, d, SOURCE)
            for (sid, d), v in sums.items()
            if (series_ids is None or sid in series_ids)
            and (start is None or d >= start)
            and (end is None or d <= end)
        ]
        return sorted(rows, key=lambda r: (r.series_id, r.date))
