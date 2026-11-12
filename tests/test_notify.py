"""Telegram notify (PLAN S6b): credentials from env then Keychain, never-fail sends, a send-once
marker per (kind, date). The HTTP call is always a mock transport; nothing here reaches Telegram,
and the Keychain is replaced by a fake `security` runner."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import httpx

from assist import notify

D = date(2026, 10, 26)
TOKEN = "123456:SECRET-token"
CHAT = "987654"
CREDS = notify.Credentials(chat=CHAT, token=TOKEN, source="env")
FIXTURES = Path(__file__).parent / "fixtures" / "stance"


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_handler(log: list):
    def handle(request: httpx.Request) -> httpx.Response:
        log.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(log)}})

    return handle


def form(request: httpx.Request) -> dict:
    return dict(httpx.QueryParams(request.content.decode()))


# ---------------- credentials ----------------


def fake_security(items: dict[str, tuple[str, str]], calls: list | None = None):
    """A stand-in for `security`: items maps service -> (account, password)."""

    def run(args):
        if calls is not None:
            calls.append(list(args))
        service = args[args.index("-s") + 1]
        if service not in items:
            return subprocess.CompletedProcess(args, 44, "", "item not found")
        acct, pw = items[service]
        if "-w" in args:
            return subprocess.CompletedProcess(args, 0, pw + "\n", "")
        out = f'keychain: "login"\nattributes:\n    "acct"<blob>="{acct}"\n'
        return subprocess.CompletedProcess(args, 0, out, "")

    return run


def test_credentials_from_env_first():
    calls: list = []
    env = {"ASSIST_TELEGRAM_TOKEN": TOKEN, "ASSIST_TELEGRAM_CHAT": CHAT}
    c = notify.credentials(env=env, security=fake_security({}, calls))
    assert c == notify.Credentials(chat=CHAT, token=TOKEN, source="env")
    assert calls == []  # the Keychain is not asked when the env has both


def test_half_env_falls_back_to_keychain():
    env = {"ASSIST_TELEGRAM_TOKEN": TOKEN}
    sec = fake_security({notify.KEYCHAIN_SERVICE: ("111", "kc-token")})
    c = notify.credentials(env=env, security=sec, platform="darwin")
    assert c == notify.Credentials(chat="111", token="kc-token",
                                   source=f"keychain:{notify.KEYCHAIN_SERVICE}")


def test_keychain_falls_back_to_legacy_idx_method_item():
    sec = fake_security({"idx-method-telegram": ("222", "idx-token")})
    c = notify.credentials(env={}, security=sec, platform="darwin")
    assert c is not None
    assert (c.chat, c.token, c.source) == ("222", "idx-token", "keychain:idx-method-telegram")


def test_hex_account_is_decoded():
    def run(args):
        if "-w" in args:
            return subprocess.CompletedProcess(args, 0, "tok\n", "")
        out = '    "acct"<blob>=0x2D313030  "-100"\n'
        return subprocess.CompletedProcess(args, 0, out, "")

    c = notify.credentials(env={}, security=run, platform="darwin")
    assert c is not None and c.chat == "-100"


def test_no_credentials_is_none_not_error():
    assert notify.credentials(env={}, security=fake_security({}), platform="darwin") is None
    # off macOS the Keychain is never asked
    def boom(args):
        raise AssertionError("security called off darwin")

    assert notify.credentials(env={}, security=boom, platform="linux") is None


def test_keychain_exception_is_swallowed():
    def boom(args):
        raise OSError("security missing")

    assert notify.credentials(env={}, security=boom, platform="darwin") is None


def test_dotenv_is_read_after_the_env_and_before_the_keychain(tmp_path, caplog):
    """S90: a manual `assist run` from a shell finds the credentials job.sh sources from the
    repo's .env: KEY=VALUE lines, never shell-evaluated, values never logged."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("# telegram\n"
                      "export ASSIST_TELEGRAM_TOKEN='dotenv-token'\n"
                      'ASSIST_TELEGRAM_CHAT="555"\n'
                      "OTHER=$(touch pwned)\n"
                      "not a pair\n")
    calls: list = []
    sec = fake_security({notify.KEYCHAIN_SERVICE: ("111", "kc-token")}, calls)
    caplog.set_level("DEBUG", logger="assist.notify")
    c = notify.credentials(env={}, security=sec, platform="darwin", dotenv=dotenv)
    assert c == notify.Credentials(chat="555", token="dotenv-token", source="dotenv")
    assert calls == []  # the Keychain is not asked
    assert "dotenv-token" not in caplog.text and "dotenv-token" not in str(c)
    assert not (tmp_path / "pwned").exists()
    # the environment still wins
    env = {"ASSIST_TELEGRAM_TOKEN": TOKEN, "ASSIST_TELEGRAM_CHAT": CHAT}
    assert notify.credentials(env=env, security=sec, dotenv=dotenv).source == "env"
    # one half in the env, the other in .env: .env must hold both
    dotenv.write_text("ASSIST_TELEGRAM_TOKEN=dotenv-token\n")
    c = notify.credentials(env={}, security=sec, platform="darwin", dotenv=dotenv)
    assert c is not None and c.source == f"keychain:{notify.KEYCHAIN_SERVICE}"


