"""The flows page (/flows, /flows/<YYYY-MM>, PLAN S38): the latest month and any month in the
index, the SVG diagram (owner columns, an arrow per matched transfer, dashed arrows to a "no
statement" box), the tables, the .json twin, 404 for a month not in the index, a notice instead of
a 500, and escaping. Files come from `flows.build_from` on the S38 fixture into a temp out/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_flows import NAMES, _db

from assist import flows, web
from assist.sources.financer import FinancerSource
from assist.views import flows as view

EVIL = "<script>alert(1)</script>"


def _app(out: Path) -> web.App:
    return web.App(out_dir=out, snapshots_dir=out / "s", journal_path=out / "j",
                   paper=lambda until: None, health=lambda: None)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    o = tmp_path / "out"
    flows.write(*flows.build_from(FinancerSource(_db(tmp_path)), NAMES), o)
    return o


def _get(out: Path, path: str) -> web.Response:
    return web.dispatch(_app(out), web.ROUTES, path)


def test_flows_shows_the_latest_month(out):
    r = _get(out, "/flows")
    assert r.status == 200
    assert "<h1>Flows" in r.body and "2026-10" in r.body
    assert "<svg" in r.body and 'class="arrow matched"' in r.body
    # links to every month in the index
    assert 'href="/flows/2026-09"' in r.body and 'href="/flows/2026-10"' in r.body


def test_diagram_has_owner_columns_and_arrows(out):
    body = _get(out, "/flows/2026-10").body
    svg = body[body.index("<svg"):body.index("</svg>")]
    assert "tommy" in svg and "priskila" in svg
    # 4 account pairs carry the 5 transfers (the two 250,000 share one arrow)
    assert svg.count('class="arrow matched"') == 4
    # one dashed arrow for the named debit, one for the unmatched settlement
    assert svg.count('class="arrow unmatched"') == 2
    assert "no statement" in svg
    # width follows the amount: the 2,500,000 card payment is wider than the 500,050 settlement
    widths = view.arrow_widths([2_500_000, 500_050])
    assert widths[0] > widths[1] > 0


def test_tables(out):
    body = _get(out, "/flows/2026-10").body
    for text in ("Matched transfers", "Unmatched", "External", "Accounts",
                 "to priskila, receiving account has no statement in financer",
                 "paid from RDN (statement not loaded)", "1,234,567.89", "4,000,000",
                 "·1111", "·7777"):
        assert text in body, text
    assert "SAV-1111" not in body


def test_stale_inputs_are_a_notice(out):
    body = _get(out, "/flows/2026-10").body
    assert 'class="notice"' in body and "cimb_cc ·9999 (tommy)" in body


def test_twin_matches_the_file(out):
    for path, name in (("/flows.json", "2026-10"), ("/flows/2026-10.json", "2026-10"),
                       ("/flows/2026-09.json", "2026-09")):
        r = _get(out, path)
        assert r.status == 200 and r.ctype == "application/json"
        file = json.loads((out / "flows" / f"{name}.json").read_text())
        assert json.loads(r.body) == file


@pytest.mark.parametrize("path", ["/flows/2026-08", "/flows/2026-8", "/flows/..%2Findex",
                                  "/flows/index", "/flows/2026-10/x", "/flows/2026-08.json"])
def test_month_not_in_the_index_is_404(out, path):
    assert _get(out, path).status == 404


def test_month_is_taken_from_the_index_never_the_url(out):
    """A month file that exists but is not in the index is not served."""
    (out / "flows" / "2026-07.json").write_text((out / "flows" / "2026-10.json").read_text())
    assert _get(out, "/flows/2026-07").status == 404


def test_bad_month_in_the_index_is_skipped(out):
    idx = json.loads((out / "flows" / "index.json").read_text())
    idx["months"].append({"month": "../../x", "file": "../../x.json", "transfers": 0,
                          "unmatched": 0})
    (out / "flows" / "index.json").write_text(json.dumps(idx))
    assert _get(out, "/flows/..%2F..%2Fx").status == 404
    assert _get(out, "/flows").status == 200


def test_no_files_is_a_notice_not_a_500(tmp_path):
    r = _get(tmp_path / "out", "/flows")
    assert r.status == 200 and "no flows in out/flows/ yet" in r.body
    assert json.loads(_get(tmp_path / "out", "/flows.json").body)["months"] == []
    assert _get(tmp_path / "out", "/flows/2026-10").status == 404


def test_unreadable_files_are_a_notice(out):
    (out / "flows" / "2026-10.json").write_text("{not json")
    r = _get(out, "/flows")
    assert r.status == 200 and "not valid JSON" in r.body
    (out / "flows" / "index.json").write_text("[]")
    r = _get(out, "/flows")
    assert r.status == 200 and "no months" in r.body


def test_every_value_is_escaped(out):
    path = out / "flows" / "2026-10.json"
    p = json.loads(path.read_text())
    p["accounts"][0]["issuer"] = EVIL
    p["accounts"][0]["owner"] = EVIL
    p["transfers"][0]["from_description"] = EVIL
    p["unmatched_named"][0]["reason"] = EVIL
    p["unmatched_settlements"][0]["reason"] = EVIL
    p["stale_inputs"].append(EVIL)
    path.write_text(json.dumps(p))
    r = _get(out, "/flows/2026-10")
    assert r.status == 200 and EVIL not in r.body and "&lt;script&gt;" in r.body


def test_flows_has_a_nav_link():
    assert ("/flows", "Flows") in web.NAV  # F8
