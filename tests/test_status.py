"""`assist status`: launchd jobs per repo and the local page. Plists live in a temp dir and
`launchctl list` is a canned string: nothing touches ~/Library or loads a job."""

from __future__ import annotations

import plistlib
import threading
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from assist import doctor, status

LIST = """PID\tStatus\tLabel
-\t0\tcom.x.fetch
-\t1\tcom.x.broken
4242\t0\tcom.x.serve
-\t0\tcom.other.job
-\t-9\tcom.x.killed
"""


def _plist(dir: Path, label: str, **keys) -> None:
    (dir / f"{label}.plist").write_bytes(plistlib.dumps({"Label": label, **keys}))


@pytest.fixture
def setup(tmp_path):
    root, agents, templates = tmp_path / "Projects", tmp_path / "agents", tmp_path / "templates"
    for d in (root / "fetcher", root / "fetcher-two", agents, templates):
        d.mkdir(parents=True)
    log = root / "fetcher" / "broken.log"
    log.write_text("one\ntwo\nTraceback ...\n  File x\nValueError: bad row 7\n"
                   "=== done, rc=1 ===\n\n")
    _plist(agents, "com.x.fetch", WorkingDirectory=str(root / "fetcher"),
           StartCalendarInterval={"Hour": 5, "Minute": 15})
    _plist(agents, "com.x.broken", ProgramArguments=["/bin/sh", str(root / "fetcher/run.sh")],
           StandardOutPath=str(log),
           StartCalendarInterval=[{"Weekday": d, "Hour": 9, "Minute": 0} for d in range(1, 6)])
    _plist(agents, "com.x.serve", WorkingDirectory=str(root / "fetcher"), KeepAlive=True)
    _plist(agents, "com.x.killed", WorkingDirectory=str(root / "fetcher"), StartInterval=900)
    _plist(agents, "com.x.unloaded", WorkingDirectory=str(root / "fetcher"))
    # jquantster's shape: no WorkingDirectory, the path is inside a `bash -c` string
    _plist(agents, "com.x.inline", ProgramArguments=[
        "/bin/bash", "-c", f"cd '{root / 'fetcher'}' && ./run.sh --sync-only"])
    # a sibling whose name only shares a prefix is not this repo's
    _plist(agents, "com.other.job", WorkingDirectory=str(root / "fetcher-two"))
    (agents / "garbage.plist").write_text("not a plist")
    _plist(templates, "com.self.weekly",
           StartCalendarInterval={"Weekday": 1, "Hour": 7, "Minute": 0})
    return root, agents, templates


def _jobs(setup, listing=LIST):
    root, agents, templates = setup
    loaded = status.launchctl_list(lambda: listing)
    return {j.label: j for j in status.find_jobs({"fetcher": root / "fetcher"}, agents,
                                                 templates, loaded)}


def test_launchctl_list_parses_pid_and_exit():
    got = status.launchctl_list(lambda: LIST)
    assert got["com.x.serve"] == (4242, 0)
    assert got["com.x.broken"] == (None, 1)
    assert got["com.x.killed"] == (None, -9)


def test_launchctl_unavailable_is_empty():
    def boom():
        raise OSError("no launchctl")
    assert status.launchctl_list(boom) == {}


@pytest.mark.parametrize("plist, text", [
    ({"KeepAlive": True}, "always on"),
    ({"StartInterval": 900}, "every 15 min"),
    ({"StartCalendarInterval": {"Hour": 5, "Minute": 15}}, "daily 05:15"),
    ({"StartCalendarInterval": {"Weekday": 1, "Hour": 7, "Minute": 0}}, "Mon 07:00"),
    ({"StartCalendarInterval": [{"Weekday": d, "Hour": 9, "Minute": 0} for d in range(1, 6)]},
     "Mon–Fri 09:00"),
    ({"StartCalendarInterval": [{"Hour": h, "Minute": 0} for h in range(5, 19)]},
     "daily 14× 05:00–18:00"),
    ({"StartCalendarInterval": {"Day": 1, "Hour": 6, "Minute": 0}}, "monthly day 1 06:00"),
    ({"StartCalendarInterval": {"Weekday": 0, "Hour": 6, "Minute": 0}}, "Sun 06:00"),
    ({"StartCalendarInterval": [{"Day": d, "Hour": 4, "Minute": 30} for d in range(1, 16)]},
     "monthly days 1–15 04:30"),
    ({"RunAtLoad": True}, "at load"),
    ({}, "on demand"),
])
def test_schedule_text(plist, text):
    assert status.schedule_text(plist) == text


