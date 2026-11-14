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

Every report also carries `absence_check`, the verdict on whether an absence
statement is allowed. With `exhaustive`, one call also ranks the sources and
scans every passage of the ranked files except navigation (page headers,
headings, claims, paragraphs, list items, tables, open questions) for all
content words of all formulations, in the members the ranking resolved plus
two scan-only additions: hyphen parts (`hyphen_part`) and the identifiers of
claim and page metadata. The hits come back under `exhaustive_hits`, cut to a
fixed budget of printed characters. The scan only adds keys: everything else equals the same
call with `include_sources`. Nothing is indexed or cached on disk.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, NamedTuple, Optional

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


# -- constants of the exhaustive scan and the absence check (Stufe 4) ----------

#: The most printed characters `exhaustive_hits` may take (owner decision E2),
#: counted exactly as the wrappers print the value, with REPORT_INDENT.
EXHAUSTIVE_BUDGET_CHARS = 100_000
#: The indent both wrappers print a report with; the budget is counted in it.
REPORT_INDENT = 2
#: A hit prints at most this many characters of its passage, cut around the first match.
EXCERPT_CHARS = 400
#: A passage ends once its text reaches this many characters, so a PDF
#: extraction without blank lines cannot become one passage per page.
PASSAGE_MAX_CHARS = 1_500
#: How many pages without a returned hit absence_check names.
OMITTED_PAGES_LISTED = 20
#: Counted reformulations a complete absence check needs.
MIN_EXHAUSTIVE_REFORMULATIONS = 2
#: The longest query the search record quotes before it is cut.
SEARCH_RECORD_QUERY_CHARS = 200
#: The kinds of passage the scan cuts a file into; hits on one line sort in this order.
PASSAGE_KINDS = ("header", "heading", "claim", "paragraph", "open_question")
#: Prepositions and contractions the closed class lacks, and the light verbs
#: of a question ("Gibt es ...?", "Wie geht ...?", "Was gilt ...?", "Was
#: passiert ...?"), which name no topic. A passage need not hold them; the
#: scan only. The ranking and the precision gate never use them.
SCAN_FUNCTION_WORDS = frozenset(normalized(word) for word in (
    "ab ans aufs außer binnen durchs fürs gegenüber hinter hinters innerhalb außerhalb neben samt statt "
    "trotz übers ums unters vors während wegen zwischen "
    "about after before between into over under via within without "
    "gibt gibts geben gab gegeben geht gehen ging gegangen gilt gelten galt gegolten passiert passieren "
    "funktioniert funktionieren steht stehen "
    "get gets got happen happens happened exist exists existed").split())
#: Words a passage never has to hold for a formulation to hit it.
SCAN_EXCLUDED = CLOSED_CLASS | SCAN_FUNCTION_WORDS
#: A page or slide marker of an extracted source, the grammar of validate_extraction.py.
PAGE_MARKER = re.compile(r"<!--\s*(page|slide)\s*:\s*([^>]+?)\s*-->", re.IGNORECASE)
#: Why an absence check is not complete, in the order they are listed.
ABSENCE_REASONS = ("not_exhaustive", "too_few_reformulations", "no_content_words", "budget_exhausted")
#: What to do before an absence statement, in the order they are listed.
ABSENCE_STEPS = (
    "read_withheld_claims", "read_results_without_claims", "read_reformulation_results", "read_exhaustive_hits",
    "add_reformulations", "narrow_formulations",
)
ABSENCE_CHECK_FORMAT = "lmwiki-absence-check/1"
SEARCH_RECORD_FORMAT = "lmwiki-search-record/1"
#: The fixed sentence every absence check carries: what a complete check shows, and what it does not.
ABSENCE_BOUNDARY = (
    "A complete check means that every passage of the scanned files that holds all content words "
    "of at least one searched formulation, in the forms listed under terms, itself or in its context, "
    "was returned under exhaustive_hits. Context is the page header, the headings and label lines above "
    "the passage, its parent list items and the first row of a split table, nothing else: a passage that "
    "needs a neighbouring paragraph, or that words the answer differently, with other words, an irregular "
    "form or another language, is not a hit, and layers marked scanned: false were not checked."
)
#: Order of the layers among pages with otherwise equal hits.
SCOPE_RANK = {"wiki": 0, "sources": 1, "history": 2}
#: A code fence: inside it no line is a heading or a marker.
FENCE = re.compile(r"^ {0,3}(```|~~~)")
#: A heading at column 0, as the ranking's HEADING counts it.
SCAN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
#: A list item starts a passage of its own.
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+")
#: Where an overlong line may be split.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
#: A setext heading underline under a one-line paragraph: = for level 1, - for level 2.
SETEXT_UNDERLINE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
#: A line that is only bold text, with an optional colon: a label that heads the passages after it.
BOLD_LABEL = re.compile(r"^(\*\*|__)(?=\S)(.+?)(?<=\S)\1:?$")
#: The longest one-line paragraph that may act as a label or a setext heading.
LABEL_MAX_CHARS = 100
#: A label's level on the heading stack: below every Markdown heading, so any heading or the next label ends it.
LABEL_LEVEL = 7
#: The scan's rule for a token that holds the word as one of its hyphen-separated parts
#: ("SMS" in "SMS-Warndienst"), and for the parts of a hyphenated search word written apart.
HYPHEN_PART_RULE = "hyphen_part"
#: Its weight, as low as a compound modifier; it only orders the listed forms and `matched`.
HYPHEN_PART_WEIGHT = 0.35
#: A source ID inside a wiki link or path, as the wiki contract names source files (`src-<hash>-<slug>.md`).
SOURCE_ID_IN_TEXT = re.compile(r"\bsrc-[0-9a-f]{16}(?![0-9a-z])")
#: A wiki link without a label; its target is an address, not text.
UNLABELLED_WIKILINK = re.compile(r"\[\[([^\[\]|]*)\]\]")


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


def claim_fields(match: "re.Match[str]") -> dict[str, Any]:
    """One claim block matched by CLAIM_BLOCK: its metadata and its text with whitespace collapsed."""
    metadata: dict[str, str] = {}
    for raw_line in match.group("meta").splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        metadata[key.strip().casefold()] = value.strip()
    return {
        "id": metadata.get("id", ""),
        "kind": metadata.get("kind", ""),
        "status": metadata.get("status", ""),
        "sources": split_pipe(metadata.get("sources", "")),
        "replaces": split_pipe(metadata.get("replaces", "")),
        "contradicts": split_pipe(metadata.get("contradicts", "")),
        "text": " ".join(match.group("text").split()),
    }


