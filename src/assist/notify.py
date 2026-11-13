"""Telegram notify (PLAN S6b): push the brief summary to a phone, never-fail and send-once.

The only outbound internet call this repo makes, and only from here. The rules are those of
idx-method's former paper daemon (`notify.py` / `paper/runner.py` before its 9a0ea38):

- **Nothing here raises.** The caller is the tail of a run that has already written its stance
  files and journal; a notifier that can take that down is worse than none. `send` returns a
  verdict dict, and every failure (dead network, revoked token, Telegram answering with an HTML
  outage page, an unwritable marker directory) becomes its `reason` and a log line.
- **Not configured is not a failure.** No credentials → `reason: "not configured"`, quietly.
- **Send-once per (kind, date).** A marker file `<state>/sent/<kind>_<date>.json` is written only
  after every part was accepted, so a second send of the same kind that day is skipped, while a
  failed send is retried on the next run instead of costing the day's message. `force` resends.

Credentials: `ASSIST_TELEGRAM_TOKEN` + `ASSIST_TELEGRAM_CHAT` from the environment (both, or
neither counts), else both from the repo's `.env` (S90: KEY=VALUE lines read as text, never
shell-evaluated, so a manual `assist run` finds what `launchd/job.sh` sources), else the macOS
Keychain item `investment-assist-telegram` (account = chat id,
password = bot token), else idx-method's former item `idx-method-telegram`, the same bot. The
token never enters a log line, a verdict or a repr.

Text goes out as HTML (`parse_mode=HTML`), wrapped in `<pre>` by default so an aligned table stays
aligned on a phone, split on line boundaries under Telegram's 4096-character cap.

The message text itself is built in `assist.messages` (phase R); with `pre=False, heads=True` a
line starting with `# ` goes out bold.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

__all__ = [
    "API",
    "KEYCHAIN_SERVICE",
    "LEGACY_KEYCHAIN_SERVICE",
    "LIMIT",
    "Credentials",
    "already_sent",
    "chunks",
    "credentials",
    "describe",
    "esc",
    "send",
    "state_dir",
    "status",
    "summary",
]

log = logging.getLogger("assist.notify")

API = "https://api.telegram.org"
KEYCHAIN_SERVICE = "investment-assist-telegram"
LEGACY_KEYCHAIN_SERVICE = "idx-method-telegram"
ENV_TOKEN = "ASSIST_TELEGRAM_TOKEN"
ENV_CHAT = "ASSIST_TELEGRAM_CHAT"
ENV_STATE = "ASSIST_NOTIFY_STATE"
# Telegram caps a message at 4096 characters; leave room for the <pre> wrapper and slack.
LIMIT = 3900
TIMEOUT = 20.0
REPO = Path(__file__).resolve().parents[2]
DOTENV = REPO / ".env"  # gitignored, chmod 600; the values never enter a log line
KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

Security = Callable[[list[str]], subprocess.CompletedProcess]


@dataclass(frozen=True)
class Credentials:
    chat: str
    token: str = field(repr=False)
    source: str = "env"

    def __str__(self) -> str:
        return f"Credentials(chat={self.chat!r}, source={self.source!r})"


# ---------------- credentials ----------------


def _security(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["security", *args], capture_output=True, text=True, timeout=30)


def _account(out: str) -> str | None:
    """The account out of `security find-generic-password` output (hex form first: a non-ASCII
    account prints both, and only the hex one is exact)."""
    m = re.search(r'"acct"<blob>=0x([0-9A-Fa-f]+)', out)
    if m:
        try:
            return bytes.fromhex(m.group(1)).decode("utf-8")
        except ValueError:
            pass
    m = re.search(r'"acct"<blob>="(.*)"', out)
    return m.group(1) if m else None


def _keychain(service: str, security: Security) -> tuple[str, str] | None:
    """(account, secret) for `service`, or None. Never raises."""
    try:
        found = security(["find-generic-password", "-s", service])
        if found.returncode != 0:
            return None
        acct = _account((found.stdout or "") + (found.stderr or ""))
        if not acct:
            return None
        got = security(["find-generic-password", "-s", service, "-a", acct, "-w"])
        if got.returncode != 0:
            return None
        secret = (got.stdout or "").rstrip("\n")
        return (acct, secret) if secret else None
    except Exception as e:  # a missing `security` is "not configured"
        log.debug("keychain %s unreadable: %s", service, type(e).__name__)
        return None


def _dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE pairs of a `.env` file (`export ` and matching quotes stripped, comments and
    other lines skipped), as plain text: nothing is expanded or run. {} when unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if not m or line.lstrip().startswith("#"):
            continue
        v = m.group(2)
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[m.group(1)] = v
    return out


def credentials(
    env: Mapping[str, str] | None = None,
    security: Security = _security,
    platform: str = sys.platform,
    dotenv: Path | None = None,
) -> Credentials | None:
    """Env first (both variables), then the repo's `.env` (both), then the Keychain on macOS.
    None when not configured."""
    env = os.environ if env is None else env
    token, chat = env.get(ENV_TOKEN, "").strip(), env.get(ENV_CHAT, "").strip()
    if token and chat:
        return Credentials(chat=chat, token=token, source="env")
    fileenv = _dotenv(DOTENV if dotenv is None else dotenv)
    token, chat = fileenv.get(ENV_TOKEN, "").strip(), fileenv.get(ENV_CHAT, "").strip()
    if token and chat:
        return Credentials(chat=chat, token=token, source="dotenv")
    if platform != "darwin":
        return None
    for service in (KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_SERVICE):
        item = _keychain(service, security)
        if item:
            return Credentials(chat=item[0], token=item[1], source=f"keychain:{service}")
    return None


def status(**kw: Any) -> dict:
    """Whether credentials resolve and from where. Never includes the token or chat id."""
    c = credentials(**kw)
    return {"configured": c is not None, "source": c.source if c else None}


# ---------------- send-once markers ----------------


def state_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get(ENV_STATE) or REPO / "data" / "notify")


def _marker(kind: str, day: date, root: Path | None) -> Path:
    return (root or state_dir()) / "sent" / f"{kind}_{day.isoformat()}.json"


def already_sent(kind: str, day: date, state_dir: Path | None = None) -> bool:
    try:
        return _marker(kind, day, state_dir).exists()
    except Exception:
        return False


def _latch(kind: str, day: date, root: Path | None, parts: int) -> None:
    path = _marker(kind, day, root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"kind": kind, "date": day.isoformat(), "parts": parts,
                                   "sent_at": datetime.now().isoformat(timespec="seconds")}))
        tmp.replace(path)
    except Exception as e:  # the message went out; only the latch is lost
        log.warning("telegram: sent, but could not write send-once marker %s: %s", path, e)


# ---------------- sending ----------------


def esc(s: object) -> str:
    """HTML-escape for parse_mode=HTML (only these three, per Telegram's docs)."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def chunks(text: str, limit: int = LIMIT) -> list[str]:
    """Split on line boundaries, never mid-line; a single over-long line is hard-cut."""
    out: list[str] = []
    cur: list[str] = []
    n = 0
    for line in str(text).split("\n"):
        while len(line) > limit:
            if cur:
                out.append("\n".join(cur))
                cur, n = [], 0
            out.append(line[:limit])
            line = line[limit:]
        if cur and n + len(line) + 1 > limit:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line)
        n += len(line) + 1
    if cur:
        out.append("\n".join(cur))
    return [c for c in out if c.strip()] or [""]


