"""`assist` command line: doctor | status | run | rules | brief | regime | paper | journal |
industries | frameworks | flows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import httpx

from assist import alerts, brief, doctor, guide, journal, notify, paper, pipeline, status, web
from assist.candidates import holdings as holdings_mod
from assist.layers import regime as regime_layer
from assist.layers import undervalued
from assist.layers.types import DISCLAIMER

STATUS_HELP = ("local pages: stances, regime, signals, candidates, industries, portfolio, flows, "
               "paper, frameworks, journal, source health")


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
                g = res.idn.gates.get(asset)
                if g is not None:
                    print(f"    gate {g.line()}")
            og = res.idn.override_gate
            if og is not None:
                for asset in ("stocks", "bonds", "currency"):
                    print(f"  {og.line(asset)}")
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


def _fmt_verdict(v: dict | None) -> str:
    if v is None:
        return "none"
    r = v["rule"]
    return (f"{'passed' if v['passed'] else 'not passed'}: on {r['n_on']}, off {r['n_off']}, "
            f"t {r['t']:.2f}, p {v['p_value']:.3f}, control t {v['control_t']:.2f}"
            f" ({v['reason']})")


def _print_gate(doc: dict) -> None:
    c, s, d = doc["covers"], doc["sample"], doc["distance"]
    print(f"IDN {doc['asset']} rule gate: {doc['state']}  ({doc['rule_fingerprint'][:19]}…,"
          f" monitor since {doc['since']})")
    print(f"  history {c['first']} → {c['last']} ({c['months']} month ends, "
          f"{c['with_return']} with a {doc['params']['horizon']}-month return); window "
          f"{c['window_first']} → {c['window_last']}; calls "
          + ", ".join(f"{k} {n}" for k, n in sorted(doc["calls"].items())))
    if "historical" in s:
        h, hd = s["historical"], d["historical"]
        print(f"  historical windows: on {h['on']} / off {h['off']} / no_call {h['no_call']}"
              f" vs MIN_N {doc['params']['min_n']} (short on {hd['on']}, off {hd['off']})")
    lv = s["live"]
    print(f"  live windows: on {lv['on']} / off {lv['off']} (short on {d['live']['on']}, off "
          f"{d['live']['off']}; revocation needs on {d['revoke']['on']}, off "
          f"{d['revoke']['off']} more)")
    print(f"  historical verdict: {_fmt_verdict(doc['historical'])}")
    print(f"  live verdict: {_fmt_verdict(doc['live'])}")
    print(f"  effective: {_fmt_verdict(doc['verdict'])}")
    print(f"  why on: {doc['why']['on']}")
    print(f"  why off: {doc['why']['off']}")
    red = doc.get("reduce")
    if red is not None:  # P74: reduce (on) vs enter / hold (off), its own gate
        rh, rd = red["sample"].get("historical"), red["distance"].get("historical")
        hist = (f"historical on {rh['on']} / off {rh['off']} (short on {rd['on']}, off "
                f"{rd['off']})" if rh is not None else "no historical sample")
        print(f"  reduce side: {red['state']}: {hist}; live on {red['sample']['live']['on']} /"
              f" off {red['sample']['live']['off']}")
        print(f"  reduce effective: {_fmt_verdict(red['verdict'])}")
    missing: dict[str, int] = {}
    for n in doc["no_call"]:
        for m in n["missing"]:
            missing[m.split(":")[0]] = missing.get(m.split(":")[0], 0) + 1
    if missing:
        print("  no_call months by missing input: "
              + ", ".join(f"{k} {n}" for k, n in sorted(missing.items())))
    for line in doc["stale_inputs"]:
        print(f"  stale: {line}")


def _rules(args: argparse.Namespace) -> int:
    """P67: build or refresh out/rules/IDN-<asset>.json; --horizon / --variant add diagnostics
    under out/rules/diagnostics/ that never gate a stance."""
    from assist.eval import gate

    day = _today(args)
    paths = pipeline.Paths.default()
    src = pipeline.IdnSources.default()
    prices = pipeline.rule_prices(src, day)
    records = list(journal.Journal(paths.journal).read())
    rules_dir = paths.out / "rules"
    gates = gate.refresh(day, rules_dir, records=records, prices=prices, build=gate.live_build,
                         rebuild=args.rebuild)
    for g in gates.values():
        _print_gate(g.to_dict())
    if args.horizon is not None or args.variant:
        h = args.horizon or gate.HORIZON
        for a, g in gates.items():
            if g.rows is None or (args.variant == "valuation-only" and a != "stocks"):
                continue
            d = gate.diagnostic(a, g.rows, prices=prices[a], day=day, horizon=h,
                                variant=args.variant)
            name = f"IDN-{a}-h{h}" + (f"-{args.variant}" if args.variant else "") + ".json"
            out = rules_dir / "diagnostics" / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8")
            v, smp = d["verdict"], d["sample"]
            print(f"diagnostic IDN {a} horizon {h}"
                  + (f", {args.variant}" if args.variant else "")
                  + f" (never gates): window {d['window']}, on {smp['on']} / off {smp['off']}"
                  f" / no_call {smp['no_call']}; {_fmt_verdict(v)} → {out}")
    print(gates["bonds"].to_dict()["disclaimer"])
    return 0


def _fmt_side(t: dict) -> str:
    """One override gate side: state, sample, t, p, Holm, control t, CLI zeroed, distance."""
    h, hd = t["sample"].get("historical"), t["distance"].get("historical")
    head = f"{t['asset']} {t['side']}: {t['state']}"
    if h is None:
        return f"{head} (no history for this override fingerprint)"
    text = f"{head}: on {h['on']} / off {h['off']} / no_call {h['no_call']}"
    text += f" (short on {hd['on']}, off {hd['off']})"
    p = t["placebo"]
    if p is not None and p["rule"]["ok"]:
        hm = t["holm"]
        text += (f"; t {p['rule']['t']:.2f}, p {p['p_value']:.3f}, control t "
                 f"{p['control_t']:.2f}; Holm rank {hm['rank']}/{hm['m']} needs p ≤ "
                 f"{hm['threshold']:.4f} ({'ok' if hm['passed'] else 'no'})")
        z, zh = t["cli_zeroed"], t["cli_holm"]
        if z is not None and z["rule"]["ok"]:
            text += (f"; cli zeroed t {z['rule']['t']:.2f}, p {z['p_value']:.3f} "
                     f"({'ok' if z['passed'] and zh['passed'] else 'no'})")
        else:
            text += "; cli zeroed: insufficient sample"
    lv = t["sample"]["live"]
    return text + f"; live on {lv['on']} / off {lv['off']}"


def _print_override_gate(doc: dict) -> None:
    c = doc["covers"]
    n = sum(len(v) for v in doc["tests"].values())
    print(f"{doc['subject']} override gate ({doc['override_fingerprint'][:19]}…, monitor since "
          f"{doc['since']}): history {c['first']} → {c['last']} ({c['months']} month ends, "
          f"{c['complete']} complete from {c['complete_from']}); Holm over {n} tests")
    for sides in doc["tests"].values():
        for side in ("up", "down"):
            t = sides[side]
            win = t["window"]
            print(f"  {_fmt_side(t)}" + (f"; window {win[0]} → {win[1]}" if win else ""))
    passed = {a: s for a, s in doc["passed"].items() if s}
    print("  passed: " + (", ".join(f"{a} {'/'.join(s)}" for a, s in passed.items())
                          if passed else "none (no override may cross a band)"))
    for line in doc["stale_inputs"]:
        print(f"  stale: {line}")


def _overrides(args: argparse.Namespace) -> int:
    """P77: build or refresh out/overrides/<SUBJECT>.json (the layer-2 override gate)."""
    from assist import override_history
    from assist.eval import override_gate

    day = _today(args)
    paths = pipeline.Paths.default()
    records = list(journal.Journal(paths.journal).read())
    for subject in args.subject or override_gate.LIVE_SUBJECTS:
        g = override_gate.refresh(day, paths.out / "overrides", subject, records=records,
                                  build=override_history.live_build, rebuild=args.rebuild)
        _print_override_gate(g.to_dict())
    print(DISCLAIMER)
    return 0


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
        g = f.override_gates.get(m.subject)
        gate = "" if g is None else "; gate passed: " + (", ".join(
            f"{a} {'/'.join(sorted(g.passed_sides(a)))}" for a in ("stocks", "bonds", "currency")
            if g.passed_sides(a)) or "none")
        print(f"foreign overrides {m.subject}: {shifts}{gate}")
    print("  KOR, TWN: no layer-2 overrides (P28 covers USA, JPN, EMU, AUS, SGP); layer-1 score"
          " stands")
    foreign = [s for s in res.stances if s["subject"] in pipeline.FOREIGN
               and s["asset"] in pipeline.FOREIGN_ASSETS]
    held = [f"{s['subject']} {s['asset']} ({s['score']:.1f})" for s in foreign
            if (s.get("layer2") or {}).get("held")]
    crossed = [f"{s['subject']} {s['asset']} → {s['stance']}" for s in foreign
               if (s.get("layer2") or {}).get("crossed")]
    if held:
        print(f"  band held until that side passes its override gate: {', '.join(held)}")
    if crossed:
        print(f"  band crossed by a passed override side: {', '.join(crossed)}")
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
    g, _ = guide.load(paths.out)
    msg = pipeline.message(day=day, undervalued=undervalued.load_out(paths.out),
                           stances=loaded.stances, guide_payload=g,
                           holdings=holdings_mod.load(paths.out, "IDN"))
    result = notify.send(msg, kind="brief", day=day, state_dir=paths.notify, pre=False,
                         heads=True)
    print(notify.describe(result), file=sys.stderr)
    return 0


def _home_source(sources: pipeline.Sources):
    """The home regime's stores for the daily check (S54), None without IDN sources."""
    return pipeline.home_sources(sources.idn) if sources.idn is not None else None


