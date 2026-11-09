# R-phase-l-weights: agent review of the phase L suspect override weights

Date: 2026-11-09. Reviewer: independent agent, on `main` at `29107fc`. Read-only: no code,
config, weight, band or PLAN number changed. Heuristic, not investment advice.

The two flags come from P83 and P78 (PLAN *Open questions*): the AUS currency weights look
inverted, and the bonds weights lean the wrong way in IDN, USA, SGP and EMU up. Scripts are in
the session scratchpad (`comp.py`, `stores.py`, `fxmr.py`, `fxpre.py`). They read
`out/overrides/*.json` (the F11 run's rows, components and forward returns) and the stores
through the repo's own read-only adapters.

## Verdicts

| Question | Verdict | Recommendation |
|---|---|---|
| 1. AUS currency (`fx` +3) | **(b) noise**, plus a sample-window effect common to every IDR cross. No bug. | **Keep.** Don't flip `fx`. |
| 2. Bonds across markets | **(b) noise**, with a **(c) design** caveat: the gate can't tell a right sign from a wrong one at this effect size. No bug. | **Keep.** Investigate the design points below. Don't change any bonds weight. |

## 1. Sign conventions, end to end (bugs first)

All of these were checked in the code and, where marked, in the data. **No construction error
was found.**

- **Component direction.** `_direction` gives +1 when the value is above the band
  (`overrides_foreign.py:388`). `fx` is the % change in IDR per local unit, so +1 means the
  local currency gained on the rupiah (`overrides_foreign.py:625`).
- **Shift to side.** The shift is Σ weight × direction, capped at ±10. `up` means shift > 0 is
  on, direction +1. `down` means shift < 0 is on, direction −1 (`override_gate.py` `SIDES`,
  `_on`). Signed t is `direction × (on − off)` (`placebo.py:115`). Positive t means the claim
  holds.
- **Currency return.** It is `p(t+h)/p(t) − 1` on IDR per local unit from the MAS crosses:
  `idr_per` (`override_history.py:581`), then `_ratio`. So + means the local currency gained,
  the same sign as the `fx` component and the currency score.
- **IDR per AUD.**
  - Live: RBA `FXRIR` is quoted as IDR per AUD.
  - History before 2023-04: `_aus_mas` uses `IDR_PER_SGD` (S$ per IDR, inverted) × S$ per AUD,
    with `local_per_base=False`, so `cross` multiplies (`fx.py:132`). That also gives IDR per
    AUD.
  - **Checked on 938 common days, 2023-01 → 2026-11:** RBA/MAS level ratio mean 1.0001 (range
    0.993–1.011). Their 3-month % changes correlate at 0.9986. Same units, same direction, no
    inversion at the 2023 switch.
- **Bond return.** Carry minus duration × Δyield (`layers/bonds/idn.py:169`): positive when
  yields fall. In IDR it is `(1 + r)(1 + fx) − 1`, with fx in IDR per local unit, which is
  right for an unhedged IDR investor (`override_history.py:634`). The IDN currency return is
  USD/IDR(t)/USD/IDR(t+h) − 1, so + means the rupiah gained (`override_history.py:387`).
- **Timing.**
  - No component's newest point is later than its row's `as_of`: 0 of 6 × 262 rows (`comp.py`).
  - Daily 10Ys (FRED DGS10, JGB, AGS `FCMYGBAG10D`, SGS) are month-end closes; under 3% of
    their points fall on the 1st.
  - `ea.bund.10y` is 100% dated the 1st, so `lag_monthly_averages` correctly lags it a month.
  - No forward return starts before its call.

## 2. Question 1: AUS currency

**What the flag says.** h3 signed t is −1.50 (up) and −0.84 (down). The h1 diagnostic is −2.39
and −2.51. The flag reads this as AUD/IDR mean-reverting, with the +3 `fx` weight to blame.

**What the data says.**

1. **`fx` isn't what drives it at h3.** Each component's direction regressed on the h3
   currency return (stride 3, 51 windows, the gate's own window 2013-12 → 2026-07) gives:

   | Component | t |
   |---|---|
   | cli | −1.83 |
   | growth | −1.48 |
   | fx | −0.78 |
   | policy | −0.28 |
   | inflation | +0.24 |
   | curve | +0.62 |

   The whole shift gives −1.64. So the failure is spread over components that aren't AUD
   momentum. Flipping `fx` would not even "fix" it in-sample. At h1, `fx` is −1.61, growth
   −1.19, and inflation is +1.33 (the wrong way for a −1 weight).
2. **The reversal is the rupiah's, not the Aussie's, and only after 2013.** The test regresses
   each IDR cross's past 3-month move on its next move (MAS crosses, `fxmr.py` / `fxpre.py`):

   | Next move, sample | USD | JPY | EUR | AUD | SGD |
   |---|---|---|---|---|---|
   | 1 month, 2013-12 → 2026 | −3.15 | −2.45 | −2.47 | −2.32 | −3.49 |
   | 3 months, 2013-12 → 2026 | −1.40 | −1.04 | +0.68 | −1.40 | −1.40 |
   | 3 months, 2005-04 → 2013-11 | +1.77 | +0.69 | +1.17 | −0.35 | +1.50 |
   | 3 months, 2005-04 → 2026 | +1.03 | +0.47 | +1.43 | −1.02 | +0.75 |

   Every rupiah cross shows short-term reversal from 2014. That fits Bank Indonesia leaning
   against moves (its "triple intervention" since 2018), not anything specific to AUD. Before
   2013 the same signal was mildly momentum-like. AUS is the only market whose gate window
   starts in 2013-12, because the AGS 10Y and curve start 2013-05. The other markets' windows
   start in 2005, and their `fx`-heavy currency sides are mixed: USA −0.56 / −0.78, JPN
   +0.90 / −0.39, EMU +0.57 / +0.93, SGP −0.19 / +0.03.
3. **Multiple testing.**
   - The two "sides" aren't two pieces of evidence. Up compares shift > 0 against the rest, and
     down compares shift < 0 against the rest, so the samples overlap: one negative relation
     makes both t's negative.
   - The h1 figure is the extreme of 22 h1 diagnostics (about 11 independent pairs). |t| ≥ 2.5
     has a two-sided p of about 0.012 per test, about 0.13 over 11. That isn't significant.
   - At the gated horizon, −1.50 is unremarkable.

**Verdict: (b), with a window effect.** There is no bug. The economics of the `fx` weight (an
unhedged IDR holder earns the local currency's gain, and 3-month FX momentum persists a little)
were a reasonable prior in 2026-10. The post-2013 rupiah reversal is a plausible alternative,
but it was found in-sample. The pre-2013 period doesn't support it for AUD (t −0.35, n 35).

**Recommendation: keep the AUS currency weights.** Flipping or cutting `fx` because it failed
would be fitting noise. If the user wants the "managed rupiah reverts at 1–3 months" idea
tested, state it now as an **IDR-wide** hypothesis, not an AUS one: an `fx` weight for all five
markets, set from economics. There is no clean out-of-sample test for it:

- The 2005–2013 holdout has now been looked at.
- The live monitor needs 10 on and 10 off windows at stride 3 per side, so 5+ years.

## 3. Question 2: bonds across markets

**What the data says.**

1. **The signs are what you'd expect from noise.**
   - Across all 28 gated sides at h3, 14 t's are negative and 14 positive. Their mean is +0.11
     and the largest |t| is 2.47. That is what 28 correlated draws from N(0, 1) look like.
   - The bonds sides alone, with up and down taken together as one shift-slope t per market:

     | IDN | USA | JPN | EMU | AUS | SGP |
     |---|---|---|---|---|---|
     | −0.44 | −0.67 | +0.18 | −0.20 | +0.40 | −1.06 |

     Mean −0.30. Even if the six were independent, that is z ≈ −0.7. They aren't independent:
     yields co-move globally, so the "consistent across markets" pattern counts closer to two
     or three draws than six.
   - In local currency (P83 diagnostic), JPN reads +2.12 / +1.31 and EMU +1.70 / +1.28,
     against USA −1.14 / −0.83. There is no consistent wrong sign.
2. **No single component is wrong-signed.** Each component's slope t on the h3 bonds return
   (positive means the component predicts better bonds):

   | Component | IDN | USA | JPN | EMU | AUS | SGP |
   |---|---|---|---|---|---|---|
   | inflation (−3) | +0.45 | +1.04 | n/a | −0.31 | −0.31 | +0.70 |
   | policy / bi_rate (−3) | +0.42 | −1.46 | +0.71 | +0.75 | +0.14 | +0.01 |

   With a −3 weight, the claim holds where t is negative. Only USA policy and the EMU and AUS
   inflation slopes go the claimed way. All are |t| < 1.5, mean about +0.2.
   - The one |t| > 2 is USA `flows_treasury`, −2.42 (bonds weight +2, so the wrong way).
   - Over 83 component tests, about 3.8 would show |t| > 2 by chance. Two do: that one, and USA
     stocks `curve` at +3.59, which goes the right way.
3. **The gate can't see an effect this size.** The on-vs-off spread needed for t = 2:

   | Side | Windows | 3-month sd | Spread needed per quarter |
   |---|---|---|---|
   | IDN bonds | 29 | 2.8% | 2.0% |
   | USA bonds | 86 | 5.1% | 2.2% |
   | SGP bonds | 82 | 4.1% | 1.8% |
   | EMU bonds | 85 | 4.4% | 1.9% |

   That is about 8%/yr between on and off months. Published macro-momentum effects in bonds are
   a fraction of that. So a −1 is what a correctly signed, realistically small effect looks
   like about one time in six: failing here says little about the sign.

**Ex-ante economics.**

- The inflation (−3) and growth / cli (−1) signs match the macro-momentum literature: rising
  growth and inflation precede weaker bonds.
- The **policy** component is the least defensible ex ante. A 6-month change in the policy rate
  is in the 10Y by the time it registers, and the late or post-hike phase is often followed by
  rallies. Its −3 weight equals inflation's.
- That is a design question for the next weight review. It doesn't justify a flip, and the data
  above don't favour either sign.

**Verdict: (b) for the signs; (c) for the design.** Keep every bonds weight.

**Investigate (no change implied):**

- **IDR vs local for bonds.** The gate tests bonds in IDR unhedged (choice 2), but the bonds
  weights describe local bond economics, and the FX leg can dominate (EMU local +1.70 becomes
  −1.14 in IDR). A hike moves the local bond down and the currency up, and `policy` carries
  bonds −3 against currency +1. So the IDR-unhedged bonds claim has an ambiguous sign by
  construction. Choice 2 is the user's call; it is noted here as a reason the IDR bonds t is
  hard to read, not as a reason to change it.
- **EMU members.** FRA and ITA bonds are gated on the Bund 10Y. A pass or fail on the Bund says
  little about BTP or OAT spreads.

## 4. What a change would cost (if the user overrides "keep")

- **Any edit to `WEIGHTS` in `layers/overrides_foreign.py`** changes the override fingerprint
  of all five foreign subjects. They share `_FOREIGN_FILES`, so the edit voids every file in
  `out/overrides/USA|JPN|EMU|AUS|SGP.json`. It also changes the model fingerprint (journal
  `RULE_GLOBS` covers `layers/**`), which opens a new journal segment.
- **An edit to `layers/overrides.py`** does the same for IDN and the model.
- **The gate rerun is cheap** (about 70 s). It is **not evidence**: the new weights would have
  been chosen on the same history. A valid verdict would need a holdout that doesn't exist.
  - The live monitor needs 10 on and 10 off non-overlapping 3-month windows per side, so
    5–10 years.
  - The only untouched history (AUS `fx` 2005–2013, other markets before 2005) is either
    already looked at here or not in the stores.

## 5. Other things noticed

- **No bug** in the sign, unit or timing paths above. The RBA/MAS AUD switch is clean.
- **Look-ahead (known).** The OECD CLI has no vintage. On AUS currency, `cli` is the most
  negative component (−1.83). The CLI-zeroed rerun reads −1.28 / −0.80, so the failure doesn't
  hinge on it.
- **IDN bonds has only 29 windows** (2017-07 → 2024-08, the 10Y hole). Any verdict there is
  weak.
- **USA `flows_treasury` on bonds** (−2.42): treat it as a lead for the next ex-ante review.
  Foreign Treasury buying bunches in flight-to-quality months, after yields have already fallen.
  Like everything else here, it was found in-sample.
