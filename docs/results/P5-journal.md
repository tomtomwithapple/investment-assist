# P5-journal — results

`src/assist/journal.py`: the decision journal and model fingerprint (CLAUDE.md *Rules*, PLAN S5/S13).
No live store is read. 18 tests in `tests/test_journal.py`, full suite 369 passed / 1 skipped, ruff clean.

## Fingerprint inputs

`fingerprint(inputs)` = `"sha256:" + sha256(canonical JSON of inputs)`, where canonical JSON has
sorted keys, compact separators, no NaN. `fingerprint_inputs()` builds:

| Key | What | Default |
|---|---|---|
| `config` | hand-set weights, bands, tilts, ladder, penalties | `stance.MODEL_CONFIG` |
| `rules` | `{relative path: sha256 of file bytes}` for every rule module | `src/assist/` `stance.py`, `layers/*.py`, `candidates/*.py`, `eval/*.py` (paths relative to `src/`, e.g. `assist/stance.py`) |
| `config_files` | `{relative path: sha256}` of model config files | `config/*.yaml|yml|json` except `sources.yaml` (store locations are plumbing, not model) |

Left out on purpose: `sources/` adapters, `cli.py`, `doctor.py`. They move data around but don't decide anything.
Paths are relative, so the fingerprint is the same in any checkout or worktree. A missing rule file raises
`FileNotFoundError` instead of being skipped silently. Any byte change in a rule module changes the
fingerprint, comments included. That's deliberate: it's conservative, and the cost is only a new segment.

Live on main at this slice: `model_fingerprint()` = `sha256:994cc910…71b76a`, stable across calls. It
covers 9 rule modules and has 0 model config files (only `sources.yaml` exists in `config/`).

**For later slices:** `stance.model_fingerprint()` (P10) hashes `MODEL_CONFIG` only, giving
`sha256:12aa4aa5…`. The run (`assist run`, S5/S6 wiring) must pass
`fingerprint=journal.model_fingerprint()` into `stance.build_stance`. `Journal.record` refuses an
output whose `model_fingerprint` differs from the journalled one.

## Record format

The decisions file is `journal/decisions.jsonl` (gitignored). It's append-only, holds one canonical-JSON
line per decision, and every write runs under an `flock` and ends with an `fsync`.

```json
{"kind":"stance","fingerprint":"sha256:…","subject":"IDN","asset":"bonds","as_of":"2026-10-23",
 "run_id":"…","recorded_at":"2026-10-23T09:00:00+00:00",
 "inputs":{"score":{…AssetScore…},"regime":{…},"weights":{"weights":{"IDN/bonds":40.0,…}}},
 "outputs":{…stance payload…},"seq":0,"prev":"","hash":"<sha256 of the record without hash>"}
```

- `inputs` and `outputs` go through `jsonable()`, which converts layer dataclasses to dicts, dates to ISO
  strings, tuples to lists and the `Weights` tuple keys to `"SUBJECT/asset"`. Anything it can't convert
  raises `TypeError` before the file is opened.
- `seq` counts up from 0. `prev` is the previous record's `hash`. `Journal.verify()` re-checks seq,
  each record's hash and the chain, and names the seq of the first edited line.
- Each model's inputs are stored once in `journal/models/<hex>.json` by `Journal.register_model()`,
  which is idempotent and refuses a file whose content differs from its name. Diffing two of these
  files shows what changed between two segments.
- `Journal.segments()` returns `{fingerprint: [records]}` in order of each model's first decision.
  `read(fingerprint=…)` and `fingerprints()` filter by model. S13 paper tracking should mark
  performance per segment, never across segments.
