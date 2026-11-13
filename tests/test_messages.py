"""PLAN phase R (T1, T2, T5, T6): the Monday Telegram message, built from the guide only, in
the user's six sections."""

from __future__ import annotations

from datetime import date

from assist import messages

DAY = date(2026, 11, 16)
DATES = ["2026-11-17", "2026-11-27", "2026-12-07"]


def tr(idr: float, dates=DATES) -> list[dict]:
    return [{"date": d, "idr": idr / len(dates), "shares": None,
             "price": {"type": "market", "at": None}} for d in dates]


def sell(n, sym, idr, tags, question="fit", dates=DATES, why="Portfolio fit: x.") -> dict:
    return {"n": n, "side": "sell", "kind": "name", "symbol": sym, "idr": idr, "tags": tags,
            "question": question, "label": f"Sell {sym}", "strength": "medium",
            "tranches": tr(idr, dates), "why": why, "market": "IDN", "asset": "stocks"}


def bucket(n, label, idr, why, market="IDN", asset="bonds") -> dict:
    return {"n": n, "side": "buy", "kind": "bucket", "symbol": None, "idr": idr, "tags": [],
            "question": None, "label": label, "strength": "medium", "tranches": tr(idr),
            "why": why, "market": market, "asset": asset}


LEGS = [{"market": "IDN", "asset": "stocks", "current_pct": 96.9, "target_pct": 45.7},
        {"market": "IDN", "asset": "bonds", "current_pct": 1.8, "target_pct": 30.5},
        {"market": "USA", "asset": "stocks", "current_pct": 0.0, "target_pct": 23.8}]


def guide(steps=None, **kw) -> dict:
    steps = steps if steps is not None else STEPS
    sells = [s for s in steps if s["side"] == "sell"]
    buys = [s for s in steps if s["side"] == "buy"]
    g = {"as_of": "2026-11-13", "regime": "neutral", "headline": "Markets are normal",
         "headline_note": "No strong mood either way; orders go in one go.", "split": 3,
         "held_for_data": [], "steps": steps, "legs": LEGS, "portfolio_value_idr": 100e6,
         "totals": {"sells": len(sells), "sell_idr": sum(s["idr"] for s in sells),
                    "buys": len(buys), "buy_idr": sum(s["idr"] for s in buys)}}
    g.update(kw)
    return g


REDUNDANT = ["redundant", "all of it"]
STEPS = [
    sell(1, "BMRI", 1.8e6, ["down to the 5% cap"]),
    sell(2, "PWON", 2.44e6, ["all of it", "hysteresis: would hold"], "valuation"),
    sell(3, "KLBF", 2.41e6, REDUNDANT),
    sell(4, "TOWR", 1.64e6, REDUNDANT),
    sell(5, "BBRI", 1.63e6, REDUNDANT),
    sell(6, "ADMF", 1.56e6, REDUNDANT),
    sell(7, "GEMS", 0.68e6, ["rebalance"], dates=DATES[:1]),
    bucket(8, "Buy SBN (Indonesian government bonds)", 15.9e6,
           "Indonesian bonds are 1.8% of your portfolio against a 30% target. Pick the "
           "product once: retail SBN, an FR series or a bond fund."),
    bucket(9, "Buy a US broad-market index fund", 13.19e6,
           "US stocks are 0.0% of your portfolio against a 24% target. No US stock passes "
           "a screen, so use a broad index fund.", "USA", "stocks"),
]

STANCES = [{"subject": "IDN", "asset": "stocks", "regime": "neutral", "dollar": "up",
            "home_regime": {"state": "neutral", "points": 0, "drivers": []}}]

