---
name: maintain-llm-wiki
description: Create, maintain, inventory, migrate, recover, quality-review, optionally clean, release, or export an evidence-linked SkillSafeWerkstatt Markdown wiki. Use whenever the user wants to initialize or extend this wiki, ingest documents as Markdown, curate claims, clusters or concepts, clean metadata, restore files, record who reviewed which pages, resolve a OneDrive or SharePoint conflict copy, publish a release, or export a frozen read-only knowledge skill or an Open Knowledge Format bundle in Claude Code, Claude Cowork, or Codex.
---

# Maintain SkillSafeWerkstatt

Build a durable, self-describing wiki in the user-supplied target directory. Treat that directory as the only canonical output. Which storage backs it later - SharePoint, OneDrive, Git, or a plain disk - does not change the file format. It does change what can happen to those files: a synchronization client writes into the directory on its own and defers writes for an unbounded time, so its behaviour is part of this skill's concern even though the storage itself is not managed here. See the contract section on synchronized storage.

Before creating, ingesting, repairing, linting, releasing, or exporting a wiki, read [references/wiki-contract.md](references/wiki-contract.md) and [references/adapted-vault-standards.md](references/adapted-vault-standards.md) completely. For frontmatter inventory, schema migration, value or link cleaning, targeted restore, action discovery, trust-tier confirmation, conflict-copy resolution, or OKF reporting and export, additionally read [references/frontmatter-operations.md](references/frontmatter-operations.md) completely. Resolve these files relative to this `SKILL.md`, not relative to the current project. If the target already contains its own `STANDARDS.md`, read it and treat its compatible local conventions as authoritative over the standalone defaults.

## User-facing skill interface

The user interacts only with this skill in natural language. Never require or instruct the user to invoke Python, a bundled script, a shell command, or the exporter directly. Ask only for the content-level inputs that are genuinely missing, such as the wiki directory, export destination, or desired skill name. The active agent resolves and runs all bundled helpers internally as implementation details, validates their results, and returns the finished wiki or skill package.

For every new wiki, begin before any lock or write with this conversational invitation, translated when necessary: “Bevor ich den Wissensraum anlege, möchte ich gemeinsam mit dir seine Identität festlegen. Ich stelle dir nacheinander wenige gezielte Fragen zu Zweck und Wissensarten, Zielgruppe, Tonalität und Antwortstil sowie Grenzen und Tabus. Anschließend fasse ich deine Antworten als vollständigen Vorschlag für die `SOUL.md` zusammen. Bis du diesen Vorschlag ausdrücklich bestätigt hast, lege ich keine Dateien an und ändere nichts.” Ask only one focused question at a time, starting with the purpose and knowledge types. Also establish the history/update model, supersession behavior, and removal boundary for `schema/CONTENT_POLICY.md`. Do not acquire the target lock, create the target structure, or write either file during this interview.

After the answers are complete, use `scripts/plan_identity.py` internally to render one hash-bound proposal containing both files. Show the complete proposed `SOUL.md`, the material content-policy choices, and `proposal_sha256`. Apply only that exact proposal after explicit confirmation. A correction creates a new proposal and invalidates the prior hash. The user may explicitly confirm sensible defaults, but silence is never confirmation.

Example user requests include “Exportiere dieses Wiki als unveränderlichen Wissens-Skill” and “Erzeuge aus diesem Wiki den Skill `produktwissen` im Zielverzeichnis”. Do not turn either request into a command-line tutorial. Bundled scripts remain private deterministic resources of the skill, as allowed by the Agent Skills structure; they are not separate products or user-facing prerequisites.

## Portability and runtime

Treat the directory containing this `SKILL.md` as `<skill-root>`. Never assume that the current working directory is the skill directory, and never persist `<skill-root>` or another machine-specific absolute path in the wiki.

