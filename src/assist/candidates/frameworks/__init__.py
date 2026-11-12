"""Phase Q frameworks as measured inputs (PLAN S93). The API is in `base`; every other module
of this package is one framework, imported here so that it registers itself. Hashed by
`journal.RULE_GLOBS`."""

from __future__ import annotations

import importlib
import pkgutil

from assist.candidates.frameworks.base import (
    GATES,
    NA,
    ROLES,
    Framework,
    FrameworkResult,
    evaluate,
    inputs_for,
    missing,
    register,
    registered,
)

__all__ = ["GATES", "NA", "ROLES", "Framework", "FrameworkResult", "evaluate", "inputs_for",
           "missing", "register", "registered"]

for _m in sorted(m.name for m in pkgutil.iter_modules(__path__)):
    if _m != "base":
        importlib.import_module(f"{__name__}.{_m}")
