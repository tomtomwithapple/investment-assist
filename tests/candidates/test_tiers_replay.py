"""Replay of the S31 top tier (P50): fundamentals lagged by `screens.LAG_DAYS` (no look-ahead),
today's membership flagged as survivorship, a planted signal that passes while its shuffled
control does not, a noise signal that fails, an insufficient sample, a byte-identical rerun, the
brief section, the journal record and the run hook that never fails. The universe is
tests/fixtures/tiers_replay/universe.json; bars, quarters and signals are generated from it
with a seeded rng. No store, no network."""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from assist import brief, journal, pipeline
from assist.candidates import tiers, tiers_replay
from assist.candidates.factors import derive
from assist.candidates.screens import LAG_DAYS
from assist.sources.idxmethod_series import Bar, Fundamentals

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tiers_replay"
DAY = date(2026, 10, 29)
CFG = tiers_replay.CONFIG


def _qends(first: date, n: int) -> list[date]:
    out, y, m = [], first.year, first.month
    for _ in range(n):
        out.append(date(y, m, 31 if m in (3, 12) else 30))
        m += 3
        if m > 12:
            y, m = y + 1, m - 12
    return out


def universe(planted: bool = True, quarters: int | None = None, seed: str = "p50") -> dict:
    """bars, quarters, members and signals from the fixture. At quarter end i the knowable
    period is two quarters back; its metrics all improve with a planted `g`, and (planted)
    the next quarter's return is beta × (g − 0.5) plus noise, else noise alone."""
    fx = json.loads((FIX / "universe.json").read_text())
    n = quarters or fx["quarters"]
    first = date.fromisoformat(fx["first_quarter"])
    qes = _qends(date(first.year - 1, 9, 30), n + 2)  # two quarters before the first
    rng = random.Random(seed)
    members, bars, funds, sigs = {}, {}, {}, {}
    for ind in fx["industries"]:
        for sym in ind["symbols"]:
            members[sym] = {"industry": ind["id"], "label": ind["label"],
                            "sector": ind["sector"]}
    for sym in sorted(members):
        price = fx["start_price"]
        bars[sym], funds[sym], sigs[sym] = [], [], {}
        for i in range(n):
            q, period = qes[i + 2], qes[i]
            g = rng.random()
            cap = price * fx["shares"]
            bars[sym].append(Bar(q, price, cap))
            pe, pbv = 4 + 30 * (1 - g), 1 + 2 * (1 - g)
            ni, eq = cap / pe, cap / pbv
            nd = eq * 0.8 * (1 - g)
            funds[sym].append(Fundamentals(
                period, period + timedelta(days=LAG_DAYS), cfo_ttm=ni * (0.5 + g), equity=eq,
                net_debt=nd, ni_ttm=ni, op_income_ttm=(cap + nd) / (4 + 16 * (1 - g)),
                roa=None, roce=None, total_assets=None, total_debt=eq * 0.5))
            sigs[sym][q] = {"days_traded_60": 60,
                            "med_value_60d": 1e8 if sym in fx["illiquid"] else 5e9,
                            "mom_12_1": rng.gauss(0, 0.2), "near_52w_high": rng.uniform(.5, 1)}
            noise = rng.gauss(0, fx["noise_sd"] if planted else 0.05)
            price *= 1 + (fx["planted_beta"] * (g - 0.5) if planted else 0.0) + noise
    return {"bars": bars, "quarters": funds, "members": members,
            "signals": lambda s, d: sigs.get(s, {}).get(d)}


def _run(u: dict, **kw) -> dict:
    return tiers_replay.run(u["bars"], u["quarters"], u["members"], u["signals"], day=DAY, **kw)


def _panel(u: dict) -> list[dict]:
    return tiers_replay.replay_panel(u["bars"], u["quarters"], u["members"], u["signals"])


@pytest.fixture(scope="module")
def planted() -> dict:
    return universe(planted=True)


@pytest.fixture(scope="module")
def planted_payload(planted) -> dict:
    return _run(planted)


# ---------------- point in time ----------------