- In Claude Code, use `${CLAUDE_SKILL_DIR}` whenever a bundled script or reference must be resolved. For example: `python3 "${CLAUDE_SKILL_DIR}/scripts/init_wiki.py" ...`.
- In Codex or another Agent Skills host, resolve the same file relative to the loaded `SKILL.md`. If the terminal supports a working directory, set it to `<skill-root>` and invoke `scripts/<name>.py` from there.
- Use Python 3.9 or newer. On macOS or Linux, prefer `python3`. On Windows, use `py -3` or `python` when `python3` is unavailable. The bundled scripts use only the Python standard library; do not rely on a POSIX shebang, `chmod`, or Bash-specific behavior.
- Runtime inputs may point anywhere the user authorizes, but generated Markdown, JSON, HTML, links, source metadata, helper reports, and user-facing result paths must remain portable and relative to the relevant wiki, skill, or selected output directory. Store vault-relative POSIX-style paths, relative links, URLs, SharePoint item identifiers, content hashes, or user-supplied logical references. Never persist or report an absolute local filesystem path, home-relative path, parent traversal, or `file:` URL. Internal path resolution is allowed only transiently during execution.

## Exclusive maintenance lock

Every mutating or maintenance invocation of this skill, including initialize, ingest, maintain, repair, migrate, release, and lint, must own the target wiki's cooperative lock for its entire lifetime. Resolve the target, then acquire the lock before inspecting wiki contents, converting sources, invoking another bundled process, or changing any target file. Read-only consumers use the separate query skill and verify a released manifest instead of taking this exclusive lock:

```text
<python> <skill-root>/scripts/wiki_lock.py acquire --target <wiki> --owner <agent-or-run-id> --operation <short-description> --token-file <private-runtime-file>
```

The command atomically creates `<wiki>/.llmwiki.lock`, writes the private capability to a mode-0600 runtime file outside the wiki, and never prints the token. Invoke allowlisted writers through `scripts/run_locked.py --token-file <runtime-file> --helper <helper> ...`; never read, print, interpolate, or delegate the token. A delegated agent may draft only in an external staging directory and must never receive the token, invoke a locked writer, or write the canonical target. Verify ownership after a long wait or user decision:

```text
<python> <skill-root>/scripts/wiki_lock.py verify --target <wiki> --token-file <private-runtime-file>
```

If normal acquisition reports an existing lock, stop before starting any wiki process and report the public owner, operation, and acquisition time. Do not infer that a lock is stale, do not reuse another run's token, and do not delete or replace the file manually.

For a standalone request that only initializes and publishes an empty wiki foundation, use `scripts/initialize_wiki.py` instead of acquiring the lock separately. That deterministic wrapper acquires the lock internally, invokes initialization, builds the graph, lints, publishes version `0.1.0`, and releases the lock on success or failure. Its top-level invocation contains no lock token. Do not call it while already holding a lock or for an existing initialized wiki.

An explicit emergency override exists, but use it only after the user confirms that the prior run may be displaced:

```text
<python> <skill-root>/scripts/wiki_lock.py acquire --target <wiki> --owner <agent-or-run-id> --operation <short-description> --token-file <private-runtime-file> --force --reason <approved-reason>
```

Force acquisition atomically replaces the prior lock and invalidates its token for future bundled processes; it cannot terminate an already running external process. Explain that residual risk before requesting approval. Never invoke `--force` merely because a lock is old or inconvenient.

Keep the lock while waiting for an in-scope user decision. Release it on successful completion, explicit cancellation, or abandonment of the run, but only with the owned token:

```text
<python> <skill-root>/scripts/wiki_lock.py release --target <wiki> --token-file <private-runtime-file> --remove-token-file
```

If release reports a token mismatch, another approved force override owns the wiki; do not remove its lock. Tell the user when a paused run intentionally keeps the lock and confirm successful release in the completion report.

## Required inputs

Obtain:

- an explicit target directory;
- one or more explicitly attached files or user-selected source paths, unless the request is only to initialize, repair, migrate, release, or lint an existing wiki;
- a title and short topic boundary when initializing a new wiki;
- the maintained wiki language as a portable language code and human-readable label when initializing, for example `de` and `Deutsch`.
- an explicitly confirmed identity proposal covering purpose and knowledge types, audience, answer language, form of address, tone, detail, answer structure, citation display, uncertainty, history presentation, boundaries, and taboos;
- an explicitly confirmed content policy selecting `current-state`, `historical-ledger`, or `hybrid`, plus supersession behavior. Removal always remains `preview-confirm-never-automatic`, and supported conflicts always remain preserved and disclosed;
- quality-review, optional cleaning-review, and frozen-snapshot reminder intervals when initializing. Propose 30, 90, and 60 days respectively; use those defaults when the user delegates the choice, and record the confirmed values in `schema/QUALITY_POLICY.md`.

