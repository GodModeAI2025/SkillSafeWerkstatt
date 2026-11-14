#!/usr/bin/env python3
"""Return the machine-readable, strictly read-only query action catalog."""

from __future__ import annotations

import json
import sys


CATALOG = {
    "format": "lmwiki-action-catalog/1",
    "skill": "query-llm-wiki",
    "read_only": True,
    "selector": {
        "types": ["all", "paths", "filter"],
        "operators": ["exists", "not_exists", "equals", "not_equals", "contains", "not_contains", "starts_with", "ends_with", "is_empty", "is_not_empty", "is_list", "is_string", "in_path"],
        "virtual_properties": ["__path", "__folder", "__filename", "__extension"],
        "combinators": ["AND", "OR"],
    },
    "actions": [
        {"id": "verify-release", "helper": "verify_release.py", "description": "Verify release hashes and lock-free snapshot stability.", "writes": False, "destructive": False, "parameters": [{"name": "expect_manifest_sha256", "type": "sha256", "required": False}]},
        {"id": "inspect-identity", "helper": "identity_status.py", "description": "Validate and return only the allowlisted confirmed SOUL and content-policy fields.", "writes": False, "destructive": False, "parameters": []},
        {"id": "assess-quality", "helper": "assess_quality.py", "description": "Assess technical state, review freshness, open questions, and snapshot age.", "writes": False, "destructive": False, "parameters": [{"name": "expect_manifest_sha256", "type": "sha256", "required": False}]},
        {"id": "inventory-frontmatter", "helper": "inventory_wiki.py", "description": "Return property counts, observed types, samples, and schema drift from a verified release.", "writes": False, "destructive": False, "parameters": [{"name": "expect_manifest_sha256", "type": "sha256", "required": False}]},
        {
            "id": "search",
            "helper": "search_wiki.py",
            "description": "Search claims and sources with concept expansion, word forms and disclosed compound and typo heuristics (match_rules per result), optional agent reformulations searched in the same call (pages only they return come back separately in reformulation_results; each result names the searches that found it in found_by), and an optional validated metadata selector; a coverage block counts truncated matches, withheld claims, word forms, and unmatched terms per search.",
            "writes": False,
            "destructive": False,
            "requires_one_of": ["query", "request"],
            "parameters": [
                {"name": "query", "type": "string", "required": False, "exclusive_with": ["request"]},
                {"name": "also", "type": "string, repeatable, at most 4, each at most 200 characters", "required": False, "exclusive_with": ["request"]},
                {"name": "request", "type": "'-': one JSON object {query, also?, filter?} on standard input; filter replaces filter_json", "required": False, "exclusive_with": ["query", "also"]},
                {"name": "limit", "type": "integer 1-100 (caps results and reformulation_results separately)", "required": False},
                {"name": "filter_json", "type": "selector", "required": False},
                {"name": "include_sources", "type": "boolean", "required": False},
                {"name": "include_history", "type": "boolean", "required": False},
                {"name": "expect_manifest_sha256", "type": "sha256", "required": False},
            ],
        },
    ],
}


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    print(json.dumps(CATALOG, ensure_ascii=False, indent=2))
