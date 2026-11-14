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
- An accepted regression names a query, a required page and a reason. With
  `accepted_rank` it accepts that one loss: the page is then held to the bands
  of the accepted rank instead of the recorded one, so a later change cannot
  push it further without failing. Without `accepted_rank` the page is exempt.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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
    "it held here, unless accepted_regressions lists that page with a reason; an entry with "
    "accepted_rank holds the page to that rank's bands instead. Changing this file is a deliberate "
    "act: state the change and its reason in the commit message."
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
    accepted = {(item.get("id"), item.get("path")): item for item in expected.get("accepted_regressions", [])}
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
                acceptance = accepted.get((query_id, path))
                if acceptance is not None:
                    if "accepted_rank" not in acceptance:
                        continue
                    # Held to the place it was accepted at, never to a better one.
                    held = acceptance["accepted_rank"]
                    rank = None if held is None or rank is None else max(rank, held)
                if rank is None:
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


# -- second gate: the agent's reformulations (Stufe 3) ----------------------------

REFORMULATIONS = HERE / "reformulations.json"
REFORMULATION_EXPECTATIONS = HERE / "reformulation_expectations.json"
REFORMULATION_FORMAT = "lmwiki-search-quality-reformulations/1"
REFORMULATION_ABOUT = (
    "Recorded by record_expectations.py --reformulations from the search as it was at recording time. "
    "reformulations.json holds two sets of up to four reformulations per question, written blind by agents "
    "that saw only the questions, never the wiki: the condition of a real reader agent. Every question runs "
    "once per set with its reformulations at --limit 12 and at --limit 100. merged_ranks names, per required "
    "page, its rank in results and its position in reformulation_results at limit 12 (results, block) and at "
    "limit 100 (results_100, block_100); null means absent. A page counts as found within N when its rank in "
    "results or its position in the block is at most N. floors are minimums, caps are maximums. "
    "tests/test_search_quality.py (ReformulationGate) fails when reformulations change the question's own "
    "results or coverage, when a set's merged found counts fall below its floors, when a required page leaves "
    "the merged top 3 or top 12 it held here unless accepted_regressions lists it (with set, id, path and a "
    "reason; accepted_rank holds it to that rank's bands), when the block of the seven negative questions grows "
    "beyond its cap, or when a navigation page enters the block. Caveats: the sets come from the same model "
    "family that is evaluated with them, so the numbers are optimistic; they are a regression gate and must "
    "never become a tuning target; a set is never edited to make the gate pass - a new set is added instead, "
    "and the commit explains why. Changing this file is a deliberate act: state the change and its reason in "
    "the commit message."
)
#: Keys a reformulation adds to a report; without them a report must equal the single-query one.
NEW_REPORT_KEYS = ("formulations", "dropped_formulations", "reformulation_results")
NEW_COVERAGE_KEYS = ("formulations", "reformulation_results")
REFORMULATION_FLOOR_KEYS = ("merged_within_3", "merged_within_12", "merged_within_100")
REFORMULATION_CAP_KEYS = ("negative_block_within_12",)


def load_reformulations() -> dict[str, dict[str, list[str]]]:
    return json.loads(REFORMULATIONS.read_text(encoding="utf-8"))


def single_query_view(report: dict[str, Any]) -> tuple[list[tuple[str, float]], dict[str, Any]]:
    """What must not change: the question's (path, score) list and its coverage without the new keys."""
    coverage = {key: value for key, value in report["coverage"].items() if key not in NEW_COVERAGE_KEYS}
    return [(item["path"], item["score"]) for item in report["results"]], coverage


def positions(items: list[dict[str, Any]], wanted: list[str]) -> dict[str, Optional[int]]:
    found = [item["path"] for item in items]
    return {path: (found.index(path) + 1 if path in found else None) for path in wanted}


def merged_rank(entry: dict[str, Optional[int]], suffix: str = "") -> Optional[int]:
    """The better of a page's rank in results and its position in the block; seen within N when at most N."""
    values = [value for value in (entry["results" + suffix], entry["block" + suffix]) if value is not None]
    return min(values) if values else None


