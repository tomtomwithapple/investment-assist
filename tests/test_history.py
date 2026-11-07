"""Point-in-time history of the IDN bonds and stocks rules (P66, PLAN S47).

Every store is an in-memory fake holding tidy `Row`s over 2020-06 → 2023-02, so the history runs
the two rules unchanged on 12 month ends of 2022. The key test poisons every value that was not
yet known on a cut-off date (dated after it, recorded after it, or inside its publication lag)
and checks that no row up to the cut-off moves."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from assist import history as H
from assist import pipeline
from assist.layers.bonds.idn import PROXY_10Y
from assist.layers.rules.idn_stocks import IDN_CRP, US_ERP
from assist.sources.base import Row, SourceUnavailable
from assist.sources.bpslooker import CPI_YOY
from assist.sources.idxmethod import JCI
from assist.sources.idxscape import IDX_NET_FOREIGN_IDR, JISDOR, SBN_NON_RESIDENT
from assist.sources.idxscape_phei import IGSYC_10Y

D = date.fromisoformat
TODAY = D("2023-02-10")
START, END = D("2022-01-31"), D("2022-12-31")
BACKFILL = D("2026-10-06")  # idxscape's recorded date on every backfilled flow / SBN row


class Fake:
    """A store as tidy rows; filters like the adapters (ids, inclusive dates)."""

    def __init__(self, name: str, rows: list[Row] | None = None, error: str | None = None):
        self.name, self._rows, self.error = name, list(rows or []), error
        self.calls = 0

    def rows(self, series_ids=None, start=None, end=None, **kw):
        self.calls += 1
        if self.error:
            raise SourceUnavailable(self.name, self.error)
        return sorted(
            (r for r in self._rows
             if (series_ids is None or r.series_id in series_ids)
             and (start is None or r.date >= start) and (end is None or r.date <= end)),
            key=lambda r: (r.series_id, r.date))


class FakeFactors:
    """`FactorSnapshots`' interface over dated cross-sections."""

    name = "idx-method"

    def __init__(self, snaps: dict[date, dict]):
        self.snaps = snaps
        self.calls = 0

    def factors_on(self, as_of):
        self.calls += 1
        known = [d for d in self.snaps if d <= as_of]
        if not known:
            raise SourceUnavailable(self.name, "missing", "no snapshot")
        return max(known), self.snaps[max(known)]


def weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def firsts(start: date, end: date) -> list[date]:
    out, d = [], start.replace(day=1)
    while d <= end:
        out.append(d)
        d = (d + timedelta(days=32)).replace(day=1)
    return out


def sources(*, proxy=True, phei_rows=(), cpi_now=None) -> H.HistorySources:
    days = weekdays(D("2020-06-01"), D("2023-02-09"))
    months = firsts(D("2019-01-01"), D("2023-01-01"))
    jci = Fake("idxscape+idx-method",
               [Row(JCI, d, 6000.0 + 2 * i, d, "idxscape") for i, d in enumerate(days)])
    fx = Fake("MAS+JISDOR", [Row(JISDOR, d, 15000.0 * (1 + 0.002 * ((i % 4) - 1.5)), None,
                                 "singstat") for i, d in enumerate(days)])
    idx_rows = [Row(IDX_NET_FOREIGN_IDR, d, 1e11, BACKFILL, "idxscape") for d in days]
    idx_rows += [Row(SBN_NON_RESIDENT, d, 800e12 + 1e12 * i, BACKFILL, "idxscape")
                 for i, d in enumerate(days[::5])]
    cpi = [Row(CPI_YOY, m, 3.0, None, "bps-looker") for m in months]
    if cpi_now is not None:  # a different value for one month, to see when it becomes known
        m, v = cpi_now
        cpi = [r._replace(value=v) if r.date == m else r for r in cpi]
    dbn = [Row(US_ERP, m, 0.045, None, "dbnomics") for m in months]
    dbn += [Row(IDN_CRP, m, 0.025, None, "dbnomics") for m in months if m.month in (1, 7)]
    if proxy:
        dbn += [Row(PROXY_10Y, m, 7.0, None, "dbnomics") for m in months
                if m <= D("2022-06-01")]
    snaps = {d: {"AAA": {"mktcap": 1e12, "earnings_yield": 12.0},
                 "BBB": {"mktcap": 1e12, "earnings_yield": 12.0}}
             for d in weekdays(D("2021-12-01"), D("2023-02-09"))}
    idn = pipeline.IdnSources(
        bps=Fake("bps-looker", cpi), bisfetcher=Fake("bisfetcher", error="missing"),
        dbnomics=Fake("dbnomics", dbn), satudatascape=Fake("satudatascape", error="missing"),
        idxscape=Fake("idxscape", idx_rows), kseistat=Fake("kseistat", error="missing"),
        tic=Fake("sec-edgar", error="missing"), phei=Fake("idxscape_phei", list(phei_rows)),
        idxmethod=jci, snapshots=FakeFactors(snaps), stocks=None, usdidr=fx)
    return H.HistorySources(idn=idn, fred=Fake("sec-edgar"))


