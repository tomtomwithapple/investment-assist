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
