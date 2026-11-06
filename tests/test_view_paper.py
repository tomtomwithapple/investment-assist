"""The paper and journal pages (/paper, /journal): the benchmark summary (48/32/20 with the US
leg, or an old 60/40 report) with the worst week computed here, each model segment, stale
reasons, a failing paper callable as a notice, the report cached per (day, journal mtime), the
chain check (ok and broken) with records per model, the .json twins and escaping. A canned
PaperReport and a tmp journal built with journal.Journal; no real store, journal or network.
The journal file must be byte-identical after every request."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import pytest

from assist import journal as jr
from assist import web
from assist.paper import Mark, PaperReport, SegmentScore
from assist.sources.base import SourceUnavailable

EVIL = "<script>alert(1)</script>"
FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64
DAY = date(2026, 10, 27)


def _mark(start: date, end: date, bench, stale=()):
    return Mark(start, end, None if bench is None else bench * 1.5,
                None if bench is None else bench / 2, bench, stale=list(stale))


FROZEN = "JCI: no close after 2026-09-30 (idx-method index CSVs frozen; no JCI fetcher)"


def _marks():
    return [_mark(date(2026, 9, 11), date(2026, 9, 18), 0.010),
            _mark(date(2026, 9, 18), date(2026, 9, 25), -0.020),
            _mark(date(2026, 9, 25), date(2026, 10, 2), 0.005),
            _mark(date(2026, 10, 2), date(2026, 10, 9), None,
                  [FROZEN]),
            _mark(date(2026, 10, 9), date(2026, 10, 16), None,
                  [FROZEN,
                   "SBN leg: no igsyc.10y yield after 2026-10-10"])]


def _seg(fp, first, last, until, weeks, stale_weeks, port, bench, hit, notes=()):
    return SegmentScore(fingerprint=fp, decisions=4, first_as_of=first, last_as_of=last,
                        until=until, weeks=weeks, stale_weeks=stale_weeks, portfolio_return=port,
                        benchmark_return=bench,
                        active_return=None if port is None else port - bench, hit_rate=hit,
                        tracking_error=None, info_ratio=None, marks=[], notes=list(notes))


def report(fp_a=FP_A, stale_inputs=("JCI frozen at 2026-09-30 (idx-method index CSVs; "
                                     "no JCI fetcher)",)) -> PaperReport:
    return PaperReport(
        as_of=DAY, start=date(2026, 9, 11),
        legs={"stocks": "JCI (IHSG) price index", "bonds": "synthetic 10Y par bond"},
        bond_series="igsyc.10y", benchmark_pct={"stocks": 60.0, "bonds": 40.0},
        stale_inputs=list(stale_inputs),
        benchmark_summary={"weeks": 3, "stale_weeks": 2, "cumulative": -0.0053,
                           "annualized": -0.0880, "volatility": 0.1100},
        benchmark=_marks(),
        segments=[_seg(fp_a, date(2026, 9, 10), date(2026, 9, 24), date(2026, 10, 1), 3, 0,
                       0.0120, -0.0053, 2 / 3),
                  _seg(FP_B, date(2026, 10, 1), date(2026, 10, 27), None, 0, 3, None, None,
                       None, ["IDN/bonds: no stance in this segment; held at the benchmark "
                              "weight"])],
        notes=["benchmark: 60% JCI / 40% SBN leg, rebalanced weekly; cash earns 0"])


def _journal(root: Path) -> jr.Journal:
    j = jr.Journal(root)
    for i, (fp, d, kind) in enumerate([(FP_A, "2026-10-13", "stance"),
                                       (FP_A, "2026-10-20", "stance"),
                                       (FP_A, "2026-10-20", "candidates"),
                                       (FP_B, "2026-10-27", "stance")]):
        j.record(kind=kind, fingerprint=fp, subject="IDN", asset="stocks", as_of=d,
                 inputs={"i": i}, outputs={"stance": "neutral"})
    return j


class Paper:
    """A paper callable that counts its calls; `fail` makes it raise instead."""

    def __init__(self, rep=None, fail: Exception | None = None):
        self.rep, self.fail, self.calls = rep if rep is not None else report(), fail, []

    def __call__(self, until):
        self.calls.append(until)
        if self.fail is not None:
            raise self.fail
        return self.rep


@pytest.fixture
def jroot(tmp_path) -> Path:
    _journal(tmp_path / "journal")
    return tmp_path / "journal"


def _app(jroot: Path, paper=None, today=DAY) -> web.App:
    box = {"today": today}
    app = web.App(out_dir=jroot.parent / "out", snapshots_dir=jroot.parent / "snap",
                  journal_path=jroot, paper=paper or Paper(), health=lambda: None,
                  today=lambda: box["today"])
    app._box = box  # tests move the day
    return app


def _get(app: web.App, path: str) -> web.Response:
    return web.dispatch(app, web.ROUTES, path)


def _card(html: str, name: str) -> str:
    m = re.search(rf'<section class="card {name}">(.*?)</section>', html, re.S)
    assert m, f"no {name} card"
    return m.group(1)


@pytest.fixture(autouse=True)
def journal_untouched(jroot):
    before = (jroot / jr.DECISIONS).read_bytes()
    yield
    assert (jroot / jr.DECISIONS).read_bytes() == before


# ---------------- /paper ----------------


def test_paper_page_in_layout_with_nav(jroot):
    app = _app(jroot)
    r = _get(app, "/paper")
    assert r.status == 200
    assert "<title>Assist Paper</title>" in r.body
    assert '<a href="/paper" class="active">Paper</a>' in r.body
    assert web.DISCLAIMER in r.body
    assert app.paper.calls == [DAY]


def test_paper_summary_and_worst_week(jroot):
    s = _card(_get(_app(jroot), "/paper").body, "summary")
    assert "60% JCI / 40% SBN leg" in s
    assert "2026-09-11" in s and "2026-10-27" in s
    assert "<th>Weeks scored</th><td>3</td>" in s
    assert "<th>Stale weeks</th><td>2</td>" in s
    assert "<th>Cumulative</th><td>-0.5%</td>" in s
    assert "<th>Annualised</th><td>-8.8%</td>" in s
    assert "<th>Volatility</th><td>11.0%</td>" in s
    # min of m.benchmark over the scored marks, computed on this page
    assert "-2.0% (week ending 2026-09-25)" in s
    assert "computed here" in s
    assert "Last scored week ends 2026-10-02: benchmark +0.5%" in s
    assert "JCI (IHSG) price index" in s and "synthetic 10Y par bond" in s


def s40_report() -> PaperReport:
    """A 48/32/20 report with the US leg and the legacy 60/40 beside it (S40)."""
    rep = report()
    rep.benchmark_pct = {"stocks": 48.0, "bonds": 32.0, "usa": 20.0}
    rep.legs["usa"] = ("US stocks in IDR, unhedged, price index: Alpaca SPY close × split factor "
                       "(sec-edgar) × USD/IDR (MAS cross then JISDOR)")
    m = rep.benchmark[2]
    m.usa, m.usa_usd, m.usd_idr = 0.0151, 0.01, 0.005
    rep.legacy_benchmark_pct = {"stocks": 60.0, "bonds": 40.0}
    rep.legacy_start = date(2026, 9, 11)
    rep.legacy_summary = {"weeks": 3, "stale_weeks": 2, "cumulative": -0.004,
                          "annualized": -0.07, "volatility": 0.1}
    rep.segments[0].benchmark_pct = {"stocks": 60.0, "bonds": 40.0}
    rep.segments[1].benchmark_pct = dict(rep.benchmark_pct)
    return rep


def test_paper_shows_the_us_leg_weights_sources_and_legacy_benchmark(jroot):
    body = _get(_app(jroot, Paper(s40_report())), "/paper").body
    s = _card(body, "summary")
    assert "IDR benchmark 48/32/20" in s
    assert "48% JCI / 32% SBN leg / 20% US stocks (IDR)" in s
    assert "<th>US stocks leg (20%)</th>" in s and "Alpaca SPY" in s and "JISDOR" in s
    assert "<th>Stocks leg (48%)</th>" in s and "<th>Bonds leg (32%)</th>" in s
    assert ("US stocks (IDR) +1.5% = SPY +1.0% × USD/IDR +0.5%" in s)
    legacy = _card(body, "legacy")
    assert "Legacy benchmark 60/40" in legacy and "60% JCI / 40% SBN leg" in legacy
    assert "never chained" in legacy
    seg = _card(body, "segments")
    rows = re.findall(r"<tr>(.*?)</tr>", seg, re.S)
    assert "<td>60/40</td>" in rows[1] and "<td>48/32/20</td>" in rows[2]
    d = json.loads(_get(_app(jroot, Paper(s40_report())), "/paper.json").body)
    assert d["report"]["benchmark_pct"]["usa"] == 20.0
    assert "legacy_benchmark" not in d["report"]


def test_paper_old_report_without_us_leg_still_renders(jroot):
    body = _get(_app(jroot), "/paper").body
    assert "IDR benchmark 60/40" in body and 'class="card legacy"' not in body


def test_paper_worst_week_none_when_nothing_scored(jroot):
    rep = report()
    rep.benchmark = [m for m in rep.benchmark if m.benchmark is None]
    rep.benchmark_summary = {"weeks": 0, "stale_weeks": 2, "cumulative": None,
                             "annualized": None, "volatility": None}
    r = _get(_app(jroot, Paper(rep)), "/paper")
    s = _card(r.body, "summary")
    assert "<th>Worst week</th><td>n/a</td>" in s
    assert "<th>Cumulative</th><td>n/a</td>" in s
    assert json.loads(_get(_app(jroot, Paper(rep)), "/paper.json").body)["worst_week"] is None


def test_paper_segments(jroot):
    s = _card(_get(_app(jroot), "/paper").body, "segments")
    rows = re.findall(r"<tr>(.*?)</tr>", s, re.S)
    assert len(rows) == 3  # head + 2 segments
    a, b = rows[1], rows[2]
    assert "<code>sha256:aaaaaaaaaaaa</code>" in a
    assert "2026-09-10 … 2026-09-24" in a and "2026-10-01" in a
    for cell in ("<td>4</td>", "<td>3</td>", "<td>0</td>", "+1.2%", "-0.5%", "+1.7%", "67%"):
        assert cell in a, cell
    assert "<code>sha256:bbbbbbbbbbbb</code>" in b
    assert "2026-10-01 … 2026-10-27" in b and "current" in b
    assert "nothing scored yet" in b and "n/a" in b
    assert "IDN/bonds: no stance in this segment" in s


def test_paper_no_segments_says_benchmark_only(jroot):
    rep = report()
    rep.segments = []
    s = _card(_get(_app(jroot, Paper(rep)), "/paper").body, "segments")
    assert "No stance history in the journal yet: benchmark marks only." in s


def test_paper_stale_reasons_are_inputs_plus_distinct_mark_stale(jroot):
    r = _get(_app(jroot), "/paper")
    s = _card(r.body, "stale")
    items = re.findall(r"<li>(.*?)</li>", s)
    assert items == [
        "JCI frozen at 2026-09-30 (idx-method index CSVs; no JCI fetcher)",
        "JCI: no close after 2026-09-30 (idx-method index CSVs frozen; no JCI fetcher)",
        "SBN leg: no igsyc.10y yield after 2026-10-10"]


def test_paper_json_twin(jroot):
    d = json.loads(_get(_app(jroot), "/paper.json").body)
    assert d["error"] is None and d["as_of"] == "2026-10-27"
    assert d["worst_week"] == {"week_end": "2026-09-25", "benchmark": -0.02}
    assert len(d["stale_reasons"]) == 3
    rep = d["report"]
    assert rep["benchmark_summary"]["weeks"] == 3
    assert [s["fingerprint"] for s in rep["segments"]] == [FP_A, FP_B]
    assert "benchmark" not in rep and "marks" not in rep["segments"][0]


@pytest.mark.parametrize("err", [RuntimeError("boom"),
                                 SourceUnavailable("dbnomics", "locked", "dbn refresh"),
                                 OSError("Could not set lock on file dbnomics.duckdb")])
def test_paper_error_is_a_notice(jroot, err):
    app = _app(jroot, Paper(fail=err))
    r = _get(app, "/paper")
    assert r.status == 200 and web.DISCLAIMER in r.body
    assert '<p class="notice">' in r.body and type(err).__name__ in r.body
    d = json.loads(_get(app, "/paper.json").body)
    assert d["report"] is None and type(err).__name__ in d["error"]


def test_paper_error_is_escaped_and_not_cached(jroot):
    app = _app(jroot, Paper(fail=ValueError(EVIL)))
    r = _get(app, "/paper")
    assert EVIL not in r.body and "&lt;script&gt;" in r.body
    _get(app, "/paper")
    assert len(app.paper.calls) == 2  # a lock is transient: the next reload tries again


def test_paper_cached_per_day_and_journal_mtime(jroot):
    app = _app(jroot)
    first = _get(app, "/paper").body
    _get(app, "/paper.json")
    _get(app, "/paper")
    assert app.paper.calls == [DAY]
    assert _get(app, "/paper").body == first
    # the day moves
    app._box["today"] = date(2026, 10, 28)
    _get(app, "/paper")
    assert app.paper.calls == [DAY, date(2026, 10, 28)]
    _get(app, "/paper")
    assert len(app.paper.calls) == 2


def test_paper_cache_drops_when_journal_mtime_changes(jroot, tmp_path):
    app = _app(jroot)
    _get(app, "/paper")
    f = jroot / jr.DECISIONS
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    _get(app, "/paper")
    _get(app, "/paper")
    assert app.paper.calls == [DAY, DAY]


def test_paper_cache_with_no_journal_file(tmp_path):
    root = tmp_path / "nojournal"
    app = web.App(out_dir=tmp_path / "o", snapshots_dir=tmp_path / "s", journal_path=root,
                  paper=Paper(), health=lambda: None, today=lambda: DAY)
    _get(app, "/paper")
    _get(app, "/paper")
    assert app.paper.calls == [DAY]
    assert not root.exists()


def test_paper_escapes_values_from_the_report(jroot):
    rep = report(fp_a=EVIL, stale_inputs=[EVIL])
    rep.legs["stocks"] = EVIL
    rep.notes.append(EVIL)
    rep.segments[0].notes.append(EVIL)
    rep.benchmark[3].stale = [EVIL]
    r = _get(_app(jroot, Paper(rep)), "/paper")
    assert r.status == 200
    assert EVIL not in r.body and "&lt;script&gt;" in r.body


# ---------------- /journal ----------------


def test_journal_chain_ok_and_models(jroot):
    r = _get(_app(jroot), "/journal")
    assert r.status == 200
    assert "<title>Assist Journal</title>" in r.body
    assert '<a href="/journal" class="active">Journal</a>' in r.body
    s = _card(r.body, "chain")
    assert "chain ok" in s and "chip good" in s
    assert "4 record(s), 2 model(s)" in s
    m = _card(r.body, "models")
    rows = re.findall(r"<tr>(.*?)</tr>", m, re.S)[1:]
    assert len(rows) == 2
    assert "<code>sha256:aaaaaaaaaaaa</code>" in rows[0]
    assert "<td>3</td>" in rows[0] and "<td>2</td>" in rows[0]
    assert "2026-10-13 … 2026-10-20" in rows[0]
    assert "<code>sha256:bbbbbbbbbbbb</code>" in rows[1]
    assert "<td>1</td>" in rows[1] and "2026-10-27 … 2026-10-27" in rows[1]


def test_journal_json_twin(jroot):
    d = json.loads(_get(_app(jroot), "/journal.json").body)
    assert d["chain_ok"] is True and d["chain"] == "chain ok" and d["records"] == 4
    assert d["models"] == [
        {"fingerprint": FP_A, "records": 3, "stances": 2, "first_as_of": "2026-10-13",
         "last_as_of": "2026-10-20"},
        {"fingerprint": FP_B, "records": 1, "stances": 1, "first_as_of": "2026-10-27",
         "last_as_of": "2026-10-27"}]


def test_journal_broken_chain(tmp_path):
    j = _journal(tmp_path / "other")
    lines = j.path.read_text().splitlines()
    lines[1] = lines[1].replace('"i":1', '"i":9')
    j.path.write_text("\n".join(lines) + "\n")
    before = j.path.read_bytes()
    app = _app(j.root)
    r = _get(app, "/journal")
    assert r.status == 200
    s = _card(r.body, "chain")
    assert "chain BROKEN: seq 1: content does not match its hash (edited?)" in s
    assert "chip bad" in s and "4 record(s), 2 model(s)" in s
    d = json.loads(_get(app, "/journal.json").body)
    assert d["chain_ok"] is False and d["chain"].startswith("chain BROKEN: seq 1")
    assert d["records"] == 4
    assert j.path.read_bytes() == before


def test_journal_unparseable_line_is_a_notice(tmp_path):
    j = _journal(tmp_path / "other")
    with open(j.path, "a") as fh:
        fh.write("{not json\n")
    r = _get(_app(j.root), "/journal")
    assert r.status == 200 and "chain BROKEN" in r.body
    assert '<p class="notice">' in r.body


def test_journal_missing_file(tmp_path):
    app = _app(tmp_path / "none")
    r = _get(app, "/journal")
    assert r.status == 200 and "no journal yet" in r.body
    assert json.loads(_get(app, "/journal.json").body)["records"] == 0
    assert not (tmp_path / "none").exists()


def test_journal_escapes_a_hand_edited_fingerprint(tmp_path):
    j = _journal(tmp_path / "other")
    with open(j.path, "a") as fh:  # not through record(), which would refuse it
        fh.write(json.dumps({"kind": EVIL, "fingerprint": EVIL, "as_of": EVIL, "seq": 4,
                             "prev": "x", "hash": "y"}) + "\n")
    r = _get(_app(j.root), "/journal")
    assert r.status == 200 and "chain BROKEN" in r.body
    assert EVIL not in r.body and "&lt;script&gt;" in r.body


def test_paper_unreadable_report_is_a_notice(jroot):
    r = _get(_app(jroot, Paper(rep={"not": "a report"})), "/paper")
    assert r.status == 200 and '<p class="notice">' in r.body
    assert "unreadable paper report" in r.body
