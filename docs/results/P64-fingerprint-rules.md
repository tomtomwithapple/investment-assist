# P64-fingerprint-rules (PLAN S45) — results, 2026-11-07

## What changed

- `src/assist/journal.py`: `RULE_GLOBS` is now
  `("stance.py", "layers/**/*.py", "candidates/**/*.py", "eval/**/*.py")`. Before, the globs were
  `layers/*.py` etc., and `PACKAGE_DIR.glob` does not recurse, so modules in subpackages were not
  hashed. The IDN bonds and stocks rules were among them. A threshold change in either one did not
  segment the journal. `**` also covers modules added later under these packages, such as phase K's
  `eval/gate.py` and any new `layers/` subpackage. `sources/`, `views/`, `cli.py`, `doctor.py`
  and `pipeline.py` stay out. The module docstring says so.
- Hashing is unchanged: P61's AST without docstrings (`code_digest`). `RULES_METHOD` still
  describes it accurately, so it was left as it is. Only the set of hashed files grew.

No decision rule, threshold, band or tilt changed.

## Modules added to the hash (27 → 31)

- `assist/layers/bonds/__init__.py`
- `assist/layers/bonds/idn.py` (IDN bonds rule)
- `assist/layers/rules/__init__.py`
- `assist/layers/rules/idn_stocks.py` (IDN stocks rule)

`candidates/` and `eval/` have no subpackages today, so the recursive glob adds nothing there yet.

## Fingerprint

`household.local.yaml` (gitignored, present only in main's checkout) is in `PLUMBING_CONFIG`
(added after P61), so main's extra config file does not enter the hash. Main's checkout and
this worktree have the same model config files (`config/sector_tilt.yaml`), so both give the same
value. I computed both anyway, with this worktree's rules plus main's `config/` directory.

| | fingerprint |
|---|---|
| before, this worktree (main HEAD `0063ad7`) | `sha256:8c6a886f278d2b1762dd1d9f34e473adab90c9e2c9adc1312eb292a69d1490d6` |
| before, main checkout's config files | `sha256:8c6a886f278d2b1762dd1d9f34e473adab90c9e2c9adc1312eb292a69d1490d6` |
| after, this worktree | `sha256:0326f73391279933c9de335e5e51da0b484422522abba0b31433ddf7243857b3` |
| after, these rules + main's config files (what main shows once merged) | `sha256:0326f73391279933c9de335e5e51da0b484422522abba0b31433ddf7243857b3` |

"Before" matches the last live model in STATUS (`sha256:8c6a886f278d…`). The next `assist run`
after the merge opens one new journal segment, as planned. No live run was made and the real
journal was not touched.

## Tests

New tests in `tests/test_journal.py` (5):
- `test_default_fingerprint_hashes_nested_rule_modules`:
  - `assist/layers/bonds/idn.py` and `assist/layers/rules/idn_stocks.py` are in
    `fingerprint_inputs()["rules"]`;
  - every `*.py` at any depth under `layers/`, `candidates/` and `eval/` is in the hash;
  - no `sources/`, `views/`, `cli.py`, `doctor.py` or `pipeline.py` is.
- `test_constant_change_in_nested_rule_changes_fingerprint`, 2 cases, run on a copy of the real
  tree: `MIN_FX_DAYS 60 → 59` in `layers/bonds/idn.py` and `ERP_BAND 1.0 → 1.5` in
  `layers/rules/idn_stocks.py` each change the fingerprint.
- `test_comment_or_docstring_edit_in_nested_rule_keeps_fingerprint`, 2 cases: rewriting the
  module docstring and adding comments in either module keeps the fingerprint.

Red before the fix: 3 failed, the membership test and both constant-change tests, for the
intended reason. The docstring tests passed trivially then, because those files were not hashed.

- `uv run pytest -q tests/test_journal.py && uv run ruff check .`: 29 passed, clean.
- `uv run pytest -q`: 1650 passed, 1 skipped (worldbankscape checkout not present).