UNDERVALUED = [{"market": "IDN", "styles": [
    {"style": "dividend_value", "passed": True, "rows": [
        {"symbol": s, "rank": i + 1, "held": s != "NEWX", "size": None, "margin_pt": 1.0,
         "held_idr": 1e6 if s != "NEWX" else 0.0,
         "style": "dividend_value",
         "entry": {"status": "buy_zone" if s in ("BMRI", "ELSA") else "avoid"}}
        for i, s in enumerate(["BMRI", "ELSA", "CPIN", "BBRI", "BFIN", "NEWX"])]},
    {"style": "garp", "passed": False, "rows": []}]},
    {"market": "USA", "styles": [{"style": "garp", "passed": False, "rows": []}]}]


def holding(sym, acts, held=1e6, action="sell_all") -> dict:
    return {"symbol": sym, "held_idr": held,
            "acted": {"action": action if acts else "hold", "thesis": {"acts": acts}}}


HOLDINGS = {"config": {"hysteresis": {"act_on_verdicts": False}},
            "holdings": [holding("ADMF", True), holding("ASII", True), holding("BMRI", False)]}


def text(**kw) -> str:
    args = {"day": DAY, "guide_payload": guide(), "stances": STANCES,
            "undervalued": UNDERVALUED, "holdings": HOLDINGS}
    args.update(kw)
    return messages.weekly(**args)


# ---------------- T1: the guide is the only source of numbers ----------------


def test_buys_come_first_and_are_never_cut():
    many = [sell(i, f"S{i:03d}", 0.1e6, ["rebalance"]) for i in range(1, 60)]
    t = text(guide_payload=guide(many + STEPS[-2:]))
    assert "Buy: SBN Rp 15.90m" in t and "Buy: US index fund Rp 13.19m" in t
    assert t.index("# Other buys") < t.index("# 5. US stocks to sell")


def test_totals_put_buy_first_and_dates_once():
    t = text()
    assert "# Buy Rp 41.1m, sell Rp 13.2m" in t
    assert "In 3 parts: 17 Nov, 27 Nov, 7 Dec, at market" in t
    assert "Smaller orders go in fewer parts." in t  # GEMS goes in one
    assert t.count("27 Nov") == 1


def test_sells_one_name_a_line_largest_first_no_reason():
    t = text(holdings=None)
    body = t.split("# 6. Indonesian stocks to sell (7, Rp 12.2m)")[1]
    assert body.split() == ["PWON", "all", "KLBF", "all", "BMRI", "1.8m", "TOWR", "all",
                            "BBRI", "all", "ADMF", "all", "GEMS", "0.7m"]
    for reason in ("Same industry", "fair value", "5% cap", "Share of the cut"):
        assert reason not in t


def flat(t: str) -> str:
    return " ".join(t.split())


def test_buy_line_amount_then_share_of_target():
    t = text()
    assert "Buy: SBN Rp 15.90m\n(1.8% of 30% target)" in t
    assert "Buy: US index fund Rp 13.19m\n(US stocks 0% of 24% target)" in t
    assert "Pick the product once" not in t


def test_one_disclaimer_no_file_name_no_jargon():
    t = text()
    assert "investment advice" not in t  # user 2026-11-13: no disclaimer
    for gone in (".md", "[medium]", "rebalance to benchmark", "margin", "dividend_value",
                 "Undervalued", "to average down", "Orders are split"):
        assert gone not in t, gone


REGIME = {"state": "neutral", "dollar": "up", "rule": {"state_at": 2},
          "inputs": [{"counted": True, "direction": "neutral", "label": "VIX 17.5"},
                     {"counted": True, "direction": "risk_off", "label": "10Y real yield 2.78%"},
                     {"counted": False, "direction": "risk_off", "label": "STLFSI4 2.1"}],
          "home": {"state": "neutral", "points": 1, "rule": {"state_at": 2},
                   "inputs": [{"counted": True, "points": 1, "label": "JCI -7.5% vs 20d high"},
                              {"counted": True, "points": 0, "label": "USD/IDR +0.5%"}]}}


