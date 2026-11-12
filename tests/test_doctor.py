"""assist doctor: per source present / missing / locked / stale with its newest date.

Fixtures are built in tmp_path (tiny DuckDB, SQLite, CSV, JSON, Parquet) from the real stores'
schemas; nothing here opens a real store or the network."""

import json
import socket
import sqlite3
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import duckdb
import httpx
import pytest
import yaml

from assist import doctor
from assist.cli import main

REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 23)
EXPECTED_SOURCES = {
    "sec-edgar",
    "bisfetcher",
    "worldbankscape",
    "bps-looker",
    "ausdata",
    "singstat",
    "dbnomics",
    "satudatascape",
    "jquantster",
    "idxscape",
    "kseistat",
    "idx-method",
    "openkrx",
    "financer",
}


def write_config(tmp_path: Path, sources: dict) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump({"sources": sources}))
    return path


def one(tmp_path: Path, name: str, spec: dict, http_client=None, env=None):
    cfg = write_config(tmp_path, {name: spec})
    (src,) = doctor.load_sources(cfg, root=tmp_path, env=env or {})
    return doctor.check_source(src, TODAY, http_client=http_client)


def make_duckdb(path: Path, sql: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(sql)
    con.close()
    return path


def make_sqlite(path: Path, sql: str, wal: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    if wal:
        con.execute("pragma journal_mode=wal")
    con.executescript(sql)
    con.commit()
    con.close()
    return path


IDXSCAPE_SQL = """
create table stock_summary (trade_date date, stock_code varchar);
insert into stock_summary values ('2026-10-20', 'BBCA'), ('2026-10-21', 'BBCA');
"""


# ---------------- config ----------------


def test_config_lists_all_14_sources_with_access_env_and_probe():
    sources = doctor.load_sources(REPO / "config" / "sources.yaml", root=Path("/siblings"), env={})
    assert {s.name for s in sources} == EXPECTED_SOURCES
    for s in sources:
        assert s.access in doctor.ACCESS_KINDS, s.name
        assert s.env and s.env.startswith("ASSIST_"), s.name
        assert s.probes, s.name
        assert all(p.max_age_days > 0 for p in s.probes), s.name


def test_config_access_kinds_follow_the_siblings():
    by_name = {
        s.name: s
        for s in doctor.load_sources(REPO / "config" / "sources.yaml", root=Path("/r"), env={})
    }
    assert by_name["satudatascape"].access == "sqlite"
    assert by_name["satudatascape"].location == str(Path("/r/satudatascape/data/satudata.db"))
    assert by_name["openkrx"].access == "files"
    assert by_name["openkrx"].location == str(Path("/r/openkrx/data/parquet"))
    assert by_name["bps-looker"].access == "postgres"
    assert by_name["sec-edgar"].access == "http"
    assert by_name["financer"].location == str(Path("~/.financer/financer.db").expanduser())


def test_env_overrides_path_and_url(tmp_path):
    cfg = write_config(
        tmp_path,
        {
            "x": {
                "access": "http",
                "url": "http://127.0.0.1:1",
                "url_env": "X_URL",
                "path": "x/x.duckdb",
                "env": "X_DB",
                "probes": [{"name": "p", "sql": "select 1", "max_age_days": 1}],
            },
        },
    )
    (src,) = doctor.load_sources(
        cfg, root=tmp_path, env={"X_DB": str(tmp_path / "elsewhere" / "x.duckdb"),
                                 "X_URL": "http://127.0.0.1:2"}
    )
    assert src.location == str(tmp_path / "elsewhere" / "x.duckdb")
    assert src.url == "http://127.0.0.1:2"


def test_siblings_root_env(tmp_path):
    cfg = write_config(
        tmp_path,
        {
            "x": {
                "access": "duckdb",
                "path": "x/x.duckdb",
                "env": "X_DB",
                "probes": [{"name": "p", "sql": "select 1", "max_age_days": 1}],
            },
        },
    )
    (src,) = doctor.load_sources(cfg, env={"ASSIST_SIBLINGS_ROOT": "/sib"})
    assert src.location == str(Path("/sib/x/x.duckdb"))


# ---------------- duckdb ----------------


def duck_spec(**probe):
    return {
        "access": "duckdb",
        "path": "idxscape/data/idxscape.duckdb",
        "env": "X",
        "probes": [
            {
                "name": "stock_summary",
                "sql": "select max(trade_date) from stock_summary",
                "max_age_days": 7,
                **probe,
            }
        ],
    }


def test_duckdb_present_with_newest_date(tmp_path):
    make_duckdb(tmp_path / "idxscape/data/idxscape.duckdb", IDXSCAPE_SQL)
    st = one(tmp_path, "idxscape", duck_spec())
    assert st.status == "present"
    assert st.newest == date(2026, 10, 21)
    assert st.probes[0].age_days == 2


def test_duckdb_stale_when_older_than_max_age(tmp_path):
    make_duckdb(tmp_path / "idxscape/data/idxscape.duckdb", IDXSCAPE_SQL)
    st = one(tmp_path, "idxscape", duck_spec(max_age_days=1))
    assert st.status == "stale"
    assert st.probes[0].status == "stale"


def test_missing_store_is_reported_not_raised(tmp_path):
    st = one(tmp_path, "idxscape", duck_spec())
    assert st.status == "missing"
    assert st.newest is None


def test_duckdb_locked_by_a_writer(tmp_path):
    db = make_duckdb(tmp_path / "idxscape/data/idxscape.duckdb", IDXSCAPE_SQL)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(f"""
            import duckdb, sys
            con = duckdb.connect({str(db)!r})
            print("ready", flush=True)
            sys.stdin.read()
        """),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        st = one(tmp_path, "idxscape", duck_spec())
    finally:
        holder.stdin.close()
        holder.wait(timeout=10)
    assert st.status == "locked"


def test_duckdb_is_opened_read_only(tmp_path):
    db = make_duckdb(tmp_path / "idxscape/data/idxscape.duckdb", IDXSCAPE_SQL)
    before = db.stat().st_mtime_ns
    one(tmp_path, "idxscape", duck_spec())
    assert db.stat().st_mtime_ns == before
    assert not (tmp_path / "idxscape/data/idxscape.duckdb.wal").exists()


def test_optional_probe_on_absent_table_is_not_stale(tmp_path):
    make_duckdb(tmp_path / "idxscape/data/idxscape.duckdb", IDXSCAPE_SQL)
    spec = duck_spec()
    spec["probes"].append(
        {
            "name": "igsyc_point PHEI",
            "sql": "select max(as_of) from igsyc_point",
            "max_age_days": 7,
            "optional": True,
        }
    )
    st = one(tmp_path, "idxscape", spec)
    assert st.status == "present"
    assert st.probes[1].status == "absent"


def test_required_probe_on_absent_table_is_an_error_not_a_crash(tmp_path):
    make_duckdb(tmp_path / "idxscape/data/idxscape.duckdb", IDXSCAPE_SQL)
    st = one(tmp_path, "idxscape", duck_spec(sql="select max(as_of) from nope"))
    assert st.status == "error"
    assert st.probes[0].status == "error"


def test_future_dates_are_ignored(tmp_path):
    make_duckdb(
        tmp_path / "a/warehouse.duckdb",
        """
        create table observations (date date);
        insert into observations values ('2026-10-01'), ('2026-12-31');
    """,
    )
    st = one(
        tmp_path,
        "ausdata",
        {
            "access": "duckdb",
            "path": "a/warehouse.duckdb",
            "env": "X",
            "probes": [
                {"name": "obs", "sql": "select max(date) from observations", "max_age_days": 45}
            ],
        },
    )
    assert st.newest is None or st.newest <= TODAY
    assert st.probes[0].status == "future"


def test_empty_required_table_makes_the_source_stale(tmp_path):
    make_duckdb(
        tmp_path / "idxscape/data/idxscape.duckdb", "create table stock_summary (trade_date date)"
    )
    st = one(tmp_path, "idxscape", duck_spec())
    assert st.probes[0].status == "empty"
    assert st.status == "stale"


# ---------------- sqlite ----------------


def sqlite_spec(sql="select max(as_of) from holdings"):
    return {
        "access": "sqlite",
        "path": "f/financer.db",
        "env": "X",
        "probes": [{"name": "holdings", "sql": sql, "max_age_days": 45}],
    }


def test_sqlite_present(tmp_path):
    make_sqlite(
        tmp_path / "f/financer.db",
        """
        create table holdings (as_of text, account text);
        insert into holdings values ('2026-09-30', 'a'), ('2026-08-31', 'a');
    """,
    )
    st = one(tmp_path, "financer", sqlite_spec())
    assert st.status == "present"
    assert st.newest == date(2026, 9, 30)


def test_sqlite_wal_without_shm_still_reads(tmp_path):
    # jquantster's file is in WAL mode with no -shm beside it; mode=ro alone cannot open that.
    db = make_sqlite(
        tmp_path / "f/financer.db",
        """
        create table holdings (as_of text);
        insert into holdings values ('2026-10-20');
    """,
        wal=True,
    )
    assert not db.with_name("financer.db-shm").exists()
    st = one(tmp_path, "financer", sqlite_spec())
    assert st.status == "present"
    assert st.newest == date(2026, 10, 20)
    assert not db.with_name("financer.db-shm").exists()


def test_sqlite_locked(tmp_path):
    db = make_sqlite(
        tmp_path / "f/financer.db",
        """
        create table holdings (as_of text);
        insert into holdings values ('2026-10-20');
    """,
    )
    writer = sqlite3.connect(db, isolation_level=None)
    writer.execute("begin exclusive")
    try:
        st = one(tmp_path, "financer", sqlite_spec())
    finally:
        writer.execute("rollback")
        writer.close()
    assert st.status == "locked"


def test_sqlite_missing(tmp_path):
    st = one(tmp_path, "satudatascape", sqlite_spec())
    assert st.status == "missing"
    assert not (tmp_path / "f/financer.db").exists()


# ---------------- files ----------------


def test_csv_probe_frozen_series_is_stale(tmp_path):
    d = tmp_path / "idx-method/data"
    d.mkdir(parents=True)
    (d / "jkse_daily.csv").write_text(
        "date,open,high,low,close,volume\n2026-09-29,1,1,1,1,1\n2026-09-30,1,1,1,1,1\n"
    )
    st = one(
        tmp_path,
        "idx-method",
        {
            "access": "files",
            "path": "idx-method",
            "env": "X",
            "probes": [
                {
                    "name": "jkse_daily.csv",
                    "csv": "data/jkse_daily.csv",
                    "column": "date",
                    "max_age_days": 7,
                }
            ],
        },
    )
    assert st.status == "stale"
    assert st.newest == date(2026, 9, 30)
    assert st.probes[0].age_days == 23


def test_sqlite_probe_inside_a_files_source(tmp_path):
    make_sqlite(
        tmp_path / "idx-method/store/data/stockbiter.db",
        """
        create table bars (date text, code text);
        insert into bars values ('2026-10-22', 'BBCA');
    """,
    )
    st = one(
        tmp_path,
        "idx-method",
        {
            "access": "files",
            "path": "idx-method",
            "env": "X",
            "probes": [
                {
                    "name": "bars",
                    "sqlite": "store/data/stockbiter.db",
                    "sql": "select max(date) from bars",
                    "max_age_days": 7,
                }
            ],
        },
    )
    assert st.status == "present"
    assert st.newest == date(2026, 10, 22)


def test_json_probe_over_a_list(tmp_path):
    out = tmp_path / "worldbankscape/out"
    out.mkdir(parents=True)
    (out / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.2.0",
                "entries": [
                    {"subject": "IDN", "asset_class": "bonds", "as_of": "2026-10-23"},
                    {"subject": "AUS", "asset_class": "bonds", "as_of": "2026-10-22"},
                ],
            }
        )
    )
    st = one(
        tmp_path,
        "worldbankscape",
        {
            "access": "files",
            "path": "worldbankscape/out",
            "env": "X",
            "probes": [
                {
                    "name": "index",
                    "json": "index.json",
                    "field": "entries.as_of",
                    "max_age_days": 45,
                }
            ],
        },
    )
    assert st.status == "present"
    assert st.newest == date(2026, 10, 23)


