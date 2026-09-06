#!/usr/bin/env python3
"""Validate structural and traceability invariants of SkillSafeWerkstatt."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Optional

from frontmatter_contract import FrontmatterError, compose_document, parse_file
from identity_contract import validate_identity_files
from wiki_lock import require_lock
from urllib.parse import urlparse

from design_contract import CLUSTER_COLORS

import sync_artifacts
import trust_contract

#: Directories a synchronization client writes into alongside the maintainer.
SYNC_SCANNED_DIRS = ("schema", "sources", "wiki", "graph")

REQUIRED_PATHS = (
    "WIKI.md",
    "SOUL.md",
    "schema/WIKI_RULES.md",
    "schema/WIKI_PROFILE.md",
    "schema/CONTENT_POLICY.md",
    "schema/CLUSTERS.md",
    "schema/CONCEPTS.md",
    "schema/QUALITY_POLICY.md",
    "sources",
    "wiki/index.md",
    "wiki/overview.md",
    "meta/sources.jsonl",
    "meta/changes.md",
    "meta/questions.md",
    "meta/releases.jsonl",
    "meta/quality-reviews.jsonl",
    "meta/quality-status.json",
    "WIKI_VERSION",
    "graph/index.html",
    "graph/graph.json",
)
PAGE_KEYS = (
    "id", "title", "type", "status", "created", "updated", "description", "language",
    "sources", "clusters", "concepts", "tags",
)
SOURCE_KEYS = (
    "source_id",
    "title",
    "date",
    "original_ref",
    "extracted_sha256",
    "source_type",
    "content_language",
    "extracted_at",
    "extractor",
    "status",
    "tags",
)
PAGE_TYPES = {"index", "overview", "concept", "entity", "topic", "comparison"}
PAGE_STATUSES = {"draft", "active", "superseded"}
SOURCE_STATUSES = {"active", "partial", "superseded", "withdrawn"}
QUALITY_REVIEW_KINDS = {"quality", "cleaning"}
QUALITY_REVIEW_OUTCOMES = {"passed", "attention-needed", "not-applicable"}
QUALITY_POLICY_FIELDS = (
    "quality_review_after_days",
    "cleaning_review_after_days",
    "snapshot_warning_after_days",
)
CLAIM_KINDS = {"fact", "observation", "definition", "interpretation", "recommendation"}
CLAIM_STATUSES = {"active", "disputed", "superseded", "unsupported"}
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
CLAIM_BLOCK = re.compile(
    r"<!--\s*claim\s*\n(?P<meta>.*?)-->\s*(?P<text>.*?)\s*<!--\s*/claim\s*-->",
    re.DOTALL | re.IGNORECASE,
)
CLAIM_ID_RE = re.compile(r"^clm-[0-9a-f]{16}$")
CLAIM_SOURCE_RE = re.compile(r"^(src-[0-9a-f]{16})@(.+)$")
CLUSTER_HEADING = re.compile(r"^##\s+([a-z0-9]+(?:-[a-z0-9]+)*)\s*$")
CLUSTER_FIELD = re.compile(r"^-\s+([A-Za-z]+):\s*(.*)$")
CONCEPT_HEADING = CLUSTER_HEADING
CONCEPT_FIELD = CLUSTER_FIELD
DEFAULT_CLUSTER_COLORS = set(CLUSTER_COLORS)


def parse_frontmatter(path: Path, errors: list[str]) -> tuple[dict[str, Any], str]:
    try:
        document = parse_file(path, require_frontmatter=True)
    except (OSError, UnicodeError, FrontmatterError) as exc:
        errors.append(str(exc))
        return {}, ""
    return document.data, document.body


def load_registry(path: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{number}: invalid JSON: {exc}")
            continue
        source_id = record.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"{path}:{number}: missing source_id")
        elif source_id in records:
            errors.append(f"{path}:{number}: duplicate source_id {source_id}")
        else:
            records[source_id] = record
    return records


def link_target(raw: str) -> str:
    value = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return value.removesuffix(".md").lstrip("./")


def source_id_from_reference(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    match = re.search(r"src-[0-9a-f]{16}", value)
    return match.group(0) if match else None


def portable_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip()
    lowered = normalized.lower()
    if lowered.startswith("file:"):
        return False
    parsed = urlparse(normalized)
    if len(parsed.scheme) > 1:
        return True
    if normalized.startswith(("~/", "~\\")):
        return False
    if PurePosixPath(normalized).is_absolute() or PureWindowsPath(normalized).is_absolute():
        return False
    return ".." not in PurePosixPath(normalized.replace("\\", "/")).parts


def portable_vault_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip()
    if PurePosixPath(normalized).is_absolute() or PureWindowsPath(normalized).is_absolute():
        return False
    return ".." not in PurePosixPath(normalized.replace("\\", "/")).parts


def safe_reference(value: str) -> str:
    return value if portable_reference(value) else "<non-portable-local-reference>"


def valid_timestamp(value: Any, allow_empty: bool = False) -> bool:
    if allow_empty and value == "":
        return True
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def load_quality_reviews(path: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    review_ids: set[str] = set()
    if not path.is_file():
        return latest
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"meta/quality-reviews.jsonl:{number}: invalid JSON: {exc}")
            continue
        if not isinstance(record, dict) or record.get("format") != "lmwiki-quality-review/1":
            errors.append(f"meta/quality-reviews.jsonl:{number}: invalid review format")
            continue
        review_id = record.get("review_id")
        if not isinstance(review_id, str) or not review_id or review_id in review_ids:
            errors.append(f"meta/quality-reviews.jsonl:{number}: missing or duplicate review_id")
        else:
            review_ids.add(review_id)
        kind = record.get("kind")
        if kind not in QUALITY_REVIEW_KINDS:
            errors.append(f"meta/quality-reviews.jsonl:{number}: invalid review kind")
            continue
        if record.get("outcome") not in QUALITY_REVIEW_OUTCOMES:
            errors.append(f"meta/quality-reviews.jsonl:{number}: invalid review outcome")
        if not valid_timestamp(record.get("reviewed_at")):
            errors.append(f"meta/quality-reviews.jsonl:{number}: invalid reviewed_at")
        summary = record.get("summary")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
            errors.append(f"meta/quality-reviews.jsonl:{number}: invalid summary")
        previous = latest.get(str(kind))
        if previous is None or str(record.get("reviewed_at") or "") >= str(previous.get("reviewed_at") or ""):
            latest[str(kind)] = record
    return latest


def load_clusters(path: Path, errors: list[str], warnings: list[str]) -> dict[str, dict[str, str]]:
    if not path.is_file():
        errors.append("schema/CLUSTERS.md is missing; navigation clusters are not configured")
        return {}
    definitions: dict[str, dict[str, str]] = {}
    current: Optional[dict[str, str]] = None
    fenced = False
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = CLUSTER_HEADING.match(line)
        if heading:
            cluster_id = heading.group(1)
            if cluster_id in definitions:
                errors.append(f"schema/CLUSTERS.md:{number}: duplicate cluster ID {cluster_id}")
            current = {"id": cluster_id}
            definitions[cluster_id] = current
            continue
        field = CLUSTER_FIELD.match(line)
        if field and current is not None:
            current[field.group(1).casefold()] = field.group(2).strip()

    for cluster_id, definition in definitions.items():
        for field in ("label", "color", "status", "purpose"):
            if not definition.get(field):
                errors.append(f"schema/CLUSTERS.md: cluster {cluster_id} is missing {field}")
        color = definition.get("color", "").upper()
        if color and color not in DEFAULT_CLUSTER_COLORS:
            errors.append(f"schema/CLUSTERS.md: cluster {cluster_id} uses a color outside the configured palette: {color}")
        if definition.get("status") not in {"active", "draft", "superseded"}:
            errors.append(f"schema/CLUSTERS.md: cluster {cluster_id} has invalid status {definition.get('status')}")
        directory = definition.get("directory", "")
        if directory and (not portable_vault_path(directory) or not directory.startswith("wiki/")):
            errors.append(f"schema/CLUSTERS.md: cluster {cluster_id} has invalid Directory")
    return definitions


def split_pipe(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def parse_claims(path: Path, body: str, errors: list[str]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for index, match in enumerate(CLAIM_BLOCK.finditer(body), 1):
        metadata: dict[str, str] = {}
        for raw_line in match.group("meta").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ":" not in line:
                errors.append(f"{path}: claim {index} has malformed metadata line {line!r}")
                continue
            key, value = line.split(":", 1)
            normalized_key = key.strip().casefold()
            if normalized_key in metadata:
                errors.append(f"{path}: claim {index} repeats metadata field {normalized_key}")
            metadata[normalized_key] = value.strip()
        for key in ("id", "kind", "status", "sources"):
            if key not in metadata:
                errors.append(f"{path}: claim {index} is missing {key}")
        unknown = set(metadata) - {"id", "kind", "status", "sources", "replaces", "contradicts", "note"}
        for key in sorted(unknown):
            errors.append(f"{path}: claim {index} has unknown metadata field {key}")
        claim = {
            **metadata,
            "text": match.group("text").strip(),
            "path": path,
            "number": index,
            "source_entries": split_pipe(metadata.get("sources", "")),
            "replaces_ids": split_pipe(metadata.get("replaces", "")),
            "contradicts_ids": split_pipe(metadata.get("contradicts", "")),
        }
        if not claim["text"]:
            errors.append(f"{path}: claim {index} has no visible claim text")
        claims.append(claim)
    if "<!-- claim" in body.casefold() and not claims:
        errors.append(f"{path}: contains an unparseable claim block")
    return claims


def load_concepts(path: Path, errors: list[str]) -> dict[str, dict[str, str]]:
    if not path.is_file():
        errors.append("schema/CONCEPTS.md is missing; controlled concepts are not configured")
        return {}
    definitions: dict[str, dict[str, str]] = {}
    current: Optional[dict[str, str]] = None
    fenced = False
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = CONCEPT_HEADING.match(line)
        if heading:
            concept_id = heading.group(1)
            if concept_id in definitions:
                errors.append(f"schema/CONCEPTS.md:{number}: duplicate concept ID {concept_id}")
            current = {"id": concept_id}
            definitions[concept_id] = current
            continue
        field = CONCEPT_FIELD.match(line)
        if field and current is not None:
            current[field.group(1).casefold()] = field.group(2).strip()

    vocabulary: dict[str, str] = {}
    for concept_id, definition in definitions.items():
        for field in ("preferred", "status", "definition"):
            if not definition.get(field):
                errors.append(f"schema/CONCEPTS.md: concept {concept_id} is missing {field}")
        if definition.get("status") not in {"active", "draft", "superseded"}:
            errors.append(
                f"schema/CONCEPTS.md: concept {concept_id} has invalid status {definition.get('status')}"
            )
        broader = split_pipe(definition.get("broader", ""))
        if len(broader) > 1:
            errors.append(f"schema/CONCEPTS.md: concept {concept_id} has more than one Broader concept")
        related = split_pipe(definition.get("related", ""))
        for relation in broader + related:
            if relation == concept_id:
                errors.append(f"schema/CONCEPTS.md: concept {concept_id} references itself")
            elif relation not in definitions:
                errors.append(f"schema/CONCEPTS.md: concept {concept_id} references unknown concept {relation}")
        if definition.get("status") == "active":
            terms = [definition.get("preferred", "")] + split_pipe(definition.get("aliases", ""))
            for term in terms:
                key = " ".join(term.casefold().split())
                if not key:
                    continue
                if key in vocabulary and vocabulary[key] != concept_id:
                    errors.append(
                        f"schema/CONCEPTS.md: active term {term!r} is ambiguous between "
                        f"{vocabulary[key]} and {concept_id}"
                    )
                else:
                    vocabulary[key] = concept_id
    return definitions


def check_storage_layer(
    target: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Report files the synchronization client or the storage layer objects to.

    Returns the paths other checks must skip: `ignorable` for operating-system
    noise and `excluded` for everything that must not be parsed as wiki content.
    """
    relatives = sync_artifacts.walk(target, SYNC_SCANNED_DIRS)
    ignorable: set[str] = set()
    excluded: set[str] = set()
    reported: list[dict[str, Any]] = []

    for artifact in sync_artifacts.classify_all(relatives):
        reported.append(artifact.as_dict())
        if artifact.kind == sync_artifacts.IGNORABLE:
            # Expected noise. Never an error, and never wiki content.
            ignorable.add(artifact.path)
            excluded.add(artifact.path)
        elif artifact.kind == sync_artifacts.CONFLICT_COPY:
            excluded.add(artifact.path)
            errors.append(
                f"{artifact.path}: synchronization conflict copy of {artifact.original}; "
                "resolve it before releasing instead of maintaining both files"
            )
        else:
            errors.append(f"{artifact.path}: {artifact.reason}")

    for collision in sync_artifacts.case_collisions(relatives):
        errors.append(
            f"{collision['paths']}: these paths differ only in case; "
            "SharePoint cannot hold both at once"
        )

    profile_prefix = read_storage_prefix(target)
    for finding in sync_artifacts.path_budget_findings(relatives, prefix=profile_prefix):
        errors.append(
            f"{finding['path']}: the storage path would need {finding['characters']} characters, "
            f"above the {finding['budget']}-character OneDrive and SharePoint limit"
        )
    if profile_prefix:
        for finding in sync_artifacts.path_budget_findings(
            relatives, prefix=profile_prefix, budget=sync_artifacts.WINDOWS_PATH_BUDGET
        ):
            warnings.append(
                f"{finding['path']}: {finding['characters']} characters exceeds the default "
                "Windows limit of 260; the file needs long-path support locally"
            )

    return {"ignorable": ignorable, "excluded": excluded, "artifacts": reported}


