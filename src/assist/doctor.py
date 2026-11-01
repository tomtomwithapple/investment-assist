"""`assist doctor`: is each sibling store present, missing, locked or stale, and how new is it?

Every store is opened READ-ONLY and closed straight away (DuckDB `read_only`, SQLite
`mode=ro`, Postgres through DuckDB's postgres extension with READ_ONLY, HTTP only to localhost).
Nothing here raises for an unavailable source: it becomes a status, so the doctor never fails a
run. Paths and probes live in `config/sources.yaml`.
"""

from __future__ import annotations

import csv
import glob
import io
import json
import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
import httpx
import yaml

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO / "config" / "sources.yaml"
ACCESS_KINDS = ("duckdb", "sqlite", "postgres", "http", "files")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
HTTP_TIMEOUT = 5.0

# Source status, worst first; probe status is fresh | stale | future | empty | absent | error.
STATUSES = ("missing", "locked", "error", "stale", "present")


class Locked(Exception):
    pass


class Missing(Exception):
    pass


class Absent(Exception):
    """The store opened but the probed table or file is not there."""


@dataclass
class Probe:
    name: str
    max_age_days: int
    sql: str | None = None
    http: str | None = None
    csv: str | None = None
    json: str | None = None
    parquet: str | None = None
    sqlite: str | None = None
    column: str | None = None
    field: str | None = None
    optional: bool = False


@dataclass
class Source:
    name: str
    access: str
    env: str
    probes: list[Probe]
    location: str | None = None  # file or directory path, or a password-free DSN
    url: str | None = None
    dsn: str | None = None
    repo: str | None = None
    layers: list[int] = field(default_factory=list)


@dataclass
class ProbeResult:
    name: str
    status: str
    newest: date | None = None
    age_days: int | None = None
    max_age_days: int | None = None
    detail: str = ""


@dataclass
class SourceStatus:
    name: str
    access: str
    location: str | None
    status: str
    via: str | None = None
    newest: date | None = None
    probes: list[ProbeResult] = field(default_factory=list)
    detail: str = ""

    def to_json(self) -> dict:
        d = asdict(self)
        d["newest"] = self.newest.isoformat() if self.newest else None
        for p in d["probes"]:
            p["newest"] = p["newest"].isoformat() if p["newest"] else None
        return d


# ---------------- config ----------------


def siblings_root(env: dict) -> Path:
    return Path(env.get("ASSIST_SIBLINGS_ROOT") or REPO.parent)


def _resolve(path: str, root: Path) -> str:
    p = Path(path).expanduser()
    return str(p if p.is_absolute() else root / p)


def load_sources(
    config: Path = DEFAULT_CONFIG, root: Path | None = None, env: dict | None = None
) -> list[Source]:
    env = dict(os.environ) if env is None else env
    root = Path(root) if root is not None else siblings_root(env)
    raw = yaml.safe_load(Path(config).read_text(encoding="utf-8"))["sources"]
    sources = []
    for name, spec in raw.items():
        access = spec["access"]
        if access not in ACCESS_KINDS:
            raise ValueError(f"{name}: access must be one of {ACCESS_KINDS}, got {access!r}")
        envvar = spec["env"]
        src = Source(
            name=name,
            access=access,
            env=envvar,
            probes=[Probe(**p) for p in spec["probes"]],
            repo=spec.get("repo"),
            layers=spec.get("layers", []),
        )
        if access == "postgres":
            src.dsn = libpq_dsn(env.get(envvar) or spec["dsn"])
            src.location = redact_dsn(src.dsn)
        else:
            path = env.get(envvar) or spec.get("path")
            src.location = _resolve(path, root) if path else None
        if access == "http":
            src.url = (env.get(spec["url_env"]) if spec.get("url_env") else None) or spec["url"]
        sources.append(src)
    return sources


def libpq_dsn(dsn: str) -> str:
    """SQLAlchemy URLs (`postgresql+psycopg://`) → a URI libpq and DuckDB accept."""
    return re.sub(r"^postgres(ql)?\+\w+://", "postgresql://", dsn)


def redact_dsn(dsn: str) -> str:
    return re.sub(r"(://[^:/@]+):[^@]*@", r"\1:***@", dsn)


# ---------------- dates ----------------


def as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def newest_until(values, today: date) -> tuple[date | None, bool]:
    """Max date not after today, and whether any later date was dropped."""
    dates = [d for d in (as_date(v) for v in values) if d is not None]
    past = [d for d in dates if d <= today]
    return (max(past) if past else None), len(past) < len(dates)


def judge(probe: Probe, newest: date | None, today: date, had_future: bool = False):
    if newest is None:
        status = "future" if had_future else "empty"
        return ProbeResult(probe.name, status, max_age_days=probe.max_age_days)
    age = (today - newest).days
    if age < 0:
        return ProbeResult(
            probe.name, "future", newest, age, probe.max_age_days, "newest date is after today"
        )
    status = "stale" if age > probe.max_age_days else "fresh"
    return ProbeResult(probe.name, status, newest, age, probe.max_age_days)


# ---------------- store access ----------------


