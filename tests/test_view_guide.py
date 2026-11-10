"""The home page (/, P94, PLAN S76): this week's steps by order date, from out/guide.json."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from test_guide import cands, name, row, stance

from assist import guide, web
from assist.views import guide as view

DAY = date(2026, 11, 10)


def _app(out: Path) -> web.App:
    return web.App(out_dir=out, snapshots_dir=out / "none", journal_path=out / "none",
                   paper=lambda until: None, health=lambda: None)


def _get(out: Path, path: str = "/") -> web.Response:
    return web.dispatch(_app(out), web.ROUTES, path)


def _write(out: Path) -> dict:
    st = [stance("IDN", "stocks", 60.0, 48.0), stance("IDN", "bonds", 20.0, 32.0),
          stance("USA", "stocks", 14.0, 20.0)]
    names = [name("AAAA", 1000.0, 50_000), name("BMRI", 1000.0, 10_000)]
    trims = [{"symbol": "BMRI", "idr": 5e6, "reason": "trim to the per-name cap of 5%"}]
    usa = cands("USA", rows=[row("MSFT")])
    g = guide.build(DAY, st, [cands(trims=trims, names=names), usa], "sha256:" + "a" * 64)
    guide.write(g, out)
    return g


def test_home_is_this_week_with_the_headline_and_the_legs(tmp_path):
    g = _write(tmp_path)
    r = _get(tmp_path)
    assert r.status == 200 and "<title>Assist This week</title>" in r.body
    assert '<a href="/" class="active">This week</a>' in r.body
    assert "Markets are nervous" in r.body and "every order is split into parts" in r.body
    t = g["totals"]
    assert f"Sell {t['sells']} (Rp 12.0m) and buy {t['buys']}" in r.body
    legs = re.search(r'<section class="card legs">(.*?)</section>', r.body, re.S).group(1)
    assert "<td>Indonesian stocks</td>" in legs and "sell Rp 12.0m" in legs
    assert "buy Rp 12.0m" in legs and "Hold the usual amount" in legs
    assert r.body.count(web.DISCLAIMER) == 1


def test_orders_are_grouped_by_date_first_day_open(tmp_path):
    _write(tmp_path)
    body = _get(tmp_path).body
    days = re.findall(r'<details class="day" data-date="([\d-]+)"( open)?>', body)
    assert days == [("2026-11-11", " open"), ("2026-11-23", ""), ("2026-12-01", "")]
    first = re.search(r'data-date="2026-11-11" open>(.*?)</details>', body, re.S).group(1)
    assert "Sell BMRI" in first and "part 1 of 3" in first and "down to the 5% cap" in first
    assert 'class="chip bad" title="A hard limit is broken' in first  # strong, with its meaning
    assert "at market, not above 1,010" in first  # the buy's first tranche
    second = re.search(r'data-date="2026-11-23">(.*?)</details>', body, re.S).group(1)
    assert "limit 900 or lower" in second
    assert first.index("Sell BMRI") < first.index("Buy MSFT")  # sells first


def test_buys_show_take_profit_and_stop(tmp_path):
    _write(tmp_path)
    card = re.search(r'<section class="card exits">(.*?)</section>', _get(tmp_path).body,
                     re.S).group(1)
    assert "<td>MSFT</td><td>1,260: stop adding and trim to half</td>" in card
    assert "<td>sell when it fails its screen</td><td>800</td>" in card
    assert "not a sell order" in card


def test_by_date_and_the_json_twin(tmp_path):
    g = _write(tmp_path)
    assert sum(len(o) for _, o in view.by_date(g)) == sum(len(s["tranches"]) for s in g["steps"])
    d = json.loads(_get(tmp_path, "/.json").body)
    assert d["problem"] is None and d["guide"]["steps"] == json.loads(json.dumps(g["steps"]))


def test_no_file_is_a_notice_and_a_bad_file_never_a_500(tmp_path):
    r = _get(tmp_path)
    assert r.status == 200 and "no out/guide.json yet: run `assist run`" in r.body
    assert 'href="/background"' in r.body
    (tmp_path / "guide.json").write_text('{"steps": "<script>"}')
    r = _get(tmp_path)
    assert r.status == 200 and "fails the schema" in r.body and "<script>" not in r.body


def test_nothing_to_do(tmp_path):
    guide.write(guide.build(DAY, [stance("IDN", "stocks", 48.0, 48.0)], [cands()], None),
                tmp_path)
    body = _get(tmp_path).body
    assert "Nothing to do this week" in body and 'class="card orders"' not in body
