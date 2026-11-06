-- financer's `transactions` table as on ~/.financer/financer.db (schema 9), applied after
-- tests/fixtures/financer/schema.sql. Money is integer minor units, scale 100, always positive;
-- `direction` is debit or credit. A row belongs to its document (`document_id`).
CREATE TABLE transactions (
        id              INTEGER PRIMARY KEY,
        document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        txn_date        TEXT NOT NULL,
        posting_date    TEXT,
        description     TEXT NOT NULL,
        raw_description TEXT NOT NULL,
        amount_minor    INTEGER NOT NULL,
        direction       TEXT NOT NULL,
        dedup_key       TEXT NOT NULL UNIQUE
    , ledger TEXT, branch_code TEXT, reference TEXT);
CREATE INDEX idx_txn_date ON transactions(txn_date);
