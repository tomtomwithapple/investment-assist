"""The stance detail page (/stance/<SUBJECT>/<asset>): every field, flags as severity chips, the
.json twin, the change since the previous snapshot, escaping and the 404 cases. Reads
tests/fixtures/ui/out/ and tests/fixtures/ui/snapshots/ (or temp copies); no real out/, store or
network."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from assist import web

UI = Path(__file__).parent / "fixtures" / "ui"
OUT, SNAPSHOTS = UI / "out", UI / "snapshots"
EVIL = "<script>alert(1)</script>"


def _app(out_dir: Path, snapshots_dir: Path = SNAPSHOTS) -> web.App:
    return web.App(out_dir=out_dir, snapshots_dir=snapshots_dir, journal_path=out_dir / "none",
                   paper=lambda until: None, health=lambda: None)


def _get(path: str, out_dir: Path = OUT, snapshots_dir: Path = SNAPSHOTS) -> web.Response:
    return web.dispatch(_app(out_dir, snapshots_dir), web.ROUTES, path)


def _section(html: str, name: str) -> str:
    m = re.search(rf'<section class="card {name}">(.*?)</section>', html, re.S)
    assert m, f"no {name} section"
    return m.group(1)


@pytest.fixture
def out_copy(tmp_path) -> Path:
    out = tmp_path / "out"
    shutil.copytree(OUT, out)
    return out


def test_idn_bonds_headline_fields():
    r = _get("/stance/IDN/bonds")
    assert r.status == 200
    assert "<title>Assist IDN bonds</title>" in r.body
    assert web.DISCLAIMER in r.body
    head = _section(r.body, "summary")
    assert '<span class="chip good">overweight</span>' in head
    assert "As of 2026-10-13" in head
    for text in ("Score</th><td>68", "Layer-1 score</th><td>58", "Confidence</th><td>0.74",
                 "Regime</th><td>neutral", "Dollar</th><td>flat",
                 "Model</th><td><code>sha256:3f2a9c0d1e4b</code>"):
        assert text in head, text
    assert "3f2a9c0d1e4b5" not in r.body  # the fingerprint is shortened


def test_lists_entry_portfolio_and_sources():
    body = _get("/stance/IDN/bonds").body
    assert "<li>real yield 3.1% (82nd pct)</li>" in _section(body, "drivers")
    assert "<li>USD/IDR at 6m high</li>" in _section(body, "risks")
    watch = _section(body, "watch")
    assert "<li>BI meeting 2026-10-22</li>" in watch and "<li>US CPI 2026-10-15</li>" in watch
    entry = _section(body, "entry")
    assert "Style</th><td>ladder" in entry and "Tranches</th><td>3" in entry
    assert "Spacing</th><td>10 days" in entry
    pf = _section(body, "portfolio")
    assert "Current</th><td>8%" in pf and "Target</th><td>15%" in pf
    assert "Delta</th><td>+7pt over 3 tranches" in pf
    src = _section(body, "sources")
    assert "<li>sec-edgar FRED</li>" in src and "<li>financer</li>" in src
    assert "none" in _section(body, "flags") and "none" in _section(body, "stale")


def test_portfolio_notes_shown_and_escaped(out_copy):
    """PLAN S32: layer 5's notes (lines valued at a trade price) in the portfolio block."""
    f = out_copy / "IDN" / "bonds.json"
    s = json.loads(f.read_text())
    s["portfolio"]["notes"] = ["financer ajaib (tommy): valued at last trade price: 1 lines", EVIL]
    f.write_text(json.dumps(s))
    pf = _section(_get("/stance/IDN/bonds", out_dir=out_copy).body, "portfolio")
    assert "Notes</th><td>financer ajaib (tommy): valued at last trade price: 1 lines" in pf
    assert "<script>" not in pf
    assert "Notes" not in _section(_get("/stance/IDN/bonds").body, "portfolio")


def test_usa_bonds_flags_as_severity_chips_and_stale_inputs():
    body = _get("/stance/USA/bonds").body
    flags = _section(body, "flags")
    assert '<span class="chip bad">critical</span>' in flags
    assert "<code>high_gov_debt</code>" in flags and "136% of GDP (&gt; 120%)" in flags
    assert '<span class="chip warn">warn</span>' in flags
    assert '<span class="chip muted">info</span>' in flags
    assert "<li>financer (locked)</li>" in _section(body, "stale")
    pf = _section(body, "portfolio")
    assert "Current</th><td>n/a" in pf and "Target</th><td>0%" in pf


