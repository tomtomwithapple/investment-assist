# P83-foreign-walk (PLAN S65): the foreign override walk-forward on the real stores

Date: 2026-11-09. Branch `phase-l`. Docs only: no code, no threshold, weight, band or window
changed. Heuristic, not investment advice.

## Setup

- **History:** P28 replayed point in time per market (S63: stores read once, FRED GDPC1 at its
  vintage, AUS `fx` on the MAS cross before 2023-04).
- **Returns:** forward returns in IDR, unhedged (S64): currency is the move in IDR per local
  unit, bonds are the local 10Y bond return × that move, and USA stocks are SPY × IDR per USD.
- **Gate:** `eval/override_gate.py` (S59) with the accepted numbers: horizon / stride / block
  3, `MIN_N` 10, t ≥ 2.0, p ≤ 0.05, 1,000 shuffles, 20 controls. Holm runs per subject over its
  gated tests (USA 6, the others 4), plus the CLI-zeroed rerun. SGP has no CLI, so zeroed
  equals stored.
- **Run:** `override_gate.refresh` for all six subjects into a scratch `out/overrides/` with
  the main checkout's journal (read-only). It took 69 s: IDN 6 s, the five markets in one
  replay. The live monitor is 0 / 0 everywhere (no record carries these fingerprints yet).
- **Override fingerprints at S65:**
  - IDN `sha256:708f4d9d9523…`, USA `20a8da05aa16…`, JPN `e6452ba0b183…`, EMU `680f44aea796…`,
    AUS `e4d9a74eed70…`, SGP `66f4d505f0ef…`;
  - they key the files the fan-in run writes.

## Verdict per subject × asset × side (horizon 3, the gate)

Signed t: positive means the side works as claimed. IDN is repeated from P78 for completeness.

| Subject | Asset | Side | Window | On / off | t | p | Control t | Holm (rank / m, needs p ≤) | CLI zeroed t, p | State |
|---|---|---|---|---|---|---|---|---|---|---|
| IDN | stocks | up | 2017-07 → 2026-07 | 24 / 13 | 1.08 | 0.186 | −0.30 | 3/6, 0.0125 | −0.35, 0.636 | failed |
| IDN | stocks | down | 2017-07 → 2026-07 | 12 / 25 | 0.92 | 0.225 | −0.29 | 4/6, 0.0167 | −0.78, 0.704 | failed |
| IDN | bonds | up | 2017-07 → 2024-08 | 13 / 16 | −0.99 | 0.810 | 0.04 | 5/6, 0.0250 | −0.23, 0.583 | failed |
| IDN | bonds | down | 2017-07 → 2024-08 | 15 / 14 | −1.03 | 0.821 | 0.15 | 6/6, 0.0500 | −0.97, 0.792 | failed |
| IDN | currency | up | 2017-07 → 2026-07 | 13 / 24 | 1.75 | 0.122 | −0.13 | 2/6, 0.0100 | 1.69, 0.087 | failed |
| IDN | currency | down | 2017-07 → 2026-07 | 15 / 22 | **2.47** | **0.047** | −0.42 | 1/6, 0.0083 | 0.95, 0.229 | failed |
| USA | stocks | up | 2016-01 → 2026-07 (SPY) | 22 / 21 | 1.01 | 0.184 | 0.21 | 2/6, 0.0100 | 1.17, 0.135 | failed |
| USA | stocks | down | 2016-01 → 2026-07 | 16 / 27 | 1.66 | 0.078 | −0.01 | 1/6, 0.0083 | 1.45, 0.102 | failed |
| USA | bonds | up | 2005-04 → 2026-07 | 37 / 49 | −0.43 | 0.647 | 0.06 | 3/6, 0.0125 | −0.26, 0.582 | failed |
| USA | bonds | down | 2005-04 → 2026-07 | 40 / 46 | −0.63 | 0.688 | 0.05 | 4/6, 0.0167 | −0.17, 0.548 | failed |
| USA | currency | up | 2005-04 → 2026-07 | 44 / 42 | −0.56 | 0.698 | −0.02 | 5/6, 0.0250 | −0.94, 0.784 | failed |
| USA | currency | down | 2005-04 → 2026-07 | 30 / 56 | −0.78 | 0.785 | 0.12 | 6/6, 0.0500 | −0.28, 0.617 | failed |
| JPN | bonds | up | 2005-04 → 2026-07 | 28 / 58 | 1.30 | 0.087 | −0.14 | 1/4, 0.0125 | 0.70, 0.282 | failed |
| JPN | bonds | down | 2005-04 → 2026-07 | 40 / 46 | 0.04 | 0.509 | −0.18 | 3/4, 0.0250 | −0.26, 0.613 | failed |
| JPN | currency | up | 2005-04 → 2026-07 | 43 / 43 | 0.90 | 0.197 | −0.19 | 2/4, 0.0167 | 0.67, 0.252 | failed |
| JPN | currency | down | 2005-04 → 2026-07 | 37 / 49 | −0.39 | 0.645 | −0.18 | 4/4, 0.0500 | −0.92, 0.825 | failed |
| EMU | bonds | up | 2005-04 → 2026-05 | 39 / 46 | −1.14 | 0.853 | 0.06 | 4/4, 0.0500 | −0.74, 0.748 | failed |
| EMU | bonds | down | 2005-04 → 2026-05 | 39 / 46 | −0.15 | 0.581 | −0.21 | 3/4, 0.0250 | 0.24, 0.428 | failed |
| EMU | currency | up | 2005-04 → 2026-07 | 49 / 37 | 0.57 | 0.319 | −0.10 | 2/4, 0.0167 | 0.29, 0.395 | failed |
| EMU | currency | down | 2005-04 → 2026-07 | 31 / 55 | 0.93 | 0.208 | −0.01 | 1/4, 0.0125 | 0.42, 0.365 | failed |
| AUS | bonds | up | 2013-12 → 2026-07 | 29 / 22 | 0.50 | 0.298 | −0.08 | 1/4, 0.0125 | −0.32, 0.626 | failed |
| AUS | bonds | down | 2013-12 → 2026-07 | 18 / 33 | 0.11 | 0.448 | −0.05 | 2/4, 0.0167 | −0.18, 0.589 | failed |
| AUS | currency | up | 2013-12 → 2026-07 | 23 / 28 | −1.50 | 0.924 | 0.08 | 4/4, 0.0500 | −1.28, 0.903 | failed |
| AUS | currency | down | 2013-12 → 2026-07 | 25 / 26 | −0.84 | 0.814 | 0.03 | 3/4, 0.0250 | −0.80, 0.810 | failed |
| SGP | bonds | up | 2006-04 → 2026-07 | 43 / 39 | −0.73 | 0.748 | 0.13 | 3/4, 0.0250 | −0.73, 0.748 | failed |
| SGP | bonds | down | 2006-04 → 2026-07 | 31 / 51 | −0.82 | 0.788 | −0.18 | 4/4, 0.0500 | −0.82, 0.788 | failed |
| SGP | currency | up | 2006-04 → 2026-07 | 41 / 41 | −0.19 | 0.565 | 0.16 | 2/4, 0.0167 | −0.19, 0.565 | failed |
| SGP | currency | down | 2006-04 → 2026-07 | 28 / 54 | 0.03 | 0.478 | −0.11 | 1/4, 0.0125 | 0.03, 0.478 | failed |

