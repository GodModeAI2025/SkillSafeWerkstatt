#!/usr/bin/env python3
"""Inventory frontmatter properties and report schema drift without changing a wiki."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from frontmatter_contract import FrontmatterError, parse_document, value_type
from wiki_lock import require_lock


PAGE_REQUIRED = {
    "id", "title", "type", "status", "created", "updated", "description", "language",
    "sources", "clusters", "concepts", "tags",
}
PAGE_OPTIONAL = {"aliases", "primary_cluster", "resource", "timestamp"}
SOURCE_REQUIRED = {
    "source_id", "title", "date", "original_ref", "extracted_sha256", "source_type",
    "content_language", "extracted_at", "extractor", "status", "tags",
}
SOURCE_OPTIONAL = {"original_version", "original_sha256", "extraction_notes", "resource", "timestamp"}
LIST_FIELDS = {"aliases", "sources", "clusters", "concepts", "tags"}
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


def candidate_paths(target: Path) -> Iterable[Path]:
    roots = (target / "wiki", target / "sources", target / "schema")
    for root in roots:
        if root.is_dir():
            yield from sorted(root.rglob("*.md"))


def document_class(relative: str) -> str:
    if relative.startswith("wiki/"):
        return "wiki-page"
    if relative.startswith("sources/"):
        return "source"
    return "schema"


def expected_fields(kind: str) -> tuple[set[str], set[str]]:
    if kind == "wiki-page":
        return PAGE_REQUIRED, PAGE_OPTIONAL
    if kind == "source":
        return SOURCE_REQUIRED, SOURCE_OPTIONAL
    return set(), set()


def sample_value(value: Any) -> Any:
    def bounded(item: Any) -> Any:
        return item[:160] + "…" if isinstance(item, str) and len(item) > 160 else item
    return [bounded(item) for item in value[:5]] if isinstance(value, list) else bounded(value)


def inventory(target: Path) -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {}
    documents: list[dict[str, Any]] = []
    parser_errors: list[dict[str, str]] = []
    kind_counts: Counter[str] = Counter()
    with_frontmatter = 0
    for path in candidate_paths(target):
        relative = path.relative_to(target).as_posix()
        kind = document_class(relative)
        kind_counts[kind] += 1
        if path.is_symlink():
            parser_errors.append({"path": relative, "error": "symbolic links are not supported"})
            continue
        try:
            document = parse_document(path.read_text(encoding="utf-8"), relative)
        except (OSError, UnicodeError, FrontmatterError) as exc:
            parser_errors.append({"path": relative, "error": str(exc)})
            continue
        if not document.has_frontmatter:
            if kind != "schema":
                parser_errors.append({"path": relative, "error": "missing YAML frontmatter"})
            continue
        with_frontmatter += 1
        required, optional = expected_fields(kind)
        keys = set(document.data)
        drift: list[dict[str, Any]] = []
        for key in sorted(required - keys):
            drift.append({"kind": "missing-required", "property": key})
        for key in sorted(keys - required - optional):
            if kind != "schema":
                drift.append({"kind": "extension", "property": key})
        for key, value in document.data.items():
            observed = value_type(value)
            if key in LIST_FIELDS and not isinstance(value, list):
                drift.append({"kind": "type-mismatch", "property": key, "expected": "list", "observed": observed})
            if kind != "schema" and not SNAKE_CASE.fullmatch(key):
                suggestion = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
                drift.append({"kind": "property-name", "property": key, "suggested": suggestion})
            stat = properties.setdefault(
                key,
                {"property": key, "count": 0, "types": Counter(), "documents": Counter(), "samples": []},
            )
            stat["count"] += 1
            stat["types"][observed] += 1
            stat["documents"][kind] += 1
            rendered = sample_value(value)
            if rendered not in stat["samples"] and len(stat["samples"]) < 5:
                stat["samples"].append(rendered)
        documents.append({"path": relative, "class": kind, "properties": len(keys), "drift": drift})

    serialized_properties = []
    for key in sorted(properties, key=lambda item: (-properties[item]["count"], item)):
        stat = properties[key]
        serialized_properties.append(
            {
                "property": key,
                "count": stat["count"],
                "types": dict(sorted(stat["types"].items())),
                "document_classes": dict(sorted(stat["documents"].items())),
                "samples": stat["samples"],
            }
        )
    drift_documents = [item for item in documents if item["drift"]]
    drift_counts = Counter(entry["kind"] for item in drift_documents for entry in item["drift"])
    return {
        "format": "lmwiki-frontmatter-inventory/1",
        "target": ".",
        "documents_scanned": sum(kind_counts.values()),
        "documents_with_frontmatter": with_frontmatter,
        "document_classes": dict(sorted(kind_counts.items())),
        "properties": serialized_properties,
        "drift": {
            "documents": drift_documents,
            "counts": dict(sorted(drift_counts.items())),
            "parser_errors": parser_errors,
            "clean": not drift_documents and not parser_errors,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    report = inventory(target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["drift"]["parser_errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
