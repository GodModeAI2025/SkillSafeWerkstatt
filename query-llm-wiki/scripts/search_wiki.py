#!/usr/bin/env python3
"""Rank relevant Markdown files in an initialized SkillSafeWerkstatt without modifying it.

This is the command-line wrapper of the query skill. It verifies the release
before and after the search; ranking, claims, snippets and the coverage block
come from `search_core.py`, which exported knowledge skills share byte for byte.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Target wiki directory")
    parser.add_argument("--query", required=True, help="Question or retrieval query")
    parser.add_argument("--limit", type=int, default=12, help="Maximum number of results (1-100)")
    parser.add_argument("--include-sources", action="store_true", help="Also search faithful source Markdown")
    parser.add_argument("--include-history", action="store_true", help="Also search historical snapshots")
    parser.add_argument("--filter-json", default='{"kind":"all"}', help="Validated metadata selector as JSON")
    parser.add_argument(
        "--expect-manifest-sha256",
        default="",
        help="Release manifest hash retained from verify_release.py; a different release reports snapshot_changed",
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not (target / "WIKI.md").is_file() or not (target / "wiki/index.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    initial_release = verify_snapshot(target, args.expect_manifest_sha256)
    if initial_release.get("state") != "ready":
        print(json.dumps({"release": initial_release, "results": []}, ensure_ascii=False, indent=2))
        return exit_code(initial_release)
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("limit must be between 1 and 100")
    try:
        selector = validate_selector(json.loads(args.filter_json))
    except (json.JSONDecodeError, ValueError, FrontmatterError) as exc:
        raise SystemExit(f"filter-json is invalid: {exc}") from exc

    try:
        found = search_core.search(
            target,
            args.query,
            limit=args.limit,
            include_sources=args.include_sources,
            include_history=args.include_history,
            selector=selector,
        )
    except search_core.QueryError as exc:
        raise SystemExit(str(exc)) from exc

    if found["parser_errors"]:
        final_release = verify_snapshot(target, str(initial_release.get("manifest_sha256") or ""))
        release = final_release if final_release.get("state") != "ready" else initial_release
        print(json.dumps({"state": "invalid_frontmatter", "release": release, "parser_errors": found["parser_errors"], "results": []}, ensure_ascii=False, indent=2))
        return 5 if final_release.get("state") == "ready" else exit_code(final_release)
    report = {
        "target": ".",
        "query": args.query,
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
