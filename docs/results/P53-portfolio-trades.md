# P53-portfolio-trades — results

PLAN S32: layer 5 rolls each account forward from its latest loaded broker statement through
financer's loaded `trades` documents (Stockbit trade confirmations, Ajaib dailies), and carries
each document's owner. Live run 2026-11-06, read-only (`mode=ro` URI, through the adapter)
against `~/.financer/financer.db` (schema 9). The file's mtime and size were the same before and
after. Account numbers are deliberately left out of this page.

## Tests

- `tests/sources/test_financer.py` (new, 9): an account with trade documents only starts from
  nothing; buys add, a sell to zero drops the line, a sell below zero goes to `unheld`; the
  last trade price values a changed or new line, an unchanged line keeps the statement value;
  a superseded document and one dated on the statement date are ignored; `as_of` is the latest
  trade document; schema-8 store (no `owner`) falls back to `tommy`; a store without a `trades`
  table reads statements only; `rows()` includes rolled holdings; positional `Statement` still
  builds.
- `tests/layers/test_portfolio.py` (42, 8 new): `by_owner` adds up to `total_idr`; ARNA-like sale
  gone; negative line listed in `unmapped`, never subtracted; a rolled account's check compares
  the statement before rolling; notes; statement-only numbers unchanged; schema-8 fallback; a
  rerun gives byte-identical stance JSON (with the note in it).
- `tests/test_brief.py` and `tests/test_view_stance.py` (1 each): the note is shown once under the
  brief's stance table and as a Notes row in the `/stance` portfolio block, escaped.
- Fixtures: `tests/fixtures/financer/schema.sql` is now schema 9 (`documents.owner`, `trades`,
  `account_owners`); `seed.sql` gains an Ajaib-like account (portfolio, a daily on the statement
  date, a sale to zero, a buy) and a second-owner Stockbit account with two loaded and one
  superseded confirmation and no SOA; `schema8.sql` drops `owner` and `account_owners` again.
- Red first: 22 of the S32 tests failed (missing account, `owner`/`by_owner` attributes, old
  totals). Accept command (`tests/sources/test_financer.py tests/layers/test_portfolio.py
  tests/test_run_e2e.py` + ruff): 60 passed, ruff clean. Full suite: **1432 passed, 1 skipped**
  (worldbankscape checkout absent in the worktree; baseline 1413 passed, 1 skipped). No
  pre-existing failures.

## Live layer 5 (as of 2026-11-02, the latest trade document)

| Bucket | IDR | Weight | Statements only (before S32) |
|---|---:|---:|---:|
| IDN stocks | 53,697,910 | 96.90% | 17,262,110 (90.95%) |
| IDN bonds | 992,100 | 1.79% | 992,100 (5.23%) |
| IDN cash (RDN/bank) | 725,413 | 1.31% | 725,413 (3.82%) |
| **Total** | **55,415,423** | **100.00%** | **18,979,623** |

| Owner | IDN stocks | IDN bonds | IDN cash | Total |
|---|---:|---:|---:|---:|
| tommy | 17,162,110 | 992,100 | 722,750 | 18,876,960 |
| priskila | 36,535,800 | — | 2,663 | 36,538,463 |

- **Second owner's Stockbit account:** 8 loaded confirmations (16–30 Oct), no SOA, so it starts
  from nothing: **63 IDN stock lines, Rp36,535,800 at last trade prices**, all 63 priced at a
  trade. Note in the brief and `/stance`: "financer stockbit (priskila): valued at last trade
  price: 63 lines".
- **Ajaib:** the 2026-11-02 daily sells ARNA (200 shares, Rp100,000 on the 10-31 portfolio); the
  line is gone, 12 → 11 lines, Rp18,154,210. Its check (statement lines vs printed total, before
  rolling) still matches at Rp18,254,210. The other 11 lines keep the statement's values.
- **Statement-only accounts:** all 10 other accounts (4 RDN, Tahapan savings, the second owner's
  Mandiri savings, and 4 broker accounts with no holdings) have holdings, cash and dates
  identical to the pre-change adapter run on the same file.
- Weights add to 100.000000. Unmapped: none. Stale inputs: none.

## Where the plan was wrong or incomplete (amended in S32)

- **"About 37.15M at trade prices"** is her trades' gross flow (buys 37,992,900 − sells 838,500
  = 37,154,400), not what the rule gives. The rule values each line at its symbol's last trade
  price: 36,535,800. The 0.62M gap is price moves between a symbol's earlier fills and its last
  one. Payment due (37,223,486) adds the fees.
- **Notes need a path to the brief and the page.** `Weights.notes` → optional
  `portfolio.notes` in the stance schema (absent when empty, so existing outputs are unchanged)
  → `brief.py` and `views/stance.py`. That touched `layers/types.py`, `stance.py`,
  `schema/stance.schema.json`, `tests/test_brief.py` and `tests/test_view_stance.py`, outside the
  slice's `owns`. The model fingerprint hashes only the stance config, so it is unchanged.
- **Two extra `Statement` fields:** `unheld` (lines sold below zero, kept out of `holdings` so
  layer 4's `holdings_from` never sums a negative) and `statement_holdings_idr` (the statement's
  lines before rolling, for the check). `StatementCheck` gains `account`, since one issuer can now
  have two accounts in the same run; an account with trades and no statement has no check.
- `documents.owner` is nullable in financer (NULL = held for review). The adapter reads a NULL
  as `unknown`, never guessed; none were present live.

## Known limits

- **Cash does not move with the trades.** A rolled buy adds stock but the RDN balance is still
  the last statement's, and a sale's proceeds appear only with the next RDN statement. Today
  that understates Ajaib's cash by the ARNA proceeds, and the second owner's RDN (about 12.8M)
  is invisible until financer loads her RDN statement (her Gmail filter, financer side).
- **Last trade price, no price feed.** Her 63 lines are priced at their October fills; they
  move only with new trades or her first SOA.
- **Date basis of Stockbit SOA holdings** (trade vs settlement date) is still unknown until her
  first SOA arrives; the rule assumes trade date.
- A bond line changed by a trade would be valued at quantity × price, which is wrong for bonds
  (priced per 100 face). No trade document touches a bond today.
