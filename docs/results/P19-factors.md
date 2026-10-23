# P19-factors — results

_Backfilled 2026-10-23 from the slice agent's report in `.slicer/run.log` (the slice did not own this file)._

P19-factors is committed as `8767171` and not pushed. The accept command passes: 18 tests, ruff clean. The full suite also passes (301).

**What it does**
- **Reading idx-method's files** (`src/assist/sources/idxmethod_stocks.py`): `IdxMethodStocks` reads `factors.json`, `consensus.json`, `composition.json`, `universe.json` and the three `cache/` folders read-only. A missing repo, file or folder is reported as "missing" and a file that won't parse (e.g. half-written) as "error", never a crash. The caches only cover some symbols, so a symbol with no file is simply left out. The index CSVs stay in P3's `idxmethod.py`.
- **The six derived columns** (`src/assist/candidates/factors.py`): `vol_1y`, `amihud`, `med_value_60d`, `days_traded_60`, `mom_12_1` and `near_52w_high` are computed only from `cache/history/`. I copied the definitions from idx-method's deleted `panel.py` (recovered from its git history) rather than writing new ones, so the screens rank on what its backtests measured. That includes its rules for skipping stock splits and for leaving out names that rarely trade.
- `enrich` puts the derived values into the `factors.json` table. A name with no derived value gets `None`, so old values from idx-method's last enrich never carry over. `load_factors()` returns the table plus a `stale_inputs` list.

**Live run (read-only, this Mac)**
- `factors.json`: 978 names, each with a history file. `consensus.json` has 98, `composition.json` 963, dividends 979, fundamentals 517.
- Factors were derived for 828 names, as of the last bar, 2026-10-09; the other 150 are too new or too thinly traded. The run took 3.5s.
- **Cross-check:** `factors.json` still holds the values idx-method's own `enrich.py` last wrote. Mine match them exactly on all 828 names for every column (`mom_12_1` on 826, where the old value isn't empty). No name that had old values is missing now.

**Where the sibling and the plan differ**
- **Stale cache here:** on this Mac the price history ends at 2026-10-09 and `factors.json` was last written 2026-10-12. The history cache isn't committed in idx-method, so the jobs Mac may be newer. Each row carries a `bar_date` so later slices can flag staleness.
- **Old values still present:** idx-method's README says `factors.json` no longer gets the six columns after its next pull. The current file still has them, which is what made the cross-check possible.
- **`near_52w_high` uses unadjusted prices**, as idx-method did. After a split it reads about 0.5 until the split drops out of the 52-week window. I kept this to match the backtests, and it's documented in the module.
- **Gitignored fixtures:** `.gitignore`'s `data/` rule covers `tests/fixtures/idxmethod/stocks/data/`. I force-added those files, as P3 did for its fixtures.

There's no `docs/results/P19-factors.md` in this slice's allowed files, so the live numbers are recorded only here.
