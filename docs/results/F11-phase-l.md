# F11-phase-l (PLAN S66): phase L fan-in, 2026-11-09

No weight, band, window, threshold, tilt, benchmark, ladder or phase K / phase L number changed.
Heuristic, not investment advice.

## Merge

- `phase-l` (tip `be07689`; S57–S65 and S61b) merged into `main` with `--no-ff`: `a8dd638`.
- `uv run pytest -q` on main: **1919 passed** (the worldbankscape contract test runs here; the
  worktree skipped it). `uv run ruff check .`: clean.
- Slice commits on `phase-l`:
  - S58 `963b8d2`, S61b `66d63aa`, S62 `c7477a0`, S59 `cc9dbf6`, S60 `0281d01`;
  - S63 `2137855`, S64 `8ac0bc9`, S61 `7f48c61`, S65 `be07689`.

## Live run (main checkout, real paths)

- **Before it:**
  - The 07:00 weekly job had already run and sent today's Telegram (`launchd/weekly.log`,
    exit 0, 07:07:09). The send-once marker `data/notify/sent/brief_2026-11-09.json` existed.
  - The journal held 503 records in 5 models, the newest `sha256:7c387d7b4148…` (F10).
  - `out/rules/` was on the phase K rule fingerprints (bonds `deb1f60c…`, stocks
    `d217e458…`), and `out/overrides/` did not exist.
- **`assist run --no-send`**, 14:55:46 → 15:34:23 WIB (38 m 37 s), exit 0. Telegram was not
  sent (`--no-send`) and no marker was touched.
  - The rule history rebuilt cold: 120 month ends in 1,916 s, since S61b's CPI fallback
    changed both rule fingerprints.
  - The override history (IDN plus one foreign replay) took about 70 s.
- **New journal segment** `sha256:b68e9bce177402343961dc0f8ad42a6a272732899c8cfa0408113a2656529006`
  (MODEL_VERSION 0.6.0, stance schema 1.3.0), 70 records. Journal: 573 records, 6 models,
  chain ok.
- **`out/rules/`** (new fingerprints, both **insufficient**, live 0 / 0 since 2026-11-09):

  | Rule | Fingerprint | Enter on / off | Reduce on / off |
  |---|---|---|---|
  | IDN bonds | `sha256:f9be0b944e8e…` | 3 / 11 | 1 / 13 |
  | IDN stocks | `sha256:457c6c858be4…` | 0 / 14 (6 no_call) | 7 / 7 (6 no_call) |

  The counts are as in F10: the CPI fallback moved no gate window. Both rules call `hold`.
- **`out/overrides/`** (new): every subject × asset × side **failed**, none insufficient, live
  0 / 0 since 2026-11-09. The verdict numbers are in P78 (IDN) and P83 (foreign).

  | Subject | Override fingerprint | Complete months | Passed |
  |---|---|---|---|
  | IDN | `sha256:708f4d9d9523…` | 112 from 2017-07 | none |
  | USA | `sha256:20a8da05aa16…` | 259 from 2005-04 | none |
  | JPN | `sha256:e6452ba0b183…` | 259 from 2005-04 | none |
  | EMU (DEU, FRA, ITA, ESP, NLD) | `sha256:680f44aea796…` | 259 from 2005-04 | none |
  | AUS | `sha256:e4d9a74eed70…` | 155 from 2013-12 | none |
  | SGP | `sha256:66f4d505f0ef…` | 247 from 2006-04 | none |

- **No override crossed a band.** Three stances stay held at the band (`layer2.held`):
  - FRA bonds 49.0 − 9 → 35.0;
  - ITA bonds 51.2 − 9 → 37.2 (EMU bonds −9);
  - USA bonds 47.6 − 3 → 39.6.

  Each would be underweight; each stays neutral because its down side failed.
- Global regime risk_off, dollar flat. Home (IDN) regime risk_off, 2 points (JCI −17.5% vs its
  20-day high).
- **IDN stances** (shifts stocks −5, bonds −4, currency +2, all inside their bands):
  - stocks neutral 43.5, laddered;
  - bonds neutral 49.0, laddered;
  - currency neutral 49.3.
- **49 stances:** 7 overweight, 36 neutral, 4 underweight, 2 avoid. The mix is the same as
  F10's.
- **Brief:** "Layer-2 override gate: no side passed (21 gated stance(s)); overrides move scores,
  never bands; held at the band: FRA bonds, ITA bonds, USA bonds".
- The local UI server (`assist status`, port 8791) was left running. It was started before the
  merge, so its `/signals` pages show the new gate column only after a restart.

## Docs

- PLAN.md:
  - STATUS (phase L done, what it delivered, Next up), phase table L 11 / 11, S66 ticked and its
    Progress row;
  - *Open data gaps*: dbnomics daily or month-end Bund 10Y; `usfin serve` reads slower than 5 s
    counting as locked (ops);
  - *Open questions* (added in S60/S65): the P17 bonds weights, the bonds weights across
    markets, and the AUS currency weights (evidence only, nothing changed).
- README.md: `assist overrides`, `out/overrides/`, and the gate line in the brief.
- CLAUDE.md: unchanged (only with the user's OK).

## Cleanup

The worktree `.claude/worktrees/agent-a4383be643f589a7d` and the branches `phase-l` and
`worktree-agent-a4383be643f589a7d` are removed (clean, merged into main). Nothing pushed.
