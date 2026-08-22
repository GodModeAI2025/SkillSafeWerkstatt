#!/usr/bin/env python3
"""Plan and atomically apply a validated batch of staged wiki pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from frontmatter_contract import FrontmatterError, parse_document
from snapshot_wiki import create_snapshot
from wiki_lock import require_lock


PLAN_FORMAT = "lmwiki-page-batch/1"
HUMAN_KEEP = re.compile(r"<!--\s*human:keep\s*-->.*?<!--\s*/human:keep\s*-->", re.DOTALL | re.IGNORECASE)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def portable_page_path(value: str) -> bool:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return (
        bool(value)
        and value == posix.as_posix()
        and value.startswith("wiki/")
        and value.endswith(".md")
        and not posix.is_absolute()
        and not windows.is_absolute()
        and not windows.drive
        and ".." not in posix.parts
        and "\\" not in value
    )


def read_paths(value: str) -> list[str]:
    try:
        paths = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"paths JSON is invalid: {exc}") from exc
    if not isinstance(paths, list) or not paths:
        raise ValueError("paths JSON must be a non-empty list")
    cleaned: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not portable_page_path(path):
            raise ValueError(f"invalid staged wiki path: {path!r}")
        if path in cleaned:
            raise ValueError(f"duplicate staged wiki path: {path}")
        cleaned.append(path)
    return cleaned


def structural_preflight(path: str, content: str) -> None:
    if "\x00" in content or "\ufffd" in content:
        raise ValueError(f"{path}: contains invalid text markers")
    if max((len(line) for line in content.splitlines()), default=0) > 20000:
        raise ValueError(f"{path}: contains an extremely long flattened line")
    try:
        document = parse_document(content, path, require_frontmatter=True)
    except FrontmatterError as exc:
        raise ValueError(str(exc)) from exc
    if not document.body.strip():
        raise ValueError(f"{path}: body is empty")


def plan_batch(target: Path, staging: Path, paths: list[str]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for relative in paths:
        staged = staging / relative
        if not staged.is_file() or staged.is_symlink():
            raise ValueError(f"staged file is missing or invalid: {relative}")
        content = staged.read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{relative}: staged file is not UTF-8") from exc
        structural_preflight(relative, text)
        current = target / relative
        before = current.read_bytes() if current.is_file() else b""
        if current.is_file():
            old_keep = HUMAN_KEEP.findall(before.decode("utf-8"))
            new_keep = HUMAN_KEEP.findall(text)
            if old_keep != new_keep:
                raise ValueError(f"{relative}: protected human:keep blocks changed")
        files.append({
            "path": relative,
            "staged_sha256": sha256_bytes(content),
            "staged_bytes": len(content),
            "before_exists": current.is_file(),
            "before_sha256": sha256_bytes(before) if current.is_file() else "",
        })
    payload = {"format": PLAN_FORMAT, "files": files}
    return {**payload, "plan_sha256": sha256_bytes(canonical(payload))}


def validate_plan(plan: Any, expected: str) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("format") != PLAN_FORMAT:
        raise ValueError("unsupported page batch plan")
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    actual = sha256_bytes(canonical(payload))
    if not expected or plan.get("plan_sha256") != expected or actual != expected:
        raise ValueError("page batch plan is stale or was modified")
    return plan


def run_json(command: list[str]) -> tuple[int, dict[str, Any]]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        value = {"error": (completed.stderr or completed.stdout or "helper returned invalid JSON").strip()}
    return completed.returncode, value if isinstance(value, dict) else {"error": "helper returned non-object JSON"}


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def apply_batch(target: Path, staging: Path, token: str, plan: dict[str, Any]) -> tuple[dict[str, Any], int]:
    require_lock(target, token)
    staged_content: dict[str, bytes] = {}
    for entry in plan["files"]:
        relative = str(entry["path"])
        staged = staging / relative
        try:
            content = staged.read_bytes()
        except OSError:
            return {"state": "stale_plan", "reason": f"staged file disappeared: {relative}"}, 3
        current = target / relative
        before = current.read_bytes() if current.is_file() else b""
        if sha256_bytes(content) != entry.get("staged_sha256") or len(content) != entry.get("staged_bytes"):
            return {"state": "stale_plan", "reason": f"staged file changed: {relative}"}, 3
        if current.is_file() != bool(entry.get("before_exists")):
            return {"state": "stale_plan", "reason": f"target existence changed: {relative}"}, 3
        if current.is_file() and sha256_bytes(before) != entry.get("before_sha256"):
            return {"state": "stale_plan", "reason": f"target file changed: {relative}"}, 3
        staged_content[relative] = content

    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="lmwiki-batch-") as temporary:
        mirror = Path(temporary) / "wiki"
        shutil.copytree(target, mirror, symlinks=True)
        for relative, content in staged_content.items():
            atomic_write(mirror / relative, content)
        graph_code, graph = run_json([
            sys.executable, str(scripts / "build_graph.py"),
            "--target", str(mirror), "--lock-token", token,
        ])
        lint_code, lint = run_json([
            sys.executable, str(scripts / "lint_wiki.py"),
            "--target", str(mirror), "--lock-token", token, "--check-only",
        ])
        if graph_code != 0 or lint_code != 0 or not lint.get("valid"):
            return {
                "state": "validation_failed",
                "writes": 0,
                "graph": graph,
                "lint": lint,
            }, 4

    snapshot = create_snapshot(
        target,
        token,
        operation="apply-validated-page-batch",
        selected_files=staged_content.keys(),
    )
    applied_paths: list[str] = []
    try:
        for relative, content in staged_content.items():
            atomic_write(target / relative, content)
            applied_paths.append(relative)
    except OSError as exc:
        return {
            "state": "partial_failure",
            "reason": f"page publishing failed after validated preflight: {exc}",
            "applied_paths": applied_paths,
            "snapshot": snapshot,
            "recovery_required": True,
        }, 5
    graph_code, graph = run_json([
        sys.executable, str(scripts / "build_graph.py"),
        "--target", str(target), "--lock-token", token,
    ])
    if graph_code != 0:
        return {
            "state": "partial_failure",
            "reason": "validated pages were applied but graph regeneration failed; retain the lock and restore the snapshot",
            "snapshot": snapshot,
            "graph": graph,
        }, 5
    return {
        "state": "applied",
        "writes": len(staged_content),
        "paths": sorted(staged_content),
        "snapshot": snapshot,
        "graph": graph,
        "plan_sha256": plan["plan_sha256"],
    }, 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--target", required=True)
    plan_parser.add_argument("--lock-token", required=True)
    plan_parser.add_argument("--staging-dir", required=True)
    plan_parser.add_argument("--paths-json", required=True)
    plan_parser.add_argument("--output", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--target", required=True)
    apply_parser.add_argument("--lock-token", required=True)
    apply_parser.add_argument("--staging-dir", required=True)
    apply_parser.add_argument("--plan-file", required=True)
    apply_parser.add_argument("--expect-plan-sha256", required=True)
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    staging = Path(args.staging_dir).expanduser().resolve()
    require_lock(target, args.lock_token)
    if staging == target or target in staging.parents or staging in target.parents:
        raise SystemExit("staging directory must be outside the target wiki")
    try:
        if args.command == "plan":
            plan = plan_batch(target, staging, read_paths(args.paths_json))
            output = Path(args.output).expanduser().resolve()
            if output == target or target in output.parents:
                raise ValueError("page batch plan must stay outside the target wiki")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        plan = validate_plan(json.loads(Path(args.plan_file).read_text(encoding="utf-8")), args.expect_plan_sha256)
        result, code = apply_batch(target, staging, args.lock_token, plan)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