- **No side passes anywhere: no override may cross a band** (IDN, USA, JPN, the euro area and
  its five members, AUS, SGP).
- Every side has a full sample (distance to 10/10 is 0 everywhere, CLI zeroed included), so
  every state is `failed`, not `insufficient`. USA stocks' window starts at the first complete
  month (2005-04), but only SPY's months (2016-01 →) have a return: 43 windows.
- Outside IDN no placebo p reaches 0.05. The best are USA stocks down (t 1.66, p 0.078) and JPN
  bonds up (t 1.30, p 0.087).
- The control t stays between −0.42 and +0.21 everywhere: the gate is not fitting noise.

## Diagnostics (never gate)

### Horizon 1, in IDR

| Subject | Stocks up / down t | Bonds up / down t | Currency up / down t |
|---|---|---|---|
| USA | 1.00 / 1.32 | −1.19 / 0.18 | −0.48 / −1.65 |
| JPN | – | 1.24 / −0.01 | −0.19 / −0.54 |
| EMU | – | −1.37 / −1.66 | 0.23 / 0.50 |
| AUS | – | 0.79 / 0.22 | **−2.39 / −2.51** |
| SGP | – | −1.09 / −1.22 | −0.30 / −0.18 |

### Horizon 3, local currency (no FX leg)

| Subject | Stocks up / down t | Bonds up / down t | Currency (= IDR) up / down t |
|---|---|---|---|
| USA | 0.11 / 0.37 | −1.14 / −0.83 | −0.56 / −0.78 |
| JPN | – | **2.12 (p 0.041)** / 1.31 | 0.90 / −0.39 |
| EMU | – | 1.70 (p 0.070) / 1.28 | 0.57 / 0.93 |
| AUS | – | 0.18 / 0.49 | −1.50 / −0.84 |
| SGP | – | −0.37 / −0.46 | −0.19 / 0.03 |

- In local currency, JPN and EMU bonds lean the claimed way (JPN up t 2.12). In IDR the FX leg
  swamps it (JPN up t 1.30, EMU up −1.14).
- That is what choice 2 decided to test: the user holds IDR, and P28's weights already carry
  the `fx` component. It is reported here, not acted on.

## Suspect numbers (evidence only, nothing changed)

- **AUS currency weights look inverted** (pattern, not proof). The AUS currency shift preceded
  the opposite AUD/IDR move on both sides: 3-month t −1.50 / −0.84, and 1-month t −2.39 /
  −2.51 (p 0.99 the claimed way). The AUS currency weights are growth +1, cli +1,
  inflation −1, policy +1, curve 0, fx +3. The `fx` component (+3, AUD's own 3-month move)
  dominates. A negative t on both sides fits AUD/IDR mean-reverting over 1–3 months more than
  it fits momentum.
- **Bonds lean the wrong way in four of six markets** (weak, consistent). Signed t is negative
  on both bonds sides for IDN (−0.99 / −1.03), USA (−0.43 / −0.63) and SGP (−0.73 / −0.82),
  and on EMU's up side (−1.14).
  - The shared bonds weights (inflation −3, policy −3, growth −1, cli −1) claim that hikes and
    rising inflation precede weaker bond returns.
  - Over 2005–2026 the opposite was a little more common at 3 months.
- **Both are recorded in PLAN.md *Open questions* for an agent review.** The weights stay as
  written (phase L choice 1).
