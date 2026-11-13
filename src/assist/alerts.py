"""Change-only alerts (PLAN S90, phase P rule 6): what the daily 07:00 check sends besides a
regime change. Plumbing: it reads `out/` files, the doctor's statuses and idx-method's job logs,
and never reruns the model.

- **Holdings.** The newest `out/holdings/IDN.json` against a snapshot of the last record sent
  (`<notify state>/alerts/holdings_IDN.json`). One line per held name whose **acted** verdict
  (S87: action, thesis, take-profit state) or fit changed since that snapshot: name, old → new,
  the question (thesis / valuation / fit) and the cause (the record's own `acted.cause` or
  `cause`; when it has none, because it changed again between two checks, the cause is derived
  against the snapshot: another model → rule version, a new report or dividend → new filing, a
  valuation move → price crossing, else data fix). A thesis sell, a take-profit reached and a
  review price reached are said in words. Names bought or sold are one line each. Nothing
  changed → no holdings line. **No snapshot yet** (the first record) is the baseline: one line
  says it was set, never one line per held name.
- **Data health.** The newest run's `data_problems` / `held_for_data`, every source the doctor
  finds missing, locked, failing or stale beyond its cadence, and idx-method's last job runs
  (`idxmethod_jobs`: a non-zero exit, a run killed at its cap, a run that never reported). Each
  problem has a key without counts or dates; the block goes out when the set of keys changed
  since it was last sent (an all-clear line once it empties), or as a reminder after
  `REMIND_DAYS` of the same set, so a persistent problem does not repeat every day.
- **One message**, kind `holdings`, send-once per day (`notify.send`), silent when neither part
  has anything. The snapshot and the health state are saved only when the message was sent or
  already sent today: a failed send saves nothing, so the next check finds the same changes and
  retries. `send=False` is a dry check that writes nothing. `daily_check` never raises: an error
  becomes `AlertCheck.error`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from assist import notify
from assist.candidates import holdings as holdings_mod
from assist.layers.types import DISCLAIMER

__all__ = ["JOBS", "KIND", "REMIND_DAYS", "AlertCheck", "Problem", "commit", "daily_check",
           "data_problems", "doctor_problems", "holding_lines", "idxmethod_jobs",
           "live_idx_jobs", "load_snapshot", "prepare", "save_snapshot", "snapshot"]

KIND = "holdings"
MARKET = "IDN"
REMIND_DAYS = 7
STATE = "alerts"
JOBS = ("open", "close", "daily", "backfill")  # idx-method's launchd jobs (store/launchd/)
JOB_LOG = "store/data/archive/{job}.log"
JOB_MAX_AGE = timedelta(days=3)  # an older last run is not today's news
JOB_NO_RESULT_AFTER = timedelta(hours=3)  # the longest cap (backfill) is 30 minutes
TAIL_BYTES = 256 * 1024

ACTIONS = {"hold": "hold", "sell_all": "sell all", "trim_to_half": "trim to half",
           "stop_adding": "stop adding"}
CAUSES = {"first": "first record", "rule_version": "rule version", "data_fix": "data fix",
          "new_filing": "new filing", "price_cross": "price crossing",
          "holdings_change": "holdings change"}


@dataclass(frozen=True)
class Problem:
    """One health problem: `key` names it without counts or dates (what repeat suppression
    compares), `text` is the line sent."""

    key: str
    text: str


@dataclass
class AlertCheck:
    day: date
    text: str | None = None
    holdings: list[str] = field(default_factory=list)
    health: list[str] = field(default_factory=list)
    baseline: bool = False
    holdings_note: str | None = None
    notify: dict | None = None
    saved: bool = False
    error: str | None = None
    act_on: bool | None = None
    snap: dict | None = field(default=None, repr=False)  # saved on a send (commit)
    health_state: dict | None = field(default=None, repr=False)


# ---------------- holdings ----------------


def _state(root: Path) -> Path:
    return Path(root) / STATE


def snapshot(p: Mapping) -> dict:
    """What the next check compares with: per held name its acted verdict, fit and prices."""
    names = {}
    for r in p.get("holdings") or []:
        a = r.get("acted") or {}
        th, av = a.get("thesis") or {}, a.get("valuation") or {}
        f, v = r.get("fit") or {}, r.get("valuation") or {}
        names[r["symbol"]] = {
            "action": a.get("action"), "thesis": th.get("status"), "gate": th.get("gate"),
            "severity": th.get("severity"), "acts": th.get("acts"),
            "tp_state": av.get("state"), "take_profit": av.get("take_profit"),
            "fit": _fit(f), "price": v.get("price"), "review_price": v.get("review_price"),
            "fingerprint": r.get("model_fingerprint"), "inputs": dict(r.get("inputs") or {})}
    return {"market": p.get("market"), "as_of": p.get("as_of"),
            "act_on_verdicts": _act_on(p), "names": names}


def _act_on(p: Mapping) -> bool:
    return bool(((p.get("config") or {}).get("hysteresis") or {}).get("act_on_verdicts"))


def _fit(f: Mapping) -> str:
    if f.get("over_cap"):
        return "over cap"
    return "redundant" if f.get("redundant") and not f.get("allowed") else "ok"


def load_snapshot(state_dir: Path, market: str = MARKET) -> dict | None:
    try:
        return json.loads((_state(state_dir) / f"holdings_{market}.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None


def save_snapshot(state_dir: Path, snap: Mapping) -> None:
    _write(_state(state_dir) / f"holdings_{snap.get('market') or MARKET}.json", snap)


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _thesis_text(n: Mapping) -> str:
    if n.get("thesis") != "fail":
        return str(n.get("thesis"))
    s = f"fail {n.get('severity') or ''}".rstrip()
    return s + (f" ({n['gate']})" if n.get("gate") else "") + (
        ", sells" if n.get("acts") and n.get("severity") != "hard" else "")


def _tp_text(n: Mapping) -> str:
    return "take-profit fired" if n.get("tp_state") == "fired" else "below fair"


def _num(x: float) -> str:
    return f"{x:,.0f}"


def _cause(r: Mapping, old: Mapping, new: Mapping, questions: list[str]) -> str:
    """The record's own cause when it names a question that changed, else derived against the
    snapshot (the record changed again between two checks)."""
    a = r.get("acted") or {}
    if a.get("cause") and set(a.get("changed") or []) & set(questions):
        return CAUSES[a["cause"]]
    if r.get("cause") and r["cause"] != "first" and set(r.get("changed") or []) & set(questions):
        return CAUSES[r["cause"]]
    if old.get("fingerprint") != new.get("fingerprint"):
        return CAUSES["rule_version"]
    oi, ni = old.get("inputs") or {}, new.get("inputs") or {}
    if any(oi.get(k) != ni.get(k) for k in ("report_period", "last_dividend_ex")):
        return CAUSES["new_filing"]
    if questions == ["valuation"]:
        return CAUSES["price_cross"]
    return CAUSES["data_fix"]


def _line(r: Mapping, old: Mapping, new: Mapping) -> str | None:
    parts, questions = [], []
    if (old["thesis"], old["severity"], old["acts"]) != (new["thesis"], new["severity"],
                                                          new["acts"]):
        questions.append("thesis")
        parts.append(f"thesis: {_thesis_text(old)} → {_thesis_text(new)}")
    if old["tp_state"] != new["tp_state"]:
        questions.append("valuation")
        parts.append(f"valuation: {_tp_text(old)} → {_tp_text(new)}")
    if old["fit"] != new["fit"]:
        questions.append("fit")
        parts.append(f"fit: {old['fit']} → {new['fit']}")
    if not questions and old["action"] == new["action"]:
        return None
    o, n = ACTIONS.get(old["action"], old["action"]), ACTIONS.get(new["action"], new["action"])
    head = f"{r['symbol']}: {o} → {n}" if o != n else f"{r['symbol']}: {n}"
    line = f"{head} — {'; '.join(parts)}; cause: {_cause(r, old, new, questions)}."
    if new["action"] == "sell_all" and old["action"] != "sell_all":
        line += " Thesis sell."
    if new["tp_state"] == "fired" and old["tp_state"] != "fired" and new.get("take_profit"):
        line += f" Take-profit reached at {_num(new['take_profit'])}."
    return line


def holding_lines(p: Mapping, last: Mapping | None) -> list[str]:
    """The change lines of record `p` against the last sent snapshot (None: baseline)."""
    cur = snapshot(p)
    if last is None:
        return [f"Holdings: baseline set: {len(cur['names'])} held names as of {cur['as_of']}; "
                "from now on only changes are sent."]
    before = last.get("names") or {}
    out = []
    for r in p.get("holdings") or []:
        sym = r["symbol"]
        old, new = before.get(sym), cur["names"][sym]
        if old is None:
            continue
        line = _line(r, old, new)
        if line:
            out.append(line)
        rp, price = old.get("review_price"), new.get("price")
        if rp and price and price <= rp:
            out.append(f"{sym}: review price {_num(rp)} reached (price {_num(price)}): "
                       "a review, never a sell.")
    bought = sorted(set(cur["names"]) - set(before))
    gone = sorted(set(before) - set(cur["names"]))
    if bought:
        out.append("Now held: " + ", ".join(bought) + ".")
    if gone:
        out.append("No longer held: " + ", ".join(gone) + ".")
    return out


# ---------------- data and source health ----------------


def _norm(s: str) -> str:
    return re.sub(r"\d+(\.\d+)?", "#", s)


def data_problems(out_dir: Path) -> list[Problem]:
    """The newest run's held-for-data notes: the guide's `held_for_data` and the holding
    record's `data_problems`."""
    found: dict[str, Problem] = {}
    try:
        g = json.loads((Path(out_dir) / "guide.json").read_text("utf-8"))
        for x in g.get("held_for_data") or []:
            found.setdefault(x, Problem(f"data:{_norm(x)}",
                                        f"run {g.get('as_of')} held for data: {x}"))
    except (OSError, ValueError, AttributeError):
        pass
    p = holdings_mod.load(out_dir, MARKET)
    for x in (p or {}).get("data_problems") or []:
        x = f"{MARKET}: {x}"
        found.setdefault(x, Problem(f"data:{_norm(x)}", f"run {p['as_of']} held for data: {x}"))
    return list(found.values())


