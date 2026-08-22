#!/usr/bin/env python3
"""Rank relevant Markdown files in an initialized SkillSafeWerkstatt without modifying it."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Optional

from frontmatter_contract import FrontmatterError, parse_document
from verify_release import verify_snapshot
from wiki_filters import matches_selector, validate_selector


H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
TOKEN = re.compile(r"[^\W_]+(?:[-_][^\W_]+)*", re.UNICODE)
STOPWORDS = {
    "aber", "als", "am", "an", "auch", "auf", "aus", "bei", "das", "der", "die",
    "ein", "eine", "einer", "eines", "für", "hat", "im", "in", "ist", "mit", "oder",
    "sich", "sind", "und", "von", "was", "wie", "zu", "zum", "zur",
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is",
    "of", "on", "or", "that", "the", "to", "what", "with",
}
CONCEPT_HEADING = re.compile(r"^##\s+([a-z0-9]+(?:-[a-z0-9]+)*)\s*$")
CONCEPT_FIELD = re.compile(r"^-\s+([A-Za-z]+):\s*(.*)$")
CLAIM_BLOCK = re.compile(
    r"<!--\s*claim\s*\n(?P<meta>.*?)-->\s*(?P<text>.*?)\s*<!--\s*/claim\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def tokens(value: str, drop_stopwords: bool = True) -> list[str]:
    values = [match.group(0) for match in TOKEN.finditer(normalized(value))]
    if drop_stopwords:
        values = [value for value in values if value not in STOPWORDS and len(value) > 1]
    return values


def frontmatter(text: str, source: str) -> tuple[dict[str, Any], str]:
    document = parse_document(text, source)
    return document.data, document.body


def candidate_paths(target: Path, include_sources: bool, include_history: bool) -> Iterable[Path]:
    roots = [target / "WIKI.md", target / "wiki", target / "meta/questions.md"]
    if include_sources:
        roots.append(target / "sources")
    if include_history:
        roots.append(target / "meta/history")
    seen: set[Path] = set()
    for root in roots:
        if root.is_file() and root.suffix.lower() == ".md":
            paths = [root]
        elif root.is_dir():
            paths = sorted(root.rglob("*.md"))
        else:
            paths = []
        for path in paths:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield path


def as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def split_pipe(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def controlled_concepts(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    definitions: dict[str, dict[str, Any]] = {}
    current: Optional[dict[str, Any]] = None
    fenced = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = CONCEPT_HEADING.match(line)
        if heading:
            concept_id = heading.group(1)
            current = {"id": concept_id}
            definitions[concept_id] = current
            continue
        field = CONCEPT_FIELD.match(line)
        if field and current is not None:
            current[field.group(1).casefold()] = field.group(2).strip()
    return {
        concept_id: {
            **definition,
            "terms": [definition.get("preferred", "")] + split_pipe(definition.get("aliases", "")),
        }
        for concept_id, definition in definitions.items()
        if definition.get("status") == "active"
    }


def expand_query(query: str, definitions: dict[str, dict[str, Any]]) -> tuple[set[str], list[str], list[str]]:
    original_tokens = set(tokens(query)) or set(tokens(query, drop_stopwords=False))
    normalized_query = " ".join(tokens(query, drop_stopwords=False))
    matched: list[str] = []
    expanded_terms: list[str] = []
    expanded_tokens = set(original_tokens)
    for concept_id, definition in sorted(definitions.items()):
        terms = [str(term) for term in definition.get("terms", []) if str(term).strip()]
        term_matches = False
        for term in terms:
            normalized_term = " ".join(tokens(term, drop_stopwords=False))
            if not normalized_term:
                continue
            if " " in normalized_term:
                term_matches = normalized_term in normalized_query
            else:
                term_matches = normalized_term in set(tokens(query, drop_stopwords=False))
            if term_matches:
                break
        if not term_matches:
            continue
        matched.append(concept_id)
        for term in terms:
            if term not in expanded_terms:
                expanded_terms.append(term)
            expanded_tokens.update(tokens(term, drop_stopwords=False))
    return expanded_tokens, matched, expanded_terms


def claims_in(body: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for match in CLAIM_BLOCK.finditer(body):
        metadata: dict[str, str] = {}
        for raw_line in match.group("meta").splitlines():
            if ":" not in raw_line:
                continue
            key, value = raw_line.split(":", 1)
            metadata[key.strip().casefold()] = value.strip()
        claims.append(
            {
                "id": metadata.get("id", ""),
                "kind": metadata.get("kind", ""),
                "status": metadata.get("status", ""),
                "sources": split_pipe(metadata.get("sources", "")),
                "replaces": split_pipe(metadata.get("replaces", "")),
                "contradicts": split_pipe(metadata.get("contradicts", "")),
                "text": " ".join(match.group("text").split()),
            }
        )
    return claims


def visible_body(body: str) -> str:
    return CLAIM_BLOCK.sub(lambda match: match.group("text"), body)


def relevant_claims(
    claims: list[dict[str, Any]],
    query_tokens: set[str],
    concept_match: bool = False,
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for claim in claims:
        claim_tokens = set(tokens(str(claim.get("text") or ""), drop_stopwords=False))
        overlap = len(query_tokens & claim_tokens)
        if overlap:
            ranked.append((overlap, str(claim.get("id") or ""), claim))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if ranked:
        return [claim for _, _, claim in ranked[:8]]
    if concept_match:
        return [claim for claim in claims if claim.get("status") in {"active", "disputed"}][:8]
    return []


def best_snippet(body: str, query_tokens: set[str]) -> str:
    candidates: list[tuple[int, str]] = []
    for line in body.splitlines():
        compact = " ".join(line.strip().split())
        if not compact or compact.startswith("#"):
            continue
        line_tokens = set(tokens(compact, drop_stopwords=False))
        overlap = len(query_tokens & line_tokens)
        if overlap:
            candidates.append((overlap, compact))
    if not candidates:
        return ""
    snippet = max(candidates, key=lambda item: (item[0], len(item[1])))[1]
    return snippet if len(snippet) <= 320 else snippet[:317].rstrip() + "..."


def score_document(
    query: str,
    query_tokens: set[str],
    data: dict[str, Any],
    body: str,
    matched_concepts: set[str],
) -> float:
    title = str(data.get("title") or "")
    aliases = " ".join(as_list(data.get("aliases")))
    description = str(data.get("description") or data.get("extraction_notes") or "")
    headings = " ".join(HEADING.findall(body))
    fields = {
        "title": (tokens(title, False), 10.0),
        "aliases": (tokens(aliases, False), 7.0),
        "headings": (tokens(headings, False), 5.0),
        "description": (tokens(description, False), 4.0),
        "body": (tokens(body, False), 1.0),
    }
    found: set[str] = set()
    score = 0.0
    for field_tokens, weight in fields.values():
        counts: dict[str, int] = {}
        for value in field_tokens:
            counts[value] = counts.get(value, 0) + 1
        for query_token in query_tokens:
            count = min(counts.get(query_token, 0), 3)
            if count:
                found.add(query_token)
                score += weight * count
    if query_tokens:
        score += 6.0 * len(found) / len(query_tokens)
    query_phrase = " ".join(tokens(query, False))
    if query_phrase and query_phrase in " ".join(tokens(body, False)):
        score += 8.0
    document_concepts = set(as_list(data.get("concepts")))
    score += 12.0 * len(document_concepts & matched_concepts)
    if score <= 0:
        return 0.0
    status = str(data.get("status") or "")
    if status == "active":
        score += 3.0
    elif status == "draft":
        score -= 0.5
    elif status in {"superseded", "withdrawn"}:
        score -= 2.0
    return max(score, 0.0)


def facets(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    output: dict[str, dict[str, int]] = {}
    for field in ("type", "status", "language", "clusters", "concepts"):
        counts: dict[str, int] = {}
        for item in results:
            raw = item.get(field)
            values = raw if isinstance(raw, list) else [raw] if raw not in (None, "") else []
            for value in values:
                key = str(value)
                counts[key] = counts.get(key, 0) + 1
        output[field] = dict(sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Target wiki directory")
    parser.add_argument("--query", required=True, help="Question or retrieval query")
    parser.add_argument("--limit", type=int, default=12, help="Maximum number of results")
    parser.add_argument("--include-sources", action="store_true", help="Also search faithful source Markdown")
    parser.add_argument("--include-history", action="store_true", help="Also search historical snapshots")
    parser.add_argument("--filter-json", default='{"kind":"all"}', help="Validated metadata selector as JSON")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not (target / "WIKI.md").is_file() or not (target / "wiki/index.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    initial_release = verify_snapshot(target)
    if initial_release.get("state") != "ready":
        print(json.dumps({"release": initial_release, "results": []}, ensure_ascii=False, indent=2))
        return {"wiki_busy": 2, "snapshot_changed": 3}.get(str(initial_release.get("state")), 4)
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("limit must be between 1 and 100")
    try:
        selector = validate_selector(json.loads(args.filter_json))
    except (json.JSONDecodeError, ValueError, FrontmatterError) as exc:
        raise SystemExit(f"filter-json is invalid: {exc}") from exc

    concept_definitions = controlled_concepts(target / "schema/CONCEPTS.md")
    query_token_set, matched_concepts, expanded_terms = expand_query(args.query, concept_definitions)
    if not query_token_set:
        raise SystemExit("query must contain at least one searchable token")

    results: list[dict[str, Any]] = []
    searched = 0
    filtered_out = 0
    parser_errors: list[dict[str, str]] = []
    for path in candidate_paths(target, args.include_sources, args.include_history):
        searched += 1
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(target).as_posix()
        try:
            data, body = frontmatter(text, relative)
        except FrontmatterError as exc:
            parser_errors.append({"path": relative, "error": str(exc)})
            continue
        if not matches_selector(data, relative, selector):
            filtered_out += 1
            continue
        page_claims = claims_in(body)
        searchable_body = visible_body(body)
        heading = H1.search(searchable_body)
        title = str(data.get("title") or (heading.group(1).strip() if heading else path.stem))
        score = score_document(
            args.query,
            query_token_set,
            {**data, "title": title},
            searchable_body,
            set(matched_concepts),
        )
        if score <= 0:
            continue
        document_concepts = set(as_list(data.get("concepts")))
        results.append(
            {
                "path": relative,
                "title": title,
                "id": str(data.get("id") or data.get("source_id") or ""),
                "type": str(data.get("type") or ("source" if relative.startswith("sources/") else "")),
                "status": str(data.get("status") or ""),
                "date": str(data.get("date") or data.get("updated") or ""),
                "description": str(data.get("description") or data.get("extraction_notes") or ""),
                "language": str(data.get("language") or data.get("content_language") or ""),
                "sources": as_list(data.get("sources")),
                "clusters": as_list(data.get("clusters")),
                "concepts": as_list(data.get("concepts")),
                "tags": as_list(data.get("tags")),
                "score": round(score, 2),
                "snippet": best_snippet(searchable_body, query_token_set),
                "claims": relevant_claims(
                    page_claims,
                    query_token_set,
                    bool(document_concepts & set(matched_concepts)),
                ),
            }
        )

    results.sort(key=lambda item: (-float(item["score"]), str(item["path"])))
    if parser_errors:
        final_release = verify_snapshot(target, str(initial_release.get("manifest_sha256") or ""))
        release = final_release if final_release.get("state") != "ready" else initial_release
        print(json.dumps({"state": "invalid_frontmatter", "release": release, "parser_errors": parser_errors, "results": []}, ensure_ascii=False, indent=2))
        return 5 if final_release.get("state") == "ready" else {"wiki_busy": 2, "snapshot_changed": 3}.get(str(final_release.get("state")), 4)
    report = {
        "target": ".",
        "query": args.query,
        "release": initial_release,
        "searched_files": searched,
        "include_sources": args.include_sources,
        "include_history": args.include_history,
        "selector": selector,
        "filtered_out": filtered_out,
        "matched_concepts": matched_concepts,
        "expanded_terms": expanded_terms,
        "facets": facets(results),
        "results": results[: args.limit],
    }
    final_release = verify_snapshot(target, str(initial_release.get("manifest_sha256") or ""))
    if final_release.get("state") != "ready":
        print(json.dumps({"release": final_release, "results": []}, ensure_ascii=False, indent=2))
        return {"wiki_busy": 2, "snapshot_changed": 3}.get(str(final_release.get("state")), 4)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
