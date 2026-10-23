"""Builders for tiny fixture stores, shared by every adapter test. Nothing here touches the real
sibling stores or the network."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
STANCE_FIXTURES = FIXTURES / "stance"


def make_duckdb(path: Path, ddl: str, rows: dict[str, list[tuple]] | None = None) -> Path:
    """A DuckDB file with `ddl` run and `rows` inserted per table; closed before returning."""
    con = duckdb.connect(str(path))
    try:
        con.execute(ddl)
        for table, values in (rows or {}).items():
            for row in values:
                marks = ", ".join("?" for _ in row)
                con.execute(f"insert into {table} values ({marks})", list(row))
    finally:
        con.close()
    return path


def make_sqlite(path: Path, ddl: str, rows: dict[str, list[tuple]] | None = None) -> Path:
    con = sqlite3.connect(path)
    try:
        con.executescript(ddl)
        for table, values in (rows or {}).items():
            for row in values:
                marks = ", ".join("?" for _ in row)
                con.execute(f"insert into {table} values ({marks})", row)
        con.commit()
    finally:
        con.close()
    return path


@contextmanager
def hold_duckdb_lock(path: Path) -> Iterator[None]:
    """Hold a read-write connection on `path` in another process, as a fetcher's refresh does.
    DuckDB locks per process, so an in-process connection would not reproduce the lock."""
    code = (
        "import sys, duckdb\n"
        "con = duckdb.connect(sys.argv[1])\n"
        "print('locked', flush=True)\n"
        "sys.stdin.read()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        yield
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def load_stances() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(STANCE_FIXTURES.glob("*.json"))]
