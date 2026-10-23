"""IDN overrides, layer 2 (P17, PLAN S7): fresh macro momentum (GDP, OECD CLI, CPI, trade, BI
rate) turned into one bounded shift of the layer-1 score per asset, clamped to ±10.

Most tests feed in-memory sources (tidy `Row`s, no store); the last ones run the real bps-looker,
bisfetcher and satudatascape adapters over their existing fixture stores."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest
from helpers import FIXTURES

from assist.layers.overrides import (
    CLI,
    DBN_CPI,
    WEIGHTS,
    IdnOverrides,
    apply,
    idn_overrides,
)
from assist.layers.types import MAX_OVERRIDE, AssetScore, Override
from assist.sources.base import Row, SourceUnavailable
from assist.sources.bisfetcher import BI_RATE_M, BisfetcherSource
from assist.sources.bpslooker import (
    CPI_YOY,
    EXPORTS,
    GDP_YOY,
    IMPORTS,
    TRADE_BALANCE,
    BpsLookerSource,
)
from assist.sources.satudatascape import SatudatascapeSource

AS_OF = date(2026, 10, 23)


class Fake:
    """A source holding rows in memory; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, rows or [], error
        self.calls: list[dict] = []

    def rows(self, series_ids=None, start=None, end=None, **kw):
        self.calls.append({"series_ids": series_ids, "start": start, "end": end, **kw})
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
    return sorted(out)


def _quarters(end: date, n: int) -> list[date]:
    return [d for d in _months(end, 3 * n) if d.month in (1, 4, 7, 10)]


def _series(sid: str, dates: list[date], values: list[float], src: str,
            recorded: date | None = date(2026, 10, 1)) -> list[Row]:
    return [Row(sid, d, v, recorded, src) for d, v in zip(dates, values, strict=True)]


def bps_rows(cpi=(3.0,) * 12, balance=(3000.0,) * 12, gdp=(5.0,) * 5,
             last_month=date(2026, 9, 1), last_quarter=date(2026, 4, 1)) -> list[Row]:
    """Monthly CPI y/y (%) and trade balance (US$ mn) ending on `last_month`, quarterly GDP y/y
    (%) ending on `last_quarter`; oldest first."""
    months = _months(last_month, len(cpi))
    rows = _series(CPI_YOY, months, list(cpi), "bps-looker")
    tmonths = _months(last_month - timedelta(days=31), len(balance))  # trade runs a month behind
    rows += _series(TRADE_BALANCE, tmonths, list(balance), "bps-looker")
    rows += _series(EXPORTS, tmonths, [20_000 + b for b in balance], "bps-looker")
    rows += _series(IMPORTS, tmonths, [20_000.0] * len(balance), "bps-looker")
    rows += _series(GDP_YOY, _quarters(last_quarter, len(gdp)), list(gdp), "bps-looker",
                    date(2026, 8, 5))
    return rows


def bis_rows(rates=(5.75,) * 12, last=date(2026, 9, 1)) -> list[Row]:
    return _series(BI_RATE_M, _months(last, len(rates)), list(rates), "bisfetcher",
                   date(2026, 10, 14))


def dbn_rows(cli=(100.0,) * 12, last=date(2026, 9, 1), cpi=None) -> list[Row]:
    rows = _series(CLI, _months(last, len(cli)), list(cli), "dbnomics", None)
    if cpi is not None:
        rows += _series(DBN_CPI, _months(last, len(cpi)), list(cpi), "dbnomics", None)
    return rows


def run(as_of=AS_OF, bps=None, bis=None, dbn=None, satu=None) -> IdnOverrides:
    return idn_overrides(
        as_of,
        bps=bps if bps is not None else Fake("bps-looker", bps_rows()),
        bisfetcher=bis if bis is not None else Fake("bisfetcher", bis_rows()),
        dbnomics=dbn if dbn is not None else Fake("dbnomics", dbn_rows()),
        satudatascape=satu if satu is not None else Fake("satudatascape", []),
    )


def deltas(out: IdnOverrides) -> dict[str, float]:
    return {o.asset: o.delta for o in out.overrides}


# ---------------- shape ----------------


def test_flat_inputs_give_zero_override_per_asset():
    out = run()
    assert isinstance(out, IdnOverrides)
    assert all(isinstance(o, Override) for o in out.overrides)
    assert {o.asset for o in out.overrides} == {"stocks", "bonds", "currency"}
    assert all(o.subject == "IDN" and o.as_of == AS_OF for o in out.overrides)
    assert deltas(out) == {"stocks": 0, "bonds": 0, "currency": 0}
    assert out.stale_inputs == ()
    assert set(out.sources) == {"bps-looker", "bisfetcher", "dbnomics"}
    assert {c.name for c in out.components} == set(WEIGHTS)


