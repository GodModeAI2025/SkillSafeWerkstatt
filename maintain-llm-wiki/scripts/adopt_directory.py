#!/usr/bin/env python3
"""Adopt an existing Markdown collection into a wiki, as registered sources.

An Obsidian vault, a documentation folder, an older wiki: material that already
exists and should not have to be re-ingested by hand one file at a time.

The concern with bulk adoption is that it can smuggle content into `wiki/` with
no evidence behind it, which is exactly what this wiki is built to prevent. That
does not happen here, because an adopted file **is** a document: it is registered
as a source like any other, with its own identifier, hash, and portable
reference. Nothing lands in the curated layer.

So adoption imports evidence, not knowledge. Turning that evidence into wiki
pages stays deliberate curation - the linter still requires sources, claims, and
locators on every active page, and this helper reports what would need curating
rather than doing it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import sync_artifacts
from frontmatter_contract import FrontmatterError, parse_document
from snapshot_wiki import create_snapshot
from wiki_lock import require_lock


PLAN_FORMAT = "lmwiki-adoption-plan/1"

#: Source type recorded for adopted material, so its origin stays visible.
ADOPTED_TYPE = "adopted"

H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def registered_hashes(target: Path) -> dict[str, str]:
    """Map each already-registered extraction hash to its source id."""
    path = target / "meta/sources.jsonl"
    known: dict[str, str] = {}
    if not path.is_file():
        return known
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            digest = record.get("extracted_sha256")
            if isinstance(digest, str) and digest:
                known[digest] = str(record.get("source_id") or "")
    return known


def derive_title(text: str, path: Path) -> str:
    """Take the document's own title: frontmatter, then first heading, then name."""
    try:
        document = parse_document(text, path.name)
    except FrontmatterError:
        document = None
    if document is not None:
        value = document.data.get("title")
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    heading = H1.search(text)
    if heading:
        return " ".join(heading.group(1).split())
    return " ".join(path.stem.replace("-", " ").replace("_", " ").split()) or path.stem


def inspect(path: Path, root: Path, known: dict[str, str]) -> dict[str, Any]:
    """Describe one candidate without changing anything."""
    relative = path.relative_to(root).as_posix()
    blockers: list[str] = []
    notes: list[str] = []

    if path.is_symlink():
        return {"path": relative, "adoptable": False, "blockers": ["symlinks are not adopted"]}
    try:
        content = path.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"path": relative, "adoptable": False, "blockers": [f"unreadable as UTF-8: {exc}"]}

    if not text.strip():
        blockers.append("the file is empty")

    digest = sha256_bytes(content)
    duplicate = known.get(digest, "")
    if duplicate:
        blockers.append(f"byte-identical content is already registered as {duplicate}")

    # The wiki names its own sources; a storage-hostile name in the origin only
    # matters for the reference it keeps, so it is a note rather than a blocker.
    artifact = sync_artifacts.classify(relative)
    if artifact is not None:
        if artifact.kind == sync_artifacts.IGNORABLE:
            return {"path": relative, "adoptable": False, "blockers": ["operating-system artifact"]}
        notes.append(f"the original name is problematic for OneDrive or SharePoint: {artifact.reason}")

    try:
        document = parse_document(text, relative)
        if not document.has_frontmatter:
            notes.append("no frontmatter; it is adopted as a plain extraction")
    except FrontmatterError as exc:
        notes.append(f"frontmatter is outside the wiki's subset and is not carried over: {exc}")

    return {
        "path": relative,
        "adoptable": not blockers,
        "title": derive_title(text, path),
        "sha256": digest,
        "bytes": len(content),
        "blockers": blockers,
        "notes": notes,
    }


def build_plan(target: Path, root: Path, language: str) -> dict[str, Any]:
    known = registered_hashes(target)
    candidates = [
        inspect(path, root, known)
        for path in sorted(root.rglob("*.md"))
        if path.is_file()
    ]
    others = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() != ".md"
    )
    adoptable = [item for item in candidates if item["adoptable"]]
    payload = {
        "format": PLAN_FORMAT,
        "source_root": root.name,
        "content_language": language,
        "candidates": candidates,
        "skipped_non_markdown": others[:200],
        "skipped_non_markdown_total": len(others),
        "summary": {
            "found": len(candidates),
            "adoptable": len(adoptable),
            "blocked": len(candidates) - len(adoptable),
        },
        "boundary": (
            "Adoption registers evidence, not knowledge. Each accepted file becomes a "
            "registered source under sources/; no wiki page is created, and every page built "
            "on this material still needs its own claims and locators."
        ),
    }
    return {**payload, "plan_sha256": sha256_bytes(canonical(payload))}


