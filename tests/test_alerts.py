"""PLAN S90 (P108-change-alerts): the daily 07:00 check's change-only holding alerts and data
health block. Telegram is always a mock transport; the holding records are built in memory with
`holdings.build` and edited, idx-method's job logs are temp files, and the doctor is a list of
`SourceStatus` made here. Nothing reads a store or the network."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from assist import alerts, cli, doctor, notify, pipeline
from assist.candidates import holdings as hd
from assist.candidates.dividend_value import DividendData
from assist.sources.idxmethod_series import Bar, Fundamentals

D = date.fromisoformat
RUN = D("2026-11-16")
DAY = D("2026-11-17")
FP = "sha256:" + "b" * 64
FP2 = "sha256:" + "c" * 64
CREDS = notify.Credentials(chat="987654", token="123456:SECRET-token", source="env")
BANK = {"car": 20.0, "npl_gross": 2.0, "npl_cov": 200.0, "ldr": 90.0, "roe": 15.0,
        "free_float": 40.0, "med_value_60d": 5e10, "price": 4000.0, "vol_1y": 0.3,
        "days_traded_60": 60}


# ---------------- fakes ----------------


def _judged(sym: str, price: float = 3000.0) -> dict:
    bar = RUN - timedelta(days=3)
    period = D("2026-06-30")
    data = DividendData(
        bars={sym: [Bar(bar, price, price * 10)]},
        quarters={sym: [Fundamentals(period, period + timedelta(days=120), 6000.0, 25000.0, 0.0,
                                     5000.0, 5000.0, None, None, None, None)]},
        dividends={sym: [{"ex": f"{y}-04-10", "value": 200.0, "ccy": "CURRENCY_IDR"}
                         for y in range(2021, 2027)]},
        sectors={sym: "Keuangan"})
    return hd.judge_inputs(sym, {**BANK, "price": price}, data, bar, hurdle_pt=13.74)


def payload(syms=("BBNI", "BMRI", "TLKM"), *, day=RUN, fp=FP, problems=()) -> dict:
    """A schema-valid out/holdings/IDN.json: every name a passing bank below its fair price
    (about 3,484), action hold."""
    c = {"market": "IDN", "as_of": day.isoformat(), "bar_date": day.isoformat(),
         "hurdle": {"required_pt": 13.74, "drivers": []}, "tilt": {"sectors": []},
         "diversification": {"names": []}, "sizing": {"trims": []},
         "average_down": {"names": [{"symbol": s, "price": 3000.0} for s in syms]},
         "data_problems": list(problems)}
    p = hd.build(c, {s: _judged(s) for s in syms}, day=day, fingerprint=fp,
                 holdings={s: 4e6 for s in syms})
    return json.loads(json.dumps(p))


def rec(p: dict, sym: str) -> dict:
    return next(r for r in p["holdings"] if r["symbol"] == sym)


def write(out: Path, p: dict) -> None:
    assert not list(hd.validator().iter_errors(p)), "fixture off the schema"
    hd.write(p, out)


def thesis_sell(p: dict, sym: str, gate="cut", cause="new_filing") -> dict:
    r = rec(p, sym)
    r["acted"]["thesis"] |= {"status": "fail", "gate": gate, "severity": "hard", "acts": True}
    r["acted"] |= {"action": "sell_all", "cause": cause, "changed": ["thesis"]}
    r["inputs"]["report_period"] = "2026-09-30"
    return p


def take_profit(p: dict, sym: str, at=3380.0) -> dict:
    r = rec(p, sym)
    r["acted"]["valuation"] |= {"state": "fired", "take_profit": at}
    r["acted"] |= {"action": "trim_to_half", "cause": "price_cross", "changed": ["valuation"]}
    return p


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "out"


@pytest.fixture
def state(tmp_path: Path) -> Path:
    return tmp_path / "notify"


@pytest.fixture
def telegram():
    log: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        log.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(log)}})

    return log, httpx.Client(transport=httpx.MockTransport(handle))


def text_of(req: httpx.Request) -> str:
    return dict(httpx.QueryParams(req.content.decode()))["text"]


def check(out, state, telegram=None, day=DAY, statuses=(), jobs=(), send=True):
    # no telegram fixture: a transport that refuses, never the real credentials
    client = telegram[1] if telegram is not None else httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"ok": False})))
    kw = {"creds": CREDS, "client": client}
    return alerts.daily_check(day, out_dir=out, state_dir=state, statuses=list(statuses),
                              jobs=list(jobs), send=send, notify_kw=kw)


# ---------------- holdings: baseline, changes, silence ----------------


def test_first_record_sets_a_baseline_in_one_line_not_67_alerts(out, state, telegram):
    write(out, payload())
    chk = check(out, state, telegram)
    assert chk.baseline and chk.notify["sent"]
    assert len(telegram[0]) == 1
    msg = text_of(telegram[0][0])
    assert "baseline set: 3 held names as of 2026-11-16" in msg
    assert "BBNI" not in msg  # no per-name line on the baseline
    assert notify.already_sent("holdings", DAY, state)


def test_nothing_changed_is_silent(out, state, telegram):
    write(out, payload())
    check(out, state, telegram, day=DAY)
    chk = check(out, state, telegram, day=DAY + timedelta(days=1))
    assert chk.text is None and chk.notify is None
    assert len(telegram[0]) == 1  # only the baseline went out


def test_only_changed_names_are_sent_with_question_and_cause(out, state, telegram):
    write(out, payload())
    check(out, state, telegram, day=DAY)
    p = take_profit(thesis_sell(payload(day=RUN + timedelta(days=7)), "BBNI"), "BMRI")
    write(out, p)
    chk = check(out, state, telegram, day=DAY + timedelta(days=7))
    assert chk.notify["sent"]
    msg = text_of(telegram[0][-1])
    assert ("BBNI: hold → sell all — thesis: pass → fail hard (cut); cause: new filing. "
            "Thesis sell.") in msg
    assert ("BMRI: hold → trim to half — valuation: below fair → take-profit fired; "
            "cause: price crossing. Take-profit reached at 3,380.") in msg
    assert "TLKM" not in msg  # unchanged: not listed
    # the next day reads the same record: silent
    assert check(out, state, telegram, day=DAY + timedelta(days=8)).text is None


def test_a_change_with_no_cause_on_the_record_takes_it_from_the_fingerprint(out, state):
    """Records changed twice between two checks: today's record carries no cause, so the
    alert derives it against the last sent snapshot (here: another model)."""
    alerts.save_snapshot(state, alerts.snapshot(payload()))
    p = thesis_sell(payload(day=RUN + timedelta(days=7), fp=FP2), "BBNI", cause=None)
    rec(p, "BBNI")["acted"]["changed"] = []
    rec(p, "BBNI")["cause"] = None
    write(out, p)
    lines = alerts.holding_lines(p, alerts.load_snapshot(state))
    assert any(ln.startswith("BBNI: hold → sell all") and "cause: rule version" in ln
               for ln in lines)


def test_review_price_reached_is_listed(out, state, telegram):
    p = payload()
    rec(p, "TLKM")["valuation"]["review_price"] = 2800.0
    write(out, p)
    check(out, state, telegram)
    p2 = payload(day=RUN + timedelta(days=7))
    rec(p2, "TLKM")["valuation"]["price"] = 2750.0
    write(out, p2)
    check(out, state, telegram, day=DAY + timedelta(days=7))
    msg = text_of(telegram[0][-1])
    assert "TLKM: review price 2,800 reached (price 2,750): a review, never a sell." in msg


def test_names_bought_and_sold_are_one_line_each(out, state, telegram):
    write(out, payload())
    check(out, state, telegram)
    write(out, payload(("BBNI", "BMRI", "ASII"), day=RUN + timedelta(days=7)))
    check(out, state, telegram, day=DAY + timedelta(days=7))
    msg = text_of(telegram[0][-1])
    assert "Now held: ASII." in msg and "No longer held: TLKM." in msg


def test_a_failed_send_saves_nothing_so_the_next_check_retries(out, state):
    write(out, payload())

    def fail(request):
        return httpx.Response(502, text="<html>bad gateway</html>")

    refuse = httpx.Client(transport=httpx.MockTransport(fail))
    bad = alerts.daily_check(DAY, out_dir=out, state_dir=state, statuses=[], jobs=[],
                             notify_kw={"creds": CREDS, "client": refuse})
    assert not bad.notify["sent"] and alerts.load_snapshot(state) is None
    log: list = []
    ok = httpx.Client(transport=httpx.MockTransport(
        lambda r: (log.append(r), httpx.Response(200, json={"ok": True}))[1]))
    again = alerts.daily_check(DAY, out_dir=out, state_dir=state, statuses=[], jobs=[],
                               notify_kw={"creds": CREDS, "client": ok})
    assert again.baseline and again.notify["sent"] and len(log) == 1


def test_no_send_is_a_dry_check_that_writes_nothing(out, state):
    write(out, payload())
    chk = check(out, state, send=False)
    assert chk.baseline and "baseline set" in chk.text and chk.notify is None
    assert not state.exists()


def test_no_holding_record_is_no_holdings_section(out, state, telegram):
    chk = check(out, state, telegram)
    assert chk.text is None and chk.holdings_note == "no out/holdings/IDN.json yet"


def test_paper_line_while_act_on_verdicts_is_off(out, state, telegram):
    write(out, payload())
    check(out, state, telegram)
    assert "Paper: acted verdicts move no order yet (ACT_ON_VERDICTS off)." in \
        text_of(telegram[0][0])


# ---------------- data and source health ----------------


def _stale() -> doctor.SourceStatus:
    return doctor.SourceStatus(
        "idxscape", "duckdb", "/x/i.duckdb", "stale", newest=D("2026-11-10"),
        probes=[doctor.ProbeResult("stock_summary", "stale", D("2026-11-10"), 7, 3)])


def test_health_block_lists_data_problems_doctor_and_idx_method_jobs(out, state, telegram):
    write(out, payload(problems=["idx-method factors: price is null for 959 of 959 names"]))
    job = alerts.Problem("idx-method:open:network", "idx-method open 2026-11-12 09:00: failed "
                                                    "(rc 1): network error")
    chk = check(out, state, telegram, statuses=[_stale()], jobs=[job])
    msg = text_of(telegram[0][0])
    assert "Data health:" in msg
    assert "- run 2026-11-16 held for data: IDN: idx-method factors: price is null" in msg
    assert "- idxscape: stale, newest 2026-11-10 (stock_summary 7d/3d)" in msg
    assert "- idx-method open 2026-11-12 09:00: failed (rc 1): network error" in msg
    assert chk.health


def test_a_persistent_problem_is_not_repeated_until_it_changes_or_a_week_passes(
        out, state, telegram):
    write(out, payload())
    check(out, state, telegram, statuses=[_stale()])  # baseline + health
    assert check(out, state, telegram, day=DAY + timedelta(days=1),
                 statuses=[_stale()]).text is None
    # the age moves (8d/3d) but the problem is the same: still silent
    later = _stale()
    later.probes[0].age_days = 8
    assert check(out, state, telegram, day=DAY + timedelta(days=2), statuses=[later]).text \
        is None
    # a new problem: the block goes out again, with every current problem
    job = alerts.Problem("idx-method:backfill:killed", "idx-method backfill: killed at its cap")
    chk = check(out, state, telegram, day=DAY + timedelta(days=3), statuses=[later], jobs=[job])
    assert "idxscape: stale" in chk.text and "killed at its cap" in chk.text
    # then a week of the same set: a reminder
    assert check(out, state, telegram, day=DAY + timedelta(days=9), statuses=[later],
                 jobs=[job]).text is None
    rem = check(out, state, telegram, day=DAY + timedelta(days=10), statuses=[later], jobs=[job])
    assert "reminder" in rem.text and "since 2026-11-20" in rem.text


def test_cleared_problems_send_one_all_clear(out, state, telegram):
    write(out, payload())
    check(out, state, telegram, statuses=[_stale()])
    chk = check(out, state, telegram, day=DAY + timedelta(days=1), statuses=[])
    assert "Data health: all clear again" in chk.text
    assert check(out, state, telegram, day=DAY + timedelta(days=2)).text is None


def test_held_for_data_in_the_guide_is_a_problem(out, state):
    (out).mkdir(parents=True)
    (out / "guide.json").write_text(json.dumps({"as_of": "2026-11-16",
                                                "held_for_data": ["IDN: pool 0"]}))
    probs = alerts.data_problems(out)
    assert [p.text for p in probs] == ["run 2026-11-16 held for data: IDN: pool 0"]


# ---------------- idx-method job logs ----------------

OPEN_DNS = """=== 2026-11-11 09:00:04 +0700 opening snapshot 09:00 ===
done in 826.5s, 0 failures, run 27 in /x/stockbiter.db
=== done, rc=0 ===
=== 2026-11-12 09:00:05 +0700 opening snapshot 09:00 ===

