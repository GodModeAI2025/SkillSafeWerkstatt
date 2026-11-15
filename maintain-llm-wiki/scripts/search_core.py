#!/usr/bin/env python3
"""Shared, read-only search core of the query skill and of exported knowledge skills.

Two entrypoints rank a wiki release: `search_wiki.py` in the query skill and
`search_knowledge.py` in every frozen knowledge skill the maintenance skill
exports. Both are thin command-line wrappers around this module. They verify
their release before and after the search, then call `search()`. One core means
one ranking: an improvement reaches both places, and the exported copy cannot
drift away from the reader again.

This module only reads. It imports no release verifier and no writer. It takes a
release root plus options and returns plain report data. It also holds what
both wrappers share of their command line and report: the options, the request
intake, the selector, the report body and the printed form (`report_json`) in
which the evidence budget is counted. Printing, exit codes and integrity checks
stay with the wrappers.

Besides the ranked results, every report carries a `coverage` block that counts
what the search did not show: matches cut off by the limit, claims withheld per
page, query words that were dropped or found nowhere, and terms that occur only
in a layer that was not searched. The block only adds keys. It never changes
which results are returned, in which order, or with which score.

By default every query term also matches the forms of the same word that occur
in the searched files, and query words additionally match through two
disclosed heuristics, compound parts and one-edit typo corrections (see
wordforms.py). Each result names the rule that matched in `match_rules`, and
the coverage block lists the forms per term.

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
what only the scan sees: hyphen parts (`hyphen_part`), endings the word forms
do not cover (`ending`), the identifiers of claim and page metadata, and words
only its segmentation repairs. The hits come back under `exhaustive_hits`, cut
to a fixed budget of printed characters. The scan only adds keys: everything else equals the same
call with `include_sources`. Nothing is indexed or cached on disk.
"""

from __future__ import annotations

import json
import re
import unicodedata
from html import unescape as html_unescape
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, NamedTuple, Optional

import bm25
import freshness
import trust_contract
import wordforms
from frontmatter_contract import FrontmatterError, parse_document
from wiki_filters import matches_selector, validate_selector


H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
TOKEN = re.compile(r"[^\W_]+(?:[-_][^\W_]+)*", re.UNICODE)
#: Digit groups split by a thousands separator, a full stop, an apostrophe or a
#: space, when every later group has exactly three digits ("2.500", "2 500",
#: "1.234.567"). `normalized` has already turned U+00A0, U+202F and U+2009 into
#: a space. A decimal comma ("2,50") is no separator, and no group starts inside
#: a number, a date ("31.12.2025") or a word.
DIGIT_GROUPS = re.compile(r"(?<![\w.,'’])\d{1,3}(?:[. '’]\d{3})+(?!\d)")
#: The separators DIGIT_GROUPS removes.
DIGIT_SEPARATOR = re.compile(r"[. '’]")
#: Units of two or more letters that a number may carry written straight after it
#: ("2500kWh"), normalised. A single letter stays on the number: "§ 14a" and
#: "§ 312g" name paragraphs, so "800W" is not split either.
NUMBER_UNITS = (
    "kwhth", "kwhel", "kwh", "mwh", "gwh", "twh", "wh", "kwp", "mwp", "gwp", "kvar", "kva", "mva", "kw", "mw", "gw",
    "kv", "va", "cent", "ct", "euro", "eur", "km", "kg", "cm", "mm", "qm", "m2", "m3", "ml", "std", "min", "sek",
    "khz", "mhz", "ghz", "hz", "kbit", "mbit", "gbit", "kb", "mb", "gb", "tb", "bar", "mio", "mrd", "tsd",
)
#: A number with one of NUMBER_UNITS written straight after it.
NUMBER_UNIT = re.compile(r"(?<![\w-])(\d+)(" + "|".join(NUMBER_UNITS) + r")(?![^\W_])")
#: Where `number_spelling` can change anything: a separator before a group of three digits, or a unit after a digit.
NUMBER_SHAPE = re.compile(r"\d(?:[. '’]\d{3}(?!\d)|(?:" + "|".join(NUMBER_UNITS) + r")(?![^\W_]))")
#: A definition heading of schema/CONCEPTS.md or schema/CLUSTERS.md: level two with a stable lowercase ID.
CONCEPT_HEADING = re.compile(r"^##\s+([a-z0-9]+(?:-[a-z0-9]+)*)\s*$")
#: A `- Field: value` line of a definition.
CONCEPT_FIELD = re.compile(r"^-\s+([A-Za-z]+):\s*(.*)$")
#: Any Markdown ATX heading line (unstripped): at most three spaces, one to six '#', then a space or the line end.
SCHEMA_HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
#: The opening line of a fenced block in a schema file, after stripping: three or more backticks or tildes.
SCHEMA_FENCE = re.compile(r"^(`{3,}|~{3,})")
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


#: A character outside ASCII; every combining mark is one.
NON_ASCII = re.compile(r"[^\x00-\x7f]")


def normalized(value: str) -> str:
    """Casefold, decompose and drop combining marks, so "Zählerstand" matches "Zahlerstand".

    Each distinct non-ASCII character is looked up once, and every mark found
    is removed with one `str.replace`. Checking every character of a long
    source text one by one made this the most expensive step of a search.
    """
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    if decomposed.isascii():
        return decomposed
    for mark in [character for character in set(NON_ASCII.findall(decomposed)) if unicodedata.combining(character)]:
        decomposed = decomposed.replace(mark, "")
    return decomposed


#: The function-word tiers of wordforms.py, normalised like every token, so "für" is dropped as "fur".
FUNCTION_WORDS = wordforms.function_words(normalized)
#: The stopwords: left out of a query's terms unless nothing else is left, never a compound part.
FORM_STOPWORDS = FUNCTION_WORDS["stopword"]
#: Words that match only literally: the stopwords and the closed word classes.
CLOSED_CLASS = FUNCTION_WORDS["closed"]


# -- constants of the exhaustive scan and the absence check (Stufe 4) ----------

#: The most printed characters `exhaustive_hits` may take (owner decision E2),
#: counted exactly as `report_json` prints the value.
EXHAUSTIVE_BUDGET_CHARS = 100_000
#: The indent `report_json` prints a report with; the budget is counted in it.
REPORT_INDENT = 2
#: A hit prints at most this many characters of its passage, cut around the first match.
EXCERPT_CHARS = 400
#: A paragraph longer than this is cut into several passages, so a PDF
#: extraction without blank lines cannot become one passage per page. The cut
#: falls at the first sentence end once a passage has reached this size, so no
#: sentence is split; a table is cut at the row that reaches it.
PASSAGE_MAX_CHARS = 1_500
#: Where a paragraph that reaches no sentence end is cut all the same, at the
#: end of the line that reaches this size.
PASSAGE_HARD_MAX_CHARS = 3_000
#: How many pages without a returned hit absence_check names.
OMITTED_PAGES_LISTED = 20
#: Counted reformulations a complete absence check needs.
MIN_EXHAUSTIVE_REFORMULATIONS = 2
#: The longest query the search record quotes before it is cut.
SEARCH_RECORD_QUERY_CHARS = 200
#: The kinds of passage the scan cuts a file into; hits on one line sort in this order.
PASSAGE_KINDS = ("header", "heading", "claim", "paragraph", "open_question")
#: The scan's own function words, normalised (see wordforms.SCAN_FUNCTION_WORDS):
#: a passage need not hold them; the ranking and the precision gate never use them.
SCAN_FUNCTION_WORDS = frozenset(normalized(word) for word in wordforms.SCAN_FUNCTION_WORDS.split())
#: Words a passage never has to hold for a formulation to hit it: the closed class and the scan's function words.
SCAN_EXCLUDED = FUNCTION_WORDS["scan"]
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
#: The fields of absence_check that the exhaustive scan fills, in their printed order; null without the scan.
SCAN_FIELDS = (
    "reformulations_counted", "budget", "counts", "omitted_pages", "absent_terms", "formulations", "scopes", "terms",
)
SEARCH_RECORD_FORMAT = "lmwiki-search-record/1"
#: The fixed sentence every absence check carries: what a complete check shows, and what it does not.
ABSENCE_BOUNDARY = (
    "A complete check means that every passage of the scanned files that holds all content words "
    "of at least one searched formulation, in the forms listed under terms, itself or in its context, "
    "was returned under exhaustive_hits. Context is the page header, the headings and label lines above "
    "the passage, its parent list items and the first row of a split table, nothing else: a passage that "
    "needs a neighbouring paragraph, or a sentence of its paragraph beyond a cut, or that words the answer "
    "differently, with other words, an irregular form, a number in words or in another unit, or another "
    "language, is not a hit, and layers marked scanned: false were not checked. A table is read as a table "
    "only as a pipe, grid, simple or multiline table or as raw HTML; one laid out otherwise is read as "
    "paragraphs, without its header row."
)
#: Order of the layers among pages with otherwise equal hits.
SCOPE_RANK = {scope: position for position, scope in enumerate(SCOPES)}
#: A code fence: inside it no line is a heading or a marker.
FENCE = re.compile(r"^ {0,3}(```|~~~)")
#: A heading at column 0, as the ranking's HEADING counts it.
SCAN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
#: A list item starts a passage of its own.
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+")
#: A possible sentence end inside a line: ., ! or ?, closing quotes or brackets, whitespace, the next word.
SENTENCE_GAP = re.compile(r"[.!?][\"'»«“”’‘)\]]*(\s+)(?=(\S))")
#: Characters that may close a sentence after its final punctuation.
SENTENCE_CLOSERS = "\"'»«“”’‘)]"
#: Characters that may open a word before its letters.
WORD_OPENERS = "\"'»«“”„‚‘(["
#: Abbreviations whose full stop ends no sentence, normalised; single letters,
#: numbers and words with an inner full stop ("z.B.") are caught by rule.
SENTENCE_ABBREVIATIONS = frozenset((
    "abs abschn anh anl anm art aufl bd bzgl bspw bzw ca dr ebd einschl entspr erg evtl exkl ff gem ggf ggu hrsg "
    "inkl insb jh kap lfd lit lt max mind mio mrd nr pkt prof sog spez std str tel tsd usw vgl vorl zt zzgl ziff "
    "jan feb mar apr jun jul aug sep sept okt nov dez mo di mi do fr sa so hr "
    "approx cf eg etc fig ie incl excl no nos pp vol vs").split())
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
#: The scan's rule for a token that shares its base with the term where the
#: stem rule cannot see it: the base is the word itself or the word without one
#: of INFLECTION_ENDINGS. That covers plurals in -er, with or without umlaut
#: ("Häuser", "Kinder"), in -s after a vowel ("Autos"), in -se ("Ergebnisse")
#: and in -nen ("Kundinnen"), the forms of a stem shorter than four letters
#: ("Tag", "Tage", "Tagen"), and the case endings -er and -em of an adjective
#: that no adjective suffix marks ("intelligentem" and "intelligenten",
#: "fester" and "festen"). It is a heuristic: "Zahl" also meets "Zähler", so a
#: hit through it is checked in the text.
ENDING_RULE = "ending"
#: The endings the rule removes from a term and from a scanned token to find their base.
INFLECTION_ENDINGS = ("e", "en", "n", "er", "ern", "es", "em", "s", "se", "sen", "nen")
#: The shortest stem the rule may leave or extend.
ENDING_MIN_STEM = 3
#: The scan's rule for a token that is another verb form of the term where the
#: word forms cannot see it: a regular verb whose stem has four letters
#: ("senkt" and "senken", "zahlte" and "zahlen", "prüft" and "geprüft"). One
#: of VERB_ENDINGS is removed from the term, another one added, or the stem
#: is put into a participle (ge-...-t). It is a heuristic: "Markt" also meets
#: "Marken", so a hit through it is checked in the text.
VERB_ENDING_RULE = "verb_ending"
#: The verb endings the rule removes from a term and adds to its stem.
VERB_ENDINGS = ("e", "en", "n", "t", "et", "te", "ten", "ete", "eten", "st", "est")
#: The shortest stem the verb rule may leave or extend.
VERB_MIN_STEM = 4
#: The particles of separable verbs, which put ge- and zu- between particle and
#: stem ("abschalten", "abgeschaltet", "abzuschalten"). The verb rule also takes
#: a token for a form of such a verb, normalised; the longer particles come first.
SEPARABLE_PARTICLES = tuple(sorted(
    {
        normalized(word)
        for word in (
            "ab an auf aus bei dar durch ein empor entgegen fest fort frei her herab heran herauf heraus herbei "
            "herein herum herunter hervor hin hinab hinauf hinaus hinein hinzu hoch los mit nach nieder um vor "
            "voran voraus vorbei weg weiter wieder zu zurecht zurück zusammen"
        ).split()
    },
    key=lambda particle: (-len(particle), particle),
))
#: The shortest stem after a separable particle ("einbauen" and "eingebaut" share "bau").
SEPARABLE_MIN_STEM = 3
#: The scan's rule for a word of two or three letters inside a longer word,
#: which the compound rules (parts of four letters or more) never consider: as
#: the first part, when the rest, after a linking element, is one or more
#: words of the scanned files ("Gas" in "Gaskunden", "Gasversorger"), or as
#: the last part, with or without an inflection ending, after at least
#: SHORT_PART_LEAD letters ("Gas" in "Erdgas", "Tag" in "Feiertagen"). It is a
#: heuristic: "Eis" also meets "Beweis", so a hit through it is checked in the text.
SHORT_PART_RULE = "short_part"
#: The shortest and the longest word the rule applies to.
SHORT_PART_MIN = 2
SHORT_PART_MAX = 3
#: The fewest letters before a short word that is the last part of a longer word.
SHORT_PART_LEAD = 3
#: The scan's rule for a compound written with a suspension hyphen: "Grund- und
#: Leistungspreis" holds "Grundpreis", "Vertragsbeginn und -ende" holds
#: "Vertragsende". The scan joins the written part to every possible part of
#: the other word and matches a term against those joined forms only; it is a
#: heuristic, so a hit through it is checked in the text.
SUSPENDED_RULE = "suspended_compound"
#: The mark that keeps a joined form of a suspended compound apart from every
#: written token; TOKEN never matches it, and the report prints the form without it.
SUSPENDED_MARK = "~"
#: A suspension hyphen before a conjunction or a slash: "Grund- und", "Netz-, ", "Strom-/".
SUSPENDED_FRONT = re.compile(r"-(?:,?\s+(?:und|oder|bzw\.?|sowie|bis|and|or|&)\s+|\s*/\s*)(?=[^\W\d_])")
#: A suspension hyphen after a comma or a conjunction: "und -ende", ", -verlängerung".
SUSPENDED_BACK = re.compile(r"(?:,|\s(?:und|oder|bzw\.?|sowie|bis|and|or|&))\s+-(?=[^\W\d_])")
#: A conjunction a suspension hyphen may stand before or after.
SUSPENDED_CONJUNCTIONS = frozenset(("und", "oder", "bzw", "bzw.", "sowie", "bis", "and", "or", "&"))
#: A run of letters.
LETTERS = re.compile(r"[^\W\d_]+")
#: The shortest part of a word that a suspended compound may take over.
SUSPENDED_MIN_PART = 3
#: The scan's rule for a word with a footnote mark glued to it as one or two
#: plain digits, as MarkItDown writes <sup>2</sup> ("Kündigungsfrist2"). The
#: joined token is kept as well, so a name like "Fix12" still matches itself.
FOOTNOTE_RULE = "footnote_mark"
#: A token of at least four letters with one or two digits glued to its end.
FOOTNOTE_TOKEN = re.compile(r"([^\W\d_]{4,})\d{1,2}")
#: Superscript digits (¹ ² ³ ⁰ ⁴-⁹), which normalisation turns into plain digits glued to the word.
SUPERSCRIPT_DIGIT = re.compile("[¹²³⁰⁴-⁹]")
#: The border of a grid table (pandoc writes one for cells with several paragraphs): +---+---+ or +===+===+.
GRID_BORDER = re.compile(r"^ {0,3}\+(?:[-=:]+\+)+[ \t]*$")
#: The column rule of a simple or multiline table (pandoc's default for a Word table): two or more runs of dashes.
COLUMN_RULE = re.compile(r"^ {0,3}-{3,}(?: +-{3,})+[ \t]*$")
#: A full-width rule: the top and bottom border of a multiline table.
FULL_RULE = re.compile(r"^ {0,3}-{3,}[ \t]*$")
#: The most lines a multiline table's header may take.
TABLE_HEADER_MAX_LINES = 10
#: The start of a raw HTML table, as pandoc writes a table with merged cells or block content.
HTML_TABLE_START = re.compile(r"<table\b", re.IGNORECASE)
#: The end of a raw HTML table.
HTML_TABLE_END = re.compile(r"</table\s*>", re.IGNORECASE)
#: One row of an HTML table, up to its closing tag or the next row (HTML allows leaving </tr> out).
HTML_ROW = re.compile(
    r"<tr\b[^>]*>(.*?)(?=</tr\s*>|<tr\b|</t(?:head|body|foot)\s*>|</table\s*>|\Z)", re.IGNORECASE | re.DOTALL
)
#: One cell of an HTML table row, header or data.
HTML_CELL = re.compile(r"<t[hd]\b[^>]*>(.*?)(?=</t[hd]\s*>|<t[hd]\b|\Z)", re.IGNORECASE | re.DOTALL)
#: An HTML heading on a line of its own.
HTML_HEADING = re.compile(r"^<h([1-6])\b[^>]*>(.*?)</h\1\s*>$", re.IGNORECASE)
#: The summary of an HTML details block on a line of its own, optionally after the opening <details>.
HTML_SUMMARY = re.compile(r"^(?:<details\b[^>]*>\s*)?<summary\b[^>]*>(.*?)</summary\s*>$", re.IGNORECASE)
#: The end of an HTML details block: the label its summary set ends here.
HTML_DETAILS_END = re.compile(r"^</details\s*>$", re.IGNORECASE)
#: Any HTML tag or comment, removed from the text of a table, heading or summary.
HTML_TAG = re.compile(r"<[^>]*>")
#: An inline HTML tag, which a browser shows without a space: removed from the text without one.
HTML_INLINE_TAG = re.compile(
    r"</?(?:a|abbr|b|bdi|bdo|cite|code|data|del|dfn|em|i|ins|kbd|mark|q|s|samp|small|span|strong|time|u|var|wbr)\b[^>]*>",
    re.IGNORECASE,
)
#: A source ID inside a wiki link or path, as the wiki contract names source files (`src-<hash>-<slug>.md`).
SOURCE_ID_IN_TEXT = re.compile(r"\bsrc-[0-9a-f]{16}(?![0-9a-z])")
#: A wiki link without a label; its target is an address, not text.
UNLABELLED_WIKILINK = re.compile(r"\[\[([^\[\]|]*)\]\]")


