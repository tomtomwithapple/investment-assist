# P48-tier-model — PLAN S31: top tier per industry, the model

Built:
- `src/assist/candidates/tiers.py`: gates, within-peer percentiles, five pillars, composite,
  Tier A/B, one `CONFIG` whose sha256 is the tier `fingerprint`, and `gather_extras` for the
  live inputs.
- `src/assist/candidates/peers.py`: `build(cmp, day, config, extras=None)` ends with
  `tiers.attach`; `SCHEMA_VERSION` is 4; `gather_live` gathers the extras at the comparison's
  date and adds their stale inputs.
- `src/assist/pipeline.py`: `peers_record` and `_journal_peers`. `assist run` journals one
  `industries` record per run (kind `industries`, subject IDN, asset stocks): the tier
  fingerprint and config as inputs, per industry its peer group and picks, per gated name its
  pillars, composite, rank and pick, `moves_stance: false`. It reads the file `write_peers`
  wrote and never fails the run.
- `src/assist/views/industries.py`: `DER_CAP`, `DER_CAP_DEFAULT` and `der_cap` moved into
  `tiers.py`; the view imports them (re-exported, so `industries.der_cap` still works). The
  page is unchanged (P49 draws the tiers).
- Tests: `tests/candidates/test_tiers.py` (26) with fixtures in `tests/fixtures/tiers/`
  (`industry.json`, `banks.json`, `one_off.json`, `no_tier_a.json`).

## Schema 4

Payload: `fingerprint`, `tier_config`. Each industry: `peer_group` (`level` industry or
sector, `label`, `n` gated names in the pool), `picks` (`A`, `B`: symbols), `gated`,
`gate_failures` (reason → count). Each name: `gates` (`pass`, `fail` with every reason, and
`missing` for floor inputs not available), `metrics` (every computed metric value; None where
missing or not finite), `pillars` (per pillar `score`, `metrics` used, `of` defined, `pct` per
metric), `composite`, `rank` (within the industry, among names with a composite) and `pick`.
Names that fail a gate have `pillars: {}` and nulls. S30 fields are unchanged.

## Inputs and where each comes from

| Input | Source |
|---|---|
| PE, PBV, P/S, EV/EBITDA, ROE, ROA, ROIC, operating margin, D/E, interest cover, Altman Z, current ratio, market cap | Stockbit `/comparison` (the S30 values) |
| Quarterly revenue, operating profit, net income, equity | S30 `financials` (12 quarters) |
| `days_traded_60`, `med_value_60d`, `mom_12_1`, `near_52w_high` | `factors.load_factors` (`cache/history/`) at the comparison date |
| Piotroski, CAR, NPL (or NPF), NPL coverage, LDR; fallbacks for ROE, Altman Z, interest cover | `data/factors.json` |
| `cfo_ttm`, TTM NI now / 1y / 2y back | `factor_series` (`stockbiter.db`); else `factors.json` `cfo_ttm` and TTM sums of the S30 quarterly net income |

## Decisions where the spec was silent

- **Missing gate inputs.** Liquidity is required: a name with no derived liquidity row fails
  ("no liquidity data"; `derive` leaves dormant names out, so absence mostly means dormant).
  TTM NI and equity are required (fallbacks: market cap / Stockbit PE, market cap / PBV).
  Floor fields (Piotroski, Altman Z, interest cover, bank fields) and D/E apply where present,
  as the spec says for the quality floor; an absent one is listed in `gates.missing`.
  Interest cover is checked only when D/E > 0.05, as `screens.passes_quality` does (Stockbit's 0
  means no interest).
- **The screener's zeros.** `factors.json` writes 0.0 for a field it lacks, so 0 reads as
  missing for CAR, NPL/NPF, NPL coverage, LDR, `cfo_ttm` and Piotroski.
- **Who is a bank.** Bank floor and the financial metric set: industry label "Bank", or any
  name with a CAR (as `screens.passes_quality`). Insurers and multifinance ("Asuransi",
  "Jasa Pembiayaan") use the financial metric set too, but no store has their prudential
  fields, so their Health pillar is missing (composite on the other four, weights rescaled) and
  their floor is Piotroski only: Altman Z and interest cover do not read an insurer or a
  lender.
- **Normalised PE.** Market cap / min(TTM NI, mean of the TTM years available, up to 3). A late
  filer with fewer than 3 years in the window uses the years it has. A non-positive base ranks
  last on PE (internally +inf), so a one-off gain against a loss history cannot buy the top
  value rank. Without any TTM history, Stockbit's PE stands in.
