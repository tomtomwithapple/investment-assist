-- Real values copied read-only from ../ausdata/warehouse.duckdb on 2026-10-23 (trimmed).
-- RBA, AOFM and derived rows are dated at period end; ABS rows at period start.
-- DER.REAL_CASH_RATE 2026-10-31 is a partial month dated at its month end, as live.
INSERT INTO series_meta VALUES
 ('FIRMMCRTD', 'rba', 'Cash Rate Target', 'Cash Rate Target on date', 'Per cent', 'Daily',
  '{"table": "F1", "publication_date": "2026-10-21", "rba_series_id": "FIRMMCRTD"}'),
 ('FCMYGBAG2D', 'rba', 'Australian Government 2 year bond', 'Yields on AGS, 2 years', 'Per cent per annum', 'Daily',
  '{"table": "F2", "publication_date": "2026-10-16", "rba_series_id": "FCMYGBAG2D"}'),
 ('FCMYGBAG10D', 'rba', 'Australian Government 10 year bond', 'Yields on AGS, 10 years', 'Per cent per annum', 'Daily',
  '{"table": "F2", "publication_date": "2026-10-16", "rba_series_id": "FCMYGBAG10D"}'),
 ('FXRUSD', 'rba', 'A$1=USD', 'AUD/USD Exchange Rate', 'USD', 'Daily',
  '{"table": "F11.1", "publication_date": "2026-10-20", "rba_series_id": "FXRUSD"}'),
 ('FXRIR', 'rba', 'A$1=IDR', 'AUD/IDR Exchange Rate', 'IDR', 'Daily',
  '{"table": "F11.1", "publication_date": "2026-10-20", "rba_series_id": "FXRIR"}'),
 ('ABS.CPI.3.10001.10.50.M', 'abs', 'Percentage change from previous year; All groups CPI; Original; Australia',
  NULL, 'Percent', 'Monthly', NULL),
 ('ABS.LF.M13.3.1599.20.AUS.M', 'abs', 'Unemployment rate; Persons; Total (age); Seasonally Adjusted; Australia',
  NULL, 'Percent', 'Monthly', NULL),
 ('ABS.ANA_AGG.M1.GPM.20.AUS.Q', 'abs', 'Chain volume measures; Gross domestic product; Seasonally Adjusted; Australia',
  NULL, 'Australian Dollars (Millions)', 'Quarterly', NULL),
 ('ABS.ABS_REGIONAL_ASGS2021.ERP_P_20.SA4.123.A', 'abs', 'Estimated resident population: Persons (no.); Sydney - Outer South West; Annual',
  NULL, 'Persons', '', NULL),
 ('AOFM.FH.AGS.NONRES_PCT', 'aofm', 'Non-resident holdings of AGS: non-resident share', NULL, 'Per cent', 'Quarterly', NULL),
 ('DER.REAL_CASH_RATE', 'derived', 'Real cash rate (cash rate target minus trimmed-mean inflation)', NULL, 'Per cent', 'Monthly',
  '{"inputs": ["FIRMMCRTD", "ABS.CPI.3.999902.20.50.M"], "indicator": "REAL_CASH_RATE"}'),
 ('DER.GDP_YY', 'derived', 'Real GDP, % change on the same quarter a year earlier', NULL, 'Per cent', 'Quarterly',
  '{"inputs": ["ABS.ANA_AGG.M1.GPM.20.AUS.Q"], "indicator": "GDP_YY"}');