def read_storage_prefix(target: Path) -> str:
    """Read the confirmed storage path prefix from the wiki profile, if present."""
    path = target / "schema/WIKI_PROFILE.md"
    if not path.is_file():
        return ""
    try:
        document = parse_file(path)
    except (OSError, UnicodeError, FrontmatterError):
        return ""
    value = document.data.get("storage_path_prefix")
    return str(value).strip() if isinstance(value, str) else ""


def repair_index_sources(path: Path) -> bool:
    """Add an empty sources list to an index page when that is the only omission."""
    if not path.is_file():
        return False
    try:
        document = parse_file(path, require_frontmatter=True)
    except (OSError, UnicodeError, FrontmatterError):
        return False
    if document.data.get("type") != "index" or "sources" in document.data:
        return False
    updated: dict[str, Any] = {}
    for key, value in document.data.items():
        if key == "tags":
            updated["sources"] = []
        updated[key] = value
    if "sources" not in updated:
        updated["sources"] = []
    path.write_text(compose_document(document, updated), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument(
        "--fix-safe",
        action="store_true",
        help="Request all safe repairs; mandatory index sources repair is always applied",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Perform a baseline audit without repairs or writing meta/lint-report.json",
    )
    args = parser.parse_args()
    if args.fix_safe and args.check_only:
        raise SystemExit("--fix-safe and --check-only cannot be combined")

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    errors: list[str] = []
    warnings: list[str] = []
    fixes: list[str] = []

    # An index never cites source evidence itself, so its required sources value is
    # deterministically the empty list. Repair this invariant on every locked lint
    # invocation; requiring a caller to remember --fix-safe caused avoidable failures.
    if not args.check_only and repair_index_sources(target / "wiki/index.md"):
        fixes.append("wiki/index.md: added empty sources list automatically")

    for relative in REQUIRED_PATHS:
        if not (target / relative).exists():
            errors.append(f"Missing required path: {relative}")

    identity_status, identity_errors = validate_identity_files(target, required=True)
    errors.extend(identity_errors)

    version_path = target / "WIKI_VERSION"
    if version_path.is_file() and not re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)",
        version_path.read_text(encoding="utf-8").strip(),
    ):
        errors.append("WIKI_VERSION must contain one semantic version x.y.z")

    profile_path = target / "schema/WIKI_PROFILE.md"
    profile, _ = parse_frontmatter(profile_path, errors) if profile_path.is_file() else ({}, "")
    for key in (
        "profile_version",
        "wiki_language",
        "wiki_language_label",
        "source_language_policy",
        "synthesis_language_policy",
        "language_migration_policy",
    ):
        if key not in profile:
            errors.append(f"schema/WIKI_PROFILE.md: missing profile field {key}")
    wiki_language = str(profile.get("wiki_language") or "")
    if wiki_language and not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", wiki_language):
        errors.append("schema/WIKI_PROFILE.md: wiki_language is not a portable BCP-47-style code")
    if profile.get("source_language_policy") != "preserve-original":
        errors.append("schema/WIKI_PROFILE.md: source_language_policy must be preserve-original")
    if profile.get("synthesis_language_policy") != "translate-to-wiki-language":
        errors.append(
            "schema/WIKI_PROFILE.md: synthesis_language_policy must be translate-to-wiki-language"
        )

    quality_policy_path = target / "schema/QUALITY_POLICY.md"
    quality_policy, _ = (
        parse_frontmatter(quality_policy_path, errors) if quality_policy_path.is_file() else ({}, "")
    )
    parsed_quality_policy: dict[str, int] = {}
    for field in QUALITY_POLICY_FIELDS:
        raw_value = str(quality_policy.get(field) or "")
        if not raw_value.isdigit() or not 1 <= int(raw_value) <= 3650:
            errors.append(f"schema/QUALITY_POLICY.md: {field} must be an integer from 1 to 3650")
        else:
            parsed_quality_policy[field] = int(raw_value)
    if quality_policy.get("status") != "active":
        errors.append("schema/QUALITY_POLICY.md: status must be active")

    latest_quality_reviews = load_quality_reviews(target / "meta/quality-reviews.jsonl", errors)
    quality_status_path = target / "meta/quality-status.json"
    quality_status: dict[str, Any] = {}
    if quality_status_path.is_file():
        try:
            loaded_quality_status = json.loads(quality_status_path.read_text(encoding="utf-8"))
            if isinstance(loaded_quality_status, dict):
                quality_status = loaded_quality_status
            else:
                errors.append("meta/quality-status.json: root must be an object")
        except json.JSONDecodeError as exc:
            errors.append(f"meta/quality-status.json: invalid JSON: {exc}")
    if quality_status and quality_status.get("format") != "lmwiki-quality/1":
        errors.append("meta/quality-status.json: invalid format")
    if quality_status:
        status_policy = quality_status.get("policy")
        if isinstance(status_policy, dict) and parsed_quality_policy and status_policy != parsed_quality_policy:
            warnings.append("meta/quality-status.json: policy differs and will be refreshed at release")
        reviews = quality_status.get("reviews")
        if not isinstance(reviews, dict) or any(kind not in reviews for kind in QUALITY_REVIEW_KINDS):
            errors.append("meta/quality-status.json: reviews must contain quality and cleaning")
        technical = quality_status.get("technical")
        if not isinstance(technical, dict):
            errors.append("meta/quality-status.json: technical status is missing")
        if not valid_timestamp(quality_status.get("generated_at"), allow_empty=True):
            errors.append("meta/quality-status.json: generated_at is invalid")

    registry = load_registry(target / "meta/sources.jsonl", errors)
    cluster_definitions = load_clusters(target / "schema/CLUSTERS.md", errors, warnings)
    concept_definitions = load_concepts(target / "schema/CONCEPTS.md", errors)
    # Classify what the storage layer and the operating system put here before
    # judging any of it as wiki content.
    storage_findings = check_storage_layer(target, errors, warnings)
    ignorable_paths = storage_findings["ignorable"]

    sources_root = target / "sources"
    if sources_root.is_dir():
        for source_entry in sorted(sources_root.rglob("*")):
            relative_entry = source_entry.relative_to(target).as_posix()
            if relative_entry in ignorable_paths:
                # Reported once by check_storage_layer; never a smuggled original.
                continue
            if source_entry.is_symlink():
                errors.append(
                    f"{relative_entry}: sources/ permits registered Markdown files only; symlinks are not allowed"
                )
            elif source_entry.is_dir():
                errors.append(
                    f"{relative_entry}: sources/ must be flat; nested directories such as sources/raw are not allowed"
                )
            elif source_entry.suffix.casefold() != ".md":
                errors.append(
                    f"{relative_entry}: sources/ permits registered Markdown files only; original or binary files must remain outside the wiki"
                )
    source_files = sorted(sources_root.glob("*.md")) if sources_root.is_dir() else []
    source_ids_from_files: set[str] = set()

    for path in source_files:
        data, _ = parse_frontmatter(path, errors)
        for key in SOURCE_KEYS:
            if key not in data:
                errors.append(f"{path}: missing source field {key}")
        source_id = data.get("source_id")
        if isinstance(source_id, str):
            if source_id in source_ids_from_files:
                errors.append(f"{path}: duplicate source_id {source_id}")
            source_ids_from_files.add(source_id)
            if source_id not in registry:
                errors.append(f"{path}: source_id {source_id} missing from registry")
        if data.get("status") and data.get("status") not in SOURCE_STATUSES:
            errors.append(f"{path}: invalid source status {data.get('status')}")
        tags = data.get("tags", [])
        if not isinstance(tags, list) or "type/source" not in tags:
            errors.append(f"{path}: missing structural type/source tag")
        if data.get("date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("date"))):
            errors.append(f"{path}: source date must use YYYY-MM-DD")
        if data.get("content_language") and not re.fullmatch(
            r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*",
            str(data.get("content_language")),
        ):
            errors.append(f"{path}: content_language is not a portable BCP-47-style code")
        if not portable_reference(data.get("original_ref")):
            errors.append(f"{path}: original_ref is not portable")

    for source_id, record in registry.items():
        relative = record.get("path")
        if not portable_vault_path(relative):
            errors.append(f"Registry source {source_id} has a non-portable path")
        elif not (target / str(relative)).is_file():
            errors.append(f"Registry source {source_id} points to a missing file: {relative}")
        if not portable_reference(record.get("original_ref")):
            errors.append(f"Registry source {source_id} has a non-portable original_ref")
        if not re.fullmatch(
            r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*",
            str(record.get("content_language") or ""),
        ):
            errors.append(f"Registry source {source_id} has an invalid or missing content_language")

    # A conflict copy carries the frontmatter of the page it was copied from, so
    # parsing it as a page would report a duplicate id and hide the real cause.
    wiki_files = [
        path
        for path in (sorted((target / "wiki").rglob("*.md")) if (target / "wiki").is_dir() else [])
        if path.relative_to(target).as_posix() not in storage_findings["excluded"]
    ]
    page_ids: dict[str, Path] = {}
    page_data: dict[Path, dict[str, Any]] = {}
    page_bodies: dict[Path, str] = {}
    claims_by_id: dict[str, dict[str, Any]] = {}
    all_claims: list[dict[str, Any]] = []

    for path in wiki_files:
        data, body = parse_frontmatter(path, errors)
        page_data[path] = data
        page_bodies[path] = body
        for key in PAGE_KEYS:
            if key not in data:
                errors.append(f"{path}: missing page field {key}")
        # Trust metadata is optional, but must be well formed when present.
        errors.extend(trust_contract.validate(data, str(path)))
        if data.get("type") != "index" and not data.get(trust_contract.GENERATED_BY):
            warnings.append(
                f"{path}: no {trust_contract.GENERATED_BY}; the page cannot say who produced it"
            )
        page_id = data.get("id")
        if isinstance(page_id, str):
            if page_id in page_ids:
                errors.append(f"{path}: duplicate page id {page_id}; also in {page_ids[page_id]}")
            page_ids[page_id] = path
        if data.get("type") and data.get("type") not in PAGE_TYPES:
            errors.append(f"{path}: invalid page type {data.get('type')}")
        if data.get("status") and data.get("status") not in PAGE_STATUSES:
            errors.append(f"{path}: invalid page status {data.get('status')}")
        if wiki_language and data.get("language") != wiki_language:
            errors.append(
                f"{path}: page language {data.get('language')!r} differs from wiki language {wiki_language!r}"
            )
        for date_key in ("created", "updated"):
            if data.get(date_key) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get(date_key))):
                errors.append(f"{path}: {date_key} must use YYYY-MM-DD")
        if len(str(data.get("description", ""))) > 140:
            warnings.append(f"{path}: description exceeds 140 characters")

        sources = data.get("sources", [])
        if not isinstance(sources, list):
            errors.append(f"{path}: sources must be a JSON-style list")
            sources = []
        if data.get("status") == "active" and data.get("type") != "index" and not sources:
            errors.append(f"{path}: active page has no registered sources")
        for source_reference in sources:
            source_id = source_id_from_reference(source_reference)
            if not source_id or source_id not in registry:
                errors.append(f"{path}: references unknown source {source_reference}")
        page_source_ids = {
            source_id
            for source_reference in sources
            for source_id in [source_id_from_reference(source_reference)]
            if source_id
        }
        tags = data.get("tags", [])
        if not isinstance(tags, list) or not any(str(tag).startswith("type/wiki-") for tag in tags):
            errors.append(f"{path}: missing structural type/wiki-* tag")
        if re.search(r"\b(TODO|TBD)\b", body, re.IGNORECASE) and data.get("status") == "active":
            warnings.append(f"{path}: active page contains TODO or TBD")

        clusters = data.get("clusters", [])
        if "clusters" not in data:
            warnings.append(f"{path}: missing clusters field; cluster assignment has not been reviewed")
            clusters = []
        elif not isinstance(clusters, list):
            errors.append(f"{path}: clusters must be a JSON-style list")
            clusters = []
        for cluster_id in clusters:
            if not isinstance(cluster_id, str) or cluster_id not in cluster_definitions:
                errors.append(f"{path}: references unknown cluster {cluster_id}")
        primary_cluster = data.get("primary_cluster")
        if primary_cluster and primary_cluster not in clusters:
            errors.append(f"{path}: primary_cluster must also appear in clusters")
        if primary_cluster in cluster_definitions:
            mapped_directory = cluster_definitions[primary_cluster].get("directory", "").rstrip("/")
            page_relative = path.relative_to(target).as_posix()
            if mapped_directory and not page_relative.startswith(mapped_directory + "/"):
                warnings.append(
                    f"{path}: primary cluster {primary_cluster} maps to {mapped_directory}; "
                    "discuss and preview a page move"
                )
        active_clusters = {
            cluster_id
            for cluster_id, definition in cluster_definitions.items()
            if definition.get("status") == "active"
        }
        if active_clusters and data.get("status") == "active" and data.get("type") != "index" and not clusters:
            warnings.append(f"{path}: active page has no confirmed navigation cluster")

        concepts = data.get("concepts", [])
        if not isinstance(concepts, list):
            errors.append(f"{path}: concepts must be a JSON-style list")
            concepts = []
        for concept_id in concepts:
            if not isinstance(concept_id, str) or concept_id not in concept_definitions:
                errors.append(f"{path}: references unknown concept {concept_id}")

        claims = parse_claims(path, body, errors)
        all_claims.extend(claims)
        if data.get("status") == "active" and data.get("type") != "index" and not claims:
            errors.append(f"{path}: active page has no claim blocks")
        for claim in claims:
            claim_id = str(claim.get("id") or "")
            if not CLAIM_ID_RE.fullmatch(claim_id):
                errors.append(f"{path}: claim {claim.get('number')} has invalid ID {claim_id!r}")
            elif claim_id in claims_by_id:
                errors.append(f"{path}: duplicate claim ID {claim_id}; also in {claims_by_id[claim_id]['path']}")
            else:
                claims_by_id[claim_id] = claim
            if claim.get("kind") not in CLAIM_KINDS:
                errors.append(f"{path}: claim {claim_id or claim.get('number')} has invalid kind {claim.get('kind')}")
            if claim.get("status") not in CLAIM_STATUSES:
                errors.append(
                    f"{path}: claim {claim_id or claim.get('number')} has invalid status {claim.get('status')}"
                )
            entries = claim.get("source_entries", [])
            if claim.get("status") in {"active", "disputed", "superseded"} and not entries:
                errors.append(f"{path}: claim {claim_id or claim.get('number')} has no source locator")
            for entry in entries:
                source_match = CLAIM_SOURCE_RE.fullmatch(str(entry))
                if not source_match or not source_match.group(2).strip():
                    errors.append(
                        f"{path}: claim {claim_id or claim.get('number')} has invalid source locator {entry!r}"
                    )
                    continue
                source_id = source_match.group(1)
                if source_id not in registry:
                    errors.append(f"{path}: claim {claim_id} references unknown source {source_id}")
                if source_id not in page_source_ids:
                    errors.append(
                        f"{path}: claim {claim_id} uses {source_id}, but page frontmatter does not cite it"
                    )

    for claim in all_claims:
        claim_id = str(claim.get("id") or claim.get("number"))
        for relation_name in ("replaces_ids", "contradicts_ids"):
            for related_id in claim.get(relation_name, []):
                if related_id == claim.get("id"):
                    errors.append(f"{claim['path']}: claim {claim_id} relates to itself")
                elif related_id not in claims_by_id:
                    errors.append(f"{claim['path']}: claim {claim_id} references unknown claim {related_id}")

    markdown_files = [
        path
        for path in target.rglob("*.md")
        if "meta/history" not in path.relative_to(target).as_posix()
        and path.relative_to(target).as_posix() not in storage_findings["excluded"]
    ]
    known_targets = {path.relative_to(target).with_suffix("").as_posix() for path in markdown_files}
    inbound: dict[str, int] = {key: 0 for key in known_targets}

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        for raw in WIKILINK.findall(text):
            link = link_target(raw)
            if link not in known_targets and not path.relative_to(target).as_posix().startswith("sources/"):
                errors.append(f"{path}: broken wikilink [[{safe_reference(raw)}]]")
            else:
                inbound[link] = inbound.get(link, 0) + 1

    index_path = target / "wiki/index.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    for path in wiki_files:
        if path == index_path:
            continue
        relative = path.relative_to(target).with_suffix("").as_posix()
        if not any(link_target(raw) == relative for raw in WIKILINK.findall(index_text)):
            errors.append(f"wiki/index.md does not list [[{relative}]]")
        if inbound.get(relative, 0) == 0:
            warnings.append(f"{path}: orphan page")

    graph_path = target / "graph/graph.json"
    if graph_path.is_file():
        try:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graphed_files = {
                node.get("path")
                for node in graph.get("nodes", [])
                if node.get("kind") == "file"
            }
            expected_graph_files = {
                path.relative_to(target).as_posix()
                for path in markdown_files
                if not path.relative_to(target).as_posix().startswith("meta/history/")
            }
            if graphed_files != expected_graph_files:
                missing = sorted(expected_graph_files - graphed_files)
                stale = sorted(graphed_files - expected_graph_files)
                errors.append(f"graph/graph.json is stale; missing={missing}, stale={stale}")
            expected_reader_pages = {
                (Path("graph/pages") / Path(relative).with_suffix(".html")).as_posix()
                for relative in expected_graph_files
            }
            actual_reader_pages = {
                path.relative_to(target).as_posix()
                for path in (target / "graph/pages").rglob("*.html")
            } if (target / "graph/pages").is_dir() else set()
            if actual_reader_pages != expected_reader_pages:
                missing = sorted(expected_reader_pages - actual_reader_pages)
                stale = sorted(actual_reader_pages - expected_reader_pages)
                errors.append(f"graph reading views are stale; missing={missing}, stale={stale}")
            for node in graph.get("nodes", []):
                if node.get("kind") != "file":
                    continue
                href = str(node.get("href") or "")
                raw_href = str(node.get("rawHref") or "")
                if not href.startswith("pages/") or not href.endswith(".html"):
                    errors.append(f"graph node {node.get('id')} has invalid relative reading-view href")
                if not raw_href.startswith("../") or not raw_href.endswith(".md"):
                    errors.append(f"graph node {node.get('id')} has invalid relative Markdown href")
            if graph.get("unresolved"):
                errors.append(f"graph/graph.json contains unresolved links: {graph.get('unresolved')}")
        except (json.JSONDecodeError, AttributeError) as exc:
            errors.append(f"graph/graph.json is invalid: {exc}")

    target_prefix = str(target)
    portable_errors = [message.replace(target_prefix, ".").replace("\\", "/") for message in errors]
    portable_warnings = [message.replace(target_prefix, ".").replace("\\", "/") for message in warnings]
    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "target": ".",
        "valid": not errors,
        "errors": portable_errors,
        "warnings": portable_warnings,
        "fixes": fixes,
        "stats": {
            "registered_sources": len(registry),
            "source_files": len(source_files),
            "wiki_pages": len(wiki_files),
            "navigation_clusters": len(cluster_definitions),
            "controlled_concepts": len(concept_definitions),
            "claims": len(all_claims),
            "wiki_language": wiki_language,
            "identity": identity_status,
            "trust": trust_contract.summary(
                trust_contract.distribution(
                    [page_data[path] for path in wiki_files if page_data.get(path)]
                )
            ),
        },
    }
    if not args.check_only:
        report_path = target / "meta/lint-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
