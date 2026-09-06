#!/usr/bin/env python3
"""Classify files a synchronization client or operating system created.

A OneDrive or SharePoint client is a writer on the wiki directory, not only a
transport. It resolves conflicts by keeping both copies and renaming one after
the device, and the operating system drops its own artifacts into synchronized
folders. Both are indistinguishable from wiki content to a plain directory walk.

This module is the single place that decides what such a file is, so the linter,
the release, and both verifiers can no longer disagree about the same path. It
only classifies; it never deletes, moves, or rewrites anything.

The storage-layer rules encoded here follow the documented OneDrive and
SharePoint restrictions: reserved names, forbidden characters, and the
400-character path budget.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional


# Kinds, ordered from "ignore quietly" to "the storage will reject this".
IGNORABLE = "os_artifact"
CONFLICT_COPY = "conflict_copy"
RESERVED_NAME = "reserved_name"
INVALID_CHARACTER = "invalid_character"
TRAILING_CHARACTER = "trailing_character"

#: Kinds that must never be treated as wiki content.
NON_CONTENT_KINDS = frozenset({IGNORABLE, CONFLICT_COPY})

#: Names the operating system or an Office application writes on its own.
#: OneDrive deliberately does not upload these, so a local copy is expected and
#: is never evidence of smuggled binary originals.
OS_ARTIFACT_NAMES = frozenset(
    {
        ".ds_store",
        ".localized",
        "desktop.ini",
        "ehthumbs.db",
        "thumbs.db",
        "icon\r",
    }
)

#: Names OneDrive and SharePoint refuse outright, compared without extension.
RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in range(10)}
    | {f"lpt{digit}" for digit in range(10)}
)

#: Full names OneDrive and SharePoint refuse outright.
RESERVED_NAMES = frozenset({".lock", "desktop.ini"})

#: Characters SharePoint rejects in a file or folder name.
INVALID_CHARACTERS = frozenset('"*:<>?/\\|')

#: Fragment SharePoint refuses anywhere inside a name.
FORBIDDEN_FRAGMENT = "_vti_"

#: Full decoded path budget for OneDrive and SharePoint, in characters.
PATH_BUDGET = 400

#: Default Windows path limit without long-path support, in characters.
WINDOWS_PATH_BUDGET = 260

# Conflict copies observed from OneDrive clients. The device suffix is the
# common Windows form; the parenthesized forms cover the localized variants.
_CONFLICT_PATTERNS = (
    re.compile(r"-(?:DESKTOP|LAPTOP|SURFACE)-[A-Z0-9]{5,8}$", re.IGNORECASE),
    re.compile(r"\((?:[^()]{1,64}\s)?conflicted copy(?:\s[^()]{1,64})?\)$", re.IGNORECASE),
    re.compile(r"\([^()]{1,64}\sconflict\)$", re.IGNORECASE),
    re.compile(r"-konfliktkopie(?:-[0-9]{1,4})?$", re.IGNORECASE),
)

# A bare device suffix is ambiguous on its own, so it only counts as a conflict
# copy when the original it was derived from still sits next to it.
_DEVICE_SUFFIX = re.compile(r"^(?P<stem>.+)-(?P<device>[A-Z0-9][A-Z0-9-]{2,30})$")


class Artifact:
    """One classified path, relative to the wiki root."""

    __slots__ = ("path", "kind", "reason", "original")

    def __init__(self, path: str, kind: str, reason: str, original: str = "") -> None:
        self.path = path
        self.kind = kind
        self.reason = reason
        self.original = original

    @property
    def ignorable(self) -> bool:
        """True when the file is noise that no contract should ever hash."""
        return self.kind == IGNORABLE

    def as_dict(self) -> dict[str, Any]:
        record = {"path": self.path, "kind": self.kind, "reason": self.reason}
        if self.original:
            record["original"] = self.original
        return record

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"Artifact({self.path!r}, {self.kind!r})"


def _is_os_artifact(name: str) -> bool:
    lowered = name.casefold()
    return lowered in OS_ARTIFACT_NAMES or lowered.startswith("~$")


def _conflict_original(relative: str, name: str, siblings: Optional[frozenset[str]]) -> Optional[str]:
    """Return the original file name when `name` looks like a conflict copy."""
    stem = PurePosixPath(name).stem
    suffix = PurePosixPath(name).suffix
    for pattern in _CONFLICT_PATTERNS:
        match = pattern.search(stem)
        if match:
            return f"{stem[: match.start()]}{suffix}"
    if siblings is None:
        return None
    # Ambiguous device suffix: only a conflict copy when the original survives.
    match = _DEVICE_SUFFIX.match(stem)
    if match:
        candidate = f"{match.group('stem')}{suffix}"
        parent = PurePosixPath(relative).parent
        if (parent / candidate).as_posix() in siblings:
            return candidate
    return None


def classify(
    relative: str,
    *,
    siblings: Optional[frozenset[str]] = None,
) -> Optional[Artifact]:
    """Classify one wiki-relative POSIX path, or return None for ordinary content.

    `siblings` is the set of wiki-relative paths that exist alongside this file.
    It is only consulted to disambiguate a device-suffixed name; pass None to
    skip that check entirely.
    """
    name = PurePosixPath(relative).name
    if not name:
        return None

    if _is_os_artifact(name):
        return Artifact(relative, IGNORABLE, f"operating-system or Office artifact {name!r}")

    original = _conflict_original(relative, name, siblings)
    if original:
        return Artifact(
            relative,
            CONFLICT_COPY,
            "synchronization conflict copy; the client kept both versions instead of merging",
            original=(PurePosixPath(relative).parent / original).as_posix(),
        )

    lowered = name.casefold()
    stem = PurePosixPath(name).stem.casefold()
    if lowered in RESERVED_NAMES or stem in RESERVED_STEMS:
        return Artifact(
            relative,
            RESERVED_NAME,
            f"OneDrive and SharePoint refuse the name {name!r}",
        )
    if FORBIDDEN_FRAGMENT in lowered:
        return Artifact(
            relative,
            RESERVED_NAME,
            f"OneDrive and SharePoint refuse {FORBIDDEN_FRAGMENT!r} anywhere in a name",
        )
    offending = sorted(INVALID_CHARACTERS & set(name))
    if offending:
        return Artifact(
            relative,
            INVALID_CHARACTER,
            f"OneDrive and SharePoint refuse the character(s) {''.join(offending)!r} in a name",
        )
    # A trailing space before the extension is stripped by Windows and by the
    # storage layer, so the stored name stops matching the recorded one.
    if name != name.strip() or name.endswith(".") or PurePosixPath(name).stem != PurePosixPath(name).stem.strip():
        return Artifact(
            relative,
            TRAILING_CHARACTER,
            "OneDrive and SharePoint refuse a leading or trailing space and a trailing period",
        )
    return None


def classify_all(relatives: Iterable[str]) -> list[Artifact]:
    """Classify a whole set of wiki-relative paths, resolving sibling context once."""
    known = frozenset(relatives)
    found = [classify(relative, siblings=known) for relative in sorted(known)]
    return [artifact for artifact in found if artifact is not None]


def is_ignorable(relative: str) -> bool:
    """True for files every contract must skip without complaint."""
    artifact = classify(relative)
    return artifact is not None and artifact.ignorable


def path_budget_findings(
    relatives: Iterable[str],
    *,
    prefix: str = "",
    budget: int = PATH_BUDGET,
) -> list[dict[str, Any]]:
    """Report paths that would exceed the storage path budget.

    `prefix` is the decoded library path the wiki will live under, for example
    ``/sites/Team/Freigegebene Dokumente/Wiki``. Without it only the wiki-relative
    length is known, which is a lower bound rather than the real figure.
    """
    normalized = prefix.strip("/")
    lead = len(normalized) + 1 if normalized else 0
    findings = []
    for relative in sorted(set(relatives)):
        total = lead + len(relative)
        if total > budget:
            findings.append(
                {
                    "path": relative,
                    "characters": total,
                    "budget": budget,
                    "reason": "the decoded storage path exceeds the OneDrive and SharePoint limit",
                }
            )
    return findings


def case_collisions(relatives: Iterable[str]) -> list[dict[str, Any]]:
    """Report paths that differ only in case.

    SharePoint preserves case but does not distinguish it, so two such files
    cannot coexist there even though they can locally on Linux.
    """
    seen: dict[str, list[str]] = {}
    for relative in sorted(set(relatives)):
        seen.setdefault(relative.casefold(), []).append(relative)
    return [
        {"paths": paths, "reason": "SharePoint does not distinguish these names"}
        for paths in seen.values()
        if len(paths) > 1
    ]


#: Path components that indicate a locally synchronized cloud library.
_SYNC_MARKERS = ("onedrive", "sharepoint")

#: Environment variables the OneDrive client sets for its sync roots.
_SYNC_ENVIRONMENT = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")


def storage_hint(target: Path, environment: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Guess whether `target` lives inside a synchronized cloud folder.

    This is a heuristic on visible path names and the client's own environment
    variables. There is no supported way to query a sync client's state, so the
    answer is advisory: it may miss a renamed sync root and it may flag an
    ordinary directory that merely contains the word. Callers must present it as
    a hint, never as a fact about the storage.
    """
    import os as _os

    environment = _os.environ if environment is None else environment
    resolved = target.expanduser().resolve()
    parts = [part.casefold() for part in resolved.parts]
    reasons: list[str] = []
    for part in parts:
        for marker in _SYNC_MARKERS:
            if marker in part:
                reasons.append(f"path component {part!r} names a synchronized library")
                break
    for name in _SYNC_ENVIRONMENT:
        root = environment.get(name)
        if not root:
            continue
        try:
            resolved.relative_to(Path(root).expanduser().resolve())
        except (ValueError, OSError):
            continue
        reasons.append(f"the target lies inside {name}")
    return {
        "synchronized": bool(reasons),
        "confidence": "heuristic",
        "reasons": reasons,
        "advisory": (
            "This wiki appears to live in a synchronized folder. The maintenance lock is a "
            "cooperative file lock on one filesystem; it cannot exclude a second device whose "
            "changes are reconciled later. Do not maintain the same wiki from two machines at "
            "once, and treat a published release as local until the client confirms upload."
        )
        if reasons
        else "",
    }


def walk(root: Path, directories: Iterable[str]) -> frozenset[str]:
    """Collect every file under `directories` as wiki-relative POSIX paths."""
    found: set[str] = set()
    for directory in directories:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                found.add(path.relative_to(root).as_posix())
    return frozenset(found)
