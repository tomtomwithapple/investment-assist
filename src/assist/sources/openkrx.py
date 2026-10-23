"""openkrx adapter: KR/TW index-level series, DuckDB read-only over openkrx's `data/parquet`.

Not Postgres: openkrx's Postgres holds only ops tables (fetch_log, quota_ledger, ...); its data
is vintaged Parquet written by its P6 store, laid out as
`{dataset}/market={KR|TW}/date={yyyy-mm-dd}/part-*.parquet`. Every file carries `market` and the
date column itself (no hive partitioning), plus `vintage` (1, 2, ... per market + key) and
`observed_at` (UTC). The read is what openkrx's `{name}_latest` view does: the highest vintage per
market + key. `meta.duckdb` is not opened (it is a writer's file); this reads the files through an
in-memory DuckDB, which never locks them. The writer's temp parts (`.part-*.parquet.tmp`) never
match the glob.

Series (index level only for now, for P29 foreign candidates):

- `TW_INDEX.<index_name>.<measure>`: `tw_index` (TWSE MI_INDEX, T3), index names as TWSE prints
  them (Traditional Chinese, e.g. TAIEX = 發行量加權股價指數), measure `close`, `change` (signed
  points) or `change_pct`.
- `KR_INDEX.<family>.<index_name>.<measure>`: `krx_index_daily` (KRX spec §4; openkrx K3 is not
  built yet, so names and columns are the spec's), family `KOSPI|KOSDAQ|KRX|...`, measure one of
  `INDEX_MEASURES`. Values in index points; `value_krw` in KRW.
- `TW_ADJ.<code>.<measure>`: `tw_adjusted_daily` (V8, backward-adjusted prices and total return,
  e.g. the 0050 ETF as a TW total-return proxy). R1 says it is derived and fully recomputed, not
  vintaged; files without `vintage` are read as they are and their rows get `as_of` None.

`as_of` is the UTC date of `observed_at` (when openkrx stored that vintage), None without it. The
default `rows()` is every index close on disk (`indices()`); a store with no index dataset at all
is `missing`, as is a named series whose dataset has no files. A part DuckDB cannot read is
`error`. DART (`dart_*`) fundamentals are not read here yet.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import duckdb

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.sources.base import Row, SourceUnavailable

__all__ = [
    "ADJ_MEASURES",
    "INDEX_MEASURES",
    "KOSPI",
    "KOSPI200",
    "SOURCE",
    "TAIEX",
    "TW50",
    "TW_INDEX_MEASURES",
    "OpenkrxSource",
    "kr_index",
    "tw_adjusted",
    "tw_index",
]

SOURCE = "openkrx"
TW_PREFIX, KR_PREFIX, ADJ_PREFIX = "TW_INDEX.", "KR_INDEX.", "TW_ADJ."
TW_INDEX_MEASURES = ("change", "change_pct", "close")
INDEX_MEASURES = ("change", "change_pct", "close", "high", "low", "open", "value_krw", "volume")
ADJ_MEASURES = ("close_adj", "close_raw", "close_tr", "total_return", "tr_index")

# kind → (dataset, market, name columns). A series' "name" is the tuple of those columns' values.
DATASETS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "tw": ("tw_index", "TW", ("index_name",)),
    "kr": ("krx_index_daily", "KR", ("family", "index_name")),
    "adj": ("tw_adjusted_daily", "TW", ("code",)),
}
INDEX_KINDS = ("kr", "tw")


def tw_index(index_name: str, measure: str = "close") -> str:
    if not index_name or measure not in TW_INDEX_MEASURES:
        raise ValueError(f"need an index name and a measure in {TW_INDEX_MEASURES}")
    return f"{TW_PREFIX}{index_name}.{measure}"


def kr_index(family: str, index_name: str, measure: str = "close") -> str:
    if not family or "." in family or not index_name or measure not in INDEX_MEASURES:
        raise ValueError(f"need a family, an index name and a measure in {INDEX_MEASURES}")
    return f"{KR_PREFIX}{family}.{index_name}.{measure}"


def tw_adjusted(code: str, measure: str) -> str:
    if not code or "." in code or measure not in ADJ_MEASURES:
        raise ValueError(f"need a code and a measure in {ADJ_MEASURES}")
    return f"{ADJ_PREFIX}{code}.{measure}"


TAIEX = tw_index("發行量加權股價指數")
TW50 = tw_index("臺灣50指數")
# KRX's own index names (IDX_NM); unverified until openkrx K3 stores them.
KOSPI = kr_index("KOSPI", "코스피")
KOSPI200 = kr_index("KOSPI", "코스피 200")


def _parse(sid: str) -> tuple[str, tuple[str, ...], str]:
    """(kind, name tuple, measure); KeyError for an id this adapter does not know."""
    head, _, measure = sid.rpartition(".")
    if sid.startswith(TW_PREFIX) and measure in TW_INDEX_MEASURES:
        name = head.removeprefix(TW_PREFIX)
        if name:
            return "tw", (name,), measure
    elif sid.startswith(KR_PREFIX) and measure in INDEX_MEASURES:
        family, _, name = head.removeprefix(KR_PREFIX).partition(".")
        if family and name:
            return "kr", (family, name), measure
    elif sid.startswith(ADJ_PREFIX) and measure in ADJ_MEASURES:
        code = head.removeprefix(ADJ_PREFIX)
        if code and "." not in code:
            return "adj", (code,), measure
    raise KeyError(f"unknown openkrx series: {sid!r}")


def _sid(kind: str, name: tuple[str, ...], measure: str) -> str:
    return {"tw": tw_index, "kr": kr_index, "adj": tw_adjusted}[kind](*name, measure)


def _float(v) -> float | None:
    return None if v is None else float(v)


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


class OpenkrxSource:
    """openkrx's Parquet store as tidy rows, sorted by series and date."""

    name = SOURCE

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()

    @classmethod
    def from_config(cls, config: Path = DEFAULT_CONFIG, env: dict | None = None) -> OpenkrxSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    # ---------------- files ----------------

    def _glob(self, kind: str) -> str | None:
        """The dataset's Parquet glob, or None when it has no part files."""
        dataset, market, _ = DATASETS[kind]
        mdir = self.root / dataset / f"market={market}"
        if not any(mdir.glob("date=*/*.parquet")):
            return None
        return str(mdir / "date=*" / "*.parquet")

    def _check_root(self) -> None:
        if not self.root.is_dir():
            raise SourceUnavailable(self.name, "missing", f"no directory at {self.root}")

    def _query(self, kind: str, sql_of) -> list[tuple]:
        """Run `sql_of(latest_cte_sql, columns)` over the dataset's newest vintages."""
        dataset, market, keys = DATASETS[kind]
        glob = self._glob(kind)
        if glob is None:
            raise SourceUnavailable(self.name, "missing", f"no {dataset} parquet under {self.root}")
        files = (f"read_parquet({_quote(glob)}, hive_partitioning = false,"
                 " union_by_name = true)")
        con = duckdb.connect()
        try:
            cols = {c for (c, *_) in con.execute(f"describe select * from {files}").fetchall()}
            part = ", ".join(("market", *keys, "trade_date"))
            latest = (f"select * from {files} where market = {_quote(market)}"
                      + (f" qualify vintage = max(vintage) over (partition by {part})"
                         if "vintage" in cols else ""))
            return con.execute(sql_of(latest, cols)).fetchall()
        except duckdb.IOException as e:
            raise SourceUnavailable(self.name, "error", str(e).splitlines()[0][:200]) from e
        except duckdb.InvalidInputException as e:
            raise SourceUnavailable(self.name, "error", str(e).splitlines()[0][:200]) from e
        finally:
            con.close()

    # ---------------- reads ----------------

    def indices(self) -> list[str]:
        """Every index close series on disk (TW and KR), sorted."""
        self._check_root()
        out = []
        for kind in INDEX_KINDS:
            if self._glob(kind) is None:
                continue
            keys = DATASETS[kind][2]
            names = self._query(
                kind, lambda latest, _c, k=keys: f"select distinct {', '.join(k)} from ({latest})"
            )
            out += [_sid(kind, tuple(n), "close") for n in names]
        return sorted(out)

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        self._check_root()
        if series_ids is None:
            if all(self._glob(k) is None for k in INDEX_KINDS):
                names = ", ".join(DATASETS[k][0] for k in INDEX_KINDS)
                raise SourceUnavailable(self.name, "missing", f"no {names} parquet")
            series_ids = self.indices()
        wanted: dict[str, dict[tuple[str, ...], set[str]]] = {}
        for sid in set(series_ids):
            kind, name, measure = _parse(sid)
            wanted.setdefault(kind, {}).setdefault(name, set()).add(measure)
        out = []
        for kind, names in sorted(wanted.items()):
            out += self._rows(kind, names, start, end)
        return sorted(out, key=lambda r: (r.series_id, r.date))

    def _rows(self, kind, names, start, end) -> list[Row]:
        keys = DATASETS[kind][2]
        measures = sorted({m for ms in names.values() for m in ms})
        where = ["(" + " or ".join(
            "(" + " and ".join(f"{k} = {_quote(v)}" for k, v in zip(keys, n, strict=True)) + ")"
            for n in sorted(names)) + ")"]
        if start:
            where.append(f"trade_date >= date {_quote(start.isoformat())}")
        if end:
            where.append(f"trade_date <= date {_quote(end.isoformat())}")

        def sql(latest: str, cols: set[str]) -> str:
            as_of = ("cast(timezone('UTC', observed_at) as date)" if "observed_at" in cols
                     else "null::date")
            values = ", ".join(m if m in cols else f"null as {m}" for m in measures)
            return (f"select {', '.join(keys)}, trade_date, {values}, {as_of}"
                    f" from ({latest}) where {' and '.join(where)}")

        out = []
        n = len(keys)
        for rec in self._query(kind, sql):
            name, d, values, as_of = tuple(rec[:n]), rec[n], rec[n + 1:-1], rec[-1]
            for measure, v in zip(measures, values, strict=True):
                if measure in names[name]:
                    out.append(Row(_sid(kind, name, measure), d, _float(v), as_of, SOURCE))
        return out
