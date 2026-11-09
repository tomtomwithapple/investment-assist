"""Stance v0 (PLAN S5): layers 0 + 1 + 5 → one stance payload per subject × asset.

A pure function over the layer types: the layer-1 score (worldbankscape), shifted by the layer-0
regime and any layer-2 overrides, falls into a stance band; the stance tilts a target weight away
from its anchor (the benchmark weight when one is given, else the current holding); the gap to the
current holding (layer 5, financer) is the delta, bought lump-sum, or in a ladder when the regime
is risk_off. A missing regime or holdings is named in `stale_inputs` and lowers the confidence,
never raises. `dumps` writes sorted keys and rounded floats, so identical inputs give identical
bytes.

Phase B (F2): an asset rule (layers 2–4, e.g. the IDN bonds and stocks rules) reaches the stance
as a `RuleView`: its drivers, risks, watch items, stale inputs and sources, plus the stance it
proposes after its placebo gate (`gated_stance`). Only a gated stance that passed may replace
the band stance. The layer-2 overrides shift the score, but a shift that alone would move the
stance into another band is held at the band without it until the overrides beat a placebo
(CLAUDE.md: a rule changes a stance only after its placebo control); the driver says so.

Phase C (F3): the foreign subjects get the same treatment. Their layer-2 overrides (P28) shift
the score under the same band hold, and their `RuleView` carries context only (the IDR edge,
hedged against unhedged, and P29's index candidate) with no stance of its own.

Phase I (S39): the whole portfolio has one benchmark, set by the user on 2026-11-06:
`BENCHMARK_PCT` = IDN stocks 48%, IDN bonds 32%, USA stocks 20% (80% Indonesia with the paper
track's 60/40 inside it, 20% US stocks). Its keys are the mandate. A stance in the mandate
targets its benchmark plus its tilt (`TILT_PT`, `avoid` → 0), clipped to 0–100; `apply_limits`
then scales the mandate's targets down pro rata when they sum above `MANDATE_CAP_PCT`, and
whatever they leave below it is cash. A leg more than `TRANSITION_PT` (10) from its target moves
in a ladder, an add or a trim alike (entry style `ladder` with a negative delta is a laddered
trim). A stance outside the mandate keeps its view (stance, score,
drivers, risks) but targets 0%, so a holding there shows as a trim; a currency stance is a view
on the currency, not an allocation, and targets 0% the same way (the cash rest is IDR). Every
target is thus a share of one plan that sums to at most 100%.

Phase J (S42): `portfolio.rebalance_pt` and `portfolio.tilt_pt` split the gap (target − current)
into the move to the benchmark and the model's own call, so a trim that only follows the new
benchmark is not shown as a model decision. `tilt_pt` is the stance's tilt (target − benchmark
before the pro-rata cap) times the cap's scale, rounded to 0.1 pt; `rebalance_pt` is the gap
less that tilt, i.e. the scaled benchmark share − current to within 0.1 pt. The rounding residue
of the cap thus sits in the rebalance, so a neutral leg always shows a 0 tilt and the two parts
add up to the gap exactly. Outside the mandate the benchmark is 0: rebalance = −current, tilt 0.
Holdings unknown: both null. Targets, deltas and entries are unchanged by the split.

Phase K (S53, open question 8, fixed 2026-11-07): the home (IDN) regime (`layers.home_regime`)
reaches IDN stocks and IDN bonds only (`HOME_ASSETS`). Home risk_off ladders their adds and trims
(`LADDER_TRANCHES` × `LADDER_SPACING_DAYS`, the same ladder): an entry style, not a stance change,
so it needs no gate. Their score moves `HOME_SHIFT_PT` (−5) only if
`home_regime.HOME_SHIFT_ADOPTED` (its walk-forward passed; False since P71), and never on top of
a global risk_off: both off is −5, not −10. Each IDN leg carries a `home_regime` block (state,
points, drivers, stale inputs); its stale inputs stay in the block and do not lower the
confidence, since the home regime does not move the score while not adopted. Bands, `TILT_PT`,
`BENCHMARK_PCT` and `TRANSITION_PT` are unchanged.

Phase L (S61, choice 11, fixed 2026-11-09): the layer-2 shift may cross a band only in the
direction of a side that passed its override gate (`eval.override_gate`, out/overrides/): an up
pass lets a positive shift lift the band stance, a down pass lets a negative shift lower it; the
other direction stays held at the band, and no pass holds both. The shift keeps its ±10 cap. The
EMU verdict reaches its five members. A passed phase K rule still replaces the band stance after.
Each stance carries a `layer2` block (shift, gate states, sides passed, crossed, held).

Every number below is hand-set and stays so until a rule using it beats its placebo control.
TODO(PLAN.md, Open questions): the ±5 pt tilt (`TILT_PT`) is still a placeholder until phase I
has run; the benchmark itself is the user's choice, not fitted.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from assist.layers import home_regime as hr
from assist.layers.home_regime import HomeRegime
from assist.layers.types import (
    DISCLAIMER,
    MAX_OVERRIDE,
    AssetScore,
    Override,
    Regime,
    Weights,
)

__all__ = [
    "BENCHMARK_PCT",
    "BENCHMARK_TEXT",
    "DISCLAIMER",
    "HOME_ASSETS",
    "HOME_SHIFT_PT",
    "LADDER_SPACING_DAYS",
    "LADDER_TRANCHES",
    "MANDATE",
    "MANDATE_CAP_PCT",
    "MODEL_CONFIG",
    "REGIME_SHIFT",
    "SCHEMA_VERSION",
    "STALE_PENALTY",
    "STANCE_BANDS",
    "TILT_PT",
    "TRANSITION_PT",
    "OverrideGateView",
    "RuleView",
    "apply_limits",
    "base_stance",
    "build_stance",
    "home_shift",
    "dumps",
    "mandate_summary",
    "model_fingerprint",
    "split_text",
    "stance_for",
]

SCHEMA_VERSION = "1.3.0"  # 1.1: portfolio.rebalance_pt / tilt_pt (S42); 1.2: home_regime (S53);
# 1.3: layer2 (S61)
MODEL_VERSION = "0.6.0"  # 0.2: phase B (F2), IDN rules and layer 4; 0.3: phase C (F3) foreign;
# 0.4: phase I (S39), benchmark 48/32/20 and the 100% rule; 0.5: phase K (S53), home regime;
# 0.6: phase L (S61), a passed override side may cross a band

# Layer-0 shift of the layer-1 score, in points (same for every asset in v0).
REGIME_SHIFT = {"risk_on": 5.0, "neutral": 0.0, "risk_off": -5.0}

# (lowest score, stance), checked top down; anything below the last band is "avoid".
STANCE_BANDS = ((60.0, "overweight"), (40.0, "neutral"), (25.0, "underweight"))

# TODO(open question): placeholder tilts in percentage points of the portfolio, not risk limits.
TILT_PT = {"overweight": 5.0, "neutral": 0.0, "underweight": -5.0}  # "avoid" targets 0
# The user's benchmark (2026-11-06): 80% Indonesia (48 stocks / 32 SBN), 20% US stocks.
BENCHMARK_PCT: dict[tuple[str, str], float] = {
    ("IDN", "stocks"): 48.0, ("IDN", "bonds"): 32.0, ("USA", "stocks"): 20.0}
BENCHMARK_TEXT = "/".join(f"{v:g}" for v in BENCHMARK_PCT.values())  # "48/32/20"
MANDATE = frozenset(BENCHMARK_PCT)  # every other (subject, asset) targets 0%
MANDATE_CAP_PCT = 100.0  # the mandate's targets are scaled down pro rata above this; rest is cash
OUTSIDE_NOTE = "outside the 80/20 mandate: target 0%"
CURRENCY_NOTE = "a currency view, not an allocation: target 0% (the cash rest is IDR)"
# Risk lines a mandate leg always carries (heuristic, not tax advice).
LEG_RISKS = {("USA", "stocks"): (
    "US estate tax: US-situs assets above US$60k held by a non-resident are exposed "
    "(heuristic, not tax advice; Ireland-domiciled UCITS ETFs avoid it)",)}

LADDER_TRANCHES = 3
LADDER_SPACING_DAYS = 10
# A mandate leg more than this many points from its target moves there in a ladder, adds and
# trims alike (user, 2026-11-06), so the first move to the benchmark is not one big trade.
TRANSITION_PT = 10.0
STALE_PENALTY = 0.9  # confidence multiplier per stale or missing input

# Open question 8 (fixed 2026-11-07): what the home (IDN) regime reaches, and its score shift,
# applied only if `home_regime.HOME_SHIFT_ADOPTED` and not on top of a global risk_off.
HOME_ASSETS = frozenset({("IDN", "stocks"), ("IDN", "bonds")})
HOME_SHIFT_PT = -5.0

MODEL_CONFIG = {
    "model_version": MODEL_VERSION,
    "regime_shift": REGIME_SHIFT,
    "stance_bands": [list(b) for b in STANCE_BANDS],
    "tilt_pt": TILT_PT,
    "benchmark_pct": {f"{s}/{a}": v for (s, a), v in sorted(BENCHMARK_PCT.items())},
    "mandate_cap_pct": MANDATE_CAP_PCT,
    "outside_mandate_target_pct": 0.0,
    "scale": "pro_rata_largest_remainder_0.1",
    "transition_pt": TRANSITION_PT,
    "ladder": {"tranches": LADDER_TRANCHES, "spacing_days": LADDER_SPACING_DAYS},
    "stale_penalty": STALE_PENALTY,
    "max_override": MAX_OVERRIDE,
    # phase L choice 11: only in the direction of a side that passed its override gate
    "override_moves_stance": "passed_side_only",
    "home_regime": {
        "assets": sorted(f"{s}/{a}" for s, a in HOME_ASSETS),
        "ladder": "risk_off",  # adds and trims, LADDER_TRANCHES x LADDER_SPACING_DAYS
        "shift_pt": HOME_SHIFT_PT,
        "shift_adopted": hr.HOME_SHIFT_ADOPTED,
        "shift_with_global_risk_off": 0.0,  # both off: -5, not -10
    },
}


@dataclass(frozen=True)
class RuleView:
    """What an asset rule (layers 2–4) adds to one stance. `stance` is the gated stance when the
    rule's placebo verdict passed (it then replaces the band stance and `entry` is used), None
    otherwise; `note` is the gate's sentence for the drivers and the journal."""

    subject: str
    asset: str
    note: str
    stance: str | None = None
    entry: Mapping | None = None
    drivers: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    watch: tuple[str, ...] = ()
    stale_inputs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class OverrideGateView:
    """What the override gate (`eval.override_gate`, S59) says for one subject × asset: the sides
    that passed (`up`, `down`), the state of each, and its line for the drivers."""

    passed: frozenset[str] = frozenset()
    states: Mapping[str, str] | None = None
    line: str = ""


