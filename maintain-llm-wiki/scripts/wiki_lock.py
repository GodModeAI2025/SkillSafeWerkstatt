#!/usr/bin/env python3
"""Hold, share, inspect, hand over, or release the cooperative SkillSafeWerkstatt lock.

A wiki on a SharePoint or OneDrive library is maintained by a team, not by one
machine. The lock therefore is not a single slot that a second maintainer has to
overwrite: `<target>/.llmwiki.lock` is a directory in which every maintainer owns
exactly one file, `claim-<maintainer>.json`, and writes only that one.

That layout is chosen for the storage, not for elegance. A synchronization client
offers no compare-and-swap: two devices that write the same path produce a lost
update or a conflict copy, and the loser finds out only after it has already
changed the wiki. Two devices that write two different paths produce two files,
which is a fact both sides can see and act on.

Arbitration over the visible claims is deterministic and fail-closed:

* exactly one effective claim, and it is mine -> I may write;
* two effective claims -> nobody writes, because a synchronized folder cannot
  tell "I am alone" apart from "the other claim has not arrived yet";
* a conflict copy of a claim, an unreadable claim, or a timestamp from the
  future -> nobody writes, because the evidence itself is broken.

A lease makes an abandoned claim recoverable without a forced eviction, but age
alone never grants ownership: taking over is a two-step, recorded protocol with a
settle window, so the other maintainer has a visible chance to object.

A wiki that still carries the single-file lock of format 1 keeps working. It is
read as one legacy claim, it never expires, and only its own token or an approved
force acquisition clears it.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
from datetime import datetime, timezone
from pathlib import Path

import portable_io
import sync_artifacts
from typing import Any, Optional
from uuid import uuid4


#: The lock is a directory in format 2 and a plain file in legacy format 1.
LOCK_NAME = ".llmwiki.lock"

CLAIM_PREFIX = "claim-"
CLAIM_SUFFIX = ".json"
CLAIM_FORMAT = "lmwiki-lock-claim/1"

#: How long a claim stays valid without a heartbeat. Every locked helper call
#: refreshes it, so the lease only ever runs out on an abandoned run.
DEFAULT_LEASE_SECONDS = 3600
MINIMUM_LEASE_SECONDS = 60
MAXIMUM_LEASE_SECONDS = 86400

#: Added to every lease before a foreign claim may be called expired. A
#: synchronized folder delivers a heartbeat late; that is not an abandoned run.
SYNC_GRACE_SECONDS = 900

#: How long a declared takeover must be visible before it takes effect.
DEFAULT_SETTLE_SECONDS = 900
MINIMUM_SETTLE_SECONDS = 60


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def epoch_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def parse_timestamp(value: Any) -> Optional[float]:
    """Parse one recorded UTC timestamp, or None when it is unusable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def lock_path(target: Path) -> Path:
    return target / LOCK_NAME


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def default_maintainer_id() -> str:
    """Identify the person-and-machine that holds a slot.

    A team shares one wiki, but each member curates from their own synchronized
    copy, so the slot is per person and machine rather than per person alone.
    """
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - only on hosts without any user record
        user = "unknown"
    return f"{user}@{socket.gethostname()}"


