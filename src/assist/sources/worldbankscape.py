"""worldbankscape adapter: layer-1 structural scores (0–100, 50 neutral) per subject × asset class.

Read as worldbankscape's `schema/README.md` asks: `out/index.json` first, then only the payloads it
lists (`out/{SUBJECT}/{asset_class}.json`); anything else in `out/` (`.tmp-*` staging, old files)
is ignored. Both are validated against worldbankscape's OWN schemas, read at runtime from its
`schema/` (default `out/../schema`), never the copy vendored here. A payload whose bytes do not
match its entry's `sha256` means a publish landed between the two reads, so the index is re-read
once.

- No `out/`, no `index.json` or no schema → `SourceUnavailable` missing; an invalid index → error.
- One bad payload (unreadable, schema-invalid, sha mismatch, or subject/asset not matching its
  entry) is skipped and named in `stale_inputs` as `worldbankscape <path> (missing|error)`.
- A subject with no entry for an asset class is "not applicable" (e.g. TLS bonds, USA currency),
  never an imputed 50: `score()` returns None.

Asset classes are worldbankscape's (`bonds currency stocks property commodities business`);
`business` and `property` are kept, the stance layer picks what it needs. As tidy rows, each score
is `WBS.<SUBJECT>.<asset>.<field>` for `score`, `confidence`, `raw_score`, `coverage`, dated and
`as_of` the payload's `as_of`. Rank with `ranked()` (confidence-weighted), display `score` and
`confidence` as published.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import NamedTuple

import jsonschema
from jsonschema.exceptions import best_match

from assist.doctor import DEFAULT_CONFIG, load_sources
from assist.layers.types import AssetScore
from assist.sources.base import Row, SourceUnavailable

__all__ = ["FIELDS", "SOURCE", "Layer1", "WorldbankscapeSource", "ranked", "series_id"]

SOURCE = "worldbankscape"
PREFIX = "WBS."
FIELDS = ("confidence", "coverage", "raw_score", "score")
SCHEMAS = {"score": "score.schema.json", "index": "index.schema.json"}


def series_id(subject: str, asset: str, field: str) -> str:
    if field not in FIELDS:
        raise ValueError(f"field must be one of {FIELDS}, got {field!r}")
    return f"{PREFIX}{subject}.{asset}.{field}"


def ranked(s: AssetScore) -> float:
    """worldbankscape's ranking key, 50 + (score − 50) × confidence. For ordering only."""
    return 50 + (s.score - 50) * s.confidence


class Layer1(NamedTuple):
    scores: list[AssetScore]
    stale_inputs: list[str]
    problems: dict[str, str]  # payload path → why it was skipped
    attribution: list[str]  # union over loaded payloads, first-seen order
    disclaimer: str
    generated_at: str


class _Bad(Exception):
    def __init__(self, reason: str, detail: str):
        self.reason, self.detail = reason, detail
        super().__init__(detail)


def _error(e: jsonschema.ValidationError) -> str:
    where = "/".join(str(p) for p in e.absolute_path) or "(root)"
    return f"{where}: {e.message}"[:200]


