-- idxscape migration 10 (`index_daily`), copied from ../idxscape/src/idxscape/db.py on 2026-11-06.
CREATE TABLE index_daily (
    trade_date       DATE    NOT NULL,
    index_code       VARCHAR NOT NULL,
    previous         DOUBLE  NOT NULL,
    high             DOUBLE,
    low              DOUBLE,
    close            DOUBLE  NOT NULL,
    change           DOUBLE,
    number_of_stocks INTEGER,
    volume_shares    BIGINT  NOT NULL,
    value_idr        BIGINT  NOT NULL,
    frequency        BIGINT  NOT NULL,
    market_cap_idr   BIGINT,
    row_no           INTEGER,
    server_row_id    BIGINT,
    PRIMARY KEY (trade_date, index_code)
);
-- the fixture's idxscape history starts 2026-09-29 so the seam with the idx-method fixture
-- (2026-09-28..30) is inside it; 2026-09-30 closes 0.004 apart, as idxscape K1 found.
INSERT INTO index_daily (trade_date, index_code, previous, close, volume_shares, value_idr, frequency) VALUES
    ('2026-09-29', 'COMPOSITE', 6118.81, 6121.70, 1, 1, 1),
    ('2026-09-30', 'COMPOSITE', 6121.70, 6071.142, 1, 1, 1),
    ('2026-10-01', 'COMPOSITE', 6071.14, 6100.50, 1, 1, 1),
    ('2026-11-05', 'COMPOSITE', 6100.50, 6250.25, 1, 1, 1),
    ('2026-09-30', 'LQ45', 800.0, 801.5, 1, 1, 1),
    ('2026-11-05', 'LQ45', 801.5, 820.0, 1, 1, 1),
    ('2026-11-05', 'IDXENERGY', 3000.0, 3010.0, 1, 1, 1);
