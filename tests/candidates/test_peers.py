"""Peer comparison (S30): log deviations with their None and floor cases and the clamp, category
scores signed so positive is better, industry and sector medians as the benchmarks (Stockbit's
means carried, never scored), market-cap tiers, a too-small industry with no median, the stale
input, the byte-stable write, and `pipeline.write_peers` never raising. Synthetic `Comparison`s;
no store."""

from __future__ import annotations

import json
import math
from datetime import date

import pytest

from assist import pipeline
from assist.candidates import peers
from assist.sources.idxmethod_comparison import Comparison

DAY = date(2026, 10, 27)
LN4 = math.log(4)
PE, PBV, YIELD, PAYOUT, ROE, DER, MKTCAP = 2891, 2896, 2915, 2916, 1461, 1508, 2892


def _cmp(rows: dict[str, tuple[str, str, dict]], as_of: date = date(2026, 10, 26)) -> Comparison:
    """rows: symbol → (industry key, sector, {fid: value})."""
    c = Comparison(date=as_of)
    for sym, (ind, sector, vals) in rows.items():
        c.ratios[sym] = dict(vals)
        c.industry[sym] = ind
        c.sector_key[sym] = sector
        c.sectors[sym] = sector
        c.names[sym] = f"{sym} Tbk"
        c.industry_avg[sym] = {PE: -77.0}  # a mean dragged below zero: never the benchmark
        c.sector_avg[sym] = {PE: 9.9}
        c.competitors[sym] = [sym]
    return c


BANKS = {
    "AAAA": ("bank", "Keuangan", {PE: 5.0, PBV: 1.0, YIELD: 10.0, PAYOUT: 60.0, ROE: 20.0,
                                  DER: 0.5, MKTCAP: 100e12}),
    "BBBB": ("bank", "Keuangan", {PE: 10.0, PBV: 2.0, YIELD: 5.0, ROE: 10.0, DER: 1.0,
                                  MKTCAP: 5e12}),
    "CCCC": ("bank", "Keuangan", {PE: 20.0, PBV: 4.0, YIELD: 0.0, ROE: -3.0, DER: 2.0,
                                  MKTCAP: 0.5e12}),
    "DDDD": ("insurer", "Keuangan", {PE: 8.0, MKTCAP: 2e12}),
}


@pytest.mark.parametrize(("value", "bench", "better", "want"), [
    (5.0, 10.0, "lower", math.log(0.5)),
    (20.0, 10.0, "higher", math.log(2)),
    (100.0, 10.0, "higher", LN4),  # clamped
    (0.1, 10.0, "lower", -LN4),
    (-3.0, 10.0, "higher", -LN4),  # a loss on a higher-is-better metric is the floor
    (0.0, 5.0, "higher", -LN4),  # no dividend
    (-6.0, 10.0, "lower", None),  # a loss-maker has no PE to be cheap on
    (5.0, -77.0, "lower", None),  # a non-positive benchmark
    (5.0, 0.0, "higher", None),
    (None, 10.0, "lower", None),
    (5.0, None, "lower", None),
])
def test_deviation(value, bench, better, want):
    got = peers.deviation(value, bench, better)
    assert got == (pytest.approx(want) if want is not None else None)


@pytest.mark.parametrize(("cap", "want"), [(10e12, "big"), (9.9e12, "mid"), (1e12, "mid"),
                                           (0.99e12, "small"), (None, None)])
def test_tier(cap, want):
    assert peers.tier(cap) == want


@pytest.fixture
def payload() -> dict:
    return peers.build(_cmp(BANKS), DAY)


def _stock(p: dict, sym: str) -> dict:
    return next(s for i in p["industries"] for s in i["stocks"] if s["symbol"] == sym)


def test_industries_and_medians(payload):
    by_id = {i["id"]: i for i in payload["industries"]}
    bank = by_id["bank"]
    assert [s["symbol"] for s in bank["stocks"]] == ["AAAA", "BBBB", "CCCC"]  # by market cap
    assert bank["n"] == 3 and bank["leaders"] == ["AAAA", "BBBB", "CCCC"]
    assert bank["label"] == "Keuangan"  # no anchor among the members: the sector name

    assert bank["median"]["pe"] == 10.0 and bank["median"]["div_yield"] == 5.0
    assert bank["average"]["pe"] == -77.0  # carried as Stockbit gave it
    assert by_id["insurer"]["median"]["pe"] is None  # one name: below min_median
    assert payload["sectors"]["Keuangan"]["median"]["pe"] == 9.0  # 5, 8, 10, 20
    assert payload["sectors"]["Keuangan"]["average"]["pe"] == 9.9