def model_fingerprint(config: Mapping | None = None) -> str:
    """sha256 of the canonical JSON of the stance config; any change segments the journal."""
    blob = json.dumps(MODEL_CONFIG if config is None else config, sort_keys=True,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def stance_for(score: float) -> str:
    for floor, stance in STANCE_BANDS:
        if score >= floor:
            return stance
    return "avoid"


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return min(hi, max(lo, x))


def _r(x: float, nd: int = 1) -> float:
    return float(round(x, nd)) + 0.0  # + 0.0 turns -0.0 into 0.0


def _override_shift(key: tuple[str, str], overrides: Sequence[Override]) -> float:
    mine = [o for o in overrides if (o.subject, o.asset) == key]
    return _clip(sum(o.delta for o in mine), -MAX_OVERRIDE, MAX_OVERRIDE)


def _home_for(key: tuple[str, str], home: HomeRegime | None) -> HomeRegime | None:
    """The home regime when it reaches this stance (IDN stocks and bonds), else None."""
    return home if key in HOME_ASSETS else None


def home_shift(state: str, home: HomeRegime | None) -> float:
    """The home score shift (open question 8): `HOME_SHIFT_PT` on a home risk_off, only if
    adopted, and 0 when the global regime is risk_off already (−5 in all, not −10)."""
    if home is None or home.state != "risk_off" or not hr.HOME_SHIFT_ADOPTED:
        return 0.0
    return 0.0 if state == "risk_off" else HOME_SHIFT_PT


def base_stance(score: AssetScore, regime: Regime | None, home: HomeRegime | None = None) -> str:
    """The band stance `build_stance` gives before any asset rule: layer 1 + regime (+ the home
    shift, if adopted, on IDN stocks and bonds). The overrides may move the score but not the
    band (see the module notes)."""
    state = regime.state if regime is not None else "neutral"
    home = _home_for((score.subject, score.asset), home)
    return stance_for(_r(_clip(score.score + REGIME_SHIFT[state] + home_shift(state, home))))


def build_stance(
    *,
    score: AssetScore,
    regime: Regime | None,
    weights: Weights | None,
    overrides: Sequence[Override] = (),
    benchmark: Mapping[tuple[str, str], float] | None = None,
    subject: str | None = None,
    asset: str | None = None,
    as_of: date | None = None,
    fingerprint: str | None = None,
    rule: RuleView | None = None,
    home: HomeRegime | None = None,
    override_gate: OverrideGateView | None = None,
) -> dict:
    """Stance payload (schema/stance.schema.json) for `score.subject` × `score.asset`.

    `regime` or `weights` may be None (store missing or locked): the regime is then taken as
    neutral, holdings as unknown, and each is named in `stale_inputs`. `home` (the home regime)
    is read for IDN stocks and bonds only and ignored for every other stance."""
    key = (score.subject, score.asset)
    if (subject and subject != key[0]) or (asset and asset != key[1]):
        raise ValueError(f"score is for {key}, asked for {(subject, asset)}")

    stale: set[str] = set(score.stale_inputs)
    sources: set[str] = {score.source}
    drivers = [f"layer-1 score {score.score:.1f}"]
    risks: list[str] = []

    state, dollar = "neutral", None
    if regime is None:
        stale.add("regime")
    else:
        state, dollar = regime.state, regime.dollar
        stale.update(regime.stale_inputs)
        sources.update(regime.sources)
    shift = REGIME_SHIFT[state]
    if shift:
        drivers.append(f"regime {state} ({shift:+.1f}pt)")
    if state == "risk_off":
        risks.append("global regime risk_off")
    if dollar == "up":
        risks.append("broad dollar rising")
    home = _home_for(key, home)
    h_shift = home_shift(state, home)
    home_off = home is not None and home.state == "risk_off"
    if home_off:
        drivers.append(f"home (IDN) regime risk_off ({home.points} points): adds and trims "
                       f"laddered over {LADDER_TRANCHES} tranches")
        if h_shift:
            drivers.append(f"home (IDN) regime risk_off ({h_shift:+.1f}pt)")
        risks.append("home (IDN) regime risk_off")
        sources.update(home.sources)
    elif home is not None:
        sources.update(home.sources)

    mine = [o for o in overrides if (o.subject, o.asset) == key]
    for o in mine:
        drivers.append(f"{o.reason} ({o.delta:+.1f}pt)")
        stale.update(o.stale_inputs)
        sources.update(o.sources)
    override = _override_shift(key, overrides)
    if regime is not None:
        drivers.extend(regime.drivers)

    final = _r(_clip(score.score + shift + h_shift + override))
    stance = base_stance(score, regime, home)
    moved, crossed, held = stance_for(final), False, False
    if moved != stance:
        side = "up" if override > 0 else "down"
        if override_gate is not None and side in override_gate.passed:
            drivers.append(f"layer-2 override crosses to {moved} from {stance}: its {side} side"
                           f" passed its gate ({override_gate.line})")
            stance, crossed = moved, True
        else:
            gate_state = (override_gate.states or {}).get(side) if override_gate else None
            drivers.append(f"layer-2 overrides would move the stance to {moved}; held at "
                           f"{stance} until their {side} side passes its gate"
                           + (f" ({side} side {gate_state})" if gate_state else " (no gate)"))
            held = True
    layer2 = {"shift": _r(override),
              "gate": dict(override_gate.states) if override_gate and override_gate.states
              else None,
              "passed": sorted(override_gate.passed) if override_gate else [],
              "crossed": crossed, "held": held}

    watch: list[str] = []
    if rule is not None:
        if (rule.subject, rule.asset) != key:
            raise ValueError(f"rule is for {(rule.subject, rule.asset)}, stance for {key}")
        if rule.stance is not None:
            stance = rule.stance
        drivers.append(rule.note)
        drivers.extend(d for d in rule.drivers if d not in drivers)
        risks.extend(r for r in rule.risks if r not in risks)
        watch.extend(rule.watch)
        stale.update(rule.stale_inputs)
        sources.update(rule.sources)

    current: float | None = None
    if weights is None:
        stale.add("financer")
    else:
        current = _r(weights.pct(*key) or 0.0)
        stale.update(weights.stale_inputs)
        sources.update(weights.sources)
        if weights.unmapped:
            risks.append(f"{len(weights.unmapped)} unmapped holding(s) not counted")

    bench = (BENCHMARK_PCT if benchmark is None else benchmark).get(key)
    if bench is None:
        target = 0.0
        drivers.append(CURRENCY_NOTE if key[1] == "currency" else OUTSIDE_NOTE)
    else:
        target = 0.0 if stance == "avoid" else _r(_clip(bench + TILT_PT[stance]))
        drivers.append(f"benchmark {bench:g}%" + (
            ", avoid: target 0%" if stance == "avoid"
            else f", tilt {TILT_PT[stance]:+g}pt ({stance})"))
        risks.extend(r for r in LEG_RISKS.get(key, ()) if r not in risks)

    if current is None:
        delta_text = "n/a (holdings unavailable)"
        entry = dict(_NONE)
    else:
        gap = _r(target - current)
        if (gap > 0 and state == "risk_off") or (gap != 0 and home_off):
            entry = dict(_LADDER)
        elif (gap > 0 and rule is not None and rule.stance is not None and rule.entry
              and rule.entry.get("style") != "none"):
            entry = {k: int(rule.entry[k]) if k != "style" else rule.entry[k]
                     for k in ("style", "tranches", "spacing_days")}
        elif gap > 0:
            entry = {"style": "lump", "tranches": 1, "spacing_days": 0}
        else:
            entry = dict(_NONE)
        delta_text = _delta_text(gap, entry)
    tilt = None if current is None else _r(target - (bench or 0.0))

    dates = [d for d in (score.as_of, regime and regime.as_of, weights and weights.as_of) if d]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "subject": key[0],
        "asset": key[1],
        "as_of": (as_of or max(dates)).isoformat(),
        "model_version": MODEL_VERSION,
        "model_fingerprint": fingerprint or model_fingerprint(),
        "stance": stance,
        "score": final,
        "layer1_score": _r(score.score),
        "confidence": _r(score.confidence * STALE_PENALTY ** len(stale), 2),
        "regime": state,
        "drivers": drivers,
        "risks": risks,
        "watch": watch,
        "entry": entry,
        "portfolio": {"current_pct": current, "target_pct": target, "delta": delta_text,
                      "benchmark_pct": 0.0 if bench is None else _r(bench)},
        "flags": [dict(f) for f in score.flags],
        "layer2": layer2,
        "stale_inputs": sorted(stale),
        "sources": sorted(sources),
        "disclaimer": DISCLAIMER,
    }
    _split(payload["portfolio"], tilt)
    if weights is not None and weights.notes:
        payload["portfolio"]["notes"] = list(weights.notes)
    if dollar is not None:
        payload["dollar"] = dollar
    if home is not None:
        payload["home_regime"] = {"state": home.state, "points": home.points,
                                  "drivers": list(home.drivers),
                                  "stale_inputs": list(home.stale_inputs)}
    return payload


