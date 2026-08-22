#!/usr/bin/env python3
"""Snapshot wiki-controlled files before an incremental maintenance run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Optional
from uuid import uuid4

from wiki_lock import require_lock


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def portable_relative(value: str) -> bool:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return bool(value) and not posix.is_absolute() and not windows.is_absolute() and not windows.drive and ".." not in posix.parts and "\\" not in value and posix.as_posix() == value


def default_candidates(target: Path) -> list[Path]:
    return [
        target / "WIKI.md",
        target / "WIKI_VERSION",
        target / "SOUL.md",
        target / "schema",
        target / "wiki",
        target / "meta/sources.jsonl",
        target / "meta/changes.md",
        target / "meta/questions.md",
        target / "meta/lint-report.json",
        target / "meta/releases.jsonl",
        target / "meta/quality-reviews.jsonl",
        target / "meta/quality-status.json",
        target / "meta/manifest.json",
    ]


def selected_candidates(target: Path, selected_files: Iterable[str]) -> list[Path]:
    candidates: list[Path] = []
    for relative in selected_files:
        if not portable_relative(relative):
            raise ValueError(f"snapshot path is not portable: {relative!r}")
        candidate = target / relative
        try:
            candidate.resolve().relative_to(target)
        except ValueError as exc:
            raise ValueError(f"snapshot path escapes the wiki: {relative!r}") from exc
        if candidate.is_symlink():
            raise ValueError(f"snapshot refuses symbolic link: {relative!r}")
        candidates.append(candidate)
    return candidates


def create_snapshot(
    target: Path,
    lock_token: str,
    run_id: Optional[str] = None,
    operation: str = "maintenance",
    selected_files: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    lock = require_lock(target, lock_token)
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")

    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    if not run_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("run-id may contain only letters, digits, hyphens, and underscores")

    destination = target / "meta/history" / run_id
    if destination.exists():
        raise SystemExit(f"Snapshot already exists: meta/history/{run_id}")

    temporary = destination.with_name(f".{run_id}.{uuid4().hex}.tmp")
    copied: list[str] = []
    missing: list[str] = []
    candidates = selected_candidates(target, selected_files) if selected_files is not None else default_candidates(target)
    try:
        for candidate in candidates:
            if not candidate.exists():
                if selected_files is not None:
                    missing.append(candidate.relative_to(target).as_posix())
                continue
            if candidate.is_symlink():
                raise ValueError(f"snapshot refuses symbolic link: {candidate.relative_to(target).as_posix()}")
            if candidate.is_dir():
                symbolic = [path.relative_to(target).as_posix() for path in candidate.rglob("*") if path.is_symlink()]
                if symbolic:
                    raise ValueError(f"snapshot refuses symbolic links: {symbolic}")
            relative = candidate.relative_to(target)
            output = temporary / relative
            if candidate.is_dir():
                shutil.copytree(candidate, output)
                copied.extend(path.relative_to(target).as_posix() for path in candidate.rglob("*") if path.is_file() and not path.is_symlink())
            elif candidate.is_file():
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, output)
                copied.append(relative.as_posix())
        copied = sorted(set(copied))
        entries = []
        for relative in copied:
            snapshot_file = temporary / relative
            entries.append({"path": relative, "bytes": snapshot_file.stat().st_size, "sha256": sha256_file(snapshot_file)})
        snapshot_record = {
            "format": "lmwiki-snapshot/1",
            "snapshot_id": run_id,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "operation": operation,
            "lock_id": str(lock.get("lock_id") or ""),
            "files": entries,
            "missing": sorted(set(missing)),
        }
        temporary.mkdir(parents=True, exist_ok=True)
        (temporary / "snapshot.json").write_text(json.dumps(snapshot_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(temporary), str(destination))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"snapshot": f"meta/history/{run_id}", "snapshot_id": run_id, "operation": operation, "copied": copied, "missing": sorted(set(missing))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--run-id", help="Optional filesystem-safe run identifier")
    parser.add_argument("--operation", default="maintenance")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    report = create_snapshot(target, args.lock_token, args.run_id, args.operation)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