def test_known_respects_lag_even_when_the_store_says_earlier():
    p = date(2020, 3, 31)
    f = Fundamentals(p, p, *([1.0] * 9))  # the store claims it was available at period end
    assert tiers_replay.known([f], p + timedelta(days=LAG_DAYS - 1)) == []
    assert tiers_replay.known([f], p + timedelta(days=LAG_DAYS)) == [f]


def test_no_look_ahead_a_quarter_not_yet_knowable_changes_nothing(planted):
    """At 2018-06-30 the knowable period is 2017-12-31 (+120d = 2018-04-30); 2018-03-31 is not
    (+120d = 2018-07-29). Wrecking 2018-03-31 changes nothing there; wrecking 2017-12-31 does."""
    q = date(2018, 6, 30)
    base = next(x for x in _panel(planted) if x["date"] == q)

    def wreck(period: date) -> dict:
        qs = {s: [f._replace(ni_ttm=-f.ni_ttm, equity=f.equity / 50) if f.period == period
                  else f for f in fs] for s, fs in planted["quarters"].items()}
        u = {**planted, "quarters": qs}
        return next(x for x in _panel(u) if x["date"] == q)

    assert wreck(date(2018, 3, 31)) == base
    assert wreck(date(2017, 12, 31)) != base


def test_signals_from_history_use_bars_up_to_the_date_only():
    rng = random.Random(7)
    day0 = date(2019, 1, 1)
    hist = {}
    for sym in ("AAAA", "BBBB"):
        px, bars = 1000.0, []
        for i in range(420):
            px *= 1 + rng.gauss(0, 0.01)
            bars.append({"date": (day0 + timedelta(days=i)).isoformat(), "close": px,
                         "value": 2e9, "volume": 1000})
        hist[sym] = bars
    at = tiers_replay.signals_from_history(hist)
    cut = day0 + timedelta(days=300)
    want = derive(hist, as_of=cut)["AAAA"]
    got = at("AAAA", cut)
    assert got["mom_12_1"] == want["mom_12_1"]
    assert got["near_52w_high"] == want["near_52w_high"]
    later = {s: [b for b in bs if b["date"] <= cut.isoformat()] for s, bs in hist.items()}
    assert tiers_replay.signals_from_history(later)("AAAA", cut) == got
    assert at("CCCC", cut) is None


def test_gates_and_reduced_metric_sets(planted):
    q = _panel(planted)[5]
    smi = q["industries"]["101"]
    assert "SMA0" not in {r["symbol"] for r in smi["recs"]}  # fails liquidity
    assert smi["n_gated"] == 9
    bank = q["industries"]["303"]["recs"][0]
    assert bank["pillars"]["health"] is None  # financial set: no health history
    assert q["industries"]["202"]["recs"][0]["pillars"]["health"] is not None


def test_tier_a_uses_the_live_rules():
    recs = [{"symbol": f"S{i}", "mktcap": 1.0, "composite": c, "pillars": {}, "fwd": 0.0}
            for i, c in enumerate([90, 80, 70, 65, 59, 50, 40, 30, 20, 10])]
    assert [r["symbol"] for r in tiers_replay.tier_a(recs, 10)] == ["S0", "S1"]
    low = [{**r, "composite": r["composite"] - 40} for r in recs]
    assert tiers_replay.tier_a(low, 10) == []  # nobody >= 60: no Tier A
    assert tiers.tier_size(10) == 2


# ---------------- verdicts ----------------


def test_planted_signal_passes(planted_payload):
    p = planted_payload
    assert p["status"] == "passed", p["verdict"]
    assert p["passed"] and not p["context_only"]
    assert p["quarters"] >= 10
    assert p["mean_excess"] > p["mean_placebo"]
    assert p["t"] >= 2 and p["p"] <= 0.05 and p["perm_p"] <= 0.05
    assert p["control_t"] < 2
    assert set(p["pillars"]) == set(tiers.PILLARS)  # diagnostics, one per pillar


def test_shuffled_control_of_the_planted_signal_fails(planted):
    v = tiers_replay.evaluate_panel(tiers_replay.shuffle_panel(_panel(planted)))
    assert v["status"] == "failed", v["verdict"]


