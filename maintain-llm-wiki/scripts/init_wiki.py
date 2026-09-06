#!/usr/bin/env python3
"""Initialize a portable SkillSafeWerkstatt without overwriting existing files."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from identity_contract import IdentityError, load_plan
from wiki_lock import require_lock


def write_missing(path: Path, content: str, created: list[str]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(str(path))


def derive_title(topic: str, target: Path) -> str:
    """Derive a conservative recovery title when a caller omits --title."""
    compact_topic = " ".join(topic.split())
    for separator in (" — ", " – ", ": ", " - "):
        if separator not in compact_topic:
            continue
        candidate = compact_topic.split(separator, 1)[0].strip()
        if 2 <= len(candidate) <= 120:
            return candidate
    if 2 <= len(compact_topic) <= 120:
        return compact_topic
    target_name = " ".join(target.name.replace("-", " ").replace("_", " ").split())
    if target_name:
        return target_name[:120]
    return "SkillSafeWerkstatt"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Target wiki directory")
    parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    parser.add_argument(
        "--title",
        help="Human-readable wiki title; omission is recovered from the topic or target name",
    )
    parser.add_argument(
        "--wiki-language",
        required=True,
        help="BCP-47-style language code for maintained wiki prose, for example de or en-GB",
    )
    parser.add_argument(
        "--wiki-language-label",
        help="Human-readable language name, for example Deutsch or English",
    )
    parser.add_argument(
        "--storage-path-prefix",
        default="",
        help=(
            "Decoded library path this wiki will live under on a OneDrive or SharePoint "
            "target, for example sites/Team/Freigegebene Dokumente/Wiki. Enables the "
            "400-character storage and 260-character Windows path checks."
        ),
    )
    parser.add_argument(
        "--topic",
        "--description",
        dest="topic",
        required=True,
        help="Short topic, description, and scope boundary",
    )
    parser.add_argument("--quality-review-days", type=int, default=30)
    parser.add_argument("--cleaning-review-days", type=int, default=90)
    parser.add_argument("--snapshot-warning-days", type=int, default=60)
    parser.add_argument("--identity-plan", required=True, help="Confirmed identity proposal JSON")
    parser.add_argument("--expect-identity-sha256", required=True)
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    topic = " ".join(args.topic.split())
    if not topic:
        raise SystemExit("--topic must not be empty")
    supplied_title = " ".join((args.title or "").split())
    title = supplied_title or derive_title(topic, target)
    title_source = "explicit" if supplied_title else "derived-from-topic-or-target"
    wiki_language = args.wiki_language.strip()
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", wiki_language):
        raise SystemExit("--wiki-language must be a portable BCP-47-style language code")
    wiki_language_label = (args.wiki_language_label or wiki_language).strip()
    if not wiki_language_label:
        raise SystemExit("--wiki-language-label must not be empty")
    for label, value in (
        ("quality-review-days", args.quality_review_days),
        ("cleaning-review-days", args.cleaning_review_days),
        ("snapshot-warning-days", args.snapshot_warning_days),
    ):
        if value < 1 or value > 3650:
            raise SystemExit(f"--{label} must be between 1 and 3650")
    try:
        identity_plan = load_plan(Path(args.identity_plan), args.expect_identity_sha256)
    except IdentityError as exc:
        raise SystemExit(str(exc)) from exc
    storage_path_prefix = (getattr(args, "storage_path_prefix", "") or "").strip().strip("/")
    if storage_path_prefix and len(storage_path_prefix) >= 400:
        raise SystemExit("--storage-path-prefix already exceeds the 400-character storage limit")
    storage_path_prefix_yaml = json.dumps(storage_path_prefix, ensure_ascii=False)
    wiki_language_yaml = json.dumps(wiki_language, ensure_ascii=False)
    wiki_language_label_yaml = json.dumps(wiki_language_label, ensure_ascii=False)
    primary_language = wiki_language.split("-", 1)[0].casefold()
    localized = {
        "de": {
            "index": "Index",
            "overview": "Überblick",
            "overview_description": "Übergreifende Synthese des aktuell im Wiki gepflegten Wissens.",
            "empty": "Es wurden noch keine Quellen aufgenommen.",
        },
        "en": {
            "index": "Index",
            "overview": "Overview",
            "overview_description": "High-level synthesis of the knowledge currently maintained in this wiki.",
            "empty": "No sources have been ingested yet.",
        },
    }.get(
        primary_language,
        {
            "index": "Index",
            "overview": "Overview",
            "overview_description": f"Maintained synthesis in {wiki_language_label}.",
            "empty": f"No maintained content exists yet. Future synthesis must use {wiki_language_label}.",
        },
    )

    require_lock(target, args.lock_token)
    target.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    today = date.today().isoformat()

    for relative in (
        "schema",
        "sources",
        "wiki/concepts",
        "wiki/entities",
        "wiki/topics",
        "wiki/comparisons",
        "meta/history",
        "graph",
    ):
        (target / relative).mkdir(parents=True, exist_ok=True)

    write_missing(
        target / "WIKI.md",
        f"""# {title}