def test_every_override_names_its_sources_and_reason():
    for o in run().overrides:
        assert set(o.sources) == {"bps-looker", "bisfetcher", "dbnomics"}
        for name in WEIGHTS:
            assert name in o.reason


def test_weights_cover_the_three_assets():
    for name, w in WEIGHTS.items():
        assert set(w) == {"stocks", "bonds", "currency"}, name


# ---------------- components ----------------


def test_gdp_speeding_up_lifts_stocks_and_trims_bonds():
    out = run(bps=Fake("bps-looker", bps_rows(gdp=(5.0, 5.0, 5.0, 5.0, 5.6))))
    growth = out.component("growth")
    assert growth.direction == 1
    assert growth.value == pytest.approx(0.6)
    d = deltas(out)
    assert d["stocks"] == WEIGHTS["growth"]["stocks"] > 0
    assert d["bonds"] == WEIGHTS["growth"]["bonds"] < 0


def test_rising_cpi_hurts_bonds_most():
    cpi = (2.5,) * 9 + (2.8, 3.1, 3.4)
    out = run(bps=Fake("bps-looker", bps_rows(cpi=cpi)))
    infl = out.component("inflation")
    assert infl.direction == 1  # inflation rising
    assert infl.value == pytest.approx(0.9)  # 3.4 now vs 2.5 three months back
    d = deltas(out)
    assert d["bonds"] == WEIGHTS["inflation"]["bonds"] < d["stocks"] <= 0
    assert "3.40%" in infl.detail and "target" in infl.detail


def test_cpi_falls_back_to_dbnomics_when_bps_has_none():
    rows = [r for r in bps_rows() if r.series_id != CPI_YOY]
    cpi = (2.5,) * 9 + (2.8, 3.1, 3.4)
    out = run(bps=Fake("bps-looker", rows), dbn=Fake("dbnomics", dbn_rows(cpi=cpi)))
    infl = out.component("inflation")
    assert infl.direction == 1 and infl.source == "dbnomics"
    assert any(CPI_YOY in s for s in out.stale_inputs)


def test_trade_balance_widening_supports_the_rupiah():
    bal = (1000.0,) * 9 + (3000.0, 3500.0, 4000.0)
    out = run(bps=Fake("bps-looker", bps_rows(balance=bal)))
    trade = out.component("trade")
    assert trade.direction == 1
    assert trade.value == pytest.approx(10_500 - 3_000)  # last 3m sum vs the 3m before
    assert deltas(out)["currency"] == WEIGHTS["trade"]["currency"] > 0


def test_bi_cuts_help_bonds_and_stocks():
    rates = (6.0,) * 6 + (5.75, 5.5, 5.5, 5.25, 5.25, 5.25)
    out = run(bis=Fake("bisfetcher", bis_rows(rates=rates)))
    bi = out.component("bi_rate")
    assert bi.direction == -1
    assert bi.value == pytest.approx(-0.75)  # vs 6 months back
    d = deltas(out)
    assert d["bonds"] == -WEIGHTS["bi_rate"]["bonds"] > 0
    assert d["stocks"] == -WEIGHTS["bi_rate"]["stocks"] > 0


def test_cli_turning_down_cuts_stocks():
    cli = (100.0,) * 9 + (99.8, 99.5, 99.2)
    out = run(dbn=Fake("dbnomics", dbn_rows(cli=cli)))
    c = out.component("cli")
    assert c.direction == -1
    assert deltas(out)["stocks"] == -WEIGHTS["cli"]["stocks"] < 0


def test_inside_the_dead_band_is_zero():
    out = run(bps=Fake("bps-looker", bps_rows(gdp=(5.0, 5.0, 5.0, 5.0, 5.1))))
    assert out.component("growth").direction == 0


# ---------------- clamp ----------------


def test_everything_bullish_for_stocks_is_clamped_to_ten():
    bps = Fake("bps-looker", bps_rows(
        gdp=(4.0, 4.0, 4.0, 4.0, 6.0),
        cpi=(4.0,) * 9 + (3.5, 3.0, 2.5),
        balance=(0.0,) * 9 + (4000.0,) * 3,
    ))
    bis = Fake("bisfetcher", bis_rows(rates=(6.5,) * 6 + (5.0,) * 6))
    dbn = Fake("dbnomics", dbn_rows(cli=(98.0,) * 9 + (99.0, 100.0, 101.0)))
    out = run(bps=bps, bis=bis, dbn=dbn)
    for o in out.overrides:
        assert abs(o.delta) <= MAX_OVERRIDE
    raw = out.raw["stocks"]
    assert raw >= MAX_OVERRIDE
    assert deltas(out)["stocks"] == MAX_OVERRIDE
    if raw > MAX_OVERRIDE:
        assert "capped" in out.for_asset("stocks").reason


