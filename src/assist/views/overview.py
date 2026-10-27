"""The overview page (/): the regime and dollar banner, a country x asset stance grid and the
commodities below it, from `brief.load_out(app.out_dir)` (out/{SUBJECT}/*.json only).

Regime and dollar are printed as the brief prints them (one value, or mixed and grouped by
value). A country row is any subject with a non-commodities stance, in the brief's order (IDN
first); a missing cell is "-". A cell with stale inputs carries a "stale" chip whose tooltip
names them. Files that fail to load are a notice, never a 500. The .json twin is the rows used.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from urllib.parse import quote

from assist import brief, web
from assist.web import esc

TITLE = "Assist Overview"
COLUMNS = ("stocks", "bonds", "currency")
STANCES = ("overweight", "neutral", "underweight", "avoid")
TONE = {"overweight": "good", "neutral": "muted", "underweight": "bad", "avoid": "bad"}
EMPTY = "no stances in out/ yet: run `assist run`"
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _href(s: Mapping) -> str:
    return f"/stance/{quote(s['subject'])}/{quote(s['asset'])}"


def _row(s: Mapping) -> dict:
    return {"subject": s["subject"], "asset": s["asset"], "stance": s["stance"],
            "score": s["score"], "confidence": s["confidence"],
            "stale_inputs": list(s["stale_inputs"]), "href": _href(s)}


def build(loaded: brief.Loaded) -> dict:
    """The rows the page shows: banner fields, country rows (one cell per column), commodities."""
    stances = loaded.stances  # sorted by brief._sort_key
    countries: dict[str, dict[str, dict | None]] = {}
    commodities = []
    for s in stances:
        if s["asset"] == "commodities":
            commodities.append(_row(s))
        elif s["asset"] in COLUMNS:
            countries.setdefault(s["subject"], dict.fromkeys(COLUMNS))[s["asset"]] = _row(s)
    counts = Counter(s["stance"] for s in stances)
    return {
        "as_of": max((s["as_of"] for s in stances), default=None),
        "regime": brief._by_value(stances, "regime"),
        "dollar": brief._by_value(stances, "dollar"),
        "counts": {k: counts.get(k, 0) for k in STANCES},
        "columns": list(COLUMNS),
        "countries": [{"subject": k, "cells": v} for k, v in countries.items()],
        "commodities": commodities,
        "problems": list(loaded.problems),
    }


# ---------------- html ----------------


def _grouped(name: str, groups: Mapping[str, list[str]]) -> str:
    """brief._grouped_line as HTML: the bullet dropped, **bold** as <strong>, the rest escaped."""
    line = brief._grouped_line(name, groups).removeprefix("- ")
    return _BOLD.sub(r"<strong>\1</strong>", esc(line))


def _stale(row: Mapping) -> str:
    if not row["stale_inputs"]:
        return ""
    names = "; ".join(row["stale_inputs"])
    return f' <span class="chip warn" title="{esc(names)}">stale</span>'


def _chip(row: Mapping) -> str:
    return web.chip(row["stance"], TONE.get(row["stance"], "muted"))


def _cell(row: Mapping | None) -> str:
    if row is None:
        return "-"
    return (f'<a href="{esc(row["href"])}">{_chip(row)}</a> {esc(brief._num(row["score"]))} '
            f'<span class="muted">'
            f'{float(row["confidence"]):.2f}</span>{_stale(row)}')


def _banner(d: Mapping) -> str:
    counts = " · ".join(f"{n} {k}" for k, n in d["counts"].items() if n)
    return (f'<section class="card banner"><header><h2>As of {esc(d["as_of"])}</h2></header>'
            f'<p>{_grouped("Regime", d["regime"])}<br>{_grouped("Dollar", d["dollar"])}</p>'
            f'<p class="muted">{esc(counts)}</p></section>')


def _grid(d: Mapping) -> str:
    head = "<tr><th>Country</th>" + "".join(f"<th>{esc(c)}</th>" for c in d["columns"]) + "</tr>"
    rows = "".join(
        f'<tr data-subject="{esc(r["subject"])}"><td>{esc(r["subject"])}</td>'
        + "".join(f"<td>{_cell(r['cells'][c])}</td>" for c in d["columns"]) + "</tr>"
        for r in d["countries"])
    return (f'<section class="card"><header><h2>Countries</h2></header>'
            f'<table class="grid">{head}{rows}</table></section>')


def _commodities(d: Mapping) -> str:
    head = "<tr><th>Commodity</th><th>Stance</th><th>Score</th><th>Conf.</th><th></th></tr>"
    rows = "".join(
        f'<tr><td><a href="{esc(r["href"])}">{esc(r["subject"])}</a></td>'
        f'<td>{_chip(r)}</td>'
        f'<td>{esc(brief._num(r["score"]))}</td><td>{float(r["confidence"]):.2f}</td>'
        f"<td>{_stale(r).strip()}</td></tr>"
        for r in d["commodities"])
    return (f'<section class="card"><header><h2>Commodities</h2></header>'
            f'<table class="commodities">{head}{rows}</table></section>')


def body(d: Mapping) -> str:
    parts = ["<h1>Overview</h1>", *(web.notice(p) for p in d["problems"])]
    if not d["countries"] and not d["commodities"]:
        return "".join([*parts, web.notice(EMPTY)])
    parts.append(_banner(d))
    if d["countries"]:
        parts.append(_grid(d))
    if d["commodities"]:
        parts.append(_commodities(d))
    return "".join(parts)


def page(app: web.App, m: re.Match[str]) -> web.View:
    d = build(brief.load_out(app.out_dir))
    return web.View(TITLE, body(d), d)
