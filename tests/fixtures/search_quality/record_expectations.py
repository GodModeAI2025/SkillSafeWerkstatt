#!/usr/bin/env python3
"""Regenerate expectations.json (or, with --reformulations, reformulation_expectations.json) from the search as it is now.

    python3 tests/fixtures/search_quality/record_expectations.py
    python3 tests/fixtures/search_quality/record_expectations.py --output /tmp/new-expectations.json
    python3 tests/fixtures/search_quality/record_expectations.py --reformulations

With --reformulations, every question runs once per set in reformulations.json
with that set's reformulations, and the second gate's expectations are written
instead (see quality.REFORMULATION_ABOUT). The sets themselves are never edited
to make a gate pass; a new set is added instead.

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


def record_reformulations(output: str) -> int:
    path = quality.REFORMULATION_EXPECTATIONS
    previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    workspace = Path(tempfile.mkdtemp(prefix="lmwiki-search-quality-"))
    try:
        wiki = quality.build(workspace / "fixture")
        measurement = quality.measure_reformulations(wiki, quality.load_ground_truth(), quality.load_reformulations())
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    document = quality.reformulation_expectations(measurement)
    Path(output).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, recorded in document["sets"].items():
        print(json.dumps({"set": name, "floors": recorded["floors"], "caps": recorded["caps"]}))
        failures = measurement["sets"][name]["aggregates"]["identity_failures"]
        if failures:
            print(f"set {name}: {failures} questions whose results changed with reformulations; the gate will fail")
        if previous is not None and name in previous.get("sets", {}):
            before = {**previous["sets"][name]["floors"], **previous["sets"][name]["caps"]}
            for key, after in {**recorded["floors"], **recorded["caps"]}.items():
                if before.get(key) != after:
                    print(f"set {name}: changed {key}: {before.get(key)} -> {after}")
    if previous is not None:
        for line in quality.reformulation_regressions(previous, measurement):
            print("worse:", line)
    print(f"wrote {output}; state this change and its reason in the commit message")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", default=None, help="Where to write (default: the expectations file of the chosen gate)")
    parser.add_argument(
        "--reformulations",
        action="store_true",
        help="Record the second gate, reformulation_expectations.json, from the sets in reformulations.json",
    )
    args = parser.parse_args()
    if args.reformulations:
        return record_reformulations(args.output or str(quality.REFORMULATION_EXPECTATIONS))
    args.output = args.output or str(quality.EXPECTATIONS)
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
