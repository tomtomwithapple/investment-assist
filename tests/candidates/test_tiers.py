"""Top tier per industry (S31, P48): percentiles with mid-rank ties, hand-worked ranks on a fixture
industry, gates with every reason listed, a one-off gain that must not rank first, a bank
industry on its own metric set and floor, a thin industry ranked within its sector, an industry
with no Tier A, coverage and degradation when inputs are missing, the fingerprint, a
byte-identical rerun and the `industries` journal record. Fixtures in tests/fixtures/tiers/
(built through `peers.build`, so the schema 4 payload is what is tested); no store."""

from __future__ import annotations

import copy
import json
import math
from datetime import date
from pathlib import Path

import pytest

from assist import journal, pipeline
from assist.candidates import peers, tiers
from assist.sources.idxmethod_comparison import Comparison

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tiers"
DAY = date(2026, 10, 27)
FID = {key: fid for _, key, fid, _ in peers.METRICS} | {"mktcap": peers.MKTCAP}


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def _cmp(fx: dict, reverse: bool = False) -> tuple[Comparison, dict]:
    """A `Comparison` and the extras from a fixture; statements are laid on the last quarters."""
    c = Comparison(date=date.fromisoformat(fx["as_of"]))
    quarters = peers.periods({"x": {"revenue": {"2026Q2": 1.0}}}, 12)
    extras = {}
    items = sorted(fx["names"].items(), reverse=reverse)
    for sym, n in items:
        c.ratios[sym] = {FID[k]: v for k, v in n["values"].items()}
        c.industry[sym] = n["industry"]
        c.sector_key[sym] = c.sectors[sym] = n["sector"]
        c.names[sym] = f"{sym} Tbk"
        c.industry_avg[sym] = {FID["pe"]: 10.0}
        c.sector_avg[sym] = {FID["pe"]: 10.0}
        c.competitors[sym] = []
        for item, xs in (n.get("statements") or {}).items():
            c.statements.setdefault(sym, {})[item] = dict(zip(quarters[-len(xs):], xs,
                                                              strict=True))
        extras[sym] = n.get("extra") or {}
    return c, extras


def _build(name: str, **kw) -> dict:
    c, extras = _cmp(_load(name))
    return peers.build(c, DAY, extras=extras, **kw)


def _ind(p: dict, iid: str) -> dict:
    return next(i for i in p["industries"] if i["id"] == iid)


def _stock(p: dict, sym: str) -> dict:
    return next(s for i in p["industries"] for s in i["stocks"] if s["symbol"] == sym)


# ---------------- pieces ----------------


def test_percentiles_mid_rank_ties_and_flip():
    got = tiers.percentiles({"a": 1.0, "b": 2.0, "c": 2.0, "d": 4.0})
    # ranks 1, 2.5, 2.5, 4 of 4 → (r - 0.5) / 4 * 100
    assert got == {"a": 12.5, "b": 50.0, "c": 50.0, "d": 87.5}
    low = tiers.percentiles({"a": 1.0, "b": 2.0, "c": 2.0, "d": 4.0}, lower_is_better=True)
    assert low == {"a": 87.5, "b": 50.0, "c": 50.0, "d": 12.5}
    assert tiers.percentiles({"a": math.inf, "b": 3.0}, True) == {"a": 25.0, "b": 75.0}
    assert tiers.percentiles({}) == {}


@pytest.mark.parametrize(("n", "k"), [(0, 0), (1, 1), (4, 1), (9, 1), (10, 2), (15, 3),
                                      (39, 3), (40, 5), (100, 5)])
def test_tier_size(n, k):
    assert tiers.tier_size(n) == k


def test_der_cap_lives_in_the_model_and_the_view_reads_it():
    from assist.views import industries

    assert industries.der_cap is tiers.der_cap and industries.DER_CAP is tiers.DER_CAP
    assert tiers.der_cap("Bank") is None and tiers.der_cap("Rokok") == 0.5
    assert tiers.der_cap("anything else") == tiers.DER_CAP_DEFAULT == 1.0