_NONE = {"style": "none", "tranches": 0, "spacing_days": 0}
_LADDER = {"style": "ladder", "tranches": LADDER_TRANCHES, "spacing_days": LADDER_SPACING_DAYS}


def _home_off(p: Mapping) -> bool:
    return (p.get("home_regime") or {}).get("state") == "risk_off"


def _split(pf: dict, tilt: float | None) -> None:
    """Set `rebalance_pt` (gap less the tilt) and `tilt_pt` on a portfolio block (S42)."""
    if pf["current_pct"] is None or tilt is None:
        pf["rebalance_pt"] = pf["tilt_pt"] = None
        return
    gap = _r(pf["target_pct"] - pf["current_pct"])
    pf["tilt_pt"] = _r(tilt) + 0.0  # + 0.0: never a -0.0
    pf["rebalance_pt"] = _r(gap - pf["tilt_pt"]) + 0.0


def _pt(x: float) -> str:
    return f"{x:+.1f}pt"


def split_text(pf: Mapping) -> str | None:
    """"-51.2pt = -48.9pt rebalance to benchmark, -2.3pt tilt" for a portfolio block or layer
    row carrying the S42 split; None when it has none (older payloads, unknown holdings)."""
    reb, tilt = pf.get("rebalance_pt"), pf.get("tilt_pt")
    if not isinstance(reb, (int, float)) or not isinstance(tilt, (int, float)):
        return None
    gap = _r(reb + tilt) + 0.0
    return f"{_pt(gap)} = {_pt(reb)} rebalance to benchmark, {_pt(tilt)} tilt"