def _bold_heads(text: str) -> str:
    return "\n".join(f"<b>{esc(x[2:])}</b>" if x.startswith("# ") else esc(x)
                     for x in text.split("\n"))


def _redact(s: str, token: str) -> str:
    return s.replace(token, "<token>") if token else s


def _post(client: Any, creds: Credentials, body: str) -> tuple[bool, str]:
    """One sendMessage call → (ok, detail). Never raises."""
    url = f"{API}/bot{creds.token}/sendMessage"
    data = {"chat_id": creds.chat, "text": body, "parse_mode": "HTML",
            "disable_web_page_preview": "true"}
    try:
        r = client.post(url, data=data, timeout=TIMEOUT)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    try:
        payload = r.json()
    except Exception:  # an HTML outage page
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if r.status_code == 200 and payload.get("ok"):
        return True, "ok"
    # Telegram puts the useful half ("chat not found", "bot was blocked") in the body.
    return False, payload.get("description") or f"HTTP {r.status_code}"


def send(
    text: str,
    *,
    kind: str,
    day: date,
    creds: Credentials | None = None,
    client: Any = None,
    state_dir: Path | None = None,
    pre: bool = True,
    heads: bool = False,
    force: bool = False,
) -> dict:
    """Send `text` once per (kind, day). Never raises.

    Returns {"sent", "skipped", "parts", "reason"}: `skipped` is True only when the send-once
    marker already exists; `parts` counts the messages Telegram accepted. With `pre` off and
    `heads` on, a line starting with `# ` goes out bold, without the marker (phase R, T5).
    """
    token = creds.token if creds else ""
    try:
        if not KIND_RE.match(kind or ""):
            return _verdict(False, 0, f"bad kind {kind!r}")
        if not force and already_sent(kind, day, state_dir):
            log.info("telegram: %s %s already sent, skipped", kind, day)
            return {"sent": False, "skipped": True, "parts": 0, "reason": "already sent"}
        creds = creds or credentials()
        if creds is None:
            return _verdict(False, 0, "not configured")
        token = creds.token
        own = client is None
        http = httpx.Client(timeout=TIMEOUT) if own else client
        sent = 0
        try:
            for part in chunks(text, LIMIT - (len("<pre></pre>") if pre else 0)):
                body = (f"<pre>{esc(part)}</pre>" if pre
                        else _bold_heads(part) if heads else esc(part))
                ok, detail = _post(http, creds, body)
                if not ok:
                    reason = _redact(detail, token)
                    log.warning("telegram: %s %s NOT sent (%d parts ok): %s", kind, day, sent,
                                reason)
                    return _verdict(False, sent, reason)
                sent += 1
        finally:
            if own:
                http.close()
        _latch(kind, day, state_dir, sent)
        return _verdict(True, sent, "ok")
    except Exception as e:  # the belt to every brace above
        reason = _redact(f"{type(e).__name__}: {e}", token)
        log.warning("telegram: %s %s NOT sent: %s", kind, day, reason)
        return _verdict(False, 0, reason)