For a frozen knowledge-skill export, also obtain an output directory and a lowercase hyphenated skill name. If the target directory or a required source path is missing, ask for it. Do not guess a location, reconstruct one from a filename, or search the user's home directory, desktop, filesystem root, mounted volumes, or whole machine. A host-provided attachment path counts as explicit. If access to that exact file or its containing user-selected directory is denied, request only that narrow access through the host. Never replace a missing source with an assumed `<wiki>/sources/raw/<filename>` path: `sources/` contains registered Markdown only and has no `raw/` original store. If a new wiki's maintained language was not explicitly provided, ask: "In welcher Sprache soll das Quellenmaterial im gepflegten Wiki zusammengeführt und übersetzt werden?" Do not infer this durable choice from the conversation language or first source. Resolve the path, acquire the lock for maintenance operations, inspect the target, and preserve unrelated or existing content.

## Frozen read-only knowledge-skill export

Use this mode when the user wants one released wiki state as an explicit Claude Cowork or Codex knowledge skill. It is a read-only operation on the canonical wiki and therefore does not acquire the exclusive maintenance lock. It must nevertheless refuse an export while `.llmwiki.lock` exists, while the release manifest is missing or invalid, or when any released file differs from the manifest.

The active agent invokes the bundled exporter internally; this command is an implementation contract for the agent, never a step delegated to the user:

```text
<python> <skill-root>/scripts/export_wiki_skill.py --target <wiki> --output-dir <destination> --skill-name <lowercase-hyphenated-name> [--description <trigger-description>]
```

The exporter verifies the same manifest before and after copying. It creates a skill folder and a deterministic `.skill` package whose archive root is that folder, matching the packaging convention of Anthropic's official `anthropics/skills` skill creator. The package contains:

- `SKILL.md` with only `name` and `description` in frontmatter and a strict knowledge-only workflow;
- the complete released wiki under `references/knowledge/`, including its original `meta/manifest.json`;
- `references/SNAPSHOT.json` with the release identity and immutable/read-only flags;
- only the entrypoints `scripts/verify_knowledge.py`, `scripts/search_knowledge.py`, and `scripts/assess_quality.py` plus their non-executable `identity_status.py`, `frontmatter_contract.py`, and `wiki_filters.py` library modules; all are bound to their own bundled snapshot, perform no writes, and cannot select or modify another wiki. The search entrypoint supports validated read-only metadata filters, and the quality helper distinguishes technical validity, confirmed identity/content policy, quality-review age, cleaning-review age, open questions, and frozen-snapshot age.

Never copy the maintenance, ingest, migration, cleaning, release, export, or lock helpers into the exported skill. Never put an absolute source path, lock token, secret, or transient lock file into it. Do not export an unreleased working state. The canonical wiki remains the only maintainable source; changes require maintaining and releasing that wiki and generating a new skill snapshot. Do not patch an exported snapshot in place.

The result of this mode is always a complete skill folder plus its uploadable `.skill` file and checksum, never merely a loose data directory, ordinary `.zip`, or standalone Python program. After installation, the user asks the exported skill normal knowledge questions; that skill runs its verification and retrieval helpers internally and must never ask the user to run them.

After export, report the wiki version, release ID, original manifest SHA-256, `.skill` SHA-256, skill folder, package path, and that self-maintenance is disabled. The `.skill` file is the installation artifact for Claude Cowork; the folder is useful for local inspection or hosts that install unpacked skills.

## Deterministic metadata transactions

The existing curation workflow remains authoritative. Use the new metadata helpers only when the request involves frontmatter inspection, bulk schema work, value normalization, wikilink cleanup, or recovery:

