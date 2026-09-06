#!/usr/bin/env python3
"""BM25F ranking (OKF stage 2).

The previous ranking added hand-picked constants per match: neither
length-normalised nor IDF-weighted, so long pages ranked higher for being long
and a term on every page counted as much as one on two.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "query-llm-wiki" / "scripts"))

import bm25  # noqa: E402
from harness import TempWiki  # noqa: E402


def fields(title: str = "", body: str = "", **rest: str) -> dict[str, list[str]]:
    document = {"title": title.split(), "body": body.split()}
    for name in ("aliases", "headings", "description"):
        document[name] = rest.get(name, "").split()
    return document


class LengthNormalisation(unittest.TestCase):
    def test_a_longer_page_does_not_win_on_length_alone(self) -> None:
        short = fields(body="netzentgelt " + "fuellwort " * 10)
        long = fields(body="netzentgelt netzentgelt " + "fuellwort " * 200)
        corpus = bm25.Corpus([short, long])
        short_score = bm25.score(corpus, short, ["netzentgelt"])
        long_score = bm25.score(corpus, long, ["netzentgelt"])
        self.assertGreater(
            short_score,
            long_score,
            "twice the matches in twenty times the text is a weaker match, not a stronger one",
        )

    def test_a_dense_match_beats_a_diluted_one(self) -> None:
        dense = fields(body="netzentgelt arbeitspreis")
        diluted = fields(body="netzentgelt " + "unrelated " * 500)
        corpus = bm25.Corpus([dense, diluted])
        self.assertGreater(
            bm25.score(corpus, dense, ["netzentgelt"]),
            bm25.score(corpus, diluted, ["netzentgelt"]),
        )


class InverseDocumentFrequency(unittest.TestCase):
    def test_a_rare_term_weighs_more_than_a_common_one(self) -> None:
        documents = [fields(body="gemeinsam selten") ] + [
            fields(body="gemeinsam anderes") for _ in range(19)
        ]
        corpus = bm25.Corpus(documents)
        self.assertGreater(
            corpus.inverse_document_frequency("selten"),
            corpus.inverse_document_frequency("gemeinsam"),
            "a term on one page in twenty must outweigh one on every page",
        )

    def test_every_observed_term_keeps_a_positive_weight(self) -> None:
        documents = [fields(body="ueberall") for _ in range(50)]
        corpus = bm25.Corpus(documents)
        self.assertGreater(
            corpus.inverse_document_frequency("ueberall"),
            0.0,
            "a term on every page must still be findable",
        )

    def test_an_unseen_term_scores_nothing(self) -> None:
        document = fields(body="etwas")
        corpus = bm25.Corpus([document])
        self.assertEqual(bm25.score(corpus, document, ["fehlt"]), 0.0)


class FieldWeighting(unittest.TestCase):
    def test_a_title_match_outranks_a_body_match(self) -> None:
        in_title = fields(title="netzentgelt", body="etwas anderes hier")
        in_body = fields(title="anderes", body="netzentgelt steht hier")
        corpus = bm25.Corpus([in_title, in_body])
        self.assertGreater(
            bm25.score(corpus, in_title, ["netzentgelt"]),
            bm25.score(corpus, in_body, ["netzentgelt"]),
        )


class CuratedSignals(unittest.TestCase):
    """The wiki's own signals reorder matches; they never invent one."""

    def test_curation_cannot_turn_a_non_match_into_a_match(self) -> None:
        document = fields(body="voellig anderes thema")
        corpus = bm25.Corpus([document])
        self.assertEqual(
            bm25.score(
                corpus, document, ["netzentgelt"],
                phrase_match=True, concept_overlap=5, status="active",
            ),
            0.0,
        )

    def test_a_superseded_page_ranks_below_an_identical_active_one(self) -> None:
        document = fields(body="netzentgelt")
        corpus = bm25.Corpus([document, document])
        active = bm25.score(corpus, document, ["netzentgelt"], status="active")
        superseded = bm25.score(corpus, document, ["netzentgelt"], status="superseded")
        self.assertGreater(active, superseded)
        self.assertGreater(superseded, 0.0, "history stays findable")

    def test_a_concept_match_lifts_a_comparable_page(self) -> None:
        document = fields(body="netzentgelt")
        corpus = bm25.Corpus([document, document])
        plain = bm25.score(corpus, document, ["netzentgelt"])
        curated = bm25.score(corpus, document, ["netzentgelt"], concept_overlap=1)
        self.assertGreater(curated, plain)

    def test_an_exact_phrase_lifts_a_comparable_page(self) -> None:
        document = fields(body="netzentgelt arbeitspreis")
        corpus = bm25.Corpus([document, document])
        self.assertGreater(
            bm25.score(corpus, document, ["netzentgelt"], phrase_match=True),
            bm25.score(corpus, document, ["netzentgelt"]),
        )

    def test_the_breakdown_is_available_for_inspection(self) -> None:
        document = fields(body="netzentgelt")
        corpus = bm25.Corpus([document])
        explain: dict[str, float] = {}
        bm25.score(corpus, document, ["netzentgelt"], status="active", explain=explain)
        self.assertEqual(sorted(explain), ["bm25", "concepts", "phrase", "status"])
        self.assertGreater(explain["bm25"], 0.0)


class EmptyCorpus(unittest.TestCase):
    def test_an_empty_corpus_does_not_divide_by_zero(self) -> None:
        corpus = bm25.Corpus([])
        self.assertEqual(corpus.average_length("body"), 0.0)
        self.assertEqual(bm25.score(corpus, fields(body="x"), ["x"]), 0.0)


class EndToEnd(unittest.TestCase):
    def test_the_best_title_match_ranks_first(self) -> None:
        with TempWiki() as wiki:
            found = wiki.query_json(
                "search_wiki.py", "--target", str(wiki.path), "--query", "Überblick"
            )
            self.assertTrue(found["results"])
            self.assertEqual(found["results"][0]["path"], "wiki/overview.md")

    def test_scores_are_positive_and_ordered(self) -> None:
        with TempWiki() as wiki:
            found = wiki.query_json(
                "search_wiki.py", "--target", str(wiki.path), "--query", "Wiki"
            )
            scores = [item["score"] for item in found["results"]]
            self.assertTrue(all(value > 0 for value in scores), scores)
            self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
