"""PLAN S38 (P58-flows): household transfers matched across financer's statements.

Fixture: `tests/fixtures/flows/` on top of `tests/fixtures/financer/schema.sql` (invented accounts
and names; the expected October is written at the top of `flows/seed.sql`). A temp out/ only; no
real store, out/ or network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jsonschema
import pytest
from helpers import FIXTURES, make_sqlite

from assist import cli, flows
from assist.sources.financer import FinancerSource, Movement

FLOWS = FIXTURES / "flows"
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schema" / "flows.schema.json")
                    .read_text())
NAMES = {"tommy": ("ANDI CONTOH",), "priskila": ("SARI CONTOH",)}


def _db(tmp_path: Path) -> Path:
    ddl = ((FIXTURES / "financer" / "schema.sql").read_text()
           + (FLOWS / "transactions.sql").read_text() + (FLOWS / "seed.sql").read_text())
    return make_sqlite(tmp_path / "financer.db", ddl)


@pytest.fixture
def src(tmp_path: Path) -> FinancerSource:
    return FinancerSource(_db(tmp_path))


@pytest.fixture
def built(src):
    return flows.build_from(src, NAMES)


@pytest.fixture
def oct_(built) -> dict:
    return built[1]["2026-10"]


def _acct(p: dict, account_id: str) -> dict:
    return next(a for a in p["accounts"] if a["id"] == account_id)


def _pairs(p: dict) -> list[tuple]:
    """(from last4, to last4, amount, gap) per matched transfer."""
    return [(_acct(p, t["from"])["account"], _acct(p, t["to"])["account"], t["amount"],
             t["gap_days"]) for t in p["transfers"]]


def test_savings_to_rdn_between_owners_matches(oct_):
    t = next(t for t in oct_["transfers"] if t["amount"] == 1_000_000)
    a, b = _acct(oct_, t["from"]), _acct(oct_, t["to"])
    assert (a["issuer"], a["account"], a["owner"]) == ("bca_tahapan", "1111", "tommy")
    assert (b["issuer"], b["account"], b["owner"]) == ("bca_rdn", "8888", "priskila")
    assert (t["date"], t["date_to"], t["gap_days"], t["kind"]) == (
        "2026-10-02", "2026-10-03", 1, "transfer")
    # matched, so the name in it does not make it an unmatched named debit
    assert all(u["amount"] != 1_000_000 for u in oct_["unmatched_named"])


def test_rdn_to_trades_settlement_matches_one_movement_not_fee_rows(oct_):
    t = next(t for t in oct_["transfers"] if t["kind"] == "settlement")
    assert _pairs({**oct_, "transfers": [t]}) == [("2222", "3333", 500_050.0, 0)]
    assert t["date"] == "2026-10-07"
    amounts = {e["amount"] for e in oct_["transfers"]}
    ext = [a for a in oct_["external"]["accounts"] if a["account"] == t["to"]]
    assert 500_000.0 not in amounts and 50.0 not in amounts and not ext  # fee rows never appear


def test_savings_to_card_payment_matches(oct_):
    t = next(t for t in oct_["transfers"] if t["kind"] == "card_payment")
    assert _pairs({**oct_, "transfers": [t]}) == [("1111", "4444", 2_500_000.0, 1)]


@pytest.mark.parametrize("amount", [300_000.0, 300_001.0, 700_000.0, 1_450_000.0])
def test_no_match_for_one_rupiah_four_days_or_same_account(oct_, amount):
    assert all(t["amount"] != amount for t in oct_["transfers"])


def test_two_equal_transfers_pair_one_to_one(oct_):
    ts = [t for t in oct_["transfers"] if t["amount"] == 250_000]
    assert [(t["date"], t["date_to"], t["gap_days"]) for t in ts] == [
        ("2026-10-15", "2026-10-15", 0), ("2026-10-16", "2026-10-16", 0)]


def test_matched_transfers_in_october(oct_):
    assert sorted(_pairs(oct_)) == sorted([
        ("1111", "8888", 1_000_000.0, 1), ("2222", "3333", 500_050.0, 0),
        ("1111", "4444", 2_500_000.0, 1), ("1111", "2222", 250_000.0, 0),
        ("1111", "2222", 250_000.0, 0)])
    assert oct_["totals"]["transfers"] == {"n": 5, "amount": 4_500_050.0}


def test_named_debit_without_receiving_statement_is_listed(oct_):
    (u,) = oct_["unmatched_named"]
    assert (u["date"], u["amount"], u["to_owner"]) == ("2026-10-14", 4_000_000.0, "priskila")
    assert _acct(oct_, u["from"])["account"] == "1111"
    assert u["reason"] == "to priskila, receiving account has no statement in financer"


def test_settlement_without_rdn_statement_is_listed(oct_):
    (u,) = oct_["unmatched_settlements"]
    a = _acct(oct_, u["account"])
    assert (a["issuer"], a["account"], a["owner"]) == ("stockbit", "7777", "priskila")
    assert (u["date"], u["amount"], u["direction"]) == ("2026-10-20", 1_234_567.89, "credit")
    assert u["reason"] == "paid from RDN (statement not loaded)"


def test_superseded_documents_are_ignored(oct_):
    # the superseded TC (4,000,000 on 10-21) and the superseded RDN credit of 700,000 on 10-05
    assert all(u["amount"] != 4_000_000 for u in oct_["unmatched_settlements"])
    assert all(t["amount"] != 700_000 for t in oct_["transfers"])


def test_card_purchase_is_spending_never_a_transfer():
    d = date(2026, 10, 1)
    buy = Movement(d, "bca_cc", "C1", "tommy", "credit_card_statement", 1, "debit", 100, "x",
                   "x", 1)
    back = Movement(d, "bca_rdn", "R1", "tommy", "savings_statement", 2, "credit", 100, "y",
                    "y", 2)
    pairs, rest = flows.match([buy, back])
    assert pairs == [] and rest == [buy, back]


def test_greedy_prefers_the_smallest_gap():
    def m(day, acct, direction, ref):
        return Movement(date(2026, 10, day), "bca_rdn", acct, "tommy", "savings_statement",
                        ref, direction, 500, "", "", ref)
    early, late = m(1, "A", "debit", 1), m(3, "A", "debit", 2)
    cr = m(3, "B", "credit", 3)
    pairs, rest = flows.match([early, late, cr])
    assert [(p.debit, p.credit, p.gap_days) for p in pairs] == [(late, cr, 0)]
    assert rest == [early]


def test_external_totals_per_account_and_owner(oct_):
    ext = {(_acct(oct_, a["account"])["account"]): a for a in oct_["external"]["accounts"]}
    assert ext["4444"]["out"] == 2_500_000.0 and ext["4444"]["in"] == 0  # the purchase
    # salary 10M in; out: 700,000 + 1,450,000 + 300,000 (the transfer 4M is listed as named)
    assert ext["1111"]["in"] == 10_000_000.0 + 1_450_000.0
    assert ext["1111"]["out"] == 700_000.0 + 1_450_000.0 + 300_000.0
    assert ext["5555"]["in"] == 700_000.0 + 300_001.0
    owners = {o["owner"]: o for o in oct_["external"]["owners"]}
    assert owners["priskila"]["in"] == 1_000_001.0
    assert owners["tommy"]["out"] == 2_500_000.0 + 2_450_000.0


def test_accounts_show_last4_and_statement_balances(oct_):
    sav = next(a for a in oct_["accounts"] if a["issuer"] == "bca_tahapan")
    assert (sav["account"], sav["owner"], sav["opening"], sav["closing"]) == (
        "1111", "tommy", 11_000_000.0, 9_000_000.0)
    sb = next(a for a in oct_["accounts"] if a["issuer"] == "stockbit")
    assert (sb["opening"], sb["closing"]) == (None, None)


def test_stale_inputs_name_missing_statements(oct_, built):
    text = " | ".join(oct_["stale_inputs"])
    assert "cimb_cc ·9999 (tommy): no statement dated 2026-10 (latest 2026-09-17)" in text
    assert "bca_rdn ·9999 (priskila): mapped in financer, no statement loaded" in text
    assert "cimb_cc" not in " ".join(built[1]["2026-09"]["stale_inputs"])


def test_no_household_file_means_no_named_matches(src, tmp_path):
    assert flows.load_household(tmp_path / "absent.yaml") == {}
    _, months = flows.build_from(src, {})
    assert months["2026-10"]["unmatched_named"] == []
    assert len(months["2026-10"]["transfers"]) == 5


def test_load_household(tmp_path):
    assert flows.load_household(FLOWS / "household.yaml") == NAMES
    bad = tmp_path / "h.yaml"
    bad.write_text("owners: [1, 2]\n")
    assert flows.load_household(bad) == {}


def test_index_and_months(built):
    index, months = built
    assert sorted(months) == ["2026-09", "2026-10"]
    assert index["latest"] == "2026-10" and index["as_of"] == "2026-10-25"
    assert [m["month"] for m in index["months"]] == ["2026-09", "2026-10"]
    assert index["months"][1]["file"] == "2026-10.json"


def test_months_keeps_the_latest_n(src):
    index, months = flows.build_from(src, NAMES, months=1)
    assert list(months) == ["2026-10"] and [m["month"] for m in index["months"]] == ["2026-10"]


def test_files_match_the_schema(built):
    index, months = built
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    for p in months.values():
        jsonschema.validate(p, SCHEMA)
    jsonschema.validate(index, {"$ref": "#/$defs/index", "$defs": SCHEMA["$defs"]})


def test_files_carry_no_full_account_number_or_name(built, tmp_path):
    flows.write(*built, tmp_path / "out")
    text = "".join(p.read_text() for p in (tmp_path / "out" / "flows").iterdir())
    for secret in ("SAV-1111", "RDN-9999", "SB-7777", "SARI CONTOH", "Sari Contoh", "ANDI"):
        assert secret not in text


def test_rerun_writes_byte_identical_files(src, tmp_path):
    out = tmp_path / "out"
    flows.write(*flows.build_from(src, NAMES), out)
    first = {p.name: p.read_bytes() for p in (out / "flows").iterdir()}
    flows.write(*flows.build_from(src, NAMES), out)
    assert {p.name: p.read_bytes() for p in (out / "flows").iterdir()} == first
    assert set(first) == {"index.json", "2026-09.json", "2026-10.json"}


def test_cli_writes_the_files(tmp_path, monkeypatch, capsys):
    db = _db(tmp_path)
    monkeypatch.setenv("ASSIST_FINANCER_DB", str(db))
    out = tmp_path / "out"
    rc = cli.main(["flows", "--out", str(out), "--household", str(FLOWS / "household.yaml")])
    assert rc == 0
    assert (out / "flows" / "2026-10.json").is_file() and (out / "flows" / "index.json").is_file()
    said = capsys.readouterr().out
    assert "2026-10: 5 matched" in said and "1 named unmatched" in said


def test_cli_without_a_store_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ASSIST_FINANCER_DB", str(tmp_path / "absent.db"))
    rc = cli.main(["flows", "--out", str(tmp_path / "out")])
    assert rc == 1 and "financer" in capsys.readouterr().err
    assert not (tmp_path / "out" / "flows").exists()


def test_example_household_is_committed_and_the_real_one_ignored():
    repo = Path(__file__).resolve().parents[1]
    assert set(flows.load_household(repo / "config" / "household.example.yaml")) == {"alice",
                                                                                      "bob"}
    assert "/config/household.local.yaml" in (repo / ".gitignore").read_text().splitlines()
    assert repo / "config" / "household.local.yaml" == flows.HOUSEHOLD