def number_spelling(value: str, apart: Optional[list[str]] = None) -> str:
    """A normalised text with every number in one spelling: digit groups joined, a unit split off (pure).

    "2.500 kwh", "2 500 kwh" and "2500kwh" all become "2500 kwh", so a query
    and a page that write one number differently meet. When `apart` is a
    list, the groups of every number joined across a space are appended to
    it: a space between two numbers ("100 200") is not always a separator.
    """
    if NUMBER_SHAPE.search(value) is None:
        return value

    def join(match: "re.Match[str]") -> str:
        written = match.group(0)
        if apart is not None and " " in written:
            apart.extend(DIGIT_SEPARATOR.split(written))
        return DIGIT_SEPARATOR.sub("", written)

    return NUMBER_UNIT.sub(r"\1 \2", DIGIT_GROUPS.sub(join, value))


def superscript_tokens(repaired: str, written: Iterable[str]) -> list[str]:
    """The tokens a repaired text gives with every superscript glued to its word that `written` lacks (pure).

    "m^2^" is split into "m" and "2" as written, and gives "m2" here, so a
    search for "m²" (normalised "m2") meets it; "Kündigungsfrist^1^" keeps
    the word apart from its footnote mark and adds "kundigungsfrist1".
    """
    joined = wordforms.join_superscripts(repaired)
    if joined == repaired:
        return []
    seen = set(written)
    extra: list[str] = []
    for token in TOKEN.findall(number_spelling(normalized(joined))):
        if token not in seen:
            seen.add(token)
            extra.append(token)
    return extra


def tokens(value: str, drop_stopwords: bool = True) -> list[str]:
    """The normalised whole words of a text, as the word-form layer reads it.

    Layout and markup artefacts that split a word are repaired first
    (`wordforms.repair_text`), numbers are brought into one spelling
    (`number_spelling`), and a word with a superscript ("m^2^") also gives
    its joined token ("m2") after the split ones. With `drop_stopwords`,
    stopwords and single characters are left out.
    """
    repaired = wordforms.repair_text(value)
    values = TOKEN.findall(number_spelling(normalized(repaired)))
    if "^" in repaired:
        values.extend(superscript_tokens(repaired, values))
    if drop_stopwords:
        values = [value for value in values if value not in FORM_STOPWORDS and len(value) > 1]
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


