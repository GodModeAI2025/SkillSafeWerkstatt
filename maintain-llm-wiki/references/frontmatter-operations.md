# Deterministic frontmatter operations

Read this reference only for frontmatter inventory, schema migration, value or link cleaning, targeted restore, action discovery, or OKF reporting. The user continues to interact with the skill in natural language; every command below is an internal agent contract.

## Canonical subset

SkillSafeWerkstatt frontmatter is a deliberately narrow portable YAML subset:

- one top-level mapping;
- safe property names without colons, control characters, or the reserved names `__proto__`, `constructor`, and `prototype`;
- string, integer, finite decimal, boolean, or null scalar values;
- flat lists containing only those scalar types;
- two-space-indented block lists or non-nested inline lists;
- optional full-line comments, which a canonical rewrite retains at the start of the frontmatter block.

Nested mappings, nested lists, block scalars, anchors, aliases, tags, duplicate keys, tab indentation, and malformed quoting are outside the contract. `frontmatter_contract.py` rejects them with a line-specific error. Never guess their meaning or apply a partial transformation. Existing material using unsupported YAML must be reviewed and migrated explicitly before bulk operations.

The canonical writer quotes strings, emits typed booleans/numbers/null, writes non-empty lists in block style, and uses `[]` for an empty list. A plan declares `frontmatter_reformatted: true` when applying it would also canonicalize the representation.

## Inventory and drift

Run the locked `scripts/inventory_wiki.py` before a schema migration or broad cleanup. Its `lmwiki-frontmatter-inventory/1` report contains:

- document counts by wiki page, source, and schema layer;
- property usage counts, observed types, document classes, and bounded samples;
- missing required fields;
- type mismatches for list fields;
- noncanonical property names and a deterministic suggestion;
- compatible extensions, which are findings rather than automatic deletions;
- parser errors, which block a bulk plan.

Do not equate a clean structural inventory with semantic quality. Discuss extension-field removal, merging, or renaming when meaning could change.

## Selectors

Selectors are JSON objects and are validated before any file is selected:

```json
{"kind":"all"}
```

```json
{"kind":"paths","paths":["wiki/topics/example.md"]}
```

```json
{
  "kind": "filter",
  "combinator": "AND",
  "conditions": [
    {"property":"status","operator":"equals","value":"active"},
    {"property":"concepts","operator":"contains","value":"access-control"}
  ]
}
```

Supported operators are `exists`, `not_exists`, `equals`, `not_equals`, `contains`, `not_contains`, `starts_with`, `ends_with`, `is_empty`, `is_not_empty`, `is_list`, `is_string`, and `in_path`. Conditions may set `case_sensitive: true`. Virtual properties are `__path`, `__folder`, `__filename`, and `__extension`. Arbitrary regular expressions are intentionally unsupported.

## Action schemas

`frontmatter_actions.py` accepts these action objects:

```json
{"type":"set","property":"aliases","value":["Alternate"],"mode":"skip"}
{"type":"delete","properties":["legacy_field"]}
{"type":"rename","from_properties":["Category"],"to_property":"type","on_conflict":"skip"}
{"type":"copy","from_properties":["updated"],"to_property":"timestamp","on_conflict":"skip"}
{"type":"merge","from_properties":["keywords","Tags"],"to_property":"tags","on_conflict":"merge_list"}
{"type":"normalize_values","property":"tags","transforms":["trim","lowercase"],"mappings":[{"from":"n/a","to":""}],"preserve_wikilinks":true}
{"type":"dedupe_wikilinks","properties":["sources","aliases"]}
```

Conflict modes are `skip`, `overwrite`, and `merge_list`. Normalization transforms are `trim`, `lowercase`, `titlecase`, and `strip_diacritics`. An empty mapping target removes that list value. Preserve wikilinks during ordinary value normalization and use `dedupe_wikilinks` for link-specific work.

Wikilink cleanup resolves only a complete vault-relative target or an unambiguous basename. It preserves `#subpaths` and display aliases, collapses only links proven to share the same target/subpath/alias identity, and deduplicates unresolved links only when their raw strings are identical.

Never normalize stable IDs, claim text, source titles, source locators, `original_ref`, hashes, or protected human content merely for visual consistency.

`stale_after` is a statement about content, not metadata hygiene. A bulk `set` that gives many pages the same expiry asserts something about each of them that the sources may not support, so plan it only when the user names a date that genuinely applies to the whole selection, and show which pages it would touch. A bulk `delete` of the field is equally a claim - that those pages no longer have an end date - and needs the same confirmation. Neither operation may be applied as cleanup.

