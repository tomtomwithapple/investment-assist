"""One-step start (PLAN S29): `./start.sh` checks uv, syncs, runs the doctor, runs the pipeline
when out/ is stale, serves the pages, waits until they answer and opens the browser.

Like the launchd tests in test_ops.py, every test copies start.sh into a temp "repo" and puts
stub `uv`, `open`, `curl` and `launchctl` on PATH that log their argv: nothing runs the real
pipeline, touches ~/Library, opens a browser or listens on a port.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "start.sh"
TODAY = "2026-10-27"
STATUS = "status --port 8791 --host 0.0.0.0"
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

STUB_UV = """#!/bin/sh
echo "uv $*" >> "$STUB_RECORD"
case "$*" in
    "run assist status"*) echo "stub server on $*"
        [ -n "${STUB_SERVE_SECONDS:-}" ] && exec sleep "$STUB_SERVE_SECONDS" ;;
    "run assist run"*) exit "${STUB_RUN_EXIT:-0}" ;;
    "run assist doctor"*) exit "${STUB_DOCTOR_EXIT:-0}" ;;
    "run assist industries"*) exit "${STUB_INDUSTRIES_EXIT:-0}" ;;
esac
exit 0
"""
STUB_CURL = """#!/bin/sh
echo "curl $*" >> "$STUB_RECORD"
exit "${STUB_CURL_EXIT:-0}"
"""
STUB_LOG = """#!/bin/sh
echo "{name} $*" >> "$STUB_RECORD"
exit 0
"""
STUB_INSTALL = """#!/bin/sh
echo "install.sh $*" >> "$STUB_RECORD"
exit 0
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "launchd").mkdir(parents=True)
    shutil.copy(START, r / "start.sh")
    (r / "launchd" / "install.sh").write_text(STUB_INSTALL)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {"uv": STUB_UV, "curl": STUB_CURL,
             "open": STUB_LOG.format(name="open"), "launchctl": STUB_LOG.format(name="launchctl")}
    for name, body in stubs.items():
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    return r


def _out(repo: Path, as_of: str | None, *, name: str = "IDN/bonds.json") -> None:
    p = repo / "out" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"subject": "IDN", "asset": "bonds", "stance": "neutral"}
    if as_of:
        body["as_of"] = as_of
    p.write_text(json.dumps(body, indent=2))


def _env(repo: Path, *, path: str | None = None, **extra) -> dict:
    tmp = repo.parent
    env = {"HOME": str(tmp / "home"), "PATH": path or f"{tmp / 'bin'}:{BASE_PATH}",
           "STUB_RECORD": str(tmp / "record.txt"), "ASSIST_START_TODAY": TODAY,
           "ASSIST_START_TIMEOUT": "2", "TMPDIR": str(tmp)}
    env.update(extra)
    return env


def _start(repo: Path, *args, env: dict | None = None) -> subprocess.CompletedProcess:
    # cwd is elsewhere on purpose: start.sh must cd to its own directory.
    return subprocess.run(["/bin/sh", str(repo / "start.sh"), *args], env=env or _env(repo),
                          capture_output=True, text=True, cwd=repo.parent, timeout=60,
                          check=False)


def _calls(repo: Path) -> list[str]:
    p = repo.parent / "record.txt"
    lines = p.read_text().splitlines() if p.exists() else []
    # one line per call, without the polling repeats of curl
    out: list[str] = []
    for line in lines:
        if not (out and line.startswith("curl ") and out[-1] == line):
            out.append(line)
    return out


def _names(calls: list[str]) -> list[str]:
    """Short form of each call: `uv run assist run --no-send` -> `run --no-send`."""
    short = []
    for c in calls:
        if c.startswith("uv run assist "):
            short.append(c.removeprefix("uv run assist "))
        elif c.startswith("curl "):
            short.append("curl")
        else:
            short.append(c)
    return short


def test_start_sh_is_executable_posix_sh():
    assert START.exists(), "start.sh missing"
    assert os.access(START, os.X_OK)
    assert START.read_text().startswith("#!/bin/sh")
    assert subprocess.run(["sh", "-n", str(START)], check=False).returncode == 0


