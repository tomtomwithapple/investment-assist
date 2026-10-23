# P6-brief — results

PLAN S6a. `src/assist/brief.py` renders the Markdown brief from stance payloads only (the
`schema/stance.schema.json` contract). It reads no store, and this slice does no live run: per
its notes, the sample below is rendered from the fixtures.

**API (for P20-pipeline)**
- `load_out(out_dir) -> Loaded(stances, problems)`: reads every `out/{SUBJECT}/*.json` and
  validates each one against the schema. It sorts home (IDN) first, then by subject, then by asset
  (stocks, bonds, currency, commodities). A file that is not JSON or fails the schema is skipped
  and listed in `problems`, never raised. A missing `out/` gives an empty result. Directories
  whose names are not subject codes (such as `_snapshots/`) are ignored.
- `save_snapshot(out_dir, snapshots_dir, as_of)`: copies the stance files to
  `<snapshots_dir>/<as_of>/` and replaces that day's copy if one exists.
- `previous_snapshot(snapshots_dir, before)`: returns the newest `YYYY-MM-DD` dated strictly
  before `before`.
- `build_brief(out_dir, snapshots_dir)`: loads `out/` and diffs it against the newest snapshot
  older than the stances' `as_of`, so today's own snapshot is never treated as "previous".
  Call order in the pipeline is: write `out/` → `build_brief` → `save_snapshot`.
- `diff(previous, current)` reports these changes:
  - the regime or dollar (taken as the most common value across payloads)
  - the model fingerprint ("the record segments here")
  - per stance: the stance, the score (moves of at least 1 pt), the entry style, the target
    weight, and stale inputs added or cleared
  - new and dropped stances
- `render(current, previous=None, problems=(), previous_as_of=None)` produces the brief. It reads
  no clock, so the same inputs always give the same bytes.

**Contents of the brief**
- The disclaimer at the top and in the footer.
- The global regime and dollar direction. When payloads disagree, they are shown as "mixed" with
  the subjects behind each value.
- A short model fingerprint and the stance table. Pipes in cells are escaped.
- Changes since the last run.
- Per-stance details: drivers, risks and flags, printed as given, so later layers need no change
  here.
- A merged, de-duplicated watch list and the stale inputs, each with the stances it affects.
- *Problems*, shown only when there are any.
- Source attribution: a full list, plus a repeat in the footer.

**Tests:** 20 in `tests/test_brief.py`, including a golden file, `tests/fixtures/brief/expected.md`
(to regenerate it, delete the file and rerun). The previous-run fixture is
`tests/fixtures/brief/previous/` (IDN bonds neutral 55 in a risk_off regime, IDN stocks
unchanged, JPN stocks later dropped). Full suite: 371 passed, 1 skipped; ruff is clean.

**For later slices**
- Telegram (P7) can send a summary of this brief, or the whole Markdown.
- Nothing here sends, writes `out/` or journals.

## Sample brief (fixtures: tests/fixtures/stance/ vs tests/fixtures/brief/previous/)

````markdown
# Investment brief 2026-10-13

> Heuristic, not investment advice. Context for an IDR-based investor, built from 3 stance payload(s); every source is listed at the end.

## Global regime

- Regime: **neutral**
- Dollar: mixed, **flat** (IDN bonds); **up** (IDN stocks, USA bonds)
- Model: `sha256:3f2a9c0d1e4b`

## Stances

| Subject | Asset | Stance | Score | Layer 1 | Conf. | Entry | Now → target | Delta |
|---|---|---|---:|---:|---:|---|---|---|
| IDN | stocks | neutral | 52 | 55.5 | 0.61 | lump | 30% → 30% | hold |
| IDN | bonds | overweight | 68 | 58 | 0.74 | ladder 3×10d | 8% → 15% | +7pt over 3 tranches |
| USA | bonds | underweight | 41 | 44 | 0.55 | none | n/a → 0% | unknown: holdings unavailable |

## Changes since last run

Compared with 2026-10-06.

- Regime: risk_off → neutral
- IDN bonds: stance neutral → overweight; score 55 → 68; target 8% → 15%
- USA bonds: new (underweight, score 41)
- JPN stocks: dropped (was neutral)

## Details

### IDN stocks: neutral, score 52

**Drivers**

- macro score 55.5
- IDX foreign flow -Rp1.1T/4w

**Risks**

- JCI index series frozen at 2026-09-30

**Flags**

- warn `stale_index`: JCI daily series frozen at 2026-09-30

### IDN bonds: overweight, score 68

**Drivers**

- real yield 3.1% (82nd pct)
- foreign SBN +Rp4.2T/4w

**Risks**

- USD/IDR at 6m high

### USA bonds: underweight, score 41

**Drivers**

- 10Y real yield 1.9%
- term premium rising

**Risks**

- IDR-unhedged return depends on USD/IDR

## Watch

- BI meeting 2026-10-22 (IDN stocks, IDN bonds)
- US CPI 2026-10-15 (IDN bonds, USA bonds)

## Stale inputs

- financer (locked): USA bonds
- idx-method jkse_daily.csv: IDN stocks

## Sources

- bisfetcher
- financer
- idxscape
- kseistat
- sec-edgar FRED
- worldbankscape

---

_Heuristic, not investment advice. Sources: bisfetcher, financer, idxscape, kseistat, sec-edgar FRED, worldbankscape._
````
