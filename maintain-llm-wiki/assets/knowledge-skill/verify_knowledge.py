#!/usr/bin/env python3
"""Verify this skill's bundled frozen wiki without modifying it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


ROOT_FILES = ("WIKI.md", "WIKI_VERSION", "SOUL.md", "STANDARDS.md")
CONTROLLED_DIRS = ("schema", "sources", "wiki", "graph")
META_FILES = (
    "meta/sources.jsonl",
    "meta/changes.md",
    "meta/questions.md",
    "meta/lint-report.json",
    "meta/releases.jsonl",
    "meta/quality-reviews.jsonl",
    "meta/quality-status.json",
)


def knowledge_root() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "knowledge"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def controlled_paths(target: Path) -> set[str]:
    paths: set[str] = set()
    for name in ROOT_FILES:
        if (target / name).is_file():
            paths.add(name)
    for directory in CONTROLLED_DIRS:
        root = target / directory
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not path.name.startswith(".") and not path.name.endswith(".tmp"):
                paths.add(path.relative_to(target).as_posix())
    for name in META_FILES:
        if (target / name).is_file():
            paths.add(name)
    return paths


def verify() -> dict[str, Any]:
    target = knowledge_root()
    manifest_path = target / "meta/manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        return {"state": "invalid_snapshot", "reason": f"Release manifest is unavailable or invalid: {exc}"}
    if not isinstance(manifest, dict) or manifest.get("format") != "lmwiki-release/1":
        return {"state": "invalid_snapshot", "reason": "Unsupported release manifest format"}
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return {"state": "invalid_snapshot", "reason": "Release manifest has no files"}

    errors: list[str] = []
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            errors.append("Manifest contains a non-object entry")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative:
            errors.append("Manifest contains an empty path")
            continue
        path_value = PurePosixPath(relative)
        windows = PureWindowsPath(relative)
        if (
            path_value.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or ".." in path_value.parts
            or ".." in windows.parts
            or "\\" in relative
            or path_value.as_posix() != relative
        ):
            errors.append(f"Manifest path is not portable: {relative}")
            continue
        if relative in seen:
            errors.append(f"Manifest path is duplicated: {relative}")
            continue
        seen.add(relative)
        path = target / relative
        try:
            content = path.read_bytes()
        except OSError:
            errors.append(f"Released file is missing: {relative}")
            continue
        if sha256_bytes(content) != entry.get("sha256"):
            errors.append(f"Released file hash differs: {relative}")
        if len(content) != entry.get("bytes"):
            errors.append(f"Released file size differs: {relative}")
    unexpected = sorted(controlled_paths(target) - seen)
    if unexpected:
        errors.append(f"Files exist outside the frozen manifest: {unexpected}")
    version_path = target / "WIKI_VERSION"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else ""
    if version != manifest.get("version"):
        errors.append("WIKI_VERSION differs from the frozen manifest")
    if errors:
        return {
            "state": "invalid_snapshot",
            "version": version,
            "manifest_sha256": sha256_bytes(manifest_bytes),
            "errors": errors,
        }
    return {
        "state": "ready",
        "version": version,
        "release_id": manifest.get("release_id", ""),
        "released_at": manifest.get("released_at", ""),
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "files": len(files),
    }


def main() -> int:
    report = verify()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("state") == "ready" else 4


if __name__ == "__main__":
    raise SystemExit(main())
