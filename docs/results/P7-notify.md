# P7-notify — results

`src/assist/notify.py` sends Telegram messages and is the repo's only outbound internet call. It follows the rules of idx-method's former paper daemon (`notify.py`, `keychain.py` and `paper/runner.py` at `9a0ea38^`):

- **A send never raises.** `send()` returns `{sent, skipped, parts, reason}`. A dead network, a Telegram 400 (its `description`, such as "chat not found", becomes the reason), an HTML outage page, an unwritable marker directory or any unexpected exception becomes a `reason` plus a WARNING log line on `assist.notify`. The bot token is redacted from every reason and log line, and `Credentials` hides it from `repr` and `str`.
- **Send-once per (kind, date).** The marker is `data/notify/sent/<kind>_<YYYY-MM-DD>.json`. `data/` is gitignored, and `$ASSIST_NOTIFY_STATE` overrides the location. The marker is written only after Telegram accepts every part, as the daemon latched `last_report_date`, so a failed send is retried on the next run. A second send of the same kind that day returns `skipped: true` without an HTTP call, and `force=True` resends. `kind` must match `[a-z0-9][a-z0-9_-]*` because it becomes part of a file name.
- **Missing credentials are not an error.** The result is `reason: "not configured"`, with nothing latched and nothing logged above INFO.
- **Message format:** HTML (`parse_mode=HTML`) wrapped in `<pre>` by default, split on line boundaries under 3,900 characters to stay inside Telegram's 4,096 limit.
- **Helpers:** `describe()` gives a one-line summary for the run log. `status()` returns `{configured, source}` and never includes the token or chat id. `summary(stances, regime=, day=)` builds a phone-width table from stance payloads, for F1 to send.

**Credential order:** `ASSIST_TELEGRAM_TOKEN` + `ASSIST_TELEGRAM_CHAT` (both must be set) → Keychain `investment-assist-telegram` → Keychain `idx-method-telegram`. In each Keychain item the account is the chat id and the password is the token, as in idx-method's layout.

## Tests

`tests/test_notify.py` has 26 tests. The HTTP call goes through `httpx.MockTransport` and the Keychain goes through a fake `security` runner. The full suite passes (377 passed, 1 skipped), and `ruff check .` is clean.

## Live check (2026-10-23, no message sent)

- `status()` → `{'configured': True, 'source': 'keychain:idx-method-telegram'}`. The token has the bot-token shape and the chat id is numeric; neither was printed.
- The environment has no `ASSIST_TELEGRAM_*` variables and the Keychain has no `investment-assist-telegram` item. Credentials resolve only through the legacy idx-method item, which holds the same bot.

## For later slices

- **F1:** call `notify.send(notify.summary(stances, regime=..., day=...), kind="brief", day=<run date>)`, then send the same call again and expect `skipped: true`. Run it from the main checkout so the marker lands in its `data/notify/`; a worktree has its own `data/`. The daily regime job can use `kind="regime"`.
- **Optional:** to stop depending on idx-method's item, store a dedicated one with `security add-generic-password -U -s investment-assist-telegram -a <chat id> -w`.