def test_fingerprint_is_the_config_sha():
    fp = tiers.fingerprint()
    assert journal.FINGERPRINT_RE.fullmatch(fp)
    other = copy.deepcopy(tiers.CONFIG)
    other["weights"]["value"] = 31
    assert tiers.fingerprint(other) != fp and tiers.fingerprint(copy.deepcopy(tiers.CONFIG)) == fp


# ---------------- the hand-worked industry ----------------


@pytest.fixture(scope="module")
def manuf() -> dict:
    return _build("industry.json")


def test_schema_4_payload_shape(manuf):
    assert manuf["schema_version"] == 4
    assert manuf["fingerprint"] == tiers.fingerprint()
    assert manuf["tier_config"]["weights"] == {"value": 30, "quality": 25, "growth": 15,
                                               "health": 15, "momentum": 15}
    s = _stock(manuf, "MNF1")
    assert {"gates", "pillars", "composite", "rank", "pick", "metrics"} <= set(s)
    assert {"peer_group", "picks", "gated", "gate_failures"} <= set(_ind(manuf, "manuf"))
    assert s["values"]["pe"] == 5 and "score_industry" in s  # S30 fields kept


def test_gates_list_every_reason(manuf):
    assert _stock(manuf, "MNF1")["gates"] == {"pass": True, "fail": [], "missing": ["piotroski"]}
    assert _stock(manuf, "XILQ")["gates"]["fail"] == ["trades too rarely", "liquidity"]
    assert _stock(manuf, "XLOS")["gates"]["fail"] == ["TTM loss"]
    assert _stock(manuf, "XDER")["gates"]["fail"] == ["F-score", "D/E above cap"]
    ind = _ind(manuf, "manuf")
    assert ind["gated"] == 8
    assert ind["gate_failures"] == {"D/E above cap": 1, "F-score": 1, "TTM loss": 1,
                                    "liquidity": 1, "trades too rarely": 1}
    for sym in ("XILQ", "XLOS", "XDER"):
        s = _stock(manuf, sym)
        assert s["composite"] is None and s["rank"] is None and s["pick"] is None
        assert s["pillars"] == {}


def test_hand_worked_ranks(manuf):
    """MNF1..8 are ordered on every value, quality and health metric (MNF1 best) and the other
    way on momentum; no statements, so growth is missing and the weights rescale to 85. With
    p = (8.5 - i) / 8 * 100 and q = (i - 0.5) / 8 * 100 the composite is (70p + 15q) / 85."""
    ind = _ind(manuf, "manuf")
    assert ind["peer_group"] == {"level": "industry", "label": "Perindustrian", "n": 8}
    want = {1: 78.31, 2: 70.22, 3: 62.13, 4: 54.04, 5: 45.96, 6: 37.87, 7: 29.78, 8: 21.69}
    for i, comp in want.items():
        s = _stock(manuf, f"MNF{i}")
        p, q = (8.5 - i) * 12.5, (i - 0.5) * 12.5
        assert s["pillars"]["value"] == {"score": p, "metrics": 4, "of": 4,
                                         "pct": {"pe_norm": p, "pbv": p, "ev_ebitda": p, "ps": p}}
        assert s["pillars"]["quality"]["score"] == p and s["pillars"]["quality"]["metrics"] == 3
        assert s["pillars"]["health"]["score"] == p
        assert s["pillars"]["momentum"]["score"] == q
        assert s["pillars"]["growth"]["score"] is None
        assert s["composite"] == comp and s["rank"] == i
    # 8 gated → k = max(1, floor(1.6)) = 1: MNF1 is Tier A (>= 60), MNF2 Tier B (>= 50)
    assert ind["picks"] == {"A": ["MNF1"], "B": ["MNF2"]}
    assert [_stock(manuf, f"MNF{i}")["pick"] for i in (1, 2, 3)] == ["A", "B", None]


