"""This week's steps (P93, PLAN S75): stances + candidates + layer 5 → dated orders. Payloads
are built here; nothing reads a store."""

from __future__ import annotations

from datetime import date

import pytest

from assist import guide
from assist.guide import build, lines, split_shares, tranche_dates

DAY = date(2026, 11, 10)  # a Tuesday
LADDER = {"style": "ladder", "tranches": 3, "spacing_days": 10}
LUMP = {"style": "lump", "tranches": 1, "spacing_days": 0}


def stance(subject, asset, cur, tgt, entry=LADDER, kind="neutral"):
    return {"subject": subject, "asset": asset, "stance": kind, "regime": "risk_off",
            "entry": entry, "portfolio": {"current_pct": cur, "target_pct": tgt}}


def name(sym, price, qty, **kw):
    return {"symbol": sym, "status": "stopped", "gate": 1, "reason": "", "avg_cost": price,
            "quantity": qty, "price": price, "below_cost_pct": 0.0, "new_avg_cost": None,
            "entry_status": None, **kw}


def cands(market="IDN", trims=(), rows=(), names=(), value=100e6, passed=True, problems=None):
    c = {"market": market,
         "styles": [{"style": "dividend_value", "passed": passed, "rows": list(rows)}],
         "sizing": {"portfolio_value_idr": value, "trims": list(trims)},
         "average_down": {"names": list(names)}}
    if problems is not None:
        c["data_problems"] = list(problems)
    return c


def row(sym="BMRI", action="add", **kw):
    size = {"idr": 6e6, "reason": "x", "tranches": [
        {"day": 0, "idr": 2e6, "shares": 2000, "limit": None},
        {"day": 10, "idr": 2e6, "shares": 2000, "limit": 900.0},
        {"day": 20, "idr": 2e6, "shares": 2000, "limit": None}]}
    return {"symbol": sym, "action": action, "margin_pt": 4.1, "size": size,
            "exits": {"entry_cap": 1010.0, "take_profit": 1260.0,
                      "take_profit_action": "stop adding and trim to half",
                      "thesis_stop": "sell when it fails its screen", "review_at": 800.0},
            "cost_basis": None, **kw}


def valid(g):
    errors = list(guide.validator().iter_errors(g))
    assert not errors, [e.message for e in errors]
    return g


# ---------------- dates and lots ----------------


def test_dates_start_the_next_weekday_and_skip_weekends():
    assert tranche_dates(DAY, 3, 10) == [date(2026, 11, 11), date(2026, 11, 23),
                                         date(2026, 12, 1)]  # 11-21 is a Saturday
    assert tranche_dates(date(2026, 11, 13), 1, 0) == [date(2026, 11, 16)]  # Friday → Monday


def test_split_shares_whole_lots_front_loaded():
    assert split_shares(500, 3) == [200, 200, 100]
    assert split_shares(100, 3) == [100]  # one lot: one order
    assert split_shares(1419, 3) == [500, 500, 419]  # a full exit keeps its odd lot
    assert split_shares(19, 3) == [19] and split_shares(0, 3) == []


# ---------------- sells ----------------


def idn(trims=(), rows=(), names=(), cur=90.0, tgt=48.0, entry=LADDER):
    return valid(build(DAY, [stance("IDN", "stocks", cur, tgt, entry)],
                       [cands(trims=trims, rows=rows, names=names)], "sha256:x"))


def test_a_cap_trim_is_strong_and_a_failed_screen_is_medium():
    names = [name("BMRI", 1000.0, 9000), name("AMRT", 500.0, 1419)]
    g = idn(trims=[{"symbol": "BMRI", "idr": 4e6, "reason": "trim to the per-name cap of 5%"},
                   {"symbol": "AMRT", "idr": 709_500.0,
                    "reason": "trim in full: fails its screen"}],
            names=names, cur=52.7, tgt=48.0)
    by = {s["symbol"]: s for s in g["steps"]}
    assert (by["BMRI"]["strength"], by["BMRI"]["shares"]) == ("strong", 4000)
    assert "more than 5% of your portfolio" in by["BMRI"]["why"]
    assert (by["AMRT"]["strength"], by["AMRT"]["shares"]) == ("medium", 1419)  # all of it
    assert "dividend screen no longer rates it" in by["AMRT"]["why"]
    assert [s["symbol"] for s in g["steps"]] == ["BMRI", "AMRT"]  # strong first
    assert [t["shares"] for t in by["BMRI"]["tranches"]] == [1400, 1300, 1300]
    assert all(t["price"] == {"type": "market", "at": None} for t in by["BMRI"]["tranches"])