- Run locked `scripts/inventory_wiki.py` before any broad frontmatter migration or cleaning proposal. Discuss missing fields, type drift, noncanonical names, and compatible extensions; parser errors block planning.
- Use `scripts/frontmatter_actions.py plan` with a validated selector and action and write its plan only to the active temporary workspace. Show the exact selected paths, material before/after differences, changed/skipped counts, destructive flag, and `plan_sha256`.
- Obtain explicit confirmation for deletion, overwrite, rename, merge, value normalization, wikilink deduplication, or source-metadata changes. Apply only the same plan with `--expect-plan-sha256`; pass `--confirm-destructive` only after that approval. `stale_plan` means zero writes and requires inspection plus a new plan, never a bypass.
- Treat the targeted snapshot created by a successful frontmatter apply as the required pre-change snapshot for that action. On `partial_failure`, retain the lock and repair or run a confirmed restore before release.
- Use `scripts/restore_wiki.py list`, then `plan`, then `apply` for recovery. Show selected paths and hashes, require confirmation, and apply with both the expected plan hash and `--confirm-restore`. A restore never deletes files absent from an older snapshot and always creates a recovery snapshot first.
- Use `normalize_values` only on fields whose semantics permit deterministic normalization. Do not normalize stable IDs, claim text, source titles or locators, hashes, `original_ref`, or protected human material. Use `dedupe_wikilinks` for alias- and subpath-preserving link cleanup.

Run `scripts/describe_actions.py` when a host needs a machine-readable description of the complete maintenance surface. It is descriptive and grants no mutation authority.

## Synchronized storage

Treat a OneDrive or SharePoint folder as a second writer on the wiki, never as a passive transport. The contract section on synchronized storage is binding; the operational rules are:

- A `sync_artifacts_present` state means a conflict copy exists. Do not curate both files and do not delete either. Run locked `scripts/resolve_conflict_copy.py plan`, show the user both sides with their hashes, sizes and modification times, take one decision per copy, then apply the confirmed plan hash. Rebuild the graph, lint, and release afterwards.
- A `sync_in_progress` state is a transfer still running. Wait and re-verify; never repair it, and never report it as a damaged wiki.
- A `hydration_required` state means released files hold no local content. Report the file count and estimated download volume and ask before proceeding. Do not pass `--allow-hydration` on your own initiative.
- Operating-system artifacts are expected noise. Report them once if useful and otherwise ignore them; never propose deleting a user's `.DS_Store` as if it were smuggled source material.
- After a release on an apparently synchronized folder, repeat the reported persistence statement. The release is durable locally; whether the client has uploaded it is unknown, so never tell the user that colleagues can already see it.
- When acquiring the lock reports a storage advisory, pass it on once. Do not maintain the same wiki from two machines at the same time, and never force-override a lock held by another machine on age alone.

## Navigation indexes

Each populated subdirectory of `wiki/` carries a generated `index.md`. Never hand-write or hand-edit one: `scripts/build_graph.py` produces them, and an edit is overwritten on the next build. When the linter reports a stale, missing, or orphaned directory index, rebuild the graph rather than repairing the file.

A page counts as listed when the index responsible for it lists it, so a root index may link to directory indexes instead of to every page. Prefer that shape for a growing wiki and say why when you change it: the root then stops growing with the wiki. A root that still lists everything remains valid; do not migrate one without asking.

## Trust tiers

Record who produced and who confirmed individual pages, so a reader can tell a reviewed page from an unreviewed one. Include `generated_by` and `generated_at` on pages you author, using your own agent identifier in the form `agent/<name>`.

Use locked `scripts/verify_pages.py plan` to show which pages a confirmation would cover and the tier it would record, then apply the confirmed plan hash. Pass `--user-confirmed-human-review` only after the named person has actually confirmed they reviewed those pages; recording agent work as `human:` is prohibited regardless of how the request is phrased. Report the resulting distribution rather than implying the wiki as a whole was reviewed.

## Open Knowledge Format

Run locked `scripts/report_okf.py` only when the user asks about interoperability or an OKF migration. Never make OKF the native contract or invent its recommended metadata.

An OKF bundle is a first-class deliverable of this skill, not a footnote. Run `scripts/export_okf_bundle.py` whenever the user wants their knowledge in an interoperable form. It takes no lock token, requires an empty destination outside the wiki, refuses to export anything but a verified release, and validates the bundle it wrote before reporting success.

