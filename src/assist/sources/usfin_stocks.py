"""sec-edgar (usfin) US single stocks (P39, PLAN S21): the listed universe joined to EDGAR, daily
Alpaca bars with their adjustment factors, and XBRL facts point in time.

Read through `Usfin` (usfin.py): `usfin serve` CSV when it answers, a read-only ATTACH otherwise.

- **Universe**: `/prices/universe?status=active&matched=1&format=csv`, or the same join on the
  store: `alpaca_universe` symbols of source `asset_active` → active `edgar_company` rows by
  `ticker_norm`, lowest CIK on a shared one (sec-edgar's How › EDGAR link). Delisted symbols do
  not join, so the universe is today's listed names (survivorship: see us_stocks).
- **Bars** per symbol: `/prices?symbol=…&format=csv`, or sec-edgar's web/prices.py `bars` query:
  `alpaca_bar_adjusted_lookup(sym)` (the security the symbol names today, across renames) joined
  to the newest version of each `alpaca_bar` for its volume. Never the whole
  `alpaca_bar_adjusted` view. `split_factor` and `tr_factor` back-adjust: adjusted = close ×
  factor, so a dividend is where `tr_factor / split_factor` steps (us_stocks.dividends_from_bars).
- **Facts** per CIK: `xbrl_as_of(d)` (filed on or before `d`) for the few tags the engines need.
  `usfin serve` has no point-in-time facts route (`/screen` and `/edgar/<cik>` pick by `frame`,
  which SEC moves to the newest filing), so facts come only from the ATTACH, which is `locked`
  while `serve` runs.

Schema: ../sec-edgar/src/usfin/migrations/007, 014, 019, 024, 025, 027, 028; routes: its
web/app.py `prices_page`, `prices_universe_page`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import NamedTuple

from assist.sources.base import SourceUnavailable
from assist.sources.usfin import SOURCE, Usfin

__all__ = ["FACT_TAGS", "Fact", "Listing", "UsBar", "UsStocks"]

# (taxonomy, tag) the engines read, in order of preference within each concept.
FACT_TAGS = {
    "net_income": (("us-gaap", "NetIncomeLoss"), ("us-gaap", "ProfitLoss")),
    "cfo": (("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")),
    "equity": (("us-gaap", "StockholdersEquity"),
               ("us-gaap",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")),
    "shares": (("dei", "EntityCommonStockSharesOutstanding"),
               ("us-gaap", "CommonStockSharesOutstanding")),
    "dps": (("us-gaap", "CommonStockDividendsPerShareDeclared"),),
    "deposits": (("us-gaap", "Deposits"),),  # a bank marker: no SIC in the store
}  # fmt: skip
_TAGS = sorted({t for refs in FACT_TAGS.values() for _, t in refs})


class Listing(NamedTuple):
    symbol: str
    cik: int
    title: str


class UsBar(NamedTuple):
    """One session, USD. `close` is as traded; adjusted = close × factor."""

    date: date
    symbol: str
    close: float
    volume: float | None
    adj_close: float
    split_factor: float
    tr_factor: float


class Fact(NamedTuple):
    tag: str
    unit: str
    accn: str
    period_start: date
    period_end: date
    value: float
    form: str
    filed: date


def _f(v) -> float | None:
    return None if v is None or v == "" else float(v)


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


_UNIVERSE_SQL = """
    with e as (
        select ticker_norm, min(cik) as cik, arg_min(title, cik) as title
        from edgar_company where active group by ticker_norm
    )
    select distinct u.symbol, e.cik, e.title
    from alpaca_universe u join e on e.ticker_norm = ticker_norm(u.symbol)
    where u.source = 'asset_active'
    order by u.symbol
"""

_BARS_SQL = """
    with adj as (select * from alpaca_bar_adjusted_lookup(?)),
    latest as (
        select * from alpaca_bar
        where symbol in (select distinct symbol from adj)
        qualify row_number() over (
            partition by symbol, date order by first_seen_at desc, raw_id desc
        ) = 1
    )
    select a.date, a.symbol, a.close, b.volume, a.adj_close, a.split_factor, a.tr_factor
    from adj a join latest b using (symbol, date)
    order by a.date
