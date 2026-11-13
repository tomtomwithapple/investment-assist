"""sec-edgar (usfin) US single stocks (P39, PLAN S21): the listed universe joined to EDGAR, daily
Alpaca bars with their adjustment factors, and XBRL facts point in time.

Read through `Usfin` (usfin.py): `usfin serve` CSV when it answers, a read-only ATTACH otherwise.

- **Universe**: `/prices/universe?status=active&matched=1&format=csv`, or the same join on the
  store: `alpaca_universe` symbols of source `asset_active` → active `edgar_company` rows by
  `ticker_norm`, lowest CIK on a shared one (sec-edgar's How › EDGAR link). Delisted symbols do
  not join, so the universe is today's listed names (survivorship: see us_stocks). Each listing
  carries its company's SIC code (sec-edgar S45: `edgar_company_profile`, the route's `sic`).
- **Bars** per symbol: `/prices?symbol=…&format=csv`, or sec-edgar's web/prices.py `bars` query:
  `alpaca_bar_adjusted_lookup(sym)` (the security the symbol names today, across renames) joined
  to the newest version of each `alpaca_bar` for its volume. Never the whole
  `alpaca_bar_adjusted` view. `split_factor` and `tr_factor` back-adjust: adjusted = close ×
  factor, so a dividend is where `tr_factor / split_factor` steps (us_stocks.dividends_from_bars).
- **Bars of many symbols** (P63, `bars_many`): one query over the ATTACH, the whole
  `alpaca_bar_adjusted` view joined to `alpaca_security_symbol` (the security each symbol names
  today, as the lookup picks it), so each symbol gets the rows `bars(symbol)` gives (equal to
  the last bit of the factors, checked live 2026-11-07). `usfin serve` has no bulk route and
  `/prices` takes ~11 s a symbol (6 000 names: ~18 h); the bulk query reads 7 177 symbols in
  ~34 s. `min_value` / `min_sessions` drop, in SQL, symbols with fewer sessions of close ×
  volume ≥ `min_value` than `min_sessions` (us_stocks.liquid_floor).
- **Facts** per CIK: `xbrl_as_of(d)` (filed on or before `d`) for the few tags the engines need.
  `usfin serve` has no point-in-time facts route (`/screen` and `/edgar/<cik>` pick by `frame`,
  which SEC moves to the newest filing), so facts come only from the ATTACH, which is `locked`
  while `serve` runs.

Schema: ../sec-edgar/src/usfin/migrations/007, 014, 019, 024, 025, 027, 028, 029; routes: its
web/app.py `prices_page`, `prices_universe_page`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from itertools import groupby
from typing import NamedTuple

from assist.sources.base import SourceUnavailable
from assist.sources.usfin import SOURCE, US_HTTP_TIMEOUT, Usfin

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
    sic: int | None = None  # SEC SIC code (sec-edgar S45); None: SEC lists none, or an old store


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
    select distinct u.symbol, e.cik, e.title, {sic}
    from alpaca_universe u join e on e.ticker_norm = ticker_norm(u.symbol)
    {join}
    where u.source = 'asset_active'
    order by u.symbol
"""
# sec-edgar before S45 has no `edgar_company_profile`: every listing then has no SIC.
_SIC = {True: ("p.sic", "left join edgar_company_profile p on p.cik = e.cik"),
        False: ("cast(null as integer) as sic", "")}

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

# `_BARS_SQL` for many symbols at once, `want` the symbol asked for; then the liquidity floor.
_BARS_MANY_SQL = """
    with want as (
        select symbol as want, security_key from alpaca_security_symbol
        where symbol in (select unnest(?::varchar[]))
    ),
    adj as (select w.want, a.* from alpaca_bar_adjusted a join want w using (security_key)),
    latest as (
        select symbol, date, volume from alpaca_bar
        where symbol in (select distinct symbol from adj)
        qualify row_number() over (
            partition by symbol, date order by first_seen_at desc, raw_id desc
        ) = 1
    ),
    j as (
        select a.want, a.date, a.symbol, a.close, b.volume, a.adj_close, a.split_factor,
               a.tr_factor
        from adj a join latest b using (symbol, date)
    )
    select * from j
    where want in (select want from j group by want
                   having count(*) filter (where close * volume >= ?) >= ?)
    order by want, date
"""
_FETCH_ROWS = 200_000

