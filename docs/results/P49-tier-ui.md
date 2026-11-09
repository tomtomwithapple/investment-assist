# P49-tier-ui — PLAN S31: /industries draws the top tier

Built (`src/assist/views/industries.py`, `tests/test_view_industries.py`):
- **Schema 4 page.** `/industries` opens with a card **Top tier by industry**: per industry
  (ordered by its best composite, then label), Tier A then Tier B rows with tier chip, symbol
  (★ when on the S20 list), name, composite, five small pillar bars (value, quality, growth,
  health, momentum; 0-100, value on hover; a missing pillar is an empty dashed box), cap tier.
  Tier B rows are muted (text and bars). The industry name prints on the first row of its group.
- **Industry cards** (one radio tab each, only industries with picks): header with sector,
  A/B counts, gated of n names, the peer group ("ranked within the industry (8 names past the
  gates)" or "ranked within sector X (n names past the gates)"), D/E cap; a picks table (rank,
  Tier A then B, B muted) where a name passing the S30 filter carries the chip "beats the
  industry average on PE, PBV and ROE"; gate failures counted by reason (most frequent first,
  "No name failed a gate." otherwise); then the metric chart and the financials timelines drawn
  for the picks (the chart label beside each name is "Tier A 78.3 · big", Tier B muted).
- **Industries without picks** are not tabs; one collapsed card "N industries without a top
  tier" lists each with why: no name passes the gates (with the gate counts), none has enough
  pillars, or the best composite under 50. A file with no picks at all shows a notice instead
  of the table.
- **Schema 3** (`schema_version` < 4 or absent): a notice ("predates the top tier (schema 3):
  run `assist industries`") and the S30 view unchanged. Junk tier fields (non-list picks, a
  string composite, missing peer group) render without a 500.
- **Twin** (`/industries.json`, schema 4): `schema_version`, `fingerprint`, `rows` (the table:
  industry, symbol, name, pick, rank, composite, pillars as score or null, cap tier, starred,
  styles, beats_average, peer_group level, …) and `industries` in page order (peer group, picks,
  gated, gate_failures, best, der_cap). Schema 3 twin: the old rows plus `notice`.
- `rows` split into `passes_filter` (also used for the chip) and `_row`; behaviour unchanged.

## Decisions
- No-pick industries listed compactly rather than as empty tabs or table rows.
- Pillar bars vertical, 10×18 px each, so the table stays narrow; header "Pillars V Q G H M".
- The JSON twin carries values from the file as raw data (it is `application/json`); escaping
  applies to HTML. `test_escaping` (schema 3) now checks the twin parses instead of asserting
  `<script>` is absent from it: in schema 4 the twin lists every industry, labels included.
- Tie on best composite: label, then id.

## Tests
New (13): table rows and order (MNF1, MNF2, THN1, MIX1 by 78.31/56.55/52.57), Tier B muted,
sector fallback label and gate counts, filter chip and charts/financials of the picks only,
industry without picks, no picks at all, schema 3 notice and twin, schema 3 without a version,
junk tier fields, escaping of `<script>` in a name, cap tier, gate reason, industry and peer group
labels, pillar bars, the tier chart legend. Fixtures: tests/fixtures/tiers/ (`industry.json`,
`no_tier_a.json`) plus one illiquid name, through `peers.build`.

Changed existing tests: the S30 tests (`out` fixture, `_ranked_out`, `test_page_without_statements`)
now write the payload as schema 3 (`_schema3` strips the tier fields), since `peers.build` writes
schema 4 and the S30 view is now the schema 3 fallback; their assertions are unchanged except
`test_escaping` above.

`uv run pytest -q tests/test_view_industries.py tests/test_web.py`: 67 passed.
`uv run pytest -q`: 1385 passed. `uv run ruff check .`: clean.

## Rendering
Checked by headless Chrome screenshots of the page rendered from the fixture payload, light and
dark (dark forced by turning the `prefers-color-scheme: dark` blocks on), plus the schema 3
fallback: table, muted Tier B, pillar bars with the dashed missing box, chip, chart and notice
all read in both themes.

## Live
Not run: idx-method's `store/data/stockbiter.db` is absent on this Mac, so there is no real
schema 4 `out/industries/IDN.json`; fixtures only. Any existing schema 3 file shows the notice
and the S30 view until `assist industries` runs where the db is present.

## Live check 2026-11-09

`assist status` on 127.0.0.1:8790: `/` 200, `/industries` 200 (2,771 B), `/industries.json`
200 (`rows: []`, problem "no peer comparison in out/industries/ yet"), an unknown
`/industries/<id>` 404, `/status` and `.json` 200; server stopped, port free. No schema 4 file
exists (P48: `api_raw` empty on this Mac), so there is no `/industries/<id>` to open and the
tier table is not drawn live yet.
