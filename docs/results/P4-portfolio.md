# P4-portfolio — results

PLAN S4: financer adapter + layer 5 weights by country × asset class. Live run 2026-10-23,
read-only (`mode=ro` URI) against `~/.financer/financer.db` (schema version 8). The file's mtime
was unchanged by the run. Account numbers are deliberately left out of this page.

## Tests

`tests/layers/test_portfolio.py`: 34 tests over a fixture store built from the real
`documents`/`holdings` schema (`tests/fixtures/financer/`). Full suite: 385 passed, 1 skipped
(worldbankscape checkout absent in the worktree); ruff clean.

## Live layer 5 (latest loaded statement per account, newest 2026-09-30)

| Bucket | IDR | Weight |
|---|---:|---:|
| IDN stocks | 17,876,086 | 60.36% |
| IDN cash (RDN/bank) | 11,741,615 | 39.64% |
| IDN bonds | 0 | — |
| **Total** | **29,617,701** | **100.00%** |

- Unmapped: **none** in the latest statements. Across every holding ever stored (412 distinct
  symbol, name and currency lines), the rules map 407 to IDN stocks, 3 to IDN bonds (FR0040, FR0081, PBS036),
  1 to IDN cash (`IDR`), and leave 1 unmapped: a mutual fund printed without a code
  (*Reksa Dana Indeks BNI AM Indeks IDX30*, last held 2024-06). It would be listed, not counted.
- Stale inputs: none (every account with value has a 2026-09-30 statement).

## Statement totals

| Account (issuer) | Latest statement | Lines | Sum of lines (IDR) | Broker's printed total | Match |
|---|---|---:|---:|---:|---|
| ajaib (portfolio) | 2026-09-30 | 15 | 17,876,086 | 17,876,086 | yes |
| bca_rdn (4 RDN/savings accounts) | 2026-09-30 | — | cash 11,741,615 | — | n/a |
| bcasek | 2026-09-30 | 0 | 0 | none printed | n/a |
| mandirisek | 2026-09-30 | 0 | 0 | none printed | n/a |
| stockbit | 2026-09-30 | 0 | 0 | none printed | n/a |
| bnisek | 2026-07-31 | 0 | 0 | none printed | n/a (empty, so not stale) |

Ajaib's statement closing balance (Rp11,623,305) is its RDN; the RDN's own bank statement says
Rp11,623,472 (Rp167 apart, interest/rounding). It is counted once, from the bank statement, and
kept apart as `broker_cash_idr`.

## Where financer differed from our notes

- **No `accounts` table, no `holdings.account_id`.** financer's PLAN §3 sketch is out of date. The
  account is `documents.account_ref` (+ `issuer`); a holding belongs to its statement
  (`document_id`). "Latest as_of per account" is implemented as the latest **loaded** statement
  per `(issuer, account_ref)`; `status = 'superseded'` statements are skipped.
- **Latest statement, not latest holdings.** Taking `max(holdings.as_of)` per account would
  revive sold-out positions: stockbit's last holdings are 2024-06, bcasek's 2025-03,
  mandirisek's 2026-03, bnisek's 2026-01, yet each has a later statement with none.
- **Money is minor units ×100** (`money.MINOR_SCALE = 100`), so IDR = `*_minor / 100`.
- Broker cash appears in two ways: as a holdings line with symbol `IDR` (stockbit; counted as
  IDN cash), and as the statement's closing balance (= the RDN; not counted, see above).
- `stockbit` documents have `account_kind = 'liability'` though they are broker statements; the
  adapter selects by `doc_type` (`portfolio`, `broker_soa`, `savings_statement`), not by kind.
  Credit-card statements are not read.

## For later slices

- `assist.layers.portfolio.current_weights()` → `(Weights | None, stale_inputs)` for `stance.py`;
  cash is keyed `("IDN", "cash")`, as S5 tests already assume.
- `Weights.unmapped` entries read `"<symbol/name> at <issuer> (Rp<value>)"`.
- All mapped lines are IDN today; a foreign-currency line or a non-IDX code goes to unmapped.
