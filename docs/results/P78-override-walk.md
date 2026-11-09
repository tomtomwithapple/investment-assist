# P78-override-walk (PLAN S60): the IDN override walk-forward on the real stores

Date: 2026-11-09. Branch `phase-l`. Docs only: no code, no threshold, weight, band or window
changed. Heuristic, not investment advice.

## Setup

- **History:**
  - P17 replayed point in time on 262 month ends, 2005-01 → 2026-10 (S57, with S61b's CPI
    fallback);
  - 112 complete months, 2017-07 → 2026-10;
  - forward returns as of 2026-11-09 (S58).
- **Gate:** `eval/override_gate.py` (S59).
  - Choices 1 and 3–10 as accepted: horizon / stride / block 3, `MIN_N` 10, t ≥ 2.0,
    p ≤ 0.05, 1,000 shuffles, 20 controls, `SEED` 20261023.
  - Holm over the six IDN tests.
  - A CLI-zeroed rerun with its own Holm family.
- **Override fingerprint at S59:** `sha256:045b0b6695f3…`. It changes again when
  `override_history.py` grows the foreign replay (S63/S64). The numbers below do not depend on
  it.
- **Live monitor:** no `overrides` record carries this fingerprint yet, so it is 0 on / 0 off
  on every side.

## Verdict per asset and side (horizon 3, the gate)

Signed t: positive means the side works as claimed (up → higher return, down → lower).

| Asset | Side | Window | On / off | Mean on / off | t | p | Control t | Holm rank, needs p ≤ | CLI zeroed: on / off, t, p | State |
|---|---|---|---|---|---|---|---|---|---|---|
| Stocks (JCI) | up | 2017-07 → 2026-07 | 24 / 13 | +0.99% / −1.99% | 1.08 | 0.186 | −0.30 | 3, 0.0125: no | 17 / 20, −0.35, 0.636 | **failed** |
| Stocks | down | 2017-07 → 2026-07 | 12 / 25 | −1.85% / +0.80% | 0.92 | 0.225 | −0.29 | 4, 0.0167: no | 12 / 25, −0.78, 0.704 | **failed** |
| Bonds (10Y) | up | 2017-07 → 2024-08 | 13 / 16 | +1.09% / +2.16% | −0.99 | 0.810 | +0.04 | 5, 0.0250: no | 10 / 19, −0.23, 0.583 | **failed** |
| Bonds | down | 2017-07 → 2024-08 | 15 / 14 | +2.20% / +1.13% | −1.03 | 0.821 | +0.15 | 6, 0.0500: no | 12 / 17, −0.97, 0.792 | **failed** |
| Currency (IDR vs USD) | up | 2017-07 → 2026-07 | 13 / 24 | +0.35% / −1.39% | 1.75 | 0.122 | −0.13 | 2, 0.0100: no | 14 / 23, +1.69, 0.087 | **failed** |
| Currency | down | 2017-07 → 2026-07 | 15 / 22 | −2.14% / +0.15% | **2.47** | **0.047** | −0.42 | 1, 0.0083: **no** | 18 / 19, +0.95, 0.229 | **failed** |

- **No side passes, so no override may cross a band.** Every side has a full sample (≥ 10 on
  and off, CLI zeroed included; distance to 10/10 is 0 everywhere), so every state is
  `failed`, not `insufficient`.
- **Currency down is the one placebo pass.** t 2.47, p 0.047, control t −0.42: a P17
  currency shift below zero did precede a weaker rupiah. Two checks stop it:
  - Holm: as the smallest p of six it must be ≤ 0.0083;
  - with the CLI zeroed, t falls to 0.95.

  It stays held. This is the case choices 6 and 10 were set for: one p under 0.05 among six,
  much of it carried by the one input with no vintage.
- **Bonds point the wrong way** (t ≈ −1 on both sides): an up shift preceded lower 10Y returns
  than the rest, a down shift higher ones. The evidence is weak (|t| ≈ 1, 29 windows) and is
  recorded below. Nothing is changed.
- **Stocks** lean the claimed way on both sides (t ≈ 1), but the edge is gone with the CLI
  zeroed (t −0.35 and −0.78). What edge there is is the revised CLI's.

## Diagnostics (never gate)

### Horizon 1 (stride 1, block 1)

| Asset | Up: on / off, t, p | Down: on / off, t, p |
|---|---|---|
| Stocks | 66 / 45, 0.71, 0.256 | 37 / 74, −0.06, 0.520 |
| Bonds | 40 / 48, 0.00, 0.506 | 45 / 43, 0.05, 0.482 |
| Currency | 42 / 69, 0.39, 0.359 | 46 / 65, 0.90, 0.168 |

Nothing is near significance at one month either.

### Per component (horizon 3)

"On" means the component pushes the asset up (direction × weight > 0), or down for the down
column. A t of 0.00 means a side under 10 windows.
- Of 30 component × side tests, none has |t| ≥ 1.1. The largest are currency `bi_rate`
  up-push 1.06 (p 0.169), bonds `bi_rate` down-push −1.09 (wrong way), and stocks `cli`
  up-push 0.92.
- `growth` and `trade` rarely leave their dead bands (growth 7–9 on-windows of 37; trade 3–9).
  Most of their tests are under 10 windows.

### Shift sizes on the complete window

- |shift| reaches 9 (stocks, once), 8 (bonds) and 5 (currency). The ±10 cap never binds.
- Live today (2026-11-09): stocks −5, bonds −4, currency +2. None crosses a band from its
  layer-1 score, and none may (no pass).

### Local returns

For IDN the local return is the IDR return, so there is no separate local diagnostic. The
foreign ones come in P83.

## Suspect numbers (evidence only, nothing changed)

- **P17 bonds weights may be wrong-signed** (weak). On 2017-07 → 2024-08, up shifts precede
  lower and down shifts higher 10Y returns (t −0.99 / −1.03), and `bi_rate` down-push reads
  t −1.09. A BI hike (bonds −3) was followed by better bond returns more often than not. With
  29 windows this is far from evidence to change a weight. It is recorded under
  *Open questions* for the next agent review; the weights stay as written (choice 1, decided).
