"""`assist` command line: doctor | status | run | brief | regime | paper | journal | industries |
flows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import httpx

from assist import brief, doctor, journal, notify, paper, pipeline, stance, status, web
from assist.layers import regime as regime_layer

STATUS_HELP = ("local pages: stances, regime, signals, candidates, industries, portfolio, flows, "
               "paper, journal, source health")


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


def _status(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else doctor.siblings_root(dict(os.environ))
    sources = doctor.load_sources(Path(args.config), root=root)
    repos = status.repo_dirs(sources, root)
    repo_of = {s.name: s.repo or s.name for s in sources}

    def build() -> status.Snapshot:
        client = None if args.no_http else httpx.Client(trust_env=False)
        try:
            statuses = doctor.run_doctor(sources, date.today(), http_client=client)
        finally:
            if client is not None:
                client.close()
        return status.Snapshot(datetime.now(), statuses, status.find_jobs(repos), repo_of)

    paths = pipeline.Paths.default()
    app = web.App(out_dir=paths.out, snapshots_dir=paths.snapshots, journal_path=paths.journal,
                  health=build)
    print(f"assist status on http://{args.host}:{args.port}/ ({STATUS_HELP}; "
          "read-only; Ctrl-C stops it)", flush=True)
    if args.host not in doctor.LOCAL_HOSTS:
        print(f"listening on {args.host}: anyone on the network can read these pages "
              "(no login)", file=sys.stderr, flush=True)
    try:
        web.serve(app, port=args.port, routes=status.ROUTES, host=args.host)
    except KeyboardInterrupt:
        pass
    except OSError as e:
        print(f"cannot listen on {args.host}:{args.port}: {e}", file=sys.stderr)
        return 1
    return 0


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
        for p in res.undervalued:
            _print_undervalued(p)
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


def _print_undervalued(p: dict) -> None:
    """S20: each style's verdict and names, the tilt's verdict, the budget, sizes and trims."""
    h = p["hurdle"]["required_pt"]
    sz = p["sizing"]
    print(f"undervalued {p['market']} (bars {p['bar_date']}, hurdle "
          f"{'n/a' if h is None else f'{h:.2f}%'}): tilt "
          f"{'passed' if p['tilt']['passed'] else 'failed'} ({p['tilt']['verdict']}); budget "
          f"IDR {sz['budget_idr']:,.0f}, unspent IDR {sz['unspent_idr']:,.0f}")
    for s in p["styles"]:
        head = "passed" if s["passed"] else "verdict failed"
        print(f"  {s['style']}: {head} ({s['verdict']}), pool {s['pool']}, "
              f"{len(s['rows'])} name(s), {len(s['dropped'])} dropped")
        for r in s["rows"]:
            size = f"add IDR {r['size']['idr']:,.0f}" if r["size"] else r["action"]
            print(f"    #{r['rank']} {r['symbol']:<5} margin {r['margin_pt']:+.2f}pt "
                  f"(net {r['net_margin_pt']:+.2f}pt); {size}")
        for d in s["dropped"]:
            print(f"    dropped {d['symbol']}: {d['reason']}")
    for t in sz["trims"]:
        print(f"  trim {t['symbol']} IDR {t['idr']:,.0f}: {t['reason']}")


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


def _industries(args: argparse.Namespace) -> int:
    """S30: write out/industries/IDN.json from idx-method's stored /comparison, nothing else."""
    from assist.candidates import peers

    day = _today(args)
    path, stale = pipeline.write_peers(day, peers.gather_live, pipeline.Paths.default().out)
    if path is None:
        print(stale[0] if stale else "peer comparison: nothing written", file=sys.stderr)
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    names = sum(i["n"] for i in payload["industries"])
    print(f"{path}: {len(payload['industries'])} industries, {names} names, "
          f"as of {payload['as_of']}")
    for line in stale:
        print(f"  stale: {line}")
    return 0


def _flows(args: argparse.Namespace) -> int:
    """S38: write out/flows/<YYYY-MM>.json and index.json from financer, read-only."""
    from assist import flows
    from assist.sources.base import SourceUnavailable
    from assist.sources.financer import FinancerSource

    out = Path(args.out) if args.out else pipeline.Paths.default().out
    names = flows.load_household(Path(args.household) if args.household else flows.HOUSEHOLD)
    try:
        index, months = flows.build_from(FinancerSource.from_config(), names, args.months)
    except SourceUnavailable as e:
        print(f"flows: nothing written: {e}", file=sys.stderr)
        return 1
    flows.write(index, months, out)
    print(f"{out / flows.OUT_DIR}: {len(months)} month(s), latest {index['latest']}, "
          f"as of {index['as_of']}; household names for {len(names)} owner(s)")
    for k, p in sorted(months.items()):
        t = p["totals"]
        print(f"  {k}: {t['transfers']['n']} matched (IDR {t['transfers']['amount']:,.2f}), "
              f"{t['unmatched_named']['n']} named unmatched, "
              f"{t['unmatched_settlements']['n']} settlement(s) unmatched")
    for line in index["stale_inputs"]:
        print(f"  stale: {line}")
    return 0


def _utf8_stdio() -> None:
    """Write UTF-8 even where the stream defaults to a legacy code page (Windows pipes, files and
    scheduled-job logs are cp1252, and the first → would be a UnicodeEncodeError)."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower()
        if hasattr(stream, "reconfigure") and encoding not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
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

    st = sub.add_parser("status", help=STATUS_HELP,
                        description=f"{STATUS_HELP}, on 127.0.0.1 unless --host, "
                        "read-only: / overview, /stance/<SUBJECT>/<asset>, /candidates[/<MKT>], "
                        "/industries[/<id>], /paper, /journal, /status (each with a .json twin)")
    st.add_argument("--port", type=int, default=status.DEFAULT_PORT,
                    help=f"port to listen on (default {status.DEFAULT_PORT})")
    st.add_argument("--host", default=status.HOST,
                    help=f"address to listen on (default {status.HOST}, this Mac only; "
                    "0.0.0.0 serves the LAN, with no login)")
    st.add_argument("--config", default=str(doctor.DEFAULT_CONFIG))
    st.add_argument("--root", help="siblings root (default ../ or $ASSIST_SIBLINGS_ROOT)")
    st.add_argument("--no-http", action="store_true",
                    help="skip local HTTP servers, read the stores directly")
    st.set_defaults(func=_status)

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

    ind = sub.add_parser("industries",
                         help="peer comparison per industry → out/industries/IDN.json")
    ind.add_argument("--today", help="YYYY-MM-DD build date (default today)")
    ind.set_defaults(func=_industries)

    fl = sub.add_parser("flows", help="household money flows → out/flows/<YYYY-MM>.json")
    fl.add_argument("--out", help="out/ directory to write flows/ into (default the repo's out/)")
    fl.add_argument("--household", help="owner names file (default config/household.local.yaml)")
    fl.add_argument("--months", type=int, default=12, help="latest months with data (default 12)")
    fl.set_defaults(func=_flows)

    args = parser.parse_args(argv)
    if args.siblings_root:
        os.environ["ASSIST_SIBLINGS_ROOT"] = args.siblings_root
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
