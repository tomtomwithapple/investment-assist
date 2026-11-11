"""IDR hurdle per market (P34, PLAN S17): local 10Y + US ERP + CRP, the unhedged FX haircut for
foreign markets and the risk-off premium. Sources are in-memory fakes holding tidy `Row`s shaped
like the real adapters' (dbnomics ids and fractions, PHEI `IGSYC.10` percent, JISDOR levels)."""

from __future__ import annotations

import importlib
from datetime import date, timedelta

import pytest

from assist.candidates import hurdle as H
from assist.candidates.hurdle import CONFIG, Hurdle, hurdle, hurdles, margin
from assist.fx import unhedged_idr_return
from assist.layers.types import Regime
from assist.sources.base import Row, SourceUnavailable
from assist.sources.idxscape import JISDOR
from assist.sources.idxscape_phei import IGSYC_10Y

AS_OF = date(2026, 10, 21)
# the module, not the function `assist.layers.rules` re-exports under the same name
idn_stocks = importlib.import_module("assist.layers.rules.idn_stocks")


class Fake:
    """A source holding rows in memory; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, rows or [], error

    def rows(self, series_ids=None, start=None, end=None):
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted(
            (r for r in self._rows
             if (series_ids is None or r.series_id in series_ids)
             and (start is None or r.date >= start) and (end is None or r.date <= end)),
            key=lambda r: (r.series_id, r.date),
        )


def _r(src: str, sid: str, d: date, v: float) -> Row:
    return Row(sid, d, v, None, src)


def _dbn_rows(**skip) -> list[Row]:
    rows = [
        _r("dbnomics", "us.erp.implied", date(2026, 9, 1), 0.0430),
        _r("dbnomics", "us.erp.implied", date(2026, 10, 1), 0.0420),
        _r("dbnomics", "idn.crp", date(2026, 7, 1), 0.0250),
        _r("dbnomics", "usa.crp", date(2026, 7, 1), 0.0),
        _r("dbnomics", "deu.crp", date(2026, 7, 1), 0.0),
        _r("dbnomics", "idn.erp.hurdle", date(2026, 8, 1), 0.0690),
        _r("dbnomics", "idn.rate.long", date(2026, 8, 1), 6.80),
        _r("dbnomics", "usa.rate.long", date(2026, 8, 1), 4.20),
        _r("dbnomics", "ea20.rate.long", date(2026, 8, 1), 2.90),
    ]
    return [r for r in rows if r.series_id not in skip.get("ids", ())]


def _jisdor(start: date, end: date, slope: float = 0.0001) -> list[Row]:
    """IDR per USD, every 7 days, rising (the dollar gains) with a dip in the middle."""
    out, d, v = [], start, 15000.0
    i = 0
    while d <= end:
        wobble = -400.0 if (i // 20) % 3 == 1 else 0.0
        out.append(_r("idxscape", JISDOR, d, v * (1 + slope * i) + wobble))
        d += timedelta(days=7)
        i += 1
    return out


def world(*, phei: bool = True, dbn_skip: tuple[str, ...] = (), fx_years: int = 4,
          **replace) -> dict[str, Fake]:
    w = {
        "dbnomics": Fake("dbnomics", _dbn_rows(ids=dbn_skip)),
        "idxscape_phei": Fake("idxscape_phei", [
            _r("idxscape_phei", IGSYC_10Y, date(2026, 10, 20), 6.50),
            _r("idxscape_phei", IGSYC_10Y, date(2026, 10, 21), 6.40),
        ]) if phei else Fake("idxscape_phei", error="missing"),
        "idxscape_sun": Fake("idxscape_phei", []),
        "idxscape": Fake("idxscape", _jisdor(AS_OF - timedelta(days=365 * fx_years), AS_OF)),
        "bisfetcher": Fake("bisfetcher", [
            _r("bisfetcher", "WS_CBPOL.M.ID", date(2026, 8, 1), 5.00),
            _r("bisfetcher", "WS_CBPOL.M.US", date(2026, 8, 1), 4.00),
            _r("bisfetcher", "WS_CBPOL.M.XM", date(2026, 8, 1), 2.00),
        ]),
        "singstat": Fake("singstat", []),
        "jquantster": Fake("jquantster", []),
        "ausdata": Fake("ausdata", []),
        "openkrx": Fake("openkrx", []),
    }
    w.update(replace)
    return w


# ---------------- IDN ----------------


def test_idn_is_igsyc_10y_plus_us_erp_plus_idn_crp():
    h = hurdle("IDN", AS_OF, "neutral", sources=world())
    assert isinstance(h, Hurdle)
    assert h.required == pytest.approx(6.40 + 4.20 + 2.50)
    assert h.local_required == pytest.approx(h.required)
    assert h.components == pytest.approx({"ten_year": 6.40, "us_erp": 4.20, "crp": 2.50,
                                          "risk_off": 0.0})
    assert h.ten_year_source == "igsyc"
    assert h.fx_move is None
    assert h.stale_inputs == () and not h.stale
    assert {"idxscape_phei", "dbnomics"} <= set(h.sources)


def test_idn_drivers_never_carry_the_raw_igsyc_10y():
    h = hurdle("IDN", AS_OF, "neutral", sources=world())
    text = " ".join(h.drivers)
    assert "6.40" not in text and "6.4%" not in text
    assert "13.10" in text  # the derived total is fine


def test_idn_takes_the_sun_10y_before_the_proxy():
    """P101: no IGSYC 10Y, DJPPR's SUN 10Y benchmark (store key `idxscape_sun`) is next."""
    from assist.sources.idxscape_phei import SUN_10Y

    sun = Fake("idxscape_phei", [_r("idxscape_phei", SUN_10Y, date(2026, 10, 20), 6.90)])
    h = hurdle("IDN", AS_OF, "neutral",
               sources=world(idxscape_phei=Fake("idxscape_phei", []), idxscape_sun=sun))
    assert h.ten_year_source == "sun"
    assert h.components["ten_year"] == pytest.approx(6.90)
    assert not any("proxy" in s for s in h.stale_inputs)
    assert any("SUN 10Y benchmark" in d for d in h.drivers)


