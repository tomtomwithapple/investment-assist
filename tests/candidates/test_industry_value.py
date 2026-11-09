"""Industry-relative value screen, IDN (PLAN S15).

The synthetic market: 62 names over five years of month ends, in three peer groups (a coal
sub-industry of 30, an oil sub-industry of 5 that falls back to its sector, and 25 banks), plus
a delisted name with no sector and one with only a `factor_universe` sector. Each name's book
and ROE are fixed, and its PBV is exp(3 × ROE + u), so its fair multiple rises with ROE and u is
the mispricing. With u drawn fresh each month (`planted`), a cheap name (u < 0) reverts and
earns more next month; with u a random walk (`flat`), next month's return is independent of it.
"""

from __future__ import annotations

import math
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from assist.candidates import industry_value as IV
from assist.candidates import screens as S
from assist.layers.candidates import assemble
from assist.sources.idxmethod_series import IdxMethodSeries
from assist.sources.idxmethod_stocks import IdxMethodStocks

FAST = {"n_shuffles": 200, "n_controls": 5}
START = IV.month_index(date(2019, 1, 31))
N_MONTHS = 60
SHARES = 1e9
BOOK = 5e12
SNAPSHOT = date(2024, 2, 15)  # after the last month end: every replayed month is back-filled


def good_row(**kw) -> dict:
    row = {"free_float": 40.0, "med_value_60d": 1e10, "price": 1000.0, "vol_1y": 0.3,
           "days_traded_60": 60, "piotroski": 7, "altman_z": 3.0, "cfo_ttm": 1e9, "der": 0.5,
           "interest_cov": 5.0, "pbv": 2.0}
    return {**row, **kw}


def universe() -> dict[str, dict]:
    """sym → {roe, sector, sub_id, sub, industry} (membership), or sector only / nothing."""
    out = {}
    for i in range(30):
        out[f"C{i:02d}"] = {"roe": 0.05 + 0.15 * i / 29, "sector": "Energi", "sub_id": 158,
                            "sub": "Batu Bara", "industry": "Batu Bara"}
    for i in range(5):
        out[f"O{i:02d}"] = {"roe": 0.06 + 0.02 * i, "sector": "Energi", "sub_id": 157,
                            "sub": "Minyak", "industry": "Minyak & Gas"}
    for i in range(25):
        out[f"B{i:02d}"] = {"roe": 0.08 + 0.12 * i / 24, "sector": "Keuangan", "sub_id": 170,
                            "sub": "Bank", "industry": "Bank"}
    out["SOLO"] = {"roe": 0.1, "sector": "Energi", "sub_id": None, "membership": False}
    out["DEAD"] = {"roe": 0.1, "sector": None, "sub_id": None, "membership": False}
    return out


def mispricing(kind: str, seed: int = 11) -> dict[str, list[float]]:
    rng = random.Random(seed)
    out = {}
    for sym in universe():
        if kind == "planted":
            out[sym] = [rng.gauss(0, 0.15) for _ in range(N_MONTHS)]
        else:
            u, xs = 0.0, []
            for _ in range(N_MONTHS):
                u += rng.gauss(0, 0.08)
                xs.append(u)
            out[sym] = xs
    return out


