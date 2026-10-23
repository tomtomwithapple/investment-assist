"""Ops (PLAN S14): the daily regime-change check, the doctor and paper sections of the brief,
the `assist paper` / `assist regime --check` commands and the launchd jobs.

Every store is a fake or a fixture and Telegram is a mock transport. The launchd tests copy
`launchd/` into a temp "repo" and put stub `uv`, `launchctl` and `lockf` on PATH: nothing touches
~/Library, loads a job or runs the real pipeline.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from helpers import FIXTURES, load_stances, make_sqlite

from assist import brief, cli, doctor, journal, notify, paper, pipeline
from assist.layers.types import DISCLAIMER
from assist.sources.base import Row, SourceUnavailable
from assist.sources.financer import FinancerSource
from assist.sources.worldbankscape import WorldbankscapeSource

DAY = date(2026, 10, 23)
CREDS = notify.Credentials(chat="987654", token="123456:SECRET-token", source="env")
ROOT = Path(__file__).resolve().parents[1]
LAUNCHD = ROOT / "launchd"
WEEKLY = "com.tommy.investment-assist.weekly"
REGIME = "com.tommy.investment-assist.regime"
MAIN_CHECKOUT = "/Users/tomtomtomtom/Projects/investment-assist"


# ---------------- fakes ----------------


CALM = {"VIXCLS": 18.0, "BAMLH0A0HYM2": 3.0, "DTWEXBGS": 100.0, "DFII10": 1.5, "NFCI": -0.3}


class FakeFred:
    """Flat FRED lines (calm → neutral, dollar flat); `stress` turns the last 13 weeks into a
    VIX spike and a widening HY spread, `dollar_up` into a rising broad dollar."""

    name = "sec-edgar"

    def __init__(self, *, stress: bool = False, dollar_up: bool = False,
                 error: SourceUnavailable | None = None):
        self.stress, self.dollar_up, self.error = stress, dollar_up, error

    def _value(self, sid: str, i: int) -> float:
        v = CALM[sid]
        recent = i < 70
        if self.stress and recent and sid == "VIXCLS":
            return 40.0
        if self.stress and recent and sid == "BAMLH0A0HYM2":
            return 6.0
        if self.stress and recent and sid == "NFCI":
            return 0.5
        if self.dollar_up and sid == "DTWEXBGS":
            return 100.0 + (200 - i) * 0.08
        return v

    def rows(self, series_ids=None, start=None, end=None, as_of=None):
        if self.error:
            raise self.error
        top = as_of or end or DAY
        out = []
        for sid in CALM:
            if series_ids is not None and sid not in series_ids:
                continue
            for i in range(200):
                d = top - timedelta(days=i)
                if (start is None or d >= start) and (end is None or d <= end):
                    out.append(Row(sid, d, self._value(sid, i), d, self.name))
        return sorted(out, key=lambda r: (r.series_id, r.date))


@pytest.fixture
def paths(tmp_path: Path) -> pipeline.Paths:
    return pipeline.Paths.under(tmp_path / "repo")


@pytest.fixture
def telegram():
    log: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        log.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(log)}})

    return log, httpx.Client(transport=httpx.MockTransport(handle))


def _check(paths, fred, day=DAY, telegram=None, send=True, creds=CREDS):
    kw = {}
    if telegram is not None:
        kw = {"creds": creds, "client": telegram[1]}
    return pipeline.regime_check(day, paths=paths, source=fred, send=send, notify_kw=kw)


def _regime_records(paths) -> list[dict]:
    return [r for r in journal.Journal(paths.journal).read() if r["kind"] == "regime"]


# ---------------- regime change detection ----------------


def test_fakes_give_the_regimes_the_checks_rely_on():
    from assist.layers import regime

    assert regime.regime(DAY, source=FakeFred()).state == "neutral"
    assert regime.regime(DAY, source=FakeFred()).dollar == "flat"
    assert regime.regime(DAY, source=FakeFred(stress=True)).state == "risk_off"
    assert regime.regime(DAY, source=FakeFred(dollar_up=True)).dollar == "up"


def test_last_regime_is_the_newest_journalled_on_or_before_the_day():
    recs = [
        {"kind": "regime", "as_of": "2026-10-19", "outputs": {"state": "neutral",
                                                                "dollar": "flat"}},
        {"kind": "stance", "as_of": "2026-10-20", "outputs": {"state": "risk_on"}},
        {"kind": "regime", "as_of": "2026-10-21", "outputs": {"state": "risk_off",
                                                                "dollar": "up"}},
        {"kind": "regime", "as_of": "2026-10-30", "outputs": {"state": "risk_on",
                                                                "dollar": "down"}},
    ]
    last = pipeline.last_regime(recs, DAY)
    assert last == {"as_of": "2026-10-21", "state": "risk_off", "dollar": "up"}
    assert pipeline.last_regime(recs, date(2026, 10, 18)) is None
    assert pipeline.last_regime([], DAY) is None


def test_first_check_journals_a_baseline_and_sends_nothing(paths, telegram):
    chk = _check(paths, FakeFred(), telegram=telegram)
    assert chk.available and chk.previous is None and not chk.changed
    assert chk.notify is None and telegram[0] == []
    recs = _regime_records(paths)
    assert len(recs) == 1 and recs[0]["outputs"]["state"] == "neutral"
    assert recs[0]["inputs"]["job"] == "regime"


def test_unchanged_regime_sends_nothing_and_journals_nothing(paths, telegram):
    _check(paths, FakeFred(), day=DAY - timedelta(days=1), telegram=telegram)
    chk = _check(paths, FakeFred(), telegram=telegram)
    assert chk.previous["state"] == "neutral" and not chk.changed
    assert chk.notify is None and telegram[0] == []
    assert len(_regime_records(paths)) == 1


def test_changed_regime_sends_once_with_kind_regime_and_journals(paths, telegram):
    _check(paths, FakeFred(), day=DAY - timedelta(days=1))
    chk = _check(paths, FakeFred(stress=True), telegram=telegram)
    assert chk.changed and chk.changes() == ["Regime: neutral → risk_off"]
    assert chk.notify["sent"] and len(telegram[0]) == 1
    text = parse_qs(telegram[0][0].content.decode())["text"][0]
    assert "neutral → risk_off" in text and "Heuristic, not investment advice" in text
    assert notify.already_sent("regime", DAY, paths.notify)
    assert not notify.already_sent("brief", DAY, paths.notify)
    assert [r["outputs"]["state"] for r in _regime_records(paths)] == ["neutral", "risk_off"]

    again = _check(paths, FakeFred(stress=True), telegram=telegram)  # same day, journalled
    assert not again.changed and again.notify is None and len(telegram[0]) == 1


def test_dollar_direction_change_alone_is_a_change(paths, telegram):
    _check(paths, FakeFred(), day=DAY - timedelta(days=1))
    chk = _check(paths, FakeFred(dollar_up=True), telegram=telegram)
    assert chk.changed and chk.changes() == ["Dollar: flat → up"]
    assert chk.notify["sent"]


def test_change_after_a_weekly_run_compares_with_the_runs_regime(paths, telegram):
    j = journal.Journal(paths.journal)
    fp = j.register_model()
    j.record(kind="regime", fingerprint=fp, inputs={"day": DAY - timedelta(days=4)},
             outputs={"as_of": "2026-10-19", "state": "risk_off", "dollar": "flat"},
             as_of=DAY - timedelta(days=4))
    chk = _check(paths, FakeFred(), telegram=telegram)
    assert chk.previous["as_of"] == "2026-10-19" and chk.changes() == [
        "Regime: risk_off → neutral"]


def test_failed_send_is_not_journalled_so_the_next_check_retries(paths):
    _check(paths, FakeFred(), day=DAY - timedelta(days=1))

    def fail(request):
        return httpx.Response(502, text="<html>bad gateway</html>")

    bad = (None, httpx.Client(transport=httpx.MockTransport(fail)))
    chk = _check(paths, FakeFred(stress=True), telegram=bad)
    assert chk.changed and not chk.notify["sent"] and not chk.journalled
    assert len(_regime_records(paths)) == 1

    log: list = []
    ok = (log, httpx.Client(transport=httpx.MockTransport(
        lambda r: (log.append(r), httpx.Response(200, json={"ok": True}))[1])))
    retry = _check(paths, FakeFred(stress=True), day=DAY + timedelta(days=1), telegram=ok)
    assert retry.changed and retry.notify["sent"] and len(log) == 1


def test_no_send_is_a_dry_check_that_writes_nothing(paths):
    _check(paths, FakeFred(), day=DAY - timedelta(days=1))
    chk = _check(paths, FakeFred(stress=True), send=False)
    assert chk.changed and chk.notify is None and not chk.journalled
    assert len(_regime_records(paths)) == 1
    assert not (paths.notify / "sent").exists()


def test_unreadable_fred_is_no_change_and_writes_nothing(paths, telegram):
    _check(paths, FakeFred(stress=True), day=DAY - timedelta(days=1))
    down = FakeFred(error=SourceUnavailable("sec-edgar", "locked", "held by usfin serve"))
    chk = _check(paths, down, telegram=telegram)
    assert not chk.available and not chk.changed and chk.notify is None
    assert telegram[0] == [] and len(_regime_records(paths)) == 1


def test_regime_message_names_change_drivers_and_disclaimer(paths):
    _check(paths, FakeFred(), day=DAY - timedelta(days=1))
    chk = _check(paths, FakeFred(stress=True), send=False)
    msg = pipeline.regime_message(chk)
    assert msg.startswith(f"investment-assist regime {DAY}")
    assert "Regime: neutral → risk_off" in msg and "since 2026-10-22" in msg
    assert msg.rstrip().endswith(DISCLAIMER)


# ---------------- doctor in the brief header ----------------


def _statuses() -> list[doctor.SourceStatus]:
    P, S = doctor.ProbeResult, doctor.SourceStatus
    return [
        S("sec-edgar", "duckdb", "/x/usfin.duckdb", "stale", via="duckdb",
          newest=date(2026, 10, 12), detail="http://127.0.0.1:8660 unavailable",
          probes=[P("fred VIXCLS", "stale", date(2026, 10, 12), 11, 7),
                  P("tic", "fresh", date(2026, 7, 1), 114, 120)]),
        S("worldbankscape", "files", "/x/out", "present", newest=date(2026, 10, 23),
          probes=[P("index.json as_of", "fresh", date(2026, 10, 23), 0, 45)]),
        S("satudatascape", "sqlite", "/x/satudata.db", "missing",
          detail="no file at /x/satudata.db"),
        S("bisfetcher", "duckdb", "/x/w.duckdb", "locked", detail="held by bisfetcher refresh"),
        S("jquantster", "sqlite", "/x/j.db", "stale", newest=date(2026, 10, 21),
          probes=[P("investor_types", "empty"), P("macro usdjpy", "fresh", date(2026, 10, 21),
                                                  2, 7)]),
        S("idxscape", "duckdb", "/x/i.duckdb", "present", newest=date(2026, 10, 21),
          probes=[P("stock_summary", "fresh", date(2026, 10, 21), 2, 7),
                  P("igsyc_point PHEI", "absent", detail="Catalog Error: no igsyc_point")]),
    ]


def test_health_lines_one_line_per_problem():
    lines = brief.health_lines(_statuses())
    assert lines[0] == "Doctor: 1 of 6 sources present and fresh; 1 missing, 1 locked, 2 stale."
    body = lines[1:]
    assert body == [
        "sec-edgar: stale, newest 2026-10-12 (fred VIXCLS 11d/7d)",
        "satudatascape: missing (no file at /x/satudata.db)",
        "bisfetcher: locked (held by bisfetcher refresh)",
        "jquantster: stale, newest 2026-10-21 (investor_types empty)",
        "idxscape: present, but igsyc_point PHEI absent",
    ]


def test_health_lines_all_clear():
    ok = [doctor.SourceStatus("a", "files", "/a", "present", newest=DAY)]
    assert brief.health_lines(ok) == ["Doctor: all 1 source(s) present and fresh."]


def test_brief_header_carries_the_doctor_and_stays_deterministic():
    stances = load_stances()
    health = brief.health_lines(_statuses())
    md = brief.render(stances, None, health=health)
    head = md.split("## Global regime", 1)[0]
    assert "## Data health" in head
    assert "- satudatascape: missing (no file at /x/satudata.db)" in head
    assert head.index(DISCLAIMER) < head.index("## Data health")
    assert md == brief.render(list(reversed(stances)), None, health=health)
    assert "## Data health" not in brief.render(stances, None)  # golden path unchanged


# ---------------- paper ----------------


def _paper_report(records=()) -> paper.PaperReport:
    start = date(2026, 8, 7)
    days = [start + timedelta(days=i) for i in range(60)]
    jci = paper.JciLeg([Row("JKSE", d, 7000 + 10 * i, d, "idx-method")
                        for i, d in enumerate(days) if d <= date(2026, 9, 30)])
    bond = paper.YieldBondLeg([(d, 6.5) for d in days], label="test 10Y", name="test10y")
    return paper.paper_track(records=list(records), jci=jci, bond=bond, until=DAY)


def test_paper_lines_benchmark_only_until_the_journal_has_history():
    lines = brief.paper_lines(_paper_report())
    text = "\n".join(lines)
    assert lines[0].startswith("Benchmark 60% JCI / 40% SBN leg: 7 week(s) scored from "
                               "2026-08-07")
    assert "4 stale week(s), not scored" in lines[0]
    assert "No stance history in the journal yet: benchmark marks only." in text
    assert "Stale: JCI frozen at 2026-09-30" in text
    assert "Last scored week ends 2026-09-25" in text


def test_paper_lines_one_line_per_model_segment():
    rec = {"kind": "stance", "fingerprint": "sha256:" + "ab" * 32, "subject": "IDN",
           "asset": "stocks", "as_of": "2026-08-10", "outputs": {"stance": "overweight"}}
    lines = brief.paper_lines(_paper_report([rec]))
    seg = [x for x in lines if x.startswith("Model")]
    assert len(seg) == 1 and "`sha256:abababababab`" in seg[0]
    assert "from 2026-08-10" in seg[0] and "portfolio" in seg[0] and "active" in seg[0]


def test_brief_paper_section_sits_before_details():
    md = brief.render(load_stances(), None, paper=["Benchmark x", "Stale: y"])
    assert "## Paper track" in md
    assert md.index("## Paper track") < md.index("## Details")
    assert "- Stale: y" in md


def test_cli_paper_text_and_json(monkeypatch, capsys):
    rep = _paper_report()
    monkeypatch.setattr(paper, "paper_track", lambda **kw: rep)
    assert cli.main(["paper", "--today", DAY.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "Benchmark 60% JCI" in out and DISCLAIMER in out
    assert cli.main(["paper", "--json"]) == 0
    assert '"segments": []' in capsys.readouterr().out


# ---------------- pipeline: weekly run with doctor + paper ----------------


@pytest.fixture
def sources(tmp_path: Path) -> pipeline.Sources:
    root = FIXTURES / "worldbankscape"
    fix = FIXTURES / "financer"
    ddl = (fix / "schema.sql").read_text() + (fix / "seed.sql").read_text()
    return pipeline.Sources(
        worldbankscape=WorldbankscapeSource(root / "out", root / "schema"), fred=FakeFred(),
        financer=FinancerSource(make_sqlite(tmp_path / "financer.db", ddl)),
        doctor=lambda day: _statuses(), paper=lambda day, j: _paper_report(j.read()))


def test_run_brief_has_doctor_header_and_paper_section(paths, sources):
    res = pipeline.run(DAY, paths=paths, sources=sources, send=False)
    md = res.brief_path.read_text()
    assert md.index("## Data health") < md.index("## Global regime")
    assert "## Paper track" in md and "Model `sha256:" in md
    first = md
    pipeline.run(DAY, paths=paths, sources=sources, send=False)
    assert res.brief_path.read_text() == first  # rerun, same inputs: same bytes


def test_run_survives_a_failing_doctor_or_paper(paths, sources):
    def boom(*a):
        raise RuntimeError("store exploded")

    sources.doctor, sources.paper = boom, boom
    res = pipeline.run(DAY, paths=paths, sources=sources, send=False)
    md = res.brief_path.read_text()
    assert res.ok and "doctor failed: RuntimeError: store exploded" in md
    assert "paper tracking failed: RuntimeError: store exploded" in md


def test_cli_regime_check(paths, monkeypatch, capsys):
    monkeypatch.setattr(pipeline.Paths, "default", classmethod(lambda cls: paths))
    fake = pipeline.Sources(worldbankscape=None, fred=FakeFred(), financer=None)
    monkeypatch.setattr(pipeline.Sources, "default", classmethod(lambda cls: fake))
    assert cli.main(["regime", "--check", "--today", "2026-10-22"]) == 0
    assert "baseline journalled" in capsys.readouterr().out
    fake.fred = FakeFred(stress=True)
    assert cli.main(["regime", "--check", "--no-send", "--today", DAY.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "Regime: neutral → risk_off" in out and "not sent (--no-send)" in out
    assert len(_regime_records(paths)) == 1


# ---------------- launchd ----------------

STUB_UV = """#!/bin/sh
echo "cwd=$PWD" >> "$STUB_RECORD"
echo "uv $*" >> "$STUB_RECORD"
exit "${STUB_EXIT:-0}"
"""
STUB_LAUNCHCTL = """#!/bin/sh
echo "launchctl $*" >> "$STUB_RECORD"
exit 0
"""
STUB_LOCKF = """#!/bin/sh
echo "lockf $1 $2 $3 $4" >> "$STUB_RECORD"
shift 4
exec "$@"
"""
FILES = ["install.sh", "job.sh", f"{WEEKLY}.plist", f"{REGIME}.plist"]
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "launchd").mkdir(parents=True)
    for name in FILES:
        shutil.copy(LAUNCHD / name, r / "launchd" / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("uv", STUB_UV), ("launchctl", STUB_LAUNCHCTL), ("lockf", STUB_LOCKF)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    return r


def _env(repo: Path, **extra) -> dict:
    tmp = repo.parent
    env = {"HOME": str(tmp / "home"), "PATH": f"{tmp / 'bin'}:{BASE_PATH}",
           "STUB_RECORD": str(tmp / "record.txt"), "ASSIST_LAUNCH_AGENTS": str(tmp / "agents"),
           "ASSIST_REPO": str(repo), "ASSIST_LOCKF": str(tmp / "bin" / "lockf")}
    env.update(extra)
    return env


def _sh(repo: Path, script: str, *args, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/sh", str(repo / "launchd" / script), *args], env=env,
                          capture_output=True, text=True, cwd=repo.parent, timeout=30,
                          check=False)


def _record(repo: Path) -> str:
    p = repo.parent / "record.txt"
    return p.read_text() if p.exists() else ""


def _plist(label: str) -> dict:
    return plistlib.loads((LAUNCHD / f"{label}.plist").read_bytes())


def test_plists_lint_and_are_templates():
    for label in (WEEKLY, REGIME):
        path = LAUNCHD / f"{label}.plist"
        subprocess.run(["plutil", "-lint", str(path)], check=True, capture_output=True)
        text = path.read_text()
        assert "__REPO__" in text and "__UV__" in text and "/opt/homebrew" not in text
        pl = _plist(label)
        assert pl["Label"] == label and pl["RunAtLoad"] is False
        assert pl["WorkingDirectory"] == "__REPO__"


def test_schedules_monday_and_daily_at_seven_local():
    weekly, regime = _plist(WEEKLY), _plist(REGIME)
    assert weekly["StartCalendarInterval"] == {"Weekday": 1, "Hour": 7, "Minute": 0}
    assert regime["StartCalendarInterval"] == {"Hour": 7, "Minute": 0}
    assert weekly["ProgramArguments"][-1] == "weekly"
    assert regime["ProgramArguments"][-1] == "regime"
    assert weekly["StandardOutPath"] == "__REPO__/launchd/weekly.log"
    assert regime["StandardOutPath"] == "__REPO__/launchd/regime.log"


def test_install_defaults_to_the_main_checkout():
    text = (LAUNCHD / "install.sh").read_text()
    assert f"ASSIST_REPO:-{MAIN_CHECKOUT}" in text


def test_dry_run_renders_both_and_writes_nothing(repo):
    res = _sh(repo, "install.sh", "--dry-run", env=_env(repo))
    assert res.returncode == 0, res.stderr
    assert f"<string>{WEEKLY}</string>" in res.stdout and f"<string>{REGIME}</string>" in res.stdout
    assert "__REPO__" not in res.stdout and f"{repo}/launchd/job.sh" in res.stdout
    assert str(repo.parent / "bin" / "uv") in res.stdout
    assert not (repo.parent / "agents").exists() and "launchctl" not in _record(repo)


def test_install_and_uninstall_with_stub_launchctl(repo):
    env = _env(repo)
    res = _sh(repo, "install.sh", env=env)
    assert res.returncode == 0, res.stderr
    agents = repo.parent / "agents"
    for label in (WEEKLY, REGIME):
        pl = plistlib.loads((agents / f"{label}.plist").read_bytes())
        assert pl["WorkingDirectory"] == str(repo)
        assert "launchctl bootstrap gui/" in _record(repo)
    assert _record(repo).count("launchctl bootstrap") == 2

    res = _sh(repo, "install.sh", "--uninstall", env=env)
    assert res.returncode == 0, res.stderr
    assert not list(agents.glob("*.plist"))
    assert _record(repo).count("launchctl bootout") >= 4


def test_install_rejects_unknown_args(repo):
    assert _sh(repo, "install.sh", "--bogus", env=_env(repo)).returncode == 2


@pytest.mark.parametrize("job,args", [("weekly", "uv run assist run"),
                                      ("regime", "uv run assist regime --check")])
def test_job_runs_assist_under_the_lock_and_logs(repo, job, args):
    env = _env(repo, ASSIST_UV=str(repo.parent / "bin" / "uv"))
    res = _sh(repo, "job.sh", job, env=env)
    assert res.returncode == 0, res.stderr
    rec = _record(repo)
    assert f"cwd={repo}" in rec and args in rec and "lockf -k -t" in rec
    log = (repo / "launchd" / f"{job}.log").read_text()
    assert f"{job} start" in log and f"{job} end, exit 0" in log


def test_job_passes_the_exit_code_and_rejects_unknown_jobs(repo):
    env = _env(repo, ASSIST_UV=str(repo.parent / "bin" / "uv"), STUB_EXIT="1")
    assert _sh(repo, "job.sh", "weekly", env=env).returncode == 1
    assert _sh(repo, "job.sh", "nope", env=env).returncode == 2


def test_launchd_logs_are_gitignored():
    ignore = (LAUNCHD / ".gitignore").read_text().split()
    assert "*.log" in ignore
