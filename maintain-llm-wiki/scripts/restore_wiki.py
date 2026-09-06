#!/usr/bin/env python3
"""List, preview, and apply a hash-guarded targeted SkillSafeWerkstatt snapshot restore."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

import portable_io
from typing import Any, Optional
from uuid import uuid4

from frontmatter_contract import sha256_bytes
from snapshot_wiki import create_snapshot, sha256_file
from wiki_lock import require_lock


PLAN_FORMAT = "lmwiki-restore-plan/1"
RESULT_FORMAT = "lmwiki-restore-result/1"
SNAPSHOT_ID = re.compile(r"^[A-Za-z0-9_-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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


def portable_relative(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return not posix.is_absolute() and not windows.is_absolute() and not windows.drive and ".." not in posix.parts and "\\" not in value and posix.as_posix() == value and not value.startswith("meta/history/") and value != ".llmwiki.lock"


def snapshot_directory(target: Path, snapshot_id: str) -> Path:
    if not SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError("snapshot id contains unsupported characters")
    path = target / "meta/history" / snapshot_id
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"snapshot does not exist: {snapshot_id}")
    return path


def snapshot_record(path: Path) -> dict[str, Any]:
    record_path = path / "snapshot.json"
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid snapshot metadata in {path.name}: {exc}") from exc
        if not isinstance(record, dict) or record.get("format") != "lmwiki-snapshot/1" or record.get("snapshot_id") != path.name:
            raise ValueError(f"unsupported snapshot metadata in {path.name}")
        files = record.get("files")
        if not isinstance(files, list):
            raise ValueError(f"snapshot file list is invalid in {path.name}")
        seen: set[str] = set()
        for entry in files:
            if not isinstance(entry, dict) or not portable_relative(entry.get("path")):
                raise ValueError(f"snapshot contains a non-portable file in {path.name}")
            relative = str(entry["path"])
            if relative in seen:
                raise ValueError(f"snapshot contains duplicate file {relative} in {path.name}")
            seen.add(relative)
            if not isinstance(entry.get("bytes"), int) or int(entry["bytes"]) < 0 or not isinstance(entry.get("sha256"), str) or not SHA256.fullmatch(str(entry["sha256"])):
                raise ValueError(f"snapshot file metadata is invalid for {relative} in {path.name}")
        missing = record.get("missing", [])
        if not isinstance(missing, list) or any(not portable_relative(item) for item in missing):
            raise ValueError(f"snapshot missing-file list is invalid in {path.name}")
        return record
    files = []
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file() or candidate.name in {"snapshot.json", "action-result.json", "restore-result.json"}:
            continue
        relative = candidate.relative_to(path).as_posix()
        if portable_relative(relative):
            files.append({"path": relative, "bytes": candidate.stat().st_size, "sha256": sha256_file(candidate)})
    return {"format": "lmwiki-snapshot/legacy", "snapshot_id": path.name, "created_at": "", "operation": "legacy", "files": files, "missing": []}


def list_snapshots(target: Path) -> list[dict[str, Any]]:
    target = target.expanduser().resolve()
    history = target / "meta/history"
    result = []
    if not history.is_dir():
        return result
    for path in sorted((item for item in history.iterdir() if item.is_dir() and not item.name.startswith(".")), reverse=True):
        try:
            record = snapshot_record(path)
        except ValueError as exc:
            result.append({"snapshot_id": path.name, "valid": False, "error": str(exc)})
            continue
        result.append({"snapshot_id": path.name, "valid": True, "created_at": record.get("created_at", ""), "operation": record.get("operation", ""), "files": len(record.get("files", []))})
    return result


def create_restore_plan(target: Path, snapshot_id: str, selected_paths: Optional[list[str]], include_missing: bool) -> dict[str, Any]:
    target = target.expanduser().resolve()
    snapshot = snapshot_directory(target, snapshot_id)
    record = snapshot_record(snapshot)
    available = {entry.get("path"): entry for entry in record.get("files", []) if isinstance(entry, dict) and portable_relative(entry.get("path"))}
    if selected_paths is None:
        requested = sorted(available)
    else:
        if not selected_paths or any(not portable_relative(item) for item in selected_paths):
            raise ValueError("selected restore paths must be a non-empty array of portable paths")
        unknown = sorted(set(selected_paths) - set(available))
        if unknown:
            raise ValueError(f"selected paths are not present in the snapshot: {unknown}")
        requested = sorted(set(selected_paths))
    entries: list[dict[str, Any]] = []
    for relative in requested:
        source = snapshot / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"snapshot file is unavailable: {relative}")
        source_hash = sha256_file(source)
        if source_hash != available[relative].get("sha256"):
            raise ValueError(f"snapshot file hash differs from metadata: {relative}")
        destination = target / relative
        exists = destination.is_file() and not destination.is_symlink()
        current_bytes = destination.read_bytes() if exists else b""
        current_hash = sha256_bytes(current_bytes) if exists else ""
        skipped_reason = "" if exists or include_missing else "target file is missing; use include-missing to restore it"
        entries.append(
            {
                "path": relative,
                "before_exists": exists,
                "before_sha256": current_hash,
                "after_sha256": source_hash,
                "changed": not skipped_reason and current_hash != source_hash,
                "skipped_reason": skipped_reason or ("already identical" if current_hash == source_hash else ""),
            }
        )
    core = {
        "format": PLAN_FORMAT,
        "plan_id": str(uuid4()),
        "target": ".",
        "snapshot_id": snapshot_id,
        "snapshot_format": record.get("format"),
        "include_missing": include_missing,
        "requires_confirmation": True,
        "files": entries,
        "change_count": sum(1 for entry in entries if entry["changed"]),
        "skipped_count": sum(1 for entry in entries if not entry["changed"]),
    }
    core["plan_sha256"] = hashlib.sha256(canonical_json(core)).hexdigest()
    return core


def validate_plan(value: object, expected_hash: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("format") != PLAN_FORMAT:
        raise ValueError("unsupported or missing restore plan format")
    allowed_plan_fields = {"format", "plan_id", "target", "snapshot_id", "snapshot_format", "include_missing", "requires_confirmation", "files", "change_count", "skipped_count", "plan_sha256"}
    if set(value) != allowed_plan_fields:
        raise ValueError(f"restore plan fields differ from the contract: {sorted(set(value) ^ allowed_plan_fields)}")
    recorded = value.get("plan_sha256")
    core = {key: item for key, item in value.items() if key != "plan_sha256"}
    actual = hashlib.sha256(canonical_json(core)).hexdigest()
    if recorded != actual:
        raise ValueError("restore plan integrity check failed")
    if recorded != expected_hash:
        raise ValueError("confirmed plan hash does not match the restore plan")
    if not isinstance(value.get("files"), list):
        raise ValueError("restore plan files must be an array")
    seen: set[str] = set()
    for entry in value["files"]:
        if not isinstance(entry, dict) or not portable_relative(entry.get("path")):
            raise ValueError("restore plan contains a non-portable path")
        if entry["path"] in seen:
            raise ValueError(f"restore plan contains duplicate path: {entry['path']}")
        seen.add(entry["path"])
        before_hash = entry.get("before_sha256")
        after_hash = entry.get("after_sha256")
        if before_hash not in {""} and (not isinstance(before_hash, str) or not SHA256.fullmatch(before_hash)):
            raise ValueError(f"restore plan has an invalid before hash: {entry['path']}")
        if not isinstance(after_hash, str) or not SHA256.fullmatch(after_hash):
            raise ValueError(f"restore plan has an invalid after hash: {entry['path']}")
    if not isinstance(value.get("snapshot_id"), str) or not SNAPSHOT_ID.fullmatch(str(value.get("snapshot_id"))):
        raise ValueError("restore plan has an invalid snapshot id")
    return value


def apply_restore(target: Path, lock_token: str, plan: dict[str, Any]) -> tuple[dict[str, Any], int]:
    target = target.expanduser().resolve()
    require_lock(target, lock_token)
    snapshot = snapshot_directory(target, str(plan.get("snapshot_id") or ""))
    changed = [entry for entry in plan["files"] if entry.get("changed")]
    conflicts = []
    for entry in changed:
        destination = target / entry["path"]
        exists = destination.is_file() and not destination.is_symlink()
        current_hash = sha256_bytes(destination.read_bytes()) if exists else ""
        if exists != bool(entry.get("before_exists")) or current_hash != entry.get("before_sha256"):
            conflicts.append({"path": entry["path"], "expected_sha256": entry.get("before_sha256", ""), "current_sha256": current_hash})
        source = snapshot / entry["path"]
        if not source.is_file() or source.is_symlink() or sha256_file(source) != entry.get("after_sha256"):
            conflicts.append({"path": entry["path"], "reason": "snapshot source changed or is unavailable"})
    if conflicts:
        return {"format": RESULT_FORMAT, "state": "stale_plan", "plan_sha256": plan["plan_sha256"], "conflicts": conflicts, "written": []}, 3
    if not changed:
        return {"format": RESULT_FORMAT, "state": "no_changes", "plan_sha256": plan["plan_sha256"], "written": []}, 0
    recovery = create_snapshot(target, lock_token, operation=f"before-restore:{plan['snapshot_id']}", selected_files=[entry["path"] for entry in changed])
    written: list[str] = []
    errors: list[dict[str, str]] = []
    for entry in changed:
        destination = target / entry["path"]
        source = snapshot / entry["path"]
        try:
            exists = destination.is_file() and not destination.is_symlink()
            current_hash = sha256_bytes(destination.read_bytes()) if exists else ""
            if exists != bool(entry.get("before_exists")) or current_hash != entry.get("before_sha256"):
                errors.append({"path": entry["path"], "error": "concurrent edit detected immediately before restore"})
                break
            content = source.read_bytes()
            if sha256_bytes(content) != entry.get("after_sha256"):
                errors.append({"path": entry["path"], "error": "snapshot file hash changed"})
                break
            atomic_write(destination, content)
            written.append(entry["path"])
        except OSError as exc:
            errors.append({"path": entry["path"], "error": str(exc)})
            break
    result = {
        "format": RESULT_FORMAT,
        "state": "restored" if not errors else "partial_failure",
        "plan_sha256": plan["plan_sha256"],
        "restored_from": f"meta/history/{plan['snapshot_id']}",
        "recovery_snapshot": recovery["snapshot"],
        "written": written,
        "written_count": len(written),
        "errors": errors,
        "release_required": True,
    }
    atomic_write(target / recovery["snapshot"] / "restore-result.json", json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return result, 0 if not errors else 5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--target", required=True)
    list_parser.add_argument("--lock-token", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--target", required=True)
    plan_parser.add_argument("--lock-token", required=True)
    plan_parser.add_argument("--snapshot-id", required=True)
    plan_parser.add_argument("--paths-json")
    plan_parser.add_argument("--include-missing", action="store_true")
    plan_parser.add_argument("--output", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--target", required=True)
    apply_parser.add_argument("--lock-token", required=True)
    apply_parser.add_argument("--plan-file", required=True)
    apply_parser.add_argument("--expect-plan-sha256", required=True)
    apply_parser.add_argument("--confirm-restore", action="store_true")
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    if args.command == "list":
        print(json.dumps({"format": "lmwiki-snapshot-list/1", "snapshots": list_snapshots(target)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "plan":
        selected = None
        if args.paths_json:
            try:
                selected = json.loads(args.paths_json)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"paths-json is invalid JSON: {exc}") from exc
            if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
                raise SystemExit("paths-json must be a string array")
        try:
            plan = create_restore_plan(target, args.snapshot_id, selected, args.include_missing)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        atomic_write(Path(args.output).expanduser().resolve(), json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if not args.confirm_restore:
        print(json.dumps({"format": RESULT_FORMAT, "state": "confirmation_required"}, ensure_ascii=False, indent=2))
        return 2
    try:
        raw_plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
        plan = validate_plan(raw_plan, args.expect_plan_sha256)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"Cannot apply restore plan: {exc}") from exc
    result, code = apply_restore(target, args.lock_token, plan)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
