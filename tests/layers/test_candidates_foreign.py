"""Foreign candidates, index level (P29, PLAN S12): one broad index per market, valued by its
earnings yield against the local 10Y and the US ERP + country CRP hurdle, and tested in IDR
through P27's `fx_edge`.

Most tests feed in-memory sources (tidy `Row`s, no store). Every market is exercised with fixture
rows, including those whose valuation has no live source (JPN, AUS, SGP, KOR, TWN): those tests
point the market's valuation at a fixture series, so the generic logic is covered even where the
live spec says "no source". The last test runs the real dbnomics adapter over a tiny store."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest
from helpers import FIXTURES, make_duckdb

from assist.fx import fx_edge
from assist.layers.candidates_foreign import (
    INVERSE,
    MARKETS,
    PCT,
    SCREEN,
    ForeignCandidates,
    IndexValuation,
    Ref,
    assess,
    expected_fx_move,
    foreign_candidates,
    market,
)
from assist.layers.types import Candidate
from assist.sources.base import Row, SourceUnavailable
from assist.sources.dbnomics import DbnomicsSource

AS_OF = date(2026, 10, 21)


class Fake:
    """A source holding rows in memory; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, rows or [], error
        self.calls: list[dict] = []

    def rows(self, series_ids=None, start=None, end=None):
        self.calls.append({"series_ids": series_ids, "start": start, "end": end})
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted(
            (r for r in self._rows
             if (series_ids is None or r.series_id in series_ids)
             and (start is None or r.date >= start) and (end is None or r.date <= end)),
            key=lambda r: (r.series_id, r.date),
        )


def _months(end: date, n: int) -> list[date]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def monthly(sid: str, value: float, source: str, end: date = date(2026, 9, 1), n: int = 3,
            as_of: date | None = None) -> list[Row]:
    return [Row(sid, d, value, as_of, source) for d in _months(end, n)]


def daily(sid: str, start_value: float, source: str, years: float = 3.0, drift: float = 0.0,
          end: date = date(2026, 10, 20)) -> list[Row]:
    """A daily series over `years`, compounding `drift` per year (weekdays only)."""
    out, d = [], end - timedelta(days=int(365 * years))
    while d <= end:
        if d.weekday() < 5:
            t = (d - (end - timedelta(days=int(365 * years)))).days / 365
            out.append(Row(sid, d, start_value * (1 + drift) ** t, d, source))
        d += timedelta(days=1)
    return out


def us_world(**overrides) -> dict[str, Fake]:
    """Every store the US needs, fresh on AS_OF: CAPE 40, 10Y 4.5%, CPI 3%, ERP 4%, CRP 0.2%,
    JISDOR rising 3%/yr over 3 years, BI 5.75% vs Fed 4%, IDN 10Y 6.5% on the PHEI curve."""
    rows = {
        "dbnomics": [
            *monthly("us.cape", 40.0, "dbnomics", end=date(2026, 10, 1)),
            *monthly("usa.rate.long", 4.5, "dbnomics"),
            *monthly("usa.cpi.yoy", 3.0, "dbnomics", end=date(2026, 8, 1)),
            *monthly("us.erp.implied", 0.04, "dbnomics", end=date(2026, 10, 1)),
            Row("usa.crp", date(2026, 1, 1), 0.002, None, "dbnomics"),
            *monthly("idn.rate.long", 7.0, "dbnomics", end=date(2024, 12, 1)),
        ],
        "idxscape": daily("JISDOR", 16000, "idxscape", drift=0.03),
        "idxscape_phei": [Row("IGSYC.10", date(2026, 10, 20), 6.5, date(2026, 10, 20),
                              "idxscape_phei")],
        "bisfetcher": [
            *monthly("WS_CBPOL.M.ID", 5.75, "bisfetcher", as_of=date(2026, 10, 14)),
            *monthly("WS_CBPOL.M.US", 4.0, "bisfetcher", as_of=date(2026, 10, 14)),
        ],
    }
    rows.update(overrides)
    return {name: Fake(name, r) for name, r in rows.items()}


def only(result: ForeignCandidates, subject: str) -> IndexValuation:
    found = [v for v in result.valuations if v.market.subject == subject]
    assert len(found) == 1, result
    return found[0]


# ---------------- the markets ----------------


