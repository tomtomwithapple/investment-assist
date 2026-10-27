"""`assist status`: one local page with each source's data health and its repo's launchd jobs.

The doctor says how new each store is; this adds whether the jobs that fill it ran. Jobs are
found in ~/Library/LaunchAgents by the repo path in their WorkingDirectory or arguments, and their
state comes from `launchctl list` (pid, last exit). Everything is read-only. The page is /status
(twin /status.json, alias /json) in the `assist.web` shell, on 127.0.0.1 only and rebuilt on every
load; Ctrl-C stops it.
"""

from __future__ import annotations

import dataclasses
import html
import plistlib
import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

from assist import doctor, web

HOST = web.HOST
DEFAULT_PORT = web.DEFAULT_PORT
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
TEMPLATES_DIR = doctor.REPO / "launchd"
SELF = doctor.REPO.name
DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass
class Job:
    label: str
    repo: str
    schedule: str
    state: str  # running | ok | failed | down | not loaded | not installed
    exit_code: int | None = None
    pid: int | None = None
    log: str | None = None
    last_log: datetime | None = None
    tail: str = ""  # last log lines, only for a failed or down job

    def to_json(self) -> dict:
        d = asdict(self)
        d["last_log"] = self.last_log.isoformat(timespec="minutes") if self.last_log else None
        return d


# ---------------- launchd ----------------


def schedule_text(plist: dict) -> str:
    if plist.get("KeepAlive"):
        return "always on"
    if plist.get("StartInterval"):
        return f"every {int(plist['StartInterval']) // 60} min"
    cal = plist.get("StartCalendarInterval")
    if not cal:
        return "at load" if plist.get("RunAtLoad") else "on demand"
    cal = cal if isinstance(cal, list) else [cal]
    times = sorted({f"{c.get('Hour', 0):02d}:{c.get('Minute', 0):02d}" for c in cal})
    days = sorted({c["Weekday"] % 7 for c in cal if "Weekday" in c})
    mdays = sorted({c["Day"] for c in cal if "Day" in c})
    if mdays:
        contiguous = len(mdays) > 3 and mdays == list(range(mdays[0], mdays[-1] + 1))
        when = (f"monthly days {mdays[0]}–{mdays[-1]}" if contiguous
                else "monthly day " + ", ".join(map(str, mdays)))
    elif not days:
        when = "daily"
    elif days == [1, 2, 3, 4, 5]:
        when = "Mon–Fri"
    else:
        when = ", ".join(DAYS[d] for d in days)
    at = ", ".join(times) if len(times) <= 3 else f"{len(times)}× {times[0]}–{times[-1]}"
    return f"{when} {at}"


def launchctl_list(
    run: Callable[[], str] | None = None,
) -> dict[str, tuple[int | None, int | None]]:
    """label → (pid, last exit status) from `launchctl list`; {} when launchctl is unavailable."""
    if run is None:
        def run() -> str:
            return subprocess.run(["launchctl", "list"], capture_output=True, text=True,
                                  timeout=10).stdout
    try:
        text = run()
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for line in text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pid, code, label = parts
        out[label] = (int(pid) if pid.lstrip("-").isdigit() else None,
                      int(code) if code.lstrip("-").isdigit() else None)
    return out


def _repo_of(plist: dict, repos: dict[str, Path]) -> str | None:
    paths = [plist.get("WorkingDirectory"), plist.get("Program"),
             *(plist.get("ProgramArguments") or [])]
    for name, root in repos.items():
        # the repo path, ending there or at / or a quote or space (also inside `bash -c` strings)
        inside = re.compile(re.escape(str(root)) + r"(?=$|[/'\"\s])")
        if any(isinstance(p, str) and inside.search(p) for p in paths):
            return name
    return None


def _tail(path: Path, lines: int = 4, size: int = 8192) -> str:
    """The last few log lines, skipping blank ones and `=== ... ===` run markers."""
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - size))
            text = f.read().decode(errors="replace")
    except OSError:
        return ""
    kept = [ln.strip()[:200] for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("===")]
    return "\n".join(kept[-lines:])


def _job(label: str, repo: str, plist: dict, loaded: dict) -> Job:
    log = plist.get("StandardOutPath") or plist.get("StandardErrorPath")
    job = Job(label, repo, schedule_text(plist), "not loaded", log=log)
    if log and Path(log).is_file():
        job.last_log = datetime.fromtimestamp(Path(log).stat().st_mtime)
    if label in loaded:
        job.pid, job.exit_code = loaded[label]
        if job.pid is not None:
            job.state = "running"
        elif plist.get("KeepAlive"):
            job.state = "down"
        else:
            job.state = "ok" if not job.exit_code else "failed"
    if job.state in ("failed", "down") and log:
        job.tail = _tail(Path(log))
    return job


def find_jobs(repos: dict[str, Path], agents_dir: Path = AGENTS_DIR,
              templates_dir: Path = TEMPLATES_DIR, loaded: dict | None = None) -> list[Job]:
    """Every installed job whose paths fall inside one of `repos`, plus this repo's own job
    templates that are not installed yet."""
    loaded = launchctl_list() if loaded is None else loaded
    jobs = []
    for f in sorted(agents_dir.glob("*.plist")):
        try:
            plist = plistlib.loads(f.read_bytes())
        except Exception:  # noqa: BLE001 - one unreadable plist is skipped, never fatal
            continue
        repo = _repo_of(plist, repos)
        if repo:
            jobs.append(_job(plist.get("Label", f.stem), repo, plist, loaded))
    installed = {j.label for j in jobs}
    for f in sorted(templates_dir.glob("*.plist")):
        plist = plistlib.loads(f.read_bytes())
        label = plist.get("Label", f.stem)
        if label not in installed:
            jobs.append(Job(label, SELF, schedule_text(plist), "not installed"))
    return jobs


