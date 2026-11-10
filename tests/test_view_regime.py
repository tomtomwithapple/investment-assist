"""The regime page (/regime): the call and dollar, every layer-0 input with value, date, direction,
vote, stale marker and a weekly line, the regime history from the journal's `regime` records, the
.json twin, a missing / unreadable / schema-failing / stub file as a notice, escaping. The file is
`tests/fixtures/ui/layers/regime.json` (generated from a live S33 file cut to 8 weeks: one input
with no value, one week without a VIX point); the journal is built in a tmp dir with
journal.Journal. Neither the file nor the journal may change on a request."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from assist import journal as jr
from assist import layers_out, web
from assist.views import regime as view

FIXTURE = Path(__file__).parent / "fixtures" / "ui" / "layers" / "regime.json"
EVIL = "<script>alert(1)</script>"
FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64


def _journal(root: Path) -> None:
    j = jr.Journal(root)
    rec = [("2026-10-16", FP_A, "neutral", "flat", None),
           ("2026-10-23", FP_A, "neutral", "flat", None),
           ("2026-10-27", FP_B, "risk_off", "up", "regime"),  # a daily check saw a change
           ("2026-10-30", FP_B, "neutral", "flat", None)]
    for day, fp, state, dollar, job in rec:
        ins = {"day": day} | ({"job": job} if job else {})
        j.record(kind="regime", fingerprint=fp, inputs=ins, as_of=day,
                 outputs={"as_of": day, "state": state, "dollar": dollar,
                          "drivers": [f"driver {day}"], "sources": ["sec-edgar"],
                          "stale_inputs": []})
        j.record(kind="stance", fingerprint=fp, subject="IDN", asset="stocks", as_of=day,
                 inputs={"regime": {"state": "risk_on"}}, outputs={"stance": "neutral"})


@pytest.fixture
def root(tmp_path) -> Path:
    (tmp_path / "out" / "layers").mkdir(parents=True)
    shutil.copy(FIXTURE, tmp_path / "out" / "layers" / "regime.json")
    _journal(tmp_path / "journal")
    return tmp_path


@pytest.fixture(autouse=True)
def untouched(root):
    files = [root / "journal" / jr.DECISIONS, root / "out" / "layers" / "regime.json"]
    before = [f.read_bytes() for f in files]
    yield
    assert [f.read_bytes() if f.exists() else None for f in files] == before


def _app(root: Path) -> web.App:
    return web.App(out_dir=root / "out", snapshots_dir=root / "snap",
                   journal_path=root / "journal", paper=lambda until: None,
                   health=lambda: None)


def _get(root: Path, path: str) -> web.Response:
    return web.dispatch(_app(root), web.ROUTES, path)


def _card(html: str, name: str) -> str:
    m = re.search(rf'<section class="card {name}">(.*?)</section>', html, re.S)
    assert m, f"no {name} card"
    return m.group(1)


def _row(html: str, feature: str) -> str:
    m = re.search(rf'<tr[^>]*data-feature="{feature}">(.*?)</tr>', html, re.S)
    assert m, f"no row {feature}"
    return m.group(1)


def _write(root: Path, d) -> None:
    text = d if isinstance(d, str) else json.dumps(d)
    (root / "out" / "layers" / "regime.json").write_text(text)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


# ---------------- fixture ----------------


def test_fixture_matches_the_schema():
    assert list(layers_out.validator("regime").iter_errors(_fixture())) == []


# ---------------- page ----------------


def test_regime_page_in_layout(root):
    r = _get(root, "/regime")
    assert r.status == 200
    assert "<title>Assist Regime</title>" in r.body
    assert web.DISCLAIMER in r.body
    assert "<h1>Regime</h1>" in r.body
    assert 'class="notice"' not in r.body


def test_call_card_shows_regime_dollar_points_and_rule(root):
    call = _card(_get(root, "/regime").body, "call-card")
    assert "As of 2026-11-06" in call
    assert '<span class="chip muted">neutral</span>' in call
    assert "Dollar <span class=\"chip muted\">flat</span>" in call
    assert "broad dollar +1.6%/13w" in call and "+2%" in call and "13 weeks" in call
    assert "risk-off 1, risk-on 0, net 1" in call
    assert "10Y real yield 2.64% (risk-off)" in call
    assert "THREEFYTP10: no observation within 14 days (fixture)" in call
    assert "sha256:074bfad11c66" in call


def test_every_input_is_a_row_with_value_date_direction_vote(root):
    html = _get(root, "/regime").body
    inputs = _card(html, "inputs")
    assert inputs.count("data-feature=") == 9
    vix = _row(inputs, "vix")
    assert "VIX 16.6" in vix and "VIXCLS" in vix and "16.61" in vix and "2026-11-04" in vix
    assert '<span class="chip muted">neutral</span>' in vix and "counted" in vix
    ry = _row(inputs, "real_yield")
    assert '<span class="chip bad">risk-off</span>' in ry and "+1" in ry
    hy = _row(inputs, "hy_oas_d13w")
    assert "+0.57pt" in hy
    usd = _row(inputs, "usd_d13w")
    assert "+1.64%" in usd
    st = _row(inputs, "stlfsi")
    assert '<span class="chip good">risk-on</span>' in st and "-1" in st
    assert "candidate, not counted" in st


def test_counted_inputs_come_first(root):
    inputs = _card(_get(root, "/regime").body, "inputs")
    feats = re.findall(r'data-feature="([^"]+)"', inputs)
    counted = [i["feature"] for i in _fixture()["inputs"] if i["counted"]]
    assert feats[:len(counted)] == counted
    assert inputs.count('class="candidate"') == 4


def test_missing_input_is_stale_with_no_line(root):
    tp = _row(_get(root, "/regime").body, "term_premium_d13w")
    assert "n/a" in tp and "chip warn" in tp and ">stale<" in tp and "no value" in tp
    assert "no history" in tp and "<svg" not in tp


def test_old_point_and_named_series_are_stale():
    d = _fixture()
    vix = next(i for i in d["inputs"] if i["feature"] == "vix")
    assert view.stale_reason(vix, d) is None
    assert "15 days before the run" in view.stale_reason(vix | {"last": "2026-10-22"}, d)
    assert view.stale_reason(vix, d | {"stale_inputs": ["VIXCLS locked"]}) == "VIXCLS locked"


def test_sparkline_per_input_with_a_gap(root):
    inputs = _card(_get(root, "/regime").body, "inputs")
    assert inputs.count('<svg class="spark"') == 8  # every input but the one without values
    vix = _row(inputs, "vix")
    path = re.search(r'<path class="ln" d="([^"]+)"', vix).group(1)
    assert path.count("M") == 2 and path.count("L") == 5  # 8 weeks, week 4 missing
    assert "low " in vix and "high " in vix
    hy = _row(inputs, "hy_oas_d13w")
    assert "(series 3.32)" in hy  # a change input's tooltip carries the series level


def test_sparkline_zero_line_only_when_range_crosses_zero():
    up = {"feature": "x", "kind": "diff", "history": [
        {"date": "2026-01-02", "value": -1.0, "series_value": 1},
        {"date": "2026-01-09", "value": 2.0, "series_value": 1}]}
    assert 'class="zero"' in view.spark(up)
    flat = up | {"history": [h | {"value": 3.0} for h in up["history"]]}
    assert 'class="zero"' not in view.spark(flat)
    one = up | {"history": up["history"][:1]}
    assert '<path class="ln" d="M' in view.spark(one)  # a single point still draws


def test_history_from_regime_records_newest_first_with_changes(root):
    html = _get(root, "/regime").body
    hist = _card(html, "history")
    days = re.findall(r"<tr[^>]*><td>(\d{4}-\d{2}-\d{2})", hist)
    assert days == ["2026-10-30", "2026-10-27", "2026-10-23", "2026-10-16"]
    assert hist.count(">changed<") == 2  # into risk-off, and back
    assert "daily check" in hist and "driver 2026-10-27" in hist
    assert '<span class="chip bad">risk-off</span>' in hist
    assert '<span class="chip warn">up</span>' in hist
    assert "risk-on" not in hist  # the stance records' regime is not history


def test_json_twin_is_file_plus_history(root):
    r = _get(root, "/regime.json")
    assert r.status == 200 and r.ctype == "application/json"
    d = json.loads(r.body)
    assert d["regime"] == _fixture()
    assert [h["as_of"] for h in d["history"]] == ["2026-10-30", "2026-10-27", "2026-10-23",
                                                   "2026-10-16"]
    assert [h["changed"] for h in d["history"]] == [True, True, False, False]
    assert d["history"][1]["job"] == "daily check" and d["problems"] == []


# ---------------- failures ----------------


def test_missing_file_is_a_notice_history_still_shows(root):
    (root / "out" / "layers" / "regime.json").unlink()
    r = _get(root, "/regime")
    assert r.status == 200
    assert view.NO_FILE in r.body
    assert "call-card" not in r.body and "2026-10-30" in _card(r.body, "history")
    (root / "out" / "layers" / "regime.json").write_bytes(FIXTURE.read_bytes())  # for untouched


@pytest.mark.parametrize("text, words", [
    ("{not json", "unreadable"),
    ("[]", "fails the schema"),
    (json.dumps(_fixture() | {"state": EVIL}), "fails the schema at state"),
])
def test_invalid_file_is_a_notice(root, text, words):
    _write(root, text)
    r = _get(root, "/regime")
    assert r.status == 200 and words in r.body and 'class="notice"' in r.body
    assert EVIL not in r.body
    assert json.loads(_get(root, "/regime.json").body)["regime"] is None
    _write(root, FIXTURE.read_text())


def test_stub_with_error_is_a_notice(root):
    d = {k: _fixture()[k] for k in ("schema_version", "kind", "as_of", "model_fingerprint",
                                    "stale_inputs", "sources", "disclaimer")}
    _write(root, d | {"error": f"builder failed: {EVIL}"})
    r = _get(root, "/regime")
    assert r.status == 200 and "holds no layer data: builder failed" in r.body
    assert EVIL not in r.body and esc(EVIL) in r.body
    _write(root, FIXTURE.read_text())


def test_no_journal_and_unreadable_journal(root):
    p = root / "journal" / jr.DECISIONS
    keep = p.read_bytes()
    p.unlink()
    r = _get(root, "/regime")
    assert r.status == 200 and "no regime records in the journal yet" in r.body
    p.write_bytes(keep + b"{oops\n")
    r = _get(root, "/regime")
    assert r.status == 200 and "journal unreadable" in r.body and "call-card" in r.body
    p.write_bytes(keep)


def test_values_from_the_file_are_escaped(root):
    d = _fixture()
    d["drivers"] = [EVIL]
    d["sources"] = [EVIL]
    d["stale_inputs"] = [EVIL]
    d["inputs"][0]["label"] = EVIL
    d["inputs"][0]["series_id"] = EVIL
    d["inputs"][0]["feature"] = EVIL
    _write(root, d)
    r = _get(root, "/regime")
    assert r.status == 200 and "<script>" not in r.body
    assert esc(EVIL) in r.body
    _write(root, FIXTURE.read_text())


def esc(s: str) -> str:
    return web.esc(s)


def test_page_style_does_not_redefine_layout_tokens():
    tokens = set(re.findall(r"(--[\w-]+):", web.PAGE))
    assert tokens and not tokens & set(re.findall(r"(--[\w-]+):", view.STYLE))


# ---------------- home (IDN) regime section (S54, P73) ----------------


def _home_block() -> dict:
    def line(vals):
        return [{"date": f"2026-10-{d:02d}", "value": v} for d, v in vals]

    return {
        "as_of": "2026-11-06", "state": "risk_off", "points": 2,
        "drivers": ["JCI -17.5% vs 20d high (2)"],
        "stale_inputs": ["idxscape SBN.TOTAL.non_resident (last 2026-09-25)"],
        "rule": {"state_at": 2, "jci_points": [[-12.0, 2], [-7.0, 1]], "flow_z_at": -1.5,
                 "usdidr_points": [[4.0, 2], [2.0, 1]], "sbn_at": -1.5, "max_age_days": 7,
                 "shift_pt": -5.0, "shift_adopted": False},
        "history_weeks": 52,
        "inputs": [
            {"feature": "jci_drawdown_20d", "counted": True, "points": 2,
             "label": "JCI -17.5% vs 20d high", "value": -17.45, "last": "2026-11-05",
             "history": line([(16, -18.8), (23, -12.2), (30, -18.3)])},
            {"feature": "idx_foreign_z", "counted": True, "points": 0,
             "label": "IDX foreign 20d z -0.72", "value": -0.72, "last": "2026-11-05",
             "history": line([(16, -0.3), (23, -0.8), (30, -1.0)])},
            {"feature": "usdidr_20d", "counted": True, "points": 0,
             "label": "USD/IDR +1.1%/20 fixings", "value": 1.15, "last": "2026-11-05",
             "history": []},
            {"feature": "sbn_non_resident_20d", "counted": False, "points": None,
             "label": "non-resident SBN +0.1%/20d", "value": 0.1, "last": "2026-09-25",
             "history": line([(16, 3.1)])},
        ],
    }


@pytest.fixture
def home_root(root):
    """`root` with a 1.1.0 regime file carrying `home`; the fixture file is put back after."""
    d = _fixture()
    d["schema_version"] = "1.1.0"
    d["home"] = _home_block()
    assert list(layers_out.validator("regime").iter_errors(d)) == []
    _write(root, d)
    yield root, d
    (root / "out" / "layers" / "regime.json").write_bytes(FIXTURE.read_bytes())


def test_home_card_shows_state_points_rule_and_drivers(home_root):
    root, _d = home_root
    home = _card(_get(root, "/regime").body, "home-card")
    assert "Home regime (IDN)" in home
    assert '<span class="chip bad">risk-off</span>' in home
    assert "2 points" in home and "risk-off at &ge; 2" in home
    assert "JCI -17.5% vs 20d high (2)" in home
    assert "not adopted" in home  # the -5pt shift waits on a passing walk-forward
    assert "laddered" in home


def test_home_inputs_have_points_value_date_and_a_line(home_root):
    root, _d = home_root
    html = _get(root, "/regime").body
    for feat in ("jci_drawdown_20d", "idx_foreign_z", "usdidr_20d", "sbn_non_resident_20d"):
        m = re.search(rf'<tr[^>]*data-home-feature="{feat}">(.*?)</tr>', html, re.S)
        assert m, feat
    jci = re.search(r'data-home-feature="jci_drawdown_20d">(.*?)</tr>', html, re.S).group(1)
    assert "-17.45%" in jci and "2026-11-05" in jci and "<svg" in jci and "<td>2 <span" in jci
    usd = re.search(r'data-home-feature="usdidr_20d">(.*?)</tr>', html, re.S).group(1)
    assert "no history" in usd
    sbn = re.search(r'data-home-feature="sbn_non_resident_20d">(.*?)</tr>', html, re.S).group(1)
    assert "not counted" in sbn and "stale" in sbn


def test_no_home_block_is_a_line_not_a_failure(root):
    html = _get(root, "/regime").body
    home = _card(html, "home-card")
    assert "no home (IDN) regime in this file" in home
    assert 'class="notice"' not in html


def test_json_twin_carries_the_home_block(home_root):
    root, d = home_root
    twin = json.loads(_get(root, "/regime.json").body)
    assert twin["regime"]["home"] == d["home"]


# ---------------- hover explanations ----------------


def test_every_layer0_input_has_a_hover_explanation(root):
    from assist.layers import regime as rule

    assert set(view.EXPLAIN) == set(rule.ALL_FEATURES)
    html = _get(root, "/regime").body
    for inp in _fixture()["inputs"]:
        row = _row(html, inp["feature"])
        tip = re.search(r'class="tip" tabindex="0" data-tip="([^"]+)"', row)
        assert tip, inp["feature"]
        assert ("Candidate: shown, never counted" in tip.group(1)) is (not inp["counted"])
    assert "fear gauge" in _row(html, "vix") and "Risk-off point at 25 or higher" in _row(
        html, "vix")


@pytest.mark.parametrize(("feature", "off", "not_off", "on", "not_on", "words"), [
    ("vix", 25, 24.9, 15, 15.1, ("at 25 or higher", "two points at 35", "15 or lower")),
    ("hy_oas_d13w", 0.75, 0.74, -0.5, -0.49, ("+0.75pt", "-0.50pt")),
    ("usd_d13w", 3.0, 2.9, -3.0, -2.9, ("+3%", "-3%", "past +2%")),
    ("real_yield", 2.5, 2.49, 0.5, 0.51, ("2.5%", "0.5%")),
    ("nfci", 0.01, 0.0, -0.5, -0.49, ("above 0", "-0.5")),
    ("net_liquidity_d13w", -3.0, -2.9, 3.0, 2.9, ("-3%", "+3%")),
    ("em_oas_d13w", 0.5, 0.49, -0.4, -0.39, ("+0.50pt", "-0.40pt")),
    ("term_premium_d13w", 0.4, 0.39, -0.4, -0.39, ("+0.40pt", "-0.40pt")),
    ("stlfsi", 0.01, 0.0, -0.5, -0.49, ("above 0", "-0.5")),
])
def test_hover_thresholds_are_the_rules(feature, off, not_off, on, not_on, words):
    from assist.layers import regime as rule

    _, _, is_off, is_on, _ = rule.ALL_FEATURES[feature]
    assert is_off(off) and not is_off(not_off) and is_on(on) and not is_on(not_on)
    assert all(w in view.explain(feature) for w in words)
    assert rule.DOLLAR_BAND == 2.0 and rule.RULES["vix"][2](35) == 2


def test_home_inputs_have_hover_explanations_with_the_files_thresholds(home_root):
    root, d = home_root
    html = _get(root, "/regime").body
    home = d["home"]
    for inp in home["inputs"]:
        m = re.search(rf'data-home-feature="{inp["feature"]}">(.*?)</tr>', html, re.S)
        assert 'class="tip"' in m.group(1), inp["feature"]
    r = home["rule"]
    tip = view.explain_home("jci_drawdown_20d", r)
    assert all(f"at {t:g}% below" in tip for t, _ in r["jci_points"])
    assert f"at most {r['max_age_days']} days" in tip
    assert f"{r['flow_z_at']:g} or lower" in view.explain_home("idx_foreign_z", r)
    assert view.explain_home("usdidr_20d", {}) == view.HOME_EXPLAIN["usdidr_20d"]  # no rule
    assert view.explain_home("unknown", r) is None and view.explain("unknown") is None