def write_store(root: Path, kind: str = "planted", *, one_off: str | None = None) -> Path:
    """An idx-method root with `store/data/stockbiter.db` holding the synthetic market. Rows
    sit on days 20 and 24 and on each month's last day; `one_off` gets a 5× TTM earnings spike
    in its last month."""
    u = mispricing(kind)
    db = root / "store" / "data" / "stockbiter.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE factor_series (freq TEXT NOT NULL, symbol TEXT NOT NULL, item TEXT NOT NULL,
            date TEXT NOT NULL, value, PRIMARY KEY (freq, symbol, item, date));
        CREATE TABLE factor_universe (symbol TEXT PRIMARY KEY, name TEXT, sector TEXT,
            status TEXT, delisted INTEGER);
        CREATE TABLE industry_membership (date TEXT NOT NULL, symbol TEXT NOT NULL,
            sector_id INTEGER, sector TEXT, sub_sector_id INTEGER, sub_sector TEXT,
            industry_id INTEGER, industry TEXT, sub_industry_id INTEGER, sub_industry TEXT,
            peers TEXT, PRIMARY KEY (date, symbol));
    """)
    rows = []
    for sym, spec in universe().items():
        con.execute("insert into factor_universe values (?, ?, ?, ?, ?)",
                    (sym, sym, spec["sector"], "STATUS_ACTIVE", int(sym == "DEAD")))
        if spec.get("membership", True):
            con.execute("insert into industry_membership values (?,?,?,?,?,?,?,?,?,?,?)",
                        (SNAPSHOT.isoformat(), sym, 1, spec["sector"], 1, None, 1,
                         spec["industry"], spec["sub_id"], spec["sub"], "[]"))
        roe = spec["roe"]
        for t in range(N_MONTHS):
            k = START + t
            end = IV.month_end(k)
            pbv = math.exp(3 * roe + u[sym][t])
            cap = pbv * BOOK
            e = roe * BOOK
            if one_off == sym and t == N_MONTHS - 1:
                e *= 5
            for d in (end.replace(day=20), end.replace(day=24), end):
                for item, v in (("price", cap / SHARES), ("mktcap", cap), ("pe", cap / e),
                                ("pbv", pbv)):
                    rows.append(("daily", sym, item, d.isoformat(), v))
    con.executemany("insert into factor_series values (?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()
    return root


LAST = IV.month_end(START + N_MONTHS - 1)


def data_for(tmp_path, kind="planted", **kw) -> IV.IndustryData:
    root = write_store(tmp_path, kind, **kw)
    return IV.load(IdxMethodSeries(root), LAST)


def table_for(data: IV.IndustryData) -> dict[str, dict]:
    return {s: good_row(price=r.price) for s, r in data.live.items()}


# ---------------- pieces ----------------


def test_month_calendar():
    assert IV.month_end(IV.month_index(date(2024, 2, 3))) == date(2024, 2, 29)
    assert IV.month_end(IV.month_index(date(2023, 12, 1))) == date(2023, 12, 31)


def test_ols_recovers_a_line_and_refuses_a_constant_regressor():
    xs = [[x] for x in range(10)]
    beta = IV.ols([1 + 2 * x[0] for x in xs], xs)
    assert beta == pytest.approx([1, 2])
    two = [[x, (x * 7) % 5] for x in range(12)]
    beta = IV.ols([0.5 - x + 3 * z for x, z in two], two)
    assert beta == pytest.approx([0.5, -1, 3])
    assert IV.ols([1.0] * 10, [[1.0]] * 10) is None


def test_fit_residuals_fall_back_to_the_peer_median_below_min_fit():
    obs = {f"S{i}": (math.log(1 + i), [0.1 * i]) for i in range(5)}
    gaps, method = IV.fit_residuals(obs, min_fit=8)
    assert method == "median"
    assert gaps["S2"] == pytest.approx(0.0)  # the median name
    assert gaps["S0"] < 0 < gaps["S4"]
    obs = {f"S{i}": (2 * 0.1 * i + (0.3 if i == 4 else 0.0), [0.1 * i]) for i in range(10)}
    gaps, method = IV.fit_residuals(obs, min_fit=8)
    assert method == "fit"
    assert max(gaps, key=gaps.get) == "S4"  # rich vs what its ROE justifies


def test_peer_groups_use_the_sub_industry_with_eight_names_else_the_sector():
    big = {f"C{i}": IV.Member("Energi", 158) for i in range(8)}
    small = {f"O{i}": IV.Member("Energi", 157) for i in range(7)}
    groups = IV.peer_groups({**big, **small})
    assert groups["C0"] == ("sub:158", "sub_industry")
    assert groups["O0"] == ("sec:Energi", "sector")


def test_membership_back_filled_before_the_first_snapshot_and_sector_fallback(tmp_path):
    data = data_for(tmp_path)
    m = IV.member_at(data, "C00", date(2020, 1, 31))
    assert m.source == "back-filled" and m.sub_industry_id == 158
    assert IV.member_at(data, "C00", SNAPSHOT).source == "recorded"
    assert IV.member_at(data, "SOLO", SNAPSHOT) == IV.Member("Energi", source="sector only")
    assert IV.member_at(data, "DEAD", SNAPSHOT) is None


# ---------------- the cross-section ----------------


def test_cheap_vs_justified_ranks_first_within_its_peers(tmp_path):
    data = data_for(tmp_path)
    k = START + 40
    d = IV.month_end(k)
    rows = {s: m[k] for s, m in data.months.items() if k in m}
    recs, info = IV.cross_section(data, d, rows)
    assert info["no peer group"] == 1  # DEAD
    assert info["back-filled"] == 60 and info["sector only"] == 1
    u = mispricing("planted")
    coal = sorted((r for r in recs.values() if r["group"] == "sub:158"),
                  key=lambda r: r["pbv_gap"])
    # the PBV gap is the mispricing u, not ROE: the fit removes what ROE justifies
    gaps = [r["pbv_gap"] for r in coal]
    us = [u[r["symbol"]][40] for r in coal]
    assert corr(gaps, us) > 0.95
    assert abs(corr(gaps, [r["roe"] for r in coal])) < 0.2
    assert gaps[0] < 0 < gaps[-1]
    assert all(r["pbv_method"] == "fit" for r in coal)
    # growth and payout do not vary here, so the PE leg falls back to the peer median
    assert {r["pe_method"] for r in coal} == {"median"}
    # oil's 5 names plus SOLO rank within the sector, banks on their own sub-industry
    assert recs["O00"]["group"] == "sec:Energi" and recs["SOLO"]["level"] == "sector"
    assert recs["B00"]["group"] == "sub:170" and recs["B00"]["financial"]
    assert "ev_gap" not in recs["B00"]
    best = max(coal, key=lambda r: r["score"])
    assert u[best["symbol"]][40] < 0
    assert all(r["score"] is not None for r in recs.values())


def test_a_name_needs_own_history_to_score(tmp_path):
    data = data_for(tmp_path)
    k = START + 10  # under CONFIG["min_own"] months of history
    rows = {s: m[k] for s, m in data.months.items() if k in m}
    recs, _ = IV.cross_section(data, IV.month_end(k), rows)
    assert all(r["score"] is None and r["unscored"] == "no own history" for r in recs.values())


def test_a_one_off_gain_does_not_rank_first_on_pe(tmp_path):
    data = data_for(tmp_path, one_off="C10")
    r = data.live["C10"]
    assert r.pe < 0.3 * data.months["C10"][START + N_MONTHS - 2].pe  # TTM PE collapsed
    recs, _ = IV.cross_section(data, LAST, data.live)
    c10 = recs["C10"]
    # normalised: the lower of TTM and the median of the 3 TTM years, i.e. the usual earnings
    e = 0.05 + 0.15 * 10 / 29
    assert c10["pe_norm"] == pytest.approx(r.mktcap / (e * BOOK))
    coal = [x for x in recs.values() if x["group"] == "sub:158"]
    assert min(coal, key=lambda x: x["pe_gap"])["symbol"] != "C10"


def test_ev_leg_fits_ev_ebitda_on_roic(tmp_path):
    data = data_for(tmp_path)
    k = START + 40
    d = IV.month_end(k)
    rows = {}
    for s, m in data.months.items():
        if k in m:
            roic = 0.05 + 0.01 * int(s[1:]) if s[1:].isdigit() else 0.1
            data.roce[s] = [(d - timedelta(days=5), 100 * roic)]
            ev = math.exp(1 + 4 * roic + (0.4 if s == "C05" else 0.0))
            rows[s] = m[k]._replace(ev_ebitda=ev)
    recs, _ = IV.cross_section(data, d, rows)
    coal = [r for r in recs.values() if r["group"] == "sub:158"]
    assert all(r["ev_method"] == "fit" for r in coal)
    assert max(coal, key=lambda r: r["ev_gap"])["symbol"] == "C05"
    assert 0.3 < recs["C05"]["ev_gap"] < 0.4


# ---------------- data ----------------


def test_load_reads_month_ends_and_skips_a_lone_echo(tmp_path):
    root = write_store(tmp_path)
    con = sqlite3.connect(root / "store" / "data" / "stockbiter.db")
    echo = (IV.month_end(START + N_MONTHS) + timedelta(days=0)).isoformat()
    for item, v in (("price", 1.0), ("mktcap", 2e12), ("pe", 5), ("pbv", 1)):
        con.execute("insert into factor_series values ('daily', 'DEAD', ?, ?, ?)",
                    (item, echo, v))
    con.commit()
    con.close()
    data = IV.load(IdxMethodSeries(root))
    assert START + N_MONTHS not in data.months["DEAD"]
    assert len(data.months["C00"]) == N_MONTHS
    assert data.months["C00"][START].date == IV.month_end(START)
    assert data.snapshots[0][0] == SNAPSHOT
    assert any("fundamentals" in s for s in data.stale)  # no shares: dividends as paid


def test_load_on_a_missing_store_is_a_stale_input(tmp_path):
    data = IV.load(IdxMethodSeries(tmp_path / "nope"))
    assert data.months == {} and data.stale == [
        "idx-method factor_series / industry_membership (missing)"]


# ---------------- replay and verdict ----------------


def test_replay_reads_nothing_after_as_of(tmp_path):
    data = data_for(tmp_path)
    cut = IV.month_end(START + 40)
    panel, _ = IV.replay_panel(data, cut)
    assert panel[-1][0] == IV.month_end(START + 39)  # its next month end is the cut
    assert all(d < cut for d, _ in panel)


def test_planted_mispricing_passes_and_names_candidates(tmp_path):
    data = data_for(tmp_path)
    res = IV.run(data, table_for(data), as_of=LAST, min_pool=30, **FAST)
    assert res["screen"] == "industry_value"
    assert res["passed"], res["blocked"]
    assert res["months"] >= 30
    assert res["window"][0] >= IV.month_end(START + IV.CONFIG["min_own"]).isoformat()
    assert res["spread_mean"] > 0 and abs(res["verdict"]["control_t"]) < 2
    picks = res["candidates"]
    assert picks and len({c["sector"] for c in picks} - {"Energi", "Keuangan"}) == 0
    assert sum(c["sector"] == "Energi" for c in picks) <= S.MAX_PER_SECTOR
    u = mispricing("planted")
    assert fmean_u(u, picks) < 0  # the names named are the cheap ones
    assert {"symbol", "score", "sector", "pbv_gap", "own_pbv", "score_pct", "price",
            "peer_level", "membership"} <= set(picks[0])
    assert any(f.startswith("membership") for f in res["flags"])
    assert res["replay"]["back-filled"] > 0


def corr(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    return cov / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))


def fmean_u(u, picks):
    return sum(u[c["symbol"]][-1] for c in picks) / len(picks)


def test_flat_market_fails_and_names_no_one(tmp_path):
    data = data_for(tmp_path, "flat")
    res = IV.run(data, table_for(data), as_of=LAST, min_pool=30, **FAST)
    assert not res["passed"] and res["blocked"]
    assert res["candidates"] == []
    assert res["n_ranked"] > 0  # it still ranks and reports


def test_quality_floor_and_gates_decide_who_may_be_named(tmp_path):
    data = data_for(tmp_path)
    table = table_for(data)
    table["C00"]["piotroski"] = 2
    table["C01"]["free_float"] = 5.0
    del table["C02"]
    res = IV.run(data, table, as_of=LAST, flagged={"C03"}, min_pool=30, **FAST)
    named = {c["symbol"] for c in res["candidates"]}
    assert not named & {"C00", "C01", "C02", "C03"}
    rj = res["rejects"]
    assert rj["F-score"] == 1 and rj["free float"] == 1 and rj["flagged board"] == 1
    assert rj["not in screener"] == 1


def test_run_is_deterministic(tmp_path):
    data = data_for(tmp_path)
    a = IV.run(data, table_for(data), as_of=LAST, min_pool=30, **FAST)
    b = IV.run(data, table_for(data), as_of=LAST, min_pool=30, **FAST)
    assert a == b


# ---------------- through screens.run_screens and layer 4 ----------------


def test_run_screens_carries_the_fourth_screen(tmp_path):
    from test_screens import spread_drift, write_root

    root = write_store(write_root(tmp_path, spread_drift()), "flat")
    out = S.run_screens(IdxMethodStocks(root), **FAST)
    iv = out["screens"]["industry_value"]
    assert iv["screen"] == "industry_value" and iv["month_ends"] > 0
    assert not iv["passed"] and iv["candidates"] == []
    assert set(out["screens"]) == {*S.SCREENS, "industry_value"}


def test_run_screens_without_the_store_blocks_the_fourth_screen(tmp_path):
    from test_screens import spread_drift, write_root

    out = S.run_screens(IdxMethodStocks(write_root(tmp_path, spread_drift())), **FAST)
    iv = out["screens"]["industry_value"]
    assert not iv["passed"] and iv["candidates"] == [] and iv["months"] == 0
    assert "idx-method factor_series / industry_membership (missing)" in out["stale_inputs"]


def test_layer_4_journals_the_flags_and_names_no_one_when_failed(tmp_path):
    data = data_for(tmp_path, "flat")
    res = IV.run(data, table_for(data), as_of=LAST, min_pool=30, **FAST)
    out = assemble({"as_of": LAST, "screens": {"industry_value": res}}, {})
    (summ,) = out.screens
    assert summ.name == "industry_value" and not summ.passed
    assert summ.flags and summ.n_named == 0 and out.candidates == ()
