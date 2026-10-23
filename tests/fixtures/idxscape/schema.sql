-- idxscape migration 7 (`fx_rate`), copied from ../idxscape/src/idxscape/db.py on 2026-10-23.
CREATE TABLE fx_rate (
    rate_date       DATE          NOT NULL,
    pair            VARCHAR       NOT NULL,  -- 'USDIDR'
    rate            DECIMAL(18,2) NOT NULL,
    source          VARCHAR       NOT NULL,  -- 'bi_jisdor'
    carried_forward BOOLEAN       NOT NULL,  -- BI says the day used D-1 data
    recorded_at     TIMESTAMPTZ   NOT NULL,
    PRIMARY KEY (rate_date, pair)
);
