-- idxscape migration 9 (phei): igsyc_point, phei_bond_quote, credit_curve_point, copied from
-- ../idxscape/src/idxscape/db.py on 2026-10-23 (phei_snapshot/phei_revision are not read here).
CREATE TABLE igsyc_point (
    as_of                 DATE          NOT NULL,
    tenor_y               DECIMAL(6,2)  NOT NULL,
    yield_pct             DECIMAL(10,4) NOT NULL,
    from_yesterday_column BOOLEAN       NOT NULL,
    artifact_sha256       VARCHAR       NOT NULL,
    fetched_at            TIMESTAMPTZ   NOT NULL,
    PRIMARY KEY (as_of, tenor_y)
);
CREATE TABLE phei_bond_quote (
    as_of                 DATE          NOT NULL,
    series_code           VARCHAR       NOT NULL,
    grp                   VARCHAR       NOT NULL CHECK (grp IN ('SBN_BENCHMARK', 'SBSN_BENCHMARK', 'RETAIL')),
    ttm_y                 DECIMAL(8,2),
    yield_pct             DECIMAL(10,4),
    price_pct             DECIMAL(10,4),
    coupon_pct            DECIMAL(10,4),
    from_yesterday_column BOOLEAN       NOT NULL,
    artifact_sha256       VARCHAR       NOT NULL,
    fetched_at            TIMESTAMPTZ   NOT NULL,
    PRIMARY KEY (as_of, series_code, grp)
);
CREATE TABLE credit_curve_point (
    as_of                 DATE          NOT NULL,
    tenor_y               DECIMAL(6,2)  NOT NULL,
    rating                VARCHAR       NOT NULL,
    yield_pct             DECIMAL(10,4) NOT NULL,
    artifact_sha256       VARCHAR       NOT NULL,
    fetched_at            TIMESTAMPTZ   NOT NULL,
    PRIMARY KEY (as_of, tenor_y, rating)
);