def doctor_problems(statuses: Sequence[Any]) -> list[Problem]:
    """Every source the doctor finds not present and fresh, in `brief.health_lines` words."""
    from assist import brief

    out = []
    for s in statuses:
        lines = brief.health_lines([s])
        if len(lines) < 2:
            continue
        bad = sorted(p.name for p in s.probes if p.status in brief._PROBLEM_PROBES)
        out.append(Problem(f"doctor:{s.name}:{s.status}:{','.join(bad)}", lines[1]))
    return out


_HEAD = re.compile(r"^=== (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}):\d{2}(?: [+-]\d{4})? .*===\s*$")
_DONE = re.compile(r"^=== done, rc=(\d+) ===\s*$")


def _reasons(body: list[str]) -> list[str]:
    out: list[str] = []
    text = "\n".join(body)
    for ln in body:
        if "killed after" in ln:
            # "/usr/bin/python3 factors_pull.py was killed after 1800s" → from the script on
            out.append(re.sub(r"^.*?(?=\S+\.py )", "", ln.strip()))
    if re.search(r"nodename nor servname|Name or service not known|getaddrinfo", text):
        out.append("network error, could not reach Stockbit (DNS)")
    elif re.search(r"URLError|could not reach|timed out", text):
        out.append("network error, could not reach Stockbit")
    if "no working Stockbit session" in text:
        out.append("no Stockbit session")
    for ln in body:
        s = ln.strip().split(" — ")[0]
        if s.endswith(" failed") and not re.search(r"\b0 failed$", s):
            out.append(s[:120])
        m = re.search(r"\b(\d+ endpoint\(s\) stored nothing): ([^;]*)", s)
        if m:
            names = [x.strip() for x in m.group(2).split(",") if x.strip()]
            out.append(f"{m.group(1)} ({', '.join(names[:3])}"
                       + (", ..." if len(names) > 3 else "") + ")")
        m = re.search(r"\bdone in [\d.]+s, ([1-9]\d* failures?)\b", s)
        if m:
            out.append(m.group(1))
    return list(dict.fromkeys(out))


