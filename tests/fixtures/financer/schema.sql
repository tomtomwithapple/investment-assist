-- financer's `documents` and `holdings` (schema version 8), copied read-only from
-- ~/.financer/financer.db on 2026-10-23. Money is integer minor units, scale 100
-- (financer src/financer/money.py MINOR_SCALE). The account is documents.account_ref; there is
-- no accounts table and holdings carry no account id.
CREATE TABLE documents (
        id              INTEGER PRIMARY KEY,
        sha256          TEXT NOT NULL UNIQUE,
        file_name       TEXT NOT NULL,
        issuer          TEXT NOT NULL,
        parser_id       TEXT NOT NULL,
        doc_type        TEXT NOT NULL,
        statement_date  TEXT NOT NULL,
        due_date        TEXT,
        card_last4      TEXT,
        currency        TEXT NOT NULL,
        number_locale   TEXT NOT NULL,
        opening_minor   INTEGER NOT NULL,
        closing_minor   INTEGER NOT NULL,
        minimum_minor   INTEGER,
        reconciled      INTEGER NOT NULL,
        status          TEXT NOT NULL,
        ingested_at     TEXT NOT NULL DEFAULT (datetime('now'))
    , account_ref TEXT, account_kind TEXT NOT NULL DEFAULT 'liability', period_start TEXT, portfolio_cost_minor INTEGER, portfolio_value_minor INTEGER, portfolio_unrealised_minor INTEGER, carries_forward INTEGER NOT NULL DEFAULT 1, states_trades INTEGER NOT NULL DEFAULT 1, review_reason TEXT, review_note TEXT);
CREATE INDEX idx_doc_issuer ON documents(issuer, statement_date);
CREATE INDEX idx_doc_account ON documents(account_ref, statement_date);
CREATE TABLE holdings (
        id              INTEGER PRIMARY KEY,
        document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        line_no         INTEGER NOT NULL,
        as_of           TEXT NOT NULL,
        symbol          TEXT NOT NULL,
        name            TEXT NOT NULL,
        quantity        TEXT NOT NULL,
        avg_cost_minor  INTEGER NOT NULL,
        market_price_minor INTEGER NOT NULL,
        cost_value_minor   INTEGER NOT NULL,
        market_value_minor INTEGER NOT NULL,
        unrealised_minor   INTEGER NOT NULL,
        currency        TEXT NOT NULL,
        UNIQUE (document_id, line_no)
    );
CREATE INDEX idx_holding_symbol ON holdings(symbol, as_of);
