-- Real values copied read-only from ../singstat/data/sgecon.duckdb (refreshed 2026-10-07),
-- plus a null cell (2026-10-08) and an empty series to cover edge cases.
insert into series values
 ('mas:sora', 'mas', 'SORA (Singapore Overnight Rate Average)', '% p.a.', 'D', '2026-10-07 19:28:59'),
 ('mas:sora:comp3m', 'mas', 'Compounded SORA 3-month', '% p.a.', 'D', '2026-10-07 19:28:59'),
 ('mas:sgs:2y', 'mas', 'SGS 2-year benchmark bond yield', '% p.a.', 'D', '2026-10-07 19:29:00'),
 ('mas:sgs:10y', 'mas', 'SGS 10-year benchmark bond yield', '% p.a.', 'D', '2026-10-07 19:29:00'),
 ('mas:tbill:6m', 'mas', 'SGS T-bill 6-month yield', '% p.a.', 'D', '2026-10-07 19:29:00'),
 ('mas:fx:usdsgd', 'mas', 'S$ per US Dollar', 'SGD', 'D', '2026-10-07 19:28:59'),
 ('mas:fx:idrsgd', 'mas', 'S$ per Indonesian Rupiah (MAS quotes per 100 units; divided by 100)', 'SGD', 'D', '2026-10-07 19:28:59'),
 ('singstat:M213751:1', 'singstat', 'All Items', 'Index', 'M', '2026-10-07 20:28:19'),
 ('ura:empty', 'ura', 'A series with no observations', 'units', 'Q', null);
insert into observations values
 ('mas:sora', '2026-10-02', 1.3724, '% p.a.', 'mas'),
 ('mas:sora', '2026-10-05', 1.3484, '% p.a.', 'mas'),
 ('mas:sora', '2026-10-06', 1.3152, '% p.a.', 'mas'),
 ('mas:sora:comp3m', '2026-10-05', 1.2325, '% p.a.', 'mas'),
 ('mas:sora:comp3m', '2026-10-06', 1.2323, '% p.a.', 'mas'),
 ('mas:sgs:2y', '2026-10-06', 1.96, '% p.a.', 'mas'),
 ('mas:sgs:2y', '2026-10-07', 1.95, '% p.a.', 'mas'),
 ('mas:sgs:10y', '2026-10-06', 2.5, '% p.a.', 'mas'),
 ('mas:sgs:10y', '2026-10-07', 2.48, '% p.a.', 'mas'),
 ('mas:tbill:6m', '2026-10-07', 1.87, '% p.a.', 'mas'),
 ('mas:fx:usdsgd', '2026-10-05', 1.2823, 'SGD', 'mas'),
 ('mas:fx:usdsgd', '2026-10-06', 1.2794, 'SGD', 'mas'),
 ('mas:fx:usdsgd', '2026-10-07', 1.2789, 'SGD', 'mas'),
 ('mas:fx:idrsgd', '2026-10-05', 7.152e-05, 'SGD', 'mas'),
 ('mas:fx:idrsgd', '2026-10-06', 7.147e-05, 'SGD', 'mas'),
 ('mas:fx:idrsgd', '2026-10-07', 7.155e-05, 'SGD', 'mas'),
 ('mas:fx:idrsgd', '2026-10-08', null, 'SGD', 'mas'),
 ('singstat:M213751:1', '2026-07-01', 102.696, 'Index', 'singstat'),
 ('singstat:M213751:1', '2026-08-01', 103.334, 'Index', 'singstat');
insert into refresh_log values
 ('mas', '2026-10-07 20:28:20', '2026-10-07 20:28:24', 'ok', '3 datasets, 36 series'),
 ('singstat', '2026-10-07 20:28:08', '2026-10-07 20:28:19', 'ok', '7/7 tables, 346 series, 76,576 obs, latest 2026-08-01'),
 ('singstat', '2026-10-07 20:28:43', '2026-10-07 20:28:43', 'skipped', 'fresh: last ok 2026-10-07 20:28 (gate 1 day)'),
 ('ura', '2026-10-07 20:28:30', '2026-10-07 20:28:30', 'skipped', 'URA_ACCESS_KEY not set');
