# P128 flow factors (S107)

`src/assist/candidates/flow.py`, run live 2026-11-18 on idxscape `stock_summary` (to 2026-11-17),
kseistat (37 months to 2026-10-30) and idx-method `insider_history` (to 2026-11-16).

## Today (decision day 2026-11-18)

| Leg | Pool names ranked | Notes |
|---|---|---|
| accumulation | 0 of 149 | 793 of 979 names left the ±10% band in 60 days; 106 non-regular over half |
| supply_demand | 149 | top: MMIX 0.75, AYAM 0.71, RSCH 0.69 (up-day share of value, 50 days) |
| ownership | 149 | before the register-base change BYAN read +32.6pt (a reclassification) |
| insider | 66 | before the block rule KETR 5,730bp and SGER 5,600bp (takeover filings) led |

## Changes made on the live data, before any replay

1. **Ownership base = the whole KSEI register.** BYAN 2026-10: local individuals 14.50bn → 3.75bn
   shares, holdings, foreign institutions and funds unchanged. Institutions over (institutions +
   local individuals) read +32.6pt with nobody buying; over all holdings it reads 0. A
   local-individual move over 10pt in a month is flagged.
2. **Insider blocks.** A single filing of 5% of listed shares or more is a corporate deal, not market
   buying: KETR 2026-08-14 Fajar Sejahtera Mandiri Nusantara +56.5%, SGER 2026-10-28 Sumbermas Inti
   Energi +50.1%. Across the history 5,397 filings are 5%+, 5,939 are 1–5%, 13,185 are 0.1–1%,
   47,799 under 0.1% (share of today's listed shares).
3. **KSEI settlement duplicates.** IDX dates an insider trade on the trade day, KSEI at settlement
   two trading days later (KETR, GEMA LINTAS BENUA: 3,951,500 shares on 10-29 from IDX and 11-02
   from KSEI). The adapter now merges the other source's record within 7 days.

## The accumulation band (choice 3, open)

Names of the liquidity pool passing each definition of "flat", per month end 2021-10 → 2026-10
(59 month ends, pool median 144, min 121). Counts only: no forward return was computed.

| Definition | Median names | Min | Months under 40 |
|---|---|---|---|
| every close within ±10% (planned) | 18 | 1 | 59 of 59 |
| every close within ±15% | 43 | 9 | 23 |
| every close within ±20% | 64 | 27 | 6 |
| net 60-day move within ±10% | 57 | 31 | 7 |
| net 60-day move within ±15% | 79 | 47 | 0 |