def _verdict(sent: bool, parts: int, reason: str) -> dict:
    return {"sent": sent, "skipped": False, "parts": parts, "reason": reason}


def describe(result: Mapping) -> str:
    """One line for a run log."""
    if result.get("sent"):
        n = result.get("parts", 1)
        return "telegram: sent" + ("" if n == 1 else f" ({n} messages)")
    if result.get("skipped"):
        return "telegram: already sent today, skipped"
    if result.get("reason") == "not configured":
        return f"telegram: not configured (set {ENV_TOKEN}/{ENV_CHAT} in the environment or " \
               f".env, or Keychain {KEYCHAIN_SERVICE})"
    return f"telegram: NOT sent ({result.get('reason')})"


# ---------------- message text ----------------


def summary(stances: Iterable[Mapping], *, regime: str | None, day: date) -> str:
    """A phone-width table of stance payloads (schema/stance.schema.json)."""
    lines = [f"investment-assist {day.isoformat()}", f"regime: {regime or 'unknown'}", ""]
    stale: set[str] = set()
    for s in sorted(stances, key=lambda s: (s.get("subject", ""), s.get("asset", ""))):
        score = s.get("score")
        score_s = f"{score:>3.0f}" if isinstance(score, (int, float)) else "  -"
        lines.append(f"{s.get('subject', '?'):<4} {s.get('asset', '?'):<11} "
                     f"{s.get('stance', '?'):<11} {score_s}")
        delta = (s.get("portfolio") or {}).get("delta")
        if delta:
            lines.append(f"     {delta}")
        stale.update(s.get("stale_inputs") or [])
    if stale:
        lines += ["", "stale: " + ", ".join(sorted(stale))]
    lines += ["", "Heuristic, not investment advice."]
    return "\n".join(lines)