- **Non-positive multiples.** PBV, P/S and EV/EBITDA at or below 0 have no value (negative
  EBITDA and net cash larger than market cap look the same).
- **Growth windows.** Revenue and NI TTM y/y need 8 quarters; the 2-year CAGRs (revenue for
  non-financials, equity for financials) need 12, because a 2-year TTM-on-TTM growth spans 12
  quarters (the spec said 8, which only gives y/y). NI y/y needs a positive base.
- **Stability.** Sample stdev of the quarterly operating margin (or annualised quarterly ROE,
  NI × 4 / equity) over the 12 quarters in the file, at least 8 quarters with a positive
  revenue (equity). Lower is better.
- **LDR** scores lower-is-better (liquidity first; the floor caps it at 110 anyway).
- **Pillar coverage.** "At least half of its metrics" counts against the pillar's defined
  list (3 of 5, 2 of 4, 1 of 2).
- **Sector pool.** The gated names whose own `sector` equals the industry's sector, across
  industries; each name keeps its own metric set. Used even when the sector itself has fewer
  than 8.
- **Tier size.** k = max(1, floor(20% of gated names)), at most 3, 5 from 40 gated names.
- **Tier B without Tier A.** Tier B is the next up to k names after Tier A scoring >= 50; in an
  industry with no Tier A it starts at rank 1 (the "no Tier A" fixture has a Tier B).
- **Rounding.** Percentiles, pillars and composites are rounded to 2 decimals and ranked on the
  rounded composite, then market cap, then symbol, so the output and its ties are stable.
- **Fingerprint.** `tiers.fingerprint()` hashes `CONFIG` only (it carries copies of
  `QUALITY_FLOOR`, `BANK_FLOOR` and `DER_CAP`); the run's model fingerprint already covers the
  code, since `candidates/*.py` is in `journal.RULE_GLOBS`.

## Tests (fixtures, no store)

Hand-worked ranks: 8 names ordered on every value, quality and health metric and the other way
on momentum, no statements (Growth missing, weights over 85): composite (70p + 15q) / 85 gives
78.31, 70.22, … 21.69; Tier A MNF1, Tier B MNF2. Gate reasons all listed (illiquid name
fails two, D/E name fails F-score and cap). One-off gain: ONEO's PE 2 normalises to 4.83 and
ranks 2nd on PE; ONE1 ranks first. Banks: own metric set, CAR floor, no D/E gate. Thin
industry: 3 gated names ranked over the 11 of the sector (PE percentiles 95.45, 40.91, 4.55),
composite 56.55 so Tier B only. No Tier A: best composite 52.57. Degradation: no extras (every
name fails liquidity, no crash), no momentum (pillar missing, weights rescale), a metric under 5
peers dropped, composite void without Quality. Byte-identical rerun, also with reversed input
order. Journal record written; a bad file is skipped without raising.

`uv run pytest -q`: 1373 passed. `uv run ruff check .`: clean.

## Live run: blocked

`ls ../idx-method/store/data/` on 2026-10-29 shows only `corpactions/`: `stockbiter.db` is
still not on this Mac, so `uv run assist industries` exits 1 with
`peer comparison failed: SourceUnavailable: idx-method missing: no file at
…/idx-method/store/data/stockbiter.db`, and no schema 4 file was written (the last
`out/industries/IDN.json` stays as it was). The tier inputs alone do load: `gather_extras`
returns 976 rows from `factors.json`, but liquidity and momentum only for 17 names, because
`cache/history/` holds 20 files on this Mac (the jobs Mac has the full set). Rerun
`assist industries` where the db and the full history cache are present to record names gated
in and out by reason, industries with a Tier A, and the A and B counts.

## Live run 2026-11-09: still blocked, on a new reason

`stockbiter.db` is on this Mac since 2026-11-06 (1.7 GB), and `cache/history/` now holds 984
files, but the db was built here by the 17:00 backfill jobs only (`pulls`: `industry`,
`factors`, and the `import_idx` loads of dividends, fundamentals, insider). `endpoints_pull.py`
(weekdays 16:30) has never run on this Mac, so `api_raw` has **0 rows** and
`uv run assist industries` exits 1 with `peer comparison failed: SourceUnavailable: idx-method
missing: no comparison_industries in api_raw`. No schema 4 file is written, so no name has a
tier yet. Nothing is wrong in the adapter: the tables it reads are unchanged, only empty.
Filling `api_raw` is idx-method's job (a `endpoints_pull.py` run on a logged-in session, or the
jobs Mac's db), *Open data gaps* in PLAN.md. `uv run pytest -q`: 1938 passed; ruff clean.