def test_parquet_probe_with_hive_partitions(tmp_path):
    root = tmp_path / "openkrx/data/parquet"
    for d in ("2026-10-20", "2026-10-22"):
        part = root / f"dart_filing/market=KR/date={d}"
        part.mkdir(parents=True)
        duckdb.sql("select 'x' as rcept_no").write_parquet(str(part / "part-0.parquet"))
    st = one(
        tmp_path,
        "openkrx",
        {
            "access": "files",
            "path": "openkrx/data/parquet",
            "env": "X",
            "probes": [
                {
                    "name": "dart_filing",
                    "parquet": "dart_filing/**/*.parquet",
                    "column": "date",
                    "max_age_days": 7,
                }
            ],
        },
    )
    assert st.status == "present"
    assert st.newest == date(2026, 10, 22)


def test_files_source_missing_dir(tmp_path):
    st = one(
        tmp_path,
        "openkrx",
        {
            "access": "files",
            "path": "openkrx/data/parquet",
            "env": "X",
            "probes": [
                {
                    "name": "dart_filing",
                    "parquet": "dart_filing/**/*.parquet",
                    "column": "date",
                    "max_age_days": 7,
                }
            ],
        },
    )
    assert st.status == "missing"


# ---------------- http (with duckdb fallback) ----------------


