# investment-assist

Reads the sibling fetcher repos in `../` (read-only) and turns their data into a stance and an
entry plan per country × asset class, for an IDR-based investor. It never fetches from the
internet and never writes into another repo; the only outbound call is the Telegram message.

Heuristic context, **not investment advice**. Every stance, brief and message says so and names
its sources.

- Decision flow: [`CLAUDE.md`](CLAUDE.md), section *Investment decision flow*.
- Build plan and progress: [`PLAN.md`](PLAN.md). All phases (A–D, S0–S14) are built.

## Use

```sh
uv sync
uv run assist doctor                  # every source: present / missing / locked / stale
uv run assist status                  # local pages on http://127.0.0.1:8790/ (read-only, Ctrl-C stops): / stance grid, /stance/<SUBJECT>/<asset>, /candidates[/<MKT>], /paper, /journal, /status source health + launchd jobs; each has a .json twin
uv run assist run                     # stances → out/, journal/, data/briefs/<day>.md, Telegram once a day
uv run assist run --no-send           # the same, without Telegram
uv run assist brief                   # print the brief for the current out/ (--send: summary, once a day)
uv run assist regime                  # layer 0 today: risk_on | neutral | risk_off, dollar direction
uv run assist regime --check          # daily job: journal it, Telegram only if it changed
uv run assist regime --check --no-send  # compare only; writes and sends nothing
uv run assist paper                   # paper track vs the IDR 60/40 benchmark (--json [--marks])
uv run assist journal                 # decisions per model fingerprint, hash-chain check
```

Run from a git worktree with `--siblings-root /path/to/Projects` (or `ASSIST_SIBLINGS_ROOT`),
because a worktree's `../` is not the siblings root.

## What a run does

`assist run` reads every layer (0 regime, 1 worldbankscape score, 2 overrides, 3 market signals,
4 candidates, 5 portfolio), writes one stance per subject × asset, journals every decision with
the model fingerprint, writes the brief and sends one Telegram summary a day. A missing, locked
or stale store is reported and lowers confidence; only a missing layer 1 stops the run.

The brief, top to bottom:

1. the disclaimer;
2. **Data health**: the doctor, one line per missing, locked or stale source (or a table a
   stance needs that is absent);
3. the regime, the stance table and the changes since the last run;
4. **Paper track**: the 60/40 benchmark (60% JCI, 40% SBN leg) and one line per model
   fingerprint. It shows benchmark marks only until the journal has history, and a stale leg is
   counted as a stale week, never filled in;
5. per-stance drivers, risks and flags, the watch list, stale inputs and sources.

Same inputs give the same bytes, so a rerun on the same day rewrites nothing.

## Outputs (all gitignored)

| Path | What |
|---|---|
| `out/{SUBJECT}/{asset}.json` | one stance per in-scope subject × asset (`schema/stance.schema.json`); a rerun with unchanged inputs writes identical bytes, and out/ holds exactly the last run |
| `journal/decisions.jsonl`, `journal/models/` | append-only, hash-chained decisions, each with the model fingerprint; the daily regime check adds `regime` records |
| `data/briefs/<day>.md` | the Markdown brief, diffed against the previous day's snapshot |
| `data/snapshots/<day>/` | copy of out/ per run day, for the brief's "changes since last run" |
| `data/notify/sent/` | send-once markers (`brief_<day>.json`, `regime_<day>.json`); `$ASSIST_NOTIFY_STATE` moves them |
| `launchd/weekly.log`, `launchd/regime.log` | the scheduled jobs' output |

Telegram credentials: `ASSIST_TELEGRAM_TOKEN` + `ASSIST_TELEGRAM_CHAT`, else the Keychain item
`investment-assist-telegram` (then `idx-method-telegram`). A failed send is logged, never raised,
and is retried on the next run.

## Scheduled jobs (launchd)

| Label | When (this Mac's time zone, WIB) | Runs |
|---|---|---|
| `com.tommy.investment-assist.weekly` | Monday 07:00, before the IDX open | `assist run`: stances, journal, brief, Telegram summary |
| `com.tommy.investment-assist.regime` | every day 07:00 | `assist regime --check`: Telegram only when the regime or dollar direction changed |

How the daily check works:

- It compares today's regime with the last one journalled, whether that came from a weekly run or
  an earlier check.
- The first check ever only records a baseline and sends nothing.
- A changed regime is journalled once its message has gone out. If the send fails, nothing is
  journalled, so the next day's check retries.
- If FRED cannot be read at all, the check compares nothing and sends nothing.

Both jobs run `launchd/job.sh` from the main checkout
(`/Users/tomtomtomtom/Projects/investment-assist`) with `uv run`. They share a `lockf` lock, so
on Monday the two 07:00 jobs run one after the other instead of interleaving.

```sh
sh launchd/install.sh --dry-run     # print both rendered plists; writes nothing
sh launchd/install.sh               # render into ~/Library/LaunchAgents and bootstrap both
sh launchd/install.sh --uninstall   # boot both out and remove the plists
sh launchd/job.sh weekly            # run a job by hand, as launchd would (logs to launchd/<job>.log)
launchctl print gui/$(id -u)/com.tommy.investment-assist.weekly   # check one is loaded
```

The plists in git are templates. `install.sh` fills in the repo path (`ASSIST_REPO` overrides
the main checkout) and the absolute `uv` path, because launchd's PATH has no Homebrew. Install
from the main checkout after pulling. The jobs need Telegram credentials in the login Keychain,
or the environment, to send.

## Data gaps the brief will flag

These are fetcher-side gaps. They are fixed in the sibling repo, never here (details in
`PLAN.md`, *Open data gaps*, and `docs/results/`).

- **PHEI tables are missing on this Mac.** idxscape is at migration 8, so there is no IGSYC
  curve. Both IDN rules make no call, and the IDN 10Y falls back to dbnomics `idn.rate.long`,
  which ends 2024-12.
- **There is no JCI fetcher.** idx-method's index CSVs are frozen at 2026-09-30. The paper
  track's JCI leg and the stocks rule's verdict stop there.
- **jquantster is on the J-Quants free plan.** TSE investor types are empty and daily bars run
  about 12 weeks behind.
- **openkrx has no index Parquet on disk.** There is no KR or TW index valuation.
- **singstat's MAS series have been stale since 2026-10-07.** This lowers SGP confidence.
- **sec-edgar's FRED copy here has been stale since 2026-10-12.** Every regime input is stale,
  so every stance's confidence carries ×0.9⁵.
- **There are no USD/IDR forwards.** Hedged IDR edges use policy-rate carry instead.
- **idx-method's stock history is short and not adjusted.** It holds about 5 years of closes,
  about 4 of which are usable for drawdowns. P21's entry levels for
  momentum names at fresh 3-year highs are wrong (for example BSML: entry 21 against a price
  of 575). Do not use `entry_typical` for those names.
- **satudatascape has no store yet.**