def test_subsector_names_a_group_by_its_anchors():
    assert peers.subsector(["XXXX", "BBRI"], "Keuangan") == "Bank"
    assert peers.subsector(["GIAA"], "Transportasi & Logistik") == "Transportasi"
    assert peers.subsector(["XXXX"], "Energi") == "Energi"
    assert peers.subsector(["XXXX"], "") == "Unknown sector"
    anchors = [a for _, xs in peers.SUBSECTORS for a in xs]
    assert len(anchors) == len(set(anchors))  # an anchor names one sub-sector only


def test_scores_are_signed_so_positive_is_better(payload):
    a, c = _stock(payload, "AAAA"), _stock(payload, "CCCC")
    # AAAA: PE 5 vs 10 and PBV 1 vs 2 → both half the median, i.e. 2x cheaper
    assert a["dev_industry"]["pe"] == pytest.approx(math.log(0.5), abs=1e-4)
    assert a["score_industry"]["valuation"] == pytest.approx(math.log(2), abs=1e-4)
    assert a["scored_metrics"]["valuation"] == 2
    assert a["score_industry"]["dividend"] == pytest.approx(math.log(2), abs=1e-4)
    assert a["scored_metrics"]["dividend"] == 1  # payout is shown, not scored
    assert a["score_industry"]["solvency"] == pytest.approx(math.log(2), abs=1e-4)
    assert c["score_industry"]["valuation"] < 0
    assert c["score_industry"]["dividend"] == pytest.approx(-LN4, abs=1e-4)  # pays nothing
    assert c["score_industry"]["profitability"] == pytest.approx(-LN4, abs=1e-4)  # a loss
    assert _stock(payload, "BBBB")["score_industry"]["valuation"] == 0.0


def test_sector_scores_use_the_sector_median(payload):
    a = _stock(payload, "AAAA")
    assert a["dev_sector"]["pe"] == pytest.approx(math.log(5 / 9), abs=1e-4)
    d = _stock(payload, "DDDD")
    assert d["score_industry"]["valuation"] is None and d["scored_metrics"]["valuation"] == 0
    assert d["score_sector"]["valuation"] == pytest.approx(-math.log(8 / 9), abs=1e-4)


def test_tiers_names_and_payload_shape(payload):
    assert [_stock(payload, s)["tier"] for s in ("AAAA", "BBBB", "CCCC")] == ["big", "mid", "small"]
    assert _stock(payload, "AAAA")["name"] == "AAAA Tbk"
    assert payload["as_of"] == "2026-10-26" and payload["built"] == "2026-10-27"
    assert payload["market"] == "IDN" and payload["stale_inputs"] == []
    assert [c["key"] for c in payload["categories"]] == ["valuation", "dividend", "profitability",
                                                        "solvency"]
    assert payload["disclaimer"]


def test_a_comparison_older_than_14_days_is_a_stale_input():
    p = peers.build(_cmp(BANKS, as_of=date(2026, 10, 1)), DAY)
    assert p["stale_inputs"] == ["peer comparison as of 2026-10-01 (26 days old)"]


def test_write_keeps_an_unchanged_file(tmp_path, payload):
    path = peers.write(payload, tmp_path)
    assert path == tmp_path / "industries" / "IDN.json"
    assert json.loads(path.read_text())["industries"]
    stamp = path.stat().st_mtime_ns
    peers.write(payload, tmp_path)
    assert path.stat().st_mtime_ns == stamp


def test_write_peers_never_raises(tmp_path, payload):
    def broken(day):
        raise RuntimeError("store locked\nsecond line")

    assert pipeline.write_peers(DAY, None, tmp_path) == (None, [])
    path, stale = pipeline.write_peers(DAY, broken, tmp_path)
    assert path is None and stale == ["peer comparison failed: RuntimeError: store locked"]
    path, stale = pipeline.write_peers(DAY, lambda d: payload, tmp_path)
    assert path == tmp_path / "industries" / "IDN.json" and stale == []