def test_moods_in_words_without_the_regime_file():
    t = flat(text())
    assert "# 1. World mood: normal" in t and "Dollar strengthening: the US dollar gained" in t
    assert "Orders go in one go." in t and "# 2. Indonesia mood: calm" in t
    off = [{**STANCES[0], "home_regime": {"state": "risk_off", "points": 2,
                                          "drivers": ["JCI -13.8% vs 20d high (2)"]}}]
    t = flat(text(stances=off))
    assert "# 2. Indonesia mood: nervous Why: JCI -13.8% vs 20d high." in t
    assert "orders are split into parts" in t


def test_moods_name_the_warning_signs_that_fired():
    t = flat(text(regime=REGIME))
    assert "Warning signs: 1 of 2 (2 make it nervous): 10Y real yield 2.78%." in t
    assert "STLFSI4" not in t  # not counted
    assert ("Warning points: 1 from 2 checks (2 make it nervous): JCI -7.5% vs 20d high."
            in t)


def test_six_sections_in_the_users_order():
    t = text()
    heads = [ln for ln in t.splitlines() if ln.startswith("# ")]
    order = ["# 1. World mood", "# 2. Indonesia mood", "# Buy Rp", "# 3. US stocks to buy",
             "# 4. Indonesian stocks to buy", "# Other buys", "# 5. US stocks to sell",
             "# 6. Indonesian stocks to sell"]
    assert [next(h for h in heads if h.startswith(o)) for o in order] == heads[1:]
    us_buy = t.split("# 3.")[1].split("# 4.")[0]
    assert "Buy: US index fund Rp 13.19m" in us_buy
    assert "No US stock passes a value screen this week." in us_buy
    idn_buy = flat(t.split("# 4.")[1].split("# Other")[0])
    assert "(Indonesian stocks 96.9% of 46% target)" in idn_buy
    assert "SBN" in t.split("# Other buys")[1].split("# 5.")[0]
    assert "None: no US stocks held." in t.split("# 5.")[1].split("# 6.")[0]


def test_us_sells_have_their_own_section():
    us = {**sell(20, "AAPL", 3e6, ["rebalance"]), "market": "USA"}
    t = text(guide_payload=guide([*STEPS, us]))
    assert "# 5. US stocks to sell (1, Rp 3.0m)" in t
    assert "AAPL" not in t.split("# 6.")[1]


def test_best_value_names_are_buy_lines_to_target_or_full():
    t = text()
    idn_buy = t.split("# 4.")[1].split("# Other")[0]
    # 5% of Rp 100m = 5m; held at 1m → 4m to target; BMRI and BBRI are sold this week
    assert "Buy: ELSA Rp 4.00m (to target)" in idn_buy
    assert "Buy: CPIN Rp 4.00m (to target)" in idn_buy and "BFIN" in idn_buy
    assert "BMRI" not in idn_buy and "BBRI" not in idn_buy
    rows = UNDERVALUED[0]["styles"][0]["rows"]
    swapped = [{**UNDERVALUED[0], "styles": [{**UNDERVALUED[0]["styles"][0],
                                               "rows": [rows[5], *rows[:4]]}]}]
    assert "Buy: NEWX Rp 5.00m (full)" in text(undervalued=swapped)
    none = [{"market": "IDN", "styles": [{"style": "garp", "passed": False, "rows": []}]}]
    assert "No Indonesian stock passes a value screen this week." in flat(text(undervalued=none))
    assert "# Buy Rp 41.1m, sell Rp 13.2m" in t  # value buys and thesis sells count


def test_nothing_to_do_and_held_for_data():
    t = text(guide_payload=guide([]), holdings=None, undervalued=())
    assert "Nothing to do this week: every leg is at its target." in t
    t = text(guide_payload=guide([], held_for_data=["IDN bars stale"]))
    assert "No orders this week: some inputs are broken" in t and "IDN bars stale" in t


def test_no_guide_says_so():
    t = text(guide_payload=None)
    assert "No steps this run" in t and "investment advice" not in t


# ---------------- T2: the thesis line ----------------