The bundle carries the registered source extractions by default so it can answer its own citations; pass `--no-sources` only when the user asks for concepts alone and say what that costs. Before exporting, tell the user what the bundle cannot carry: claim locators, the release manifest, snapshots, `SOUL.md`, concept worlds, and clusters. After exporting, name the release version it was bound to, report the concept and source counts, list the recommended fields that had no basis in the wiki, and repeat that editing the bundle does not change the wiki. Never fill a missing field to make a bundle look complete.

## Workflow

For initialize, ingest, maintain, repair, migrate, release, or lint operations:

1. For a new wiki, complete the identity/content-policy interview and obtain confirmation of the hash-bound proposal before taking a lock or writing any target file. For an existing wiki whose identity files are missing or invalid, take the lock, run a baseline audit, conduct the same no-write proposal discussion, and apply the confirmed proposal with `scripts/apply_identity.py`; replacement of existing identity files requires explicit confirmation.
2. Acquire the exclusive wiki lock as specified above and keep only its private runtime token file until release. For a standalone initialization-only request, use the internal-lock wrapper described above and skip the remaining workflow after its successful released result.
3. Run `scripts/lint_wiki.py --check-only` before the first maintenance change. This baseline mode performs no repair and writes no lint report. Report pre-existing blockers separately from planned changes; never describe the whole wiki as releasable merely because the current batch is valid.
4. Inspect the locked target and classify the request as initialize, ingest, maintain, repair, migrate, quality-review, cleaning-review, release, or lint.
5. Before invoking initialization, construct and check one complete argument map containing target, explicit title, topic boundary, wiki-language code, language label, all three review intervals, the confirmed identity-plan path and hash, and either the private runtime token file or the standalone wrapper's public owner label. For a new wiki that will be curated further under the same lock, invoke `scripts/init_wiki.py` through `run_locked.py` and explicitly pass `--title <title>`, `--topic <topic>`, `--wiki-language <code>`, `--wiki-language-label <label>`, `--quality-review-days <days>`, `--cleaning-review-days <days>`, `--snapshot-warning-days <days>`, `--identity-plan <plan>`, and `--expect-identity-sha256 <confirmed-hash>`. Do not start the helper with a partial argument map. `--description` is an alias for `--topic`. As defensive recovery for a faulty caller, the script derives a title from the topic or target instead of failing when `--title` is omitted, reports `title_source: derived-from-topic-or-target`, and requires that derived title to be reviewed before further curation. The script creates only missing files and records the confirmed identity, content policy, language, and reminder intervals.

   For a standalone initialization-only request, invoke `scripts/initialize_wiki.py` internally with the same complete content arguments, identity plan and expected hash plus `--owner <agent-or-run-id>` and no lock token. It constructs and validates the full wiki outside the target and commits only the complete released result. A successful result must report `state: initialized`, `lint_valid: true`, version, release ID, manifest hash, and `lock_released: true`; a failure leaves no partial wiki content. Never expose or ask the user to handle an internal token.
6. Resolve every new source only from its current host attachment path or an exact path/directory explicitly selected by the user. Check that exact path before conversion. If it is missing, inaccessible, or no longer attached, return a concise `source_missing` or `source_access_denied` result and ask the user to reattach it or select its location; do not run a broad `find`, recursive home-directory scan, Spotlight/system search, or filename hunt. Convert the verified source to faithful Markdown in a temporary workspace outside the target wiki. Preserve its original language, headings, lists, tables, quotations, dates, identifiers, and page or slide markers when recoverable. Do not translate, summarize, or improve the source during extraction.
7. Run `scripts/validate_extraction.py` on the staged Markdown before registration. A rejected extraction never enters the wiki. An extraction with warnings is registered as `partial` unless the user reviews the concrete warnings and explicitly confirms active use. Capability probing for optional converters must return structured availability instead of a traceback; absence of one optional converter is not a failure when a suitable fallback exists.
8. Register each converted Markdown file with the bundled `scripts/register_source.py` through `run_locked.py`, including `--content-language <source-language-or-und>`. The original remains outside the wiki. Use `--original-ref` for a portable relative or logical reference, URL, SharePoint item identifier, or other stable identifier. Use `--original-file` only at runtime when the exact verified original is still available for hashing; that machine path must never be stored. Never create or read `<wiki>/sources/raw/`, never copy an original binary below `sources/`, and never assume that a registered Markdown source implies continued access to its original file.
9. Process batches sequentially. For each non-duplicate source, read the wiki rules, content policy, index, relevant existing pages, and the new source before planning updates.
10. Read both `schema/CLUSTERS.md` and `schema/CONCEPTS.md` before synthesis. Treat them as separate contracts:
   - clusters control navigation, graph grouping, curation boundaries, and optional directories;
   - controlled concepts provide preferred terminology, multilingual aliases, and deterministic retrieval expansion;
   - a concept assignment never moves a page, and a cluster label never becomes a search synonym merely because it exists.
