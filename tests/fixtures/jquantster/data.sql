-- Tiny jquantster store. Values are hand-picked; expected results are worked out in the tests.
INSERT INTO meta VALUES ('plan', 'free'), ('window', '2024-07-31..2026-07-31'),
    ('last_sync', '2026-10-23T16:50:23');
INSERT INTO entitlements VALUES
    ('bars', 'ok', '', '2026-10-23 09:50:18'),
    ('investor_types', 'ok', '', '2026-10-23 09:50:18'),
    ('macro', 'ok', '', '2026-10-23 09:50:23');

-- MOF JGB curve: 40Y only on the newer day
INSERT INTO jgb_yields VALUES
    ('2026-10-21', '2Y', 0.93), ('2026-10-21', '10Y', 1.66),
    ('2026-10-22', '2Y', 0.95), ('2026-10-22', '10Y', 1.70), ('2026-10-22', '40Y', 3.35);

-- BOJ series
INSERT INTO macro_series VALUES
    ('usdjpy', 'FM08', 'FXERD01', 'US.Dollar/Yen Spot Rate at 9:00 in JST, Tokyo Market',
     'Yen per U.S. Dollar', 'DAILY', '2026-10-23'),
    ('call_rate', 'FM01', 'STRDCLUCON', 'Call Rate, Uncollateralized Overnight, Average (Daily)',
     'percent per annum', 'DAILY', '2026-10-23'),
    ('tankan_lm', 'CO', 'TK99F1000601GCQ01000',
     'D.I./Business Conditions/Large Enterprises/Manufacturing/Actual result', '% points',
     'QUARTERLY', '2026-10-02'),
    ('tankan_lm_fc', 'CO', 'TK99F1000601GCQ11000',
     'D.I./Business Conditions/Large Enterprises/Manufacturing/Forecast', '% points',
     'QUARTERLY', '2026-10-02');
INSERT INTO macro_obs VALUES
    ('usdjpy', '2026-10-20', 150.1), ('usdjpy', '2026-10-21', 151.2),
    ('call_rate', '2026-10-21', 0.477),
    ('tankan_lm', '2026-06-30', 13.0), ('tankan_lm', '2026-09-30', 24.0),
    ('tankan_lm_fc', '2026-12-31', 21.0);

-- TSE investor types: week 1 published twice (the revision wins), week 2 once; a Standard row
INSERT INTO investor_types (section, st_date, en_date, pub_date, FrgnSell, FrgnBuy, FrgnBal,
                            IndBal) VALUES
    ('TSEPrime', '2026-10-05', '2026-10-09', '2026-10-15', 9000.0, 10000.0, 1000.0, -800.0),
    ('TSEPrime', '2026-10-05', '2026-10-09', '2026-10-22', 9000.0, 10200.0, 1200.0, -900.0),
    ('TSEPrime', '2026-10-12', '2026-10-16', '2026-10-22', 8000.0, 7500.0, -500.0, 300.0),
    ('TSEStandard', '2026-10-12', '2026-10-16', '2026-10-22', 100.0, 140.0, 40.0, NULL);

-- Daily bars (adjusted close differs from close for the split stock)
INSERT INTO daily_bars VALUES
    ('72030', '2026-07-30', 2800, 2850, 2790, 2840, 1e7, 2.8e10, 1.0, 2800, 2850, 2790, 2840, 1e7),
    ('72030', '2026-07-31', 2840, 2860, 2820, 2830, 9e6, 2.5e10, 1.0, 2840, 2860, 2820, 2830, 9e6),
    ('99840', '2026-07-31', 9000, 9100, 8900, 9050, 5e6, 4.5e10, 0.5, 4500, 4550, 4450, 4525, 1e7);

-- Financial summaries: FY 2026-03 filed, then corrected (the correction wins); a 1Q with no FEPS
INSERT INTO fins_summary VALUES
    ('72030', '20260508000001', '2026-05-08', 'FYFinancialStatements_Consolidated_IFRS',
     '{"DiscDate": "2026-05-08", "Code": "72030", "DiscNo": "20260508000001", "CurPerType": "FY", "CurPerEn": "2026-03-31", "EPS": "300.5", "FEPS": "320.0", "BPS": "2900.0", "NP": "4000000000000"}'),
    ('72030', '20260520000002', '2026-05-20', 'FYFinancialStatements_Consolidated_IFRS',
     '{"DiscDate": "2026-05-20", "Code": "72030", "DiscNo": "20260520000002", "CurPerType": "FY", "CurPerEn": "2026-03-31", "EPS": "301.0", "FEPS": "320.0", "BPS": "2900.0", "NP": "4010000000000"}'),
    ('72030', '20260801000003', '2026-08-01', '1QFinancialStatements_Consolidated_IFRS',
     '{"DiscDate": "2026-08-01", "Code": "72030", "DiscNo": "20260801000003", "CurPerType": "1Q", "CurPerEn": "2026-06-30", "EPS": "80.0", "FEPS": "", "BPS": "", "NP": "1050000000000"}');
