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

**Names.** The groups match the IDX sub-sectors that Stockbit lists in idx-method's
`data/universe.json` one for one, sector by sector. `peers.SUBSECTORS` names each group by the
sub-sector whose anchor symbols it holds (BBCA → Bank, TLKM → Telekomunikasi, …). Barang
Rekreasi (DOSS), Energi Alternatif (ALII, SEMA) and Logistik & Pengantaran (TMAS, SMDR) are
named by elimination. A group with no anchor takes its sector name (Barang Baku is one
sub-sector).

## Model

| Category | Scored (direction) | Shown only |
|---|---|---|
| valuation | PE TTM, PBV, P/S TTM, EV/EBITDA TTM (lower) | |
| dividend | dividend yield (higher) | payout ratio |
| profitability | ROE, ROA, ROIC TTM, net / operating / gross margin Q (higher) | |
| solvency | D/E, liabilities/equity (lower); current ratio, interest cover, Altman Z modified (higher) | |

**Benchmarks.** Since 2026-10-28 the industry benchmark is Stockbit's industry average, and no
industry median is computed (schema 2). The sector benchmark is still the sector median, computed
here over at least 3 values, with Stockbit's sector average shown beside it. Stockbit's averages
are means that loss-makers can drag to zero or below: on 2026-10-26 the industry PE mean was
−77.3 for the POLU/HRTA/ARGO group and −114.7 for DOSS. Where an industry average is not positive
or missing, nobody in that industry gets a deviation on that metric, so the `/industries` filters
fail there. On 2026-10-26 that shuts 9 industries out of the list: PE in Jasa Konsumen, Media &
Hiburan, Pakaian & Barang Mewah, Barang Rumah Tangga and Barang Rekreasi; PBV and D/E in
Transportasi; dividend yield in Jasa Konsumen, Media & Hiburan, Pakaian & Barang Mewah, Jasa &
Peralatan Kesehatan, Perusahaan Holding & Investasi and Perangkat Lunak & Jasa TI. With the
average, 45 names in 15 industries pass (41 in 18 with the median).

**Deviation.** log(value / benchmark), clamped to ±log 4. It is None in two cases: the benchmark is
not positive, or the value is not positive on a lower-is-better metric (a loss-maker's PE is not
cheap). On a higher-is-better metric, a value at or below zero against a positive benchmark reads
as the floor −log 4. So a non-payer is 4× worse on yield, and a loss is 4× worse on ROE.

**Score.** The mean of the scored deviations in a category, signed so that positive is better.
It is reported with the count of metrics that fed it.

**Tiers.** By Stockbit's market cap: big ≥ IDR 10T, mid ≥ 1T, small below.

**Stale.** An input older than 14 days is a stale input. `pipeline.write_peers` never raises:
a failure becomes a stale input, and the previous file stays.

This is context only. No screen, verdict or stance reads it, so it carries no placebo control.

## Pages

- **`/industries`** shows only the names that pass the filters below, as one SVG chart per
  industry. The industry with the best overall score comes first, and its names are in score
  order.
  - Each chart has one panel per metric: PE, PBV, dividend yield, ROE and D/E. Each panel starts
    with one grey bar, Stockbit's industry average. Then comes one bar per passing name: blue
    when it is better than the average, red when it is worse. The average is drawn as a dashed
    line.
  - A name must pass every one of these (since 2026-10-28):
    - Its PE and its PBV are each below the industry average.
    - Its ROE is above the industry average.
    - Its D/E is at least 0 and below its industry's cap (`DER_CAP` in `views/industries.py`).
      The common cap is 1. Jasa Pembiayaan allows 5; Telekomunikasi, Utilitas, Infrastruktur
      Transportasi and Perusahaan Holding Multi Sektor allow 1.5; Perangkat Lunak & Jasa TI,
      Media & Hiburan and Rokok require below 0.5. Bank and Asuransi have no cap, because
      their leverage isn't read from D/E and most of them have no D/E on Stockbit.

    Dividend is not filtered, and the overall and category scores only order the names. A
    missing value or average fails the name, except D/E where there is no cap. On 2026-10-26,
    73 names in 19 industries pass (45 in 15 under the earlier score filters).
  - The page took this shape in three steps on 2026-10-27, after the first version (cards per
    sector, one row per industry):
    - `cf40630`: one ranked table.
    - `79b2a15`: the PE and PBV check.
    - `33cb34c`: the 0.8× floors and the sub-sector names.

    `d3cad8c` then replaced the table with the charts.
