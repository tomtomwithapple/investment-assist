# P46-peers — PLAN S30: peer comparison per industry

Three parts:
- `src/assist/sources/idxmethod_comparison.py`: the adapter.
- `src/assist/candidates/peers.py`: the model and the writer.
- `src/assist/views/industries.py`: the pages.

`web.ROUTES` maps `^/industries$` and `^/industries/([^/]+)$` to them, and the nav gains
*Industries*. `pipeline.write_peers` runs after the undervalued lists in `assist run`, and
`assist industries` writes only this file.

## Source

idx-method's `store/endpoints_pull.py` (weekdays 16:30, `launchd/close.sh`) stores three Stockbit
endpoints verbatim, zlib-compressed, in `api_raw`:
- `comparison_metrics`: the catalogue, 66 metrics in 9 groups.
- `comparison_ratios`: one per symbol.
- `comparison_industries`: one per symbol, with the `industry` and `sector` averages and up to
  four `competitor` symbols.

The adapter reads the newest date only, read-only. Values come as display strings ("16.00%",
"129,422 B", "(47,342 B)", "-", "N/A", "25 Mar 26") and are parsed to floats. A body that will
not decode drops that symbol only.

There is no industry name or id in the data. An industry is the set of names whose `industry`
block is byte-identical (`block_key`, sha1, 8 hex). On 2026-10-26 that gives 33 industries in 11
sectors, and each industry sits within one IDX-IC sector. The largest has 93 names (Barang Baku
is one industry); 4 have fewer than 3 names and get no industry median.

## Model

| Category | Scored (direction) | Shown only |
|---|---|---|
| valuation | PE TTM, PBV, P/S TTM, EV/EBITDA TTM (lower) | |
| dividend | dividend yield (higher) | payout ratio |
| profitability | ROE, ROA, ROIC TTM, net / operating / gross margin Q (higher) | |
| solvency | D/E, liabilities/equity (lower); current ratio, interest cover, Altman Z modified (higher) | |

**Benchmarks.** The industry and sector medians are computed here over the names that have a
value, and need at least 3 values. Stockbit's averages are means. On 2026-10-26 the industry PE
mean was −77.3 for the POLU/HRTA/ARGO group and −114.7 for DOSS. Those benchmarks are not
positive, which would leave the industry with no valuation scores, so the means are carried and
shown but never scored against.

**Deviation.** log(value / median), clamped to ±log 4. It is None in two cases: the benchmark is
not positive, or the value is not positive on a lower-is-better metric (a loss-maker's PE is not
cheap). On a higher-is-better metric, a value at or below zero against a positive median reads
as the floor −log 4. So a non-payer is 4× worse on yield, and a loss is 4× worse on ROE.

**Score.** The mean of the scored deviations in a category, signed so that positive is better.
It is reported with the count of metrics that fed it.

**Tiers.** By Stockbit's market cap: big ≥ IDR 10T, mid ≥ 1T, small below.

**Stale.** An input older than 14 days is a stale input. `pipeline.write_peers` never raises:
a failure becomes a stale input, and the previous file stays.

This is context only. No screen, verdict or stance reads it, so it carries no placebo control.

## Pages

- **`/industries`** has one card per sector. Each row is an industry, labelled by its 3 largest
  names, with its name count, big / mid / small counts, and PE, PBV, yield, ROE and D/E. Each
  of those shows the median, with Stockbit's mean under it.
- **`/industries/<id>`** has one SVG chart of four small multiples, one per category:
  - A row per name, grouped big / mid / small and ordered by market cap.
  - The bar is the score against the industry median, the ring the score against the sector
    median.
  - The axis is log, ¼× to 4×. Right is better, drawn blue; left is worse, drawn red. Direction
    carries the sign, so colour is never the only cue. The blue/red pair passes the dataviz
    validator in light and dark mode.
  - Each cell has a hover title, for example "BBNI Valuation: 1.11× better than the industry
    median, … than the sector median (4 metrics)".
- **Tables.** Under the chart there is one `<details>` table per category; valuation opens by
  default. The first four rows are the industry median, the industry mean, the sector median
  and the sector mean. Each name's cell shows its value with its "×ind · ×sec" deviation.
- **Stars.** Names listed in `out/candidates/IDN.json` are starred, with their style.
- **Guards.** `<id>` is matched exactly against the ids in the file and never becomes a path.
  Every value is escaped. The `.json` twins are the index data and the industry with its
  sector benchmarks.

## Tests

- 22 adapter tests: parsing, newest date, grouping by block, an undecodable body, and a missing
  db, table or pull.
- 23 peers tests: deviation cases, tiers, medians, signs, sector scoring, stale input, a
  byte-stable write, and `write_peers` never raising.
- 15 view tests: nav, index, chart, tables, twins, escaping, 6 404 cases, a missing or invalid
  file, and no stars without a candidates file.
- Full suite: 1317 passed, ruff clean.

## Live run (2026-10-27)

- `assist industries --today 2026-10-27` → `out/industries/IDN.json`: 33 industries, 836 names,
  as of 2026-10-26, 1.9 MB.
- `assist status --port 8797`:
  - `/industries` and `/industries/8f8ca75c` (banks, 47 names, 147 KB) answer 200, as do
    their `.json` twins.
  - `/industries/nope` and `/industries/..` answer 404.
  - Screenshots checked in light and dark mode: no label collisions after widening the panel
    gap to 30.
- On banks (industry PE median 8.78, Stockbit mean 7.60):
  - BMRI and BBNI are about level to slightly cheaper on valuation (1.04×, 1.11×), pay about 2–3×
    the median yield, and are less solvent (0.58×, 0.72×).
  - BBCA is dearer (0.53×) and 3.16× more profitable.
- The Stockbit session had expired (refresh 401, `./run.sh login` needed in idx-method). That
  did not matter here because the 2026-10-26 pull is stored, but the 16:30 pull will store
  nothing until the session is renewed.

## Gaps

- **No industry names.** Naming needs membership per IDX-IC sub-sector: `/screener` with
  universe scope `sub`, or `/emitten`. That is idx-method V2, which also keeps membership per
  day.
- **Today only.** Every pull is today's cross-section (`/comparison` ignores a date), so there
  is no history yet. One date is stored per weekday pull from now on.