def build(src=None, start=START, end=END):
    return H.build(src or sources(), H.month_ends(start, end), today=TODAY)


@pytest.fixture(scope="module")
def base():
    return build()


# ---------------- dates ----------------


def test_month_ends():
    assert H.month_ends(D("2022-01-15"), D("2022-04-30")) == [
        D("2022-01-31"), D("2022-02-28"), D("2022-03-31"), D("2022-04-30")]
    assert H.month_ends(D("2024-02-01"), D("2024-02-28")) == []
    assert H.month_ends(D("2024-02-01"), D("2024-02-29")) == [D("2024-02-29")]


def test_last_month_end_is_before_today():
    assert H.last_month_end(D("2026-11-07")) == D("2026-10-31")
    assert H.last_month_end(D("2026-10-31")) == D("2026-09-30")  # the day itself is not over


def test_horizon_is_the_live_gate_horizon():
    assert H.HORIZON == pipeline.RULE_HORIZON


# ---------------- the rows ----------------


def test_one_row_per_month_end_for_each_rule(base):
    assert set(base) == {"bonds", "stocks"}
    for h in base.values():
        assert [r.as_of for r in h.rows] == H.month_ends(START, END)


def test_rules_call_while_every_input_is_known(base):
    b, s = base["bonds"].row(D("2022-03-31")), base["stocks"].row(D("2022-03-31"))
    assert b.call == "enter" and b.proposed_stance == "overweight" and b.missing == ()
    assert b.ten_year_source == "dbnomics proxy"
    assert b.values["real_yield"] == pytest.approx(4.0)
    # implied ERP 12 + 2 − (7 − 3) = 10% against the 4.5 + 2.5 hurdle: +3pt, cheap
    assert s.call == "enter" and s.proposed_stance == "overweight" and s.missing == ()
    assert s.values["earnings_yield"] == pytest.approx(12.0)


def test_stocks_macro_is_layer_1_held_at_50(base):
    s = base["stocks"].row(D("2022-03-31"))
    assert s.values["macro_score"] == pytest.approx(50.0)  # no override components in the fakes
    assert H.held_score(D("2022-03-31")).score == 50.0


def test_old_proxy_is_no_call_with_the_reason(base):
    # the proxy ends 2022-06 (monthly average dated the 1st): too old to call 90 days on
    b = base["bonds"].row(D("2022-09-30"))
    assert b.call == "no_call" and b.proposed_stance is None
    assert [m.split(":")[0] for m in b.missing] == ["10Y"]
    assert "too old" in b.missing[0] and "2022-06" in b.missing[0]
    assert base["stocks"].row(D("2022-09-30")).missing[0].startswith("10Y")


def test_month_with_no_10y_is_no_call_with_the_reason():
    h = build(sources(proxy=False), D("2022-03-31"), D("2022-03-31"))
    for asset in ("bonds", "stocks"):
        r = h[asset].row(D("2022-03-31"))
        assert r.call == "no_call" and r.ten_year_source is None
        assert any(m.startswith("10Y:") and "no data" in m for m in r.missing), r.missing


