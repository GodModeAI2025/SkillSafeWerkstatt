#!/usr/bin/env python3
"""Register a faithful Markdown extraction in an initialized SkillSafeWerkstatt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlparse
from uuid import uuid4

from validate_extraction import assess
from wiki_lock import require_lock


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")[:64] or "source"


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def portable_reference(value: str) -> bool:
    """Return whether a source reference is safe to persist across machines."""
    normalized = value.strip()
    lowered = normalized.lower()
    if not normalized or lowered.startswith("file:"):
        return False
    parsed = urlparse(normalized)
    if len(parsed.scheme) > 1:
        return True
    if normalized.startswith(("~/", "~\\")):
        return False
    if PurePosixPath(normalized).is_absolute() or PureWindowsPath(normalized).is_absolute():
        return False
    if ".." in PurePosixPath(normalized.replace("\\", "/")).parts:
        return False
    return True


def is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def read_registry(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON in meta/sources.jsonl:{number}: {exc}") from exc
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--markdown-file", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--original-ref", required=True)
    parser.add_argument("--original-file")
    parser.add_argument("--original-version", default="")
    parser.add_argument("--source-type", default="unknown")
    parser.add_argument(
        "--content-language",
        default="und",
        help="BCP-47-style language code of the extracted source; use und when unknown",
    )
    parser.add_argument("--extractor", default="codex")
    parser.add_argument("--status", choices=("active", "partial"), default="active")
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--confirm-extraction-warnings",
        action="store_true",
        help="Allow an active registration after the user reviewed extraction warnings",
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    if not portable_reference(args.original_ref):
        raise SystemExit(
            "original-ref must be a portable relative or logical reference, URL, or remote item ID; "
            "absolute local paths, file: URLs, home-relative paths, and parent traversal are not allowed"
        )
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", args.content_language.strip()):
        raise SystemExit("content-language must be a portable BCP-47-style language code")

    markdown_file = Path(args.markdown_file).expanduser().resolve()
    registry_path = target / "meta/sources.jsonl"
    sources_dir = target / "sources"

    if not (target / "WIKI.md").is_file() or not sources_dir.is_dir():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    if not markdown_file.is_file():
        raise SystemExit("Markdown extraction file not found")
    if markdown_file.suffix.casefold() != ".md":
        raise SystemExit("markdown-file must be a completed .md extraction")
    if is_within(markdown_file, target):
        raise SystemExit(
            "Markdown staging input must stay outside the target wiki; register it from a temporary workspace"
        )

    extraction_report = assess(markdown_file, args.source_type)
    if extraction_report["state"] == "rejected":
        raise SystemExit(json.dumps({"state": "extraction_rejected", "extraction": extraction_report}, ensure_ascii=False))
    if (
        extraction_report["state"] == "attention-needed"
        and args.status == "active"
        and not args.confirm_extraction_warnings
    ):
        raise SystemExit(
            json.dumps(
                {
                    "state": "extraction_review_required",
                    "message": "Register as partial or confirm the reviewed extraction warnings.",
                    "extraction": extraction_report,
                },
                ensure_ascii=False,
            )
        )

    extracted_hash = sha256(markdown_file)
    original_hash = ""
    if args.original_file:
        original_file = Path(args.original_file).expanduser().resolve()
        if not original_file.is_file():
            raise SystemExit("Original source file not found")
        if is_within(original_file, target):
            raise SystemExit(
                "Original source files must stay outside the target wiki; sources/ contains registered Markdown only"
            )
        original_hash = sha256(original_file)

    identity_hash = original_hash or extracted_hash
    source_id = f"src-{identity_hash[:16]}"
    records = read_registry(registry_path)
    duplicate = next((record for record in records if record.get("source_id") == source_id), None)
    if duplicate:
        print(json.dumps({"duplicate": True, "source": duplicate}, ensure_ascii=False, indent=2))
        return 0

    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    destination = sources_dir / f"{source_id}-{slugify(args.title)}.md"
    if destination.exists():
        raise SystemExit("Source destination already exists without a matching registry entry; repair drift first")
    extracted_text = markdown_file.read_text(encoding="utf-8")
    frontmatter = "\n".join(
        (
            "---",
            f"source_id: {yaml_string(source_id)}",
            f"title: {yaml_string(args.title)}",
            f"date: {yaml_string(timestamp[:10])}",
            f"original_ref: {yaml_string(args.original_ref)}",
            f"original_version: {yaml_string(args.original_version)}",
            f"original_sha256: {yaml_string(original_hash)}",
            f"extracted_sha256: {yaml_string(extracted_hash)}",
            f"source_type: {yaml_string(args.source_type)}",
            f"content_language: {yaml_string(args.content_language.strip())}",
            f"extracted_at: {yaml_string(timestamp)}",
            f"extractor: {yaml_string(args.extractor)}",
            f"status: {yaml_string(args.status)}",
            f"extraction_notes: {yaml_string(args.notes)}",
            "tags:",
            '  - "type/source"',
            "---",
            "",
            f"# {args.title}",
            "",
            "## Extracted content",
            "",
        )
    )
    destination_text = frontmatter + extracted_text.rstrip() + "\n"

    record: dict[str, object] = {
        "source_id": source_id,
        "title": args.title,
        "path": destination.relative_to(target).as_posix(),
        "original_ref": args.original_ref,
        "original_version": args.original_version,
        "original_sha256": original_hash,
        "extracted_sha256": extracted_hash,
        "source_type": args.source_type,
        "content_language": args.content_language.strip(),
        "extracted_at": timestamp,
        "extractor": args.extractor,
        "status": args.status,
        "notes": args.notes,
    }
    existing_registry = registry_path.read_text(encoding="utf-8") if registry_path.is_file() else ""
    if existing_registry and not existing_registry.endswith("\n"):
        existing_registry += "\n"
    updated_registry = existing_registry + json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    temporary_source = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary_registry = registry_path.with_name(f".{registry_path.name}.{uuid4().hex}.tmp")
    source_committed = False
    try:
        temporary_source.write_text(destination_text, encoding="utf-8")
        temporary_registry.write_text(updated_registry, encoding="utf-8")
        os.replace(str(temporary_source), str(destination))
        source_committed = True
        os.replace(str(temporary_registry), str(registry_path))
    except Exception:
        # Source Markdown and its registry row form one canonical invariant.
        # Roll the new file back when publishing the registry fails.
        if source_committed:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        if temporary_source.exists():
            temporary_source.unlink()
        if temporary_registry.exists():
            temporary_registry.unlink()

    print(json.dumps({"duplicate": False, "source": record, "extraction": extraction_report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