def merged_entry(narrow: dict[str, Any], wide: dict[str, Any], wanted: list[str]) -> dict[str, dict[str, Optional[int]]]:
    results, block = positions(narrow["results"], wanted), positions(narrow["reformulation_results"], wanted)
    results_100, block_100 = positions(wide["results"], wanted), positions(wide["reformulation_results"], wanted)
    return {
        path: {"results": results[path], "block": block[path], "results_100": results_100[path], "block_100": block_100[path]}
        for path in wanted
    }


def measure_reformulations(
    wiki: Path, ground_truth: list[dict[str, Any]], sets: dict[str, dict[str, list[str]]], core: Any = None
) -> dict[str, Any]:
    """Run every question once per set with its reformulations, at the default limit and at RANK_LIMIT.

    A question missing from a set runs without reformulations. Questions with
    `requires_flags` run a second time with those flags, recorded under
    `with_required_flags`; aggregates use the runs without flags.
    """
    core = core or load_core()
    baseline: dict[tuple[str, tuple[str, ...]], Any] = {}

    def single(item: dict[str, Any], flags: tuple[str, ...]) -> Any:
        key = (item["id"], flags)
        if key not in baseline:
            options = {FLAG_OPTIONS[flag]: True for flag in flags}
            baseline[key] = single_query_view(core.search(wiki, item["query"], limit=DEFAULT_LIMIT, **options))
        return baseline[key]

    measured: dict[str, Any] = {}
    for name in sorted(sets):
        queries: dict[str, dict[str, Any]] = {}
        for item in ground_truth:
            also = list(sets[name].get(item["id"], []))
            runs: dict[tuple[str, ...], dict[str, Any]] = {}
            flag_sets = [()] + ([tuple(item["requires_flags"])] if item.get("requires_flags") else [])
            identical = True
            for flags in flag_sets:
                options = {FLAG_OPTIONS[flag]: True for flag in flags}
                narrow = core.search(wiki, item["query"], also=also, limit=DEFAULT_LIMIT, **options)
                wide = core.search(wiki, item["query"], also=also, limit=RANK_LIMIT, **options)
                identical = identical and single_query_view(narrow) == single(item, flags)
                runs[flags] = {"narrow": narrow, "wide": wide}
            narrow, wide = runs[()]["narrow"], runs[()]["wide"]
            block = narrow["reformulation_results"]
            expected = set(item["expected_paths"])
            entry: dict[str, Any] = {
                "category": item["category"],
                "identical": identical,
                "reformulations": len(narrow["formulations"]) - 1,
                "dropped": len(narrow["dropped_formulations"]),
                "merged_ranks": merged_entry(narrow, wide, item["must_find"]),
                "results_within_default_limit": len(narrow["results"]),
                "navigation_in_top_3": sum(1 for result in narrow["results"][:TOP] if result["navigation"]),
                "block_within_default_limit": len(block),
                "block_paths": [result["path"] for result in block],
                "block_expected": sum(1 for result in block if result["path"] in expected),
                "navigation_in_block": sum(
                    1 for result in block + wide["reformulation_results"] if result["navigation"]
                ),
                "contributed": [entry["contributed"] for entry in narrow["coverage"]["formulations"][1:]],
                "question_ranks_100": positions(wide["results"], item["must_find"]),
            }
            if len(flag_sets) > 1:
                flagged = runs[flag_sets[1]]
                entry["with_required_flags"] = {
                    "flags": list(flag_sets[1]),
                    "merged_ranks": merged_entry(flagged["narrow"], flagged["wide"], item["must_find"]),
                }
            queries[item["id"]] = entry
        measured[name] = {"queries": queries, "aggregates": reformulation_aggregates(queries)}
    return {"sets": measured}


def found_within(entry: dict[str, Any], bound: int, merged: bool = True) -> bool:
    ranks = entry["merged_ranks"]
    suffix = "_100" if bound > DEFAULT_LIMIT else ""
    values = [merged_rank(page, suffix) if merged else page["results" + suffix] for page in ranks.values()]
    return bool(values) and all(value is not None and value <= bound for value in values)


