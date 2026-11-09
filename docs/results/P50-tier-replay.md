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

## Live run 2026-11-09

**Of record: blocked.** `assist run` writes `out/industries/IDN.replay.json` with `status:
blocked` ("no S30 membership (IDN.json: FileNotFoundError)"), because `assist industries`
cannot build `IDN.json` while idx-method's `api_raw` is empty on this Mac (P48). Everything
else the replay reads is present: `factor_series` 1,006 symbols 2016-11-07 → 2026-11-06,
`cache/history/` 962 of 963 member names.

**Diagnostic only, not the verdict of record.** S30's industries are the IDX sub-sectors one
for one (`peers.SUBSECTORS`), and idx-method's `industry_membership` (V2, 963 names,
2026-11-06) carries the same 33 sub-sectors with the same names. So `tiers_replay.run` was run
read-only from a scratch script with membership `sub_sector_id` / `sub_sector` / `sector` from
that table, everything else as `run_live` (code, `CONFIG` and fingerprints unchanged):

| | |
|---|---|
| status | **failed** (t 0.02 below 2.0) |
| quarters | 15, 2022-12-31 → 2026-06-30 |
| Tier A minus industry median, 3 m | +3.11 pt vs placebo +3.08 pt |
| t / p / perm_p / control t | 0.02 / 0.508 / 0.468 / −0.17 |
| pool | 963 members, 17.2 industries with a Tier A per quarter, 370 Tier A picks in all |
| pillars alone (decide nothing) | value +2.92 pt t 2.66; growth +4.98 t 2.16; health +4.08 t 2.12; momentum +3.19 t 1.53; quality +1.67 t 1.38 |

Random picks of the same size from the gated pool beat the industry median by as much as the
composite's Tier A does: the composite adds nothing over its own placebo, though each pillar
alone beats the median. That spread is diagnosis only; S31's weights are fixed before the
replay, so a re-weighting is a new model and would need an agent review the user decides.

Why 15 quarters, not ~37 from 2017: `cache/history/` starts 2021-11-01, so `mom_12_1` and the
liquidity gate (`days_traded_60`) have no value before late 2022, and every name fails the
liquidity gate in earlier quarters. Momentum and liquidity from `factor_series` daily bars
(back to 2016-11) would lengthen the replay, but the spec names `cache/history/`, so that is a
user decision too.

The `survivorship` flag still says "until idx-method V2"; V2 (`industry_membership`) has
landed but holds one date (2026-11-06), so today's membership is still back-filled and the
flag stands in substance.

## Replay of record on `industry_membership` (2026-11-09, user-approved)

The user approved two spec changes on 2026-11-09 (data sources only; `CONFIG`, weights,
thresholds and both fingerprints unchanged, `sha256:6cf25fa49ea6…` / tier `sha256:bb4e3805c09d…`):

1. **Membership from idx-method `industry_membership`. Done.** `membership_snapshots(series)`
   reads the table read-only (`sub_sector_id` as the industry, `sub_sector` as the label, the
   same 33 IDX sub-sectors S30's Stockbit groups match, with the same names). `replay_panel` and
   `run` take either the old static mapping or dated snapshots; at each quarter end
   `membership_at` takes the latest snapshot on or before it, else the first one back-filled, and
   a name outside that snapshot sits the quarter out. The payload gains a `membership` block
   (`source`, `snapshots`, `first_snapshot`, `last_snapshot`, `names`, `quarters_back_filled`,
   `quarters_point_in_time`), and the survivorship flag now states how many scored quarters
   are back-filled. `run_live` no longer reads `out/industries/IDN.json`; it is blocked only
   when the table is missing or empty. Tests: 5 new (snapshot choice, one later snapshot
   reproducing the static panel and verdict exactly, a reclassified and a dropped name moving
   from their snapshot date, the live read from a fixture db with no IDN.json, blocked without
   the table); 21 in the file, 1943 total; ruff clean.
2. **Momentum and liquidity from bars back to 2016-11. Not done: no source.** `factor_series`
   has daily `price` (close) from 2016-11-07 for 541 names already listed then, enough for
   `mom_12_1` and `near_52w_high`, but no traded value or volume: its items are price, mktcap
   and the five multiples. idx-method's `bars` table (the `idx-method-history` import of
   `cache/history/`) starts 2021-10-18, and idxscape `stock_summary` (`value_idr`,
   `volume_shares`) starts 2021-10-01. `days_traded_60` and `med_value_60d` therefore cannot be
   computed before late 2021 without a proxy, so per the instruction the work stopped there.
   Momentum alone from `factor_series` would not lengthen the replay either, because every name
   still fails the liquidity gate before 2021-12.

**Live verdict (`run_live`, written to `out/industries/IDN.replay.json`): failed**, the same
numbers as the diagnostic above, as expected with one snapshot over the same 33 groups:

| | |
|---|---|
| status | **failed**: t-stat 0.02 below 2.0 |
| quarters | 15, 2022-12-31 → 2026-06-30, all 15 back-filled from the 2026-11-06 snapshot |
| Tier A minus industry median, 3 m | +3.11 pt vs placebo +3.08 pt |
| t / p / perm_p / control t | 0.02 / 0.508 / 0.468 / −0.17 |
| pool | 963 member names (962 with history), 17.2 industries with a Tier A per quarter, 370 Tier A picks |
| pillars alone (decide nothing) | value t 2.66, growth 2.16, health 2.12, momentum 1.53, quality 1.38 |

The tiers stay context only (`context_only: true`). Any change to the weights after this
result is post-hoc and would need an agent review the user decides.
