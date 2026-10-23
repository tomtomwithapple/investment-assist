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

`rows()` gives the tidy view: `HOLDING.<symbol>` (market value of IDR lines, summed across
accounts) and `CASH.IDR`, dated by the statement. Layer 5 (`assist.layers.portfolio`) uses
`statements()`.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import NamedTuple

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, sqlite_ro

__all__ = ["BROKER_DOC_TYPES", "CASH_DOC_TYPES", "SOURCE", "FinancerSource", "Holding", "Statement"]

SOURCE = "financer"
MINOR_SCALE = 100
BROKER_DOC_TYPES = ("portfolio", "broker_soa")
CASH_DOC_TYPES = ("savings_statement",)

_LATEST = f"""
with ranked as (
    select d.*, row_number() over (
        partition by d.issuer, coalesce(d.account_ref, '') order by d.statement_date desc, d.id desc
    ) as rn
    from documents d
    where d.status = 'loaded'
      and d.doc_type in ({", ".join(f"'{t}'" for t in BROKER_DOC_TYPES + CASH_DOC_TYPES)})
)
select id, issuer, coalesce(account_ref, ''), doc_type, statement_date, currency,
       closing_minor, portfolio_value_minor
from ranked where rn = 1
order by issuer, account_ref
"""

_HOLDINGS = """
select document_id, symbol, name, quantity, market_value_minor, currency
from holdings where document_id in ({marks}) order by document_id, line_no
"""


class Holding(NamedTuple):
    """One line of a broker's holdings table; `value` is the market value in `currency`."""

    symbol: str
    name: str
    quantity: str
    value: float
    currency: str


class Statement(NamedTuple):
    """An account's latest loaded statement. `cash_idr` is set for bank/RDN statements only;
    `stated_value_idr` is the portfolio total the broker printed (None if it printed none)."""

    issuer: str
    account: str
    doc_type: str
    as_of: date
    cash_idr: float | None
    stated_value_idr: float | None
    broker_cash_idr: float | None
    holdings: tuple[Holding, ...]

    @property
    def holdings_idr(self) -> float:
        return sum(h.value for h in self.holdings if h.currency == "IDR")


def _idr(minor: int | None) -> float | None:
    return None if minor is None else minor / MINOR_SCALE


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

    def statements(self) -> list[Statement]:
        with sqlite_ro(self.path, self.name) as con:
            docs = con.execute(_LATEST).fetchall()
            ids = [d[0] for d in docs]
            held: dict[int, list[Holding]] = defaultdict(list)
            if ids:
                sql = _HOLDINGS.format(marks=", ".join("?" for _ in ids))
                for doc_id, symbol, name, qty, value, ccy in con.execute(sql, ids):
                    held[doc_id].append(Holding(symbol, name, qty, value / MINOR_SCALE, ccy))
        out = []
        for doc_id, issuer, account, doc_type, as_of, ccy, closing, stated in docs:
            is_cash = doc_type in CASH_DOC_TYPES
            if is_cash and ccy != "IDR":
                # foreign-currency cash: kept as a holding so layer 5 lists it as unmapped
                held[doc_id].append(Holding(ccy, f"{issuer} cash", "1", _idr(closing), ccy))
                closing = None
            out.append(
                Statement(
                    issuer=issuer,
                    account=account,
                    doc_type=doc_type,
                    as_of=date.fromisoformat(as_of),
                    cash_idr=_idr(closing) if is_cash else None,
                    stated_value_idr=_idr(stated),
                    broker_cash_idr=None if is_cash else _idr(closing),
                    holdings=tuple(held[doc_id]),
                )
            )
        return out

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
