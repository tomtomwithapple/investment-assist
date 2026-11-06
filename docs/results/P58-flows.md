# P58-flows — results

PLAN S38: `/flows`, where the household's money moved. `assist flows` reads financer's loaded
documents (read-only, through `FinancerSource`), matches transfers between the household's own
accounts and writes `out/flows/<YYYY-MM>.json` for the latest 12 months with data, plus
`out/flows/index.json` (`schema/flows.schema.json`). Live run 2026-11-06 against
`~/.financer/financer.db` (schema 9) into a scratch `out/p58-scratch/` (gitignored); the
store's mtime and size were the same before and after. Accounts appear by their last 4
characters, people by their owner key only.

## Built

- `FinancerSource.movements(start, end)`: every `transactions` row of a `loaded` document (any
  doc type), and **one** settlement per `loaded` trades document: minus `closing_minor` (a buy's
  payment due is a credit to the broker account, a sale's proceeds a debit), dated on its
  trades' latest `settle_date`; the document's fee rows are never read. Also `ledgers()`
  (opening and closing per loaded statement) and `owner_map()` (`account_owners`). An account is
  `coalesce(nullif(account_ref, ''), card_last4, '')`.
- `assist/flows.py` (pure): `match` pairs a debit with a credit of another account, equal to the
  rupiah (minor units rounded half up), at most 3 days apart, one to one, greedy by smallest
  gap, then date, then document id. A card's debits (purchases) are spending and never a
  transfer candidate. Unpaired debits naming a household member (from the gitignored
  `config/household.local.yaml`, case-insensitive on `raw_description`) are "to <owner>,
  receiving account has no statement in financer"; unpaired trades settlements "paid from RDN
  (statement not loaded)" (a sale: "proceeds to RDN ..."); everything else is external in/out per
  account and owner. Names and full account numbers never reach the files.
- `stale_inputs` per month: an account with a statement dated the month before and none this
  month, and an account financer maps to an owner with no statement at all.
- `views/flows.py` + routes `/flows` (latest month in the index) and `/flows/<YYYY-MM>` (only a
  month the index lists; the file name comes from the index entry). SVG: one column per owner,
  an arrow per account pair of matched transfers (width linear in the amount), dashed arrows
  to/from a "no statement in financer" box per owner. Tables of matched transfers, unmatched
  items, external totals and accounts; `.json` twin = the month file; notice, not 500, when
  files are missing or unreadable. No nav link (F8).
- `config/household.example.yaml` (invented names); `.gitignore` ignores
  `/config/household.local.yaml`, which exists only locally.

## Tests

- `tests/test_flows.py` (27), `tests/test_view_flows.py` (17), `tests/sources/test_financer.py`
  (+6, 15), `tests/test_web.py` (+1). Fixture `tests/fixtures/flows/` (transactions DDL, an
  invented household seed, invented names) on top of `tests/fixtures/financer/schema.sql`.
- Red first: collection failed on the missing `assist.flows`, 6 adapter tests on missing
  `movements`/`ledgers`/`owner_map`, the web test on `/flows` 404.
- Accept command: 85 passed, ruff clean. Full suite: **1483 passed, 1 skipped**
  (worldbankscape checkout absent in the worktree; baseline 1432 passed, 1 skipped). No
  pre-existing failures.

## Live, 2026-10

| | n | IDR |
|---|---:|---:|
| matched transfers | 10 | 13,066,567 |
| — Ajaib RDN ·8116 → Ajaib dailies (buys) | 4 | 2,284,850 |
| — Ajaib dailies (sales) → Ajaib RDN ·8116 | 3 | 2,422,100 |
| — Ajaib RDN ·8116 → BCA Tahapan ·5654 | 3 | 8,359,617 (1.45M 10-08, 4.0M 10-19, 2.91M 10-31) |
| unmatched named debits (Tahapan ·5654) | 6 | 82,288,796 |
| — to priskila: 12, 14, 19, 23, 31 Oct | 5 | 70,000,000 (10M, 40M, 4M, 10M, 6M) |
| — to tommy: card payment 23 Oct | 1 | 12,288,796 |
| unmatched settlements (her Stockbit TCs) | 6 | 34,146,218.04 |

- All 7 October Ajaib dailies match their RDN debit or credit to the rupiah on the settle date
  (gap 0), each as one settlement, never its fee rows.
- Her 8 TCs are all unmatched: 6 settle in October, 2 on 11-02 and 11-03 (2026-11 file,
  3,077,267.58), together **37,223,485.62**, financer's payment-due total. 2026-11 also holds
  Ajaib's 11-02 daily (settles 11-04, 99,749), unmatched until the November RDN statement.
- Stale for 2026-10: `cimb_cc (tommy)`, `mandiri_consolidated ·6353 (priskila)`, `mandirisek
  ·B21C (tommy)` (no October statement yet), and `bca_rdn ·4750 (priskila): mapped in financer,
  no statement loaded`.
- **Mandiri savings → Mandiri card** match in every month where both statements exist:
  2025-12 to 2026-09, 1–2 a month (e.g. 2026-09: 2, 10,053,745). October has no Mandiri savings
  statement yet.
- Across the 12 months: 135 matched transfers; named unmatched from 2026-05 on (none before),
  mostly to priskila.
- Page: `/flows` 200 (opens on 2026-11, the latest month with data), `/flows/2026-10` 200
  (19 kB), `/flows/2026-10.json` 200 and equal to the file, `/flows/2024-01` and
  `/flows/..%2Findex` 404. Checked by headless Chrome screenshot in light and dark.

## Where the plan was wrong or incomplete (S38 amended in place)

- **"Tommy's BCA savings → his Ajaib RDN transfers match."** In October the matched transfers
  between them run the other way, RDN ·8116 → Tahapan (3, 8.36M); Tahapan → RDN happened in
  March and April (23M, 2M). The 4M of 10-19 came into Tahapan from the RDN and went out the
  same day to priskila.
- **Six named debits, not five.** The five to priskila are as expected; the sixth is his own
  BCA card payment (`KARTU KREDIT/PL`, 12,288,796, naming him), whose credit is on the card
  statement of 11-16, not loaded yet (latest 10-16). It matches with no code change once
  that statement loads.
- **8 TC settlements are split across months** by settle date: 6 in 2026-10, 2 in 2026-11.
- **Two more adapter methods**, `ledgers()` (opening/closing) and `owner_map()` (accounts
  mapped to an owner with no statement, e.g. her RDN ·4750). The plan listed `movements()` only.
- **Card purchases are never transfer candidates**, otherwise a purchase could pair with a
  same-amount credit elsewhere; a card's credit (a payment) can be.
- **A settlement's sign:** minus `closing_minor` is a credit to the broker account for a buy,
  so "a debit in A pairs with a credit in B" covers RDN → broker; a sale pairs the other way.
- **`/flows` opens on 2026-11**, a partial month (3 unmatched settlements, every account
  "no statement dated 2026-11"), because it is the latest month with data.
- Fixtures live in `tests/fixtures/flows/` (plan.yaml `owns`), not `tests/fixtures/financer/`;
  `tests/test_web.py` gained one test (outside `owns`; the accept command runs it).

## Known limits

- Matching is amount and date only. Small amounts can pair by coincidence (e.g. a 4,500
  mandirisek → stockbit "transfer" in 2026-05); broker SOA ledger rows count as movements too.
- financer stores Tommy's CIMB card with no account ref and, on some statements, no last 4, so
  it shows as two accounts (`cimb_cc ·8086` and `cimb_cc`).
- Account ids are issuer-last4-owner; two accounts of one issuer and owner with the same last
  4 would merge.
- Arrowheads hide under the widest strokes.
