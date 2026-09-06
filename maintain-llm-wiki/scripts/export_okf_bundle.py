#!/usr/bin/env python3
"""Export one verified release as an Open Knowledge Format v0.2 bundle.

The export is read-only with respect to the wiki and writes only into a
separately chosen destination. It is deliberately lossy: OKF has no equivalent
for claim-level evidence, the release manifest, snapshots, the confirmed
identity, or controlled concept worlds. Every bundle therefore carries a README
that names what did not come with it, so nobody mistakes the export for the
wiki.

Nothing is invented. A recommended field the wiki does not hold is left out and
reported, never filled with a guess.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

import okf_contract
import trust_contract
from frontmatter_contract import FrontmatterError, parse_document
from verify_release import verify_snapshot


BUNDLE_FORMAT = "lmwiki-okf-export/1"
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def yaml_scalar(value: Any) -> str:
    """Render one scalar for OKF frontmatter, quoting conservatively."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_frontmatter(data: dict[str, Any]) -> str:
    """Render the OKF frontmatter, including the nested forms OKF expects."""
    lines = ["---"]
    for key, value in data.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            inline = ", ".join(f"{name}: {yaml_scalar(item)}" for name, item in value.items())
            lines.append(f"{key}: {{ {inline} }}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    first = True
                    for name, inner in item.items():
                        prefix = "  - " if first else "    "
                        lines.append(f"{prefix}{name}: {yaml_scalar(inner)}")
                        first = False
                else:
                    lines.append(f"  - {yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def bundle_relative_link(raw: str) -> str:
    """Rewrite one wikilink into an OKF bundle-relative link."""
    target, _, label = raw.partition("|")
    target = target.split("#", 1)[0].strip().removesuffix(".md").lstrip("./")
    text = label.strip() or PurePosixPath(target).name
    return f"[{text}](/{target}.md)"


def convert_body(body: str) -> str:
    """Convert wikilinks to Markdown links and strip claim markers.

    The visible claim text is kept because it is the maintained statement. The
    machine-readable evidence around it is dropped, which is the single largest
    thing an OKF bundle cannot carry.
    """
    without_claims = re.sub(
        r"<!--\s*claim\s*\n.*?-->\s*(.*?)\s*<!--\s*/claim\s*-->",
        lambda match: match.group(1),
        body,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return WIKILINK.sub(lambda match: bundle_relative_link(match.group(1)), without_claims)


def load_registry(path: Path) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return registry
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("source_id"), str):
            registry[record["source_id"]] = record
    return registry


def convert_page(
    data: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Map one wiki page onto OKF frontmatter, reporting what was left out."""
    omitted: list[str] = []
    okf: dict[str, Any] = {"type": str(data.get("type") or "Concept")}

    for field in ("title", "description"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            okf[field] = value
        else:
            omitted.append(field)

    tags = data.get("tags")
    if isinstance(tags, list) and tags:
        okf["tags"] = [str(tag) for tag in tags]
    else:
        omitted.append("tags")

    okf["status"] = okf_contract.okf_status(data.get("status"))
    note = okf_contract.status_note(data.get("status"))

    generated = okf_contract.actor_record(
        data.get(trust_contract.GENERATED_BY), data.get(trust_contract.GENERATED_AT)
    )
    if generated:
        okf["generated"] = generated
    verified = okf_contract.actor_record(
        data.get(trust_contract.VERIFIED_BY), data.get(trust_contract.VERIFIED_AT)
    )
    if verified:
        okf["verified"] = verified

    sources = okf_contract.source_records(data.get("sources"), registry)
    if sources:
        okf["sources"] = sources

    # `resource` identifies the underlying asset. The wiki holds no such URI for
    # a curated page, so it is reported as missing rather than fabricated.
    omitted.append("resource")
    return okf, ([note] if note else []) + [f"missing recommended field: {field}" for field in omitted]


def build_index(pages: list[dict[str, Any]], title: str, topic: str) -> str:
    """Build the bundle root index. Per the spec it carries okf_version only."""
    lines = [
        "---",
        f'okf_version: "{okf_contract.OKF_VERSION}"',
        "---",
        "",
        f"# {title}",
        "",
        topic,
        "",
        "## Concepts",
        "",
    ]
    for page in sorted(pages, key=lambda item: str(item["path"])):
        label = str(page["title"] or PurePosixPath(str(page["path"])).stem)
        lines.append(f"- [{label}](/{page['path']}) — {page['status']}, {page['trust_tier']}")
    return "\n".join(lines) + "\n"


def build_readme(version: str, release_id: str, findings: list[dict[str, Any]]) -> str:
    lines = [
        "# What this bundle is, and what it is not",
        "",
        f"This is an Open Knowledge Format v{okf_contract.OKF_VERSION} export of "
        f"SkillSafeWerkstatt release {version} ({release_id}).",
        "",
        "It is an interoperability view of a wiki, not the wiki. The following does not "
        "exist in this bundle and cannot be reconstructed from it:",
        "",
    ]
    lines.extend(f"- {item}" for item in okf_contract.NOT_EXPORTED)
    lines.extend(
        [
            "",
            "## Fields that could not be filled",
            "",
            "The export never invents a value. Where a recommended field had no basis in the "
            "wiki, it was left out and listed here.",
            "",
        ]
    )
    if findings:
        for finding in findings:
            for note in finding["notes"]:
                lines.append(f"- `{finding['path']}`: {note}")
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Getting the current state",
            "",
            "Maintain and release the canonical wiki, then export again. Editing this bundle "
            "does not change the wiki and the change would be lost on the next export.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--destination", required=True, help="Empty or non-existing output directory")
    parser.add_argument("--allow-hydration", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    destination = Path(args.destination).expanduser().resolve()
    if destination == target or target in destination.parents or destination in target.parents:
        raise SystemExit("the export destination must stay outside the wiki")
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"export destination is not empty: {destination}")

    # An export must describe one published state, so it is bound to a verified
    # release rather than to whatever happens to be on disk. It deliberately runs
    # without a maintenance lock: an active lock means maintenance is in flight,
    # and a half-finished state must not be exported at all.
    verification = verify_snapshot(target, allow_hydration=bool(args.allow_hydration))
    if verification.get("state") != "ready":
        print(json.dumps({"state": "not_exported", "verification": verification}, indent=2))
        return 4

    registry = load_registry(target / "meta/sources.jsonl")
    wiki_root = target / "wiki"
    pages: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    staged: list[tuple[str, str]] = []

    for path in sorted(wiki_root.rglob("*.md")):
        relative = path.relative_to(target).as_posix()
        try:
            document = parse_document(
                path.read_text(encoding="utf-8"), relative, require_frontmatter=True
            )
        except (OSError, UnicodeError, FrontmatterError) as exc:
            raise SystemExit(f"{relative}: {exc}") from exc
        if document.data.get("type") == "index":
            # The bundle root index is generated; a wiki index has no OKF role.
            continue
        okf, notes = convert_page(document.data, registry)
        bundle_path = relative.removeprefix("wiki/")
        staged.append((bundle_path, render_frontmatter(okf) + convert_body(document.body)))
        pages.append(
            {
                "path": bundle_path,
                "title": okf.get("title", ""),
                "status": okf["status"],
                "trust_tier": trust_contract.trust_tier(document.data),
            }
        )
        if notes:
            findings.append({"path": bundle_path, "notes": notes})

    destination.mkdir(parents=True, exist_ok=True)
    try:
        for bundle_path, content in staged:
            output = destination / bundle_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
        heading = next(
            (
                line.lstrip("# ").strip()
                for line in (target / "WIKI.md").read_text(encoding="utf-8").splitlines()
                if line.startswith("#")
            ),
            "",
        )
        (destination / "index.md").write_text(
            build_index(pages, heading or "Wiki", f"Exported from SkillSafeWerkstatt release "
                                                f"{verification['version']}."),
            encoding="utf-8",
        )
        (destination / "README.md").write_text(
            build_readme(str(verification["version"]), str(verification["release_id"]), findings),
            encoding="utf-8",
        )
    except OSError:
        # A partial bundle would misrepresent the release, so leave none behind.
        shutil.rmtree(destination, ignore_errors=True)
        raise

    print(
        json.dumps(
            {
                "state": "exported",
                "format": BUNDLE_FORMAT,
                "okf_version": okf_contract.OKF_VERSION,
                "source_release": {
                    "version": verification["version"],
                    "release_id": verification["release_id"],
                    "manifest_sha256": verification["manifest_sha256"],
                },
                "documents": len(pages),
                "unfilled_fields": findings,
                "not_exported": list(okf_contract.NOT_EXPORTED),
                "wiki_unchanged": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