def claims_in(body: str) -> list[dict[str, Any]]:
    return [claim_fields(match) for match in CLAIM_BLOCK.finditer(body)]


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
            # The exhaustive scan is a command-line switch; the request keeps its three keys.
            hint = "; pass --exhaustive on the command line" if key == "exhaustive" else ""
            raise _invalid_request(f"unknown key '{key}'; allowed keys are {', '.join(REQUEST_KEYS)}{hint}")
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
    exhaustive: bool = False,
) -> LoadedRelease:
    """Read the release under `root` once for every query a call ranks (see `search` for the options).

    With `exhaustive`, which needs `include_sources`, every ranked file is also
    cut into passages and indexed for the exhaustive scan, from the same text
    the ranking parses: each file is still read once. The scan index is not
    built when any file is outside the frontmatter contract, because the
    wrappers refuse the results then.
    """
    if include_history and not history_shipped:
        raise ValueError("this release ships no history layer to search")
    if exhaustive and not include_sources:
        raise ValueError("an exhaustive search also ranks the sources; pass include_sources=True")
    if exhaustive and not word_forms:
        raise ValueError("an exhaustive search needs the word-form layer")
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
    scanned_files: list[tuple[str, str, str, dict[str, Any], bool]] = []
    for path in candidate_paths(root, include_sources, include_history):
        searched += 1
        relative = path.relative_to(root).as_posix()
        scope = scope_of(relative)
        scope_files[scope] += 1
        # The exhaustive scan segments the very text the ranking parses, so
        # the file is read here, once, exactly as read_document reads it.
        text = path.read_text(encoding="utf-8") if exhaustive else None
        try:
            document = read_document(path, relative, text, forms=forms)
        except FrontmatterError as exc:
            parser_errors.append({"path": path_prefix + relative, "error": str(exc)})
            continue
        # Counted before the selector applies: a metadata restriction narrows
        # the results, but must not make an existing term look absent.
        navigation = is_navigation(relative)
        searched_words.append((scope, document["words"], navigation))
        selected = matches_selector(document["data"], relative, selector)
        if exhaustive and not parser_errors:
            scanned_files.append((relative, scope, str(text), document, selected))
        if not selected:
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
        include_history=include_history,
        history_shipped=history_shipped,
        exhaustive=exhaustive,
        # The scan index; None without `exhaustive` and after a parser error.
        scan=(
            ScanIndex(scanned_files, include_history, history_shipped, path_prefix, selector != {"kind": "all"})
            if exhaustive and not parser_errors
            else None
        ),
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
    `expanded_terms` describe this query alone. `terms` (the ordered term
    dicts) and `members` (term -> list of (token, rule, weight)) are internal:
    the exhaustive scan matches every term in these members, so a report
    never lists different word forms for one word in two places; it only adds
    its own `hyphen_part` tokens and identifiers (see `scan_members`).
    """

    def __init__(
        self,
        matches: list[tuple[dict[str, Any], dict[str, Any], bool]],
        highlight: Any,
        forms: bool,
        coverage: dict[str, Any],
        matched_concepts: list[str],
        expanded_terms: list[str],
        terms: Optional[list[dict[str, str]]] = None,
        members: Optional[dict[str, list[wordforms.Member]]] = None,
    ) -> None:
        self.terms = list(terms or [])
        self.members = dict(members or {})
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
    return Ranking(matches, highlight, forms, coverage, matched_concepts, expanded_terms, ordered_terms, members_of)


def found_by(rankings: list[Ranking], path: str) -> list[dict[str, int]]:
    """Every search whose ranking holds `path`, with the page's rank there, in formulation order."""
    return [
        {"formulation": index, "rank": ranking.rank_of[path]}
        for index, ranking in enumerate(rankings)
        if path in ranking.rank_of
    ]


# -- the exhaustive scan (Stufe 4) -------------------------------------------------


class Passage(NamedTuple):
    """One unit of the exhaustive scan: a page header, heading, claim, paragraph, list item, table or open question.

    `line` is the 1-based file line where it starts, `locator` the claim ID or
    the source page or slide (`page=3`), `status` the claim status, `tokens`
    its own normalised words and identifiers, and `section` the path of its
    context, outermost first: the headings and labels above it, then its
    parent list items, then the first row of the table it continues (for a
    heading passage: its ancestors only). `opens` is the path this passage
    heads for the passages after it (a heading, a label, a list item, the
    first chunk of a split table), with the tokens that path holds in
    `opens_tokens`. `identifiers` are the tokens taken from metadata (claim,
    source and page IDs); they match only as whole tokens.
    """

    kind: str
    line: int
    locator: str
    status: str
    text: str
    tokens: frozenset
    section: tuple
    opens: tuple = ()
    opens_tokens: frozenset = frozenset()
    identifiers: frozenset = frozenset()


def link_labels(text: str) -> str:
    """A text with every labelled wiki link and Markdown link replaced by its label, as `visible_body` does."""
    if "[" not in text:
        return text
    text = LABELLED_WIKILINK.sub(lambda match: match.group(1), text)
    return MARKDOWN_LINK.sub(lambda match: match.group(1), text)


def inner_path(relative: str) -> str:
    """The path inside a history snapshot (after `meta/history/<snapshot-id>/`), otherwise the path itself."""
    if relative.startswith("meta/history/"):
        parts = relative.split("/", 3)
        return parts[3] if len(parts) == 4 else ""
    return relative


def scan_navigation(relative: str) -> bool:
    """True for WIKI.md and every index.md, decided inside a history snapshot on the inner path.

    Unlike the ranking, the scan reads `meta/questions.md`: an open question
    that names the asked word is exactly what an absence answer must disclose.
    """
    return inner_path(relative) == "WIKI.md" or PurePosixPath(relative).name == "index.md"


def sentence_chunks(line: str) -> list[str]:
    """An overlong line split at sentence ends into chunks of at most PASSAGE_MAX_CHARS where possible."""
    chunks: list[str] = []
    current = ""
    for sentence in SENTENCE_END.split(line):
        if current and len(current) + 1 + len(sentence) > PASSAGE_MAX_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        chunks.append(current)
    return chunks


def identifier_tokens(*values: Any) -> frozenset:
    """The normalised whole tokens of identifier values: claim, source and page IDs (pure)."""
    joined = " ".join(str(value) for value in values if value)
    if not joined:
        return frozenset()
    # IDs are almost always ASCII, where casefolding is all that normalized() does.
    return frozenset(TOKEN.findall(joined.lower() if joined.isascii() else normalized(joined)))


def link_addresses(text: str) -> frozenset:
    """The tokens of unlabelled wiki-link targets and the source IDs they name (pure).

    A link target is an address: it matches only as a whole token and is
    never split at its hyphens, so "[[wiki/entities/tarif-lindenstrom-fix12]]"
    never stands for the word "Tarif".
    """
    if "[[" not in text:
        return frozenset()
    found: set[str] = set()
    for target in UNLABELLED_WIKILINK.findall(text):
        target = normalized(target)
        found.update(TOKEN.findall(target))
        found.update(SOURCE_ID_IN_TEXT.findall(target))
    return frozenset(found)


def claim_identifiers(claim: dict[str, Any]) -> frozenset:
    """The IDs a claim block's metadata names: its own, its sources' (before the @ locator), replaced and contradicted claims."""
    return identifier_tokens(
        claim["id"],
        *(entry.split("@", 1)[0] for entry in claim["sources"]),
        *claim["replaces"],
        *claim["contradicts"],
    )


