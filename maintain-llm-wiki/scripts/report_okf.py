#!/usr/bin/env python3
"""Report Open Knowledge Format v0.2 compatibility without modifying a wiki."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import okf_contract
import sync_artifacts
from frontmatter_contract import FrontmatterError, parse_document
from wiki_lock import require_lock


def load_registry(path: Path) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return registry
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        source_id = record.get("source_id") if isinstance(record, dict) else None
        if isinstance(source_id, str) and source_id:
            registry[source_id] = record
    return registry


def inspect_file(path: Path, target: Path) -> dict[str, Any]:
    relative = path.relative_to(target).as_posix()
    try:
        document = parse_document(
            path.read_text(encoding="utf-8"), relative, require_frontmatter=True
        )
    except (OSError, UnicodeError, FrontmatterError) as exc:
        return {
            "path": relative,
            "conformant": False,
            "errors": [str(exc)],
            "warnings": [],
            "missing_recommended": list(okf_contract.RECOMMENDED),
            "suggestions": [],
        }
    return okf_contract.inspect(document.data, relative)


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
    paths = [
        path
        for path in paths
        if not sync_artifacts.is_ignorable(path.relative_to(target).as_posix())
    ]

    documents = [inspect_file(path, target) for path in paths]
    report = {
        "format": okf_contract.REPORT_FORMAT,
        "okf_version": okf_contract.OKF_VERSION,
        "target": ".",
        "mode": "report-only",
        "documents": documents,
        "summary": {
            "checked": len(documents),
            "conformant": sum(1 for item in documents if item["conformant"]),
            "nonconformant": sum(1 for item in documents if not item["conformant"]),
            "missing_recommended": sum(len(item["missing_recommended"]) for item in documents),
            "warnings": sum(len(item.get("warnings") or []) for item in documents),
        },
        "not_exported": list(okf_contract.NOT_EXPORTED),
        "boundary": (
            "OKF compatibility is an interoperability view. It does not replace the "
            "SkillSafeWerkstatt claim, source, cluster, concept, quality, or release contracts, "
            "and this report never invents a missing value."
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