def duckdb_locked(msg: str) -> bool:
    """A DuckDB error from another process holding the file: "Conflicting lock" on macOS and
    Linux, "being used by another process" on Windows, which has no "lock" in it."""
    m = msg.lower()
    return "lock" in m or "being used by another process" in m


def _duckdb_error(e: Exception) -> Exception:
    msg = str(e)
    if duckdb_locked(msg):
        return Locked(msg.splitlines()[0])
    return e


def _absent(msg: str) -> bool:
    m = msg.lower()
    return "does not exist" in m or "no such table" in m or "not found" in m


def open_duckdb(path: str) -> duckdb.DuckDBPyConnection:
    if not Path(path).is_file():
        raise Missing(f"no file at {path}")
    try:
        return duckdb.connect(path, read_only=True)
    except duckdb.Error as e:
        raise _duckdb_error(e) from e


def open_sqlite(path: str) -> sqlite3.Connection:
    """Read-only, without leaving a file beside the store. A WAL-mode file whose `-shm` is
    absent (no writer has it open, e.g. jquantster's) would get a new `-shm` from mode=ro, or
    fail to open, so it is read with immutable=1; with no -shm there is no live writer."""
    p = Path(path)
    if not p.is_file():
        raise Missing(f"no file at {path}")
    uri = p.resolve().as_uri() + "?mode=ro"
    if _is_wal(p) and not p.with_name(p.name + "-shm").exists():
        uri += "&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=0.2)
        con.execute("select count(*) from sqlite_master").fetchone()
    except sqlite3.OperationalError as e:
        if "locked" in str(e):
            raise Locked(str(e)) from e
        raise
    return con


def _is_wal(path: Path) -> bool:
    with path.open("rb") as f:
        header = f.read(20)
    return len(header) == 20 and header[18] == 2 and header[19] == 2


def query_one(con, sql: str):
    try:
        row = con.execute(sql).fetchone()
    except sqlite3.OperationalError as e:
        if "locked" in str(e):
            raise Locked(str(e)) from e
        if _absent(str(e)):
            raise Absent(str(e)) from e
        raise
    except duckdb.CatalogException as e:
        raise Absent(str(e).splitlines()[0]) from e
    return row[0] if row else None


def open_postgres(dsn: str) -> duckdb.DuckDBPyConnection:
    """Postgres through DuckDB's postgres extension. Never installs it (that would fetch from
    the internet): it must already be installed, once, with `INSTALL postgres`."""
    con = duckdb.connect()
    con.execute("set autoinstall_known_extensions = false")
    try:
        con.execute("load postgres")
    except duckdb.Error as e:
        con.close()
        raise RuntimeError(
            "duckdb postgres extension not installed (run once: INSTALL postgres)"
        ) from e
    try:
        con.execute(f"attach '{dsn}' as src (type postgres, read_only)")
    except duckdb.Error as e:
        con.close()
        raise Missing(redact_dsn(str(e).splitlines()[0])) from e
    con.execute("use src")
    return con


def check_local_url(url: str) -> None:
    host = urlsplit(url).hostname
    if host not in LOCAL_HOSTS:
        raise ValueError(f"{url}: HTTP sources must be on localhost")


