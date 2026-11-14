#!/usr/bin/env python3
"""Measure the search against the fixture's ground truth.

Shared by the gate test (tests/test_search_quality.py) and by
record_expectations.py, so the test checks exactly what the recorder records.
Queries run in-process through the query skill's `search_core.search`, the same
function `search_wiki.py` calls after verifying the release; the gate test adds
a few real command-line calls as smoke tests.

Counting rules:

- A rank is the 1-based position of a required page at `--limit 100`; None
  means it is not among the first 100 results.
- Every query runs without flags. Queries whose ground truth names
  `requires_flags` (the source-only questions) run a second time with those
  flags, recorded under `with_required_flags`.
- Aggregates are taken from the runs without flags. A query counts as found
  within N when every one of its required pages ranks at N or better. A query
  has a required first result when one of its required pages ranks 1.
- Rank 1 is judged per query, the top 3 and the top 12 per required page: a
  query whose first result was a required page must keep a required page
  first, so two required pages that swap places lose nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
QUERY_SCRIPTS = REPO / "query-llm-wiki" / "scripts"
GROUND_TRUTH = HERE / "ground_truth.json"
EXPECTATIONS = HERE / "expectations.json"
EXPECTATIONS_FORMAT = "lmwiki-search-quality-expectations/1"
RANK_LIMIT = 100
DEFAULT_LIMIT = 12
TOP = 3
FLAG_OPTIONS = {"--include-sources": "include_sources", "--include-history": "include_history"}
ABOUT = (
    "Recorded by record_expectations.py from the search as it was at recording time. A rank is the "
    "1-based position of a required page at --limit 100 (null: not among the first 100), without "
    "flags unless with_required_flags says otherwise. floors are minimums, caps are maximums. "
    "tests/test_search_quality.py fails when a query whose first result is a required page here "
    "no longer has a required page first, or when a required page leaves the top 3 or the top 12 "
    "it held here, unless accepted_regressions lists that page with a reason. Changing this file "
    "is a deliberate act: state the change and its reason in the commit message."
)


def load_ground_truth() -> list[dict[str, Any]]:
    return json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))


def build(out: Path) -> Path:
    """Build the fixture below `out` (outside the repository) and return its wiki root.

    The caller's PYTHONDONTWRITEBYTECODE is not passed on, so the gate test sees
    whether the builder itself keeps bytecode out of the repository. The builder
    prints UTF-8 on every host, so its output is decoded as UTF-8.
    """
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
    result = subprocess.run(
        [sys.executable, "-B", str(HERE / "build_fixture.py"), "--out", str(out)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError(f"fixture build failed ({result.returncode}):\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}")
    return out / "wiki"


def load_core() -> Any:
    if str(QUERY_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(QUERY_SCRIPTS))
    import search_core

    return search_core


def ranks(paths: list[str], wanted: list[str]) -> dict[str, Optional[int]]:
    return {path: (paths.index(path) + 1 if path in paths else None) for path in wanted}


def all_within(found: dict[str, Optional[int]], bound: int) -> bool:
    return bool(found) and all(rank is not None and rank <= bound for rank in found.values())


def measure(wiki: Path, ground_truth: list[dict[str, Any]], core: Any = None) -> dict[str, Any]:
    core = core or load_core()
    queries: dict[str, dict[str, Any]] = {}
    for item in ground_truth:
        results = core.search(wiki, item["query"], limit=RANK_LIMIT)["results"]
        paths = [result["path"] for result in results]
        entry: dict[str, Any] = {
            "category": item["category"],
            "must_find_ranks": ranks(paths, item["must_find"]),
            "results_within_default_limit": len(paths[:DEFAULT_LIMIT]),
            "navigation_in_top_3": sum(1 for result in results[:TOP] if result["navigation"]),
        }
        flags = list(item.get("requires_flags") or [])
        if flags:
            options = {FLAG_OPTIONS[flag]: True for flag in flags}
            flagged = core.search(wiki, item["query"], limit=RANK_LIMIT, **options)["results"]
            entry["with_required_flags"] = {
                "flags": flags,
                "must_find_ranks": ranks([result["path"] for result in flagged], item["must_find"]),
            }
        queries[item["id"]] = entry
    return {"queries": queries, "aggregates": aggregates(queries)}


def aggregates(queries: dict[str, dict[str, Any]]) -> dict[str, int]:
    answerable = [entry for entry in queries.values() if entry["category"] != "negative"]
    negative = [entry for entry in queries.values() if entry["category"] == "negative"]
    return {
        "answerable_queries": len(answerable),
        "negative_queries": len(negative),
        "required_first_result": sum(1 in entry["must_find_ranks"].values() for entry in answerable),
        "all_must_find_within_3": sum(all_within(entry["must_find_ranks"], 3) for entry in answerable),
        "all_must_find_within_12": sum(all_within(entry["must_find_ranks"], 12) for entry in answerable),
        "all_must_find_within_100": sum(all_within(entry["must_find_ranks"], 100) for entry in answerable),
        "negative_results_within_12": sum(entry["results_within_default_limit"] for entry in negative),
        "navigation_in_top_3": sum(entry["navigation_in_top_3"] for entry in queries.values()),
    }


FLOOR_KEYS = (
    "answerable_queries", "required_first_result",
    "all_must_find_within_3", "all_must_find_within_12", "all_must_find_within_100",
)
CAP_KEYS = ("negative_results_within_12", "navigation_in_top_3")


def expectations(measurement: dict[str, Any]) -> dict[str, Any]:
    """The expectations document for one measurement; accepted_regressions starts empty."""
    totals = measurement["aggregates"]
    queries: dict[str, dict[str, Any]] = {}
    for query_id, entry in measurement["queries"].items():
        recorded: dict[str, Any] = {"must_find_ranks": entry["must_find_ranks"]}
        if "with_required_flags" in entry:
            recorded["with_required_flags"] = entry["with_required_flags"]
        queries[query_id] = recorded
    return {
        "format": EXPECTATIONS_FORMAT,
        "about": ABOUT,
        "rank_limit": RANK_LIMIT,
        "default_limit": DEFAULT_LIMIT,
        "floors": {key: totals[key] for key in FLOOR_KEYS},
        "caps": {key: totals[key] for key in CAP_KEYS},
        "queries": queries,
        "accepted_regressions": [],
    }


def rank_maps(entry: dict[str, Any]) -> list[tuple[str, dict[str, Optional[int]]]]:
    maps = [("without flags", entry["must_find_ranks"])]
    if "with_required_flags" in entry:
        flagged = entry["with_required_flags"]
        maps.append((" ".join(flagged["flags"]), flagged["must_find_ranks"]))
    return maps


def rank_regressions(expected: dict[str, Any], measured: dict[str, Any]) -> list[str]:
    """Rank-1 losses per query, and required pages that left the top 3 or the top 12.

    Everything is compared with the ranks held at recording time. A query whose
    first result was a required page loses rank 1 only when no required page is
    first any more; accepting the page that was first accepts that loss.
    """
    accepted = {(item.get("id"), item.get("path")) for item in expected.get("accepted_regressions", [])}
    problems: list[str] = []
    for query_id, entry in expected["queries"].items():
        current = dict(rank_maps(measured["queries"][query_id]))
        for label, recorded in rank_maps(entry):
            ranks_now = current.get(label, {})
            first = [path for path, rank in recorded.items() if rank == 1 and (query_id, path) not in accepted]
            if first and 1 not in ranks_now.values():
                now = ranks_now.get(first[0])
                where = f"rank {now}" if now is not None else f"not in the first {RANK_LIMIT}"
                problems.append(
                    f"{query_id} ({label}): {first[0]} lost rank 1 and no required page took it: rank 1 -> {where}"
                )
            for path, rank in recorded.items():
                if rank is None or (query_id, path) in accepted:
                    continue
                now = ranks_now.get(path)
                for bound in (TOP, DEFAULT_LIMIT):
                    if rank <= bound and (now is None or now > bound):
                        where = f"rank {now}" if now is not None else f"not in the first {RANK_LIMIT}"
                        problems.append(f"{query_id} ({label}): {path} left the top {bound}: rank {rank} -> {where}")
                        break
    return problems


def improvements(expected: dict[str, Any], measured: dict[str, Any]) -> list[str]:
    """Required pages that rank better than recorded; informational only."""
    found: list[str] = []
    for query_id, entry in expected["queries"].items():
        current = dict(rank_maps(measured["queries"][query_id]))
        for label, recorded in rank_maps(entry):
            for path, rank in recorded.items():
                now = current.get(label, {}).get(path)
                if now is not None and (rank is None or now < rank):
                    found.append(f"{query_id} ({label}): {path} rank {rank} -> {now}")
    return found
