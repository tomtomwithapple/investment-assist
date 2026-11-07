# F9-docs (PLAN S43): docs refresh to 2026-11-07

Docs only; no code, rule, band, tilt, benchmark or ladder changed.

## PLAN.md

- STATUS *Last updated* 2026-11-07: phase J done (S41 fingerprint by AST, cumulative only below
  12 scored weeks; S42 `rebalance_pt` / `tilt_pt`, schema 1.1.0, Telegram "Paper only, not an
  order"; live IDN stocks −48.9pt, IDN bonds +30.2, USA stocks +20.0, all rebalance, tilt 0);
  model `sha256:b836b881ad37…` on main, no run since, so the next run opens one new segment;
  1633 tests. The two oldest *Earlier* entries (S32, P48–P50) were dropped (they stay in
  Progress); phases H, I, J named as done.
- launchd: both jobs are installed and loaded on this Mac (was "not installed").
- *Next up*: phase K planned by the user (G1 historical walk-forward gate with placebo, G2 home
  IDN regime), not yet written; open ops question on what refreshes the fetcher stores that have
  no launchd agent here (only bisfetcher.refresh, dbnomics.refresh/serve, worldbankscape.daily,
  idxscape.phei are installed).
- Phase table: J 3 / 3.
- Open data gaps: jquantster bars end 2026-08-14 (stale around 11-22); openkrx no `data/parquet`,
  R1 still pending; singstat and FRED struck as fresh again (doctor 2026-11-07); satudatascape
  still missing; idx-method valuation history and industry membership closed by `c432999`
  (unblocks S15, no adapter reads it yet).
- S41, S42, S43 ticked with *Done 2026-11-07* notes; Progress rows for S41, S42, S43.

## README.md

- Phase line: A–D and G–J done; E 0 / 2 (S15 open, S31 live verdict open), F 7 / 8 (S22 open).
- *What a run does*: the Telegram message's content (paper-only header, undervalued lists, sized
  names per market with the rebalance / tilt label); the brief's stance table shows the split;
  the paper track shows cumulative only below 12 scored weeks.
- *Data gaps*: as of the 2026-11-07 doctor (11 present, 1 stale, 2 missing); the "no JCI
  fetcher" and "0 weeks scored" gaps replaced by the IGSYC hole; FRED and singstat no longer
  stale; jquantster and openkrx dates updated.

## CLAUDE.md

- openkrx R1 "still pending 2026-11-07"; coverage gaps heading as of 2026-11-07; gap 6: JCI P/E
  is wired (cap-weighted earnings yield over idx-method's snapshot, 963 names).

## Checks

`uv run pytest -q`: 1633 passed. `uv run ruff check .`: clean.