def test_fresh_out_skips_the_run_and_serves_then_opens(repo):
    _out(repo, TODAY)
    _out(repo, "2026-10-20", name="USA/stocks.json")  # the newest as_of decides
    _out(repo, TODAY, name="industries/IDN.json")
    res = _start(repo)
    assert res.returncode == 0, res.stderr
    assert _names(_calls(repo)) == ["uv sync", "doctor", STATUS, "curl",
                                    "open http://127.0.0.1:8791/"]
    assert "out/ is current" in res.stdout


def test_fresh_out_without_industries_builds_them_once(repo):
    _out(repo, TODAY)
    res = _start(repo)
    assert res.returncode == 0, res.stderr
    assert _names(_calls(repo)) == ["uv sync", "doctor", "industries", STATUS, "curl",
                                    "open http://127.0.0.1:8791/"]


def test_failed_industries_still_serves(repo):
    _out(repo, TODAY)
    res = _start(repo, env=_env(repo, STUB_INDUSTRIES_EXIT="3", STUB_DOCTOR_EXIT="4"))
    assert res.returncode == 0, res.stderr
    assert STATUS in _names(_calls(repo))
    assert "assist industries failed (exit 3)" in res.stderr
    assert "doctor exited 4" in res.stdout


def test_a_run_or_no_run_skips_industries(repo):
    _out(repo, "2026-10-01")
    for args in ([], ["--no-run"]):
        res = _start(repo, *args)
        assert res.returncode == 0, res.stderr
        assert "industries" not in _names(_calls(repo))


@pytest.mark.parametrize("as_of", ["2026-10-26", None])
def test_stale_out_runs_no_send(repo, as_of):
    _out(repo, as_of)
    res = _start(repo)
    assert res.returncode == 0, res.stderr
    assert _names(_calls(repo)) == ["uv sync", "doctor", "run --no-send", STATUS,
                                    "curl", "open http://127.0.0.1:8791/"]


def test_empty_out_runs_no_send(repo):
    res = _start(repo)  # no out/ at all
    assert res.returncode == 0, res.stderr
    assert "run --no-send" in _names(_calls(repo))
    (repo / "out").mkdir()
    (repo.parent / "record.txt").unlink()
    res = _start(repo)  # out/ exists but holds no stance
    assert res.returncode == 0, res.stderr
    assert "run --no-send" in _names(_calls(repo))


def test_send_runs_with_telegram(repo):
    res = _start(repo, "--send")
    assert res.returncode == 0, res.stderr
    names = _names(_calls(repo))
    assert "run" in names and "run --no-send" not in names


def test_run_forces_a_run_on_fresh_out(repo):
    _out(repo, TODAY)
    res = _start(repo, "--run")
    assert res.returncode == 0, res.stderr
    assert _names(_calls(repo))[:3] == ["uv sync", "doctor", "run --no-send"]


def test_no_run_skips_a_stale_out(repo):
    _out(repo, "2026-10-01")
    res = _start(repo, "--no-run")
    assert res.returncode == 0, res.stderr
    assert not any(n.startswith("run") for n in _names(_calls(repo)))


def test_run_and_no_run_together_is_a_usage_error(repo):
    assert _start(repo, "--run", "--no-run").returncode == 2
    assert _calls(repo) == []


def test_no_open_skips_the_browser_and_port_passes_through(repo):
    _out(repo, TODAY)
    _out(repo, TODAY, name="industries/IDN.json")
    res = _start(repo, "--no-open", "--port", "8799")
    assert res.returncode == 0, res.stderr
    calls = _calls(repo)
    assert _names(calls) == ["uv sync", "doctor", "status --port 8799 --host 0.0.0.0", "curl"]
    assert "http://127.0.0.1:8799/" in calls[-1]
    assert "http://127.0.0.1:8799/" in res.stdout


def test_host_passes_through_and_prints_the_lan_url(repo):
    _out(repo, TODAY)
    _out(repo, TODAY, name="industries/IDN.json")
    res = _start(repo, "--no-open", "--host", "192.168.1.5")
    assert res.returncode == 0, res.stderr
    calls = _calls(repo)
    assert _names(calls) == ["uv sync", "doctor", "status --port 8791 --host 192.168.1.5", "curl"]
    assert "http://127.0.0.1:8791/" in calls[-1]
    assert "also on http://192.168.1.5:8791/" in res.stdout


def test_local_listens_on_localhost_only(repo):
    _out(repo, TODAY)
    _out(repo, TODAY, name="industries/IDN.json")
    res = _start(repo, "--no-open", "--local")
    assert res.returncode == 0, res.stderr
    assert _names(_calls(repo))[2] == "status --port 8791 --host 127.0.0.1"
    assert "also on" not in res.stdout


