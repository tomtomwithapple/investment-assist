-- jquantster store schema (tables the P23 adapter reads), copied read-only from the live
-- data/jquantster.db, which is jquantster src/jquantster/db.py SCHEMA at commit e42574b.
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE entitlements (
    dataset TEXT PRIMARY KEY, status TEXT NOT NULL, message TEXT, checked_at TEXT NOT NULL
);
CREATE TABLE daily_bars (
    code TEXT NOT NULL, date TEXT NOT NULL,
    o REAL, h REAL, l REAL, c REAL, vo REAL, va REAL, adj_factor REAL, adj_o REAL, adj_h REAL, adj_l REAL, adj_c REAL, adj_vo REAL,
    PRIMARY KEY (code, date)
);
CREATE TABLE fins_summary (
    code TEXT NOT NULL, disc_no TEXT NOT NULL, disc_date TEXT, doc_type TEXT,
    raw TEXT NOT NULL, PRIMARY KEY (code, disc_no)
);
CREATE TABLE investor_types (
    section TEXT NOT NULL, st_date TEXT NOT NULL, en_date TEXT NOT NULL, pub_date TEXT NOT NULL,
    PropSell REAL, PropBuy REAL, PropTot REAL, PropBal REAL, BrkSell REAL, BrkBuy REAL, BrkTot REAL, BrkBal REAL, TotSell REAL, TotBuy REAL, TotTot REAL, TotBal REAL, IndSell REAL, IndBuy REAL, IndTot REAL, IndBal REAL, FrgnSell REAL, FrgnBuy REAL, FrgnTot REAL, FrgnBal REAL, SecCoSell REAL, SecCoBuy REAL, SecCoTot REAL, SecCoBal REAL, InvTrSell REAL, InvTrBuy REAL, InvTrTot REAL, InvTrBal REAL, BusCoSell REAL, BusCoBuy REAL, BusCoTot REAL, BusCoBal REAL, OthCoSell REAL, OthCoBuy REAL, OthCoTot REAL, OthCoBal REAL, InsCoSell REAL, InsCoBuy REAL, InsCoTot REAL, InsCoBal REAL, BankSell REAL, BankBuy REAL, BankTot REAL, BankBal REAL, TrstBnkSell REAL, TrstBnkBuy REAL, TrstBnkTot REAL, TrstBnkBal REAL, OthFinSell REAL, OthFinBuy REAL, OthFinTot REAL, OthFinBal REAL,
    PRIMARY KEY (section, st_date, pub_date)
);
CREATE VIEW investor_types_latest AS
    SELECT t.* FROM investor_types t
    JOIN (SELECT section, st_date, MAX(pub_date) AS pub_date
          FROM investor_types GROUP BY section, st_date) m
      USING (section, st_date, pub_date);
CREATE TABLE jgb_yields (
    date TEXT NOT NULL, tenor TEXT NOT NULL, yield_pct REAL NOT NULL, PRIMARY KEY (date, tenor)
);
CREATE TABLE macro_series (
    key TEXT PRIMARY KEY, db TEXT NOT NULL, code TEXT NOT NULL, name TEXT, unit TEXT,
    frequency TEXT, last_update TEXT
);
CREATE TABLE macro_obs (
    key TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (key, date)
);
