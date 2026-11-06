# P57-ui-portfolio — results

PLAN S36: `/portfolio` shows layer 5 from `out/layers/portfolio.json` (S33) and the trims and
adds of every `out/candidates/*.json`. Read-only, 127.0.0.1, no store opened. Account numbers
stay masked to their last 4 characters; this page shows no more than P53's doc does.

## What the page shows

- **Summary:** total, run day, newest statement or trade document, broker cash (not in the
  weights), unmapped value, model fingerprint, layer-5 notes, a link to `/flows`.
- **Weights against the stances' targets:**
  - per asset class: value, current % (sum of the buckets), target % (sum of every stance's own
    target for that asset), with an SVG bar (current filled, target as a tick, 0–100%);
  - per subject: the layer-5 buckets;
  - per stance: call, score, current, target, bar, delta, entry (style, tranches, spacing). The
    stances at 0% with no target and no entry are folded into a `<details>`.
- **By owner:** total, share of the household, buckets.
- **Accounts and holdings,** grouped by owner. Each account shows:
  - issuer and masked number, document type, as-of date;
  - statement age in days from the run (over 40 days warn, over 100 bad);
  - the roll-forward ("from 2026-10-31 through 1 trade doc", "from nothing through 8 trade
    docs");
  - cash, holdings, stated value and broker cash;
  - the statement check: matches, differs (with both totals), no stated total, or no check.

  Each account with lines gets a `<details>` with its holdings (quantity, value, weight in the
  household, bucket, or an *unmapped* chip). Lines valued at a trade price are marked †. Its
  `unheld` lines appear under a notice, and that `<details>` is open.
- **Unmapped:** total and lines.
- **Trims and adds** per candidate market: budget and unspent, trims (symbol, IDR, reason) and
  adds (rows with action `add` and a size: symbol, style, IDR, tranches, reason). Each market
  links to `/candidates/<MKT>`.
- `.json` twin: `{portfolio, problem, candidates: [{market, problem, trims, adds, budget_idr,
  unspent_idr}]}`.

Failures are a notice, never a 500:
- a missing file, invalid JSON, a non-object, or a builder stub (`error`) each show a notice;
  the trims card still renders;
- a payload the schema rejects shows a notice and still renders, with absent fields shown as
  "-".

## Tests

`tests/test_view_portfolio.py` (19) runs on the fixture `tests/fixtures/ui/portfolio/portfolio.json`
(schema-valid: two owners, an unheld line, an unmapped line, a 98-day-old statement, a check that
differs, trade-priced lines) and the existing `tests/fixtures/ui/candidates/` (IDN trims, AUS a
sized add). It covers:
- every section, totals and dates;
- asset-class and stance weights with bars, and the folded stances;
- owner shares;
- masked accounts, age chips, the check states and the roll-forward;
- holdings, unheld lines, trade-priced lines and unmapped lines;
- trims and adds, and the JSON twin;
- the missing, invalid, stub and schema-mismatch cases;
- masking a long account number again, escaping, and the route.

Full suite **1519 passed, 1 skipped** (worldbankscape checkout absent). Ruff is clean.

## Live (2026-11-06)

Run on copies of the S33 worktree's `out/` and the journal, with `assist status --port 8797`:
- `/portfolio` 200, 57,991 B; `/portfolio.json` 200, 43,597 B; no notice.
- Total Rp55,415,423 as of 11-02.
- By asset class: stocks 96.90% against 111.90% summed targets (IDN 96.9 plus SGP, TWN and USA
  at 5 each); bonds 1.79% against 26.80%; commodities 0% against 35%.
- 18 of 49 stances have a weight, a target or an entry.
- Owners: priskila 65.94%, tommy 34.06%.
- Accounts: 12, every number masked. The bnisek SOA (07-31) is flagged at 98 days. The Ajaib
  check matches, rolled from 10-31 through 1 trade doc. Her Stockbit account is rolled from
  nothing through 8 docs, with 63 lines marked †.
- Unmapped 0.
- IDN 10 trims (full trims of names failing their screen; BBNI and BMRI cut to the 5% cap), no
  adds. USA: budget Rp2,770,771 unspent, no adds.
- Screenshots in light and dark (headless Chrome); the colours follow the shared tokens.

## Decided differently or found

- **Target per asset class** is the sum of the stances' targets. The stances are sized one by
  one, so live targets add up to more than 100% (stocks alone 111.9%), and the page says so. The
  page does not normalise them: S36 only shows what the run computes.
- **Accounts are masked again on load.** Anything longer than "…1234" is cut to its last 4,
  for the page and the twin. A schema-mismatch notice names the JSON path and keyword, not the
  validator's message, because the message quotes the value (a test caught a full account
  number leaking that way).
- **Merged the S33 commits from main** (fast-forward to 48b8881) before starting, since the
  input file and its schema come from S33.
- Nav and cross-links are left to S37 (F8). Only the `^/portfolio$` route was added to
  `web.py`.
