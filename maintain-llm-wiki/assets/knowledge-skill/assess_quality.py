#!/usr/bin/env python3
"""Assess this frozen skill's bundled wiki quality without modifying it."""

# The quality helper of an exported knowledge skill. It verifies the bundled
# snapshot, optionally pinned to the manifest hash retained from
# verify_knowledge.py with the same rule as the search; the assessment itself
# comes from quality_core.py, the same module, byte for byte, as the query
# skill's assess_quality.py, worded for a frozen release that only a new export
# can replace.

from __future__ import annotations

import argparse
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
from verify_knowledge import MANIFEST_HELP, knowledge_root, pinned, verify


def assess_quality(expected_manifest_sha256: str = "", now: Optional[datetime] = None) -> dict[str, Any]:
    release = pinned(verify(), expected_manifest_sha256)
    return quality_core.assess(release, knowledge_root(), assess_identity, frozen=True, now=now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-manifest-sha256", default="", help=MANIFEST_HELP)
    args = parser.parse_args()
    report = assess_quality(args.expect_manifest_sha256)
    print(quality_core.report_json(report))
    return quality_core.exit_code(report, frozen=True)


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
