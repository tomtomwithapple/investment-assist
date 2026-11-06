"""Layer 5 (PLAN S4): what is held now, as % of the portfolio per country × asset class.

Input is financer's latest loaded statement per account, rolled forward through the trade
documents after it (`assist.sources.financer`, PLAN S32). Each line is mapped by a fixed rule,
never guessed:

- `IDR` (a broker's cash line) and bank/RDN balances → (IDN, cash)
- SBN codes: FR, VR, ORI, SR, SBR, ST, PBS, SPN, SPNS + digits (retail series may end `T<n>`)
  → (IDN, bonds)
- IDX tickers (four capitals), with `-R` (rights) or `-W` (warrants) → (IDN, stocks)
- anything else (a fund printed without a code, a foreign-currency line) → listed in
  `unmapped` with its value and left out of the weights, which add up to 100 over what is mapped.

A line sold below zero (no statement shows the position) is listed in `unmapped` with its
(negative) value and never subtracted from a bucket.

Both owners (financer's `documents.owner`) are summed into one household portfolio; `by_owner`
splits the buckets per owner. An account valued partly at trade prices gets a `notes` line
("valued at last trade price: N lines"), shown in the brief and the stance page, not in
`stale_inputs`.

Every account sits at an Indonesian broker or bank today, so all mapped lines are IDN. An account
whose latest statement is more than `STALE_DAYS` older than the newest one, and still holds
something, is named in `stale_inputs`: its numbers may no longer be current.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from assist.layers.types import Weights
from assist.sources.base import Source, SourceUnavailable
from assist.sources.financer import SOURCE, FinancerSource, Statement

__all__ = ["STALE_DAYS", "Portfolio", "StatementCheck", "build_portfolio", "classify",
           "current_weights"]

STALE_DAYS = 45
MATCH_TOLERANCE_IDR = 1.0  # rounding allowed between the broker's printed total and its lines

_IDX_TICKER = re.compile(r"[A-Z]{4}(-[RW])?")
_SBN = re.compile(r"(FR|VR|ORI|SBR|SR|ST|PBS|SPNS|SPN)\d{2,8}(T\d)?")


def classify(symbol: str, currency: str = "IDR") -> tuple[str, str] | None:
    """(subject, asset) for one holding line, or None when no rule maps it."""
    if currency != "IDR":
        return None
    if symbol == "IDR":
        return ("IDN", "cash")
    if _SBN.fullmatch(symbol):
        return ("IDN", "bonds")
    if _IDX_TICKER.fullmatch(symbol):
        return ("IDN", "stocks")
    return None


@dataclass(frozen=True)
class StatementCheck:
    """Does the sum of a broker statement's lines equal the total the broker printed?
    `matches` is None when the statement prints no total (or is a bank statement). For a rolled
    account the statement's own lines are compared, before rolling."""

    issuer: str
    as_of: date
    holdings_idr: float
    stated_idr: float | None
    cash_idr: float | None
    account: str = ""

    @property
    def matches(self) -> bool | None:
        if self.stated_idr is None:
            return None
        return abs(self.holdings_idr - self.stated_idr) <= MATCH_TOLERANCE_IDR


@dataclass(frozen=True)
class Portfolio:
    as_of: date | None
    buckets_idr: dict[tuple[str, str], float]
    unmapped: tuple[tuple[str, float], ...] = ()
    checks: tuple[StatementCheck, ...] = ()
    stale_inputs: tuple[str, ...] = ()
    broker_cash_idr: float = field(default=0.0)
    by_owner: dict[str, dict[tuple[str, str], float]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def total_idr(self) -> float:
        return sum(self.buckets_idr.values())

    @property
    def unmapped_idr(self) -> float:
        return sum(v for _, v in self.unmapped)

    def weights(self) -> Weights:
        total = self.total_idr
        weights = {k: 100 * v / total for k, v in self.buckets_idr.items()} if total else {}
        return Weights(
            as_of=self.as_of or date.min,
            weights=weights,
            unmapped=tuple(f"{label} (Rp{v:,.0f})" for label, v in self.unmapped),
            sources=(SOURCE,),
            stale_inputs=self.stale_inputs,
            total_idr=total,
            notes=self.notes,
        )


def build_portfolio(statements: Iterable[Statement], stale_days: int = STALE_DAYS) -> Portfolio:
    statements = list(statements)
    buckets: dict[tuple[str, str], float] = defaultdict(float)
    owners: dict[str, dict[tuple[str, str], float]] = defaultdict(lambda: defaultdict(float))
    unmapped: list[tuple[str, float]] = []
    for s in statements:
        mine = owners[s.owner]
        if s.cash_idr is not None:
            buckets[("IDN", "cash")] += s.cash_idr
            mine[("IDN", "cash")] += s.cash_idr
        for h in s.unheld:
            unmapped.append((f"{h.symbol} ({h.quantity} shares, sold below zero) at {s.issuer}",
                             h.value))
        for h in s.holdings:
            key = classify(h.symbol, h.currency)
            if key is None:
                what = h.symbol or h.name
                if h.symbol and h.name and h.name != h.symbol:
                    what = f"{h.symbol} {h.name}"
                ccy = "" if h.currency == "IDR" else f" {h.currency}"
                unmapped.append((f"{what}{ccy} at {s.issuer}", h.value))
            else:
                buckets[key] += h.value
                mine[key] += h.value

    newest = max((s.as_of for s in statements), default=None)
    stale = tuple(
        f"{SOURCE} {s.issuer} (statement {s.as_of.isoformat()})"
        for s in statements
        if newest is not None
        and (newest - s.as_of).days > stale_days
        and (s.holdings_idr or s.cash_idr)
    )
    checks = tuple(
        StatementCheck(s.issuer, s.rolled_from or s.as_of,
                       s.holdings_idr if s.statement_holdings_idr is None
                       else s.statement_holdings_idr,
                       s.stated_value_idr, s.cash_idr, s.account)
        for s in statements
        if not (s.trade_docs and s.rolled_from is None)  # trades only: no statement to check
    )
    notes = tuple(
        f"{SOURCE} {s.issuer} ({s.owner}): valued at last trade price: "
        f"{len(s.priced_at_trade)} lines"
        for s in statements if s.priced_at_trade
    )
    return Portfolio(
        as_of=newest,
        buckets_idr={k: v for k, v in buckets.items()},
        unmapped=tuple(unmapped),
        checks=checks,
        stale_inputs=stale,
        broker_cash_idr=sum(s.broker_cash_idr or 0.0 for s in statements),
        by_owner={o: dict(b) for o, b in owners.items() if b},
        notes=notes,
    )


def current_weights(source: Source | None = None) -> tuple[Weights | None, list[str]]:
    """Layer 5 for the stance: (weights, stale_inputs). A missing or locked store gives
    (None, ["financer (missing)"]), never an exception."""
    source = source or FinancerSource.from_config()
    try:
        p = build_portfolio(source.statements())
    except SourceUnavailable as e:
        return None, [e.stale_input]
    return p.weights(), list(p.stale_inputs)
