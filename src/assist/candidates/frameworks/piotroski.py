"""Point-in-time Piotroski F-score (P112, PLAN S95; frameworks document §2.1). Context only:
role `context`, gate `untested`; it changes no stance, size or quality floor.

On date d the newest quarter t is the newest `factor_series` quarter knowable by d (period end
+ `LAG_DAYS` 120, `Fundamentals.available`); t4 and t8 are the quarter ends one and two years
earlier. Flows are trailing twelve months (TTM), stocks are balance sheets, and every change is
year on year (t against t4), so seasonality cancels.

Signal (pass if) — items read, and the stand-ins:

1. ROA: NI TTM(t) / TA(t4) > 0. `factor_series` `ni_ttm` (net income to the parent; the store
   has no extraordinary items, so NI stands in for NI before them) and `total_assets`.
2. CFO: CFO TTM(t) / TA(t4) > 0. `cfo_ttm`.
3. ΔROA: ROA(t) > NI TTM(t4) / TA(t8).
4. Accrual: CFO TTM(t) > NI TTM(t).
5. ΔLeverage: total debt / average TA falls. `total_debt` stands in for long-term debt; no
   debt in either year passes (there is no leverage to fall).
6. ΔCurrent ratio: CA/CL(t) > CA/CL(t4). `fundamentals` `current_assets`,
   `current_liabilities`.
7. No issuance: shares(t) <= shares(t4) × 1.01. `shares_bs`, else `is.shares`; the 1% absorbs
   rounding and ESOP grants, a rights issue counts as issuance.
8. ΔGross margin: GP / revenue over the TTM rises. `gross_profit`, `revenue`, each the sum of
   four discrete quarters.
9. ΔAsset turnover: revenue TTM / beginning TA rises. As 8, with `total_assets`.

Total assets come from `factor_series`, never `fundamentals` `bs.assets`, which does not equal
liabilities plus equity in 92% of its rows (BBRI 63T against ~2,100T). A TTM flow needs all four
quarters present; a missing one is never filled in. A share count that is a whole multiple (×2
or more, within 1%) of the year before is a split or a bonus issue as likely as a rights issue,
so signal 7 is not counted then.

**Missing inputs.** A signal whose inputs are missing is None and flagged, and is not counted:
`score` is F, the signals passed, out of `computable`. Below `MIN_COMPUTABLE` (6) the score is
None and the signal n/a (§0.3), the partial F kept as `f_partial`. Six is a bank's seven minus
one gap: a bank with full data is always scored (phase P rule 5 needs its F), and a non-bank may
miss three. Below six a floor of 4 or 5 judges mostly which signals were missing.

**Banks** (phase Q decision 1): signal 6 (no current ratio in a bank balance sheet) and 8 (a
bank has no cost of goods; Stockbit's "gross profit" is net interest income) are flagged and not
counted, so a bank scores out of 7 and phase P rule 5's F >= 4 reads the same F. Asset turnover
(revenue is interest and fee income over assets) is kept.

`signal`: "strong" when F >= computable − 1, "weak" when F <= 1, else "neutral" (the
document's 8 and 1 on nine).

Hashed by `journal.RULE_GLOBS` (`candidates/**/*.py`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from assist.candidates.frameworks.base import Framework, FrameworkResult, inputs_for, register

__all__ = ["MIN_COMPUTABLE", "SHARE_TOLERANCE", "SIGNALS", "STATEMENT_ITEMS", "Piotroski",
           "PiotroskiInputs", "banks_from", "compare", "fscore", "history", "shift"]

VERSION = "0.1.0"
NAME = "piotroski_f"
MIN_COMPUTABLE = 6
SHARE_TOLERANCE = 0.01
SIGNALS = ("s1_roa", "s2_cfo", "s3_droa", "s4_accrual", "s5_dlever", "s6_dcurrent",
           "s7_no_issue", "s8_dmargin", "s9_dturnover")
BANK_NA = ("s6_dcurrent", "s8_dmargin")
STATEMENT_ITEMS = ("revenue", "gross_profit", "current_assets", "current_liabilities",
                   "shares_bs", "shares")
_QE = ((3, 31), (6, 30), (9, 30), (12, 31))


def shift(d: date, n: int) -> date:
    """The calendar quarter end `n` quarters before quarter end `d` (negative: after)."""
    i = d.year * 4 + (d.month - 1) // 3 - n
    y, q = divmod(i, 4)
    return date(y, *_QE[q])


@dataclass(frozen=True)
class PiotroskiInputs:
    """What the F-score reads on `as_of`: `factor_series` quarters per symbol
    (`IdxMethodSeries.quarterly`), `fundamentals` statements per symbol {period end: {item:
    value}} (`IdxMethodSeries.statements`), and which symbols are banks."""

    as_of: date
    quarters: Mapping[str, Sequence] = field(default_factory=dict)
    statements: Mapping[str, Mapping[date, Mapping[str, float]]] = field(default_factory=dict)
    banks: frozenset[str] = frozenset()


def banks_from(factors: Mapping[str, Mapping]) -> frozenset[str]:
    """Banks as `screens.passes_quality` tells them: the screener reports a CAR."""
    return frozenset(s for s, r in factors.items() if r.get("car"))


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b <= 0:
        return None
    return a / b


def _ttm(st: Mapping[date, Mapping[str, float]], t: date, item: str) -> float | None:
    vals = [(st.get(shift(t, k)) or {}).get(item) for k in range(4)]
    return None if any(v is None for v in vals) else sum(vals)


def _shares(row: Mapping[str, float] | None) -> float | None:
    row = row or {}
    v = row.get("shares_bs") or row.get("shares")
    return v if v is not None and v > 0 else None


def _bit(ok: bool) -> float:
    return 1.0 if ok else 0.0


def fscore(sym: str, quarters: Sequence, statements: Mapping[date, Mapping[str, float]] | None,
           d: date, *, bank: bool = False) -> FrameworkResult:
    """The F-score of `sym` as knowable on `d` (see the module docstring)."""
    fw = Piotroski()
    known = [q for q in quarters if q.available <= d]
    if not known:
        return fw.missing(sym, None, f"no quarterly fundamentals available by {d}")
    cur = max(known, key=lambda q: q.period)
    t = cur.period
    by = {q.period: q for q in known}
    q4, q8 = by.get(shift(t, 4)), by.get(shift(t, 8))
    st = {p: v for p, v in (statements or {}).items() if p <= t}
    c: dict[str, float | None] = dict.fromkeys(SIGNALS)
    flags: list[str] = []

    def need(sig: str, what: str, *vals) -> bool:
        if any(v is None for v in vals):
            flags.append(f"{sig}: no {what}")
            return False
        return True

    ta_b = q4.total_assets if q4 else None
    roa = _div(cur.ni_ttm, ta_b)
    cfo_ta = _div(cur.cfo_ttm, ta_b)
    roa_prior = _div(q4.ni_ttm if q4 else None, q8.total_assets if q8 else None)
    c |= {"roa": roa, "cfo_ta": cfo_ta, "roa_prior": roa_prior}
    if need("s1", f"NI TTM or total assets a year before {t}", roa):
        c["s1_roa"] = _bit(roa > 0)
    if need("s2", f"CFO TTM or total assets a year before {t}", cfo_ta):
        c["s2_cfo"] = _bit(cfo_ta > 0)
    if need("s3", f"ROA a year before {t}", roa, roa_prior):
        c["s3_droa"] = _bit(roa > roa_prior)
    if need("s4", f"CFO or NI TTM at {t}", roa, cfo_ta):
        c["s4_accrual"] = _bit(cur.cfo_ttm > cur.ni_ttm)

    avg = (None if cur.total_assets is None or ta_b is None else (cur.total_assets + ta_b) / 2)
    avg_p = (None if ta_b is None or q8 is None or q8.total_assets is None
             else (ta_b + q8.total_assets) / 2)
    lev = _div(cur.total_debt, avg)
    lev_p = _div(q4.total_debt if q4 else None, avg_p)
    c |= {"leverage": lev, "leverage_prior": lev_p}
    if need("s5", f"total debt or total assets at {t} and a year before", lev, lev_p):
        if lev == 0 and lev_p == 0:
            flags.append("s5: no debt either year, counted as a pass")
            c["s5_dlever"] = 1.0
        else:
            c["s5_dlever"] = _bit(lev < lev_p)

    now, then = st.get(t) or {}, st.get(shift(t, 4)) or {}
    if bank:
        flags.append("bank: s6 current ratio and s8 gross margin not meaningful, not counted")
    else:
        cr = _div(now.get("current_assets"), now.get("current_liabilities"))
        cr_p = _div(then.get("current_assets"), then.get("current_liabilities"))
        c |= {"current_ratio": cr, "current_ratio_prior": cr_p}
        if need("s6", f"current assets or liabilities at {t} and a year before", cr, cr_p):
            c["s6_dcurrent"] = _bit(cr > cr_p)

    sh, sh_p = _shares(now), _shares(then)
    ratio = _div(sh, sh_p)
    c["shares_ratio"] = ratio
    if need("s7", f"share count at {t} and a year before", ratio):
        k = round(ratio)
        if k >= 2 and abs(ratio - k) <= SHARE_TOLERANCE * k:
            flags.append(f"s7: share count x{k}: a split or bonus issue as likely as a rights"
                         " issue, not counted")
        else:
            c["s7_no_issue"] = _bit(ratio <= 1 + SHARE_TOLERANCE)

    rev, rev_p = _ttm(st, t, "revenue"), _ttm(st, shift(t, 4), "revenue")
    if not bank:
        gm = _div(_ttm(st, t, "gross_profit"), rev)
        gm_p = _div(_ttm(st, shift(t, 4), "gross_profit"), rev_p)
        c |= {"gross_margin": gm, "gross_margin_prior": gm_p}
        if need("s8", "four quarters of revenue and gross profit in each of the two years to"
                f" {t}", gm, gm_p):
            c["s8_dmargin"] = _bit(gm > gm_p)
    ato = _div(rev, ta_b)
    ato_p = _div(rev_p, q8.total_assets if q8 else None)
    c |= {"asset_turnover": ato, "asset_turnover_prior": ato_p}
    if need("s9", f"four quarters of revenue in each of the two years to {t}, or total assets",
            ato, ato_p):
        c["s9_dturnover"] = _bit(ato > ato_p)

    done = [c[s] for s in SIGNALS if c[s] is not None]
    n, f = len(done), sum(done)
    c["computable"] = float(n)
    if n < MIN_COMPUTABLE:
        c["f_partial"] = float(f)
        return fw.missing(sym, cur.available,
                          f"only {n} of 9 signals computable (minimum {MIN_COMPUTABLE})", *flags,
                          components=c)
    signal = "strong" if f >= n - 1 else "weak" if f <= 1 else "neutral"
    return fw.result(sym, cur.available, float(f), signal, c, *flags)


def history(sym: str, inputs: PiotroskiInputs, dates: Iterable[date] | None = None
            ) -> list[FrameworkResult]:
    """`sym`'s F-score on each of `dates`, or by default once per report: on each quarter's
    `available` date, oldest first (S87's two reports in a row, S88's bank floor)."""
    qs = sorted(inputs.quarters.get(sym) or (), key=lambda q: q.period)
    if dates is None:
        dates = [q.available for q in qs]
    st = inputs.statements.get(sym) or {}
    bank = sym in inputs.banks
    return [fscore(sym, qs, st, d, bank=bank) for d in dates]


def compare(ours: Mapping[str, float | None], theirs: Mapping[str, float | None], top: int = 10
            ) -> dict:
    """Agreement with another F-score (Stockbit's) over the names both score: share exactly
    equal, share within 1 point, mean of ours minus theirs, and the `top` largest gaps as
    (sym, ours, theirs). It checks the mapping, not the truth."""
    pairs = [(s, ours[s], theirs[s]) for s in sorted(ours)
             if ours[s] is not None and theirs.get(s) is not None]
    n = len(pairs)
    if not n:
        return {"n": 0, "exact": None, "within_1": None, "mean_diff": None, "largest": []}
    gaps = sorted(pairs, key=lambda p: (-abs(p[1] - p[2]), p[0]))
    return {"n": n, "exact": sum(a == b for _, a, b in pairs) / n,
            "within_1": sum(abs(a - b) <= 1 for _, a, b in pairs) / n,
            "mean_diff": sum(a - b for _, a, b in pairs) / n,
            "largest": [(s, a, b) for s, a, b in gaps[:top]]}


@register
class Piotroski(Framework):
    name = NAME
    VERSION = VERSION

    def evaluate(self, sym: str, inputs) -> FrameworkResult:
        inputs = inputs_for(inputs, NAME)
        if not isinstance(inputs, PiotroskiInputs):
            return self.missing(sym, None, "no point-in-time IDN statements given")
        if sym not in inputs.quarters:
            return self.missing(sym, None, "no quarterly fundamentals for this name")
        return fscore(sym, inputs.quarters[sym], inputs.statements.get(sym), inputs.as_of,
                      bank=sym in inputs.banks)