def test_change_since_previous_snapshot():
    change = _section(_get("/stance/IDN/bonds").body, "change")
    # 2026-10-13 is not before as_of, 2026-09-29 is older than 2026-10-06
    assert "2026-10-06" in change and "2026-10-13" not in change and "2026-09-29" not in change
    assert '<span class="chip muted">neutral</span>' in change and "55.5" in change
    assert '<span class="chip good">overweight</span>' in change and "68" in change
    assert "+12.5" in change


def test_change_when_pair_absent_from_snapshot_or_no_snapshot(tmp_path):
    change = _section(_get("/stance/USA/bonds").body, "change")
    assert "not in the 2026-10-06 snapshot" in change
    for snaps in (tmp_path / "missing", tmp_path):
        change = _section(_get("/stance/IDN/bonds", snapshots_dir=snaps).body, "change")
        assert "no earlier snapshot" in change


def test_json_twin_is_the_stance_as_written():
    r = _get("/stance/USA/bonds.json")
    assert r.status == 200 and r.ctype == "application/json"
    assert json.loads(r.body) == json.loads((OUT / "USA" / "bonds.json").read_text())


@pytest.mark.parametrize("path", [
    "/stance/IDN/currency",       # known subject, no such asset
    "/stance/XXX/bonds",          # unknown subject
    "/stance/idn/bonds",          # case sensitive
    "/stance/IDN/BONDS",
    "/stance/IDN/../x",           # what /stance/IDN/..%2Fx decodes to
    "/stance/IDN/..%2Fx",
    "/stance/IDN/..",
    "/stance/../IDN/bonds",
    "/stance/IDN",
    "/stance/IDN/bonds/extra",
    "/stance/IDN/bonds.json/x",
    "/stance/IDN/currency.json",
])
def test_unknown_or_unsafe_paths_are_404(path):
    r = _get(path)
    assert r.status == 404, path
    assert "Not found" in r.body


def test_values_are_escaped(out_copy, tmp_path):
    f = out_copy / "USA" / "bonds.json"
    s = json.loads(f.read_text())
    s["drivers"] = [EVIL]
    s["risks"] = [EVIL]
    s["watch"] = [EVIL]
    s["sources"] = [EVIL]
    s["stale_inputs"] = [EVIL]
    s["portfolio"]["delta"] = EVIL
    s["flags"] = [{"code": "x", "message": EVIL, "severity": "warn"}]
    f.write_text(json.dumps(s))
    r = _get("/stance/USA/bonds", out_dir=out_copy)
    assert r.status == 200
    assert "<script>" not in r.body
    assert r.body.count("&lt;script&gt;alert(1)&lt;/script&gt;") == 7


def test_invalid_previous_snapshot_file_is_ignored_not_a_500(tmp_path):
    snaps = tmp_path / "snapshots"
    shutil.copytree(SNAPSHOTS, snaps)
    (snaps / "2026-10-06" / "IDN" / "bonds.json").write_text("{not json")
    r = _get("/stance/IDN/bonds", snapshots_dir=snaps)
    assert r.status == 200
    assert "not in the 2026-10-06 snapshot" in _section(r.body, "change")


def test_overview_cells_link_to_pages_that_exist():
    body = _get("/").body
    for href in sorted(set(re.findall(r'href="(/stance/[^"]+)"', body))):
        assert _get(href).status == 200, href


def test_disclaimer_once_in_the_footer():
    body = _get("/stance/IDN/bonds").body
    assert body.count(web.DISCLAIMER) == 1
    assert f"<footer>{web.DISCLAIMER}" in body


def test_a_different_disclaimer_is_shown(out_copy):
    f = out_copy / "IDN" / "bonds.json"
    s = json.loads(f.read_text())
    s["disclaimer"] = f"Heuristic, not investment advice. {EVIL}"
    f.write_text(json.dumps(s))
    body = _get("/stance/IDN/bonds", out_copy).body
    assert body.count(web.DISCLAIMER) == 2
    assert '<p class="muted">Heuristic, not investment advice. &lt;script&gt;' in body
