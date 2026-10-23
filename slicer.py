#!/usr/bin/env python3
"""slicer: schedule a project plan of serial + parallel slices across many machines.

The plan is a DAG of slices (plan.yaml / plan.json). Shared state (claims, leases,
done markers) lives either in a local JSON file (one machine, file-locked) or on a
dedicated git branch, where every update is a compare-and-swap: a non-fast-forward
push is rejected, so two machines can never claim the same slice.

Commands: validate, plan, status, graph, claim, heartbeat, done, release,
          retry, invalidate, reset, run
"""
import argparse
import contextlib
import fnmatch
import json
import os
import random
import shlex
import socket
import subprocess
import sys
import threading
import time
from collections import defaultdict

STATE_FILE_IN_BRANCH = "state.json"
DEFAULTS = {
    "state": "local:.slicer/state.json",
    "lease_minutes": 90,
    "max_attempts": 3,
}


class PlanError(Exception):
    pass


def die(msg, code=1):
    print(f"slicer: {msg}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- plan

def load_plan(path):
    if not os.path.exists(path):
        raise PlanError(f"plan not found: {path}")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError:
            raise PlanError("YAML plans need PyYAML (pip install pyyaml), or use plan.json")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    if isinstance(data, list):
        data = {"slices": data}
    settings = dict(DEFAULTS)
    settings.update(data.get("settings") or {})

    plan = {}
    for raw in data.get("slices") or []:
        if "id" not in raw:
            raise PlanError(f"slice without id: {raw}")
        sid = str(raw["id"])
        if sid in plan:
            raise PlanError(f"duplicate slice id: {sid}")
        est = float(raw.get("estimate", 1))
        if est <= 0:
            raise PlanError(f"{sid}: estimate must be > 0")
        plan[sid] = {
            "id": sid,
            "title": raw.get("title", ""),
            "kind": raw.get("kind", "build"),
            "depends_on": [str(d) for d in (raw.get("depends_on") or [])],
            "produces": list(raw.get("produces") or []),
            "owns": list(raw.get("owns") or []),
            "accept": raw.get("accept"),
            "estimate": est,
            "notes": raw.get("notes", ""),
        }
    if not plan:
        raise PlanError("plan has no slices")
    return plan, settings


class Graph:
    def __init__(self, plan):
        self.plan = plan
        self.children = defaultdict(list)
        for s in plan.values():
            for d in s["depends_on"]:
                if d not in plan:
                    raise PlanError(f"{s['id']} depends on unknown slice {d}")
                if d == s["id"]:
                    raise PlanError(f"{d} depends on itself")
                self.children[d].append(s["id"])
        for k in self.children:
            self.children[k].sort()
        self.order = self._toposort()
        est = {k: v["estimate"] for k, v in plan.items()}

        self.level = {}
        self.earliest = {}
        for sid in self.order:
            deps = plan[sid]["depends_on"]
            self.level[sid] = 0 if not deps else 1 + max(self.level[d] for d in deps)
            self.earliest[sid] = max((self.earliest[d] + est[d] for d in deps), default=0.0)

        # bottom level = longest path from this slice to the end, including itself.
        self.bottom = {}
        for sid in reversed(self.order):
            self.bottom[sid] = est[sid] + max((self.bottom[c] for c in self.children[sid]), default=0.0)

        self.total_work = sum(est.values())
        self.critical_length = max(self.bottom.values())

    def _toposort(self):
        indeg = {k: len(v["depends_on"]) for k, v in self.plan.items()}
        ready = sorted(k for k, d in indeg.items() if d == 0)
        out = []
        while ready:
            n = ready.pop(0)
            out.append(n)
            for c in self.children[n]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    ready.append(c)
                    ready.sort()
        if len(out) != len(self.plan):
            stuck = sorted(k for k in self.plan if k not in out)
            raise PlanError(f"dependency cycle among: {', '.join(stuck)}")
        return out

    def descendants(self, sid):
        seen, stack = set(), [sid]
        while stack:
            for c in self.children[stack.pop()]:
                if c not in seen:
                    seen.add(c)
                    stack.append(c)
        return seen

    def critical_path(self):
        roots = [s for s in self.order if not self.plan[s]["depends_on"]]
        cur = max(roots, key=lambda s: (self.bottom[s], s))
        path = [cur]
        while self.children[cur]:
            cur = max(self.children[cur], key=lambda s: (self.bottom[s], s))
            path.append(cur)
        return path

    def waves(self):
        w = defaultdict(list)
        for sid in self.order:
            w[self.level[sid]].append(sid)
        return [w[i] for i in sorted(w)]

    def priority_key(self, sid):
        return (-self.bottom[sid], sid)


def glob_prefix(g):
    out = []
    for ch in g:
        if ch in "*?[":
            break
        out.append(ch)
    return "".join(out)


def globs_overlap(a, b):
    if a == b:
        return True
    wa, wb = glob_prefix(a) != a, glob_prefix(b) != b
    if not wa and not wb:
        return False
    if not wa:
        return fnmatch.fnmatch(a, b)
    if not wb:
        return fnmatch.fnmatch(b, a)
    pa, pb = glob_prefix(a), glob_prefix(b)
    return pa.startswith(pb) or pb.startswith(pa)


def validate(plan):
    """Returns (graph, errors, warnings)."""
    g = Graph(plan)  # raises PlanError for unknown deps / cycles
    errors, warnings = [], []
    desc = {s: g.descendants(s) for s in plan}
    ids = g.order
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if b in desc[a] or a in desc[b]:
                continue  # ordered by the DAG, never concurrent
            for ga in plan[a]["owns"]:
                for gb in plan[b]["owns"]:
                    if globs_overlap(ga, gb):
                        errors.append(
                            f"ownership clash: {a} ({ga}) and {b} ({gb}) can run concurrently")
    for s in plan.values():
        if not s["accept"]:
            warnings.append(f"{s['id']}: no accept check (done-ness is a judgment call)")
        if not s["owns"] and s["kind"] != "contract":
            warnings.append(f"{s['id']}: owns no paths")
        if s["estimate"] > 4:
            warnings.append(f"{s['id']}: estimate {s['estimate']}h, consider splitting")
    return g, errors, warnings


def simulate(g, machines):
    """List scheduling by critical-path priority. Returns (makespan, timeline)."""
    est = {k: v["estimate"] for k, v in g.plan.items()}
    remaining = {k: len(v["depends_on"]) for k, v in g.plan.items()}
    ready = [k for k, n in remaining.items() if n == 0]
    free = list(range(machines))
    running, timeline, t = [], [], 0.0
    while ready or running:
        ready.sort(key=g.priority_key)
        while free and ready:
            m, s = free.pop(0), ready.pop(0)
            running.append((t + est[s], s, m))
            timeline.append((t, t + est[s], s, m))
        running.sort()
        t = running[0][0]
        while running and running[0][0] == t:
            _, s, m = running.pop(0)
            free.append(m)
            for c in g.children[s]:
                remaining[c] -= 1
                if remaining[c] == 0:
                    ready.append(c)
        free.sort()
    return t, timeline


# -------------------------------------------------------------------------- state

def empty_state():
    return {"slices": {}}


def _lock_exclusive(f):
    """Block until this process holds an exclusive lock on f (released when f closes)."""
    if os.name == "nt":
        import msvcrt
        import time
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:  # LK_LOCK gives up after ~10s; keep waiting like flock does
                time.sleep(0.1)
    import fcntl
    fcntl.flock(f, fcntl.LOCK_EX)


class LocalState:
    def __init__(self, path):
        self.path = path

    def read(self):
        if not os.path.exists(self.path):
            return empty_state()
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def update(self, fn, message=""):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path + ".lock", "w") as lock:
            _lock_exclusive(lock)
            state = self.read()
            before = json.dumps(state, sort_keys=True)
            result = fn(state)
            after = json.dumps(state, sort_keys=True, indent=2)
            if json.dumps(json.loads(after), sort_keys=True) != before:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(after + "\n")
                os.replace(tmp, self.path)
            return result


