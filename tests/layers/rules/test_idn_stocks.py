"""IDN stocks market rule (P22, PLAN S10a): JCI earnings yield vs the SBN 10Y, an implied ERP
against the US ERP + IDN CRP hurdle, IDX foreign flow + KSEI foreign share (P18) and the layer-1
macro score shifted by P17's override, turned into a call and an entry plan that may change a
stance only once it beats its placebo (P9).

Sources are in-memory fakes (tidy `Row`s, no store), except the snapshot reader, which runs over
a tiny idx-method tree built in tmp_path."""

from __future__ import annotations

import gzip
import json
import os
from datetime import date, datetime, timedelta

import pytest

from assist.eval.placebo import Verdict
from assist.layers.bonds.idn import PROXY_10Y
from assist.layers.overrides import DBN_CPI, IdnOverrides
from assist.layers.rules import (
    FactorSnapshots,
    IdnStocks,
    decide,
    gated_stance,
    idn_stocks,
    market_earnings_yield,
    month_end_closes,
    rule_verdict,
)
from assist.layers.rules.idn_stocks import HURDLE, IDN_CRP, US_ERP
from assist.layers.signals import IdnSignals
from assist.layers.types import AssetScore, Override, Regime, Signal
from assist.sources.base import Row, SourceUnavailable
from assist.sources.bpslooker import CPI_YOY
from assist.sources.idxmethod import JCI
from assist.sources.idxscape_phei import IGSYC_10Y

AS_OF = date(2026, 10, 23)


