# P61-fingerprint-scope (PLAN S41) — results, 2026-11-07

## What changed

- `src/assist/journal.py`: rule modules (`stance.py`, `layers/*.py`, `candidates/*.py`,
  `eval/*.py`) are hashed with `code_digest`: `ast.parse`, drop the module, class and function
  docstrings (only a body's first bare-string statement), `ast.dump(tree, include_attributes=False)`,
  sha256. Comments, docstrings, blank lines, formatting and line numbers no longer change the
  fingerprint. Any code change still does: constants, expressions, operators, names, signature
  defaults, and string statements that are not docstrings. A rule file that does not parse raises
  `SyntaxError`, and a missing one still raises `FileNotFoundError`. Config files are still
  hashed by bytes, so a YAML comment still segments the record. The inputs now carry
  `rules_method` (`RULES_METHOD`), which is stored in `journal/models/<hex>.json`. The module
  docstring describes the new method.
- `src/assist/paper.py`: `MIN_ANNUALISE_WEEKS = 12`. `summarize` returns `annualized: None` below
  12 scored weeks and always adds `annualize_min_weeks: 12`. A new helper, `annualized_note(summary)`,
  returns "annualised after 12 scored weeks" while a summary is below that minimum.
- `src/assist/brief.py`: `paper_lines` (via its own helper `_bench_line`, which only
  `paper_lines` calls) prints "cumulative -7.7%, annualised after 12 scored weeks" below 12
  weeks. The `assist paper` CLI prints `brief.paper_lines`, so `cli.py` was not touched.
- `src/assist/views/paper.py`: in the /paper summary and legacy cards, the Annualised cell reads
  "after 12 scored weeks". The `/paper.json` twin gets `annualized_note`, and the report's
  summaries carry `annualized: null` and `annualize_min_weeks: 12`.

No decision rule, band, tilt, benchmark or ladder changed.

## Fingerprint

| | fingerprint |
|---|---|
| before, main checkout (raw bytes, incl. gitignored `config/household.local.yaml`) | `sha256:2b5fe4df2fb50a29bc8e739edd5757fe0daf5f5fdfa32a17c8b044b176833aae` |
| before, this worktree (no `household.local.yaml`) | `sha256:7822bcfd80e492f8dd74c8299157df3d3abae0595c4b783ea6be8e8930720e6a` |
| after, this worktree | `sha256:0ff351651958afdd9120aacf8929a216fbd04e0e4f69e6c923544c9a8c00451e` |
| after, these rules + main's config files (what main should show once merged) | `sha256:a016aee010ae0afe21cb65528314085bf9158e8c592333bd90d11adcbc35b55f` |

The method change opens one new segment, as planned.

Check on the real tree: I copied `src/assist` to a temp directory, rewrote `stance.py`'s module
docstring, added a comment and added comment lines to `layers/regime.py`. The fingerprint stayed
the same (`sha256:dfd3e14af84e…` before and after, with no config files). Adding `_X = 1` to
`regime.py` changed it. The test `test_real_tree_fingerprint_survives_a_docstring_edit` makes
the same check.

## Tests

`uv run pytest -q`: 1617 passed, 1 skipped (worldbankscape checkout not present). `uv run ruff
check .`: clean. New tests:
- 6 in `test_journal.py`:
  - docstring, comment and blank-line edits keep the fingerprint;
  - a constant, expression, operator, default, name or string-constant change alters it;
  - a non-docstring string statement and a config-file byte change both alter it;
  - `rules_method` is recorded;
  - a file that does not parse raises;
  - the real-tree docstring edit.
- 2 in `test_paper.py`: below 12 weeks there is no annualised figure, including a single −7.7%
  week; at 12 there is one.
- 2 in `test_brief.py`: the same for `paper_lines`.
- 2 in `test_view_paper.py`: the same for the HTML cell and the JSON twin.

Red before implementation: 9 failed, for the intended reasons. The code-change tests already
passed under byte hashing, which was expected.

## Live

`uv run assist --siblings-root /Users/tommy/Projects run --no-send` exited 0 and wrote only to
this worktree's `out/`, `journal/` and `data/briefs/`. Telegram was not sent. The journal
registered model `0ff351651958…`.

`uv run assist --siblings-root /Users/tommy/Projects paper`:

```
- Benchmark 48% JCI / 32% SBN leg / 20% US stocks (IDR): 1 week(s) scored from 2026-10-06, cumulative -7.7%, annualised after 12 scored weeks; 3 stale week(s), not scored.
- Last scored week ends 2026-10-16: benchmark -7.7% (JCI -14.9%, SBN leg -1.0%, US stocks (IDR) -1.1% = SPY -2.0% × USD/IDR +0.9%).
- Legacy benchmark (segments before S39) 60% JCI / 40% SBN leg: 1 week(s) scored from 2026-10-06, cumulative -9.4%, annualised after 12 scored weeks; 3 stale week(s), not scored.
- Model `sha256:0ff351651958` (vs 48/32/20): from 2026-11-07, 0 week(s) scored (0 stale): nothing scored yet.
- Stale: JCI ends 2026-11-05 (idxscape index_daily).
- Stale: IGSYC.10 ends 2026-11-05.
- Stale: SPY ends 2026-11-06.
- Stale: USD/IDR ends 2026-11-05.
```

The brief in `data/briefs/` carries the same lines. Before this change it showed "annualised
-98.5%".
