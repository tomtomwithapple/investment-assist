"""PLAN S21 (P39): US single stocks. The P36 dividend and P37 GARP engines on sec-edgar data:
XBRL facts point in time by filed date, Alpaca bars with their split and total-return factors,
held to the P34 USA hurdle in unhedged IDR and to the IDN hurdle in IDR too.

The adapter's fixture (tests/fixtures/usfin_stocks) is a tiny usfin.duckdb built from
sec-edgar's DDL (read 2026-10-27) with a stand-in for the security / adjusted-bar macros, and a
fake `usfin serve` (httpx MockTransport, no socket) answering `/prices/universe` and `/prices`
from that same file, so both paths are held equal. Engine inputs are built in memory."""

from __future__ import annotations

import csv
import io
import random
from datetime import date, timedelta

import duckdb
import httpx
import pytest
from helpers import FIXTURES, hold_duckdb_lock

from assist.candidates import dividend_value as dv
from assist.candidates import garp
from assist.candidates import us_stocks as us
from assist.candidates.hurdle import Hurdle
from assist.eval.placebo import evaluate
from assist.sources.base import SourceUnavailable
from assist.sources.idxmethod_series import Bar, Fundamentals, quarter_ends
from assist.sources.usfin import Usfin
from assist.sources.usfin_stocks import Fact, Listing, UsBar, UsStocks

D = date.fromisoformat
FIX = FIXTURES / "usfin_stocks"
URL = "http://127.0.0.1:8660"
TABLES = ("edgar_company", "xbrl_fact", "alpaca_universe", "alpaca_bar", "fixture_adjusted")


# ---------------- adapter ----------------


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "usfin.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute((FIX / "schema.sql").read_text())
        for t in TABLES:
            con.execute(f"insert into {t} select * from read_csv(?, header = true)",
                        [str(FIX / f"{t}.csv")])
    finally:
        con.close()
    return path


def _csv(cols, rows) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return out.getvalue()


