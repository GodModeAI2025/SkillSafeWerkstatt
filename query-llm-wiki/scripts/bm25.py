#!/usr/bin/env python3
"""Field-weighted BM25 ranking over a wiki, using the standard library only.

The previous ranking added hand-picked constants per match. That is neither
length-normalised nor inverse-document-frequency weighted, so long pages ranked
higher simply for being long, and a term appearing on every page counted as much
as one appearing on two.

This implements BM25F: term frequency is accumulated across weighted fields,
each normalised by that field's own average length, and every query term is
weighted by how rare it is in this corpus. It needs corpus statistics, so
callers collect all candidates first and score afterwards.

The wiki's own signals - controlled concepts, an exact phrase, page status - stay
as bonuses on top. They express curation the corpus statistics cannot see.

Every query term is a weighted group of document tokens (see `TermGroup`
and wordforms.py): the literal token at weight 1.0 and its word forms and
heuristic matches at lower weights. A group of the literal token alone scores
exactly as the plain BM25F of that token.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Optional, Sequence


#: Term-frequency saturation. The standard default.
K1 = 1.2

#: Length normalisation per field. The standard default.
B = 0.75

#: Field weights, carried over from the previous ranking so relative emphasis
#: between title, aliases, headings, description and body is unchanged.
FIELD_WEIGHTS = {
    "title": 10.0,
    "aliases": 7.0,
    "headings": 5.0,
    "description": 4.0,
    "body": 1.0,
}

#: Modifiers for signals the corpus statistics cannot see.
#:
#: These are multiplicative on purpose. BM25 scores scale with corpus size and
#: term rarity, so a fixed addition means something different in a wiki of ten
#: pages than in one of a thousand - and a fixed subtraction could drive a real
#: textual match below zero and drop it from the results entirely. A factor
#: reorders comparable documents without ever suppressing or inventing a match.
PHRASE_FACTOR = 1.5
CONCEPT_FACTOR_PER_MATCH = 0.5
STATUS_FACTOR = {"active": 1.15, "draft": 0.95, "superseded": 0.75, "withdrawn": 0.75}


class Corpus:
    """Corpus statistics needed to score any document in it."""

    def __init__(self, documents: Iterable[dict[str, list[str]]]) -> None:
        self.count = 0
        self.field_length_total: dict[str, int] = {field: 0 for field in FIELD_WEIGHTS}
        for fields in documents:
            self.count += 1
            for field in FIELD_WEIGHTS:
                self.field_length_total[field] += len(fields.get(field) or [])

    def average_length(self, field: str) -> float:
        if not self.count:
            return 0.0
        return self.field_length_total.get(field, 0) / self.count

    def inverse_document_frequency_of(self, frequency: int) -> float:
        """Standard BM25 IDF for a document frequency counted by the caller, such as a term group's.

        It stays positive for every observed term.
        """
        return math.log(1.0 + (self.count - frequency + 0.5) / (frequency + 0.5))


class TermGroup:
    """One query term as weighted document tokens.

    `members` maps every token that counts for the term to its weight: 1.0 for
    the literal token, less for a word form or a heuristic member (see
    wordforms.py). `document_frequency` is counted by the caller, because only
    the caller knows which members may make a term look common: the search
    core counts word forms only, and heuristic members only when no document
    holds a word form.
    """

    __slots__ = ("label", "members", "document_frequency")

    def __init__(self, label: str, members: Mapping[str, float], document_frequency: int) -> None:
        self.label = label
        self.members = dict(members)
        self.document_frequency = document_frequency


def group_base_score(
    corpus: Corpus,
    fields: dict[str, list[str]],
    groups: Sequence[TermGroup],
    counted: Optional[dict[str, list[str]]] = None,
    words: Optional[set[str]] = None,
) -> float:
    """BM25F where every query term is a TermGroup.

    The occurrences of a group's members are accumulated across the weighted
    fields exactly like those of one literal token and saturated; the rule
    weight is applied after saturation. Members of different weights are
    layered: the layer up to weight w is filled by the occurrences of every
    member weighing at least w. So a document holding only the literal token
    scores exactly as the plain BM25F of that token, one holding only a
    member of weight w scores w times that (a compound part in a title keeps
    its own weight of an exact title hit, not almost all of it), and every
    further occurrence of any member only adds. A document holding no member
    of any group scores 0.

    `counted`, when given, receives per group label the tokens that counted.
    `words`, when given, must be the set of every token of `fields`; a caller
    that keeps it per document saves building it again.
    """
    if not corpus.count:
        # Without a corpus there is no term rarity and no average length, so a
        # score would be a number without meaning. Rank nothing instead.
        return 0.0
    field_tokens = {field: fields.get(field) or [] for field in FIELD_WEIGHTS}
    if words is None:
        words = set().union(*field_tokens.values())
    normalisers: dict[str, float] = {}
    for field, values in field_tokens.items():
        # Normalise by this field's own average length, so a long body does
        # not outrank a precise title.
        average = corpus.average_length(field)
        normalisers[field] = 1.0 - B + B * (len(values) / average if average else 1.0)
    score = 0.0
    for group in groups:
        # Only the members the document holds are counted, in a fixed order.
        present = sorted(words.intersection(group.members))
        if not present:
            continue
        by_weight: dict[float, float] = {}
        for token in present:
            accumulated = 0.0
            for field, weight in FIELD_WEIGHTS.items():
                frequency = field_tokens[field].count(token)
                if frequency:
                    accumulated += weight * frequency / normalisers[field]
            level = group.members[token]
            by_weight[level] = by_weight.get(level, 0.0) + accumulated
        idf = corpus.inverse_document_frequency_of(group.document_frequency)
        levels = sorted(by_weight, reverse=True)
        layered = 0.0
        for index, level in enumerate(levels):
            layered += by_weight[level]
            below = levels[index + 1] if index + 1 < len(levels) else 0.0
            score += (level - below) * idf * layered / (K1 + layered)
        if counted is not None:
            counted[group.label] = present
    return score


def score(
    corpus: Corpus,
    fields: dict[str, list[str]],
    groups: Sequence[TermGroup],
    *,
    phrase_match: bool = False,
    concept_overlap: int = 0,
    status: str = "",
    explain: Optional[dict[str, float]] = None,
    counted: Optional[dict[str, list[str]]] = None,
    words: Optional[set[str]] = None,
) -> float:
    """BM25F over the query's term groups, scaled by the wiki's curated signals, never below zero.

    `counted` and `words` are passed to `group_base_score`.
    """
    base = group_base_score(corpus, fields, groups, counted, words)
    if base <= 0:
        # Nothing in this document's text answers the query. Curation reorders
        # matches; it never turns a non-match into one.
        if explain is not None:
            explain.update({"bm25": 0.0, "phrase": 1.0, "concepts": 1.0, "status": 1.0})
        return 0.0
    phrase = PHRASE_FACTOR if phrase_match else 1.0
    concepts = 1.0 + CONCEPT_FACTOR_PER_MATCH * max(concept_overlap, 0)
    adjustment = STATUS_FACTOR.get(status, 1.0)
    if explain is not None:
        explain.update(
            {
                "bm25": round(base, 4),
                "phrase": phrase,
                "concepts": concepts,
                "status": adjustment,
            }
        )
    return max(base * phrase * concepts * adjustment, 0.0)