class Fake:
    """A source holding rows in memory; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, rows or [], error

    def rows(self, series_ids=None, start=None, end=None, **kw):
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted(
            (r for r in self._rows
             if (series_ids is None or r.series_id in series_ids)
             and (start is None or r.date >= start) and (end is None or r.date <= end)),
            key=lambda r: (r.series_id, r.date),
        )


class FakeSnapshots:
    name = "idx-method"

    def __init__(self, factors: dict | None, on: date = date(2026, 10, 22), error=None):
        self.factors, self.on, self.error = factors, on, error

    def factors_on(self, as_of: date):
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        if self.factors is None or self.on > as_of:
            raise SourceUnavailable(self.name, "missing", f"no snapshot on or before {as_of}")
        return self.on, self.factors


class FakeWbs:
    name = "worldbankscape"

    def __init__(self, score: AssetScore | None = None, error=None):
        self._score, self.error = score, error

    def score(self, subject, asset):
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return self._score


def _months(end: date, n: int) -> list[date]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return sorted(out)


def _days(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def factors(ey=10.0, n=3) -> dict:
    """`n` names of equal cap, each at earnings yield `ey` %."""
    return {f"S{i}": {"symbol": f"S{i}", "mktcap": 1e14, "earnings_yield": ey, "pe": 100 / ey}
            for i in range(n)}


def phei_source(ten=7.0, last=date(2026, 10, 22)) -> Fake:
    return Fake("idxscape_phei", [Row(IGSYC_10Y, d, ten, d, "idxscape_phei")
                                  for d in _days(last, 5)])


def dbn_source(ten=7.0, ten_last=date(2024, 12, 1), us_erp=0.04, crp=0.02,
               erp_last=date(2026, 9, 1), hurdle=None, crp_on=date(2026, 1, 1)) -> Fake:
    """dbnomics: the 10Y proxy, US ERP (fraction, monthly), IDN CRP (one snapshot), optional
    derived hurdle."""
    rows = [Row(PROXY_10Y, d, ten, None, "dbnomics") for d in _months(ten_last, 24)]
    if us_erp is not None:
        rows += [Row(US_ERP, d, us_erp, None, "dbnomics") for d in _months(erp_last, 12)]
    if crp is not None:
        rows.append(Row(IDN_CRP, crp_on, crp, None, "dbnomics"))
    if hurdle is not None:
        rows += [Row(HURDLE, d, hurdle, None, "dbnomics") for d in _months(erp_last, 12)]
    return Fake("dbnomics", rows)


def cpi_source(level=3.0, last=date(2026, 9, 1)) -> Fake:
    return Fake("bps-looker", [Row(CPI_YOY, d, level, date(2026, 10, 1), "bps-looker")
                               for d in _months(last, 24)])


def jci_source(last=date(2026, 9, 30), level=6071.14) -> Fake:
    return Fake("idx-method", [Row(JCI, d, level, last, "idx-method") for d in _days(last, 30)])


def flow(name: str, direction: int, value: float = 0.0) -> Signal:
    return Signal("IDN", "stocks", AS_OF, name, value, direction, "idxscape", f"{name} {value:+}")


def signals(idx: int | None = 1, ksei: int | None = 1, stale=()) -> IdnSignals:
    sigs = []
    if idx is not None:
        sigs.append(flow("idx_foreign_flow", idx, 3e12))
    if ksei is not None:
        sigs.append(flow("ksei_foreign_share", ksei, 0.4))
    sigs.append(flow("tic_us_equity_net", -1, -1577))
    sigs.append(Signal("IDN", "bonds", AS_OF, "sbn_non_resident_change", 5e12, 1, "idxscape"))
    return IdnSignals(AS_OF, tuple(sigs), tuple(stale), ("idxscape", "kseistat", "sec-edgar"))


def score(value=60.0, as_of=AS_OF) -> AssetScore:
    return AssetScore("IDN", "stocks", as_of, value, 0.89)


def overrides(delta=0.0) -> IdnOverrides:
    ov = Override("IDN", "stocks", AS_OF, delta, "test", ("bps-looker",),
                  ("satudatascape (missing)",))
    return IdnOverrides(AS_OF, (ov,), (), {"stocks": delta}, {})


def regime(state="neutral", dollar="flat") -> Regime:
    return Regime(AS_OF, state, dollar)


def run(**kw) -> IdnStocks:
    """Default: cheap market (EY 10%, real 10Y 4% → implied ERP 8% vs hurdle 6%), foreign
    buying, macro 60: an enter."""
    args = {"regime": regime(), "overrides": overrides(), "signals": signals(), "score": score(),
            "phei": phei_source(), "dbnomics": dbn_source(), "bps": cpi_source(),
            "idxmethod": jci_source(), "snapshots": FakeSnapshots(factors())}
    args.update(kw)
    return idn_stocks(AS_OF, **args)


# ---------------- the decision table ----------------


@pytest.mark.parametrize("valuation, flows, macro, call, stance", [
    (1, 1, 1, "enter", "overweight"),
    (1, 0, 0, "enter", "overweight"),
    (1, -1, 1, "hold", "neutral"),
    (1, 1, -1, "hold", "neutral"),
    (0, 1, 1, "hold", "neutral"),
    (-1, 1, 1, "hold", "neutral"),
    (-1, -1, 1, "reduce", "underweight"),
    (-1, 1, -1, "reduce", "underweight"),
    (None, 1, 1, "no_call", None),
    (1, None, 1, "no_call", None),
    (1, 1, None, "no_call", None),
])
def test_decide(valuation, flows, macro, call, stance):
    assert decide(valuation, flows, macro) == (call, stance)


# ---------------- market earnings yield ----------------


def test_market_earnings_yield_is_cap_weighted():
    caps = {"A": (3e14, 4.0), "B": (1e14, 12.0), "C": (1e14, None), "D": (None, 50.0),
            "E": (0.0, 30.0), "F": (1e14, -4.0)}
    f = {k: {"mktcap": m, "earnings_yield": ey} for k, (m, ey) in caps.items()}
    ey, n, cap = market_earnings_yield(f)
    assert ey == pytest.approx((3 * 4 + 12 - 4) / 5)
    assert n == 3 and cap == pytest.approx(5e14)


def test_market_earnings_yield_empty():
    assert market_earnings_yield({}) == (None, 0, 0.0)


# ---------------- the rule ----------------


def test_enter_when_cheap_flows_in_and_macro_supportive():
    s = run()
    assert (s.call, s.proposed_stance) == ("enter", "overweight")
    assert s.entry == {"style": "lump", "tranches": 1, "spacing_days": 0}
    assert s.earnings_yield == pytest.approx(10.0) and s.pe == pytest.approx(10.0)
    assert s.hurdle == pytest.approx(6.0)
    assert s.implied_erp == pytest.approx(10.0 + 2.0 - 4.0)
    assert s.ey_gap == pytest.approx(3.0)
    assert s.macro_score == pytest.approx(60.0)
    assert s.ten_year_source == "idxscape_phei"
    assert {sig.name for sig in s.signals} >= {"implied_erp_vs_hurdle", "ey_vs_sbn",
                                               "idx_foreign_flow", "ksei_foreign_share", "macro"}
    assert all(sig.asset == "stocks" for sig in s.signals)
    assert any(d.startswith("hurdle 6.00% (US ERP 4.00% 2026-09 + IDN CRP 2.00% 2026-01")
               for d in s.drivers)
    assert any("IGSYC curve" in d for d in s.drivers)


@pytest.mark.parametrize("reg, style", [(regime("risk_off"), "ladder"), (None, "ladder"),
                                        (regime("risk_on"), "lump")])
def test_entry_style_follows_regime(reg, style):
    s = run(regime=reg)
    assert s.call == "enter" and s.entry["style"] == style
    if reg is None:
        assert "regime (not given)" in s.stale_inputs


def test_reduce_when_rich_and_foreigners_sell():
    s = run(snapshots=FakeSnapshots(factors(ey=5.0)), signals=signals(idx=-1, ksei=-1))
    # implied 5 + 2 − 4 = 3% vs hurdle 6% → rich
    assert (s.call, s.proposed_stance) == ("reduce", "underweight")
    assert s.entry["style"] == "none"
    assert "foreign investors net selling IDX stocks" in s.risks


def test_hold_when_cheap_but_flows_out():
    s = run(signals=signals(idx=-1, ksei=-1))
    assert s.call == "hold"


def test_valuation_band_is_neutral():
    s = run(snapshots=FakeSnapshots(factors(ey=8.5)))  # implied 6.5 vs 6.0: inside ±1pt
    assert s.signal("implied_erp_vs_hurdle").direction == 0
    assert s.call == "hold"


def test_ksei_missing_still_calls_on_idx_flow():
    s = run(signals=signals(ksei=None))
    assert s.call == "enter"
    assert any("ksei_foreign_share" in x for x in s.stale_inputs)


def test_idx_flow_missing_is_no_call():
    s = run(signals=signals(idx=None))
    assert s.call == "no_call" and s.proposed_stance is None
    assert any("idx_foreign_flow" in x for x in s.stale_inputs)


def test_flows_net_out():
    s = run(signals=signals(idx=1, ksei=-1))
    assert s.signal("idx_foreign_flow").direction == 1
    assert s.call == "enter"  # net 0: stable counts as not selling


def test_signal_stale_inputs_for_bonds_are_dropped():
    sig = signals(stale=("idxscape SBN.TOTAL.non_resident (last 2026-09-30)",
                         "kseistat KSEI.sum.foreign_pct (last 2026-08-31)"))
    s = run(signals=sig)
    assert "kseistat KSEI.sum.foreign_pct (last 2026-08-31)" in s.stale_inputs
    assert not any("SBN" in x for x in s.stale_inputs)


# ---------------- macro ----------------


def test_macro_score_shifted_by_override():
    s = run(score=score(52.0), overrides=overrides(-5.0))
    assert s.macro_score == pytest.approx(47.0)
    assert s.signal("macro").direction == 0
    s = run(score=score(48.0), overrides=overrides(-5.0))
    assert s.signal("macro").direction == -1
    assert s.call == "hold"  # cheap, flows in, macro headwind
    assert "satudatascape (missing)" in s.stale_inputs


def test_macro_without_overrides_uses_layer1():
    s = run(overrides=None)
    assert s.macro_score == pytest.approx(60.0)
    assert "overrides (not given)" in s.stale_inputs
    assert s.call == "enter"


def test_macro_score_read_from_worldbankscape_when_not_given():
    s = run(score=None, worldbankscape=FakeWbs(score(58.0)))
    assert s.macro_score == pytest.approx(58.0)
    s = run(score=None, worldbankscape=FakeWbs(error="missing"))
    assert s.call == "no_call" and "worldbankscape (missing)" in s.stale_inputs
    s = run(score=None, worldbankscape=FakeWbs(None))
    assert s.call == "no_call" and any("worldbankscape IDN stocks" in x for x in s.stale_inputs)


def test_layer1_score_from_the_future_is_not_used():
    s = run(score=score(as_of=AS_OF + timedelta(days=1)))
    assert s.call == "no_call" and s.macro_score is None


# ---------------- 10Y: PHEI, proxy, staleness ----------------


def test_proxy_10y_too_old_makes_no_call():
    s = run(phei=Fake("idxscape_phei", error="missing"))
    assert s.ten_year_source == "dbnomics proxy"
    assert s.call == "no_call" and s.proposed_stance is None
    assert s.implied_erp is not None  # still reported
    assert "idxscape_phei (missing)" in s.stale_inputs
    assert any("idn.rate.long" in x and "2024-12-01" in x for x in s.stale_inputs)
    assert any("proxy" in d and "idn.rate.long" in d for d in s.drivers)
    assert any("too old to call" in sig.detail for sig in s.signals
               if sig.name == "implied_erp_vs_hurdle")


def test_fresh_proxy_calls():
    s = run(phei=Fake("idxscape_phei", error="missing"),
            dbnomics=dbn_source(ten_last=date(2026, 8, 1)))
    assert s.ten_year_source == "dbnomics proxy" and s.call == "enter"


def test_phei_without_10y_falls_back():
    s = run(phei=Fake("idxscape_phei", []))
    assert s.ten_year_source == "dbnomics proxy"
    assert any("idxscape_phei IGSYC.10 (no data)" in x for x in s.stale_inputs)


def test_sun_10y_stands_in_for_igsyc_before_the_proxy():
    """P101: no IGSYC 10Y (before 2026-10), DJPPR's SUN 10Y benchmark is next, not the proxy."""
    from assist.sources.idxscape_phei import SUN_10Y

    sun = Fake("idxscape_phei", [Row(SUN_10Y, d, 7.0, d, "idxscape_phei")
                                 for d in _days(date(2026, 10, 22), 5)])
    s = run(phei=sun)
    assert s.ten_year_source == "idxscape_sun" and s.call == "enter"
    assert s.ey_gap == pytest.approx(run().ey_gap)  # same 7.0 as the IGSYC default
    assert any("SUN 10Y benchmark" in d for d in s.drivers)
    assert not any("proxy" in d for d in s.drivers)
    assert {sig.source for sig in s.signals if sig.name == "ey_vs_sbn"} == {"idxscape_sun"}