# ---------------- page ----------------


def repo_dirs(sources: list[doctor.Source], root: Path) -> dict[str, Path]:
    dirs = {s.repo: root / s.repo for s in sources if s.repo}
    dirs[SELF] = doctor.REPO
    return dirs


@dataclass
class Snapshot:
    built: datetime
    sources: list[doctor.SourceStatus]
    jobs: list[Job]
    repo_of: dict[str, str]  # source name → repo

    def to_json(self) -> dict:
        return {"built": self.built.isoformat(timespec="seconds"),
                "sources": [s.to_json() for s in self.sources],
                "jobs": [j.to_json() for j in self.jobs]}


GOOD = {"present", "fresh", "ok", "running"}
BAD = {"missing", "locked", "error", "failed", "down"}


def _chip(state: str) -> str:
    tone = "good" if state in GOOD else "bad" if state in BAD else "warn"
    return web.chip(state, tone)


def _jobs_table(jobs: list[Job]) -> str:
    if not jobs:
        return '<p class="muted">No launchd job found for this repo.</p>'
    rows = []
    for j in jobs:
        last = j.last_log.strftime("%Y-%m-%d %H:%M") if j.last_log else "-"
        state = j.state + (f" (exit {j.exit_code})" if j.state == "failed" else "")
        tail = f'<div class="tail">{html.escape(j.tail)}</div>' if j.tail else ""
        rows.append(f"<tr><td><code>{html.escape(j.label)}</code>{tail}</td>"
                    f"<td>{html.escape(j.schedule)}</td><td>{_chip(state)}</td>"
                    f"<td>{last}</td></tr>")
    return ("<table><thead><tr><th>Job</th><th>Schedule</th><th>State</th>"
            "<th>Log written</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _probes_table(s: doctor.SourceStatus) -> str:
    if not s.probes:
        return ""
    rows = []
    for p in s.probes:
        newest = p.newest.isoformat() if p.newest else "-"
        age = f"{p.age_days}d / {p.max_age_days}d" if p.age_days is not None else ""
        detail = f'<div class="tail">{html.escape(p.detail)}</div>' if p.detail else ""
        rows.append(f"<tr><td>{html.escape(p.name)}{detail}</td><td>{_chip(p.status)}</td>"
                    f"<td>{newest}</td><td>{age}</td></tr>")
    return ("<table><thead><tr><th>Probe</th><th>Status</th><th>Newest</th>"
            "<th>Age / max</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def body(snap: Snapshot) -> str:
    by_repo: dict[str, list[Job]] = {}
    for j in snap.jobs:
        by_repo.setdefault(j.repo, []).append(j)
    cards = []
    for s in snap.sources:
        repo = snap.repo_of.get(s.name, s.name)
        newest = s.newest.isoformat() if s.newest else "-"
        via = f" · via {html.escape(s.via)}" if s.via else ""
        detail = f'<p class="tail">{html.escape(s.detail)}</p>' if s.detail else ""
        cards.append(
            f'<section class="card"><header><h2>{html.escape(s.name)}</h2>{_chip(s.status)}'
            f'<span class="muted">newest {newest}{via}</span></header>{detail}'
            f"{_probes_table(s)}{_jobs_table(by_repo.get(repo, []))}</section>")
    cards.append(f'<section class="card"><header><h2>{SELF}</h2>'
                 f'<span class="muted">this repo\'s jobs</span></header>'
                 f"{_jobs_table(by_repo.get(SELF, []))}</section>")
    counts = {k: sum(s.status == k for s in snap.sources) for k in doctor.STATUSES}
    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
    failing = sum(j.state in BAD for j in snap.jobs)
    jobs_line = f"{len(snap.jobs)} jobs, {failing} failed or down"
    return (f'<h1>investment-assist status</h1>\n<p class="muted">Built '
            f'{snap.built.strftime("%Y-%m-%d %H:%M:%S")} (reload to refresh) · sources: '
            f'{summary} · {jobs_line} ·\nread-only · <a href="/status.json">json</a></p>\n'
            + "\n".join(cards))


def render(snap: Snapshot) -> str:
    return web.layout(TITLE, body(snap), "/status")


TITLE = "Assist Status"


# ---------------- server ----------------


def page(app: web.App, m: re.Match[str]) -> web.View:
    snap = app.health()
    return web.View(TITLE, body(snap), snap.to_json())


ROUTES: list[web.Route] = [(re.compile(r"^/status$"), page), *web.ROUTES]


def serve(build: Callable[[], Snapshot], port: int = DEFAULT_PORT,
          ready: Callable[[ThreadingHTTPServer], None] | None = None, *,
          app: web.App | None = None) -> None:
    """Serve the UI with this page as /status on 127.0.0.1 until interrupted (`build` is the
    app's health). `ready` gets the server (tests)."""
    app = web.App(health=build) if app is None else dataclasses.replace(app, health=build)
    web.serve(app, port, ready, routes=ROUTES)