def http_newest(client: httpx.Client, url: str, probe: Probe, today: date):
    check_local_url(url)
    r = client.get(url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    rows = csv.DictReader(io.StringIO(r.text))
    return newest_until((row.get(probe.column) for row in rows), today)


def file_newest(root: Path, probe: Probe, today: date):
    if probe.csv:
        path = root / probe.csv
        if not path.is_file():
            raise Absent(f"no file {path}")
        with path.open(newline="", encoding="utf-8") as f:
            return newest_until((row.get(probe.column) for row in csv.DictReader(f)), today)
    if probe.json:
        path = root / probe.json
        if not path.is_file():
            raise Absent(f"no file {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return newest_until(_json_field(payload, probe.field), today)
    if probe.parquet:
        pattern = str(root / probe.parquet)
        if not glob.glob(pattern, recursive=True):
            raise Absent(f"no parquet under {pattern}")
        con = duckdb.connect()
        try:
            value = con.execute(
                f"select max({probe.column}) from read_parquet(?, hive_partitioning = true)"
                f" where {probe.column} <= ?",
                [pattern, today],
            ).fetchone()[0]
        finally:
            con.close()
        return as_date(value), False
    if probe.sqlite:
        path = root / probe.sqlite
        if not path.is_file():
            raise Absent(f"no file {path}")
        con = open_sqlite(str(path))
        try:
            return newest_until([query_one(con, probe.sql)], today)
        finally:
            con.close()
    raise ValueError(f"probe {probe.name}: files probes need csv, json, parquet or sqlite")


def _json_field(doc, dotted: str):
    values = [doc]
    for key in dotted.split("."):
        nxt = []
        for v in values:
            if isinstance(v, list):
                nxt.extend(x.get(key) for x in v if isinstance(x, dict))
            elif isinstance(v, dict):
                nxt.append(v.get(key))
        values = nxt
    out = []
    for v in values:
        out.extend(v if isinstance(v, list) else [v])
    return out


# ---------------- checks ----------------


def _run_probe(probe: Probe, fn, today: date) -> ProbeResult:
    try:
        newest, had_future = fn()
    except Absent as e:
        status = "absent" if probe.optional else "error"
        return ProbeResult(probe.name, status, max_age_days=probe.max_age_days, detail=str(e))
    except (Locked, Missing):
        raise
    except Exception as e:  # noqa: BLE001 - a probe failure is a status, never a crash
        return _probe_error(probe, e)
    return judge(probe, newest, today, had_future)


def _probe_error(probe: Probe, e: Exception) -> ProbeResult:
    return ProbeResult(
        probe.name,
        "error",
        max_age_days=probe.max_age_days,
        detail=f"{type(e).__name__}: {str(e).splitlines()[0][:200]}",
    )


def _probe_sql(con, probe: Probe, today: date) -> ProbeResult:
    return _run_probe(probe, lambda: newest_until([query_one(con, probe.sql)], today), today)


def _check_db(src: Source, today: date, opener, location: str) -> list[ProbeResult]:
    con = opener(location)
    try:
        return [_probe_sql(con, p, today) for p in src.probes if p.sql]
    finally:
        con.close()


def _check_files(src: Source, today: date) -> list[ProbeResult]:
    root = Path(src.location)
    if not root.is_dir():
        raise Missing(f"no directory at {root}")
    return [_run_probe(p, lambda p=p: file_newest(root, p, today), today) for p in src.probes]


def _check_http(src: Source, today: date, client: httpx.Client | None):
    """HTTP first; if the server is down, a read-only open of the DuckDB file."""
    http_detail = ""
    if client is not None:
        try:
            check_local_url(src.url)
            results = []
            for p in src.probes:
                if not p.http:
                    continue
                url = src.url.rstrip("/") + p.http
                try:
                    newest, had_future = http_newest(client, url, p, today)
                except httpx.TransportError:
                    raise
                except Exception as e:  # noqa: BLE001 - a probe failure is a status
                    results.append(_probe_error(p, e))
                    continue
                results.append(judge(p, newest, today, had_future))
            return results, "http", ""
        except (httpx.TransportError, ValueError) as e:
            http_detail = f"{src.url} unavailable ({type(e).__name__}: {e})"
    if not src.location:
        raise Missing(http_detail or "no URL reachable and no store path")
    try:
        results = _check_db(src, today, open_duckdb, src.location)
    except Missing as e:
        raise Missing("; ".join(x for x in (http_detail, str(e)) if x)) from e
    return results, "duckdb", http_detail


def check_source(src: Source, today: date, http_client: httpx.Client | None = None) -> SourceStatus:
    st = SourceStatus(src.name, src.access, src.location, "present")
    try:
        if src.access == "duckdb":
            st.probes = _check_db(src, today, open_duckdb, src.location)
            st.via = "duckdb"
        elif src.access == "sqlite":
            st.probes = _check_db(src, today, open_sqlite, src.location)
            st.via = "sqlite"
        elif src.access == "postgres":
            st.probes = _check_db(src, today, open_postgres, src.dsn)
            st.via = "postgres"
        elif src.access == "files":
            st.probes = _check_files(src, today)
            st.via = "files"
        elif src.access == "http":
            st.probes, st.via, st.detail = _check_http(src, today, http_client)
    except Missing as e:
        st.status, st.detail = "missing", str(e)
        return st
    except Locked as e:
        st.status, st.detail = "locked", str(e)
        return st
    except Exception as e:  # noqa: BLE001 - never fail the run for one source
        st.status, st.detail = "error", f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
        return st
    dates = [p.newest for p in st.probes if p.newest]
    st.newest = max(dates) if dates else None
    kinds = {p.status for p in st.probes}
    if "error" in kinds:
        st.status = "error"
    elif kinds & {"stale", "empty"}:
        st.status = "stale"
    return st


def run_doctor(
    sources: list[Source], today: date, http_client: httpx.Client | None = None
) -> list[SourceStatus]:
    return [check_source(s, today, http_client) for s in sources]


def format_report(statuses: list[SourceStatus], today: date) -> str:
    lines = [f"assist doctor — {today.isoformat()} (read-only)", ""]
    w = max((len(s.name) for s in statuses), default=10)
    for s in statuses:
        newest = s.newest.isoformat() if s.newest else "-"
        via = f"via {s.via}" if s.via else ""
        lines.append(f"{s.name:<{w}}  {s.status:<7}  {newest:<10}  {via:<12}  {s.location or ''}")
        if s.detail:
            lines.append(f"{'':<{w}}    {s.detail}")
        for p in s.probes:
            pn = p.newest.isoformat() if p.newest else "-"
            age = f"{p.age_days}d/{p.max_age_days}d" if p.age_days is not None else ""
            extra = f"  {p.detail}" if p.detail else ""
            lines.append(f"{'':<{w}}    - {p.name:<24} {p.status:<7} {pn:<10} {age}{extra}")
    counts = {k: sum(s.status == k for s in statuses) for k in STATUSES}
    lines += ["", ", ".join(f"{v} {k}" for k, v in counts.items() if v)]
    return "\n".join(lines)