def test_jobs_matched_to_repo_with_state(setup):
    jobs = _jobs(setup)
    assert {"com.x.fetch", "com.x.broken", "com.x.serve", "com.x.killed",
            "com.x.unloaded", "com.x.inline", "com.self.weekly"} == set(jobs)
    assert "com.other.job" not in jobs
    assert jobs["com.x.fetch"].state == "ok"
    assert jobs["com.x.fetch"].schedule == "daily 05:15"
    assert jobs["com.x.serve"].state == "running" and jobs["com.x.serve"].pid == 4242
    assert jobs["com.x.killed"].state == "failed" and jobs["com.x.killed"].exit_code == -9
    assert jobs["com.x.unloaded"].state == "not loaded"
    broken = jobs["com.x.broken"]
    assert broken.state == "failed" and broken.exit_code == 1
    assert broken.tail == "two\nTraceback ...\nFile x\nValueError: bad row 7"
    assert broken.last_log is not None
    assert jobs["com.x.fetch"].tail == ""  # only failed or down jobs show a log line
    weekly = jobs["com.self.weekly"]
    assert weekly.state == "not installed" and weekly.repo == status.SELF


def test_keepalive_service_not_running_is_down(setup):
    jobs = _jobs(setup, LIST.replace("4242\t0\tcom.x.serve", "-\t0\tcom.x.serve"))
    assert jobs["com.x.serve"].state == "down"


def test_installed_template_is_not_listed_twice(setup):
    root, agents, templates = setup
    _plist(agents, "com.self.weekly", WorkingDirectory=str(status.doctor.REPO),
           StartCalendarInterval={"Weekday": 1, "Hour": 7, "Minute": 0})
    jobs = status.find_jobs({status.SELF: status.doctor.REPO}, agents, templates, {})
    assert [j.state for j in jobs if j.label == "com.self.weekly"] == ["not loaded"]


def _snapshot(setup) -> status.Snapshot:
    src = doctor.SourceStatus(
        "fetcher", "duckdb", "/x/fetcher.duckdb", "stale", via="duckdb",
        newest=date(2026, 10, 20),
        probes=[doctor.ProbeResult("prices", "stale", date(2026, 10, 20), 7, 5)])
    missing = doctor.SourceStatus("gone", "sqlite", "/x/gone.db", "missing",
                                  detail="no file at <gone>")
    return status.Snapshot(datetime(2026, 10, 27, 9, 0), [src, missing],
                           list(_jobs(setup).values()), {"fetcher": "fetcher", "gone": "gone"})


def test_render_shows_sources_jobs_and_escapes(setup):
    page = status.render(_snapshot(setup))
    assert "<title>Assist Status</title>" in page
    assert "1 missing, 1 stale" in page
    assert "com.x.broken" in page and "failed (exit 1)" in page
    assert "ValueError: bad row 7" in page
    assert "Mon–Fri 09:00" in page
    assert "7d / 5d" in page
    assert "no file at &lt;gone&gt;" in page and "<gone>" not in page
    assert "No launchd job found for this repo." in page  # `gone` has none
    assert "com.self.weekly" in page and "not installed" in page
    assert "prefers-color-scheme: dark" in page


def test_serve_on_localhost_status_json_404(setup):
    snap = _snapshot(setup)
    started = threading.Event()
    box = {}

    def ready(server):
        box["server"] = server
        started.set()

    t = threading.Thread(target=status.serve, args=(lambda: snap,),
                         kwargs={"port": 0, "ready": ready}, daemon=True)
    t.start()
    assert started.wait(5)
    server = box["server"]
    host, port = server.server_address[:2]
    assert host == "127.0.0.1"
    try:
        base = f"http://127.0.0.1:{port}"
        page = httpx.get(base + "/status", trust_env=False)
        assert page.status_code == 200 and "com.x.broken" in page.text
        assert "<title>Assist Status</title>" in page.text
        assert 'href="/status.json"' in page.text
        assert "Heuristic, not investment advice." in page.text
        assert page.headers["cache-control"] == "no-store"
        for twin in ("/status.json", "/json"):
            data = httpx.get(base + twin, trust_env=False).json()
            assert data["built"] == "2026-10-27T09:00:00"
            assert {s["name"] for s in data["sources"]} == {"fetcher", "gone"}
            assert any(j["state"] == "failed" for j in data["jobs"])
        assert httpx.get(base + "/nope", trust_env=False).status_code == 404
    finally:
        server.shutdown()
        t.join(5)