def test_noise_signal_fails():
    p = _run(universe(planted=False, seed="noise"))
    assert p["status"] == "failed", p["verdict"]
    assert p["context_only"]


def test_insufficient_sample():
    p = _run(universe(quarters=6))
    assert p["status"] == "insufficient"
    assert "insufficient sample" in p["verdict"] and not p["passed"]


def test_membership_flag_and_fingerprint(planted_payload):
    p = planted_payload
    assert any(f.startswith("survivorship") for f in p["flags"])
    assert p["fingerprint"] == tiers_replay.fingerprint()
    assert p["tier_fingerprint"] == tiers.fingerprint()
    assert p["weights"] == tiers.CONFIG["weights"]
    assert p["config"]["replay"]["lag_days"] == LAG_DAYS


def test_deterministic_rerun(planted, planted_payload):
    a = json.dumps(planted_payload, sort_keys=True)
    assert json.dumps(_run(planted), sort_keys=True) == a


def test_blocked_payload_and_live_without_membership(tmp_path):
    from assist.sources.idxmethod_series import IdxMethodSeries

    p = tiers_replay.run_live(DAY, tmp_path, series=IdxMethodSeries(tmp_path))
    assert p["status"] == "blocked" and p["context_only"]
    assert "membership" in p["verdict"]


# ---------------- dated membership (idx-method industry_membership; user, 2026-11-09) -------


