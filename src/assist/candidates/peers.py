"""Peer comparison (S30): each IDN name against its industry and sector, in four categories.

From Stockbit's `/comparison` (idx-method `api_raw`, `assist.sources.idxmethod_comparison`):

- **valuation**: PE (TTM), PBV, P/S (TTM), EV/EBITDA (TTM); lower is better
- **dividend**: dividend yield, higher is better; payout ratio shown, not scored
- **profitability**: ROE, ROA, ROIC (TTM), net, operating and gross margin (quarter); higher
- **solvency**: debt/equity and liabilities/equity (lower), current ratio, interest cover and
  Altman Z (modified) (higher)

The benchmarks are the industry median and the sector median, computed here over the names that
have a value (at least `min_median`). Stockbit's own industry and sector averages are means that
loss-makers drag below zero (an industry PE of −77 on 2026-10-26), so they are carried beside the
medians as a cross-check and never scored against (as PLAN S15 decided for its peer baseline).

A deviation is log(name / benchmark), never percent. It is None when the benchmark is not
positive, or when the name's value is not positive on a lower-is-better metric (a loss-maker has
no PE to be cheap on). A higher-is-better metric where the name is at or below zero and the
benchmark above it reads as the floor, −log(clamp). Each deviation is clamped to ±log(clamp). A
category score is the mean of its scored deviations, signed so that positive is better (cheaper,
higher yield, more profitable, more solvent), reported with how many metrics fed it.

Context only: no screen, verdict or stance reads this, so it carries no placebo control.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from assist.sources.idxmethod_comparison import Comparison

__all__ = ["CATEGORIES", "CONFIG", "OUT_DIR", "SUBSECTORS", "build", "deviation", "gather_live",
           "subsector", "tier", "write"]

OUT_DIR = "industries"
SCHEMA_VERSION = 1
DISCLAIMER = "Heuristic, not investment advice."
SOURCE = "idx-method api_raw comparison_* (Stockbit /comparison)"
MKTCAP = 2892

CONFIG: dict[str, Any] = {
    "clamp": 4.0,  # a deviation beyond 4x or 1/4x reads as 4x
    "tiers": {"big": 10e12, "mid": 1e12},  # IDR market cap: big >= 10T, mid >= 1T, else small
    "stale_days": 14,
    "min_median": 3,
}

# (category, label, [(key, fid, label, better: "lower" | "higher" | None for not scored)])
CATEGORIES: tuple[tuple[str, str, tuple[tuple[str, int, str, str | None], ...]], ...] = (
    ("valuation", "Valuation", (
        ("pe", 2891, "PE (TTM)", "lower"),
        ("pbv", 2896, "PBV", "lower"),
        ("ps", 2893, "P/S (TTM)", "lower"),
        ("ev_ebitda", 21457, "EV/EBITDA (TTM)", "lower"),
    )),
    ("dividend", "Dividend", (
        ("div_yield", 2915, "Dividend yield %", "higher"),
        ("payout", 2916, "Payout ratio %", None),
    )),
    ("profitability", "Profitability", (
        ("roe", 1461, "ROE % (TTM)", "higher"),
        ("roa", 1460, "ROA % (TTM)", "higher"),
        ("roic", 13447, "ROIC % (TTM)", "higher"),
        ("npm", 1563, "Net margin % (Q)", "higher"),
        ("opm", 1562, "Operating margin % (Q)", "higher"),
        ("gpm", 1561, "Gross margin % (Q)", "higher"),
    )),
    ("solvency", "Solvency", (
        ("der", 1508, "Debt/equity (Q)", "lower"),
        ("liab_equity", 1573, "Liabilities/equity (Q)", "lower"),
        ("current", 1498, "Current ratio (Q)", "higher"),
        ("int_cover", 1484, "Interest cover (TTM)", "higher"),
        ("altman_z", 13402, "Altman Z (modified)", "higher"),
    )),
)
# Stockbit's /comparison carries no industry name. Its industry groups match the IDX sub-sectors
# Stockbit lists in idx-method's data/universe.json one for one, sector by sector (33 on
# 2026-10-26), so a group takes the name of the sub-sector whose anchor names it holds. Anchors
# marked "by elimination" are the one group left in their sector; a group with no anchor is
# named by its sector alone.
SUBSECTORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Barang Baku", ("ANTM", "INTP", "TPIA")),
    ("Media & Hiburan", ("SCMA", "MNCN")),
    ("Perdagangan Ritel", ("MAPI", "ACES", "ERAA")),
    ("Pakaian & Barang Mewah", ("HRTA", "PBRX")),
    ("Otomotif & Komponen Otomotif", ("AUTO", "GJTL", "SMSM")),
    ("Barang Rumah Tangga", ("WOOD", "CINT")),
    ("Jasa Konsumen", ("BUVA", "JSPT", "BLTZ")),
    ("Barang Rekreasi", ("DOSS",)),  # by elimination
    ("Minyak, Gas & Batu Bara", ("ADRO", "BYAN", "PTBA")),
    ("Energi Alternatif", ("ALII", "SEMA")),  # by elimination
    ("Bank", ("BBCA", "BBRI", "BMRI")),
    ("Asuransi", ("TUGU", "LIFE", "ABDA")),
    ("Jasa Pembiayaan", ("BFIN", "ADMF", "WOMF")),
    ("Jasa Investasi", ("TRIM", "PANS", "YULE")),
    ("Perusahaan Holding & Investasi", ("SRTG", "DNET")),
    ("Farmasi & Riset Kesehatan", ("KLBF", "SIDO", "KAEF")),
    ("Jasa & Peralatan Kesehatan", ("MIKA", "SILO", "HEAL")),
    ("Perusahaan Holding Multi Sektor", ("ASII", "BNBR")),
    ("Barang Perindustrian", ("UNTR", "IMPC")),
    ("Jasa Perindustrian", ("ASGR", "JTPE")),
    ("Konstruksi Bangunan", ("TOTL", "SSIA")),
    ("Infrastruktur Transportasi", ("JSMR", "CMNP")),
    ("Telekomunikasi", ("TLKM", "ISAT", "EXCL")),
    ("Utilitas", ("PGEO", "BREN", "POWR")),
    ("Perdagangan Ritel Barang Primer", ("AMRT", "MIDI", "HERO")),
    ("Makanan & Minuman", ("ICBP", "INDF", "MYOR")),
    ("Produk Rumah Tangga Tidak Tahan Lama", ("UNVR", "KINO")),
    ("Rokok", ("HMSP", "GGRM", "WIIM")),
    ("Properti & Real Estat", ("CTRA", "BSDE", "PWON")),
    ("Perangkat Lunak & Jasa TI", ("GOTO", "EMTK", "DCII")),
    ("Perangkat Keras & Peralatan Teknologi", ("PTSN", "MTDL")),
    ("Transportasi", ("GIAA", "BIRD")),
    ("Logistik & Pengantaran", ("TMAS", "SMDR")),  # by elimination
)


def subsector(members: Sequence[str], sector: str) -> str:
    """The first `SUBSECTORS` name with an anchor among `members`; else the sector, else
    'Unknown sector'."""
    have = set(members)
    return next((name for name, anchors in SUBSECTORS if have & set(anchors)),
                sector or "Unknown sector")


METRICS = [(cat, key, fid, better) for cat, _, ms in CATEGORIES for key, fid, _, better in ms]


def tier(mktcap: float | None, tiers: Mapping[str, float] = CONFIG["tiers"]) -> str | None:
    if mktcap is None:
        return None
    return "big" if mktcap >= tiers["big"] else "mid" if mktcap >= tiers["mid"] else "small"


def deviation(value: float | None, bench: float | None, better: str | None,
              clamp: float = CONFIG["clamp"]) -> float | None:
    """log(value / bench), clamped to ±log(clamp); see the module notes for the None cases."""
    if value is None or bench is None or bench <= 0:
        return None
    lim = math.log(clamp)
    if value <= 0:
        return -lim if better == "higher" else None
    return max(-lim, min(lim, math.log(value / bench)))


def _score(devs: Mapping[str, float | None], cat: str) -> tuple[float | None, int]:
    signed = [(-d if better == "lower" else d) for c, key, _, better in METRICS
              if c == cat and better and (d := devs.get(key)) is not None]
    if not signed:
        return None, 0
    return round(sum(signed) / len(signed), 4), len(signed)


def _pick(vals: Mapping[int, float | None]) -> dict[str, float | None]:
    return {key: vals.get(fid) for _, key, fid, _ in METRICS}


def _devs(values: Mapping[str, float | None], bench: Mapping[str, float | None],
          clamp: float) -> dict[str, float | None]:
    out = {}
    for _, key, _, better in METRICS:
        d = deviation(values.get(key), bench.get(key), better or "higher", clamp)
        out[key] = None if d is None else round(d, 4)
    return out


def _median(rows: Sequence[Mapping[str, float | None]], n_min: int) -> dict[str, float | None]:
    out = {}
    for _, key, _, _ in METRICS:
        xs = [v for r in rows if (v := r.get(key)) is not None]
        out[key] = statistics.median(xs) if len(xs) >= n_min else None
    return out


def build(cmp: Comparison, day: date, config: Mapping[str, Any] = CONFIG) -> dict:
    """The `out/industries/IDN.json` payload: sectors with their benchmarks, industries by sector
    then size, names by market cap, each with values, deviations and category scores."""
    clamp, n_min = float(config["clamp"]), int(config["min_median"])
    values = {s: _pick(cmp.ratios.get(s) or {}) for s in cmp.industry}
    caps = {s: (cmp.ratios.get(s) or {}).get(MKTCAP) for s in cmp.industry}
    members: dict[str, list[str]] = defaultdict(list)
    by_sector: dict[str, list[str]] = defaultdict(list)
    for sym, ind in cmp.industry.items():
        members[ind].append(sym)
        by_sector[cmp.sectors.get(sym) or ""].append(sym)
    sectors = {sec: {"n": len(syms),
                     "median": _median([values[s] for s in syms], n_min),
                     "average": _pick(cmp.sector_avg[min(syms)])}
               for sec, syms in sorted(by_sector.items())}

    industries = []
    for ind, syms in members.items():
        syms = sorted(syms, key=lambda s: (-(caps[s] or 0), s))
        names = [cmp.sectors.get(s) or "" for s in syms]
        sector = max(sorted(set(names)), key=names.count)
        median = _median([values[s] for s in syms], n_min)
        stocks = []
        for s in syms:
            sec = cmp.sectors.get(s) or ""
            dev_i = _devs(values[s], median, clamp)
            dev_s = _devs(values[s], sectors[sec]["median"], clamp)
            score_i, score_s, used = {}, {}, {}
            for cat, _, _ in CATEGORIES:
                score_i[cat], used[cat] = _score(dev_i, cat)
                score_s[cat], _ = _score(dev_s, cat)
            stocks.append({
                "symbol": s,
                "name": cmp.names.get(s, ""),
                "sector": sec,
                "mktcap": caps[s],
                "tier": tier(caps[s], config["tiers"]),
                "competitors": cmp.competitors.get(s, []),
                "values": values[s],
                "dev_industry": dev_i,
                "dev_sector": dev_s,
                "score_industry": score_i,
                "score_sector": score_s,
                "scored_metrics": used,
            })
        industries.append({
            "id": ind,
            "label": subsector(syms, sector),
            "sector": sector,
            "n": len(syms),
            "leaders": syms[:3],
            "median": median,
            "average": _pick(cmp.industry_avg[syms[0]]),
            "stocks": stocks,
        })
    industries.sort(key=lambda i: (i["sector"], -i["n"], i["id"]))

    age = (day - cmp.date).days
    stale = ([f"peer comparison as of {cmp.date.isoformat()} ({age} days old)"]
             if age > int(config["stale_days"]) else [])
    return {
        "schema_version": SCHEMA_VERSION,
        "market": "IDN",
        "as_of": cmp.date.isoformat(),
        "built": day.isoformat(),
        "source": SOURCE,
        "config": dict(config),
        "categories": [{"key": cat, "label": label,
                        "metrics": [{"key": k, "fid": f, "label": lb, "better": b}
                                    for k, f, lb, b in ms]}
                       for cat, label, ms in CATEGORIES],
        "sectors": sectors,
        "industries": industries,
        "stale_inputs": stale,
        "disclaimer": DISCLAIMER,
    }


def gather_live(day: date) -> dict:
    """The payload from the real idx-method store (read-only)."""
    from assist.sources.idxmethod_comparison import IdxMethodComparison

    return build(IdxMethodComparison.from_config().latest(), day)


def write(payload: Mapping, out_dir: Path) -> Path:
    """`out/industries/{MARKET}.json`, rewritten only when its bytes change."""
    import json

    path = Path(out_dir) / OUT_DIR / f"{payload['market']}.json"
    text = json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text() == text:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text)
    tmp.replace(path)
    return path
