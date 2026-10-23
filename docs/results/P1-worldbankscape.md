# P1-worldbankscape — results

Live run on 2026-10-23, read-only against `../worldbankscape/out` (export `generated_at`
2026-10-22T21:01:59Z, schema 1.2.0), with the schemas read from `../worldbankscape/schema` at
runtime.

## What it reads

`src/assist/sources/worldbankscape.py` → `WorldbankscapeSource(out_dir, schema_dir=None)`:

- `load(subjects=None, assets=None) -> Layer1(scores, stale_inputs, problems, attribution,
  disclaimer, generated_at)`. It reads `index.json` first and loads only the payloads it lists. The
  index is validated against `index.schema.json` and each payload against `score.schema.json`,
  both from worldbankscape's own `schema/` (default `out/../schema`).
- If a payload's sha256 differs from its index entry, the index is re-read once, because a publish
  may have landed between the two reads. This is what worldbankscape's `schema/README.md` asks
  readers to do.
- A bad payload is skipped and listed in `stale_inputs` as `worldbankscape <path> (error|missing)`.
  Bad means unreadable, failing the schema, with a sha mismatch that stays after the re-read, or
  with a subject or asset class that does not match its entry.
- If `out/`, `index.json` or the schema is missing, `SourceUnavailable` is raised as missing. An
  invalid index is raised as error.
- `score(subject, asset)` returns None when there is no entry. That means "not applicable", and
  no neutral 50 is filled in.
- `ranked(s)` gives worldbankscape's ranking key, 50 + (score − 50) × confidence. Use it for
  ordering only.
- `rows()` follows the `Source` protocol. Each series id is `WBS.<SUBJECT>.<asset>.<field>`, where
  field is `score`, `confidence`, `raw_score` or `coverage`. Both the date and `as_of` are the
  payload's `as_of`.

## Live numbers

- **144 scores loaded**, 0 stale or invalid. That is 27 countries plus 14 commodities, all with
  `as_of` 2026-10-23, giving 576 rows.
- **Scores per asset class:** business 27, property 27, bonds 26, currency 25, stocks 25,
  commodities 14. The gaps are worldbankscape's exclusions by design, not missing data: TLS has
  no bonds; USA and TLS have no currency; BRN and TLS have no stocks.
- **Confidence:** every score has one, and the lowest is TWN property at 0.115. Five scores fall
  below the 0.5 "don't rank as a top pick" line: TWN property 0.115, LAO property 0.219, MMR
  property 0.219, VNM property 0.225 and MMR stocks 0.231.
- **Flags:** 47 flags on 38 payloads, 8 critical, 23 warn and 16 info.
  - Critical `high_gov_debt`: USA, JPN, FRA, ITA and CAN bonds.
  - Critical `large_fiscal_deficit`: BRN bonds.
  - Critical `external_debt_high`: LAO bonds and LAO currency.
- **IDN:** bonds 58.0 (0.97), stocks 53.6 (0.89), currency 52.5 (0.97), property 66.0 (1.0),
  business 55.7 (0.968). Each value is the score, with its confidence in brackets. IDN bonds lists
  `yield_spread (missing)` in its stale inputs.
- **Targets (score / confidence):**

  | | bonds | stocks | currency |
  |---|---|---|---|
  | USA | 48.1 / 1.0 | 61.3 / 0.97 | none (excluded) |
  | JPN | 59.2 / 1.0 | 50.7 / 1.0 | 52.1 / 1.0 |
  | DEU | 56.3 / 1.0 | 45.4 / 1.0 | 50.4 / 0.946 |
  | SGP | 60.1 / 0.747 | 66.4 / 0.86 | 60.3 / 0.88 |
  | AUS | 61.2 / 1.0 | 59.5 / 0.89 | 47.1 / 1.0 |
  | KOR | 66.4 / 1.0 | 53.6 / 1.0 | 57.9 / 1.0 |
  | TWN | 65.9 / 0.707 | 60.5 / 0.6 | 58.0 / 0.576 |

- **Commodities (score, confidence 1.0 for all):** COAL_AUS 59.8, NICKEL 42.3, PALM_OIL 54.3,
  TIN 49.3, BRENT 66.2, GOLD 31.1.
- **Store untouched:** the test suite asserts that no mtime changes. The live run only reads.

## Where the sibling differs from our notes

- **Asset classes:** worldbankscape publishes 6, adding `business` and `property` to
  stocks/bonds/currency/commodities. The adapter keeps all of them; the stance layer picks the
  ones it needs.
- **No EU aggregate:** the euro area is only available as its members: DEU, FRA, ITA, ESP and NLD.
- **Model versions differ by asset class:** the index's top-level `model_version` is 0.4.0, but
  it is only the highest among the entries. Compare scores only within the same per-entry
  `model_version`. `AssetScore` does not carry it, so a later slice that needs it should read it
  from the index.
- **`out/quality.json`:** status green on this run. It is informational and outside the contract,
  so the adapter does not read it.
- **Schema copies agree:** `schema/worldbankscape/score.schema.json`, vendored by S1, is
  byte-identical to the live one.
- **Worktree path quirk:** inside a git worktree `REPO.parent` is not `../Projects`, so live runs
  from a worktree need `ASSIST_SIBLINGS_ROOT=/Users/tomtomtomtom/Projects`, or
  `ASSIST_WORLDBANKSCAPE_OUT`.
