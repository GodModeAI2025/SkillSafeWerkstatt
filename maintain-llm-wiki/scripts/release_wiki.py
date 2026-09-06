#!/usr/bin/env python3
"""Validate and publish one immutable SkillSafeWerkstatt release boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional
from uuid import uuid4

import portable_io
import sync_artifacts

from wiki_lock import require_lock


VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
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
QUALITY_FIELDS = (
    "quality_review_after_days",
    "cleaning_review_after_days",
    "snapshot_warning_after_days",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        portable_io.replace_with_retry(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_version(path: Path) -> tuple[int, int, int]:
    value = path.read_text(encoding="utf-8").strip() if path.is_file() else "0.0.0"
    match = VERSION_RE.fullmatch(value)
    if not match:
        raise SystemExit(f"WIKI_VERSION is not semantic version x.y.z: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def version_text(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def prior_operation(path: Path, operation_id: str) -> Optional[dict[str, object]]:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("operation_id") == operation_id:
            return record
    return None


def bump_version(version: tuple[int, int, int], bump: str) -> str:
    major, minor, patch = version
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def controlled_files(target: Path) -> list[Path]:
    found: set[Path] = set()
    for name in ROOT_FILES:
        path = target / name
        if path.is_file():
            found.add(path)
    for directory in CONTROLLED_DIRS:
        root = target / directory
        if root.is_dir():
            for path in root.rglob("*"):
                if not path.is_file() or path.name.startswith(".") or path.name.endswith(".tmp"):
                    continue
                # Never hash operating-system noise into a release boundary; the
                # storage layer does not carry it, so its hash cannot be reproduced.
                if sync_artifacts.is_ignorable(path.relative_to(target).as_posix()):
                    continue
                found.add(path)
    for name in META_FILES:
        path = target / name
        if path.is_file():
            found.add(path)
    return sorted(found, key=lambda path: path.relative_to(target).as_posix())


def previous_manifest_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes()) if path.is_file() else ""


def read_quality_policy(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    policy: dict[str, int] = {}
    for field in QUALITY_FIELDS:
        match = re.search(rf"^{re.escape(field)}:\s*(\d+)\s*$", text, re.MULTILINE)
        if not match:
            raise SystemExit(f"schema/QUALITY_POLICY.md is missing {field}")
        value = int(match.group(1))
        if value < 1 or value > 3650:
            raise SystemExit(f"schema/QUALITY_POLICY.md has invalid {field}")
        policy[field] = value
    return policy


def latest_quality_reviews(path: Path) -> dict[str, object]:
    latest: dict[str, object] = {"quality": None, "cleaning": None}
    if not path.is_file():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("format") != "lmwiki-quality-review/1":
            continue
        kind = record.get("kind")
        if kind not in latest:
            continue
        current = latest[kind]
        if not isinstance(current, dict) or str(record.get("reviewed_at") or "") >= str(current.get("reviewed_at") or ""):
            latest[str(kind)] = {
                "review_id": str(record.get("review_id") or ""),
                "reviewed_at": str(record.get("reviewed_at") or ""),
                "outcome": str(record.get("outcome") or ""),
                "summary": str(record.get("summary") or ""),
            }
    return latest


def count_open_question_items(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"^\s*[-*+]\s+\S", line)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    parser.add_argument("--summary", default="Validated wiki maintenance release")
    parser.add_argument("--operation-id", required=True, help="Stable idempotency key for this release intent")
    parser.add_argument("--expect-current-version", required=True)
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    lock = require_lock(target, args.lock_token)
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    operation_id = args.operation_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id):
        raise SystemExit("operation-id must be a portable identifier of at most 128 characters")

    releases_path = target / "meta/releases.jsonl"
    existing_operation = prior_operation(releases_path, operation_id)
    if existing_operation is not None:
        current_version = version_text(read_version(target / "WIKI_VERSION"))
        manifest_path = target / "meta/manifest.json"
        try:
            current_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_hash = sha256_bytes(manifest_path.read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Existing release operation cannot be verified: {exc}") from exc
        if (
            current_manifest.get("release_id") != existing_operation.get("release_id")
            or current_version != existing_operation.get("version")
        ):
            raise SystemExit("operation-id was already used by an older release; use a new operation-id")
        print(json.dumps({
            "state": "already_released",
            "released": True,
            "idempotent_replay": True,
            "operation_id": operation_id,
            "release_id": existing_operation.get("release_id", ""),
            "version": current_version,
            "manifest": "meta/manifest.json",
            "manifest_sha256": manifest_hash,
            "lint_valid": True,
            "manifest_written_last": True,
        }, ensure_ascii=False, indent=2))
        return 0

    old_version = read_version(target / "WIKI_VERSION")
    current_version = version_text(old_version)
    if args.expect_current_version != current_version:
        raise SystemExit(
            f"stale release precondition: expected {args.expect_current_version}, current {current_version}"
        )

    lint_script = Path(__file__).resolve().parent / "lint_wiki.py"
    lint = subprocess.run(
        [
            sys.executable,
            str(lint_script),
            "--target",
            str(target),
            "--lock-token",
            args.lock_token,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if lint.returncode != 0:
        if lint.stdout:
            print(lint.stdout, end="", file=sys.stderr)
        if lint.stderr:
            print(lint.stderr, end="", file=sys.stderr)
        raise SystemExit("Release refused because the strict wiki lint failed")
    try:
        lint_result = json.loads(lint.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("Release lint helper returned invalid JSON") from exc
    new_version = bump_version(old_version, args.bump)
    released_at = utc_now()
    release_id = str(uuid4())
    manifest_path = target / "meta/manifest.json"
    prior_hash = previous_manifest_hash(manifest_path)

    atomic_write(target / "WIKI_VERSION", (new_version + "\n").encode("utf-8"))
    existing_log = releases_path.read_bytes() if releases_path.is_file() else b""
    if existing_log and not existing_log.endswith(b"\n"):
        existing_log += b"\n"
    release_record = {
        "format": "lmwiki-release-log/1",
        "release_id": release_id,
        "version": new_version,
        "released_at": released_at,
        "summary": args.summary,
        "bump": args.bump,
        "previous_manifest_sha256": prior_hash,
        "lock_id": lock.get("lock_id", ""),
        "operation_id": operation_id,
    }
    log_line = json.dumps(release_record, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
    atomic_write(releases_path, existing_log + log_line)

    try:
        lint_report = json.loads((target / "meta/lint-report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SystemExit("Release lint report is unavailable or invalid")
    policy = read_quality_policy(target / "schema/QUALITY_POLICY.md")
    quality_status = {
        "format": "lmwiki-quality/1",
        "generated_at": released_at,
        "release_id": release_id,
        "version": new_version,
        "policy": policy,
        "technical": {
            "last_lint_at": released_at,
            "valid": bool(lint_report.get("valid")),
            "errors": len(lint_report.get("errors") or []),
            "warnings": len(lint_report.get("warnings") or []),
        },
        "reviews": latest_quality_reviews(target / "meta/quality-reviews.jsonl"),
        "open_question_items": count_open_question_items(target / "meta/questions.md"),
    }
    atomic_write(
        target / "meta/quality-status.json",
        (json.dumps(quality_status, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )

    entries: list[dict[str, object]] = []
    total_bytes = 0
    for path in controlled_files(target):
        relative = path.relative_to(target).as_posix()
        if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
            raise SystemExit(f"Refusing non-portable manifest path: {relative}")
        content = path.read_bytes()
        total_bytes += len(content)
        entries.append({"path": relative, "sha256": sha256_bytes(content), "bytes": len(content)})

    manifest = {
        "format": "lmwiki-release/1",
        "release_id": release_id,
        "version": new_version,
        "released_at": released_at,
        "previous_manifest_sha256": prior_hash,
        "files": entries,
        "totals": {"files": len(entries), "bytes": total_bytes},
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    atomic_write(manifest_path, manifest_bytes)
    manifest_hash = sha256_bytes(manifest_bytes)

    print(
        json.dumps(
            {
                "state": "released",
                "released": True,
                "idempotent_replay": False,
                "operation_id": operation_id,
                "release_id": release_id,
                "version": new_version,
                "manifest": "meta/manifest.json",
                "manifest_sha256": manifest_hash,
                "quality_status": "meta/quality-status.json",
                "quality_review_at": (
                    (quality_status.get("reviews") or {}).get("quality", {}).get("reviewed_at", "")
                    if isinstance((quality_status.get("reviews") or {}).get("quality"), dict)
                    else ""
                ),
                "cleaning_review_at": (
                    (quality_status.get("reviews") or {}).get("cleaning", {}).get("reviewed_at", "")
                    if isinstance((quality_status.get("reviews") or {}).get("cleaning"), dict)
                    else ""
                ),
                "files": len(entries),
                "bytes": total_bytes,
                "manifest_written_last": True,
                "lint_valid": bool(lint_result.get("valid")),
                "stats": lint_result.get("stats", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