def validate_plan(plan: object, expected: str) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("format") != PLAN_FORMAT:
        raise SystemExit("unsupported adoption plan")
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if not expected or plan.get("plan_sha256") != expected or sha256_bytes(canonical(payload)) != expected:
        raise SystemExit("adoption plan is stale or was modified after confirmation")
    return plan


def register(
    scripts: Path,
    target: Path,
    token: str,
    file_path: Path,
    entry: dict[str, Any],
    language: str,
) -> tuple[int, dict[str, Any]]:
    """Register one adopted file through the ordinary source helper.

    Going through the real helper rather than writing the registry directly means
    adoption cannot bypass a single check that a hand-registered source passes.
    """
    command = [
        sys.executable,
        str(scripts / "register_source.py"),
        "--target", str(target),
        "--lock-token", token,
        "--markdown-file", str(file_path),
        "--title", str(entry["title"]),
        "--original-ref", str(entry["path"]),
        "--content-language", language,
        "--source-type", ADOPTED_TYPE,
        "--extractor", "adopt-directory",
        "--confirm-extraction-warnings",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"error": (completed.stderr or completed.stdout or "").strip()}
    return completed.returncode, payload


def apply_plan(
    target: Path,
    root: Path,
    token: str,
    plan: dict[str, Any],
    accepted: list[str],
) -> tuple[dict[str, Any], int]:
    entries = {str(item["path"]): item for item in plan["candidates"]}
    unknown = sorted(set(accepted) - set(entries))
    if unknown:
        return {"state": "invalid_selection", "unknown_paths": unknown, "writes": 0}, 2
    blocked = sorted(path for path in accepted if not entries[path]["adoptable"])
    if blocked:
        return {"state": "blocked_selection", "blocked_paths": blocked, "writes": 0}, 2
    if not accepted:
        return {"state": "nothing_selected", "writes": 0}, 0

    # Re-check every file against the confirmed plan before the first write.
    for relative in accepted:
        path = root / relative
        try:
            digest = sha256_bytes(path.read_bytes())
        except OSError:
            return {"state": "stale_plan", "reason": f"file disappeared: {relative}", "writes": 0}, 3
        if digest != entries[relative]["sha256"]:
            return {"state": "stale_plan", "reason": f"file changed: {relative}", "writes": 0}, 3

    snapshot = create_snapshot(target, token, operation="adopt-directory")
    scripts = Path(__file__).resolve().parent
    language = str(plan.get("content_language") or "und")

    registered: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for relative in accepted:
        code, payload = register(scripts, target, token, root / relative, entries[relative], language)
        if code != 0:
            failures.append({"path": relative, "error": payload.get("error", payload)})
            continue
        record = payload.get("source") if isinstance(payload, dict) else None
        registered.append(
            {
                "path": relative,
                "source_id": (record or {}).get("source_id", ""),
                "registered_as": (record or {}).get("path", ""),
                "duplicate": bool(payload.get("duplicate")),
            }
        )

    return (
        {
            "state": "partial_failure" if failures else "applied",
            "writes": len(registered),
            "snapshot": snapshot,
            "registered": registered,
            "failures": failures,
            "next_steps": [
                "Nothing was added to wiki/. The adopted files are evidence, not knowledge.",
                "Curate the material into pages with their own claims and source locators.",
                "Rebuild the graph, run the strict linter, and publish a release.",
            ],
        },
        4 if failures else 0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="Report what an existing directory offers")
    plan_parser.add_argument("--target", required=True)
    plan_parser.add_argument("--lock-token", required=True)
    plan_parser.add_argument("--source-dir", required=True, help="Existing Markdown collection")
    plan_parser.add_argument("--content-language", default="und")
    plan_parser.add_argument("--output")
    apply_parser = subparsers.add_parser("apply", help="Register the confirmed files as sources")
    apply_parser.add_argument("--target", required=True)
    apply_parser.add_argument("--lock-token", required=True)
    apply_parser.add_argument("--source-dir", required=True)
    apply_parser.add_argument("--plan-file", required=True)
    apply_parser.add_argument("--expect-plan-sha256", required=True)
    apply_parser.add_argument("--accept", action="append", default=[], metavar="PATH")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    root = Path(args.source_dir).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"source directory does not exist: {root}")
    if root == target or target in root.parents or root in target.parents:
        raise SystemExit("the source directory must stay outside the wiki")

    if args.command == "plan":
        plan = build_plan(target, root, args.content_language)
        if args.output:
            output = Path(args.output).expanduser().resolve()
            if output == target or target in output.parents:
                raise SystemExit("the plan must stay outside the target wiki")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    plan = validate_plan(
        json.loads(Path(args.plan_file).read_text(encoding="utf-8")),
        args.expect_plan_sha256,
    )
    result, code = apply_plan(target, root, args.lock_token, plan, list(args.accept))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
