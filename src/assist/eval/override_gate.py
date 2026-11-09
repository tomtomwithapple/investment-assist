"""The layer-2 override gate (phase L, PLAN S59, P77): may an override's shift cross a stance band?

Phase L choices 1, 3–8 and 10 (accepted by the user 2026-11-09), on the point-in-time override
history (`assist.override_history`, S57/S58 for IDN, S63/S64 abroad):

- **What is tested** (choice 1). The sign of each asset's capped shift, as P17 / P28 compute it:
  an **up** side, shift > 0 (on) against shift ≤ 0 (off), direction +1; a **down** side,
  shift < 0 (on) against shift ≥ 0 (off), direction −1. Each side is gated on its own.
- **Which months** (choice 4). Complete months only (`OverrideRow.complete`, every component of
  the market's spec computed); a partial month is a no_call. The window (choice 5) runs from the
  first complete month to the last month with a full forward return for that asset.
- **Numbers** (choice 3). Phase K's: horizon 3 month ends, stride 3, block 3, `MIN_N` 10 per
  side, t ≥ `T_MIN`, p ≤ `ALPHA` before Holm, 1,000 shuffles, 20 controls, `SEED`
  (`placebo.evaluate`, unchanged).
- **Holm** (choice 6). Over each subject's tests (IDN: 3 assets × 2 sides = 6), family-wise
  `ALPHA`: the smallest p must be ≤ α/m, the next ≤ α/(m−1), …, stopping at the first miss. A
  side's historical verdict passes only if the placebo passes (t, p, control) and Holm does.
- **CLI zeroed** (choice 10). The same test with the `cli` component's points taken out of the
  uncapped sum before the ±10 cap (`zeroed_shift`), its own Holm family; a side passes only if it
  passes both ways (the stored OECD CLI has no vintage, so a pass that needs it may be
  look-ahead).
- **Live monitor and revocation** (choice 7). The journal's `overrides` records carrying this
  override fingerprint, dated from `since` (the first day this fingerprint's file was written) to
  the day before the run, the last record in a month standing for it, priced on the history's
  own forward returns for that month; the same test. State as phase K (`gate._state`,
  `gate._effective`): `revoked` (a pass, with ≥ `REVOKE_N` live windows per side and signed live
  t ≤ `REVOKE_T`), `passed`, `live-passed`, `none` (no history for this fingerprint),
  `insufficient`, `failed`.
- **Fingerprint** (choice 8). One per subject: the AST (docstrings removed) of the override layer
  (`layers/overrides.py` for IDN, `layers/overrides_foreign.py` abroad), `layers/types.py`,
  `override_history.py`, and the gate's numbers. It keys `out/overrides/<SUBJECT>.json`; a file
  for another fingerprint counts as no verdict.

`refresh` reads `out/overrides/<SUBJECT>.json` and rebuilds the history (`build(subject, day)`)
when the file is missing, for another fingerprint, behind the newest month end, or `rebuild`. A
failed build never raises: the cached verdict of the same fingerprint stands (named stale), or
there is none. What a passed side allows (choice 11) is `stance.build_stance`'s business.

Nothing here changes a weight, band or window. Heuristic, not investment advice.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path

import jsonschema

from assist import journal
from assist.eval import placebo
from assist.eval.gate import REVOKE_N, REVOKE_T, _effective, _state
from assist.eval.placebo import ALPHA, MIN_N, Edge, Verdict, edge, evaluate
from assist.history import HORIZON, last_month_end, month_ends
from assist.layers import overrides as idn_layer
from assist.layers import overrides_foreign as foreign_layer
from assist.layers.types import DISCLAIMER, MAX_OVERRIDE, SCHEMA_DIR
from assist.override_history import START, OverrideHistory, OverrideRow

__all__ = [
    "ASSETS",
    "FILES",
    "REVOKE_N",
    "REVOKE_T",
    "SIDES",
    "STATES",
    "OverrideGate",
    "SideTest",
    "combine",
    "evaluate_subject",
    "feature",
    "holm",
    "journal_outputs",
    "live_calls",
    "live_feature",
    "override_fingerprint",
    "refresh",
    "validator",
    "zeroed_shift",
]

SCHEMA_VERSION = "1.0.0"
OVERRIDES_SCHEMA = SCHEMA_DIR / "overrides.schema.json"
SIDES = {"up": 1, "down": -1}  # the shift sign tested as on, and the sign of its claimed edge
STATES = ("passed", "insufficient", "failed", "revoked", "live-passed", "none")
SUBJECTS = ("IDN", "USA", "JPN", "EMU", "AUS", "SGP")
LIVE_SUBJECTS = ("IDN",)  # the subjects `override_history.live_build` can replay
# Choice 13: which assets have a forward return to gate on. No JP / euro-area / AU / SG equity
# index price is in any store, so only USA stocks are gated abroad.
ASSETS = {"IDN": ("stocks", "bonds", "currency"), "USA": ("stocks", "bonds", "currency"),
          **{s: ("bonds", "currency") for s in ("JPN", "EMU", "AUS", "SGP")}}
_FOREIGN_FILES = ("layers/overrides_foreign.py", "layers/types.py", "override_history.py")
FILES = {"IDN": ("layers/overrides.py", "layers/types.py", "override_history.py"),
         **{s: _FOREIGN_FILES for s in SUBJECTS if s != "IDN"}}

Month = tuple[int, int]


def weights(subject: str) -> Mapping[str, Mapping[str, int]]:
    return idn_layer.WEIGHTS if subject == "IDN" else foreign_layer.WEIGHTS


# ---------------- fingerprint ----------------


def gate_params(horizon: int = HORIZON) -> dict:
    return {"horizon": horizon, "stride": horizon, "block": horizon, "min_n": MIN_N,
            "revoke_n": REVOKE_N, "revoke_t": REVOKE_T, "t_min": placebo.T_MIN,
            "alpha": ALPHA, "seed": placebo.SEED, "n_shuffles": 1000, "n_controls": 20,
            "holm": "per subject", "cli_zeroed": True, "start": START.isoformat()}


def override_fingerprint(subject: str, *, root: Path | None = None) -> str:
    """sha256 of the subject's override modules (AST, docstrings removed) and the gate's
    numbers (choice 8)."""
    base = Path(root) if root is not None else journal.PACKAGE_DIR
    files = {rel: journal.code_digest((base / rel).read_bytes(), rel)
             for rel in sorted(FILES[subject])}
    body = {"subject": subject, "kind": "overrides", "files": files, "params": gate_params(),
            "assets": list(ASSETS[subject]), "method": journal.RULES_METHOD}
    return journal.fingerprint(body)


# ---------------- features ----------------


def _cap(x: float) -> float:
    return max(-MAX_OVERRIDE, min(MAX_OVERRIDE, x))


def zeroed_shift(r: OverrideRow, asset: str, subject: str = "IDN") -> float:
    """The asset's shift with the `cli` component's points removed before the ±10 cap."""
    c = r.components.get("cli")
    pts = 0 if c is None else c.direction * weights(subject)["cli"][asset]
    return _cap(r.raw[asset] - pts)


def _on(shift: float, side: str) -> bool:
    return shift > 0 if side == "up" else shift < 0


def feature(r: OverrideRow, asset: str, side: str, *, cli_zeroed: bool = False,
            subject: str = "IDN") -> bool | None:
    """On (the side's sign), off, or None on an incomplete month (no_call)."""
    if not r.complete:
        return None
    shift = zeroed_shift(r, asset, subject) if cli_zeroed else r.shift[asset]
    return _on(shift, side)


# ---------------- Holm ----------------


def holm(ps: Sequence[float], alpha: float = ALPHA) -> list[dict]:
    """Holm's step-down over `ps` (in input order): rank, family size, threshold α/(m−rank+1),
    and whether the test passes (every smaller p passed its own threshold too)."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: (ps[i], i))
    out: dict[int, dict] = {}
    ok = True
    for k, i in enumerate(order):
        thr = alpha / (m - k)
        ok = ok and ps[i] <= thr
        out[i] = {"index": i, "rank": k + 1, "m": m, "threshold": thr, "p": ps[i],
                  "passed": ok}
    return [out[i] for i in range(m)]


def combine(placebo_v: Verdict, holm_r: Mapping, cli_v: Verdict, cli_holm: Mapping) -> Verdict:
    """The side's historical verdict: the placebo verdict, failed when Holm or the CLI-zeroed
    check (its placebo or its Holm) does not pass."""
    if not placebo_v.passed:
        return placebo_v
    if not holm_r["passed"]:
        return dataclasses.replace(placebo_v, passed=False, reason=(
            f"Holm: p {placebo_v.p_value:.3f} > {holm_r['threshold']:.4f} (rank "
            f"{holm_r['rank']} of {holm_r['m']}); placebo alone: {placebo_v.reason}"))
    if not cli_v.passed or not cli_holm["passed"]:
        why = cli_v.reason if not cli_v.passed else (
            f"Holm p {cli_v.p_value:.3f} > {cli_holm['threshold']:.4f}")
        return dataclasses.replace(placebo_v, passed=False, reason=(
            f"cli zeroed does not pass ({why}); with the stored CLI: {placebo_v.reason}"))
    return dataclasses.replace(placebo_v, reason=(
        f"{placebo_v.reason}; Holm rank {holm_r['rank']} of {holm_r['m']} (p ≤ "
        f"{holm_r['threshold']:.4f}); cli zeroed t {cli_v.rule.t:.2f}, p {cli_v.p_value:.3f}"))


def _verdict(feats: Sequence, rets: Sequence[float], horizon: int, direction: int) -> Verdict:
    return evaluate(lambda fs, _rs: list(fs), list(feats), list(rets), stride=horizon,
                    block=horizon, direction=direction)


def _counts(feats: Sequence, horizon: int) -> dict[str, int]:
    picked = list(feats)[::horizon]
    on = sum(1 for f in picked if f is True)
    off = sum(1 for f in picked if f is False)
    return {"on": on, "off": off, "no_call": len(picked) - on - off}


def _short(n: int, need: int) -> int:
    return max(0, need - n)


def _ym(d: date | None) -> str | None:
    return None if d is None else f"{d:%Y-%m}"


def _month(d: date) -> Month:
    return d.year, d.month


# ---------------- live monitor ----------------


def journal_outputs(deltas: Mapping[str, float], raw: Mapping[str, float], complete: bool,
                    cli_direction: int | None, fingerprint: str) -> dict:
    """What an `overrides` journal record carries for the live monitor."""
    return {"deltas": dict(deltas), "raw": dict(raw), "complete": bool(complete),
            "cli_direction": cli_direction, "override_fingerprint": fingerprint}


def live_calls(records: Sequence[Mapping], subject: str, fingerprint: str, *, since: date,
               before: date) -> dict[Month, Mapping]:
    """{(year, month): outputs} of the journal's `overrides` records for `subject` carrying
    `fingerprint`, dated `since` ≤ as_of < `before`; the last record in a month stands."""
    out: dict[Month, Mapping] = {}
    for rec in records:
        o = rec.get("outputs") or {}
        if (rec.get("kind") != "overrides" or rec.get("subject") != subject
                or o.get("override_fingerprint") != fingerprint or not rec.get("as_of")):
            continue
        d = date.fromisoformat(str(rec["as_of"])[:10])
        if since <= d < before:
            out[_month(d)] = o
    return out


def live_feature(o: Mapping, asset: str, side: str, *, cli_zeroed: bool = False,
                 subject: str = "IDN") -> bool | None:
    if not o.get("complete") or asset not in (o.get("deltas") or {}):
        return None
    if not cli_zeroed:
        return _on(float(o["deltas"][asset]), side)
    cli = o.get("cli_direction") or 0
    return _on(_cap(float(o["raw"][asset]) - cli * weights(subject)["cli"][asset]), side)


# ---------------- the gate ----------------


@dataclass(frozen=True)
class SideTest:
    """One subject × asset × side: `verdict` is the effective one (None = none); `historical`
    combines `placebo`, `holm`, `cli_zeroed` and `cli_holm`."""

    asset: str
    side: str
    state: str
    verdict: Verdict | None
    historical: Verdict | None
    placebo: Verdict | None
    cli_zeroed: Verdict | None
    holm: Mapping | None
    cli_holm: Mapping | None
    live: Verdict
    live_edge: Edge
    sample: Mapping[str, Mapping[str, int]]
    distance: Mapping[str, Mapping[str, int]]
    window: tuple[date, date] | None
    why: str

    @property
    def passed(self) -> bool:
        return self.state in ("passed", "live-passed")

    def line(self) -> str:
        h = self.sample.get("historical")
        hist = ("no history for this override" if h is None else
                f"on {h['on']}/{MIN_N}, off {h['off']}/{MIN_N}")
        v = self.placebo
        if v is not None and v.rule.ok:
            hist += f", t {v.rule.t:.2f}, p {v.p_value:.3f}"
            if self.holm is not None:
                hist += f" (Holm {'ok' if self.holm['passed'] else 'no'})"
            if self.cli_zeroed is not None:
                hist += f", cli zeroed t {self.cli_zeroed.rule.t:.2f}"
        return f"{self.asset} {self.side}: {self.state} ({hist})"

    def to_dict(self) -> dict:
        def vd(v: Verdict | None) -> dict | None:
            return None if v is None else v.to_dict()

        return {"asset": self.asset, "side": self.side, "direction": SIDES[self.side],
                "state": self.state, "verdict": vd(self.verdict),
                "historical": vd(self.historical), "placebo": vd(self.placebo),
                "cli_zeroed": vd(self.cli_zeroed),
                "holm": None if self.holm is None else dict(self.holm),
                "cli_holm": None if self.cli_holm is None else dict(self.cli_holm),
                "live": vd(self.live), "live_edge": dataclasses.asdict(self.live_edge),
                "sample": {k: dict(v) for k, v in self.sample.items()},
                "distance": {k: dict(v) for k, v in self.distance.items()},
                "window": None if self.window is None else [_ym(self.window[0]),
                                                            _ym(self.window[1])],
                "why": self.why}


@dataclass(frozen=True)
class OverrideGate:
    """One subject's override gate on `as_of`."""

    subject: str
    as_of: date
    fingerprint: str
    since: date
    tests: Mapping[tuple[str, str], SideTest]
    rows: tuple[OverrideRow, ...] | None
    horizon: int = HORIZON
    stale_inputs: tuple[str, ...] = ()
    store_dates: Mapping[str, str | None] = field(default_factory=dict)

    def test(self, asset: str, side: str) -> SideTest:
        return self.tests[(asset, side)]

    def passed_sides(self, asset: str) -> frozenset[str]:
        """The sides of `asset` whose gate passed (an empty set for an asset not gated)."""
        return frozenset(s for s in SIDES
                         if (asset, s) in self.tests and self.tests[(asset, s)].passed)

    def states(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for (a, s), t in self.tests.items():
            out.setdefault(a, {})[s] = t.state
        return out

    def line(self, asset: str) -> str:
        if (asset, "up") not in self.tests:
            return f"override gate {self.subject} {asset}: not gated (no forward return)"
        return (f"override gate {self.subject} {asset}: "
                + "; ".join(self.test(asset, s).line() for s in SIDES))

    def to_dict(self) -> dict:
        rows = self.rows or ()
        complete = [r for r in rows if r.complete]
        tests: dict[str, dict] = {}
        for (a, s), t in self.tests.items():
            tests.setdefault(a, {})[s] = t.to_dict()
        return journal.jsonable({
            "schema_version": SCHEMA_VERSION, "subject": self.subject,
            "as_of": self.as_of.isoformat(), "override_fingerprint": self.fingerprint,
            "since": self.since.isoformat(), "params": gate_params(self.horizon),
            "assets": list(ASSETS[self.subject]),
            "covers": {"first": _ym(rows[0].as_of) if rows else None,
                       "last": _ym(rows[-1].as_of) if rows else None,
                       "months": len(rows), "complete": len(complete),
                       "complete_from": _ym(complete[0].as_of) if complete else None},
            "passed": {a: sorted(self.passed_sides(a)) for a in ASSETS[self.subject]},
            "tests": tests,
            "stale_inputs": list(self.stale_inputs),
            "store_dates": dict(self.store_dates),
            "rows": None if self.rows is None else [r.to_dict() for r in self.rows],
            "disclaimer": DISCLAIMER,
        })


def window(rows: Sequence[OverrideRow], asset: str) -> tuple[OverrideRow, ...]:
    """First complete month → last month with a forward return for `asset` (choice 5)."""
    first = next((i for i, r in enumerate(rows) if r.complete), None)
    last = next((i for i in range(len(rows) - 1, -1, -1)
                 if rows[i].forward.get(asset) is not None), None)
    if first is None or last is None or last < first:
        return ()
    return tuple(rows[first:last + 1])


def _sample(win: Sequence[OverrideRow], asset: str, side: str, *, cli_zeroed: bool,
            subject: str) -> tuple[list, list[float]]:
    rs = [r for r in win if r.forward.get(asset) is not None]
    return ([feature(r, asset, side, cli_zeroed=cli_zeroed, subject=subject) for r in rs],
            [r.forward[asset] for r in rs])


def _why(side: str, counts: Mapping[str, int] | None, win: Sequence[OverrideRow],
         horizon: int) -> str:
    if counts is None:
        return f"no historical verdict for this override fingerprint ({side} side)"
    span = f"{_ym(win[0].as_of)} → {_ym(win[-1].as_of)}" if win else "no window"
    return (f"{side} side, window {span}: {counts['on']} on / {counts['off']} off / "
            f"{counts['no_call']} no_call on the stride-{horizon} windows; short on "
            f"{_short(counts['on'], MIN_N)}, off {_short(counts['off'], MIN_N)} of {MIN_N}")


def evaluate_subject(subject: str, rows: Sequence[OverrideRow] | None, *,
                     records: Sequence[Mapping], day: date, fingerprint: str, since: date,
                     horizon: int = HORIZON, stale_inputs: Sequence[str] = (),
                     store_dates: Mapping[str, str | None] | None = None) -> OverrideGate:
    """The subject's gate from its history rows (None: no history for this fingerprint) and the
    journal, on `day`."""
    rows = None if rows is None else tuple(rows)
    keys = [(a, s) for a in ASSETS[subject] for s in SIDES]
    calls = live_calls(records, subject, fingerprint, since=since, before=day)
    fwd = {a: {_month(r.as_of): r.forward.get(a) for r in rows or ()} for a in ASSETS[subject]}

    hist: dict = {}
    for a, s in keys:
        if rows is None:
            hist[(a, s)] = None
            continue
        win = window(rows, a)
        f, r = _sample(win, a, s, cli_zeroed=False, subject=subject)
        fz, rz = _sample(win, a, s, cli_zeroed=True, subject=subject)
        span = (win[0].as_of, win[-1].as_of) if win else None
        hist[(a, s)] = (win, span, _verdict(f, r, horizon, SIDES[s]),
                        _verdict(fz, rz, horizon, SIDES[s]), _counts(f, horizon))

    def p_of(v: Verdict) -> float:
        return v.p_value if v.rule.ok else 1.0

    have = [k for k in keys if hist[k] is not None]
    h_main = dict(zip(have, holm([p_of(hist[k][2]) for k in have]), strict=True))
    h_cli = dict(zip(have, holm([p_of(hist[k][3]) for k in have]), strict=True))

    live: dict = {}
    for a, s in keys:
        months = sorted(m for m in calls if fwd[a].get(m) is not None)
        lf = [live_feature(calls[m], a, s, subject=subject) for m in months]
        lr = [fwd[a][m] for m in months]
        live[(a, s)] = (lf, lr)
    live_v = {k: _verdict(*live[k], horizon, SIDES[k[1]]) for k in keys}
    live_h = dict(zip(keys, holm([p_of(live_v[k]) for k in keys]), strict=True))

    tests = {}
    for a, s in keys:
        lf, lr = live[(a, s)]
        lv = live_v[(a, s)]
        if lv.passed and not live_h[(a, s)]["passed"]:
            lv = dataclasses.replace(lv, passed=False, reason=(
                f"Holm: p {lv.p_value:.3f} > {live_h[(a, s)]['threshold']:.4f}"))
        le = edge(lf, lr, stride=horizon, min_n=REVOKE_N, direction=SIDES[s])
        lcounts = _counts(lf, horizon)
        sample = {"live": lcounts}
        distance = {"live": {"on": _short(lcounts["on"], MIN_N),
                             "off": _short(lcounts["off"], MIN_N)},
                    "revoke": {"on": _short(lcounts["on"], REVOKE_N),
                               "off": _short(lcounts["off"], REVOKE_N)}}
        h = hist[(a, s)]
        if h is None:
            win, span, pv, zv, hc, combined, hm, hz = (), None, None, None, None, None, None, None
        else:
            win, span, pv, zv, hc = h
            hm, hz = h_main[(a, s)], h_cli[(a, s)]
            combined = combine(pv, hm, zv, hz)
            sample["historical"] = hc
            distance["historical"] = {"on": _short(hc["on"], MIN_N),
                                      "off": _short(hc["off"], MIN_N)}
        state = _state(combined, lv, le)
        eff = _effective(state, combined, lv, le, since, sample.get("historical"))
        if eff is not None:
            eff = dataclasses.replace(eff, reason=f"{s} side: {eff.reason}")
        tests[(a, s)] = SideTest(a, s, state, eff, combined, pv, zv, hm, hz, lv, le, sample,
                                 distance, span, _why(s, hc, win, horizon))
    return OverrideGate(subject, day, fingerprint, since, tests, rows, horizon,
                        tuple(dict.fromkeys(stale_inputs)), dict(store_dates or {}))


# ---------------- out/overrides ----------------


def path_for(out_dir: Path, subject: str) -> Path:
    return Path(out_dir) / f"{subject}.json"


@cache
def _schema() -> dict:
    return json.loads(OVERRIDES_SCHEMA.read_text(encoding="utf-8"))


def validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(
        _schema(), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


def _load(out_dir: Path | None, subject: str) -> dict | None:
    if out_dir is None:
        return None
    try:
        doc = json.loads(path_for(out_dir, subject).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("rows"), list) else None


def _write(out_dir: Path, g: OverrideGate) -> Path:
    doc = g.to_dict()
    validator().validate(doc)
    text = json.dumps(doc, indent=1, ensure_ascii=False, allow_nan=False) + "\n"
    p = path_for(out_dir, g.subject)
    if p.is_file() and p.read_text(encoding="utf-8") == text:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(p)
    return p


Build = Callable[[str, date], OverrideHistory]


def refresh(day: date, out_dir: Path | None, subject: str, *, records: Sequence[Mapping],
            build: Build | None, fingerprint: str | None = None, rebuild: bool = False,
            horizon: int = HORIZON) -> OverrideGate:
    """The subject's gate on `day`, read from and written to `out_dir` (None: in memory).
    `build(subject, day)` replays the override history with its forward returns; it runs when
    the file is missing, for another fingerprint, behind the newest month end, or `rebuild`.
    Never raises for a failed build."""
    fp = fingerprint or override_fingerprint(subject)
    newest = month_ends(START, last_month_end(day))[-1]
    doc = _load(out_dir, subject)
    rows: tuple[OverrideRow, ...] | None = None
    store_dates: Mapping[str, str | None] = {}
    since, why = day, None
    if doc is not None and doc.get("override_fingerprint") == fp:
        rows = tuple(OverrideRow.from_dict(r) for r in doc["rows"])
        since = date.fromisoformat(doc["since"])
        store_dates = doc.get("store_dates") or {}
    else:
        why = ("no out/overrides file" if doc is None
               else "out/overrides file is for another override fingerprint")
    stale: list[str] = []
    todo = rebuild or rows is None or not rows or rows[-1].as_of < newest
    if todo:
        if build is None:
            fail = "no override history builder"
        else:
            try:
                h = build(subject, day)
                rows, store_dates, fail = tuple(h.rows), dict(h.store_dates), None
            except Exception as e:  # noqa: BLE001 - the run goes on with what is cached
                first = str(e).splitlines()[0][:200] if str(e) else ""
                fail = f"rebuild failed: {type(e).__name__}: {first}"
        if fail is not None:
            if rows is not None:
                stale.append(f"override history {subject}: covers to "
                             f"{_ym(rows[-1].as_of) if rows else '-'}, newest month end "
                             f"{_ym(newest)} ({fail})")
            else:
                stale.append(f"override history {subject}: no verdict for this override "
                             f"({why}; {fail})")
    g = evaluate_subject(subject, rows, records=records, day=day, fingerprint=fp, since=since,
                         horizon=horizon, stale_inputs=stale, store_dates=store_dates)
    if out_dir is not None and rows is not None:
        _write(out_dir, g)
    return g
