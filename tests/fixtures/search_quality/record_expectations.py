#!/usr/bin/env python3
"""Regenerate expectations.json (or reformulation_expectations.json, or absence_expectations.json) from the search as it is now.

    python3 tests/fixtures/search_quality/record_expectations.py
    python3 tests/fixtures/search_quality/record_expectations.py --output /tmp/new-expectations.json
    python3 tests/fixtures/search_quality/record_expectations.py --reformulations
    python3 tests/fixtures/search_quality/record_expectations.py --absence

With --reformulations, every question runs once per set in reformulations.json
with that set's reformulations, and the second gate's expectations are written
instead (see quality.REFORMULATION_ABOUT). With --absence, every question runs
once per set with --exhaustive, and the third gate's expectations are written
(see quality.ABSENCE_ABOUT): a negative question keeps the reason recorded for
its heuristic hits while they stay the same; a new hit is written with the
unjudged marker, and the gate fails until a person has read the passage and
replaced the marker with the judgment. The sets themselves are never edited to
make a gate pass; a new set is added instead.

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
from typing import Any, Callable, NamedTuple, Optional  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import quality  # noqa: E402


class Gate(NamedTuple):
    """How one gate is recorded."""

    path: Path  # the committed expectations file
    measure: Callable[[Path], dict[str, Any]]  # the fixture wiki -> the measurement
    document: Callable[[dict[str, Any], Optional[dict[str, Any]]], dict[str, Any]]  # measurement, previous file
    summary: Callable[[dict[str, Any], dict[str, Any], Optional[dict[str, Any]]], None]  # document, measurement, previous


def print_changes(before: dict[str, Any], after: dict[str, Any], prefix: str = "") -> None:
    for key, value in after.items():
        if before.get(key) != value:
            print(f"{prefix}changed {key}: {before.get(key)} -> {value}")


def summarise_ranks(document: dict[str, Any], measurement: dict[str, Any], previous: Optional[dict[str, Any]]) -> None:
    print(json.dumps({"floors": document["floors"], "caps": document["caps"]}, indent=2))
    if previous is None:
        return
    print_changes({**previous.get("floors", {}), **previous.get("caps", {})}, {**document["floors"], **document["caps"]})
    for line in quality.rank_regressions(previous, measurement):
        print("worse:", line)
    for line in quality.improvements(previous, measurement):
        print("better:", line)


def summarise_reformulations(
    document: dict[str, Any], measurement: dict[str, Any], previous: Optional[dict[str, Any]]
) -> None:
    for name, recorded in document["sets"].items():
        print(json.dumps({"set": name, "floors": recorded["floors"], "caps": recorded["caps"]}))
        failures = measurement["sets"][name]["aggregates"]["identity_failures"]
        if failures:
            print(f"set {name}: {failures} questions whose results changed with reformulations; the gate will fail")
        if previous is not None and name in previous.get("sets", {}):
            before = previous["sets"][name]
            print_changes(
                {**before["floors"], **before["caps"]}, {**recorded["floors"], **recorded["caps"]}, f"set {name}: "
            )
    if previous is not None:
        for line in quality.reformulation_regressions(previous, measurement):
            print("worse:", line)


def summarise_absence(document: dict[str, Any], measurement: dict[str, Any], previous: Optional[dict[str, Any]]) -> None:
    floors = ("complete_floor", "claims_returned_floor")
    for name, recorded in document["sets"].items():
        totals = measurement["sets"][name]["aggregates"]
        print(json.dumps({
            "set": name, "complete_floor": recorded["complete_floor"],
            "claims_returned_floor": recorded["claims_returned_floor"], "incomplete": totals["incomplete"],
        }, ensure_ascii=False))
        for query_id, negative in recorded["negatives"].items():
            if negative["reason"] == quality.UNJUDGED:
                for hit in measurement["sets"][name]["queries"][query_id]["heuristic_hits"]:
                    print(f"set {name}, {query_id}: judge {hit['path']} {hit['kind']} line {hit['line']}: {hit['text']!r}")
        if previous is not None and name in previous.get("sets", {}):
            print_changes(previous["sets"][name], {key: recorded[key] for key in floors}, f"set {name}: ")
    if previous is not None:
        for rule, lines in quality.absence_problems(previous, measurement).items():
            for line in lines:
                print(f"worse ({rule}):", line)


GATES = {
    "ranks": Gate(
        quality.EXPECTATIONS,
        lambda wiki: quality.measure(wiki, quality.load_ground_truth()),
        lambda measurement, _previous: quality.expectations(measurement),
        summarise_ranks,
    ),
    "reformulations": Gate(
        quality.REFORMULATION_EXPECTATIONS,
        lambda wiki: quality.measure_reformulations(wiki, quality.load_ground_truth(), quality.load_reformulations()),
        lambda measurement, _previous: quality.reformulation_expectations(measurement),
        summarise_reformulations,
    ),
    "absence": Gate(
        quality.ABSENCE_EXPECTATIONS,
        lambda wiki: quality.measure_absence(wiki, quality.load_ground_truth(), quality.load_reformulations()),
        quality.absence_expectations,
        summarise_absence,
    ),
}


def record(gate: Gate, output: str) -> int:
    """Build the fixture outside the repository, measure it, write the document, and print what changed."""
    previous = json.loads(gate.path.read_text(encoding="utf-8")) if gate.path.is_file() else None
    workspace = Path(tempfile.mkdtemp(prefix="lmwiki-search-quality-"))
    try:
        measurement = gate.measure(quality.build(workspace / "fixture"))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    document = gate.document(measurement, previous)
    Path(output).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate.summary(document, measurement, previous)
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
    parser.add_argument(
        "--absence",
        action="store_true",
        help="Record the third gate, absence_expectations.json, from exhaustive searches with the sets in reformulations.json",
    )
    args = parser.parse_args()
    if args.reformulations and args.absence:
        parser.error("choose one of --reformulations and --absence")
    gate = GATES["absence" if args.absence else "reformulations" if args.reformulations else "ranks"]
    return record(gate, args.output or str(gate.path))


if __name__ == "__main__":
    raise SystemExit(main())
