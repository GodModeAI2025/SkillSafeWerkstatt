#!/usr/bin/env python3
"""Return the machine-readable action catalog of the maintenance skill."""

from __future__ import annotations

import json


SELECTOR = {
    "type": "all | paths | filter",
    "operators": ["exists", "not_exists", "equals", "not_equals", "contains", "not_contains", "starts_with", "ends_with", "is_empty", "is_not_empty", "is_list", "is_string", "in_path"],
    "virtual_properties": ["__path", "__folder", "__filename", "__extension"],
    "combinators": ["AND", "OR"],
}


def action(action_id: str, helper: str, description: str, parameters: list[dict[str, object]], *, writes: bool, preview: bool = False, snapshot: bool = False, confirmation: bool = False) -> dict[str, object]:
    return {"id": action_id, "helper": helper, "description": description, "parameters": parameters, "writes": writes, "destructive": confirmation, "preview": preview, "snapshot": snapshot, "confirmation_required": confirmation, "lock_required": writes or helper not in {"plan_identity.py", "verify_release.py", "export_wiki_skill.py"}}


CATALOG = {
    "format": "lmwiki-action-catalog/1",
    "skill": "maintain-llm-wiki",
    "selector": SELECTOR,
    "actions": [
        action("plan-identity", "plan_identity.py", "Render a hash-bound SOUL and content-policy proposal without touching a wiki.", [{"name": "input", "type": "identity JSON", "required": True}], writes=False, preview=True, confirmation=True),
        action("apply-identity", "apply_identity.py", "Apply only a confirmed identity proposal and snapshot prior identity files.", [{"name": "plan_file", "type": "path", "required": True}, {"name": "expect_proposal_sha256", "type": "sha256", "required": True}], writes=True, snapshot=True, confirmation=True),
        action("initialize", "initialize_wiki.py", "Build and release a new wiki in staging, then commit it without exposing a lock token.", [{"name": "target", "type": "path", "required": True}, {"name": "title", "type": "string", "required": True}, {"name": "topic", "type": "string", "required": True}, {"name": "wiki_language", "type": "BCP-47 string", "required": True}, {"name": "identity_plan", "type": "confirmed plan path", "required": True}, {"name": "expect_identity_sha256", "type": "sha256", "required": True}], writes=True, snapshot=False, confirmation=True),
        action("validate-extraction", "validate_extraction.py", "Assess UTF-8, flattening, page markers, headings, and table structure before registration.", [{"name": "markdown_file", "type": "runtime path", "required": True}, {"name": "source_type", "type": "string", "required": False}], writes=False),
        action("register-source", "register_source.py", "Register faithful Markdown source evidence without storing an absolute source path.", [{"name": "markdown_file", "type": "runtime path", "required": True}, {"name": "title", "type": "string", "required": True}, {"name": "original_ref", "type": "portable reference", "required": True}], writes=True),
        action("inventory-frontmatter", "inventory_wiki.py", "Return property counts, observed types, samples, and schema drift.", [], writes=False),
        action("plan-frontmatter", "frontmatter_actions.py plan", "Resolve a selector and create an immutable before/after plan with file hashes.", [{"name": "selector", "type": "selector", "required": True}, {"name": "action", "type": "frontmatter action", "required": True}, {"name": "output", "type": "temporary plan path", "required": True}], writes=False, preview=True),
        action("apply-frontmatter", "frontmatter_actions.py apply", "Apply exactly a confirmed plan when every file still matches its precondition hash.", [{"name": "plan_file", "type": "path", "required": True}, {"name": "expect_plan_sha256", "type": "sha256", "required": True}], writes=True, snapshot=True, confirmation=True),
        action("snapshot", "snapshot_wiki.py", "Create a portable pre-change snapshot with its own file manifest.", [{"name": "operation", "type": "string", "required": False}], writes=True),
        action("list-snapshots", "restore_wiki.py list", "List valid and invalid recovery snapshots.", [], writes=False),
        action("plan-restore", "restore_wiki.py plan", "Preview a targeted restore with current and snapshot hashes.", [{"name": "snapshot_id", "type": "string", "required": True}, {"name": "paths", "type": "string[]", "required": False}], writes=False, preview=True),
        action("apply-restore", "restore_wiki.py apply", "Restore only a confirmed hash-bound plan and create a recovery snapshot first.", [{"name": "plan_file", "type": "path", "required": True}, {"name": "expect_plan_sha256", "type": "sha256", "required": True}], writes=True, snapshot=True, confirmation=True),
        action("move-page", "move_wiki_page.py", "Preview or apply a page move while rewriting internal wikilinks.", [{"name": "from_path", "type": "wiki path", "required": True}, {"name": "to_path", "type": "wiki path", "required": True}], writes=True, preview=True, snapshot=True, confirmation=True),
        action("plan-language-migration", "plan_language_migration.py", "Report complete impact of a maintained-language migration.", [{"name": "to_language", "type": "BCP-47 string", "required": True}], writes=False, preview=True),
        action("plan-page-batch", "page_batch.py plan", "Hash a staged wiki-page batch and target preconditions outside the canonical wiki.", [{"name": "staging_dir", "type": "runtime path", "required": True}, {"name": "paths", "type": "wiki path[]", "required": True}], writes=False, preview=True),
        action("apply-page-batch", "page_batch.py apply", "Validate a complete temporary mirror, then commit the batch with atomic per-file replacement and snapshot recovery.", [{"name": "staging_dir", "type": "runtime path", "required": True}, {"name": "plan_file", "type": "path", "required": True}, {"name": "expect_plan_sha256", "type": "sha256", "required": True}], writes=True, snapshot=True),
        action("lint", "lint_wiki.py", "Validate deterministic structure; check-only is no-write and fix-safe permits only deterministic repairs.", [{"name": "fix_safe", "type": "boolean", "required": False}, {"name": "check_only", "type": "boolean", "required": False}], writes=True),
        action("build-graph", "build_graph.py", "Regenerate the offline graph and relative HTML reading views.", [], writes=True),
        action("quality-review-record", "record_quality_review.py", "Record a review only after it actually occurred.", [{"name": "kind", "type": "quality | cleaning", "required": True}, {"name": "outcome", "type": "passed | attention-needed | not-applicable", "required": True}], writes=True),
        action("release", "release_wiki.py", "Idempotently lint, version, record quality status, hash controlled files, and publish the manifest last.", [{"name": "bump", "type": "patch | minor | major", "required": True}, {"name": "operation_id", "type": "portable idempotency key", "required": True}, {"name": "expect_current_version", "type": "semantic version", "required": True}], writes=True),
        action("verify-release", "verify_release.py", "Verify a released snapshot read-only.", [{"name": "expect_manifest_sha256", "type": "sha256", "required": False}], writes=False),
        action("export-frozen-skill", "export_wiki_skill.py", "Export one verified release as an immutable knowledge-only skill.", [{"name": "skill_name", "type": "lowercase-hyphenated", "required": True}], writes=False),
        action(
            "resolve-conflict-copy-plan",
            "resolve_conflict_copy.py",
            "Report synchronization conflict copies with both sides, without changing anything.",
            [],
            writes=False,
        ),
        action(
            "resolve-conflict-copy-apply",
            "resolve_conflict_copy.py",
            "Apply one confirmed, hash-bound conflict resolution after an automatic snapshot.",
            [
                {"name": "plan_file", "type": "string", "required": True},
                {"name": "expect_plan_sha256", "type": "string", "required": True},
                {"name": "decision", "type": "string[]", "required": True},
            ],
            writes=True,
        ),
        action(
            "verify-pages-plan",
            "verify_pages.py",
            "Show which pages a confirmation would cover and the tier it would record.",
            [
                {"name": "actor", "type": "string", "required": True},
                {"name": "page", "type": "string[]", "required": True},
            ],
            writes=False,
        ),
        action(
            "verify-pages-apply",
            "verify_pages.py",
            "Record a confirmed page review after an automatic snapshot; a human actor "
            "additionally requires explicit user confirmation.",
            [
                {"name": "plan_file", "type": "string", "required": True},
                {"name": "expect_plan_sha256", "type": "string", "required": True},
                {"name": "user_confirmed_human_review", "type": "boolean", "required": False},
            ],
            writes=True,
        ),
        action(
            "export-okf-bundle",
            "export_okf_bundle.py",
            "Write one verified release as an OKF v0.2 bundle into a separate destination; "
            "lossy by construction and never modifies the wiki.",
            [
                {"name": "destination", "type": "string", "required": True},
                {"name": "allow_hydration", "type": "boolean", "required": False},
            ],
            writes=False,
        ),
        action("report-okf", "report_okf.py", "Report optional OKF required/recommended field compatibility without mutation.", [{"name": "include_sources", "type": "boolean", "required": False}], writes=False),
    ],
}


if __name__ == "__main__":
    print(json.dumps(CATALOG, ensure_ascii=False, indent=2))
