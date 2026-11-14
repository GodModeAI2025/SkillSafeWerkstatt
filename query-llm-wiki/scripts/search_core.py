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

By default every query term also matches the forms of the same word that occur
in the searched files, and query words additionally match through two
disclosed heuristics, compound parts and one-edit typo corrections (see
wordforms.py). Each result names the rule that matched in `match_rules`, and
the coverage block lists the forms per term. `word_forms=False` runs the
literal search exactly as it was before the word-form layer existed.

A search may carry up to four reformulations of the query, written by the
agent (synonyms, the wiki's own terms, a translation). One call reads the
release once and ranks the query and every reformulation over it. The query's
own `results`, `coverage` and `facets` stay exactly what they are without
reformulations; each result only names the searches that found it in
`found_by`. Pages that only reformulations return within the limit come back
separately in `reformulation_results`, taken in turn by rank from each
reformulation and never mixed into the query's ranking.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional

import bm25
import freshness
import trust_contract
import wordforms
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

#: Version of the coverage block's shape. Version 2 counts word forms and adds
#: `forms`, `forms_total`, `form_only_terms` and the per-result `match_rules`.
#: Version 3 adds the per-search counts `formulations` and
#: `reformulation_results`; every report carries them, with or without
#: reformulations.
COVERAGE_FORMAT = "lmwiki-search-coverage/3"
#: At most this many reformulations per call, so at most five searches with the query.
MAX_ALSO = 4
#: The longest reformulation, counted after stripping surrounding whitespace.
MAX_FORMULATION_CHARS = 200
#: The largest request `--request -` reads from standard input.
MAX_REQUEST_BYTES = 65536
#: The keys a request may hold; any other key is refused.
REQUEST_KEYS = ("query", "also", "filter")
#: The fixed sentence that keeps a reader from taking the reformulation block for coverage.
REFORMULATION_BOUNDARY = (
    "These pages were returned by the agent's reformulations, not by the words of the question, and are "
    "ordered by their rank within each reformulation, not by score. They count as found only after the "
    "page has been read and confirmed to answer the question; neither this list nor its absence shows "
    "whether the wiki covers the topic."
)
#: A question mark directly before a letter: how Windows PowerShell 5.1 pipes a
#: non-ASCII character when its output encoding is ASCII ("K?ndigung",
#: "?kostrom", "Gr??e"). A damaged character at the end of a word ("s??") is
#: not caught, so the escapes stay the only reliable protection.
RE_ENCODED = re.compile(r"\?[^\W\d_]")
#: A lone surrogate code point: half of a character outside U+FFFF, which a
#: JSON escape can produce but no UTF-8 output can carry.
RE_SURROGATE = re.compile(r"[\ud800-\udfff]")
#: Why a request with a lone surrogate escape is refused, and what to send instead.
SURROGATE_DETAIL = (
    "holds a lone surrogate escape; write a character outside U+FFFF as a surrogate pair, or as UTF-8"
)
#: How a reader learns to send text that no console code page can change.
ESCAPE_HINT = "escape every non-ASCII character as \\uXXXX"
#: How many forms the coverage block names per query term.
FORMS_LISTED = 10
#: How many matches beyond the limit the coverage block names with path and score.
OMITTED_TOP_LIMIT = 20
#: Searchable layers of a release, in the order the coverage block lists them.
SCOPES = ("wiki", "sources", "history")
#: The fixed sentence every coverage block carries, so no reader takes a count for a verdict.
COVERAGE_BOUNDARY = (
    "These counts describe matches of the listed terms in the listed files, counting the forms "
    "of the same word and the disclosed compound and typo matches listed under forms. They do not "
    "show that the wiki holds nothing on the topic: a page that uses other words, an irregular "
    "form or another language is not counted."
)
#: Files that route a reader to content instead of holding it. Any index.md is one too.
NAVIGATION_FILES = frozenset({"WIKI.md", "meta/questions.md"})


class QueryError(ValueError):
    """The query holds no token the search can match."""


class RequestError(ValueError):
    """A request or its reformulations cannot be searched; the message is ready for the user."""


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


#: The stopword list normalised like every token, so "für" is dropped as "fur".
FORM_STOPWORDS = frozenset(normalized(word) for word in STOPWORDS)
#: Words that match only literally: the stopwords and the closed word classes.
CLOSED_CLASS = FORM_STOPWORDS | wordforms.closed_class(normalized)


def tokens(value: str, drop_stopwords: bool = True, forms: bool = False) -> list[str]:
    """The normalised whole words of a text.

    With `forms` (the word-form layer), layout artefacts that split a word are
    repaired first and the stopword list is compared in its normalised form.
    Without it, tokens are exactly those of the literal search.
    """
    if forms:
        value = wordforms.repair_text(value)
    values = TOKEN.findall(normalized(value))
    if drop_stopwords:
        stopwords = FORM_STOPWORDS if forms else STOPWORDS
        values = [value for value in values if value not in stopwords and len(value) > 1]
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


def alias_values(value: Any) -> list[str]:
    """Page aliases as a list: a list as before, a non-empty string as one alias (lint warns), anything else none."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        return [value]
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


def term_in_query(term_tokens: list[str], query_tokens: list[str]) -> bool:
    """A concept term matches a run of whole query words, each the same word by spelling or inflection.

    Compound parts and typo corrections never trigger a concept: a confirmed
    concept must not be pulled in by a guess.
    """
    width = len(term_tokens)
    for start in range(len(query_tokens) - width + 1):
        if all(
            wordforms.same_word(query_tokens[start + offset], term_tokens[offset], CLOSED_CLASS)
            for offset in range(width)
        ):
            return True
    return False


def expand_query(
    query: str, definitions: dict[str, dict[str, Any]], forms: bool = False
) -> tuple[set[str], list[str], list[str]]:
    original_tokens = set(tokens(query, forms=forms)) or set(tokens(query, drop_stopwords=False, forms=forms))
    query_words = tokens(query, drop_stopwords=False, forms=forms)
    normalized_query = " ".join(query_words)
    matched: list[str] = []
    expanded_terms: list[str] = []
    expanded_tokens = set(original_tokens)
    for concept_id, definition in sorted(definitions.items()):
        terms = [str(term) for term in definition.get("terms", []) if str(term).strip()]
        term_matches = False
        for term in terms:
            term_words = tokens(term, drop_stopwords=False, forms=forms)
            normalized_term = " ".join(term_words)
            if not normalized_term:
                continue
            if forms:
                term_matches = term_in_query(term_words, query_words)
            elif " " in normalized_term:
                term_matches = normalized_term in normalized_query
            else:
                term_matches = normalized_term in set(query_words)
            if term_matches:
                break
        if not term_matches:
            continue
        matched.append(concept_id)
        for term in terms:
            if term not in expanded_terms:
                expanded_terms.append(term)
            expanded_tokens.update(tokens(term, drop_stopwords=False, forms=forms))
    return expanded_tokens, matched, expanded_terms


def query_terms(
    query: str, expanded_terms: list[str], forms: bool = False
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The terms the ranking matches, in a stable order and with their origin, plus dropped words.

    The term set equals the token set `expand_query` returns for the same query:
    the query's own words without stopwords and single characters (or all of its
    words when nothing else is left), then the tokens of every confirmed concept
    term the query triggered. Dropped words are reported only when they were
    actually left out of the ranking: a stopword that a confirmed concept term
    brings back, such as "und" in "Arbeitspreis und Grundpreis", is ranked and
    therefore listed as a term of origin `concept-expansion`, not as dropped.
    """
    words = tokens(query, drop_stopwords=False, forms=forms)
    stopwords = FORM_STOPWORDS if forms else STOPWORDS
    kept = [word for word in words if word not in stopwords and len(word) > 1]
    terms: list[dict[str, str]] = []
    seen: set[str] = set()
    for word in kept or words:
        if word not in seen:
            seen.add(word)
            terms.append({"term": word, "origin": "query"})
    for expanded in expanded_terms:
        for word in tokens(expanded, drop_stopwords=False, forms=forms):
            if word not in seen:
                seen.add(word)
                terms.append({"term": word, "origin": "concept-expansion"})
    dropped: list[dict[str, str]] = []
    if kept:
        for word in words:
            if word in seen:
                continue
            seen.add(word)
            dropped.append({"term": word, "reason": "stopword" if word in stopwords else "single-character"})
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


#: A wiki link with a label, and a Markdown link: the label is what a reader sees.
LABELLED_WIKILINK = re.compile(r"\[\[[^\[\]|]*\|([^\[\]]*)\]\]")
MARKDOWN_LINK = re.compile(r"(?<!!)\[([^\[\]]*)\]\([^()\s]*\)")


def visible_body(body: str, forms: bool = False) -> str:
    """The body without claim metadata; with `forms`, also without the targets of labelled links.

    A link target is an address, not text. The word-form layer must not let
    "[[wiki/concepts/kuendigungsfrist|Kündigungsfrist]]" count the word twice,
    once as the folded slug and once as the label.
    """
    text = CLAIM_BLOCK.sub(lambda match: match.group("text"), body)
    if forms:
        text = LABELLED_WIKILINK.sub(lambda match: match.group(1), text)
        text = MARKDOWN_LINK.sub(lambda match: match.group(1), text)
    return text


def overlap(query_tokens: Any, text_tokens: set[str]) -> int:
    """How many query terms a text holds.

    `query_tokens` is a set of literal tokens, or a mapping from every token
    that counts to the term it counts for; then each term counts once, however
    many of its forms the text holds.
    """
    if isinstance(query_tokens, dict):
        return len({query_tokens[token] for token in text_tokens if token in query_tokens})
    return len(query_tokens & text_tokens)


def relevant_claims(
    claims: list[dict[str, Any]],
    query_tokens: Any,
    concept_match: bool = False,
    forms: bool = False,
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for claim in claims:
        claim_tokens = set(tokens(str(claim.get("text") or ""), drop_stopwords=False, forms=forms))
        held = overlap(query_tokens, claim_tokens)
        if held:
            ranked.append((held, str(claim.get("id") or ""), claim))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if ranked:
        return [claim for _, _, claim in ranked[:8]]
    if concept_match:
        return [claim for claim in claims if claim.get("status") in {"active", "disputed"}][:8]
    return []


def best_snippet(body: str, query_tokens: Any, forms: bool = False) -> str:
    candidates: list[tuple[int, str]] = []
    for line in body.splitlines():
        compact = " ".join(line.strip().split())
        if not compact or compact.startswith("#"):
            continue
        line_tokens = set(tokens(compact, drop_stopwords=False, forms=forms))
        held = overlap(query_tokens, line_tokens)
        if held:
            candidates.append((held, compact))
    if not candidates:
        return ""
    snippet = max(candidates, key=lambda item: (item[0], len(item[1])))[1]
    return snippet if len(snippet) <= 320 else snippet[:317].rstrip() + "..."


def document_fields(data: dict[str, Any], body: str, forms: bool = False) -> dict[str, list[str]]:
    """Split one document into the weighted fields BM25F scores over."""
    return {
        "title": tokens(str(data.get("title") or ""), False, forms),
        "aliases": tokens(" ".join(alias_values(data.get("aliases"))), False, forms),
        "headings": tokens(" ".join(HEADING.findall(body)), False, forms),
        "description": tokens(
            str(data.get("description") or data.get("extraction_notes") or ""), False, forms
        ),
        "body": tokens(body, False, forms),
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


def read_document(path: Path, relative: str, text: Optional[str] = None, forms: bool = False) -> dict[str, Any]:
    """Parse one Markdown file into what ranking and accounting read from it.

    Raises FrontmatterError when the file is outside the frontmatter contract.
    """
    data, body = frontmatter(path.read_text(encoding="utf-8") if text is None else text, relative)
    searchable_body = visible_body(body, forms)
    heading = H1.search(searchable_body)
    title = str(data.get("title") or (heading.group(1).strip() if heading else path.stem))
    fields = document_fields({**data, "title": title}, searchable_body, forms)
    return {
        "data": data,
        "raw_body": body,
        "body": searchable_body,
        "title": title,
        "fields": fields,
        "words": set().union(*fields.values()),
    }


def unsearched_words(path: Path, relative: str, forms: bool = False) -> set[str]:
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
        return read_document(path, relative, text, forms)["words"]
    except FrontmatterError:
        return set(tokens(text, False, forms))


def scope_paths(target: Path, scope: str) -> list[Path]:
    """The Markdown files of one layer that is counted without being searched."""
    root = target / ("sources" if scope == "sources" else "meta/history")
    if not root.is_dir():
        return []
    return [path for path in sorted(root.rglob("*.md")) if path.is_file()]


def has_phrase(query_phrase: str, body_phrase: str, forms: bool = False) -> bool:
    """Whether a body holds all query words in a row, the phrase signal of the ranking.

    Both arguments are space-joined tokens. With the word-form layer only the
    literal query words count, and only on whole-token boundaries: "tarif" is
    no phrase in "festpreistarif" and none in "tarife". The literal search keeps
    its substring comparison.
    """
    if not query_phrase:
        return False
    if forms:
        return f" {query_phrase} " in f" {body_phrase} "
    return query_phrase in body_phrase


def term_members(
    ordered_terms: list[dict[str, str]],
    vocabulary: dict[str, int],
    forms: bool,
    attested_elsewhere: Iterable[str] = (),
    resolver: Optional[wordforms.Resolver] = None,
) -> dict[str, list[wordforms.Member]]:
    """Per query term, the tokens of the searched files that count for it, with rule and weight.

    Query words get word forms and, after them, the heuristics; concept
    expansions get word forms only. A term in `attested_elsewhere` occurs, as
    itself or as a word form, in a layer that was not searched; it is no typo,
    so it is never corrected to another word. Without the word-form layer
    every term is its literal token alone. `resolver`, when given, must be a
    resolver over `vocabulary`; one search builds it once for all its queries.
    """
    if not forms:
        return {
            item["term"]: ([(item["term"], "exact", wordforms.WEIGHTS["exact"])] if item["term"] in vocabulary else [])
            for item in ordered_terms
        }
    if resolver is None:
        resolver = wordforms.Resolver(vocabulary, CLOSED_CLASS, FORM_STOPWORDS)
    attested = set(attested_elsewhere)
    return {
        item["term"]: resolver.resolve(
            item["term"], heuristics=item["origin"] == "query", typos=item["term"] not in attested
        )
        for item in ordered_terms
    }


def layer_resolver(word_sets: list[set[str]], forms: bool) -> Optional[wordforms.Resolver]:
    """A word-form resolver over the vocabulary of one unsearched layer, or None for the literal search."""
    if not forms:
        return None
    vocabulary: dict[str, int] = {}
    for words in word_sets:
        for token in words:
            vocabulary[token] = vocabulary.get(token, 0) + 1
    return wordforms.Resolver(vocabulary, CLOSED_CLASS, FORM_STOPWORDS, heuristics=False)


def layer_tokens(term_names: list[str], resolver: Optional[wordforms.Resolver]) -> dict[str, frozenset]:
    """Per term, the tokens of a layer that are the same word, from that layer's `layer_resolver`."""
    if resolver is None:
        return {term: frozenset([term]) for term in term_names}
    return {
        term: frozenset(token for token, _, _ in resolver.resolve(term, heuristics=False)) for term in term_names
    }


def layer_members(term_names: list[str], word_sets: list[set[str]], forms: bool) -> dict[str, frozenset]:
    """Per term, the tokens of an unsearched layer that are the same word: literal and word forms only."""
    return layer_tokens(term_names, layer_resolver(word_sets, forms))


def scoring_groups(
    term_names: list[str],
    members_of: dict[str, list[wordforms.Member]],
    candidates: list[dict[str, Any]],
) -> tuple[list[bm25.TermGroup], list[bm25.TermGroup], dict[str, str]]:
    """The BM25 term groups for content pages and for navigation pages, and each term's group label.

    Terms that are forms of one word ("Tarif" and "Tarife", or a concept term
    the query already holds) form one group, so a page is not counted twice for
    one word. On navigation pages a group holds only its literal tokens. A
    group's document frequency counts the pages holding a word form; only a
    group with no such page counts the pages holding a heuristic member, so
    compound parts and typo corrections never make a word look common.
    """
    merged: dict[str, dict[str, Any]] = {}
    label_of: dict[str, str] = {}
    for term in term_names:
        identity = term if term in CLOSED_CLASS else wordforms.stem_key(term)
        entry = merged.setdefault(identity, {"label": term, "members": {}})
        label_of[term] = entry["label"]
        for token, rule, weight in members_of[term]:
            current = entry["members"].get(token)
            if current is None or weight > current[1]:
                entry["members"][token] = (rule, weight)
    content_groups: list[bm25.TermGroup] = []
    navigation_groups: list[bm25.TermGroup] = []
    for entry in merged.values():
        members = entry["members"]
        if not members:
            continue
        literal = frozenset(token for token in members if members[token][0] == "exact")
        word_forms = frozenset(token for token in members if members[token][0] in wordforms.WORD_FORM_RULES)
        heuristics = frozenset(members) - word_forms

        def holders(tokens_: frozenset) -> int:
            return sum(
                1
                for candidate in candidates
                if not candidate["words"].isdisjoint(literal if candidate["navigation"] else tokens_)
            )

        frequency = holders(word_forms) or holders(heuristics)
        weights = {token: members[token][1] for token in sorted(members)}
        content_groups.append(bm25.TermGroup(entry["label"], weights, frequency))
        navigation_groups.append(
            bm25.TermGroup(entry["label"], {token: weights[token] for token in sorted(literal)}, frequency)
        )
    return content_groups, navigation_groups, label_of


# -- requests and reformulations ----------------------------------------------


def _invalid_request(detail: str) -> RequestError:
    return RequestError(f"request is invalid: {detail}")


def _invalid_reformulations(detail: str) -> RequestError:
    return RequestError(f"reformulations are invalid: {detail}")


def request_from_stdin(stream: Any) -> dict[str, Any]:
    """Read one request from a wrapper's standard input and check it (see `read_request`).

    Only the stream's bytes are read: the text layer decodes with the host's
    locale, which differs between consoles. A terminal or a closed input is
    refused instead of waiting for input that never comes.
    """
    absent = _invalid_request(
        "--request - reads one JSON object from standard input, but standard input is a terminal or closed"
    )
    buffer = getattr(stream, "buffer", None)
    if stream is None or buffer is None:
        raise absent
    try:
        interactive = bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        interactive = False
    if interactive:
        raise absent
    try:
        raw = buffer.read(MAX_REQUEST_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise absent from exc
    return read_request(raw or b"")


def _request_text(raw: bytes) -> str:
    """The request bytes as text: UTF-8 with or without BOM, or UTF-16 as PowerShell may send it."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw, encoding = raw[3:], "utf-8"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif len(raw) > 1 and raw[1] == 0:
        encoding = "utf-16-le"
    elif raw[:1] == b"\x00":
        encoding = "utf-16-be"
    else:
        encoding = "utf-8"
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise _invalid_request(f"not UTF-8 text; send UTF-8, or {ESCAPE_HINT}") from exc


def read_request(raw: bytes) -> dict[str, Any]:
    """Decode and check one request object `{"query": ..., "also": [...], "filter": {...}}`.

    Returns `query` exactly as given, `also` as a list (empty when absent) and
    `filter` as the given object or None when absent. The selector itself is
    validated by the wrapper, like `--filter-json`. Raises RequestError with a
    message ready for the user.
    """
    if len(raw) > MAX_REQUEST_BYTES:
        raise _invalid_request(f"request exceeds {MAX_REQUEST_BYTES} bytes")
    text = _request_text(raw).lstrip("﻿").strip()
    if not text:
        raise _invalid_request("empty input; pipe one JSON object to --request -")

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for key, item in pairs:
            if key in found:
                raise _invalid_request(f"duplicate key '{key}'")
            found[key] = item
        return found

    def no_constant(_name: str) -> Any:
        raise _invalid_request("NaN and Infinity are not JSON")

    try:
        value = json.loads(text, object_pairs_hook=unique_keys, parse_constant=no_constant)
    except json.JSONDecodeError as exc:
        raise _invalid_request(f"not valid JSON: {exc.msg} (line {exc.lineno} column {exc.colno})") from exc
    except RecursionError as exc:
        raise _invalid_request("not valid JSON: nested too deeply") from exc
    if not isinstance(value, dict):
        raise _invalid_request("the top level must be a JSON object")
    for key in value:
        if key not in REQUEST_KEYS:
            raise _invalid_request(f"unknown key '{key}'; allowed keys are {', '.join(REQUEST_KEYS)}")
    query = value.get("query")
    if not isinstance(query, str) or not query.strip():
        raise _invalid_request("query must be a non-empty string")
    also = value.get("also", [])
    if not isinstance(also, list):
        raise _invalid_request("also must be a list of strings")
    for index, item in enumerate(also):
        if not isinstance(item, str):
            raise _invalid_request(f"also[{index}] must be a string")
    selector = value.get("filter")
    if "filter" in value and not isinstance(selector, dict):
        raise _invalid_request("filter must be a JSON object (a selector)")
    fields = [("query", query)] + [(f"also[{index}]", item) for index, item in enumerate(also)]
    for field, item in fields:
        if RE_SURROGATE.search(item):
            raise _invalid_request(f"{field} {SURROGATE_DETAIL}")
        if "�" in item or RE_ENCODED.search(item):
            raise _invalid_request(
                f"{field} looks re-encoded on the way (a ? before a letter, or U+FFFD); {ESCAPE_HINT}"
            )
    # The selector is printed back with the result, so it must be printable too.
    if selector is not None and any(RE_SURROGATE.search(text) for text in _json_strings(selector)):
        raise _invalid_request(f"filter {SURROGATE_DETAIL}")
    return {"query": query, "also": list(also), "filter": selector}


def _json_strings(value: Any) -> list[str]:
    """Every string in a decoded JSON value, object keys included, collected without recursion."""
    found: list[str] = []
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return found


def check_also(also: list[str]) -> None:
    """Refuse more than MAX_ALSO reformulations or one longer than MAX_FORMULATION_CHARS after stripping."""
    if len(also) > MAX_ALSO:
        raise _invalid_reformulations(
            f"at most {MAX_ALSO} reformulations may be given ({MAX_ALSO + 1} searches including the query); "
            f"got {len(also)}"
        )
    for position, entry in enumerate(also, 1):
        if not isinstance(entry, str):
            raise _invalid_reformulations(f"reformulation {position} is not a string")
        length = len(entry.strip())
        if length > MAX_FORMULATION_CHARS:
            raise _invalid_reformulations(
                f"reformulation {position} is longer than {MAX_FORMULATION_CHARS} characters ({length})"
            )


def formulation_key(text: str) -> str:
    """The words of a formulation in order, without case, accents or punctuation: what makes two the same search."""
    return " ".join(TOKEN.findall(normalized(text)))


def plan_formulations(query: str, also: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The searches of one call: the query first, then every reformulation that adds a search.

    A reformulation without a word, or with the same words in the same order
    as the query or an earlier kept reformulation, is dropped and reported with
    its 1-based `position` in the given list. Kept entries are numbered
    consecutively from 0, the query. Raises RequestError through `check_also`.
    """
    check_also(also)
    kept: list[dict[str, Any]] = [{"index": 0, "text": query, "origin": "query"}]
    seen = {formulation_key(query): 0}
    dropped: list[dict[str, Any]] = []
    for position, raw in enumerate(also, 1):
        text = raw.strip()
        key = formulation_key(text)
        if not key:
            dropped.append({"position": position, "text": text, "reason": "empty", "duplicate_of": None})
            continue
        if key in seen:
            dropped.append({"position": position, "text": text, "reason": "duplicate", "duplicate_of": seen[key]})
            continue
        seen[key] = len(kept)
        kept.append({"index": len(kept), "text": text, "origin": "also"})
    return kept, dropped


# -- one release, any number of queries ------------------------------------------


class LoadedRelease:
    """Everything a search reads from one release that does not depend on the query.

    `load()` builds it once per call: every searched file read, parsed and
    tokenized, the selector applied, the unsearched layers counted, the
    vocabularies, the word-form resolvers and the BM25 corpus statistics.
    `rank()` ranks any number of queries over it without reading a file again.
    """

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


def load(
    root: Path,
    *,
    include_sources: bool = False,
    include_history: bool = False,
    selector: Optional[dict[str, Any]] = None,
    history_shipped: bool = True,
    path_prefix: str = "",
    word_forms: bool = True,
) -> LoadedRelease:
    """Read the release under `root` once for every query a call ranks (see `search` for the options)."""
    if include_history and not history_shipped:
        raise ValueError("this release ships no history layer to search")
    selector = selector if selector is not None else {"kind": "all"}
    forms = bool(word_forms)
    concept_definitions = controlled_concepts(root / "schema/CONCEPTS.md")

    searched_scopes = {"wiki": True, "sources": include_sources, "history": include_history}
    # Sources are always counted, searched or not; history only when searched.
    counted_scopes = {scope: searched_scopes[scope] or scope == "sources" for scope in SCOPES}
    scope_files = {scope: 0 for scope in SCOPES}

    searched = 0
    filtered_out = 0
    parser_errors: list[dict[str, str]] = []

    # BM25 needs corpus-wide term rarity and average field lengths, and the
    # word-form layer needs the vocabulary of every searched file, so every
    # file is read before any of them is scored or counted.
    searched_words: list[tuple[str, set[str], bool]] = []
    candidates: list[dict[str, Any]] = []
    for path in candidate_paths(root, include_sources, include_history):
        searched += 1
        relative = path.relative_to(root).as_posix()
        scope = scope_of(relative)
        scope_files[scope] += 1
        try:
            document = read_document(path, relative, forms=forms)
        except FrontmatterError as exc:
            parser_errors.append({"path": path_prefix + relative, "error": str(exc)})
            continue
        # Counted before the selector applies: a metadata restriction narrows
        # the results, but must not make an existing term look absent.
        navigation = is_navigation(relative)
        searched_words.append((scope, document["words"], navigation))
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
                "raw_body": document["raw_body"],
                "fields": document["fields"],
                "words": document["words"],
                "navigation": navigation,
            }
        )
    unsearched: dict[str, list[set[str]]] = {}
    for scope in SCOPES:
        if counted_scopes[scope] and not searched_scopes[scope]:
            for path in scope_paths(root, scope):
                relative = path.relative_to(root).as_posix()
                scope_files[scope] += 1
                unsearched.setdefault(scope, []).append(unsearched_words(path, relative, forms))

    # Which tokens count for which term is decided on every searched file,
    # before the selector, so a selector never changes what a word matches.
    # Navigation pages route to content and are never cited; on them only the
    # literal token counts, so word forms cannot lift an index into the top.
    vocabulary: dict[str, int] = {}
    content_vocabulary: dict[str, int] = {}
    for _scope, words, navigation in searched_words:
        for token in words:
            vocabulary[token] = vocabulary.get(token, 0) + 1
            if not navigation:
                content_vocabulary[token] = content_vocabulary.get(token, 0) + 1
    return LoadedRelease(
        root=root,
        forms=forms,
        include_sources=include_sources,
        history_shipped=history_shipped,
        path_prefix=path_prefix,
        concept_definitions=concept_definitions,
        searched_scopes=searched_scopes,
        counted_scopes=counted_scopes,
        scope_files=scope_files,
        searched=searched,
        filtered_out=filtered_out,
        parser_errors=parser_errors,
        searched_words=searched_words,
        candidates=candidates,
        unsearched=unsearched,
        # Unsearched layers count the literal token and its word forms only.
        layer_resolvers={scope: layer_resolver(word_sets, forms) for scope, word_sets in unsearched.items()},
        vocabulary=vocabulary,
        content_vocabulary=content_vocabulary,
        resolver=wordforms.Resolver(vocabulary, CLOSED_CLASS, FORM_STOPWORDS) if forms else None,
        corpus=bm25.Corpus(candidate["fields"] for candidate in candidates),
    )


def candidate_phrase(candidate: dict[str, Any]) -> str:
    """A candidate's body as space-joined tokens for the phrase signal, built once per call."""
    phrase = candidate.get("phrase")
    if phrase is None:
        phrase = candidate["phrase"] = " ".join(candidate["fields"]["body"])
    return phrase


def candidate_claims(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """A candidate's claim blocks, parsed once per call and only for printed entries."""
    claims = candidate.get("claims")
    if claims is None:
        claims = candidate["claims"] = claims_in(candidate["raw_body"])
    return claims


class Ranking:
    """One query ranked over a loaded release.

    `ordered` holds every match sorted by score, then path, as result objects
    whose `snippet`, `claims`, `claims_total` and `claims_returned` are still
    empty; `full(i)` returns entry i completed. `rank_of` maps each matched
    path to its 1-based rank. `coverage`, `facets`, `matched_concepts` and
    `expanded_terms` describe this query alone.
    """

    def __init__(
        self,
        matches: list[tuple[dict[str, Any], dict[str, Any], bool]],
        highlight: Any,
        forms: bool,
        coverage: dict[str, Any],
        matched_concepts: list[str],
        expanded_terms: list[str],
    ) -> None:
        self.ordered = [result for result, _, _ in matches]
        self._pending = [(candidate, concept_match) for _, candidate, concept_match in matches]
        self._highlight = highlight
        self._forms = forms
        self.rank_of = {result["path"]: number for number, result in enumerate(self.ordered, 1)}
        self.coverage = coverage
        self.facets = facets(self.ordered)
        self.matched_concepts = matched_concepts
        self.expanded_terms = expanded_terms

    def full(self, index: int) -> dict[str, Any]:
        """Entry `index` of `ordered` with its snippet and claims, as a new object."""
        result = dict(self.ordered[index])
        candidate, concept_match = self._pending[index]
        page_claims = candidate_claims(candidate)
        claims = relevant_claims(page_claims, self._highlight, concept_match, self._forms)
        result["snippet"] = best_snippet(candidate["body"], self._highlight, self._forms)
        result["claims"] = claims
        result["claims_total"] = len(page_claims)
        result["claims_returned"] = len(claims)
        return result


def rank(loaded: LoadedRelease, query: str, *, limit: int) -> Ranking:
    """Rank one query over a loaded release and account for what its top `limit` does not show.

    Raises QueryError for a query without a searchable token.
    """
    forms = loaded.forms
    query_token_set, matched_concepts, expanded_terms = expand_query(query, loaded.concept_definitions, forms)
    if not query_token_set:
        raise QueryError("query must contain at least one searchable token")
    ordered_terms, dropped_terms = query_terms(query, expanded_terms, forms)
    term_names = [item["term"] for item in ordered_terms]
    searched_scopes = loaded.searched_scopes
    counted_scopes = loaded.counted_scopes
    include_sources = loaded.include_sources
    vocabulary = loaded.vocabulary
    content_vocabulary = loaded.content_vocabulary
    candidates = loaded.candidates

    files_with_term = {scope: 0 for scope in SCOPES}
    term_files = {scope: {term: 0 for term in term_names} for scope in SCOPES}

    def account(scope: str, words: set[str], tokens_of: dict[str, frozenset]) -> None:
        present = [term for term in term_names if not tokens_of[term].isdisjoint(words)]
        for term in present:
            term_files[scope][term] += 1
        if present:
            files_with_term[scope] += 1

    # Unsearched layers count the literal token and its word forms only.
    for scope, word_sets in loaded.unsearched.items():
        tokens_of = layer_tokens(term_names, loaded.layer_resolvers[scope])
        for words in word_sets:
            account(scope, words, tokens_of)
    attested_unsearched = {
        term for term in term_names if any(term_files[scope][term] for scope in loaded.unsearched)
    }

    members_of = term_members(ordered_terms, vocabulary, forms, attested_unsearched, loaded.resolver)
    member_tokens = {term: frozenset(token for token, _, _ in members_of[term]) for term in term_names}
    literal_tokens = {
        term: frozenset(token for token, rule, _ in members_of[term] if rule == "exact") for term in term_names
    }
    # The same word: the literal token and its word forms, never a compound part or typo.
    form_tokens = {
        term: frozenset(token for token, rule, _ in members_of[term] if rule in wordforms.WORD_FORM_RULES)
        for term in term_names
    }
    same_word_searched: set[str] = set()
    for scope, words, navigation in loaded.searched_words:
        account(scope, words, literal_tokens if navigation else member_tokens)
        same_word = literal_tokens if navigation else form_tokens
        same_word_searched.update(term for term in term_names if not same_word[term].isdisjoint(words))

    corpus = loaded.corpus
    matched_concept_set = set(matched_concepts)
    query_phrase = " ".join(tokens(query, False, forms))
    groups: Optional[list[bm25.TermGroup]] = None
    navigation_groups: Optional[list[bm25.TermGroup]] = None
    label_of: dict[str, str] = {}
    # What claims and snippets are matched with: literal tokens, or every
    # counting token mapped to the word it counts for.
    highlight: Any = query_token_set
    if forms:
        groups, navigation_groups, label_of = scoring_groups(term_names, members_of, candidates)
        highlight = {}
        for term in term_names:
            for token in sorted(member_tokens[term]):
                highlight.setdefault(token, label_of[term])
    # A file holding no token that counts for any term scores 0, because the
    # ranking never turns a non-match into a match; it is not scored at all.
    scored_tokens = frozenset().union(*member_tokens.values()) if forms else frozenset(query_token_set)

    path_prefix = loaded.path_prefix
    matches: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
    for candidate in candidates:
        if candidate["words"].isdisjoint(scored_tokens):
            continue
        data = candidate["data"]
        relative = candidate["relative"]
        document_concepts = set(as_list(data.get("concepts")))
        phrase_match = has_phrase(query_phrase, candidate_phrase(candidate), forms)
        counted: dict[str, list[str]] = {}
        score = bm25.score(
            corpus,
            candidate["fields"],
            query_token_set,
            phrase_match=phrase_match,
            concept_overlap=len(document_concepts & matched_concept_set),
            status=str(data.get("status") or ""),
            groups=navigation_groups if candidate["navigation"] else groups,
            counted=counted,
        )
        if score <= 0:
            continue
        if forms:
            # On a navigation page only a term's own literal token counted.
            allowed = literal_tokens if candidate["navigation"] else member_tokens
            counted_tokens = {term: set(counted.get(label_of[term], ())) & allowed[term] for term in term_names}
        else:
            counted_tokens = {term: {term} & candidate["words"] for term in term_names}
        result = {
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
            # Filled by Ranking.full() for entries that are printed.
            "snippet": None,
            "claims": None,
            "matched_terms": [term for term in term_names if member_tokens[term] & counted_tokens[term]],
            "match_rules": [
                {"term": term, "token": token, "rule": rule, "weight": weight}
                for term in term_names
                for token, rule, weight in members_of[term]
                if token in counted_tokens[term]
            ],
            "claims_total": None,
            "claims_returned": None,
            "navigation": candidate["navigation"],
        }
        matches.append((result, candidate, bool(document_concepts & matched_concept_set)))

    matches.sort(key=lambda match: (-float(match[0]["score"]), str(match[0]["path"])))
    results = [result for result, _, _ in matches]
    returned = results[:limit]
    omitted = results[limit:]

    def files_per_scope(term: str) -> dict[str, Optional[int]]:
        return {scope: term_files[scope][term] if counted_scopes[scope] else None for scope in SCOPES}

    def in_searched_files(term: str) -> bool:
        return any(term_files[scope][term] for scope in SCOPES if searched_scopes[scope])

    def counting_files(token: str, rule: str) -> int:
        # The searched files in which a member counts: the literal token
        # everywhere, any other form only outside navigation pages.
        return (vocabulary if rule == "exact" else content_vocabulary).get(token, 0)

    def counting_members(term: str) -> list[tuple[str, str, float, int]]:
        found = [(token, rule, weight, counting_files(token, rule)) for token, rule, weight in members_of[term]]
        return sorted((member for member in found if member[3]), key=lambda member: (-member[2], -member[3], member[0]))

    def forms_of(term: str) -> list[dict[str, Any]]:
        return [
            {"token": token, "rule": rule, "weight": weight, "files": files}
            for token, rule, weight, files in counting_members(term)[:FORMS_LISTED]
        ]

    coverage = {
        "format": COVERAGE_FORMAT,
        "searched_files": loaded.searched,
        "matched": len(results),
        "returned": len(returned),
        "truncated": len(results) > len(returned),
        "omitted_count": len(omitted),
        "omitted_top": [{"path": item["path"], "score": item["score"]} for item in omitted[:OMITTED_TOP_LIMIT]],
        "scopes": {
            scope: {
                "searched": searched_scopes[scope],
                "shipped": loaded.history_shipped if scope == "history" else True,
                "files": loaded.scope_files[scope] if counted_scopes[scope] else None,
                "files_with_a_query_term": files_with_term[scope] if counted_scopes[scope] else None,
            }
            for scope in SCOPES
        },
        "query_terms": [
            {
                **item,
                "files": files_per_scope(item["term"]),
                "forms": forms_of(item["term"]),
                "forms_total": len(counting_members(item["term"])),
            }
            for item in ordered_terms
        ],
        "dropped_terms": dropped_terms,
        "unmatched_terms": [
            item["term"] for item in ordered_terms if item["origin"] == "query" and not in_searched_files(item["term"])
        ],
        "form_only_terms": [
            item["term"]
            for item in ordered_terms
            if item["origin"] == "query" and item["term"] not in vocabulary and in_searched_files(item["term"])
        ],
        # Decided on the same basis as the unsearched layer: the word itself and
        # its word forms. A compound or typo match in the wiki is not the word.
        "terms_only_in_unsearched": {
            "sources": [
                term
                for term in term_names
                if not include_sources and term_files["sources"][term] and term not in same_word_searched
            ],
        },
        "boundary": COVERAGE_BOUNDARY,
    }
    return Ranking(matches, highlight, forms, coverage, matched_concepts, expanded_terms)


def found_by(rankings: list[Ranking], path: str) -> list[dict[str, int]]:
    """Every search whose ranking holds `path`, with the page's rank there, in formulation order."""
    return [
        {"formulation": index, "rank": ranking.rank_of[path]}
        for index, ranking in enumerate(rankings)
        if path in ranking.rank_of
    ]


def search(
    root: Path,
    query: str,
    *,
    also: Iterable[str] = (),
    limit: int = 12,
    include_sources: bool = False,
    include_history: bool = False,
    selector: Optional[dict[str, Any]] = None,
    history_shipped: bool = True,
    path_prefix: str = "",
    word_forms: bool = True,
) -> dict[str, Any]:
    """Rank the release under `root` for `query` and its reformulations, and account for what is not shown.

    `also` holds at most MAX_ALSO reformulations (see `plan_formulations`).
    `selector` must already be validated by `wiki_filters.validate_selector`.
    `history_shipped=False` describes a release that carries no history layer,
    such as an exported knowledge skill. `path_prefix` is prepended to every
    path the report names; selectors, scopes and navigation are decided on the
    release-relative path. `word_forms=False` runs the literal search without
    the word-form layer, for measurement and tests; the helpers never pass it.

    The release is read once and every formulation is ranked over it. The
    query's `matched_concepts`, `expanded_terms`, `facets` (over every match),
    `results` (at most `limit`) and `coverage` are exactly those of a search
    without reformulations, plus `found_by` on each result and the coverage
    keys `formulations` and `reformulation_results`. `reformulation_results`
    holds at most `limit` pages that only reformulations returned within the
    limit, without navigation pages. Also returned: `searched_files`,
    `filtered_out`, `formulations`, `dropped_formulations` and
    `parser_errors`. A caller must not report results when `parser_errors` is
    non-empty. Raises QueryError for a query without a searchable token,
    RequestError for invalid reformulations and ValueError for an impossible
    option.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if include_history and not history_shipped:
        raise ValueError("this release ships no history layer to search")
    also = list(also)
    kept, dropped = plan_formulations(query, also)
    if not TOKEN.findall(normalized(query)):
        raise QueryError("query must contain at least one searchable token")
    loaded = load(
        root,
        include_sources=include_sources,
        include_history=include_history,
        selector=selector,
        history_shipped=history_shipped,
        path_prefix=path_prefix,
        word_forms=word_forms,
    )
    rankings = [rank(loaded, query, limit=limit)]
    formulations = [kept[0]]
    dropped_positions = {item["position"] for item in dropped}
    kept_positions = [position for position in range(1, len(also) + 1) if position not in dropped_positions]
    for entry, position in zip(kept[1:], kept_positions):
        try:
            ranking = rank(loaded, entry["text"], limit=limit)
        except QueryError:
            # Defensive: plan_formulations already drops text without a word.
            dropped.append({"position": position, "text": entry["text"], "reason": "empty", "duplicate_of": None})
            continue
        formulations.append({**entry, "index": len(formulations)})
        rankings.append(ranking)
    dropped.sort(key=lambda item: item["position"])

    first = rankings[0]
    results: list[dict[str, Any]] = []
    for index in range(min(limit, len(first.ordered))):
        result = first.full(index)
        result["found_by"] = found_by(rankings, result["path"])
        results.append(result)

    # Pages only reformulations return within the limit, taken in turn by
    # rank: scores of different searches are not comparable, ranks are.
    shown = {result["path"] for result in results}
    pool: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    navigation_skipped: set[str] = set()
    for position in range(1, limit + 1):
        for formulation, ranking in enumerate(rankings[1:], 1):
            if position > len(ranking.ordered):
                continue
            item = ranking.ordered[position - 1]
            path = item["path"]
            if path in shown or path in seen:
                continue
            if item["navigation"]:
                navigation_skipped.add(path)
                continue
            seen.add(path)
            pool.append((path, formulation, position))
    block: list[dict[str, Any]] = []
    for path, via, position in pool[:limit]:
        entry = rankings[via].full(position - 1)
        entry["found_by"] = found_by(rankings, path)
        entry["via"] = via
        block.append(entry)
    omitted = pool[limit:]

    coverage = dict(first.coverage)
    coverage["formulations"] = [
        {
            "formulation": index,
            "matched": ranking.coverage["matched"],
            "within_limit": min(ranking.coverage["matched"], limit),
            "truncated": ranking.coverage["matched"] > limit,
            "contributed": sum(
                1
                for entry in block
                if any(hit["formulation"] == index and hit["rank"] <= limit for hit in entry["found_by"])
            ),
            "query_terms": [
                {key: value for key, value in item.items() if key != "forms"}
                for item in ranking.coverage["query_terms"]
            ],
            "dropped_terms": ranking.coverage["dropped_terms"],
            "unmatched_terms": ranking.coverage["unmatched_terms"],
            "form_only_terms": ranking.coverage["form_only_terms"],
            "terms_only_in_unsearched": ranking.coverage["terms_only_in_unsearched"],
        }
        for index, ranking in enumerate(rankings)
    ]
    coverage["reformulation_results"] = {
        "returned": len(block),
        "candidates": len(pool),
        "truncated": len(pool) > len(block),
        "omitted_count": len(omitted),
        "omitted_top": [
            {"path": path, "formulation": formulation, "rank": position}
            for path, formulation, position in omitted[:OMITTED_TOP_LIMIT]
        ],
        "navigation_skipped": len(navigation_skipped),
        "boundary": REFORMULATION_BOUNDARY,
    }
    return {
        "searched_files": loaded.searched,
        "filtered_out": loaded.filtered_out,
        "formulations": [
            {
                "index": entry["index"],
                "text": entry["text"],
                "origin": entry["origin"],
                "matched_concepts": ranking.matched_concepts,
                "expanded_terms": ranking.expanded_terms,
            }
            for entry, ranking in zip(formulations, rankings)
        ],
        "dropped_formulations": dropped,
        "matched_concepts": first.matched_concepts,
        "expanded_terms": first.expanded_terms,
        "facets": first.facets,
        "results": results,
        "reformulation_results": block,
        "coverage": coverage,
        "parser_errors": loaded.parser_errors,
    }
