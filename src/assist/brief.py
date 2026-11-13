"""Markdown brief (PLAN S6a) from the stance payloads in `out/{SUBJECT}/{asset}.json`.

Rendered only from the payload contract (`schema/stance.schema.json`): regime, a stance table,
changes since the last run, every stance's drivers / risks / flags, a merged watch list, stale
inputs and source attribution, with the disclaimer at the top and the bottom. Drivers, risks and
watch items are printed as given, so a later layer that adds a driver needs no change here.

"Changes since last run" is a diff against the previous `out/` snapshot: `save_snapshot` copies
`out/` to `<snapshots>/<as_of>/` after a run, and `build_brief` diffs against the newest snapshot
dated before the current stances. A file that is not JSON or fails the schema is skipped and
listed under *Problems*, never raised. Same inputs give the same bytes (no clock reads).

Two optional sections come from outside `out/` (PLAN S14), each passed in as ready-made lines so
the brief stays a pure function of its inputs: *Data health* (the doctor, one line per missing,
locked or stale source; `health_lines`) right under the disclaimer, and *Paper track* (the
48/32/20 benchmark, the legacy 60/40 and each model segment; `paper_lines`) before the details.
Without them the brief is exactly as before.

Rebalance vs tilt (PLAN S42): a payload carrying `portfolio.rebalance_pt` / `tilt_pt` gets its
delta cell suffixed with the split, and a line under the stance table names the mandate legs'
rebalance part a move to the benchmark, not a model call. Older payloads render as before.

*Undervalued candidates* (PLAN S20) is rendered from `out/candidates/*.json`
(`schema/candidates.schema.json`) when that directory holds any valid file, so `assist brief`
reprints it too: per market (IDN, then USA from F6) the hurdle and its drivers (for the US, which
market's hurdle binds), stance and budget, the tilt's verdict, each style's verdict (a failed one
with no names) and its rows ranked by margin, then trims. Amounts and prices are in IDR; a US row's
drivers carry its USD price and its margins over both hurdles.

*Top tier replay* (PLAN S31, P50) is rendered from `out/industries/IDN.replay.json` when it is
there: the replay's verdict on Tier A against its industry's median, with its control, t, p,
quarters, flags and fingerprint, and a reminder that the tiers stay context only.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from assist.candidates import tiers_replay
from assist.layers.types import DISCLAIMER, stance_validator
from assist.layers.undervalued import load_out as load_candidates
from assist.stance import BENCHMARK_PCT, BENCHMARK_TEXT, mandate_summary, split_text

__all__ = [
    "ASSET_ORDER",
    "HOME",
    "SCORE_EPS",
    "Loaded",
    "build_brief",
    "diff",
    "health_lines",
    "load_out",
    "paper_lines",
    "tier_replay_lines",
    "undervalued_lines",
    "previous_snapshot",
    "render",
    "save_snapshot",
    "split_line",
    "targets_line",
]

HOME = "IDN"  # the investor's home market sorts first
ASSET_ORDER = ("stocks", "bonds", "currency", "commodities")
SCORE_EPS = 1.0  # score moves smaller than this many points are not reported as changes
_SUBJECT_DIR = re.compile(r"^[A-Z0-9_]+$")
_SNAPSHOT_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Loaded:
    stances: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


# ---------------- loading and snapshots ----------------

def _stance_files(out_dir: Path) -> list[Path]:
    if not out_dir.is_dir():
        return []
    return [f for d in sorted(out_dir.iterdir()) if d.is_dir() and _SUBJECT_DIR.match(d.name)
            for f in sorted(d.glob("*.json"))]


def load_out(out_dir: Path) -> Loaded:
    """Every valid stance under `out_dir/{SUBJECT}/*.json`, sorted; bad files go to `problems`."""
    out_dir = Path(out_dir)
    validator = stance_validator()
    stances, problems = [], []
    for f in _stance_files(out_dir):
        rel = f.relative_to(out_dir).as_posix()
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            problems.append(f"{rel}: not readable JSON ({e})")
            continue
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            problems.append(f"{rel}: fails the stance schema ({errors[0].message})")
            continue
        stances.append(payload)
    return Loaded(_sorted(stances), problems)


def save_snapshot(out_dir: Path, snapshots_dir: Path, as_of: str) -> Path:
    """Copy the stance files of `out_dir` to `snapshots_dir/as_of/`, replacing that day's copy."""
    out_dir, dest = Path(out_dir), Path(snapshots_dir) / as_of
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for f in _stance_files(out_dir):
        target = dest / f.relative_to(out_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    return dest


def previous_snapshot(snapshots_dir: Path, before: str) -> Path | None:
    """The newest `snapshots_dir/YYYY-MM-DD` dated strictly before `before`, or None."""
    snapshots_dir = Path(snapshots_dir)
    if not snapshots_dir.is_dir():
        return None
    dates = [d for d in snapshots_dir.iterdir()
             if d.is_dir() and _SNAPSHOT_DIR.match(d.name) and d.name < before]
    return max(dates, key=lambda d: d.name) if dates else None


def build_brief(out_dir: Path, snapshots_dir: Path, *, health: Sequence[str] | None = None,
                paper: Sequence[str] | None = None) -> str:
    """Brief for the stances in `out_dir`, diffed against the newest earlier snapshot."""
    loaded = load_out(out_dir)
    as_of = _as_of(loaded.stances)
    prev_dir = previous_snapshot(snapshots_dir, before=as_of) if as_of else None
    previous = load_out(prev_dir).stances if prev_dir else None
    cands = load_candidates(out_dir)
    replay = tiers_replay.load(out_dir)
    return render(loaded.stances, previous, problems=loaded.problems,
                  previous_as_of=prev_dir.name if prev_dir else None, health=health,
                  paper=paper, undervalued=[x for p in cands for x in undervalued_lines(p)]
                  or None, tier_replay=tier_replay_lines(replay) if replay else None)


def with_guide(text: str, guide_lines: Sequence[str]) -> str:
    """The brief with a "This week" section (PLAN S78) right after its title and disclaimer:
    the guide's plain lines, the numbered steps as a list."""
    if not guide_lines:
        return text
    body = ["## This week", ""]
    for line in guide_lines:
        body.append(line if re.match(r"\d+\. ", line) else f"- {line}")
    section = "\n".join(body) + "\n\n"
    at = text.find("\n## ")
    return text + "\n" + section if at < 0 else text[:at + 1] + section + text[at + 1:]


# ---------------- doctor and paper lines ----------------

_PROBLEM_PROBES = ("stale", "empty", "absent", "error")
_PROBLEM_ORDER = ("missing", "locked", "error", "stale")


def _probe_text(p: Any) -> str:
    if p.status == "stale" and p.age_days is not None:
        return f"{p.name} {p.age_days}d/{p.max_age_days}d"
    return f"{p.name} {p.status}"


def health_lines(statuses: Sequence[Any]) -> list[str]:
    """The doctor (`doctor.SourceStatus` list) in a few lines: a count, then one line per source
    that is not present and fresh, or present with a probe that is absent or failing."""
    n = len(statuses)
    bad = {s.name: [p for p in s.probes if p.status in _PROBLEM_PROBES] for s in statuses}
    fine = [s for s in statuses if s.status == "present" and not bad[s.name]]
    if len(fine) == n:
        return [f"Doctor: all {n} source(s) present and fresh."]
    counts = Counter(s.status for s in statuses)
    tally = ", ".join(f"{counts[k]} {k}" for k in _PROBLEM_ORDER if counts[k])
    lines = [f"Doctor: {len(fine)} of {n} sources present and fresh"
             + (f"; {tally}." if tally else ".")]
    for s in statuses:
        if s in fine:
            continue
        probes = ", ".join(_probe_text(p) for p in bad[s.name])
        if s.status == "present":
            lines.append(f"{s.name}: present, but {probes}")
        elif s.status == "stale":
            newest = f", newest {s.newest.isoformat()}" if s.newest else ""
            lines.append(f"{s.name}: stale{newest}" + (f" ({probes})" if probes else ""))
        else:
            detail = s.detail.splitlines()[0][:120] if s.detail else probes
            lines.append(f"{s.name}: {s.status}" + (f" ({detail})" if detail else ""))
    return lines


def _signed(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f}%"


_LEG_NAMES = {"stocks": "JCI", "bonds": "SBN leg", "usa": "US stocks (IDR)"}


def _pct_text(pct: Mapping) -> str:
    return " / ".join(f"{pct[k]:g}% {n}" for k, n in _LEG_NAMES.items() if k in pct)


def _bench_line(name: str, pct: Mapping, summary: Mapping, start: Any) -> str:
    line = f"{name} {_pct_text(pct)}: "
    if summary.get("weeks"):
        n = summary.get("annualize_min_weeks")  # paper.MIN_ANNUALISE_WEEKS (S41)
        ann = (f"annualised after {n} scored weeks"
               if n and summary["annualized"] is None and summary["weeks"] < n
               else f"annualised {_signed(summary['annualized'])}")
        line += (f"{summary['weeks']} week(s) scored from {start}, cumulative "
                 f"{_signed(summary['cumulative'])}, {ann}")
    else:
        line += "no week scored"
    if summary.get("stale_weeks"):
        line += f"; {summary['stale_weeks']} stale week(s), not scored"
    return line + "."


def mark_legs(m: Any) -> str:
    """'JCI +1.0%, SBN leg +0.2%, US stocks (IDR) +0.9% = SPY +0.5% × USD/IDR +0.4%'."""
    out = f"JCI {_signed(m.jci)}, SBN leg {_signed(m.sbn)}"
    if getattr(m, "usa", None) is not None:
        out += (f", US stocks (IDR) {_signed(m.usa)} = SPY {_signed(m.usa_usd)} × USD/IDR "
                f"{_signed(m.usd_idr)}")
    return out


def paper_lines(report: Any) -> list[str]:
    """`paper.PaperReport` in a few lines: the benchmark's scored and stale weeks (and the legacy
    60/40's beside it), the last scored week with each leg, one line per model segment with the
    benchmark it is scored on (or "benchmark marks only"), stale legs, the legs and their sources.
    A stale week is counted, never filled in."""
    lines = [_bench_line("Benchmark", report.benchmark_pct, report.benchmark_summary,
                         report.start)]
    scored = [m for m in report.benchmark if m.benchmark is not None]
    if scored:
        m = scored[-1]
        lines.append(f"Last scored week ends {m.week_end}: benchmark {_signed(m.benchmark)} "
                     f"({mark_legs(m)}).")
    legacy = getattr(report, "legacy_summary", None)
    if legacy is not None and getattr(report, "legacy_benchmark_pct", None):
        lines.append(_bench_line("Legacy benchmark (segments before S39)",
                                 report.legacy_benchmark_pct, legacy, report.legacy_start))
    if not report.segments:
        lines.append("No stance history in the journal yet: benchmark marks only.")
    for seg in report.segments:
        pct = getattr(seg, "benchmark_pct", None)
        line = (f"Model `{_fingerprint(seg.fingerprint)}`"
                + (f" (vs {'/'.join(f'{v:g}' for v in pct.values())})" if pct else "")
                + f": from {seg.first_as_of}, {seg.weeks} week(s) scored "
                f"({seg.stale_weeks} stale)")
        if seg.weeks:
            hit = "n/a" if seg.hit_rate is None else f"{seg.hit_rate * 100:.0f}%"
            line += (f": portfolio {_signed(seg.portfolio_return)} vs benchmark "
                     f"{_signed(seg.benchmark_return)}, active {_signed(seg.active_return)}, "
                     f"hit rate {hit}")
        else:
            line += ": nothing scored yet"
        lines.append(line + ".")
    lines += [f"Stale: {x}." for x in report.stale_inputs]
    legs = "; ".join(f"{_LEG_NAMES[k]} = {report.legs[k]}" for k in _LEG_NAMES
                     if k in report.legs)
    lines.append(f"Legs: {legs}.")
    fl = getattr(report, "flips", None)
    if fl:  # S91: acted verdict flips per held name per quarter
        from assist import flips as _flips
        lines += _flips.lines(fl)
    return lines


def _idr(x: float | None) -> str:
    return "n/a" if x is None else f"IDR {x:,.0f}"


GATE_NAMES = {2: "not kept by a passing screen", 4: "no room under the caps",
              5: "not sized"}


def average_down_view(p: Mapping) -> dict | None:
    """The payload's `average_down` block (PLAN S68) sorted for display: `funded` (with the
    sized amount), `unfunded`, `stopped` (underwater names past gate 1) and counts. None when
    the payload has no block or no held name."""
    block = p.get("average_down") or {}
    names = [n for n in block.get("names") or [] if isinstance(n, Mapping)]
    if not names:
        return None
    sized = {r["symbol"]: r["size"]["idr"] for s in p.get("styles") or []
             for r in s.get("rows") or [] if r.get("action") == "average_down" and r.get("size")}
    under = [n for n in names if n.get("gate") != 1]
    stopped = [n for n in under if n.get("status") == "stopped"]
    return {"held": len(names), "underwater": len(under),
            "underwater_pct": block.get("underwater_pct"), "gate3": block.get("gate3"),
            "funded": [{**n, "idr": sized.get(n["symbol"])} for n in under
                       if n.get("status") == "average_down"],
            "unfunded": [n for n in under if n.get("status") == "unfunded"],
            "stopped": sorted(stopped, key=lambda n: (n.get("below_cost_pct") or 0.0,
                                                      n["symbol"])),
            "stops": dict(Counter(n.get("gate") for n in stopped))}


def _vs_cost(n: Mapping) -> str:
    b = n.get("below_cost_pct")
    return "n/a" if b is None else f"{b:+.1f}% vs cost"


def average_down_lines(p: Mapping) -> list[str]:
    """Plain lines for the brief and Telegram: each funded and unfunded name, then one line on
    the underwater names that stopped at a gate. Empty when nothing is held."""
    v = average_down_view(p)
    if v is None:
        return []
    out = []
    for n in v["funded"]:
        new = n.get("new_avg_cost")
        move = "" if new is None else f", average cost {n['avg_cost']:,.0f} → {new:,.0f}"
        out.append(f"{n['symbol']} {_idr(n.get('idr'))} ({_vs_cost(n)}{move})")
    for n in v["unfunded"]:
        out.append(f"{n['symbol']} unfunded ({_vs_cost(n)}): {n['reason']}")
    pct = v["underwater_pct"]
    pct = "" if pct is None else f" {pct:g}% or more"
    if not v["underwater"]:
        out.append(f"none: no held name is{pct} below cost ({v['held']} held)")
        return out
    stops = ", ".join(f"{k} {GATE_NAMES.get(g, f'stopped at gate {g}')}"
                      for g, k in sorted(v["stops"].items(), key=lambda x: (x[0] or 0)))
    head = "" if v["funded"] or v["unfunded"] else "none: "
    out.append(f"{head}{v['underwater']} of {v['held']} held names are{pct} below cost"
               + (f" ({stops})" if stops else ""))
    return out


def undervalued_lines(p: Mapping) -> list[str]:
    """One market's candidates payload as Markdown lines (a few bullets and one table per
    passing style). Rows are ranked within their style only."""
    st, h = p["stance"], p["hurdle"]["required_pt"]
    head = (f"**{p['market']}** (bars {p['bar_date'] or 'n/a'}): hurdle "
            f"{'n/a' if h is None else f'{h:.2f}%'}, stocks stance {st['stance'] or 'n/a'} "
            f"{_pct(st['current_pct'])} → {_pct(st['target_pct'])}, budget "
            f"{_idr(p['sizing']['budget_idr'])}")
    if p["sizing"]["budget_idr"]:
        head += f" ({_idr(p['sizing']['unspent_idr'])} unspent)"
    t = p["tilt"]
    if t["passed"]:
        tilt = f"- Sector tilt: passed ({t['verdict']}); margins shifted and sector caps set"
    elif t["fingerprint"] is None and not t["sectors"]:  # no tilt run at all (USA: by design)
        tilt = f"- Sector tilt: {t['verdict']}; no margin shift, default caps"
    else:
        tilt = f"- Sector tilt: verdict failed ({t['verdict']}); no margin shift, default caps"
    out = [head + ".", ""]
    if p["hurdle"]["drivers"]:
        out.append("- Hurdle: " + "; ".join(p["hurdle"]["drivers"]))
    out.append(tilt)
    for s in p["styles"]:
        stats = ", ".join(x for x in (
            None if s.get("t") is None else f"t {s['t']:.2f}",
            None if s.get("p") is None else f"p {s['p']:.3f}") if x)
        # not when the verdict already says them, nor for a replay with no quarters to judge
        shown = re.search(r"\bt -?\d", s["verdict"]) or not s.get("quarters")
        stats = f", {stats}" if stats and not shown else ""
        if s["passed"]:
            drop = f", {len(s['dropped'])} dropped" if s["dropped"] else ""
            out.append(f"- {s['style']}: passed ({s['verdict']}){stats}, pool {s['pool']}, "
                       f"{len(s['rows'])} name(s){drop}")
        else:
            out.append(f"- {s['style']}: verdict failed ({s['verdict']}){stats}, pool "
                       f"{s['pool']}: no names")
    for s in p["styles"]:
        if not s["rows"]:
            continue
        out += ["", f"*{s['style']}*, ranked by margin over the hurdle:", "",
                "| # | Symbol | Sector | Expected | Margin | Net of cost | Entry | Held | Action |",
                "|---:|---|---|---:|---:|---:|---|---|---|"]
        for r in s["rows"]:
            e = r["entry"]
            entry = "n/a" if e["level"] is None else f"{e['level']:,.0f} ({e['basis']})"
            verb = "average down" if r["action"] == "average_down" else "add"
            act = r["action"] if r["size"] is None else f"{verb} {_idr(r['size']['idr'])}"
            cells = [str(r["rank"]), r["symbol"], r["sector"] or "n/a",
                     f"{r['expected_pt']:.2f}%", f"{r['margin_pt']:+.2f}pt",
                     f"{r['net_margin_pt']:+.2f}pt", entry,
                     _idr(r["held_idr"]) if r["held"] else "no", act]
            out.append("| " + " | ".join(_cell(c) for c in cells) + " |")
        out.append("")
        for r in s["rows"]:
            if r["drivers"][1:]:
                out.append(f"- {r['symbol']}: " + "; ".join(r["drivers"][1:]))
        for d in s["dropped"]:
            out.append(f"- dropped {d['symbol']}: {d['reason']}")
    for x in p["sizing"]["trims"]:
        out.append(f"- trim {x['symbol']} {_idr(x['idr'])}: {x['reason']}")
    for line in average_down_lines(p):
        out.append(f"- average down: {line}")
    out.append("")
    return out


def _stat(name: str, x: Any, fmt: str) -> str | None:
    return None if x is None else f"{name} {format(x, fmt)}"


def tier_replay_lines(p: Mapping) -> list[str]:
    """The S31 replay payload as a few Markdown bullets: verdict, statistics, flags, model."""
    out = [f"- Tier A minus industry median, 3-month forward return from quarter ends: "
           f"**{p.get('status')}** ({p.get('verdict')})"]
    if p.get("quarters"):
        ex, pl = p.get("mean_excess"), p.get("mean_placebo")
        stats = ", ".join(x for x in (
            f"{p['quarters']} quarters {p.get('first_quarter')} to {p.get('last_quarter')}",
            None if ex is None else f"mean excess {ex * 100:+.2f}pt",
            None if pl is None else f"shuffled-composite placebo {pl * 100:+.2f}pt",
            _stat("t", p.get("t"), ".2f"),
            _stat("p", p.get("p"), ".3f"),
            _stat("perm p", p.get("perm_p"), ".3f"),
            _stat("control t", p.get("control_t"), ".2f"),
        ) if x)
        out.append(f"- {stats}")
    if p.get("flags"):
        out.append("- Flags: " + "; ".join(p["flags"]))
    if p.get("passed"):
        out.append("- Passed, but the tiers stay context only until a later decision lets "
                   "Tier A feed S20.")
    else:
        out.append("- Context only: the tiers feed no screen, S20 list, sizing or stance.")
    fp = p.get("fingerprint")
    if fp:
        out.append(f"- Replay model: `{_fingerprint(fp)}`")
    return out + [""]


# ---------------- helpers ----------------

def _key(s: Mapping) -> tuple[str, str]:
    return s["subject"], s["asset"]


def _sort_key(s: Mapping) -> tuple:
    asset = s["asset"]
    rank = ASSET_ORDER.index(asset) if asset in ASSET_ORDER else len(ASSET_ORDER)
    return (s["subject"] != HOME, s["subject"], rank, asset)


def _sorted(stances: Iterable[Mapping]) -> list[dict]:
    return sorted((dict(s) for s in stances), key=_sort_key)


def _label(s: Mapping) -> str:
    return f"{s['subject']} {s['asset']}"


def _as_of(stances: Sequence[Mapping]) -> str | None:
    return max((s["as_of"] for s in stances), default=None)


def _num(x: float | None) -> str:
    return "n/a" if x is None else format(round(float(x), 1), "g")


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{_num(x)}%"


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def targets_line(stances: Sequence[Mapping]) -> str:
    """S39: the mandate legs' targets, their sum over every stance and the cash rest."""
    m = mandate_summary(stances)
    legs = " + ".join(f"{k.replace('/', ' ')} {_pct(v)}" for k, v in m["targets_pct"].items())
    bench = " / ".join(f"{k.replace('/', ' ')} {v:g}%" for k, v in m["benchmark_pct"].items())
    return (f"Targets: {legs or 'no mandate leg'} = {_pct(m['target_sum_pct'])}; cash rest "
            f"{_pct(m['cash_pct'])}. Benchmark {bench}; every other stance is outside the 80/20 "
            "mandate and targets 0%.")


def _delta_cell(pf: Mapping) -> str:
    split = split_text(pf)
    return pf["delta"] if split is None else f"{pf['delta']}; {split}"


def split_line(stances: Sequence[Mapping]) -> str | None:
    """S42: each mandate leg's gap as rebalance + tilt, or None when no leg carries the split."""
    parts = []
    for s in stances:
        pf = s.get("portfolio") or {}
        if (s.get("subject"), s.get("asset")) in BENCHMARK_PCT and split_text(pf):
            parts.append(f"{s['subject']} {s['asset']} {pf['rebalance_pt']:+.1f}pt rebalance, "
                         f"{pf['tilt_pt']:+.1f}pt tilt")
    if not parts:
        return None
    return (f"Rebalance vs tilt: {'; '.join(parts)}. The rebalance part is a move to the "
            f"{BENCHMARK_TEXT} benchmark, not a model call; only the tilt comes from the stance. "
            "Paper only, not an order.")


def _entry(e: Mapping) -> str:
    if e["style"] == "ladder":
        return f"ladder {e['tranches']}×{e['spacing_days']}d"
    return e["style"]


def _mode(values: Iterable[str]) -> str | None:
    counts = Counter(values)
    if not counts:
        return None
    top = max(counts.values())
    return min(v for v, n in counts.items() if n == top)


def _by_value(stances: Sequence[Mapping], field_name: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for s in stances:
        if s.get(field_name) is not None:
            groups.setdefault(s[field_name], []).append(_label(s))
    return dict(sorted(groups.items()))


def _fingerprint(fp: str) -> str:
    return fp[: len("sha256:") + 12]


HOME_ASSETS = (("IDN", "stocks"), ("IDN", "bonds"))


def _home(stances: Sequence[Mapping]) -> Mapping | None:
    """The home (IDN) regime block of the IDN stocks or bonds stance (S53), None without one."""
    for s in stances:
        if (s.get("subject"), s.get("asset")) in HOME_ASSETS and s.get("home_regime"):
            return s["home_regime"]
    return None


def home_line(stances: Sequence[Mapping]) -> str | None:
    """The brief's "Home regime (IDN)" line (S54): state, points, scoring drivers, what a
    risk_off does, stale inputs; None when no IDN stance carries the home regime."""
    h = _home(stances)
    if h is None:
        return None
    n = int(h.get("points") or 0)
    line = f"- Home regime (IDN): {h['state']}, {n} point{'' if n == 1 else 's'}"
    if h.get("drivers"):
        line += f" ({'; '.join(h['drivers'])})"
    if h["state"] == "risk_off":
        line += "; IDN stocks and bonds adds and trims laddered"
    if h.get("stale_inputs"):
        line += "; stale: " + "; ".join(h["stale_inputs"])
    return line


def override_gate_line(stances: Sequence[Mapping]) -> str | None:
    """The brief's layer-2 override gate line (S61): the sides that passed their gate, the bands
    a passed side crossed, and the stances held at the band; None when no stance carries a
    gate (`layer2.gate`)."""
    gated = [s for s in stances if (s.get("layer2") or {}).get("gate")]
    if not gated:
        return None
    passed = [f"{_label(s)} {'/'.join(s['layer2']['passed'])}" for s in gated
              if s["layer2"].get("passed")]
    crossed = [f"{_label(s)} → {s['stance']}" for s in gated if s["layer2"].get("crossed")]
    held = [_label(s) for s in gated if s["layer2"].get("held")]
    if passed:
        line = f"- Layer-2 override gate: passed: {', '.join(passed)}"
        if crossed:
            line += f"; crossed: {', '.join(crossed)}"
    else:
        line = (f"- Layer-2 override gate: no side passed ({len(gated)} gated stance(s)); "
                "overrides move scores, never bands")
    if held:
        line += f"; held at the band: {', '.join(held)}"
    return line


def _grouped_line(name: str, groups: Mapping[str, list[str]]) -> str:
    if not groups:
        return f"- {name}: n/a"
    if len(groups) == 1:
        return f"- {name}: **{next(iter(groups))}**"
    parts = "; ".join(f"**{v}** ({', '.join(labels)})" for v, labels in groups.items())
    return f"- {name}: mixed, {parts}"


# ---------------- diff ----------------

def diff(previous: Sequence[Mapping], current: Sequence[Mapping]) -> list[str]:
    """One line per change between two runs: regime, model, and per stance its stance, score
    (moves of at least `SCORE_EPS`), entry style, target weight and stale inputs; new and
    dropped stances. Empty when nothing changed."""
    prev, cur = {_key(s): s for s in previous}, {_key(s): s for s in current}
    lines = []
    for name in ("regime", "dollar"):
        before = _mode(s[name] for s in previous if s.get(name) is not None)
        after = _mode(s[name] for s in current if s.get(name) is not None)
        if before and after and before != after:
            lines.append(f"{name.capitalize()}: {before} → {after}")
    fp_before = sorted({s["model_fingerprint"] for s in previous})
    fp_after = sorted({s["model_fingerprint"] for s in current})
    if fp_before and fp_after and fp_before != fp_after:
        lines.append(
            f"Model changed: {', '.join(map(_fingerprint, fp_before))} → "
            f"{', '.join(map(_fingerprint, fp_after))} (the record segments here)")
    for s in _sorted(cur.values()):
        p = prev.get(_key(s))
        if p is None:
            lines.append(f"{_label(s)}: new ({s['stance']}, score {_num(s['score'])})")
            continue
        parts = []
        if p["stance"] != s["stance"]:
            parts.append(f"stance {p['stance']} → {s['stance']}")
        if abs(float(s["score"]) - float(p["score"])) >= SCORE_EPS:
            parts.append(f"score {_num(p['score'])} → {_num(s['score'])}")
        if p["entry"]["style"] != s["entry"]["style"]:
            parts.append(f"entry {p['entry']['style']} → {s['entry']['style']}")
        if p["portfolio"]["target_pct"] != s["portfolio"]["target_pct"]:
            parts.append(f"target {_pct(p['portfolio']['target_pct'])} → "
                         f"{_pct(s['portfolio']['target_pct'])}")
        added = sorted(set(s["stale_inputs"]) - set(p["stale_inputs"]))
        cleared = sorted(set(p["stale_inputs"]) - set(s["stale_inputs"]))
        if added or cleared:
            moves = [f"+{x}" for x in added] + [f"-{x}" for x in cleared]
            parts.append("stale " + ", ".join(moves))
        if parts:
            lines.append(f"{_label(s)}: " + "; ".join(parts))
    for s in _sorted(p for k, p in prev.items() if k not in cur):
        lines.append(f"{_label(s)}: dropped (was {s['stance']})")
    return lines


# ---------------- render ----------------

def render(current: Sequence[Mapping], previous: Sequence[Mapping] | None = None, *,
           problems: Sequence[str] = (), previous_as_of: str | None = None,
           health: Sequence[str] | None = None, paper: Sequence[str] | None = None,
           undervalued: Sequence[str] | None = None,
           tier_replay: Sequence[str] | None = None) -> str:
    """The brief as Markdown. `previous` None means there is no earlier run to diff against.
    `health` (doctor lines) and `paper` (paper-track lines) add their sections when given."""
    stances = _sorted(current)
    as_of = _as_of(stances)
    out: list[str] = [f"# Investment brief {as_of}" if as_of else "# Investment brief", ""]
    out += [f"> {DISCLAIMER} Context for an IDR-based investor, built from "
            f"{len(stances)} stance payload(s); every source is listed at the end.", ""]
    if health is not None:
        out += ["## Data health", ""] + [f"- {x}" for x in health] + [""]

    out += ["## Global regime", ""]
    if stances:
        out.append(_grouped_line("Regime", _by_value(stances, "regime")))
        out.append(_grouped_line("Dollar", _by_value(stances, "dollar")))
        home = home_line(stances)
        if home:
            out.append(home)
        gate = override_gate_line(stances)
        if gate:
            out.append(gate)
        fps = sorted({_fingerprint(s["model_fingerprint"]) for s in stances})
        out.append(f"- Model: `{'`, `'.join(fps)}`")
    else:
        out.append("No stances in out/ yet.")
    out.append("")

    out += ["## Stances", ""]
    if stances:
        out.append("| Subject | Asset | Stance | Score | Layer 1 | Conf. | Entry | Now → target "
                   "| Delta |")
        out.append("|---|---|---|---:|---:|---:|---|---|---|")
        for s in stances:
            pf = s["portfolio"]
            cells = [s["subject"], s["asset"], s["stance"], _num(s["score"]),
                     _num(s.get("layer1_score")), f"{float(s['confidence']):.2f}",
                     _entry(s["entry"]), f"{_pct(pf['current_pct'])} → {_pct(pf['target_pct'])}",
                     _delta_cell(pf)]
            out.append("| " + " | ".join(_cell(c) for c in cells) + " |")
        notes = sorted({n for s in stances for n in s["portfolio"].get("notes", [])})
        if notes:
            out += ["", "Holdings: " + "; ".join(notes) + "."]
        out += ["", targets_line(stances)]
        split = split_line(stances)
        if split:
            out += ["", split]
    else:
        out.append("No stances.")
    out.append("")

    out += ["## Changes since last run", ""]
    if previous is None:
        out.append("First run: no earlier snapshot to compare with.")
    else:
        since = previous_as_of or _as_of(previous)
        if since:
            out += [f"Compared with {since}.", ""]
        changes = diff(previous, stances)
        out += [f"- {c}" for c in changes] if changes else ["No changes."]
    out.append("")

    if undervalued is not None:
        out += ["## Undervalued candidates", "",
                "Context only: no stance moves on these, and sizes are paper until the weight "
                "bands are confirmed.", "", *undervalued]

    if tier_replay is not None:
        out += ["## Top tier replay", "", *tier_replay]

    if paper is not None:
        out += ["## Paper track", ""] + [f"- {x}" for x in paper] + [""]

    out += ["## Details", ""]
    for s in stances:
        out += [f"### {_label(s)}: {s['stance']}, score {_num(s['score'])}", ""]
        for title, items in (("Drivers", s["drivers"]), ("Risks", s["risks"]),
                             ("Flags", [f"{f['severity']} `{f['code']}`: {f['message']}"
                                        for f in s.get("flags", [])])):
            if items:
                out += [f"**{title}**", ""] + [f"- {i}" for i in items] + [""]
        if not (s["drivers"] or s["risks"] or s.get("flags")):
            out += ["No drivers or risks given.", ""]
    if not stances:
        out += ["None.", ""]

    out += ["## Watch", ""]
    watch: dict[str, list[str]] = {}
    for s in stances:
        for item in s["watch"]:
            watch.setdefault(item, []).append(_label(s))
    out += [f"- {item} ({', '.join(watch[item])})" for item in sorted(watch)] or ["Nothing."]
    out.append("")

    out += ["## Stale inputs", ""]
    stale: dict[str, list[str]] = {}
    for s in stances:
        for item in s["stale_inputs"]:
            stale.setdefault(item, []).append(_label(s))
    out += [f"- {item}: {', '.join(stale[item])}" for item in sorted(stale)] or ["None."]
    out.append("")

    if problems:
        out += ["## Problems", ""] + [f"- {p}" for p in problems] + [""]

    sources = sorted({src for s in stances for src in s["sources"]})
    out += ["## Sources", ""]
    out += [f"- {src}" for src in sources] or ["None."]
    out += ["", "---", "",
            f"_{DISCLAIMER} Sources: {', '.join(sources) if sources else 'none'}._", ""]
    return "\n".join(out)