def test_phei_counts_only_once_fetched():
    # a curve point dated 11-25 but fetched 12-05 is unknown on 11-30
    phei = [Row(IGSYC_10Y, D("2022-11-25"), 6.5, D("2022-12-05"), "idxscape_phei")]
    phei += [Row(IGSYC_10Y, d, 6.5, d, "idxscape_phei")
             for d in weekdays(D("2022-12-01"), D("2022-12-30"))]
    h = build(sources(phei_rows=phei), D("2022-11-30"), D("2022-12-31"))
    assert h["bonds"].row(D("2022-11-30")).ten_year_source == "dbnomics proxy"
    dec = h["bonds"].row(D("2022-12-31"))
    assert dec.ten_year_source == "idxscape_phei"
    assert dec.values["real_yield"] == pytest.approx(3.5)


def test_cpi_counts_only_past_its_lag():
    # bps-looker CPI for 2022-03 (dated 03-01, no vintage) is known 35 days on: 04-05
    h = build(sources(cpi_now=(D("2022-03-01"), 5.0)), D("2022-03-31"), D("2022-04-30"))
    assert h["bonds"].row(D("2022-03-31")).values["real_yield"] == pytest.approx(4.0)
    assert h["bonds"].row(D("2022-04-30")).values["real_yield"] == pytest.approx(2.0)
    assert h["stocks"].row(D("2022-03-31")).values["real_yield"] == pytest.approx(4.0)


# ---------------- no look-ahead ----------------

LAGS = {CPI_YOY: 35, PROXY_10Y: 45, US_ERP: 10, IDN_CRP: 45, JISDOR: 1,
        IDX_NET_FOREIGN_IDR: 1, SBN_NON_RESIDENT: 40, IGSYC_10Y: 0, JCI: 0}


def _unknown(r: Row, cut: date) -> bool:
    recorded = r.as_of is not None and r.as_of <= cut
    return r.date > cut or (not recorded and r.date + timedelta(days=LAGS[r.series_id]) > cut)


def _poison(src: H.HistorySources, cut: date) -> H.HistorySources:
    """Every value not yet known on `cut` replaced by an absurd one."""
    idn = src.idn
    for name in ("bps", "dbnomics", "idxscape", "phei", "idxmethod", "usdidr"):
        fake = getattr(idn, name)
        fake._rows = [r._replace(value=r.value * 3 + 17) if _unknown(r, cut) else r
                      for r in fake._rows]
    snaps = idn.snapshots.snaps
    for d in snaps:
        if d > cut:
            snaps[d] = {k: {**v, "earnings_yield": -40.0} for k, v in snaps[d].items()}
    return src


@pytest.mark.parametrize("cut", [D("2022-04-30"), D("2022-08-31"), D("2022-11-30")])
def test_no_row_reads_a_value_unknown_on_its_as_of(base, cut):
    phei = [Row(IGSYC_10Y, D("2022-11-25"), 6.5, D("2022-12-05"), "idxscape_phei")]
    clean = build(sources(phei_rows=phei))
    poisoned = build(_poison(sources(phei_rows=phei), cut))
    for asset in ("bonds", "stocks"):
        before = [r for r in clean[asset].rows if r.as_of <= cut]
        after = [r for r in poisoned[asset].rows if r.as_of <= cut]
        assert before
        strip = [r.to_dict() | {"forward_return": None} for r in before]
        assert strip == [r.to_dict() | {"forward_return": None} for r in after]
        later = [r for r in poisoned[asset].rows if r.as_of > cut]
        # the poison is visible once known, so the test can see a leak
        if later and asset == "stocks":
            assert later[-1].values["earnings_yield"] == pytest.approx(-40.0)


# ---------------- forward returns ----------------