def test_markets_cover_us_jp_au_sg_kr_tw():
    assert [m.subject for m in MARKETS] == ["USA", "JPN", "AUS", "SGP", "KOR", "TWN"]
    assert [m.symbol for m in MARKETS] == ["SPX", "TOPIX", "XJO", "STI", "KOSPI", "TAIEX"]
    assert market("USA").index == "S&P 500"
    with pytest.raises(KeyError):
        market("IDN")


def test_every_market_names_its_hurdle_and_fx():
    for m in MARKETS:
        assert m.crp, m.subject
        assert m.fx is not None, m.subject
        # whatever has no source says which fetcher would add it
        for name in ("valuation", "yield_10y", "inflation", "short_rate"):
            if not getattr(m, name):
                assert dict(m.gaps).get(name), (m.subject, name)


# ---------------- the pure core ----------------


def test_assess_expensive_us():
    v = assess(market("USA"), AS_OF, earnings_yield=0.025, basis="CAPE", yield_10y=0.045,
               us_erp=0.04, crp=0.002)
    assert v.gap == pytest.approx(-0.02)
    assert v.hurdle == pytest.approx(0.042)
    assert v.edge == pytest.approx(-0.062)
    assert v.score == pytest.approx(50 - 5 * 6.2)
    assert v.fx is None and not v.passes
    c = v.candidate()
    assert isinstance(c, Candidate)
    assert (c.subject, c.asset, c.symbol, c.screen, c.as_of) == (
        "USA", "stocks", "SPX", SCREEN, AS_OF)
    assert c.entry_level is None
    assert "CAPE" in c.detail and "-6.20%" in c.detail and "IDR edge unknown" in c.detail


def test_assess_score_is_clamped():
    cheap = assess(market("KOR"), AS_OF, earnings_yield=0.30, basis="P/E", yield_10y=0.03,
                   us_erp=0.04, crp=0.006)
    dear = assess(market("KOR"), AS_OF, earnings_yield=0.01, basis="P/E", yield_10y=0.10,
                  us_erp=0.04, crp=0.006)
    assert cheap.score == 100 and dear.score == 0


def test_assess_fx_edge_matches_p27():
    v = assess(market("KOR"), AS_OF, earnings_yield=0.10, basis="P/E", yield_10y=0.03,
               us_erp=0.04, crp=0.006, inflation=0.02, r_idr=0.065, fx_move=-0.01,
               fx_basis="adverse", i_idr=0.0575, i_local=0.025)
    assert v.r_local == pytest.approx(0.12)
    assert v.fx == fx_edge(v.r_local, 0.065, -0.01, 0.0575, 0.025, 1.0)
    assert v.fx.survives and v.passes
    assert v.score == pytest.approx(50 + 5 * 2.4)


def test_fx_that_does_not_survive_caps_the_score():
    v = assess(market("KOR"), AS_OF, earnings_yield=0.10, basis="P/E", yield_10y=0.03,
               us_erp=0.04, crp=0.006, inflation=0.0, r_idr=0.15, fx_move=-0.05,
               fx_basis="adverse")
    assert v.edge > 0 and not v.fx.survives
    assert v.score == 50 and not v.passes
    assert "does not survive" in v.candidate().detail


def test_no_fx_edge_without_inflation_or_idr_alternative():
    base = dict(earnings_yield=0.10, basis="P/E", yield_10y=0.03, us_erp=0.04, crp=0.006,
                fx_move=0.0, fx_basis="adverse")
    assert assess(market("KOR"), AS_OF, **base, r_idr=0.065).fx is None
    assert assess(market("KOR"), AS_OF, **base, inflation=0.02).fx is None


def test_expected_fx_move_prefers_the_adverse_historical_move():
    rows = daily("X", 100, "s", years=3, drift=0.05)
    move, basis = expected_fx_move(rows, AS_OF, i_idr=0.0575, i_local=0.01)
    assert move == pytest.approx(0.05, abs=0.002)  # a steady drift: every 1y change is ~5%
    assert "5th pct" in basis


def test_expected_fx_move_falls_back_to_uip_on_short_history():
    rows = daily("X", 100, "s", years=1.2)
    move, basis = expected_fx_move(rows, AS_OF, i_idr=0.0575, i_local=0.01)
    assert move == pytest.approx(1.0575 / 1.01 - 1)
    assert basis.startswith("UIP")
    assert expected_fx_move(rows, AS_OF) == (None, "")
    assert expected_fx_move([], AS_OF, i_idr=None, i_local=0.01) == (None, "")