def scan_passages(relative: str, text: str, document: dict[str, Any]) -> list[Passage]:
    """Cut one file into the passages the exhaustive scan matches (pure).

    `document` is what `read_document` returned for `text`, so the frontmatter
    is parsed once. Lines are 1-based file lines, split on "\\n" only: a form
    feed from a PDF extraction must not shift them. Trailing whitespace is
    stripped from every line, so a CRLF file yields the same passages.

    Context reaches a passage from the headings above it (Markdown and setext
    headings, and labels: a one-line paragraph of at most LABEL_MAX_CHARS
    characters that is only bold text or ends in a colon, which lasts until
    the next heading or label), from its parent list items, and, in a table
    cut at the size cap, from the table's first row. The page header and every
    claim also carry the identifiers of their metadata as whole tokens: page
    and source IDs, and the claim, source, replaced and contradicted claim IDs.
    The targets of unlabelled wiki links are identifiers too (`link_addresses`).
    """
    data = document["data"]
    body = document["raw_body"]
    body_line = text.count("\n", 0, len(text) - len(body)) + 1
    title = str(document["title"])
    aliases = alias_values(data.get("aliases"))
    description = str(data.get("description") or data.get("extraction_notes") or "")
    header_text = title + (" — " + ", ".join(aliases) if aliases else "") + (" — " + description if description else "")
    listed_sources = " ".join(as_list(data.get("sources")))
    header_ids = identifier_tokens(data.get("id"), data.get("source_id"))
    if "src-" in listed_sources:
        header_ids = header_ids.union(SOURCE_ID_IN_TEXT.findall(normalized(listed_sources)))
    header_tokens = frozenset(tokens(title, False, True)).union(
        tokens(", ".join(aliases), False, True), tokens(description, False, True), header_ids
    )
    passages: list[Passage] = [Passage("header", 1, "", "", header_text, header_tokens, (), identifiers=header_ids)]
    title_tokens = tokens(title, False, True)
    plain_kind = "open_question" if inner_path(relative) == "meta/questions.md" else "paragraph"

    # The context stacks, each as parallel lists: headings and labels (level,
    # text) and list items (indent, text). `section` caches their texts.
    levels: list[int] = []
    labels: list[str] = []
    indents: list[int] = []
    items: list[str] = []
    section: tuple = ()
    fenced = False
    locator = ""
    lines: list[str] = []
    first_line = 0
    length = 0
    table = False
    listed = False
    indent = 0
    table_row = ""
    carried: tuple = ()

    def refresh() -> None:
        nonlocal section
        section = tuple(labels) + tuple(items) if items else tuple(labels)

    def pop_headings(level: int) -> None:
        while levels and levels[-1] >= level:
            levels.pop()
            labels.pop()

    def heading(level: int, label: str, number: int) -> None:
        indents.clear()
        items.clear()
        pop_headings(level)
        refresh()
        words = tokens(label, False, True)
        # An H1 that repeats the title is carried by the header passage.
        if words and not (level == 1 and words == title_tokens):
            found = frozenset(words)
            passages.append(Passage("heading", number, locator, "", label, found, section, section + (label,), found))
        levels.append(level)
        labels.append(label)
        refresh()

    def finish(cut: bool = False) -> None:
        nonlocal lines, length, table, listed, carried
        if not lines:
            # Most calls come from a blank line after a passage that already ended.
            carried = ()
            listed = False
            return
        if lines:
            raw = "\n".join(lines)
            # tokens(raw, False, True) repairs and then splits; the repaired text is also the display text.
            repaired = wordforms.repair_text(link_labels(raw))
            found = frozenset(TOKEN.findall(normalized(repaired)))
            addresses = link_addresses(raw)
            if addresses:
                found = found | addresses
            if found:
                shown = " ".join(repaired.split())
                label = (
                    len(lines) == 1 and not listed and not table and not items and len(shown) <= LABEL_MAX_CHARS
                    and (shown.endswith(":") or BOLD_LABEL.match(shown) is not None)
                )
                if label:
                    pop_headings(LABEL_LEVEL)
                    refresh()
                where = section + carried if carried else section
                opens: tuple = ()
                opens_tokens: frozenset = frozenset()
                if listed or label:
                    opens, opens_tokens = where + (shown,), found
                elif table and cut and not carried:
                    repaired_row = wordforms.repair_text(link_labels(table_row))
                    row_tokens = frozenset(TOKEN.findall(normalized(repaired_row)))
                    if row_tokens:
                        opens, opens_tokens = where + (" ".join(repaired_row.split()),), row_tokens
                passages.append(Passage(plain_kind, first_line, locator, "", shown, found, where, opens, opens_tokens, addresses))
                if label:
                    levels.append(LABEL_LEVEL)
                    labels.append(shown)
                    refresh()
                elif listed:
                    indents.append(indent)
                    items.append(shown)
                    refresh()
                if table and cut and opens:
                    carried = (opens[-1],)
        if not (cut and table):
            carried = ()
        lines = []
        length = 0
        table = False
        listed = False

    def append(line: str, number: int, is_table: bool = False) -> None:
        nonlocal first_line, length, table, table_row
        if len(line) > PASSAGE_MAX_CHARS:
            finish()
            for chunk in sentence_chunks(line):
                lines.append(chunk)
                first_line = number
                finish()
            return
        if not lines:
            first_line = number
            table = is_table
            length = len(line)
            if is_table and not carried:
                table_row = line
        else:
            length += 1 + len(line)
        lines.append(line)
        if length >= PASSAGE_MAX_CHARS:
            finish(cut=True)

    def enter(depth: int) -> None:
        # A new passage that is no list item leaves every list item indented as deep or deeper.
        nonlocal indent
        indent = depth
        if indents and indents[-1] >= depth:
            while indents and indents[-1] >= depth:
                indents.pop()
                items.pop()
            refresh()

    def handle(line: str, number: int) -> None:
        nonlocal fenced, locator, lines, length, listed
        line = line.rstrip()
        left = line.lstrip()
        # Each pattern runs only where its first characters can match: the scan reads every line.
        if left[:1] in ("`", "~") and FENCE.match(line):
            finish()
            fenced = not fenced
            return
        if not fenced:
            marker = PAGE_MARKER.search(line) if "<!--" in line else None
            if marker:
                finish()
                locator = f"{marker.group(1).lower()}={marker.group(2)}"
                rest = line[: marker.start()] + line[marker.end():]
                if rest.strip():
                    handle(rest, number)
                return
            atx = SCAN_HEADING.match(line) if line[:1] == "#" else None
            if atx:
                finish()
                heading(len(atx.group(1)), " ".join(wordforms.repair_text(link_labels(atx.group(2))).split()), number)
                return
            if (
                left[:1] in ("=", "-") and len(lines) == 1 and not table and not listed
                and SETEXT_UNDERLINE.match(line)
            ):
                label = " ".join(wordforms.repair_text(link_labels(lines[0])).split())
                if label and len(label) <= LABEL_MAX_CHARS:
                    number = first_line
                    lines = []
                    length = 0
                    heading(1 if left[0] == "=" else 2, label, number)
                    return
        if not left:
            finish()
            return
        first = left[0]
        if (first in "-*+" or first.isdigit()) and LIST_ITEM.match(line):
            finish()
            enter(len(line) - len(left))
            listed = True
            append(line, number)
            return
        if first == "|":  # a table row; consecutive rows form one passage
            if lines and not table:
                finish()
            if not lines:
                enter(len(line) - len(left))
            append(line, number, True)
            return
        if table:
            finish()
        if not lines:
            enter(len(line) - len(left))
        append(line, number)

    position = 0
    line_at = body_line

    def walk(segment: str, start: int) -> None:
        for offset, line in enumerate(segment.split("\n")):
            handle(line, start + offset)

    for match in CLAIM_BLOCK.finditer(body):
        walk(body[position:match.start()], line_at)
        finish()
        # A claim block stands at column 0: it ends every list.
        if items:
            indents.clear()
            items.clear()
            refresh()
        claim_line = line_at + body.count("\n", position, match.start())
        claim = claim_fields(match)
        identifiers = claim_identifiers(claim)
        addresses = link_addresses(match.group("text"))
        if addresses:
            identifiers = identifiers | addresses
        # Tokens come from the text with its line breaks, so a hyphen at a line end is repaired as the ranking does.
        found = frozenset(tokens(link_labels(match.group("text")), False, True)).union(identifiers)
        if found:
            passages.append(
                Passage("claim", claim_line, claim["id"], claim["status"], claim["text"], found, section, identifiers=identifiers)
            )
        line_at = claim_line + body.count("\n", match.start(), match.end())
        position = match.end()
    walk(body[position:], line_at)
    finish()
    return passages