def _delta_text(gap: float, entry: Mapping) -> str:
    """The delta sentence for a gap (target − current, pt) bought with `entry`."""
    ladder = entry["style"] == "ladder"
    if gap > 0:
        return (f"+{gap:.1f}pt over {entry['tranches']} tranches" if ladder
                else f"+{gap:.1f}pt lump")
    if gap < 0:  # a laddered trim (S39 transition) sells in the same tranches
        return f"{gap:.1f}pt trim over {entry['tranches']} tranches" if ladder \
            else f"{gap:.1f}pt trim"
    return "0.0pt hold"


def mandate_summary(stances: Sequence[Mapping],
                    benchmark: Mapping[tuple[str, str], float] | None = None) -> dict:
    """Sum of every stance's target, the mandate legs' targets, and the cash rest below
    `MANDATE_CAP_PCT`. Reads `portfolio.target_pct` (stance payloads) or `target_pct` (rows)."""
    bm = BENCHMARK_PCT if benchmark is None else benchmark
    legs, total = {}, 0.0
    for p in stances:
        pf = p.get("portfolio") or p
        t = pf.get("target_pct")
        if not isinstance(t, (int, float)):
            continue
        total += t
        if (p.get("subject"), p.get("asset")) in bm:
            legs[f"{p['subject']}/{p['asset']}"] = float(t)
    total = _r(total)
    return {"benchmark_pct": {f"{s}/{a}": v for (s, a), v in sorted(bm.items())},
            "targets_pct": dict(sorted(legs.items())), "target_sum_pct": total,
            "cash_pct": _r(max(0.0, MANDATE_CAP_PCT - total))}


