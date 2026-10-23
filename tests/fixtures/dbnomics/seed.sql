-- A few real-shaped rows per group (values from the live store on 2026-10-23, trimmed).
insert into series values
  ('idn.cli', 'Indonesia: Composite leading indicator (amplitude adjusted)', 'IDN', 'M',
   'index, long-term average = 100', 'oecd',
   '[{"kind": "oecd", "key": "OECD.SDD.STES,DSD_STES@DF_CLI/IDN.M.LI.IX._Z.AA.IX._Z.H"}]', 75),
  ('idn.rate.long', 'Indonesia: Long-term interest rate (10-year government bond)', 'IDN', 'M',
   '% p.a.', 'oecd',
   '[{"kind": "oecd", "key": "OECD.SDD.STES,DSD_STES@DF_FINMARK/IDN.M.IRLT.PA._Z._Z._Z._Z.N"}]', 75),
  ('cn.pmi.mfg', 'China: Manufacturing PMI', 'CHN', 'M', 'index, 50 = no change', 'china',
   '[{"kind": "nbs", "key": "93ffbb1aa85740d3aa2618371508b606/a09aa989bdcf4cffa2021795722eb916"}, {"kind": "dbnomics", "key": "NBS/M_A0B01/A0B0101"}]', 75),
  ('ea.rate.deposit', 'Euro area: ECB deposit facility rate', 'EA', 'D', '% p.a.', 'eurozone',
   '[{"kind": "dbnomics", "key": "ECB/FM/D.U2.EUR.4F.KR.DFR.LEV"}]', 10),
  ('us.erp.implied', 'United States: Damodaran implied ERP (trailing 12m)', 'USA', 'M',
   'fraction', 'valuation', '[{"kind": "derived", "key": "damodaran_erp"}]', 75),
  ('idn.crp', 'Indonesia: Country risk premium (rating-based)', 'IDN', 'A', 'fraction',
   'valuation', '[{"kind": "derived", "key": "damodaran_crp"}]', 450);

insert into observations values
  ('idn.cli', '2026-07-01', '2026-07', 98.9529, 'oecd', 'OECD.SDD.STES,DSD_STES@DF_CLI/IDN.M.LI.IX._Z.AA.IX._Z.H', '2026-10-21 06:40:01'),
  ('idn.cli', '2026-08-01', '2026-08', 98.75598, 'oecd', 'OECD.SDD.STES,DSD_STES@DF_CLI/IDN.M.LI.IX._Z.AA.IX._Z.H', '2026-10-21 06:40:01'),
  ('idn.cli', '2026-09-01', '2026-09', 98.62859, 'oecd', 'OECD.SDD.STES,DSD_STES@DF_CLI/IDN.M.LI.IX._Z.AA.IX._Z.H', '2026-10-21 06:40:01'),
  ('idn.rate.long', '2024-11-01', '2024-11', 6.85, 'oecd', 'OECD.SDD.STES,DSD_STES@DF_FINMARK/IDN.M.IRLT.PA._Z._Z._Z._Z.N', '2026-10-21 06:40:02'),
  ('idn.rate.long', '2024-12-01', '2024-12', null, 'oecd', 'OECD.SDD.STES,DSD_STES@DF_FINMARK/IDN.M.IRLT.PA._Z._Z._Z._Z.N', '2026-10-21 06:40:02'),
  ('cn.pmi.mfg', '2026-08-01', '2026-08', 49.4, 'nbs', '93ffbb1aa85740d3aa2618371508b606/a09aa989bdcf4cffa2021795722eb916', '2026-10-21 06:40:20'),
  ('cn.pmi.mfg', '2026-09-01', '2026-09', 49.8, 'nbs', '93ffbb1aa85740d3aa2618371508b606/a09aa989bdcf4cffa2021795722eb916', '2026-10-21 06:40:20'),
  ('ea.rate.deposit', '2026-10-19', '2026-10-19', 2.0, 'dbnomics', 'ECB/FM/D.U2.EUR.4F.KR.DFR.LEV', '2026-10-21 06:40:30'),
  ('ea.rate.deposit', '2026-10-20', '2026-10-20', 2.0, 'dbnomics', 'ECB/FM/D.U2.EUR.4F.KR.DFR.LEV', '2026-10-21 06:40:30'),
  ('us.erp.implied', '2026-09-01', '2026-09', 0.0383, 'derived', 'damodaran_erp/M/t12m', '2026-10-21 06:40:40'),
  ('us.erp.implied', '2026-10-01', '2026-10', 0.037, 'derived', 'damodaran_erp/M/t12m', '2026-10-21 06:40:40'),
  ('idn.crp', '2025-01-01', '2025-01', 0.025410424967656622, 'derived', 'damodaran_crp/IDN/2025-01-01/crp', '2026-10-21 06:40:40'),
  ('idn.crp', '2026-01-01', '2026-01', 0.024649631345505598, 'derived', 'damodaran_crp/IDN/2026-01-01/crp', '2026-10-21 06:40:40');

insert into series_status values
  ('idn.cli', 'oecd', '2026-09', false, '2026-10-21 06:40:01'),
  ('idn.rate.long', 'oecd', '2024-12', true, '2026-10-21 06:40:02'),
  ('cn.pmi.mfg', 'nbs', '2026-09', false, '2026-10-21 06:40:20'),
  ('ea.rate.deposit', 'dbnomics', '2026-10-20', false, '2026-10-21 06:40:30'),
  ('us.erp.implied', 'derived', '2026-10', false, '2026-10-21 06:40:40'),
  ('idn.crp', 'derived', '2026-01', false, '2026-10-21 06:40:40');

insert into damodaran_erp values
  ('2026-09-01', 'M', 't12m', 0.0383, 7600.0, 0.0510),
  ('2026-10-01', 'M', 't12m', 0.037, 7652.0, 0.0529),
  ('2026-10-01', 'M', 't12m_sustainable', 0.042, 7652.0, 0.0529),
  ('2025-12-31', 'A', 'fcfe', 0.0433, 6845.5, 0.0457);

insert into damodaran_crp values
  ('2025-01-01', 'Indonesia', 'IDN', 'Asia', 'Baa2', 'BBB', 0.01885748822216712, 0.009,
   0.025410424967656622, 0.06871042496765661, 0.01212748071294449, 0.05542748071294449, 0.0433, 'ctryprem24.xlsx'),
  ('2026-01-01', 'Indonesia', 'IDN', 'Asia', 'Baa2', 'BBB', 0.016180901401917473, 0.0105,
   0.024649631345505598, 0.06694963134550559, 0.01599547038196141, 0.05829547038196141, 0.0423, 'ctryprem.xlsx'),
  ('2026-01-01', 'Japan', 'JPN', 'Asia', 'A1', 'A+', 0.0068, 0.003, 0.0103, 0.0526, null, null, 0.0423, 'ctryprem.xlsx'),
  ('2026-01-01', 'Abu Dhabi', null, 'Middle East', 'Aa2', 'AA', 0.0049, null, 0.0074, 0.0497, null, null, 0.0423, 'ctryprem.xlsx');

insert into shiller values
  ('2026-09-01', 7669.414285714285, null, null, 335.511, 4.99, 40.58087409538742, 43.21199789029356, 0.008197963917198934, false),
  ('2026-10-01', 7722.72, null, null, 335.77650000000006, 5.24, 40.710608577487044, 43.32811219938697, 0.005572419089988807, true);
