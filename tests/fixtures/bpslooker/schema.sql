-- DuckDB stand-in for bps-looker's Postgres tables the adapter reads (public schema, Alembic
-- migrations up to 0012, checked read-only 2026-10-23). Columns and types as in Postgres.
create table variable (
  domain_id varchar(4) not null, var_id integer not null, title text not null, unit text,
  last_update timestamp, primary key (domain_id, var_id)
);
create table period (
  domain_id varchar(4) not null, var_id integer not null, th_id integer not null,
  label text not null, primary key (domain_id, var_id, th_id)
);
create table observation (
  domain_id varchar(4) not null, var_id integer not null, vervar bigint not null,
  turvar integer not null, th integer not null, turth integer not null, value numeric not null,
  last_update timestamp, fetched_at timestamptz not null,
  primary key (domain_id, var_id, vervar, turvar, th, turth)
);
create table trade_flow (
  flow smallint not null, period_type smallint not null, year smallint not null,
  month smallint not null, hs2 varchar(2) not null, port text not null, country text not null,
  value_usd numeric, netweight_kg numeric, fetched_at timestamptz not null,
  primary key (flow, period_type, year, month, hs2, port, country)
);