def test_missing_or_unreadable_dotenv_is_not_configured(tmp_path):
    assert notify.credentials(env={}, security=fake_security({}), platform="darwin",
                              dotenv=tmp_path / "none") is None
    (tmp_path / "dir").mkdir()
    assert notify.credentials(env={}, security=fake_security({}), platform="linux",
                              dotenv=tmp_path / "dir") is None


def test_credentials_repr_hides_token():
    assert TOKEN not in repr(CREDS)
    assert TOKEN not in str(CREDS)


def test_status_never_shows_token():
    s = notify.status(env={"ASSIST_TELEGRAM_TOKEN": TOKEN, "ASSIST_TELEGRAM_CHAT": CHAT})
    assert s["configured"] is True and s["source"] == "env"
    assert TOKEN not in json.dumps(s)
    s = notify.status(env={}, security=fake_security({}), platform="darwin")
    assert s == {"configured": False, "source": None}


# ---------------- sending ----------------


def test_send_posts_html_to_bot_api(tmp_path):
    log: list = []
    r = notify.send("a <b> & c", kind="brief", day=D, creds=CREDS, client=client(ok_handler(log)),
                    state_dir=tmp_path)
    assert r == {"sent": True, "skipped": False, "parts": 1, "reason": "ok"}
    (req,) = log
    assert req.method == "POST"
    assert req.url.host == "api.telegram.org"
    assert req.url.path == f"/bot{TOKEN}/sendMessage"
    body = form(req)
    assert body["chat_id"] == CHAT
    assert body["parse_mode"] == "HTML"
    assert body["text"] == "<pre>a &lt;b&gt; &amp; c</pre>"


def test_send_plain_without_pre(tmp_path):
    log: list = []
    notify.send("x", kind="brief", day=D, creds=CREDS, client=client(ok_handler(log)),
                state_dir=tmp_path, pre=False)
    assert form(log[0])["text"] == "x"


def test_send_once_per_kind_and_day(tmp_path):
    log: list = []
    c = client(ok_handler(log))
    first = notify.send("hi", kind="brief", day=D, creds=CREDS, client=c, state_dir=tmp_path)
    second = notify.send("hi", kind="brief", day=D, creds=CREDS, client=c, state_dir=tmp_path)
    assert first["sent"] is True
    assert second == {"sent": False, "skipped": True, "parts": 0, "reason": "already sent"}
    assert len(log) == 1
    assert notify.already_sent("brief", D, state_dir=tmp_path)
    # another kind or another day is its own slot
    assert notify.send("hi", kind="regime", day=D, creds=CREDS, client=c,
                       state_dir=tmp_path)["sent"]
    assert notify.send("hi", kind="brief", day=date(2026, 10, 27), creds=CREDS, client=c,
                       state_dir=tmp_path)["sent"]
    assert len(log) == 3


def test_force_resends(tmp_path):
    log: list = []
    c = client(ok_handler(log))
    notify.send("hi", kind="brief", day=D, creds=CREDS, client=c, state_dir=tmp_path)
    r = notify.send("hi", kind="brief", day=D, creds=CREDS, client=c, state_dir=tmp_path,
                    force=True)
    assert r["sent"] and len(log) == 2


def test_failure_is_not_latched_so_it_retries(tmp_path):
    def down(request):
        raise httpx.ConnectError("no route to host")

    r = notify.send("hi", kind="brief", day=D, creds=CREDS, client=client(down),
                    state_dir=tmp_path)
    assert r["sent"] is False and r["skipped"] is False
    assert "ConnectError" in r["reason"]
    assert not notify.already_sent("brief", D, state_dir=tmp_path)
    log: list = []
    assert notify.send("hi", kind="brief", day=D, creds=CREDS, client=client(ok_handler(log)),
                       state_dir=tmp_path)["sent"]


def test_telegram_400_reports_description(tmp_path):
    def bad(request):
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    r = notify.send("hi", kind="brief", day=D, creds=CREDS, client=client(bad), state_dir=tmp_path)
    assert r["sent"] is False
    assert r["reason"] == "Bad Request: chat not found"


