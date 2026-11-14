#!/usr/bin/env python3
"""Shared, read-only search core of the query skill and of exported knowledge skills.

Two entrypoints rank a wiki release: `search_wiki.py` in the query skill and
`search_knowledge.py` in every frozen knowledge skill the maintenance skill
exports. Both are thin command-line wrappers around this module. They verify
their release before and after the search, then call `search()`. One core means
one ranking: an improvement reaches both places, and the exported copy cannot
drift away from the reader again.

This module only reads. It imports no release verifier and no writer. It takes a
release root plus options and returns plain report data; printing, exit codes
and integrity checks stay with the wrappers.

Besides the ranked results, every report carries a `coverage` block that counts
what the search did not show: matches cut off by the limit, claims withheld per
page, query words that were dropped or found nowhere, and terms that occur only
in a layer that was not searched. The block only adds keys. It never changes
which results are returned, in which order, or with which score.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional

import bm25
import freshness
import trust_contract
from frontmatter_contract import FrontmatterError, parse_document
from wiki_filters import matches_selector


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

#: Version of the coverage block's shape.
COVERAGE_FORMAT = "lmwiki-search-coverage/1"
#: How many matches beyond the limit the coverage block names with path and score.
OMITTED_TOP_LIMIT = 20
#: Searchable layers of a release, in the order the coverage block lists them.
SCOPES = ("wiki", "sources", "history")
#: The fixed sentence every coverage block carries, so no reader takes a count for a verdict.
COVERAGE_BOUNDARY = (
    "These counts describe whole-word matches of the listed terms in the listed files. They do "
    "not show that the wiki holds nothing on the topic: a page that uses other words, another "
    "word form or another language is not counted."
)
#: Files that route a reader to content instead of holding it. Any index.md is one too.
NAVIGATION_FILES = frozenset({"WIKI.md", "meta/questions.md"})


class QueryError(ValueError):
    """The query holds no token the search can match."""


def normalized(value: str) -> str:
    """Casefold, decompose and drop combining marks, so "Zählerstand" matches "Zahlerstand".

    Each distinct character is looked up once, and every mark found is removed
    with one `str.replace`. Checking every character of a long source text one
    by one made this the most expensive step of a search.
    """
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    if decomposed.isascii():
        return decomposed
    for mark in [character for character in set(decomposed) if unicodedata.combining(character)]:
        decomposed = decomposed.replace(mark, "")
    return decomposed


def tokens(value: str, drop_stopwords: bool = True) -> list[str]:
    values = TOKEN.findall(normalized(value))
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
            # Like the release verifier, only regular files count: a folder
            # named like a page or a dangling link is not part of the release.
            paths = [path for path in sorted(root.rglob("*.md")) if path.is_file()]
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


def query_terms(query: str, expanded_terms: list[str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The terms the ranking matches, in a stable order and with their origin, plus dropped words.

    The term set equals the token set `expand_query` returns for the same query:
    the query's own words without stopwords and single characters (or all of its
    words when nothing else is left), then the tokens of every confirmed concept
    term the query triggered. Dropped words are reported only when they were
    actually left out of the ranking: a stopword that a confirmed concept term
    brings back, such as "und" in "Arbeitspreis und Grundpreis", is ranked and
    therefore listed as a term of origin `concept-expansion`, not as dropped.
    """
    words = TOKEN.findall(normalized(query))
    kept = [word for word in words if word not in STOPWORDS and len(word) > 1]
    terms: list[dict[str, str]] = []
    seen: set[str] = set()
    for word in kept or words:
        if word not in seen:
            seen.add(word)
            terms.append({"term": word, "origin": "query"})
    for expanded in expanded_terms:
        for word in tokens(expanded, drop_stopwords=False):
            if word not in seen:
                seen.add(word)
                terms.append({"term": word, "origin": "concept-expansion"})
    dropped: list[dict[str, str]] = []
    if kept:
        for word in words:
            if word in seen:
                continue
            seen.add(word)
            dropped.append({"term": word, "reason": "stopword" if word in STOPWORDS else "single-character"})
    return terms, dropped


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


def document_fields(data: dict[str, Any], body: str) -> dict[str, list[str]]:
    """Split one document into the weighted fields BM25F scores over."""
    return {
        "title": tokens(str(data.get("title") or ""), False),
        "aliases": tokens(" ".join(as_list(data.get("aliases"))), False),
        "headings": tokens(" ".join(HEADING.findall(body)), False),
        "description": tokens(
            str(data.get("description") or data.get("extraction_notes") or ""), False
        ),
        "body": tokens(body, False),
    }


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


