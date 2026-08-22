#!/usr/bin/env python3
"""Preview the complete impact of changing SkillSafeWerkstatt's maintained language."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from wiki_lock import require_lock


CLAIM_ID = re.compile(r"\bid:\s*(clm-[0-9a-f]{16})\b")


def profile_language(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise SystemExit("schema/WIKI_PROFILE.md is missing")
    text = path.read_text(encoding="utf-8")
    code = re.search(r'^wiki_language:\s*["\']?([^"\'\s]+)', text, re.MULTILINE)
    label = re.search(r'^wiki_language_label:\s*["\']?(.+?)["\']?\s*$', text, re.MULTILINE)
    if not code or not label:
        raise SystemExit("schema/WIKI_PROFILE.md has no readable wiki language")
    return code.group(1), label.group(1).strip().strip('"\'')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument("--to-language", required=True)
    parser.add_argument("--to-label", required=True)
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    to_language = args.to_language.strip()
    to_label = args.to_label.strip()
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", to_language):
        raise SystemExit("to-language must be a portable BCP-47-style language code")
    if not to_label:
        raise SystemExit("to-label must not be empty")
    current_language, current_label = profile_language(target / "schema/WIKI_PROFILE.md")
    if current_language.casefold() == to_language.casefold():
        raise SystemExit("The requested wiki language is already configured")

    wiki_pages = sorted((target / "wiki").rglob("*.md"))
    claim_count = sum(len(CLAIM_ID.findall(path.read_text(encoding="utf-8"))) for path in wiki_pages)
    schema_files = [
        relative
        for relative in ("schema/CLUSTERS.md", "schema/CONCEPTS.md")
        if (target / relative).is_file()
    ]
    affected = ["WIKI.md", "schema/WIKI_PROFILE.md", *schema_files]
    affected.extend(path.relative_to(target).as_posix() for path in wiki_pages)
    if (target / "SOUL.md").is_file():
        affected.append("SOUL.md")
    if (target / "schema/CONTENT_POLICY.md").is_file():
        affected.append("schema/CONTENT_POLICY.md")

    print(
        json.dumps(
            {
                "mode": "preview",
                "from": {"code": current_language, "label": current_label},
                "to": {"code": to_language, "label": to_label},
                "affected_files": affected,
                "wiki_pages": len(wiki_pages),
                "claim_texts": claim_count,
                "unchanged_source_markdown": len(list((target / "sources").glob("*.md"))),
                "required_actions": [
                    "Obtain explicit user confirmation for the complete migration",
                    "Snapshot the current wiki-controlled files",
                    "Translate maintained page titles, descriptions, prose, and claim text",
                    "Translate cluster labels and descriptions plus preferred concept terms and definitions",
                    "Retain stable IDs, source IDs, source locators, paths, and useful old-language aliases",
                    "Set every wiki page language field and WIKI_PROFILE to the target language",
                    "Rebuild index, graph, reading views, and run strict lint",
                    "Publish one major release and verify its manifest before unlocking",
                ],
                "preserved": [
                    "sources/*.md content and source language",
                    "claim IDs and source locators",
                    "page IDs and default file paths",
                    "human:keep blocks",
                    "historical snapshots",
                ],
                "release_bump": "major",
                "applied": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