def _regime_check(args: argparse.Namespace) -> int:
    """Daily job: Telegram when the regime, the dollar direction or the home (IDN) regime
    changed, then the change-only holding and data health alerts (S90)."""
    day = _today(args)
    sources = pipeline.Sources.default()
    paths = pipeline.Paths.default()
    code = 0
    try:
        _regime_change(args, day, sources, paths)
    except Exception as e:  # noqa: BLE001 - the alerts below still run; the job exits 1
        print(f"regime check failed: {type(e).__name__}: {e}")
        code = 1
    _alerts(args, day, sources, paths)
    return code


def _never_fail(name: str, fn, *a) -> list:
    if fn is None:
        return []
    try:
        return list(fn(*a))
    except Exception as e:  # noqa: BLE001 - a broken probe is no alert, not a failed job
        print(f"alerts: {name} unreadable ({type(e).__name__}: {e})")
        return []


def _alerts(args: argparse.Namespace, day: date, sources: pipeline.Sources,
            paths: pipeline.Paths) -> None:
    """S90: changed held names and data health, one message (kind `holdings`), send-once."""
    chk = alerts.daily_check(day, out_dir=paths.out, state_dir=paths.notify,
                             statuses=_never_fail("doctor", sources.doctor, day),
                             jobs=_never_fail("idx-method jobs", sources.idx_jobs, day),
                             send=not args.no_send)
    if chk.error:
        print(f"alerts: error ({chk.error}), nothing sent")
        return
    if chk.holdings_note:
        print(f"holdings: {chk.holdings_note}")
    if chk.text is None:
        print("alerts: no held name changed, no new data problem: nothing sent")
        return
    for line in chk.holdings:
        print(f"holdings: {line[len('Holdings: '):] if line.startswith('Holdings: ') else line}")
    for line in chk.health:
        print(f"health: {line}")
    if chk.notify is None:
        print("alerts: not sent (--no-send)")
    else:
        print("alerts " + notify.describe(chk.notify))
        if not chk.saved:
            print("alerts not saved: the next check retries the message")