def concept_runs(query: str, definitions: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """For each concept the query triggers, the query words of its first matching run (pure).

    Iterates exactly as `expand_query(query, definitions, forms=True)`: concept
    ids sorted, terms in definition order, the first term that matches, and its
    first start position where every word is the same word.
    """
    query_words = tokens(query, drop_stopwords=False, forms=True)
    runs: dict[str, list[str]] = {}
    for concept_id, definition in sorted(definitions.items()):
        terms = [str(term) for term in definition.get("terms", []) if str(term).strip()]
        for term in terms:
            term_words = tokens(term, drop_stopwords=False, forms=True)
            if not term_words:
                continue
            width = len(term_words)
            start = next(
                (
                    start
                    for start in range(len(query_words) - width + 1)
                    if all(
                        wordforms.same_word(query_words[start + offset], term_words[offset], CLOSED_CLASS)
                        for offset in range(width)
                    )
                ),
                None,
            )
            if start is not None:
                runs[concept_id] = query_words[start:start + width]
                break
    return runs


def content_words(terms: list[dict[str, str]]) -> list[str]:
    """The words a passage must hold for a formulation: its query words without closed-class and function words."""
    return [item["term"] for item in terms if item["origin"] == "query" and item["term"] not in SCAN_EXCLUDED]


def alternatives(
    words: list[str], runs: dict[str, list[str]], definitions: dict[str, dict[str, Any]]
) -> dict[str, list[tuple[Optional[str], tuple]]]:
    """Per content word, the word itself and then every confirmed concept term that may stand in for it."""
    found: dict[str, list[tuple[Optional[str], tuple]]] = {}
    for word in words:
        options: list[tuple[Optional[str], tuple]] = [(None, (word,))]
        listed = {(word,)}
        for concept_id in sorted(runs):
            if word not in runs[concept_id]:
                continue
            for term in definitions[concept_id].get("terms", []):
                if not str(term).strip():
                    continue
                option = tuple(token for token in tokens(str(term), False, True) if token not in SCAN_EXCLUDED)
                if option and option not in listed:
                    listed.add(option)
                    options.append((concept_id, option))
        found[word] = options
    return found


def hyphen_units(word: str) -> tuple:
    """The parts of a hyphenated content word that a passage may write apart, or () (pure).

    Closed-class and function words among them are dropped; at least two
    distinct parts of two or more characters must remain, so "E-Mobilität"
    never stands for "Mobilität" alone.
    """
    if "-" not in word and "_" not in word:
        return ()
    units = tuple(dict.fromkeys(unit for unit in wordforms.units_of(word) if unit not in SCAN_EXCLUDED))
    if len(units) < 2 or any(len(unit) < 2 for unit in units):
        return ()
    return units


def scan_members(ranking: Ranking, scan: "ScanIndex") -> dict[Any, list[wordforms.Member]]:
    """The members the scan matches per term: the ranking's, plus what only the scan can see.

    Two additions, both for terms outside the closed class and function words:

    - a term that is itself a scanned token but not one of the ranking's
      members gets it as `exact`; that only happens for an identifier from
      claim metadata or the frontmatter, which the ranking never reads;
    - every joined text token that holds the term as a hyphen-separated part
      of the same stem key ("sms" in "sms-warndienst") is added under the
      heuristic rule `hyphen_part`, which the ranking does not know.
    """
    parts = scan.hyphen_parts()
    members: dict[Any, list[wordforms.Member]] = {}
    for item in ranking.terms:
        term = item["term"]
        listed = list(ranking.members.get(term, ()))
        if term not in SCAN_EXCLUDED:
            known = {token for token, _, _ in listed}
            if term not in known and term in scan.own:
                listed.insert(0, (term, "exact", wordforms.WEIGHTS["exact"]))
                known.add(term)
            for token in sorted(parts.get(wordforms.stem_key(term), ())):
                if token not in known:
                    listed.append((token, HYPHEN_PART_RULE, HYPHEN_PART_WEIGHT))
        members[term] = listed
    return members


def counted_reformulations(formulations: list[dict[str, Any]], contents: list[list[str]]) -> list[bool]:
    """Which kept formulations count as reformulations for a complete absence check (pure).

    The question never counts. A reformulation counts when it has a content
    word and its set of content-word stem keys is neither equal to nor a
    superset of the question's set or of any earlier counted reformulation's
    set: the same words in another order, another spelling or another
    inflection are no new search, and neither are added words, which under
    the hit rule can only narrow what the scan finds. A hyphenated word
    counts as its parts (`hyphen_units`), because the scan matches
    "SMS-Warndienst" and "SMS Warndienst" against each other.
    """

    def stem_keys(words: list[str]) -> frozenset:
        return frozenset(wordforms.stem_key(unit) for word in words for unit in (hyphen_units(word) or (word,)))

    question = stem_keys(contents[0]) if contents else frozenset()
    seen = [question] if question else []
    counted: list[bool] = []
    for index, (entry, words) in enumerate(zip(formulations, contents)):
        keys = stem_keys(words)
        counts = (
            index > 0 and entry.get("origin") == "also" and bool(words) and not any(keys >= earlier for earlier in seen)
        )
        if counts:
            seen.append(keys)
        counted.append(counts)
    return counted


def printed_chars(value: Any, depth: int) -> int:
    """The characters `value` takes when a wrapper prints it nested `depth` levels deep with REPORT_INDENT."""
    text = json.dumps(value, ensure_ascii=False, indent=REPORT_INDENT)
    return len(text) + REPORT_INDENT * depth * text.count("\n")


def excerpt(text: str, wanted: frozenset) -> tuple[str, bool]:
    """A passage text, or a window of at most EXCERPT_CHARS characters around its first word in `wanted`."""
    if len(text) <= EXCERPT_CHARS:
        return text, False
    room = EXCERPT_CHARS - 4
    words = text.split(" ")
    starts: list[int] = []
    offset = 0
    for word in words:
        starts.append(offset)
        offset += len(word) + 1
    first = next((index for index, word in enumerate(words) if not wanted.isdisjoint(tokens(word, False, True))), 0)

    def window(start: int) -> list[str]:
        taken: list[str] = []
        size = 0
        for word in words[start:]:
            grown = size + len(word) + (1 if taken else 0)
            if grown > room:
                break
            taken.append(word)
            size = grown
        return taken

    start = first
    while start > 0 and starts[first] - starts[start - 1] <= 100:
        start -= 1
    taken = window(start)
    if start + len(taken) <= first:
        start = first
        taken = window(start)
    cut = False
    if not taken:
        taken = [words[start][:room]]
        cut = True
    remaining = cut or start + len(taken) < len(words)
    return ("… " if start > 0 else "") + " ".join(taken) + (" …" if remaining else ""), True


class ScanIndex:
    """The passages of every scanned file and the posting lists the hit rule needs, built once per call."""

    def __init__(
        self,
        files: list[tuple[str, str, str, dict[str, Any], bool]],
        include_history: bool,
        history_shipped: bool,
        path_prefix: str,
        mark_selected: bool,
    ) -> None:
        self.path_prefix = path_prefix
        self.mark_selected = mark_selected
        self.scanned = {"wiki": True, "sources": True, "history": include_history}
        self.shipped = {"wiki": True, "sources": True, "history": history_shipped}
        self.counts = {
            scope: {"files": 0, "navigation_skipped": 0, "passages": 0, "chars": 0} for scope in SCOPES
        }
        self.passages: list[Passage] = []
        self.passage_page: list[int] = []
        self.pages: list[dict[str, Any]] = []
        self.page_passages: list[range] = []
        self.own: dict[str, set[int]] = {}
        self.header_pages: dict[str, set[int]] = {}
        self.section_index: dict[str, set[tuple[int, tuple]]] = {}
        self.section_passages: dict[tuple[int, tuple], set[int]] = {}
        # Tokens that came from metadata or link targets: never split for the hyphen_part rule.
        self.identifiers: set[str] = set()
        self._parts: Optional[dict[str, frozenset]] = None
        self._stems: Optional[dict[str, frozenset]] = None
        for relative, scope, text, document, selected in files:
            if scan_navigation(relative):
                self.counts[scope]["navigation_skipped"] += 1
                continue
            self.counts[scope]["files"] += 1
            self.counts[scope]["chars"] += len(text)
            self.add_page(relative, scope, document, selected, scan_passages(relative, text, document))

    def add_page(
        self, relative: str, scope: str, document: dict[str, Any], selected: bool, passages: list[Passage]
    ) -> None:
        page = len(self.pages)
        self.pages.append(
            {
                "relative": relative,
                "scope": scope,
                "title": str(document["title"]),
                "status": str(document["data"].get("status") or ""),
                "selected": selected,
            }
        )
        first = len(self.passages)
        self.counts[scope]["passages"] += len(passages)
        own = self.own
        section_passages = self.section_passages
        # Consecutive passages share their section; its prefixes are computed once per section.
        prefixes: dict[tuple, list[tuple[int, tuple]]] = {}
        openers: list[Passage] = []
        for pid, passage in enumerate(passages, first):
            if passage.identifiers:
                self.identifiers.update(passage.identifiers)
            for token in passage.tokens:
                holders = own.get(token)
                if holders is None:
                    own[token] = {pid}
                else:
                    holders.add(pid)
            keys = prefixes.get(passage.section)
            if keys is None:
                keys = prefixes[passage.section] = [
                    (page, passage.section[:depth]) for depth in range(1, len(passage.section) + 1)
                ]
            for key in keys:
                holders = section_passages.get(key)
                if holders is None:
                    section_passages[key] = {pid}
                else:
                    holders.add(pid)
            if passage.kind == "header":
                for token in passage.tokens:
                    self.header_pages.setdefault(token, set()).add(page)
            if passage.opens:
                openers.append(passage)
        # A heading, label, list item or table row is context only for the
        # passages under it; one with nothing under it is not indexed.
        for passage in openers:
            key = (page, passage.opens)
            if key in section_passages:
                for token in passage.opens_tokens:
                    self.section_index.setdefault(token, set()).add(key)
        self.passages.extend(passages)
        self.passage_page.extend([page] * len(passages))
        # A heading that is not emitted (an H1 repeating the title) still
        # leads its section: its words are the title's, held by the header.
        self.page_passages.append(range(first, len(self.passages)))

    def hyphen_parts(self) -> dict[str, frozenset]:
        """Per stem key, the joined text tokens with a part of that key ("sms" -> "sms-warndienst"), built once.

        Identifiers and link targets are left out, even where the same token
        also stands in text: an address is never split at its hyphens.
        """
        if self._parts is None:
            parts: dict[str, set[str]] = {}
            for token in self.own:
                if ("-" not in token and "_" not in token) or token in self.identifiers:
                    continue
                for unit in wordforms.units_of(token):
                    if len(unit) >= 2 and unit not in SCAN_EXCLUDED:
                        parts.setdefault(wordforms.stem_key(unit), set()).add(token)
            self._parts = {key: frozenset(found) for key, found in parts.items()}
        return self._parts

    def stems(self) -> dict[str, frozenset]:
        """Per stem key, every scanned token with that key, built once and only for a hyphenated search word."""
        if self._stems is None:
            stems: dict[str, set[str]] = {}
            for token in self.own:
                stems.setdefault(wordforms.stem_key(token), set()).add(token)
            self._stems = {key: frozenset(found) for key, found in stems.items()}
        return self._stems

    def unit_members(self, unit: str) -> list[wordforms.Member]:
        """The members of one part of a hyphenated search word written apart: its stem key alone or as a part."""
        key = wordforms.stem_key(unit)
        found = self.stems().get(key, frozenset()) | self.hyphen_parts().get(key, frozenset())
        return [(token, HYPHEN_PART_RULE, HYPHEN_PART_WEIGHT) for token in sorted(found)]


class _Matcher:
    """The set algebra of the hit rule over one ScanIndex, with posting unions cached for one call."""

    def __init__(self, scan: ScanIndex) -> None:
        self.scan = scan
        self._own: dict[frozenset, set[int]] = {}
        self._context: dict[frozenset, set[int]] = {}

    def own(self, members: frozenset) -> set[int]:
        found = self._own.get(members)
        if found is None:
            found = set()
            for token in members:
                found.update(self.scan.own.get(token, ()))
            self._own[members] = found
        return found

    def context(self, members: frozenset) -> set[int]:
        """Passages that hold a member themselves, under a heading holding one, or on a page whose header holds one."""
        found = self._context.get(members)
        if found is None:
            scan = self.scan
            found = set(self.own(members))
            for token in members:
                for page in scan.header_pages.get(token, ()):
                    found.update(scan.page_passages[page])
                for key in scan.section_index.get(token, ()):
                    found.update(scan.section_passages.get(key, ()))
            self._context[members] = found
        return found


class _Formulation:
    """What the scan needs of one kept formulation: content words, alternatives and their members.

    The members are the ranking's (see `scan_members`). A hyphenated content
    word also gets the alternative of its parts written apart (`hyphen_units`),
    each part matched in its stem key, alone or as a part of a joined token;
    `splits` maps the word to the keys of those parts.
    """

    def __init__(self, text: str, ranking: Ranking, definitions: dict[str, dict[str, Any]], scan: ScanIndex) -> None:
        self.text = text
        self.terms = ranking.terms
        self.members: dict[Any, list[wordforms.Member]] = scan_members(ranking, scan)
        self.content = content_words(ranking.terms)
        self.alternatives = alternatives(self.content, concept_runs(text, definitions), definitions)
        self.splits: dict[str, tuple] = {}
        for word in self.content:
            units = hyphen_units(word)
            if not units:
                continue
            # Keys of their own, so a part never takes the members of a term with the same spelling.
            keys = tuple((HYPHEN_PART_RULE, unit) for unit in units)
            for key, unit in zip(keys, units):
                self.members[key] = scan.unit_members(unit)
            self.splits[word] = keys
            self.alternatives[word] = self.alternatives[word] + [(None, keys)]

    def tokens_of(self, token: Any, word_forms_only: bool) -> frozenset:
        return frozenset(
            member
            for member, rule, _ in self.members.get(token, ())
            if not word_forms_only or rule in wordforms.WORD_FORM_RULES
        )

    def hits(self, matcher: _Matcher, word_forms_only: bool) -> set[int]:
        """H_i: passages inside the context of every content word that hold at least one of them themselves."""
        if not self.content:
            return set()
        contexts: list[set[int]] = []
        owned: set[int] = set()
        for word in self.content:
            word_context: set[int] = set()
            for _concept, option in self.alternatives[word]:
                option_context: Optional[set[int]] = None
                option_own: set[int] = set()
                for token in option:
                    members = self.tokens_of(token, word_forms_only)
                    context = matcher.context(members)
                    option_context = set(context) if option_context is None else option_context & context
                    option_own |= matcher.own(members)
                word_context |= option_context or set()
                owned |= (option_context or set()) & option_own
            contexts.append(word_context)
        contexts.sort(key=len)
        found = set(contexts[0])
        for context in contexts[1:]:
            found &= context
        return found & owned

    def every_member(self) -> frozenset:
        """Every member token of every content word and of its alternatives."""
        return frozenset(
            member
            for word in self.content
            for _concept, option in self.alternatives[word]
            for token in option
            for member in self.tokens_of(token, False)
        )

    def matched(self, matcher: _Matcher, pid: int) -> list[dict[str, Any]]:
        """Per content word, the member that carried it into a heuristic hit, and where it occurred."""
        scan = matcher.scan
        passage = scan.passages[pid]
        page = scan.passage_page[pid]
        sections = {(page, passage.section[:depth]) for depth in range(1, len(passage.section) + 1)}
        entries: list[dict[str, Any]] = []
        for word in self.content:
            for concept, option in self.alternatives[word]:
                # The first alternative whose context holds the passage carried the word.
                if not all(pid in matcher.context(self.tokens_of(token, False)) for token in option):
                    continue
                pool = [member for token in option for member in self.members.get(token, ())]
                best: Optional[tuple[tuple[int, float, str], str]] = None
                for token, rule, weight in pool:
                    if token in passage.tokens:
                        where = 0
                    elif not sections.isdisjoint(scan.section_index.get(token, ())):
                        where = 1
                    elif page in scan.header_pages.get(token, ()):
                        where = 2
                    else:
                        continue
                    key = (where, -weight, token)
                    if best is None or key < best[0]:
                        best = (key, rule)
                if best is None:
                    continue
                entry: dict[str, Any] = {
                    "term": word,
                    "token": best[0][2],
                    "rule": best[1],
                    "in": ("text", "heading", "header")[best[0][0]],
                }
                if concept is not None:
                    entry["concept"] = concept
                entries.append(entry)
                break
        return entries


def printed_claim_keys(
    results: list[dict[str, Any]], block: list[dict[str, Any]], path_prefix: str
) -> dict[tuple[str, str], str]:
    """Every claim already printed, keyed by (release-relative path, claim ID or text), with where it is printed."""
    printed: dict[tuple[str, str], str] = {}
    for where, entries in (("results", results), ("reformulation_results", block)):
        for entry in entries:
            path = str(entry["path"])
            relative = path[len(path_prefix):] if path_prefix and path.startswith(path_prefix) else path
            for claim in entry.get("claims") or []:
                key = (relative, str(claim.get("id") or "") or str(claim.get("text") or ""))
                printed.setdefault(key, where)
    return printed


def exhaustive_scan(
    scan: ScanIndex,
    rankings: list[Ranking],
    texts: list[str],
    definitions: dict[str, dict[str, Any]],
    vocabulary: dict[str, int],
    printed: dict[tuple[str, str], str],
    counted: list[bool],
    budget: int,
) -> dict[str, Any]:
    """Every passage that holds all content words of a kept formulation, ordered, cut to `budget` printed characters.

    Returns the returned page entries (`hits`), whether the question's own
    hits fit into the budget (`narrowable`, internal), and the fields of
    absence_check that describe the scan: per-formulation counts, census,
    absent terms, counts, budget, omitted pages and scopes.
    """
    matcher = _Matcher(scan)
    formulations = [_Formulation(text, ranking, definitions, scan) for text, ranking in zip(texts, rankings)]
    by_formulation: list[set[int]] = []
    word_form_hits: set[int] = set()
    summary: list[dict[str, Any]] = []
    for index, formulation in enumerate(formulations):
        found = formulation.hits(matcher, False)
        strong = formulation.hits(matcher, True)
        by_formulation.append(found)
        word_form_hits |= strong
        summary.append(
            {
                "formulation": index,
                "content_words": formulation.content,
                "counted": counted[index],
                "hits": len(found),
                "hits_word_form": len(strong),
            }
        )
    all_hits = sorted(set().union(*by_formulation)) if by_formulation else []

    pages: dict[int, list[tuple[tuple[int, int, int], dict[str, Any]]]] = {}
    references = 0
    for pid in all_hits:
        passage = scan.passages[pid]
        page = scan.passage_page[pid]
        member_of = [index for index, found in enumerate(by_formulation) if pid in found]
        hit: dict[str, Any] = {
            "kind": passage.kind,
            "line": passage.line,
            "locator": passage.locator,
            "status": passage.status,
            "formulations": member_of,
            "strength": "word_form" if pid in word_form_hits else "heuristic",
        }
        key = (scan.pages[page]["relative"], passage.locator or passage.text)
        if passage.kind == "claim" and key in printed:
            hit["shown_in"] = printed[key]
            references += 1
        else:
            if hit["strength"] == "heuristic":
                hit["matched"] = formulations[member_of[0]].matched(matcher, pid)
            wanted = frozenset().union(*(formulations[index].every_member() for index in member_of))
            text, cut = excerpt(passage.text, wanted)
            hit.update({"text": text, "text_chars": len(passage.text), "excerpt": cut})
        pages.setdefault(page, []).append(((passage.line, PASSAGE_KINDS.index(passage.kind), pid), hit))

    entries: list[dict[str, Any]] = []
    for page, items in pages.items():
        items.sort(key=lambda item: item[0])
        hits = [hit for _, hit in items]
        info = scan.pages[page]
        entry: dict[str, Any] = {
            "path": scan.path_prefix + info["relative"],
            "scope": info["scope"],
            "title": info["title"],
            "status": info["status"],
            "hits_total": len(hits),
        }
        if scan.mark_selected:
            entry["selected"] = info["selected"]
        entry["hits"] = hits
        entries.append(entry)
    entries.sort(
        key=lambda entry: (
            1 if entry["scope"] == "history" else 0,
            -max(len(hit["formulations"]) for hit in entry["hits"]),
            0 if any(0 in hit["formulations"] for hit in entry["hits"]) else 1,
            0 if any(hit["strength"] == "word_form" for hit in entry["hits"]) else 1,
            SCOPE_RANK[entry["scope"]],
            entry["path"],
        )
    )

    # Emit a strict prefix: hit by hit while the printed size stays within budget.
    returned: list[dict[str, Any]] = []
    used = 2  # "[]"
    stopped = False
    for entry in entries:
        emitted: Optional[dict[str, Any]] = None
        for hit in entry["hits"]:
            if emitted is None:
                cost = (8 if not returned else 6) + printed_chars({**entry, "hits": [hit]}, 2)
            else:
                cost = 10 + printed_chars(hit, 4)
            if used + cost > budget:
                stopped = True
                break
            used += cost
            if emitted is None:
                emitted = {**entry, "hits": [hit]}
                returned.append(emitted)
            else:
                emitted["hits"].append(hit)
        if stopped:
            break
    used = printed_chars(returned, 1)
    needed = printed_chars(entries, 1) if stopped else used
    # Narrower reformulations can only help while the question's own hits fit:
    # its hits do not depend on the reformulations.
    # Counted with the same increments as the emission, and only until the budget is passed.
    narrowable = True
    if stopped:
        size = 2
        for entry in entries:
            own_hits = [hit for hit in entry["hits"] if 0 in hit["formulations"]]
            for position, hit in enumerate(own_hits):
                if position:
                    size += 10 + printed_chars(hit, 4)
                else:
                    size += (8 if size == 2 else 6) + printed_chars({**entry, "hits_total": len(own_hits), "hits": [hit]}, 2)
                if size > budget:
                    break
            if size > budget:
                narrowable = False
                break

    hits_total = len(all_hits)
    hits_returned = sum(len(entry["hits"]) for entry in returned)
    returned_paths = {entry["path"] for entry in returned}
    counts = {
        "hits_total": hits_total,
        "hits_returned": hits_returned,
        "hits_omitted": hits_total - hits_returned,
        "hits_word_form": len(word_form_hits.intersection(all_hits)),
        "hits_heuristic": hits_total - len(word_form_hits.intersection(all_hits)),
        "hits_already_printed": references,
        "pages_with_hits": len(entries),
        "pages_returned": len(returned),
        "pages_partial": sum(1 for entry in returned if len(entry["hits"]) < entry["hits_total"]),
        "pages_not_returned": len(entries) - len(returned),
    }
    omitted_pages = [
        {"path": entry["path"], "hits": entry["hits_total"]} for entry in entries if entry["path"] not in returned_paths
    ][:OMITTED_PAGES_LISTED]

    # The census: every term except closed-class and function words, once per (term, origin).
    census: dict[tuple[str, str], dict[str, Any]] = {}
    for index, formulation in enumerate(formulations):
        for item in formulation.terms:
            term, origin = item["term"], item["origin"]
            if term in SCAN_EXCLUDED:
                continue
            key = (term, origin)
            if key in census:
                census[key]["formulations"].append(index)
                continue
            members = formulation.members.get(term, [])
            holders = matcher.own(frozenset(token for token, _, _ in members))
            split = formulation.splits.get(term) if origin == "query" else None
            if split:
                # A hyphenated word also occurs where a passage holds all of its parts.
                apart: Optional[set[int]] = None
                for part in split:
                    owned = matcher.own(formulation.tokens_of(part, False))
                    apart = set(owned) if apart is None else apart & owned
                holders = holders | (apart or set())
            passages = {scope: 0 for scope in SCOPES}
            files: dict[str, set[int]] = {scope: set() for scope in SCOPES}
            for pid in holders:
                page = scan.passage_page[pid]
                scope = scan.pages[page]["scope"]
                passages[scope] += 1
                files[scope].add(page)
            ordered = sorted(members, key=lambda member: (-member[2], -vocabulary.get(member[0], 0), member[0]))
            census[key] = {
                "term": term,
                "origin": origin,
                "formulations": [index],
                "passages": {scope: passages[scope] if scan.scanned[scope] else None for scope in SCOPES},
                "files": {scope: len(files[scope]) if scan.scanned[scope] else None for scope in SCOPES},
                "forms": [{"token": token, "rule": rule} for token, rule, _ in ordered[:FORMS_LISTED]],
                "forms_total": len(members),
            }
    absent = sorted(
        {
            entry["term"]
            for entry in census.values()
            if entry["origin"] == "query" and not any(entry["passages"][scope] for scope in SCOPES if scan.scanned[scope])
        }
    )
    scopes = {
        scope: {
            "scanned": scan.scanned[scope],
            "shipped": scan.shipped[scope],
            **{
                field: (scan.counts[scope][field] if scan.scanned[scope] else None)
                for field in ("files", "navigation_skipped", "passages", "chars")
            },
        }
        for scope in SCOPES
    }
    return {
        "hits": returned,
        "narrowable": narrowable,
        "reformulations_counted": sum(counted),
        "budget": {"limit_chars": budget, "used_chars": used, "needed_chars": needed},
        "counts": counts,
        "omitted_pages": omitted_pages,
        "absent_terms": absent,
        "formulations": summary,
        "scopes": scopes,
        "terms": list(census.values()),
    }


def absence_steps(
    reasons: list[str],
    results: list[dict[str, Any]],
    block: list[dict[str, Any]],
    hits: list[dict[str, Any]],
    narrowable: bool = True,
) -> list[str]:
    """What to do before an absence statement, from the closed vocabulary ABSENCE_STEPS, in its order.

    `read_results_without_claims` names entries that print no claims (every
    source, a page without claim blocks): their snippet is all the report
    shows, and their text can answer in words the scan does not match.
    `narrow_formulations` is listed only while `narrowable` holds, that is
    while the question's own hits fit into the budget.
    """
    printed = [entry for entry in list(results) + list(block) if not entry.get("navigation")]
    conditions = {
        "read_withheld_claims": any(entry["claims_returned"] < entry["claims_total"] for entry in printed),
        "read_results_without_claims": any(not entry["claims_total"] for entry in printed),
        "read_reformulation_results": bool(block),
        "read_exhaustive_hits": any("text" in hit for entry in hits for hit in entry["hits"]),
        "add_reformulations": "too_few_reformulations" in reasons or "no_content_words" in reasons,
        "narrow_formulations": "budget_exhausted" in reasons and narrowable,
    }
    return [step for step in ABSENCE_STEPS if conditions[step]]


def absence_check(
    scanned: Optional[dict[str, Any]], results: list[dict[str, Any]], block: list[dict[str, Any]]
) -> dict[str, Any]:
    """The verdict every report carries: whether an absence statement is allowed, and what is missing if not.

    `scanned` is the return value of `exhaustive_scan`, or None when the call
    ran without the exhaustive scan; then only `not_exhaustive` is listed and
    every field that was not evaluated is null rather than zero.
    """
    if scanned is None:
        return {
            "format": ABSENCE_CHECK_FORMAT,
            "complete": False,
            "reasons": ["not_exhaustive"],
            "next_steps": None,
            "reformulations_counted": None,
            "budget": None,
            "counts": None,
            "omitted_pages": None,
            "absent_terms": None,
            "formulations": None,
            "scopes": None,
            "terms": None,
            "boundary": ABSENCE_BOUNDARY,
        }
    applies = {
        "not_exhaustive": False,
        "too_few_reformulations": scanned["reformulations_counted"] < MIN_EXHAUSTIVE_REFORMULATIONS,
        "no_content_words": not any(entry["content_words"] for entry in scanned["formulations"]),
        "budget_exhausted": scanned["budget"]["needed_chars"] > scanned["budget"]["limit_chars"],
    }
    reasons = [reason for reason in ABSENCE_REASONS if applies[reason]]
    return {
        "format": ABSENCE_CHECK_FORMAT,
        "complete": not reasons,
        "reasons": reasons,
        "next_steps": absence_steps(reasons, results, block, scanned["hits"], scanned.get("narrowable", True)),
        "reformulations_counted": scanned["reformulations_counted"],
        "budget": scanned["budget"],
        "counts": scanned["counts"],
        "omitted_pages": scanned["omitted_pages"],
        "absent_terms": scanned["absent_terms"],
        "formulations": scanned["formulations"],
        "scopes": scanned["scopes"],
        "terms": scanned["terms"],
        "boundary": ABSENCE_BOUNDARY,
    }


def search_record(found: dict[str, Any], release: dict[str, Any]) -> dict[str, str]:
    """The one-line record of a search that an answer quotes; `release` is the release the wrapper verified (pure)."""
    query = str(found["formulations"][0]["text"])
    if len(query) > SEARCH_RECORD_QUERY_CHARS:
        query = query[:SEARCH_RECORD_QUERY_CHARS] + "…"
    scopes = found["coverage"]["scopes"]
    exhaustive = found["exhaustive_hits"] is not None
    check = found["absence_check"]
    hits = f"{check['counts']['hits_returned']}/{check['counts']['hits_total']}" if exhaustive else "none"
    line = " ".join(
        [
            SEARCH_RECORD_FORMAT,
            f"release={release.get('version', '')}",
            f"id={release.get('release_id', '')}",
            f"manifest={str(release.get('manifest_sha256') or '')[:12]}",
            f"query={json.dumps(query, ensure_ascii=False)}",
            f"reformulations={len(found['formulations']) - 1}",
            f"ranked={'+'.join(scope for scope in SCOPES if scopes[scope]['searched'])}",
            f"exhaustive={'true' if exhaustive else 'false'}",
            f"results={len(found['results'])}/{found['coverage']['matched']}",
            f"hits={hits}",
            f"complete={'true' if check['complete'] else 'false'}",
        ]
    )
    return {"format": SEARCH_RECORD_FORMAT, "line": line}


def search_loaded(
    loaded: LoadedRelease,
    query: str,
    *,
    also: Iterable[str] = (),
    limit: int = 12,
    exhaustive: bool = False,
    exhaustive_budget: int = EXHAUSTIVE_BUDGET_CHARS,
) -> dict[str, Any]:
    """Rank `query` and its reformulations over a loaded release, fuse them, and add the absence check.

    The steps after `load`: plan the formulations, rank each kept one, build
    `results`, `reformulation_results` and `coverage` exactly as without the
    exhaustive scan, then, with `exhaustive` (which needs `load(exhaustive=True)`),
    scan every passage for all words of all formulations. `absence_check` is
    computed in both modes; `exhaustive_hits` is None without the scan.
    `exhaustive_budget` exists for tests only. Raises QueryError, RequestError
    and ValueError like `search`.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if exhaustive and not getattr(loaded, "exhaustive", False):
        raise ValueError("an exhaustive search needs a release loaded with exhaustive=True")
    also = list(also)
    kept, dropped = plan_formulations(query, also)
    if not TOKEN.findall(normalized(query)):
        raise QueryError("query must contain at least one searchable token")
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

    scanned: Optional[dict[str, Any]] = None
    if exhaustive and loaded.scan is not None:
        contents = [content_words(ranking.terms) for ranking in rankings]
        scanned = exhaustive_scan(
            loaded.scan,
            rankings,
            [entry["text"] for entry in formulations],
            loaded.concept_definitions,
            loaded.vocabulary,
            printed_claim_keys(results, block, loaded.path_prefix),
            counted_reformulations(formulations, contents),
            exhaustive_budget,
        )
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
        "absence_check": absence_check(scanned, results, block),
        "exhaustive_hits": scanned["hits"] if scanned is not None else None,
        "parser_errors": loaded.parser_errors,
    }


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
    exhaustive: bool = False,
    exhaustive_budget: int = EXHAUSTIVE_BUDGET_CHARS,
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
    `filtered_out`, `formulations`, `dropped_formulations`, `absence_check`,
    `exhaustive_hits` and `parser_errors`. A caller must not report results
    when `parser_errors` is non-empty.

    `exhaustive=True` forces `include_sources` and scans every passage of the
    ranked files except navigation for all words of all formulations, within
    `exhaustive_budget` printed characters of `exhaustive_hits` (tests only;
    the helpers never pass it). Everything else in the report stays what the
    same call without the scan but with `include_sources` returns. Raises
    QueryError for a query without a searchable token, RequestError for
    invalid reformulations and ValueError for an impossible option.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if include_history and not history_shipped:
        raise ValueError("this release ships no history layer to search")
    if exhaustive and not word_forms:
        raise ValueError("an exhaustive search needs the word-form layer")
    also = list(also)
    plan_formulations(query, also)
    if not TOKEN.findall(normalized(query)):
        raise QueryError("query must contain at least one searchable token")
    loaded = load(
        root,
        include_sources=include_sources or exhaustive,
        include_history=include_history,
        selector=selector,
        history_shipped=history_shipped,
        path_prefix=path_prefix,
        word_forms=word_forms,
        exhaustive=exhaustive,
    )
    return search_loaded(
        loaded, query, also=also, limit=limit, exhaustive=exhaustive, exhaustive_budget=exhaustive_budget
    )
