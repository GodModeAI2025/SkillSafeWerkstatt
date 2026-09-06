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
from pathlib import Path, PurePosixPath
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

#: Files the specification reserves; every other .md is a concept document.
RESERVED_FILES = ("index.md", "log.md")


def validate_bundle(root: "Path") -> list[str]:
    """Check a written bundle against the OKF v0.2 conformance rules.

    The specification requires three things of a conformant bundle: every
    non-reserved Markdown file parses as frontmatter, every such block carries a
    non-empty `type`, and the reserved files follow their prescribed shape. An
    export that claims conformance should be able to demonstrate it, so this runs
    over the bundle that was actually written rather than over the intent.
    """
    problems: list[str] = []
    root_index = root / "index.md"
    if not root_index.is_file():
        problems.append("index.md is missing at the bundle root")
    else:
        try:
            data = read_okf_frontmatter(root_index.read_text(encoding="utf-8"), "index.md")
        except (OSError, UnicodeError, ValueError) as exc:
            problems.append(str(exc))
        else:
            keys = set(data)
            if keys != {"okf_version"}:
                problems.append(
                    f"index.md must declare okf_version and nothing else, found {sorted(keys)}"
                )
            elif str(data.get("okf_version")) != OKF_VERSION:
                problems.append(
                    f"index.md declares okf_version {data.get('okf_version')!r}, "
                    f"expected {OKF_VERSION!r}"
                )

    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if PurePosixPath(relative).name in RESERVED_FILES:
            continue
        try:
            data = read_okf_frontmatter(path.read_text(encoding="utf-8"), relative)
        except (OSError, UnicodeError, ValueError) as exc:
            problems.append(str(exc))
            continue
        value = data.get("type")
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{relative}: required field type is missing or empty")
    return problems

def read_okf_frontmatter(text: str, label: str) -> dict[str, Any]:
    """Parse the YAML subset an OKF bundle uses.

    The wiki's own frontmatter contract deliberately rejects nested mappings and
    lists of mappings, which is exactly what OKF v0.2 requires for `generated`,
    `verified` and `sources`. So a bundle cannot be validated with the wiki's
    parser, and this reads the OKF surface instead: scalars, inline mappings,
    scalar lists, and lists of mappings, one level deep.

    Anything outside that surface raises, because the exporter is the only writer
    of these bundles and must not emit a shape it cannot read back.
    """
    if not text.startswith("---"):
        raise ValueError(f"{label}: no frontmatter block")
    lines = text.splitlines()
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        raise ValueError(f"{label}: unterminated frontmatter block") from None

    data: dict[str, Any] = {}
    key: Optional[str] = None
    index = 1
    while index < end:
        raw = lines[index]
        line = raw.rstrip()
        if not line.strip():
            index += 1
            continue
        if not raw.startswith(" "):
            name, separator, value = line.partition(":")
            if not separator:
                raise ValueError(f"{label}:{index + 1}: expected 'key: value'")
            key = name.strip()
            if not key:
                raise ValueError(f"{label}:{index + 1}: empty property name")
            if key in data:
                raise ValueError(f"{label}:{index + 1}: duplicate property {key!r}")
            remainder = value.strip()
            if not remainder:
                data[key] = []          # a block list follows
            elif remainder.startswith("{"):
                data[key] = _inline_mapping(remainder, label, index + 1)
            else:
                data[key] = _scalar(remainder)
            index += 1
            continue
        if key is None:
            raise ValueError(f"{label}:{index + 1}: indented line before any property")
        stripped = line.strip()
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            name, separator, value = item.partition(":")
            if separator and not item.startswith(('"', "'")):
                entry: dict[str, Any] = {name.strip(): _scalar(value.strip())}
                index += 1
                # Continuation lines of the same mapping are indented further.
                while index < end and lines[index].startswith("    ") and not lines[index].strip().startswith("- "):
                    inner, inner_separator, inner_value = lines[index].strip().partition(":")
                    if not inner_separator:
                        raise ValueError(f"{label}:{index + 1}: expected 'key: value' in list item")
                    entry[inner.strip()] = _scalar(inner_value.strip())
                    index += 1
                _append(data, key, entry, label, index)
                continue
            _append(data, key, _scalar(item), label, index + 1)
            index += 1
            continue
        raise ValueError(f"{label}:{index + 1}: unsupported frontmatter line")
    return data


def _append(data: dict[str, Any], key: str, value: Any, label: str, line: int) -> None:
    holder = data.get(key)
    if not isinstance(holder, list):
        raise ValueError(f"{label}:{line}: list item under a non-list property {key!r}")
    holder.append(value)


def _inline_mapping(raw: str, label: str, line: int) -> dict[str, Any]:
    body = raw.strip()
    if not body.startswith("{") or not body.endswith("}"):
        raise ValueError(f"{label}:{line}: malformed inline mapping")
    mapping: dict[str, Any] = {}
    inner = body[1:-1].strip()
    if not inner:
        return mapping
    for part in _split_inline(inner, label, line):
        name, separator, value = part.partition(":")
        if not separator:
            raise ValueError(f"{label}:{line}: expected 'key: value' inside the inline mapping")
        mapping[name.strip()] = _scalar(value.strip())
    return mapping


def _split_inline(inner: str, label: str, line: int) -> list[str]:
    """Split on commas that are not inside a quoted value."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    for character in inner:
        if quote:
            if character == quote:
                quote = ""
            current.append(character)
        elif character in "\"'":
            quote = character
            current.append(character)
        elif character == ",":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if quote:
        raise ValueError(f"{label}:{line}: unterminated quoted value")
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def _scalar(raw: str) -> Any:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if value in {"true", "false"}:
        return value == "true"
    if value == "null" or value == "":
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value
