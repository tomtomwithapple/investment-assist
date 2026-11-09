# P73-home-pages (PLAN S54): the home (IDN) regime on the brief, /regime, Telegram and the daily check

Date: 2026-11-09. Heuristic, not investment advice. Display and alerting only: no stance, score
or number changes.

## What changed

- **Brief** (`brief.home_line`). A `- Home regime (IDN): <state>, <n> points (<drivers>)` line
  under *Global regime*, read from the IDN stocks or bonds stance's `home_regime`. On risk_off it
  adds "IDN stocks and bonds adds and trims laddered", and it lists any stale inputs. No block,
  no line. The golden brief changes only by that line (a test removes the line and compares
  against `expected.md`).
- **Telegram** (`pipeline.message`, `brief.home_message_line`). On a home risk_off, one line
  goes right after the header. On neutral or without the block, no line.
- **`/regime`** (`views/regime.py`). A *Home regime (IDN)* card shows:
  - the state chip, points (risk-off at ≥ 2; there is no home risk-on), drivers, what a
    risk-off does, and the −5pt shift as adopted or not;
  - the rule's numbers as written in the file, and the stale inputs;
  - the four inputs, each with its value, newest date, points (or "not counted", with a stale
    chip) and the 52-week Friday line.

  A file without `home` (schema 1.0.0, or a run with no IDN sources) shows one muted line, not
  a notice. The `.json` twin already carries the block.
- **Daily check** (`pipeline.regime_check(..., home_source=)`, `cli regime --check`). The check
  reads the home regime too and journals it as `home` in its `regime` record. `last_regime`
  returns the last journalled home state. A home state change counts as a change: one message
  holds every change ("Home regime (IDN): neutral → risk_off") plus `home:` driver lines,
  send-once per day as before. If the last record has no home state, the check journals a home
  baseline and sends nothing. An unreadable home regime, or one that read no store, is no home
  change. The CLI prints the home state, its points and drivers, and the last journalled home
  state.
- Tests (written first): 6 in `test_ops.py`, 4 in `test_brief.py`, 2 in `test_notify.py`, 4 in
  `test_view_regime.py`. The existing `last_regime` test now expects the `home` key. Full suite
  1811 passed, 1 skipped; ruff clean.

## Live (2026-11-09, on the S53 scratch run's `out/` and journal, `send=False`)

- Brief, *Global regime*: "Regime: risk_off · Dollar: flat · Home regime (IDN): risk_off,
  2 points (JCI -17.5% vs 20d high (2)); IDN stocks and bonds adds and trims laddered".
- Telegram: line 5 reads "Home regime (IDN) risk_off (2 points: JCI -17.5% vs 20d high (2)): IDN
  stocks and bonds adds and trims laddered". Nothing was sent.
- `/regime` returns 200 with no notice. The home card shows the four inputs (−17.45% on 11-05,
  2 points; z −0.72, 0; USD/IDR +1.15%, 0; SBN +0.45% on 11-04, 0), all counted, each with
  its line. The shift is shown as not adopted.
- Dry daily check: global risk_off, dollar flat; home risk_off, 2 points; previous record
  2026-11-09 with home risk_off; unchanged, so nothing would be sent.