def test_expected_fx_move_is_point_in_time():
    rows = daily("X", 100, "s", years=3, drift=0.05)
    later = [Row("X", AS_OF + timedelta(days=d), 50.0, None, "s") for d in range(1, 30)]
    assert expected_fx_move(rows + later, AS_OF)[0] == pytest.approx(0.05, abs=0.002)


# ---------------- reading the stores ----------------


def test_us_live_spec_end_to_end():
    res = foreign_candidates(AS_OF, us_world(), markets=[market("USA")])
    v = only(res, "USA")
    assert v.earnings_yield == pytest.approx(1 / 40)
    assert v.basis == "CAPE"
    assert v.yield_10y == pytest.approx(0.045)
    assert v.hurdle == pytest.approx(0.042)
    assert v.inflation == pytest.approx(0.03)
    assert v.r_local == pytest.approx(0.055)
    assert v.r_idr == pytest.approx(0.065)  # PHEI 10Y, not the stale dbnomics IDN rate
    assert v.i_idr == pytest.approx(0.0575) and v.i_local == pytest.approx(0.04)
    assert v.fx_move == pytest.approx(0.03, abs=0.002)
    assert v.fx is not None and v.fx.hedged is not None
    assert res.candidates == (v.candidate(),)
    assert res.stale_inputs == ()
    assert set(res.sources) == {"dbnomics", "idxscape", "idxscape_phei", "bisfetcher"}
    assert "dbnomics" in v.candidate().source and "idxscape" in v.candidate().source


def test_reads_once_per_store_with_a_window_ending_on_as_of():
    world = us_world()
    foreign_candidates(AS_OF, world, markets=[market("USA")])
    for fake in world.values():
        assert len(fake.calls) == 1
        assert fake.calls[0]["end"] == AS_OF
        assert fake.calls[0]["start"] <= AS_OF - timedelta(days=365 * 3)


def test_idr_alternative_falls_back_to_dbnomics_and_names_it_stale():
    world = us_world(idxscape_phei=[])
    world["idxscape_phei"] = Fake("idxscape_phei", error="missing")
    res = foreign_candidates(AS_OF, world, markets=[market("USA")])
    v = only(res, "USA")
    assert v.r_idr == pytest.approx(0.07)
    assert "idxscape_phei (missing)" in res.stale_inputs
    assert any(s.startswith("dbnomics idn.rate.long (stale") for s in res.stale_inputs)


def test_missing_valuation_input_gives_no_candidate():
    world = us_world()
    world["dbnomics"] = Fake("dbnomics", [r for r in world["dbnomics"]._rows
                                          if r.series_id != "us.cape"])
    res = foreign_candidates(AS_OF, world, markets=[market("USA")])
    assert res.valuations == () and res.candidates == ()
    assert any(s.startswith("USA stocks valuation: no data") for s in res.stale_inputs)


def test_unavailable_store_is_a_stale_input_not_a_crash():
    world = us_world()
    world["dbnomics"] = Fake("dbnomics", error="locked")
    res = foreign_candidates(AS_OF, world, markets=[market("USA")])
    assert res.valuations == ()
    assert "dbnomics (locked)" in res.stale_inputs
    assert "dbnomics" not in res.sources


def test_unconfigured_store_is_named():
    world = us_world()
    del world["bisfetcher"]
    res = foreign_candidates(AS_OF, world, markets=[market("USA")])
    v = only(res, "USA")
    assert v.i_idr is None and v.fx.hedged is None  # unhedged only
    assert "bisfetcher (not configured)" in res.stale_inputs


def test_crp_snapshot_waits_for_its_publication_lag():
    world = us_world()
    world["dbnomics"]._rows.append(Row("usa.crp", date(2026, 10, 1), 0.05, None, "dbnomics"))
    v = only(foreign_candidates(AS_OF, world, markets=[market("USA")]), "USA")
    assert v.crp == pytest.approx(0.002)  # the Oct snapshot is not out until mid-November
    later = date(2026, 11, 20)
    v = only(foreign_candidates(later, world, markets=[market("USA")]), "USA")
    assert v.crp == pytest.approx(0.05)