def test_default_prints_the_lan_url(repo):
    _out(repo, TODAY)
    stub = repo.parent / "bin" / "ipconfig"
    stub.write_text("#!/bin/sh\n[ \"$2\" = en0 ] && echo 10.0.0.7\n")
    stub.chmod(0o755)
    res = _start(repo, "--no-open")
    assert res.returncode == 0, res.stderr
    assert "also on http://10.0.0.7:8791/" in res.stdout


def test_install_jobs_runs_install_sh_after_the_sync(repo):
    _out(repo, TODAY)
    res = _start(repo, "--install-jobs", "--no-open")
    assert res.returncode == 0, res.stderr
    assert _names(_calls(repo))[:3] == ["uv sync", "install.sh ", "doctor"]


def test_without_install_jobs_nothing_touches_launchd(repo):
    _out(repo, "2026-10-01")
    res = _start(repo, "--send", "--run")
    assert res.returncode == 0, res.stderr
    assert not any(c.startswith(("install.sh", "launchctl")) for c in _calls(repo))
    assert not (repo.parent / "home").exists()


def test_uv_missing_exits_1_with_a_message(repo):
    bare = repo.parent / "bare"
    bare.mkdir()
    for name in ("curl", "open"):
        shutil.copy(repo.parent / "bin" / name, bare / name)
    res = _start(repo, env=_env(repo, path=f"{bare}:{BASE_PATH}"))
    assert res.returncode == 1
    assert "uv not found" in res.stderr and "docs.astral.sh/uv" in res.stderr
    assert _calls(repo) == []


@pytest.mark.parametrize("args", [["--bogus"], ["--port"], ["--port", "x"], ["--host"]])
def test_bad_flag_exits_2_with_usage(repo, args):
    res = _start(repo, *args)
    assert res.returncode == 2
    assert "usage:" in res.stderr
    assert _calls(repo) == []


def test_help_exits_0(repo):
    res = _start(repo, "--help")
    assert res.returncode == 0 and "usage:" in res.stderr
    assert _calls(repo) == []


def test_server_never_answering_exits_1_and_stops_it(repo):
    _out(repo, TODAY)
    env = _env(repo, STUB_CURL_EXIT="7", STUB_SERVE_SECONDS="31")
    t0 = time.monotonic()
    res = _start(repo, env=env)
    assert res.returncode == 1
    assert time.monotonic() - t0 < 20
    assert "did not answer" in res.stderr
    assert "stub server on run assist status" in res.stderr  # the server log tail is shown
    assert not any(c.startswith("open") for c in _calls(repo))
    found = subprocess.run(["pgrep", "-f", "sleep 31"], capture_output=True, text=True,
                           check=False)
    assert found.stdout.strip() == "", f"server still running: {found.stdout}"


def test_server_exiting_early_exits_1_without_waiting(repo):
    _out(repo, TODAY)
    env = _env(repo, STUB_CURL_EXIT="7", ASSIST_START_TIMEOUT="30")
    t0 = time.monotonic()
    res = _start(repo, env=env)
    assert res.returncode == 1
    assert time.monotonic() - t0 < 10
    assert "exited" in res.stderr


def test_failed_doctor_and_run_still_serve(repo):
    env = _env(repo, STUB_DOCTOR_EXIT="1", STUB_RUN_EXIT="3")
    res = _start(repo, "--no-open", env=env)
    assert res.returncode == 0, res.stderr
    assert _names(_calls(repo)) == ["uv sync", "doctor", "run --no-send", STATUS,
                                    "curl"]
    assert "run failed (exit 3)" in res.stdout + res.stderr


def test_sigterm_stops_the_server(repo):
    _out(repo, TODAY)
    env = _env(repo, STUB_SERVE_SECONDS="45")
    proc = subprocess.Popen(["/bin/sh", str(repo / "start.sh"), "--no-open"], env=env,
                            cwd=repo.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if any(c.startswith("curl") for c in _calls(repo)):
            break
        time.sleep(0.1)
    time.sleep(0.5)
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=15)
    assert proc.returncode != 0
    assert "stopped" in out + err
    found = subprocess.run(["pgrep", "-f", "sleep 45"], capture_output=True, text=True,
                           check=False)
    assert found.stdout.strip() == "", f"server still running: {found.stdout}"