- **`/industries/<id>`** has one SVG chart of four small multiples, one per category:
  - A row per name, grouped big / mid / small and ordered by market cap.
  - The bar is the score against the industry average, the ring the score against the sector
    median.
  - The axis is log, ¼× to 4×. Right is better, drawn blue; left is worse, drawn red. Direction
    carries the sign, so colour is never the only cue. The blue/red pair passes the dataviz
    validator in light and dark mode.
  - Each cell has a hover title, for example "BBNI Valuation: 1.11× better than the industry
    average, … than the sector median (4 metrics)".
- **Tables.** Under the chart there is one `<details>` table per category; valuation opens by
  default. The first three rows are the industry average (the benchmark), the sector median
  and the sector average. Each name's cell shows its value with its "×ind · ×sec" deviation.
- **Stars.** Names listed in `out/candidates/IDN.json` are starred, with their style.
- **Guards.** `<id>` is matched exactly against the ids in the file and never becomes a path.
  Every value is escaped. The `.json` twin of `/industries` has `as_of` and `rows`, the
  passing names, and `industries`, each with its label, sector, average and passing
  symbols. The twin of `/industries/<id>` is the industry with its sector benchmarks.

## Tests

- 22 adapter tests: parsing, newest date, grouping by block, an undecodable body, and a missing
  db, table or pull.
- 24 peers tests: deviation cases, tiers, medians, signs, sector scoring, sub-sector names,
  stale input, a byte-stable write, and `write_peers` never raising.
- 15 view tests: nav, the per-industry charts and their filters (with medians pinned by
  identical names), the industry page, tables, twins, escaping, 6 404 cases, a missing or
  invalid file, and no stars without a candidates file.
- Full suite, 2026-10-28: 1318 passed, ruff clean.

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
- **After the follow-ups.** With the filters, 41 of the 836 names pass on 2026-10-26, in 18
  industries:
  - Barang Baku: 8 names.
  - Makanan & Minuman, and Minyak, Gas & Batu Bara: 6 names each.
  - Perdagangan Ritel: 3 names.
  - Bank: BNGA and PNBN.

  BMRI and BBNI are not in the list. Their solvency is 0.58× and 0.72× the median, below the
  0.8× floor.
- **Check on 2026-10-28.** `/industries` answered 200 in 17 ms with 131 KB, and its twin lists
  the 18 industries.
- The Stockbit session had expired (refresh 401, `./run.sh login` needed in idx-method). That
  did not matter here because the 2026-10-26 pull is stored. The 16:30 pull will store
  nothing until the session is renewed, and none was stored on 2026-10-27 or 2026-10-28.

## Gaps

- **Names are inferred.** Sub-sector names come from anchor symbols, not from membership data.
  Real membership per IDX-IC sub-sector, dated per day, is idx-method V2 (`/screener` with
  universe scope `sub`, or `/emitten`).
- **Today only.** Every pull is today's cross-section (`/comparison` ignores a date), so there
  is no history yet. One date is stored per weekday pull from now on.

## Update (2026-10-29): no page per industry

`/industries/<id>` is gone (route, category chart, category tables, statement tables; it now
answers 404). Its financials timelines (P47-financials) moved into each industry card on
`/industries`, under the metric chart, for that card's passing names (at most 8, chart order),
plus a third timeline, profit growth y/y (gross, operating, net; none on a base at or below 0;
axis clipped to ±200%). On the 2026-10-28 file: 19 cards, 16 with financials, 3 with no
statements for their passing names.
