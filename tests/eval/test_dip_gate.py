"""Placebo for gate 3 of the average-down rule (P88, PLAN S69): adds made in `buy_zone` or
`deep` against adds on random days for the same names. Bars are synthetic and built here, so
nothing touches the real stores."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from assist.candidates.entry import MIN_BARS, measure
from assist.eval import dip_gate
from assist.eval.dip_gate import (
    HORIZON,
    MIN_NAMES,
    ZONES,
    build_panel,
    evaluate_panel,
    month_ends,
    months_on,
    run,
    total_return,
    windows,
)
from assist.eval.placebo import ALPHA, MIN_N, SEED, T_MIN
from assist.sources.idxmethod_stocks import IdxMethodStocks


def _sessions(n: int, start: date = date(2020, 1, 1)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bars(closes: list[float], start: date = date(2020, 1, 1)) -> list[dict]:
    return [{"date": d.isoformat(), "close": c}
            for d, c in zip(_sessions(len(closes), start), closes, strict=True)]


def _wave(n: int, period: int = 180, depth: float = 0.3, drift: float = 0.0003) -> list[float]:
    """A rising price with regular corrections, so every status occurs."""
    return [1000 * (1 + drift) ** i * (1 - depth * (0.5 - 0.5 * math.cos(2 * math.pi * i / period)))
            for i in range(n)]


# ---------------- phase K's gate numbers, unchanged ----------------


def test_gate_numbers_are_phase_ks():
    p = dip_gate.gate_params()
    assert (p["min_n"], p["t_min"], p["alpha"], p["seed"]) == (MIN_N, T_MIN, ALPHA, SEED)
    assert (MIN_N, T_MIN, ALPHA) == (10, 2.0, 0.05)
    assert p["horizon"] == p["stride"] == HORIZON == 12  # non-overlapping 12-month windows
    assert ZONES == ("buy_zone", "deep")


# ---------------- calendar and returns ----------------


def test_months_on_clamps_the_day():
    assert months_on(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert months_on(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert months_on(date(2024, 11, 15), 3) == date(2025, 2, 15)


def test_month_ends_are_last_sessions():
    days = _sessions(70, date(2024, 1, 1))
    ends = month_ends(days)
    assert ends[:2] == [date(2024, 1, 31), date(2024, 2, 29)]
    assert ends[-1] == days[-1]


def test_total_return_counts_dividends_and_ignores_a_split():
    bars = _bars([1000, 1000, 500, 500])  # 1-for-2 split on the third bar: a zero return
    dates, tr = total_return(bars, [])
    assert tr == pytest.approx([1.0, 1.0, 1.0, 1.0])
    divs = [{"ex": dates[1].isoformat(), "value": 50.0, "ccy": "CURRENCY_IDR"},
            {"ex": dates[3].isoformat(), "value": 99.0, "ccy": "CURRENCY_USD"}]
    _, tr = total_return(bars, divs)
    assert tr == pytest.approx([1.0, 1.05, 1.05, 1.05])


# ---------------- the panel: point in time ----------------


@pytest.fixture(scope="module")
def wave_panel():
    n = MIN_BARS + 420
    history = {"AAAA": _bars(_wave(n)), "BBBB": _bars(_wave(n, period=230, depth=0.4)),
               "YOUNG": _bars(_wave(MIN_BARS - 10))}
    return history, build_panel(history, {}, horizon=3)


def test_status_uses_only_bars_up_to_the_month_end(wave_panel):
    history, panel = wave_panel
    assert panel["months"], "the synthetic history gives scored months"
    for m in panel["months"]:
        for a in m["adds"]:
            lv = measure(history[a["symbol"]], [], as_of=m["date"])
            assert a["status"] == lv.status
    # the same history with a different future: every status up to the cut is unchanged
    cut = panel["months"][2]["date"]
    crashed = {s: [b if date.fromisoformat(b["date"]) <= cut else {**b, "close": b["close"] / 3}
                   for b in bars] for s, bars in history.items()}
    again = build_panel(crashed, {}, horizon=3)
    def upto(p):
        return [(m["date"], a["symbol"], a["status"]) for m in p["months"] if m["date"] <= cut
                for a in m["adds"]]
    assert upto(again) == upto(panel)


def test_add_is_priced_at_the_first_session_after_the_month_end(wave_panel):
    history, panel = wave_panel
    m = panel["months"][0]
    a = next(x for x in m["adds"] if x["symbol"] == "AAAA")
    dates, tr = total_return(history["AAAA"], [])
    i = next(k for k, d in enumerate(dates) if d > m["date"])
    e = next(k for k, d in enumerate(dates) if d >= months_on(dates[i], 3))
    assert a["add_date"] == dates[i]
    assert a["fwd"] == pytest.approx(100 * (tr[e] / tr[i] - 1))


def test_names_without_history_or_a_forward_return_sit_out(wave_panel):
    history, panel = wave_panel
    assert all(a["symbol"] != "YOUNG" for m in panel["months"] for a in m["adds"])
    assert "YOUNG" not in panel["pools"]
    last = date.fromisoformat(history["AAAA"][-1]["date"])
    assert all(months_on(a["add_date"], 3) <= last for m in panel["months"] for a in m["adds"])
    # a random day is eligible only once MIN_BARS bars lie before it
    dates, _ = total_return(history["AAAA"], [])
    assert len(panel["pools"]["AAAA"]) == sum(
        1 for i, d in enumerate(dates) if i >= MIN_BARS and months_on(d, 3) <= last)


def test_stale_name_sits_out():
    n = MIN_BARS + 420
    bars = _bars(_wave(n))
    halted = bars[: MIN_BARS + 100] + bars[MIN_BARS + 300:]  # no bars for about nine months
    gap = (date.fromisoformat(halted[MIN_BARS + 99]["date"]),
           date.fromisoformat(halted[MIN_BARS + 100]["date"]))
    panel = build_panel({"AAAA": bars, "HALT": halted}, {}, horizon=3)
    for m in panel["months"]:
        if gap[0] + timedelta(days=dip_gate.BAR_WINDOW_DAYS) < m["date"] < gap[1]:
            assert all(a["symbol"] != "HALT" for a in m["adds"])


# ---------------- the verdict ----------------


def _made(n_months: int, zone_fwd: float, pool: list[float], names: int = MIN_NAMES,
          jitter: float = 1.0) -> dict:
    months = []
    for k in range(n_months):
        d = months_on(date(2010, 1, 31), k)
        adds = [{"symbol": f"S{j}", "status": "buy_zone" if j % 2 else "deep", "add_date": d,
                 "fwd": zone_fwd + jitter * math.sin(k * 7 + j)} for j in range(names)]
        adds.append({"symbol": "WAIT", "status": "wait", "add_date": d, "fwd": -50.0})
        months.append({"date": d, "adds": adds})
    pools = {f"S{j}": list(pool) for j in range(names)} | {"WAIT": [0.0]}
    return {"months": months, "pools": pools, "horizon": 1}


def test_windows_do_not_overlap():
    days = [months_on(date(2020, 1, 31), k) for k in range(30)]
    assert windows(days, 12) == [days[0], days[12], days[24]]
    assert windows(days, 3) == days[::3]


def test_too_few_windows_is_insufficient():
    panel = _made(MIN_N - 1, 20.0, [0.0, 1.0, -1.0])
    res = evaluate_panel(panel, n_sets=20)
    assert (res["status"], res["passed"], res["binding"]) == ("insufficient", False, False)
    assert res["windows"] == MIN_N - 1
    assert f"needs {MIN_N}" in res["verdict"]


def test_overlapping_months_do_not_count_as_windows():
    panel = _made(30, 20.0, [0.0, 1.0, -1.0]) | {"horizon": 12}
    res = evaluate_panel(panel, n_sets=20)
    assert (res["status"], res["windows"], res["months"]) == ("insufficient", 3, 30)
    assert res["windows_short"] == MIN_N - 3


def test_real_edge_passes_and_binds():
    res = evaluate_panel(_made(24, 20.0, [0.0, 1.0, -1.0, 2.0, -2.0]), n_sets=50)
    assert (res["status"], res["passed"], res["binding"]) == ("passed", True, True)
    assert res["mean_real"] > res["mean_placebo"]
    assert res["perm_p"] <= ALPHA


def test_no_edge_fails():
    pool = [20.0 + math.sin(i) for i in range(40)]
    res = evaluate_panel(_made(24, 20.0, pool), n_sets=50)
    assert (res["status"], res["binding"]) == ("failed", False)


def test_only_zone_adds_are_scored_and_thin_months_sit_out():
    panel = _made(24, 20.0, [0.0])
    assert evaluate_panel(panel, n_sets=5)["mean_real"] == pytest.approx(20.0, abs=1.0)
    thin = _made(24, 20.0, [0.0], names=MIN_NAMES - 1)
    assert evaluate_panel(thin, n_sets=5)["months"] == 0
    by = evaluate_panel(panel, n_sets=5)["by_status"]
    assert by["wait"]["adds"] == 24 and by["wait"]["mean_fwd"] == pytest.approx(-50.0)


def test_rerun_gives_the_same_verdict():
    panel = _made(24, 3.0, [0.0, 5.0, -5.0, 2.0])
    assert evaluate_panel(panel, n_sets=30) == evaluate_panel(panel, n_sets=30)


# ---------------- run ----------------


def test_run_without_the_store_is_blocked(tmp_path):
    res = run(IdxMethodStocks(tmp_path / "nowhere"))
    assert (res["status"], res["passed"], res["binding"]) == ("blocked", False, False)
    assert res["stale_inputs"]


def test_run_reads_history_and_dividends(tmp_path):
    import json

    for kind in ("history", "dividends"):
        (tmp_path / "cache" / kind).mkdir(parents=True)
    (tmp_path / "cache" / "history" / "AAAA.json").write_text(
        json.dumps(_bars(_wave(MIN_BARS + 420))))
    (tmp_path / "cache" / "dividends" / "AAAA.json").write_text("[]")
    res = run(IdxMethodStocks(tmp_path), horizon=3, n_sets=5)
    assert res["status"] == "insufficient"
    assert res["horizon"] == 3 and res["names"] == 1
    assert res["disclaimer"] == "Heuristic, not investment advice."
