-- bisfetcher's store DDL (../bisfetcher/src/bisfetcher/store.py SCHEMA), the contract in its PLAN.md.
CREATE TABLE IF NOT EXISTS series (
    series_id VARCHAR PRIMARY KEY, dataset VARCHAR, freq VARCHAR, ref_area VARCHAR,
    ref_area_name VARCHAR, title VARCHAR, unit VARCHAR, unit_code VARCHAR, unit_mult INTEGER,
    decimals INTEGER, dims JSON, attrs JSON, key VARCHAR, updated_at TIMESTAMP,
    discontinued_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS observations (
    series_id VARCHAR, date DATE, period VARCHAR, period_end DATE, value DOUBLE,
    obs_status VARCHAR, first_seen_at TIMESTAMP, updated_at TIMESTAMP,
    PRIMARY KEY (series_id, date)
);
CREATE TABLE IF NOT EXISTS datasets (
    dataset VARCHAR PRIMARY KEY, name VARCHAR, version VARCHAR, structure_pulled_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS fetch_log (
    dataset VARCHAR, key VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP, status VARCHAR,
    series INTEGER, observations INTEGER, error VARCHAR, raw_path VARCHAR
);
CREATE OR REPLACE VIEW observation_latest AS
SELECT o.series_id, o.date, o.period, o.period_end, o.value, o.obs_status, o.updated_at,
       s.dataset, s.freq, s.ref_area, s.title, s.unit
FROM observations o JOIN series s USING (series_id)
QUALIFY row_number() OVER (PARTITION BY o.series_id ORDER BY o.date DESC) = 1;
