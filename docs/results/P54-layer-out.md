# P54-layer-out — results

PLAN S33: `assist run` writes each layer's structured result to `out/layers/` so the phase H
pages (S34–S36) can show layers 0, 2, 3 and 5 without reading a store. Live run 2026-11-06,
read-only, `--no-send` (`uv run assist --siblings-root /Users/tommy/Projects run --no-send`
from a worktree), 3 m 32 s wall, most of it the existing layers.

## What is written

| File | Holds | Schema |
|---|---|---|
| `out/layers/regime.json` | state, dollar, drivers, risk-off/on points, rule constants; every input of `layers.regime` (5 counted, 4 candidates) with value, newest date, vote (+1/+2 off, −1 on, 0), direction, label and a 52-week line (each Friday: the series' last point and the input as `regime.inputs` computes it) | `schema/layers/regime.schema.json` |
| `out/layers/<SUBJECT>.json` | IDN and P28's USA, JPN, EMU (with `members`), AUS, SGP: layer-2 components (name, source, series id, change, direction, last point, detail, weights), per asset shift / raw / cap / capped / reason, foreign IDR terms and gaps; IDN also layer-3 signals with tally, and the chart windows | `schema/layers/subject.schema.json` |
| `out/layers/portfolio.json` | layer 5: buckets with IDR and %, by owner, every account's rolled statement (account masked to its last 4 characters, holdings with their bucket, `unheld`), unmapped, statement checks, notes; each stance's stance, score, current/target/delta and entry | `schema/layers/portfolio.schema.json` |

Every file: `schema_version` 1.0.0, `kind`, `as_of` (run day), `model_fingerprint`, `sources`,
`stale_inputs`, `disclaimer`. Sorted keys, 1-space indent; a same-day rerun writes the same bytes.

## How

- `src/assist/layers_out.py` (new) serialises what `pipeline.gather` built. `pipeline` now keeps
  the regime `Inputs` (it calls `regime.read_inputs` + `classify`, which is what
  `regime.regime` does), the `Portfolio` and the statements (`build_portfolio` over
  `financer.statements()`, as `current_weights` does), and calls `write_layers` right after
  `write_out` when `Sources.layers_out` is set. `Sources.default()` sets it; the default field
  is False so the fixture runs of the existing e2e tests (which list every file in `out/`) are
  unchanged.
- New reads, all read-only through the existing adapters: FRED (core + candidate series, 1 year
  + 140 days, vintage = run day), idxscape (IDX net foreign IDR/USD and JISDOR over 150 days,
  `carried_forward()`, SBN non-resident 1 year), `idxmethod.jci()` 1 year, `PheiSource.curve`
  on/before the run day and on/before 4 weeks before the newest curve day.
- Failures: each chart read is guarded on its own (`chart <name>: <store> (missing)` or
  `chart <name> failed: <Type>: <msg>` in the file's `stale_inputs`, the chart null); a builder
  that raises, or a payload the schema rejects, writes a stub with `error` and the common fields.
  `write_layers` never raises; files from an earlier run that this run did not write are removed.

## Tests

- `tests/test_layers_out.py` (17): three kinds of file written and schema-valid with the common
  fields; off unless `layers_out`; stances, brief and journal kinds identical with and without
  it; rerun byte-identical; old subject files removed; regime inputs, votes, points and the
  weekly line (Fridays, level and 13-week change); history read with the run day's vintage;
  FRED down → stale and no history; IDN components/shift/cap/raw/signals serialised exactly;
  chart windows on the fixture store (flows with a JISDOR gap left null, JISDOR with a
  carried-forward day and the gap listed, JCI, IGSYC today and 4 weeks back, SBN); a chart read
  that raises → stale input; IDN stores missing → file still written; foreign markets each get
  a file (EMU with members); builder bug → stub; portfolio buckets, owners, masked accounts,
  stance targets; financer missing → stale.
- Fixture: `tests/fixtures/layers/extra.sql` on top of the idxscape flows, PHEI and index
  fixtures (two JISDOR days, one carried forward; an earlier IGSYC curve without a 10Y point).
- Red first (import error), then green. Full suite **1449 passed, 1 skipped** (baseline 1432);
  ruff clean.

## Live (2026-11-06)

| File | Size | Values |
|---|---:|---|
| `regime.json` | 44,764 B | neutral, dollar flat; points off 1 (real yield 2.64%), on 0; 9 inputs (5 counted), 52 weekly points each 2025-11-14 → 2026-11-06; VIX 16.61 (11-04), HY OAS +0.57/13w, dollar +1.64%/13w, NFCI −0.459; candidate STLFSI4 −0.52 would vote risk-on (not counted); no stale inputs |
| `IDN.json` | 50,641 B | 5 components (growth 0, CLI −1, inflation +1, trade +1, BI rate +1) → stocks −5, bonds −4, currency +2 (none capped); 5 signals, tally stocks −3, bonds +2; stale: satudatascape (missing) |
| `USA/JPN/EMU/AUS/SGP.json` | 4.3–5.6 kB | 7/4/6/6/5 components; bonds −3/−2/−9/−6/−3 |
| `portfolio.json` | 32,178 B | as of 2026-11-02, total Rp55,415,423: stocks 96.90%, bonds 1.79%, cash 1.31%; priskila Rp36.54 M, tommy Rp18.88 M; 12 accounts; 49 stances; 0 unmapped; the 63-line trade-price note |

IDN chart windows:

- Net foreign: 60 IDX days 2026-08-12 → 11-05; USD is null on 49 of them, every day before
  JISDOR's first fixing here (10-22).
- JISDOR: 11 fixings 2026-10-22 → 11-05 (this Mac's history starts 10-22), no carried-forward
  day, no IDX day without a fixing inside that span.
- JCI: 239 closes 2025-11-06 → 2026-11-05. SBN non-resident: 239 days 2025-11-06 → 11-04.
- IGSYC: 31 tenors on 2026-11-05 against 31 on 2026-10-08 (target 10-08). The 10-22 → 11-03
  hole does not touch either curve.

Read-only: `~/.financer/financer.db` mtime unchanged (14:11). Files newer in sibling repos
after the run: sec-edgar's `usfin-serve.log` (the serve process logging our GETs) and idx-method's
`stockbiter.db-shm` (SQLite's shared-memory file, touched by any `mode=ro` reader in WAL mode);
no store file changed.

## Decided differently or found

- `Sources.layers_out` is opt-in (False by default, True in `Sources.default()`): the e2e tests
  assert the exact set of JSON files in `out/` and must stay unchanged.
- Account numbers are masked to their last 4 characters in `portfolio.json` (P53 kept them out
  of its result doc); issuer and owner tell the accounts apart.
- The weekly regime line is read with the run day's vintage, not each Friday's own; it is a
  picture of the series, not a backtest.
- Pre-existing bug, not fixed here (outside this slice's files): `layers/bonds/idn.py`
  `bond_returns` raises IndexError when it gets exactly 2 month-end 10Y points with horizon 3
  (`pts[:len(pts) - horizon]` turns into a negative slice). Live has years of points, so it does
  not fire; the fixture curve avoids a 10Y point because of it.
