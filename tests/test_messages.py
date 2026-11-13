"""PLAN phase R (T1, T2, T5): the Monday Telegram message built from the guide only."""

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


def bucket(n, label, idr, why) -> dict:
    return {"n": n, "side": "buy", "kind": "bucket", "symbol": None, "idr": idr, "tags": [],
            "question": None, "label": label, "strength": "medium", "tranches": tr(idr),
            "why": why, "market": "IDN", "asset": "bonds"}


def guide(steps=None, **kw) -> dict:
    steps = steps if steps is not None else STEPS
    sells = [s for s in steps if s["side"] == "sell"]
    buys = [s for s in steps if s["side"] == "buy"]
    g = {"as_of": "2026-11-13", "regime": "neutral", "headline": "Markets are normal",
         "headline_note": "No strong mood either way; orders go in one go.", "split": 3,
         "held_for_data": [], "steps": steps,
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
           "a screen, so use a broad index fund."),
]

STANCES = [{"subject": "IDN", "asset": "stocks", "regime": "neutral", "dollar": "up",
            "home_regime": {"state": "neutral", "points": 0, "drivers": []}}]

UNDERVALUED = [{"market": "IDN", "styles": [
    {"style": "dividend_value", "passed": True, "rows": [
        {"symbol": s, "rank": i + 1, "held": s != "NEWX", "size": None, "margin_pt": 1.0,
         "style": "dividend_value"}
        for i, s in enumerate(["BMRI", "ELSA", "CPIN", "BBRI", "BFIN", "NEWX"])]},
    {"style": "garp", "passed": False, "rows": []}]},
    {"market": "USA", "styles": [{"style": "garp", "passed": False, "rows": []}]}]


def holding(sym, acts) -> dict:
    return {"symbol": sym, "acted": {"thesis": {"acts": acts}}}


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
    assert "SBN (Indonesian government bonds) Rp 15.9m" in t
    assert "US broad-market index fund Rp 13.2m" in t
    assert t.index("# Buy") < t.index("# Sell")


def test_totals_put_buy_first_and_dates_once():
    t = text()
    assert "# This week: buy Rp 29.1m, sell Rp 12.2m" in t
    assert "In 3 parts: 17 Nov, 27 Nov, 7 Dec, at market" in t
    assert "Smaller orders go in fewer parts." in t  # GEMS goes in one
    assert t.count("27 Nov") == 1


def test_sells_grouped_by_reason_top_three_by_amount():
    t = text()
    assert "Same industry and size held twice (4, Rp 7.2m)" in t
    assert "KLBF 2.4m, TOWR 1.6m, BBRI 1.6m, +1 more" in t
    assert "ADMF" not in t.split("# Sell")[1].split("# ")[0]
    assert "Price above its fair value (1, Rp 2.4m)" in t and "PWON 2.4m" in t
    assert "Over the 5% cap (1, Rp 1.8m)" in t
    assert "Share of the cut to the target (1, Rp 0.7m)" in t
    # largest group first
    assert t.index("Same industry") < t.index("Price above") < t.index("Over the 5%")


def flat(t: str) -> str:
    return " ".join(t.split())


def test_buy_reason_is_the_first_sentence_of_why():
    t = flat(text())
    assert "bonds are 1.8% of your portfolio against a 30% target" in t
    assert "Pick the product once" not in t


def test_one_disclaimer_no_file_name_no_jargon():
    t = text()
    assert t.count("not investment advice") == 1
    for gone in (".md", "[medium]", "rebalance to benchmark", "margin", "dividend_value",
                 "Undervalued", "to average down", "Orders are split"):
        assert gone not in t, gone


def test_market_line_in_words():
    t = flat(text())
    assert "Markets: normal; dollar rising; Indonesia calm." in t
    off = [{**STANCES[0], "home_regime": {"state": "risk_off", "points": 2,
                                          "drivers": ["JCI -13.8% vs 20d high (2)"]}}]
    t = flat(text(stances=off))
    assert "Indonesia nervous (JCI -13.8% vs 20d high)" in t


def test_best_value_names_held_and_new():
    t = text()
    assert "# Best value now (dividend screen)" in t
    assert "BMRI ELSA CPIN BBRI BFIN, all held" in t
    rows = UNDERVALUED[0]["styles"][0]["rows"]
    swapped = [{**UNDERVALUED[0], "styles": [{**UNDERVALUED[0]["styles"][0],
                                               "rows": [rows[5], *rows[:4]]}]}]
    assert "NEWX BMRI ELSA CPIN BBRI, NEWX not held" in text(undervalued=swapped)
    none = [{"market": "IDN", "styles": [{"style": "garp", "passed": False, "rows": []}]}]
    assert "No stock screen passes its test this week." in text(undervalued=none)


def test_nothing_to_do_and_held_for_data():
    t = text(guide_payload=guide([]))
    assert "Nothing to do this week: every leg is at its target." in t
    t = text(guide_payload=guide([], held_for_data=["IDN bars stale"]))
    assert "No orders this week: some inputs are broken" in t and "IDN bars stale" in t


def test_no_guide_says_so():
    t = text(guide_payload=None)
    assert "No steps this run" in t and t.count("not investment advice") == 1


# ---------------- T2: the thesis line ----------------


def test_thesis_fails_listed_while_not_acted_on():
    t = text()
    assert "# Business no longer passes (2)" in t
    assert "ADMF ASII" in t and "not acted on yet" in t
    on = {**HOLDINGS, "config": {"hysteresis": {"act_on_verdicts": True}}}
    assert "not acted on yet" not in text(holdings=on)
    assert "Business no longer passes" not in text(holdings=None)
    clean = {**HOLDINGS, "holdings": [holding("BMRI", False)]}
    assert "Business no longer passes" not in text(holdings=clean)


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
    assert t[1] == "Paper only. Heuristic, not investment advice."