def test_stocks_forward_return_is_jci_over_3_month_ends(base):
    jci = {d: 6000.0 + 2 * i for i, d in enumerate(weekdays(D("2020-06-01"), D("2023-02-09")))}
    def close(y, m):
        return jci[max(d for d in jci if (d.year, d.month) == (y, m))]
    r = base["stocks"].row(D("2022-03-31"))
    assert r.forward_return == pytest.approx(close(2022, 6) / close(2022, 3) - 1)
    # 2022-11 → 2023-02 has no complete February yet on 2023-02-10
    assert base["stocks"].row(D("2022-10-31")).forward_return is not None
    assert base["stocks"].row(D("2022-11-30")).forward_return is None


def test_bonds_forward_return_on_month_end_10y(base):
    # flat 7.0% proxy: carry only, 7% × 3/12
    assert base["bonds"].row(D("2022-03-31")).forward_return == pytest.approx(0.07 * 3 / 12)
    # the proxy ends 2022-06, so 2022-04 → 2022-07 has no forward point
    assert base["bonds"].row(D("2022-04-30")).forward_return is None


def test_bond_forward_never_spans_a_gap():
    ten = [(D("2024-10-01"), 7.0), (D("2024-11-01"), 7.0), (D("2024-12-01"), 7.0),
           (D("2026-10-31"), 6.0), (D("2026-11-30"), 6.0), (D("2026-12-31"), 6.0),
           (D("2027-01-29"), 5.0)]
    out = H.bond_forward(ten, H.HORIZON)
    assert (2024, 10) not in out  # index-based pairing would take 2026-10 as 2024-10 + 3
    assert out[(2026, 10)] == pytest.approx(0.06 * 3 / 12 - 7.0 * (5.0 - 6.0) / 100)


# ---------------- sample and coverage ----------------


def test_sample_counts_non_overlapping_windows(base):
    s = base["bonds"].sample()
    rows = [r for r in base["bonds"].rows if r.forward_return is not None]
    assert s["on"] + s["off"] + s["no_call"] == len(rows[::H.HORIZON])
    calls = base["bonds"].summary()
    assert calls["first"] == "2022-01" and calls["last"] == "2022-12"
    assert sum(calls["calls"].values()) == 12
    assert calls["missing"]["10Y"] == len([r for r in base["bonds"].rows
                                           if any(m.startswith("10Y") for m in r.missing)])


def test_history_round_trips_json(base):
    h = base["stocks"]
    back = H.RuleHistory.from_dict(json.loads(json.dumps(h.to_dict())))
    assert back == h


# ---------------- cache ----------------


class Boom:
    """A sources object that fails if a build touches it."""

    def __getattr__(self, name):
        raise AssertionError(f"store read on a cache hit ({name})")


def test_cache_keyed_by_fingerprint_and_store_dates(tmp_path):
    dates = {"idxscape": "2023-02-09", "dbnomics": "2023-01-01"}
    kw = {"start": START, "today": TODAY, "cache_dir": tmp_path, "store_dates": dates}
    first = H.history(sources(), fingerprint="sha256:" + "a" * 64, **kw)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["IDN-bonds.json", "IDN-stocks.json"]
    again = H.history(Boom(), fingerprint="sha256:" + "a" * 64, **kw)
    assert again == first
    src = sources()
    H.history(src, fingerprint="sha256:" + "b" * 64, **kw)  # a new model: rebuilt
    assert src.idn.snapshots.calls > 0
    src = sources()
    H.history(src, fingerprint="sha256:" + "b" * 64,
              **{**kw, "store_dates": {**dates, "idxscape": "2023-02-10"}})
    assert src.idn.snapshots.calls > 0  # a store moved: rebuilt
    saved = json.loads((tmp_path / "IDN-bonds.json").read_text())
    assert saved["fingerprint"] == "sha256:" + "b" * 64
    assert saved["store_dates"]["idxscape"] == "2023-02-10"


def test_default_cache_dir_is_under_data_history():
    assert H.CACHE_DIR.parts[-2:] == ("data", "history")
