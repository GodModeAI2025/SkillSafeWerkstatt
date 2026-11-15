#!/usr/bin/env python3
"""Search only this skill's bundled frozen wiki and return ranked JSON evidence.

This is the command-line wrapper of an exported knowledge skill. It verifies the
bundled snapshot before and after the search; ranking, claims, snippets,
reformulations and the coverage block come from `search_core.py`, the same core
the query skill uses. The query and up to four reformulations come from
`--query` and `--also`, or as one JSON object on standard input with
`--request -`. With `--exhaustive` the same call also ranks the sources and
scans every passage for all words of all searches before an absence statement;
every report carries `search_record` and `absence_check`.
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
from verify_knowledge import knowledge_root, verify


#: Result paths are relative to this skill's folder, where the agent opens them.
PATH_PREFIX = "references/knowledge/"


def snapshot_changed(expected: str = "", actual: str = "") -> int:
    release: dict = {"state": "snapshot_changed"}
    if expected:
        release.update({"expected_manifest_sha256": expected, "manifest_sha256": actual})
    print(search_core.report_json({"release": release, "results": []}))
    return 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    search_core.add_search_arguments(
        parser,
        history=False,
        limit_help="Maximum result count (1-100)",
        exhaustive_help="Also rank sources and scan every passage of the wiki pages, meta/questions.md and the source "
        "Markdown for all words of all searches; "
        "returns at most 100,000 printed characters of matching passages under exhaustive_hits; "
        "required before stating that the snapshot holds nothing on a question",
        manifest_help="Manifest hash retained from verify_knowledge.py; a different snapshot reports snapshot_changed",
    )
    args = search_core.parse_search_arguments(parser)
    # The request is read and checked before the snapshot is touched.
    try:
        query, also, request_filter = search_core.query_from_arguments(args, sys.stdin)
    except search_core.RequestError as exc:
        raise SystemExit(str(exc)) from exc
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("limit must be between 1 and 100")
    try:
        selector = search_core.selector_from(request_filter, args.filter_json)
    except search_core.RequestError as exc:
        raise SystemExit(str(exc)) from exc

    release = verify()
    if release.get("state") != "ready":
        print(search_core.report_json({"release": release, "results": []}))
        return 4
    if args.expect_manifest_sha256 and release.get("manifest_sha256") != args.expect_manifest_sha256:
        return snapshot_changed(args.expect_manifest_sha256, str(release.get("manifest_sha256") or ""))
    # The exhaustive scan ranks the sources too; the report prints the effective value.
    include_sources = args.include_sources or args.exhaustive
    try:
        found = search_core.search(
            knowledge_root(),
            query,
            also=also,
            limit=args.limit,
            include_sources=include_sources,
            selector=selector,
            history_shipped=False,
            path_prefix=PATH_PREFIX,
            exhaustive=args.exhaustive,
        )
    except (search_core.QueryError, search_core.RequestError) as exc:
        raise SystemExit(str(exc)) from exc

    final_release = verify()
    if final_release.get("state") != "ready" or final_release.get("manifest_sha256") != release.get("manifest_sha256"):
        return snapshot_changed()
    if found["parser_errors"]:
        print(search_core.report_json({"state": "invalid_frontmatter", "release": release, "parser_errors": found["parser_errors"], "results": []}))
        return 5
    print(search_core.report_json(search_core.report_body(found, release, selector, {"include_sources": include_sources})))
    return 0


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