"""

_FACTS_SQL = f"""
    select tag, unit, accn, period_start, period_end, value, form, filed
    from xbrl_as_of(cast(? as date))
    where cik = ? and tag in ({", ".join("?" for _ in _TAGS)})
      and unit in ('USD', 'shares', 'USD/shares')
    order by tag, period_end, filed, accn
"""


class UsStocks:
    """US listed stocks from sec-edgar. Every call reads one symbol or one CIK."""

    name = SOURCE

    def __init__(self, usfin: Usfin | None = None):
        self.usfin = usfin or Usfin.from_config()

    # ---------------- universe ----------------

    def universe(self) -> list[Listing]:
        return self.usfin.fetch(self.universe_http, self.universe_duckdb)

    def universe_http(self) -> list[Listing]:
        rows = self.usfin.get_csv("/prices/universe", {"status": "active", "matched": "1"}) or []
        return sorted(Listing(r["symbol"], int(r["cik"]), r["edgar_title"])
                      for r in rows if r.get("cik"))

    def universe_duckdb(self) -> list[Listing]:
        with self.usfin.attached() as con:
            found = con.execute(_UNIVERSE_SQL).fetchall()
        return [Listing(s, int(c), t) for s, c, t in found]

    # ---------------- bars ----------------

    def bars(self, symbol: str) -> list[UsBar]:
        return self.usfin.fetch(lambda: self.bars_http(symbol), lambda: self.bars_duckdb(symbol))

    def bars_http(self, symbol: str) -> list[UsBar]:
        rows = self.usfin.get_csv("/prices", {"symbol": symbol}) or []  # 404: no bars
        return [
            UsBar(_d(r["date"]), r["symbol"], float(r["close"]), _f(r["volume"]),
                  float(r["adj_close"]), float(r["split_factor"]), float(r["tr_factor"]))
            for r in rows
        ]

    def bars_duckdb(self, symbol: str) -> list[UsBar]:
        with self.usfin.attached() as con:
            found = con.execute(_BARS_SQL, [symbol]).fetchall()
        return [UsBar(_d(d), s, float(c), _f(v), float(a), float(sf), float(tr))
                for d, s, c, v, a, sf, tr in found]

    # ---------------- facts ----------------

    def facts(self, cik: int, as_of: date | None = None) -> list[Fact]:
        """XBRL facts of `cik` filed on or before `as_of` (default today)."""
        return self.usfin.fetch(lambda: self.facts_http(cik, as_of),
                                lambda: self.facts_duckdb(cik, as_of))

    def facts_http(self, cik: int, as_of: date | None = None) -> list[Fact]:
        raise SourceUnavailable(self.name, "missing",
                                "usfin serve has no point-in-time XBRL facts route")

    def facts_duckdb(self, cik: int, as_of: date | None = None) -> list[Fact]:
        return self.facts_many_duckdb([cik], as_of).get(cik, [])

    def facts_many(self, ciks: Sequence[int], as_of: date | None = None
                   ) -> dict[int, list[Fact]]:
        """`facts` of several CIKs, over one ATTACH."""
        return self.usfin.fetch(lambda: self.facts_http(0, as_of),
                                lambda: self.facts_many_duckdb(ciks, as_of))

    def facts_many_duckdb(self, ciks: Sequence[int], as_of: date | None = None
                          ) -> dict[int, list[Fact]]:
        """One query per CIK, so each is pruned by the store's `cik` zonemaps."""
        as_of = as_of or date.today()
        out: dict[int, list[Fact]] = {}
        with self.usfin.attached() as con:
            for cik in ciks:
                found = con.execute(_FACTS_SQL, [as_of, cik, *_TAGS]).fetchall()
                out[cik] = [Fact(t, u, a, _d(ps), _d(pe), float(v), fm, _d(fd))
                            for t, u, a, ps, pe, v, fm, fd in found]
        return out
