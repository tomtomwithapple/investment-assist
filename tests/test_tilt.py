"""PLAN S16 (P35): IDN macro sector tilt. Hand-set sensitivity table (config/sector_tilt.yaml),
drivers from layers 0-2 read point in time, quarterly placebo replay over factor_series. Data is
built in memory, plus tests/fixtures/tilt/sectors.json: two real names per IDX-IC sector from
idx-method's `data/sectors.json` (read 2026-10-27)."""

from __future__ import annotations

import json
import random
import shutil
from datetime import date, timedelta

import pytest
from helpers import FIXTURES

from assist.candidates import tilt
from assist.sources.base import Row, SourceUnavailable
from assist.sources.idxmethod_series import Bar, quarter_ends

D = date.fromisoformat
FIX = FIXTURES / "tilt"
SECTORS = json.loads((FIX / "sectors.json").read_text())


@pytest.fixture(scope="module")
def table():
    return tilt.load_table()


def monthly(sid: str, source: str, values: list[float], start: str = "2025-01-01",
            as_of: date | None = None) -> list[Row]:
    """One row a month from `start`, dated at the month start like the stores do."""
    out, d = [], D(start)
    for v in values:
        out.append(Row(sid, d, v, as_of, source))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def rows_by_label(rows: list[Row]) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {}
    for r in rows:
        out.setdefault(f"{r.source} {r.series_id}", []).append(r)
    return out


# ---------------- the table ----------------


def test_table_covers_every_idx_ic_sector(table):
    assert set(table.sectors) == set(SECTORS.values())
    assert len(table.sectors) == 11
    for sens in table.sectors.values():
        assert set(sens) <= set(table.drivers)
        assert all(-1 <= w <= 1 for w in sens.values())


def test_table_names_the_plan_drivers(table):
    assert set(table.drivers) == {"coal", "nickel", "palm_oil", "china", "bi_rate", "real_yield",
                                  "credit_gap", "usd_idr", "inflation", "consumer", "regime"}


def test_fingerprint_is_the_yaml_hash(tmp_path, table):
    assert len(table.fingerprint) == 64
    copy = tmp_path / "t.yaml"
    shutil.copy(tilt.CONFIG_PATH, copy)
    assert tilt.load_table(copy).fingerprint == table.fingerprint
    copy.write_text(copy.read_text() + "\n# edited\n")
    assert tilt.load_table(copy).fingerprint != table.fingerprint


# ---------------- mappings ----------------


@pytest.mark.parametrize(("t", "shift", "cap"), [
    (1.0, -2.0, 7), (-1.0, 2.0, 3), (0.0, 0.0, 5), (0.25, -0.5, 6), (0.2, -0.4, 5),
    (-0.25, 0.5, 4), (0.75, -1.5, 7),
])
def test_margin_shift_and_cap(table, t, shift, cap):
    assert tilt.margin_shift_pt(t, table) == pytest.approx(shift)
    assert tilt.sector_cap(t, table) == cap


def test_failed_verdict_applies_nothing(table):
    st = tilt.SectorTilt("Energi", 0.8, ("coal +1.00",), ())
    assert tilt.applied(st, passed=False, table=table) == (0.0, 5)
    assert tilt.applied(st, passed=True, table=table) == (pytest.approx(-1.6), 7)
    assert tilt.applied(None, passed=True, table=table) == (0.0, 5)


def test_direction_is_clipped():
    assert tilt.direction(62.5, {"center": 50, "scale": 25}) == pytest.approx(0.5)
    assert tilt.direction(200, {"center": 50, "scale": 25}) == 1.0
    assert tilt.direction(-9, {"center": 0, "scale": 3}) == -1.0


# ---------------- drivers, point in time ----------------


def macro_rows(as_of_rec: date | None = None) -> dict[str, list[Row]]:
    bi = monthly("WS_CBPOL.M.ID", "bisfetcher", [6.0] * 6 + [5.5, 5.25, 5.0, 4.75], as_of=as_of_rec)
    cpi = monthly("idn.cpi.yoy", "dbnomics", [2.0] * 6 + [2.0, 2.5, 3.0, 3.5])
    pmi = monthly("cn.pmi.mfg", "dbnomics", [50.0] * 9 + [51.0])
    cci = monthly("idn.cci", "dbnomics", [100.0] * 9 + [98.5])
    gap = [Row("WS_CREDIT_GAP.Q.ID.P.A.C", D("2024-10-01"), -2.5, as_of_rec, "bisfetcher")]
    jisdor = [Row("JISDOR", D("2025-07-01") + timedelta(days=i), 16000 + 8 * i, D("2025-07-01")
                  + timedelta(days=i), "idxscape") for i in range(0, 140)]
    return rows_by_label(bi + cpi + pmi + cci + gap + jisdor)