def _last_run(path: Path) -> tuple[str, str, list[str], int | None] | None:
    """(date, HH:MM, body lines, rc or None) of the last run in a job log."""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    start = next((i for i in range(len(lines) - 1, -1, -1) if _HEAD.match(lines[i])), None)
    if start is None:
        return None
    m = _HEAD.match(lines[start])
    body, rc = [], None
    for ln in lines[start + 1:]:
        d = _DONE.match(ln)
        if d:
            rc = int(d.group(1))
            break
        body.append(ln)
    return m.group(1), m.group(2), body, rc


def idxmethod_jobs(root: Path | None, *, now: datetime | None = None,
                   jobs: Sequence[str] = JOBS) -> list[Problem]:
    """idx-method's last run of each launchd job, read-only from its logs: a non-zero exit, a
    run killed at its cap, or a run with no result `JOB_NO_RESULT_AFTER` after it started.
    A last run older than `JOB_MAX_AGE` or a missing log is no problem (the doctor's
    freshness probes cover a job that stopped firing)."""
    if root is None:
        return []
    now = now or datetime.now()
    out = []
    for job in jobs:
        run = _last_run(Path(root) / JOB_LOG.format(job=job))
        if run is None:
            continue
        day, hhmm, body, rc = run
        try:
            started = datetime.fromisoformat(f"{day}T{hhmm}")
        except ValueError:
            continue
        if now - started > JOB_MAX_AGE:
            continue
        head = f"idx-method {job} {day} {hhmm}"
        reasons = _reasons(body)
        if rc is None:
            if now - started < JOB_NO_RESULT_AFTER:
                continue
            out.append(Problem(f"idx-method:{job}:no-result",
                               f"{head}: no result reported (killed or still running)"))
        elif rc != 0 or any("killed after" in r for r in reasons):
            why = "; ".join(reasons) or (body[-1].strip()[:160] if body else "no detail")
            out.append(Problem(f"idx-method:{job}:{_norm(why)}",
                               f"{head}: failed (rc {rc}): {why}"))
    return out


