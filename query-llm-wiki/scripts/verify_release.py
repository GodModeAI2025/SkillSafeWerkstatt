#!/usr/bin/env python3
"""Verify a released SkillSafeWerkstatt snapshot without modifying it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import sync_artifacts


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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def result(state: str, **values: Any) -> dict[str, Any]:
    return {"state": state, **values}


def transfer_pending(target: Path, drifted: list[str]) -> bool:
    """True when the manifest is newer than every file whose content disagrees.

    A synchronization client transfers in its own order, so a second device can
    receive the new manifest before the content it describes. That is a transient
    state rather than a damaged release, and only waiting fixes it.
    """
    try:
        manifest_mtime = (target / "meta/manifest.json").stat().st_mtime
    except OSError:
        return False
    for relative in set(drifted):
        try:
            if (target / relative).stat().st_mtime >= manifest_mtime:
                return False
        except OSError:
            return False
    return True


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
            if not path.is_file() or path.name.endswith(".tmp"):
                continue
            relative = path.relative_to(target).as_posix()
            # A dot-prefixed name is skipped as before. Operating-system noise is
            # kept here so it can be disclosed, and filtered out when judging.
            if path.name.startswith(".") and not sync_artifacts.is_ignorable(relative):
                continue
            paths.add(relative)
    for name in META_FILES:
        if (target / name).is_file():
            paths.add(name)
    return paths


def verify_snapshot(target: Path, expected_manifest_sha256: str = "") -> dict[str, Any]:
    lock_path = target / ".llmwiki.lock"
    if lock_path.exists():
        return result("wiki_busy", reason="A maintenance writer currently owns the wiki lock")
    manifest_path = target / "meta/manifest.json"
    try:
        first_bytes = manifest_path.read_bytes()
    except OSError as exc:
        return result("invalid_wiki", reason=f"Release manifest is unavailable: {exc}")
    first_hash = sha256_bytes(first_bytes)
    if expected_manifest_sha256 and first_hash != expected_manifest_sha256:
        return result(
            "snapshot_changed",
            expected_manifest_sha256=expected_manifest_sha256,
            manifest_sha256=first_hash,
        )
    try:
        manifest = json.loads(first_bytes)
    except json.JSONDecodeError as exc:
        return result("invalid_wiki", reason=f"Release manifest is invalid JSON: {exc}")
    if not isinstance(manifest, dict) or manifest.get("format") != "lmwiki-release/1":
        return result("invalid_wiki", reason="Unsupported or missing release manifest format")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return result("invalid_wiki", reason="Release manifest contains no files")

    errors: list[str] = []
    content_drift: list[str] = []
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            errors.append("Manifest contains a non-object file entry")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative:
            errors.append("Manifest contains an empty file path")
            continue
        portable = PurePosixPath(relative)
        windows = PureWindowsPath(relative)
        if (
            portable.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or ".." in portable.parts
            or ".." in windows.parts
            or "\\" in relative
            or portable.as_posix() != relative
        ):
            errors.append(f"Manifest contains a non-portable path: {relative}")
            continue
        if relative in seen:
            errors.append(f"Manifest contains a duplicate path: {relative}")
            continue
        seen.add(relative)
        path = target / relative
        try:
            content = path.read_bytes()
        except OSError:
            errors.append(f"Released file is missing or unreadable: {relative}")
            continue
        if sha256_bytes(content) != entry.get("sha256"):
            errors.append(f"Released file hash differs: {relative}")
            content_drift.append(relative)
        if len(content) != entry.get("bytes"):
            errors.append(f"Released file size differs: {relative}")
            content_drift.append(relative)

    unexpected = sorted(controlled_paths(target) - seen)
    # A synchronization client writes into this directory too. Separate the
    # files it created from genuine release damage before judging the wiki.
    artifacts = [
        artifact
        for artifact in sync_artifacts.classify_all(unexpected)
        if artifact.kind in sync_artifacts.NON_CONTENT_KINDS
    ]
    artifact_paths = {artifact.path for artifact in artifacts}
    genuinely_unexpected = [path for path in unexpected if path not in artifact_paths]
    if genuinely_unexpected:
        errors.append(
            f"Controlled files exist outside the release manifest: {genuinely_unexpected}"
        )
    version_path = target / "WIKI_VERSION"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else ""
    if version != manifest.get("version"):
        errors.append("WIKI_VERSION differs from the release manifest")
    if lock_path.exists():
        return result("wiki_busy", reason="Maintenance started while the release was being verified")
    try:
        second_bytes = manifest_path.read_bytes()
    except OSError as exc:
        return result("snapshot_changed", reason=f"Release manifest became unavailable: {exc}")
    if second_bytes != first_bytes:
        return result(
            "snapshot_changed",
            expected_manifest_sha256=first_hash,
            manifest_sha256=sha256_bytes(second_bytes),
        )
    if errors:
        # Content that lags behind a freshly arrived manifest is a transfer still
        # in flight, not damage. Waiting resolves it; repairing would not.
        if content_drift and not genuinely_unexpected and transfer_pending(target, content_drift):
            return result(
                "sync_in_progress",
                manifest_sha256=first_hash,
                version=version,
                pending=sorted(set(content_drift)),
                reason=(
                    "The manifest is newer than the files it describes. A synchronization "
                    "transfer is most likely still running; retry once it settles."
                ),
            )
        return result("invalid_wiki", manifest_sha256=first_hash, version=version, errors=errors)
    # A conflict copy carries content that diverged across devices, so reading
    # must stop until a human decides. Operating-system noise carries nothing and
    # must never block a reader; it is reported and otherwise ignored.
    blocking = [artifact for artifact in artifacts if artifact.kind == sync_artifacts.CONFLICT_COPY]
    notices = [artifact.as_dict() for artifact in artifacts if artifact.ignorable]
    if blocking:
        return result(
            "sync_artifacts_present",
            manifest_sha256=first_hash,
            version=version,
            sync_artifacts=[artifact.as_dict() for artifact in blocking],
            ignored_artifacts=notices,
            reason=(
                "A synchronization client kept a conflicting copy next to a released file. "
                "Resolve it with the maintenance skill before reading; the release itself is intact."
            ),
        )
    return result(
        "ready",
        ignored_artifacts=notices,
        manifest_sha256=first_hash,
        release_id=manifest.get("release_id", ""),
        version=version,
        files=len(files),
        released_at=manifest.get("released_at", ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--expect-manifest-sha256", default="")
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    report = verify_snapshot(target, args.expect_manifest_sha256)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {
        "ready": 0,
        "wiki_busy": 2,
        "snapshot_changed": 3,
        "sync_artifacts_present": 5,
        "sync_in_progress": 6,
    }.get(str(report.get("state")), 4)


if __name__ == "__main__":
    raise SystemExit(main())