def test_igsyc_wins_over_sun_on_the_same_day():
    from assist.sources.idxscape_phei import SUN_10Y

    both = phei_source(ten=7.0)
    both._rows += [Row(SUN_10Y, d, 9.0, d, "idxscape_phei") for d in _days(date(2026, 10, 22), 5)]
    assert run(phei=both).ten_year_source == "idxscape_phei"
    assert run(phei=both).ey_gap == pytest.approx(run().ey_gap)


def test_stale_phei_flagged():
    s = run(phei=phei_source(last=date(2026, 10, 9)))
    assert any(x.startswith("idxscape_phei IGSYC.10 (last") for x in s.stale_inputs)


def test_no_10y_at_all_is_no_call():
    no_proxy = Fake("dbnomics", [r for r in dbn_source()._rows if r.series_id != PROXY_10Y])
    s = run(phei=Fake("idxscape_phei", error="missing"), dbnomics=no_proxy)
    assert s.call == "no_call" and s.ten_year_source is None


def test_no_raw_phei_point_in_output():
    s = run(phei=phei_source(ten=7.1234))
    text = " ".join(s.drivers + s.risks + tuple(sig.detail for sig in s.signals))
    assert "7.12" not in text


# ---------------- hurdle ----------------


def test_hurdle_falls_back_to_derived_series():
    s = run(dbnomics=dbn_source(us_erp=None, crp=None, hurdle=0.065))
    assert s.hurdle == pytest.approx(6.5)
    assert any(HURDLE in d for d in s.drivers)