def test_the_unnamed_cut_is_sold_pro_rata_and_labelled_a_rebalance():
    names = [name("AAAA", 1000.0, 50_000), name("BBBB", 500.0, 40_000),
             name("TRIM", 1000.0, 10_000)]
    g = idn(trims=[{"symbol": "TRIM", "idr": 10e6, "reason": "trim in full: fails its screen"}],
            names=names, cur=80.0, tgt=48.0)  # cut 32m: 10m named, 22m pro rata over 70m
    by = {s["symbol"]: s for s in g["steps"]}
    assert set(by) == {"TRIM", "AAAA", "BBBB"}
    assert by["AAAA"]["tags"] == ["rebalance"] and "not a view on the stock" in by["AAAA"]["why"]
    assert "80.0% of your portfolio against a 48% target" in by["AAAA"]["why"]
    assert g["totals"]["sell_idr"] == pytest.approx(32e6, abs=50_000)
    assert g["totals"]["sell_idr"] <= 32e6
    assert by["AAAA"]["idr"] / 50e6 == pytest.approx(by["BBBB"]["idr"] / 20e6, rel=0.02)


def test_a_leg_at_target_has_no_steps():
    g = idn(names=[name("AAAA", 1000.0, 1000)], cur=48.0, tgt=48.0)
    assert g["steps"] == [] and "Nothing to do this week" in lines(g)[-1]


# ---------------- buys ----------------


def test_a_sized_row_is_a_buy_with_entry_take_profit_and_stop():
    g = idn(rows=[row()], cur=42.0, tgt=48.0, entry=LADDER)
    s = g["steps"][0]
    assert (s["side"], s["kind"], s["symbol"], s["shares"]) == ("buy", "name", "BMRI", 6000)
    assert [t["price"] for t in s["tranches"]] == [
        {"type": "market_cap", "at": 1010.0}, {"type": "limit", "at": 900.0},
        {"type": "market", "at": None}]
    assert [t["date"] for t in s["tranches"]] == ["2026-11-11", "2026-11-23", "2026-12-01"]
    assert s["take_profit"]["at"] == 1260.0
    assert s["take_profit"]["action"] == "stop adding and trim to half"
    assert s["stop"]["rule"] == "sell when it fails its screen" and s["stop"]["review_at"] == 800.0
    assert "Passes the dividend screen with +4.1 points" in s["why"]
    assert g["steps"][0]["n"] == 1


def test_an_average_down_says_so():
    r = row(action="average_down", cost_basis={"below_cost_pct": -15.2})
    s = idn(rows=[r], cur=42.0, tgt=48.0)["steps"][0]
    assert s["tags"] == ["average down"] and "15% below your cost" in s["why"]


# ---------------- bucket steps ----------------


def test_bonds_and_a_us_leg_with_no_names_are_bucket_steps():
    st = [stance("IDN", "stocks", 48.0, 48.0), stance("IDN", "bonds", 2.0, 32.0),
          stance("USA", "stocks", 0.0, 20.0)]
    g = valid(build(DAY, st, [cands(), cands("USA", passed=False)], None))
    by = {(s["market"], s["asset"]): s for s in g["steps"]}
    sbn, us = by[("IDN", "bonds")], by[("USA", "stocks")]
    assert sbn["label"] == "Buy SBN (Indonesian government bonds)" and sbn["kind"] == "bucket"
    assert sbn["idr"] == pytest.approx(30e6) and sbn["shares"] is None
    assert "1 2.0% of your portfolio against a 32% target" in "1 " + sbn["why"].split(" are ")[1]
    assert us["label"] == "Buy a US broad-market index fund" and us["idr"] == pytest.approx(20e6)
    assert "No US stock passes a screen" in us["why"]
    assert len(sbn["tranches"]) == 3 and g["split"] == 3