def test_apply_shifts_and_bounds_the_layer1_score():
    o = Override("IDN", "stocks", AS_OF, 8.0, "r", ("bps-looker",))
    s = AssetScore("IDN", "stocks", AS_OF, 95.0, 0.7)
    assert apply(s, o) == 100.0
    assert apply(50.0, o) == 58.0
    assert apply(5.0, Override("IDN", "stocks", AS_OF, -10.0, "r", ())) == 0.0
    assert apply(50.0, None) == 50.0


# ---------------- point in time, staleness ----------------


def test_rows_not_yet_published_are_ignored():
    # Sep CPI recorded 2026-10-01: on 09-25 only rows past their publication lag count.
    cpi = (2.5,) * 11 + (9.9,)
    rows = [r if r.series_id != CPI_YOY else r._replace(as_of=date(2026, 10, 1))
            for r in bps_rows(cpi=cpi)]
    out = run(as_of=date(2026, 9, 25), bps=Fake("bps-looker", rows))
    infl = out.component("inflation")
    assert infl.last.date == date(2026, 8, 1)
    assert infl.direction == 0


def test_dbnomics_rows_without_vintage_wait_for_their_lag():
    cli = (100.0,) * 11 + (90.0,)
    out = run(as_of=date(2026, 9, 20), dbn=Fake("dbnomics", dbn_rows(cli=cli)))
    assert out.component("cli").last.date < date(2026, 9, 1)


def test_missing_store_goes_to_stale_inputs_not_failure():
    out = run(bis=Fake("bisfetcher", error="missing"), satu=Fake("satudatascape", error="missing"))
    assert "bisfetcher (missing)" in out.stale_inputs
    assert "satudatascape (missing)" in out.stale_inputs
    assert out.component("bi_rate") is None
    assert "bisfetcher" not in out.sources
    for o in out.overrides:
        assert "bisfetcher (missing)" in o.stale_inputs
        assert "bisfetcher" not in o.sources


def test_every_store_missing_still_returns_zero_overrides():
    gone = {k: Fake(k, error="missing") for k in ("bps-looker", "bisfetcher", "dbnomics")}
    out = run(bps=gone["bps-looker"], bis=gone["bisfetcher"], dbn=gone["dbnomics"])
    assert deltas(out) == {"stocks": 0, "bonds": 0, "currency": 0}
    assert out.components == ()
    assert len(out.stale_inputs) == 3


def test_short_history_is_named_not_used():
    out = run(bps=Fake("bps-looker", bps_rows(gdp=(5.0,))))
    assert out.component("growth") is None
    assert any(GDP_YOY in s for s in out.stale_inputs)


def test_old_newest_point_still_counts_but_is_flagged():
    rows = bps_rows(last_quarter=date(2025, 10, 1), gdp=(5.0, 5.0, 5.0, 5.0, 5.6))
    out = run(bps=Fake("bps-looker", rows))
    assert out.component("growth").direction == 1
    assert any(GDP_YOY in s and "last 2025-10-01" in s for s in out.stale_inputs)


def test_reads_are_bounded_by_as_of():
    bps = Fake("bps-looker", bps_rows())
    run(bps=bps)
    assert all(c["end"] == AS_OF and c["start"] is not None for c in bps.calls)


def test_inputs_expose_latest_cpi_for_real_yield():
    out = run(bps=Fake("bps-looker", bps_rows(cpi=(3.0,) * 11 + (3.28,))))
    assert out.latest("cpi_yoy").value == pytest.approx(3.28)
    assert out.latest("bi_rate").value == pytest.approx(5.75)


# ---------------- real adapters over fixture stores ----------------


def _duck(path: Path, *sql: Path) -> Path:
    con = duckdb.connect(str(path))
    try:
        for f in sql:
            con.execute(f.read_text())
    finally:
        con.close()
    return path


def test_runs_over_the_real_adapters(tmp_path):
    bps = BpsLookerSource.from_duckdb(_duck(tmp_path / "bps.duckdb",
                                            FIXTURES / "bpslooker" / "schema.sql",
                                            FIXTURES / "bpslooker" / "data.sql"))
    bis = BisfetcherSource(_duck(tmp_path / "bis.duckdb", FIXTURES / "bisfetcher" / "schema.sql",
                                 FIXTURES / "bisfetcher" / "seed.sql"))
    satu = SatudatascapeSource(tmp_path / "absent" / "satudata.db")
    out = idn_overrides(AS_OF, bps=bps, bisfetcher=bis, dbnomics=Fake("dbnomics", dbn_rows()),
                        satudatascape=satu)
    assert "satudatascape (missing)" in out.stale_inputs
    assert {"bps-looker", "bisfetcher"} <= set(out.sources)
    assert out.latest("cpi_yoy").value == pytest.approx(3.28)
    assert out.latest("bi_rate").value == pytest.approx(5.75)
    assert all(abs(o.delta) <= MAX_OVERRIDE for o in out.overrides)