_FACTS_SQL = f"""
    select tag, unit, accn, period_start, period_end, value, form, filed
    from xbrl_as_of(cast(? as date))
    where cik = ? and tag in ({", ".join("?" for _ in _TAGS)})
      and unit in ('USD', 'shares', 'USD/shares')
    order by tag, period_end, filed, accn
"""


class UsStocks:
    """US listed stocks from sec-edgar. Every call reads one symbol or one CIK, but
    `facts_many` and `bars_many`. Built from the config, it reads `usfin serve` with the long
    timeout (`US_HTTP_TIMEOUT`): the universe route takes ~22 s."""

    name = SOURCE

    def __init__(self, usfin: Usfin | None = None):
        if usfin is None:
            usfin = Usfin.from_config()
            usfin.timeout = US_HTTP_TIMEOUT
        self.usfin = usfin

    # ---------------- universe ----------------

    def universe(self) -> list[Listing]:
        return self.usfin.fetch(self.universe_http, self.universe_duckdb)

    def universe_http(self) -> list[Listing]:
        rows = self.usfin.get_csv("/prices/universe", {"status": "active", "matched": "1"}) or []
        return sorted(Listing(r["symbol"], int(r["cik"]), r["edgar_title"],
                              int(r["sic"]) if r.get("sic") else None)
                      for r in rows if r.get("cik"))

    def universe_duckdb(self) -> list[Listing]:
        with self.usfin.attached() as con:
            has = con.execute(
                "select count(*) from duckdb_tables() where database_name = current_database()"
                " and table_name = 'edgar_company_profile'").fetchone()[0] > 0
            sic, join = _SIC[has]
            found = con.execute(_UNIVERSE_SQL.format(sic=sic, join=join)).fetchall()
        return [Listing(s, int(c), t, None if sic is None else int(sic))
                for s, c, t, sic in found]

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

    def bars_many(self, symbols: Sequence[str], *, min_value: float = 0.0,
                  min_sessions: int = 0,
                  each: Callable[[str, list[UsBar]], None] | None = None,
                  ) -> dict[str, list[UsBar]]:
        """`bars` of several symbols over one ATTACH, without the symbols that have fewer than
        `min_sessions` sessions of close × volume ≥ `min_value` (and those with no bars). With
        `each`, every symbol's bars go to `each(symbol, bars)` as they stream in, and the
        result is empty (so ~10 M rows are never held at once)."""
        return self.usfin.fetch(
            lambda: self.bars_many_http(symbols),
            lambda: self.bars_many_duckdb(symbols, min_value=min_value,
                                          min_sessions=min_sessions, each=each))

    def bars_many_http(self, symbols: Sequence[str]) -> dict[str, list[UsBar]]:
        raise SourceUnavailable(self.name, "missing",
                                "usfin serve has no bulk bars route (/prices is one symbol)")

    def bars_many_duckdb(self, symbols: Sequence[str], *, min_value: float = 0.0,
                         min_sessions: int = 0,
                         each: Callable[[str, list[UsBar]], None] | None = None,
                         ) -> dict[str, list[UsBar]]:
        out: dict[str, list[UsBar]] = {}
        keep = each or out.__setitem__
        if not symbols:
            return out
        with self.usfin.attached() as con:
            cur = con.execute(_BARS_MANY_SQL, [sorted(set(symbols)), min_value, min_sessions])
            want, bars = None, []
            while chunk := cur.fetchmany(_FETCH_ROWS):
                for w, rows in groupby(chunk, key=lambda r: r[0]):
                    if w != want:
                        if want is not None:
                            keep(want, bars)
                        want, bars = w, []
                    bars += [UsBar(_d(d), s, float(c), _f(v), float(a), float(sf), float(tr))
                             for _, d, s, c, v, a, sf, tr in rows]
            if want is not None:
                keep(want, bars)
        return out

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