def live_idx_jobs(day: date) -> list[Problem]:
    """`idxmethod_jobs` on the idx-method checkout `config/sources.yaml` names."""
    from assist import doctor

    src = next((s for s in doctor.load_sources() if s.name == "idx-method"), None)
    return idxmethod_jobs(Path(src.location) if src and src.location else None)


def _health(problems: Sequence[Problem], last: Mapping | None, day: date
            ) -> tuple[list[str], dict | None]:
    """(lines to send, health state to save on a send). Nothing when the set is unchanged and
    the last send is under `REMIND_DAYS` old."""
    keys = sorted({p.key for p in problems})
    last = last or {}
    before = last.get("keys") or []
    if keys == before:
        if not keys or not last.get("last_sent"):
            return [], None
        if day - date.fromisoformat(last["last_sent"]) < timedelta(days=REMIND_DAYS):
            return [], None
        head = f"Data health (reminder, unchanged since {last.get('first_sent')}):"
        state = dict(last) | {"last_sent": day.isoformat()}
    elif not keys:
        return (["Data health: all clear again (the problems sent on "
                 f"{last.get('first_sent')} are gone)."],
                {"keys": [], "first_sent": day.isoformat(), "last_sent": day.isoformat()})
    else:
        head = "Data health:"
        state = {"keys": keys, "first_sent": day.isoformat(), "last_sent": day.isoformat()}
    seen: set[str] = set()
    lines = [head]
    for p in problems:
        if p.text not in seen:
            seen.add(p.text)
            lines.append(f"- {p.text}")
    return lines, state


def _load_health(state_dir: Path) -> dict | None:
    try:
        return json.loads((_state(state_dir) / "health.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None


# ---------------- the daily check ----------------


def message(day: date, holdings: Sequence[str], health: Sequence[str],
            act_on: bool | None) -> str:
    lines = [f"investment-assist alerts {day.isoformat()}"]
    if holdings:
        if act_on is False:
            lines.append("Paper: acted verdicts move no order yet (ACT_ON_VERDICTS off).")
        lines += ["", *holdings]
    if health:
        lines += ["", *health]
    return "\n".join([*lines, "", DISCLAIMER])


def prepare(day: date, *, out_dir: Path, state_dir: Path, statuses: Sequence[Any] = (),
            jobs: Sequence[Problem] = ()) -> AlertCheck:
    """Read only: the holding change lines and the health lines, and the state to save if they
    are sent (`commit`). Never raises: an error becomes `AlertCheck.error`."""
    chk = AlertCheck(day=day)
    try:
        p = holdings_mod.load(out_dir, MARKET)
        if p is None:
            chk.holdings_note = f"no out/holdings/{MARKET}.json yet"
        else:
            last = load_snapshot(state_dir)
            chk.baseline = last is None
            chk.holdings = holding_lines(p, last)
            chk.snap = snapshot(p)
            chk.act_on = chk.snap["act_on_verdicts"]
        problems = [*data_problems(out_dir), *doctor_problems(statuses), *jobs]
        chk.health, chk.health_state = _health(problems, _load_health(state_dir), day)
    except Exception as e:  # noqa: BLE001 - the daily check never fails on its alerts
        chk.error = f"{type(e).__name__}: {e}"
    return chk


def commit(chk: AlertCheck, state_dir: Path) -> None:
    """After a send (or a send already made today): save the snapshot and the health state, so
    the next check compares against what was sent. A failed send saves nothing."""
    if not (chk.notify and (chk.notify.get("sent") or chk.notify.get("skipped"))):
        return
    try:
        if chk.snap is not None:
            save_snapshot(state_dir, chk.snap)
        if chk.health_state is not None:
            _write(_state(state_dir) / "health.json", chk.health_state)
        chk.saved = True
    except Exception as e:  # noqa: BLE001
        chk.error = f"{type(e).__name__}: {e}"


def daily_check(day: date, *, out_dir: Path, state_dir: Path, statuses: Sequence[Any] = (),
                jobs: Sequence[Problem] = (), send: bool = True,
                notify_kw: Mapping[str, Any] | None = None) -> AlertCheck:
    """Compare the newest holding record with the last sent one and the health problems with
    the last sent set; send one message (kind `holdings`, send-once per day) when either has
    something. Never raises."""
    chk = prepare(day, out_dir=out_dir, state_dir=state_dir, statuses=statuses, jobs=jobs)
    if chk.error or (not chk.holdings and not chk.health):
        return chk
    chk.text = message(day, chk.holdings, chk.health, chk.act_on)
    if not send:
        return chk
    chk.notify = notify.send(chk.text, kind=KIND, day=day, state_dir=state_dir,
                             **dict(notify_kw or {}))
    commit(chk, state_dir)
    return chk
