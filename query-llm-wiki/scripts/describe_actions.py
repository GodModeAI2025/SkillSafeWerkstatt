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
        {"id": "search", "helper": "search_wiki.py", "description": "Search claims and sources with concept expansion and an optional validated metadata selector; a coverage block counts truncated matches, withheld claims, and unmatched terms.", "writes": False, "destructive": False, "parameters": [{"name": "query", "type": "string", "required": True}, {"name": "limit", "type": "integer 1-100", "required": False}, {"name": "filter_json", "type": "selector", "required": False}, {"name": "include_sources", "type": "boolean", "required": False}, {"name": "include_history", "type": "boolean", "required": False}, {"name": "expect_manifest_sha256", "type": "sha256", "required": False}]},
    ],
}


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    print(json.dumps(CATALOG, ensure_ascii=False, indent=2))