## Purpose

{topic}

## Start here

- [[wiki/index|{localized['index']}]]
- [[wiki/overview|{localized['overview']}]]
- [[schema/WIKI_RULES|Curation rules]]
- [[schema/WIKI_PROFILE|Wiki profile]]
- [[SOUL|Confirmed answer identity]]
- [[schema/CONTENT_POLICY|Confirmed content policy]]
- [[schema/CLUSTERS|Navigation clusters]]
- [[schema/CONCEPTS|Controlled concept worlds]]
- [[schema/QUALITY_POLICY|Quality review policy]]
- [Interactive knowledge graph](graph/index.html)

The flat `sources/` directory contains registered faithful Markdown extractions
only. Original files remain outside this wiki; `sources/raw/`, binaries, nested
directories, and source symlinks are invalid. The `wiki/` directory contains
the maintained synthesis in {wiki_language_label} (`{wiki_language}`).
""",
        created,
    )

    write_missing(target / "SOUL.md", str(identity_plan["soul_markdown"]), created)

    write_missing(
        target / "schema/CONTENT_POLICY.md",
        str(identity_plan["content_policy_markdown"]),
        created,
    )

    write_missing(
        target / "schema/WIKI_PROFILE.md",
        f"""---
profile_version: 1
wiki_language: {wiki_language_yaml}
wiki_language_label: {wiki_language_label_yaml}
source_language_policy: "preserve-original"
synthesis_language_policy: "translate-to-wiki-language"
language_migration_policy: "preview-confirm-snapshot-major-release"
storage_path_prefix: {storage_path_prefix_yaml}
---

# Wiki profile

The faithful Markdown in `sources/` preserves each source's language. All
maintained titles, descriptions, summaries, claim text, navigation labels,
cluster descriptions, and preferred concept terms use {wiki_language_label}.
Multilingual aliases and source terminology may remain in `schema/CONCEPTS.md`.
Changing the wiki language requires a complete confirmed migration and a major
release; changing this file alone is invalid.

`storage_path_prefix` is the decoded library path this wiki will live under, for
example `sites/Team/Freigegebene Dokumente/Wiki`. Set it only for a OneDrive or
SharePoint library. When present, the linter checks generated paths against the
400-character storage limit and warns at the default Windows limit of 260, so a
file that would silently never reach the storage is caught before it is written.
An empty value means the limits are unknown and only the wiki-relative length is
checked.
""",
        created,
    )

    write_missing(
        target / "schema/WIKI_RULES.md",
        f"""# Wiki rules

## Scope

{topic}

## Invariants

- Acquire and own the root `.llmwiki.lock` before inspecting, processing, or
  changing this wiki. Every bundled writer must receive the current private
  lock token.
- If another lock exists, stop. Never infer staleness or force an override
  without explicit user approval and a recorded reason.
