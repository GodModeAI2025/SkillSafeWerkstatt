# Read-only inventory and metadata filters

Read this reference when the user asks to restrict a query by metadata, inspect available fields, compare subsets, or understand schema drift. These operations never acquire the writer lock and always verify the release before and after reading.

## Inventory

Run `scripts/inventory_wiki.py --target <target> --expect-manifest-sha256 <retained-hash>` internally. It returns property counts, observed types, bounded samples, missing required fields, compatible extensions, property-name drift, and parser errors. The report is descriptive. It does not repair frontmatter or turn structural consistency into semantic quality.

## Filter selector

Pass one validated selector to `search_wiki.py` through its internal `--filter-json` argument:

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
    {"property":"clusters","operator":"contains","value":"governance"}
  ]
}
```

Supported operators are `exists`, `not_exists`, `equals`, `not_equals`, `contains`, `not_contains`, `starts_with`, `ends_with`, `is_empty`, `is_not_empty`, `is_list`, `is_string`, and `in_path`. A condition may use `case_sensitive: true`. Virtual properties are `__path`, `__folder`, `__filename`, and `__extension`. Regular expressions and executable predicates are not accepted.

Typical safe filters use `type`, `status`, `language`, `clusters`, `concepts`, `sources`, `tags`, `date`, `created`, `updated`, or a virtual path property. Clusters remain navigational groupings; concepts remain retrieval vocabulary. Filtering by either does not treat them as interchangeable.

The search result reports the normalized selector, the number filtered out, and facets for type, status, language, clusters, and concepts. Facets describe the positive ranked result set before the result limit is applied.

## Boundaries

- Filtering never changes relevance evidence, claim status, or source applicability.
- A filter can hide conflicting or historical material; disclose the restriction when it materially affects the answer.
- Do not silently force `status=active` for a historical or supersession question.
- An empty filtered result means that the requested subset contains no support, not that the entire wiki lacks the information.
- Parser errors in a verified release are a quality finding; they do not authorize repair by this skill.
- `scripts/describe_actions.py` exposes the complete read-only action and selector catalog for agent discovery. It contains no write, lock, snapshot, cleaning, or restore action.
