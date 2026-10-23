"""Rebuild the openkrx Parquet fixtures: `uv run python tests/fixtures/openkrx/build.py`.

Layout and stored columns follow openkrx's P6 writer (src/openkrx/core/store/dataset.py):
`parquet/{dataset}/market={KR|TW}/date={yyyy-mm-dd}/part-{observed_at}-{rand}.parquet`, each row
carrying the frame's columns plus `market`, `vintage` (int64) and `observed_at` (UTC timestamptz).

- tw_index: T3's MI_INDEX parser SCHEMA (numbers Decimal(38,4)). 2026-10-20 TAIEX is restated
  (vintage 2 in a later part); 2026-10-21 values are openkrx's own MI_INDEX fixture, TW50's change
  blank. A half-written `.part-*.parquet.tmp` (the writer's temp name) must be ignored.
- krx_index_daily: KRX spec §4 columns (K3 is not built yet, so this is the planned shape).
- tw_adjusted_daily: V8's OUTPUT_SCHEMA, written WITHOUT vintage/observed_at (R1: "derived and
  fully recomputed, not vintaged"), so its rows have no `as_of`.
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent / "parquet"

D4 = "decimal(38,4)"
D18 = "decimal(38,18)"

PARTS = {
    "tw_index/market=TW/date=2026-10-20/part-20261020T100000000000Z-aaaa0001.parquet": f"""
        select date '2026-10-20' as trade_date, index_name, close::{D4} as close,
          change::{D4} as change, change_pct::{D4} as change_pct, null::varchar as note,
          'aa' as raw_sha256, false as as_of_inferred, 'TW' as market, 1::bigint as vintage,
          timestamptz '2026-10-20 10:00:00+00' as observed_at
        from (values ('發行量加權股價指數', 46200.0, 100.0, 0.22),
                     ('臺灣50指數', 42700.0, -50.0, -0.12)) t(index_name, close, change, change_pct)
    """,
    "tw_index/market=TW/date=2026-10-20/part-20261021T010000000000Z-aaaa0002.parquet": f"""
        select date '2026-10-20' as trade_date, '發行量加權股價指數' as index_name,
          46292.93::{D4} as close, 192.93::{D4} as change, 0.42::{D4} as change_pct,
          null::varchar as note, 'ab' as raw_sha256, false as as_of_inferred, 'TW' as market,
          2::bigint as vintage, timestamptz '2026-10-21 01:00:00+00' as observed_at
    """,
    "tw_index/market=TW/date=2026-10-21/part-20261021T213000000000Z-aaaa0003.parquet": f"""
        select date '2026-10-21' as trade_date, index_name, close::{D4} as close,
          change::{D4} as change, change_pct::{D4} as change_pct, null::varchar as note,
          'ac' as raw_sha256, false as as_of_inferred, 'TW' as market, 1::bigint as vintage,
          timestamptz '2026-10-21 21:30:00+00' as observed_at
        from (values ('發行量加權股價指數', 46887.77, 594.84, 1.28),
                     ('臺灣50指數', 43209.23, null, 1.08)) t(index_name, close, change, change_pct)
    """,
    "krx_index_daily/market=KR/date=2026-10-21/part-20261021T090000000000Z-bbbb0001.parquet": f"""
        select date '2026-10-21' as trade_date, family, index_name, close::{D4} as close,
          change::{D4} as change, change_pct::{D4} as change_pct, open::{D4} as open,
          high::{D4} as high, low::{D4} as low, volume::bigint as volume,
          value_krw::bigint as value_krw, 'ba' as raw_sha256, 'KR' as market,
          1::bigint as vintage, timestamptz '2026-10-21 09:00:00+00' as observed_at
        from (values
          ('KOSPI', '코스피', 3600.5, 10.5, 0.29, 3590.0, 3610.0, 3585.0, 400000000, 9000000000000),
          ('KOSPI', '코스피 200', 480.25, -1.25, -0.26, 481.0, 482.0, 479.0,
           90000000, 6000000000000)
        ) t(family, index_name, close, change, change_pct, open, high, low, volume, value_krw)
    """,
    "krx_index_daily/market=KR/date=2026-10-22/part-20261022T090000000000Z-bbbb0002.parquet": f"""
        select date '2026-10-22' as trade_date, family, index_name, close::{D4} as close,
          change::{D4} as change, change_pct::{D4} as change_pct, open::{D4} as open,
          high::{D4} as high, low::{D4} as low, volume::bigint as volume,
          value_krw::bigint as value_krw, 'bb' as raw_sha256, 'KR' as market,
          1::bigint as vintage, timestamptz '2026-10-22 09:00:00+00' as observed_at
        from (values
          ('KOSPI', '코스피', 3650.0, 49.5, 1.37, 3601.0, 3655.0, 3600.0, 410000000, 9500000000000),
          ('KOSPI', '코스피 200', 487.0, 6.75, 1.41, 480.5, 488.0, 480.0, 95000000, 6500000000000)
        ) t(family, index_name, close, change, change_pct, open, high, low, volume, value_krw)
    """,
    "tw_adjusted_daily/market=TW/date=2026-10-21/part-20261022T000000000000Z-cccc0001.parquet": f"""
        select trade_date, code, close_raw::decimal(18,4) as close_raw,
          ex_factor::{D18} as ex_factor,
          event_status, adj_factor::{D18} as adj_factor, close_adj::{D18} as close_adj,
          tr_factor::{D18} as tr_factor, close_tr::{D18} as close_tr,
          total_return::{D18} as total_return, tr_index::{D18} as tr_index, 'TW' as market
        from (values
          (date '2026-10-20', '0050', 200.0, null, null, 0.99, 198.0, 1.0, 200.0, null, 1.0),
          (date '2026-10-21', '0050', 199.0, 0.99, 'applied', 1.0, 199.0, 1.0, 199.0,
           0.005050505050505051, 1.005050505050505051)
        ) t(trade_date, code, close_raw, ex_factor, event_status, adj_factor, close_adj,
            tr_factor, close_tr, total_return, tr_index)
    """,
}

TMP = "tw_index/market=TW/date=2026-10-21/.part-20261022T000000000000Z-tmp00001.parquet.tmp"


def main() -> None:
    con = duckdb.connect()
    con.execute("set TimeZone = 'UTC'")
    for rel, sql in PARTS.items():
        out = ROOT / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"copy ({sql}) to '{out}' (format parquet)")
    (ROOT / TMP).write_text("half-written part")
    con.close()


if __name__ == "__main__":
    main()
