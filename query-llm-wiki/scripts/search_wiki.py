#!/usr/bin/env python3
"""Rank relevant Markdown files in an initialized SkillSafeWerkstatt without modifying it.

This is the command-line wrapper of the query skill. It verifies the release
before and after the search; ranking, claims, snippets, reformulations and the
coverage block come from `search_core.py`, which exported knowledge skills share
byte for byte. The query and up to four reformulations come from `--query` and
`--also`, or as one JSON object on standard input with `--request -`. With
`--exhaustive` the same call also ranks the sources and scans every passage for
all words of all searches before an absence statement; every report carries
`search_record` and `absence_check`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Siblings are imported from this folder even where the interpreter leaves it
# off sys.path: python -I, python -P, PYTHONSAFEPATH=1.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import search_core
from verify_release import verify_snapshot


def exit_code(release: dict) -> int:
    return {"wiki_busy": 2, "snapshot_changed": 3}.get(str(release.get("state")), 4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Target wiki directory")
    search_core.add_search_arguments(
        parser,
        history=True,
        limit_help="Maximum number of results (1-100)",
        exhaustive_help="Also rank sources and scan every passage of the wiki pages, meta/questions.md and the source "
        "Markdown (with --include-history also the history snapshots) for all words of all searches; "
        "returns at most 100,000 printed characters of matching passages under exhaustive_hits; "
        "required before stating that the wiki holds nothing on a question",
        manifest_help="Release manifest hash retained from verify_release.py; a different release reports snapshot_changed",
    )
    args = search_core.parse_search_arguments(parser)
    # The request is read and checked before the target is touched.
    try:
        query, also, request_filter = search_core.query_from_arguments(args, sys.stdin)
    except search_core.RequestError as exc:
        raise SystemExit(str(exc)) from exc

    target = Path(args.target).expanduser().resolve()
    if not (target / "WIKI.md").is_file() or not (target / "wiki/index.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    initial_release = verify_snapshot(target, args.expect_manifest_sha256)
    if initial_release.get("state") != "ready":
        print(search_core.report_json({"release": initial_release, "results": []}))
        return exit_code(initial_release)
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("limit must be between 1 and 100")
    # The exhaustive scan ranks the sources too; the report prints the effective value.
    include_sources = args.include_sources or args.exhaustive

    try:
        selector = search_core.selector_from(request_filter, args.filter_json)
        found = search_core.search(
            target,
            query,
            also=also,
            limit=args.limit,
            include_sources=include_sources,
            include_history=args.include_history,
            selector=selector,
            exhaustive=args.exhaustive,
        )
    except (search_core.QueryError, search_core.RequestError) as exc:
        raise SystemExit(str(exc)) from exc

    if found["parser_errors"]:
        final_release = verify_snapshot(target, str(initial_release.get("manifest_sha256") or ""))
        release = final_release if final_release.get("state") != "ready" else initial_release
        print(search_core.report_json({"state": "invalid_frontmatter", "release": release, "parser_errors": found["parser_errors"], "results": []}))
        return 5 if final_release.get("state") == "ready" else exit_code(final_release)
    report = {
        "target": ".",
        **search_core.report_body(
            found,
            initial_release,
            selector,
            {"include_sources": include_sources, "include_history": args.include_history},
        ),
    }
    final_release = verify_snapshot(target, str(initial_release.get("manifest_sha256") or ""))
    if final_release.get("state") != "ready":
        print(search_core.report_json({"release": final_release, "results": []}))
        return exit_code(final_release)
    print(search_core.report_json(report))
    return 0


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
