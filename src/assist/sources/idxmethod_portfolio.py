"""Live brokerage portfolios from idx-method (`./run.sh portfolio --account NAME`), layered over
financer for layer 5.

idx-method writes one file per Stockbit login, `portfolio/<account>/latest.json` (schema 1,
`securities.py` there; gitignored, read in place, read-only): the login's positions at the last
price and its trading cash, read from Stockbit after the PIN login. financer only has what a
statement or trade confirmation printed, so for a household member with no Stockbit SOA (priskila)
it rebuilds the account from confirmations and misses every trade since the last one, and the
cash entirely.

`LivePortfolioSource` wraps the financer source and keeps its interface (`movements`, `ledgers`,
`owner_map`, `rows` pass through). Its `statements()` is financer's with one change: a live file
**replaces** financer's statement of the same `stockbit` account when the file is at least as
new; an older file is ignored and financer stands. A live account financer does not know is added.

- The owner is financer's `account_owners` for that account, else the file's `account` name.
- Holdings: `market_value_idr` at the last price, cost from `invested_idr` (avg price × shares).
- Cash: Stockbit's trading balance is the RDN. It counts as `cash_idr` only when financer has no
  loaded RDN statement (`*_rdn` savings) of the same owner, which would already count it; otherwise
  it is kept as `broker_cash_idr`, like a broker statement's closing balance.
- `source` is `idx-method`; layer 5 names it in its notes and sources.

A missing directory or file is no live data, never an error: financer alone, as before.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.financer import CASH_DOC_TYPES, FinancerSource, Holding, Statement

__all__ = ["DOC_TYPE", "ISSUER", "SCHEMA", "SOURCE", "LivePortfolioSource", "read_live"]

SOURCE = "idx-method"
SCHEMA = 1
ISSUER = "stockbit"
DOC_TYPE = "live"


def read_live(root: Path | str) -> list[dict[str, Any]]:
    """Every `portfolio/*/latest.json` under idx-method's root with a known schema, by account."""
    base = Path(root).expanduser() / "portfolio"
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.glob("*/latest.json")):
        try:
            doc = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if doc.get("schema") == SCHEMA and doc.get("broker_account") and doc.get("as_of"):
            out.append(doc)
    return out


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) else None


def _statement(doc: dict[str, Any], owner: str, rdn_owners: set[str]) -> Statement:
    holdings = []
    for p in doc.get("positions") or []:
        shares = p.get("shares")
        value = _num(p.get("market_value_idr"))
        if not p.get("symbol") or not shares or value is None:
            continue
        cost = _num(p.get("invested_idr"))
        holdings.append(Holding(p["symbol"], p.get("name") or "", str(shares), value, "IDR",
                                _num(p.get("avg_price")) if cost else None, cost or None))
    cash = _num(doc.get("cash_idr"))
    counted = owner not in rdn_owners
    return Statement(issuer=ISSUER, account=str(doc["broker_account"]), doc_type=DOC_TYPE,
                     as_of=date.fromisoformat(doc["as_of"]),
                     cash_idr=cash if counted else None, stated_value_idr=None,
                     broker_cash_idr=None if counted else cash,
                     holdings=tuple(sorted(holdings, key=lambda h: h.symbol)), owner=owner,
                     source=SOURCE)


class LivePortfolioSource:
    """financer's statements with idx-method's live Stockbit accounts laid over them."""

    name = "financer"

    def __init__(self, financer: Any, root: Path | str | None):
        self.financer = financer
        self.root = Path(root).expanduser() if root else None

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG,
                    env: dict | None = None) -> LivePortfolioSource:
        env = {**os.environ, **(env or {})}
        src = next((s for s in load_sources(config, env=env) if s.name == SOURCE), None)
        return cls(FinancerSource.from_config(config, env), src.location if src else None)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.financer, attr)

    def statements(self) -> list[Statement]:
        base = self.financer.statements()
        live = read_live(self.root) if self.root else []
        if not live:
            return base
        owners = {(i, a): o for i, a, o in self._owner_map()}
        rdn_owners = {s.owner for s in base
                      if s.doc_type in CASH_DOC_TYPES and s.issuer.endswith("_rdn")}
        out = {(s.issuer, s.account): s for s in base}
        for doc in live:
            key = (ISSUER, str(doc["broker_account"]))
            st = _statement(doc, owners.get(key, doc.get("account") or "unknown"), rdn_owners)
            old = out.get(key)
            if old is None or st.as_of >= old.as_of:
                out[key] = st
        return [out[k] for k in sorted(out)]

    def _owner_map(self) -> Sequence[tuple[str, str, str]]:
        fn = getattr(self.financer, "owner_map", None)
        return fn() if fn else []
