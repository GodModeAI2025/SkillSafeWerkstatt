#!/usr/bin/env python3
"""Report optional Open Knowledge Format compatibility without modifying a wiki."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from frontmatter_contract import FrontmatterError, parse_document
from wiki_lock import require_lock


RECOMMENDED = ("title", "description", "resource", "tags", "timestamp")
ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?$")


def valid_resource(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme) or value.startswith(("./", "../"))


def inspect(path: Path, target: Path) -> dict[str, Any]:
    relative = path.relative_to(target).as_posix()
    try:
        document = parse_document(path.read_text(encoding="utf-8"), relative, require_frontmatter=True)
    except (OSError, UnicodeError, FrontmatterError) as exc:
        return {"path": relative, "conformant": False, "errors": [str(exc)], "missing_recommended": list(RECOMMENDED), "suggestions": []}
    data = document.data
    errors = []
    if not isinstance(data.get("type"), str) or not str(data.get("type") or "").strip():
        errors.append("required field type must be a non-empty string")
    missing = [field for field in RECOMMENDED if data.get(field) in (None, "", [])]
    warnings = []
    if "tags" not in missing and not isinstance(data.get("tags"), list):
        warnings.append("recommended field tags should be a list")
    if "timestamp" not in missing and not ISO_TIMESTAMP.fullmatch(str(data.get("timestamp"))):
        warnings.append("recommended field timestamp is not ISO-8601-shaped")
    if "resource" not in missing and not valid_resource(data.get("resource")):
        warnings.append("recommended field resource is not a URI or relative resource reference")
    suggestions = []
    if "timestamp" in missing and data.get("updated"):
        suggestions.append({"action": "copy", "from": "updated", "to": "timestamp", "value": data.get("updated")})
    if "title" in missing:
        suggestions.append({"action": "review", "field": "title", "candidate": path.stem})
    if "description" in missing:
        suggestions.append({"action": "curate", "field": "description", "candidate": None})
    if "resource" in missing:
        suggestions.append({"action": "supply-if-known", "field": "resource", "candidate": None})
    return {
        "path": relative,
        "conformant": not errors,
        "errors": errors,
        "missing_recommended": missing,
        "warnings": warnings,
        "suggestions": suggestions,
        "unknown_fields_preserved": sorted(set(data) - {"type", *RECOMMENDED}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True)
    parser.add_argument("--include-sources", action="store_true")
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    paths = sorted((target / "wiki").rglob("*.md")) if (target / "wiki").is_dir() else []
    if args.include_sources and (target / "sources").is_dir():
        paths.extend(sorted((target / "sources").rglob("*.md")))
    documents = [inspect(path, target) for path in paths]
    report = {
        "format": "lmwiki-okf-compatibility/1",
        "target": ".",
        "mode": "report-only",
        "documents": documents,
        "summary": {
            "checked": len(documents),
            "conformant": sum(1 for item in documents if item["conformant"]),
            "nonconformant": sum(1 for item in documents if not item["conformant"]),
            "missing_recommended": sum(len(item["missing_recommended"]) for item in documents),
        },
        "boundary": "OKF compatibility does not replace the SkillSafeWerkstatt claim, source, cluster, concept, quality, or release contracts.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
