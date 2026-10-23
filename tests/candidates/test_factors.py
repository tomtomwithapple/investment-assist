"""idx-method stock reads (P19) and the factor columns derived from `cache/history/`.

idx-method dropped `enrich.py` on 2026-10-14 (README, *Changes the parent must follow*), so
`vol_1y`, `amihud`, `med_value_60d`, `days_traded_60`, `mom_12_1` and `near_52w_high` are
derived here, with the definitions of its former `panel.signals`. tests/fixtures/idxmethod/stocks/
stands in for the idx-method repo root: synthetic bars in cache/history/ (270 weekdays from
2025-09-01 to 2026-09-11) and trimmed copies of the real JSON files."""

from __future__ import annotations

import math
import shutil
from datetime import date

import pytest
from helpers import FIXTURES

from assist.candidates.factors import DERIVED, align, derive, enrich, load_factors
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_stocks import SOURCE, IdxMethodStocks

FIX = FIXTURES / "idxmethod" / "stocks"
LAST = date(2026, 9, 11)


@pytest.fixture
def stocks() -> IdxMethodStocks:
    return IdxMethodStocks(FIX)


@pytest.fixture
def history(stocks):
    return stocks.history()


# ---------------- reads ----------------


def test_name_is_idx_method(stocks):
    assert stocks.name == SOURCE == "idx-method"


def test_factors_keyed_by_symbol(stocks):
    f = stocks.factors()
    assert set(f) == {"AADI", "BBCA", "AAA"}
    assert f["BBCA"]["symbol"] == "BBCA" and f["BBCA"]["pe"] > 0


def test_consensus_composition_universe(stocks):
    assert stocks.consensus()["BBCA"]["rec"]
    assert stocks.composition()["AADI"]["report_date"] == "2026-09-30"
    u = stocks.universe()
    assert set(u) == {"index", "sectors", "watchlist"}
    assert u["index"][0]["name"] == "IHSG"


def test_history_all_and_some(stocks):
    h = stocks.history()
    assert set(h) == {"AAA", "BBB", "BBS", "EEE", "SHORT"}
    assert h["AAA"][-1]["date"] == "2026-09-11" and len(h["AAA"]) == 270
    # a symbol the cache doesn't hold is absent, not an error (the cache is partial)
    assert set(stocks.history(["AAA", "ZZZZ"])) == {"AAA"}


def test_dividends_and_fundamentals(stocks):
    dv = stocks.dividends()
    assert set(dv) == {"BBCA"} and dv["BBCA"][-1]["ex"] == "2026-08-31"
    fu = stocks.fundamentals(["BBCA"])
    assert fu["BBCA"]["periods"]["is"][-1] == "2026Q2"
    assert fu["BBCA"]["items"]["is"]["eps"][-1] == pytest.approx(120.46)


def test_missing_repo_is_unavailable(tmp_path):
    with pytest.raises(SourceUnavailable) as e:
        IdxMethodStocks(tmp_path / "nope").factors()
    assert e.value.reason == "missing"


def test_missing_file_and_dir_are_unavailable(tmp_path):
    shutil.copytree(FIX / "data", tmp_path / "data")
    (tmp_path / "data" / "consensus.json").unlink()
    s = IdxMethodStocks(tmp_path)
    assert s.factors()
    with pytest.raises(SourceUnavailable, match="consensus.json") as e:
        s.consensus()
    assert e.value.reason == "missing"
    with pytest.raises(SourceUnavailable) as e:
        s.history()
    assert e.value.reason == "missing"


def test_half_written_json_is_an_error(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "factors.json").write_text('{"AAA": {')
    with pytest.raises(SourceUnavailable) as e:
        IdxMethodStocks(tmp_path).factors()
    assert e.value.reason == "error"


def test_reads_never_write(stocks, tmp_path):
    before = {p: p.stat().st_mtime_ns for p in FIX.rglob("*") if p.is_file()}
    stocks.factors(), stocks.history(), stocks.fundamentals(), stocks.dividends()
    assert before == {p: p.stat().st_mtime_ns for p in FIX.rglob("*") if p.is_file()}


# ---------------- derived factors ----------------