def test_sells_come_before_buys():
    st = [stance("IDN", "stocks", 60.0, 48.0), stance("IDN", "bonds", 20.0, 32.0)]
    g = valid(build(DAY, st, [cands(names=[name("AAAA", 1000.0, 60_000)])], None))
    assert [s["side"] for s in g["steps"]] == ["sell", "buy"]
    assert [leg["label"] for leg in g["legs"]] == ["Indonesian stocks", "Indonesian bonds",
                                                   "US stocks"]


def test_no_portfolio_value_no_steps_and_a_note():
    g = valid(build(DAY, [stance("IDN", "stocks", 90.0, 48.0)], [cands(value=None)], None))
    assert g["steps"] == [] and any("no stance or portfolio value" in n for n in g["notes"])


# ---------------- text, out/ ----------------


def test_lines_and_roundtrip(tmp_path):
    g = idn(rows=[row()], cur=42.0, tgt=48.0)
    text = lines(g)
    assert text[0] == "Markets are nervous. Orders are split in 3."
    assert text[1] == "0 to sell (Rp 0.0m), 1 to buy (Rp 6.0m)."
    assert text[2] == ("1. Buy BMRI Rp 6.0m, 6,000 shares, 3 parts from 2026-11-11 to "
                       "2026-12-01, at market, not above 1,010; take profit 1,260; review at "
                       "800 [medium]")
    assert guide.load(tmp_path) == (None, "no out/guide.json yet: run `assist run`")
    path = guide.write(g, tmp_path)
    before = path.stat().st_mtime_ns
    assert guide.write(g, tmp_path).stat().st_mtime_ns == before  # unchanged bytes, no rewrite
    assert guide.load(tmp_path) == (g, None)
    path.write_text("{}")
    assert guide.load(tmp_path)[0] is None and "fails the schema" in guide.load(tmp_path)[1]


def test_lines_limit():
    names = [name(f"N{i:03d}", 1000.0, 10_000) for i in range(8)]
    text = lines(idn(names=names, cur=80.0, tgt=48.0), limit=3)
    assert text[-1] == "... and 5 more steps on the home page"


# ---------------- brief and Telegram (P96, PLAN S78) ----------------


def test_brief_and_telegram_open_with_the_steps():
    from assist import brief, pipeline

    g = idn(rows=[row()], cur=42.0, tgt=48.0)
    text = brief.with_guide("# Investment brief\n\n> note\n\n## Data health\n\n- ok\n", lines(g))
    assert text.index("## This week") < text.index("## Data health")
    assert "- Markets are nervous. Orders are split in 3." in text
    assert "\n1. Buy BMRI Rp 6.0m" in text
    assert brief.with_guide("x", []) == "x"
    msg = pipeline.message(day=DAY, guide_payload=g)
    assert "Buy: BMRI Rp 6.00m" in msg
    assert "Buy: " not in pipeline.message(day=DAY)


def test_write_guide_never_raises(tmp_path):
    from assist import pipeline

    g, stale = pipeline.write_guide(DAY, [stance("IDN", "stocks", 42.0, 48.0)],
                                    [cands(rows=[row()])], "sha256:" + "a" * 64, tmp_path)
    assert stale == [] and (tmp_path / "guide.json").is_file() and g["steps"]
    g, stale = pipeline.write_guide(DAY, [{"bad": 1}], [], "x", tmp_path)
    assert g is None and stale[0].startswith("guide failed: KeyError")


# ---------------- the principle in the sell order (P100, PLAN S83) ----------------


def _dv(sym, position, keeper, redundant, basis="unrated", allowed=False, size=3):
    return {"symbol": sym, "sector": "Primer", "industry": "Produk Makanan Pertanian",
            "mktcap": 9e12, "size": "mid", "div_yield": None, "group_size": size,
            "position": position, "keeper": keeper, "redundant": redundant,
            "allowed": allowed, "basis": basis}


