#!/usr/bin/env python3
"""Atomic writes that survive a synchronization client holding a handle.

On Windows a sync client or an antivirus scanner briefly opens files it is
uploading, and the rename that completes an atomic write then fails with a
sharing violation. The operation is not wrong, only early, so a bounded retry
turns a spurious failure into a short wait.

Retries are deliberately few and short: they cover a transient handle, never a
genuine permission problem, and never a lock the wiki contract cares about.
"""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path
from typing import Callable, TypeVar
from uuid import uuid4


#: Windows sharing-violation and access-denied codes seen from sync clients.
_WINDOWS_SHARING = frozenset({32, 33, 5})

#: Bounded backoff in seconds. Four attempts in total, under a second overall.
RETRY_DELAYS = (0.05, 0.15, 0.4)

T = TypeVar("T")


class TransientStorageError(OSError):
    """Raised when a storage operation kept failing for a transient reason."""


def _is_transient(exc: OSError) -> bool:
    """True for errors a synchronization client or scanner causes briefly."""
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror in _WINDOWS_SHARING:
        return True
    return exc.errno in {errno.EACCES, errno.EBUSY, errno.ETXTBSY}


def with_retry(operation: Callable[[], T], *, what: str) -> T:
    """Run one filesystem operation, retrying only transient storage failures."""
    last: OSError
    for delay in (*RETRY_DELAYS, None):
        try:
            return operation()
        except OSError as exc:
            if not _is_transient(exc) or delay is None:
                if _is_transient(exc):
                    raise TransientStorageError(
                        f"{what} kept failing because another process holds the file. "
                        "A synchronization client or virus scanner is the usual cause; "
                        f"retry once it releases the handle. Last error: {exc}"
                    ) from exc
                raise
            last = exc
            time.sleep(delay)
    raise last  # pragma: no cover - the loop always returns or raises


def replace_with_retry(source: Path, destination: Path) -> None:
    """Rename `source` onto `destination`, retrying a transient sharing violation."""
    with_retry(
        lambda: os.replace(str(source), str(destination)),
        what=f"replacing {destination.name}",
    )


def atomic_write_bytes(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    """Write `content` to `path` atomically, durably, and with a bounded retry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))
