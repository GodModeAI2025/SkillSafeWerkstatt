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

A query term can also be a weighted group of document tokens (see
`TermGroup` and wordforms.py): the literal token at weight 1.0 and its word
forms and heuristic matches at lower weights. Without groups, scoring is the
literal-token BM25F exactly as before groups existed.
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
        self.document_frequency: dict[str, int] = {}
        self.field_length_total: dict[str, int] = {field: 0 for field in FIELD_WEIGHTS}
        for fields in documents:
            self.count += 1
            seen: set[str] = set()
            for field in FIELD_WEIGHTS:
                field_tokens = fields.get(field) or []
                self.field_length_total[field] += len(field_tokens)
                seen.update(field_tokens)
            for term in seen:
                self.document_frequency[term] = self.document_frequency.get(term, 0) + 1

    def average_length(self, field: str) -> float:
        if not self.count:
            return 0.0
        return self.field_length_total.get(field, 0) / self.count

    def inverse_document_frequency(self, term: str) -> float:
        """Standard BM25 IDF, which stays positive for every observed term."""
        frequency = self.document_frequency.get(term, 0)
        return math.log(1.0 + (self.count - frequency + 0.5) / (frequency + 0.5))

    def inverse_document_frequency_of(self, frequency: int) -> float:
        """The same IDF for a document frequency counted by the caller, such as a term group's."""
        return math.log(1.0 + (self.count - frequency + 0.5) / (frequency + 0.5))


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def base_score(
    corpus: Corpus,
    fields: dict[str, list[str]],
    query_terms: Iterable[str],
) -> float:
    """The BM25F score of one document against the query terms."""
    if not corpus.count:
        # Without a corpus there is no term rarity and no average length, so a
        # score would be a number without meaning. Rank nothing instead.
        return 0.0
    counted = {field: _counts(fields.get(field) or []) for field in FIELD_WEIGHTS}
    score = 0.0
    for term in set(query_terms):
        accumulated = 0.0
        for field, weight in FIELD_WEIGHTS.items():
            frequency = counted[field].get(term, 0)
            if not frequency:
                continue
            average = corpus.average_length(field)
            length = len(fields.get(field) or [])
            # Normalise by this field's own average length, so a long body does
            # not outrank a precise title.
            normaliser = 1.0 - B + B * (length / average if average else 1.0)
            accumulated += weight * frequency / normaliser
        if accumulated:
            score += corpus.inverse_document_frequency(term) * accumulated / (K1 + accumulated)
    return score


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
) -> float:
    """BM25F where every query term is a TermGroup.

    The occurrences of a group's members are accumulated across the weighted
    fields exactly like those of one literal token and saturated; the rule
    weight is applied after saturation. Members of different weights are
    layered: the layer up to weight w is filled by the occurrences of every
    member weighing at least w. So a document holding only the literal token
    scores exactly as in the literal search, one holding only a member of
    weight w scores w times that (a compound part in a title keeps its own
    weight of an exact title hit, not almost all of it), and every further
    occurrence of any member only adds. A document holding no member of any
    group scores 0.

    `counted`, when given, receives per group label the tokens that counted.
    """
    if not corpus.count:
        return 0.0
    counts = {field: _counts(fields.get(field) or []) for field in FIELD_WEIGHTS}
    present_tokens: set[str] = set()
    for field_counts in counts.values():
        present_tokens.update(field_counts)
    normalisers: dict[str, float] = {}
    for field in FIELD_WEIGHTS:
        average = corpus.average_length(field)
        length = len(fields.get(field) or [])
        normalisers[field] = 1.0 - B + B * (length / average if average else 1.0)
    score = 0.0
    for group in groups:
        present = sorted(present_tokens.intersection(group.members))
        if not present:
            continue
        by_weight: dict[float, float] = {}
        for token in present:
            accumulated = 0.0
            for field, weight in FIELD_WEIGHTS.items():
                frequency = counts[field].get(token, 0)
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
    query_terms: Iterable[str],
    *,
    phrase_match: bool = False,
    concept_overlap: int = 0,
    status: str = "",
    explain: Optional[dict[str, float]] = None,
    groups: Optional[Sequence[TermGroup]] = None,
    counted: Optional[dict[str, list[str]]] = None,
) -> float:
    """BM25F scaled by the wiki's curated signals, never below zero.

    With `groups`, every query term is a TermGroup and `query_terms` is not
    used; `counted` then receives the tokens that counted per group. Without
    `groups`, this is the literal-token score, unchanged.
    """
    if groups is not None:
        base = group_base_score(corpus, fields, groups, counted)
    else:
        base = base_score(corpus, fields, query_terms)
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
