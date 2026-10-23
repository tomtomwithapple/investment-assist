-- Two loaded months, two stocks, investor types ID (individual) and CP (corporate) only.
-- 2026-08-31: AAAA holds 100 (foreign CP 20), BBBB holds 300 (foreign ID 30, CP 120).
-- 2026-09-30: AAAA holds 100 (foreign CP 30); BBBB holds 0, so its pcts are NULL.
INSERT INTO holdings VALUES
    ('2026-08-31', 'AAAA', 200, 1000, 'local',   'ID', 60),
    ('2026-08-31', 'AAAA', 200, 1000, 'local',   'CP', 20),
    ('2026-08-31', 'AAAA', 200, 1000, 'foreign', 'ID', 0),
    ('2026-08-31', 'AAAA', 200, 1000, 'foreign', 'CP', 20),
    ('2026-08-31', 'BBBB', 500,  50,  'local',   'ID', 150),
    ('2026-08-31', 'BBBB', 500,  50,  'local',   'CP', 0),
    ('2026-08-31', 'BBBB', 500,  50,  'foreign', 'ID', 30),
    ('2026-08-31', 'BBBB', 500,  50,  'foreign', 'CP', 120),
    ('2026-09-30', 'AAAA', 200, 1100, 'local',   'ID', 50),
    ('2026-09-30', 'AAAA', 200, 1100, 'local',   'CP', 20),
    ('2026-09-30', 'AAAA', 200, 1100, 'foreign', 'ID', 0),
    ('2026-09-30', 'AAAA', 200, 1100, 'foreign', 'CP', 30),
    ('2026-09-30', 'BBBB', 500,  50,  'local',   'ID', 0),
    ('2026-09-30', 'BBBB', 500,  50,  'local',   'CP', 0),
    ('2026-09-30', 'BBBB', 500,  50,  'foreign', 'ID', 0),
    ('2026-09-30', 'BBBB', 500,  50,  'foreign', 'CP', 0);
INSERT INTO loads VALUES
    ('2026-08-31', 'BalanceposEfek20260831.zip', 'aaa', 8, 2, '2026-09-05 10:00:00'),
    ('2026-09-30', 'BalanceposEfek20260930.zip', 'bbb', 8, 2, '2026-10-07 10:53:52');