def schema_definitions(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Definitions of CONCEPTS.md or CLUSTERS.md in file order, and the field lines that belong to none (pure).

    A level-two heading with a stable ID starts a definition and its `- Field: value`
    lines follow. Any other ATX heading ends the open definition, so a section such as
    `## Notes` can never pass its fields to the definition above it. Fenced blocks
    (three or more backticks or tildes, closed only by a run of the same character at
    least as long) and HTML comments over several lines are skipped, so a `#` line in
    an example or a commented-out draft ends nothing; neither does a line indented by
    four or more spaces. Returns (definitions, orphans): {"id", "line", "fields"} and
    {"line", "field", "heading", "closed"}; `heading` is the nearest heading above the
    orphan, `closed` the definition the old parse applied it to; lines are 1-based.
    A repeated field keeps its last value. Lint, the search and the graph all read
    both files through this one function.
    """
    definitions: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    closer: Optional[dict[str, str]] = None
    fence = ""  # the run of backticks or tildes that opened the current fenced block
    comment = False  # inside an HTML comment that spans several lines
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if fence:
            if line.startswith(fence):
                fence = ""
            continue
        if comment:
            comment = "-->" not in line
            continue
        opening = SCHEMA_FENCE.match(line)
        if opening:
            fence = opening.group(1)
            continue
        if line.startswith("<!--") and "-->" not in line[4:]:
            comment = True
            continue
        heading = CONCEPT_HEADING.match(line)
        if heading:
            current = {"id": heading.group(1), "line": number, "fields": {}}
            definitions.append(current)
            closer = None
            continue
        if SCHEMA_HEADING.match(raw_line):
            if current is not None:
                closer = {"heading": line, "closed": current["id"]}
            elif closer is not None:
                closer = {**closer, "heading": line}
            current = None
            continue
        field = CONCEPT_FIELD.match(line)
        if not field:
            continue
        if current is not None:
            current["fields"][field.group(1).casefold()] = field.group(2).strip()
        elif closer is not None:
            orphans.append({"line": number, "field": field.group(1).casefold(), **closer})
    return definitions, orphans


def controlled_concepts(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    definitions: dict[str, dict[str, Any]] = {}
    for block in schema_definitions(path.read_text(encoding="utf-8"))[0]:
        # A repeated ID replaces the earlier definition as a whole.
        definitions[block["id"]] = {"id": block["id"], **block["fields"]}
    return {
        concept_id: {
            **definition,
            "terms": [definition.get("preferred", "")] + split_pipe(definition.get("aliases", "")),
        }
        for concept_id, definition in definitions.items()
        if definition.get("status") == "active"
    }


def matching_run(term_words: list[str], query_words: list[str]) -> Optional[int]:
    """Where a concept term first matches a run of query words, each the same word by spelling or inflection (pure).

    Returns the start of the run, or None. Compound parts and typo
    corrections never trigger a concept: a confirmed concept must not be
    pulled in by a guess.
    """
    width = len(term_words)
    for start in range(len(query_words) - width + 1):
        if all(
            wordforms.same_word(query_words[start + offset], term_words[offset], CLOSED_CLASS)
            for offset in range(width)
        ):
            return start
    return None


def triggered_concepts(
    query_words: list[str], definitions: dict[str, dict[str, Any]]
) -> Iterator[tuple[str, list[str], list[str]]]:
    """Every concept the query words trigger, by id: its id, its terms and the query words of its matching run (pure).

    A concept is triggered by the first of its terms, in definition order,
    that matches a run of the query words (`matching_run`); the run is the
    first one that term matches. A blank term, such as an empty Preferred
    line, is no term: it never triggers and is not returned.
    """
    for concept_id, definition in sorted(definitions.items()):
        terms = [term for term in definition.get("terms", []) if term.strip()]
        for term in terms:
            term_words = tokens(term, drop_stopwords=False)
            if not term_words:
                continue
            start = matching_run(term_words, query_words)
            if start is not None:
                yield concept_id, terms, query_words[start:start + len(term_words)]
                break


def expand_query(query: str, definitions: dict[str, dict[str, Any]]) -> tuple[set[str], list[str], list[str]]:
    """The tokens the ranking matches, the concepts the query triggers, and the terms of those concepts."""
    query_words = tokens(query, drop_stopwords=False)
    expanded_tokens = set(tokens(query)) or set(query_words)
    matched: list[str] = []
    expanded_terms: list[str] = []
    for concept_id, terms, _run in triggered_concepts(query_words, definitions):
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
    words = tokens(query, drop_stopwords=False)
    kept = [word for word in words if word not in FORM_STOPWORDS and len(word) > 1]
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
            dropped.append({"term": word, "reason": "stopword" if word in FORM_STOPWORDS else "single-character"})
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
#: A Markdown link; after a "!" it is an image, which `link_labels` leaves as written.
MARKDOWN_LINK = re.compile(r"\[([^\[\]]*)\]\([^()\s]*\)")


def link_labels(text: str) -> str:
    """A text with every labelled wiki link and Markdown link replaced by its label (pure).

    An image ("![text](target)") is no link and stays. MARKDOWN_LINK has no
    lookbehind for the "!", which would keep the regular expression engine
    from scanning fast for the "["; a match after a "!" is skipped instead,
    and the search goes on right after its "[", where a lookbehind would.
    """
    if "[" not in text:
        return text
    text = LABELLED_WIKILINK.sub(lambda match: match.group(1), text)
    pieces: list[str] = []
    done = 0
    match = MARKDOWN_LINK.search(text)
    while match is not None:
        start = match.start()
        if start and text[start - 1] == "!":
            match = MARKDOWN_LINK.search(text, start + 1)
            continue
        pieces.append(text[done:start])
        pieces.append(match.group(1))
        done = match.end()
        match = MARKDOWN_LINK.search(text, done)
    if not pieces:
        return text
    pieces.append(text[done:])
    return "".join(pieces)


def visible_body(body: str) -> str:
    """The body without claim metadata and without the targets of labelled links.

    A link target is an address, not text. The word-form layer must not let
    "[[wiki/concepts/kuendigungsfrist|Kündigungsfrist]]" count the word twice,
    once as the folded slug and once as the label.
    """
    return link_labels(CLAIM_BLOCK.sub(lambda match: match.group("text"), body))


def overlap(query_tokens: dict[str, str], text_tokens: set[str]) -> int:
    """How many query terms a text holds.

    `query_tokens` maps every token that counts to the term it counts for, so
    each term counts once, however many of its forms the text holds.
    """
    return len({query_tokens[token] for token in text_tokens if token in query_tokens})


def relevant_claims(
    claims: list[dict[str, Any]],
    query_tokens: dict[str, str],
    concept_match: bool = False,
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for claim in claims:
        claim_tokens = set(tokens(str(claim.get("text") or ""), drop_stopwords=False))
        held = overlap(query_tokens, claim_tokens)
        if held:
            ranked.append((held, str(claim.get("id") or ""), claim))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if ranked:
        return [claim for _, _, claim in ranked[:8]]
    if concept_match:
        return [claim for claim in claims if claim.get("status") in {"active", "disputed"}][:8]
    return []


def best_snippet(body: str, query_tokens: dict[str, str]) -> str:
    candidates: list[tuple[int, str]] = []
    for line in body.splitlines():
        compact = " ".join(line.strip().split())
        if not compact or compact.startswith("#"):
            continue
        line_tokens = set(tokens(compact, drop_stopwords=False))
        held = overlap(query_tokens, line_tokens)
        if held:
            candidates.append((held, compact))
    if not candidates:
        return ""
    snippet = max(candidates, key=lambda item: (item[0], len(item[1])))[1]
    return snippet if len(snippet) <= 320 else snippet[:317].rstrip() + "..."


def description_of(data: dict[str, Any]) -> str:
    """A page's description, or a source's extraction notes."""
    return str(data.get("description") or data.get("extraction_notes") or "")


def document_fields(data: dict[str, Any], body: str) -> dict[str, list[str]]:
    """Split one document into the weighted fields BM25F scores over."""
    return {
        "title": tokens(str(data.get("title") or ""), False),
        "aliases": tokens(" ".join(alias_values(data.get("aliases"))), False),
        "headings": tokens(" ".join(HEADING.findall(body)), False),
        "description": tokens(description_of(data), False),
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
    return parsed_document(data, body, path.stem)


def parsed_document(data: dict[str, Any], body: str, stem: str) -> dict[str, Any]:
    """`read_document` for a file whose frontmatter is already parsed; `stem` titles it when it has no title or H1."""
    searchable_body = visible_body(body)
    heading = H1.search(searchable_body)
    title = str(data.get("title") or (heading.group(1).strip() if heading else stem))
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


def has_phrase(query_phrase: str, body_phrase: str) -> bool:
    """Whether a body holds all query words in a row, the phrase signal of the ranking.

    Both arguments are space-joined tokens. Only the literal query words
    count, and only on whole-token boundaries: "tarif" is no phrase in
    "festpreistarif" and none in "tarife".
    """
    if not query_phrase:
        return False
    return f" {query_phrase} " in f" {body_phrase} "


def term_members(
    ordered_terms: list[dict[str, str]],
    resolver: wordforms.Resolver,
    attested_elsewhere: Iterable[str] = (),
) -> dict[str, list[wordforms.Member]]:
    """Per query term, the tokens of the searched files that count for it, with rule and weight.

    Query words get word forms and, after them, the heuristics; concept
    expansions get word forms only. A term in `attested_elsewhere` occurs, as
    itself or as a word form, in a layer that was not searched; it is no typo,
    so it is never corrected to another word. `resolver` resolves over the
    vocabulary of the searched files; one search builds it once for all its
    queries.
    """
    attested = set(attested_elsewhere)
    return {
        item["term"]: resolver.resolve(
            item["term"], heuristics=item["origin"] == "query", typos=item["term"] not in attested
        )
        for item in ordered_terms
    }


def layer_resolver(word_sets: list[set[str]]) -> wordforms.Resolver:
    """A word-form resolver over the vocabulary of one unsearched layer."""
    vocabulary: dict[str, int] = {}
    for words in word_sets:
        for token in words:
            vocabulary[token] = vocabulary.get(token, 0) + 1
    return wordforms.Resolver(vocabulary, CLOSED_CLASS, FORM_STOPWORDS, heuristics=False)


def layer_tokens(term_names: list[str], resolver: wordforms.Resolver) -> dict[str, frozenset]:
    """Per term, the tokens of a layer that are the same word, from that layer's `layer_resolver`."""
    return {
        term: frozenset(token for token, _, _ in resolver.resolve(term, heuristics=False)) for term in term_names
    }


def layer_members(term_names: list[str], word_sets: list[set[str]]) -> dict[str, frozenset]:
    """Per term, the tokens of an unsearched layer that are the same word: literal and word forms only."""
    return layer_tokens(term_names, layer_resolver(word_sets))


#: The rules whose members count on a navigation page (WIKI.md, an index.md,
#: meta/questions.md): a term's literal token only. Navigation pages route to
#: content and are never cited; word forms must not lift an index into the
#: top, make a word look common, or count as the word in the coverage block.
NAVIGATION_RULES = frozenset({"exact"})


def members_for(members: list[wordforms.Member], navigation: bool) -> list[wordforms.Member]:
    """The members of a term that count on a page of one role: on a navigation page only NAVIGATION_RULES (pure)."""
    return [member for member in members if member[1] in NAVIGATION_RULES] if navigation else members


def scoring_groups(
    term_names: list[str],
    members_of: dict[str, list[wordforms.Member]],
    candidates: list[dict[str, Any]],
) -> tuple[list[bm25.TermGroup], list[bm25.TermGroup], dict[str, str]]:
    """The BM25 term groups for content pages and for navigation pages, and each term's group label.

    Terms that are forms of one word ("Tarif" and "Tarife", or a concept term
    the query already holds) form one group, so a page is not counted twice for
    one word. On navigation pages a group holds only its members of
    NAVIGATION_RULES. A group's document frequency counts the pages holding a
    word form; only a group with no such page counts the pages holding a
    heuristic member, so compound parts and typo corrections never make a word
    look common.
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
        on_navigation = frozenset(token for token in members if members[token][0] in NAVIGATION_RULES)
        word_forms = frozenset(token for token in members if members[token][0] in wordforms.WORD_FORM_RULES)
        heuristics = frozenset(members) - word_forms

        def holders(tokens_: frozenset) -> int:
            return sum(
                1
                for candidate in candidates
                if not candidate["words"].isdisjoint(on_navigation if candidate["navigation"] else tokens_)
            )

        frequency = holders(word_forms) or holders(heuristics)
        weights = {token: members[token][1] for token in sorted(members)}
        content_groups.append(bm25.TermGroup(entry["label"], weights, frequency))
        navigation_groups.append(
            bm25.TermGroup(entry["label"], {token: weights[token] for token in sorted(on_navigation)}, frequency)
        )
    return content_groups, navigation_groups, label_of


# -- requests and reformulations ----------------------------------------------


def _invalid_request(detail: str) -> RequestError:
    return RequestError(f"request is invalid: {detail}")


def _invalid_reformulations(detail: str) -> RequestError:
    return RequestError(f"reformulations are invalid: {detail}")


def request_from_stdin(stream: Any, *, verbatim: bool = False) -> dict[str, Any]:
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
    return read_request(raw or b"", verbatim=verbatim)


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


def read_request(raw: bytes, *, verbatim: bool = False) -> dict[str, Any]:
    """Decode and check one request object `{"query": ..., "also": [...], "filter": {...}}`.

    Returns `query` exactly as given, `also` as a list (empty when absent) and
    `filter` as the given object or None when absent. The selector itself is
    validated by the wrapper, like `--filter-json`. Raises RequestError with a
    message ready for the user. `verbatim` is for wording that must keep a
    person's punctuation (findability questions): a `?` before a letter then
    counts as re-encoded only where the JSON text carries it literally, so the
    client sends a real one as `\\u003f`.
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
        if "�" in item or (RE_ENCODED.search(item) and (not verbatim or RE_ENCODED.search(text))):
            raise _invalid_request(
                f"{field} looks re-encoded on the way (a ? before a letter, or U+FFFD); {ESCAPE_HINT}"
                + (", and write a ? that really stands before a letter as \\u003f" if verbatim else "")
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


# -- the command line both wrappers share ------------------------------------------


def add_search_arguments(
    parser: Any, *, history: bool, limit_help: str, exhaustive_help: str, manifest_help: str
) -> None:
    """Add the search options of both wrappers to an argparse parser, in the order their help lists them.

    A wrapper adds its own release option first (the query skill's
    `--target`) and words three helps itself; `history` adds
    `--include-history`, which only a release with history offers.
    """
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", help="Question or retrieval query")
    group.add_argument(
        "--request",
        metavar="-",
        help="Read the query, its reformulations and an optional selector as one JSON object from standard input; "
        "only '-' is accepted",
    )
    parser.add_argument(
        "--also",
        action="append",
        default=[],
        metavar="REFORMULATION",
        help="Reformulation of the query searched in the same call; repeatable, at most 4, each at most 200 characters",
    )
    parser.add_argument("--limit", type=int, default=12, help=limit_help)
    parser.add_argument("--include-sources", action="store_true", help="Also search faithful source Markdown")
    if history:
        parser.add_argument("--include-history", action="store_true", help="Also search historical snapshots")
    parser.add_argument("--exhaustive", action="store_true", help=exhaustive_help)
    parser.add_argument("--filter-json", default=None, help="Validated metadata selector as JSON (default: all)")
    parser.add_argument("--expect-manifest-sha256", default="", help=manifest_help)


def parse_search_arguments(parser: Any) -> Any:
    """The parsed command line of `add_search_arguments`, with the combinations argparse cannot refuse refused."""
    args = parser.parse_args()
    if args.request is not None and args.request != "-":
        parser.error("--request accepts only '-' (standard input)")
    if args.request is not None and args.also:
        parser.error("--also cannot be combined with --request; put the reformulations into the request's also list")
    return args


def query_from_arguments(args: Any, stdin: Any) -> tuple[str, list[str], Optional[dict[str, Any]]]:
    """The query, its reformulations and the request's filter from the parsed command line.

    A wrapper calls this before it touches its release, so standard input is
    always drained and invalid input never depends on the release. Raises
    RequestError.
    """
    if args.request is not None:
        request = request_from_stdin(stdin)
        query, also, request_filter = request["query"], request["also"], request["filter"]
    else:
        query, also, request_filter = args.query, list(args.also), None
    check_also(also)
    if request_filter is not None and args.filter_json is not None:
        raise _invalid_request("filter is given both in the request and as --filter-json; give it once")
    return query, also, request_filter


def selector_from(request_filter: Optional[dict[str, Any]], filter_json: Optional[str]) -> dict[str, Any]:
    """The validated selector: the request's filter, else --filter-json, else everything. Raises RequestError."""
    if request_filter is not None:
        try:
            return validate_selector(request_filter)
        except (ValueError, FrontmatterError) as exc:
            raise _invalid_request(f"filter is not a valid selector: {exc}") from exc
    try:
        return validate_selector(json.loads(filter_json if filter_json is not None else '{"kind":"all"}'))
    except (json.JSONDecodeError, ValueError, FrontmatterError) as exc:
        raise RequestError(f"filter-json is invalid: {exc}") from exc


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
    selector = selector if selector is not None else {"kind": "all"}
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
            document = read_document(path, relative, text)
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
                unsearched.setdefault(scope, []).append(unsearched_words(path, relative))

    # Which tokens count for which term is decided on every searched file,
    # before the selector, so a selector never changes what a word matches.
    # On navigation pages only NAVIGATION_RULES count, so a member of another
    # rule counts in the files of content_vocabulary only.
    vocabulary: dict[str, int] = {}
    content_vocabulary: dict[str, int] = {}
    for _scope, words, navigation in searched_words:
        for token in words:
            vocabulary[token] = vocabulary.get(token, 0) + 1
            if not navigation:
                content_vocabulary[token] = content_vocabulary.get(token, 0) + 1
    return LoadedRelease(
        include_sources=include_sources,
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
        layer_resolvers={scope: layer_resolver(word_sets) for scope, word_sets in unsearched.items()},
        vocabulary=vocabulary,
        content_vocabulary=content_vocabulary,
        resolver=wordforms.Resolver(vocabulary, CLOSED_CLASS, FORM_STOPWORDS),
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
        highlight: dict[str, str],
        coverage: dict[str, Any],
        matched_concepts: list[str],
        expanded_terms: list[str],
        terms: list[dict[str, str]],
        members: dict[str, list[wordforms.Member]],
    ) -> None:
        self.terms = terms
        self.members = members
        self.ordered = [result for result, _, _ in matches]
        self._pending = [(candidate, concept_match) for _, candidate, concept_match in matches]
        self._highlight = highlight
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
        claims = relevant_claims(page_claims, self._highlight, concept_match)
        result["snippet"] = best_snippet(candidate["body"], self._highlight)
        result["claims"] = claims
        result["claims_total"] = len(page_claims)
        result["claims_returned"] = len(claims)
        return result


def rank(loaded: LoadedRelease, query: str, *, limit: int) -> Ranking:
    """Rank one query over a loaded release and account for what its top `limit` does not show.

    Raises QueryError for a query without a searchable token.
    """
    query_token_set, matched_concepts, expanded_terms = expand_query(query, loaded.concept_definitions)
    if not query_token_set:
        raise QueryError("query must contain at least one searchable token")
    ordered_terms, dropped_terms = query_terms(query, expanded_terms)
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

    members_of = term_members(ordered_terms, loaded.resolver, attested_unsearched)

    def role_view(navigation: bool, rules: Optional[frozenset] = None) -> dict[str, frozenset]:
        # Per term, the tokens that count on a page of this role (members_for), of `rules` only when given.
        return {
            term: frozenset(
                token for token, rule, _ in members_for(members_of[term], navigation) if rules is None or rule in rules
            )
            for term in term_names
        }

    # The view of each page role (navigation or not): every token that counts,
    # and the same word, the literal token and its word forms, never a compound part or typo.
    counting = {navigation: role_view(navigation) for navigation in (False, True)}
    same_word = {navigation: role_view(navigation, wordforms.WORD_FORM_RULES) for navigation in (False, True)}
    member_tokens = counting[False]
    same_word_searched: set[str] = set()
    for scope, words, navigation in loaded.searched_words:
        account(scope, words, counting[navigation])
        same_word_searched.update(term for term in term_names if not same_word[navigation][term].isdisjoint(words))

    corpus = loaded.corpus
    matched_concept_set = set(matched_concepts)
    query_phrase = " ".join(tokens(query, False))
    content_groups, navigation_groups, label_of = scoring_groups(term_names, members_of, candidates)
    groups = {False: content_groups, True: navigation_groups}
    # What claims and snippets are matched with: every counting token mapped to the word it counts for.
    highlight: dict[str, str] = {}
    for term in term_names:
        for token in sorted(member_tokens[term]):
            highlight.setdefault(token, label_of[term])
    # A file holding no token that counts for any term scores 0, because the
    # ranking never turns a non-match into a match; it is not scored at all.
    scored_tokens = frozenset().union(*member_tokens.values())

    path_prefix = loaded.path_prefix
    matches: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
    for candidate in candidates:
        if candidate["words"].isdisjoint(scored_tokens):
            continue
        data = candidate["data"]
        relative = candidate["relative"]
        navigation = candidate["navigation"]
        document_concepts = set(as_list(data.get("concepts")))
        counted: dict[str, list[str]] = {}
        score = bm25.score(
            corpus,
            candidate["fields"],
            groups[navigation],
            phrase_match=has_phrase(query_phrase, candidate_phrase(candidate)),
            concept_overlap=len(document_concepts & matched_concept_set),
            status=str(data.get("status") or ""),
            counted=counted,
            words=candidate["words"],
        )
        if score <= 0:
            continue
        allowed = counting[navigation]
        counted_tokens = {term: set(counted.get(label_of[term], ())) & allowed[term] for term in term_names}
        result = {
            "path": path_prefix + relative,
            "title": candidate["title"],
            "id": str(data.get("id") or data.get("source_id") or ""),
            "type": str(data.get("type") or ("source" if relative.startswith("sources/") else "")),
            "status": str(data.get("status") or ""),
            "date": str(data.get("date") or data.get("updated") or ""),
            "description": description_of(data),
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
            "navigation": navigation,
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
        # The searched files in which a member counts: a member of
        # NAVIGATION_RULES everywhere, any other only outside navigation pages.
        return (vocabulary if rule in NAVIGATION_RULES else content_vocabulary).get(token, 0)

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
    return Ranking(matches, highlight, coverage, matched_concepts, expanded_terms, ordered_terms, members_of)


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
    the source page or slide (`page=3`, or `page=3-4` for a paragraph that
    runs across a page break), `status` the claim status, `tokens` its own
    normalised words and identifiers, and `section` the path of its context,
    outermost first: the headings and labels above it, then its parent list
    items, then the first row of the table it continues (for a heading
    passage: its ancestors only). `opens` is the path this passage heads for
    the passages after it (a heading, a label, a list item, the first chunk
    of a split table), with the tokens that path holds in `opens_tokens`.
    `identifiers` are the tokens this passage holds only as an identifier,
    from metadata (claim, source and page IDs) or the target of a wiki link
    without a label, and not also as written text; they match only as whole
    tokens and are never split at their hyphens.
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


def _letters_before(text: str, end: int) -> int:
    """Where the run of letters that ends at `end` starts (`end` when there is none)."""
    start = end
    while start > 0 and text[start - 1].isalpha():
        start -= 1
    return start


def _skip_space_before(text: str, end: int) -> int:
    while end > 0 and text[end - 1] in " \t\n":
        end -= 1
    return end


def _word_before(text: str, end: int) -> int:
    """Where the word that ends at `end` starts, a hyphenated one ("e-mail") included."""
    start = _letters_before(text, end)
    while start >= 2 and start < end and text[start - 1] == "-" and text[start - 2].isalpha():
        start = _letters_before(text, start - 1)
    return start


def suspended_forms(text: str) -> set[str]:
    """The joined forms of every compound a normalised text writes with a suspension hyphen, marked (pure).

    "grund- und leistungspreis" gives "grund" joined to every trailing part of
    "leistungspreis" of at least SUSPENDED_MIN_PART letters ("grundpreis",
    "grundspreis", ...), and "vertragsbeginn und -ende" gives every leading part
    of "vertragsbeginn" joined to "ende" ("vertragsende", ...). Chains count
    too ("grund-, arbeits- und leistungspreis", "strom-/gas-/wasserversorgung",
    "beginn, -dauer und -ende"). Each form carries SUSPENDED_MARK, so it never
    stands for a written token: the scan matches a term against these forms
    only under SUSPENDED_RULE, where most of them meet nothing.
    """
    found: set[str] = set()
    longest = wordforms.MAX_COMPOUND
    for match in SUSPENDED_FRONT.finditer(text):
        end = match.start()
        if not end or not text[end - 1].isalpha():
            continue
        other = LETTERS.match(text, match.end())
        if other is None or len(other.group(0)) > longest:
            continue
        word = other.group(0)
        parts = [word[cut:] for cut in range(1, len(word) - SUSPENDED_MIN_PART + 1)]
        for _ in range(8):
            start = _word_before(text, end)
            written = text[start:end]
            if not written or len(written) > longest:
                break
            found.update(SUSPENDED_MARK + written + part for part in parts)
            # An earlier part of a chain: "grund-, arbeits- und ..." or "strom-/gas-/...".
            before = _skip_space_before(text, start)
            if before >= 2 and text[before - 1] in ",/" and text[before - 2] == "-":
                end = before - 2
                continue
            break
    for match in SUSPENDED_BACK.finditer(text):
        other = LETTERS.match(text, match.end())
        if other is None or len(other.group(0)) > longest:
            continue
        # Walk back over earlier suspended parts of a chain ("beginn, -dauer und -ende") to the written word.
        end = _skip_space_before(text, match.start())
        word = ""
        for _ in range(8):
            start = _word_before(text, end)
            if start == end:
                break
            if start and text[start - 1] == "-" and (start < 2 or not text[start - 2].isalpha()):
                end = _skip_space_before(text, start - 1)
                if end and text[end - 1] in ",&":
                    end = _skip_space_before(text, end - 1)
                    continue
                stop = end - 1 if end and text[end - 1] == "." else end
                conjunction = _letters_before(text, stop)
                if text[conjunction:stop] not in SUSPENDED_CONJUNCTIONS:
                    break
                end = _skip_space_before(text, conjunction)
                continue
            word = text[start:end]
            break
        if not word or len(word) > longest:
            continue
        found.update(
            SUSPENDED_MARK + word[:cut] + other.group(0) for cut in range(SUSPENDED_MIN_PART, len(word))
        )
    return found


def scan_words(repaired: str) -> frozenset:
    """The tokens the scan indexes for an already repaired text (pure).

    They are the tokens of the word-form layer (`tokens(..., False, True)`),
    plus the groups of every number joined across a space, which may have
    been two numbers ("100 200") rather than one; plus, where a superscript
    digit is glued to a word ("Kündigungsfrist²", which normalisation turns
    into "kundigungsfrist2"), the word and the digit apart, while the joined
    token stays; plus, where a superscript in pandoc's markup follows a word
    ("m^2^", "Kündigungsfrist^1^"), the joined token (`superscript_tokens`),
    while the word and the mark stay apart; plus the marked joined forms of
    compounds written with a suspension hyphen (`suspended_forms`).
    """
    apart: list[str] = []
    text = normalized(repaired)
    found = frozenset(TOKEN.findall(number_spelling(text, apart)))
    if apart:
        found = found.union(apart)
    if "^" in repaired:
        joined = superscript_tokens(repaired, found)
        if joined:
            found = found.union(joined)
    if SUPERSCRIPT_DIGIT.search(repaired) is not None:
        spaced = SUPERSCRIPT_DIGIT.sub(lambda match: " " + match.group(0), repaired)
        found = found.union(TOKEN.findall(number_spelling(normalized(spaced))))
    if "-" in text:
        joined = suspended_forms(text)
        if joined:
            found = found.union(joined)
    return found


def html_text(fragment: str) -> str:
    """The text of an HTML fragment: tags and comments removed, entities decoded, whitespace collapsed (pure).

    A subscript is joined to its word and a superscript written as pandoc's
    ^...^ (`wordforms.repair_markup`), and an inline tag ("<strong>",
    "<em>", "<span>") is removed without a space, so "CO<sub>2</sub>" and
    "<b>Kündigungs</b>frist" stay one word as a browser shows them; every
    other tag stands for a space.
    """
    if "<" in fragment:
        fragment = HTML_INLINE_TAG.sub("", wordforms.repair_markup(fragment))
        fragment = HTML_TAG.sub(" ", fragment)
    if "&" in fragment:
        fragment = html_unescape(fragment)
    return " ".join(fragment.split())


def sentence_end(word: str, following: str) -> bool:
    """Whether `word`, followed by the word `following` ("" at a line end), ends a sentence (pure).

    It must end in ., ! or ?, before any closing quotes or brackets, and the
    next word must not start in lowercase. A full stop after a number ("am 1.
    Januar"), a single letter ("S. 3"), a word with an inner full stop
    ("z.B.") or an abbreviation ("Abs. 2") ends nothing.
    """
    core = word.rstrip(SENTENCE_CLOSERS)
    if not core or core[-1] not in ".!?" or following[:1].islower():
        return False
    if core[-1] != ".":
        return True
    bare = core.rstrip(".").lstrip(WORD_OPENERS)
    if len(bare) < 2 or "." in bare or bare[-1].isdigit():
        return False
    return normalized(bare) not in SENTENCE_ABBREVIATIONS


def sentence_pieces(line: str) -> list[tuple[str, bool]]:
    """A line cut after every sentence end, each piece with whether it ends a sentence (pure).

    The last piece ends a sentence when the line ends with one; whitespace
    between the pieces is dropped.
    """
    pieces: list[tuple[str, bool]] = []
    start = 0
    if "." in line or "!" in line or "?" in line:
        for match in SENTENCE_GAP.finditer(line):
            begin = max(line.rfind(" ", start, match.start()), line.rfind("\t", start, match.start())) + 1
            if sentence_end(line[max(begin, start):match.start(1)], match.group(2)):
                pieces.append((line[start:match.start(1)], True))
                start = match.end(1)
    rest = line[start:]
    last = rest[max(rest.rfind(" "), rest.rfind("\t")) + 1:]
    pieces.append((rest, sentence_end(last, "")))
    return pieces


def locator_span(first: str, last: str) -> str:
    """The locator of a passage that starts under `first` and ends under `last`: one of them, or a range like `page=3-4` (pure)."""
    if first == last or not first:
        return last
    if not last:
        return first
    kind, _, _ = first.partition("=")
    last_kind, _, value = last.partition("=")
    return f"{first}-{value}" if kind == last_kind else f"{first}-{last}"


def readable(raw: str) -> str:
    """A fragment as the scan reads and shows it: links replaced by their labels, then split words joined (pure)."""
    return wordforms.repair_text(link_labels(raw))


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


def _blank_or_marker(line: str) -> bool:
    """True for a blank line or a line that holds only page or slide markers."""
    stripped = line.strip()
    return not stripped or (stripped.startswith("<!--") and not PAGE_MARKER.sub("", stripped).strip())


def _column_cells(line: str, bounds: list[Optional[int]]) -> list[str]:
    """The cells of one line of a simple or multiline table, cut where the column rule's runs start."""
    return [line[bounds[column]:bounds[column + 1]].strip() for column in range(len(bounds) - 1)]


def _grid_cells(line: str) -> list[str]:
    """The cells of one content line of a grid table, between its pipes."""
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    return [cell.strip() for cell in inner.split("|")]


def _table_rows(
    lines: list[str], first: int, last: int, groups: list[list[int]], cells_of: Any
) -> tuple[list[tuple[int, str, list[str]]], list[str]]:
    """Each group of lines as one pipe-style row, with the page markers met up to it, and the markers after the last row.

    The fragments of a cell are joined with a line break, so a hyphen at the
    end of a fragment is repaired as in a paragraph.
    """
    markers_at: dict[int, list[str]] = {}
    for number in range(first, last + 1):
        if "<!--" in lines[number]:
            found = [f"{match.group(1).lower()}={match.group(2)}" for match in PAGE_MARKER.finditer(lines[number])]
            if found:
                markers_at[number] = found
    rows: list[tuple[int, str, list[str]]] = []
    pending: list[str] = []
    done = first - 1
    for group in groups:
        for number in range(done + 1, group[-1] + 1):
            pending.extend(markers_at.get(number, ()))
        done = group[-1]
        columns: list[list[str]] = []
        for number in group:
            line = PAGE_MARKER.sub(" ", lines[number]) if number in markers_at else lines[number]
            for column, cell in enumerate(cells_of(line.rstrip())):
                if column == len(columns):
                    columns.append([])
                if cell:
                    columns[column].append(cell)
        if any(columns):
            rows.append((group[0], "| " + " | ".join("\n".join(column) for column in columns) + " |", pending))
            pending = []
    for number in range(done + 1, last + 1):
        pending.extend(markers_at.get(number, ()))
    return rows, pending


def _rule_groups(lines: list[str], start: int, single: bool) -> Optional[tuple[list[list[int]], int]]:
    """The rows from `start` up to a closing rule, and the rule's line, or None when no rule closes them.

    Rows are separated by blank lines, unless `single` makes every line a row.
    Two blank lines in a row, a heading at column 0 or a fence end the search
    without a table.
    """
    groups: list[list[int]] = []
    current: list[int] = []
    blank = False
    for number in range(start, len(lines)):
        line = lines[number].rstrip()
        if not line.strip():
            if blank:
                return None
            blank = True
            if current:
                groups.append(current)
                current = []
            continue
        blank = False
        if COLUMN_RULE.match(line) or FULL_RULE.match(line):
            if current:
                groups.append(current)
            return (groups, number) if groups else None
        if line.startswith("#") or FENCE.match(line):
            return None
        if single:
            groups.append([number])
        else:
            current.append(number)
    return None


def pandoc_table(lines: list[str], index: int) -> Optional[tuple[int, int, list[tuple[int, str, list[str]]], list[str]]]:
    """A table in one of pandoc's Markdown forms that starts at `lines[index]`, or None (pure).

    The forms are the grid table (rows between +---+ borders, the header above
    a +===+ border), the multiline table (pandoc's default for a Word table: a
    full-width rule, the header, a column rule of dashes, rows separated by
    blank lines, a closing rule), the simple table (a header line, a column
    rule, one row per line, up to a blank line) and both without a header.
    Returns the number of lines the table takes, the indent of its first line,
    its rows as pipe-style text with the index of each row's first line and
    the page markers met up to it (the header row first), and the markers
    after its last row. Cells are cut at the column rule's runs or at the
    grid's pipes, so a cell over several lines stays one cell.
    """
    line = lines[index].rstrip()
    left = line.lstrip()
    depth = len(line) - len(left)
    count = len(lines)
    previous = lines[index - 1] if index else ""
    if left[:1] == "+":
        if GRID_BORDER.match(line) is None:
            return None
        groups: list[list[int]] = []
        current: list[int] = []
        header_end = 0
        number = index + 1
        while number < count:
            row = lines[number].rstrip()
            if GRID_BORDER.match(row):
                if current:
                    groups.append(current)
                    current = []
                if "=" in row and not header_end:
                    header_end = len(groups)
            elif row.lstrip().startswith("|"):
                current.append(number)
            else:
                break
            number += 1
        if current:
            groups.append(current)
        if not groups:
            return None
        if header_end > 1:
            groups = [[number for group in groups[:header_end] for number in group]] + groups[header_end:]
        rows, trailing = _table_rows(lines, index, number - 1, groups, _grid_cells)
        return (number - index, depth, rows, trailing) if rows else None
    if left[:1] == "-":
        if FULL_RULE.match(line):
            # A multiline table with a header: the header lines run up to the column rule.
            for rule in range(index + 1, min(count, index + 2 + TABLE_HEADER_MAX_LINES)):
                ruled = lines[rule].rstrip()
                if not ruled.strip() or FULL_RULE.match(ruled):
                    return None
                if COLUMN_RULE.match(ruled):
                    break
            else:
                return None
            if rule == index + 1:
                return None
            found = _rule_groups(lines, rule + 1, False)
            if found is None:
                return None
            body, close = found
            groups = [list(range(index + 1, rule))] + body
        elif COLUMN_RULE.match(line) and _blank_or_marker(previous):
            # A table without a header: between two column rules, rows separated by blank lines or one per line.
            found = _rule_groups(lines, index + 1, False)
            if found is None:
                return None
            body, close = found
            if all(len(group) == 1 for group in body) or not any(
                not lines[number].strip() for number in range(index + 1, close)
            ):
                body = [[number] for group in body for number in group]
            rule = index
            groups = body
        else:
            return None
        starts = [match.start() for match in re.finditer(r"-+", lines[rule].rstrip())]
        bounds: list[Optional[int]] = [0, *starts[1:], None]
        rows, trailing = _table_rows(lines, index, close, groups, lambda text: _column_cells(text, bounds))
        return (close - index + 1, depth, rows, trailing) if rows else None
    if (
        index + 1 < count and left and left[0] not in "#|<>" and LIST_ITEM.match(line) is None
        and COLUMN_RULE.match(lines[index + 1].rstrip())
        and (_blank_or_marker(previous) or FULL_RULE.match(previous.rstrip()))
    ):
        # A simple table: one header line, the column rule, one row per line up to a blank line or a closing rule.
        groups = [[index]]
        close = index + 1
        for number in range(index + 2, count):
            row = lines[number].rstrip()
            if not row.strip():
                break
            close = number
            if COLUMN_RULE.match(row) or FULL_RULE.match(row):
                break
            groups.append([number])
        if len(groups) == 1:
            return None
        starts = [match.start() for match in re.finditer(r"-+", lines[index + 1].rstrip())]
        bounds = [0, *starts[1:], None]
        rows, trailing = _table_rows(lines, index, close, groups, lambda text: _column_cells(text, bounds))
        return (close - index + 1, depth, rows, trailing) if rows else None
    return None


def scan_passages(relative: str, text: str, document: dict[str, Any]) -> list[Passage]:
    """Cut one file into the passages the exhaustive scan matches (pure).

    `document` is what `read_document` returned for `text`, so the frontmatter
    is parsed once. Lines are 1-based file lines, split on "\\n" only: a form
    feed from a PDF extraction must not shift them. Trailing whitespace is
    stripped from every line, so a CRLF file yields the same passages.

    Only a blank line or a structural line (heading, list item, table, fence,
    claim block, HTML table, heading or summary) ends a paragraph. A page or
    slide marker does not: it only sets the locator of what follows, so a
    sentence broken across a page stays one passage, with the locator range
    of both pages, and a hyphen at the line end before the marker is joined.
    A paragraph longer than PASSAGE_MAX_CHARS is cut at a sentence end.

    Context reaches a passage from the headings above it (Markdown, setext and
    HTML headings, and labels: a one-line paragraph of at most LABEL_MAX_CHARS
    characters that is only bold text or ends in a colon, or the summary of an
    HTML details block, which lasts until the next heading or label), from its
    parent list items, and, in a table cut at the size cap, from the table's
    first row. A raw HTML table is read as a table: each row becomes a row of
    cells, and its first row is the one a cut carries. So are pandoc's grid,
    multiline and simple tables (`pandoc_table`): a row over several lines or
    separated by blank lines stays one row of cells, and the header row is
    the first row a cut carries. The page header and
    every claim also carry the identifiers of their metadata as whole tokens:
    page and source IDs, and the claim, source, replaced and contradicted
    claim IDs. The targets of unlabelled wiki links are identifiers too
    (`link_addresses`).
    """
    data = document["data"]
    body = document["raw_body"]
    body_line = text.count("\n", 0, len(text) - len(body)) + 1
    title = str(document["title"])
    aliases = alias_values(data.get("aliases"))
    description = description_of(data)
    header_text = title + (" — " + ", ".join(aliases) if aliases else "") + (" — " + description if description else "")
    listed_sources = " ".join(as_list(data.get("sources")))
    header_ids = identifier_tokens(data.get("id"), data.get("source_id"))
    if "src-" in listed_sources:
        header_ids = header_ids.union(SOURCE_ID_IN_TEXT.findall(normalized(listed_sources)))
    repair = wordforms.repair_text
    header_words = scan_words(repair(title)).union(scan_words(repair(", ".join(aliases))), scan_words(repair(description)))
    passages: list[Passage] = [
        Passage("header", 1, "", "", header_text, header_words | header_ids, (), identifiers=header_ids - header_words)
    ]
    # The title tokens read_document gave the title field, for an H1 that repeats the title.
    title_tokens = document["fields"]["title"]
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
    # The locators in effect at the first and at the last text of the open passage.
    first_locator = ""
    last_locator = ""
    # The lines of a raw HTML table that is still open, as (number, line).
    html_block: Optional[list[tuple[int, str]]] = None

    def refresh() -> None:
        nonlocal section
        section = tuple(labels) + tuple(items) if items else tuple(labels)

    def pop_headings(level: int) -> None:
        while levels and levels[-1] >= level:
            levels.pop()
            labels.pop()

    def written(addresses: frozenset, text_with_links: str) -> frozenset:
        # The link targets this passage does not also hold as written text: its identifiers.
        if not addresses:
            return frozenset()
        return addresses - scan_words(UNLABELLED_WIKILINK.sub(" ", text_with_links))

    def heading(level: int, label: str, number: int) -> None:
        indents.clear()
        items.clear()
        pop_headings(level)
        refresh()
        words = tokens(label, False)
        # An H1 that repeats the title is carried by the header passage.
        if words and not (level == 1 and words == title_tokens):
            found = scan_words(label)
            addresses = link_addresses(label)
            identifiers = written(addresses, label)
            found = found | addresses
            passages.append(Passage("heading", number, locator, "", label, found, section, section + (label,), found, identifiers))
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
        raw = "\n".join(lines)
        # The repaired text is the display text too.
        repaired = readable(raw)
        found = scan_words(repaired)
        addresses = link_addresses(raw)
        identifiers = written(addresses, repaired)
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
                repaired_row = readable(table_row)
                row_tokens = scan_words(repaired_row)
                if row_tokens:
                    opens, opens_tokens = where + (" ".join(repaired_row.split()),), row_tokens
            span = locator_span(first_locator, last_locator)
            passages.append(Passage(plain_kind, first_line, span, "", shown, found, where, opens, opens_tokens, identifiers))
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

    def begin(number: int, is_table: bool, size: int) -> None:
        nonlocal first_line, table, length, first_locator
        first_line = number
        table = is_table
        length = size
        first_locator = locator

    def append(line: str, number: int, is_table: bool = False) -> None:
        nonlocal length, table_row, last_locator
        if is_table:
            # A table row is one unit; the table is cut at the row that reaches the cap.
            if not lines:
                begin(number, True, len(line))
                if not carried:
                    table_row = line
            else:
                length += 1 + len(line)
            lines.append(line)
            last_locator = locator
            if length >= PASSAGE_MAX_CHARS:
                finish(cut=True)
            return
        if (length + 1 + len(line) if lines else len(line)) < PASSAGE_MAX_CHARS:
            # No cut can fall in this line: it joins the passage whole.
            if lines:
                length += 1 + len(line)
            else:
                begin(number, False, len(line))
            lines.append(line)
            last_locator = locator
            return
        for piece_number, (piece, ends) in enumerate(sentence_pieces(line)):
            if not lines:
                begin(number, False, len(piece))
                lines.append(piece)
            else:
                length += 1 + len(piece)
                if piece_number:
                    lines[-1] = f"{lines[-1]} {piece}"
                else:
                    lines.append(piece)
            last_locator = locator
            # Cut at the first sentence end once the cap is reached; the rest of the line starts the next passage.
            if length >= PASSAGE_MAX_CHARS and (ends or length >= PASSAGE_HARD_MAX_CHARS):
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

    def table_line(row: str, number: int, depth: int) -> None:
        # Consecutive rows form one passage.
        if lines and not table:
            finish()
        if not lines:
            enter(depth)
        append(row, number, True)

    def close_html() -> None:
        # Read a raw HTML table as a table: each <tr> a row of cells, the first row carried across a cut.
        nonlocal html_block, locator
        block, html_block = html_block, None
        raw = "\n".join(line for _, line in block)
        start = block[0][0]
        depth = len(block[0][1]) - len(block[0][1].lstrip())
        markers = [(match.start(), f"{match.group(1).lower()}={match.group(2)}") for match in PAGE_MARKER.finditer(raw)]
        # Text outside the rows (a caption, an unclosed fragment) is kept as a paragraph.
        rest = html_text(HTML_ROW.sub(" ", raw))
        if rest:
            enter(depth)
            append(rest, start)
            finish()
        for match in HTML_ROW.finditer(raw):
            while markers and markers[0][0] < match.end():
                locator = markers.pop(0)[1]
            cells = [html_text(cell) for cell in HTML_CELL.findall(match.group(1))]
            row = "| " + " | ".join(cells) + " |" if cells else html_text(match.group(1))
            if row.strip("| "):
                table_line(row, start + raw.count("\n", 0, match.start()), depth)
        finish()
        for _, value in markers:
            locator = value

    def handle(line: str, number: int) -> None:
        nonlocal fenced, locator, lines, length, listed, html_block
        line = line.rstrip()
        left = line.lstrip()
        if html_block is not None:
            # Inside a raw HTML table: everything up to </table> belongs to it; a blank line ends an unclosed one.
            if not left:
                close_html()
                finish()
                return
            html_block.append((number, line))
            if HTML_TABLE_END.search(line):
                close_html()
            return
        # Each pattern runs only where its first characters can match: the scan reads every line.
        if left[:1] in ("`", "~") and FENCE.match(line):
            finish()
            fenced = not fenced
            return
        if not fenced:
            marker = PAGE_MARKER.search(line) if "<!--" in line else None
            if marker:
                # A marker moves the locator for what follows; it never ends the passage it stands in.
                before, after = line[: marker.start()], line[marker.end():]
                if before.strip():
                    handle(before, number)
                locator = f"{marker.group(1).lower()}={marker.group(2)}"
                if after.strip():
                    handle(after, number)
                return
            atx = SCAN_HEADING.match(line) if line[:1] == "#" else None
            if atx:
                finish()
                heading(len(atx.group(1)), " ".join(readable(atx.group(2)).split()), number)
                return
            if (
                left[:1] in ("=", "-") and len(lines) == 1 and not table and not listed
                and SETEXT_UNDERLINE.match(line)
            ):
                label = " ".join(readable(lines[0]).split())
                if label and len(label) <= LABEL_MAX_CHARS:
                    number = first_line
                    lines = []
                    length = 0
                    heading(1 if left[0] == "=" else 2, label, number)
                    return
            if left[:1] == "<":
                if HTML_TABLE_START.match(left):
                    finish()
                    html_block = [(number, line)]
                    if HTML_TABLE_END.search(line):
                        close_html()
                    return
                tag = HTML_HEADING.match(left)
                summary = None if tag else HTML_SUMMARY.match(left)
                if tag or summary:
                    label = html_text(readable(tag.group(2) if tag else summary.group(1)))
                    if label:
                        finish()
                        heading(int(tag.group(1)) if tag else LABEL_LEVEL, label, number)
                        return
                if HTML_DETAILS_END.match(left):
                    finish()
                    pop_headings(LABEL_LEVEL)
                    refresh()
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
        if first == "|":  # a table row
            table_line(line, number, len(line) - len(left))
            return
        if table:
            finish()
        if not lines:
            enter(len(line) - len(left))
        append(line, number)

    def pandoc_rows(table: tuple[int, int, list[tuple[int, str, list[str]]], list[str]], start: int) -> None:
        # A pandoc grid, multiline or simple table is read as a table: each row one row of cells, the header carried across a cut.
        nonlocal locator
        _, depth, rows, trailing = table
        finish()
        for offset, row, markers in rows:
            if markers:
                locator = markers[-1]
            table_line(row, start + offset, depth)
        finish()
        if trailing:
            locator = trailing[-1]

    position = 0
    line_at = body_line

    def walk(segment: str, start: int) -> None:
        segment_lines = segment.split("\n")
        count = len(segment_lines)
        index = 0
        while index < count:
            line = segment_lines[index]
            if (
                not fenced and html_block is None
                and (line.lstrip()[:1] in ("-", "+") or (index + 1 < count and segment_lines[index + 1].lstrip()[:1] == "-"))
            ):
                table = pandoc_table(segment_lines, index)
                if table is not None:
                    pandoc_rows(table, start)
                    index += table[0]
                    continue
            handle(line, start + index)
            index += 1

    def close() -> None:
        if html_block is not None:
            close_html()
        finish()

    for match in CLAIM_BLOCK.finditer(body):
        walk(body[position:match.start()], line_at)
        close()
        # A claim block stands at column 0: it ends every list.
        if items:
            indents.clear()
            items.clear()
            refresh()
        claim_line = line_at + body.count("\n", position, match.start())
        claim = claim_fields(match)
        claim_ids = claim_identifiers(claim)
        addresses = link_addresses(match.group("text"))
        # Tokens come from the text with its line breaks, so a hyphen at a line end is repaired as the ranking does.
        claim_text = readable(match.group("text"))
        words = scan_words(claim_text)
        # Identifiers are the IDs and link targets the claim does not also hold as written text.
        plain = scan_words(UNLABELLED_WIKILINK.sub(" ", claim_text)) if addresses else words
        identifiers = (claim_ids | addresses) - plain
        found = words | claim_ids | addresses
        if found:
            passages.append(
                Passage("claim", claim_line, claim["id"], claim["status"], claim["text"], found, section, identifiers=identifiers)
            )
        line_at = claim_line + body.count("\n", match.start(), match.end())
        position = match.end()
    walk(body[position:], line_at)
    close()
    return passages


def concept_runs(query: str, definitions: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """For each concept the query triggers, the query words of its matching run, as `expand_query` finds them (pure)."""
    return {
        concept_id: run for concept_id, _terms, run in triggered_concepts(tokens(query, drop_stopwords=False), definitions)
    }


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
                option = tuple(token for token in tokens(term, False) if token not in SCAN_EXCLUDED)
                if option and option not in listed:
                    listed.add(option)
                    options.append((concept_id, option))
        found[word] = options
    return found


def hyphen_groups(units: list[str]) -> list[str]:
    """The written parts of a hyphenated token with every one-character part kept on its neighbour (pure).

    A part of one character joins the part after it, or the part before it
    when it is the last: "e-mail-adresse" gives "e-mail" and "adresse",
    "typ-2-stecker" gives "typ" and "2-stecker", "vitamin-c" gives
    "vitamin-c". So "E-Mail" stays one part and "E" is never one.
    """
    groups: list[str] = []
    pending = ""
    for unit in units:
        if pending:
            unit = pending + "-" + unit
            pending = ""
        if len(unit) < 2:
            pending = unit
            continue
        groups.append(unit)
    if pending:
        if groups:
            groups[-1] = groups[-1] + "-" + pending
        else:
            groups.append(pending)
    return groups


def hyphen_units(word: str) -> tuple:
    """The parts of a hyphenated content word that a passage may write apart, or () (pure).

    A one-character part stays on its neighbour (`hyphen_groups`), so
    "E-Mail-Adresse" gives "e-mail" and "adresse", and "E-Mobilität" gives
    no parts at all: it never stands for "Mobilität" alone. Closed-class and
    function words among the parts are dropped; at least two distinct parts
    must remain.
    """
    if "-" not in word and "_" not in word:
        return ()
    units = tuple(dict.fromkeys(unit for unit in hyphen_groups(wordforms.units_of(word)) if unit not in SCAN_EXCLUDED))
    if len(units) < 2:
        return ()
    return units


def shown_token(token: str) -> str:
    """A member token as a report prints it: a joined form of a suspended compound without its mark."""
    return token[1:] if token[:1] == SUSPENDED_MARK else token


def ending_bases(spelling: str) -> set[str]:
    """The bases of a folded spelling: itself and itself without one of INFLECTION_ENDINGS (pure).

    A base keeps at least ENDING_MIN_STEM letters, and a spelling shorter than
    that has none. Two words share a base when the `ending` rule matches them.
    """
    if not spelling.isalpha() or len(spelling) < ENDING_MIN_STEM:
        return set()
    bases = {spelling}
    bases.update(
        spelling[: -len(ending)]
        for ending in INFLECTION_ENDINGS
        if spelling.endswith(ending) and len(spelling) - len(ending) >= ENDING_MIN_STEM
    )
    return bases


def ending_variants(spelling: str) -> set[str]:
    """The spellings that share a base with a folded spelling, as the `ending` rule compares (pure).

    Every base of `ending_bases` with nothing or one of INFLECTION_ENDINGS
    after it: "intelligenten" gives "intelligentem" and "intelligenter"
    (through "intelligent"), "tag" gives "tage", "auto" gives "autos". The
    spelling itself is left out.
    """
    variants = {base + ending for base in ending_bases(spelling) for ending in ("", *INFLECTION_ENDINGS)}
    variants.discard(spelling)
    return variants


def verb_stems(spelling: str) -> set[str]:
    """The verb stems a folded spelling may hold: without one of VERB_ENDINGS, or inside a participle ge-...-t (pure)."""
    if not spelling.isalpha():
        return set()
    stems = {
        spelling[: -len(ending)]
        for ending in VERB_ENDINGS
        if spelling.endswith(ending) and len(spelling) - len(ending) >= VERB_MIN_STEM
    }
    if spelling.startswith("ge") and spelling.endswith("t"):
        inner = spelling[2:-2] if spelling.endswith("et") else spelling[2:-1]
        if len(inner) >= VERB_MIN_STEM:
            stems.add(inner)
    return stems


def separable_stems(spelling: str) -> set[tuple[str, str]]:
    """The (particle, stem) pairs of a separable verb that a folded spelling may be a form of (pure).

    A spelling that starts with one of SEPARABLE_PARTICLES is read three ways:
    particle, stem and one of VERB_ENDINGS ("abschalten", "abschaltete");
    particle, ge-, stem and -t, -et or -en, the participle ("abgeschaltet",
    "angepasst", "angegeben"); and particle, zu-, stem and -n or -en, the
    infinitive with zu ("abzuschalten"). Each stem keeps at least
    SEPARABLE_MIN_STEM letters.
    """
    pairs: set[tuple[str, str]] = set()
    if not spelling.isalpha():
        return pairs
    for particle in SEPARABLE_PARTICLES:
        if not spelling.startswith(particle):
            continue
        rest = spelling[len(particle):]
        if len(rest) < SEPARABLE_MIN_STEM:
            continue
        stems = {
            rest[: -len(ending)]
            for ending in VERB_ENDINGS
            if rest.endswith(ending) and len(rest) - len(ending) >= SEPARABLE_MIN_STEM
        }
        for infix, endings in (("ge", ("t", "et", "en")), ("zu", ("n", "en"))):
            if rest.startswith(infix):
                stems.update(
                    rest[2: -len(ending)]
                    for ending in endings
                    if rest.endswith(ending) and len(rest) - 2 - len(ending) >= SEPARABLE_MIN_STEM
                )
        pairs.update((particle, stem) for stem in stems)
    return pairs


def verb_variants(spelling: str) -> set[str]:
    """The other verb forms of a folded spelling, as the `verb_ending` rule compares (pure).

    Every stem of `verb_stems` with each of VERB_ENDINGS and as a participle
    ge-...-t and ge-...-et: "senkt" gives "senken", "senkte" and "gesenkt".
    Every pair of `separable_stems` with each of VERB_ENDINGS after the stem,
    as a participle with ge- after the particle (-t, -et, -en), and as an
    infinitive with zu- after the particle: "abschalten" gives "abgeschaltet"
    and "abzuschalten", "abgeschaltet" gives "abschalten".
    """
    variants: set[str] = set()
    for stem in verb_stems(spelling):
        variants.update(stem + ending for ending in VERB_ENDINGS)
        variants.update(("ge" + stem + "t", "ge" + stem + "et"))
    for particle, stem in separable_stems(spelling):
        variants.update(particle + stem + ending for ending in VERB_ENDINGS)
        variants.update(particle + "ge" + stem + ending for ending in ("t", "et", "en"))
        variants.update((particle + "zu" + stem + "en", particle + "zu" + stem + "n"))
    variants.discard(spelling)
    return variants


def scan_members(ranking: Ranking, scan: "ScanIndex", vocabulary: dict[str, int]) -> dict[Any, list[wordforms.Member]]:
    """The members the scan matches per term: the ranking's, plus what only the scan can see.

    Three additions, all for terms outside the closed class and function words:

    - a scanned token that the ranking's vocabulary lacks and that is the
      term itself or has its spelling or stem key gets the word-form rule
      `exact`, `fold` or `stem`; that happens for an identifier from claim
      metadata or the frontmatter, which the ranking never reads, and for a
      word only the scan's segmentation repairs (a hyphen at a line end
      before a page marker, a number in a table cell);
    - every joined token written as text that holds the term as a
      hyphen-separated part of the same stem key ("sms" in "sms-warndienst")
      is added under the heuristic rule `hyphen_part`, which the ranking does
      not know;
    - every scanned token that is the term with an inflection ending added
      or removed where the stem rule cannot see it ("krankenhauser" for
      "krankenhaus", "tage" for "tag") is added under the heuristic rule
      `ending` (see `ScanIndex.ending_forms`);
    - every scanned token that is another verb form of a four-letter stem
      ("senken" for "senkt", "zahlt" for "zahlen") is added under the
      heuristic rule `verb_ending` (see `ScanIndex.verb_forms`);
    - every scanned token that glues a one- or two-digit footnote mark to the
      term's stem key ("kundigungsfrist2") is added under `footnote_mark`, and
      every marked joined form of a suspended compound with the term's stem
      key ("grund- und leistungspreis" for "grundpreis") under
      `suspended_compound`;
    - for a term of two or three letters, every scanned token that holds it
      as its first or last part ("gaskunden", "erdgas" for "gas") is added
      under `short_part` (see `ScanIndex.short_parts`).
    """
    parts = scan.hyphen_parts()
    footnotes = scan.footnote_marks()
    suspended = scan.suspended()
    members: dict[Any, list[wordforms.Member]] = {}
    for item in ranking.terms:
        term = item["term"]
        listed = list(ranking.members.get(term, ()))
        if term not in SCAN_EXCLUDED:
            known = {token for token, _, _ in listed}
            for token, rule in scan.scan_only_forms(term, vocabulary):
                if token not in known:
                    member = (token, rule, wordforms.WEIGHTS[rule])
                    if rule == "exact":
                        listed.insert(0, member)
                    else:
                        listed.append(member)
                    known.add(token)
            key = wordforms.stem_key(term)
            for found, rule in (
                (parts.get(key, ()), HYPHEN_PART_RULE),
                (scan.ending_forms(term), ENDING_RULE),
                (scan.verb_forms(term), VERB_ENDING_RULE),
                (footnotes.get(key, ()), FOOTNOTE_RULE),
                (suspended.get(key, ()), SUSPENDED_RULE),
                (scan.short_parts(term), SHORT_PART_RULE),
            ):
                for token in sorted(found):
                    if token not in known:
                        listed.append((token, rule, wordforms.WEIGHTS[rule]))
                        known.add(token)
        members[term] = listed
    return members


def _word_sequence(text: str, words: frozenset, memo: dict[str, bool]) -> bool:
    """Whether a folded spelling is one or more of `words` joined by linking elements (the last one by its stem too)."""
    known = memo.get(text)
    if known is not None:
        return known
    found = text in words or wordforms.stem(text) in words
    if not found and len(text) <= wordforms.MAX_COMPOUND:
        for cut in range(wordforms.MIN_PART, len(text) - wordforms.MIN_PART + 1):
            if text[:cut] not in words:
                continue
            if any(
                text.startswith(link, cut) and len(text) - cut - len(link) >= wordforms.MIN_PART
                and _word_sequence(text[cut + len(link):], words, memo)
                for link in wordforms.LINKS
            ):
                found = True
                break
    memo[text] = found
    return found


def _linked_words(rest: str, words: frozenset, memo: dict[str, bool]) -> bool:
    """Whether the rest of a word after a short first part is a linking element and one or more `words`."""
    return any(
        rest.startswith(link) and len(rest) - len(link) >= wordforms.MIN_PART and _word_sequence(rest[len(link):], words, memo)
        for link in wordforms.LINKS
    )


def same_scan_word(left: str, right: str) -> bool:
    """Whether the scan matches two content words as forms of each other (pure).

    True for the same word in another spelling or inflection (`exact`, `fold`
    and `stem`: one stem key, so also a hyphenated word written joined or
    hyphenated elsewhere), a verb form of the word forms (`verb`: a shared
    verb key), a shared base of the `ending` rule ("Kinder" and "Kind",
    "Tage" and "Tag", "intelligentem" and "intelligenten"), and another verb
    form of a four-letter stem or of a separable verb (`verb_ending`:
    "senkt" and "senken", "abgeschaltet" and "abschalten").
    """
    if left == right:
        return True
    left_key, right_key = wordforms.stem_key(left), wordforms.stem_key(right)
    if left_key == right_key:
        return True
    if left_key.isalpha() and right_key.isalpha():
        if not {left_key, *wordforms.verb_keys(left_key)}.isdisjoint((right_key, *wordforms.verb_keys(right_key))):
            return True
    left_spelling, right_spelling = wordforms.spelling_key(left), wordforms.spelling_key(right)
    if not (left_spelling.isalpha() and right_spelling.isalpha()):
        return False
    return (
        right_spelling in ending_variants(left_spelling) or left_spelling in ending_variants(right_spelling)
        or right_spelling in verb_variants(left_spelling) or left_spelling in verb_variants(right_spelling)
    )


def counted_reformulations(
    formulations: list[dict[str, Any]],
    contents: list[list[str]],
    concepts: Optional[list[dict[str, frozenset]]] = None,
) -> list[bool]:
    """Which kept formulations count as reformulations for a complete absence check (pure).

    The question never counts. A reformulation counts when it has a content
    word and does not hold every content word of the question or of another
    reformulation with content words, wherever that one stands; of several
    reformulations that hold each other's words, only the first counts. The
    same words in another order, spelling or inflection are no new search, and
    neither are added words, which under the hit rule can only narrow what the
    scan finds. So the order of the reformulations never changes the count.

    Two words are the same when the scan matches them as forms of each other
    (`same_scan_word`), or when both stand in a run of the same confirmed
    concept in their own formulation (`concepts`: per formulation, the concept
    ids per content word), because the scan then matches every term of that
    concept for both. A hyphenated word is held where a word with the same
    stem key is ("SMS-Warndienst", "SMSWarndienst", "SMS-Warn-Dienst"), or
    where all of its parts are (`hyphen_units`: "SMS Warndienst"); the parts
    of a hyphenated word hold what they hold alone.
    """
    concepts = concepts or [{} for _ in contents]

    def pool(index: int) -> list[tuple[str, frozenset]]:
        words = [(word, concepts[index].get(word, frozenset())) for word in contents[index]]
        words.extend((unit, frozenset()) for word in contents[index] for unit in hyphen_units(word))
        return words

    def same(left: tuple[str, frozenset], right: tuple[str, frozenset]) -> bool:
        return not left[1].isdisjoint(right[1]) or same_scan_word(left[0], right[0])

    def holds(index: int, other: int) -> bool:
        """Whether formulation `index` holds every content word of formulation `other`."""
        words = pool(index)
        for word in contents[other]:
            item = (word, concepts[other].get(word, frozenset()))
            if any(same(item, candidate) for candidate in words):
                continue
            units = hyphen_units(word)
            if units and all(any(same((unit, frozenset()), candidate) for candidate in words) for unit in units):
                continue
            return False
        return True

    filled = [index for index, words in enumerate(contents) if words]
    counted: list[bool] = []
    for index, entry in enumerate(formulations[: len(contents)]):
        counts = index > 0 and entry.get("origin") == "also" and bool(contents[index])
        if counts and contents[0] and holds(index, 0):
            counts = False
        if counts:
            for other in filled:
                if other in (0, index) or not holds(index, other):
                    continue
                # A strict superset never counts; of equal ones only the first does.
                if not holds(other, index) or other < index:
                    counts = False
                    break
        counted.append(counts)
    return counted


def printed_chars(value: Any, depth: int) -> int:
    """The characters `value` takes when `report_json` prints it nested `depth` levels deep."""
    text = report_json(value)
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
    first = next((index for index, word in enumerate(words) if not wanted.isdisjoint(tokens(word, False))), 0)

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
        # Where a token stands only as an identifier (metadata, a link target), per
        # passage, header page and context key. The hyphen_part rule never splits
        # a token there; the same token written as text elsewhere is split.
        self.address_only: dict[str, set[int]] = {}
        self.header_address_only: dict[str, set[int]] = {}
        self.section_address_only: dict[str, set[tuple[int, tuple]]] = {}
        self._parts: Optional[dict[str, frozenset]] = None
        self._stems: Optional[dict[str, frozenset]] = None
        self._spellings: Optional[dict[str, frozenset]] = None
        self._footnotes: Optional[dict[str, frozenset]] = None
        self._suspended: Optional[dict[str, frozenset]] = None
        self._scan_only: Optional[tuple[Any, dict[str, frozenset]]] = None
        self._part_words: Optional[tuple[frozenset, list[tuple[str, str]]]] = None
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
            for token in passage.identifiers:
                self.address_only.setdefault(token, set()).add(pid)
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
                for token in passage.identifiers:
                    self.header_address_only.setdefault(token, set()).add(page)
            if passage.opens:
                openers.append(passage)
        # A heading, label, list item or table row is context only for the
        # passages under it; one with nothing under it is not indexed.
        for passage in openers:
            key = (page, passage.opens)
            if key in section_passages:
                for token in passage.opens_tokens:
                    self.section_index.setdefault(token, set()).add(key)
                for token in passage.identifiers:
                    self.section_address_only.setdefault(token, set()).add(key)
        self.passages.extend(passages)
        self.passage_page.extend([page] * len(passages))
        # A heading that is not emitted (an H1 repeating the title) still
        # leads its section: its words are the title's, held by the header.
        self.page_passages.append(range(first, len(self.passages)))

    def written_holders(self, token: str) -> set[int]:
        """The passages that hold `token` as written text, not only as an identifier."""
        holders = self.own.get(token, set())
        only = self.address_only.get(token)
        return holders - only if only else holders

    def hyphen_parts(self) -> dict[str, frozenset]:
        """Per stem key, the joined tokens written as text with a part of that key ("sms" -> "sms-warndienst"), built once.

        Whether a token is text is decided per passage: a token that stands
        somewhere only as an identifier or link target is still split where it
        is written as text, and never where it is an address. A part of one
        character is indexed only together with its neighbour
        (`hyphen_groups`): "e-mail-adresse" is listed under "mail",
        "adress" and "email", never under "e".
        """
        if self._parts is None:
            parts: dict[str, set[str]] = {}
            for token in self.own:
                if ("-" not in token and "_" not in token) or not self.written_holders(token):
                    continue
                units = wordforms.units_of(token)
                for unit in units:
                    if len(unit) >= 2 and unit not in SCAN_EXCLUDED:
                        parts.setdefault(wordforms.stem_key(unit), set()).add(token)
                if any(len(unit) < 2 for unit in units):
                    for group in hyphen_groups(units):
                        if "-" in group:
                            parts.setdefault(wordforms.stem_key(group), set()).add(token)
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

    def spellings(self) -> dict[str, frozenset]:
        """Per folded spelling, the alphabetic tokens scanned in an ae/oe/ue spelling ("haeuser"), built once for the ending rule.

        Every other alphabetic token is its own folded spelling and is looked up in `own` directly.
        """
        if self._spellings is None:
            spellings: dict[str, set[str]] = {}
            for token in self.own:
                if ("ae" in token or "oe" in token or "ue" in token) and token.isalpha():
                    key = wordforms.spelling_key(token)
                    if key != token:
                        spellings.setdefault(key, set()).add(token)
            self._spellings = {key: frozenset(found) for key, found in spellings.items()}
        return self._spellings

    def ending_forms(self, term: str) -> frozenset:
        """The scanned tokens that share a base with `term` (`ending_variants`), compared in folded spelling.

        "krankenhaus" finds "krankenhauser" and "krankenhausern", "tag" finds
        "tage", "tagen" and "tages", "tage" finds "tag", "intelligenten"
        finds "intelligentem" and "intelligenter", "auto" finds "autos"; a
        base of fewer than ENDING_MIN_STEM letters is never used.
        """
        if term in SCAN_EXCLUDED:
            return frozenset()
        return self._scanned(ending_variants(wordforms.spelling_key(term)), term)

    def verb_forms(self, term: str) -> frozenset:
        """The scanned tokens that are another verb form of `term` (`verb_variants`), compared in folded spelling.

        "senkt" finds "senken" and "gesenkt", "zahlen" finds "zahlt" and
        "zahlte", "abschalten" finds "abgeschaltet" and "abzuschalten"; a
        stem of fewer than VERB_MIN_STEM letters (SEPARABLE_MIN_STEM after a
        separable particle) is never used.
        """
        if term in SCAN_EXCLUDED:
            return frozenset()
        return self._scanned(verb_variants(wordforms.spelling_key(term)), term)

    def _scanned(self, candidates: set[str], term: str) -> frozenset:
        """The scanned tokens that are one of the folded `candidates`, without `term` and the excluded words."""
        if not candidates:
            return frozenset()
        spellings = self.spellings()
        found: set[str] = set()
        for candidate in candidates:
            if candidate in self.own:
                found.add(candidate)
            found.update(spellings.get(candidate, ()))
        found.discard(term)
        return frozenset(found - SCAN_EXCLUDED)

    def footnote_marks(self) -> dict[str, frozenset]:
        """Per stem key of the letters, the scanned tokens that glue one or two digits to a word of four or more letters, built once.

        "kundigungsfrist2" is listed under "kundigungsfrist": a footnote mark
        that a converter wrote as a plain digit.
        """
        if self._footnotes is None:
            footnotes: dict[str, set[str]] = {}
            for token in self.own:
                if token[-1:].isdigit():
                    match = FOOTNOTE_TOKEN.fullmatch(token)
                    if match is not None:
                        footnotes.setdefault(wordforms.stem_key(match.group(1)), set()).add(token)
            self._footnotes = {key: frozenset(found) for key, found in footnotes.items()}
        return self._footnotes

    def part_words(self) -> tuple[frozenset, list[tuple[str, str]]]:
        """The words a short part's rest may be, and the words a short part is looked for in, built once.

        The first are the folded spellings and stem keys of every alphabetic
        scanned token of at least wordforms.MIN_PART letters outside the
        excluded words. The second are (token, folded spelling) for every
        alphabetic scanned token, and for every part of a hyphenated token
        written as text, of at most wordforms.MAX_COMPOUND letters.
        """
        if self._part_words is None:
            words: set[str] = set()
            alpha: list[tuple[str, str]] = []
            for token in self.own:
                if token.isalpha():
                    if len(token) > wordforms.MAX_COMPOUND:
                        continue
                    spelling = wordforms.spelling_key(token)
                    alpha.append((token, spelling))
                    if len(spelling) >= wordforms.MIN_PART and token not in SCAN_EXCLUDED:
                        words.add(spelling)
                        words.add(wordforms.stem(spelling))
                elif "-" in token and token[:1] != SUSPENDED_MARK and self.written_holders(token):
                    for unit in wordforms.units_of(token):
                        if unit.isalpha() and len(unit) <= wordforms.MAX_COMPOUND:
                            alpha.append((token, wordforms.spelling_key(unit)))
            self._part_words = (frozenset(words), alpha)
        return self._part_words

    def short_parts(self, term: str) -> frozenset:
        """The scanned tokens that hold a term of two or three letters as a part (SHORT_PART_RULE).

        "gas" finds "gaskunden" and "gasversorger" when "kunden" and
        "versorger" are words of the scanned files, and "erdgas",
        "flussiggas" and "erdgas-tarif" without that condition; "tag" finds
        "feiertagen". A term outside those lengths, or excluded, finds nothing.
        """
        if term in SCAN_EXCLUDED:
            return frozenset()
        key = wordforms.spelling_key(term)
        if not key.isalpha() or not SHORT_PART_MIN <= len(key) <= SHORT_PART_MAX:
            return frozenset()
        words, alpha = self.part_words()
        heads = tuple(key + ending for ending in ("", *INFLECTION_ENDINGS))
        memo: dict[str, bool] = {}
        found: set[str] = set()
        for token, spelling in alpha:
            if token in found or len(spelling) < len(key) + SHORT_PART_LEAD:
                continue
            if any(
                spelling.endswith(head) and len(spelling) - len(head) >= SHORT_PART_LEAD for head in heads
            ) or (spelling.startswith(key) and _linked_words(spelling[len(key):], words, memo)):
                found.add(token)
        found.discard(term)
        return frozenset(found - SCAN_EXCLUDED)

    def suspended(self) -> dict[str, frozenset]:
        """Per stem key, the marked joined forms of suspended compounds (`suspended_forms`), built once."""
        if self._suspended is None:
            joined: dict[str, set[str]] = {}
            for token in self.own:
                if token[:1] == SUSPENDED_MARK:
                    joined.setdefault(wordforms.stem_key(token[1:]), set()).add(token)
            self._suspended = {key: frozenset(found) for key, found in joined.items()}
        return self._suspended

    def scan_only_forms(self, term: str, vocabulary: dict[str, int]) -> list[tuple[str, str]]:
        """Scanned tokens the ranking's vocabulary lacks that are `term` itself or one of its word forms, with the rule.

        The rule is `exact` for the term itself, `fold` for the same folded
        spelling, and `stem` for the same stem key, as the word-form layer
        names them. Closed-class and function words are never added.
        """
        if self._scan_only is None or self._scan_only[0] is not vocabulary:
            index: dict[str, set[str]] = {}
            for token in self.own:
                if token not in vocabulary and token not in SCAN_EXCLUDED:
                    index.setdefault(wordforms.stem_key(token), set()).add(token)
            self._scan_only = (vocabulary, {key: frozenset(found) for key, found in index.items()})
        found = self._scan_only[1].get(wordforms.stem_key(term), frozenset())
        spelling = wordforms.spelling_key(term)
        return [
            (token, "exact" if token == term else "fold" if wordforms.spelling_key(token) == spelling else "stem")
            for token in sorted(found)
        ]

    def unit_members(self, unit: str) -> list[wordforms.Member]:
        """The members of one part of a hyphenated search word written apart: its stem key alone or as a part."""
        key = wordforms.stem_key(unit)
        found = self.stems().get(key, frozenset()) | self.hyphen_parts().get(key, frozenset())
        weight = wordforms.WEIGHTS
        members = [(token, HYPHEN_PART_RULE, weight[HYPHEN_PART_RULE]) for token in sorted(found)]
        ending = self.ending_forms(unit) - found
        members.extend((token, ENDING_RULE, weight[ENDING_RULE]) for token in sorted(ending))
        members.extend(
            (token, SHORT_PART_RULE, weight[SHORT_PART_RULE]) for token in sorted(self.short_parts(unit) - found - ending)
        )
        return members


#: The matcher's key for a hyphen_part member that may only count where it is written as text.
TEXT_ONLY = "text-only"


class _Matcher:
    """The set algebra of the hit rule over one ScanIndex, with posting unions cached for one call.

    A member key is a token, or (TEXT_ONLY, token) for a joined token that
    the hyphen_part rule may only take where it is written as text.
    """

    def __init__(self, scan: ScanIndex) -> None:
        self.scan = scan
        self._own: dict[frozenset, set[int]] = {}
        self._context: dict[frozenset, set[int]] = {}

    def holders(self, key: Any) -> Iterable[int]:
        if key.__class__ is tuple:
            return self.scan.written_holders(key[1])
        return self.scan.own.get(key, ())

    def header_pages(self, key: Any) -> Iterable[int]:
        if key.__class__ is tuple:
            only = self.scan.header_address_only.get(key[1])
            pages = self.scan.header_pages.get(key[1], set())
            return pages - only if only else pages
        return self.scan.header_pages.get(key, ())

    def section_keys(self, key: Any) -> Iterable[tuple[int, tuple]]:
        if key.__class__ is tuple:
            only = self.scan.section_address_only.get(key[1])
            keys = self.scan.section_index.get(key[1], set())
            return keys - only if only else keys
        return self.scan.section_index.get(key, ())

    def own(self, members: frozenset) -> set[int]:
        found = self._own.get(members)
        if found is None:
            found = set()
            for key in members:
                found.update(self.holders(key))
            self._own[members] = found
        return found

    def context(self, members: frozenset) -> set[int]:
        """Passages that hold a member themselves, under a heading holding one, or on a page whose header holds one."""
        found = self._context.get(members)
        if found is None:
            scan = self.scan
            found = set(self.own(members))
            for key in members:
                for page in self.header_pages(key):
                    found.update(scan.page_passages[page])
                for section in self.section_keys(key):
                    found.update(scan.section_passages.get(section, ()))
            self._context[members] = found
        return found


class _Formulation:
    """What the scan needs of one kept formulation: content words, alternatives and their members.

    The members are the ranking's (see `scan_members`). A hyphenated content
    word also gets the alternative of its parts written apart (`hyphen_units`),
    each part matched in its stem key, alone or as a part of a joined token;
    `splits` maps the word to the keys of those parts.
    """

    def __init__(
        self,
        text: str,
        ranking: Ranking,
        definitions: dict[str, dict[str, Any]],
        scan: ScanIndex,
        vocabulary: dict[str, int],
    ) -> None:
        self.text = text
        self.scan = scan
        self.terms = ranking.terms
        self.members: dict[Any, list[wordforms.Member]] = scan_members(ranking, scan, vocabulary)
        self.content = content_words(ranking.terms)
        self.runs = concept_runs(text, definitions)
        self.alternatives = alternatives(self.content, self.runs, definitions)
        self._keys: dict[tuple[Any, bool], frozenset] = {}
        self._every: Optional[frozenset] = None
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

    def key_of(self, token: str, rule: str) -> Any:
        """The matcher's key for one member: a token taken by hyphen_part or short_part counts only where it is text."""
        if token in self.scan.address_only and (
            rule == SHORT_PART_RULE or (rule == HYPHEN_PART_RULE and ("-" in token or "_" in token))
        ):
            return (TEXT_ONLY, token)
        return token

    def tokens_of(self, token: Any, word_forms_only: bool) -> frozenset:
        """The matcher's keys of a term's (or a part's) members, of the word forms only when asked, built once."""
        found = self._keys.get((token, word_forms_only))
        if found is None:
            found = self._keys[(token, word_forms_only)] = frozenset(
                self.key_of(member, rule)
                for member, rule, _ in self.members.get(token, ())
                if not word_forms_only or rule in wordforms.WORD_FORM_RULES
            )
        return found

    def concepts(self) -> dict[str, frozenset]:
        """Per content word, the concepts in whose matching run it stands."""
        return {word: frozenset(key for key, run in self.runs.items() if word in run) for word in self.content}

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
        """Every member token of every content word and of its alternatives, built once."""
        if self._every is None:
            self._every = frozenset(
                member
                for word in self.content
                for _concept, option in self.alternatives[word]
                for token in option
                for member, _, _ in self.members.get(token, ())
            )
        return self._every

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
                    key = self.key_of(token, rule)
                    if token in passage.tokens and (key.__class__ is not tuple or token not in passage.identifiers):
                        where = 0
                    elif not sections.isdisjoint(matcher.section_keys(key)):
                        where = 1
                    elif page in matcher.header_pages(key):
                        where = 2
                    else:
                        continue
                    rank = (where, -weight, token)
                    if best is None or rank < best[0]:
                        best = (rank, rule)
                if best is None:
                    continue
                entry: dict[str, Any] = {
                    "term": word,
                    "token": shown_token(best[0][2]),
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
            relative = path.removeprefix(path_prefix)
            for claim in entry.get("claims") or []:
                key = (relative, str(claim.get("id") or "") or str(claim.get("text") or ""))
                printed.setdefault(key, where)
    return printed


def fit_prefix(entries: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], bool]:
    """The longest prefix of page entries, hit by hit, that `report_json` prints within `budget` characters (pure).

    Returns the entries of that prefix, the last one possibly with fewer
    hits, and whether anything was left out. The size is counted where
    exhaustive_hits stands in a report, one level deep: "[]", each entry with
    its first hit two levels deep, each further hit four levels deep, and the
    line breaks, commas and indents between them.
    """
    returned: list[dict[str, Any]] = []
    used = 2  # "[]"
    for entry in entries:
        emitted: Optional[dict[str, Any]] = None
        for hit in entry["hits"]:
            if emitted is None:
                # A first entry adds two line breaks and the indents of the entry and of "]",
                # a later one ",\n" and its indent.
                cost = (8 if not returned else 6) + printed_chars({**entry, "hits": [hit]}, 2)
            else:
                # ",\n" and the indent of a hit.
                cost = 10 + printed_chars(hit, 4)
            if used + cost > budget:
                return returned, True
            used += cost
            if emitted is None:
                emitted = {**entry, "hits": [hit]}
                returned.append(emitted)
            else:
                emitted["hits"].append(hit)
    return returned, False


def _census(formulations: list[_Formulation], matcher: _Matcher, vocabulary: dict[str, int]) -> list[dict[str, Any]]:
    """Every term of every formulation except closed-class and function words, once per (term, origin).

    Each entry names the formulations that hold the term, how many passages
    and files hold one of its members per scanned layer (a hyphenated query
    word also where a passage holds all of its parts), and its members.
    """
    scan = matcher.scan
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
            holders = matcher.own(formulation.tokens_of(term, False))
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
                "forms": [{"token": shown_token(token), "rule": rule} for token, rule, _ in ordered[:FORMS_LISTED]],
                "forms_total": len(members),
            }
    return list(census.values())


def exhaustive_scan(
    scan: ScanIndex,
    rankings: list[Ranking],
    kept: list[dict[str, Any]],
    definitions: dict[str, dict[str, Any]],
    vocabulary: dict[str, int],
    printed: dict[tuple[str, str], str],
    budget: int,
) -> dict[str, Any]:
    """Every passage that holds all content words of a kept formulation, ordered, cut to `budget` printed characters.

    `kept` holds the kept formulations (index, text, origin), `rankings` their
    rankings. Returns the returned page entries (`hits`), whether the
    question's own hits fit into the budget (`narrowable`, internal), and the
    fields of absence_check that describe the scan: the counted
    reformulations, per-formulation counts, census, absent terms, counts,
    budget, omitted pages and scopes.
    """
    matcher = _Matcher(scan)
    formulations = [
        _Formulation(entry["text"], ranking, definitions, scan, vocabulary) for entry, ranking in zip(kept, rankings)
    ]
    counted = counted_reformulations(
        kept, [formulation.content for formulation in formulations], [formulation.concepts() for formulation in formulations]
    )
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
    returned, stopped = fit_prefix(entries, budget)
    used = printed_chars(returned, 1)
    needed = printed_chars(entries, 1) if stopped else used
    # Narrower reformulations can only help while the question's own hits fit:
    # its hits do not depend on the reformulations.
    narrowable = True
    if stopped:
        own_entries: list[dict[str, Any]] = []
        for entry in entries:
            own_hits = [hit for hit in entry["hits"] if 0 in hit["formulations"]]
            if own_hits:
                own_entries.append({**entry, "hits_total": len(own_hits), "hits": own_hits})
        narrowable = not fit_prefix(own_entries, budget)[1]

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

    terms = _census(formulations, matcher, vocabulary)
    absent = sorted(
        {
            entry["term"]
            for entry in terms
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
        "terms": terms,
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
    next_steps: Optional[list[str]] = None
    if scanned is None:
        reasons = ["not_exhaustive"]
    else:
        applies = {
            "not_exhaustive": False,
            "too_few_reformulations": scanned["reformulations_counted"] < MIN_EXHAUSTIVE_REFORMULATIONS,
            "no_content_words": not any(entry["content_words"] for entry in scanned["formulations"]),
            "budget_exhausted": scanned["budget"]["needed_chars"] > scanned["budget"]["limit_chars"],
        }
        reasons = [reason for reason in ABSENCE_REASONS if applies[reason]]
        next_steps = absence_steps(reasons, results, block, scanned["hits"], scanned["narrowable"])
    return {
        "format": ABSENCE_CHECK_FORMAT,
        "complete": not reasons,
        "reasons": reasons,
        "next_steps": next_steps,
        **{field: None if scanned is None else scanned[field] for field in SCAN_FIELDS},
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


def report_body(
    found: dict[str, Any], release: dict[str, Any], selector: dict[str, Any], scope_flags: dict[str, bool]
) -> dict[str, Any]:
    """The report a wrapper prints for a search, in the order both wrappers print it (pure).

    `found` is what `search` returned, `release` the release the wrapper
    verified and `selector` the validated selector. `scope_flags` holds the
    effective layer options the wrapper offers, in its order (`include_sources`,
    and `include_history` where history ships).
    """
    return {
        # The query exactly as given: plan_formulations keeps it as formulation 0.
        "query": found["formulations"][0]["text"],
        "formulations": found["formulations"],
        "dropped_formulations": found["dropped_formulations"],
        "release": release,
        # The verdict and the record line come first: hosts may cut long output to a preview.
        "search_record": search_record(found, release),
        "absence_check": found["absence_check"],
        "searched_files": found["searched_files"],
        **scope_flags,
        "selector": selector,
        "filtered_out": found["filtered_out"],
        "matched_concepts": found["matched_concepts"],
        "expanded_terms": found["expanded_terms"],
        "facets": found["facets"],
        "results": found["results"],
        "reformulation_results": found["reformulation_results"],
        "coverage": found["coverage"],
        # Last, so a cut preview still shows everything above.
        "exhaustive_hits": found["exhaustive_hits"],
    }


def report_json(value: Any) -> str:
    """A report, or any part of one, as both wrappers print it; the budget of exhaustive_hits is counted in it."""
    return json.dumps(value, ensure_ascii=False, indent=REPORT_INDENT)


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
    if exhaustive and not loaded.exhaustive:
        raise ValueError("an exhaustive search needs a release loaded with exhaustive=True")
    also = list(also)
    kept, dropped = plan_formulations(query, also)
    if not formulation_key(query):
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
        scanned = exhaustive_scan(
            loaded.scan,
            rankings,
            formulations,
            loaded.concept_definitions,
            loaded.vocabulary,
            printed_claim_keys(results, block, loaded.path_prefix),
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
    exhaustive: bool = False,
    exhaustive_budget: int = EXHAUSTIVE_BUDGET_CHARS,
) -> dict[str, Any]:
    """Rank the release under `root` for `query` and its reformulations, and account for what is not shown.

    `also` holds at most MAX_ALSO reformulations (see `plan_formulations`).
    `selector` must already be validated by `wiki_filters.validate_selector`.
    `history_shipped=False` describes a release that carries no history layer,
    such as an exported knowledge skill. `path_prefix` is prepended to every
    path the report names; selectors, scopes and navigation are decided on the
    release-relative path.

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
    # Invalid input is refused before the release is read.
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if include_history and not history_shipped:
        raise ValueError("this release ships no history layer to search")
    also = list(also)
    plan_formulations(query, also)
    if not formulation_key(query):
        raise QueryError("query must contain at least one searchable token")
    loaded = load(
        root,
        include_sources=include_sources or exhaustive,
        include_history=include_history,
        selector=selector,
        history_shipped=history_shipped,
        path_prefix=path_prefix,
        exhaustive=exhaustive,
    )
    return search_loaded(
        loaded, query, also=also, limit=limit, exhaustive=exhaustive, exhaustive_budget=exhaustive_budget
    )
