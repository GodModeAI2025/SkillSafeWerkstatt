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
"""

from __future__ import annotations

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
COVERAGE_FORMAT = "lmwiki-search-coverage/2"
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
        "aliases": tokens(" ".join(as_list(data.get("aliases"))), False, forms),
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
) -> dict[str, list[wordforms.Member]]:
    """Per query term, the tokens of the searched files that count for it, with rule and weight.

    Query words get word forms and, after them, the heuristics; concept
    expansions get word forms only. A term in `attested_elsewhere` occurs, as
    itself or as a word form, in a layer that was not searched; it is no typo,
    so it is never corrected to another word. Without the word-form layer
    every term is its literal token alone.
    """
    if not forms:
        return {
            item["term"]: ([(item["term"], "exact", wordforms.WEIGHTS["exact"])] if item["term"] in vocabulary else [])
            for item in ordered_terms
        }
    resolver = wordforms.Resolver(vocabulary, CLOSED_CLASS, FORM_STOPWORDS)
    attested = set(attested_elsewhere)
    return {
        item["term"]: resolver.resolve(
            item["term"], heuristics=item["origin"] == "query", typos=item["term"] not in attested
        )
        for item in ordered_terms
    }


def layer_members(term_names: list[str], word_sets: list[set[str]], forms: bool) -> dict[str, frozenset]:
    """Per term, the tokens of an unsearched layer that are the same word: literal and word forms only."""
    if not forms:
        return {term: frozenset([term]) for term in term_names}
    vocabulary: dict[str, int] = {}
    for words in word_sets:
        for token in words:
            vocabulary[token] = vocabulary.get(token, 0) + 1
    resolver = wordforms.Resolver(vocabulary, CLOSED_CLASS, FORM_STOPWORDS, heuristics=False)
    return {
        term: frozenset(token for token, _, _ in resolver.resolve(term, heuristics=False)) for term in term_names
    }


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
    word_forms: bool = True,
) -> dict[str, Any]:
    """Rank the release under `root` for `query` and account for what is not shown.

    `selector` must already be validated by `wiki_filters.validate_selector`.
    `history_shipped=False` describes a release that carries no history layer,
    such as an exported knowledge skill. `path_prefix` is prepended to every
    path the report names; selectors, scopes and navigation are decided on the
    release-relative path. `word_forms=False` runs the literal search without
    the word-form layer, for measurement and tests; the helpers never pass it.

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
    forms = bool(word_forms)

    concept_definitions = controlled_concepts(root / "schema/CONCEPTS.md")
    query_token_set, matched_concepts, expanded_terms = expand_query(query, concept_definitions, forms)
    if not query_token_set:
        raise QueryError("query must contain at least one searchable token")
    ordered_terms, dropped_terms = query_terms(query, expanded_terms, forms)
    term_names = [item["term"] for item in ordered_terms]

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
                "claims": claims_in(document["raw_body"]),
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

    files_with_term = {scope: 0 for scope in SCOPES}
    term_files = {scope: {term: 0 for term in term_names} for scope in SCOPES}

    def account(scope: str, words: set[str], tokens_of: dict[str, frozenset]) -> None:
        present = [term for term in term_names if not tokens_of[term].isdisjoint(words)]
        for term in present:
            term_files[scope][term] += 1
        if present:
            files_with_term[scope] += 1

    # Unsearched layers count the literal token and its word forms only.
    for scope, word_sets in unsearched.items():
        tokens_of = layer_members(term_names, word_sets, forms)
        for words in word_sets:
            account(scope, words, tokens_of)
    attested_unsearched = {term for term in term_names if any(term_files[scope][term] for scope in unsearched)}

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
    members_of = term_members(ordered_terms, vocabulary, forms, attested_unsearched)
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
    for scope, words, navigation in searched_words:
        account(scope, words, literal_tokens if navigation else member_tokens)
        same_word = literal_tokens if navigation else form_tokens
        same_word_searched.update(term for term in term_names if not same_word[term].isdisjoint(words))

    corpus = bm25.Corpus(candidate["fields"] for candidate in candidates)
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

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        data = candidate["data"]
        relative = candidate["relative"]
        searchable_body = candidate["body"]
        page_claims = candidate["claims"]
        document_concepts = set(as_list(data.get("concepts")))
        phrase_match = has_phrase(query_phrase, " ".join(tokens(searchable_body, False, forms)), forms)
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
        claims = relevant_claims(page_claims, highlight, bool(document_concepts & matched_concept_set), forms)
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
                "snippet": best_snippet(searchable_body, highlight, forms),
                "claims": claims,
                "matched_terms": [term for term in term_names if member_tokens[term] & counted_tokens[term]],
                "match_rules": [
                    {"term": term, "token": token, "rule": rule, "weight": weight}
                    for term in term_names
                    for token, rule, weight in members_of[term]
                    if token in counted_tokens[term]
                ],
                "claims_total": len(page_claims),
                "claims_returned": len(claims),
                "navigation": candidate["navigation"],
            }
        )

    results.sort(key=lambda item: (-float(item["score"]), str(item["path"])))
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
