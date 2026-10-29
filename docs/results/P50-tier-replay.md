# P50-tier-replay: PLAN S31, quarter-end replay of the top tier per industry

Built:
- `src/assist/candidates/tiers_replay.py`: the replay. At each quarter end from 2017 that has a
  later one, it rebuilds a reduced composite from `factor_series` (via `dividend_value.load`) and
  `cache/history/`, picks Tier A per industry by the live model's rules, and scores Tier A
  against its industry median over the next 3 months against a within-industry shuffled
  placebo. The verdict is written to `out/industries/IDN.replay.json` (`write`) and read back
  with `load(out_dir)` (for the brief, and for the page later). `journal_record` builds the
  journal entry and `run_live(day, out_dir)` runs it on the real stores.
- `src/assist/candidates/tiers.py` (P48's model, refactor only): the tier picking moved out of
  `attach` into `rank_key` and `assign(composites, k, config)`, so the replay picks through the
  same function. `tiers.CONFIG` and its fingerprint are unchanged, and P48's 26 tests pass as
  before.
- `src/assist/brief.py`: a *Top tier replay* section after *Undervalued candidates*
  (`tier_replay_lines`). It appears only when `out/industries/IDN.replay.json` exists, so
  `expected.md` and the existing briefs are unchanged.
- `src/assist/pipeline.py` (additions only): a `Sources.tier_replay` field (live default
  `tiers_replay.run_live`, None in tests), `write_tier_replay` after `write_peers`, and
  `_journal_tier_replay`, which writes one `tier_replay` record per run (`moves_stance: false`).
  Neither can fail the run: an exception becomes a stale input ("tier replay failed: ...").
- Tests: `tests/candidates/test_tiers_replay.py` (16), fixture
  `tests/fixtures/tiers_replay/universe.json` (3 industries × 10 names: one standard industry
  with one illiquid name, one standard industry, one bank industry). Bars, quarters and
  signals are generated from it with a seeded rng.

## The replay

| Pillar | Standard | Bank / insurer / multifinance (by label) |
|---|---|---|
| Value | normalised PE, PBV, EV/EBIT, P/CFO | normalised PE, PBV |
| Quality | ROE (`ni_ttm`/`equity`), CFO/NI | ROE |
| Growth | `ni_ttm` y/y | `ni_ttm` y/y |
| Health | net debt / equity | none (no prudential history) |
| Momentum | `mom_12_1`, `near_52w_high` | same |

- **Point in time.** A quarter counts only once period end + `screens.LAG_DAYS` (120) is on or
  before the quarter end, even if the store's `available` says earlier. Momentum and liquidity
  come from `factors._signals` on history bars up to that date. The price is the last
  `factor_series` bar no more than 10 days before the quarter end.
- **Gates.** `tiers.gates` itself: liquidity (`days_traded_60` ≥ 30, `med_value_60d` ≥ IDR 1bn),
  positive TTM NI and equity, and D/E (`total_debt`/`equity`) under `DER_CAP`. The quality
  floor inputs have no history, so they are left out, and `tiers.gates` lists them as
  `missing` without failing the name.
- **Peers, composite, tiers.** `tiers._pool_pcts` and `tiers._score` run on a config that is
  `tiers.CONFIG` with only the metric sets and `lower_is_better` swapped, so weights, coverage,
  `min_peer_group` with the sector fallback, and the tier cutoffs are the live model's.
  `tiers.tier_size` and `tiers.assign` pick Tier A.
- **Statistic.** For each industry with a Tier A: Tier A's mean forward return minus the median
  forward return of the industry's gated names. The forward return runs to the next quarter
  end and includes price plus dividends gone ex, as GARP does. A quarter's statistic is the
  equal-weighted mean over industries, and the quarter is scored only when at least 3
  industries have a Tier A.
- **Placebo.** 200 seeded sets in which composites (and their pillars) are shuffled within each
  industry (`placebo.block_shuffle`), with Tier A picked by the same rules. Each scored quarter
  gives `placebo.evaluate` two observations: (True, real) and (False, mean placebo). The run
  passes only when that verdict passes (Welch t ≥ 2, return-shuffle p ≤ 0.05, control t < 2)
  **and** `perm_p` ≤ 0.05, where `perm_p` is the share of shuffle sets whose mean is at least
  the real mean.
- **Insufficient** means fewer than 10 scored quarters. **Blocked** means membership or
  `factor_series` is missing. In both cases the payload has `context_only: true`.
- **Diagnostics.** Each pillar alone is ranked by the same tier rules (mean excess, t,
  quarters). These numbers decide nothing.
- **Flags** (in every payload): survivorship from today's membership (until idx-method V2), the
  120-day lag (V3 open), the reduced composite (V1), and that the quality floor is not
  replayed.
- **Fingerprint.** `tiers_replay.fingerprint()` is the sha256 of the replay config (the live
  weights and rules plus the replay block). The payload also carries `tier_fingerprint`, and
  the journal record carries the run's model fingerprint, which covers the code.

## Decisions where the spec was silent

- **"Industry median" pool.** The median is over the industry's gated names with a forward
  return, i.e. the pool Tier A is picked from. Illiquid and loss-making names are left out.
- **Placebo as the "off" leg.** `evaluate` compares on/off observations. The "off" leg is the
  shuffled-composite Tier A (the mean of 200 sets), not the rest of the industry, so the test
  is Tier A against random picks of the same size from the same pool. Because of right skew,
  random picks already beat the median. `perm_p` is added as a second gate because a single
  pair per quarter is a thin placebo.
- **Financial industries.** These are decided by label only, since there is no CAR history.
  They have no Health pillar, so their composite uses four pillars with the weights rescaled,
  as in the live model.
- **Membership source.** `out/industries/IDN.json` (the S30 file this run just wrote, or the
  last one). The replay never reads the comparison store directly.
- **Cost.** About 1.2 s on the fixture. On the full universe (~900 names, ~38 quarters) expect
  a few seconds per `assist run`.

## Tests (fixtures only, no store)

- Lag: the store's early `available` is overridden. At 2018-06-30, wrecking the 2018-03-31
  quarter (not yet knowable) leaves the panel byte-identical, and wrecking 2017-12-31 changes it.
- History signals at a date match `factors.derive(as_of=date)` and do not change when later
  bars are cut.
- Gates and metric sets: the illiquid name is never gated, and banks have no Health pillar.
- Tier A uses the live rules.
- Planted signal: passed, t 19.78, p 0.001, perm p 0.005, control t 0.15, 17 quarters, mean
  excess +4.52pt against placebo +0.10pt.
- The same panel with composites shuffled within each industry fails.
- Noise: failed (t −0.25).
- 6 quarters: insufficient sample.
- Survivorship flag and fingerprints are present.
- A rerun is byte-identical.
- Live with no membership gives a blocked payload.
- write/load round trip; brief section present with verdict, statistics, flags and model;
  absent without the file; blocked lines say context only.
- Journal record written; the hook turns an exception into a stale input; a missing file does
  not raise.

`uv run pytest -q tests/candidates/test_tiers_replay.py`: 16 passed. `uv run pytest -q`: 1401
passed. `uv run ruff check .`: clean.

## Live run: blocked

On 2026-10-29 `ls ../idx-method/store/data/` shows only `corpactions/`: `stockbiter.db` is
absent, so `dividend_value.load()` returns no bars (`idx-method (missing)`). There is also no
`out/industries/IDN.json`, because `assist industries` fails on the same missing db (see P48),
so there is no membership. `tiers_replay.run_live` returns `status: blocked` ("no S30
membership (IDN.json: FileNotFoundError)"), and `cache/history/` holds only 20 files on this
Mac. To get the verdict, run `assist run` (or `assist industries`, then
`tiers_replay.run_live`) where the db and the full history cache are present, and record
status, t, p, perm p, control t, quarters and the per-pillar diagnostics.

## For P49 (the page)

`tiers_replay.load(app.out_dir)` returns the payload or None. Show one line above *Top tier
by industry*: `status` (passed / failed / insufficient / blocked) with `verdict`, then
`quarters`, `first_quarter` to `last_quarter`, `mean_excess` against `mean_placebo` (both are
fractions, ×100 for pt), `t`, `p`, `perm_p` and `control_t`. Then the `flags`, with
survivorship first, and "context only" whenever `context_only` is true. `pillars` (per pillar
`mean_excess`, `t`, `quarters`) can go in a collapsed diagnostics row marked "decides
nothing". `per_quarter` holds the series (`quarter`, `excess`, `placebo`, `industries`,
`picks`) if a chart is wanted.