def reformulation_aggregates(queries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    answerable = [entry for entry in queries.values() if entry["category"] != "negative"]
    negative = [entry for entry in queries.values() if entry["category"] == "negative"]
    totals: dict[str, Any] = {
        "answerable_queries": len(answerable),
        "negative_queries": len(negative),
        "identity_failures": sum(1 for entry in queries.values() if not entry["identical"]),
    }
    for bound in (TOP, DEFAULT_LIMIT, RANK_LIMIT):
        totals[f"merged_within_{bound}"] = sum(found_within(entry, bound) for entry in answerable)
        totals[f"results_within_{bound}"] = sum(found_within(entry, bound, merged=False) for entry in answerable)
    totals.update(
        {
            "negative_results_within_12": sum(entry["results_within_default_limit"] for entry in negative),
            "negative_block_within_12": sum(entry["block_within_default_limit"] for entry in negative),
            "negatives_with_block": sum(1 for entry in negative if entry["block_within_default_limit"]),
            "navigation_in_top_3": sum(entry["navigation_in_top_3"] for entry in queries.values()),
            "navigation_in_block": sum(entry["navigation_in_block"] for entry in queries.values()),
        }
    )
    return totals


def reformulation_expectations(measurement: dict[str, Any]) -> dict[str, Any]:
    """The second gate's expectations document; accepted_regressions starts empty."""
    sets: dict[str, Any] = {}
    for name, measured in measurement["sets"].items():
        totals = measured["aggregates"]
        queries: dict[str, Any] = {}
        for query_id, entry in measured["queries"].items():
            recorded: dict[str, Any] = {"merged_ranks": entry["merged_ranks"]}
            if "with_required_flags" in entry:
                recorded["with_required_flags"] = entry["with_required_flags"]
            queries[query_id] = recorded
        sets[name] = {
            "floors": {key: totals[key] for key in REFORMULATION_FLOOR_KEYS},
            "caps": {**{key: totals[key] for key in REFORMULATION_CAP_KEYS}, "navigation_in_block": 0},
            "queries": queries,
        }
    return {
        "format": REFORMULATION_FORMAT,
        "about": REFORMULATION_ABOUT,
        "rank_limit": RANK_LIMIT,
        "default_limit": DEFAULT_LIMIT,
        "sets": sets,
        "accepted_regressions": [],
    }


def merged_maps(entry: dict[str, Any]) -> list[tuple[str, dict[str, Optional[int]]]]:
    maps = [("without flags", {path: merged_rank(page) for path, page in entry["merged_ranks"].items()})]
    if "with_required_flags" in entry:
        flagged = entry["with_required_flags"]
        maps.append((" ".join(flagged["flags"]), {path: merged_rank(page) for path, page in flagged["merged_ranks"].items()}))
    return maps


def reformulation_regressions(expected: dict[str, Any], measured: dict[str, Any]) -> list[str]:
    """Required pages that left the merged top 3 or top 12 they held at recording time.

    The merged rank of a page is the better of its rank in results and its
    position in reformulation_results at the default limit. An accepted
    regression names set, id and path; with `accepted_rank` the page is held
    to that rank's bands, without it the page is exempt.
    """
    accepted = {
        (item.get("set"), item.get("id"), item.get("path")): item for item in expected.get("accepted_regressions", [])
    }
    problems: list[str] = []
    for name, recorded_set in expected["sets"].items():
        current_set = measured["sets"][name]["queries"]
        for query_id, entry in recorded_set["queries"].items():
            current = dict(merged_maps(current_set[query_id]))
            for label, recorded in merged_maps(entry):
                now_map = current.get(label, {})
                for path, rank in recorded.items():
                    acceptance = accepted.get((name, query_id, path))
                    if acceptance is not None:
                        if "accepted_rank" not in acceptance:
                            continue
                        held = acceptance["accepted_rank"]
                        rank = None if held is None or rank is None else max(rank, held)
                    if rank is None:
                        continue
                    now = now_map.get(path)
                    for bound in (TOP, DEFAULT_LIMIT):
                        if rank <= bound and (now is None or now > bound):
                            where = f"merged rank {now}" if now is not None else f"not in the merged top {DEFAULT_LIMIT}"
                            problems.append(
                                f"set {name}, {query_id} ({label}): {path} left the merged top {bound}: "
                                f"merged rank {rank} -> {where}"
                            )
                            break
    return problems


# -- third gate: the guarded absence finding (Stufe 4) ------------------------------

ABSENCE_EXPECTATIONS = HERE / "absence_expectations.json"
ABSENCE_FORMAT = "lmwiki-search-quality-absence/1"
#: The reason a freshly recorded heuristic hit carries until a person has judged it.
UNJUDGED = "unjudged: read the passage and replace this with the judgment"
ABSENCE_ABOUT = (
    "Recorded by record_expectations.py --absence from the search as it was at recording time. Every question "
    "runs once per set of reformulations.json with --exhaustive at --limit 12, on one release loaded with "
    "load(exhaustive=True, include_sources=True). negatives lists, per set, the seven questions about topics the "
    "wiki does not hold: complete must stay true with zero word-form hits, and every heuristic hit, identified "
    "within its file by path, kind and line, must be one recorded here with a reason, the judgment of a person "
    "who read the passage (a newly recorded hit carries the unjudged marker until then). complete_floor and "
    "claims_returned_floor are minimums per set: the number of complete checks, and the number of claim-heavy "
    "questions whose answering claim is printed in results or reformulation_results or returned as an exhaustive "
    "hit. tests/test_search_quality.py (AbsenceGate) also fails when a required page of an answerable question is "
    "in none of results, reformulation_results and the returned exhaustive_hits unless accepted lists it (set, id, "
    "path, reason), when an answering claim is not reachable (printed, a hit, or on a printed page with withheld "
    "claims), when a navigation file appears as a hit page, or when the exhaustive call changes anything the same "
    "call with include_sources returns. Caveats: the sets come from the same model family that is evaluated with "
    "them, so the numbers are optimistic; they are a regression gate, never a tuning target, and are never edited "
    "to make the gate pass. Changing this file is a deliberate act: state the change and its reason in the commit "
    "message."
)
#: What the exhaustive scan may add to a report; everything else must equal the call with include_sources.
ABSENCE_INVARIANT_KEYS = (
    "results", "reformulation_results", "formulations", "dropped_formulations", "matched_concepts",
    "expanded_terms", "facets", "coverage", "searched_files", "filtered_out",
)


def navigation_file(path: str) -> bool:
    """WIKI.md or an index.md, also inside a history snapshot: decided here, independent of the core under test."""
    parts = path.split("/")
    inner = parts[3:] if len(parts) > 3 and parts[:2] == ["meta", "history"] else parts
    return parts[-1] == "index.md" or inner == ["WIKI.md"]


def answer_claim(wiki: Path, page: str, ordinal: int, core: Any) -> dict[str, Any]:
    """The claim a claim-heavy question asks about: the `ordinal`-th claim block of its page."""
    body = core.frontmatter((wiki / page).read_text(encoding="utf-8"), page)[1]
    return core.claims_in(body)[ordinal - 1]


def measure_absence(
    wiki: Path, ground_truth: list[dict[str, Any]], sets: dict[str, dict[str, list[str]]], core: Any = None
) -> dict[str, Any]:
    """Run every question once per set with --exhaustive; compare each run with the same call without the scan.

    The release is loaded twice, once with the scan index and once with
    include_sources only, and every question is searched over both loads.
    """
    core = core or load_core()
    started = time.perf_counter()
    exhaustive = core.load(wiki, include_sources=True, exhaustive=True)
    plain = core.load(wiki, include_sources=True)
    measured: dict[str, Any] = {}
    for name in sorted(sets):
        queries: dict[str, dict[str, Any]] = {}
        for item in ground_truth:
            also = list(sets[name].get(item["id"], []))
            report = core.search_loaded(exhaustive, item["query"], also=also, limit=DEFAULT_LIMIT, exhaustive=True)
            baseline = core.search_loaded(plain, item["query"], also=also, limit=DEFAULT_LIMIT)
            check = report["absence_check"]
            hits = report["exhaustive_hits"]
            printed = report["results"] + report["reformulation_results"]
            visible = {entry["path"] for entry in printed} | {entry["path"] for entry in hits}
            entry: dict[str, Any] = {
                "category": item["category"],
                "query": item["query"],
                "identical": all(report[key] == baseline[key] for key in ABSENCE_INVARIANT_KEYS),
                "complete": check["complete"],
                "reasons": check["reasons"],
                "next_steps": check["next_steps"],
                "reformulations_kept": len(report["formulations"]) - 1,
                "reformulations_counted": check["reformulations_counted"],
                "counts": check["counts"],
                "budget": check["budget"],
                "absent_terms": check["absent_terms"],
                "results": len(report["results"]),
                "matched": report["coverage"]["matched"],
                "block": len(report["reformulation_results"]),
                "navigation_hit_pages": [page["path"] for page in hits if navigation_file(page["path"])],
                "heuristic_hits": [
                    {
                        "path": page["path"],
                        "kind": hit["kind"],
                        "line": hit["line"],
                        "locator": hit["locator"],
                        "formulations": hit["formulations"],
                        "matched": hit.get("matched"),
                        "text": str(hit.get("text") or "")[:200],
                    }
                    for page in hits
                    for hit in page["hits"]
                    if hit["strength"] == "heuristic"
                ],
                "visible": {path: path in visible for path in item["must_find"]},
            }
            if item.get("answer_claim_ordinal"):
                page = item["must_find"][0]
                claim = answer_claim(wiki, page, item["answer_claim_ordinal"], core)
                shown = any(
                    result["path"] == page and any(found.get("id") == claim["id"] for found in result["claims"])
                    for result in printed
                )
                hit = any(
                    found["kind"] == "claim" and found["locator"] == claim["id"]
                    for result in hits
                    if result["path"] == page
                    for found in result["hits"]
                )
                withheld = any(
                    result["path"] == page and result["claims_returned"] < result["claims_total"] for result in printed
                )
                entry["claim"] = {"id": claim["id"], "printed": shown, "hit": hit, "withheld_on_printed_page": withheld}
            queries[item["id"]] = entry
        measured[name] = {"queries": queries, "aggregates": absence_aggregates(queries)}
    return {"sets": measured, "seconds": round(time.perf_counter() - started, 2)}


def absence_aggregates(queries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    answerable = {key: entry for key, entry in queries.items() if entry["category"] != "negative"}
    claims = [entry["claim"] for entry in answerable.values() if "claim" in entry]
    needed = sorted(entry["budget"]["needed_chars"] for entry in queries.values())
    return {
        "questions": len(queries),
        "complete": sum(1 for entry in queries.values() if entry["complete"]),
        "incomplete": {key: entry["reasons"] for key, entry in queries.items() if not entry["complete"]},
        "identity_failures": sum(1 for entry in queries.values() if not entry["identical"]),
        "visible_all": sum(1 for entry in answerable.values() if all(entry["visible"].values())),
        "answerable": len(answerable),
        "claims_returned": sum(1 for claim in claims if claim["printed"] or claim["hit"]),
        "claims_reachable": sum(
            1 for claim in claims if claim["printed"] or claim["hit"] or claim["withheld_on_printed_page"]
        ),
        "claim_questions": len(claims),
        "navigation_hit_pages": sum(len(entry["navigation_hit_pages"]) for entry in queries.values()),
        "needed_chars_median": needed[len(needed) // 2] if needed else 0,
        "needed_chars_max": needed[-1] if needed else 0,
    }


def absence_expectations(measurement: dict[str, Any], previous: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """The third gate's expectations; a negative keeps its reason when its heuristic hits did not change."""
    sets: dict[str, Any] = {}
    for name, measured in measurement["sets"].items():
        before = ((previous or {}).get("sets", {}).get(name, {}) or {}).get("negatives", {})
        negatives: dict[str, Any] = {}
        for query_id, entry in measured["queries"].items():
            if entry["category"] != "negative":
                continue
            recorded = [{"path": hit["path"], "kind": hit["kind"], "line": hit["line"]} for hit in entry["heuristic_hits"]]
            old = before.get(query_id, {})
            if not recorded:
                reason = "no heuristic hits"
            elif old.get("heuristic_hits") == recorded and str(old.get("reason") or "").strip():
                reason = old["reason"]
            else:
                reason = UNJUDGED
            negatives[query_id] = {"complete": entry["complete"], "heuristic_hits": recorded, "reason": reason}
        totals = measured["aggregates"]
        sets[name] = {
            "negatives": negatives,
            "complete_floor": totals["complete"],
            "claims_returned_floor": totals["claims_returned"],
        }
    return {
        "format": ABSENCE_FORMAT,
        "about": ABSENCE_ABOUT,
        "default_limit": DEFAULT_LIMIT,
        "sets": sets,
        "accepted": list((previous or {}).get("accepted", [])),
    }


def absence_problems(expected: dict[str, Any], measured: dict[str, Any]) -> dict[str, list[str]]:
    """Every breach of the third gate's rules, grouped by rule; empty lists when the gate holds."""
    problems: dict[str, list[str]] = {
        "negatives": [], "heuristic_hits": [], "visibility": [], "floors": [], "navigation": [], "invariant": [],
        "claims": [],
    }
    accepted = {(item.get("set"), item.get("id"), item.get("path")) for item in expected.get("accepted", [])}
    for name, recorded in expected["sets"].items():
        queries = measured["sets"][name]["queries"]
        totals = measured["sets"][name]["aggregates"]
        for query_id, negative in recorded["negatives"].items():
            entry = queries[query_id]
            if not entry["complete"] or entry["counts"]["hits_word_form"]:
                problems["negatives"].append(
                    f"set {name}, {query_id}: complete={entry['complete']} reasons={entry['reasons']} "
                    f"word-form hits={entry['counts']['hits_word_form']}"
                )
            allowed = {(hit["path"], hit["kind"], hit["line"]) for hit in negative["heuristic_hits"]}
            for hit in entry["heuristic_hits"]:
                if (hit["path"], hit["kind"], hit["line"]) not in allowed:
                    problems["heuristic_hits"].append(
                        f"set {name}, {query_id}: new heuristic hit {hit['path']} {hit['kind']} line {hit['line']} "
                        f"matched={json.dumps(hit['matched'], ensure_ascii=False)} text={hit['text']!r}"
                    )
        for query_id, entry in queries.items():
            for path, seen in entry["visible"].items():
                if not seen and (name, query_id, path) not in accepted:
                    problems["visibility"].append(
                        f"set {name}, {query_id}: required page {path} is in none of results, reformulation_results "
                        "and the returned exhaustive_hits"
                    )
            for path in entry["navigation_hit_pages"]:
                problems["navigation"].append(f"set {name}, {query_id}: navigation file {path} is a hit page")
            if not entry["identical"]:
                problems["invariant"].append(f"set {name}, {query_id}: the exhaustive call changed the ranking output")
            claim = entry.get("claim")
            if claim and not (claim["printed"] or claim["hit"] or claim["withheld_on_printed_page"]):
                problems["claims"].append(f"set {name}, {query_id}: answering claim {claim['id']} is not reachable")
        if totals["complete"] < recorded["complete_floor"]:
            problems["floors"].append(
                f"set {name}: complete checks {totals['complete']} < floor {recorded['complete_floor']}: "
                f"{totals['incomplete']}"
            )
        if totals["claims_returned"] < recorded["claims_returned_floor"]:
            problems["floors"].append(
                f"set {name}: answering claims returned {totals['claims_returned']} < floor "
                f"{recorded['claims_returned_floor']}"
            )
    return problems
