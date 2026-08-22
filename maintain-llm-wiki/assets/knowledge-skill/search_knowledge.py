#!/usr/bin/env python3
"""Search only this skill's bundled frozen wiki and return ranked JSON evidence."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Optional

from frontmatter_contract import FrontmatterError, parse_document
from verify_knowledge import knowledge_root, verify
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


def as_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


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
            current = {"id": heading.group(1)}
            definitions[heading.group(1)] = current
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
    all_query_tokens = set(tokens(query, drop_stopwords=False))
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
            term_matches = normalized_term in normalized_query if " " in normalized_term else normalized_term in all_query_tokens
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


def candidate_paths(target: Path, include_sources: bool) -> Iterable[Path]:
    roots = [target / "WIKI.md", target / "wiki", target / "meta/questions.md"]
    if include_sources:
        roots.append(target / "sources")
    seen: set[Path] = set()
    for root in roots:
        paths = [root] if root.is_file() and root.suffix.lower() == ".md" else sorted(root.rglob("*.md")) if root.is_dir() else []
        for path in paths:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield path


def claims_in(body: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for match in CLAIM_BLOCK.finditer(body):
        metadata: dict[str, str] = {}
        for raw_line in match.group("meta").splitlines():
            if ":" in raw_line:
                key, value = raw_line.split(":", 1)
                metadata[key.strip().casefold()] = value.strip()
        claims.append({
            "id": metadata.get("id", ""),
            "kind": metadata.get("kind", ""),
            "status": metadata.get("status", ""),
            "sources": split_pipe(metadata.get("sources", "")),
            "replaces": split_pipe(metadata.get("replaces", "")),
            "contradicts": split_pipe(metadata.get("contradicts", "")),
            "text": " ".join(match.group("text").split()),
        })
    return claims


def visible_body(body: str) -> str:
    return CLAIM_BLOCK.sub(lambda match: match.group("text"), body)


def relevant_claims(claims: list[dict[str, Any]], query_tokens: set[str], concept_match: bool) -> list[dict[str, Any]]:
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for claim in claims:
        overlap = len(query_tokens & set(tokens(str(claim.get("text") or ""), False)))
        if overlap:
            ranked.append((overlap, str(claim.get("id") or ""), claim))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if ranked:
        return [claim for _, _, claim in ranked[:8]]
    return [claim for claim in claims if claim.get("status") in {"active", "disputed"}][:8] if concept_match else []


def best_snippet(body: str, query_tokens: set[str]) -> str:
    candidates: list[tuple[int, str]] = []
    for line in body.splitlines():
        compact = " ".join(line.strip().split())
        overlap = len(query_tokens & set(tokens(compact, False)))
        if compact and not compact.startswith("#") and overlap:
            candidates.append((overlap, compact))
    if not candidates:
        return ""
    snippet = max(candidates, key=lambda item: (item[0], len(item[1])))[1]
    return snippet if len(snippet) <= 320 else snippet[:317].rstrip() + "..."


def score_document(query: str, query_tokens: set[str], data: dict[str, Any], body: str, matched: set[str]) -> float:
    fields = (
        (str(data.get("title") or ""), 10.0),
        (" ".join(as_list(data.get("aliases"))), 7.0),
        (" ".join(HEADING.findall(body)), 5.0),
        (str(data.get("description") or data.get("extraction_notes") or ""), 4.0),
        (body, 1.0),
    )
    found: set[str] = set()
    score = 0.0
    for text, weight in fields:
        counts: dict[str, int] = {}
        for value in tokens(text, False):
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
    score += 12.0 * len(set(as_list(data.get("concepts"))) & matched)
    status = str(data.get("status") or "")
    if score > 0 and status == "active":
        score += 3.0
    elif score > 0 and status in {"superseded", "withdrawn"}:
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
    parser.add_argument("--query", required=True, help="Question or retrieval query")
    parser.add_argument("--limit", type=int, default=12, help="Maximum result count (1-100)")
    parser.add_argument("--include-sources", action="store_true", help="Also search faithful source Markdown")
    parser.add_argument("--filter-json", default='{"kind":"all"}', help="Validated metadata selector as JSON")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        raise SystemExit("limit must be between 1 and 100")
    try:
        selector = validate_selector(json.loads(args.filter_json))
    except (json.JSONDecodeError, ValueError, FrontmatterError) as exc:
        raise SystemExit(f"filter-json is invalid: {exc}") from exc

    release = verify()
    if release.get("state") != "ready":
        print(json.dumps({"release": release, "results": []}, ensure_ascii=False, indent=2))
        return 4
    target = knowledge_root()
    definitions = controlled_concepts(target / "schema/CONCEPTS.md")
    query_tokens, matched_concepts, expanded_terms = expand_query(args.query, definitions)
    if not query_tokens:
        raise SystemExit("query must contain at least one searchable token")

    results: list[dict[str, Any]] = []
    searched = 0
    filtered_out = 0
    parser_errors: list[dict[str, str]] = []
    for path in candidate_paths(target, args.include_sources):
        searched += 1
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(target).as_posix()
        try:
            data, body = frontmatter(text, relative)
        except FrontmatterError as exc:
            parser_errors.append({"path": f"references/knowledge/{relative}", "error": str(exc)})
            continue
        if not matches_selector(data, relative, selector):
            filtered_out += 1
            continue
        searchable_body = visible_body(body)
        heading = H1.search(searchable_body)
        title = str(data.get("title") or (heading.group(1).strip() if heading else path.stem))
        score = score_document(args.query, query_tokens, {**data, "title": title}, searchable_body, set(matched_concepts))
        if score <= 0:
            continue
        document_concepts = set(as_list(data.get("concepts")))
        results.append({
            "path": f"references/knowledge/{relative}",
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
            "snippet": best_snippet(searchable_body, query_tokens),
            "claims": relevant_claims(claims_in(body), query_tokens, bool(document_concepts & set(matched_concepts))),
        })
    results.sort(key=lambda item: (-float(item["score"]), str(item["path"])))
    final_release = verify()
    if final_release.get("state") != "ready" or final_release.get("manifest_sha256") != release.get("manifest_sha256"):
        print(json.dumps({"release": {"state": "snapshot_changed"}, "results": []}, ensure_ascii=False, indent=2))
        return 4
    if parser_errors:
        print(json.dumps({"state": "invalid_frontmatter", "release": release, "parser_errors": parser_errors, "results": []}, ensure_ascii=False, indent=2))
        return 5
    print(json.dumps({
        "query": args.query,
        "release": release,
        "searched_files": searched,
        "include_sources": args.include_sources,
        "selector": selector,
        "filtered_out": filtered_out,
        "matched_concepts": matched_concepts,
        "expanded_terms": expanded_terms,
        "facets": facets(results),
        "results": results[:args.limit],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