11. When a new wiki has no confirmed clusters, or maintenance reveals material overlap, overloaded clusters, or unassigned durable topics, present a concise cluster proposal before reorganizing the synthesis. For each proposed cluster include a stable ID, label, purpose, inclusion and exclusion boundary, representative pages, overlaps, and one color from the palette declared in `schema/CLUSTERS.md`. Separately propose new or changed concepts when sources introduce durable terminology, ambiguity, synonyms, translations, or concept relationships. For each concept include its stable ID, preferred label in the wiki language, definition, aliases, and optional broader or related concepts. Invite the user to confirm, rename, merge, split, recolor, relate, or reject proposals. Do not activate proposals until the user confirms them unless the user explicitly delegates the decision.
12. After confirmation, verify lock ownership and update the applicable schema plus affected page frontmatter. A page may have several `clusters` and `concepts`; use `primary_cluster` only when a cluster controls its directory. A confirmed cluster or category change may move a wiki page to the cluster's declared `Directory`. Run the bundled `scripts/move_wiki_page.py` through `run_locked.py` without `--apply` to produce the impact plan containing the old and new vault-relative paths, affected inbound links and index entries, per-file precondition hashes, `preview_sha256`, and possible external-link breakage. Show that preview and obtain user confirmation. After confirmation, verify the lock again and rerun with `--apply --expect-preview-sha256 <approved-hash>`; the helper creates its own targeted recovery snapshot before moving. Then rebuild the graph, run the linter, and record the migration. A mismatched preview hash is stale and must be regenerated. The helper refuses overwrites, preserves history, and rewrites internal wikilinks; it cannot repair links stored outside the wiki. Never move a page because only its concept assignment changed. Never move source Markdown under `sources/` as a side effect of categorization. Preserve stable cluster and concept IDs during ordinary maintenance and propose migrations rather than silently renaming them.
13. Never let an agent or delegated worker write a new or revised page directly into the canonical target. Draft every affected `wiki/*.md` file under one external temporary staging directory using the same relative path it will have in the wiki. Run `scripts/page_batch.py plan` through `run_locked.py`; it checks UTF-8, extreme line flattening, frontmatter, protected `human:keep` blocks, staged hashes, and target preconditions. Apply only the same plan hash with `page_batch.py apply`. The apply helper constructs a complete temporary wiki mirror, inserts the full batch there, builds the graph, and runs no-write lint. Any invalid staged page causes `validation_failed` with zero canonical writes. Only a fully valid batch receives a targeted snapshot and atomic per-file commit. A delegated agent may return drafts or populate this staging directory, but cannot receive the lock capability or canonical target as a write destination.
14. For non-page changes not already protected by a hash-bound apply helper, run `scripts/snapshot_wiki.py` through `run_locked.py` before changing the existing wiki. A confirmed `frontmatter_actions.py apply`, `restore_wiki.py apply`, `move_wiki_page.py --apply`, `apply_identity.py`, or `page_batch.py apply` creates its own targeted pre-change snapshot and satisfies this invariant for those exact files. Never snapshot or copy original input files into the wiki unless the user explicitly asks.
15. Update the staged wiki batch incrementally:
   - extend or revise existing pages when the concept already exists and translate new synthesis into the language declared by `schema/WIKI_PROFILE.md`;
   - create a new page only when it has a distinct durable subject;
   - preserve all required frontmatter fields when editing a page; an index must retain `sources: []` even though it does not cite sources itself;
   - add vault-relative `[[wikilinks]]`, source IDs, and confirmed concept IDs;
   - generate globally unused claim IDs through the locked helper and wrap every material assertion in the exact HTML-comment claim-block grammar from the wiki contract; never substitute an Obsidian callout;
   - give every active, disputed, or superseded claim one or more `source_id@locator` entries and ensure those source IDs also appear in page frontmatter;
   - preserve a claim ID only while the assertion keeps the same meaning; connect replacements and contradictions explicitly rather than silently rewriting history;
   - make contradictions, uncertainty, scope, and dates explicit;
   - preserve blocks enclosed by `<!-- human:keep -->` and `<!-- /human:keep -->` exactly;
   - never delete sources or pages without explicit approval; mark superseded pages instead.
