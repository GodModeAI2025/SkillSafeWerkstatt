#!/usr/bin/env python3
"""Append one explicit quality or cleaning review under the owned wiki lock."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from wiki_lock import require_lock


KINDS = ("quality", "cleaning")
OUTCOMES = ("passed", "attention-needed", "not-applicable")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--outcome", choices=OUTCOMES, required=True)
    parser.add_argument("--summary", required=True, help="One-line factual review summary")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    lock = require_lock(target, args.lock_token)
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    summary = " ".join(args.summary.split())
    if not summary or len(summary) > 500:
        raise SystemExit("summary must contain 1 to 500 characters on one line")
    if re.search(r"(?:^|\s)(?:file:|~[/\\]|/\S|[A-Za-z]:[/\\])", summary, re.IGNORECASE):
        raise SystemExit("summary must not contain an absolute, home-relative, or file URL path")

    path = target / "meta/quality-reviews.jsonl"
    existing = path.read_bytes() if path.is_file() else b""
    if existing and not existing.endswith(b"\n"):
        existing += b"\n"
    record = {
        "format": "lmwiki-quality-review/1",
        "review_id": str(uuid4()),
        "kind": args.kind,
        "reviewed_at": utc_now(),
        "outcome": args.outcome,
        "summary": summary,
        "reviewer": str(lock.get("owner") or ""),
        "lock_id": str(lock.get("lock_id") or ""),
    }
    atomic_write(
        path,
        existing + json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n",
    )
    print(json.dumps({"recorded": True, "path": "meta/quality-reviews.jsonl", "review": record}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