def test_thin_industry_ranks_within_its_sector(manuf):
    """3 names pass in `thin`, fewer than 8, so its percentiles are over the 11 gated names of
    the sector (8 manuf + 3 thin); manuf's own ranks do not see the thin names."""
    ind = _ind(manuf, "thin")
    assert ind["peer_group"] == {"level": "sector", "label": "Perindustrian", "n": 11}
    pe = {s: _stock(manuf, s)["pillars"]["value"]["pct"]["pe_norm"] for s in ("THN1", "THN2",
                                                                            "THN3")}
    # PE 4.5 is the lowest of 11 (rank 1), 9.5 the 7th, 30 the highest
    assert pe == {"THN1": 95.45, "THN2": 40.91, "THN3": 4.55}
    assert [_stock(manuf, s)["rank"] for s in ("THN1", "THN2", "THN3")] == [1, 2, 3]
    # THN1: value (95.45 + 3 × 54.55) / 4 = 64.78 (on PBV, EV/EBITDA and P/S it ties 4 ways
    # with MNF4 and its two peers),
    # quality and health 54.55, momentum 45.45 → (30·64.78 + 40·54.55 + 15·45.45) / 85 = 56.55:
    # under 60, so k = 1 goes to Tier B
    assert _stock(manuf, "THN1")["pillars"]["value"]["score"] == 64.78
    assert _stock(manuf, "THN1")["composite"] == 56.55
    assert ind["picks"] == {"A": [], "B": ["THN1"]}


def test_no_tier_a():
    """Value and health run one way, quality and momentum the other: the best composite is
    (5 × 93.75 + 4000) / 85 = 52.57, under 60, so no Tier A; it is still Tier B."""
    p = _build("no_tier_a.json")
    ind = _ind(p, "mixed")
    assert _stock(p, "MIX1")["composite"] == 52.57
    assert ind["picks"] == {"A": [], "B": ["MIX1"]}


def test_a_one_off_gain_does_not_rank_first():
    """ONEO's last quarter books 300 against a run rate of 10: TTM 330, a year and two years
    back 40, so Stockbit's PE is 2 but the normalised PE is 660 / min(330, 136.7) = 4.83."""
    p = _build("one_off.json")
    o = _stock(p, "ONEO")
    assert o["metrics"]["pe_norm"] == pytest.approx(660 / (410 / 3), abs=1e-3)
    assert o["values"]["pe"] == 2.0
    pcts = {s["symbol"]: s["pillars"]["value"]["pct"]["pe_norm"]
            for s in _ind(p, "oneoff")["stocks"]}
    assert max(pcts, key=pcts.get) == "ONE1" and pcts["ONEO"] < pcts["ONE1"]
    assert o["metrics"]["ni_yoy"] == pytest.approx(725.0)
    assert o["rank"] != 1 and _stock(p, "ONE1")["rank"] == 1
    assert _ind(p, "oneoff")["picks"]["A"] == ["ONE1"]


def test_bank_industry_uses_its_metric_set_and_floor():
    p = _build("banks.json")
    ind = _ind(p, "bank")
    assert ind["label"] == "Bank" and ind["peer_group"]["level"] == "industry"
    assert _stock(p, "BCAR")["gates"]["fail"] == ["CAR"]
    b = _stock(p, "BBCA")
    assert b["gates"] == {"pass": True, "fail": [], "missing": []}  # no D/E gate, no F-score
    assert b["pillars"]["value"]["of"] == 2 and set(b["pillars"]["value"]["pct"]) == {
        "pe_norm", "pbv"}
    assert set(b["pillars"]["health"]["pct"]) == {"car", "npl", "npl_cov", "ldr"}
    assert set(b["pillars"]["quality"]["pct"]) == {"roe", "roa"}  # no statements: no stability
    assert b["pillars"]["health"]["score"] == 93.75 and b["composite"] == 78.31
    assert ind["picks"] == {"A": ["BBCA"], "B": ["BBRI"]}


