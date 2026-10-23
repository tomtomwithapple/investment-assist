-- kseistat SCHEMA + VIEWS, copied from ../kseistat/kseistat/db.py on 2026-10-23 (commit 40791dc).
-- Percentages are of KSEI-recorded holdings, not sec_num.
CREATE TABLE IF NOT EXISTS holdings (
    date DATE NOT NULL,
    code VARCHAR NOT NULL,
    sec_num BIGINT,
    price BIGINT,
    origin VARCHAR NOT NULL,
    investor_type VARCHAR NOT NULL,
    shares BIGINT,
    PRIMARY KEY (date, code, origin, investor_type)
);
CREATE TABLE IF NOT EXISTS loads (
    date DATE PRIMARY KEY,
    filename VARCHAR,
    sha256 VARCHAR,
    rows INTEGER,
    stocks INTEGER,
    loaded_at TIMESTAMP
);

CREATE OR REPLACE VIEW v_stock_composition AS
WITH s AS (
    SELECT date, code, ANY_VALUE(sec_num) AS sec_num, ANY_VALUE(price) AS price,
        SUM(shares)::BIGINT AS holdings,
        COALESCE(SUM(shares) FILTER (WHERE origin = 'local'), 0)::BIGINT AS local_shares,
        COALESCE(SUM(shares) FILTER (WHERE origin = 'foreign'), 0)::BIGINT AS foreign_shares,
        COALESCE(SUM(shares) FILTER (WHERE investor_type = 'ID'), 0)::BIGINT AS individual_shares,
        COALESCE(SUM(shares) FILTER (WHERE investor_type <> 'ID'), 0)::BIGINT AS institution_shares,
        COALESCE(SUM(shares) FILTER (WHERE origin = 'local' AND investor_type = 'ID'), 0)::BIGINT AS local_individual,
        COALESCE(SUM(shares) FILTER (WHERE origin = 'local' AND investor_type <> 'ID'), 0)::BIGINT AS local_institution,
        COALESCE(SUM(shares) FILTER (WHERE origin = 'foreign' AND investor_type = 'ID'), 0)::BIGINT AS foreign_individual,
        COALESCE(SUM(shares) FILTER (WHERE origin = 'foreign' AND investor_type <> 'ID'), 0)::BIGINT AS foreign_institution
    FROM holdings
    GROUP BY date, code
)
SELECT *,
    holdings::DOUBLE / NULLIF(sec_num, 0) AS coverage,
    100 * local_shares::DOUBLE / NULLIF(holdings, 0) AS local_pct,
    100 * foreign_shares::DOUBLE / NULLIF(holdings, 0) AS foreign_pct,
    100 * individual_shares::DOUBLE / NULLIF(holdings, 0) AS individual_pct,
    100 * institution_shares::DOUBLE / NULLIF(holdings, 0) AS institution_pct,
    100 * local_individual::DOUBLE / NULLIF(holdings, 0) AS local_individual_pct,
    100 * local_institution::DOUBLE / NULLIF(holdings, 0) AS local_institution_pct,
    100 * foreign_individual::DOUBLE / NULLIF(holdings, 0) AS foreign_individual_pct,
    100 * foreign_institution::DOUBLE / NULLIF(holdings, 0) AS foreign_institution_pct
FROM s;

CREATE OR REPLACE VIEW v_market_composition AS
SELECT date, 'sum' AS method, COUNT(*) FILTER (WHERE holdings > 0) AS n_stocks,
    SUM(holdings)::BIGINT AS total_holdings,
    100 * SUM(local_shares)::DOUBLE / NULLIF(SUM(holdings), 0) AS local_pct,
    100 * SUM(foreign_shares)::DOUBLE / NULLIF(SUM(holdings), 0) AS foreign_pct,
    100 * SUM(individual_shares)::DOUBLE / NULLIF(SUM(holdings), 0) AS individual_pct,
    100 * SUM(institution_shares)::DOUBLE / NULLIF(SUM(holdings), 0) AS institution_pct,
    100 * SUM(local_individual)::DOUBLE / NULLIF(SUM(holdings), 0) AS local_individual_pct,
    100 * SUM(local_institution)::DOUBLE / NULLIF(SUM(holdings), 0) AS local_institution_pct,
    100 * SUM(foreign_individual)::DOUBLE / NULLIF(SUM(holdings), 0) AS foreign_individual_pct,
    100 * SUM(foreign_institution)::DOUBLE / NULLIF(SUM(holdings), 0) AS foreign_institution_pct
FROM v_stock_composition GROUP BY date
UNION ALL
SELECT date, 'equal_weight' AS method, COUNT(local_pct) AS n_stocks,
    SUM(holdings)::BIGINT AS total_holdings,
    AVG(local_pct), AVG(foreign_pct), AVG(individual_pct), AVG(institution_pct),
    AVG(local_individual_pct), AVG(local_institution_pct),
    AVG(foreign_individual_pct), AVG(foreign_institution_pct)
FROM v_stock_composition GROUP BY date;

CREATE OR REPLACE VIEW v_type_composition AS
WITH h AS (
    SELECT date, origin, investor_type, shares,
        SUM(shares) OVER (PARTITION BY date, code) AS holdings
    FROM holdings
)
SELECT date, origin, investor_type, SUM(shares)::BIGINT AS shares,
    100 * SUM(shares)::DOUBLE / NULLIF(SUM(SUM(shares)) OVER (PARTITION BY date), 0) AS pct_sum,
    AVG(100 * shares::DOUBLE / NULLIF(holdings, 0)) AS pct_equal_weight
FROM h
GROUP BY date, origin, investor_type;

CREATE OR REPLACE VIEW v_stock_shifts AS
WITH d AS (
    SELECT date, LAG(date) OVER (ORDER BY date) AS prev_date
    FROM (SELECT DISTINCT date FROM holdings)
)
SELECT c.date, c.code, d.prev_date, c.holdings, c.foreign_pct, c.individual_pct,
    c.foreign_pct - p.foreign_pct AS foreign_pct_change,
    c.individual_pct - p.individual_pct AS individual_pct_change,
    c.local_individual_pct - p.local_individual_pct AS local_individual_pct_change,
    c.local_institution_pct - p.local_institution_pct AS local_institution_pct_change,
    c.foreign_individual_pct - p.foreign_individual_pct AS foreign_individual_pct_change,
    c.foreign_institution_pct - p.foreign_institution_pct AS foreign_institution_pct_change
FROM v_stock_composition c
JOIN d USING (date)
LEFT JOIN v_stock_composition p ON p.code = c.code AND p.date = d.prev_date;
