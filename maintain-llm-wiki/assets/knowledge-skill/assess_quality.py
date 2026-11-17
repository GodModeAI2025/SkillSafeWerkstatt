#!/usr/bin/env python3
"""Assess this frozen skill's bundled wiki quality without modifying it."""

# The quality helper of an exported knowledge skill. It verifies the bundled
# snapshot; the assessment itself comes from quality_core.py, the same module,
# byte for byte, as the query skill's assess_quality.py, worded for a frozen
# release that only a new export can replace.

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Siblings are imported from this folder even where the interpreter leaves it
# off sys.path: python -I, python -P, PYTHONSAFEPATH=1.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import quality_core
from identity_status import assess_identity
from verify_knowledge import knowledge_root, verify


def assess_quality(now: Optional[datetime] = None) -> dict[str, Any]:
    return quality_core.assess(verify(), knowledge_root(), assess_identity, frozen=True, now=now)


def main() -> int:
    report = assess_quality()
    print(quality_core.report_json(report))
    return quality_core.exit_code(report)


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