def test_thesis_fails_are_sell_lines_trim_or_all():
    h = {**HOLDINGS, "holdings": [holding("ADMF", True), holding("ASII", True, 3e6),
                                  holding("LPPF", True, 2e6, "trim_to_half"),
                                  holding("BMRI", False)]}
    t = text(holdings=h)
    body = t.split("# 6. Indonesian stocks to sell (9, Rp 16.2m)")[1]
    assert "ASII all" in body and "LPPF trim 1.0m" in body
    assert body.count("ADMF") == 1  # already a step: listed once
    assert "Business no longer passes" not in t and "not acted on" not in t


# ---------------- T5: phone format ----------------


def test_every_line_fits_a_phone():
    many = [sell(i, f"S{i:03d}", 0.1e6, REDUNDANT) for i in range(1, 60)]
    long_why = bucket(99, "Buy SBN (Indonesian government bonds)", 1e6, "word " * 40 + ".")
    for g in (guide(), guide(many + [long_why])):
        for line in text(guide_payload=g).splitlines():
            assert len(line) <= messages.WIDTH, line


def test_heads_marked_for_bold():
    t = text().splitlines()
    assert t[0] == "# investment-assist, Mon 16 Nov 2026"
    assert t[1] == ""


# ---------------- T3: one 07:00 message ----------------


PREV = {"as_of": "2026-11-12", "state": "neutral", "dollar": "up", "home": "risk_off",
        "drivers": ["10Y real yield 2.78% (risk-off)"],
        "home_drivers": ["JCI -12.8% vs 20d high (2)"]}


def test_regime_lines_say_what_cleared_and_what_it_means():
    lines = messages.regime_lines(PREV, world="neutral", dollar="up", drivers=[],
                                  home="neutral", home_drivers=[])
    t = flat("\n".join(lines))
    assert lines[0] == "# Mood changed"
    assert "Indonesia: nervous → calm." in t
    assert "Cleared: JCI -12.8% vs 20d high." in t
    assert "Monday: the extra caution for Indonesia ends." in t
    assert "World" not in t and "Dollar" not in t  # unchanged parts are not repeated


def test_regime_lines_world_turns_nervous_with_why():
    prev = {**PREV, "home": "neutral", "home_drivers": []}
    lines = messages.regime_lines(prev, world="risk_off", dollar="flat",
                                  drivers=["VIX 31 (risk-off)", "HY spread 5.1% (risk-off)"],
                                  home="neutral", home_drivers=[])
    t = flat("\n".join(lines))
    assert "World: normal → nervous." in t
    assert "Why: VIX 31; HY spread 5.1%." in t
    assert "Dollar: strengthening → steady." in t
    assert "Monday: orders split in 3, new buys need a higher return." in t
    assert all(len(x) <= messages.WIDTH for x in lines)


def test_morning_message_one_disclaimer_and_sections():
    t = messages.morning(DAY, regime=["# Mood changed", "Indonesia: nervous → calm."],
                         holdings=["Holdings: baseline set: 67 held names as of 2026-11-13; "
                                   "from now on only changes are sent."],
                         health=["Data health:", "- openkrx: missing (no directory)",
                                 "- idx-method close 2026-11-12 16:30: failed (rc 1)"],
                         act_on=False)
    lines = t.splitlines()
    assert lines[0] == "# investment-assist morning, Mon 16 Nov 2026"
    assert "investment advice" not in t
    assert "# Holdings" in lines and "# Data health" in lines
    assert "• baseline set: 67 held names" in t and "• openkrx: missing" in t
    assert "not acted on yet" in t
    assert all(len(x) <= messages.WIDTH for x in lines)
    clear = messages.morning(DAY, regime=[], holdings=[], act_on=None, health=[
        "Data health: all clear again (the problems sent on 2026-11-06 are gone)."])
    assert "# Data health" in clear and "all clear again" in clear
    reminder = messages.morning(DAY, regime=[], holdings=[], act_on=None, health=[
        "Data health (reminder, unchanged since 2026-11-06):", "- x"])
    assert "# Data health (reminder, unchanged since 2026-11-06)" in reminder
