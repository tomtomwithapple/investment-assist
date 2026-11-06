-- A made-up household for PLAN S38 (/flows), applied after financer/schema.sql and
-- flows/transactions.sql. Accounts, names and amounts are invented. Expected for 2026-10:
--   matched (5): SAV-1111 -> RDN-8888 1,000,000 (between owners, names SARI CONTOH);
--                RDN-2222 -> AJ-3333 500,050 (the daily's one settlement, not its fee rows);
--                SAV-1111 -> CC-4444 2,500,000 (card payment, a day apart);
--                SAV-1111 -> RDN-2222 250,000 twice, 10-15 with 10-15 and 10-16 with 10-16.
--   unmatched named (1): SAV-1111 4,000,000 on 10-14 to priskila (her receiving account has no
--                statement). The 10-02 debit also names her but is matched.
--   unmatched settlement (1): SB-7777 1,234,567.89 on 10-20 (no RDN statement of hers).
--   no match: 300,000 vs 300,001 (1 rupiah); 700,000 four days apart (the superseded RDN
--   statement's 700,000 on 10-05 must not count); 1,450,000 out and in on SAV-1111 itself;
--   the card purchase of 2,500,000 on 10-22 (purchases are spending, never a transfer).
--   stale: CIMB-9999 has a September statement and none in October; RDN-9999 is mapped to
--   priskila and has no statement at all.
INSERT INTO documents (id, sha256, file_name, issuer, parser_id, doc_type, statement_date,
    currency, number_locale, opening_minor, closing_minor, reconciled, status, account_ref,
    account_kind, owner, period_start) VALUES
(101, 'f1', 'sav-sep.pdf', 'bca_tahapan', 'bca_tahapan_v1', 'savings_statement', '2026-09-30',
    'IDR', 'id', 1000000000, 1100000000, 1, 'loaded', 'SAV-1111', 'asset', 'tommy', '2026-09-01'),
(102, 'f2', 'sav-oct.pdf', 'bca_tahapan', 'bca_tahapan_v1', 'savings_statement', '2026-10-31',
    'IDR', 'id', 1100000000, 900000000, 1, 'loaded', 'SAV-1111', 'asset', 'tommy', '2026-10-01'),
(103, 'f3', 'rdn-oct.pdf', 'bca_rdn', 'bca_v1', 'savings_statement', '2026-10-31',
    'IDR', 'id', 10000000, 9995000, 1, 'loaded', 'RDN-2222', 'asset', 'tommy', '2026-10-01'),
(104, 'f4', 'rdn-oct-old.pdf', 'bca_rdn', 'bca_v1', 'savings_statement', '2026-10-31',
    'IDR', 'id', 10000000, 80000000, 1, 'superseded', 'RDN-2222', 'asset', 'tommy', '2026-10-01'),
(105, 'f5', 'aj-1005.pdf', 'ajaib', 'ajaib_daily_v1', 'trades', '2026-10-05',
    'IDR', 'id', 0, -50005000, 1, 'loaded', 'AJ-3333', 'asset', 'tommy', '2026-10-05'),
(106, 'f6', 'cc-nov.pdf', 'bca_cc', 'bca_cc_v1', 'credit_card_statement', '2026-11-16',
    'IDR', 'id', 0, 0, 1, 'loaded', 'CC-4444', 'liability', 'tommy', '2026-10-17'),
(107, 'f7', 'cimb-sep.pdf', 'cimb_cc', 'cimb_v1', 'credit_card_statement', '2026-09-17',
    'IDR', 'id', 0, 5000000, 1, 'loaded', 'CIMB-9999', 'liability', 'tommy', '2026-08-18'),
(108, 'f8', 'mdr-oct.pdf', 'mandiri_consolidated', 'mandiri_v1', 'savings_statement', '2026-10-31',
    'IDR', 'id', 50000000, 51000100, 1, 'loaded', 'MDR-5555', 'asset', 'priskila', '2026-10-01'),
(109, 'f9', 'rdn8-oct.pdf', 'bca_rdn', 'bca_v1', 'savings_statement', '2026-10-31',
    'IDR', 'id', 0, 100000000, 1, 'loaded', 'RDN-8888', 'asset', 'priskila', '2026-10-01'),
(110, 'fa', 'tc-1016.pdf', 'stockbit', 'stockbit_tc_v1', 'trades', '2026-10-16',
    'IDR', 'id', 0, -123456789, 1, 'loaded', 'SB-7777', 'asset', 'priskila', '2026-10-16'),
(111, 'fb', 'tc-1017.pdf', 'stockbit', 'stockbit_tc_v1', 'trades', '2026-10-17',
    'IDR', 'id', 0, -400000000, 1, 'superseded', 'SB-7777', 'asset', 'priskila', '2026-10-17');

INSERT INTO trades (document_id, trade_date, settle_date, reference, symbol, side, board,
    quantity, price_minor, gross_minor, net_minor, fees_minor, currency, dedup_key) VALUES
(105, '2026-10-05', '2026-10-07', 'A1', 'AAAA', 'buy', 'RG', '100', 500000, 50000000, 50005000, 5000, 'IDR', 'f-k1'),
(110, '2026-10-16', '2026-10-20', 'B1', 'BBBB', 'buy', 'RG', '100', 1200000, 120000000, 120456789, 456789, 'IDR', 'f-k2'),
(110, '2026-10-16', '2026-10-20', 'B2', 'CCCC', 'buy', 'RG', '10', 300000, 3000000, 3000000, 0, 'IDR', 'f-k3'),
(111, '2026-10-17', '2026-10-21', 'B3', 'DDDD', 'buy', 'RG', '100', 4000000, 400000000, 400000000, 0, 'IDR', 'f-k4');

INSERT INTO transactions (document_id, txn_date, posting_date, description, raw_description,
    amount_minor, direction, dedup_key) VALUES
-- SAV-1111 September: salary in
(101, '2026-09-25', '2026-09-25', 'TRSF E-BANKING CR 2509', '25/09 TRSF E-BANKING CR 2509 PT CONTOH', 1000000000, 'credit', 't01'),
-- SAV-1111 October
(102, '2026-10-02', '2026-10-02', 'TRSF E-BANKING DB 0210', '02/10 TRSF E-BANKING DB 0210 SARI CONTOH', 100000000, 'debit', 't02'),
(102, '2026-10-05', '2026-10-05', 'TRSF E-BANKING DB 0510', '05/10 TRSF E-BANKING DB 0510 TOKO', 70000000, 'debit', 't03'),
(102, '2026-10-08', '2026-10-08', 'TRSF E-BANKING DB 0810', '08/10 TRSF E-BANKING DB 0810', 145000000, 'debit', 't04'),
(102, '2026-10-08', '2026-10-08', 'TRSF E-BANKING CR 0810', '08/10 TRSF E-BANKING CR 0810', 145000000, 'credit', 't05'),
(102, '2026-10-10', '2026-10-10', 'TRSF E-BANKING DB 1010', '10/10 TRSF E-BANKING DB 1010', 30000000, 'debit', 't06'),
(102, '2026-10-14', '2026-10-14', 'TRSF E-BANKING DB 1410', '14/10 TRSF E-BANKING DB 1410 Sari Contoh', 400000000, 'debit', 't07'),
(102, '2026-10-15', '2026-10-15', 'TRSF E-BANKING DB 1510', '15/10 TRSF E-BANKING DB 1510', 25000000, 'debit', 't08'),
(102, '2026-10-16', '2026-10-16', 'TRSF E-BANKING DB 1610', '16/10 TRSF E-BANKING DB 1610', 25000000, 'debit', 't09'),
(102, '2026-10-23', '2026-10-23', 'KARTU KREDIT/PL 1023', '23/10 KARTU KREDIT/PL 1023', 250000000, 'debit', 't10'),
(102, '2026-10-25', '2026-10-25', 'TRSF E-BANKING CR 2510', '25/10 TRSF E-BANKING CR 2510 PT CONTOH', 1000000000, 'credit', 't11'),
-- RDN-2222 October (tommy's RDN)
(103, '2026-10-07', '2026-10-07', 'TRSF E-BANKING DB 0710', '07/10 TRSF E-BANKING DB 0710', 50005000, 'debit', 't12'),
(103, '2026-10-15', '2026-10-15', 'TRSF E-BANKING CR 1510', '15/10 TRSF E-BANKING CR 1510', 25000000, 'credit', 't13'),
(103, '2026-10-16', '2026-10-16', 'TRSF E-BANKING CR 1610', '16/10 TRSF E-BANKING CR 1610', 25000000, 'credit', 't14'),
-- RDN-2222 superseded October: never read
(104, '2026-10-05', '2026-10-05', 'TRSF E-BANKING CR 0510', '05/10 TRSF E-BANKING CR 0510', 70000000, 'credit', 't15'),
-- AJ-3333 daily: its rows are parts of one settlement, never movements of their own
(105, '2026-10-05', '2026-10-07', 'Total Beli', 'Total Beli', 50000000, 'debit', 't16'),
(105, '2026-10-05', '2026-10-07', 'Komisi Broker Levy, PPN', 'Komisi Broker Levy, PPN', 5000, 'debit', 't17'),
-- CC-4444 (statement 2026-11-16): a purchase, then the payment from SAV-1111
(106, '2026-10-22', '2026-10-24', 'TOKO <b>CONTOH</b>', 'TOKO <b>CONTOH</b> JAKARTA', 250000000, 'debit', 't18'),
(106, '2026-10-24', '2026-10-24', 'PEMBAYARAN', 'PEMBAYARAN - TERIMA KASIH', 250000000, 'credit', 't19'),
-- CIMB-9999 September only
(107, '2026-09-05', '2026-09-06', 'RESTORAN', 'RESTORAN JAKARTA', 5000000, 'debit', 't20'),
-- MDR-5555 October (priskila's savings)
(108, '2026-10-09', '2026-10-09', 'TRANSFER IN', 'TRANSFER IN', 70000000, 'credit', 't21'),
(108, '2026-10-10', '2026-10-10', 'TRANSFER IN', 'TRANSFER IN', 30000100, 'credit', 't22'),
-- RDN-8888 October (priskila's RDN): the 10-02 transfer from SAV-1111 lands a day later
(109, '2026-10-03', '2026-10-03', 'TRSF E-BANKING CR 0310', '03/10 TRSF E-BANKING CR 0310 ANDI CONTOH', 100000000, 'credit', 't23'),
-- SB-7777 TC: fee rows as financer stores them
(110, '2026-10-16', '2026-10-20', 'Total Value buy', 'Total Value buy', 123000000, 'debit', 't24'),
(110, '2026-10-16', '2026-10-20', 'Commission buy', 'Commission buy', 456789, 'debit', 't25'),
(111, '2026-10-17', '2026-10-21', 'Total Value buy', 'Total Value buy', 400000000, 'debit', 't26');

INSERT INTO account_owners (issuer, account_ref, owner) VALUES
('bca_tahapan', 'SAV-1111', 'tommy'), ('bca_rdn', 'RDN-2222', 'tommy'),
('bca_rdn', 'RDN-8888', 'priskila'), ('stockbit', 'SB-7777', 'priskila'),
('bca_rdn', 'RDN-9999', 'priskila');