def _regime_change(args: argparse.Namespace, day: date, sources: pipeline.Sources,
                   paths: pipeline.Paths) -> None:
    chk = pipeline.regime_check(day, paths=paths, source=sources.fred,
                                send=not args.no_send, home_source=_home_source(sources))
    reg = chk.regime
    print(f"regime check {day}: {reg.state}, dollar {reg.dollar}")
    for s in reg.stale_inputs:
        print(f"  stale: {s}")
    if chk.home is not None:
        h = chk.home
        print(f"home (IDN) regime: {h.state} ({h.points} points)"
              + (": " + "; ".join(h.drivers) if h.drivers else ""))
        for s in h.stale_inputs:
            print(f"  home stale: {s}")
    if not chk.available:
        print("regime unreadable (no FRED source): nothing compared, nothing sent")
        return
    prev = chk.previous
    if prev is None:
        print("no regime journalled yet: " + ("baseline journalled" if chk.journalled
                                              else "nothing written (--no-send)"))
        return
    print(f"last journalled {prev['as_of']}: {prev['state']}, dollar {prev['dollar']}"
          + (f", home {prev['home']}" if prev.get("home") else ""))
    if not chk.changed:
        print("unchanged: nothing sent")
        return
    for c in chk.changes():
        print(c)
    if chk.notify is None:
        print("telegram: not sent (--no-send)")
    else:
        print(notify.describe(chk.notify))
        if not chk.journalled:
            print("not journalled: the next check retries the message")


