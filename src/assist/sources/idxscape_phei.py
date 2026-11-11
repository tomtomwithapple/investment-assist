"""idxscape PHEI adapter: IGSYC government curve, PHEI bond quotes, credit curve; read-only.

Tables are idxscape's J4 (migration 9, `docs/storage.md`); the curve and slope follow its own J8
overlay (`idxscape.queries.igsyc_curve`, `igsyc_slopes`), so both repos show the same numbers.
Kept apart from `idxscape.py` on purpose: PHEI is for the owner's LOCAL USE ONLY. Raw quotes and
curve points never leave this Mac; anything sent off it (Telegram) carries derived numbers only.

- `IGSYC.<tenor>` (`igsyc_series`): `igsyc_point.yield_pct` per day at one tenor (0.1, 1 … 40
  years). Tenors past 30Y are extrapolated by PHEI, so the default `rows()` and `curve()` stop at
  30Y; a longer tenor is read only when asked for by id or with `max_tenor=None`.
- `PHEI_BOND.<grp>.<series_code>` (`bond_series`): a bond's PHEI fair yield, `grp`
  `SBN_BENCHMARK|SBSN_BENCHMARK|RETAIL`. Benchmark membership rotates, so never read a series as
  "the 10Y benchmark": take tenors from the curve. Full quotes (ttm, price, coupon) via
  `bond_quotes()`. Asked for by id only.
- `PHEI_CREDIT.<rating>.<tenor>` (`credit_series`): `credit_curve_point`, rating
  `IGS|AAA|AA|A|BBB`, tenors 0.1–10. Asked for by id or through `credit_curve()`.
- `SUN.<tenor>` (`sun_series`): DJPPR's daily quote of the year's SUN benchmark series at 5, 10,
  15 or 20 years (idxscape J9, migration 11, `sun_benchmark_quote.yield_pct`, 2021-01 on). Not
  PHEI: public DJPPR data in the same store, served here so every IDN 10Y reader takes it from
  the source it already holds (P101). The series code rotates each January; the tenor is the
  benchmark's label, not a constant maturity. A quote is known on its own date (DJPPR prices the
  day's close; its files carry no per-day publish time), so `as_of` = the quote date. Asked for
  by id only.

Values are percent as printed (7.1677 means 7.1677%). `as_of` = the WIB date of `fetched_at`,
the snapshot it came from (a later page may revise a day). `from_yesterday_column` (the day had
no page of its own and was filled from the next page's Yesterday column; bond `ttm_y` is None
then) is kept as a flag on `CurvePoint`, `CurveSlope` and `BondQuote` and by
`yesterday_column_days()`.

A store without migration 9 (no PHEI tables) is `missing`, as is a series whose table is absent.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

import duckdb

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable, duckdb_ro

__all__ = [
    "GROUPS",
    "IGSYC_2Y",
    "IGSYC_10Y",
    "SUN_10Y",
    "SUN_SOURCE",
    "MAX_TENOR",
    "RATINGS",
    "SOURCE",
    "BondQuote",
    "CreditPoint",
    "CurveDay",
    "CurvePoint",
    "CurveSlope",
    "PheiSource",
    "bond_series",
    "credit_series",
    "igsyc_series",
    "sun_series",
]

SOURCE = "idxscape_phei"
# Store key for the SUN series in a sources mapping (the same PheiSource): read apart from the
# PHEI series, so a store without migration 11 still serves IGSYC.
SUN_SOURCE = "idxscape_sun"
CONFIG_NAME = "idxscape"  # the store's entry in config/sources.yaml
IGSYC, BOND, CREDIT, SUN = "IGSYC.", "PHEI_BOND.", "PHEI_CREDIT.", "SUN."
GROUPS = ("SBN_BENCHMARK", "SBSN_BENCHMARK", "RETAIL")
RATINGS = ("IGS", "AAA", "AA", "A", "BBB")
MAX_TENOR = 30.0  # PHEI extrapolates beyond ~30Y
TABLES = {"igsyc": "igsyc_point", "bond": "phei_bond_quote", "credit": "credit_curve_point",
          "sun": "sun_benchmark_quote"}
WIB = "set TimeZone = 'Asia/Jakarta'"


def _tenor(t: float | Decimal | str) -> str:
    return format(Decimal(str(t)).normalize(), "f")


def igsyc_series(tenor: float | Decimal) -> str:
    return IGSYC + _tenor(tenor)


def bond_series(grp: str, series_code: str) -> str:
    return f"{BOND}{grp}.{series_code}"


def credit_series(rating: str, tenor: float | Decimal) -> str:
    return f"{CREDIT}{rating}.{_tenor(tenor)}"


def sun_series(tenor: int) -> str:
    return f"{SUN}{int(tenor)}"


IGSYC_2Y = igsyc_series(2)
IGSYC_10Y = igsyc_series(10)
SUN_10Y = sun_series(10)  # DJPPR SUN 10Y benchmark (idxscape J9), the IGSYC 10Y fallback


class CurvePoint(NamedTuple):
    as_of: date
    tenor_y: float
    yield_pct: float
    from_yesterday_column: bool


class CurveDay(NamedTuple):
    as_of: date
    from_yesterday_column: bool  # any of its points came from a Yesterday column


class CurveSlope(NamedTuple):
    as_of: date
    yield_2y: float
    yield_10y: float
    slope_pct: float  # 10Y - 2Y, percentage points
    from_yesterday_column: bool  # either point came from a Yesterday column


class BondQuote(NamedTuple):
    as_of: date
    series_code: str
    grp: str
    ttm_y: float | None  # None when from the Yesterday column
    yield_pct: float | None
    price_pct: float | None
    coupon_pct: float | None
    from_yesterday_column: bool


class CreditPoint(NamedTuple):
    as_of: date
    tenor_y: float
    rating: str
    yield_pct: float


def _parse(sid: str) -> tuple[str, tuple] | None:
    """Series id → (kind, key) or None if it is not a PHEI id."""
    try:
        if sid.startswith(IGSYC):
            return "igsyc", (Decimal(sid.removeprefix(IGSYC)),)
        if sid.startswith(SUN):
            return "sun", (int(sid.removeprefix(SUN)),)
        if sid.startswith(CREDIT):
            rating, tenor = sid.removeprefix(CREDIT).split(".", 1)
            return ("credit", (rating, Decimal(tenor))) if rating in RATINGS else None
        if sid.startswith(BOND):
            grp, code = sid.removeprefix(BOND).split(".", 1)
            return ("bond", (grp, code)) if grp in GROUPS and code else None
    except (ValueError, ArithmeticError):
        return None
    return None


def _window(col: str, start: date | None, end: date | None) -> tuple[list[str], list]:
    where, params = [], []
    if start:
        where.append(f"{col} >= ?")
        params.append(start)
    if end:
        where.append(f"{col} <= ?")
        params.append(end)
    return where, params


def _f(v) -> float | None:
    return None if v is None else float(v)


class PheiSource:
    """idxscape's PHEI tables as tidy rows (sorted by series and date) and curve helpers."""

    name = SOURCE
    local_only = True  # PHEI terms: raw quotes stay on this Mac

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> PheiSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == CONFIG_NAME)
        return cls(src.location)

    @contextmanager
    def _connect(self) -> Iterator[tuple[duckdb.DuckDBPyConnection, set[str]]]:
        with duckdb_ro(self.path, self.name) as con:
            con.execute(WIB)  # fetched_at is TIMESTAMPTZ; take the WIB date
            names = con.execute("select table_name from duckdb_tables()").fetchall()
            yield con, {t for (t,) in names}

    def _need(self, tables: set[str], *needed: str) -> None:
        absent = [t for t in needed if t not in tables]
        if absent:
            raise SourceUnavailable(
                self.name, "missing",
                f"no {', '.join(absent)} table (idxscape migration"
                f" {11 if absent == [TABLES['sun']] else 9})")

    def _query(self, kind: str, sql: str, params: Sequence = ()) -> list[tuple]:
        with self._connect() as (con, tables):
            self._need(tables, TABLES[kind])
            return con.execute(sql, list(params)).fetchall()

    # ---------------- tidy rows ----------------

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        with self._connect() as (con, tables):
            if series_ids is None:
                self._need(tables, TABLES["igsyc"])
                where, params = _window("as_of", start, end)
                sql = (
                    "select tenor_y, as_of, yield_pct, cast(fetched_at as date) from igsyc_point"
                    f" where {' and '.join(['tenor_y <= ?', *where])} order by tenor_y, as_of"
                )
                return [Row(igsyc_series(t), d, float(v), rec, self.name)
                        for t, d, v, rec in con.execute(sql, [MAX_TENOR, *params]).fetchall()]
            parsed = {sid: p for sid in set(series_ids) if (p := _parse(sid))}
            for kind, _ in parsed.values():
                self._need(tables, TABLES[kind])
            out = []
            for sid in sorted(parsed):
                kind, key = parsed[sid]
                sql, params = self._sql(kind, key, start, end)
                out += [Row(sid, d, _f(v), rec, self.name)
                        for d, v, rec in con.execute(sql, params).fetchall()]
            return out

    def _sql(self, kind: str, key: tuple, start: date | None, end: date | None):
        where, params = _window("as_of", start, end)
        if kind == "sun":  # known on its quote date: as_of doubles as the vintage
            return (
                f"select as_of, yield_pct, as_of from {TABLES[kind]}"
                f" where {' and '.join(['tenor_y = ?', *where])} order by as_of",
                [*key, *params],
            )
        keys = {"igsyc": ["tenor_y = ?"], "credit": ["rating = ?", "tenor_y = ?"],
                "bond": ["grp = ?", "series_code = ?"]}[kind]
        return (
            f"select as_of, yield_pct, cast(fetched_at as date) from {TABLES[kind]}"
            f" where {' and '.join([*keys, *where])} order by as_of",
            [*key, *params],
        )

    # ---------------- curve ----------------

    def curve_days(self) -> list[CurveDay]:
        """Curve days, newest first (a day counts as gap-filled if any of its points is)."""
        sql = ("select as_of, bool_or(from_yesterday_column) from igsyc_point"
               " group by as_of order by as_of desc")
        return [CurveDay(d, bool(f)) for d, f in self._query("igsyc", sql)]

    def yesterday_column_days(self) -> set[date]:
        """Curve days with any point filled from a later page's Yesterday column."""
        return {d.as_of for d in self.curve_days() if d.from_yesterday_column}

    def curve(
        self,
        as_of: date | None = None,
        max_tenor: float | None = MAX_TENOR,
        on_or_before: bool = False,
    ) -> list[CurvePoint]:
        """The IGSYC curve on `as_of` (default: the newest day) up to `max_tenor` years (`None`:
        every tenor, to 40Y). `on_or_before` takes the newest curve day on or before `as_of`."""
        if as_of is None:
            day_sql, day_params = "(select max(as_of) from igsyc_point)", []
        elif on_or_before:
            day_sql, day_params = "(select max(as_of) from igsyc_point where as_of <= ?)", [as_of]
        else:
            day_sql, day_params = "?", [as_of]
        where, params = [f"as_of = {day_sql}"], day_params
        if max_tenor is not None:
            where.append("tenor_y <= ?")
            params = [*params, max_tenor]
        sql = ("select as_of, tenor_y, yield_pct, from_yesterday_column from igsyc_point"
               f" where {' and '.join(where)} order by tenor_y")
        return [CurvePoint(d, float(t), float(y), bool(f))
                for d, t, y, f in self._query("igsyc", sql, params)]

    def slopes(
        self, start: date | None = None, end: date | None = None, short: float = 2, long: float = 10
    ) -> list[CurveSlope]:
        """`long` - `short` (default 10Y - 2Y, as idxscape J8) per curve day with both tenors."""
        where, params = _window("a.as_of", start, end)
        sql = (
            "select a.as_of, a.yield_pct, b.yield_pct, b.yield_pct - a.yield_pct,"
            " a.from_yesterday_column or b.from_yesterday_column"
            " from igsyc_point a join igsyc_point b on a.as_of = b.as_of and b.tenor_y = ?"
            f" where {' and '.join(['a.tenor_y = ?', *where])} order by a.as_of"
        )
        return [CurveSlope(d, float(y2), float(y10), float(s), bool(f))
                for d, y2, y10, s, f in self._query("igsyc", sql, [long, short, *params])]

    # ---------------- bonds and credit ----------------

    def bond_quotes(self, as_of: date | None = None, grp: str | None = None) -> list[BondQuote]:
        """PHEI quotes on `as_of` (default: the newest day), optionally one group. Raw quotes:
        local use only."""
        if grp is not None and grp not in GROUPS:
            raise ValueError(f"grp must be one of {GROUPS}, got {grp!r}")
        day = "(select max(as_of) from phei_bond_quote)" if as_of is None else "?"
        where = [f"as_of = {day}"]
        params: list = [] if as_of is None else [as_of]
        if grp is not None:
            where.append("grp = ?")
            params.append(grp)
        sql = (
            "select as_of, series_code, grp, ttm_y, yield_pct, price_pct, coupon_pct,"
            f" from_yesterday_column from phei_bond_quote where {' and '.join(where)}"
            " order by grp, ttm_y nulls last, series_code"
        )
        return [BondQuote(d, c, g, _f(t), _f(y), _f(p), _f(cp), bool(f))
                for d, c, g, t, y, p, cp, f in self._query("bond", sql, params)]

    def credit_curve(self, as_of: date | None = None) -> list[CreditPoint]:
        """Credit curve points on `as_of` (default: the newest day), by tenor then rating."""
        day = "(select max(as_of) from credit_curve_point)" if as_of is None else "?"
        sql = ("select as_of, tenor_y, rating, yield_pct from credit_curve_point"
               f" where as_of = {day} order by tenor_y, rating")
        return [CreditPoint(d, float(t), r, float(y))
                for d, t, r, y in self._query("credit", sql, [] if as_of is None else [as_of])]
