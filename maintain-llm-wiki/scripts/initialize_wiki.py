#!/usr/bin/env python3
"""Create and release a complete empty wiki without exposing a lock token."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import portable_io
from typing import Any
from uuid import uuid4

from wiki_lock import acquire_lock, release_owned_lock


class InitializationFailure(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


def run_json(stage: str, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "helper failed").strip().splitlines()
        raise InitializationFailure(stage, detail[-1] if detail else "helper failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise InitializationFailure(stage, "helper returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise InitializationFailure(stage, "helper returned an invalid result")
    return value


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with source.open("rb") as input_handle, os.fdopen(descriptor, "wb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        portable_io.replace_with_retry(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def publish_staged_wiki(staging: Path, target: Path) -> list[Path]:
    created: list[Path] = []
    try:
        directories = sorted(
            (path for path in staging.rglob("*") if path.is_dir()),
            key=lambda path: len(path.relative_to(staging).parts),
        )
        for source in directories:
            destination = target / source.relative_to(staging)
            if destination.exists():
                if not destination.is_dir():
                    raise InitializationFailure(
                        "commit",
                        f"Target changed during initialization: {source.relative_to(staging).as_posix()}",
                    )
                continue
            destination.mkdir()
            created.append(destination)
        for source in sorted(path for path in staging.rglob("*") if path.is_file() and path.name != ".llmwiki.lock"):
            relative = source.relative_to(staging)
            destination = target / relative
            if destination.exists():
                raise InitializationFailure("commit", f"Target changed during initialization: {relative.as_posix()}")
            atomic_copy(source, destination)
            created.append(destination)
    except Exception:
        rollback_created(created, target)
        raise
    return created


def rollback_created(paths: list[Path], target: Path) -> None:
    for path in reversed(paths):
        try:
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    directories = sorted(
        {parent for path in paths for parent in path.parents if parent != target and target in parent.parents},
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--title", help="Human-readable title; normally supplied explicitly")
    parser.add_argument("--topic", required=True, help="Short topic and scope boundary")
    parser.add_argument("--wiki-language", required=True)
    parser.add_argument("--wiki-language-label")
    parser.add_argument("--quality-review-days", type=int, default=30)
    parser.add_argument("--cleaning-review-days", type=int, default=90)
    parser.add_argument("--snapshot-warning-days", type=int, default=60)
    parser.add_argument("--identity-plan", required=True, help="Confirmed identity proposal JSON")
    parser.add_argument("--expect-identity-sha256", required=True)
    parser.add_argument("--owner", default="initialize-wiki", help="Public agent or run label")
    parser.add_argument("--summary", default="Initialize portable SkillSafeWerkstatt")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    record, token, _ = acquire_lock(target, args.owner, "initialize")
    released_lock = False
    stage = "preflight"
    committed_paths: list[Path] = []
    try:
        if (target / "WIKI.md").exists():
            raise InitializationFailure(
                stage,
                "Target is already an initialized wiki; use the maintenance workflow.",
            )
        unexpected = [path.name for path in target.iterdir() if path.name != ".llmwiki.lock"]
        if unexpected:
            raise InitializationFailure(stage, f"Target is not empty: {sorted(unexpected)}")
        scripts = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(prefix="lmwiki-initialize-", dir=str(target.parent)) as temporary:
            staged_target = Path(temporary) / "wiki"
            staged_target.mkdir()
            shutil.copyfile(target / ".llmwiki.lock", staged_target / ".llmwiki.lock")
            init_command = [
                sys.executable,
                str(scripts / "init_wiki.py"),
                "--target", str(staged_target),
                "--lock-token", token,
                "--topic", args.topic,
                "--wiki-language", args.wiki_language,
                "--quality-review-days", str(args.quality_review_days),
                "--cleaning-review-days", str(args.cleaning_review_days),
                "--snapshot-warning-days", str(args.snapshot_warning_days),
                "--identity-plan", args.identity_plan,
                "--expect-identity-sha256", args.expect_identity_sha256,
            ]
            if args.title:
                init_command.extend(("--title", args.title))
            if args.wiki_language_label:
                init_command.extend(("--wiki-language-label", args.wiki_language_label))
            initialized = run_json("initialize", init_command)
            graph = run_json(
                "graph",
                [
                    sys.executable, str(scripts / "build_graph.py"),
                    "--target", str(staged_target), "--lock-token", token,
                ],
            )
            lint = run_json(
                "lint",
                [
                    sys.executable, str(scripts / "lint_wiki.py"),
                    "--target", str(staged_target), "--lock-token", token, "--fix-safe",
                ],
            )
            released = run_json(
                "release",
                [
                    sys.executable, str(scripts / "release_wiki.py"),
                    "--target", str(staged_target), "--lock-token", token,
                    "--bump", "minor", "--summary", args.summary,
                    "--operation-id", f"initialize-{record.get('lock_id', '')}",
                    "--expect-current-version", "0.0.0",
                ],
            )
            stage = "commit"
            committed_paths = publish_staged_wiki(staged_target, target)
        public_lock = release_owned_lock(target, token)
        released_lock = True
        print(json.dumps({
            "state": "initialized",
            "target": ".",
            "title": initialized.get("title", ""),
            "title_source": initialized.get("title_source", ""),
            "identity_proposal_sha256": initialized.get("identity_proposal_sha256", ""),
            "created": initialized.get("created", []),
            "graph": {
                "output": graph.get("output", "graph/index.html"),
                "nodes": graph.get("nodes", 0),
                "links": graph.get("links", 0),
            },
            "lint_valid": bool(lint.get("valid")),
            "version": released.get("version", ""),
            "release_id": released.get("release_id", ""),
            "manifest": released.get("manifest", "meta/manifest.json"),
            "manifest_sha256": released.get("manifest_sha256", ""),
            "lock_released": True,
            "lock_id": public_lock.get("lock_id", record.get("lock_id", "")),
        }, ensure_ascii=False, indent=2))
        return 0
    except InitializationFailure as exc:
        stage = exc.stage
        if committed_paths:
            rollback_created(committed_paths, target)
        try:
            release_owned_lock(target, token)
            released_lock = True
        except (OSError, SystemExit):
            released_lock = False
        print(json.dumps({
            "state": "initialization_failed",
            "stage": stage,
            "error": str(exc),
            "target": ".",
            "partial_state_preserved": False,
            "lock_released": released_lock,
        }, ensure_ascii=False, indent=2))
        return 4
    except (OSError, ValueError) as exc:
        if committed_paths:
            rollback_created(committed_paths, target)
        try:
            release_owned_lock(target, token)
            released_lock = True
        except (OSError, SystemExit):
            released_lock = False
        print(json.dumps({
            "state": "initialization_failed",
            "stage": stage,
            "error": str(exc),
            "target": ".",
            "partial_state_preserved": False,
            "lock_released": released_lock,
        }, ensure_ascii=False, indent=2))
        return 4
    finally:
        if not released_lock:
            try:
                release_owned_lock(target, token)
            except (OSError, SystemExit):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