class GitState:
    """State on a dedicated branch; each write is a CAS via non-force push."""

    def __init__(self, remote, branch, repo="."):
        self.remote, self.branch, self.repo = remote, branch, repo
        self.local_ref = f"refs/slicer/{remote}/{branch}"
        self.env = dict(os.environ)
        for k, v in (("GIT_AUTHOR_NAME", "slicer"), ("GIT_AUTHOR_EMAIL", "slicer@localhost"),
                     ("GIT_COMMITTER_NAME", "slicer"), ("GIT_COMMITTER_EMAIL", "slicer@localhost")):
            self.env.setdefault(k, v)

    def _git(self, *args, input=None, check=True):
        r = subprocess.run(["git", "-C", self.repo, *args], input=input,
                           capture_output=True, text=True, env=self.env)
        if check and r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
        return r

    def _fetch(self):
        r = self._git("fetch", "-q", self.remote,
                      f"+refs/heads/{self.branch}:{self.local_ref}", check=False)
        if r.returncode != 0:
            if "couldn't find remote ref" in r.stderr:
                return None
            raise RuntimeError(f"git fetch failed: {r.stderr.strip()}")
        return self._git("rev-parse", self.local_ref).stdout.strip()

    def _load(self, commit):
        if not commit:
            return empty_state()
        r = self._git("show", f"{commit}:{STATE_FILE_IN_BRANCH}")
        return json.loads(r.stdout)

    def read(self):
        return self._load(self._fetch())

    def update(self, fn, message="slicer update"):
        for attempt in range(25):
            parent = self._fetch()
            state = self._load(parent)
            before = json.dumps(state, sort_keys=True)
            result = fn(state)
            if json.dumps(state, sort_keys=True) == before:
                return result
            body = json.dumps(state, sort_keys=True, indent=2) + "\n"
            blob = self._git("hash-object", "-w", "--stdin", input=body).stdout.strip()
            tree = self._git("mktree", input=f"100644 blob {blob}\t{STATE_FILE_IN_BRANCH}\n").stdout.strip()
            args = ["commit-tree", tree, "-m", message]
            if parent:
                args += ["-p", parent]
            commit = self._git(*args).stdout.strip()
            push = self._git("push", "-q", self.remote, f"{commit}:refs/heads/{self.branch}", check=False)
            if push.returncode == 0:
                self._git("update-ref", self.local_ref, commit)
                return result
            time.sleep(min(2.0, 0.05 * (2 ** attempt)) * random.uniform(0.5, 1.5))
        raise RuntimeError("could not update shared state: too much contention")


