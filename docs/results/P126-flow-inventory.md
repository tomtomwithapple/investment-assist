# P126 flow inventory

Read-only inventory of per-name money-flow data, run 2026-11-18 by `assist flow-inventory` (S105). Minimums: 750 trading days, 36 KSEI months, 1000 insider market trades, 80% sign agreement.

## Legs

| Leg | Verdict | Why |
|---|---|---|
| accumulation | usable | 1232 trading days; sign agreement 100% |
| supply_demand | usable | 1222 trading days of bars |
| ownership | usable | 37 months |
| insider | usable | 75127 market trades |

## Foreign flow (idxscape `stock_summary`)

| Field | Value |
|---|---|
| first | 2021-10-01 |
| last | 2026-11-17 |
| days | 1232 |
| codes | 982 |
| rows | 1102357 |
| rows_with_foreign_trade | 653333 |
| codes_with_foreign_trade | 938 |
| net_value_zero_when_shares_nonzero | 0 |
| non_regular_share_of_value | 0.2014 |
| name_days_non_regular_over_half | 42525 |
| days_by_year | 2021 64, 2022 246, 2023 239, 2024 237, 2025 236, 2026 210 |

## Cross-check (idx-method `bars.net_foreign` vs idxscape)

| Field | Value |
|---|---|
| first | 2021-10-18 |
| last | 2026-11-17 |
| names | 982 |
| name_days | 1087265 |
| both_nonzero | 641120 |
| sign_agreement | 0.9968 |
| median_abs_ratio | 1.0 |
| names_below_80pct | 0 |

Names that agree least:

| Code | Days | Sign agreement |
|---|---|---|
| ROCK | 172 | 98% |
| BAUT | 145 | 98% |
| TIRT | 147 | 98% |
| MEDS | 615 | 98% |
| SEMA | 567 | 98% |
| KOTA | 311 | 98% |
| SWID | 635 | 98% |
| INTD | 108 | 98% |
| YPAS | 216 | 98% |
| BRRC | 381 | 98% |

## Daily bars (idx-method `bars`)

| Field | Value |
|---|---|
| first | 2021-10-18 |
| last | 2026-11-18 |
| days | 1222 |
| names | 984 |
| rows_with_net_foreign | 1090554 |
| rows_with_value | 1329816 |

## Ownership (kseistat `holdings`)

| Field | Value |
|---|---|
| months | 37 |
| first | 2023-10-31 |
| last | 2026-10-30 |
| codes_latest | 1005 |
| investor_types | foreign CP, FD, IB, ID, IS, MF, OT, PF, SC, local CP, FD, IB, ID, IS, MF, OT, PF, SC |
| months_with_load_date | 37 |
| median_load_lag_days | 530 |
| max_load_lag_days | 1077 |
| stock_view | True |

## Insider and major holders (idx-method `insider_history`)

| Field | Value |
|---|---|
| rows | 77778 |
| first | 2021-08-03 |
| last | 2026-11-16 |
| symbols | 904 |
| actions | ACTION_TYPE_BOND_CONVERSION 13, ACTION_TYPE_BUY 47131, ACTION_TYPE_CAPITAL_REDUCTION 16, ACTION_TYPE_CROSS 795, ACTION_TYPE_MERGER 5, ACTION_TYPE_MESOP_OPTION 80, ACTION_TYPE_MSOP_OPTION 12, ACTION_TYPE_PRIVATE_PLACEMENT 63, ACTION_TYPE_REVERSE_SPLIT 7, ACTION_TYPE_RIGHT_ISSUE 442, ACTION_TYPE_SELL 27996, ACTION_TYPE_STOCK_BONUS 23, ACTION_TYPE_STOCK_DIVIDEND 10, ACTION_TYPE_STOCK_SPLIT 137, ACTION_TYPE_TENDER_OFFER 1, ACTION_TYPE_TRANSFER 659, ACTION_TYPE_UNSPECIFIED 1, ACTION_TYPE_WARRANT_EXERCISE 387 |
| sources | SOURCE_TYPE_IDX 22405, SOURCE_TYPE_KSEI 55373 |
| market_trades | 75127 |
| changes_parsed | 75127 |
| rows_by_year | 2021 4381, 2022 9370, 2023 13994, 2024 15805, 2025 18103, 2026 16125 |

## Shareholder register (idx-method `composition.json`)

| Field | Value |
|---|---|
| names | 944 |
| report_dates | 2026-10-30 944 |
| window_first | 2026-03-31 |
| window_last | 2026-10-30 |
| labels | Individual 943, Corporate 909, Securities Company 705, Investment Advisors 691, Bank 622, Private Bank 510, Mutual Funds 474, Investment Manager 404, Insurance 332, Pension Funds 323, Private Equity 321, Firm 309 |

## Broker top (idx-method `api_raw`)

| Field | Value |
|---|---|
| days | 6 |
| first | 2026-11-10 |
| last | 2026-11-17 |

## Screeners (idx-method Foreign Flow and Bandarmology)

| Field | Value |
|---|---|
| days | 5 |
| first | 2026-11-12 |
| last | 2026-11-17 |
| screeners | Bandarmology: Bandar Accumulation Uptrend, Bandarmology: Bandar Bearish Reversal, Bandarmology: Bandar Bullish Reversal, Bandarmology: Big Accumulation, Bandarmology: Big Distribution, Foreign Flow: 1 Month Net Foreign Flow, Foreign Flow: 1 Week Net Foreign Flow, Foreign Flow: 1 Year Net Foreign Flow, Foreign Flow: 3 Month Net Foreign Flow, Foreign Flow: 6 Months Net Foreign Flow, Foreign Flow: Daily Net Foreign Flow, Foreign Flow: Foreign Flow Uptrend |
| names_latest | 959 |
