"""Layer 5 (PLAN S4): what is held now, as % of the portfolio per country × asset class.

Input is financer's latest loaded statement per account (`assist.sources.financer`). Each line is
mapped by a fixed rule, never guessed:

- `IDR` (a broker's cash line) and bank/RDN balances → (IDN, cash)
- SBN codes: FR, VR, ORI, SR, SBR, ST, PBS, SPN, SPNS + digits (retail series may end `T<n>`)
  → (IDN, bonds)
- IDX tickers (four capitals), with `-R` (rights) or `-W` (warrants) → (IDN, stocks)
- anything else (a fund printed without a code, a foreign-currency line) → listed in
  `unmapped` with its value and left out of the weights, which add up to 100 over what is mapped.

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
    `matches` is None when the statement prints no total (or is a bank statement)."""

    issuer: str
    as_of: date
    holdings_idr: float
    stated_idr: float | None
    cash_idr: float | None

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
        )


def build_portfolio(statements: Iterable[Statement], stale_days: int = STALE_DAYS) -> Portfolio:
    statements = list(statements)
    buckets: dict[tuple[str, str], float] = defaultdict(float)
    unmapped: list[tuple[str, float]] = []
    for s in statements:
        if s.cash_idr is not None:
            buckets[("IDN", "cash")] += s.cash_idr
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

    newest = max((s.as_of for s in statements), default=None)
    stale = tuple(
        f"{SOURCE} {s.issuer} (statement {s.as_of.isoformat()})"
        for s in statements
        if newest is not None
        and (newest - s.as_of).days > stale_days
        and (s.holdings_idr or s.cash_idr)
    )
    checks = tuple(
        StatementCheck(s.issuer, s.as_of, s.holdings_idr, s.stated_value_idr, s.cash_idr)
        for s in statements
    )
    return Portfolio(
        as_of=newest,
        buckets_idr={k: v for k, v in buckets.items()},
        unmapped=tuple(unmapped),
        checks=checks,
        stale_inputs=stale,
        broker_cash_idr=sum(s.broker_cash_idr or 0.0 for s in statements),
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