def fake_serve(path) -> httpx.Client:
    """`usfin serve`'s two price routes, answered from the fixture store as web/prices.py does
    (columns as its UNIVERSE_COLUMNS and BAR_COLUMNS). Read up front: the real server holds the
    store's lock while it answers."""
    db = UsStocks(Usfin(url=None, path=path))
    universe = _csv(
        ("symbol", "status", "exchange", "name", "sources", "delisted", "first_bar", "last_bar",
         "bars", "cik", "edgar_ticker", "edgar_title", "sic"),
        [(r.symbol, "active", "NASDAQ", "", "asset_active", False, "", "", 1, r.cik, r.symbol,
          r.title, r.sic) for r in db.universe_duckdb()])
    bars = {}
    for sym in ("AAPL", "META", "BRK.B", "NOPE"):
        rows = db.bars_duckdb(sym)
        if rows:
            bars[sym] = _csv(
                ("date", "symbol", "open", "high", "low", "close", "volume", "trade_count",
                 "vwap", "adj_close", "split_factor", "tr_factor", "security_key"),
                [(b.date, b.symbol, "", "", "", b.close,
                  None if b.volume is None else int(b.volume), "", "", b.adj_close,
                  b.split_factor, b.tr_factor, "k") for b in rows])

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        assert q.get("format") == "csv"
        if request.url.path == "/prices/universe":
            assert q.get("status") == "active" and q.get("matched") == "1"
            return httpx.Response(200, text=universe)
        if request.url.path == "/prices" and q.get("symbol") in bars:
            return httpx.Response(200, text=bars[q["symbol"]])
        return httpx.Response(404, json={"detail": "no bars"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_universe_joins_active_symbols_to_edgar_by_ticker_norm(store):
    src = UsStocks(Usfin(url=None, path=store))
    got = src.universe()
    assert got == [
        Listing("AAPL", 320193, "Apple Inc."),
        Listing("BRK.B", 1067983, "BERKSHIRE HATHAWAY INC"),  # BRK-B under ticker_norm
        Listing("META", 1326801, "Meta Platforms, Inc."),
    ]  # SPY has no EDGAR company, FB is a rename, OLDCO inactive


def _add_profiles(path, rows):
    """sec-edgar S45's `edgar_company_profile` (its migration 029 columns), with `rows` of
    (cik, sic)."""
    con = duckdb.connect(str(path))
    try:
        con.execute("""create table edgar_company_profile (cik bigint primary key, name varchar,
            sic integer, sic_description varchar, owner_org varchar, entity_type varchar,
            category varchar, fiscal_year_end varchar, state_of_incorporation varchar,
            exchanges varchar[], seen_at timestamp, raw_id bigint)""")
        con.executemany("insert into edgar_company_profile (cik, sic) values (?, ?)", rows)
    finally:
        con.close()


def test_universe_carries_each_company_sic_when_the_store_has_profiles(store):
    _add_profiles(store, [(320193, 3571), (1326801, None)])
    db = UsStocks(Usfin(url=None, path=store))
    got = {x.symbol: x.sic for x in db.universe()}
    assert got == {"AAPL": 3571, "BRK.B": None, "META": None}  # no row / NULL: no SIC
    http = UsStocks(Usfin(url=URL, path=None, client=fake_serve(store)))
    assert http.universe() == db.universe()


def test_universe_has_no_sic_on_a_store_before_profiles(store):
    assert all(x.sic is None for x in UsStocks(Usfin(url=None, path=store)).universe())


def test_sic_sector_is_the_major_group_and_industry_the_code():
    assert (us.sic_sector(3674), us.sic_industry(3674)) == ("SIC 36", "SIC 3674")
    assert (us.sic_sector(100), us.sic_industry(100)) == ("SIC 01", "SIC 0100")
    assert us.sic_sector(None) is None and us.sic_industry(None) is None


def test_bars_per_symbol_follow_the_security_across_renames_and_take_the_latest_version(store):
    src = UsStocks(Usfin(url=None, path=store))
    meta = src.bars("META")
    assert [(b.date, b.symbol) for b in meta] == [(D("2022-06-08"), "FB"),
                                                  (D("2022-06-09"), "META")]
    aapl = src.bars("AAPL")
    assert len(aapl) == 4
    nov6 = next(b for b in aapl if b.date == D("2020-11-06"))
    assert nov6.volume == 114457900  # newest first_seen_at wins
    assert aapl[0].split_factor == 0.25 and aapl[0].close == 499.23
    assert src.bars("NOPE") == []


def test_http_and_duckdb_give_the_same_rows(store):
    http = UsStocks(Usfin(url=URL, path=None, client=fake_serve(store)))
    db = UsStocks(Usfin(url=None, path=store))
    assert http.universe() == db.universe()
    assert http.usfin.via == "http"
    assert http.bars("AAPL") == db.bars("AAPL")
    assert http.bars("META") == db.bars("META")
    assert http.bars("NOPE") == []


def test_facts_are_point_in_time_by_filed_date(store):
    src = UsStocks(Usfin(url=None, path=store))
    before = src.facts(320193, D("2025-10-30"))
    assert before == []
    facts = src.facts(320193, D("2026-02-01"))
    assert {f.tag for f in facts} == {"NetIncomeLoss", "StockholdersEquity",
                                      "EntityCommonStockSharesOutstanding"}  # not Revenues
    assert all(f.filed <= D("2026-02-01") for f in facts)
    assert len(src.facts(320193, D("2025-12-31"))) == 3


def test_facts_fall_back_to_the_file_since_serve_has_no_route(store):
    src = UsStocks(Usfin(url=URL, path=store, client=fake_serve(store)))
    assert len(src.facts(320193, D("2026-02-01"))) == 4
    assert src.usfin.via == "duckdb"


def test_facts_locked_while_serve_holds_the_store(store):
    src = UsStocks(Usfin(url=URL, path=store, client=fake_serve(store)))
    with hold_duckdb_lock(store), pytest.raises(SourceUnavailable) as e:
        src.facts(320193)
    assert e.value.reason == "locked"


def test_missing_store_and_server_down_is_missing(tmp_path):
    def down(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(down))
    src = UsStocks(Usfin(url=URL, path=tmp_path / "nope.duckdb", client=client))
    with pytest.raises(SourceUnavailable) as e:
        src.universe()
    assert e.value.reason == "missing"


# ---------------- building engine inputs ----------------


def ubar(d, close, *, sf=1.0, tr=None, volume=1e6, sym="X") -> UsBar:
    tr = sf if tr is None else tr
    return UsBar(D(d) if isinstance(d, str) else d, sym, close, volume, close * tr, sf, tr)


def fact(tag, start, end, value, filed, form="10-Q", unit="USD", accn=None) -> Fact:
    return Fact(tag, unit, accn or f"a-{filed}-{form}", D(start), D(end), value, form, D(filed))


def test_dividends_from_bars_read_the_total_return_steps():
    bars = [
        ubar("2024-01-02", 200.0, sf=0.5, tr=0.5 * 0.99),
        ubar("2024-01-03", 198.0, sf=0.5, tr=0.5),  # ex: 1% of 200 = 2.00 raw
        ubar("2024-06-03", 100.0, sf=1.0, tr=1.0),  # 2-for-1 split: no dividend
    ]
    got = us.dividends_from_bars(bars)
    assert len(got) == 1
    assert got[0]["ex"] == "2024-01-03"
    assert got[0]["value"] == pytest.approx(1.0)  # 2.00 raw on the split-adjusted basis
    assert got[0]["raw"] == pytest.approx(2.0)


def test_engine_bars_price_split_adjusted_and_mktcap_from_shares_known_then():
    bars = [ubar("2020-07-01", 360.0, sf=0.25), ubar("2020-08-28", 499.0, sf=0.25),
            ubar("2020-09-01", 129.0, sf=1.0)]
    shares = [fact("EntityCommonStockSharesOutstanding", "2020-07-17", "2020-07-17", 1000.0,
                   "2020-07-31", unit="shares")]
    got = us.engine_bars(bars, shares)
    assert got[0] == Bar(D("2020-07-01"), 90.0, None)  # no share count filed yet
    assert got[1].price == pytest.approx(124.75)
    assert got[1].mktcap == pytest.approx(499_000.0)
    assert got[2].mktcap == pytest.approx(129.0 * 4000)  # 4-for-1 after the count was filed


def _apple_like():
    return [
        fact("NetIncomeLoss", "2023-10-01", "2024-09-28", 100.0, "2024-11-01", "10-K"),
        fact("NetCashProvidedByUsedInOperatingActivities", "2023-10-01", "2024-09-28", 120.0,
             "2024-11-01", "10-K"),
        fact("StockholdersEquity", "2024-09-28", "2024-09-28", 500.0, "2024-11-01", "10-K"),
        fact("NetIncomeLoss", "2024-09-29", "2024-12-28", 30.0, "2025-01-31"),
        fact("NetIncomeLoss", "2023-10-01", "2023-12-30", 25.0, "2025-01-31"),
        fact("NetCashProvidedByUsedInOperatingActivities", "2024-09-29", "2024-12-28", 40.0,
             "2025-01-31"),
        fact("NetCashProvidedByUsedInOperatingActivities", "2023-10-01", "2023-12-30", 35.0,
             "2025-01-31"),
        fact("StockholdersEquity", "2024-12-28", "2024-12-28", 520.0, "2025-01-31"),
        # 10-K/A restating FY2024 net income, filed later
        fact("NetIncomeLoss", "2023-10-01", "2024-09-28", 90.0, "2025-03-01", "10-K/A"),
    ]


def test_quarters_ttm_from_ytd_plus_prior_year_and_available_on_the_filed_date():
    q = us.quarters_from_facts(_apple_like())
    first = q[0]
    assert first.period == D("2024-09-30")  # 52/53-week year end snapped to the month end
    assert first.available == D("2024-11-01")
    assert (first.ni_ttm, first.cfo_ttm, first.equity) == (100.0, 120.0, 500.0)
    dec = next(f for f in q if f.period == D("2024-12-31"))
    assert dec.available == D("2025-01-31")
    assert dec.ni_ttm == pytest.approx(30 + 100 - 25)
    assert dec.cfo_ttm == pytest.approx(40 + 120 - 35)
    assert dec.equity == 520.0
    assert isinstance(dec, Fundamentals)


def test_quarters_are_point_in_time_a_restatement_is_a_later_row():
    q = us.quarters_from_facts(_apple_like())
    sep = [f for f in q if f.period == D("2024-09-30")]
    assert [(f.available, f.ni_ttm) for f in sep] == [(D("2024-11-01"), 100.0),
                                                      (D("2025-03-01"), 90.0)]
    dec = next(f for f in q if f.period == D("2024-12-31"))
    assert dec.ni_ttm == pytest.approx(105.0)  # built from what was known on 2025-01-31
    assert q == sorted(q, key=lambda f: (f.period, f.available))


def test_bank_marker_is_a_deposits_fact():
    assert us.is_bank([fact("Deposits", "2024-12-31", "2024-12-31", 1e9, "2025-02-01")])
    assert not us.is_bank(_apple_like())


def test_median_value_is_over_the_last_sessions():
    bars = [ubar(D("2024-01-01") + timedelta(days=i), 10.0, volume=1e6 * (i + 1))
            for i in range(100)]
    vals = us.values(bars)
    d = D("2024-01-01") + timedelta(days=99)
    assert us.median_value(vals, d, 60) == pytest.approx(10 * 1e6 * 70.5)
    assert us.median_value(vals, D("2023-01-01"), 60) is None


# ---------------- hurdles ----------------


USA = Hurdle("USA", D("2026-10-22"), "USD", "neutral", 8.92, 9.73, fx_move=-0.0074,
             fx_basis="adverse")
IDN = Hurdle("IDN", D("2026-10-22"), "IDR", "neutral", 13.56, 13.56)


def test_usd_bar_is_the_higher_of_the_us_and_the_idn_alternative_in_usd():
    bar, binding = us.usd_bar(USA, IDN)
    assert bar == pytest.approx(100 * (1.1356 / (1 - 0.0074) - 1))
    assert binding == "IDN"
    assert us.usd_bar(USA, None) == (9.73, "USA")
    assert us.usd_bar(None, IDN) == (None, None)  # no FX move without the USA hurdle


def test_idr_margins_must_beat_both_hurdles():
    m = us.idr_margins(12.0, USA, IDN)
    idr = 100 * ((1.12) * (1 - 0.0074) - 1)
    assert m["expected_idr_pt"] == pytest.approx(idr)
    assert m["margin_usa_pt"] == pytest.approx(idr - 8.92)
    assert m["margin_idn_pt"] == pytest.approx(idr - 13.56)
    assert m["margin_pt"] == pytest.approx(idr - 13.56)  # the binding one
    assert us.idr_margins(12.0, USA, None)["margin_pt"] is None
    assert us.idr_margins(None, USA, IDN)["margin_pt"] is None


# ---------------- engines on US data ----------------


def _weekly(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=7)


START, END = date(2016, 1, 1), date(2023, 12, 29)


def synth(n=40, seed=7, edge=True, start=START, end=END) -> us.UsData:
    """`n` names, weekly bars, quarterly dividends at a fixed yield per name and earnings that
    track the price (payout 40%). With `edge`, yield rises with i and higher-yield names drift
    up; without, every name yields 3% and drifts nowhere."""
    rng = random.Random(seed)
    data = us.UsData()
    for i in range(n):
        sym = f"S{i:02d}"
        price = 50.0 + i
        yld = 0.01 + 0.002 * i if edge else 0.03  # no edge: ranked on price noise alone
        bars, divs = [], []
        for d in _weekly(start, end):
            drift = (0.0004 * (i - n / 2) if edge else 0.0) + rng.gauss(0, 0.01)
            price *= 1 + drift
            bars.append(Bar(d, price, price * 1e8))
            if d.month in (3, 6, 9, 12) and d.day <= 7:
                divs.append({"ex": d.isoformat(), "value": price * yld / 4})
        quarters = []
        for p in quarter_ends(start, end):
            b = dv._bar_at(bars, p)
            ni = 2.5 * yld * max(b.mktcap, 2.5e9)
            quarters.append(Fundamentals(p, p + timedelta(days=40), ni * 1.2, ni * 5, None,
                                         ni, None, None, None, None, None))
        data.bars[sym] = bars
        data.values[sym] = [(b.date, 5e7) for b in bars]
        data.quarters[sym] = quarters
        data.dividends[sym] = divs
        data.listings[sym] = Listing(sym, 1000 + i, f"Name {i}")
    return data


# The replay-harness tests rank on yield alone: a price-tracking dividend falls with the price,
# which the 2-year cut gate would read as a cut.
NO_CUT = {**us.CONFIG, "dividend": {**us.CONFIG["dividend"], "cut_tol": 1.0}}


def test_replay_panel_applies_the_us_size_and_liquidity_gates_and_no_idx_price_floor():
    data = synth(n=6)
    data.bars["S00"] = [Bar(b.date, b.price, 1e9) for b in data.bars["S00"]]  # < US$2bn
    data.values["S01"] = [(d, 1e6) for d, _ in data.values["S01"]]  # < US$20m a day
    for b in data.bars["S02"]:
        assert b.price < 100  # the IDX Rp100 floor would drop every US name under $100
    data.bars = {s: [Bar(b.date, b.price, b.price * 1e8) for b in bs]
                 if s != "S00" else bs for s, bs in data.bars.items()}
    for s in ("S02", "S03", "S04", "S05"):
        data.bars[s] = [Bar(b.date, b.price, 5e9) for b in data.bars[s]]
    panel = us.replay_panel("dividend_value", data)
    q, recs = next((q, r) for q, r in panel if r)
    syms = {r["symbol"] for r in recs}
    assert "S00" not in syms and "S01" not in syms
    assert syms <= {"S02", "S03", "S04", "S05"}
    r = recs[0]
    assert set(r) >= {"symbol", "expected_pt", "fwd"}


def test_replay_ranks_garp_on_realised_gap_at_the_usd_bar():
    data = synth(n=6)
    for s in data.bars:
        data.bars[s] = [Bar(b.date, b.price, 5e9) for b in data.bars[s]]
    panel = us.replay_panel("garp", data, hurdle_pt=14.4)
    recs = [r for _, rs in panel for r in rs]
    assert recs and all("gap_pt" in r for r in recs)


def test_replay_verdict_finds_a_real_edge_and_not_noise():
    good = us.replay_panel("dividend_value", _big(synth(n=40, edge=True)), cfg=NO_CUT)
    v = dv.evaluate_replay(good, min_pool=30, n_shuffles=200, n_controls=5)
    assert v.passed and v.rule.diff > 0
    noise = us.replay_panel("dividend_value", _big(synth(n=40, edge=False, seed=3)), cfg=NO_CUT)
    assert not dv.evaluate_replay(noise, min_pool=30, n_shuffles=200, n_controls=5).passed


def _big(data: us.UsData) -> us.UsData:
    """Every name above the US$2bn floor (mktcap tracks price from a 1e8-share base)."""
    for s, bs in data.bars.items():
        data.bars[s] = [Bar(b.date, b.price, max(b.price * 1e8, 2.5e9)) for b in bs]
    return data


def _passed():
    return evaluate(lambda f, _r: list(f), [True, False] * 20,
                    [0.05 + 0.001 * i if i % 2 == 0 else -0.05 for i in range(40)],
                    n_shuffles=50, n_controls=2)


def test_run_names_no_candidate_when_the_replay_fails():
    data = _big(synth(n=40, edge=False, seed=3))
    out = us.run("dividend_value", data, as_of=D("2023-12-29"), usa=USA, idn=IDN, cfg=NO_CUT,
                 n_shuffles=50, n_controls=2)
    assert out["screen"] == "us_dividend_value"
    assert not out["passed"] and out["candidates"] == []
    assert out["pool"] > 0
    assert out["universe"] == 40


def test_run_candidates_need_a_passed_verdict_and_must_beat_the_idn_hurdle(monkeypatch):
    data = _big(synth(n=40, edge=True))
    monkeypatch.setattr(dv, "evaluate_replay", lambda panel, **kw: _passed())
    loose_idn = Hurdle("IDN", D("2026-10-22"), "IDR", "neutral", 3.0, 3.0)
    out = us.run("dividend_value", data, as_of=D("2023-12-29"), usa=USA, idn=loose_idn,
                 panel=[])
    assert out["passed"]
    assert out["candidates"]
    assert all(c["margin_usa_pt"] > 0 and c["margin_idn_pt"] > 0 for c in out["candidates"])
    margins = [r["margin_pt"] for r in out["ranking"]]
    assert margins == sorted(margins, reverse=True)
    assert len(out["top"]) <= 10
    tight = us.run("dividend_value", data, as_of=D("2023-12-29"), usa=USA, idn=IDN, panel=[])
    assert all(c["margin_idn_pt"] > 0 for c in tight["candidates"])
    assert len(tight["candidates"]) < len(out["candidates"])


def test_run_garp_discounts_at_the_usd_bar_and_reports_idr_margins(monkeypatch):
    data = _big(synth(n=40, edge=True))
    monkeypatch.setattr(garp, "evaluate_replay", lambda panel, **kw: _passed())
    out = us.run("garp", data, as_of=D("2023-12-29"), usa=USA, idn=IDN, panel=[])
    assert out["screen"] == "us_garp"
    assert out["usd_bar_pt"] == pytest.approx(us.usd_bar(USA, IDN)[0])
    assert out["binding"] == "IDN"
    gaps = [r["gap_pt"] for r in out["ranking"]]
    assert gaps == sorted(gaps, reverse=True)
    for r in out["ranking"]:
        assert set(r) >= {"symbol", "cik", "title", "expected_usd_pt", "expected_idr_pt",
                          "margin_usa_pt", "margin_idn_pt", "margin_pt", "legs"}
    for c in out["candidates"]:
        assert c["gap_pt"] >= us.CONFIG["garp"]["min_gap_pt"]


def _with_sic(data: us.UsData, sic_of) -> us.UsData:
    for sym, lst in list(data.listings.items()):
        data.listings[sym] = lst._replace(sic=sic_of(int(sym[1:])))
    return data


def test_run_caps_candidates_per_sic_major_group(monkeypatch):
    monkeypatch.setattr(dv, "evaluate_replay", lambda panel, **kw: _passed())
    loose_idn = Hurdle("IDN", D("2026-10-22"), "IDR", "neutral", 3.0, 3.0)
    free = us.run("dividend_value", _big(synth(n=40, edge=True)), as_of=D("2023-12-29"),
                  usa=USA, idn=loose_idn, panel=[])
    assert len(free["candidates"]) > us.MAX_PER_SECTOR  # every name its own sector
    data = _with_sic(_big(synth(n=40, edge=True)), lambda i: 3674 if i % 2 else 3571)
    out = us.run("dividend_value", data, as_of=D("2023-12-29"), usa=USA, idn=loose_idn,
                 panel=[])
    sectors = [c["sector"] for c in out["candidates"]]
    assert set(sectors) <= {"SIC 35", "SIC 36"}
    assert all(sectors.count(x) <= us.MAX_PER_SECTOR for x in set(sectors))
    assert len(out["candidates"]) == min(len(free["candidates"]), 2 * us.MAX_PER_SECTOR)
    r = out["ranking"][0]
    assert r["industry"] == f"SIC {r['sic']:04d}" and r["sector"] == f"SIC {r['sic'] // 100}"
    assert not any("SIC" in x for x in out["stale_inputs"])  # every ranked name has one


def test_names_without_sic_are_counted_as_a_stale_input():
    data = _with_sic(_big(synth(n=40, edge=True)), lambda i: None if i % 3 == 0 else 3571)
    out = us.run("dividend_value", data, as_of=D("2023-12-29"), usa=USA, idn=IDN, panel=[],
                 n_shuffles=20, n_controls=1)
    missing = sum(1 for r in out["ranking"] if r["sic"] is None)
    assert missing and f"{missing} of {out['pool']} ranked names have no SIC" in " ".join(
        out["stale_inputs"])
    assert out["ranking"][0]["sector"] in (None, "SIC 35")


def test_run_without_hurdles_ranks_but_names_no_one():
    data = _big(synth(n=40, edge=True))
    out = us.run("dividend_value", data, as_of=D("2023-12-29"), usa=None, idn=None, panel=[],
                 n_shuffles=20, n_controls=1)
    assert out["candidates"] == []
    assert any("hurdle" in s for s in out["stale_inputs"])
    assert any("SIC" in s for s in out["stale_inputs"])  # no peer groups in the store


def test_live_gates_reject_small_and_illiquid_names():
    data = _big(synth(n=3, edge=True))
    data.bars["S00"] = [Bar(b.date, b.price, 1e9) for b in data.bars["S00"]]
    data.values["S01"] = [(d, 1e6) for d, _ in data.values["S01"]]
    rows, rejects = us.rank_live("dividend_value", data, D("2023-12-29"), USA, IDN)
    assert rejects["mktcap"] == 1 and rejects["liquidity"] == 1
    assert [r["symbol"] for r in rows] in ([], ["S02"])


# ---------------- load ----------------


def test_build_turns_store_rows_into_engine_inputs():
    lst = [Listing("AAA", 1, "Aaa Corp"), Listing("BNK", 2, "Bank Corp")]
    raw = {"AAA": [ubar(D("2024-01-01") + timedelta(days=i), 100.0, sym="AAA")
                   for i in range(10)], "BNK": []}
    facts = {1: _apple_like() + [fact("EntityCommonStockSharesOutstanding", "2024-10-20",
                                      "2024-10-20", 1e8, "2024-11-01", unit="shares")],
             2: [fact("Deposits", "2024-12-31", "2024-12-31", 1e9, "2025-02-01")]}
    data = us.build(lst, raw, facts)
    assert data.listings["AAA"].cik == 1
    assert len(data.bars["AAA"]) == 10 and data.values["AAA"][0][1] == pytest.approx(1e8)
    assert data.quarters["AAA"][0].ni_ttm == 100.0
    assert data.banks == {"BNK"}
    assert "BNK" not in data.bars  # no bars, not a name


def test_load_with_the_store_locked_is_stale_not_a_crash(store):
    src = UsStocks(Usfin(url=URL, path=store, client=fake_serve(store)))
    with hold_duckdb_lock(store):
        data = us.load(src, as_of=D("2026-02-01"))
    assert any("locked" in s for s in data.stale)
    assert data.quarters == {} or all(not v for v in data.quarters.values())


# The fixture has 4 AAPL sessions: a 3-session median keeps the liquidity floor at 1 session.
LOOSE = {**us.CONFIG, "med_sessions": 3}


def test_load_reads_the_fixture_store(store):
    src = UsStocks(Usfin(url=None, path=store))
    data = us.load(src, as_of=D("2026-02-01"), cfg=LOOSE)
    assert set(data.listings) == {"AAPL", "BRK.B", "META"}
    assert len(data.bars["AAPL"]) == 4
    assert data.quarters["AAPL"][0].ni_ttm == 112010000000
    assert data.stale == [] or all("bars" in s for s in data.stale)


def test_load_with_an_empty_universe_says_so(tmp_path, store):
    con = duckdb.connect(str(store))
    con.execute("delete from alpaca_universe")
    con.close()
    data = us.load(UsStocks(Usfin(url=None, path=store)), as_of=D("2026-02-01"))
    assert data.listings == {}
    assert any("universe empty" in s for s in data.stale)


# ---------------- P63: long timeout, one bulk bar read ----------------


def test_default_source_reads_sec_edgar_with_the_long_timeout(monkeypatch, store):
    """The USA candidate step (load without a source, as undervalued.gather_live_usa calls it)
    asks `usfin serve` with paper's long timeout, not the 5 s probe timeout."""
    from assist.sources import usfin as usfin_mod

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.extensions["timeout"]["read"]))
        return fake_serve(store)._transport.handle_request(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(usfin_mod.Usfin, "from_config",
                        classmethod(lambda cls, *a, **k: cls(url=URL, path=store, client=client)))
    us.load(as_of=D("2026-02-01"))
    assert seen and seen[0] == ("/prices/universe", usfin_mod.US_HTTP_TIMEOUT)


def test_bars_many_equal_bars_per_symbol(store):
    src = UsStocks(Usfin(url=None, path=store))
    got = src.bars_many(["AAPL", "META", "NOPE"])
    assert got == {"AAPL": src.bars("AAPL"), "META": src.bars("META")}


def test_bars_many_skip_names_never_liquid_enough(store):
    """AAPL trades over US$10bn on each of its 4 fixture days, META ~US$4.6bn on 1 and
    ~US$3.5bn on the other: a floor of 2 sessions at US$4bn keeps AAPL only."""
    src = UsStocks(Usfin(url=None, path=store))
    got = src.bars_many(["AAPL", "META"], min_value=4e9, min_sessions=2)
    assert set(got) == {"AAPL"}
    assert set(src.bars_many(["AAPL", "META"], min_value=4e9, min_sessions=1)) == {"AAPL", "META"}


def test_bars_many_go_to_the_file_since_serve_has_no_bulk_route(store):
    src = UsStocks(Usfin(url=URL, path=store, client=fake_serve(store)))
    assert set(src.bars_many(["AAPL"])) == {"AAPL"}
    assert src.usfin.via == "duckdb"


def test_liquid_floor_is_a_necessary_condition_of_the_median_value_gate():
    value, sessions = us.liquid_floor(us.CONFIG)
    assert value == us.CONFIG["min_med_value"]
    n = max(1, us.CONFIG["med_sessions"] // 3)
    assert sessions == -(-n // 2)  # 10: half the shortest window median_value judges
    # a window of the shortest length with one session fewer than the floor fails the gate
    d0 = D("2024-01-01")
    vals = [(d0 + timedelta(days=i), 2 * value if i < sessions - 1 else 1.0) for i in range(n)]
    assert us.median_value(vals, vals[-1][0], us.CONFIG["med_sessions"]) < value
    vals[sessions - 1] = (vals[sessions - 1][0], 2 * value)
    assert us.median_value(vals, vals[-1][0], us.CONFIG["med_sessions"]) >= value


def test_load_reads_bars_in_one_bulk_query_not_per_symbol(store):
    calls = []
    client = fake_serve(store)
    inner = client._transport

    def handler(request):
        calls.append(request.url.path)
        return inner.handle_request(request)

    src = UsStocks(Usfin(url=URL, path=store, client=httpx.Client(
        transport=httpx.MockTransport(handler))))
    data = us.load(src, as_of=D("2026-02-01"), cfg=LOOSE)
    assert "/prices" not in calls  # bars come from one ATTACH, not one GET a symbol
    assert len(data.bars["AAPL"]) == 4


def test_load_skips_bars_of_names_below_the_liquidity_floor(store):
    """With the live floor (10 sessions of US$20m) the 4-session fixture names are not read."""
    data = us.load(UsStocks(Usfin(url=None, path=store)), as_of=D("2026-02-01"))
    assert data.bars == {} and set(data.listings) == {"AAPL", "BRK.B", "META"}
