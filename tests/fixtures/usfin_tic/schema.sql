-- The TIC part of sec-edgar's store, copied from its migrations 005 (bls_as_of_utc) and 021
-- (tic_*), checked against ../sec-edgar on 2026-10-23. Tests build a tiny usfin.duckdb from this
-- plus tic_series.csv and tic_observation.csv; the fake `usfin serve` reads the same file.

CREATE MACRO bls_as_of_utc(ts) AS CASE
    WHEN typeof(ts) = 'DATE' THEN timezone('UTC', timezone('America/New_York',
        CAST(CAST(ts AS DATE) AS TIMESTAMP) + INTERVAL '23 hours 59 minutes 59 seconds'))
    WHEN typeof(ts) = 'TIMESTAMP WITH TIME ZONE' THEN timezone('UTC', CAST(ts AS TIMESTAMPTZ))
    ELSE CAST(ts AS TIMESTAMP)
END;

CREATE TABLE tic_series (
    series_id      VARCHAR PRIMARY KEY,
    title          VARCHAR NOT NULL,
    measure        VARCHAR NOT NULL,
    kind           VARCHAR NOT NULL,
    country_code   VARCHAR NOT NULL,
    country        VARCHAR,
    active         BOOLEAN NOT NULL,
    units          VARCHAR,
    frequency      VARCHAR,
    transmitted_at TIMESTAMP,
    raw_id         BIGINT NOT NULL
);

CREATE TABLE tic_observation (
    series_id     VARCHAR NOT NULL,
    date          DATE NOT NULL,
    value         DECIMAL(24, 6),
    first_seen_at TIMESTAMP NOT NULL,
    raw_id        BIGINT NOT NULL,
    PRIMARY KEY (series_id, date, first_seen_at)
);

CREATE MACRO tic_as_of(ts) AS TABLE
SELECT series_id, date, value, first_seen_at, raw_id
FROM tic_observation
WHERE first_seen_at <= bls_as_of_utc(ts)
QUALIFY row_number() OVER (PARTITION BY series_id, date ORDER BY first_seen_at DESC) = 1;

CREATE VIEW tic_observation_latest AS
SELECT series_id, date, value, first_seen_at, raw_id
FROM tic_observation
QUALIFY row_number() OVER (PARTITION BY series_id, date ORDER BY first_seen_at DESC) = 1;