def test_redundant_names_are_sold_first_and_the_kept_name_last():
    names = [name("JPFA", 1000.0, 3000), name("LSIP", 1000.0, 2000), name("TAPG", 1000.0, 4000),
             name("OTHR", 1000.0, 20_000), name("BMRI", 1000.0, 20_000)]
    c = cands(names=names, value=100e6)
    c["diversification"] = {"names": [
        _dv("TAPG", 1, "TAPG", False), _dv("JPFA", 2, "TAPG", True),
        _dv("LSIP", 3, "TAPG", True),
        {**_dv("BMRI", 1, "BMRI", False, basis="kept by a passing screen", size=1),
         "industry": "Bank"},
        {**_dv("OTHR", 1, "OTHR", False, size=1), "industry": "Semen"}]}
    g = valid(build(DAY, [stance("IDN", "stocks", 55.0, 48.0)], [c], None))  # cut 7m
    by = {s["symbol"]: s for s in g["steps"]}
    # BMRI is kept by the screen: untouched. TAPG, the group's keeper, is unrated like OTHR, so
    # both take their pro-rata share of what the redundant names did not cover
    assert set(by) == {"LSIP", "JPFA", "OTHR", "TAPG"}
    assert by["TAPG"]["tags"] == ["rebalance"]
    assert [s["symbol"] for s in g["steps"]][:1] != ["TAPG"]
    assert by["LSIP"]["tags"] == ["redundant", "all of it"] and by["LSIP"]["shares"] == 2000
    assert by["JPFA"]["tags"] == ["redundant", "all of it"] and by["JPFA"]["shares"] == 3000
    assert "TAPG is the one to keep" in by["JPFA"]["why"]
    assert "3 mid companies in the same industry (Produk Makanan Pertanian)" in by["JPFA"]["why"]
    assert by["OTHR"]["tags"] == ["rebalance"]
    assert by["OTHR"]["idr"] + by["TAPG"]["idr"] == 2e6
    assert g["totals"]["sell_idr"] == 7e6


def test_an_allowed_redundant_name_is_not_singled_out():
    names = [name("JPFA", 1000.0, 3000), name("TAPG", 1000.0, 4000)]
    c = cands(names=names, value=100e6)
    c["diversification"] = {"names": [_dv("TAPG", 1, "TAPG", False, size=2),
                                      _dv("JPFA", 2, "TAPG", True, allowed=True, size=2)]}
    g = valid(build(DAY, [stance("IDN", "stocks", 51.0, 48.0)], [c], None))
    assert all(s["tags"] == ["rebalance"] for s in g["steps"])


# ---------------- P103 data gate ----------------


def test_a_data_problem_holds_every_step_and_says_why():
    st = [stance("IDN", "stocks", 96.9, 45.7), stance("IDN", "bonds", 1.8, 30.5),
          stance("USA", "stocks", 0.0, 23.8)]
    bad = "idx-method factors: price is null for 959 of 959 names"
    g = valid(build(DAY, st, [cands(trims=[{"symbol": "BBNI", "idr": 3e6, "reason": "x"}],
                                    problems=[bad]), cands("USA", passed=False)], None))
    assert g["steps"] == [] and g["totals"]["sells"] == 0 and g["totals"]["buys"] == 0
    assert g["held_for_data"] == [f"IDN: {bad}"]
    assert any("held" in n and bad in n for n in g["notes"])
    text = "\n".join(guide.lines(g))
    assert "Steps held this week" in text and bad in text
    assert "Nothing to do this week" not in text


def test_no_data_problem_keeps_the_steps():
    g = valid(build(DAY, [stance("IDN", "stocks", 55.0, 48.0)], [cands(problems=[])], None))
    assert g["steps"] and g.get("held_for_data", []) == []


# ---------------- S86: the holding record says which question drove a sell ----------------


def hrec(sym, status="pass", gate=None, severity=None, above=False, fair=3380.0, price=3400.0):
    return {"symbol": sym, "stale": False,
            "thesis": {"status": status, "gate": gate, "severity": severity},
            "valuation": {"price": price, "fair_price": fair, "above_fair": above}}


def held_records(*recs, market="IDN"):
    return {"market": market, "holdings": list(recs)}


def _with(records, trims=(), names=(), cur=52.7, tgt=48.0, div=None):
    c = cands(trims=trims, names=names)
    if div is not None:
        c["diversification"] = {"names": div}
    return valid(build(DAY, [stance("IDN", "stocks", cur, tgt)], [c], "sha256:x",
                       holdings=[held_records(*records)]))


FULL = "trim in full: fails its screen"


def _sym(g, sym):
    return next(s for s in g["steps"] if s["symbol"] == sym)