def apply_limits(stances: Sequence[dict],
                 benchmark: Mapping[tuple[str, str], float] | None = None) -> dict:
    """The portfolio pass after every stance is built (PLAN S39). Outside the mandate a target
    is 0 already; if the mandate's targets sum above `MANDATE_CAP_PCT` each is scaled down pro
    rata in 0.1 pt steps (largest remainder, so the rounded targets sum to the cap exactly) and
    its delta and entry are recomputed. Then every leg more than `TRANSITION_PT` from its
    target gets a ladder (`LADDER_TRANCHES` × `LADDER_SPACING_DAYS`), for an add or a trim; a
    smaller move keeps the per-stance entry (global or home risk_off or gated rule ladder, else
    lump; a trim `none`, or a ladder on a home risk_off). Changes the payloads in place and
    returns `mandate_summary` plus the scale."""
    bm = BENCHMARK_PCT if benchmark is None else benchmark
    legs = sorted((p for p in stances if (p["subject"], p["asset"]) in bm),
                  key=lambda p: (p["subject"], p["asset"]))
    raw = _r(sum(p["portfolio"]["target_pct"] for p in legs))
    scale = 1.0
    if raw > MANDATE_CAP_PCT:
        scale = MANDATE_CAP_PCT / raw
        exact = [round(p["portfolio"]["target_pct"] * scale * 10, 6) for p in legs]
        units = [math.floor(x) for x in exact]
        spare = round(MANDATE_CAP_PCT * 10) - sum(units)
        for i in sorted(range(len(legs)), key=lambda i: (units[i] - exact[i], i))[:spare]:
            units[i] += 1
        for p, u in zip(legs, units, strict=True):
            pf = p["portfolio"]
            before = pf["target_pct"]
            pf["target_pct"] = _r(u / 10)
            _split(pf, (before - pf["benchmark_pct"]) * scale)
            p["drivers"].append(f"mandate targets sum {raw:.1f}%: scaled ×{scale:.3f} pro rata "
                                f"to {MANDATE_CAP_PCT:g}% ({before:.1f}% → "
                                f"{pf['target_pct']:.1f}%)")
            if pf["current_pct"] is None:
                continue
            gap = _r(pf["target_pct"] - pf["current_pct"])
            if gap < 0 and _home_off(p):  # home risk_off ladders trims too (S53)
                p["entry"] = dict(_LADDER)
            elif gap <= 0:
                p["entry"] = dict(_NONE)
            pf["delta"] = _delta_text(gap, p["entry"])
    for p in legs:
        pf = p["portfolio"]
        if pf["current_pct"] is None:
            continue
        gap = _r(pf["target_pct"] - pf["current_pct"])
        if abs(gap) > TRANSITION_PT:
            p["entry"] = dict(_LADDER)
            pf["delta"] = _delta_text(gap, p["entry"])
            p["drivers"].append(f"move of {abs(gap):.1f}pt to target is above "
                                f"{TRANSITION_PT:g}pt: laddered over {LADDER_TRANCHES} tranches")
    return {**mandate_summary(stances, bm), "scale": _r(scale, 4)}


def dumps(payload: Mapping) -> str:
    """Canonical text of a payload: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
