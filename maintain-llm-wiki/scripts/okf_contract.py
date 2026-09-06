#!/usr/bin/env python3
"""Mapping between the SkillSafeWerkstatt contract and Open Knowledge Format v0.2.

OKF is an interoperability view, not the native contract. It is deliberately
permissive where this wiki is strict, and it has no equivalent for the things
this wiki is built around: claim-level locators, a release manifest, snapshots,
a confirmed identity, or controlled concept worlds. An export is therefore
lossy by construction, and this module names exactly what it loses rather than
letting a consumer assume equivalence.

Reference: https://github.com/GoogleCloudPlatform/open-knowledge-format
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Optional
from urllib.parse import urlparse

import trust_contract


OKF_VERSION = "0.2"
REPORT_FORMAT = "lmwiki-okf-compatibility/2"

#: The only always-required concept field in OKF v0.2.
REQUIRED = ("type",)

#: Recommended in v0.2. `timestamp` is deliberately absent: it is not a field of
#: this specification, and the previous report checked for it in error.
RECOMMENDED = ("title", "description", "resource", "tags")

#: Trust, provenance and lifecycle fields added in v0.2.
LIFECYCLE = ("status", "stale_after")
PROVENANCE = ("generated", "verified", "sources")

#: OKF concept statuses, with `stable` as the default.
OKF_STATUSES = ("draft", "stable", "deprecated")

#: How this wiki's page statuses map onto the OKF set.
STATUS_MAP = {
    "active": "stable",
    "draft": "draft",
    "superseded": "deprecated",
}

#: Everything an OKF bundle cannot carry. Stated in every export.
NOT_EXPORTED = (
    "Claim blocks and their source_id@locator evidence, which is the wiki's "
    "finest-grained provenance; OKF records sources per document only.",
    "The release manifest and its hash boundary, so an OKF consumer cannot tell "
    "a complete published state from a half-finished one.",
    "Snapshots and the recovery history under meta/history.",
    "SOUL.md, the confirmed identity that governs how answers are phrased.",
    "Controlled concept worlds with preferred terms and aliases.",
    "Navigation clusters, colours, and the generated graph.",
    "The strict frontmatter subset and the linter that enforces it; OKF requires "
    "consumers to accept unknown keys and broken cross-links.",
)

ISO_INSTANT = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?$"
)


def valid_resource(value: Any) -> bool:
    """True for an absolute URI, a bundle-relative path, or a relative path."""
    if not isinstance(value, str) or not value.strip():
        return False
    if value.startswith(("/", "./", "../")):
        return True
    return bool(urlparse(value).scheme)


def okf_status(value: Any) -> str:
    """Map a wiki page status onto the OKF set, defaulting to stable."""
    return STATUS_MAP.get(str(value or ""), "stable")


def status_note(value: Any) -> str:
    """Explain a mapping that loses meaning, or return an empty string."""
    if str(value or "") == "disputed":
        return (
            "This page is disputed in the wiki. OKF has no disputed status, so it is "
            "exported as draft; the disagreement itself is not carried over."
        )
    return ""


def inspect(data: dict[str, Any], relative: str) -> dict[str, Any]:
    """Report one document's conformance with OKF v0.2 without changing it."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data.get("type"), str) or not str(data.get("type") or "").strip():
        errors.append("required field type must be a non-empty string")

    missing = [field for field in RECOMMENDED if data.get(field) in (None, "", [])]
    if "tags" not in missing and not isinstance(data.get("tags"), list):
        warnings.append("recommended field tags should be a list")
    if "resource" not in missing and not valid_resource(data.get("resource")):
        warnings.append("recommended field resource is not a URI or a relative reference")

    status = data.get("status")
    if status not in (None, "") and str(status) not in STATUS_MAP:
        warnings.append(f"status {status!r} has no OKF equivalent and would export as stable")
    stale = data.get("stale_after")
    if stale not in (None, "") and not ISO_INSTANT.fullmatch(str(stale)):
        warnings.append("stale_after is not an ISO-8601 instant")

    # v0.2 trust fields, held flat here and composed on export.
    warnings.extend(
        message.split(": ", 1)[-1] for message in trust_contract.validate(data, relative)
    )

    suggestions: list[dict[str, Any]] = []
    if "title" in missing:
        suggestions.append({"action": "review", "field": "title", "candidate": PurePosixPath(relative).stem})
    if "description" in missing:
        suggestions.append({"action": "curate", "field": "description", "candidate": None})
    if "resource" in missing:
        suggestions.append({"action": "supply-if-known", "field": "resource", "candidate": None})
    if not data.get(trust_contract.GENERATED_BY):
        suggestions.append({"action": "record", "field": trust_contract.GENERATED_BY, "candidate": None})

    return {
        "path": relative,
        "conformant": not errors,
        "errors": errors,
        "warnings": warnings,
        "missing_recommended": missing,
        "okf_status": okf_status(status),
        "trust_tier": trust_contract.trust_tier(data),
        "suggestions": suggestions,
        "unknown_fields_preserved": sorted(
            set(data) - {*REQUIRED, *RECOMMENDED, *LIFECYCLE, *PROVENANCE}
        ),
    }


def actor_record(actor: Any, at: Any) -> Optional[dict[str, str]]:
    """Compose the nested {by, at} form OKF expects from the flat fields."""
    if not trust_contract.valid_actor(actor) or not trust_contract.valid_instant(at):
        return None
    return {"by": str(actor), "at": str(at)}


def source_records(
    references: Any,
    registry: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Turn the page's source wikilinks into OKF source entries.

    Only registered sources are emitted, and only with values the registry
    actually holds. Nothing is invented to fill a recommended field.
    """
    records: list[dict[str, Any]] = []
    if not isinstance(references, list):
        return records
    for reference in references:
        match = re.search(r"src-[0-9a-f]{16}", str(reference))
        if not match:
            continue
        record = registry.get(match.group(0))
        # An empty registry record still identifies a real registered source;
        # only an unknown id is skipped.
        if record is None:
            continue
        entry: dict[str, Any] = {"id": match.group(0)}
        title = record.get("title")
        if isinstance(title, str) and title.strip():
            entry["title"] = title
        original = record.get("original_ref")
        if isinstance(original, str) and original.strip():
            entry["resource"] = original
        modified = record.get("extracted_at")
        if isinstance(modified, str) and ISO_INSTANT.fullmatch(modified):
            entry["last_modified"] = modified
        records.append(entry)
    return records
