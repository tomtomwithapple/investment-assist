-- financer's `documents`, `holdings`, `trades` and `account_owners` (schema version 9), copied
-- from ~/.financer/financer.db on 2026-10-23 and from financer's migrations 004 (trades) and 009
-- (owner, account_owners, slice 12). Money is integer minor units, scale 100 (financer
-- src/financer/money.py MINOR_SCALE). The account is documents.account_ref; there is no accounts
-- table and holdings and trades carry no account id. `schema8.sql` turns this back into schema 8.
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
    , account_ref TEXT, account_kind TEXT NOT NULL DEFAULT 'liability', period_start TEXT, portfolio_cost_minor INTEGER, portfolio_value_minor INTEGER, portfolio_unrealised_minor INTEGER, carries_forward INTEGER NOT NULL DEFAULT 1, states_trades INTEGER NOT NULL DEFAULT 1, review_reason TEXT, review_note TEXT, owner TEXT DEFAULT 'tommy');
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
CREATE TABLE trades (
        id              INTEGER PRIMARY KEY,
        document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        trade_date      TEXT NOT NULL,
        settle_date     TEXT,
        reference       TEXT NOT NULL,
        symbol          TEXT NOT NULL,
        side            TEXT NOT NULL,
        board           TEXT NOT NULL,
        quantity        TEXT NOT NULL,
        price_minor     INTEGER NOT NULL,
        gross_minor     INTEGER NOT NULL,
        net_minor       INTEGER NOT NULL,
        fees_minor      INTEGER NOT NULL,
        currency        TEXT NOT NULL,
        dedup_key       TEXT NOT NULL UNIQUE
    );
CREATE INDEX idx_trade_symbol ON trades(symbol, trade_date);
CREATE TABLE account_owners (
        issuer      TEXT NOT NULL,
        account_ref TEXT NOT NULL,
        owner       TEXT NOT NULL,
        set_at      TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (issuer, account_ref)
    );