def test_no_hurdle_is_no_call():
    s = run(dbnomics=dbn_source(us_erp=None, crp=None))
    assert s.call == "no_call" and s.hurdle is None
    assert any(US_ERP in x for x in s.stale_inputs)


def test_hurdle_point_in_time():
    # the October ERP (dated 10-01) is not yet published on 10-05; CRP snapshot lags 6 weeks
    dbn = dbn_source(erp_last=date(2026, 10, 1), crp_on=date(2026, 9, 1), us_erp=0.04, crp=0.03)
    rows = dbn._rows + [Row(IDN_CRP, date(2026, 1, 1), 0.02, None, "dbnomics")]
    s = idn_stocks(date(2026, 10, 5), regime=regime(), overrides=overrides(), signals=signals(),
                   score=score(as_of=date(2026, 10, 5)), phei=phei_source(last=date(2026, 10, 2)),
                   dbnomics=Fake("dbnomics", rows), bps=cpi_source(), idxmethod=jci_source(),
                   snapshots=FakeSnapshots(factors(), on=date(2026, 10, 2)))
    assert s.hurdle == pytest.approx(6.0)  # 4% (Sep) + 2% (Jan snapshot; Sep not yet out)


# ---------------- earnings yield inputs ----------------


def test_snapshot_missing_is_no_call():
    s = run(snapshots=FakeSnapshots(None))
    assert s.call == "no_call" and s.earnings_yield is None
    assert any("idx-method" in x and "missing" in x for x in s.stale_inputs)


