-- Values copied from the real warehouse.duckdb (read-only, 2026-10-23); histories trimmed.
INSERT INTO datasets VALUES
  ('WS_CBPOL', 'Central bank policy rates', '1.0', '2026-10-21 00:30:01'),
  ('WS_EER', 'Effective exchange rates', '1.0', '2026-10-21 00:30:29'),
  ('WS_CREDIT_GAP', 'Credit-to-GDP gaps', '1.0', '2026-10-21 00:31:13'),
  ('WS_SPP', 'Selected residential property prices', '1.0', '2026-10-21 00:31:18'),
  ('WS_DSR', 'Debt service ratios', '1.0', '2026-10-21 00:31:25');

INSERT INTO series VALUES
  ('WS_CBPOL.M.ID', 'WS_CBPOL', 'M', 'ID', 'Indonesia', 'Central bank policy rates - Indonesia - Monthly - End of period', 'Per cent per year', '368', 0, 4, '{"FREQ": {"code": "M", "label": "Monthly"}, "REF_AREA": {"code": "ID", "label": "Indonesia"}}', '{"SOURCE_REF": "Bank Indonesia", "UNIT_MULT": "0"}', 'M', '2026-10-14 06:45:08', NULL),
  ('WS_CBPOL.D.ID', 'WS_CBPOL', 'D', 'ID', 'Indonesia', 'Central bank policy rates - Indonesia - Daily', 'Per cent per year', '368', 0, 4, '{"FREQ": {"code": "D", "label": "Daily"}, "REF_AREA": {"code": "ID", "label": "Indonesia"}}', '{"SOURCE_REF": "Bank Indonesia"}', 'D', '2026-10-14 06:45:30', NULL),
  ('WS_CBPOL.M.US', 'WS_CBPOL', 'M', 'US', 'United States', 'Central bank policy rates - United States - Monthly - End of period', 'Per cent per year', '368', 0, 4, '{}', '{}', 'M', '2026-10-14 06:45:08', NULL),
  ('WS_EER.M.R.B.ID', 'WS_EER', 'M', 'ID', 'Indonesia', 'Indonesia - Real - Broad (64 economies)', 'Index, 2020 = 100', '882', NULL, NULL, '{}', '{"UNIT_MEASURE": "882"}', 'M.R+N.B', '2026-10-14 06:46:06', NULL),
  ('WS_CREDIT_GAP.Q.ID.P.A.C', 'WS_CREDIT_GAP', 'Q', 'ID', 'Indonesia', 'Indonesia - Private non-financial sector - All sectors - Credit-to-GDP gaps (actual-trend) - Quarterly', 'Percentage of GDP', '770', 0, 1, '{}', '{}', 'all', '2026-10-14 06:47:45', NULL),
  ('WS_SPP.Q.ID.R.771', 'WS_SPP', 'Q', 'ID', 'Indonesia', 'Indonesia - Real - Year-on-year changes, in per cent - Quarterly', 'Year-on-year changes, in per cent', '771', 0, NULL, '{}', '{}', 'all', '2026-10-14 06:47:52', NULL),
  ('WS_DSR.Q.ID.P', 'WS_DSR', 'Q', 'ID', 'Indonesia', 'Indonesia - Private non-financial sector', 'Per cent', '367', 0, 1, '{}', '{}', 'all', '2026-10-14 06:47:56', NULL),
  ('WS_DSR.Q.XX.P', 'WS_DSR', 'Q', 'XX', 'Nowhere', 'A discontinued series', 'Per cent', '367', 0, 1, '{}', '{}', 'all', '2026-10-14 06:47:56', '2026-10-21 00:31:25');

INSERT INTO observations VALUES
  ('WS_CBPOL.M.ID', '2026-07-01', '2026-07', '2026-07-31', 5.75, NULL, '2026-10-14 06:45:08', '2026-10-14 06:45:08'),
  ('WS_CBPOL.M.ID', '2026-08-01', '2026-08', '2026-08-31', 5.75, NULL, '2026-10-14 06:45:08', '2026-10-14 06:45:08'),
  ('WS_CBPOL.M.ID', '2026-09-01', '2026-09', '2026-09-30', 5.75, NULL, '2026-10-14 06:45:08', '2026-10-21 00:30:01'),
  ('WS_CBPOL.D.ID', '2026-10-02', '2026-10-02', '2026-10-02', 5.75, NULL, '2026-10-14 06:45:30', '2026-10-14 06:45:30'),
  ('WS_CBPOL.D.ID', '2026-10-05', '2026-10-05', '2026-10-05', 5.75, NULL, '2026-10-14 06:45:30', '2026-10-14 06:45:30'),
  ('WS_CBPOL.M.US', '2026-08-01', '2026-08', '2026-08-31', 3.625, NULL, '2026-10-14 06:45:08', '2026-10-14 06:45:08'),
  ('WS_CBPOL.M.US', '2026-09-01', '2026-09', '2026-09-30', 3.875, NULL, '2026-10-14 06:45:08', '2026-10-14 06:45:08'),
  ('WS_EER.M.R.B.ID', '2026-07-01', '2026-07', '2026-07-31', 88.10, NULL, '2026-10-14 06:46:06', '2026-10-14 06:46:06'),
  ('WS_EER.M.R.B.ID', '2026-08-01', '2026-08', '2026-08-31', 87.77, NULL, '2026-10-14 06:46:06', '2026-10-14 06:46:06'),
  ('WS_CREDIT_GAP.Q.ID.P.A.C', '2025-10-01', '2025-Q4', '2025-12-31', -1.10, NULL, '2026-10-14 06:47:45', '2026-10-14 06:47:45'),
  ('WS_CREDIT_GAP.Q.ID.P.A.C', '2026-01-01', '2026-Q1', '2026-03-31', -1.3337, NULL, '2026-10-14 06:47:45', '2026-10-14 06:47:45'),
  ('WS_SPP.Q.ID.R.771', '2026-04-01', '2026-Q2', '2026-06-30', -2.1917, NULL, '2026-10-14 06:47:52', '2026-10-14 06:47:52'),
  ('WS_DSR.Q.ID.P', '2025-10-01', '2025-Q4', '2025-12-31', 4.4, NULL, '2026-10-14 06:47:56', '2026-10-14 06:47:56'),
  ('WS_DSR.Q.ID.P', '2026-01-01', '2026-Q1', '2026-03-31', 4.2, NULL, '2026-10-14 06:47:56', '2026-10-14 06:47:56'),
  ('WS_DSR.Q.XX.P', '2020-01-01', '2020-Q1', '2020-03-31', NULL, NULL, '2026-10-14 06:47:56', '2026-10-14 06:47:56');