def test_html_outage_page_does_not_raise(tmp_path):
    def html(request):
        return httpx.Response(502, text="<html>bad gateway</html>")

    r = notify.send("hi", kind="brief", day=D, creds=CREDS, client=client(html), state_dir=tmp_path)
    assert r["sent"] is False and "502" in r["reason"]


def test_failure_reason_never_leaks_token(tmp_path, caplog):
    def down(request):
        raise httpx.ConnectError(f"failed for {request.url}")

    r = notify.send("hi", kind="brief", day=D, creds=CREDS, client=client(down),
                    state_dir=tmp_path)
    assert TOKEN not in r["reason"]
    assert TOKEN not in caplog.text


def test_failure_is_logged(tmp_path, caplog):
    def down(request):
        raise httpx.ConnectError("boom")

    with caplog.at_level("WARNING", logger="assist.notify"):
        notify.send("hi", kind="brief", day=D, creds=CREDS, client=client(down),
                    state_dir=tmp_path)
    assert "telegram" in caplog.text.lower()


def test_not_configured_is_quiet(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "credentials", lambda **kw: None)
    r = notify.send("hi", kind="brief", day=D, client=client(ok_handler([])), state_dir=tmp_path)
    assert r == {"sent": False, "skipped": False, "parts": 0, "reason": "not configured"}
    assert not notify.already_sent("brief", D, state_dir=tmp_path)


def test_unwritable_state_dir_still_sends_and_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    log: list = []
    r = notify.send("hi", kind="brief", day=D, creds=CREDS, client=client(ok_handler(log)),
                    state_dir=blocker / "sub")
    assert r["sent"] is True and len(log) == 1


def test_anything_unexpected_is_swallowed(tmp_path):
    class Broken:
        def post(self, *a, **kw):
            raise RuntimeError("unexpected")

    r = notify.send("hi", kind="brief", day=D, creds=CREDS, client=Broken(), state_dir=tmp_path)
    assert r["sent"] is False and "RuntimeError" in r["reason"]


def test_long_text_split_on_lines(tmp_path):
    log: list = []
    text = "\n".join(f"row {i:04d} " + "x" * 80 for i in range(120))
    r = notify.send(text, kind="brief", day=D, creds=CREDS, client=client(ok_handler(log)),
                    state_dir=tmp_path)
    assert r["sent"] and r["parts"] == len(log) > 1
    for req in log:
        assert len(form(req)["text"]) <= 4096
    joined = "\n".join(form(req)["text"][5:-6] for req in log)
    assert joined == text


def test_partial_failure_reports_parts_and_does_not_latch(tmp_path):
    n = {"i": 0}

    def flaky(request):
        n["i"] += 1
        if n["i"] == 2:
            return httpx.Response(429, json={"ok": False, "description": "Too Many Requests"})
        return httpx.Response(200, json={"ok": True})

    text = "\n".join("y" * 100 for _ in range(100))
    r = notify.send(text, kind="brief", day=D, creds=CREDS, client=client(flaky),
                    state_dir=tmp_path)
    assert r["sent"] is False and r["parts"] == 1
    assert r["reason"] == "Too Many Requests"
    assert not notify.already_sent("brief", D, state_dir=tmp_path)


# ---------------- helpers ----------------


def test_chunks():
    assert notify.chunks("a\nb", 100) == ["a\nb"]
    assert notify.chunks("aaaa\nbbbb", 6) == ["aaaa", "bbbb"]
    assert notify.chunks("x" * 10, 4) == ["xxxx", "xxxx", "xx"]
    assert notify.chunks("", 10) == [""]


def test_bad_kind_is_rejected_without_raising(tmp_path):
    r = notify.send("hi", kind="../evil", day=D, creds=CREDS, client=client(ok_handler([])),
                    state_dir=tmp_path)
    assert r["sent"] is False and "kind" in r["reason"]
    assert not any(tmp_path.parent.glob("evil*"))


def test_describe():
    assert notify.describe({"sent": True, "skipped": False, "parts": 1, "reason": "ok"}) \
        == "telegram: sent"
    assert "2 messages" in notify.describe({"sent": True, "skipped": False, "parts": 2,
                                            "reason": "ok"})
    assert "already sent" in notify.describe({"sent": False, "skipped": True, "parts": 0,
                                              "reason": "already sent"})
    assert "not configured" in notify.describe({"sent": False, "skipped": False, "parts": 0,
                                                "reason": "not configured"})
    assert "NOT sent" in notify.describe({"sent": False, "skipped": False, "parts": 0,
                                          "reason": "boom"})