class WorldbankscapeSource:
    name = SOURCE

    def __init__(self, out_dir: Path | str, schema_dir: Path | str | None = None):
        self.out_dir = Path(out_dir).expanduser()
        schema_dir = Path(schema_dir).expanduser() if schema_dir else None
        self.schema_dir = schema_dir or self.out_dir.parent / "schema"

    @classmethod
    def from_config(
        cls, config: Path = DEFAULT_CONFIG, env: dict | None = None
    ) -> WorldbankscapeSource:
        env = {**os.environ, **(env or {})}
        src = next(s for s in load_sources(config, env=env) if s.name == SOURCE)
        return cls(src.location)

    # ---------------- reading ----------------

    def _validators(self) -> dict[str, jsonschema.Draft202012Validator]:
        out = {}
        for kind, fname in SCHEMAS.items():
            p = self.schema_dir / fname
            if not p.is_file():
                raise SourceUnavailable(self.name, "missing", f"no schema at {p}")
            out[kind] = jsonschema.Draft202012Validator(
                json.loads(p.read_text()),
                format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
            )
        return out

    def _read_index_text(self) -> str:
        p = self.out_dir / "index.json"
        if not p.is_file():
            raise SourceUnavailable(self.name, "missing", f"no index at {p}")
        return p.read_text()

    def _index(self, validator: jsonschema.Draft202012Validator) -> dict:
        try:
            index = json.loads(self._read_index_text())
        except json.JSONDecodeError as e:
            raise SourceUnavailable(self.name, "error", f"index.json: {e}") from e
        err = best_match(validator.iter_errors(index))
        if err is not None:
            raise SourceUnavailable(self.name, "error", f"index.json {_error(err)}")
        return index

    def _payload(self, entry: dict, validator: jsonschema.Draft202012Validator) -> dict:
        p = self.out_dir / entry["path"]
        if not p.is_file():
            raise _Bad("missing", f"listed but no file at {p}")
        data = p.read_bytes()
        if entry.get("sha256") and hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise _Bad("error", "sha256 differs from index entry")
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as e:
            raise _Bad("error", f"not JSON: {e}") from e
        err = best_match(validator.iter_errors(payload))
        if err is not None:
            raise _Bad("error", _error(err))
        for key in ("subject", "subject_type", "asset_class"):
            if payload[key] != entry[key]:
                raise _Bad("error", f"{key} {payload[key]!r} != index entry {entry[key]!r}")
        return payload

    def load(
        self, subjects: Iterable[str] | None = None, assets: Iterable[str] | None = None
    ) -> Layer1:
        """Every score the index lists (optionally filtered), each payload schema-validated."""
        if not self.out_dir.is_dir():
            raise SourceUnavailable(self.name, "missing", f"no directory at {self.out_dir}")
        v = self._validators()
        subjects = set(subjects) if subjects is not None else None
        assets = set(assets) if assets is not None else None

        def wanted(index: dict) -> list[dict]:
            return [e for e in index["entries"]
                    if (subjects is None or e["subject"] in subjects)
                    and (assets is None or e["asset_class"] in assets)]

        index = self._index(v["index"])
        for attempt in (0, 1):
            payloads, bad = {}, {}
            for entry in wanted(index):
                try:
                    payloads[entry["path"]] = self._payload(entry, v["score"])
                except _Bad as e:
                    bad[entry["path"]] = e
            if attempt or not any("sha256" in e.detail for e in bad.values()):
                break
            index = self._index(v["index"])  # a publish finished between the reads

        scores, attribution, disclaimer = [], [], ""
        for payload in payloads.values():
            scores.append(_score(payload))
            attribution += [a for a in payload["attribution"] if a not in attribution]
            disclaimer = disclaimer or payload["disclaimer"]
        scores.sort(key=lambda s: (s.subject, s.asset))
        return Layer1(
            scores=scores,
            stale_inputs=[f"{self.name} {p} ({e.reason})" for p, e in sorted(bad.items())],
            problems={p: e.detail for p, e in sorted(bad.items())},
            attribution=attribution,
            disclaimer=disclaimer,
            generated_at=index["generated_at"],
        )

    def score(self, subject: str, asset: str) -> AssetScore | None:
        """One score, or None when worldbankscape has no entry (not applicable or a gap)."""
        found = self.load(subjects=[subject], assets=[asset]).scores
        return found[0] if found else None

    def rows(
        self,
        series_ids: Sequence[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Row]:
        wanted = None if series_ids is None else set(series_ids)
        out = []
        for s in self.load().scores:
            if (start and s.as_of < start) or (end and s.as_of > end):
                continue
            for field in FIELDS:
                sid = series_id(s.subject, s.asset, field)
                value = getattr(s, field)
                if (wanted is None or sid in wanted) and value is not None:
                    out.append(Row(sid, s.as_of, float(value), s.as_of, self.name))
        return sorted(out, key=lambda r: (r.series_id, r.date))


def _score(p: dict) -> AssetScore:
    return AssetScore(
        subject=p["subject"],
        asset=p["asset_class"],
        as_of=date.fromisoformat(p["as_of"]),
        score=float(p["score"]),
        confidence=float(p["confidence"]),
        raw_score=p.get("raw_score"),
        coverage=p.get("coverage"),
        flags=tuple(p["flags"]),
        stale_inputs=tuple(p["stale_inputs"]),
    )
