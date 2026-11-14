#!/usr/bin/env python3
"""Search only this skill's bundled frozen wiki and return ranked JSON evidence.

This is the command-line wrapper of an exported knowledge skill. It verifies the
bundled snapshot before and after the search; ranking, claims, snippets and the
coverage block come from `search_core.py`, the same core the query skill uses.
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
from verify_knowledge import knowledge_root, verify
from wiki_filters import validate_selector


#: Result paths are relative to this skill's folder, where the agent opens them.
PATH_PREFIX = "references/knowledge/"


def snapshot_changed(expected: str = "", actual: str = "") -> int:
    release: dict = {"state": "snapshot_changed"}
    if expected:
        release.update({"expected_manifest_sha256": expected, "manifest_sha256": actual})
    print(json.dumps({"release": release, "results": []}, ensure_ascii=False, indent=2))
    return 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Question or retrieval query")
    parser.add_argument("--limit", type=int, default=12, help="Maximum result count (1-100)")
    parser.add_argument("--include-sources", action="store_true", help="Also search faithful source Markdown")
    parser.add_argument("--filter-json", default='{"kind":"all"}', help="Validated metadata selector as JSON")
    parser.add_argument(
        "--expect-manifest-sha256",
        default="",
        help="Manifest hash retained from verify_knowledge.py; a different snapshot reports snapshot_changed",
    )
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("limit must be between 1 and 100")
    try:
        selector = validate_selector(json.loads(args.filter_json))
    except (json.JSONDecodeError, ValueError, FrontmatterError) as exc:
        raise SystemExit(f"filter-json is invalid: {exc}") from exc

    release = verify()
    if release.get("state") != "ready":
        print(json.dumps({"release": release, "results": []}, ensure_ascii=False, indent=2))
        return 4
    if args.expect_manifest_sha256 and release.get("manifest_sha256") != args.expect_manifest_sha256:
        return snapshot_changed(args.expect_manifest_sha256, str(release.get("manifest_sha256") or ""))
    try:
        found = search_core.search(
            knowledge_root(),
            args.query,
            limit=args.limit,
            include_sources=args.include_sources,
            selector=selector,
            history_shipped=False,
            path_prefix=PATH_PREFIX,
        )
    except search_core.QueryError as exc:
        raise SystemExit(str(exc)) from exc

    final_release = verify()
    if final_release.get("state") != "ready" or final_release.get("manifest_sha256") != release.get("manifest_sha256"):
        return snapshot_changed()
    if found["parser_errors"]:
        print(json.dumps({"state": "invalid_frontmatter", "release": release, "parser_errors": found["parser_errors"], "results": []}, ensure_ascii=False, indent=2))
        return 5
    print(json.dumps({
        "query": args.query,
        "release": release,
        "searched_files": found["searched_files"],
        "include_sources": args.include_sources,
        "selector": selector,
        "filtered_out": found["filtered_out"],
        "matched_concepts": found["matched_concepts"],
        "expanded_terms": found["expanded_terms"],
        "facets": found["facets"],
        "results": found["results"],
        "coverage": found["coverage"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