def test_a_thesis_fail_says_the_business_failed_which_test():
    g = _with([hrec("AMRT", "fail", "F-score", "soft")],
              trims=[{"symbol": "AMRT", "idr": 709_500.0, "reason": FULL}],
              names=[name("AMRT", 500.0, 1419)])
    s = _sym(g, "AMRT")
    assert s["question"] == "thesis"
    assert "fails the F-score test" in s["why"] and "soft" in s["why"]


def test_a_price_above_fair_is_a_valuation_sell_and_says_the_business_passes():
    g = _with([hrec("AMRT", above=True, fair=450.0, price=500.0)],
              trims=[{"symbol": "AMRT", "idr": 709_500.0, "reason": FULL}],
              names=[name("AMRT", 500.0, 1419)])
    s = _sym(g, "AMRT")
    assert s["question"] == "valuation"
    assert "above its fair price 450" in s["why"] and "business still passes" in s["why"]
    assert "fails" not in s["why"]


def test_a_cap_trim_is_fit():
    g = _with([hrec("BMRI")], trims=[{"symbol": "BMRI", "idr": 4e6,
                                      "reason": "trim to the per-name cap of 5%"}],
              names=[name("BMRI", 1000.0, 9000)])
    s = g["steps"][0]
    assert s["question"] == "fit" and "more than 5% of your portfolio" in s["why"]
    assert "business still passes" in s["why"]


def test_bbni_redundant_sale_is_fit_never_a_thesis_verdict():
    div = [{**_dv("BMRI", 1, "BMRI", False, basis="kept by a passing screen"),
            "industry": "Bank", "size": "large"},
           {**_dv("BBRI", 2, "BMRI", True, basis="kept by a passing screen"),
            "industry": "Bank", "size": "large"},
           {**_dv("BBNI", 3, "BMRI", True, basis="kept by a passing screen"),
            "industry": "Bank", "size": "large"}]
    names = [name("BMRI", 5000.0, 1000), name("BBRI", 4000.0, 1000), name("BBNI", 3400.0, 1000)]
    g = _with([hrec("BBNI"), hrec("BBRI"), hrec("BMRI")], names=names, div=div,
              cur=55.0, tgt=48.0)  # cut 7m: BBNI and BBRI in full
    by = {s["symbol"]: s for s in g["steps"]}
    s = by["BBNI"]
    assert s["question"] == "fit" and "redundant" in s["tags"]
    assert "BMRI is the one to keep" in s["why"]
    assert "business still passes" in s["why"] and "near its fair price 3,380" in s["why"]
    assert "fails" not in s["why"]


def test_a_redundant_sale_of_a_failing_name_still_says_the_thesis_failed():
    div = [{**_dv("BMRI", 1, "BMRI", False), "industry": "Bank", "size": "large"},
           {**_dv("BBNI", 2, "BMRI", True), "industry": "Bank", "size": "large"}]
    names = [name("BMRI", 5000.0, 1000), name("BBNI", 3400.0, 1000)]
    g = _with([hrec("BBNI", "fail", "CAR", "soft")], names=names, div=div, cur=52.0, tgt=48.0)
    s = {x["symbol"]: x for x in g["steps"]}["BBNI"]
    assert s["question"] == "fit" and "also fails the CAR test (soft fail)" in s["why"]


def test_without_a_record_a_full_trim_names_no_question():
    g = idn(trims=[{"symbol": "AMRT", "idr": 709_500.0, "reason": FULL}],
            names=[name("AMRT", 500.0, 1419)], cur=52.7, tgt=48.0)
    s = _sym(g, "AMRT")
    assert s["question"] is None and "dividend screen no longer rates it" in s["why"]


def test_buys_and_buckets_carry_no_question():
    g = idn(rows=[row()], cur=42.0, tgt=48.0)
    assert all(s["question"] is None for s in g["steps"] if s["side"] == "buy")


# ---------------- S87: the acted verdict (hysteresis), behind ACT_ON_VERDICTS ----------------