== Stockbit session
   no working session (could not reach Stockbit (URLError: <urlopen error [Errno 8] \
nodename nor servname provided, or not known>) — a network problem)
no working Stockbit session — nothing fetched; recover from the repo root with: ./run.sh login
=== done, rc=1 ===
"""
BACKFILL_KILLED = """=== 2026-11-11 17:00:04 +0700 backfill refresh ===
  quarterly: 1000/1010 (1822s)
/usr/bin/python3 factors_pull.py was killed after 1800s
factors_pull.py failed
=== done, rc=1 ===
"""
BACKFILL_HUNG = """=== 2026-11-12 17:00:05 +0700 backfill refresh ===
  quarterly: 100/1010 (1383s)
"""
DAILY_OK = """=== 2026-11-12 17:30:01 +0700 daily ===
== Done
=== done, rc=0 ===
"""


def logs(tmp_path: Path, **jobs: str) -> Path:
    root = tmp_path / "idx-method"
    d = root / "store" / "data" / "archive"
    d.mkdir(parents=True)
    for job, text in jobs.items():
        (d / f"{job}.log").write_text(text)
    return root


def test_idx_method_dns_failure_is_reported(tmp_path):
    root = logs(tmp_path, open=OPEN_DNS, daily=DAILY_OK)
    probs = alerts.idxmethod_jobs(root, now=datetime(2026, 11, 13, 7, 0))
    assert [p.text for p in probs] == [
        "idx-method open 2026-11-12 09:00: failed (rc 1): network error, could not reach "
        "Stockbit (DNS); no Stockbit session. Next: in idx-method, ./run.sh session."]


def test_idx_method_kill_at_the_cap_and_a_run_with_no_result_are_reported(tmp_path):
    root = logs(tmp_path, backfill=BACKFILL_KILLED)
    probs = alerts.idxmethod_jobs(root, now=datetime(2026, 11, 12, 7, 0))
    assert [p.text for p in probs] == [
        "idx-method backfill 2026-11-11 17:00: failed (rc 1): factors_pull.py was killed after "
        "1800s; factors_pull.py failed. Next: usually cleared by the next run."]
    root2 = logs(tmp_path / "b", backfill=BACKFILL_HUNG)
    hung = alerts.idxmethod_jobs(root2, now=datetime(2026, 11, 13, 7, 0))
    assert [p.text for p in hung] == [
        "idx-method backfill 2026-11-12 17:00: no result reported (killed or still running). "
        "Next: usually cleared by the next run."]
    # still inside its window: not a problem yet
    assert alerts.idxmethod_jobs(root2, now=datetime(2026, 11, 12, 17, 30)) == []


def test_idx_method_problem_keys_ignore_counts_and_dates(tmp_path):
    a = alerts.idxmethod_jobs(logs(tmp_path / "a", backfill=BACKFILL_KILLED),
                              now=datetime(2026, 11, 12, 7, 0))
    b = alerts.idxmethod_jobs(logs(tmp_path / "b", backfill=BACKFILL_KILLED.replace(
        "2026-11-11", "2026-11-12").replace("1800s", "1900s")), now=datetime(2026, 11, 13, 7, 0))
    assert [p.key for p in a] == [p.key for p in b]


def test_idx_method_old_or_missing_logs_are_no_problem(tmp_path):
    root = logs(tmp_path, open=OPEN_DNS)
    assert alerts.idxmethod_jobs(root, now=datetime(2026, 11, 20, 7, 0)) == []
    assert alerts.idxmethod_jobs(tmp_path / "nowhere", now=datetime(2026, 11, 13)) == []


# ---------------- never fails ----------------


def test_daily_check_never_raises(out, state, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(alerts, "holding_lines", boom)
    write(out, payload())
    chk = check(out, state)
    assert chk.notify is None and "disk on fire" in chk.error


# ---------------- the CLI daily check ----------------


def test_cli_regime_check_prints_the_alert_and_sends_nothing_with_no_send(
        tmp_path, monkeypatch, capsys):
    from test_ops import FakeFred

    paths = pipeline.Paths.under(tmp_path / "repo")
    write(paths.out, payload())
    monkeypatch.setattr(pipeline.Paths, "default", classmethod(lambda cls: paths))
    fake = pipeline.Sources(worldbankscape=None, fred=FakeFred(), financer=None,
                            doctor=lambda day: [_stale()])
    monkeypatch.setattr(pipeline.Sources, "default", classmethod(lambda cls: fake))
    assert cli.main(["regime", "--check", "--no-send", "--today", DAY.isoformat()]) == 0
    printed = capsys.readouterr().out
    assert "holdings: baseline set: 3 held names as of 2026-11-16" in printed
    assert "idxscape: stale" in printed and "morning: not sent (--no-send)" in printed
    assert not paths.notify.exists()



CLOSE_400 = """=== 2026-11-12 16:30:01 +0700 close ===
  orderbook: 836 stored, 0 failed
