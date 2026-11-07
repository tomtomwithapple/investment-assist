"""Decision journal + model fingerprint (CLAUDE.md Rules, PLAN S5/S13).

Every decision is appended to `journal/decisions.jsonl` (gitignored) as one JSON line holding its
inputs, its outputs and the fingerprint of the model that made it, so a rule change segments the
record instead of averaging two regimes. Lines are never rewritten: each carries a running `seq`,
the hash of the line before it (`prev`) and its own hash, and `verify()` checks the chain.

The fingerprint is sha256 over the canonical JSON of four things:
- `config`: the hand-set weights, bands and tilts (`stance.MODEL_CONFIG` by default);
- `rules`: sha256 of each rule module's normalised AST (stance, layers, candidates, placebo
  eval): the module is parsed with `ast`, the module, class and function docstrings are dropped,
  and `ast.dump(tree, include_attributes=False)` is hashed. Comments, docstrings, blank lines,
  formatting and line numbers therefore leave the fingerprint unchanged, while any change to code
  (a constant, an expression, a name, a signature, a string that is not a docstring) changes it
  (S41; before it the raw bytes were hashed, so the switch segmented the record once);
- `config_files`: sha256 of each model config file's bytes under `config/` (not `sources.yaml`,
  which only says where stores live);
- `rules_method`: `RULES_METHOD`, so a change of hashing method shows in the stored inputs.
Paths are kept relative, so the same code checked out elsewhere has the same fingerprint. The full
inputs behind each fingerprint are kept once in `journal/models/<hex>.json`, so two segments can be
diffed later.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assist import stance

if os.name == "nt":
    import msvcrt

    def _lock(fh) -> None:
        """Exclusive lock on the file's first byte (msvcrt locks ranges, not whole files)."""
        fh.seek(0)
        while True:
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)  # retries for ~10 s, then raises
                return
            except OSError:
                continue

    def _unlock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fh) -> None:
        fcntl.flock(fh, fcntl.LOCK_EX)

    def _unlock(fh) -> None:
        fcntl.flock(fh, fcntl.LOCK_UN)

__all__ = [
    "DECISIONS",
    "FINGERPRINT_RE",
    "RULES_METHOD",
    "Journal",
    "canonical",
    "code_digest",
    "fingerprint",
    "fingerprint_inputs",
    "jsonable",
    "model_fingerprint",
]

PACKAGE_DIR = Path(__file__).resolve().parent  # src/assist
SRC_DIR = PACKAGE_DIR.parent  # rule paths are relative to this: "assist/stance.py"
REPO_ROOT = SRC_DIR.parent
CONFIG_DIR = REPO_ROOT / "config"
JOURNAL_DIR = REPO_ROOT / "journal"
DECISIONS = "decisions.jsonl"
MODELS = "models"

FINGERPRINT_RE = re.compile(r"sha256:[0-9a-f]{64}")
# Modules whose code decides a stance or names a candidate. Adapters (sources/), the CLI and
# doctor move data around and do not change a decision, so they stay out of the fingerprint.
RULE_GLOBS = ("stance.py", "layers/*.py", "candidates/*.py", "eval/*.py")
PLUMBING_CONFIG = frozenset({"sources.yaml"})
RULES_METHOD = "sha256 of ast.dump(include_attributes=False), docstrings removed"


# ---------------- canonical JSON ----------------


def jsonable(obj: Any) -> Any:
    """Plain-JSON form of layer types and payloads: dataclasses → dicts, dates → ISO strings,
    tuples → lists, tuple dict keys (Weights) → "SUBJECT/asset". Anything else raises TypeError."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Mapping):
        return {_key(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        items = [jsonable(v) for v in obj]
        return sorted(items, key=canonical) if isinstance(obj, (set, frozenset)) else items
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return obj.as_posix()
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    raise TypeError(f"cannot journal {type(obj).__name__}: {obj!r}")


def _key(k: Any) -> str:
    if isinstance(k, tuple):
        return "/".join(str(p) for p in k)
    if isinstance(k, (date, datetime)):
        return k.isoformat()
    return str(k)


def canonical(obj: Any) -> str:
    """Compact JSON with sorted keys: equal content gives equal text."""
    return json.dumps(jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _sha(text: str | bytes) -> str:
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


# ---------------- fingerprint ----------------


def default_rule_files() -> list[Path]:
    return sorted({p for g in RULE_GLOBS for p in PACKAGE_DIR.glob(g) if p.is_file()})


def default_config_files() -> list[Path]:
    if not CONFIG_DIR.is_dir():
        return []
    return sorted(p for p in CONFIG_DIR.iterdir()
                  if p.is_file() and p.suffix in (".yaml", ".yml", ".json")
                  and p.name not in PLUMBING_CONFIG)


_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def code_digest(source: str | bytes, filename: str = "<rule>") -> str:
    """sha256 of the module's AST without docstrings or positions (SyntaxError if it does not
    parse). Only a body's first statement, when it is a bare string, is a docstring; a body left
    empty keeps a `pass` so the tree stays valid."""
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_OWNERS):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return _sha(ast.dump(tree, include_attributes=False))


def _rel(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.name


def _file_hashes(paths: Iterable[Path], root: Path) -> dict[str, str]:
    """sha256 of each file's bytes (config files)."""
    return dict(sorted((_rel(Path(p), root), _sha(Path(p).read_bytes())) for p in paths))


