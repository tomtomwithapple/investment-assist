-- idxscape migrations 1 (stock_summary), 2 (trading_day), 4 (broker_summary), 7 (fx_rate) and
-- 8 (sbn_ownership, sbn_ownership_file), copied from ../idxscape/src/idxscape/db.py on 2026-10-23.
CREATE TABLE stock_summary (
    trade_date                DATE    NOT NULL,
    code                      VARCHAR NOT NULL,
    name                      VARCHAR,
    remarks                   VARCHAR,
    previous                  BIGINT  NOT NULL,
    open_price                BIGINT,
    first_trade               BIGINT,
    high                      BIGINT,
    low                       BIGINT,
    close                     BIGINT  NOT NULL,
    change                    BIGINT,
    volume_shares             BIGINT  NOT NULL,
    value_idr                 BIGINT  NOT NULL,
    frequency                 BIGINT  NOT NULL,
    non_regular_volume_shares BIGINT,
    non_regular_value_idr     BIGINT,
    non_regular_frequency     BIGINT,
    index_individual          DOUBLE,
    offer                     BIGINT,
    offer_volume_shares       BIGINT,
    bid                       BIGINT,
    bid_volume_shares         BIGINT,
    listed_shares             BIGINT  NOT NULL,
    tradeable_shares          BIGINT,
    weight_for_index          BIGINT,
    foreign_buy_shares        BIGINT  NOT NULL,
    foreign_sell_shares       BIGINT  NOT NULL,
    net_foreign_shares        BIGINT  NOT NULL,
    net_foreign_value_est_idr BIGINT  NOT NULL,
    delisting_date            DATE,
    persen                    DOUBLE,
    percentage                DOUBLE,
    row_no                    INTEGER,
    server_row_id             BIGINT,
    PRIMARY KEY (trade_date, code)
);
CREATE TABLE trading_day (
    trade_date  DATE        PRIMARY KEY,
    is_trading  BOOLEAN     NOT NULL,
    row_count   INTEGER     NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE broker_summary (
    trade_date    DATE    NOT NULL,
    broker_code   VARCHAR NOT NULL,
    broker_name   VARCHAR,
    volume_shares BIGINT  NOT NULL,
    value_idr     BIGINT  NOT NULL,
    frequency     BIGINT  NOT NULL,
    row_no        INTEGER,
    server_row_id BIGINT,
    PRIMARY KEY (trade_date, broker_code)
);
CREATE TABLE fx_rate (
    rate_date       DATE          NOT NULL,
    pair            VARCHAR       NOT NULL,
    rate            DECIMAL(18,2) NOT NULL,
    source          VARCHAR       NOT NULL,
    carried_forward BOOLEAN       NOT NULL,
    recorded_at     TIMESTAMPTZ   NOT NULL,
    PRIMARY KEY (rate_date, pair)
);
CREATE TABLE sbn_ownership (
    as_of           DATE    NOT NULL,
    instrument      VARCHAR NOT NULL CHECK (instrument IN ('SUN', 'SBSN', 'TOTAL')),
    investor_type   VARCHAR NOT NULL,
    amount_idr      BIGINT  NOT NULL,
    artifact_sha256 VARCHAR NOT NULL,
    PRIMARY KEY (as_of, instrument, investor_type)
);
CREATE TABLE sbn_ownership_file (
    sha256      VARCHAR PRIMARY KEY,
    source      VARCHAR NOT NULL,
    name        VARCHAR NOT NULL,
    format      VARCHAR NOT NULL,
    fingerprint VARCHAR NOT NULL,
    first_date  DATE    NOT NULL,
    last_date   DATE    NOT NULL,
    days        INTEGER NOT NULL,
    rows        INTEGER NOT NULL,
    revised     INTEGER NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    loaded_at   TIMESTAMPTZ NOT NULL
);