def arec(sym, action="hold", status="pass", gate=None, severity=None, periods=(), **kw):
    r = hrec(sym, status, gate, severity, **kw)
    r["acted"] = {"action": action,
                  "thesis": {"status": status, "gate": gate, "severity": severity,
                             "acts": action == "sell_all", "soft_fail_periods": list(periods)},
                  "valuation": {"fair_price": kw.get("fair", 3380.0), "state":
                                "fired" if action in ("trim_to_half", "stop_adding") else
                                "armed", "rearm_below": kw.get("fair", 3380.0) * 0.9}}
    return r


def _acted(records, trims=(), names=(), rows=(), cur=48.0, tgt=48.0, act=True, sold=()):
    c = cands(trims=trims, names=names, rows=rows)
    h = held_records(*records) | {"sold": [{"symbol": s, "since": "2026-11-09", "gate": "cut"}
                                           for s in sold]}
    return valid(build(DAY, [stance("IDN", "stocks", cur, tgt)], [c], "sha256:x",
                       holdings=[h], act=act))


def test_flag_off_keeps_s86_amounts_and_says_what_hysteresis_would_do():
    g = _acted([arec("AMRT", "hold", "fail", "F-score", "soft", periods=["2026-09-30"])],
               trims=[{"symbol": "AMRT", "idr": 709_500.0, "reason": FULL}],
               names=[name("AMRT", 500.0, 1419)], act=False)
    s = _sym(g, "AMRT")
    assert s["idr"] == 709_500.0 and "all of it" in s["tags"]
    assert "hysteresis: would hold" in s["tags"] and "first soft-fail report" in s["why"]


def test_flag_on_a_first_soft_fail_holds_instead_of_selling_in_full():
    g = _acted([arec("AMRT", "hold", "fail", "F-score", "soft", periods=["2026-09-30"])],
               trims=[{"symbol": "AMRT", "idr": 709_500.0, "reason": FULL}],
               names=[name("AMRT", 500.0, 1419)])
    assert not [s for s in g["steps"] if s["symbol"] == "AMRT"]
    assert any("AMRT" in n and "hysteresis" in n for n in g["notes"])


def test_flag_on_a_thesis_sell_sells_in_full_even_without_a_sizing_trim():
    g = _acted([arec("AMRT", "sell_all", "fail", "F-score", "soft",
                     periods=["2026-06-30", "2026-09-30"])],
               names=[name("AMRT", 500.0, 1419)])
    s = _sym(g, "AMRT")
    assert s["question"] == "thesis" and s["shares"] == 1419 and "all of it" in s["tags"]
    assert "two reports in a row" in s["why"]


def test_flag_on_a_hard_fail_sells_in_full():
    g = _acted([arec("AMRT", "sell_all", "fail", "cut", "hard")],
               trims=[{"symbol": "AMRT", "idr": 709_500.0, "reason": FULL}],
               names=[name("AMRT", 500.0, 1419)])
    s = _sym(g, "AMRT")
    assert s["question"] == "thesis" and s["shares"] == 1419 and "hard fail" in s["why"]


def test_flag_on_take_profit_trims_to_half_once():
    g = _acted([arec("BBNI", "trim_to_half", above=True, fair=3380.0, price=3500.0)],
               names=[name("BBNI", 3500.0, 2000)])
    s = _sym(g, "BBNI")
    assert s["question"] == "valuation" and s["shares"] == 1000 and "half" in s["tags"]
    assert "10% below" in s["why"]
    g2 = _acted([arec("BBNI", "stop_adding", above=True, fair=3380.0, price=3500.0)],
                names=[name("BBNI", 3500.0, 2000)], rows=[row("BBNI", action="average_down")],
                cur=40.0)
    assert not [s for s in g2["steps"] if s["symbol"] == "BBNI"]  # no trim, no add


def test_flag_on_a_sold_name_needs_a_margin_to_come_back():
    thin = _acted([], rows=[row("BBNI", margin_pt=0.5)], cur=40.0, sold=["BBNI"])
    assert not [s for s in thin["steps"] if s["symbol"] == "BBNI"]
    wide = _acted([], rows=[row("BBNI", margin_pt=4.1)], cur=40.0, sold=["BBNI"])
    assert _sym(wide, "BBNI")["side"] == "buy"
    off = _acted([], rows=[row("BBNI", margin_pt=0.5)], cur=40.0, sold=["BBNI"], act=False)
    assert _sym(off, "BBNI")["side"] == "buy"
