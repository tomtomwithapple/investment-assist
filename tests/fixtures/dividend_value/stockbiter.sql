-- Tiny stand-in for ../idx-method/store/data/stockbiter.db (schema copied read-only 2026-10-27):
-- factor_series, factor_universe, dividends, and fundamentals (only `shares` rows are read here).
-- SPLT did a 1:5 split in 2021-10 (dividends unadjusted, prices adjusted, as the real store).
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
CREATE TABLE fundamentals (
    symbol   TEXT NOT NULL,
    stmt     TEXT NOT NULL,
    item     TEXT NOT NULL,
    period   TEXT NOT NULL,
    value    REAL,
    currency TEXT,
    PRIMARY KEY (symbol, stmt, item, period)
);
INSERT INTO factor_universe VALUES
  ('SPLT', 'Split Tbk.', 'Keuangan', 'STATUS_ACTIVE', 0),
  ('PLAIN', 'Plain Tbk.', 'Energi', 'STATUS_ACTIVE', 0);
INSERT INTO factor_series VALUES
  ('daily', 'SPLT', 'price',  '2021-04-01', 1000),
  ('daily', 'SPLT', 'mktcap', '2021-04-01', 100000),
  ('daily', 'SPLT', 'price',  '2022-04-01', 1000),
  ('daily', 'SPLT', 'mktcap', '2022-04-01', 100000),
  ('daily', 'PLAIN', 'price',  '2022-04-01', 500),
  ('daily', 'PLAIN', 'mktcap', '2022-04-01', 5000),
  ('quarterly', 'SPLT', 'ni_ttm', '2021-12-31', 10000),
  ('quarterly', 'SPLT', 'equity', '2021-12-31', 50000),
  ('quarterly', 'SPLT', 'cfo_ttm', '2021-12-31', 12000),
  ('quarterly', 'SPLT', 'ni_ttm', '2026-10-26', 10000);
INSERT INTO dividends VALUES
  ('SPLT', 1, '2021-04-08', 250.0, 'CURRENCY_IDR'),
  ('SPLT', 2, '2022-04-08', 50.0, 'CURRENCY_IDR'),
  ('PLAIN', 1, '2022-04-08', 20.0, 'CURRENCY_IDR');
INSERT INTO fundamentals VALUES
  ('SPLT', 'is', 'shares', '2021Q2', 20.0, 'IDR'),
  ('SPLT', 'is', 'shares', '2022Q2', 100.0, 'IDR'),
  ('SPLT', 'is', 'eps', '2022Q2', 100.0, 'IDR');