# ---------------- coverage and degradation ----------------


def test_no_extras_fails_the_liquidity_gate_without_crashing():
    c, _ = _cmp(_load("industry.json"))
    p = peers.build(c, DAY)
    assert all(s["gates"]["fail"][:1] == ["no liquidity data"]
               for i in p["industries"] for s in i["stocks"])
    assert all(i["picks"] == {"A": [], "B": []} for i in p["industries"])


def test_missing_momentum_is_a_missing_pillar_and_weights_rescale():
    fx = _load("industry.json")
    for n in fx["names"].values():
        n["extra"] = {k: n["extra"][k] for k in ("days_traded_60", "med_value_60d")}
    c, extras = _cmp(fx)
    p = peers.build(c, DAY, extras=extras)
    s = _stock(p, "MNF1")
    assert s["pillars"]["momentum"] == {"score": None, "metrics": 0, "of": 2, "pct": {}}
    assert s["composite"] == 93.75  # value, quality, health only: all 93.75


def test_a_metric_with_fewer_than_5_peers_is_dropped():
    fx = _load("industry.json")
    for i in range(1, 9):
        if i > 4:
            fx["names"][f"MNF{i}"]["values"].pop("ps")
    c, extras = _cmp(fx)
    p = peers.build(c, DAY, extras=extras)
    v = _stock(p, "MNF1")["pillars"]["value"]
    assert "ps" not in v["pct"] and v["metrics"] == 3


def test_composite_needs_value_and_quality():
    fx = _load("industry.json")
    for n in fx["names"].values():
        for k in ("roe", "roic", "opm"):
            n["values"].pop(k)
    c, extras = _cmp(fx)
    p = peers.build(c, DAY, extras=extras)
    s = _stock(p, "MNF1")
    assert s["pillars"]["quality"]["score"] is None and s["composite"] is None
    assert s["rank"] is None and _ind(p, "manuf")["picks"] == {"A": [], "B": []}


# ---------------- determinism and journal ----------------


def test_byte_identical_rerun(tmp_path):
    fx = _load("industry.json")
    texts = []
    for i, rev in enumerate((False, False, True)):
        c, extras = _cmp(fx, reverse=rev)
        path = peers.write(peers.build(c, DAY, extras=extras), tmp_path / str(i))
        texts.append(path.read_bytes())
    assert texts[0] == texts[1] == texts[2]


def test_industries_journal_record(tmp_path, manuf):
    path = peers.write(manuf, tmp_path)
    j = journal.Journal(tmp_path / "journal")
    fp = j.register_model({"config": {}, "rules": {}, "config_files": {}})
    pipeline._journal_peers(j, path, fp, "run1")
    (rec,) = list(j.read())
    assert rec["kind"] == "industries" and rec["subject"] == "IDN" and rec["run_id"] == "run1"
    out = rec["outputs"]
    assert out["tier_fingerprint"] == tiers.fingerprint() and out["moves_stance"] is False
    assert out["picks"]["manuf"]["A"] == ["MNF1"] and out["picks"]["manuf"]["B"] == ["MNF2"]
    assert out["names"]["MNF1"]["pillars"]["value"] == 93.75
    assert "XILQ" not in out["names"]  # gated out: no pillars to journal
    assert rec["inputs"]["tier_config"] == tiers.CONFIG | {}  # JSON round trip of CONFIG


def test_industries_journal_never_raises(tmp_path):
    j = journal.Journal(tmp_path / "journal")
    fp = j.register_model({"config": {}, "rules": {}, "config_files": {}})
    pipeline._journal_peers(j, None, fp, None)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    pipeline._journal_peers(j, bad, fp, None)
    assert list(j.read()) == []