def open_state(spec):
    kind, _, rest = spec.partition(":")
    if kind == "local":
        return LocalState(rest or DEFAULTS["state"].split(":", 1)[1])
    if kind == "git":
        remote, _, branch = (rest or "origin/slicer-state").partition("/")
        return GitState(remote, branch or "slicer-state")
    die(f"unknown state backend '{spec}' (use local:PATH or git:REMOTE/BRANCH)")


# ----------------------------------------------------------------- status logic

def compute_status(g, state, now, max_attempts):
    st = state.get("slices", {})
    out = {}
    for sid in g.order:
        rec = st.get(sid, {})
        if rec.get("status") == "done":
            out[sid] = "done"
        elif rec.get("status") == "claimed" and rec.get("lease_until", 0) > now:
            out[sid] = "claimed"
        elif rec.get("attempts", 0) >= max_attempts:
            out[sid] = "failed"
        elif all(out[d] == "done" for d in g.plan[sid]["depends_on"]):
            out[sid] = "ready"
        else:
            out[sid] = "blocked"
    return out


def fmt_h(x):
    return f"{x:g}h"


def default_machine():
    return os.environ.get("SLICER_MACHINE") or socket.gethostname()


# ------------------------------------------------------------------- commands

def cmd_validate(args, plan, settings):
    g, errors, warnings = validate(plan)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error:   {e}")
    print(f"{len(plan)} slices, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def cmd_plan(args, plan, settings):
    g, errors, _ = validate(plan)
    if errors:
        print("plan has errors, run `slicer validate`")
        return 1
    print("Waves (slices in one wave can run in parallel):")
    for i, wave in enumerate(g.waves()):
        items = ", ".join(f"{s}[{fmt_h(plan[s]['estimate'])}]" for s in sorted(wave, key=g.priority_key))
        print(f"  W{i}: {items}")
    cp = g.critical_path()
    print(f"\nCritical path ({fmt_h(g.critical_length)}): {' -> '.join(cp)}")
    print(f"Total work: {fmt_h(g.total_work)}")
    print(f"Max useful parallelism ≈ {g.total_work / g.critical_length:.1f} machines")
    print("\nSimulated makespan (critical-path list scheduling):")
    top = args.machines or max(1, min(12, int(g.total_work / g.critical_length + 0.999) + 1))
    for n in range(1, top + 1):
        span, _ = simulate(g, n)
        print(f"  {n:>2} machine{'s' if n > 1 else ' '}: {fmt_h(round(span, 2)):>8}"
              f"  speedup {g.total_work / span:4.2f}x  utilisation {g.total_work / (span * n):4.0%}")
    if args.machines:
        span, tl = simulate(g, args.machines)
        print(f"\nSchedule on {args.machines} machines:")
        for start, end, s, m in sorted(tl, key=lambda x: (x[3], x[0])):
            print(f"  M{m}  {start:6.2f} -> {end:6.2f}  {s}")
    return 0


def cmd_status(args, plan, settings, store):
    g = Graph(plan)
    state = store.read()
    now = time.time()
    status = compute_status(g, state, now, settings["max_attempts"])
    rows = []
    for sid in sorted(g.order, key=lambda s: (g.level[s],) + g.priority_key(s)):
        rec = state.get("slices", {}).get(sid, {})
        extra = ""
        if status[sid] == "claimed":
            extra = f"{rec.get('by')} (lease {int((rec['lease_until'] - now) / 60)}m left)"
        elif status[sid] == "done":
            extra = f"by {rec.get('by', '?')}" + (f" @ {rec['commit'][:10]}" if rec.get("commit") else "")
        elif rec.get("attempts"):
            extra = f"attempts {rec['attempts']}: {rec.get('last_error', '')[:60]}"
        rows.append((f"W{g.level[sid]}", sid, status[sid], extra))
    if args.json:
        print(json.dumps({"status": status, "state": state}, indent=2, sort_keys=True))
        return 0
    w = max(len(r[1]) for r in rows)
    for wave, sid, s, extra in rows:
        print(f"{wave:<4}{sid:<{w + 2}}{s:<9}{extra}")
    counts = defaultdict(int)
    for s in status.values():
        counts[s] += 1
    done_work = sum(plan[s]["estimate"] for s, v in status.items() if v == "done")
    print("\n" + "  ".join(f"{k}:{counts[k]}" for k in ("done", "claimed", "ready", "blocked", "failed")))
    print(f"progress: {done_work:g}/{g.total_work:g}h of work")
    return 0


def cmd_graph(args, plan, settings, store):
    g = Graph(plan)
    status = compute_status(g, store.read(), time.time(), settings["max_attempts"]) if args.status else {}
    cp = set(g.critical_path())
    lines = ["flowchart LR"]
    for sid in g.order:
        label = plan[sid]["title"] or sid
        lines.append(f'  {sid.replace("-", "_")}["{sid}<br/>{label} ({fmt_h(plan[sid]["estimate"])})"]')
    for sid in g.order:
        for d in plan[sid]["depends_on"]:
            arrow = "==>" if d in cp and sid in cp else "-->"
            lines.append(f"  {d.replace('-', '_')} {arrow} {sid.replace('-', '_')}")
    colors = {"done": "#2e7d32", "claimed": "#f9a825", "ready": "#1565c0", "failed": "#c62828"}
    for s, c in colors.items():
        lines.append(f"  classDef {s} fill:{c},color:#fff")
    for sid, s in status.items():
        if s in colors:
            lines.append(f"  class {sid.replace('-', '_')} {s}")
    print("\n".join(lines))
    return 0


def claim_next(g, settings, store, machine, lease_minutes, only=None):
    def fn(state):
        now = time.time()
        status = compute_status(g, state, now, settings["max_attempts"])
        ready = [s for s in g.order if status[s] == "ready" and (not only or s in only)]
        if not ready:
            return None
        sid = sorted(ready, key=g.priority_key)[0]
        rec = state.setdefault("slices", {}).setdefault(sid, {})
        rec.update(status="claimed", by=machine, claimed_at=now,
                   lease_until=now + lease_minutes * 60)
        return sid
    return store.update(fn, f"claim by {machine}")


def _require_claim(state, sid, machine, force=False):
    rec = state.setdefault("slices", {}).setdefault(sid, {})
    if force:
        return rec
    if rec.get("status") != "claimed" or rec.get("by") != machine:
        raise RuntimeError(f"{sid} is not claimed by {machine} (status={rec.get('status')}, by={rec.get('by')})")
    return rec


def cmd_claim(args, plan, settings, store):
    g = Graph(plan)
    sid = claim_next(g, settings, store, args.machine, args.lease or settings["lease_minutes"])
    if not sid:
        print("" if args.json else "nothing ready")
        return 3
    s = plan[sid]
    if args.json:
        print(json.dumps(s, indent=2))
    else:
        print(sid)
    return 0


def cmd_heartbeat(args, plan, settings, store):
    lease = args.lease or settings["lease_minutes"]

    def fn(state):
        rec = _require_claim(state, args.slice, args.machine)
        rec["lease_until"] = time.time() + lease * 60
    store.update(fn, f"heartbeat {args.slice}")
    return 0


def cmd_done(args, plan, settings, store):
    if args.slice not in plan:
        die(f"unknown slice {args.slice}")
    if args.check and plan[args.slice]["accept"]:
        r = subprocess.run(plan[args.slice]["accept"], shell=True)
        if r.returncode != 0:
            die(f"accept check failed for {args.slice}; not marking done")

    def fn(state):
        rec = _require_claim(state, args.slice, args.machine, args.force)
        rec.update(status="done", by=args.machine, done_at=time.time())
        rec.pop("lease_until", None)
        if args.commit:
            rec["commit"] = args.commit
    store.update(fn, f"done {args.slice}")
    return 0


def cmd_release(args, plan, settings, store):
    def fn(state):
        rec = _require_claim(state, args.slice, args.machine, args.force)
        rec.pop("lease_until", None)
        rec["status"] = "open"
        if args.error is not None:
            rec["attempts"] = rec.get("attempts", 0) + 1
            rec["last_error"] = args.error
    store.update(fn, f"release {args.slice}")
    return 0


def cmd_retry(args, plan, settings, store):
    def fn(state):
        rec = state.setdefault("slices", {}).setdefault(args.slice, {})
        rec.update(status="open", attempts=0)
        rec.pop("last_error", None)
    store.update(fn, f"retry {args.slice}")
    return 0


def cmd_invalidate(args, plan, settings, store):
    """A contract changed: reopen the slice and everything downstream of it."""
    g = Graph(plan)
    targets = {args.slice} | g.descendants(args.slice)

    def fn(state):
        for sid in targets:
            state.setdefault("slices", {}).pop(sid, None)
    store.update(fn, f"invalidate {args.slice}")
    print("reopened: " + ", ".join(s for s in g.order if s in targets))
    return 0


def cmd_reset(args, plan, settings, store):
    if not args.yes:
        die("reset wipes all progress; pass --yes")

    def fn(state):
        state.clear()
        state.update(empty_state())
    store.update(fn, "reset")
    return 0


@contextlib.contextmanager
def heartbeat_thread(store, sid, machine, lease_minutes):
    stop = threading.Event()

    def beat():
        while not stop.wait(lease_minutes * 60 / 3):
            try:
                def fn(state):
                    rec = _require_claim(state, sid, machine)
                    rec["lease_until"] = time.time() + lease_minutes * 60
                store.update(fn, f"heartbeat {sid}")
            except Exception as e:  # keep working; the lease just may expire
                print(f"slicer: heartbeat failed: {e}", file=sys.stderr)
    t = threading.Thread(target=beat, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()


def run_shell(cmd, env):
    print(f"$ {cmd}", flush=True)
    return subprocess.run(cmd, shell=True, env=env).returncode


def cmd_run(args, plan, settings, store):
    """Worker loop: claim -> exec -> accept -> on-done -> mark done. Repeat."""
    g = Graph(plan)
    lease = args.lease or settings["lease_minutes"]
    completed = 0
    while True:
        sid = claim_next(g, settings, store, args.machine, lease)
        if not sid:
            status = compute_status(g, store.read(), time.time(), settings["max_attempts"])
            if all(v == "done" for v in status.values()):
                print(f"[{args.machine}] all slices done ({completed} by this machine)")
                return 0
            if "claimed" not in status.values() and "ready" not in status.values():
                failed = [s for s, v in status.items() if v == "failed"]
                print(f"[{args.machine}] stuck: failed slices block the rest: {', '.join(failed)}")
                return 2
            if args.once:
                return 3
            time.sleep(args.poll)
            continue

        s = plan[sid]
        env = dict(os.environ,
                   SLICER_ID=sid, SLICER_TITLE=s["title"], SLICER_KIND=s["kind"],
                   SLICER_OWNS="\n".join(s["owns"]), SLICER_PRODUCES="\n".join(s["produces"]),
                   SLICER_DEPENDS_ON=" ".join(s["depends_on"]), SLICER_ACCEPT=s["accept"] or "",
                   SLICER_NOTES=s["notes"], SLICER_MACHINE=args.machine)
        print(f"[{args.machine}] claimed {sid} (priority {fmt_h(g.bottom[sid])} to finish)", flush=True)
        error = None
        with heartbeat_thread(store, sid, args.machine, lease):
            steps = []
            if args.exec:
                steps.append(("exec", args.exec.replace("{id}", shlex.quote(sid))))
            if s["accept"]:
                steps.append(("accept", s["accept"]))
            if args.on_done:
                steps.append(("on-done", args.on_done.replace("{id}", shlex.quote(sid))))
            for name, cmd in steps:
                rc = run_shell(cmd, env)
                if rc != 0:
                    error = f"{name} exited {rc}"
                    break
        commit = None
        if not error:
            r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
            commit = r.stdout.strip() if r.returncode == 0 else None

        def fn(state):
            rec = _require_claim(state, sid, args.machine)
            rec.pop("lease_until", None)
            if error:
                rec["status"] = "open"
                rec["attempts"] = rec.get("attempts", 0) + 1
                rec["last_error"] = error
            else:
                rec.update(status="done", done_at=time.time())
                if commit:
                    rec["commit"] = commit
        try:
            store.update(fn, f"{'fail' if error else 'done'} {sid}")
        except RuntimeError as e:
            print(f"[{args.machine}] lost claim on {sid}: {e}", file=sys.stderr)
        print(f"[{args.machine}] {sid}: {'FAILED, ' + error if error else 'done'}", flush=True)
        if not error:
            completed += 1
        if args.once:
            return 0 if not error else 1


# ----------------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(prog="slicer", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan", default=os.environ.get("SLICER_PLAN", "plan.yaml"))
    p.add_argument("--state", default=os.environ.get("SLICER_STATE"),
                   help="local:PATH or git:REMOTE/BRANCH (default: plan settings.state)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_machine(sp):
        sp.add_argument("--machine", default=default_machine())

    sub.add_parser("validate", help="check ids, deps, cycles, ownership clashes")
    sp = sub.add_parser("plan", help="waves, critical path, simulated makespan")
    sp.add_argument("--machines", type=int)
    sp = sub.add_parser("status", help="live progress from shared state")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("graph", help="print Mermaid flowchart")
    sp.add_argument("--status", action="store_true", help="colour by live status")
    sp = sub.add_parser("claim", help="atomically claim the highest-priority ready slice")
    with_machine(sp)
    sp.add_argument("--lease", type=float, help="lease minutes")
    sp.add_argument("--json", action="store_true")
    for name in ("heartbeat", "done", "release"):
        sp = sub.add_parser(name)
        sp.add_argument("slice")
        with_machine(sp)
        if name == "heartbeat":
            sp.add_argument("--lease", type=float)
        if name == "done":
            sp.add_argument("--commit")
            sp.add_argument("--check", action="store_true", help="run accept first")
            sp.add_argument("--force", action="store_true")
        if name == "release":
            sp.add_argument("--error", help="record a failed attempt")
            sp.add_argument("--force", action="store_true")
    sp = sub.add_parser("retry", help="clear attempts on a failed slice")
    sp.add_argument("slice")
    sp = sub.add_parser("invalidate", help="contract changed: reopen slice + downstream")
    sp.add_argument("slice")
    sp = sub.add_parser("reset")
    sp.add_argument("--yes", action="store_true")
    sp = sub.add_parser("run", help="worker loop for one machine")
    with_machine(sp)
    sp.add_argument("--exec", help="command per slice; {id} and SLICER_* env available")
    sp.add_argument("--on-done", help="command after accept passes (e.g. push / merge)")
    sp.add_argument("--lease", type=float)
    sp.add_argument("--poll", type=float, default=30, help="seconds to wait when blocked")
    sp.add_argument("--once", action="store_true")

    args = p.parse_args(argv)
    try:
        plan, settings = load_plan(args.plan)
        if args.cmd == "validate":
            return cmd_validate(args, plan, settings)
        if args.cmd == "plan":
            return cmd_plan(args, plan, settings)
        store = open_state(args.state or settings["state"])
        return {
            "status": cmd_status, "graph": cmd_graph, "claim": cmd_claim,
            "heartbeat": cmd_heartbeat, "done": cmd_done, "release": cmd_release,
            "retry": cmd_retry, "invalidate": cmd_invalidate, "reset": cmd_reset,
            "run": cmd_run,
        }[args.cmd](args, plan, settings, store)
    except (PlanError, RuntimeError) as e:
        die(str(e))


if __name__ == "__main__":
    sys.exit(main())