def test_drivers_read_point_in_time(table):
    rows = macro_rows()
    # 2025-10-01 rows are not known on 2025-10-20 (monthly lags), so September is the newest
    drv, stale = tilt.drivers_at(D("2025-10-20"), rows, table, regime="risk_off",
                                 commodities={"coal": 75.0})
    assert drv["bi_rate"].direction == pytest.approx(-1.0)  # Sep 5.00 vs Mar 6.00
    assert "5.00" in drv["bi_rate"].reading
    assert drv["inflation"].direction == pytest.approx(1.0)  # 3.0 vs 2.0 three months before
    assert drv["real_yield"].direction == pytest.approx((5.0 - 3.0 - 2.0) / 2.0)
    assert drv["china"].direction == pytest.approx(0.0)  # Oct's 51 not known yet
    assert drv["consumer"].direction == pytest.approx(0.0)
    assert drv["credit_gap"].direction == pytest.approx(-0.5)
    assert drv["regime"].direction == -1.0 and "risk_off" in drv["regime"].reading
    assert drv["coal"].direction == pytest.approx(1.0)
    assert "nickel" not in drv and "palm_oil" not in drv
    assert any("nickel" in s for s in stale)
    # JISDOR: % change over 3 months, scale 3%
    j = {r.date: r.value for r in rows["idxscape JISDOR"]}
    last = max(d for d in j if d <= D("2025-10-20"))
    base = max(d for d in j if d <= last - timedelta(days=91))
    assert drv["usd_idr"].direction == pytest.approx(min(1.0, 100 * (j[last] / j[base] - 1) / 3))


def test_drivers_later_see_new_rows(table):
    drv, _ = tilt.drivers_at(D("2025-12-01"), macro_rows(), table)
    assert drv["china"].direction == pytest.approx(0.5)
    assert drv["consumer"].direction == pytest.approx(-1.0)
    assert "regime" not in drv  # unknown regime is a missing driver, not neutral


def test_cpi_prefers_bps_looker(table):
    rows = macro_rows()
    rows.update(rows_by_label(monthly("BPS_CPI_YOY", "bps-looker", [1.0] * 10)))
    drv, _ = tilt.drivers_at(D("2025-12-01"), rows, table)
    assert drv["inflation"].direction == pytest.approx(0.0)
    assert "bps-looker" in drv["inflation"].reading


def test_usd_idr_falls_back_to_reer(table):
    rows = {k: v for k, v in macro_rows().items() if "JISDOR" not in k}
    rows.update(rows_by_label(monthly("WS_EER.M.R.B.ID", "bisfetcher",
                                      [100.0] * 6 + [100, 100, 100, 97.0])))
    drv, _ = tilt.drivers_at(D("2025-12-01"), rows, table)
    # REER down 3% = IDR weaker = +1
    assert drv["usd_idr"].direction == pytest.approx(1.0)
    assert "REER" in drv["usd_idr"].reading


def test_stale_driver_is_used_but_named(table):
    drv, stale = tilt.drivers_at(D("2027-06-30"), macro_rows(), table)
    assert "bi_rate" in drv
    assert any("WS_CBPOL.M.ID" in s and "stale" in s for s in stale)


# ---------------- tilts ----------------


def test_tilt_is_clipped_weighted_sum(table):
    drv = {n: tilt.Driver(n, d, f"{n} reading") for n, d in
           {"coal": 1.0, "china": 1.0, "usd_idr": 1.0, "regime": 1.0, "bi_rate": -1.0}.items()}
    tilts = {t.sector: t for t in tilt.sector_tilts(drv, table)}
    assert tilts["Energi"].tilt == pytest.approx(1.0)  # 0.5 + 0.2 + 0.2 + 0.1
    assert tilts["Teknologi"].tilt == pytest.approx(0.5 + 0.2)
    assert tilts["Keuangan"].tilt == pytest.approx(0.3 + 0.3)
    assert "real_yield" in " ".join(tilts["Keuangan"].stale)
    assert tilts["Energi"].stale == ()
    assert tilts["Energi"].drivers[0].startswith("coal")  # largest contribution first
    many = {n: tilt.Driver(n, 1.0, n) for n in table.drivers}
    assert all(-1 <= t.tilt <= 1 for t in tilt.sector_tilts(many, table))


# ---------------- sector returns ----------------


def bars(points: dict[str, float], price: float = 100.0) -> list[Bar]:
    return [Bar(D(d), price, m) for d, m in sorted(points.items())]


def test_sector_return_is_mktcap_weighted(table):
    q, q1 = D("2025-03-31"), D("2025-06-30")
    b = {f"A{i}": bars({"2025-03-28": 100.0, "2025-06-30": 110.0}) for i in range(4)}
    b["BIG"] = bars({"2025-03-31": 400.0, "2025-06-27": 360.0})
    b["OLD"] = bars({"2025-02-01": 100.0, "2025-06-30": 500.0})  # no bar near q: dropped
    secs = {s: "Energi" for s in b}
    ret = tilt.sector_returns(b, secs, q, q1, table)
    assert ret["Energi"] == pytest.approx((440 + 360) / 800 - 1)
    secs["A0"] = "Teknologi"
    assert "Energi" not in tilt.sector_returns(b, secs, q, q1, table)  # 4 names < min_names


# ---------------- replay ----------------


