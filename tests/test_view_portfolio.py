"""The portfolio page (/portfolio, PLAN S36): totals and dates, weights per asset class and per
stance against the targets (with SVG bars), owners, accounts with masked numbers, statement age,
statement checks, the trade roll-forward, `unheld` and trade-priced lines, unmapped value, trims
and adds from the candidate lists, the .json twin, notices instead of a 500 and escaping.

Reads temp copies of tests/fixtures/ui/portfolio/portfolio.json (schema-valid layer 5 file: two
owners, an unheld line, an unmapped line, a stale statement, a check that differs) as
out/layers/portfolio.json, and of tests/fixtures/ui/candidates/ (IDN has trims, AUS a sized add)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from assist import web
from assist.views import portfolio as view

UI = Path(__file__).parent / "fixtures" / "ui"
EVIL = "<script>alert(1)</script>"


@pytest.fixture
def out(tmp_path) -> Path:
    o = tmp_path / "out"
    (o / "layers").mkdir(parents=True)
    shutil.copy(UI / "portfolio" / "portfolio.json", o / "layers" / "portfolio.json")
    shutil.copytree(UI / "candidates", o / "candidates")
    return o


def _get(out: Path, path: str) -> web.Response:
    app = web.App(out_dir=out, snapshots_dir=out / "none", journal_path=out / "none",
                  paper=lambda until: None, health=lambda: None)
    return web.dispatch(app, web.ROUTES, path)


def _card(html: str, name: str) -> str:
    m = re.search(rf'<section class="card {name}">(.*?)</section>', html, re.S)
    assert m, f"no {name} card"
    return m.group(1)


def _payload(out: Path) -> dict:
    return json.loads((out / "layers" / "portfolio.json").read_text())


def _put(out: Path, p: dict) -> None:
    (out / "layers" / "portfolio.json").write_text(json.dumps(p))


# ---------------- page ----------------


def test_page_renders_every_section(out):
    r = _get(out, "/portfolio")
    assert r.status == 200
    assert "<h1>Portfolio</h1>" in r.body
    for card in ("summary", "weights", "owners", "accounts", "unmapped", "trades", "sources"):
        _card(r.body, card)
    assert "Heuristic, not investment advice." in r.body
    assert 'href="/flows"' in r.body


def test_summary_totals_and_dates(out):
    s = _card(_get(out, "/portfolio").body, "summary")
    assert "IDR 10,100,000" in s and "2026-11-06" in s and "2026-11-02" in s
    assert "IDR 2,909,617" in s  # broker cash
    assert "valued at last trade price: 2 lines" in s
    assert "sha256:074bfad11c" in s


def test_weights_per_asset_class_and_stance(out):
    w = _card(_get(out, "/portfolio").body, "weights")
    # asset classes: stocks 85.15% vs targets 85.1 + 5 = 90.1; bonds 8.91% vs 15
    assert "85.15%" in w and "90.10%" in w and "8.91%" in w and "15.00%" in w
    # S39: cash has no stance; its target is the cash rest. This fixture predates the mandate
    # block, so the rest is worked out from its rows (old targets sum 105.1%, so no cash rest)
    assert re.search(r"<td>cash</td>.*?5\.94%</td><td class=\"num\">0\.00%</td>", w, re.S)
    assert "targets need not add up" not in w
    assert "= <b>105.10%</b>" in w and "cash rest <b>0.00%</b>" in w
    # stances with a weight, target or entry; GOLD at 0 with nothing to do is folded away
    assert 'href="/stance/IDN/bonds"' in w and 'href="/stance/USA/stocks"' in w
    assert "+6.1pt over 3 tranches" in w and "ladder · 3 tranches, every 10 d" in w
    assert "lump · 1 tranche<" in w
    assert "1 more at 0% with nothing to do" in w
    assert w.index("<details>") < w.index("/stance/GOLD/commodities")
    assert w.count('<svg class="bar"') >= 3 + 4  # 3 asset classes, 4 stances


def test_weights_show_the_mandate_sums_and_cash_rest(out):
    p = _payload(out)
    p["mandate"] = {"benchmark_pct": {"IDN/bonds": 32.0, "IDN/stocks": 48.0, "USA/stocks": 20.0},
                    "targets_pct": {"IDN/bonds": 32.0, "IDN/stocks": 43.0, "USA/stocks": 20.0},
                    "target_sum_pct": 95.0, "cash_pct": 5.0}
    _put(out, p)
    w = _card(_get(out, "/portfolio").body, "weights")
    assert "IDN bonds 32.00% + IDN stocks 43.00% + USA stocks 20.00% = <b>95.00%</b>" in w
    assert "cash rest <b>5.00%</b>" in w
    assert "IDN bonds 32% / IDN stocks 48% / USA stocks 20%" in w
    assert "outside the 80/20 mandate" in w
    assert re.search(r"<td>cash</td>.*?5\.94%</td><td class=\"num\">5\.00%</td>", w, re.S)
    assert view.mandate(p)["cash_pct"] == 5.0
    assert json.loads(_get(out, "/portfolio.json").body)["portfolio"]["mandate"] == p["mandate"]


def test_bar_scales_current_and_target():
    svg = view.bar(50, 25)
    assert 'class="cur" x="0" y="2" width="80.0"' in svg
    assert 'x1="40.0"' in svg  # target tick
    assert 'width="0.0"' in view.bar(None, None) and "<line" not in view.bar(None, None)
    assert 'width="160.0"' in view.bar(250, 10)  # clipped


def test_owners(out):
    o = _card(_get(out, "/portfolio").body, "owners")
    assert "priskila" in o and "tommy" in o
    assert "5,000,000" in o and "49.50%" in o and "5,100,000" in o and "50.50%" in o
    assert "IDN bonds 900,000" in o


def test_accounts_masked_aged_checked_and_rolled(out):
    a = _card(_get(out, "/portfolio").body, "accounts")
    assert "<h3>priskila</h3>" in a and "<h3>tommy</h3>" in a
    assert "ajaib ·…6FXF" in a and "stockbit ·…8825" in a
    # statement age from the run day: 2026-07-31 is 98 days → flagged; 4 days is plain
    assert '<span class="chip warn">98 d</span>' in a and "<td>4 d</td>" in a
    # checks: matches, differs (with both totals), no stated total
    assert '<span class="chip good">matches</span>' in a
    assert '<span class="chip bad">differs</span>' in a
    assert "lines 1,000,000 vs stated 1,100,000" in a
    assert "no stated total" in a
    # roll-forward
    assert "from 2026-10-31 through 1 trade doc<" in a
    assert "from nothing through 8 trade docs" in a


def test_holdings_unheld_and_trade_priced(out):
    a = _card(_get(out, "/portfolio").body, "accounts")
    assert "ASTRA INTERNATIONAL Tbk" in a and "2,400,000" in a and "23.76%" in a
    assert "1 line sold below zero (unheld)" in a
    assert "ARNA" in a and "-50,000" in a
    assert "<details open><summary>ajaib ·…6FXF: 2 lines, IDR 4,100,000, 1 unheld" in a
    assert "† 2 lines valued at the last trade price" in a
    assert '<span class="chip warn">unmapped</span>' in a  # MYST has no bucket


def test_unmapped(out):
    u = _card(_get(out, "/portfolio").body, "unmapped")
    assert "IDR 100,000" in u and "bnisek MYST (USD)" in u


def test_trims_and_adds_from_candidates(out):
    t = _card(_get(out, "/portfolio").body, "trades")
    idn = t[t.index('href="/candidates/IDN"'):t.index('href="/candidates/USA"')]
    assert "AMRT" in idn and "1,848,000" in idn and "trim in full: fails its screen" in idn
    assert "trim to the per-name cap of 5%" in idn
    aus = t[t.index('href="/candidates/AUS"'):]
    assert "JPFA" in aus and "1,500,000" in aus and "quarter-Kelly, capped at 5%" in aus
    assert "<td class=\"num\">3</td>" in aus  # tranches
    assert "no adds" in idn and "no trims" in aus


def test_json_twin(out):
    r = _get(out, "/portfolio.json")
    assert r.status == 200 and r.ctype == "application/json"
    d = json.loads(r.body)
    assert d["problem"] is None and d["portfolio"]["total_idr"] == 10100000.0
    by = {c["market"]: c for c in d["candidates"]}
    assert [t["symbol"] for t in by["IDN"]["trims"]] == ["AMRT", "BBNI", "BMRI"]
    assert by["AUS"]["adds"] == [{"symbol": "JPFA", "name": None, "style": by["AUS"]["adds"][0][
        "style"], "idr": 1500000.0, "tranches": 3, "reason": "quarter-Kelly, capped at 5%"}]


# ---------------- failures ----------------


def test_missing_file_is_a_notice(out):
    (out / "layers" / "portfolio.json").unlink()
    r = _get(out, "/portfolio")
    assert r.status == 200 and view.EMPTY in r.body.replace("&#x27;", "'").replace("&#96;", "`")
    _card(r.body, "trades")  # trims still shown
    assert json.loads(_get(out, "/portfolio.json").body)["portfolio"] is None


def test_no_files_at_all(tmp_path):
    r = _get(tmp_path / "nothing", "/portfolio")
    assert r.status == 200 and 'class="notice"' in r.body and "no candidate lists" in r.body


@pytest.mark.parametrize("text, msg", [("{not json", "is not valid JSON"),
                                       ("[1, 2]", "is not a JSON object")])
def test_invalid_file_is_a_notice(out, text, msg):
    (out / "layers" / "portfolio.json").write_text(text)
    r = _get(out, "/portfolio")
    assert r.status == 200 and msg in r.body


def test_builder_stub_is_a_notice(out):
    p = {k: _payload(out)[k] for k in ("schema_version", "kind", "as_of", "model_fingerprint",
                                       "stale_inputs", "sources", "disclaimer")}
    _put(out, {**p, "error": "KeyError: 'x'"})
    r = _get(out, "/portfolio")
    assert r.status == 200 and "layer 5 failed in the last run: KeyError: &#x27;x&#x27;" in r.body


def test_schema_mismatch_still_renders_with_absent_fields(out):
    p = _payload(out)
    del p["checks"], p["by_owner"]
    p["accounts"][0].pop("trade_docs")
    p["stale_inputs"] = ["financer (missing)"]
    _put(out, p)
    r = _get(out, "/portfolio")
    assert r.status == 200 and "does not match the schema" in r.body
    assert "stale input: financer (missing)" in r.body
    assert "no owners" in _card(r.body, "owners")
    assert "no check" in _card(r.body, "accounts")


def test_long_account_numbers_are_masked_again(out):
    p = _payload(out)
    p["accounts"][0]["account"] = "1234567890"
    _put(out, p)
    body = _get(out, "/portfolio").body
    assert "1234567890" not in body and "ajaib ·…7890" in body
    assert "1234567890" not in _get(out, "/portfolio.json").body
    assert view.mask("…6FXF") == "…6FXF" and view.mask("24NP") == "24NP" and view.mask(None) == ""


def test_every_value_is_escaped(out):
    p = _payload(out)
    p["accounts"][0]["holdings"][0]["name"] = EVIL
    p["accounts"][0]["issuer"] = EVIL
    p["by_owner"][0]["owner"] = EVIL
    p["accounts"][3]["owner"] = EVIL
    p["unmapped"][0]["label"] = EVIL
    p["notes"] = [EVIL]
    p["stances"][0]["delta"] = EVIL
    p["stances"][0]["subject"] = EVIL
    p["stale_inputs"] = [EVIL]
    _put(out, p)
    c = json.loads((out / "candidates" / "IDN.json").read_text())
    c["sizing"]["trims"][0]["reason"] = EVIL
    (out / "candidates" / "IDN.json").write_text(json.dumps(c))
    r = _get(out, "/portfolio")
    assert r.status == 200
    assert "<script>" not in r.body and "&lt;script&gt;" in r.body


def test_stance_rows_split_the_gap_into_rebalance_and_tilt(out):
    """PLAN S42: rows carrying rebalance_pt / tilt_pt show the split under the delta; older
    rows without them show the delta alone."""
    p = _payload(out)
    for s in p["stances"]:
        if (s["subject"], s["asset"]) == ("IDN", "stocks"):
            s.update(current_pct=96.9, target_pct=45.7, delta="-51.2pt trim over 3 tranches",
                     benchmark_pct=48.0, rebalance_pt=-51.2, tilt_pt=0.0)
        if (s["subject"], s["asset"]) == ("USA", "stocks"):
            s.update(current_pct=0.0, target_pct=23.8, delta="+23.8pt over 3 tranches",
                     benchmark_pct=20.0, rebalance_pt=19.0, tilt_pt=4.8)
    _put(out, p)
    w = _card(_get(out, "/portfolio").body, "weights")
    assert "-51.2pt = -51.2pt rebalance to benchmark, +0.0pt tilt" in w
    assert "+23.8pt = +19.0pt rebalance to benchmark, +4.8pt tilt" in w
    assert "rebalance to benchmark" not in _card(_get(out, "/portfolio").body, "summary")
    # the IDN bonds row predates S42: its delta alone
    assert "+6.1pt over 3 tranches</td>" in w


def test_stance_page_shows_the_split(tmp_path):
    """PLAN S42: the stance page's portfolio block has a Rebalance vs tilt row when the payload
    carries the split (tests/test_view_stance.py is outside this slice)."""
    src = UI / "out"
    o = tmp_path / "out"
    shutil.copytree(src, o)
    f = o / "IDN" / "bonds.json"
    s = json.loads(f.read_text())
    s["portfolio"].update(current_pct=3.1, target_pct=30.5, benchmark_pct=32.0,
                          rebalance_pt=27.4, tilt_pt=0.0)
    f.write_text(json.dumps(s))
    app = web.App(out_dir=o, snapshots_dir=UI / "snapshots", journal_path=o / "none",
                  paper=lambda until: None, health=lambda: None)
    body = web.dispatch(app, web.ROUTES, "/stance/IDN/bonds").body
    assert "Rebalance vs tilt</th><td>+27.4pt = +27.4pt rebalance to benchmark, +0.0pt tilt" \
        in body
    plain = web.dispatch(web.App(out_dir=src, snapshots_dir=UI / "snapshots",
                                 journal_path=src / "none", paper=lambda until: None,
                                 health=lambda: None), web.ROUTES, "/stance/IDN/bonds").body
    assert "Rebalance vs tilt" not in plain


def test_route_is_registered():
    assert any(rx.pattern == r"^/portfolio$" for rx, _ in web.ROUTES)
    assert _get(Path("/nonexistent"), "/portfolio/x").status == 404
