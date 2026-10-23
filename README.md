# investment-assist

Reads the sibling fetcher repos in `../` (read-only) and turns their data into a stance and an
entry plan per country × asset class, for an IDR-based investor. It never fetches from the
internet and never writes into another repo; the only outbound call is the Telegram summary.

Heuristic context, **not investment advice**.

- Decision flow: [`CLAUDE.md`](CLAUDE.md), section *Investment decision flow*.
- Build plan and progress: [`PLAN.md`](PLAN.md). Phase A (layers 0, 1, 5) is wired.

## Use

```sh
uv sync
uv run assist doctor           # every source: present / missing / locked / stale
uv run assist run              # stances → out/, journal/, data/briefs/<day>.md, Telegram once a day
uv run assist run --no-send    # the same, without Telegram
uv run assist brief            # print the brief for the current out/ (--send: summary, once a day)
uv run assist regime           # layer 0 today: risk_on | neutral | risk_off, dollar direction
uv run assist journal          # decisions per model fingerprint, hash-chain check
```

Run from a git worktree with `--siblings-root /path/to/Projects` (or `ASSIST_SIBLINGS_ROOT`),
because a worktree's `../` is not the siblings root.

## Outputs (all gitignored)

| Path | What |
|---|---|
| `out/{SUBJECT}/{asset}.json` | one stance per in-scope subject × asset (`schema/stance.schema.json`); a rerun with unchanged inputs writes identical bytes, and out/ holds exactly the last run |
| `journal/decisions.jsonl`, `journal/models/` | append-only, hash-chained decisions, each with the model fingerprint |
| `data/briefs/<day>.md` | the Markdown brief, diffed against the previous day's snapshot |
| `data/snapshots/<day>/` | copy of out/ per run day, for the brief's "changes since last run" |
| `data/notify/sent/` | send-once markers (`brief_<day>.json`); `$ASSIST_NOTIFY_STATE` moves them |

Telegram credentials: `ASSIST_TELEGRAM_TOKEN` + `ASSIST_TELEGRAM_CHAT`, else the Keychain item
`investment-assist-telegram` (then `idx-method-telegram`). A failed send is logged, never raised,
and is retried on the next run.
