#!/usr/bin/env python3
"""Apply one confirmed identity proposal to an initialized wiki."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from identity_contract import IdentityError, load_plan
from snapshot_wiki import create_snapshot
from wiki_lock import require_lock


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True)
    parser.add_argument("--plan-file", required=True)
    parser.add_argument("--expect-proposal-sha256", required=True)
    parser.add_argument("--confirm-replace", action="store_true")
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    try:
        plan = load_plan(Path(args.plan_file), args.expect_proposal_sha256)
    except IdentityError as exc:
        raise SystemExit(str(exc)) from exc
    paths = (target / "SOUL.md", target / "schema/CONTENT_POLICY.md")
    if any(path.exists() for path in paths) and not args.confirm_replace:
        raise SystemExit("identity files already exist; confirmed replacement requires --confirm-replace")
    snapshot = create_snapshot(
        target,
        args.lock_token,
        operation="apply-confirmed-identity",
        selected_files=("SOUL.md", "schema/CONTENT_POLICY.md"),
    )
    atomic_write(paths[0], str(plan["soul_markdown"]))
    atomic_write(paths[1], str(plan["content_policy_markdown"]))
    print(json.dumps({
        "state": "identity_applied",
        "proposal_sha256": plan["proposal_sha256"],
        "files": ["SOUL.md", "schema/CONTENT_POLICY.md"],
        "snapshot": snapshot,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