def test_old_value_is_used_and_named_stale():
    world = us_world()
    world["dbnomics"] = Fake("dbnomics", [
        r for r in world["dbnomics"]._rows if r.series_id != "usa.rate.long"
    ] + monthly("usa.rate.long", 4.0, "dbnomics", end=date(2026, 1, 1)))
    res = foreign_candidates(AS_OF, world, markets=[market("USA")])
    assert only(res, "USA").yield_10y == pytest.approx(0.04)
    assert "dbnomics usa.rate.long (stale, last 2026-01-01)" in res.stale_inputs


def test_live_specs_without_valuation_name_the_gap():
    res = foreign_candidates(AS_OF, us_world())
    assert [v.market.subject for v in res.valuations] == ["USA"]
    for subject, fetcher in (("JPN", "jquantster"), ("KOR", "openkrx"), ("TWN", "openkrx")):
        gap = next(s for s in res.stale_inputs if s.startswith(f"{subject} stocks valuation"))
        assert "no source" in gap and fetcher in gap
    # stores the other markets need but this world lacks are named once, not crashed on
    assert "jquantster (not configured)" in res.stale_inputs
    assert res.stale_inputs.count("openkrx (not configured)") == 1


# ---------------- every market on fixtures ----------------


def _all_markets_world() -> tuple[dict[str, Fake], list]:
    """us_world plus fixture rows for every other market, with a fixture valuation series each."""
    world = us_world()
    fixture = {"JPN": 0.07, "AUS": 0.06, "SGP": 0.075, "KOR": 0.10, "TWN": 0.05}
    val_rows = [Row(f"fixture.{s}.pe", date(2026, 10, 15), 1 / ey, None, "fixture")
                for s, ey in fixture.items()]
    world["fixture"] = Fake("fixture", val_rows + [
        *monthly("fixture.TWN.10y", 1.6, "fixture"), *monthly("fixture.TWN.cpi", 1.8, "fixture"),
        *monthly("fixture.TWN.rate", 2.0, "fixture"), *monthly("fixture.JPN.cpi", 2.5, "fixture"),
    ])
    world["dbnomics"]._rows += [
        *monthly("aus.cpi.yoy", 3.5, "dbnomics", end=date(2026, 8, 1)),
        *monthly("kor.rate.long", 3.2, "dbnomics"),
        *monthly("kor.cpi.yoy", 2.0, "dbnomics", end=date(2026, 8, 1)),
        *[Row(f"{s}.crp", date(2026, 1, 1), c, None, "dbnomics")
          for s, c in (("jpn", 0.009), ("aus", 0.0), ("sgp", 0.0), ("kor", 0.0064),
                       ("twn", 0.0078))],
    ]
    world["bisfetcher"]._rows += [
        *monthly("WS_CBPOL.M.JP", 1.0, "bisfetcher", as_of=date(2026, 10, 14)),
        *monthly("WS_CBPOL.M.AU", 3.6, "bisfetcher", as_of=date(2026, 10, 14)),
        *monthly("WS_CBPOL.M.KR", 2.5, "bisfetcher", as_of=date(2026, 10, 14)),
    ]
    jisdor = world["idxscape"]._rows
    world["jquantster"] = Fake("jquantster", [
        Row("JGB.10Y", date(2026, 10, 20), 2.9, None, "jquantster"),
        *[r._replace(series_id="BOJ.usdjpy", value=150.0, source="jquantster") for r in jisdor],
    ])
    world["ausdata"] = Fake("ausdata", [
        Row("FCMYGBAG10D", date(2026, 10, 14), 5.3, date(2026, 10, 15), "ausdata"),
        *daily("FXRIR", 11000, "ausdata", drift=0.02),
    ])
    world["singstat"] = Fake("singstat", [
        *monthly("mas:sgs:10y", 2.5, "singstat", end=date(2026, 10, 1)),
        *[Row("singstat:M213751:1", d, 100 * 1.015 ** (i / 12), None, "singstat")
          for i, d in enumerate(_months(date(2026, 8, 1), 24))],
        *monthly("mas:sora:comp3m", 1.25, "singstat", end=date(2026, 10, 1)),
        *daily("mas:fx:idrsgd", 1 / 12000, "singstat", drift=-0.02),
        *daily("mas:fx:krwsgd", 0.00095, "singstat"),
        *daily("mas:fx:twdsgd", 0.040, "singstat"),
    ])
    world["openkrx"] = Fake("openkrx", error="missing")
    markets = []
    for m in MARKETS:
        if m.subject == "USA":
            markets.append(m)
            continue
        extra = {"valuation": (Ref("fixture", f"fixture.{m.subject}.pe", INVERSE, note="P/E"),)}
        if m.subject == "TWN":
            extra |= {"yield_10y": (Ref("fixture", "fixture.TWN.10y", PCT),),
                      "inflation": (Ref("fixture", "fixture.TWN.cpi", PCT),),
                      "short_rate": (Ref("fixture", "fixture.TWN.rate", PCT),)}
        if m.subject == "JPN":
            extra |= {"inflation": (Ref("fixture", "fixture.JPN.cpi", PCT),)}
        markets.append(replace(m, **extra))
    return world, markets


