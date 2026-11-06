"""The adapter contract: every source yields tidy `Row`s, and every store is opened READ-ONLY.

A store that is missing, locked or down raises `SourceUnavailable`; callers turn it into a
`stale_inputs` entry (`read_rows` does this), never a crash. Anything else (a bad query, a 404)
is a bug and propagates. The openers build on the doctor's (S0), so both see a store the same way:

- DuckDB: `duckdb_ro` (own read-only connection) or `attach_ro` (ATTACH ... READ_ONLY into a
  shared connection); `open_query_close` for dbnomics, whose lock is mutual (any open reader
  blocks `dbn refresh`), so nothing may stay open.
- SQLite: `sqlite_ro` (`file:...?mode=ro`, `immutable=1` for a WAL file with no writer).
- Postgres: `postgres_ro` through DuckDB's postgres extension (never auto-installed).
- HTTP CSV: `http_csv`, localhost only (sec-edgar `usfin serve`, dbnomics `dbn serve`).
"""

from __future__ import annotations

import csv
import io
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import NamedTuple, Protocol, runtime_checkable

import duckdb
import httpx

from assist.doctor import (
    HTTP_TIMEOUT,
    Locked,
    Missing,
    SourceStatus,
    check_local_url,
    duckdb_locked,
    open_postgres,
    open_sqlite,
    redact_dsn,
)

__all__ = [
    "REASONS",
    "Row",
    "Source",
    "SourceStatus",
    "SourceUnavailable",
    "attach_ro",
    "duckdb_ro",
    "http_csv",
    "open_query_close",
    "postgres_ro",
    "read_rows",
    "sqlite_ro",
]

REASONS = ("missing", "locked", "error")


class Row(NamedTuple):
    """One observation. `as_of` is when the source published or revised it (None if unknown)."""

    series_id: str
    date: date
    value: float | None
    as_of: date | None
    source: str


class SourceUnavailable(Exception):
    """The store is missing, locked or down. Reported in `stale_inputs`, never fatal."""

    def __init__(self, source: str, reason: str, detail: str = ""):
        if reason not in REASONS:
            raise ValueError(f"reason must be one of {REASONS}, got {reason!r}")
        self.source, self.reason, self.detail = source, reason, detail
        super().__init__(f"{source} {reason}" + (f": {detail}" if detail else ""))

    @property
    def stale_input(self) -> str:
        return f"{self.source} ({self.reason})"


@runtime_checkable
class Source(Protocol):
    """A sibling store seen as tidy rows. Adapters filter by series id and date (inclusive)."""

    name: str

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]: ...


def read_rows(source: Source, *args, **kwargs) -> tuple[list[Row], list[str]]:
    """`source.rows(...)`, with an unavailable store turned into a `stale_inputs` entry."""
    try:
        return source.rows(*args, **kwargs), []
    except SourceUnavailable as e:
        return [], [e.stale_input]


# ---------------- DuckDB ----------------


def _first_line(e: Exception) -> str:
    return (str(e).splitlines() or [""])[0][:200]


def _from_duckdb(e: duckdb.Error, source: str) -> SourceUnavailable:
    reason = "locked" if duckdb_locked(str(e)) else "error"
    return SourceUnavailable(source, reason, _first_line(e))


def _require_file(path: Path | str, source: str) -> str:
    p = Path(path).expanduser()
    if not p.is_file():
        raise SourceUnavailable(source, "missing", f"no file at {p}")
    return str(p)


@contextmanager
def duckdb_ro(path: Path | str, source: str) -> Iterator[duckdb.DuckDBPyConnection]:
    path = _require_file(path, source)
    try:
        con = duckdb.connect(path, read_only=True)
    except duckdb.Error as e:
        raise _from_duckdb(e, source) from e
    try:
        yield con
    finally:
        con.close()


def attach_ro(con: duckdb.DuckDBPyConnection, path: Path | str, alias: str, source: str) -> None:
    """ATTACH a DuckDB file READ_ONLY as `alias` into a shared connection."""
    path = _require_file(path, source)
    quoted = path.replace("'", "''")
    try:
        con.execute(f"attach '{quoted}' as \"{alias}\" (read_only)")
    except duckdb.Error as e:
        raise _from_duckdb(e, source) from e


def open_query_close(
    path: Path | str, sql: str, params: Sequence | None = None, source: str = "dbnomics"
) -> tuple[list[str], list[tuple]]:
    """Open read-only, run one query, close straight away: for stores whose lock is mutual."""
    with duckdb_ro(path, source) as con:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return cols, cur.fetchall()


# ---------------- SQLite ----------------


@contextmanager
def sqlite_ro(path: Path | str, source: str) -> Iterator[sqlite3.Connection]:
    try:
        con = open_sqlite(str(Path(path).expanduser()))
    except Missing as e:
        raise SourceUnavailable(source, "missing", str(e)) from e
    except Locked as e:
        raise SourceUnavailable(source, "locked", str(e)) from e
    except sqlite3.Error as e:
        raise SourceUnavailable(source, "error", _first_line(e)) from e
    try:
        yield con
    finally:
        con.close()


# ---------------- Postgres ----------------


@contextmanager
def postgres_ro(dsn: str, source: str) -> Iterator[duckdb.DuckDBPyConnection]:
    """A DuckDB connection with the database attached READ_ONLY and selected (`use src`)."""
    try:
        con = open_postgres(dsn)
    except Missing as e:
        raise SourceUnavailable(source, "missing", str(e)) from e
    except (RuntimeError, duckdb.Error) as e:
        raise SourceUnavailable(source, "error", redact_dsn(_first_line(e))) from e
    try:
        yield con
    finally:
        con.close()


# ---------------- HTTP CSV ----------------


def http_csv(
    client: httpx.Client, url: str, source: str, params: dict | None = None,
    timeout: float = HTTP_TIMEOUT,
) -> list[dict[str, str]]:
    """GET `url?format=csv` from a localhost server → one dict per CSV row.

    Server down → missing; 503 (busy, e.g. dbnomics refresh holding the lock) → locked; other
    5xx → error. A 4xx is a wrong path or id, so it raises."""
    check_local_url(url)
    try:
        r = client.get(url, params={**(params or {}), "format": "csv"}, timeout=timeout)
    except httpx.TransportError as e:
        raise SourceUnavailable(source, "missing", f"{url}: {type(e).__name__}") from e
    if r.status_code >= 500:
        reason = "locked" if r.status_code == 503 else "error"
        raise SourceUnavailable(source, reason, f"{url}: HTTP {r.status_code} {r.text[:100]}")
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))
