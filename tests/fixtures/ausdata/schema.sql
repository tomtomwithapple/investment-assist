-- ausdata's own DDL (../ausdata/src/ausdata/store.py SCHEMA, as of S26 632727a).
CREATE TABLE IF NOT EXISTS observations (
    series_id TEXT, source TEXT, date DATE, value DOUBLE, unit TEXT, frequency TEXT,
    pulled_at TIMESTAMP, PRIMARY KEY (series_id, date)
);
CREATE TABLE IF NOT EXISTS series_meta (
    series_id TEXT PRIMARY KEY, source TEXT, title TEXT, description TEXT, unit TEXT,
    frequency TEXT, extra JSON
);
CREATE TABLE IF NOT EXISTS raw_loads (
    source TEXT, dataset TEXT, path TEXT, loaded_at TIMESTAMP, PRIMARY KEY (source, dataset)
);
