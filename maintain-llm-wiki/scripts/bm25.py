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
"""

from __future__ import annotations

import math
from typing import Iterable, Optional


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


def score(
    corpus: Corpus,
    fields: dict[str, list[str]],
    query_terms: Iterable[str],
    *,
    phrase_match: bool = False,
    concept_overlap: int = 0,
    status: str = "",
    explain: Optional[dict[str, float]] = None,
) -> float:
    """BM25F scaled by the wiki's curated signals, never below zero."""
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
