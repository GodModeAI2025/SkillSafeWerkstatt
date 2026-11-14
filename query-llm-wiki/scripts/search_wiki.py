#!/usr/bin/env python3
"""Rank relevant Markdown files in an initialized SkillSafeWerkstatt without modifying it.

This is the command-line wrapper of the query skill. It verifies the release
before and after the search; ranking, claims, snippets, reformulations and the
coverage block come from `search_core.py`, which exported knowledge skills share
byte for byte. The query and up to four reformulations come from `--query` and
`--also`, or as one JSON object on standard input with `--request -`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Siblings are imported from this folder even where the interpreter leaves it
# off sys.path: python -I, python -P, PYTHONSAFEPATH=1.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import search_core
from frontmatter_contract import FrontmatterError
from verify_release import verify_snapshot
from wiki_filters import validate_selector


def exit_code(release: dict) -> int:
    return {"wiki_busy": 2, "snapshot_changed": 3}.get(str(release.get("state")), 4)


def selector_from(request_filter: Optional[dict], filter_json: Optional[str]) -> dict:
    """The validated selector: the request's filter, else --filter-json, else everything."""
    if request_filter is not None:
        try:
            return validate_selector(request_filter)
        except (ValueError, FrontmatterError) as exc:
            raise SystemExit(f"request is invalid: filter is not a valid selector: {exc}") from exc
    try:
        return validate_selector(json.loads(filter_json if filter_json is not None else '{"kind":"all"}'))
    except (json.JSONDecodeError, ValueError, FrontmatterError) as exc:
        raise SystemExit(f"filter-json is invalid: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Target wiki directory")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", help="Question or retrieval query")
    group.add_argument(
        "--request",
        metavar="-",
        help="Read the query, its reformulations and an optional selector as one JSON object from standard input; "
        "only '-' is accepted",
    )
    parser.add_argument(
        "--also",
        action="append",
        default=[],
        metavar="REFORMULATION",
        help="Reformulation of the query searched in the same call; repeatable, at most 4, each at most 200 characters",
    )
    parser.add_argument("--limit", type=int, default=12, help="Maximum number of results (1-100)")
    parser.add_argument("--include-sources", action="store_true", help="Also search faithful source Markdown")
    parser.add_argument("--include-history", action="store_true", help="Also search historical snapshots")
    parser.add_argument("--filter-json", default=None, help="Validated metadata selector as JSON (default: all)")
    parser.add_argument(
        "--expect-manifest-sha256",
        default="",
        help="Release manifest hash retained from verify_release.py; a different release reports snapshot_changed",
    )
    args = parser.parse_args()
    if args.request is not None and args.request != "-":
        parser.error("--request accepts only '-' (standard input)")
    if args.request is not None and args.also:
        parser.error("--also cannot be combined with --request; put the reformulations into the request's also list")

    # The request is read and checked before the target is touched, so standard
    # input is always drained and invalid input never depends on the wiki.
    try:
        if args.request is not None:
            request = search_core.request_from_stdin(sys.stdin)
            query, also, request_filter = request["query"], request["also"], request["filter"]
        else:
            query, also, request_filter = args.query, list(args.also), None
        search_core.check_also(also)
    except search_core.RequestError as exc:
        raise SystemExit(str(exc)) from exc
    if request_filter is not None and args.filter_json is not None:
        raise SystemExit("request is invalid: filter is given both in the request and as --filter-json; give it once")

    target = Path(args.target).expanduser().resolve()
    if not (target / "WIKI.md").is_file() or not (target / "wiki/index.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    initial_release = verify_snapshot(target, args.expect_manifest_sha256)
    if initial_release.get("state") != "ready":
        print(json.dumps({"release": initial_release, "results": []}, ensure_ascii=False, indent=2))
        return exit_code(initial_release)
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("limit must be between 1 and 100")
    selector = selector_from(request_filter, args.filter_json)

    try:
        found = search_core.search(
            target,
            query,
            also=also,
            limit=args.limit,
            include_sources=args.include_sources,
            include_history=args.include_history,
            selector=selector,
        )
    except (search_core.QueryError, search_core.RequestError) as exc:
        raise SystemExit(str(exc)) from exc

    if found["parser_errors"]:
        final_release = verify_snapshot(target, str(initial_release.get("manifest_sha256") or ""))
        release = final_release if final_release.get("state") != "ready" else initial_release
        print(json.dumps({"state": "invalid_frontmatter", "release": release, "parser_errors": found["parser_errors"], "results": []}, ensure_ascii=False, indent=2))
        return 5 if final_release.get("state") == "ready" else exit_code(final_release)
    report = {
        "target": ".",
        "query": query,
        "formulations": found["formulations"],
        "dropped_formulations": found["dropped_formulations"],
        "release": initial_release,
        "searched_files": found["searched_files"],
        "include_sources": args.include_sources,
        "include_history": args.include_history,
        "selector": selector,
        "filtered_out": found["filtered_out"],
        "matched_concepts": found["matched_concepts"],
        "expanded_terms": found["expanded_terms"],
        "facets": found["facets"],
        "results": found["results"],
        "reformulation_results": found["reformulation_results"],
        "coverage": found["coverage"],
    }
    final_release = verify_snapshot(target, str(initial_release.get("manifest_sha256") or ""))
    if final_release.get("state") != "ready":
        print(json.dumps({"release": final_release, "results": []}, ensure_ascii=False, indent=2))
        return exit_code(final_release)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
