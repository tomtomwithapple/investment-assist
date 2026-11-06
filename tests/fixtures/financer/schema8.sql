-- Applied after schema.sql + seed.sql: financer schema 8, before slice 12's migration 009.
-- No documents.owner and no account_owners; the adapter then takes every document as 'tommy'.
ALTER TABLE documents DROP COLUMN owner;
DROP TABLE account_owners;