INSERT INTO observations VALUES
 ('FIRMMCRTD', 'rba', '2026-10-16', 4.6, 'Per cent', 'Daily', '2026-10-21 03:00:08'),
 ('FIRMMCRTD', 'rba', '2026-10-19', 4.6, 'Per cent', 'Daily', '2026-10-21 03:00:08'),
 ('FIRMMCRTD', 'rba', '2026-10-20', 4.6, 'Per cent', 'Daily', '2026-10-21 03:00:08'),
 ('FCMYGBAG2D', 'rba', '2026-10-13', 4.886, 'Per cent per annum', 'Daily', '2026-10-17 13:25:15'),
 ('FCMYGBAG2D', 'rba', '2026-10-14', 4.919, 'Per cent per annum', 'Daily', '2026-10-17 13:25:15'),
 ('FCMYGBAG10D', 'rba', '2026-10-13', 5.288, 'Per cent per annum', 'Daily', '2026-10-17 13:25:15'),
 ('FCMYGBAG10D', 'rba', '2026-10-14', 5.314, 'Per cent per annum', 'Daily', '2026-10-17 13:25:15'),
 ('FXRUSD', 'rba', '2026-10-19', 0.6975, 'USD', 'Daily', '2026-10-21 03:00:09'),
 ('FXRUSD', 'rba', '2026-10-20', 0.6984, 'USD', 'Daily', '2026-10-21 03:00:09'),
 ('FXRIR', 'rba', '2026-10-19', 12585.0, 'IDR', 'Daily', '2026-10-21 03:00:09'),
 ('FXRIR', 'rba', '2026-10-20', 12578.0, 'IDR', 'Daily', '2026-10-21 03:00:09'),
 ('ABS.CPI.3.10001.10.50.M', 'abs', '2026-07-01', 3.5, 'Percent', 'Monthly', '2026-10-21 03:00:17'),
 ('ABS.CPI.3.10001.10.50.M', 'abs', '2026-08-01', 4.0, 'Percent', 'Monthly', '2026-10-21 03:00:17'),
 ('ABS.LF.M13.3.1599.20.AUS.M', 'abs', '2026-08-01', 4.65160785, 'Percent', 'Monthly', '2026-10-21 03:00:17'),
 ('ABS.LF.M13.3.1599.20.AUS.M', 'abs', '2026-09-01', 4.71834873, 'Percent', 'Monthly', '2026-10-21 03:00:17'),
 ('ABS.ANA_AGG.M1.GPM.20.AUS.Q', 'abs', '2026-01-01', 696539.0, 'Australian Dollars (Millions)', 'Quarterly', '2026-10-21 03:00:23'),
 ('ABS.ANA_AGG.M1.GPM.20.AUS.Q', 'abs', '2026-04-01', 699461.0, 'Australian Dollars (Millions)', 'Quarterly', '2026-10-21 03:00:23'),
 ('ABS.ABS_REGIONAL_ASGS2021.ERP_P_20.SA4.123.A', 'abs', '2025-01-01', 323758.0, 'Persons', '', '2026-10-21 03:00:20'),
 ('AOFM.FH.AGS.NONRES_PCT', 'aofm', '2026-03-31', 50.8608057691078, 'Per cent', 'Quarterly', '2026-10-09 02:42:18'),
 ('AOFM.FH.AGS.NONRES_PCT', 'aofm', '2026-06-30', 52.3678345914524, 'Per cent', 'Quarterly', '2026-10-09 02:42:18'),
 ('DER.REAL_CASH_RATE', 'derived', '2026-09-30', 1.0, 'Per cent', 'Monthly', '2026-10-21 03:24:13'),
 ('DER.REAL_CASH_RATE', 'derived', '2026-10-31', 1.0, 'Per cent', 'Monthly', '2026-10-21 03:24:13'),
 ('DER.GDP_YY', 'derived', '2026-03-31', 2.504713, 'Per cent', 'Quarterly', '2026-10-21 03:24:13'),
 ('DER.GDP_YY', 'derived', '2026-06-30', 2.137636, 'Per cent', 'Quarterly', '2026-10-21 03:24:13'),
 ('DER.GDP_YY', 'derived', '2026-09-30', NULL, 'Per cent', 'Quarterly', '2026-10-21 03:24:13');

INSERT INTO raw_loads VALUES
 ('rba', 'f1', '/x/ausdata/raw/rba/f1/2026-10-21.csv', '2026-10-21 03:00:08'),
 ('abs', 'cpi', '/x/ausdata/raw/abs/cpi/2026-10-21.csv', '2026-10-21 03:00:17'),
 ('aofm', 'foreign_holdings', '/x/ausdata/raw/aofm/fh/2026-10-09.xlsx', '2026-10-09 02:42:18');