def test_summary_from_sample_stances():
    stances = [json.loads(p.read_text()) for p in sorted(FIXTURES.glob("*.json"))]
    text = notify.summary(stances, regime="neutral", day=D)
    assert "2026-10-26" in text and "neutral" in text
    for s in stances:
        assert s["subject"] in text and s["stance"] in text
    assert "not investment advice" in text.lower()


# ---------------- paper header and rebalance vs tilt (S42) ----------------


def _leg(subject, asset, current, target, rebalance, tilt):
    return {"subject": subject, "asset": asset, "stance": "neutral",
            "portfolio": {"current_pct": current, "target_pct": target, "benchmark_pct": 48.0,
                          "delta": "x", "rebalance_pt": rebalance, "tilt_pt": tilt}}


LEGS = [_leg("IDN", "stocks", 96.9, 45.7, -51.2, 0.0), _leg("USA", "stocks", 0.0, 23.8, 19.0, 4.8),
        _leg("IDN", "bonds", 3.1, 30.5, 27.4, 0.0)]


def test_paper_line_names_the_benchmark():
    assert notify.PAPER_LINE == ("Paper only, not an order. Sizes rebalance to the 48/32/20 "
                                 "benchmark plus the model tilt; read the brief.")


def test_header_puts_the_paper_line_right_after_the_disclaimer():
    lines = notify.header(D)
    assert lines[0] == "investment-assist 2026-10-26"
    assert lines[1] == "Heuristic, not investment advice."
    assert lines[2] == notify.PAPER_LINE


def test_leg_line_splits_rebalance_and_tilt():
    assert notify.leg_line(LEGS, "IDN") == (
        "IDN stocks leg (paper): -51.2pt = -51.2pt rebalance to benchmark, +0.0pt tilt")
    assert notify.leg_line(LEGS, "USA") == (
        "USA stocks leg (paper): +23.8pt = +19.0pt rebalance to benchmark, +4.8pt tilt")
    assert notify.leg_line(LEGS, "JPN") is None
    no_holdings = [_leg("IDN", "stocks", None, 45.7, None, None)]
    assert notify.leg_line(no_holdings, "IDN") == (
        "IDN stocks leg (paper): rebalance vs tilt n/a (holdings unavailable)")


def test_message_carries_the_paper_header_and_leg_labels():
    from assist import pipeline

    idn = {"market": "IDN", "styles": [{"style": "garp", "passed": False, "rows": []}],
           "sizing": {"budget_idr": 0, "trims": [
               {"symbol": "PWON", "idr": 2.7e6, "reason": "trim in full: fails its screen"}]}}
    usa = {"market": "USA", "styles": [{"style": "garp", "passed": False, "rows": []}],
           "sizing": {"budget_idr": 13.2e6, "trims": []}}
    text = pipeline.message(day=D, brief_path=None, undervalued=[idn, usa], stances=LEGS)
    lines = text.splitlines()
    assert lines[1] == "Heuristic, not investment advice." and lines[2] == notify.PAPER_LINE
    i = lines.index("IDN to sell (1, IDR 2.7m):")
    assert lines[i - 1].startswith("IDN stocks leg (paper): -51.2pt = -51.2pt rebalance")
    j = lines.index("USA to sell: none")
    assert lines[j - 1].startswith("USA stocks leg (paper): +23.8pt = +19.0pt rebalance")
    assert text.endswith("not investment advice.")


# ---------------- home (IDN) regime line (S54, P73) ----------------


def _home_legs(state: str) -> list[dict]:
    import copy

    legs = copy.deepcopy(LEGS)
    for s in legs:
        if s["subject"] == "IDN":
            s["home_regime"] = {"state": state, "points": 2 if state == "risk_off" else 0,
                                "drivers": ["JCI -17.5% vs 20d high (2)"], "stale_inputs": []}
    return legs


def test_message_has_one_home_line_on_home_risk_off():
    from assist import pipeline

    text = pipeline.message(day=D, brief_path=None, stances=_home_legs("risk_off"))
    lines = text.splitlines()
    home = [x for x in lines if x.startswith("Home regime (IDN)")]
    assert home == ["Home regime (IDN) risk_off (2 points: JCI -17.5% vs 20d high (2)): IDN "
                    "stocks and bonds adds and trims laddered"]
    assert lines.index(home[0]) == 4  # right after the header


def test_message_has_no_home_line_when_neutral_or_absent():
    from assist import pipeline

    for legs in (_home_legs("neutral"), LEGS):
        text = pipeline.message(day=D, brief_path=None, stances=legs)
        assert "Home regime" not in text