def test_align_uses_the_union_calendar_and_min_bars(history):
    dates, data = align(history, min_bars=200)
    assert len(dates) == 270 and dates[-1] == LAST
    assert "SHORT" not in data  # 100 bars < min_bars
    # EEE stopped 40 bars early: close forward-filled, the tail marked untraded
    e = data["EEE"]
    assert e["close"][-1] == 500.0 and e["traded"][-41:] == [True] + [False] * 40


def test_steady_riser(history):
    a = derive(history)["AAA"]
    assert set(DERIVED) <= set(a)
    assert a["date"] == LAST and a["price"] == pytest.approx(1000 * 1.001**269)
    assert a["vol_1y"] == pytest.approx(0, abs=1e-9)  # every return identical
    assert a["amihud"] == pytest.approx(0.001 / 2)  # |r| per IDR bn: 0.1% on 2bn
    assert a["med_value_60d"] == 2e9
    assert a["days_traded_60"] == 60
    assert a["mom_12_1"] == pytest.approx(1.001**231 - 1)  # t-252 .. t-21
    assert a["near_52w_high"] == pytest.approx(1.0)


def test_zigzag_values(history):
    b = derive(history)["BBB"]
    # 252 daily returns alternating +2% / -1%, the last 10 flat (untraded, stale close)
    up, dn = 0.02, -0.01
    assert b["days_traded_60"] == 50
    assert b["med_value_60d"] == 2e9  # 10 zero-value days sort first, then 17 at 1bn
    r = [up if k % 2 else dn for k in range(18, 260)] + [0.0] * 10
    mu = sum(r) / len(r)
    vol = math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252)
    assert b["vol_1y"] == pytest.approx(vol)
    assert 0 < b["near_52w_high"] <= 1


def test_split_day_is_neutralised(history):
    """A 2:1 split shows as a -50% day in the unadjusted close; it counts as a zero return.
    BBS is BBB's zigzag with every close from bar 200 halved; bar 200 was a -1% day."""
    split = derive(history)["BBS"]
    ref = derive(dict(history, BBS=_unsplit(history["BBS"])))["BBS"]
    assert split["mom_12_1"] == pytest.approx((1 + ref["mom_12_1"]) / 0.99 - 1)
    assert split["vol_1y"] == pytest.approx(ref["vol_1y"], rel=0.01)
    assert split["amihud"] == pytest.approx(ref["amihud"])  # bar 200 is outside the 60 days


def _unsplit(bars):
    return [dict(x, close=x["close"] * 2) if k >= 200 else x for k, x in enumerate(bars)]


def test_dormant_and_short_names_get_nothing(history):
    d = derive(history)
    assert "EEE" not in d  # 20 of the last 60 days traded < 30
    assert "SHORT" not in d


def test_as_of_uses_only_bars_on_or_before_it(history):
    d = derive(history, as_of=date(2026, 8, 28))  # 10 bars before the end
    b = d["BBB"]
    assert b["date"] == date(2026, 8, 28)
    assert b["days_traded_60"] == 60  # the untraded tail is in the future
    # an as_of before 252 bars of history derives nothing
    assert derive(history, as_of=date(2026, 8, 1)) == {}


def test_enrich_overwrites_and_blanks_stale_columns(stocks, history):
    fac = stocks.factors()
    assert fac["BBCA"]["mom_12_1"] is not None  # stale value from idx-method's last enrich
    out = enrich(fac, derive(history))
    assert out["AAA"]["mom_12_1"] == pytest.approx(1.001**231 - 1)
    assert out["AAA"]["pe"] == fac["AADI"]["pe"]  # screener columns pass through
    assert all(out["BBCA"][k] is None for k in DERIVED)  # no history → no stale carry-over
    assert fac["BBCA"]["mom_12_1"] is not None  # input left untouched


def test_load_factors(stocks):
    table, stale = load_factors(stocks)
    assert stale == []
    assert set(table) == {"AADI", "BBCA", "AAA"}
    assert table["AAA"]["days_traded_60"] == 60
    assert table["AAA"]["bar_date"] == LAST


def test_load_factors_with_missing_repo_is_stale(tmp_path):
    table, stale = load_factors(IdxMethodStocks(tmp_path / "nope"))
    assert table == {} and stale == ["idx-method (missing)"]