16. Update `wiki/index.md`, `meta/changes.md`, and `meta/questions.md` as needed through an applicable validated batch or transaction. Record confirmed identity, content-policy, cluster, and concept changes and affected pages in the change log.
17. Run `scripts/build_graph.py` through `run_locked.py` to regenerate `graph/index.html`, `graph/graph.json`, and the static reading views below `graph/pages/`. It stages the complete output and publishes the graph index last. The graph uses Markdown files as nodes, wikilinks as edges, and confirmed navigation clusters as visible structure nodes and filters. Controlled concepts stay retrieval metadata rather than graph-layout instructions. A normal node click opens a generated HTML reading view through a URL relative to `graph/index.html`. Source views preserve uncertain line boundaries, render page/slide markers as anchors instead of raw comments, fall back to preformatted fragments for malformed tables, and identify layout limitations. Wiki claim views retain claim ID, status, and relative links to source locators. Every view links the canonical Markdown file and graph using only relative routes and is never a second editable source of truth.
18. Run `scripts/lint_wiki.py --fix-safe` through `run_locked.py` for the final validation pass. The linter uses the canonical flat frontmatter parser and validates the confirmed SOUL/content-policy schema. It fails clearly on unsupported YAML rather than guessing. It may repair the mandatory missing `sources: []` only on a page of type `index`; neither mode may invent sources, clusters, concepts, identity, policy, or content metadata. Repair all remaining errors introduced by the current run and regenerate the graph when links or pages changed.
19. Publish exactly one release through `run_locked.py` with a new stable `--operation-id`, `--expect-current-version <observed-version>`, one bump, and summary. The release helper reruns strict lint, enforces the version precondition, updates `WIKI_VERSION`, appends the release log, generates quality status, hashes controlled files, and writes `meta/manifest.json` last. Repeating the same operation ID returns the same current release without another version bump; reusing it after a later release is refused. Never rerun the release helper to display omitted fields: inspect its complete result, then use the read-only verifier. Use patch for ordinary content, minor for a compatible schema expansion, and major for an intentionally breaking contract or complete wiki-language migration. If release fails, retain the lock while repairing or restoring the snapshot.
20. Verify the published manifest read-only. Only after successful verification release the lock using its private runtime token file and remove that token file. Report sources added or skipped, pages created or changed, confirmed identity/content policy, cluster and concept decisions, contradictions or open questions, graph statistics, release ID, `WIKI_VERSION`, manifest SHA-256, final lint result, quality-review and cleaning-review state with next due dates, and successful lock release.

## Quality and optional cleaning review cycle

Treat technical validation, semantic quality review, and cleaning review as separate events:

- strict lint checks deterministic structure and runs for every release;
- a quality review checks semantic duplication, claim support and applicability, stale or inconsistent statuses, unresolved questions, partial extraction, wiki-language consistency, page boundaries, cluster fitness, and controlled-concept quality;
- a cleaning review examines removable duplication, obsolete generated material, superseded content, unused concepts or clusters, and reorganization opportunities. It is optional and begins with a preview. Never delete sources, pages, claims, history, or protected human content merely because cleaning is due.

