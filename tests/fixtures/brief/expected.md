# Investment brief 2026-10-13

> Heuristic, not investment advice. Context for an IDR-based investor, built from 3 stance payload(s); every source is listed at the end.

## Global regime

- Regime: **neutral**
- Dollar: mixed, **flat** (IDN bonds); **up** (IDN stocks, USA bonds)
- Model: `sha256:3f2a9c0d1e4b`

## Stances

| Subject | Asset | Stance | Score | Layer 1 | Conf. | Entry | Now → target | Delta |
|---|---|---|---:|---:|---:|---|---|---|
| IDN | stocks | neutral | 52 | 55.5 | 0.61 | lump | 30% → 30% | hold |
| IDN | bonds | overweight | 68 | 58 | 0.74 | ladder 3×10d | 8% → 15% | +7pt over 3 tranches |
| USA | bonds | underweight | 41 | 44 | 0.55 | none | n/a → 0% | unknown: holdings unavailable |

## Changes since last run

Compared with 2026-10-06.

- Regime: risk_off → neutral
- IDN bonds: stance neutral → overweight; score 55 → 68; target 8% → 15%
- USA bonds: new (underweight, score 41)
- JPN stocks: dropped (was neutral)

## Details

### IDN stocks: neutral, score 52

**Drivers**

- macro score 55.5
- IDX foreign flow -Rp1.1T/4w

**Risks**

- JCI index series frozen at 2026-09-30

**Flags**

- warn `stale_index`: JCI daily series frozen at 2026-09-30

### IDN bonds: overweight, score 68

**Drivers**

- real yield 3.1% (82nd pct)
- foreign SBN +Rp4.2T/4w

**Risks**

- USD/IDR at 6m high

### USA bonds: underweight, score 41

**Drivers**

- 10Y real yield 1.9%
- term premium rising

**Risks**

- IDR-unhedged return depends on USD/IDR

## Watch

- BI meeting 2026-10-22 (IDN stocks, IDN bonds)
- US CPI 2026-10-15 (IDN bonds, USA bonds)

## Stale inputs

- financer (locked): USA bonds
- idx-method jkse_daily.csv: IDN stocks

## Sources

- bisfetcher
- financer
- idxscape
- kseistat
- sec-edgar FRED
- worldbankscape

---

_Heuristic, not investment advice. Sources: bisfetcher, financer, idxscape, kseistat, sec-edgar FRED, worldbankscape._