def test_stale_snapshot_flagged():
    s = run(snapshots=FakeSnapshots(factors(), on=date(2026, 10, 1)))
    assert "idx-method factors snapshot (last 2026-10-01)" in s.stale_inputs
    assert s.factors_date == date(2026, 10, 1)


def test_jci_frozen_flagged_but_does_not_block():
    s = run()
    assert "idx-method JKSE (stale, last 2026-09-30)" in s.stale_inputs
    assert s.call == "enter"
    s = run(idxmethod=Fake("idx-method", error="missing"))
    assert "idx-method (missing)" in s.stale_inputs and s.call == "enter"


def test_missing_stores_never_raise():
    s = run(phei=Fake("idxscape_phei", error="missing"), dbnomics=Fake("dbnomics", error="locked"),
            bps=Fake("bps-looker", error="missing"), idxmethod=Fake("idx-method", error="missing"),
            snapshots=FakeSnapshots(None, error="missing"))
    assert s.call == "no_call"
    assert {"idxscape_phei (missing)", "dbnomics (locked)", "bps-looker (missing)"} <= set(
        s.stale_inputs)


def test_cpi_from_dbnomics_when_bps_has_none():
    rows = dbn_source()._rows + [Row(DBN_CPI, d, 3.0, None, "dbnomics")
                                 for d in _months(date(2026, 8, 1), 12)]
    s = run(bps=Fake("bps-looker", []), dbnomics=Fake("dbnomics", rows))
    assert s.real_yield == pytest.approx(4.0)


# ---------------- snapshot reader ----------------


def _snap(root, d: str, ey: float):
    folder = root / "data" / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    with gzip.open(folder / f"{d}.json.gz", "wt") as f:
        json.dump({"date": d, "factors": factors(ey)}, f)


def test_snapshot_reader_point_in_time(tmp_path):
    _snap(tmp_path, "2026-10-01", 6.0)
    _snap(tmp_path, "2026-10-09", 7.0)
    snaps = FactorSnapshots(tmp_path)
    d, f = snaps.factors_on(date(2026, 10, 8))
    assert d == date(2026, 10, 1) and f["S0"]["earnings_yield"] == 6.0
    d, f = snaps.factors_on(AS_OF)
    assert d == date(2026, 10, 9)
    assert [(d, round(ey, 6)) for d, ey in snaps.history()] == [(date(2026, 10, 1), 6.0),
                                                                 (date(2026, 10, 9), 7.0)]
    with pytest.raises(SourceUnavailable):
        snaps.factors_on(date(2026, 9, 1))


def test_snapshot_reader_falls_back_to_factors_json(tmp_path):
    (tmp_path / "data").mkdir()
    p = tmp_path / "data" / "factors.json"
    p.write_text(json.dumps(factors(9.0)))
    ts = datetime(2026, 10, 12, 9, 54).timestamp()
    os.utime(p, (ts, ts))
    snaps = FactorSnapshots(tmp_path)
    d, f = snaps.factors_on(AS_OF)
    assert d == date(2026, 10, 12) and f["S0"]["earnings_yield"] == 9.0
    with pytest.raises(SourceUnavailable):
        snaps.factors_on(date(2026, 10, 11))  # written after as_of


def test_snapshot_reader_missing_and_corrupt(tmp_path):
    with pytest.raises(SourceUnavailable) as e:
        FactorSnapshots(tmp_path / "nope").factors_on(AS_OF)
    assert e.value.stale_input == "idx-method (missing)"
    folder = tmp_path / "data" / "snapshots"
    folder.mkdir(parents=True)
    (folder / "2026-10-01.json.gz").write_bytes(b"not gzip")
    with pytest.raises(SourceUnavailable) as e:
        FactorSnapshots(tmp_path).factors_on(AS_OF)
    assert e.value.stale_input == "idx-method (error)"


