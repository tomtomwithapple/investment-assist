-- Made-up statements shaped like the real store (issuers, doc types, minor units ×100).
-- Account refs are fake. Expected layer-5 result (IDR), latest loaded statement per account:
--   IDN stocks 700,000 (BBCA 600,000 + INCO-R 0 + TLKM 100,000 from the stale account)
--   IDN bonds  299,000 (FR0081 200,000 + PBS036 99,000)
--   IDN cash   301,000 (RDN 300,000 + broker IDR line 1,000)
--   total    1,300,000; unmapped: the mutual fund with no symbol (50,000)
INSERT INTO documents (id, sha256, file_name, issuer, parser_id, doc_type, statement_date,
    currency, number_locale, opening_minor, closing_minor, reconciled, status, account_ref,
    account_kind, portfolio_value_minor) VALUES
-- app broker (portfolio snapshot); closing = cash in its RDN, also on the RDN statement
(1, 'a1', 'a-aug.pdf', 'ajaib', 'ajaib_v1', 'portfolio', '2026-08-31', 'IDR', 'id',
    10000000, 10000000, 1, 'loaded', 'AJ-TEST', 'asset', 90000000),
(2, 'a2', 'a-sep.pdf', 'ajaib', 'ajaib_v1', 'portfolio', '2026-09-30', 'IDR', 'id',
    30000000, 30000000, 1, 'loaded', 'AJ-TEST', 'asset', 85000000),
-- RDN savings account: latest loaded is September; a superseded October must be ignored
(3, 'r1', 'r-aug.pdf', 'bca_rdn', 'bca_v1', 'savings_statement', '2026-08-31', 'IDR', 'id',
    0, 99999900, 1, 'loaded', 'RDN-TEST', 'asset', NULL),
(4, 'r2', 'r-sep.pdf', 'bca_rdn', 'bca_v1', 'savings_statement', '2026-09-30', 'IDR', 'id',
    99999900, 30000000, 1, 'loaded', 'RDN-TEST', 'asset', NULL),
(5, 'r3', 'r-oct.pdf', 'bca_rdn', 'bca_v1', 'savings_statement', '2026-10-31', 'IDR', 'id',
    30000000, 500000000, 0, 'superseded', 'RDN-TEST', 'asset', NULL),
-- broker that sold out: the latest statement has no holdings, an older one does
(6, 'm1', 'm-mar.pdf', 'mandirisek', 'mandirisek_v1', 'broker_soa', '2026-03-31', 'IDR', 'id',
    0, 0, 1, 'loaded', 'MS-TEST', 'asset', 100000000),
(7, 'm2', 'm-sep.pdf', 'mandirisek', 'mandirisek_v1', 'broker_soa', '2026-09-30', 'IDR', 'id',
    0, 0, 1, 'loaded', 'MS-TEST', 'asset', NULL),
-- broker with a cash line, a right and a sukuk in its holdings table
(8, 's1', 's-sep.pdf', 'stockbit', 'stockbit_v1', 'broker_soa', '2026-09-30', 'IDR', 'id',
    0, 0, 1, 'loaded', 'SB-TEST', 'liability', 10000000),
-- broker whose last statement is three months older than the rest, still holding a stock
(9, 'b1', 'b-jun.pdf', 'bnisek', 'bnisek_v1', 'broker_soa', '2026-06-30', 'IDR', 'us',
    0, 0, 1, 'loaded', 'BN-TEST', 'asset', NULL),
-- credit card: a liability statement, never a holding
(10, 'c1', 'c-sep.pdf', 'cimb_cc', 'cimb_v1', 'credit_card_statement', '2026-09-17', 'IDR', 'id',
    0, 123400, 1, 'loaded', NULL, 'liability', NULL);

INSERT INTO holdings (document_id, line_no, as_of, symbol, name, quantity, avg_cost_minor,
    market_price_minor, cost_value_minor, market_value_minor, unrealised_minor, currency) VALUES
(1, 1, '2026-08-31', 'BBCA', 'BANK CENTRAL ASIA Tbk', '100', 900000, 900000, 90000000, 90000000, 0, 'IDR'),
(2, 1, '2026-09-30', 'BBCA', 'BANK CENTRAL ASIA Tbk', '100', 900000, 600000, 90000000, 60000000, -30000000, 'IDR'),
(2, 2, '2026-09-30', 'FR0081', 'OBLIGASI NEGARA REPUBLIK INDONESIA SERI FR0081', '200000', 100, 100, 20000000, 20000000, 0, 'IDR'),
(2, 3, '2026-09-30', '', 'REKSA DANA INDEKS BNI AM INDEKS IDX30', '10', 500000, 500000, 5000000, 5000000, 0, 'IDR'),
(6, 1, '2026-03-31', 'ASII', 'ASTRA INTERNATIONAL Tbk', '200', 500000, 500000, 100000000, 100000000, 0, 'IDR'),
(8, 1, '2026-09-30', 'IDR', 'INDONESIA RUPIAH', '1', 100000, 100000, 100000, 100000, 0, 'IDR'),
(8, 2, '2026-09-30', 'INCO-R', 'RIGHT I VALE INDONESIA Tbk', '12', 0, 0, 0, 0, 0, 'IDR'),
(8, 3, '2026-09-30', 'PBS036', 'SBSN Seri PBS036', '100000', 100, 99, 10000000, 9900000, -100000, 'IDR'),
(9, 1, '2026-06-30', 'TLKM', 'TELKOM INDONESIA Tbk', '100', 100000, 100000, 10000000, 10000000, 0, 'IDR');