def _rule_hashes(paths: Iterable[Path], root: Path) -> dict[str, str]:
    """`code_digest` of each rule module; FileNotFoundError on a missing rule: never skip it."""
    return dict(sorted((_rel(Path(p), root), code_digest(Path(p).read_bytes(), str(p)))
                       for p in paths))


def fingerprint_inputs(
    *,
    config: Mapping | None = None,
    rule_files: Iterable[Path] | None = None,
    config_files: Iterable[Path] | None = None,
    root: Path | None = None,
) -> dict:
    """What the fingerprint hashes. Defaults: `stance.MODEL_CONFIG`, the rule modules under
    src/assist (paths relative to src/) and the model files under config/ (relative to the repo).
    With explicit files, both are taken relative to `root`."""
    rule_root = root or SRC_DIR
    cfg_root = root or REPO_ROOT
    rules = default_rule_files() if rule_files is None else rule_files
    cfgs = default_config_files() if config_files is None else config_files
    return {
        "config": jsonable(stance.MODEL_CONFIG if config is None else config),
        "rules": _rule_hashes(rules, rule_root),
        "config_files": _file_hashes(cfgs, cfg_root),
        "rules_method": RULES_METHOD,
    }


def fingerprint(inputs: Mapping) -> str:
    return "sha256:" + _sha(canonical(inputs))


def model_fingerprint() -> str:
    """Fingerprint of the model as checked out: pass it to `stance.build_stance(fingerprint=…)` so
    the payload and its journal line carry the same value."""
    return fingerprint(fingerprint_inputs())


def _check_fp(fp: Any) -> str:
    if not isinstance(fp, str) or not FINGERPRINT_RE.fullmatch(fp):
        raise ValueError(f"fingerprint must look like sha256:<64 hex>, got {fp!r}")
    return fp


# ---------------- journal ----------------


class Journal:
    """Append-only decision log under `root` (default `journal/` in the repo)."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else JOURNAL_DIR
        self.path = self.root / DECISIONS

    # -- models --

    def register_model(self, inputs: Mapping | None = None) -> str:
        """Store the fingerprint's inputs once under models/; returns the fingerprint."""
        body = jsonable(fingerprint_inputs() if inputs is None else inputs)
        fp = fingerprint(body)
        path = self.root / MODELS / f"{fp.split(':', 1)[1]}.json"
        if path.exists():
            if canonical(json.loads(path.read_text(encoding="utf-8"))) != canonical(body):
                raise ValueError(f"{path} differs from the model it is named after")
            return fp
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n")
        os.replace(tmp, path)
        return fp

    def model(self, fp: str) -> dict:
        _check_fp(fp)
        path = self.root / MODELS / f"{fp.split(':', 1)[1]}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # -- decisions --

    def record(
        self,
        *,
        kind: str,
        fingerprint: str,
        inputs: Any,
        outputs: Any,
        subject: str | None = None,
        asset: str | None = None,
        as_of: date | str | None = None,
        run_id: str | None = None,
    ) -> dict:
        """Append one decision. Validates everything before the file is touched."""
        _check_fp(fingerprint)
        if not kind:
            raise ValueError("kind is required")
        ins, outs = jsonable(inputs), jsonable(outputs)
        out_fp = outs.get("model_fingerprint") if isinstance(outs, dict) else None
        if out_fp is not None and out_fp != fingerprint:
            raise ValueError(f"output carries model_fingerprint {out_fp}, journalled as "
                             f"{fingerprint}: the decision came from another model")
        rec = {
            "kind": kind,
            "fingerprint": fingerprint,
            "subject": subject,
            "asset": asset,
            "as_of": jsonable(as_of),
            "run_id": run_id,
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "inputs": ins,
            "outputs": outs,
        }
        canonical(rec)  # NaN or other bad values fail here, before the file is opened

        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a+", encoding="utf-8") as fh:
            _lock(fh)
            try:
                fh.seek(0)
                last = None
                for line in fh:
                    if line.strip():
                        last = line
                if last is None:
                    rec["seq"], rec["prev"] = 0, ""
                else:
                    tail = json.loads(last)
                    rec["seq"], rec["prev"] = tail["seq"] + 1, tail["hash"]
                rec["hash"] = _sha(canonical(rec))
                fh.write(canonical(rec) + "\n")  # "a" mode: always at the end
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                _unlock(fh)
        return rec

    def read(self, fingerprint: str | None = None) -> Iterator[dict]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if fingerprint is None or rec["fingerprint"] == fingerprint:
                    yield rec

    def fingerprints(self) -> list[str]:
        return list(self.segments())

    def segments(self) -> dict[str, list[dict]]:
        """Records grouped by model fingerprint, in order of each model's first decision."""
        out: dict[str, list[dict]] = {}
        for rec in self.read():
            out.setdefault(rec["fingerprint"], []).append(rec)
        return out

    def verify(self) -> int:
        """Check seq, hashes and the prev chain; returns the record count or raises ValueError."""
        prev, n = "", 0
        for rec in self.read():
            body = {k: v for k, v in rec.items() if k != "hash"}
            if rec.get("seq") != n:
                raise ValueError(f"seq {rec.get('seq')} out of order, expected {n}")
            if _sha(canonical(body)) != rec.get("hash"):
                raise ValueError(f"seq {n}: content does not match its hash (edited?)")
            if rec.get("prev") != prev:
                raise ValueError(f"seq {n}: prev hash breaks the chain")
            prev, n = rec["hash"], n + 1
        return n