# ---------------- the placebo gate ----------------


def _verdict(passed: bool) -> Verdict:
    from assist.eval.placebo import Edge
    e = Edge(20, 20, 0.02, 0.0, 0.02, 3.0, True)
    return Verdict(passed, "passed" if passed else "t 1.2 below 2.0", e, e.t, 0.01, 0.1, (), 1,
                   1000, 20, 3, 3, 1, 2.0, 0.05)


def test_gated_stance():
    s = run()
    assert gated_stance("neutral", s, None) == (
        "neutral", "stocks rule proposes overweight; not applied: no placebo verdict")
    assert gated_stance("neutral", s, _verdict(False))[0] == "neutral"
    assert gated_stance("neutral", s, _verdict(True)) == (
        "overweight", "stocks rule applied: overweight (passed)")
    nc = run(signals=signals(idx=None))
    assert gated_stance("underweight", nc, _verdict(True)) == (
        "underweight", "stocks rule: no call (no_call)")


def test_gated_stance_applies_a_reduce_only_on_a_passed_reduce_verdict():
    # P74: the enter verdict tests enter vs hold + reduce; it says nothing about reduce
    import dataclasses
    red = dataclasses.replace(run(), call="reduce", proposed_stance="underweight")
    stance, note = gated_stance("neutral", red, _verdict(True))
    assert stance == "neutral"
    assert note == ("stocks rule proposes underweight; not applied: reduce side untested")
    stance, note = gated_stance("neutral", red, _verdict(True), reduce_verdict=_verdict(False))
    assert stance == "neutral" and "not applied: reduce side t 1.2 below 2.0" in note
    stance, note = gated_stance("neutral", red, None, reduce_verdict=_verdict(True))
    assert stance == "underweight" and note.startswith("stocks rule applied: underweight")


def test_gated_stance_never_applies_a_hold():
    import dataclasses
    hold = dataclasses.replace(run(), call="hold", proposed_stance="neutral")
    stance, note = gated_stance("overweight", hold, _verdict(True), reduce_verdict=_verdict(True))
    assert stance == "overweight" and "not applied: a hold claims no edge" in note


def test_an_enter_needs_the_enter_verdict_not_the_reduce_one():
    s = run()
    assert gated_stance("neutral", s, None, reduce_verdict=_verdict(True))[0] == "neutral"


def _prices(n=120, seed_moves=None):
    out, p = [], 100.0
    for i, d in enumerate(_months(date(2026, 9, 1), n)):
        out.append((d, p))
        p *= 1 + (seed_moves[i] if seed_moves else 0.0)
    return out


def test_rule_verdict_working_rule_passes():
    import random
    rng = random.Random(1)
    moves = [rng.gauss(0, 0.03) for _ in range(240)]
    calls, prices, p = {}, [], 100.0
    for i, d in enumerate(_months(date(2026, 9, 1), 240)):
        on = (i // 6) % 2 == 0
        calls[d] = "enter" if on else "hold"
        prices.append((d, p))
        p *= 1 + moves[i] + (0.03 if on else -0.01)  # enter months rise in the next month
    v = rule_verdict(calls, prices, horizon=1)
    assert v.passed, v.reason


def test_rule_verdict_noise_and_no_calls():
    import random
    rng = random.Random(2)
    moves = [rng.gauss(0, 0.03) for _ in range(240)]
    prices = _prices(240, moves)
    calls = {d: rng.choice(["enter", "hold", "reduce"]) for d, _ in prices}
    assert not rule_verdict(calls, prices, horizon=3).passed
    v = rule_verdict({d: "no_call" for d, _ in prices}, prices)
    assert not v.passed and "insufficient" in v.reason


def test_month_end_closes():
    pts = [(date(2026, 8, 28), 1.0), (date(2026, 8, 31), 2.0), (date(2026, 9, 30), 3.0),
           (date(2026, 9, 1), None)]
    rows = [Row(JCI, d, v, None, "x") for d, v in pts]
    assert month_end_closes(rows) == [(date(2026, 8, 31), 2.0), (date(2026, 9, 30), 3.0)]
