#!/usr/bin/env python3
"""Acquire, inspect, force-override, or release the cooperative SkillSafeWerkstatt lock."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


LOCK_NAME = ".llmwiki.lock"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def lock_path(target: Path) -> Path:
    return target / LOCK_NAME


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_lock(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "token_sha256"}


def read_lock(target: Path) -> dict[str, Any]:
    path = lock_path(target)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError("Wiki lock is missing")
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Wiki lock is unreadable: {exc}")
    if not isinstance(record, dict) or not record.get("lock_id") or not record.get("token_sha256"):
        raise RuntimeError("Wiki lock has an invalid schema")
    return record


def require_lock(target: Path, token: str) -> dict[str, Any]:
    """Require ownership of the current lock before a wiki process starts."""
    if not token:
        raise SystemExit("--lock-token is required; acquire the wiki lock first")
    try:
        record = read_lock(target)
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    if not hmac.compare_digest(str(record["token_sha256"]), token_hash(token)):
        owner = record.get("owner", "unknown")
        acquired = record.get("acquired_at", "unknown")
        raise SystemExit(f"Wiki is locked by {owner} since {acquired}; refusing to start")
    return record


def write_exclusive(path: Path, record: dict[str, Any]) -> None:
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def replace_atomically(path: Path, record: dict[str, Any]) -> None:
    temporary = path.with_name(f"{LOCK_NAME}.{uuid4().hex}.tmp")
    write_exclusive(temporary, record)
    try:
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def write_private_token(path: Path, target: Path, token: str) -> None:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(target.expanduser().resolve())
    except ValueError:
        pass
    else:
        raise SystemExit("The runtime token file must stay outside the target wiki")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(resolved), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            resolved.unlink()
        except OSError:
            pass
        raise


def token_from_args(args: argparse.Namespace) -> str:
    direct = str(getattr(args, "lock_token", "") or "")
    token_file = str(getattr(args, "token_file", "") or "")
    if bool(direct) == bool(token_file):
        raise SystemExit("Provide exactly one of --lock-token or --token-file")
    if direct:
        return direct
    try:
        return Path(token_file).expanduser().resolve().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SystemExit(f"Runtime token file is unavailable: {exc}") from exc


def acquire_lock(
    target: Path,
    owner: str,
    operation: str,
    force: bool = False,
    reason: str = "",
) -> tuple[dict[str, Any], str, Optional[dict[str, Any]]]:
    """Acquire a lock without exposing its private token on standard output."""
    target = target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    path = lock_path(target)
    # A raw urlsafe token can begin with "-", which some argparse versions
    # mistake for another option when helpers receive it as a separate value.
    # The stable alphanumeric prefix keeps the private token CLI-safe without
    # weakening its random component.
    token = "lk_" + secrets.token_urlsafe(32)
    record = {
        "format_version": 1,
        "lock_id": str(uuid4()),
        "token_sha256": token_hash(token),
        "owner": owner.strip(),
        "operation": operation.strip(),
        "acquired_at": utc_now(),
        "host": socket.gethostname(),
        "forced": bool(force),
    }
    if not record["owner"]:
        raise SystemExit("--owner must not be empty")
    if not record["operation"]:
        raise SystemExit("--operation must not be empty")
    previous: Optional[dict[str, Any]] = None
    if force:
        if not reason or not reason.strip():
            raise SystemExit("--force requires a non-empty --reason")
        record["override_reason"] = reason.strip()
        if path.exists():
            try:
                previous = public_lock(read_lock(target))
            except RuntimeError as exc:
                previous = {"invalid_lock": str(exc)}
        replace_atomically(path, record)
    else:
        try:
            write_exclusive(path, record)
        except FileExistsError:
            try:
                current = public_lock(read_lock(target))
            except RuntimeError as exc:
                current = {"invalid_lock": str(exc)}
            raise SystemExit(
                json.dumps(
                    {
                        "acquired": False,
                        "error": "wiki is already locked",
                        "lock": current,
                        "override_hint": "Use acquire --force --reason only after explicit user approval.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    return record, token, previous


def release_owned_lock(target: Path, token: str) -> dict[str, Any]:
    """Release a lock owned by token and return only public metadata."""
    target = target.expanduser().resolve()
    record = require_lock(target, token)
    lock_path(target).unlink()
    return public_lock(record)


def acquire(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    record, token, previous = acquire_lock(
        target,
        args.owner,
        args.operation,
        force=bool(args.force),
        reason=args.reason or "",
    )
    token_path = Path(args.token_file).expanduser().resolve()
    try:
        write_private_token(token_path, target, token)
    except Exception:
        try:
            release_owned_lock(target, token)
        except (OSError, SystemExit):
            pass
        raise
    result: dict[str, Any] = {
        "acquired": True,
        "lock_file": LOCK_NAME,
        "lock_id": record["lock_id"],
        "token_file_written": True,
        "owner": record["owner"],
        "operation": record["operation"],
        "forced": record["forced"],
    }
    if previous is not None:
        result["overridden_lock"] = previous
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def status(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    if not lock_path(target).exists():
        print(json.dumps({"locked": False, "lock_file": LOCK_NAME}, ensure_ascii=False, indent=2))
        return 0
    try:
        record = public_lock(read_lock(target))
        result = {"locked": True, "lock_file": LOCK_NAME, "lock": record}
    except RuntimeError as exc:
        result = {"locked": True, "lock_file": LOCK_NAME, "invalid_lock": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def release(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    token = token_from_args(args)
    record = release_owned_lock(target, token)
    token_file = str(getattr(args, "token_file", "") or "")
    if token_file and args.remove_token_file:
        try:
            Path(token_file).expanduser().resolve().unlink()
        except FileNotFoundError:
            pass
    print(
        json.dumps(
            {
                "released": True,
                "lock_file": LOCK_NAME,
                "lock_id": record["lock_id"],
                "owner": record.get("owner", ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def verify(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    record = require_lock(target, token_from_args(args))
    print(
        json.dumps(
            {
                "owned": True,
                "lock_file": LOCK_NAME,
                "lock": public_lock(record),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire_parser = subparsers.add_parser("acquire", help="Create the lock atomically")
    acquire_parser.add_argument("--target", required=True)
    acquire_parser.add_argument("--owner", required=True, help="Agent or run identifier")
    acquire_parser.add_argument("--operation", default="maintain", help="Short operation description")
    acquire_parser.add_argument("--token-file", required=True, help="Private runtime file outside the wiki")
    acquire_parser.add_argument("--force", action="store_true", help="Atomically override an existing lock")
    acquire_parser.add_argument("--reason", help="Required explanation for --force")
    acquire_parser.set_defaults(handler=acquire)

    status_parser = subparsers.add_parser("status", help="Show the current public lock metadata")
    status_parser.add_argument("--target", required=True)
    status_parser.set_defaults(handler=status)

    verify_parser = subparsers.add_parser("verify", help="Verify ownership with the private token")
    verify_parser.add_argument("--target", required=True)
    verify_group = verify_parser.add_mutually_exclusive_group(required=True)
    verify_group.add_argument("--lock-token")
    verify_group.add_argument("--token-file")
    verify_parser.set_defaults(handler=verify)

    release_parser = subparsers.add_parser("release", help="Release the owned lock")
    release_parser.add_argument("--target", required=True)
    release_group = release_parser.add_mutually_exclusive_group(required=True)
    release_group.add_argument("--lock-token")
    release_group.add_argument("--token-file")
    release_parser.add_argument("--remove-token-file", action="store_true")
    release_parser.set_defaults(handler=release)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