## Plan and apply

Create the plan while holding the writer lock:

```text
<python> <skill-root>/scripts/run_locked.py --token-file <private-runtime-file> --helper frontmatter_actions.py plan --target <wiki> --selector-json <selector-json> --action-json <action-json> --output <temporary-plan-file>
```

The plan contains only relative wiki paths, its normalized selector and action, file-level before hashes, computed after hashes, before/after frontmatter, skip reasons, link-cleaning details, and one `plan_sha256`. Store it only in the active temporary workspace; it is not canonical wiki content.

Show the selected paths, changed and skipped counts, material before/after differences, parser errors, destructive flag, and plan hash. Meaning-changing, deleting, overwriting, normalizing, deduplicating, or source-field operations require explicit user confirmation. A compatible additive change may proceed only when the user's request already authorizes that concrete change.

Apply exactly the approved plan:

```text
<python> <skill-root>/scripts/run_locked.py --token-file <private-runtime-file> --helper frontmatter_actions.py apply --target <wiki> --plan-file <temporary-plan-file> --expect-plan-sha256 <approved-hash> [--confirm-destructive]
```

Apply validates the plan hash, checks every current file against its recorded before hash before writing anything, and checks again immediately before each write. Any preflight mismatch returns `stale_plan` with zero writes. Discard the plan, inspect the concurrent change, and generate a new proposal; never bypass the hash. Apply creates a targeted `lmwiki-snapshot/1` recovery snapshot before its first write and records its result under that snapshot. A mid-run external edit can still produce `partial_failure`; retain the lock and either finish a repaired release or use the confirmed restore workflow.

## Snapshots and targeted restore

New snapshots contain `snapshot.json` with snapshot ID, time, operation, public lock ID, relative file paths, sizes, SHA-256 hashes, and explicitly missing selected paths. Historical snapshot content remains outside the active release manifest and is never pruned automatically.

List snapshots internally with `restore_wiki.py list`. To restore, first run `restore_wiki.py plan` with a snapshot ID and optional relative path list. Missing current files are skipped unless the user explicitly approves `--include-missing`. Show the plan and obtain confirmation, then call `restore_wiki.py apply` with both `--expect-plan-sha256` and `--confirm-restore`.

Restore refuses stale current files or changed snapshot content and creates a recovery snapshot of the pre-restore state. It never deletes a current file merely because it was absent from the older snapshot. A successful restore is an unreleased maintained state: rebuild affected generated artifacts, lint, publish one appropriate release, verify it, and only then release the writer lock.

## Self-description, trust, and OKF

`scripts/describe_actions.py` returns the complete machine-readable maintenance surface. It describes capability and grants no authority; confirmation and safety rules are unchanged by it.

`scripts/verify_pages.py` records who confirmed individual pages. `plan` shows the pages, the tier before and after, and the file hashes; `apply` requires that plan hash, snapshots first, and performs zero writes on a stale plan. A `human:` actor additionally requires `--user-confirmed-human-review`, which may be passed only after the named person confirmed the review. An index cannot be confirmed because it carries no assertions.

`scripts/resolve_conflict_copy.py` resolves what a synchronization client left behind. `plan` shows each conflict copy beside its original with hashes, sizes, and modification times and changes nothing; an identical copy is recommended for removal and a diverged one is left to the user. `apply` takes one decision per copy - `keep-original`, `keep-copy`, or `keep-both` - snapshots first, and renames a kept copy to a name the storage layer accepts.

Run locked `scripts/report_okf.py` only when the user asks about interoperability or an OKF migration. The `lmwiki-okf-compatibility/2` result checks the required `type`, the recommended `title`, `description`, `resource`, and `tags`, and the v0.2 `status`, `stale_after`, `generated`, and `verified`. `timestamp` is not an OKF field and is no longer checked. Suggestions remain proposals; nothing is invented. Unknown SkillSafeWerkstatt fields are preserved.

`scripts/export_okf_bundle.py` writes a verified release as an OKF v0.2 bundle into an empty destination outside the wiki. It takes no lock token by design. Registered source extractions travel with the bundle unless `--no-sources` is passed, the change record becomes the reserved `log.md`, and the result is validated against the conformance rules before success is reported; a bundle that fails is removed rather than shipped. The bundle documents its own losses; OKF never replaces claims, source locators, clusters, controlled concepts, quality policy, history, or release integrity.
