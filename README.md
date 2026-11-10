# investment-assist

Reads the sibling fetcher repos in `../` (read-only) and turns their data into a stance and an
entry plan per country × asset class, for an IDR-based investor. It never fetches from the
internet and never writes into another repo; the only outbound call is the Telegram message.

Heuristic context, **not investment advice**. Every stance, brief and message says so and names
its sources.

- Decision flow: [`CLAUDE.md`](CLAUDE.md), section *Investment decision flow*.
- Build plan and progress: [`PLAN.md`](PLAN.md). Phases A–D and G–K are done (2026-11-09; K: the IDN rules gated on their point-in-time history, and an IDN home regime); E is 0 of 2 (S15 open, S31 built but its live verdict is open) and F 7 of 8 (S22 open).

## Quick start

```sh
./start.sh                  # uv sync, doctor, run if out/ is stale (else industries if missing), then the pages on port 8791 (this Mac and the LAN)
```

`start.sh` works from any directory. It stops with a message if `uv` is not installed
(https://docs.astral.sh/uv/). Then it:

1. runs `uv sync`;
2. runs `assist doctor` (informational, never stops the script);
3. runs `assist run --no-send` when `out/` holds no stance or its newest `as_of` is before
   today; a failed run is reported and the pages still start on whatever `out/` holds;
4. starts `assist status`, waits up to 30 s for it to answer (else shows its log and exits 1),
   opens the browser and keeps serving until Ctrl-C.

| Flag | Effect |
|---|---|
| `--run` / `--no-run` | always run / never run, whatever the age of `out/` |
| `--send` | the run sends its Telegram summary (`assist run`, still once a day) |
| `--no-open` | do not open the browser |
| `--port N` | serve on another port (default 8791, so it does not clash with a plain `assist status` on 8790) |
| `--host ADDR` | listen on ADDR instead of the default `0.0.0.0` (this Mac and the LAN, no login: anyone on the network can read the pages; the LAN URL is printed) |
| `--local` | listen on 127.0.0.1 only |
| `--install-jobs` | also run `sh launchd/install.sh` after the sync; without it `~/Library/LaunchAgents` is never touched |

## Use

```sh
uv sync
uv run assist doctor                  # every source: present / missing / locked / stale
uv run assist status                  # (--host 0.0.0.0 for the LAN) local pages on http://127.0.0.1:8790/ (read-only, Ctrl-C stops): / stance grid, /stance/<SUBJECT>/<asset>, /regime (layer 0 inputs and history), /signals[/<SUBJECT>] (layers 2-3), /candidates[/<MKT>], /industries[/<id>], /portfolio (layer 5), /flows[/<YYYY-MM>] (household transfers), /paper, /journal, /status source health + launchd jobs; each has a .json twin
uv run assist run                     # stances → out/, journal/, data/briefs/<day>.md, Telegram once a day
uv run assist run --no-send           # the same, without Telegram
uv run assist brief                   # print the brief for the current out/ (--send: summary, once a day)
uv run assist regime                  # layer 0 today: risk_on | neutral | risk_off, dollar direction
uv run assist regime --check          # daily job: journal it, Telegram only if it changed
uv run assist regime --check --no-send  # compare only; writes and sends nothing
uv run assist rules                   # IDN rule gates → out/rules/ (history verdict, live monitor, state, distance per side; --rebuild ~40 min)
uv run assist overrides               # layer-2 override gates → out/overrides/<SUBJECT>.json (up / down per asset: placebo, Holm, CLI zeroed, live; ~70 s; --subject S, --rebuild)
uv run assist paper                   # paper track vs the IDR 48/32/20 benchmark, 60/40 alongside (--json [--marks])
uv run assist journal                 # decisions per model fingerprint, hash-chain check
uv run assist flows                   # household transfers from financer → out/flows/<YYYY-MM>.json (for /flows)
```

Run from a git worktree with `--siblings-root /path/to/Projects` (or `ASSIST_SIBLINGS_ROOT`),
because a worktree's `../` is not the siblings root.

## What a run does

The home page of the local pages (`/`, "This week") and the top of the brief and the Telegram
message list this week's orders: what to sell and buy, how much, on which dates, at what price,
with a take-profit and a stop on each named buy (`out/guide.json`). The detail pages explain why.
Selling follows the investing principle: stocks that duplicate another holding's industry and
size go first, in full; the names the dividend screen keeps go last.

`assist run` reads every layer (0 regime, 1 worldbankscape score, 2 overrides, 3 market signals,
4 candidates, 5 portfolio), writes one stance per subject × asset, journals every decision with
the model fingerprint, writes the brief and sends one Telegram message a day. The message opens
with the disclaimer and "Paper only, not an order", then the undervalued IDN and USA lists and
every name sized to sell or buy per market and the held names to average down (a sized add on a
held name 5% or more below its average cost; cost basis changes no size), each market labelled with its stocks leg's split
into a rebalance to the 48/32/20 benchmark and the model's tilt; stances and regime stay in the
brief. A missing, locked
or stale store is reported and lowers confidence; only a missing layer 1 stops the run.

The brief, top to bottom:

1. the disclaimer;
2. **Data health**: the doctor, one line per missing, locked or stale source (or a table a
   stance needs that is absent);
3. the global regime, the home (IDN) regime line, the layer-2 override gate line (sides passed,
   bands crossed or held), the stance table (each delta split into rebalance to the benchmark
   and tilt) and the changes since the last run;
4. **Paper track**: the benchmark (48% JCI, 32% SBN leg, 20% US stocks in IDR), the old 60/40
   alongside (it still scores model segments from before S39), and one line per model
   fingerprint. It shows benchmark marks only until the journal has history, shows only the
   cumulative return until a series has 12 scored weeks, and counts a stale leg as a stale week,
   never filled in;
5. per-stance drivers, risks and flags, the watch list, stale inputs and sources.

Same inputs give the same bytes, so a rerun on the same day rewrites nothing.

## Outputs (all gitignored)

| Path | What |
|---|---|
| `out/{SUBJECT}/{asset}.json` | one stance per in-scope subject × asset (`schema/stance.schema.json`); a rerun with unchanged inputs writes identical bytes, and out/ holds exactly the last run |
| `out/rules/IDN-{stocks,bonds}.json` | each IDN rule's gate: historical verdict per side (enter, reduce), live journal monitor, state (passed, insufficient, failed, revoked), months covered, inputs missing; `assist run` rebuilds it when a month end has passed or a rule changed |
| `out/overrides/{IDN,USA,JPN,EMU,AUS,SGP}.json` | each subject's layer-2 override gate (phase L): per asset an up and a down side, its placebo verdict on the point-in-time override history (complete months only, IDR forward returns), Holm over the subject's tests, the CLI-zeroed check, the live monitor and state; a passed side lets that shift cross a band in its direction (EMU's reaches DEU, FRA, ITA, ESP, NLD); `assist run` rebuilds it when a month end has passed or the override changed |
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
(`/Users/tommy/Projects/investment-assist`) with `uv run`. They share a `lockf` lock, so
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
from the main checkout after pulling. The jobs need Telegram credentials to send: the login
Keychain item, or `ASSIST_TELEGRAM_TOKEN` and `ASSIST_TELEGRAM_CHAT` in the environment or in the
gitignored `.env` at the repo root (`chmod 600`), which `job.sh` loads before each run.

Run the jobs on **one machine only**: each machine keeps its own journal and paper track, and two
senders would deliver every message twice. Since 2026-11-06 that is this Mac (`/Users/tommy`,
installed with `ASSIST_REPO=/Users/tommy/Projects/investment-assist`); the Windows tasks below
are to be uninstalled.

On Windows, `schedule.ps1` registers the same two jobs in Task Scheduler
(`investment-assist-weekly` Monday 07:00, `investment-assist-regime` daily 07:05, so the check
runs after the weekly run instead of under a shared lock), with no console window, logging to
`%LOCALAPPDATA%\investment-assist\logs\`. Telegram there needs the two `ASSIST_TELEGRAM_*`
variables, since there is no Keychain.

```powershell
powershell -ExecutionPolicy Bypass -File schedule.ps1 install   # or -DryRun, status, run [-Regime], uninstall
```

## Data gaps the brief will flag

These are fetcher-side gaps. They are fixed in the sibling repo, never here (details in
`PLAN.md`, *Open data gaps*, and `docs/results/`). As of the 2026-11-07 doctor: 11 of 14
sources present, 1 stale (jquantster), 2 missing (satudatascape, openkrx).

- **The PHEI curve is short and has a hole.** idxscape's IGSYC history starts in October 2026
  and has a hole 2026-10-22 → 11-03 on this Mac, so both IDN rules propose a call but neither
  is applied (insufficient sample), and the paper weeks ending 10-23, 10-30 and 11-06 stay
  unscored. JCI reads idxscape `index_daily` since 2026-11-06, so the paper track scores its
  first week (10-16).
- **No IDN 10Y for 2025-01 → 2026-09.** The OECD proxy ends 2024-12 and IGSYC starts 2026-10,
  so both IDN rules' histories stop short of their gates (bonds "not yet"); asked of dbnomics
  (IMF IFS) and idxscape (DJPPR SUN auctions).
- **jquantster is on the J-Quants free plan.** TSE investor types are empty and daily bars end
  2026-08-14 (stale around 2026-11-22).
- **openkrx has no `data/parquet` on this Mac.** There is no KR or TW index valuation.
- **There are no USD/IDR forwards.** Hedged IDR edges use policy-rate carry instead.
- **idx-method's stock history is short and not adjusted.** It holds about 5 years of closes,
  about 4 of which are usable for drawdowns. P21's entry levels for
  momentum names at fresh 3-year highs are wrong (for example BSML: entry 21 against a price
  of 575). Do not use `entry_typical` for those names.
- **satudatascape has no store yet.**
