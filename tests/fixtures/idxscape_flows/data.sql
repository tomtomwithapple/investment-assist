-- Shaped like the real rows of 2026-10-19..21 (values rounded so the sums are easy to check).
-- net_foreign_value_est_idr = net_foreign_shares x close, as idxscape stores it.
-- Market net foreign: 10-19 +3.20bn, 10-20 -1.61bn, 10-21 +0.50bn (IDR).
INSERT INTO stock_summary (trade_date, code, name, previous, close, volume_shares, value_idr,
    frequency, listed_shares, foreign_buy_shares, foreign_sell_shares, net_foreign_shares,
    net_foreign_value_est_idr) VALUES
    ('2026-10-19', 'AAAA', 'Aaaa Tbk.', 1000, 1000, 9000000, 9000000000, 900, 1000000000, 5000000, 1000000, 4000000, 4000000000),
    ('2026-10-19', 'BBBB', 'Bbbb Tbk.', 2000, 2000, 1000000, 2000000000, 100, 1000000000, 100000, 500000, -400000, -800000000),
    ('2026-10-20', 'AAAA', 'Aaaa Tbk.', 1000, 1000, 3000000, 3000000000, 300, 1000000000, 0, 1000000, -1000000, -1000000000),
    ('2026-10-20', 'BBBB', 'Bbbb Tbk.', 2000, 2000, 1000000, 2000000000, 100, 1000000000, 195000, 500000, -305000, -610000000),
    ('2026-10-21', 'AAAA', 'Aaaa Tbk.', 1000, 1000, 2000000, 2000000000, 200, 1000000000, 700000, 200000, 500000, 500000000);
-- 10-21 was recorded at 17:30 UTC = 10-22 00:30 WIB
INSERT INTO trading_day VALUES
    ('2026-10-19', true, 2, '2026-10-19 11:00:00+00'),
    ('2026-10-20', true, 2, '2026-10-20 11:00:00+00'),
    ('2026-10-21', true, 1, '2026-10-21 17:30:00+00');
-- no JISDOR on 10-21: a gap, the USD flow stays empty
INSERT INTO fx_rate VALUES
    ('2026-10-19', 'USDIDR', 16000.00, 'bi_jisdor', false, '2026-10-19 09:00:00+00'),
    ('2026-10-20', 'USDIDR', 16100.00, 'bi_jisdor', false, '2026-10-20 09:00:00+00');
INSERT INTO broker_summary VALUES
    ('2026-10-20', 'AD', 'Sukadana Prima Sekuritas', 17246600, 1985742000, 111, 1, 965297),
    ('2026-10-20', 'AF', 'Harita Kencana Sekuritas', 1670900, 2577805900, 117, 2, 965298),
    ('2026-10-21', 'AD', 'Sukadana Prima Sekuritas', 1000, 1000000, 3, 1, 966000);
-- file aaa fetched 10-20 03:00 UTC (WIB 10-20); bbb fetched 10-21 20:00 UTC (WIB 10-22)
INSERT INTO sbn_ownership VALUES
    ('2026-10-19', 'TOTAL', 'non_resident', 920440000000000, 'aaa'),
    ('2026-10-19', 'TOTAL', 'total', 6400000000000000, 'aaa'),
    ('2026-10-20', 'TOTAL', 'non_resident', 918070000000000, 'aaa'),
    ('2026-10-20', 'TOTAL', 'total', 6410000000000000, 'aaa'),
    ('2026-10-21', 'TOTAL', 'non_resident', 914410000000000, 'bbb'),
    ('2026-10-21', 'TOTAL', 'total', 6420000000000000, 'bbb'),
    ('2026-10-21', 'SUN', 'non_resident', 850000000000000, 'bbb');
INSERT INTO sbn_ownership_file VALUES
    ('aaa', 'djppr', 'GUID-A', 'xlsx', 'fp', '2026-10-01', '2026-10-20', 14, 30, 0, '2026-10-20 03:00:00+00', '2026-10-20 03:05:00+00'),
    ('bbb', 'djppr', 'GUID-B', 'xlsx', 'fp', '2026-10-01', '2026-10-21', 15, 33, 0, '2026-10-21 20:00:00+00', '2026-10-21 20:05:00+00');
