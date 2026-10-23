"""`assist` command line: doctor | run | brief | regime | paper | journal."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import httpx

from assist import brief, doctor, journal, notify, paper, pipeline, stance
from assist.layers import regime as regime_layer


def _today(args: argparse.Namespace) -> date:
    return date.fromisoformat(args.today) if getattr(args, "today", None) else date.today()


def _doctor(args: argparse.Namespace) -> int:
    today = _today(args)
    sources = doctor.load_sources(Path(args.config), root=Path(args.root) if args.root else None)
    client = None if args.no_http else httpx.Client(trust_env=False)
    try:
        statuses = doctor.run_doctor(sources, today, http_client=client)
    finally:
        if client is not None:
            client.close()
    if args.json:
        print(json.dumps([s.to_json() for s in statuses], indent=2))
    else:
        print(doctor.format_report(statuses, today))
    return 0  # a missing, locked or stale source is reported, never a failure


def _run(args: argparse.Namespace) -> int:
    day = _today(args)
    paths = pipeline.Paths.default()
    res = pipeline.run(day, paths=paths, sources=pipeline.Sources.default(),
                       send=not args.no_send)
    reg = res.regime
    print(f"assist run {day}: regime {reg.state}, dollar {reg.dollar}")
    if res.ok:
        counts: dict[str, int] = {}
        for s in res.stances:
            counts[s["stance"]] = counts.get(s["stance"], 0) + 1
        mix = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        print(f"{len(res.stances)} stance(s) → {paths.out} ({mix})")
        print(f"model {res.fingerprint}")
        print(f"brief {res.brief_path}")
        for s in res.stances:
            if s["subject"] == pipeline.HOME and s["asset"] in pipeline.RULE_ASSETS:
                print(f"{s['subject']} {s['asset']}: {s['stance']} (score {s['score']:.1f},"
                      f" confidence {s['confidence']:.2f})")
        if res.idn is not None:
            for asset in pipeline.RULE_ASSETS:
                rule, verdict = res.idn.rule(asset), res.idn.verdicts.get(asset)
                v = "none" if verdict is None else verdict.reason
                print(f"  {asset} rule: {rule.call}, proposes {rule.proposed_stance};"
                      f" verdict: {v}")
            print(f"  {res.idn.candidates.headline()}")
            for c in res.idn.candidates.candidates:
                print(f"    {c.symbol:<5} {c.screen}: {c.detail}")
        if res.foreign is not None:
            _print_foreign(res)
    else:
        print("no stance written: layer 1 (worldbankscape) unavailable; out/ left as it was")
    for s in res.stale_inputs:
        print(f"stale: {s}")
    for path, why in res.problems.items():
        print(f"problem: {path}: {why}")
    if res.notify is not None:
        print(notify.describe(res.notify))
    elif args.no_send:
        print("telegram: not sent (--no-send)")
    else:
        print("telegram: not sent (no stances)")
    return 0 if res.ok else 1


def _print_foreign(res: pipeline.RunResult) -> None:
    """Phase C: each P28 market's shifts, the bands they were held at, P29's index candidates
    and each foreign stance that is not neutral."""
    f = res.foreign
    for m in f.overrides.markets:
        shifts = ", ".join(f"{o.asset} {o.delta:+.0f}" for o in m.overrides)
        print(f"foreign overrides {m.subject}: {shifts}")
    print("  KOR, TWN: no layer-2 overrides (P28 covers USA, JPN, EMU, AUS, SGP); layer-1 score"
          " stands")
    foreign = [s for s in res.stances if s["subject"] in pipeline.FOREIGN
               and s["asset"] in pipeline.FOREIGN_ASSETS]
    held = [f"{s['subject']} {s['asset']} ({s['score']:.1f})" for s in foreign
            if stance.stance_for(s["score"]) != s["stance"]]
    if held:
        print(f"  band held until the overrides beat a placebo: {', '.join(held)}")
    vals = f.candidates.valuations
    passing = sum(v.passes for v in vals)
    print(f"foreign layer 4: {len(vals)} index candidate(s), {passing} passing. Context only:"
          " no stance change")
    for v in vals:
        print(f"    {v.market.symbol:<6} score {v.score:.1f}: {v.detail()}")
    for s in foreign:
        if s["stance"] != "neutral":
            print(f"{s['subject']} {s['asset']}: {s['stance']} (score {s['score']:.1f},"
                  f" confidence {s['confidence']:.2f})")


def _brief(args: argparse.Namespace) -> int:
    paths = pipeline.Paths.default()
    text = brief.build_brief(paths.out, paths.snapshots)
    print(text, end="" if text.endswith("\n") else "\n")
    if not args.send:
        return 0
    loaded = brief.load_out(paths.out)
    if not loaded.stances:
        print("telegram: nothing to send (out/ is empty)", file=sys.stderr)
        return 1
    day = date.fromisoformat(max(s["as_of"] for s in loaded.stances))
    regimes = "/".join(sorted({s["regime"] for s in loaded.stances}))
    msg = pipeline.message(loaded.stances, regime=regimes, day=day,
                           brief_path=paths.briefs / f"{day}.md")
    result = notify.send(msg, kind="brief", day=day, state_dir=paths.notify)
    print(notify.describe(result), file=sys.stderr)
    return 0


def _regime_check(args: argparse.Namespace) -> int:
    """Daily job: Telegram only when the regime or the dollar direction changed."""
    day = _today(args)
    chk = pipeline.regime_check(day, paths=pipeline.Paths.default(),
                                source=pipeline.Sources.default().fred, send=not args.no_send)
    reg = chk.regime
    print(f"regime check {day}: {reg.state}, dollar {reg.dollar}")
    for s in reg.stale_inputs:
        print(f"  stale: {s}")
    if not chk.available:
        print("regime unreadable (no FRED source): nothing compared, nothing sent")
        return 0
    prev = chk.previous
    if prev is None:
        print("no regime journalled yet: " + ("baseline journalled" if chk.journalled
                                              else "nothing written (--no-send)"))
        return 0
    print(f"last journalled {prev['as_of']}: {prev['state']}, dollar {prev['dollar']}")
    if not chk.changed:
        print("unchanged: nothing sent")
        return 0
    for c in chk.changes():
        print(c)
    if chk.notify is None:
        print("telegram: not sent (--no-send)")
    else:
        print(notify.describe(chk.notify))
        if not chk.journalled:
            print("not journalled: the next check retries the message")
    return 0


def _paper(args: argparse.Namespace) -> int:
    day = _today(args)
    rep = paper.paper_track(journal=journal.Journal(pipeline.Paths.default().journal), until=day)
    if args.json:
        print(json.dumps(rep.to_dict(marks=args.marks), indent=2, sort_keys=True))
        return 0
    print(f"paper track {day} (IDN sleeve vs the IDR 60/40 benchmark)")
    for line in brief.paper_lines(rep):
        print(f"- {line}")
    print(rep.disclaimer)
    return 0


def _regime(args: argparse.Namespace) -> int:
    if args.check:
        return _regime_check(args)
    day = _today(args)
    reg = regime_layer.regime(day, source=pipeline.Sources.default().fred)
    if args.json:
        print(json.dumps(journal.jsonable(reg), indent=2, sort_keys=True))
        return 0
    print(f"regime {day}: {reg.state}, dollar {reg.dollar}")
    for d in reg.drivers:
        print(f"  driver: {d}")
    for s in reg.stale_inputs:
        print(f"  stale: {s}")
    return 0


def _journal(args: argparse.Namespace) -> int:
    j = journal.Journal(pipeline.Paths.default().journal)
    try:
        n, chain = j.verify(), "chain ok"
    except ValueError as e:
        n, chain = sum(1 for _ in j.read()), f"chain BROKEN: {e}"
    segs = j.segments()
    print(f"{j.path}: {n} record(s), {len(segs)} model(s), {chain}")
    for fp, recs in segs.items():
        days = sorted({r["as_of"] for r in recs if r.get("as_of")})
        span = f"{days[0]} … {days[-1]}" if days else "-"
        stances = sum(1 for r in recs if r["kind"] == "stance")
        print(f"  {fp[:19]}  {len(recs)} record(s), {stances} stance(s), {span}")
    return 0 if chain == "chain ok" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assist", description=__doc__)
    parser.add_argument("--siblings-root",
                        help="siblings root for every source (sets ASSIST_SIBLINGS_ROOT)")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="present / missing / locked / stale per source")
    d.add_argument("--config", default=str(doctor.DEFAULT_CONFIG))
    d.add_argument("--root", help="siblings root (default ../ or $ASSIST_SIBLINGS_ROOT)")
    d.add_argument("--today", help="YYYY-MM-DD to judge staleness against (default today)")
    d.add_argument("--json", action="store_true", help="machine-readable output")
    d.add_argument(
        "--no-http", action="store_true", help="skip local HTTP servers, read the stores directly"
    )
    d.set_defaults(func=_doctor)

    r = sub.add_parser("run", help="stances → out/, journal, brief, Telegram (once a day)")
    r.add_argument("--today", help="YYYY-MM-DD run date (default today)")
    r.add_argument("--no-send", action="store_true", help="write everything, send nothing")
    r.set_defaults(func=_run)

    b = sub.add_parser("brief", help="print the brief for the current out/")
    b.add_argument("--send", action="store_true", help="also send the summary (once a day)")
    b.set_defaults(func=_brief)

    g = sub.add_parser("regime", help="layer 0: risk regime and dollar direction")
    g.add_argument("--today", help="YYYY-MM-DD, read point in time (default today)")
    g.add_argument("--json", action="store_true")
    g.add_argument("--check", action="store_true",
                   help="daily job: journal the regime and send Telegram only on a change")
    g.add_argument("--no-send", action="store_true",
                   help="with --check: compare only, write and send nothing")
    g.set_defaults(func=_regime)

    p = sub.add_parser("paper", help="paper track: IDN stances vs the IDR 60/40 benchmark")
    p.add_argument("--today", help="YYYY-MM-DD, mark up to this day (default today)")
    p.add_argument("--json", action="store_true", help="the full report as JSON")
    p.add_argument("--marks", action="store_true", help="with --json: include weekly marks")
    p.set_defaults(func=_paper)

    j = sub.add_parser("journal", help="decision journal: records per model, chain check")
    j.set_defaults(func=_journal)

    args = parser.parse_args(argv)
    if args.siblings_root:
        os.environ["ASSIST_SIBLINGS_ROOT"] = args.siblings_root
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
