# Adapted vault standards

These rules adapt the user-supplied `STANDARDS.md` to the standalone SkillSafeWerkstatt produced by this skill. They preserve the useful conventions without importing project-specific people, domain lists, or unrelated output workflows.

## Layers and metadata

- Folders express layers; tags express orthogonal classification.
- `sources/` is the faithful extracted-source layer. `wiki/` is the maintained synthesis layer. `graph/` is a generated read surface.
- Clusters organize navigation, graph presentation, curation ownership, and optional directories. Controlled concepts organize terminology and retrieval. Never use one as a substitute for the other.
- Machine-readable dates use ISO `YYYY-MM-DD`. Dates in German prose use `DD.MM.YYYY`; English prose follows English conventions.
- Source content preserves its original language. Structural field names and operational files are English. `schema/WIKI_PROFILE.md` always declares the maintained wiki language; there is no implicit fallback. Wiki prose and claim text are translated into that language.
- Filenames are lowercase kebab-case. Do not encode status or language in filenames.

## Links and aliases

- The first meaningful mention of an existing entity or concept should be a wikilink. Later mentions may remain plain when readability benefits.
- Use vault-relative targets, for example `[[wiki/entities/maria-example|Maria Example]]`.
- Known aliases belong in page frontmatter. Do not assign an ambiguous short alias to multiple entities.
- YAML lists containing wikilinks use block style and quoted values. Do not use inline unquoted wikilinks in frontmatter.
- Do not create empty pages only to eliminate a potential graph node. Create a durable entity or concept page when there is enough source-backed knowledge to maintain it. Repeated unresolved mentions belong in `meta/questions.md` until that threshold is reached.

## Frontmatter conventions

Wiki pages include `created`, `updated`, a concise `description`, `sources`, `clusters`, `concepts`, and a structural `type/wiki-*` tag. `aliases` is required when known. `sources` contains quoted wikilinks to files under `sources/`, not free-text provenance. `concepts` contains only IDs confirmed in `schema/CONCEPTS.md`.

Use only the canonical flat frontmatter subset from `wiki-contract.md`: one top-level mapping, typed scalars, and flat scalar lists. Quote strings and use two-space-indented block lists. Inventory and preview any field migration or value/link cleanup; never silently reinterpret nested or otherwise unsupported YAML.

Source pages keep free-text provenance in `original_ref` and use structural tag `type/source`. Source extraction remains faithful and carries no conceptual tags added by the model.

## Graph conventions

- Markdown files are nodes and wikilinks are edges.
- Sources and each wiki page type have distinct colors.
- Structural tags may appear as optional first-class nodes.
- A node click opens the corresponding Markdown file.
- Search, zoom, pan, hover details, degree-based node sizing, and a cluster legend remain available without a network connection.
- Local exploration is the primary interaction. The generated graph is a derived artifact and can always be rebuilt from Markdown.
