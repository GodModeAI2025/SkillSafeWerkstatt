#!/usr/bin/env python3
"""Generated directory indexes, so orientation stops growing with the wiki.

A single `wiki/index.md` must list every page, so the cost of orienting in a
wiki rises linearly with its size - paid before a single page has been read. A
directory index per branch lets a reader load the root, choose a branch, and
read only that branch.

These are the first generated files inside the curated `wiki/` namespace, which
is why the decision needed care. Two things settle it. First, `wiki/index.md`
already exists there and is already navigation rather than knowledge, with its
own `type: index` that the contract exempts from sources, clusters and claims -
so a branch index extends an existing category instead of introducing a new one.
Second, the alternative of generating them under `graph/` would not reduce what
the reading skill loads as Markdown, which was the entire point.

They are regenerated on every graph build. A hand edit does not survive, and the
linter reports a stale index the same way it reports a stale graph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import portable_io
import trust_contract
from frontmatter_contract import FrontmatterError, parse_document


#: Actor recorded on every generated index, so its origin is visible in the file.
GENERATOR = "process:skillsafewerkstatt-navigation"

#: Directory holding the maintained knowledge layer.
WIKI_DIR = "wiki"

#: Reserved name of an index within its directory.
INDEX_NAME = "index.md"

#: Written into every index so a maintainer knows not to edit it by hand.
GENERATED_NOTICE = (
    "Diese Übersicht wird bei jedem Graphlauf neu erzeugt. Änderungen hier gehen "
    "verloren; pflege stattdessen die verlinkten Seiten."
)

#: Fixed timestamp component, so regenerating an unchanged wiki changes nothing.
STABLE_CREATED = "1970-01-01"


#: Longest description carried into an index. A branch index exists to let a
#: reader choose a page without opening it; a full abstract defeats the saving.
DESCRIPTION_BUDGET = 100

#: Values so common they carry no information when repeated on every line.
QUIET_STATUS = "active"
QUIET_TIER = trust_contract.UNVERIFIED


def render_entry(entry: dict[str, str]) -> str:
    """Render one page line, naming only what differs from the norm.

    Status and trust tier appear only when they are not the ordinary case. On a
    healthy wiki most pages are active and unconfirmed, so repeating that on
    every line would cost tokens to say nothing, and would bury the one page
    that is superseded or the one that a person actually reviewed.
    """
    parts: list[str] = []
    description = " ".join(entry["description"].split())
    if description:
        if len(description) > DESCRIPTION_BUDGET:
            description = description[: DESCRIPTION_BUDGET - 1].rstrip() + "…"
        parts.append(description)
    if entry["status"] and entry["status"] != QUIET_STATUS:
        parts.append(entry["status"])
    if entry["trust_tier"] != QUIET_TIER:
        parts.append(entry["trust_tier"])
    detail = " — ".join(parts)
    return f"- [[{entry['link']}|{entry['title']}]]{f' — {detail}' if detail else ''}"


def _read(path: Path, relative: str) -> Optional[dict[str, Any]]:
    try:
        document = parse_document(
            path.read_text(encoding="utf-8"), relative, require_frontmatter=True
        )
    except (OSError, UnicodeError, FrontmatterError):
        return None
    return document.data


def _label(data: dict[str, Any], path: Path) -> str:
    title = data.get("title")
    return str(title) if isinstance(title, str) and title.strip() else path.stem


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def page_entries(directory: Path, target: Path) -> list[dict[str, str]]:
    """Describe every non-index page directly inside one directory."""
    entries: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == INDEX_NAME:
            continue
        relative = path.relative_to(target).as_posix()
        data = _read(path, relative)
        if data is None:
            continue
        entries.append(
            {
                "link": relative.removesuffix(".md"),
                "title": _label(data, path),
                "description": str(data.get("description") or "").strip(),
                "status": str(data.get("status") or ""),
                "trust_tier": trust_contract.trust_tier(data),
            }
        )
    return entries


def render_index(relative: str, label: str, entries: list[dict[str, str]], updated: str) -> str:
    """Render one directory index as an ordinary wiki page of type `index`."""
    lines = [
        "---",
        f"id: {_quote('wiki-index-' + label)}",
        f"title: {_quote(label.replace('-', ' ').capitalize())}",
        'type: "index"',
        'status: "active"',
        f"created: {_quote(STABLE_CREATED)}",
        f"updated: {_quote(updated)}",
        f"description: {_quote('Übersicht der Seiten unter ' + relative.rsplit('/', 1)[0] + '.')}",
        'language: "de"',
        f"generated_by: {_quote(GENERATOR)}",
        "sources: []",
        "clusters: []",
        "concepts: []",
        "tags:",
        '  - "type/wiki-index"',
        "---",
        "",
        f"# {label.replace('-', ' ').capitalize()}",
        "",
        GENERATED_NOTICE,
        "",
    ]
    if entries:
        for entry in entries:
            lines.append(render_entry(entry))
    else:
        lines.append("Diese Gruppe enthält derzeit keine Seiten.")
    return "\n".join(lines) + "\n"


def expected_indexes(target: Path, updated: str) -> dict[str, str]:
    """Return the index each populated wiki subdirectory should currently have.

    Only directories that actually hold pages get one. An empty group needs no
    navigation, and creating one would add a file nobody asked for.
    """
    root = target / WIKI_DIR
    expected: dict[str, str] = {}
    if not root.is_dir():
        return expected
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        entries = page_entries(directory, target)
        if not entries:
            continue
        relative = (directory / INDEX_NAME).relative_to(target).as_posix()
        expected[relative] = render_index(relative, directory.name, entries, updated)
    return expected


def stale_indexes(target: Path, updated: str) -> list[str]:
    """Report generated indexes that are missing, outdated, or no longer wanted.

    The `updated` field is ignored when comparing, so merely rebuilding on a
    later day never counts as drift.
    """
    expected = expected_indexes(target, updated)
    problems: list[str] = []
    for relative, content in expected.items():
        path = target / relative
        if not path.is_file():
            problems.append(f"{relative}: generated directory index is missing")
        elif _without_updated(path.read_text(encoding="utf-8")) != _without_updated(content):
            problems.append(f"{relative}: generated directory index is stale")
    root = target / WIKI_DIR
    if root.is_dir():
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            relative = (directory / INDEX_NAME).relative_to(target).as_posix()
            if (target / relative).is_file() and relative not in expected:
                problems.append(f"{relative}: directory index is stale; the group holds no pages")
    return problems


def _without_updated(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("updated:")
    )


def write_indexes(target: Path, updated: str) -> list[str]:
    """Create, refresh, or remove the generated indexes. Returns what changed."""
    expected = expected_indexes(target, updated)
    changed: list[str] = []
    for relative, content in expected.items():
        path = target / relative
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if _without_updated(current) == _without_updated(content):
            continue
        portable_io.atomic_write_text(path, content)
        changed.append(relative)
    root = target / WIKI_DIR
    if root.is_dir():
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            relative = (directory / INDEX_NAME).relative_to(target).as_posix()
            path = target / relative
            # A group emptied by a page move keeps no orphan navigation behind.
            if path.is_file() and relative not in expected:
                path.unlink()
                changed.append(relative)
    return changed


def listing_indexes(target: Path) -> dict[str, str]:
    """Map each wiki page to the index that is allowed to list it.

    A page in a subdirectory belongs to that directory's index; a page directly
    under `wiki/` belongs to the root index.
    """
    mapping: dict[str, str] = {}
    root = target / WIKI_DIR
    if not root.is_dir():
        return mapping
    for path in sorted(root.rglob("*.md")):
        if path.name == INDEX_NAME:
            continue
        relative = path.relative_to(target).as_posix()
        parent = path.parent
        candidate = (parent / INDEX_NAME).relative_to(target).as_posix()
        mapping[relative] = candidate if parent != root else f"{WIKI_DIR}/{INDEX_NAME}"
    return mapping