Use `schema/QUALITY_POLICY.md` as the user-controlled reminder policy. Changing an interval is a maintained wiki change: verify the lock, snapshot first, update the policy, lint, release, and report the new schedule. A due date is advisory, not permission to mutate content.

When an older compliant wiki lacks the current quality or identity files, treat this as a compatible schema upgrade. Preserve its existing title, topic boundary, and maintained language. Confirm the three review intervals and conduct the full identity/content-policy interview. Apply the hash-bound identity proposal, add other missing files without overwriting compatible content, update root navigation, rebuild the graph, lint, and publish one minor release. Until that release exists, readers report the missing quality or identity state rather than inventing it.

Record a review only after the active agent actually completed it. Invoke `scripts/record_quality_review.py` internally with the owned lock, `--kind quality|cleaning`, `--outcome passed|attention-needed|not-applicable`, and a concise factual `--summary`. Do not record semantic quality merely because lint passed, and do not record cleaning merely because candidates were listed. If findings require changes, discuss destructive or meaning-changing proposals with the user, implement only approved changes, then record the truthful outcome and publish a new release so readers receive the updated status.

## Conversion routing

Use the most reliable local extraction capability available for the format. Plain text and Markdown need no model-based transformation. For PDF, Office, HTML, images, audio, or scanned material, use an available trusted reader or converter such as MarkItDown or Docling. Use OCR only when necessary and record extraction limitations.

The converter may read only the exact attachment or user-selected path. Never search protected or unrelated filesystem areas to recover a guessed filename. Perform conversion in a temporary workspace and pass the resulting `.md` file to the registrar. The canonical `sources/` directory is flat and contains only `src-<hash>-<slug>.md`; a `sources/raw/` directory and original PDF, Office, image, audio, or archive files are invalid.

When a previously registered Markdown extraction is incomplete, use the content that is actually present and disclose the limitation. If the missing pages require the original, ask the user to reattach or select that original. Do not manufacture a likely original path from `original_ref`, the source title, a prior machine path, or the wiki directory. Do not register a source as successfully extracted when important content could not be read. Preserve partial output only with `status: partial` and a clear extraction note.

## Complete wiki-language migration

A later language change is allowed but always expensive and explicit. It affects the maintained wiki, not the faithful source layer.

1. Acquire the maintenance lock and run `scripts/plan_language_migration.py` through `run_locked.py` with the private runtime token file, target, destination language code, and label.
2. Show its full page and claim impact and obtain explicit confirmation. Keep the lock while the user decides.
3. Verify the lock and snapshot the current wiki. Do not change `sources/*.md`, source IDs, claim IDs, locators, page IDs, or default file paths.
4. Translate every maintained page title, description, body, and claim text; translate index labels, cluster labels and descriptions, preferred concept terms and definitions, and user-facing root navigation. Preserve `human:keep` blocks exactly and report any resulting deliberate language exception. Retain useful old-language terms as aliases.
5. Update every page's `language` field and finally `schema/WIKI_PROFILE.md`. Do not change only the profile or publish a partly translated active wiki.
6. Rebuild index, graph, and reading views; run the normal release workflow with `--bump major`; verify the released manifest; then release the lock.

## Safety and quality boundaries

- Never modify an original source.
- Never search an entire home directory or machine for a missing source and never invent a local source path.
- Never create `sources/raw/` or store original/binary input below `sources/`; register only faithful Markdown.
- Never invent missing facts, citations, document versions, or source identifiers.
- Do not silently replace a conflicting claim with the newest wording. Record the conflict and its sources.
- Keep source extraction separate from wiki synthesis.
- Prefer exact source traceability over polished but unsupported prose.
- Never apply a stale frontmatter, move, or restore plan and never substitute a newly computed hash for the hash the user approved.
- Preserve compatible frontmatter extensions unless their removal or migration was explicitly approved.
- Do not describe the wiki as perfect merely because lint passes. State remaining warnings, partial extractions, and unresolved questions.

The operation is complete only when the target remains readable as ordinary Markdown, the index reflects the pages, active claims cite registered sources, no broken wikilinks remain, the interactive graph represents the current files and links, the linter reports zero errors, and `meta/manifest.json` is the last successfully published release boundary.