def test_idn_falls_back_to_the_flagged_dbnomics_proxy():
    h = hurdle("IDN", AS_OF, "neutral", sources=world(phei=False))
    assert h.ten_year_source == "proxy"
    assert h.components["ten_year"] == pytest.approx(6.80)
    assert h.required == pytest.approx(6.80 + 4.20 + 2.50)
    assert any("idxscape_phei" in s for s in h.stale_inputs)
    assert any("idn.rate.long" in s and "proxy" in s for s in h.stale_inputs)
    assert any("proxy" in d for d in h.drivers)
    assert h.stale


def test_idn_uses_the_dbnomics_hurdle_when_erp_or_crp_is_missing():
    h = hurdle("IDN", AS_OF, "neutral", sources=world(dbn_skip=("idn.crp",)))
    assert h.components == pytest.approx({"ten_year": 6.40, "erp_hurdle": 6.90, "risk_off": 0.0})
    assert h.required == pytest.approx(6.40 + 6.90)
    assert any("idn.crp" in s for s in h.stale_inputs)


def test_idn_reuses_the_idn_stocks_series_and_lags():
    assert H.US_ERP is idn_stocks.US_ERP
    assert H.IDN_CRP is idn_stocks.IDN_CRP
    assert H.HURDLE is idn_stocks.HURDLE
    erp, = (r for r in H.ERP_REFS if r.series_id == idn_stocks.US_ERP)
    assert erp.lag_days == idn_stocks.LAG[idn_stocks.US_ERP].days


def test_point_in_time_a_crp_inside_its_publication_lag_is_not_known():
    rows = _dbn_rows() + [_r("dbnomics", "idn.crp", date(2026, 10, 1), 0.0400)]
    h = hurdle("IDN", AS_OF, "neutral", sources=world(dbnomics=Fake("dbnomics", rows)))
    assert h.components["crp"] == pytest.approx(2.50)  # 2026-10-01 + 45d > as_of


def test_missing_10y_gives_no_hurdle_and_names_it():
    w = world(phei=False, dbn_skip=("idn.rate.long",))
    h = hurdle("IDN", AS_OF, "neutral", sources=w)
    assert h.required is None
    assert any("10Y" in s for s in h.stale_inputs)
    assert margin(12.0, h) is None


def test_locked_dbnomics_is_a_stale_input_not_a_crash():
    h = hurdle("IDN", AS_OF, "neutral", sources=world(dbnomics=Fake("dbnomics", error="locked")))
    assert h.required is None
    assert any("dbnomics" in s and "locked" in s for s in h.stale_inputs)


