-- dbnomics store DDL (tables the adapter reads), copied from ../dbnomics/src/dbnomics/store.py
create table if not exists series (
    series_id varchar primary key,
    title varchar,
    country varchar,
    freq varchar,
    unit varchar,
    grp varchar,
    chain json,
    max_lag_days integer
);
create table if not exists observations (
    series_id varchar,
    date date,
    period varchar,
    value double,
    source varchar,
    source_series_id varchar,
    fetched_at timestamp,
    primary key (series_id, date)
);
create table if not exists series_status (
    series_id varchar primary key,
    source varchar,
    latest_period varchar,
    stale boolean,
    checked_at timestamp
);
create table if not exists damodaran_crp (
    snapshot_date date,
    country varchar,
    iso3 varchar,
    region varchar,
    moodys varchar,
    sp_rating varchar,
    default_spread double,
    cds_spread double,
    crp double,
    total_erp double,
    crp_cds double,
    total_erp_cds double,
    us_erp_base double,
    file varchar,
    primary key (snapshot_date, country)
);
create table if not exists damodaran_erp (
    date date,
    freq varchar,
    variant varchar,
    value double,
    sp500 double,
    tbond double,
    primary key (date, freq, variant)
);
create table if not exists shiller (
    date date primary key,
    price double,
    dividend double,
    earnings double,
    cpi double,
    gs10 double,
    cape double,
    tr_cape double,
    excess_cape_yield double,
    provisional boolean
);
create or replace view series_latest as
with ranked as (
    select
        series_id, date, value, source,
        lead(value) over (partition by series_id order by date desc) as prev_value,
        row_number() over (partition by series_id order by date desc) as rn
    from observations
)
select
    r.series_id, r.date, r.value, r.prev_value,
    r.value - r.prev_value as change,
    r.source, s.stale
from ranked r
left join series_status s using (series_id)
where r.rn = 1;
