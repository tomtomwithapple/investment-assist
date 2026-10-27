-- sec-edgar DDL for what P39 reads (migrations 007, 014, 019, 025), read 2026-10-27.
-- alpaca_universe is a view over alpaca_asset_history and alpaca_corp_action_latest upstream
-- (024); here it is a table with its two columns. alpaca_bar_adjusted_lookup(sym) (027 + 028)
-- is a stand-in over fixture_adjusted: every bar of the security the symbol names, with the
-- same columns (security_key, date, symbol, close, adj_close, split_factor, tr_factor).
CREATE TABLE edgar_company (
    cik         BIGINT NOT NULL,
    ticker      VARCHAR NOT NULL,
    title       VARCHAR NOT NULL,
    ticker_norm VARCHAR NOT NULL,
    active      BOOLEAN NOT NULL,
    updated_at  TIMESTAMP NOT NULL,
    PRIMARY KEY (cik, ticker)
);
CREATE TABLE xbrl_fact (
    cik          BIGINT NOT NULL,
    taxonomy     VARCHAR NOT NULL,
    tag          VARCHAR NOT NULL,
    unit         VARCHAR NOT NULL,
    accn         VARCHAR NOT NULL,
    period_start DATE NOT NULL,
    period_end   DATE NOT NULL,
    is_instant   BOOLEAN NOT NULL,
    value        DOUBLE NOT NULL,
    fy           INTEGER,
    fp           VARCHAR,
    form         VARCHAR NOT NULL,
    filed        DATE NOT NULL,
    frame        VARCHAR
);
CREATE MACRO xbrl_as_of(d) AS TABLE
SELECT * FROM xbrl_fact WHERE filed <= CAST(d AS DATE);
CREATE MACRO ticker_norm(s) AS regexp_replace(regexp_replace(regexp_replace(
    translate(replace(upper(trim(s)), '$', '.P'), '-/ ', '...'),
    '\.UN$', '.U'), '\.WT$', '.W'), '\.RI$', '.R');
CREATE TABLE alpaca_universe (symbol VARCHAR, source VARCHAR);
CREATE TABLE alpaca_bar (
    symbol         VARCHAR NOT NULL,
    date           DATE NOT NULL,
    open           DOUBLE,
    high           DOUBLE,
    low            DOUBLE,
    close          DOUBLE,
    volume         BIGINT,
    trade_count    BIGINT,
    vwap           DOUBLE,
    first_seen_at  TIMESTAMP NOT NULL,
    raw_id         BIGINT NOT NULL
);
CREATE TABLE fixture_adjusted (
    security_key VARCHAR, date DATE, symbol VARCHAR, close DOUBLE, adj_close DOUBLE,
    split_factor DOUBLE, tr_factor DOUBLE
);
CREATE MACRO alpaca_bar_adjusted_lookup(sym) AS TABLE
SELECT * FROM fixture_adjusted
WHERE security_key IN (SELECT security_key FROM fixture_adjusted WHERE symbol = upper(sym)
                       ORDER BY date DESC LIMIT 1);
