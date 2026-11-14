#!/usr/bin/env python3
"""Regenerate expectations.json from the search as it is now.

    python3 tests/fixtures/search_quality/record_expectations.py
    python3 tests/fixtures/search_quality/record_expectations.py --output /tmp/new-expectations.json

The fixture is built into a temporary directory outside the repository, all
ground-truth queries run through the query skill's search core, and the result
replaces expectations.json (or goes to --output for review). The script prints
what changed against the previous file.

Changing expectations.json is a deliberate act. It lowers or raises the bar the
gate test tests/test_search_quality.py holds every later change to. State the
change and its reason in the commit message. A fresh recording starts with an
empty accepted_regressions list, because the new ranks already include them.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import quality  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", default=str(quality.EXPECTATIONS), help="Where to write (default: expectations.json)")
    args = parser.parse_args()
    previous = None
    if quality.EXPECTATIONS.is_file():
        previous = json.loads(quality.EXPECTATIONS.read_text(encoding="utf-8"))
    workspace = Path(tempfile.mkdtemp(prefix="lmwiki-search-quality-"))
    try:
        wiki = quality.build(workspace / "fixture")
        measurement = quality.measure(wiki, quality.load_ground_truth())
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    document = quality.expectations(measurement)
    Path(args.output).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"floors": document["floors"], "caps": document["caps"]}, indent=2))
    if previous is not None:
        for key in quality.FLOOR_KEYS + quality.CAP_KEYS:
            before = {**previous.get("floors", {}), **previous.get("caps", {})}.get(key)
            after = {**document["floors"], **document["caps"]}[key]
            if before != after:
                print(f"changed {key}: {before} -> {after}")
        for line in quality.rank_regressions(previous, measurement):
            print("worse:", line)
        for line in quality.improvements(previous, measurement):
            print("better:", line)
    print(f"wrote {args.output}; state this change and its reason in the commit message")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