# ---------------- risk-off premium ----------------


def test_risk_off_adds_the_configured_premium():
    base = hurdle("IDN", AS_OF, "neutral", sources=world())
    off = hurdle("IDN", AS_OF, "risk_off", sources=world())
    assert CONFIG["risk_off_premium_pt"] == 1.0
    assert off.required - base.required == pytest.approx(1.0)
    assert off.components["risk_off"] == pytest.approx(1.0)
    assert any("risk-off" in d for d in off.drivers)


def test_regime_object_and_unknown_regime():
    reg = Regime(as_of=AS_OF, state="risk_off", dollar="up")
    assert hurdle("IDN", AS_OF, reg, sources=world()).regime == "risk_off"
    unknown = hurdle("IDN", AS_OF, None, sources=world())
    assert unknown.components["risk_off"] == 0.0
    assert any("regime unknown" in d for d in unknown.drivers)


# ---------------- foreign ----------------


def test_usa_is_local_10y_plus_erp_plus_crp_with_the_adverse_fx_haircut():
    h = hurdle("USA", AS_OF, "neutral", sources=world())
    assert h.required == pytest.approx(4.20 + 4.20 + 0.0)
    assert h.fx_basis.startswith("adverse")
    assert h.fx_move is not None and h.fx_move < 0  # the dip makes the 5% quantile a USD fall
    expect_local = 100 * ((1 + h.required / 100) / (1 + h.fx_move) - 1)
    assert h.local_required == pytest.approx(expect_local)
    assert h.components["fx_haircut"] == pytest.approx(expect_local - h.required)
    # a name earning exactly local_required in USD delivers the IDR hurdle after the move
    assert h.idr_return(h.local_required) == pytest.approx(h.required)
    assert h.idr_return(10.0) == pytest.approx(100 * unhedged_idr_return(0.10, h.fx_move))


def test_usa_short_fx_history_falls_back_to_uip():
    h = hurdle("USA", AS_OF, "neutral", sources=world(fx_years=1))
    assert h.fx_basis.startswith("UIP")
    assert h.fx_move == pytest.approx((1 + 0.05) / (1 + 0.04) - 1)


def test_usa_without_fx_keeps_the_idr_hurdle_and_names_the_gap():
    h = hurdle("USA", AS_OF, "neutral",
               sources=world(idxscape=Fake("idxscape", error="missing"),
                             bisfetcher=Fake("bisfetcher", [])))
    assert h.required == pytest.approx(8.40)
    assert h.fx_move is None and h.local_required is None and h.idr_return(9.0) is None
    assert any("fx" in s for s in h.stale_inputs)


def test_emu_uses_ea20_10y_and_germany_crp_flagged():
    h = hurdle("EMU", AS_OF, "neutral", sources=world())
    assert h.components["ten_year"] == pytest.approx(2.90)
    assert h.components["crp"] == pytest.approx(0.0)
    assert any("deu.crp" in d for d in h.drivers)


def test_hurdles_reads_once_for_several_markets():
    out = hurdles(["IDN", "USA"], AS_OF, "risk_off", sources=world())
    assert [h.market for h in out] == ["IDN", "USA"]
    assert all(h.components["risk_off"] == 1.0 for h in out)


def test_unknown_market_raises():
    with pytest.raises(KeyError):
        hurdle("XXX", AS_OF, "neutral", sources=world())


# ---------------- margin ----------------


def test_margin_is_expected_minus_hurdle_minus_sector_shift():
    h = hurdle("IDN", AS_OF, "neutral", sources=world())
    assert margin(15.0, h) == pytest.approx(15.0 - 13.10)
    assert margin(15.0, h, sector_shift_pt=1.5) == pytest.approx(15.0 - 13.10 - 1.5)
    assert margin(15.0, h.required) == pytest.approx(1.90)
    assert margin(None, h) is None


def test_margin_clamps_the_sector_shift():
    assert CONFIG["sector_shift_max_pt"] == 2.0
    assert margin(10.0, 8.0, sector_shift_pt=5.0) == pytest.approx(0.0)
    assert margin(10.0, 8.0, sector_shift_pt=-5.0) == pytest.approx(4.0)


def test_config_is_hashed_into_the_model_fingerprint():
    from assist.journal import default_rule_files
    assert any(p.name == "hurdle.py" and p.parent.name == "candidates"
               for p in default_rule_files())
