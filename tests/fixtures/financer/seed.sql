-- Made-up statements shaped like the real store (issuers, doc types, minor units ×100).
-- Account refs are fake. Expected layer-5 result (IDR), latest loaded statement per account,
-- rolled forward through the loaded `trades` documents dated after it (PLAN S32):
--   IDN stocks 1,960,000 (BBCA 600,000 + INCO-R 0 + TLKM 100,000 from the stale account
--                         + UNVR 420,000 rolled at AJ-TWO + BBRI 840,000 at SB-PRIS)
--   IDN bonds    299,000 (FR0081 200,000 + PBS036 99,000)
--   IDN cash     301,000 (RDN 300,000 + broker IDR line 1,000)
--   total      2,560,000 = tommy 1,720,000 + priskila 840,000
--   unmapped: the mutual fund with no symbol (50,000) and ADRO sold below zero (-250,000)
-- Without the trades (statements only, as before S32): 1,300,000, stocks 700,000.
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

-- ---------------- schema 9 (financer slices 12-13): owners and trade documents ----------------
-- AJ-TWO, an Ajaib-like account: a 2026-09-30 portfolio (ARNA 1000 sh, UNVR 100 sh), then dailies.
--   doc 12 (2026-09-30, on the statement date) is already in the portfolio: ignored.
--   doc 13 sells ARNA to zero (line dropped); doc 14 buys UNVR, now 200 sh at 2,100 = 420,000.
-- SB-PRIS, the second owner's Stockbit account: trade confirmations only, no SOA.
--   doc 15 buys BBRI 100 at 4,000 and GOTO 1000 at 60; doc 16 is superseded (ignored);
--   doc 17 buys BBRI 100 at 4,200 (last price), sells GOTO 1000 (zero), sells ADRO 100 that no
--   statement shows (-100 sh, -250,000: unmapped, never subtracted).
INSERT INTO documents (id, sha256, file_name, issuer, parser_id, doc_type, statement_date,
    currency, number_locale, opening_minor, closing_minor, reconciled, status, account_ref,
    account_kind, portfolio_value_minor, owner) VALUES
(11, 'a3', 'a2-sep.pdf', 'ajaib', 'ajaib_v1', 'portfolio', '2026-09-30', 'IDR', 'id',
    0, 0, 1, 'loaded', 'AJ-TWO', 'asset', 70000000, 'tommy'),
(12, 'd1', 'd-0930.pdf', 'ajaib', 'ajaib_daily_v1', 'trades', '2026-09-30', 'IDR', 'id',
    0, 0, 1, 'loaded', 'AJ-TWO', 'asset', NULL, 'tommy'),
(13, 'd2', 'd-1002.pdf', 'ajaib', 'ajaib_daily_v1', 'trades', '2026-10-02', 'IDR', 'id',
    0, 0, 1, 'loaded', 'AJ-TWO', 'asset', NULL, 'tommy'),
(14, 'd3', 'd-1003.pdf', 'ajaib', 'ajaib_daily_v1', 'trades', '2026-10-03', 'IDR', 'id',
    0, 0, 1, 'loaded', 'AJ-TWO', 'asset', NULL, 'tommy'),
(15, 't1', 'tc-1016.pdf', 'stockbit', 'stockbit_tc_v1', 'trades', '2026-10-16', 'IDR', 'id',
    0, 0, 1, 'loaded', 'SB-PRIS', 'asset', NULL, 'priskila'),
(16, 't2', 'tc-1018.pdf', 'stockbit', 'stockbit_tc_v1', 'trades', '2026-10-18', 'IDR', 'id',
    0, 0, 1, 'superseded', 'SB-PRIS', 'asset', NULL, 'priskila'),
(17, 't3', 'tc-1020.pdf', 'stockbit', 'stockbit_tc_v1', 'trades', '2026-10-20', 'IDR', 'id',
    0, 0, 1, 'loaded', 'SB-PRIS', 'asset', NULL, 'priskila');

INSERT INTO holdings (document_id, line_no, as_of, symbol, name, quantity, avg_cost_minor,
    market_price_minor, cost_value_minor, market_value_minor, unrealised_minor, currency) VALUES
(11, 1, '2026-09-30', 'ARNA', 'ARWANA CITRAMULIA Tbk', '1000', 50000, 50000, 50000000, 50000000, 0, 'IDR'),
(11, 2, '2026-09-30', 'UNVR', 'UNILEVER INDONESIA Tbk', '100', 200000, 200000, 20000000, 20000000, 0, 'IDR');

INSERT INTO trades (document_id, trade_date, settle_date, reference, symbol, side, board,
    quantity, price_minor, gross_minor, net_minor, fees_minor, currency, dedup_key) VALUES
(12, '2026-09-30', '2026-10-02', 'R1', 'UNVR', 'buy', 'RG', '100', 190000, 19000000, 19000000, 0, 'IDR', 'k1'),
(13, '2026-10-02', '2026-10-06', 'R2', 'ARNA', 'sell', 'RG', '1000', 52000, 52000000, 52000000, 0, 'IDR', 'k2'),
(14, '2026-10-03', '2026-10-07', 'R3', 'UNVR', 'buy', 'RG', '100', 210000, 21000000, 21000000, 0, 'IDR', 'k3'),
(15, '2026-10-16', '2026-10-20', 'S1', 'BBRI', 'buy', 'RG', '100', 400000, 40000000, 40000000, 0, 'IDR', 'k4'),
(15, '2026-10-16', '2026-10-20', 'S2', 'GOTO', 'buy', 'RG', '1000', 6000, 6000000, 6000000, 0, 'IDR', 'k5'),
(16, '2026-10-18', '2026-10-22', 'S3', 'BBRI', 'buy', 'RG', '9900', 410000, 4059000000, 4059000000, 0, 'IDR', 'k6'),
(17, '2026-10-20', '2026-10-22', 'S4', 'BBRI', 'buy', 'RG', '100', 420000, 42000000, 42000000, 0, 'IDR', 'k7'),
(17, '2026-10-20', '2026-10-22', 'S5', 'GOTO', 'sell', 'RG', '1000', 7000, 7000000, 7000000, 0, 'IDR', 'k8'),
(17, '2026-10-20', '2026-10-22', 'S6', 'ADRO', 'sell', 'RG', '100', 250000, 25000000, 25000000, 0, 'IDR', 'k9');

INSERT INTO account_owners (issuer, account_ref, owner) VALUES
('ajaib', 'AJ-TEST', 'tommy'), ('ajaib', 'AJ-TWO', 'tommy'), ('stockbit', 'SB-PRIS', 'priskila');