def scope_of(relative: str) -> str:
    """The layer a release-relative path belongs to."""
    if relative.startswith("sources/"):
        return "sources"
    if relative.startswith("meta/history/"):
        return "history"
    return "wiki"


def is_navigation(relative: str) -> bool:
    """True for WIKI.md, every index.md, and meta/questions.md."""
    return relative in NAVIGATION_FILES or PurePosixPath(relative).name == "index.md"


def read_document(path: Path, relative: str, text: Optional[str] = None) -> dict[str, Any]:
    """Parse one Markdown file into what ranking and accounting read from it.

    Raises FrontmatterError when the file is outside the frontmatter contract.
    """
    data, body = frontmatter(path.read_text(encoding="utf-8") if text is None else text, relative)
    searchable_body = visible_body(body)
    heading = H1.search(searchable_body)
    title = str(data.get("title") or (heading.group(1).strip() if heading else path.stem))
    fields = document_fields({**data, "title": title}, searchable_body)
    return {
        "data": data,
        "raw_body": body,
        "body": searchable_body,
        "title": title,
        "fields": fields,
        "words": set().union(*fields.values()),
    }


def unsearched_words(path: Path, relative: str) -> set[str]:
    """Every whole word of a file that is counted but not ranked.

    A file outside the frontmatter contract or the UTF-8 encoding cannot be
    ranked, but its words still exist; counting them keeps a damaged file in a
    layer nobody searched from hiding a term or from failing the search. A file
    that cannot be read at all contributes no words.
    """
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return set()
    try:
        return read_document(path, relative, text)["words"]
    except FrontmatterError:
        return set(tokens(text, False))


def scope_paths(target: Path, scope: str) -> list[Path]:
    """The Markdown files of one layer that is counted without being searched."""
    root = target / ("sources" if scope == "sources" else "meta/history")
    if not root.is_dir():
        return []
    return [path for path in sorted(root.rglob("*.md")) if path.is_file()]


