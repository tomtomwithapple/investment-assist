"""Diversification without redundancy (PLAN S81, phase O; the user's principle, 2026-11-10).

Several names of one industry and one size are one bet held several times. A different size or
a different market is a different bet, and where a tested tilt favours a sector or industry the
concentration is deliberate.

- **Group** = (industry, size bucket). The industry is idx-method's IDX-IC `industry` (58
  groups); the size bucket is `large` at `SIZE_LINES["large"]` of market cap or more, `mid` from
  `SIZE_LINES["mid"]`, else `small`. No industry or no market cap: no group, never redundant.
  Each market is judged alone, so a US name is never redundant with an Indonesian one.
- **Order within a group**: names a placebo-passing screen keeps (higher margin first), then
  names it ranked but did not keep (higher margin first), then unrated names by dividend
  yield (higher first; user 2026-11-10, in place of the largest holding), a name with no yield
  after those with one, then the larger holding, then by symbol. The first is the
  **keeper**; the rest are **redundant**.
- **Tilt exception** (user 2026-11-10: only a favourable tilt): a redundant name is `allowed`
  when a passed tilt favours its sector (tilt > 0) or its industry. There is no industry tilt
  yet, so `industry_tilts` is empty today.

`judge` is pure. What it decides: a redundant name that is not allowed gets no new money
(`sizing.size`) and is first in line when a leg must be cut (`rebalance.ordered_sales`). It
never calls a trim on its own. Hashed by `journal.RULE_GLOBS`; `config()` goes into the payload.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["LEVEL", "SIZE_LINES", "SIZES", "US_SIZE_LINES", "config", "judge", "size_bucket"]

VERSION = "0.2.0"  # 0.2.0: unrated names keep the highest dividend yield
LEVEL = "industry"  # idx-method industry_membership column (58 groups)
SIZES = ("large", "mid", "small")
# IDR market cap. Three buckets and both lines are the user's (2026-11-10).
SIZE_LINES = {"large": 50e12, "mid": 5e12}
# USD market cap for US names (sec-edgar S45): the usual US large / mid lines, $10B and $2B.
# A default, not yet confirmed by the user; the IDR lines would make nearly every US name large.
US_SIZE_LINES = {"large": 10e9, "mid": 2e9}


def config() -> dict:
    return {"diversify_version": VERSION, "level": LEVEL, "size_lines": dict(SIZE_LINES),
            "keeper": "kept by a passing screen (margin), then ranked (margin), then the "
                      "highest dividend yield, then the largest holding",
            "tilt": "a redundant name is allowed only where a passed tilt is favourable (> 0)"}


def size_bucket(mktcap: float | None, lines: Mapping[str, float] | None = None) -> str | None:
    """`lines` in the market cap's own currency (default the IDR `SIZE_LINES`)."""
    lines = lines or SIZE_LINES
    if mktcap is None or not mktcap > 0:
        return None
    if mktcap >= lines["large"]:
        return "large"
    return "mid" if mktcap >= lines["mid"] else "small"


def _rank(sym: str, kept: Mapping[str, float], ranked: Mapping[str, float | None],
          held: Mapping[str, float], profiles: Mapping[str, Mapping[str, Any]]) -> tuple:
    if sym in kept:
        return (0, -kept[sym], 0.0, sym)
    if sym in ranked and ranked[sym] is not None:
        return (1, -ranked[sym], 0.0, sym)
    y = (profiles.get(sym) or {}).get("div_yield")
    has = isinstance(y, (int, float)) and not isinstance(y, bool) and y > 0
    return (2 if has else 3, -float(y) if has else 0.0, -float(held.get(sym, 0.0)), sym)


def judge(symbols: Iterable[str], profiles: Mapping[str, Mapping[str, Any]], *,
          kept: Mapping[str, float] | None = None,
          ranked: Mapping[str, float | None] | None = None,
          held: Mapping[str, float] | None = None,
          sector_tilts: Mapping[str, float] | None = None,
          industry_tilts: Mapping[str, float] | None = None,
          size_lines: Mapping[str, float] | None = None) -> list[dict]:
    """One verdict per symbol, by symbol. `profiles` is sym → {sector, industry, mktcap, div_yield};
    `kept` sym → margin of the names a passing screen keeps; `ranked` sym → margin of every name
    a passing screen ranked; `held` IDR held per symbol; `sector_tilts` / `industry_tilts` the
    applied tilt per sector / industry of a **passed** tilt only; `size_lines` the market's
    lines in the profiles' market-cap currency (default IDR `SIZE_LINES`)."""
    kept, ranked, held = kept or {}, ranked or {}, held or {}
    sector_tilts, industry_tilts = sector_tilts or {}, industry_tilts or {}
    groups: dict[tuple[str, str], list[str]] = {}
    info: dict[str, dict] = {}
    for sym in sorted(set(symbols)):
        p = profiles.get(sym) or {}
        size = size_bucket(p.get("mktcap"), size_lines)
        ind = p.get(LEVEL)
        info[sym] = {"symbol": sym, "sector": p.get("sector"), "industry": ind,
                     "mktcap": p.get("mktcap"), "size": size, "div_yield": p.get("div_yield")}
        if ind and size:
            groups.setdefault((str(ind), size), []).append(sym)
    out = []
    for sym, base in info.items():
        key = (str(base["industry"]), base["size"]) if base["industry"] and base["size"] else None
        members = [sym]
        if key:
            members = sorted(groups[key], key=lambda s: _rank(s, kept, ranked, held, profiles))
        position = members.index(sym) + 1
        redundant = position > 1
        favoured = (sector_tilts.get(base["sector"], 0.0) > 0
                    or industry_tilts.get(base["industry"], 0.0) > 0)
        basis = ("kept by a passing screen" if sym in kept else
                 "ranked by a passing screen" if ranked.get(sym) is not None else "unrated")
        out.append({**base, "group_size": len(members), "position": position,
                    "keeper": members[0], "redundant": redundant,
                    "allowed": redundant and favoured, "basis": basis})
    return out
