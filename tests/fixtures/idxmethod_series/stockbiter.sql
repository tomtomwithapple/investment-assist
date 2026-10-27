-- Tiny stand-in for ../idx-method/store/data/stockbiter.db (schema copied read-only 2026-10-27).
CREATE TABLE factor_series (
    freq   TEXT NOT NULL,
    symbol TEXT NOT NULL,
    item   TEXT NOT NULL,
    date   TEXT NOT NULL,
    value,
    PRIMARY KEY (freq, symbol, item, date)
);
CREATE TABLE factor_universe (
    symbol   TEXT PRIMARY KEY,
    name     TEXT,
    sector   TEXT,
    status   TEXT,
    delisted INTEGER
);
CREATE TABLE dividends (
    symbol TEXT NOT NULL,
    seq    INTEGER NOT NULL,
    ex     TEXT,
    value  REAL,
    ccy    TEXT,
    PRIMARY KEY (symbol, seq)
);
INSERT INTO factor_universe VALUES
  ('BBCA', 'Bank Central Asia Tbk.', 'Keuangan', 'STATUS_ACTIVE', 0),
  ('LOSS', 'Loss Maker Tbk.', 'Teknologi', 'STATUS_ACTIVE', 0),
  ('GONE', 'Delisted Tbk.', 'Energi', 'STATUS_DELISTED', 1);
INSERT INTO factor_series VALUES
  ('daily', 'BBCA', 'price',  '2025-12-30', 8000),
  ('daily', 'BBCA', 'mktcap', '2025-12-30', 1000000),
  ('daily', 'BBCA', 'price',  '2026-04-30', 9000),
  ('daily', 'BBCA', 'mktcap', '2026-04-30', 1200000),
  ('daily', 'BBCA', 'price',  '2026-06-30', 9500),
  ('daily', 'BBCA', 'mktcap', '2026-06-30', 1300000),
  ('daily', 'BBCA', 'price',  '2026-07-01', 9400),
  ('daily', 'BBCA', 'price',  '2026-10-26', 4940),
  ('daily', 'BBCA', 'mktcap', '2026-10-26', 600000),
  ('quarterly', 'BBCA', 'ni_ttm',        '2025-12-31', 100000),
  ('quarterly', 'BBCA', 'equity',        '2025-12-31', 400000),
  ('quarterly', 'BBCA', 'cfo_ttm',       '2025-12-31', 80000),
  ('quarterly', 'BBCA', 'op_income_ttm', '2025-12-31', 120000),
  ('quarterly', 'BBCA', 'net_debt',      '2025-12-31', -200000),
  ('quarterly', 'BBCA', 'roa',           '2025-12-31', 3.63),
  ('quarterly', 'BBCA', 'roce',          '2025-12-31', 4.56),
  ('quarterly', 'BBCA', 'total_assets',  '2025-12-31', 1500000),
  ('quarterly', 'BBCA', 'total_debt',    '2025-12-31', 1000),
  ('quarterly', 'BBCA', 'ni_ttm',        '2026-03-31', 120000),
  ('quarterly', 'BBCA', 'equity',        '2026-03-31', 480000),
  ('quarterly', 'BBCA', 'cfo_ttm',       '2026-03-31', 60000),
  ('quarterly', 'BBCA', 'op_income_ttm', '2026-03-31', 150000),
  ('quarterly', 'BBCA', 'net_debt',      '2026-03-31', 300000),
  ('quarterly', 'BBCA', 'roa',           '2026-03-31', 3.54),
  -- the store echoes the latest quarter on the pull date; it is not a quarter end
  ('quarterly', 'BBCA', 'ni_ttm',        '2026-10-26', 120000),
  ('quarterly', 'BBCA', 'equity',        '2026-10-26', 480000),
  ('daily', 'LOSS', 'price',  '2026-10-26', 50),
  ('daily', 'LOSS', 'mktcap', '2026-10-26', 1000),
  ('quarterly', 'LOSS', 'ni_ttm',        '2025-12-31', -10),
  ('quarterly', 'LOSS', 'equity',        '2025-12-31', 0),
  ('quarterly', 'LOSS', 'cfo_ttm',       '2025-12-31', -5),
  ('quarterly', 'LOSS', 'op_income_ttm', '2025-12-31', 0),
  ('quarterly', 'LOSS', 'net_debt',      '2025-12-31', 100),
  ('daily', 'GONE', 'price',  '2017-03-01', 100),
  ('daily', 'GONE', 'mktcap', '2017-03-01', 5000),
  ('quarterly', 'GONE', 'ni_ttm', '2016-12-31', 500),
  ('quarterly', 'GONE', 'ni_ttm', '2019-12-10', 999);
INSERT INTO dividends VALUES
  ('BBCA', 1, '2026-03-30', 281.0, 'CURRENCY_IDR'),
  ('BBCA', 0, '2025-12-03', 55.0, 'CURRENCY_IDR'),
  ('GONE', 0, '2017-06-01', 10.0, 'CURRENCY_IDR');
