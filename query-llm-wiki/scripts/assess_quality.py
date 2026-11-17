#!/usr/bin/env python3
"""Assess a released wiki's quality freshness without modifying it."""

# The command-line wrapper of the query skill. It verifies the release under
# --target, optionally pinned to a retained manifest hash; the assessment
# itself comes from quality_core.py, which every exported knowledge skill
# shares byte for byte.

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
from verify_release import verify_snapshot


def assess_quality(target: Path, expected_manifest_sha256: str = "", now: Optional[datetime] = None) -> dict[str, Any]:
    return quality_core.assess(verify_snapshot(target, expected_manifest_sha256), target, assess_identity, now=now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--expect-manifest-sha256", default="")
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    report = assess_quality(target, args.expect_manifest_sha256)
    print(quality_core.report_json(report))
    return quality_core.exit_code(report)


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