done in 1512s; 10 endpoint(s) stored nothing: fundachart_metrics, running_trade, \
trade_book_chart, broker_activity
endpoints_pull.py: some endpoints stored nothing — see the 'endpoints' row in pulls
=== done, rc=1 ===
"""
BACKFILL_FAILURES = """=== 2026-11-12 17:00:05 +0700 backfill refresh ===
done in 1833s, 18 failures
factors_pull.py failed
=== done, rc=1 ===
"""


def test_idx_method_reasons_are_short_and_skip_zero_failure_lines(tmp_path):
    root = logs(tmp_path, close=CLOSE_400, backfill=BACKFILL_FAILURES)
    probs = alerts.idxmethod_jobs(root, now=datetime(2026, 11, 13, 7, 0))
    assert [p.text for p in probs] == [
        "idx-method close 2026-11-12 16:30: failed (rc 1): 10 endpoint(s) stored nothing "
        "(fundachart_metrics, running_trade, trade_book_chart, ...). Next: usually cleared by "
        "the next run.",
        "idx-method backfill 2026-11-12 17:00: failed (rc 1): 18 failures; factors_pull.py "
        "failed. Next: usually cleared by the next run."]


# ---------------- known gaps muted, next steps (phase R, T4) ----------------


def test_accepted_problems_are_muted_until_their_key_changes(tmp_path):
    known = alerts.Problem("doctor:openkrx:missing:", "openkrx: missing")
    new = alerts.Problem("doctor:idxscape:stale:index_daily", "idxscape: stale")
    chk = alerts.prepare(DAY, out_dir=tmp_path / "out", state_dir=tmp_path / "state",
                         jobs=[known], accepted={"doctor:openkrx:missing:"})
    assert chk.health == []
    chk = alerts.prepare(DAY, out_dir=tmp_path / "out", state_dir=tmp_path / "state",
                         jobs=[known, new], accepted={"doctor:openkrx:missing:"})
    assert chk.health == ["Data health:", "- idxscape: stale"]
    changed = alerts.Problem("doctor:openkrx:failing:", "openkrx: failing")
    chk = alerts.prepare(DAY, out_dir=tmp_path / "out", state_dir=tmp_path / "state",
                         jobs=[changed], accepted={"doctor:openkrx:missing:"})
    assert chk.health == ["Data health:", "- openkrx: failing"]


def test_accepted_keys_come_from_config(tmp_path):
    cfg = tmp_path / "alerts.yaml"
    cfg.write_text("accepted:\n  - 'doctor:openkrx:missing:'\n"
                   "  - 'doctor:satudatascape:missing:'\n")
    assert alerts.accepted_keys(cfg) == {"doctor:openkrx:missing:",
                                          "doctor:satudatascape:missing:"}
    assert alerts.accepted_keys(tmp_path / "none.yaml") == set()
    assert "doctor:jquantster:stale:investor_types" in alerts.accepted_keys()


def test_idx_method_failures_carry_a_next_step(tmp_path):
    root = tmp_path / "idx"
    log = root / "store/data/archive"
    log.mkdir(parents=True)
    (log / "close.log").write_text(CLOSE_400)
    (log / "backfill.log").write_text(BACKFILL_FAILURES)
    (log / "open.log").write_text(
        "=== 2026-11-12 09:00:01 +0700 open ===\nURLError: nodename nor servname provided\n"
        "no working Stockbit session\n=== done, rc=1 ===\n")
    probs = alerts.idxmethod_jobs(root, now=datetime(2026, 11, 12, 20, 0))
    text = {p.key.split(":")[1]: p.text for p in probs}
    assert text["open"].endswith("Next: in idx-method, ./run.sh session.")
    assert text["close"].endswith("Next: usually cleared by the next run.")
    assert text["backfill"].endswith("Next: usually cleared by the next run.")
