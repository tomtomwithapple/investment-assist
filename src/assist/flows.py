"""Where the household's money moved (PLAN S38): transfers between the household's own accounts,
matched across financer's statements, and the gaps where one side has no statement.

Pure functions over `FinancerSource.movements()`, `ledgers()` and `owner_map()`; `assist flows`
writes `out/flows/<YYYY-MM>.json` for the latest `MONTHS` months with data, plus
`out/flows/index.json` (`schema/flows.schema.json`). Context only: nothing here moves a stance.

- **Internal transfer.** A debit in account A pairs with a credit in another account B when the
  amounts are equal to the rupiah and the dates are at most `MAX_GAP_DAYS` apart, one to one,
  greedy by the smallest gap, then the debit's date, then document id (then row, for a stable
  order). A card's debits are purchases, i.e. spending, and never a transfer; a card's credit (a
  payment) can be. A trades document is one movement, its settlement (see the adapter).
- **Named but unmatched.** An unpaired debit whose `raw_description` contains a name from the
  gitignored `config/household.local.yaml` (`owners: {key: [NAME, ...]}`, case-insensitive) goes
  "to <owner>, receiving account has no statement in financer". The names never reach the files.
- **Unmatched settlement.** An unpaired trades document: "paid from RDN (statement not loaded)"
  for a buy, "proceeds to RDN (statement not loaded)" for a sale.
- Everything else is external in or out, totalled per account and per owner.

A matched transfer belongs to the month of its debit; every other item to its own date's month.
Accounts are shown by their last 4 characters only. `stale_inputs` names an account with a
statement dated in the previous month and none in this one, and an account financer maps to an
owner that has no statement at all.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import NamedTuple

import yaml

from assist.sources.financer import (
    CARD_DOC_TYPE,
    SOURCE,
    TRADE_DOC_TYPE,
    FinancerSource,
    Ledger,
    Movement,
)

SCHEMA_VERSION = "1.0.0"
MAX_GAP_DAYS = 3
MONTHS = 12
OUT_DIR = Path("flows")
INDEX = "index.json"
MONTH_RX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
HOUSEHOLD = Path(__file__).resolve().parents[2] / "config" / "household.local.yaml"
DISCLAIMER = ("Heuristic, not investment advice. Transfers are matched on amount and date only, "
              "from financer's statements; a missing statement leaves its side unmatched.")
RULES = {"max_gap_days": MAX_GAP_DAYS, "amount": "equal to the rupiah",
         "pairing": "one to one, greedy by smallest gap, then date, then document id",
         "card_purchases": "spending, never a transfer"}
NAMED_REASON = "to {owner}, receiving account has no statement in financer"
SETTLE_REASON = {"credit": "paid from RDN (statement not loaded)",
                 "debit": "proceeds to RDN (statement not loaded)"}


class Transfer(NamedTuple):
    debit: Movement
    credit: Movement
    gap_days: int


# ---------------- household names ----------------


def load_household(path: Path | str = HOUSEHOLD) -> dict[str, tuple[str, ...]]:
    """owner → names from the gitignored household file; {} when it is missing or malformed."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    owners = raw.get("owners") if isinstance(raw, dict) else None
    if not isinstance(owners, dict):
        return {}
    return {str(k): tuple(str(n) for n in v if str(n).strip())
            for k, v in owners.items() if isinstance(v, list)}


def named_owner(m: Movement, names: Mapping[str, Sequence[str]]) -> str | None:
    text = m.raw_description.upper()
    for owner in sorted(names):
        if any(n.upper() in text for n in names[owner]):
            return owner
    return None


# ---------------- matching ----------------


def _key(m: Movement) -> tuple[str, str, str]:
    return (m.issuer, m.account, m.owner)


def _rupiah(m: Movement) -> int:
    return (m.amount_minor + 50) // 100  # half up, to the rupiah


def _order(m: Movement) -> tuple:
    return (m.date, m.document_id, m.ref or 0)