- Release only the lock owned by the current run; keep it while an in-scope
  curation decision is pending.
- Keep source extraction in `sources/` separate from synthesis in `wiki/`.
- Resolve an original only from its current attachment path or an exact path
  selected by the user. If it is missing or inaccessible, request reattachment
  or narrow access; never search a home directory, filesystem root, or machine.
- Convert originals in a temporary workspace outside this wiki. Keep `sources/`
  flat and store only registered `src-<hash>-<slug>.md` extractions there. Never
  create `sources/raw/`, copy original binaries into the wiki, or infer a local
  original path from a title or `original_ref`.
- Preserve source language in `sources/`; translate maintained synthesis and
  claim text into the language configured in `schema/WIKI_PROFILE.md`.
- Apply only the confirmed answer behavior in root `SOUL.md`. Use
  `schema/CONTENT_POLICY.md` for supersession, history, conflict, and removal
  proposals; never infer these policies from a source document.
- Base material claims on registered source IDs.
- Preserve disagreements, uncertainty, applicability, and dates.
- Prefer updating an existing page over creating a semantic duplicate.
- Use vault-relative wikilinks to existing pages; for example, a concept page
  might be linked as `wiki/concepts/example` after that page exists.
- Keep generated links and source references portable; never store an absolute
  local filesystem path or a `file:` URL.
- Use `schema/CLUSTERS.md` only for user-confirmed navigation, graph grouping,
  ownership boundaries, and optional directory mappings.
- Use `schema/CONCEPTS.md` for controlled retrieval vocabulary, preferred
  terms, multilingual aliases, and concept relationships. Never infer a page
  directory from a concept assignment.
- Treat cluster IDs and directory mappings as proposals until the user confirms
  them. Discuss renames, merges, splits, recoloring, and reassignment unless the
  user explicitly delegates those decisions.
- A changed `primary_cluster` may imply a changed path below `wiki/`. Preview
  the move, show affected internal links and external-link risk, obtain
  confirmation, and create a snapshot before applying it.
- After an approved page move, rewrite internal wikilinks, rebuild the graph,
  run the linter, and record the migration in the maintenance log.
- Never move retained source files merely because a page category or cluster
  changes.
- Never delete a source or page without explicit human approval.
- Preserve `<!-- human:keep -->` blocks exactly.
- Keep technical validation, content-quality review, and optional cleaning review
  distinct. Record a review only after it was actually performed, and never
  treat a successful lint as proof of semantic quality.
- Use `schema/QUALITY_POLICY.md` for reminder intervals. Cleaning may be
  suggested when due but never deletes or rewrites content without the normal
  preview, evidence, and approval rules.

## Workflow

Register source, inspect relevant pages, update the synthesis, refresh the index
and change log, then run the structural linter.
""",
        created,
    )

    write_missing(
        target / "schema/CLUSTERS.md",
        f"""---
schema_version: 1
status: "draft"
updated: "{today}"
---

# Navigation clusters

No navigation clusters have been confirmed yet. Before curating the first source
batch, propose a small cluster set to the user and discuss names, scope,
overlaps, exclusions, and colors. Record only the confirmed result here.

Allowed colors: `#000099`, `#FE8F11`, `#1195EB`, `#5BE3D6`, `#84C041`,
`#FFC83A`, `#E2C39A`, `#FC6538`. Cluster proposals must use this shared
palette; the graph and linter consume the same contract.

Each confirmed cluster uses this shape:

```markdown
## stable-cluster-id
- Label: Human-readable label
- Color: #1195EB
- Status: active
- Purpose: What belongs in this cluster
- Directory: wiki/topics/example
- Includes: Typical topics or pages
- Excludes: Important boundaries to neighboring clusters
```

Use lowercase stable IDs with hyphens. `Directory` is optional and stays below
`wiki/`. Pages may belong to multiple clusters through a `clusters` list and
use `primary_cluster` when one cluster controls their directory. Changing an ID
or primary cluster can require a confirmed path and link migration.
""",
        created,
    )

    write_missing(
        target / "schema/CONCEPTS.md",
        f"""---