def test_every_market_is_valued_on_fixtures():
    world, markets = _all_markets_world()
    res = foreign_candidates(AS_OF, world, markets=markets)
    assert [v.market.subject for v in res.valuations] == [
        "USA", "JPN", "AUS", "SGP", "KOR", "TWN"]
    by = {v.market.subject: v for v in res.valuations}
    assert by["JPN"].yield_10y == pytest.approx(0.029)  # JGB from jquantster, daily
    assert by["AUS"].yield_10y == pytest.approx(0.053)  # AGS from ausdata
    assert by["SGP"].yield_10y == pytest.approx(0.025)
    assert by["SGP"].inflation == pytest.approx(0.015, abs=1e-9)  # CPI index → y/y
    assert by["SGP"].i_local == pytest.approx(0.0125)  # SORA 3m compounded
    assert by["KOR"].earnings_yield == pytest.approx(0.10)
    assert by["KOR"].hurdle == pytest.approx(0.04 + 0.0064)
    for v in res.valuations:
        assert v.fx is not None, v.market.subject
        assert v.i_local is not None, v.market.subject
    # IDR per JPY crosses JISDOR with USD/JPY, so it moves like JISDOR (+3%/yr)
    assert by["JPN"].fx_move == pytest.approx(0.03, abs=0.002)
    # IDR per KRW crosses MAS: SGD per KRW flat, SGD per IDR falling 2%/yr → KRW +2%/yr vs IDR
    assert by["KOR"].fx_move == pytest.approx(1 / 0.98 - 1, abs=0.002)
    assert by["AUS"].fx_move == pytest.approx(0.02, abs=0.002)
    assert len(res.candidates) == 6
    assert all(c.screen == SCREEN and c.asset == "stocks" for c in res.candidates)
    assert "openkrx (missing)" in res.stale_inputs  # index levels for KR/TW are context only
    ranked = res.ranked()
    assert ranked[0].symbol == "KOSPI" and ranked[-1].symbol == "SPX"


def test_passing_needs_edge_and_fx():
    world, markets = _all_markets_world()
    res = foreign_candidates(AS_OF, world, markets=markets)
    passing = {c.subject for c in res.passing()}
    for v in res.valuations:
        assert (v.market.subject in passing) == (v.edge > 0 and v.fx.survives)
    assert "USA" not in passing and "KOR" in passing


# ---------------- the real dbnomics adapter ----------------


def test_us_through_the_dbnomics_adapter(tmp_path):
    ddl = (FIXTURES / "dbnomics" / "schema.sql").read_text()
    seed = (FIXTURES / "dbnomics" / "seed.sql").read_text()
    obs = [
        (sid, d, d.strftime("%Y-%m"), v, "fixture", sid, "2026-10-21 06:40:40")
        for sid, v, end in (("us.cape", 40.0, date(2026, 10, 1)),
                            ("usa.rate.long", 4.5, date(2026, 9, 1)),
                            ("usa.cpi.yoy", 3.0, date(2026, 8, 1)))
        for d in _months(end, 2)
    ] + [("usa.crp", date(2026, 1, 1), "2026-01", 0.002, "derived", "x", "2026-10-21 06:40:40")]
    path = make_duckdb(tmp_path / "dbnomics.duckdb", ddl + seed, {"observations": obs})
    world = us_world()
    world["dbnomics"] = DbnomicsSource(url=None, path=path)
    res = foreign_candidates(AS_OF, world, markets=[market("USA")])
    v = only(res, "USA")
    assert v.earnings_yield == pytest.approx(0.025)
    assert v.us_erp == pytest.approx(0.037)  # the seed's Oct 2026 Damodaran ERP
    assert v.hurdle == pytest.approx(0.039)
    assert res.candidates[0].symbol == "SPX"