def _store(root: Path, rows: list[tuple]) -> Path:
    db = root / "store" / "data" / "stockbiter.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE industry_membership (date TEXT NOT NULL, symbol TEXT NOT NULL,
        sector_id INTEGER, sector TEXT, sub_sector_id INTEGER, sub_sector TEXT,
        industry_id INTEGER, industry TEXT, sub_industry_id INTEGER, sub_industry TEXT,
        peers TEXT, PRIMARY KEY (date, symbol))""")
    con.executemany("insert into industry_membership values (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return db


def _row(d: str, sym: str, sub_id: int, sub: str, sector: str) -> tuple:
    return (d, sym, 9, sector, sub_id, sub, 1, "ind", 2, "subind", "[]")


def test_membership_at_takes_the_latest_snapshot_on_or_before_else_the_first():
    s1, s2 = {"A": {"industry": "1"}}, {"A": {"industry": "2"}}
    snaps = [(date(2020, 1, 1), s1), (date(2021, 1, 1), s2)]
    assert tiers_replay.membership_at(snaps, date(2019, 12, 31)) == (s1, True)  # back-filled
    assert tiers_replay.membership_at(snaps, date(2020, 6, 30)) == (s1, False)
    assert tiers_replay.membership_at(snaps, date(2021, 1, 1)) == (s2, False)


def test_one_later_snapshot_is_todays_membership_back_filled(planted, planted_payload):
    snaps = [(date(2026, 11, 6), planted["members"])]
    assert tiers_replay.replay_panel(planted["bars"], planted["quarters"], snaps,
                                     planted["signals"]) == _panel(planted)
    p = _run({**planted, "members": snaps})
    for k in ("status", "t", "p", "perm_p", "control_t", "quarters", "picks"):
        assert p[k] == planted_payload[k]
    m = p["membership"]
    assert m["snapshots"] == 1 and m["first_snapshot"] == "2026-11-06"
    assert m["quarters_back_filled"] == p["quarters"] and m["quarters_point_in_time"] == 0
    flag = next(f for f in p["flags"] if f.startswith("survivorship"))
    assert "industry_membership" in flag and "2026-11-06" in flag and "back-filled" in flag


def test_dated_membership_moves_a_name_from_its_snapshot_date(planted):
    base = _panel(planted)
    early, late = base[3], base[12]
    sym = next(r["symbol"] for r in early["industries"]["101"]["recs"]
               if r["symbol"] in {x["symbol"] for x in late["industries"]["101"]["recs"]})
    moved = {**planted["members"], sym: {**planted["members"][sym], "industry": "202"}}
    gone = {s: m for s, m in planted["members"].items() if s != sym}
    for later, where in ((moved, "202"), (gone, None)):
        snaps = [(early["date"] - timedelta(days=1), planted["members"]),
                 (late["date"] - timedelta(days=1), later)]
        panel = tiers_replay.replay_panel(planted["bars"], planted["quarters"], snaps,
                                          planted["signals"])
        q3 = next(q for q in panel if q["date"] == early["date"])
        q12 = next(q for q in panel if q["date"] == late["date"])
        assert sym in {r["symbol"] for r in q3["industries"]["101"]["recs"]}
        assert sym not in {r["symbol"] for r in q12["industries"]["101"]["recs"]}
        in_202 = sym in {r["symbol"] for r in q12["industries"]["202"]["recs"]}
        assert in_202 == (where == "202")


def test_run_live_reads_industry_membership_not_the_s30_file(tmp_path):
    from assist.sources.idxmethod_series import IdxMethodSeries

    _store(tmp_path, [_row("2026-11-06", "BBCA", 31, "Bank", "Keuangan"),
                      _row("2026-11-06", "ANTM", 11, "Barang Baku", "Barang Baku")])
    snaps = tiers_replay.membership_snapshots(IdxMethodSeries(tmp_path))
    assert snaps == [(date(2026, 11, 6), {
        "ANTM": {"industry": "11", "label": "Barang Baku", "sector": "Barang Baku"},
        "BBCA": {"industry": "31", "label": "Bank", "sector": "Keuangan"}})]
    out = tmp_path / "out"  # no out/industries/IDN.json at all
    p = tiers_replay.run_live(DAY, out, series=IdxMethodSeries(tmp_path))
    assert p["status"] == "blocked" and "factor_series" in p["verdict"]  # got past membership


def test_run_live_blocked_without_industry_membership(tmp_path):
    from assist.sources.idxmethod_series import IdxMethodSeries

    p = tiers_replay.run_live(DAY, tmp_path, series=IdxMethodSeries(tmp_path))
    assert p["status"] == "blocked" and "industry_membership" in p["verdict"]
    _store(tmp_path, [])
    p = tiers_replay.run_live(DAY, tmp_path, series=IdxMethodSeries(tmp_path))
    assert p["status"] == "blocked" and "industry_membership" in p["verdict"]


# ---------------- outputs ----------------


def test_write_load_and_brief_section(tmp_path, planted_payload):
    out = tmp_path / "out"
    path = tiers_replay.write(planted_payload, out)
    assert path == out / "industries" / "IDN.replay.json"
    assert tiers_replay.load(out)["status"] == "passed"
    md = brief.build_brief(out, tmp_path / "snap")
    assert "## Top tier replay" in md
    body = md.split("## Top tier replay", 1)[1].split("\n## ", 1)[0]
    assert "**passed**" in body and "perm p" in body and "control t" in body
    assert "survivorship" in body and "Replay model: `sha256:" in body
    assert "context only" in body


def test_brief_without_replay_has_no_section(tmp_path):
    assert "Top tier replay" not in brief.build_brief(tmp_path / "out", tmp_path / "snap")


def test_brief_lines_for_insufficient():
    lines = brief.tier_replay_lines(tiers_replay.blocked(DAY, "factor_series unavailable"))
    assert "**blocked**" in lines[0]
    assert any("Context only" in x for x in lines)


def test_journal_record_and_hook_never_fail(tmp_path, planted_payload):
    out = tmp_path / "out"
    path, stale = pipeline.write_tier_replay(DAY, lambda d, o: planted_payload, out)
    assert path is not None and stale == []
    j = journal.Journal(tmp_path / "journal")
    fp = j.register_model()
    pipeline._journal_tier_replay(j, path, fp, "run-1")
    rec = [r for r in j.read() if r["kind"] == "tier_replay"][-1]
    assert rec["outputs"]["status"] == "passed"
    assert rec["outputs"]["moves_stance"] is False
    assert rec["inputs"]["fingerprint"] == tiers_replay.fingerprint()

    def boom(d, o):
        raise RuntimeError("store gone")

    path, stale = pipeline.write_tier_replay(DAY, boom, out)
    assert path is None and stale[0].startswith("tier replay failed: RuntimeError")
    pipeline._journal_tier_replay(j, tmp_path / "missing.json", fp, None)  # no raise
