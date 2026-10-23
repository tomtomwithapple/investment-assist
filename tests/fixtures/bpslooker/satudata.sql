-- satudatascape tables the parent reads (its migrations/0001_init.sql, checked 2026-10-23).
CREATE TABLE tables (resource_id TEXT PRIMARY KEY, parser TEXT, path TEXT, n_rows INT, n_cols INT,
       columns TEXT, sheets TEXT, quality TEXT, warnings TEXT, extracted_at TEXT);
CREATE TABLE runs (id INTEGER PRIMARY KEY, kind TEXT, started_at TEXT, finished_at TEXT,
     count_search INT, count_list INT, count_stored INT, upserts INT,
     changed INT, errors INT, checkpoint TEXT, notes TEXT);
INSERT INTO runs VALUES
  (1, 'crawl', '2026-10-20T01:00:00Z', '2026-10-20T01:40:00Z', 10, 10, 120, 120, 5, 0, null, null),
  (2, 'crawl', '2026-10-22T01:00:00Z', '2026-10-22T01:35:00Z', 10, 10, 130, 130, 3, 1, null, null),
  (3, 'download', '2026-10-22T02:00:00Z', '2026-10-22T02:10:00Z', 0, 0, 40, 0, 0, 2, null, null),
  (4, 'crawl', '2026-10-23T01:00:00Z', null, 0, 0, 0, 0, 0, 0, null, 'running');
INSERT INTO tables VALUES
  ('r-a', 'xlsx', 'tables/r-a.parquet', 34, 5, '["provinsi","tahun","nilai"]', null, 'A', null, '2026-10-22T02:05:00Z'),
  ('r-b', 'csv', 'tables/r-b.parquet', 12, 3, '["tahun","nilai"]', null, 'B', null, '2026-10-22T02:06:00Z'),
  ('r-c', 'pdf', 'tables/r-c.parquet', 3, 9, '[]', null, 'C', '["merged cells"]', '2026-10-22T02:07:00Z');