def http_spec():
    return {
        "access": "http",
        "url": "http://127.0.0.1:8660",
        "path": "s/usfin.duckdb",
        "env": "X",
        "probes": [
            {
                "name": "fred VIXCLS",
                "http": "/series/fred/VIXCLS?format=csv",
                "column": "date",
                "sql": "select max(date) from fred_observation_latest",
                "max_age_days": 7,
            }
        ],
    }


def test_http_probe_reads_csv(tmp_path):
    def handler(request):
        assert request.url.host == "127.0.0.1"
        assert request.url.path == "/series/fred/VIXCLS"
        return httpx.Response(200, text="date,value\n2026-10-21,17.1\n2026-10-22,16.9\n")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    st = one(tmp_path, "sec-edgar", http_spec(), http_client=client)
    assert st.status == "present"
    assert st.via == "http"
    assert st.newest == date(2026, 10, 22)


def test_http_down_falls_back_to_read_only_duckdb(tmp_path):
    make_duckdb(
        tmp_path / "s/usfin.duckdb",
        """
        create table fred_observation_latest (series_id varchar, date date, value double);
        insert into fred_observation_latest values ('VIXCLS', '2026-10-13', 20.0);
    """,
    )

    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    st = one(tmp_path, "sec-edgar", http_spec(), http_client=client)
    assert st.via == "duckdb"
    assert st.newest == date(2026, 10, 13)
    assert st.status == "stale"