def claim_slug(maintainer_id: str) -> str:
    """A storage-safe, collision-free file-name fragment for one maintainer.

    The readable part is truncated and stripped of everything SharePoint refuses;
    the appended digest keeps two different maintainers from sharing a file even
    when their readable parts collapse to the same text.
    """
    readable = re.sub(r"[^a-z0-9]+", "-", maintainer_id.casefold()).strip("-")[:48]
    digest = hashlib.sha256(maintainer_id.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{digest}" if readable else digest


def claim_path(target: Path, maintainer_id: str) -> Path:
    return lock_path(target) / f"{CLAIM_PREFIX}{claim_slug(maintainer_id)}{CLAIM_SUFFIX}"


def public_lock(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "token_sha256"}


class Claim:
    """One maintainer's claim on the wiki, as it is visible on this machine."""

    __slots__ = ("record", "path", "legacy", "mtime")

    def __init__(self, record: dict[str, Any], path: Path, *, legacy: bool = False) -> None:
        self.record = record
        self.path = path
        self.legacy = legacy
        try:
            self.mtime = path.stat().st_mtime
        except OSError:
            self.mtime = 0.0

    @property
    def claim_id(self) -> str:
        return str(self.record.get("claim_id") or self.record.get("lock_id") or "")

    @property
    def maintainer_id(self) -> str:
        return str(self.record.get("maintainer_id") or "")

    @property
    def host(self) -> str:
        return str(self.record.get("host") or "")

    @property
    def lease_seconds(self) -> int:
        try:
            return max(0, int(self.record.get("lease_seconds", 0)))
        except (TypeError, ValueError):
            return 0

    @property
    def pending(self) -> bool:
        """True while this claim is only a declared, not yet effective, takeover."""
        return bool(self.record.get("takeover")) and not self.record.get("token_sha256")

    @property
    def supersedes(self) -> list[str]:
        values = self.record.get("supersedes")
        return [str(value) for value in values] if isinstance(values, list) else []

    def last_seen(self) -> float:
        """The most recent evidence that this claim is alive.

        The recorded heartbeat comes from the claimant's clock, the file's
        modification time from this machine's. Taking the later of the two makes
        a claim look alive whenever either says so, which is the conservative
        direction: an unnecessary wait is recoverable, a wrongly declared stale
        lock is not.
        """
        recorded = parse_timestamp(self.record.get("heartbeat_at")) or parse_timestamp(
            self.record.get("acquired_at")
        )
        return max(recorded or 0.0, self.mtime)

    def expired(self, now: Optional[float] = None) -> bool:
        if self.legacy or self.lease_seconds <= 0:
            # Format 1 knew no lease. Adopting one retroactively would expire a
            # lock the other side still believes it holds.
            return False
        now = epoch_now() if now is None else now
        return self.last_seen() + self.lease_seconds + SYNC_GRACE_SECONDS < now

    def from_the_future(self, now: Optional[float] = None) -> bool:
        now = epoch_now() if now is None else now
        recorded = parse_timestamp(self.record.get("heartbeat_at")) or parse_timestamp(
            self.record.get("acquired_at")
        )
        return recorded is not None and recorded > now + SYNC_GRACE_SECONDS

    def takeover_effective_at(self) -> Optional[float]:
        takeover = self.record.get("takeover")
        if not isinstance(takeover, dict):
            return None
        return parse_timestamp(takeover.get("effective_at"))

    def describe(self, now: Optional[float] = None) -> dict[str, Any]:
        now = epoch_now() if now is None else now
        described = public_lock(self.record)
        described["claim_file"] = self.path.name
        described["expired"] = self.expired(now)
        if self.legacy:
            described["format"] = "lmwiki-lock/1"
            described["legacy_single_slot"] = True
        if self.pending:
            described["takeover_pending"] = True
        return described


class LockState:
    """Everything this machine can currently see about the wiki's lock."""

    __slots__ = ("claims", "legacy", "conflict_copies", "unreadable", "now")

    def __init__(
        self,
        claims: list[Claim],
        legacy: Optional[Claim],
        conflict_copies: list[dict[str, Any]],
        unreadable: list[dict[str, Any]],
        now: float,
    ) -> None:
        self.claims = claims
        self.legacy = legacy
        self.conflict_copies = conflict_copies
        self.unreadable = unreadable
        self.now = now

    def all_claims(self) -> list[Claim]:
        return ([self.legacy] if self.legacy is not None else []) + self.claims

    def effective(self) -> list[Claim]:
        """Claims that currently count as holding the wiki.

        A pending takeover declaration holds nothing yet. A claim superseded by a
        live, effective takeover no longer holds anything either.
        """
        live = [claim for claim in self.all_claims() if not claim.pending]
        superseded: set[str] = set()
        for claim in live:
            if claim.expired(self.now):
                continue
            superseded.update(claim.supersedes)
        return [claim for claim in live if claim.claim_id not in superseded]

    def pending_takeovers(self) -> list[Claim]:
        return [claim for claim in self.claims if claim.pending]

    def claim_for(self, maintainer_id: str) -> Optional[Claim]:
        for claim in self.claims:
            if claim.maintainer_id == maintainer_id:
                return claim
        return None

    def problems(self) -> list[dict[str, Any]]:
        """Conditions under which no claim may be trusted at all."""
        found: list[dict[str, Any]] = list(self.conflict_copies) + list(self.unreadable)
        for claim in self.all_claims():
            if claim.from_the_future(self.now):
                found.append(
                    {
                        "problem": "clock_skew",
                        "claim_file": claim.path.name,
                        "reason": (
                            "The claim is timestamped in the future, so no lease on this wiki "
                            "can be judged. Correct the clock on the claiming machine, or "
                            "override with --force after agreeing with the team."
                        ),
                    }
                )
        return found

    def state(self) -> str:
        if self.problems():
            return "contended"
        effective = self.effective()
        if len(effective) > 1:
            return "contended"
        if effective:
            return "held"
        if self.pending_takeovers():
            return "takeover_pending"
        return "free"


def _read_record(path: Path) -> tuple[Optional[dict[str, Any]], str]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "the claim disappeared while it was being read"
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"the claim is unreadable: {exc}"
    if not isinstance(record, dict):
        return None, "the claim is not a JSON object"
    return record, ""


def _legacy_claim(path: Path) -> tuple[Optional[Claim], str]:
    record, problem = _read_record(path)
    if record is None:
        return None, problem
    if not record.get("lock_id") or not record.get("token_sha256"):
        return None, "the format-1 lock has an invalid schema"
    adopted = dict(record)
    adopted.setdefault("claim_id", record["lock_id"])
    adopted.setdefault(
        "maintainer_id",
        f"{record.get('owner') or 'unknown'}@{record.get('host') or 'unknown'}",
    )
    adopted["lease_seconds"] = 0
    return Claim(adopted, path, legacy=True), ""


def read_state(target: Path) -> LockState:
    """Collect every claim, conflict copy, and unreadable file the lock shows."""
    target = target.expanduser().resolve()
    now = epoch_now()
    claims: list[Claim] = []
    unreadable: list[dict[str, Any]] = []
    conflict_copies: list[dict[str, Any]] = []

    # A conflict copy of the whole format-1 lock sits next to it in the wiki
    # root, where nothing else ever looks. It is the visible proof that two
    # machines held the single slot at the same time.
    try:
        neighbours = sorted(path for path in target.iterdir() if path.is_file())
    except OSError:
        neighbours = []
    for path in neighbours:
        artifact = sync_artifacts.classify(path.name)
        if artifact is not None and artifact.kind == sync_artifacts.CONFLICT_COPY:
            if artifact.original == LOCK_NAME:
                conflict_copies.append(
                    {
                        "problem": "conflict_copy",
                        "path": path.name,
                        "reason": (
                            "A synchronization client kept a second copy of the single-slot "
                            "lock, so two machines held it at once. Compare both records and "
                            "remove the copy after agreeing with the team."
                        ),
                    }
                )

    root = lock_path(target)
    legacy: Optional[Claim] = None
    if root.is_file():
        legacy, problem = _legacy_claim(root)
        if legacy is None:
            unreadable.append({"problem": "unreadable_claim", "path": LOCK_NAME, "reason": problem})
    elif root.is_dir():
        try:
            entries = sorted(path for path in root.iterdir() if path.is_file())
        except OSError as exc:  # pragma: no cover - unreadable lock directory
            entries = []
            unreadable.append(
                {"problem": "unreadable_claim", "path": LOCK_NAME, "reason": str(exc)}
            )
        for path in entries:
            artifact = sync_artifacts.classify(path.name)
            if artifact is not None and artifact.kind == sync_artifacts.CONFLICT_COPY:
                conflict_copies.append(
                    {
                        "problem": "conflict_copy",
                        "path": f"{LOCK_NAME}/{path.name}",
                        "reason": (
                            "Two machines wrote the same claim file, so one maintainer "
                            "identity was used twice at once. The maintainer it belongs to "
                            "resolves it with 'withdraw'."
                        ),
                    }
                )
                continue
            if artifact is not None and artifact.ignorable:
                continue
            if not (path.name.startswith(CLAIM_PREFIX) and path.name.endswith(CLAIM_SUFFIX)):
                continue
            record, problem = _read_record(path)
            if record is None:
                unreadable.append(
                    {
                        "problem": "unreadable_claim",
                        "path": f"{LOCK_NAME}/{path.name}",
                        "reason": problem,
                    }
                )
                continue
            if record.get("format") != CLAIM_FORMAT or not record.get("claim_id"):
                unreadable.append(
                    {
                        "problem": "unreadable_claim",
                        "path": f"{LOCK_NAME}/{path.name}",
                        "reason": f"unsupported claim format {record.get('format')!r}",
                    }
                )
                continue
            claims.append(Claim(record, path))
    return LockState(claims, legacy, conflict_copies, unreadable, now)


def read_lock(target: Path) -> dict[str, Any]:
    """The single effective claim, for callers that expect one holder."""
    state = read_state(target)
    problems = state.problems()
    if problems:
        raise RuntimeError(f"Wiki lock is contended: {json.dumps(problems, ensure_ascii=False)}")
    effective = state.effective()
    if not effective:
        raise RuntimeError("Wiki lock is missing")
    if len(effective) > 1:
        raise RuntimeError(
            "Wiki lock is held by several maintainers at once: "
            + ", ".join(sorted(claim.maintainer_id for claim in effective))
        )
    return effective[0].record


def refuse(payload: dict[str, Any]) -> "SystemExit":
    return SystemExit(json.dumps(payload, ensure_ascii=False, indent=2))


def _contention_report(state: LockState, **extra: Any) -> dict[str, Any]:
    problems = state.problems()
    report: dict[str, Any] = {
        "acquired": False,
        "state": "contended",
        "error": "the wiki lock cannot be trusted right now",
        "claims": [claim.describe(state.now) for claim in state.all_claims()],
    }
    if problems:
        report["problems"] = problems
    else:
        report["holders"] = [claim.describe(state.now) for claim in state.effective()]
    return {
        **report,
        "resolution": (
            "No maintainer may write while the lock is contended. Agree who continues, let "
            "everyone else run 'wiki_lock.py withdraw' on their own machine, and only then "
            "acquire again. 'acquire --force --reason' remains available after explicit user "
            "approval."
        ),
        **extra,
    }


def _held_report(state: LockState, holders: list[Claim], **extra: Any) -> dict[str, Any]:
    return {
        "acquired": False,
        "state": "held",
        "error": "wiki is already locked",
        "lock": holders[0].describe(state.now) if holders else {},
        "holders": [claim.describe(state.now) for claim in holders],
        "pending_takeovers": [claim.describe(state.now) for claim in state.pending_takeovers()],
        "override_hint": (
            "Use acquire --take-over --reason once every holder's lease has run out, or "
            "acquire --force --reason only after explicit user approval."
        ),
        **extra,
    }


def write_exclusive(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    body = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    portable_io.atomic_write_text(path, body)


def _write_claim(path: Path, record: dict[str, Any], *, replace: bool) -> None:
    if replace:
        replace_atomically(path, record)
    else:
        write_exclusive(path, record)


def discard_empty_lock(target: Path) -> dict[str, Any]:
    """Remove the lock directory once it holds no claim, so readers unblock.

    Readers treat the mere presence of `.llmwiki.lock` as "maintenance running".
    A directory that outlives its last claim would therefore take the wiki
    offline for everybody, so the operating-system noise a file browser leaves
    inside it is cleared away with it. Nothing outside the lock is touched.
    """
    root = lock_path(target)
    if not root.is_dir():
        return {"removed": not root.exists()}
    try:
        entries = list(root.iterdir())
    except OSError as exc:  # pragma: no cover - unreadable lock directory
        return {"removed": False, "reason": str(exc)}
    remaining = [
        path
        for path in entries
        if path.name.startswith(CLAIM_PREFIX) and path.name.endswith(CLAIM_SUFFIX)
    ]
    if remaining:
        return {"removed": False, "claims": len(remaining)}
    for path in entries:
        artifact = sync_artifacts.classify(path.name)
        if artifact is not None and artifact.ignorable:
            try:
                path.unlink()
            except OSError:
                pass
    try:
        root.rmdir()
    except OSError as exc:
        return {
            "removed": False,
            "reason": (
                f"The lock directory still holds files this helper must not delete ({exc}). "
                "Readers keep reporting wiki_busy until it is empty; inspect it before "
                "removing anything."
            ),
        }
    return {"removed": True}


def clear_conflict_copies(target: Path, state: "LockState") -> list[dict[str, Any]]:
    """Remove the lock's conflict copies, preserving what they contained.

    Only an explicitly approved force acquisition reaches this. Leaving the
    copies would keep the wiki contended with no way out, and deleting them
    silently would destroy the only record that two machines held the lock at
    once, so each file's digest and public content travel into the result the
    maintainer reports.
    """
    cleared: list[dict[str, Any]] = []
    for entry in state.conflict_copies:
        path = target / entry["path"]
        try:
            content = path.read_bytes()
        except OSError:
            continue
        removed: dict[str, Any] = {
            "path": entry["path"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        try:
            removed["content"] = public_lock(json.loads(content.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            removed["content"] = None
        try:
            path.unlink()
        except OSError:
            continue
        cleared.append(removed)
    return cleared


def copy_lock(target: Path, destination: Path) -> None:
    """Mirror the current lock into a staging directory, file or directory alike."""
    source = lock_path(target)
    if source.is_dir():
        mirror = lock_path(destination)
        mirror.mkdir(parents=True, exist_ok=True)
        for path in source.iterdir():
            if path.is_file():
                portable_io.atomic_write_bytes(mirror / path.name, path.read_bytes())
    elif source.is_file():
        portable_io.atomic_write_bytes(lock_path(destination), source.read_bytes())


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


def _matching_claim(state: LockState, token: str) -> Optional[Claim]:
    digest = token_hash(token)
    for claim in state.all_claims():
        recorded = claim.record.get("token_sha256")
        if isinstance(recorded, str) and hmac.compare_digest(recorded, digest):
            return claim
    return None


def _refresh_heartbeat(claim: Claim) -> bool:
    """Extend one's own lease. Best effort: ownership never depends on it."""
    if claim.legacy:
        return False
    record = dict(claim.record)
    record["heartbeat_at"] = utc_now()
    try:
        replace_atomically(claim.path, record)
    except OSError:
        return False
    claim.record = record
    return True


def require_lock(target: Path, token: str) -> dict[str, Any]:
    """Require sole, current ownership before a wiki process starts or writes."""
    if not token:
        raise SystemExit("--lock-token is required; acquire the wiki lock first")
    target = Path(target).expanduser().resolve()
    state = read_state(target)
    problems = state.problems()
    if problems:
        raise refuse(_contention_report(state, error="refusing to start while the lock is contended"))
    mine = _matching_claim(state, token)
    if mine is None:
        holders = state.effective()
        if not holders:
            raise SystemExit("Wiki lock is missing")
        # The historical wording is kept: it is what an interrupted run reports.
        owner = holders[0].record.get("owner", "unknown")
        acquired = holders[0].record.get("acquired_at", "unknown")
        if len(holders) == 1:
            raise SystemExit(f"Wiki is locked by {owner} since {acquired}; refusing to start")
        raise refuse(_contention_report(state))
    effective = state.effective()
    if mine.claim_id not in {claim.claim_id for claim in effective}:
        taking_over = [
            claim.describe(state.now)
            for claim in effective
            if mine.claim_id in claim.supersedes
        ]
        raise refuse(
            {
                "acquired": False,
                "state": "superseded",
                "error": "this claim was handed over to another maintainer",
                "claim": mine.describe(state.now),
                "taken_over_by": taking_over,
                "resolution": (
                    "Stop writing. Verify what the other maintainer changed, then acquire the "
                    "lock again before continuing."
                ),
            }
        )
    if len(effective) > 1:
        raise refuse(_contention_report(state, error="refusing to write while two claims are effective"))
    refreshed = _refresh_heartbeat(mine)
    record = dict(mine.record)
    record["heartbeat_refreshed"] = refreshed
    return record


def acquire_lock(
    target: Path,
    owner: str,
    operation: str,
    force: bool = False,
    reason: str = "",
    *,
    maintainer: str = "",
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    take_over: bool = False,
    settle_seconds: int = DEFAULT_SETTLE_SECONDS,
) -> tuple[dict[str, Any], str, Optional[dict[str, Any]]]:
    """Acquire a claim without exposing its private token on standard output."""
    target = Path(target).expanduser().resolve()
    owner = owner.strip()
    operation = operation.strip()
    if not owner:
        raise SystemExit("--owner must not be empty")
    if not operation:
        raise SystemExit("--operation must not be empty")
    lease_seconds = int(lease_seconds)
    if not MINIMUM_LEASE_SECONDS <= lease_seconds <= MAXIMUM_LEASE_SECONDS:
        raise SystemExit(
            f"--lease-seconds must lie between {MINIMUM_LEASE_SECONDS} and {MAXIMUM_LEASE_SECONDS}"
        )
    settle_seconds = int(settle_seconds)
    if settle_seconds < MINIMUM_SETTLE_SECONDS:
        raise SystemExit(f"--settle-seconds must be at least {MINIMUM_SETTLE_SECONDS}")
    if force and not reason.strip():
        raise SystemExit("--force requires a non-empty --reason")
    if take_over and not reason.strip():
        raise SystemExit("--take-over requires a non-empty --reason")
    if force and take_over:
        raise SystemExit("Use either --take-over or --force, not both")

    target.mkdir(parents=True, exist_ok=True)
    maintainer_id = maintainer.strip() or default_maintainer_id()
    state = read_state(target)
    problems = state.problems()
    if problems and not force:
        raise refuse(_contention_report(state))

    effective = state.effective()
    mine = state.claim_for(maintainer_id)
    others = [
        claim
        for claim in effective
        if claim.maintainer_id != maintainer_id or claim.legacy
    ]
    superseded: list[dict[str, Any]] = []

    cleared: list[dict[str, Any]] = []
    if force:
        superseded = [claim.describe(state.now) for claim in effective]
        cleared = clear_conflict_copies(target, state)
        if state.legacy is not None:
            # Format 1 occupies the path the claim directory needs.
            try:
                lock_path(target).unlink()
            except OSError as exc:
                raise SystemExit(f"The format-1 lock could not be replaced: {exc}")
    elif take_over:
        return _take_over(
            target, state, maintainer_id, owner, operation, reason, lease_seconds, settle_seconds
        )
    elif others:
        raise refuse(_held_report(state, others))
    elif mine is not None and not mine.pending and not mine.expired(state.now):
        raise refuse(
            _held_report(
                state,
                [mine],
                error="this machine already holds a live claim on the wiki",
                override_hint=(
                    "A run on this machine still owns the wiki. Let it finish, or run "
                    "'wiki_lock.py withdraw --reason ...' here if it was abandoned."
                ),
            )
        )

    token = "lk_" + secrets.token_urlsafe(32)
    record = _new_claim_record(
        maintainer_id, owner, operation, lease_seconds, token=token, forced=force
    )
    if force:
        record["override_reason"] = reason.strip()
        record["supersedes"] = sorted(
            {claim.claim_id for claim in effective if claim.claim_id and claim.maintainer_id != maintainer_id}
        )
    path = claim_path(target, maintainer_id)
    _write_claim(path, record, replace=path.exists())
    previous: Optional[dict[str, Any]] = None
    if superseded or cleared:
        previous = {"superseded": superseded}
        if cleared:
            previous["cleared_conflict_copies"] = cleared
    return record, token, previous


def _new_claim_record(
    maintainer_id: str,
    owner: str,
    operation: str,
    lease_seconds: int,
    *,
    token: str = "",
    forced: bool = False,
) -> dict[str, Any]:
    moment = utc_now()
    record: dict[str, Any] = {
        "format": CLAIM_FORMAT,
        "format_version": 2,
        "claim_id": str(uuid4()),
        "lock_id": "",
        "maintainer_id": maintainer_id,
        "owner": owner,
        "operation": operation,
        "acquired_at": moment,
        "heartbeat_at": moment,
        "lease_seconds": lease_seconds,
        "host": socket.gethostname(),
        "forced": bool(forced),
    }
    # `lock_id` is retained so a format-1 reader still finds the field it knows.
    record["lock_id"] = record["claim_id"]
    if token:
        record["token_sha256"] = token_hash(token)
    return record


def _take_over(
    target: Path,
    state: LockState,
    maintainer_id: str,
    owner: str,
    operation: str,
    reason: str,
    lease_seconds: int,
    settle_seconds: int,
) -> tuple[dict[str, Any], str, Optional[dict[str, Any]]]:
    """Run the two-step handover of an abandoned claim.

    Step one records the intention and does nothing else. Step two, after the
    settle window, promotes it only if every claim it supersedes is still
    expired. Age alone therefore never takes a wiki away from anybody: the
    other maintainer only has to come back and heartbeat once.
    """
    effective = state.effective()
    holders = [claim for claim in effective if claim.maintainer_id != maintainer_id]
    mine = state.claim_for(maintainer_id)
    live = [claim for claim in holders if not claim.expired(state.now)]

    if mine is not None and mine.pending:
        declared = set(mine.supersedes)
        effective_at = mine.takeover_effective_at() or 0.0
        if live or not declared.issubset({claim.claim_id for claim in holders}):
            try:
                mine.path.unlink()
            except OSError:
                pass
            raise refuse(
                {
                    "acquired": False,
                    "state": "takeover_void",
                    "error": "the declared takeover no longer applies",
                    "reason": (
                        "The other maintainer is active again, or the claim this takeover named "
                        "is gone. The declaration was withdrawn; acquire normally."
                    ),
                    "holders": [claim.describe(state.now) for claim in holders],
                }
            )
        if state.now < effective_at:
            raise refuse(
                {
                    "acquired": False,
                    "state": "takeover_pending",
                    "error": "the declared takeover has not settled yet",
                    "effective_at": (mine.record.get("takeover") or {}).get("effective_at", ""),
                    "seconds_remaining": int(effective_at - state.now),
                    "declaration": mine.describe(state.now),
                    "holders": [claim.describe(state.now) for claim in holders],
                    "resolution": (
                        "The window exists so the other maintainer can see the takeover and "
                        "object. Re-run the same command once it has passed."
                    ),
                }
            )
        token = "lk_" + secrets.token_urlsafe(32)
        record = _new_claim_record(maintainer_id, owner, operation, lease_seconds, token=token)
        record["acquired_at"] = mine.record.get("acquired_at", record["acquired_at"])
        record["supersedes"] = sorted(declared)
        record["takeover_reason"] = reason.strip()
        replace_atomically(mine.path, record)
        return record, token, {"superseded": [claim.describe(state.now) for claim in holders]}

    if not holders:
        raise refuse(
            {
                "acquired": False,
                "state": "free",
                "error": "there is nothing to take over",
                "resolution": "Acquire the lock normally.",
            }
        )
    if live:
        raise refuse(
            _held_report(
                state,
                live,
                error="a holder's lease has not run out, so it cannot be taken over",
                override_hint=(
                    "Wait for the lease to expire, or use acquire --force --reason after "
                    "explicit user approval."
                ),
            )
        )
    declaration = _new_claim_record(maintainer_id, owner, operation, lease_seconds)
    declaration.pop("token_sha256", None)
    declaration["supersedes"] = sorted({claim.claim_id for claim in holders if claim.claim_id})
    declaration["takeover"] = {
        "declared_at": declaration["acquired_at"],
        "settle_seconds": settle_seconds,
        "effective_at": datetime.fromtimestamp(state.now + settle_seconds, timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "reason": reason.strip(),
    }
    path = claim_path(target, maintainer_id)
    _write_claim(path, declaration, replace=path.exists())
    raise refuse(
        {
            "acquired": False,
            "state": "takeover_declared",
            "declaration": Claim(declaration, path).describe(state.now),
            "holders": [claim.describe(state.now) for claim in holders],
            "effective_at": declaration["takeover"]["effective_at"],
            "resolution": (
                "The intention is now recorded in the wiki, where the other maintainer can see "
                "it. Nothing is locked yet. Re-run the same command after the settle window to "
                "complete the handover; if the other maintainer returns in the meantime, the "
                "declaration is withdrawn automatically."
            ),
        }
    )


def release_owned_lock(target: Path, token: str) -> dict[str, Any]:
    """Release one's own claim and return only public metadata."""
    target = Path(target).expanduser().resolve()
    state = read_state(target)
    mine = _matching_claim(state, token)
    if mine is None:
        effective = state.effective()
        if not effective:
            raise SystemExit("Wiki lock is missing")
        owner = effective[0].record.get("owner", "unknown")
        acquired = effective[0].record.get("acquired_at", "unknown")
        raise SystemExit(f"Wiki is locked by {owner} since {acquired}; refusing to start")
    try:
        mine.path.unlink()
    except FileNotFoundError:
        pass
    discard_empty_lock(target)
    return public_lock(mine.record)


def describe_foreign_host(record: dict[str, Any]) -> dict[str, Any]:
    """Describe a lock that a different machine wrote.

    On a synchronized folder a released lock can linger for minutes, and an
    unreleased one can belong to a device that is currently offline. Neither is
    proof that maintenance is still running, so the caller is told what it is
    rather than being left to guess from the age alone.
    """
    holder = str(record.get("host") or "")
    if not holder or holder == socket.gethostname():
        return {}
    return {
        "foreign_host": holder,
        "note": (
            f"The lock was written by {holder!r}, not by this machine. On a synchronized "
            "folder a lock release can arrive late, so this may be a lock that no longer "
            "exists elsewhere. Confirm with the other maintainer before overriding; age "
            "alone never proves a lock is stale."
        ),
    }


def acquire(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    record, token, previous = acquire_lock(
        target,
        args.owner,
        args.operation,
        force=bool(args.force),
        reason=args.reason or "",
        maintainer=args.maintainer or "",
        lease_seconds=args.lease_seconds,
        take_over=bool(args.take_over),
        settle_seconds=args.settle_seconds,
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
        "state": "held",
        "lock_file": LOCK_NAME,
        "claim_file": f"{LOCK_NAME}/{claim_path(target, record['maintainer_id']).name}",
        "lock_id": record["claim_id"],
        "claim_id": record["claim_id"],
        "token_file_written": True,
        "maintainer_id": record["maintainer_id"],
        "owner": record["owner"],
        "operation": record["operation"],
        "lease_seconds": record["lease_seconds"],
        "forced": record["forced"],
    }
    if previous is not None:
        result["overridden_lock"] = previous
        result["superseded"] = previous.get("superseded", [])
        if previous.get("cleared_conflict_copies"):
            result["cleared_conflict_copies"] = previous["cleared_conflict_copies"]
    # State the cross-device limit where a maintainer will actually see it,
    # instead of leaving it in the contract alone.
    hint = sync_artifacts.storage_hint(target)
    if hint["synchronized"]:
        result["storage_advisory"] = hint
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def status(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    state = read_state(target)
    condition = state.state()
    effective = state.effective()
    result: dict[str, Any] = {
        "locked": condition in {"held", "contended"},
        "state": condition,
        "lock_file": LOCK_NAME,
        "maintainer_id": default_maintainer_id(),
        "claims": [claim.describe(state.now) for claim in state.all_claims()],
    }
    problems = state.problems()
    if problems:
        result["problems"] = problems
        result["resolution"] = _contention_report(state)["resolution"]
    if len(effective) == 1:
        record = public_lock(effective[0].record)
        result["lock"] = effective[0].describe(state.now)
        result.update(describe_foreign_host(record))
    elif len(effective) > 1:
        result["holders"] = [claim.describe(state.now) for claim in effective]
        result["resolution"] = _contention_report(state)["resolution"]
    pending = state.pending_takeovers()
    if pending:
        result["pending_takeovers"] = [claim.describe(state.now) for claim in pending]
    if state.unreadable and not effective:
        result["invalid_lock"] = "; ".join(entry["reason"] for entry in state.unreadable)
    if condition == "free":
        result["locked"] = False
    hint = sync_artifacts.storage_hint(target)
    if hint["synchronized"]:
        result["storage_advisory"] = hint
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
                "lock_id": record.get("claim_id", record.get("lock_id", "")),
                "claim_id": record.get("claim_id", ""),
                "maintainer_id": record.get("maintainer_id", ""),
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


def heartbeat(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve()
    record = require_lock(target, token_from_args(args))
    print(
        json.dumps(
            {
                "owned": True,
                "heartbeat_refreshed": bool(record.get("heartbeat_refreshed")),
                "heartbeat_at": record.get("heartbeat_at", ""),
                "lease_seconds": record.get("lease_seconds", 0),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def withdraw(args: argparse.Namespace) -> int:
    """Remove this machine's own claim without a token.

    A crashed run leaves a claim nobody can release, because the private token
    died with it. Withdrawing is restricted to claims this machine wrote, so it
    is never a way around another maintainer's lock, and it also clears the
    conflict copies a synchronization client made of one's own claim.
    """
    target = Path(args.target).expanduser().resolve()
    if not (args.reason or "").strip():
        raise SystemExit("withdraw requires a non-empty --reason")
    maintainer_id = (args.maintainer or "").strip() or default_maintainer_id()
    state = read_state(target)
    removed: list[str] = []
    refused: list[dict[str, Any]] = []
    for claim in state.claims:
        if claim.maintainer_id != maintainer_id:
            continue
        if claim.host and claim.host != socket.gethostname():
            refused.append(
                {
                    "claim_file": claim.path.name,
                    "reason": (
                        f"The claim was written by {claim.host!r}. Withdraw it on that machine, "
                        "or use acquire --force --reason after explicit user approval."
                    ),
                }
            )
            continue
        try:
            claim.path.unlink()
            removed.append(claim.path.name)
        except OSError as exc:
            refused.append({"claim_file": claim.path.name, "reason": str(exc)})
    own_prefix = f"{CLAIM_PREFIX}{claim_slug(maintainer_id)}"
    root = lock_path(target)
    if root.is_dir():
        for path in sorted(root.iterdir()):
            artifact = sync_artifacts.classify(path.name)
            conflict = artifact is not None and artifact.kind == sync_artifacts.CONFLICT_COPY
            if conflict and path.name.startswith(own_prefix):
                try:
                    path.unlink()
                    removed.append(path.name)
                except OSError as exc:
                    refused.append({"claim_file": path.name, "reason": str(exc)})
    discarded = discard_empty_lock(target)
    print(
        json.dumps(
            {
                "withdrawn": bool(removed),
                "maintainer_id": maintainer_id,
                "removed": sorted(removed),
                "refused": refused,
                "lock_directory_removed": bool(discarded.get("removed")),
                "reason": args.reason.strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if removed or not refused else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire_parser = subparsers.add_parser("acquire", help="Claim the wiki for this maintainer")
    acquire_parser.add_argument("--target", required=True)
    acquire_parser.add_argument("--owner", required=True, help="Agent or run identifier")
    acquire_parser.add_argument("--operation", default="maintain", help="Short operation description")
    acquire_parser.add_argument("--token-file", required=True, help="Private runtime file outside the wiki")
    acquire_parser.add_argument(
        "--maintainer",
        default="",
        help="Stable team slot identifier; defaults to user@host",
    )
    acquire_parser.add_argument(
        "--lease-seconds",
        type=int,
        default=DEFAULT_LEASE_SECONDS,
        help="How long this claim stays valid without a heartbeat",
    )
    acquire_parser.add_argument(
        "--take-over",
        action="store_true",
        help="Two-step handover of a claim whose lease has run out",
    )
    acquire_parser.add_argument(
        "--settle-seconds",
        type=int,
        default=DEFAULT_SETTLE_SECONDS,
        help="How long a declared takeover stays visible before it takes effect",
    )
    acquire_parser.add_argument("--force", action="store_true", help="Immediately override every claim")
    acquire_parser.add_argument("--reason", help="Required explanation for --force and --take-over")
    acquire_parser.set_defaults(handler=acquire)

    status_parser = subparsers.add_parser("status", help="Show every visible claim")
    status_parser.add_argument("--target", required=True)
    status_parser.set_defaults(handler=status)

    verify_parser = subparsers.add_parser("verify", help="Verify ownership with the private token")
    verify_parser.add_argument("--target", required=True)
    verify_group = verify_parser.add_mutually_exclusive_group(required=True)
    verify_group.add_argument("--lock-token")
    verify_group.add_argument("--token-file")
    verify_parser.set_defaults(handler=verify)

    heartbeat_parser = subparsers.add_parser("heartbeat", help="Extend the owned claim's lease")
    heartbeat_parser.add_argument("--target", required=True)
    heartbeat_group = heartbeat_parser.add_mutually_exclusive_group(required=True)
    heartbeat_group.add_argument("--lock-token")
    heartbeat_group.add_argument("--token-file")
    heartbeat_parser.set_defaults(handler=heartbeat)

    release_parser = subparsers.add_parser("release", help="Release the owned claim")
    release_parser.add_argument("--target", required=True)
    release_group = release_parser.add_mutually_exclusive_group(required=True)
    release_group.add_argument("--lock-token")
    release_group.add_argument("--token-file")
    release_parser.add_argument("--remove-token-file", action="store_true")
    release_parser.set_defaults(handler=release)

    withdraw_parser = subparsers.add_parser(
        "withdraw", help="Remove this machine's own claim after an abandoned run"
    )
    withdraw_parser.add_argument("--target", required=True)
    withdraw_parser.add_argument("--maintainer", default="")
    withdraw_parser.add_argument("--reason", required=True)
    withdraw_parser.set_defaults(handler=withdraw)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
