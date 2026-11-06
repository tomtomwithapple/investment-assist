# F8-ui-layers — results

PLAN S37, the phase H fan-in: the layer pages from S34–S36 and S38's `/flows` join the nav, the
overview and the stance page link to them, and every page is checked end to end and live.

## What changed

- **Nav** (`web.NAV`): Overview, Regime, Signals, Candidates, Industries, Portfolio, Flows,
  Paper, Journal, Status. `active_nav` already matched sub-paths (`/signals/IDN` → Signals,
  `/flows/2026-10` → Flows); tests now cover them.
- **Overview:** the regime/dollar banner has a "Regime inputs and history →" link to `/regime`.
- **Stance detail:** the Drivers card header links to `/signals/<SUBJECT>` only when
  `out/layers/<SUBJECT>.json` exists (`signals.subjects`, the same test the signals page uses for
  its 404), so commodities and a run without layer files show no link. The Portfolio card header
  links to `/portfolio`. Links are styled as a small muted `a.more` at the header's right.
- The "nav link comes with F8" route comments are gone.
- `assist status` help and its start-up line name the pages: stances, regime, signals,
  candidates, industries, portfolio, flows, paper, journal, source health. README's pages list
  names every route, and `assist flows` is in the command block.

## Tests

1571 passed, 1 skipped (worldbankscape checkout absent); ruff clean.

- `test_ui_e2e.py`: the tmp repo now also holds `out/layers/` (regime fixture, portfolio
  fixture, the IDN subject payload from `test_view_signals`) and `out/flows/` built from the S38
  financer fixture. Every page and its `.json` twin is 200 with the full nav and the disclaimer,
  including `/industries`, `/regime`, `/signals`, `/signals/IDN`, `/portfolio`, `/flows`,
  `/flows/2026-10`. These are 404: `/signals/XXX`, `/signals/XXX.json`, `/signals/regime`,
  `/signals/..%2Fregime` and `/flows/1999-01`. The cross-links resolve: the overview links
  `/regime`, IDN bonds links `/signals/IDN` and `/portfolio`, and USA bonds and GOLD link no
  signals page. The tree under the tmp repo is byte-identical afterwards.
- `test_web.py`: the NAV order; `active_nav` for the new routes and their sub-paths; `/flows` now
  has its active nav link (the old "no nav link" assertion is inverted).
- `test_view_stance.py`: a signals link only with a layer file, and only for that subject; the
  portfolio link. `test_view_overview.py`: the banner links `/regime`.
- `test_view_flows.py` and `test_view_signals.py` relied on there being no nav link: the first
  now asserts the link, and the second checks for "regime" and "portfolio" only in the page body
  after `</nav>`.

## Live (2026-11-06)

This used a gitignored copy of the S33 worktree's `out/` and of the repo's `journal/`, plus
`out/flows/` written into that copy by `assist flows` from financer (read-only, 12 months
2025-12 → 2026-11). It was served by `assist status --port 8797 --no-http` on 127.0.0.1.

| Page | HTML | JSON |
|---|---|---|
| `/` | 200, 13,396 B | 200, 18,260 B |
| `/regime` | 200, 16,819 | 200, 61,713 |
| `/signals` | 200, 6,486 | 200, 1,256 |
| `/signals/IDN` | 200, 105,222 | 200, 63,392 |
| `/signals/USA` | 200, 11,379 | 200, 6,306 |
| `/signals/EMU` | 200, 10,848 | 200, 5,677 |
| `/candidates` | 200, 15,391 | 200, 26,889 |
| `/candidates/IDN` | 200, 12,846 | 200, 19,262 |
| `/candidates/USA` | 200, 5,144 | 200, 4,068 |
| `/industries` | 200, 2,771 (notice) | 200, 115 |
| `/portfolio` | 200, 58,230 | 200, 43,597 |
| `/flows` | 200, 9,266 | 200, 2,839 |
| `/flows/2026-10` | 200, 15,521 | 200, 9,335 |
| `/stance/IDN/bonds` | 200, 5,515 | 200, 1,912 |
| `/stance/IDN/stocks` | 200, 9,327 | 200, 5,697 |
| `/stance/USA/stocks` | 200, 6,082 | 200, 2,483 |
| `/stance/GOLD/commodities` | 200, 4,653 | 200, 1,090 |
| `/paper` | 200, 5,294 | 200, 2,409 |
| `/journal` | 200, 3,298 | 200, 656 |
| `/status` | 200, 12,887 | 200, 12,471 |

`/signals/XXX`, `/signals/regime`, `/flows/1999-01` and `/nope` are 404.

The links work. IDN bonds links `/signals/IDN` and `/portfolio`. USA stocks links `/signals/USA`
and `/portfolio`. GOLD links `/portfolio` only. On `/flows/2026-10` the Flows tab is active.

- `/industries` shows its notice because the copied `out/industries/` holds only
  `IDN.replay.json`, with no `IDN.json`. It is still a 200 and never a 500.
- `/flows/2026-10` shows 10 matched (IDR 13,066,567) and 6 settlements unmatched. It shows 0
  named unmatched because `config/household.local.yaml` is gitignored and absent in this
  worktree. That is expected: no names means no named matches.

Screenshots (headless Chrome, `preferredColorScheme` light and dark) were taken of `/`,
`/stance/IDN/bonds` and `/regime`. The nav, the banner link and the card links read well in
both themes.

## Not done here

`plan.yaml`'s F8 note also says `assist run` should call `flows.write` (never-fail, a failure
is a stale input). That touches `pipeline.py`, which F8 does not own and the S37 brief does not
list. `/flows` therefore still depends on `assist flows` being run, and that is left open.