def match(movements: Iterable[Movement]) -> tuple[list[Transfer], list[Movement]]:
    """(pairs, the rest), both in a stable order (PLAN S38)."""
    ms = list(movements)
    debits: dict[int, list[Movement]] = defaultdict(list)
    credits: dict[int, list[Movement]] = defaultdict(list)
    for m in ms:
        if m.direction == "debit" and m.doc_type != CARD_DOC_TYPE:
            debits[_rupiah(m)].append(m)
        elif m.direction == "credit":
            credits[_rupiah(m)].append(m)
    cands = []
    for amount, ds in debits.items():
        for d in ds:
            for c in credits.get(amount, ()):
                gap = abs((c.date - d.date).days)
                if gap <= MAX_GAP_DAYS and _key(d) != _key(c):
                    cands.append((gap, _order(d), _order(c), d, c))
    cands.sort(key=lambda x: x[:3])
    used: set[int] = set()
    pairs = []
    for gap, _, _, d, c in cands:
        if id(d) in used or id(c) in used:
            continue
        used.update((id(d), id(c)))
        pairs.append(Transfer(d, c, gap))
    pairs.sort(key=lambda t: (_order(t.debit), _order(t.credit)))
    rest = [m for m in ms if id(m) not in used]
    return pairs, rest


# ---------------- payloads ----------------


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _last4(account: str) -> str:
    return account[-4:]


def _id(issuer: str, account: str, owner: str) -> str:
    return f"{issuer}-{_last4(account)}-{owner}"


def _label(issuer: str, account: str, owner: str) -> str:
    last4 = _last4(account)
    return f"{issuer}{' ·' + last4 if last4 else ''} ({owner})"


def _amt(minor: int) -> float:
    return round(minor / 100, 2)


def _kind(t: Transfer) -> str:
    if TRADE_DOC_TYPE in (t.debit.doc_type, t.credit.doc_type):
        return "settlement"
    if t.credit.doc_type == CARD_DOC_TYPE:
        return "card_payment"
    return "transfer"


def _prev(month: str) -> str:
    y, m = int(month[:4]), int(month[5:])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def _stale(month: str, ledgers: Sequence[Ledger], unmapped: Sequence[str]) -> list[str]:
    by_acct: dict[tuple, list[date]] = defaultdict(list)
    for x in ledgers:
        by_acct[(x.issuer, x.account, x.owner)].append(x.statement_date)
    out = []
    for (iss, acct, own), days in sorted(by_acct.items()):
        months = {_month(d) for d in days}
        if _prev(month) in months and month not in months:
            latest = max(d for d in days if _month(d) < month)
            out.append(f"{_label(iss, acct, own)}: no statement dated {month} "
                       f"(latest {latest.isoformat()})")
    return out + list(unmapped)


def _unmapped(owner_map: Sequence[tuple[str, str, str]], ledgers: Sequence[Ledger],
              movements: Sequence[Movement]) -> list[str]:
    seen = {(x.issuer, x.account) for x in ledgers} | {(m.issuer, m.account) for m in movements}
    return [f"{_label(iss, acct, own)}: mapped in financer, no statement loaded"
            for iss, acct, own in sorted(owner_map) if (iss, acct) not in seen]


def build(movements: Sequence[Movement], ledgers: Sequence[Ledger],
          owner_map: Sequence[tuple[str, str, str]], names: Mapping[str, Sequence[str]],
          months: int = MONTHS) -> tuple[dict, dict[str, dict]]:
    """(index, {month: payload}) for the latest `months` months with a movement."""
    pairs, rest = match(movements)
    all_months = sorted({_month(m.date) for m in movements})
    keep = all_months[-months:] if months > 0 else []
    unmapped = _unmapped(owner_map, ledgers, movements)
    payloads = {}
    for month in keep:
        payloads[month] = _payload(month, pairs, rest, movements, ledgers, names, unmapped)
    index = {
        "schema_version": SCHEMA_VERSION,
        "as_of": max(m.date for m in movements).isoformat() if movements else None,
        "latest": keep[-1] if keep else None,
        "months": [{"month": k, "file": f"{k}.json",
                    "transfers": len(payloads[k]["transfers"]),
                    "unmatched": len(payloads[k]["unmatched_named"])
                    + len(payloads[k]["unmatched_settlements"])} for k in keep],
        "stale_inputs": list(unmapped),
        "sources": [SOURCE],
        "disclaimer": DISCLAIMER,
    }
    return index, payloads


