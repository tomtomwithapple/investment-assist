# F13-phase-m (PLAN S71): phase M fan-in, 2026-11-10

No weight, band, window, threshold, tilt, benchmark, ladder, cap or phase K / phase L / S15 number
changed. Heuristic, not investment advice.

## Merge

- `phase-m` (tip `6855d28`; S67–S70) merged into `main` with `--no-ff`: `bc595b9`. Not pushed.
- `uv run pytest -q` on main: **2001 passed**. `uv run ruff check .`: clean.
- Slice commits: S67 `2850ae8`, S69 `60a42b5`, S68 `9d272ea`, S70 `6855d28`; the three choices
  `7637f0b`.

## Live run (main checkout, real paths)

- **`assist run`**, 11:37:42 → 11:44:38 WIB (6 m 56 s), exit 0.
- **Telegram was not sent**: the run reported "telegram: not configured" (this shell has no
  `ASSIST_TELEGRAM_TOKEN` / `ASSIST_TELEGRAM_CHAT` and could not read the Keychain item). No
  `brief_2026-11-10` marker was written, so Monday's weekly job is unaffected. The first message
  with the new block will be the weekly job's on 2026-11-16.
- **New journal segment** `sha256:aa9e0c60fe9cd2f7b93cc82b7ba4c45e769bca2809f1fa91da37c0c3dd3e30ca`,
  70 records. Journal: 574 → 644 records, 7 → 8 models.
- **`out/candidates/IDN.json`** (schema 1.1.0, bars 2026-11-05, regime risk_off, IDN stocks
  96.9% against a 48.0% target, budget 0): 67 held names, 46 stop at gate 1, 20 at gate 2
  (not kept by a passing screen), BMRI (−15.2%) at gate 4 (over the 5% per-name cap). **No
  average down, funded or unfunded**, as S68's read-only check found. One row (BMRI, `hold`).
- **`out/candidates/USA.json`** (schema 1.1.0): nothing held, an empty `average_down` block.
- **Brief** (`data/briefs/2026-11-10.md`) and the Telegram text the run built: "IDN to average
  down: none: 21 of 67 held names are 5% or more below cost (20 not kept by a passing screen, 1
  no room under the caps)". USA gets no line.
- The other stale inputs are the standing ones (openkrx and satudatascape missing, ausdata
  curve last 2026-10-28, the foreign valuation gaps, idx-method's `comparison_industries`).

## What phase M leaves

- Cost basis is in layer 5 and on every held row; it changes no size.
- The average-down label exists and is journalled; nothing qualifies while IDN stocks are over
  their target and BMRI is over the per-name cap.
- Gate 3 (entry status) is context. Its placebo needs 10 non-overlapping 12-month windows and
  has 1; rerun `uv run python -m assist.eval.dip_gate` as the history grows (about one window a
  year).

## Docs

PLAN.md (S71, Progress rows, STATUS), README.md (*What a run does*).
CLAUDE.md is untouched.
