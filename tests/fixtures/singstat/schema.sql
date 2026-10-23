-- singstat (sgecon) store schema, copied from ../singstat/src/sgecon/store.py SCHEMA (2026-10-23)
-- plus refresh_log as found in the live data/sgecon.duckdb.
create table series (
    series_id varchar primary key,
    source varchar,
    title varchar,
    unit varchar,
    frequency varchar,
    updated_at timestamp
);
create table observations (
    series_id varchar,
    date date,
    value double,
    unit varchar,
    source varchar,
    primary key (series_id, date)
);
create table refresh_log (
    source varchar,
    started_at timestamp,
    finished_at timestamp,
    status varchar,
    detail varchar
);