def _payload(month: str, pairs: Sequence[Transfer], rest: Sequence[Movement],
             movements: Sequence[Movement], ledgers: Sequence[Ledger],
             names: Mapping[str, Sequence[str]], unmapped: Sequence[str]) -> dict:
    accounts: dict[tuple, dict] = {}

    def acct(iss: str, account: str, own: str, doc_type: str) -> str:
        k = (iss, account, own)
        if k not in accounts:
            accounts[k] = {"id": _id(iss, account, own), "issuer": iss,
                           "account": _last4(account), "owner": own, "kind": doc_type,
                           "opening": None, "closing": None, "statements": []}
        elif accounts[k]["kind"] == TRADE_DOC_TYPE and doc_type != TRADE_DOC_TYPE:
            accounts[k]["kind"] = doc_type
        return accounts[k]["id"]

    def of(m: Movement) -> str:
        return acct(m.issuer, m.account, m.owner, m.doc_type)

    for x in sorted(ledgers, key=lambda x: (x.statement_date, x.issuer, x.account)):
        if _month(x.statement_date) != month:
            continue
        acct(x.issuer, x.account, x.owner, x.doc_type)
        a = accounts[(x.issuer, x.account, x.owner)]
        if a["opening"] is None:
            a["opening"] = round(x.opening, 2)
        a["closing"] = round(x.closing, 2)
        a["statements"].append(x.statement_date.isoformat())
    transfers = []
    for t in pairs:
        if _month(t.debit.date) != month:
            continue
        transfers.append({"date": t.debit.date.isoformat(), "date_to": t.credit.date.isoformat(),
                          "from": of(t.debit), "to": of(t.credit),
                          "amount": _amt(t.debit.amount_minor), "gap_days": t.gap_days,
                          "kind": _kind(t), "from_description": t.debit.description,
                          "to_description": t.credit.description})
    named, settles = [], []
    ext: dict[str, dict] = {}
    for m in rest:
        if _month(m.date) != month:
            continue
        if m.doc_type == TRADE_DOC_TYPE:
            settles.append({"date": m.date.isoformat(), "account": of(m),
                            "direction": m.direction, "amount": _amt(m.amount_minor),
                            "reason": SETTLE_REASON[m.direction]})
            continue
        owner = named_owner(m, names) if m.direction == "debit" else None
        if owner is not None:
            named.append({"date": m.date.isoformat(), "from": of(m), "to_owner": owner,
                          "amount": _amt(m.amount_minor), "description": m.description,
                          "reason": NAMED_REASON.format(owner=owner)})
            continue
        e = ext.setdefault(of(m), {"account": of(m), "in": 0, "out": 0, "n_in": 0, "n_out": 0})
        side = "in" if m.direction == "credit" else "out"
        e[side] += m.amount_minor
        e[f"n_{side}"] += 1
    owner_of = {a["id"]: a["owner"] for a in accounts.values()}
    by_owner: dict[str, dict] = {}
    for e in ext.values():
        o = by_owner.setdefault(owner_of[e["account"]],
                                {"owner": owner_of[e["account"]], "in": 0, "out": 0})
        o["in"] += e["in"]
        o["out"] += e["out"]
    for e in (*ext.values(), *by_owner.values()):
        e["in"], e["out"] = _amt(e["in"]), _amt(e["out"])
    days = [m.date for m in movements if _month(m.date) == month]
    acc = sorted(accounts.values(), key=lambda a: (a["owner"], a["issuer"], a["account"]))

    def total(items: list[dict]) -> dict:
        return {"n": len(items), "amount": round(sum(i["amount"] for i in items), 2)}

    return {
        "schema_version": SCHEMA_VERSION,
        "month": month,
        "as_of": max(days).isoformat(),
        "currency": "IDR",
        "rules": RULES,
        "accounts": acc,
        "transfers": transfers,
        "unmatched_named": named,
        "unmatched_settlements": settles,
        "external": {"accounts": sorted(ext.values(), key=lambda e: e["account"]),
                     "owners": sorted(by_owner.values(), key=lambda o: o["owner"])},
        "totals": {"transfers": total(transfers), "unmatched_named": total(named),
                   "unmatched_settlements": total(settles)},
        "stale_inputs": _stale(month, ledgers, unmapped),
        "sources": [SOURCE],
        "disclaimer": DISCLAIMER,
    }


def build_from(source: FinancerSource, names: Mapping[str, Sequence[str]],
               months: int = MONTHS) -> tuple[dict, dict[str, dict]]:
    """Read the store once (read-only) and build every file."""
    return build(source.movements(), source.ledgers(), source.owner_map(), names, months)


# ---------------- files ----------------


def _dump(obj: Mapping) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _write(path: Path, text: str) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def write(index: Mapping, payloads: Mapping[str, Mapping], out_dir: Path) -> list[Path]:
    """`out/flows/<YYYY-MM>.json` per month, then `index.json`; a file is rewritten only when its
    bytes change."""
    root = Path(out_dir) / OUT_DIR
    paths = []
    for month, p in sorted(payloads.items()):
        if not MONTH_RX.match(month):
            raise ValueError(f"not a month: {month!r}")
        path = root / f"{month}.json"
        _write(path, _dump(p))
        paths.append(path)
    _write(root / INDEX, _dump(index))
    return [*paths, root / INDEX]

