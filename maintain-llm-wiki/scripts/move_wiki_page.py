#!/usr/bin/env python3
"""Preview or apply a safe wiki-page move and rewrite internal wikilinks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from snapshot_wiki import create_snapshot
from wiki_lock import require_lock


WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
PROTECTED_PAGES = {"wiki/index.md", "wiki/overview.md"}


def portable_wiki_path(value: str) -> bool:
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or PurePosixPath(normalized).is_absolute() or PureWindowsPath(normalized).is_absolute():
        return False
    return ".." not in path.parts and normalized.startswith("wiki/") and normalized.endswith(".md")


def link_target(raw: str) -> str:
    value = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return value.removesuffix(".md").lstrip("./")


def rewrite_links(text: str, old_target: str, new_target: str) -> tuple[str, int]:
    replacements = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacements
        raw = match.group(1)
        if link_target(raw) != old_target:
            return match.group(0)
        target_and_anchor, separator, alias = raw.partition("|")
        _, anchor_separator, anchor = target_and_anchor.partition("#")
        updated = new_target
        if anchor_separator:
            updated += "#" + anchor
        if separator:
            updated += "|" + alias
        replacements += 1
        return "[[" + updated + "]]"

    return WIKILINK.sub(replace, text), replacements


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Target wiki directory")
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--from-path", required=True, help="Existing vault-relative Markdown path")
    parser.add_argument("--to-path", required=True, help="New vault-relative Markdown path")
    parser.add_argument("--apply", action="store_true", help="Apply the move after the user approves the preview")
    parser.add_argument("--expect-preview-sha256", help="Required with --apply; binds the write to the approved preview")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    old_relative = args.from_path.replace("\\", "/").strip()
    new_relative = args.to_path.replace("\\", "/").strip()
    for label, value in (("from-path", old_relative), ("to-path", new_relative)):
        if not portable_wiki_path(value):
            raise SystemExit(f"{label} must be a portable .md path below wiki/")
    if old_relative in PROTECTED_PAGES:
        raise SystemExit("wiki/index.md and wiki/overview.md cannot be moved by category migration")
    if old_relative == new_relative:
        raise SystemExit("from-path and to-path must differ")

    source = target / old_relative
    destination = target / new_relative
    if not (target / "WIKI.md").is_file() or not source.is_file():
        raise SystemExit("Target or source page does not exist")
    if source.is_symlink():
        raise SystemExit("Source page may not be a symbolic link")
    if destination.exists():
        raise SystemExit("Destination already exists; refusing to overwrite")

    old_target = old_relative.removesuffix(".md")
    new_target = new_relative.removesuffix(".md")
    affected: list[dict[str, object]] = []
    for path in sorted(target.rglob("*.md")):
        relative = path.relative_to(target).as_posix()
        if relative.startswith("meta/history/"):
            continue
        if path.is_symlink():
            raise SystemExit(f"Move planning refuses symbolic link: {relative}")
        _, count = rewrite_links(path.read_text(encoding="utf-8"), old_target, new_target)
        if count:
            affected.append({"path": relative, "links": count})

    precondition_paths = sorted({old_relative, *(str(item["path"]) for item in affected)})
    plan: dict[str, object] = {
        "from": old_relative,
        "to": new_relative,
        "affected_files": affected,
        "preconditions": [
            {"path": relative, "sha256": sha256_file(target / relative)}
            for relative in precondition_paths
        ],
        "destination_must_not_exist": True,
        "external_link_warning": "Links stored outside this wiki cannot be rewritten automatically.",
    }
    preview_sha256 = plan_hash(plan)
    report: dict[str, object] = {"mode": "apply" if args.apply else "preview", **plan, "preview_sha256": preview_sha256}
    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if not args.expect_preview_sha256:
        raise SystemExit("--expect-preview-sha256 is required with --apply")
    if args.expect_preview_sha256 != preview_sha256:
        raise SystemExit("Move preview is stale or differs from the approved preview; no files were changed")

    snapshot = create_snapshot(
        target,
        args.lock_token,
        operation=f"move:{old_relative}->{new_relative}",
        selected_files=[*precondition_paths, new_relative],
    )
    report["snapshot"] = snapshot["snapshot"]

    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)
    rewritten: list[dict[str, object]] = []
    for path in sorted(target.rglob("*.md")):
        relative = path.relative_to(target).as_posix()
        if relative.startswith("meta/history/"):
            continue
        original = path.read_text(encoding="utf-8")
        updated, count = rewrite_links(original, old_target, new_target)
        if count:
            path.write_text(updated, encoding="utf-8")
            rewritten.append({"path": relative, "links": count})
    report["rewritten_files"] = rewritten
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