def _paper(args: argparse.Namespace) -> int:
    day = _today(args)
    rep = paper.paper_track(journal=journal.Journal(pipeline.Paths.default().journal), until=day)
    if args.json:
        print(json.dumps(rep.to_dict(marks=args.marks), indent=2, sort_keys=True))
        return 0
    print(f"paper track {day} (model allocation vs the IDR benchmark 48/32/20, legacy 60/40)")
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


def _pt(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:+.1f}pt"


def _frameworks(args: argparse.Namespace) -> int:
    """S94: the baseline board → out/frameworks/IDN.json (read-only on the stores)."""
    from assist import framework_board

    payload = framework_board.live(_today(args))
    path = framework_board.write(payload, pipeline.Paths.default().out)
    print(f"{path}: {len(payload['frameworks'])} entries, as of {payload['as_of']}")
    for e in payload["frameworks"]:
        print(f"  {e['name']} ({e['kind']}, gate {e['gate']['state']}): {e['status']}, "
              f"{e['starts']} start(s), {e['mean_picks'] or 0:.0f} held of "
              f"{e['mean_pool'] or 0:.0f} on average")
        for w in e["windows"]:
            if w["n_starts"]:
                print(f"    {w['window']:>2}: vs pool {_pt(w['excess_pool'])}, vs JCI "
                      f"{_pt(w['excess_jci'])}, total {_pt(w['total'])} (n_ind "
                      f"{w['n_independent']}, starts {w['n_starts']})")
        if e["survivorship"]:
            print(f"    survivorship: {e['survivorship']['note']}")
    for s in payload["skipped"]:
        print(f"  skipped {s['name']}: {s['reason']}")
    for line in payload["stale_inputs"]:
        print(f"  stale: {line}")
    print(payload["verdict_note"])
    print(DISCLAIMER)
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
                        "/industries[/<id>], /paper, /frameworks, /journal, /status (each with "
                        "a .json twin)")
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

    ru = sub.add_parser("rules", help="IDN rule gates → out/rules/IDN-<asset>.json (historical "
                                      "verdict, live monitor, state, distance to the gate)")
    ru.add_argument("--today", help="YYYY-MM-DD (default today)")
    ru.add_argument("--rebuild", action="store_true",
                    help="rerun every month end (about 19 min on the real stores)")
    ru.add_argument("--horizon", type=int,
                    help="diagnostic: the verdict on another horizon in months (never gates)")
    ru.add_argument("--variant", choices=("valuation-only",),
                    help="diagnostic: a variant of the stocks calls (never gates)")
    ru.set_defaults(func=_rules)

    ov = sub.add_parser("overrides", help="layer-2 override gates → out/overrides/<SUBJECT>.json "
                                          "(per asset and side: placebo, Holm, CLI zeroed, live)")
    ov.add_argument("--today", help="YYYY-MM-DD (default today)")
    ov.add_argument("--subject", action="append",
                    help="IDN, USA, JPN, EMU, AUS or SGP (repeatable; default every gated one)")
    ov.add_argument("--rebuild", action="store_true", help="replay every month end again")
    ov.set_defaults(func=_overrides)

    b = sub.add_parser("brief", help="print the brief for the current out/")
    b.add_argument("--send", action="store_true", help="also send the summary (once a day)")
    b.set_defaults(func=_brief)

    g = sub.add_parser("regime", help="layer 0: risk regime and dollar direction")
    g.add_argument("--today", help="YYYY-MM-DD, read point in time (default today)")
    g.add_argument("--json", action="store_true")
    g.add_argument("--check", action="store_true",
                   help="daily job: journal the regime, send Telegram only on a change, then "
                        "the change-only holding and data health alerts (S90)")
    g.add_argument("--no-send", action="store_true",
                   help="with --check: compare only, write and send nothing")
    g.set_defaults(func=_regime)

    p = sub.add_parser("paper", help="paper track: stances vs the IDR benchmark "
                                     "(48/32/20; legacy 60/40)")
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

    fw = sub.add_parser("frameworks", help="baseline board: each screen's replay picks vs JCI "
                                           "and pool → out/frameworks/IDN.json (not in run)")
    fw.add_argument("--today", help="YYYY-MM-DD build date (default today)")
    fw.set_defaults(func=_frameworks)

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
