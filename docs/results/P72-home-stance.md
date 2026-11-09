# P72-home-stance (PLAN S53): the home (IDN) regime in the stance

Date: 2026-11-09. Heuristic, not investment advice. Open question 8 as fixed on 2026-11-07; no
phase K number changed.

## What changed

- **`stance.py`** (model 0.5.0, stance schema 1.2.0). `HOME_ASSETS` = IDN stocks and IDN bonds,
  `HOME_SHIFT_PT` = −5. On those two stances, a home risk_off ladders the adds *and* trims
  (`LADDER_TRANCHES` × `LADDER_SPACING_DAYS`, unchanged). This is an entry style, not a stance
  change, so it needs no gate. `home_shift` moves the score −5 only if
  `home_regime.HOME_SHIFT_ADOPTED` (False since P71), and by 0 when the global regime is
  already risk_off (−5 in all, not −10). `apply_limits` keeps a laddered trim on a home
  risk_off. Each IDN leg carries `home_regime` {state, points, drivers, stale_inputs}. Its
  stale inputs stay in the block and do not lower the confidence, because the home regime
  moves no score while it is not adopted. Bands, `TILT_PT`, `BENCHMARK_PCT` and `TRANSITION_PT`
  are unchanged. `MODEL_CONFIG.home_regime` records all of this, so it is fingerprinted.
- **`pipeline.py`**. `read_home` (never raises: a failure becomes one run-level stale line)
  and `home_sources` (JCI, idxscape, and the P65 USD/IDR splice). `Layers.home`,
  `RunResult.home`. `build_stance(..., home=)` and `base_stance(..., home)` for the rule
  gate's base. The run's `regime` journal record carries `home`.
- **`layers_out.py`**: layer schema per kind (`SCHEMA_VERSIONS`), regime 1.1.0. `regime.json`
  gets a `home` block: state, points, drivers, stale inputs, the rule's numbers (as written in
  `home_regime.py`), and each of the four inputs with its points, label, value, newest date and
  a 52-week Friday line (`home_history`: each Friday's value as `home_inputs` computes it that
  day). No home regime means no block. A failing history read leaves the block in place with
  empty lines and adds a `home history failed: …` stale line. 1.0.0 files still validate.
- **Schemas**: `stance.schema.json` 1.2.0 adds optional `home_regime`;
  `layers/regime.schema.json` adds optional `home`.
- Tests (written first): a home risk_off with a neutral global regime ladders an IDN add within
  10pt of its target; trims are laddered too; a USA stance is unchanged; no shift while not
  adopted; −5 not −10 with both regimes off (adoption monkeypatched); the regime file carries the
  block; the home history matches `home_inputs` on each Friday of the real 2026-10 JCI fixture;
  failure paths. Full suite 1795 passed, 1 skipped; ruff clean.

## Live (scratch `Paths.under`, `ASSIST_SIBLINGS_ROOT=/Users/tommy/Projects`, run date 2026-11-09, `send=False`)

- Run ok in 353 s (warm `out/rules/`), model `sha256:56314c66842c…`. The global regime is
  risk_off.
- **Home regime: risk_off, 2 points**, all from the JCI: −17.5% against its 20-day high (newest
  close 11-05). IDX foreign z −0.72 (11-05, 0 points), USD/IDR +1.15% over 20 fixings (11-05, 0),
  non-resident SBN +0.45% over 20 days (11-04, 0). All four inputs are fresh, none is stale.
- IDN stocks: neutral 43.5, ladder 3×10d, −48.9pt trim. IDN bonds: neutral 49.0, ladder 3×10d,
  +30.2pt. Both legs were already laddered by `TRANSITION_PT` (each is more than 10pt from
  target), so the home ladder changes no entry today; it would on a smaller gap. No score moved
  (`HOME_SHIFT_ADOPTED` False).
- `regime.json` is schema 1.1.0 with 52 weekly points per home input. The JCI line reads −12.2%
  (10-23), −18.3% (10-30) and −17.5% (11-06). The journal `regime` record carries `home`.