def synthetic(n_quarters: int = 30, signal: float = 0.08, seed: int = 1):
    """Two sectors whose tilts flip with the BI rate; the favoured one beats the other by
    `signal` the next quarter (0: pure noise)."""
    rng = random.Random(seed)
    qes = quarter_ends(D("2016-12-31"), D("2026-12-31"))[:n_quarters + 1]
    rates, d, hikes = [], D("2015-01-01"), []
    level = 6.0
    while d <= qes[-1]:
        if d.month in (1, 4, 7, 10):
            level += rng.choice((-1.0, 1.0))
        rates.append(Row("WS_CBPOL.M.ID", d, level, None, "bisfetcher"))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    rows = rows_by_label(rates)
    sens = {"Energi": {"bi_rate": 0.5}, "Keuangan": {"bi_rate": -0.5}}
    tb = tilt.load_table()
    tb = tilt.Table(tb.drivers, sens, tb.apply, {**tb.replay, "k": 1, "min_names": 1},
                    tb.fingerprint)
    for q in qes:
        drv, _ = tilt.drivers_at(q, rows, tb)
        hikes.append(drv["bi_rate"].direction if "bi_rate" in drv else 0.0)
    bs: dict[str, list[Bar]] = {"E1": [], "K1": []}
    caps = {"E1": 100.0, "K1": 100.0}
    for i, q in enumerate(qes):
        for s in bs:
            bs[s].append(Bar(q, 100.0, caps[s]))
        if i + 1 < len(qes):
            noise = rng.gauss(0, 0.02)
            caps["E1"] *= 1 + 0.01 + signal * hikes[i] + noise
            caps["K1"] *= 1 + 0.01 - signal * hikes[i] - noise
    return bs, {"E1": "Energi", "K1": "Keuangan"}, rows, tb


def test_replay_panel_uses_tilts_known_at_each_quarter():
    bs, secs, rows, tb = synthetic(8)
    panel = tilt.replay_panel(bs, secs, rows, {}, tb)
    assert len(panel) == 8
    q, recs = panel[0]
    drv, _ = tilt.drivers_at(q, rows, tb)
    by = {r["sector"]: r for r in recs}
    assert by["Energi"]["tilt"] == pytest.approx(0.5 * drv["bi_rate"].direction)
    assert set(by["Energi"]) == {"sector", "tilt", "ret"}


def test_replay_finds_a_real_edge_and_not_noise():
    bs, secs, rows, tb = synthetic(40, signal=0.08)
    v = tilt.evaluate_replay(tilt.replay_panel(bs, secs, rows, {}, tb), tb, n_shuffles=200,
                             n_controls=10)
    assert v.passed, v.reason
    bs, secs, rows, tb = synthetic(40, signal=0.0)
    v = tilt.evaluate_replay(tilt.replay_panel(bs, secs, rows, {}, tb), tb, n_shuffles=200,
                             n_controls=10)
    assert not v.passed


def test_observations_skip_flat_quarters(table):
    panel = [
        (D("2025-03-31"), [{"sector": s, "tilt": 0.0, "ret": 0.01} for s in "ABCDEFG"]),
        (D("2025-06-30"), [{"sector": s, "tilt": t, "ret": t / 10}
                           for s, t in zip("ABCDEFG", (0.9, 0.5, 0.3, 0, -0.2, -0.4, -0.8),
                                           strict=True)]),
    ]
    feats, rets, spreads = tilt.observations(panel, table)
    assert feats == [True, False]
    mean = sum((0.9, 0.5, 0.3, 0, -0.2, -0.4, -0.8)) / 70
    assert rets[0] == pytest.approx((0.09 + 0.05 + 0.03) / 3 - mean)
    assert spreads == [pytest.approx((0.09 + 0.05 + 0.03 + 0.02 + 0.04 + 0.08) / 3)]


# ---------------- run ----------------


class Down:
    name = "bisfetcher"

    def rows(self, *a, **k):
        raise SourceUnavailable("bisfetcher", "locked", "held by refresh")


def test_read_rows_turns_a_locked_store_into_stale():
    rows, stale = tilt.read_rows({"bisfetcher": Down()}, D("2016-01-01"), D("2026-10-27"))
    assert rows == {}
    assert any("bisfetcher" in s and "locked" in s for s in stale)


def test_run_reports_tilts_verdict_and_fingerprint():
    bs, secs, rows, tb = synthetic(40, signal=0.0)
    out = tilt.run(D("2026-10-27"), bs, secs, rows, {}, tb, commodities=None, n_shuffles=50,
                   n_controls=5)
    assert out["fingerprint"] == tb.fingerprint
    assert out["passed"] is False and out["blocked"]
    assert {t["sector"] for t in out["tilts"]} == {"Energi", "Keuangan"}
    for t in out["tilts"]:
        assert t["margin_shift_pt"] == 0.0 and t["cap"] == 5  # failed verdict: nothing applied
        assert t["raw_margin_shift_pt"] == pytest.approx(-2 * t["tilt"])
    assert any("worldbankscape" in s for s in out["stale_inputs"])
    assert out["quarters"] > 0
    assert out["disclaimer"]