def search(
    root: Path,
    query: str,
    *,
    limit: int = 12,
    include_sources: bool = False,
    include_history: bool = False,
    selector: Optional[dict[str, Any]] = None,
    history_shipped: bool = True,
    path_prefix: str = "",
) -> dict[str, Any]:
    """Rank the release under `root` for `query` and account for what is not shown.

    `selector` must already be validated by `wiki_filters.validate_selector`.
    `history_shipped=False` describes a release that carries no history layer,
    such as an exported knowledge skill. `path_prefix` is prepended to every
    path the report names; selectors, scopes and navigation are decided on the
    release-relative path.

    Returns `searched_files`, `filtered_out`, `matched_concepts`,
    `expanded_terms`, `facets` (over every match), `results` (at most `limit`),
    `coverage`, and `parser_errors`. A caller must not report results when
    `parser_errors` is non-empty. Raises QueryError for a query without a
    searchable token and ValueError for an impossible option.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if include_history and not history_shipped:
        raise ValueError("this release ships no history layer to search")
    selector = selector if selector is not None else {"kind": "all"}

    concept_definitions = controlled_concepts(root / "schema/CONCEPTS.md")
    query_token_set, matched_concepts, expanded_terms = expand_query(query, concept_definitions)
    if not query_token_set:
        raise QueryError("query must contain at least one searchable token")
    ordered_terms, dropped_terms = query_terms(query, expanded_terms)
    term_names = [item["term"] for item in ordered_terms]

    searched_scopes = {"wiki": True, "sources": include_sources, "history": include_history}
    # Sources are always counted, searched or not; history only when searched.
    counted_scopes = {scope: searched_scopes[scope] or scope == "sources" for scope in SCOPES}
    scope_files = {scope: 0 for scope in SCOPES}
    files_with_term = {scope: 0 for scope in SCOPES}
    term_files = {scope: {term: 0 for term in term_names} for scope in SCOPES}

    def account(scope: str, words: set[str]) -> None:
        present = [term for term in term_names if term in words]
        for term in present:
            term_files[scope][term] += 1
        if present:
            files_with_term[scope] += 1

    searched = 0
    filtered_out = 0
    parser_errors: list[dict[str, str]] = []

    # BM25 needs corpus-wide term rarity and average field lengths, so every
    # candidate is collected before any of them is scored.
    candidates: list[dict[str, Any]] = []
    for path in candidate_paths(root, include_sources, include_history):
        searched += 1
        relative = path.relative_to(root).as_posix()
        scope = scope_of(relative)
        scope_files[scope] += 1
        try:
            document = read_document(path, relative)
        except FrontmatterError as exc:
            parser_errors.append({"path": path_prefix + relative, "error": str(exc)})
            continue
        # Counted before the selector applies: a metadata restriction narrows
        # the results, but must not make an existing term look absent.
        account(scope, document["words"])
        if not matches_selector(document["data"], relative, selector):
            filtered_out += 1
            continue
        candidates.append(
            {
                "path": path,
                "relative": relative,
                "data": document["data"],
                "title": document["title"],
                "body": document["body"],
                "claims": claims_in(document["raw_body"]),
                "fields": document["fields"],
                "words": document["words"],
            }
        )
    for scope in SCOPES:
        if counted_scopes[scope] and not searched_scopes[scope]:
            for path in scope_paths(root, scope):
                relative = path.relative_to(root).as_posix()
                scope_files[scope] += 1
                account(scope, unsearched_words(path, relative))

    corpus = bm25.Corpus(candidate["fields"] for candidate in candidates)
    query_phrase = " ".join(tokens(query, False))
    matched_concept_set = set(matched_concepts)

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        data = candidate["data"]
        relative = candidate["relative"]
        searchable_body = candidate["body"]
        page_claims = candidate["claims"]
        document_concepts = set(as_list(data.get("concepts")))
        score = bm25.score(
            corpus,
            candidate["fields"],
            query_token_set,
            phrase_match=bool(query_phrase and query_phrase in " ".join(tokens(searchable_body, False))),
            concept_overlap=len(document_concepts & matched_concept_set),
            status=str(data.get("status") or ""),
        )
        if score <= 0:
            continue
        claims = relevant_claims(page_claims, query_token_set, bool(document_concepts & matched_concept_set))
        results.append(
            {
                "path": path_prefix + relative,
                "title": candidate["title"],
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
                "trust_tier": trust_contract.trust_tier(data),
                "stale_after": str(data.get(freshness.STALE_AFTER) or ""),
                "past_expiry": freshness.is_stale(data),
                "snippet": best_snippet(searchable_body, query_token_set),
                "claims": claims,
                "matched_terms": [term for term in term_names if term in candidate["words"]],
                "claims_total": len(page_claims),
                "claims_returned": len(claims),
                "navigation": is_navigation(relative),
            }
        )

    results.sort(key=lambda item: (-float(item["score"]), str(item["path"])))
    returned = results[:limit]
    omitted = results[limit:]

    def files_per_scope(term: str) -> dict[str, Optional[int]]:
        return {scope: term_files[scope][term] if counted_scopes[scope] else None for scope in SCOPES}

    def in_searched_files(term: str) -> bool:
        return any(term_files[scope][term] for scope in SCOPES if searched_scopes[scope])

    coverage = {
        "format": COVERAGE_FORMAT,
        "searched_files": searched,
        "matched": len(results),
        "returned": len(returned),
        "truncated": len(results) > len(returned),
        "omitted_count": len(omitted),
        "omitted_top": [{"path": item["path"], "score": item["score"]} for item in omitted[:OMITTED_TOP_LIMIT]],
        "scopes": {
            scope: {
                "searched": searched_scopes[scope],
                "shipped": history_shipped if scope == "history" else True,
                "files": scope_files[scope] if counted_scopes[scope] else None,
                "files_with_a_query_term": files_with_term[scope] if counted_scopes[scope] else None,
            }
            for scope in SCOPES
        },
        "query_terms": [{**item, "files": files_per_scope(item["term"])} for item in ordered_terms],
        "dropped_terms": dropped_terms,
        "unmatched_terms": [
            item["term"] for item in ordered_terms if item["origin"] == "query" and not in_searched_files(item["term"])
        ],
        "terms_only_in_unsearched": {
            "sources": [
                term
                for term in term_names
                if not include_sources and term_files["sources"][term] and not in_searched_files(term)
            ],
        },
        "boundary": COVERAGE_BOUNDARY,
    }
    return {
        "searched_files": searched,
        "filtered_out": filtered_out,
        "matched_concepts": matched_concepts,
        "expanded_terms": expanded_terms,
        "facets": facets(results),
        "results": returned,
        "coverage": coverage,
        "parser_errors": parser_errors,
    }