def test_http_down_and_no_store_is_missing(tmp_path):
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    st = one(tmp_path, "sec-edgar", http_spec(), http_client=client)
    assert st.status == "missing"


def test_http_refuses_non_localhost_url(tmp_path):
    spec = http_spec() | {"url": "http://example.com"}
    st = one(tmp_path, "sec-edgar", spec, http_client=httpx.Client())
    assert st.status in {"missing", "error"}
    assert "localhost" in st.detail


# ---------------- postgres ----------------


def test_postgres_dsn_drops_the_sqlalchemy_driver():
    assert doctor.libpq_dsn("postgresql+psycopg://bps:bps@localhost:5432/bps") == (
        "postgresql://bps:bps@localhost:5432/bps"
    )


def test_postgres_unreachable_is_reported_not_raised(tmp_path):
    st = one(
        tmp_path,
        "bps-looker",
        {
            "access": "postgres",
            "dsn": "postgresql://u:p@127.0.0.1:1/none",
            "env": "X",
            "probes": [{"name": "obs", "sql": "select current_date", "max_age_days": 45}],
        },
    )
    assert st.status in {"missing", "error"}
    assert "p@" not in st.location  # the password is never printed


# ---------------- doctor + CLI ----------------


def test_cli_doctor_never_fails_on_missing_sources(tmp_path, capsys, monkeypatch):
    # Keep the two sources outside ../ off the real stores too.
    monkeypatch.setenv("ASSIST_FINANCER_DB", str(tmp_path / "financer.db"))
    monkeypatch.setenv("ASSIST_BPS_LOOKER_DSN", "postgresql://u:p@127.0.0.1:1/none")
    rc = main(
        [
            "doctor",
            "--root",
            str(tmp_path),
            "--today",
            "2026-10-23",
            "--config",
            str(REPO / "config" / "sources.yaml"),
            "--no-http",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    for name in EXPECTED_SOURCES:
        assert name in out
    assert "missing" in out


def test_cli_doctor_json(tmp_path, capsys):
    make_duckdb(tmp_path / "idxscape/data/idxscape.duckdb", IDXSCAPE_SQL)
    cfg = write_config(tmp_path, {"idxscape": duck_spec()})
    rc = main(
        ["doctor", "--root", str(tmp_path), "--today", "2026-10-23", "--config", str(cfg), "--json"]
    )
    assert rc == 0
    (row,) = json.loads(capsys.readouterr().out)
    assert row["name"] == "idxscape"
    assert row["status"] == "present"
    assert row["newest"] == "2026-10-21"
    assert row["probes"][0]["age_days"] == 2


def test_report_lists_every_source_and_probe(tmp_path):
    make_duckdb(tmp_path / "idxscape/data/idxscape.duckdb", IDXSCAPE_SQL)
    cfg = write_config(tmp_path, {"idxscape": duck_spec(), "kseistat": duck_spec()})
    sources = doctor.load_sources(cfg, root=tmp_path, env={})
    sources[1].location = str(tmp_path / "nope.duckdb")
    text = doctor.format_report(doctor.run_doctor(sources, TODAY), TODAY)
    assert "idxscape" in text and "2026-10-21" in text
    assert "kseistat" in text and "missing" in text


# ---------------- socket guard ----------------


def test_socket_guard_blocks_the_internet():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="only localhost"):
            s.connect(("93.184.216.34", 80))
    finally:
        s.close()
    with pytest.raises(RuntimeError, match="only localhost"):
        socket.getaddrinfo("example.com", 80)


def test_socket_guard_allows_localhost():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()


def _watchlist_probe():
    cfg = doctor.load_sources(REPO / "config" / "sources.yaml", root=Path("/r"), env={})
    src = next(s for s in cfg if s.name == "idx-method")
    return next(p for p in src.probes if p.name == "screener_member watchlist")


def _member_db(path: Path, day: str) -> None:
    if path.exists():
        path.unlink()
    make_sqlite(path, "create table screener_member (date text, screener_id int, rank int, "
                      f"symbol text); insert into screener_member values ('{day}', 1, 1, 'A');")


def test_watchlist_probe_reports_fresh_stale_or_absent(tmp_path):
    """S89: the Stockbit watchlist (screener_member) is reported; optional, so a store without
    the table reads absent, and an old date is stale, never an error."""
    probe = _watchlist_probe()
    assert probe.optional and probe.sqlite == "store/data/stockbiter.db"
    spec = {"access": "files", "path": "idx-method", "env": "X",
            "probes": [{k: v for k, v in vars(probe).items() if v is not None}]}
    db = tmp_path / "idx-method/store/data/stockbiter.db"
    make_sqlite(db, "create table bars (date text);")
    assert one(tmp_path, "idx-method", spec).probes[0].status == "absent"
    _member_db(db, "2026-10-01")
    st = one(tmp_path, "idx-method", spec)
    assert st.probes[0].status == "stale" and st.status == "stale"
    _member_db(db, TODAY.isoformat())
    assert one(tmp_path, "idx-method", spec).probes[0].status == "fresh"
