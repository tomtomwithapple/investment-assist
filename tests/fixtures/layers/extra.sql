-- P54: rows added on top of the idxscape_flows, idxscape_phei and idxscape index_daily fixtures
-- so one store holds every IDN chart window of tests/test_layers_out.py (run day 2026-10-23).
-- JISDOR: 10-16 a normal day, 10-22 a day BI says used D-1 data (carried forward). 10-21 stays
-- without a rate: an IDX day with no JISDOR is a gap, never filled.
INSERT INTO fx_rate VALUES
    ('2026-10-16', 'USDIDR', 15950.00, 'bi_jisdor', false, '2026-10-16 09:00:00+00'),
    ('2026-10-22', 'USDIDR', 16100.00, 'bi_jisdor', true, '2026-10-22 09:00:00+00');
-- An IGSYC curve about 4 weeks before the newest (2026-10-12): 2026-09-11. The target 09-14
-- has no curve, so the newest curve on or before it is used. It has no 10Y point (a second
-- month-end 10Y once crashed bonds.idn.bond_returns with 2 points and horizon 3; fixed since).
INSERT INTO igsyc_point VALUES
 ('2026-09-11', 1,  5.1000, false, 'sha0911', '2026-09-11 12:30:00+00'),
 ('2026-09-11', 2,  5.4000, false, 'sha0911', '2026-09-11 12:30:00+00'),
 ('2026-09-11', 5,  6.2000, false, 'sha0911', '2026-09-11 12:30:00+00');
