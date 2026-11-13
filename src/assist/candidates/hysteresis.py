"""Hysteresis on the holding record (PLAN S87, phase P rule 4): the previous acted verdict,
today's raw answers (`holdings.answers`), the report and dividend dates judged and the price →
today's **acted** verdict and the cause of its change. Pure.

- **Thesis** is re-judged only when a new quarterly report (`report_period`) or dividend record
  (`last_dividend_ex`) arrives, or the model changed (`rejudge`). On any other day the previous
  acted thesis stands, whatever today's raw answer says (a screener value moving with no filing
  is not evidence). A **hard** fail (`holdings.HARD`: dividend cut, negative equity, negative
  CFO) acts at once. A **soft** fail acts only when `SOFT_FAIL_REPORTS` (2) quarterly reports in
  a row failed: `soft_fail_periods` lists the report periods of the current run of soft fails; a
  pass resets it, a dividend record alone re-judges but adds no report. An `unknown` raw thesis
  never acts: the previous acted thesis stands (rule 3).
- **Required return held between reports** (the 2026-11-11 → 11-12 BBNI flip, option a). The
  fair price is the dividend legs at the required return (hurdle + sector shift). The hurdle
  moves with the regime (+1pt risk-off), the US ERP, the IDN CRP and the tilt, none of them a
  filing, so a fair price at the live required return flips take-profit on a regime toggle
  alone. `required_pt` is set from the live one when the thesis is re-judged (a new report or
  dividend record, the first record, a model change) and held until the next; the live value is
  kept beside it (`required_live_pt`). The legs (yield = trailing DPS / price; payout and g from
  DPS, shares and NI) make the fair price DPS / (required − g): with the required return held it
  moves only on a filing. Option b (keep it live, call a regime-only crossing no change) would
  need every hurdle component labelled and still leaves ERP, CRP and tilt moves flipping it.
- **Take-profit** fires when the price reaches the fair price (`state` armed → fired, action
  `trim_to_half`: `exits.TP_ACTION`), then `stop_adding` while fired. It re-arms only once the
  price is `REARM_BELOW_FAIR_PCT` (10%) below fair, so a price hovering at fair trims once.
  **First record is a baseline** (user 2026-11-13): a name already at or above fair on its first
  record starts `fired` without a trim (`stop_adding`, `baseline` true), so the first run does
  not trim every rich holding at once; it trims only on a later crossing up after re-arming.
- **Action**: `sell_all` (the thesis acts) > `trim_to_half` (take-profit fired today) >
  `stop_adding` (fired earlier, not re-armed) > `hold`.
- **Re-entry**: `sold` lists the names the model sold on its thesis and that are no longer held;
  one of them may be bought again only when its row's margin over the required return is at
  least `REENTRY_MARGIN_PT` (`reenters`), as large as the risk-off premium so a regime toggle
  alone cannot bring it back.

**A model change, behind a flag.** `ACT_ON_VERDICTS` (True since the user's call 2026-11-13;
False keeps S86's amounts in the guide, the acted verdict only shown beside each step). True
makes the guide's thesis sells, take-profit trims, stop-adding and re-entry follow the acted
verdict (and drop sizing's "trim in full" where the acted thesis holds). It changes stances'
orders, so per CLAUDE.md it waits for its placebo and the user's decision (S87 Progress row).
`REARM_BELOW_FAIR_PCT` may change after a retrospective review.

Hashed by `journal.RULE_GLOBS` (`candidates/**/*.py`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from assist.candidates import exits

__all__ = ["ACTIONS", "ACT_ON_VERDICTS", "REARM_BELOW_FAIR_PCT", "REENTRY_MARGIN_PT",
           "SOFT_FAIL_REPORTS", "act", "config", "reenters", "sold"]

VERSION = "0.2.0"
SOFT_FAIL_REPORTS = 2  # phase P rule 4 (user 2026-11-12)
REARM_BELOW_FAIR_PCT = 10.0  # rule 4 (user 2026-11-12); may change after a retrospective
REENTRY_MARGIN_PT = 1.0  # = hurdle risk_off_premium_pt; confirmed by the user 2026-11-13
ACT_ON_VERDICTS = True  # user 2026-11-13: thesis sells, trims and re-entry move the guide
ACTIONS = ("hold", "sell_all", "trim_to_half", "stop_adding")


def config() -> dict:
    return {"hysteresis_version": VERSION, "soft_fail_reports": SOFT_FAIL_REPORTS,
            "rearm_below_fair_pct": REARM_BELOW_FAIR_PCT,
            "reentry_margin_pt": REENTRY_MARGIN_PT, "act_on_verdicts": ACT_ON_VERDICTS,
            "first_record": "baseline: above fair stops adding, no trim",
            "rejudged_on": "a new report period or dividend record, or a model change",
            "required_return": "held between reports (set when the thesis is re-judged)"}


def _filing(inputs: Mapping | None) -> dict:
    i = inputs or {}
    return {"report_period": i.get("report_period"), "last_dividend_ex": i.get("last_dividend_ex")}


def _thesis(prev: Mapping | None, raw: Mapping, judged: Mapping, new_report: bool) -> dict:
    status = raw.get("status")
    if status == "unknown" and prev is not None:
        return dict(prev)
    periods: list[str] = []
    if status == "fail" and raw.get("severity") == "soft":
        before = list((prev or {}).get("soft_fail_periods") or [])
        if (prev or {}).get("status") != "fail" or (prev or {}).get("severity") != "soft":
            before = []
        rp = judged.get("report_period")
        periods = before + ([rp] if rp is not None and (new_report or not before)
                            and rp not in before else [])
    hard = status == "fail" and raw.get("severity") == "hard"
    return {"status": status, "gate": raw.get("gate"), "severity": raw.get("severity"),
            "acts": hard or len(periods) >= SOFT_FAIL_REPORTS,
            "soft_fail_periods": periods, **judged}


def act(prev: Mapping | None, thesis: Mapping, inputs: Mapping, *, price: float | None,
        dv: Mapping | None, required_live: float | None, rejudge: bool = False) -> dict:
    """The acted verdict for one held name. `prev` is the previous record's `acted` block (None
    for a first record), `thesis` today's raw `holdings.thesis`, `inputs` the filings judged,
    `dv` today's dividend assessment (`price`, `legs`), `required_live` today's required return
    (hurdle + sector shift), `rejudge` true after a model change."""
    judged = _filing(inputs)
    pt, pv = (prev or {}).get("thesis"), (prev or {}).get("valuation") or {}
    before = _filing(pt)
    filed = prev is None or judged != before
    new_report = pt is None or judged["report_period"] != before["report_period"]
    th = _thesis(pt, thesis, judged, new_report) if filed or rejudge or pt is None else dict(pt)

    relock = filed or rejudge or pv.get("required_pt") is None
    required = required_live if relock else pv["required_pt"]
    dv = dv or {}
    fair = exits.fair_price("dividend_value", dv.get("price"), dv.get("legs"), required)
    state, fired_now = pv.get("state") or "armed", False
    ok = bool(price and price > 0)
    baseline = prev is None and bool(fair and ok and price >= fair)
    if fair and ok:
        if state == "armed" and price >= fair:
            state, fired_now = "fired", not baseline
        elif state == "fired" and price <= fair * (1 - REARM_BELOW_FAIR_PCT / 100):
            state = "armed"
    val = {"required_pt": required, "required_live_pt": required_live,
           "required_for": dict(judged) if relock else pv.get("required_for"),
           "fair_price": fair, "take_profit": exits._floor_tick(fair) if fair else None,
           "state": state, "baseline": baseline,
           "rearm_below": fair * (1 - REARM_BELOW_FAIR_PCT / 100) if fair else None}
    action = ("sell_all" if th.get("acts") else "trim_to_half" if fired_now
              else "stop_adding" if state == "fired" else "hold")

    if prev is None:
        cause, changed = "first", []
    else:
        changed = [q for q, a, b in (
            ("thesis", (pt or {}).get("status"), th["status"]),
            ("thesis", (pt or {}).get("acts"), th["acts"]),
            ("valuation", pv.get("state"), state)) if a != b]
        changed = list(dict.fromkeys(changed))
        cause = (None if not changed else "rule_version" if rejudge and not filed
                 else "new_filing" if "thesis" in changed or (filed and fair != pv.get(
                     "fair_price")) else "price_cross")
    return {"thesis": th, "valuation": val, "action": action, "cause": cause, "changed": changed}


def reenters(margin_pt: float | None) -> bool:
    """A name the model sold may be bought again only with this margin over the required
    return."""
    return margin_pt is not None and margin_pt >= REENTRY_MARGIN_PT


def sold(previous_records: Sequence[Mapping], previous_sold: Iterable[Mapping], *,
         held: Iterable[str], since: str) -> list[dict]:
    """The names the model sold on its thesis that are not held now: last run's records whose
    acted action was `sell_all`, plus last run's `sold`, minus the names held again. An entry
    keeps its first date."""
    held = set(held)
    out: dict[str, dict[str, Any]] = {}
    for s in previous_sold:
        if s["symbol"] not in held:
            out.setdefault(s["symbol"], dict(s))
    for r in previous_records:
        a = r.get("acted") or {}
        if a.get("action") == "sell_all" and r["symbol"] not in held:
            out.setdefault(r["symbol"], {"symbol": r["symbol"], "since": since,
                                         "gate": (a.get("thesis") or {}).get("gate")})
    return [out[s] for s in sorted(out)]