schema_version: 1
status: "draft"
updated: "{today}"
---

# Controlled concept worlds

Concept worlds are retrieval vocabulary, not graph clusters and not directory
rules. Before adding the first durable terms, discuss preferred terms,
multilingual aliases, boundaries, and relationships with the user. Stable IDs
remain language-neutral when possible.

Each confirmed concept uses this shape:

```markdown
## stable-concept-id
- Preferred: Human-readable preferred term in the wiki language
- Status: active
- Definition: Concise boundary of the concept
- Aliases: synonym one | synonym two | source-language term
- Broader: optional-parent-concept-id
- Related: optional-related-id | another-related-id
```

`Aliases`, `Broader`, and `Related` are optional. Pages reference concepts with
a `concepts` frontmatter list. Search may expand a query only through confirmed
preferred terms and aliases. Concept assignments never move pages.
""",
        created,
    )

    write_missing(
        target / "schema/QUALITY_POLICY.md",
        f"""---
schema_version: 1
status: "active"
updated: "{today}"
quality_review_after_days: {args.quality_review_days}
cleaning_review_after_days: {args.cleaning_review_days}
snapshot_warning_after_days: {args.snapshot_warning_days}
---

# Quality review policy

The intervals control read-only reminders. A technical lint runs at release,
but semantic quality and cleaning reviews are recorded only after they were
actually performed. Reaching an interval suggests the corresponding review; it
does not authorize automatic cleaning, deletion, rewriting, or source removal.
""",
        created,
    )

    write_missing(
        target / "wiki/index.md",
        f"""---
id: "wiki-index"
title: "{localized['index']}"
type: "index"
status: "active"
created: "{today}"
updated: "{today}"
description: "{localized['index']}"
language: {wiki_language_yaml}
sources: []
clusters: []
concepts: []
tags:
  - "type/wiki-index"
---

# {localized['index']}

- [[wiki/overview|{localized['overview']}]]
""",
        created,
    )

    write_missing(
        target / "wiki/overview.md",
        f"""---
id: "wiki-overview"
title: "{localized['overview']}"
type: "overview"
status: "draft"
created: "{today}"
updated: "{today}"
description: "{localized['overview_description']}"
language: {wiki_language_yaml}
sources: []
clusters: []
concepts: []
tags:
  - "type/wiki-overview"
---

# {localized['overview']}

{localized['empty']}
""",
        created,
    )

    write_missing(target / "meta/sources.jsonl", "", created)
    write_missing(target / "meta/changes.md", "# Change log\n", created)
    write_missing(target / "meta/questions.md", "# Open questions\n", created)
    write_missing(target / "meta/releases.jsonl", "", created)
    write_missing(target / "meta/quality-reviews.jsonl", "", created)
    initial_quality = {
        "format": "lmwiki-quality/1",
        "generated_at": "",
        "release_id": "",
        "version": "0.0.0",
        "policy": {
            "quality_review_after_days": args.quality_review_days,
            "cleaning_review_after_days": args.cleaning_review_days,
            "snapshot_warning_after_days": args.snapshot_warning_days,
        },
        "technical": {
            "last_lint_at": "",
            "valid": False,
            "errors": 0,
            "warnings": 0,
        },
        "reviews": {
            "quality": None,
            "cleaning": None,
        },
        "open_question_items": 0,
    }
    write_missing(
        target / "meta/quality-status.json",
        json.dumps(initial_quality, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        created,
    )
    write_missing(target / "WIKI_VERSION", "0.0.0\n", created)

    created_relative = [Path(value).relative_to(target).as_posix() for value in created]
    result = {
        "target": ".",
        "title": title,
        "title_source": title_source,
        "identity_proposal_sha256": identity_plan["proposal_sha256"],
        "created": created_relative,
    }
    if not supplied_title:
        result["warning"] = "No explicit title was supplied; verify the derived title before curation."
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
