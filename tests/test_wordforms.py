#!/usr/bin/env python3
"""The word-form layer of the shared search core (Stufe 2).

Every query term becomes a weighted group of tokens that really occur in the
searched files: the literal token at 1.0, word forms (fold, stem, verb) and the
disclosed heuristics (compound parts, query-word head, typo) below it. These
tests pin the rules one by one and the five construction rules a precision
attack on an earlier draft found (R1 to R5); each of those tests fails when its
rule is broken:

- R1: a group's rarity comes from the literal token and its word forms only.
- R2: a rule weight applies after BM25 saturation.
- R3: the phrase signal counts only literal words on whole-token boundaries.
- R4: link targets and slugs are never split into parts that can match.
- R5: a typo correction is one edit, only for long words, only as a last resort.

A review of the first implementation added tests for rules that could be
broken without any test failing: the verb and -er rules, the navigation and
unsearched-layer counts, group merging, concept triggering, and a bound on the
length of a token the compound rules consider.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "query-llm-wiki" / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))

import bm25  # noqa: E402
import search_core  # noqa: E402
import wordforms  # noqa: E402


def resolver(*words: str) -> wordforms.Resolver:
    """A resolver over the given normalised words, each in one file."""
    return wordforms.Resolver({word: 1 for word in words}, search_core.CLOSED_CLASS, search_core.FORM_STOPWORDS)


def rules(members: list) -> dict[str, str]:
    return {token: rule for token, rule, _weight in members}


def page(title: str, body: str, **frontmatter: str) -> str:
    lines = ["---", f'title: "{title}"', 'status: "active"']
    lines += [f'{key}: "{value}"' for key, value in frontmatter.items()]
    return "\n".join(lines + ["---", "", f"# {title}", "", body, ""])


class TempPages:
    """A folder the search core can read: wiki pages, no release, nothing else."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def __enter__(self) -> Path:
        self._directory = tempfile.TemporaryDirectory(prefix="lmwiki-wordforms-")
        root = Path(self._directory.name)
        (root / "WIKI.md").write_text("# Wiki\n", encoding="utf-8")
        for relative, text in self.pages.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    def __exit__(self, *_exc: object) -> None:
        self._directory.cleanup()


class StepA_Normalisation(unittest.TestCase):
    def test_umlaut_digraphs_fold_in_both_directions(self) -> None:
        self.assertEqual(wordforms.spelling_key("kuendigung"), wordforms.spelling_key("kundigung"))
        self.assertEqual(rules(resolver("kundigung").resolve("kuendigung")), {"kundigung": "fold"})
        self.assertEqual(rules(resolver("kuendigung").resolve("kundigung")), {"kuendigung": "fold"})
        # ue after q, a or e is no umlaut spelling.
        for word in ("quelle", "steuer", "neue", "bauer"):
            with self.subTest(word=word):
                self.assertEqual(wordforms.fold_umlaut(word), word)
        # ß and ss already meet through case folding.
        self.assertEqual(search_core.tokens("Schlußrechnung", forms=True), ["schlussrechnung"])

    def test_a_hyphenated_word_meets_its_joined_spelling(self) -> None:
        self.assertEqual(rules(resolver("e-mail").resolve("email")), {"e-mail": "fold"})
        self.assertEqual(rules(resolver("email").resolve("e-mail")), {"email": "fold"})

    def test_layout_artefacts_inside_words_are_repaired(self) -> None:
        self.assertEqual(wordforms.repair_text("Kün­digung"), "Kündigung")
        self.assertEqual(wordforms.repair_text("Zähler​stand"), "Zählerstand")
        self.assertEqual(wordforms.repair_text("Kündi-\ngung"), "Kündigung")
        self.assertEqual(wordforms.repair_text("Kündi- \r\n  gung"), "Kündigung")
        self.assertEqual(wordforms.repair_text("E‑Mobilität"), "E-Mobilität")
        # A hyphenated word broken at its own hyphen keeps the hyphen.
        self.assertEqual(wordforms.repair_text("Schufa-\nAbfrage"), "Schufa-Abfrage")
        # A suspended compound, a list and a paragraph break stay as they are.
        for text in ("Netz-\nund Messentgelte", "Text-\n- Punkt", "Ende-\n\nNeuer Absatz", "Seite 3-\n4"):
            with self.subTest(text=text):
                self.assertEqual(wordforms.repair_text(text), text)

    def test_the_stopword_list_is_compared_in_its_normalised_form(self) -> None:
        self.assertEqual(search_core.tokens("Frist für Kündigung", forms=True), ["frist", "kundigung"])
        # The literal search keeps its old behaviour, where "für" never matched.
        self.assertEqual(search_core.tokens("Frist für Kündigung"), ["frist", "fur", "kundigung"])
        terms, dropped = search_core.query_terms("Frist für Kündigung", [], forms=True)
        self.assertEqual([item["term"] for item in terms], ["frist", "kundigung"])
        self.assertEqual(dropped, [{"term": "fur", "reason": "stopword"}])

    def test_closed_class_words_match_only_literally(self) -> None:
        index = resolver(
            "werden", "wer", "seit", "seite", "seiten", "uber", "uberweisung", "gegen", "gegenleistung", "leistung"
        )
        self.assertEqual(rules(index.resolve("werden")), {"werden": "exact"})
        self.assertEqual(rules(index.resolve("uber")), {"uber": "exact"}, "never a modifier of a compound")
        # "seit" is never a form of "Seite", and "Seite" never a form of "seit".
        self.assertEqual(rules(index.resolve("seite")), {"seite": "exact", "seiten": "stem"})
        self.assertEqual(rules(index.resolve("seit")), {"seit": "exact"})
        # A closed-class word still glues a compound together.
        self.assertEqual(rules(index.resolve("leistung"))["gegenleistung"], "compound_head")
        self.assertFalse(wordforms.same_word("seit", "seite", search_core.CLOSED_CLASS))


class StepB_Inflection(unittest.TestCase):
    def test_inflection_endings_are_stripped_conservatively(self) -> None:
        cases = {
            "tarife": "tarif", "netzentgelten": "netzentgelt", "gebuhren": "gebuhr", "vertrages": "vertrag",
            "zahlern": "zahler", "elektronischer": "elektronisch", "policies": "policy", "meters": "meter",
            "monats": "monat",
        }
        for word, expected in cases.items():
            with self.subTest(word=word):
                self.assertEqual(wordforms.stem(word), expected)

    def test_no_derivational_suffix_and_no_agent_noun_ending_is_removed(self) -> None:
        self.assertEqual(wordforms.stem("kundigung"), "kundigung")
        self.assertEqual(wordforms.stem("zahler"), "zahler")
        self.assertNotEqual(wordforms.stem("zahler"), wordforms.stem("zahlen"), "Zähler is not zahlen")
        self.assertEqual(wordforms.stem("daten"), "daten", "a stem keeps at least four letters")

    def test_verb_forms_are_a_weaker_secondary_key(self) -> None:
        self.assertIn("kundig", wordforms.verb_keys("gekundigt"))
        found = resolver("widerruf", "kundigen").resolve("widerruft")
        self.assertEqual(rules(found), {"widerruf": "verb"})
        self.assertEqual(rules(resolver("kundigen").resolve("gekundigt")), {"kundigen": "verb"})
        self.assertEqual(rules(resolver("berechnet").resolve("berechnen")), {"berechnet": "verb"})
        weights = wordforms.WEIGHTS
        self.assertTrue(1.0 == weights["exact"] > weights["fold"] > weights["stem"] > weights["verb"])
        self.assertTrue(all(weight < 1.0 for rule, weight in weights.items() if rule != "exact"))


    def test_et_is_a_verb_ending_only_where_german_writes_the_e(self) -> None:
        for word in ("meldet", "arbeitet", "rechnet", "zeichnet", "offnet"):
            with self.subTest(word=word):
                self.assertEqual(wordforms.verb_keys(wordforms.stem_key(word)), [word[:-2]])
        for word in ("planet", "market", "internet", "budget"):
            with self.subTest(word=word):
                self.assertEqual(wordforms.verb_keys(wordforms.stem_key(word)), [])
        self.assertEqual(resolver("plan", "planen").resolve("planet"), [])
        self.assertEqual(resolver("internen", "interne", "intern").word_forms("internet"), {})
        self.assertEqual(resolver("internet").word_forms("internen"), {})

    def test_a_corpus_t_form_is_a_verb_form_only_of_a_word_that_can_be_a_verb(self) -> None:
        index = resolver("andert", "widerruft")
        self.assertEqual(index.resolve("andere"), [], "andere is no form of ändert")
        self.assertEqual(index.resolve("anders"), [])
        self.assertEqual(rules(index.resolve("andern")), {"andert": "verb"})
        self.assertEqual(rules(index.resolve("widerruf")), {"widerruft": "verb"})

    def test_a_noun_keeps_its_er_and_one_key_for_all_its_forms(self) -> None:
        for family, verb in (
            (("hersteller", "herstellers", "herstellern"), "herstellen"),
            (("antragsteller", "antragstellers", "antragstellern"), "antragstellen"),
            (("keller", "kellers", "kellern"), "kelle"),
            (("zeiger", "zeigers", "zeigern"), "zeigen"),
            (("fischer", "fischers", "fischern"), "fisch"),
        ):
            with self.subTest(family=family):
                self.assertEqual({wordforms.stem(word) for word in family}, {family[0]})
                self.assertNotEqual(wordforms.stem(family[0]), wordforms.stem(verb))
        found = rules(resolver("hersteller", "herstellers", "herstellen").resolve("herstellern"))
        self.assertEqual(found, {"hersteller": "stem", "herstellers": "stem"})
        # Adjectives still lose their -er: aktueller, wichtiger, frischer, formeller.
        adjectives = (("aktueller", "aktuell"), ("wichtiger", "wichtig"), ("frischer", "frisch"), ("formeller", "formell"))
        for word, expected in adjectives:
            with self.subTest(word=word):
                self.assertEqual(wordforms.stem(word), expected)
        # A noun the rule reads as an adjective still keeps one key for its forms.
        self.assertEqual({wordforms.stem(word) for word in ("glaubiger", "glaubigers", "glaubigern")}, {"glaubig"})


class StepC_Compounds(unittest.TestCase):
    def test_a_term_matches_as_head_or_modifier_only_between_real_words(self) -> None:
        index = resolver("vertragslaufzeit", "vertrag", "laufzeit", "sondervertrag")
        laufzeit = rules(index.resolve("laufzeit"))
        self.assertEqual(laufzeit, {"laufzeit": "exact", "vertragslaufzeit": "compound_head"})
        vertrag = rules(index.resolve("vertrag"))
        self.assertEqual(vertrag["vertragslaufzeit"], "compound_modifier")
        # "sonder" is no word of the corpus, so "Sondervertrag" is not taken apart.
        self.assertNotIn("sondervertrag", vertrag)

    def test_er_and_ens_are_no_linking_elements(self) -> None:
        index = resolver("zahl", "stand", "zahlerstand")
        self.assertEqual(index.part_position("zahlerstand", "zahl"), "")
        self.assertNotIn("zahlerstand", rules(index.resolve("zahl")))
        index = resolver("herz", "wunsch", "herzenswunsch")
        self.assertEqual(index.part_position("herzenswunsch", "herz"), "")
        self.assertNotIn("herzenswunsch", rules(index.resolve("herz")))

    def test_an_endless_run_of_letters_is_never_taken_apart(self) -> None:
        """A token beyond MAX_COMPOUND letters is no compound: no deep recursion, no quadratic time."""
        index = resolver("strom", "tarif", "stromtarif" * 600)
        self.assertEqual(index.resolve("strom" * 1100), [])
        self.assertEqual(index.query_head("strom" * 1100), "")
        self.assertNotIn("stromtarif" * 600, rules(index.resolve("tarif")))
        pages = {
            "wiki/concepts/tarif.md": page("Tarif", "Der Tarif gilt. " + "Stromtarif" * 600),
            "sources/lang.md": page("Lang", "Stromtarif" * 600),
        }
        with TempPages(pages) as root:
            for query in ("Tarif", "Strom" * 1100):
                for include_sources in (False, True):
                    with self.subTest(query=query[:12], include_sources=include_sources):
                        report = search_core.search(root, query, limit=5, include_sources=include_sources)
                        self.assertEqual(report["parser_errors"], [])

    def test_an_unknown_query_word_is_split_only_at_its_head(self) -> None:
        index = resolver("warmepumpe", "tarif", "tarife")
        found = rules(index.resolve("warmepumpentarif"))
        self.assertEqual(found, {"tarif": "query_part", "tarife": "query_part"})
        self.assertNotIn("warmepumpe", found, "the modifier never matches on its own")
        # Without real words on both sides, nothing is split.
        self.assertEqual(resolver("tarif").resolve("gastarif"), [])

    def test_compound_parts_need_a_minimum_length(self) -> None:
        index = resolver("gas", "gastarif", "tarif")
        self.assertNotIn("gastarif", rules(index.resolve("gas")))


class StepD_Typos(unittest.TestCase):
    def test_a_long_word_matching_nothing_else_is_corrected_by_one_edit(self) -> None:
        index = resolver("netzentgelt", "zahlerstand")
        self.assertEqual(rules(index.resolve("netzentgeld")), {"netzentgelt": "typo"})
        self.assertEqual(rules(index.resolve("zahlerstnad")), {"zahlerstand": "typo"}, "a swap is one edit")

    def test_r5_short_words_and_correct_words_absent_from_the_wiki_are_not_corrected(self) -> None:
        """Measured on the fixture: 0 of 8 real typos missed, 3 of 130 absent words of 8+ letters corrected."""
        index = resolver("start", "alter", "kundigen", "anmeldungen")
        for word in ("smart", "meter", "ankundigen"):
            with self.subTest(word=word):
                self.assertEqual(index.resolve(word), [])
        self.assertEqual(wordforms.MIN_TYPO_LENGTH, 8)
        self.assertEqual(resolver("netzentgelt").typos("netzentgeldd"), {}, "two edits are never corrected")

    def test_r5_a_typo_correction_is_only_a_last_resort(self) -> None:
        index = resolver("netzentgelte", "netzentgelt")
        self.assertEqual(rules(index.resolve("netzentgelten")), {"netzentgelt": "stem", "netzentgelte": "stem"})
        self.assertEqual(resolver("wiederholung", "uberweisung").resolve("uberweisung"), [("uberweisung", "exact", 1.0)])
        self.assertEqual(resolver("wieder").resolve("wider"), [], "never for short words")
        self.assertEqual(resolver("werdenn").resolve("werden"), [], "never for closed-class words")
        # A word with an exact match is never also corrected to a neighbour.
        self.assertEqual(resolver("anmeldung", "abmeldung").resolve("anmeldung"), [("anmeldung", "exact", 1.0)])

    def test_a_word_that_exists_in_an_unsearched_layer_is_no_typo(self) -> None:
        index = resolver("verfahren")
        self.assertEqual(rules(index.resolve("verjahren")), {"verfahren": "typo"})
        self.assertEqual(index.resolve("verjahren", typos=False), [])


class ConstructionRules(unittest.TestCase):
    def test_r1_heuristics_never_raise_a_terms_document_frequency(self) -> None:
        members = {
            "kunden": [("kunden", "exact", 1.0), ("haushaltskunden", "compound_head", wordforms.WEIGHTS["compound_head"])],
        }
        candidates = [{"words": {"kunden"}, "navigation": False}] + [
            {"words": {"haushaltskunden"}, "navigation": False} for _ in range(5)
        ]
        groups, _, _ = search_core.scoring_groups(["kunden"], members, candidates)
        self.assertEqual(groups[0].document_frequency, 1, "only the page with the literal token counts")
        # A term with no word form anywhere takes its rarity from its heuristic members.
        typo = {"netzentgeld": [("netzentgelt", "typo", wordforms.WEIGHTS["typo"])]}
        groups, _, _ = search_core.scoring_groups(["netzentgeld"], typo, [{"words": {"netzentgelt"}, "navigation": False}] * 3)
        self.assertEqual(groups[0].document_frequency, 3)

    def test_r1_a_navigation_page_counts_for_rarity_only_with_the_literal_token(self) -> None:
        members = {"tarif": [("tarif", "exact", 1.0), ("tarife", "stem", wordforms.WEIGHTS["stem"])]}
        candidates = [
            {"words": {"tarif"}, "navigation": False},
            {"words": {"tarife"}, "navigation": True},
            {"words": {"tarife"}, "navigation": False},
        ]
        content, navigation, _ = search_core.scoring_groups(["tarif"], members, candidates)
        self.assertEqual(content[0].document_frequency, 2, "the index holding only Tarife does not count")
        self.assertEqual(navigation[0].members, {"tarif": 1.0})

    def test_forms_of_one_word_share_one_scoring_group(self) -> None:
        members = {
            "tarif": [("tarif", "exact", 1.0), ("tarife", "stem", wordforms.WEIGHTS["stem"])],
            "tarife": [("tarife", "exact", 1.0), ("tarif", "stem", wordforms.WEIGHTS["stem"])],
        }
        candidates = [{"words": {"tarif"}, "navigation": False}, {"words": {"tarife"}, "navigation": False}]
        content, _, label_of = search_core.scoring_groups(["tarif", "tarife"], members, candidates)
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0].members, {"tarif": 1.0, "tarife": 1.0})
        self.assertEqual(label_of, {"tarif": "tarif", "tarife": "tarif"})

    def test_an_unsearched_layer_counts_only_the_word_and_its_word_forms(self) -> None:
        layer = [{"vertrage", "vertragslaufzeit", "laufzeit"}, {"netzentgelt"}]
        found = search_core.layer_members(["vertrag", "netzentgeld"], layer, True)
        self.assertEqual(found["vertrag"], frozenset({"vertrage"}), "no compound part")
        self.assertEqual(found["netzentgeld"], frozenset(), "no typo correction")

    def test_r2_a_compound_part_in_the_title_keeps_only_its_own_weight(self) -> None:
        corpus = bm25.Corpus([{"title": ["netzentgelt"]}, {"title": ["netzentgeltrechner"]}, {"title": ["anderes"]}])
        weight = wordforms.WEIGHTS["compound_modifier"]
        group = [bm25.TermGroup("netzentgelt", {"netzentgelt": 1.0, "netzentgeltrechner": weight}, 1)]
        exact = bm25.group_base_score(corpus, {"title": ["netzentgelt"]}, group)
        part = bm25.group_base_score(corpus, {"title": ["netzentgeltrechner"]}, group)
        self.assertGreater(exact, 0)
        self.assertAlmostEqual(part / exact, weight, places=9)
        # Weighting before saturation would have kept most of the exact score.
        self.assertLess(part / exact, 0.5)

    def test_r2_every_further_occurrence_only_adds(self) -> None:
        corpus = bm25.Corpus([{"body": ["tarif", "x"]}, {"body": ["tarife", "y"]}, {"body": ["z"]}])
        group = [bm25.TermGroup("tarif", {"tarif": 1.0, "tarife": wordforms.WEIGHTS["stem"]}, 2)]
        alone = bm25.group_base_score(corpus, {"body": ["tarif", "x", "x"]}, group)
        more = bm25.group_base_score(corpus, {"body": ["tarif", "x", "tarife"]}, group)
        self.assertGreater(more, alone)

    def test_r3_the_phrase_signal_needs_literal_words_on_token_boundaries(self) -> None:
        self.assertTrue(search_core.has_phrase("frist kundigung", "die frist kundigung gilt", forms=True))
        self.assertFalse(search_core.has_phrase("tarif", "der festpreistarif gilt", forms=True))
        self.assertFalse(search_core.has_phrase("tarif", "die tarife gelten", forms=True))
        self.assertFalse(search_core.has_phrase("frist kundigung", "die fristen kundigung", forms=True))
        # The literal search keeps its substring comparison.
        self.assertTrue(search_core.has_phrase("tarif", "der festpreistarif gilt"))

    def test_r4_link_targets_and_slugs_are_never_split_into_matching_parts(self) -> None:
        self.assertEqual(resolver("tarif-lindenstrom-fix12").resolve("tarif"), [])
        pages = {
            "wiki/concepts/basis.md": page("Grundlagen", "Siehe [[wiki/entities/tarif-lindenstrom|LindenStrom]] und [[wiki/entities/tarif-fix]]."),
            "wiki/entities/tarif.md": page("Tarif", "Der Tarif gilt ein Jahr."),
        }
        with TempPages(pages) as root:
            found = search_core.search(root, "Tarif", limit=10)
        self.assertEqual([item["path"] for item in found["results"]], ["wiki/entities/tarif.md"])

    def test_score_zero_stays_zero(self) -> None:
        corpus = bm25.Corpus([{"body": ["tarif"]}, {"body": ["anderes"]}])
        group = [bm25.TermGroup("tarif", {"tarif": 1.0, "tarife": 0.6}, 1)]
        self.assertEqual(
            bm25.score(corpus, {"body": ["anderes"]}, [], groups=group, phrase_match=True, concept_overlap=3), 0.0
        )

    def test_a_literal_only_group_scores_exactly_like_the_literal_search(self) -> None:
        documents = [
            {"title": ["netzentgelt"], "body": ["netzentgelt", "preis", "netzentgelt"]},
            {"title": ["preis"], "body": ["preis", "arbeitspreis"]},
            {"body": ["netzentgelt"]},
        ]
        corpus = bm25.Corpus(documents)
        for fields in documents:
            with self.subTest(fields=fields):
                literal = bm25.score(corpus, fields, ["netzentgelt", "preis"], status="active", phrase_match=True)
                grouped = bm25.score(
                    corpus,
                    fields,
                    [],
                    status="active",
                    phrase_match=True,
                    groups=[
                        bm25.TermGroup("netzentgelt", {"netzentgelt": 1.0}, corpus.document_frequency.get("netzentgelt", 0)),
                        bm25.TermGroup("preis", {"preis": 1.0}, corpus.document_frequency.get("preis", 0)),
                    ],
                )
                self.assertAlmostEqual(literal, grouped, places=12)


class ConceptTerms(unittest.TestCase):
    DEFINITIONS = {
        "grundversorgung": {"id": "grundversorgung", "status": "active", "terms": ["Grundversorgung", "Basisversorgung"]},
        "netzentgelt": {"id": "netzentgelt", "status": "active", "terms": ["Netzentgelt", "Arbeitspreis und Grundpreis"]},
    }

    def matched(self, query: str) -> list[str]:
        return search_core.expand_query(query, self.DEFINITIONS, forms=True)[1]

    def test_concept_terms_match_through_spelling_and_inflection(self) -> None:
        self.assertEqual(self.matched("Basisversorgung kündigen"), ["grundversorgung"])
        self.assertEqual(self.matched("Netzentgelten"), ["netzentgelt"])
        self.assertEqual(self.matched("Grundversorgungen"), ["grundversorgung"])
        self.assertEqual(self.matched("Arbeitspreise und Grundpreise"), ["netzentgelt"])

    def test_concept_terms_never_match_through_compound_parts_or_typos(self) -> None:
        self.assertEqual(self.matched("Grundversorung"), [], "a typo never triggers a concept")
        self.assertEqual(self.matched("Versorgung"), [], "a compound part never triggers a concept")
        self.assertEqual(self.matched("Grundversorgungstarif"), [])
        self.assertEqual(self.matched("Arbeitspreis oder Grundpreis"), [], "a closed-class word matches literally")

    def test_verb_forms_do_not_trigger_a_concept(self) -> None:
        """Only the word itself, its spelling (fold) and its inflection ending (stem) trigger a concept."""
        definitions = {
            "widerrufsrecht": {"id": "widerrufsrecht", "status": "active", "terms": ["Widerrufsrecht", "Widerruf"]},
        }
        self.assertEqual(search_core.expand_query("Widerrufe", definitions, forms=True)[1], ["widerrufsrecht"])
        self.assertEqual(search_core.expand_query("Wie widerruft man", definitions, forms=True)[1], [])
        self.assertFalse(wordforms.same_word("kundigt", "kundigen", search_core.CLOSED_CLASS))


class SearchBehaviour(unittest.TestCase):
    PAGES = {
        "wiki/concepts/tarif.md": page("Tarif", "Ein Tarif legt den Preis fest."),
        "wiki/concepts/wechsel.md": page("Wechsel", "Die Tarife wechseln jährlich."),
        "wiki/concepts/zaehler.md": page("Zähler", "Der Wärmepumpentarif braucht einen eigenen Zähler."),
        "wiki/concepts/netz.md": page("Netz", "Das Netzentgelt zahlt der Lieferant."),
        "wiki/concepts/index.md": page("Konzepte", "- [[wiki/concepts/tarif|Tarif]] und Tarife"),
        "wiki/topics/preisblatt-a.md": page("Preisblatt A", "Die Tarife gelten ab Januar."),
        "wiki/topics/preisblatt-b.md": page("Preisblatt B", "Die Tarif gelten ab Januar."),
    }

    def test_word_forms_find_a_page_the_literal_search_misses_and_say_how(self) -> None:
        with TempPages(self.PAGES) as root:
            literal = search_core.search(root, "Tarife", limit=10, word_forms=False)
            found = search_core.search(root, "Tarife", limit=10)
        self.assertNotIn("wiki/concepts/tarif.md", [item["path"] for item in literal["results"]])
        by_path = {item["path"]: item for item in found["results"]}
        self.assertIn("wiki/concepts/tarif.md", by_path)
        self.assertEqual(
            by_path["wiki/concepts/tarif.md"]["match_rules"],
            [{"term": "tarife", "token": "tarif", "rule": "stem", "weight": wordforms.WEIGHTS["stem"]}],
        )
        self.assertEqual(by_path["wiki/concepts/tarif.md"]["matched_terms"], ["tarife"])
        # The literal match ranks above the word form on an otherwise identical page.
        scores = {item["path"]: item["score"] for item in found["results"]}
        self.assertGreater(scores["wiki/topics/preisblatt-a.md"], scores["wiki/topics/preisblatt-b.md"])

    def test_navigation_pages_count_only_the_literal_token(self) -> None:
        with TempPages(self.PAGES) as root:
            found = search_core.search(root, "Tarifen", limit=10)
            literal_hit = search_core.search(root, "Tarife", limit=10)
        self.assertNotIn("wiki/concepts/index.md", [item["path"] for item in found["results"]])
        index = [item for item in literal_hit["results"] if item["path"] == "wiki/concepts/index.md"]
        self.assertEqual([rule["rule"] for rule in index[0]["match_rules"]], ["exact"])

    def test_on_a_navigation_page_only_a_terms_own_literal_token_is_reported(self) -> None:
        """A merged group may count a concept term's literal token on an index; the query word's
        stem relation to it is not what counted there."""
        definitions = "\n".join(
            ["# Concepts", "", "## tarif", "", "- preferred: Tarif", "- status: active", ""]
        )
        pages = {
            "schema/CONCEPTS.md": definitions,
            "wiki/concepts/index.md": page("Konzepte", "Der Tarif im Überblick."),
            "wiki/concepts/tarif.md": page("Tarif", "Ein Tarif legt den Preis fest."),
        }
        with TempPages(pages) as root:
            report = search_core.search(root, "Tarifen", limit=10)
        self.assertEqual(report["matched_concepts"], ["tarif"])
        index = {item["path"]: item for item in report["results"]}["wiki/concepts/index.md"]
        self.assertEqual(index["matched_terms"], ["tarif"])
        self.assertEqual(index["match_rules"], [{"term": "tarif", "token": "tarif", "rule": "exact", "weight": 1.0}])
        content = {item["path"]: item for item in report["results"]}["wiki/concepts/tarif.md"]
        self.assertEqual(content["matched_terms"], ["tarifen", "tarif"])

    def test_the_coverage_block_lists_forms_and_terms_carried_only_by_forms(self) -> None:
        with TempPages(self.PAGES) as root:
            report = search_core.search(root, "Netzentgeld Tarif Ladesäule", limit=10)
        coverage = report["coverage"]
        self.assertEqual(coverage["format"], "lmwiki-search-coverage/2")
        terms = {item["term"]: item for item in coverage["query_terms"]}
        self.assertEqual(terms["netzentgeld"]["forms"], [{"token": "netzentgelt", "rule": "typo", "weight": 0.3, "files": 1}])
        self.assertEqual(terms["netzentgeld"]["files"]["wiki"], 1)
        self.assertEqual(terms["tarif"]["forms"][0], {"token": "tarif", "rule": "exact", "weight": 1.0, "files": 3})
        self.assertEqual(coverage["form_only_terms"], ["netzentgeld"])
        self.assertEqual(coverage["unmatched_terms"], ["ladesaule"])
        netz = [item for item in report["results"] if item["path"] == "wiki/concepts/netz.md"][0]
        self.assertEqual(netz["match_rules"], [{"term": "netzentgeld", "token": "netzentgelt", "rule": "typo", "weight": 0.3}])
        self.assertEqual(coverage["boundary"], search_core.COVERAGE_BOUNDARY)
        self.assertIn("forms of the same word", coverage["boundary"])
        self.assertIn("compound and typo matches", coverage["boundary"])

    def test_a_word_only_in_unsearched_sources_is_reported_even_with_a_heuristic_match(self) -> None:
        """terms_only_in_unsearched counts the same word on both sides: a compound part or a typo
        neighbour in the wiki is not the word, so the reader is still sent to --include-sources."""
        pages = {
            "wiki/concepts/verfahren.md": page("Verfahren", "Das Verfahren ist lang. Die Lösung: Dauerlösung."),
            "wiki/concepts/forderung.md": page("Forderung", "Offene Forderungen werden gemahnt."),
            "sources/recht.md": page("Recht", "Forderungen verjähren nach drei Jahren. Die Dauer: drei Jahre."),
        }
        with TempPages(pages) as root:
            report = search_core.search(root, "Wann verjähren Forderungen Dauer", limit=10)
            with_sources = search_core.search(root, "Wann verjähren Forderungen Dauer", limit=10, include_sources=True)
        coverage = report["coverage"]
        self.assertEqual(coverage["terms_only_in_unsearched"], {"sources": ["verjahren", "dauer"]})
        # A word that exists in the release is never typo-corrected to "Verfahren".
        self.assertEqual(coverage["unmatched_terms"], ["wann", "verjahren"])
        terms = {item["term"]: item for item in coverage["query_terms"]}
        self.assertEqual(terms["verjahren"]["forms"], [])
        # "Dauer" still matches the compound in the wiki, disclosed as such.
        self.assertEqual(coverage["form_only_terms"], ["dauer"])
        self.assertEqual([form["rule"] for form in terms["dauer"]["forms"]], ["compound_modifier"])
        self.assertEqual(with_sources["coverage"]["terms_only_in_unsearched"], {"sources": []})
        self.assertIn("sources/recht.md", [item["path"] for item in with_sources["results"]])

    def test_a_form_found_only_on_a_navigation_page_leaves_the_term_unmatched(self) -> None:
        pages = {
            "wiki/concepts/index.md": page("Konzepte", "Alle Tarife im Überblick."),
            "wiki/concepts/netz.md": page("Netz", "Das Netzentgelt zahlt der Lieferant."),
        }
        with TempPages(pages) as root:
            report = search_core.search(root, "Tarif", limit=10)
        self.assertEqual(report["results"], [])
        self.assertEqual(report["coverage"]["unmatched_terms"], ["tarif"])
        self.assertEqual(report["coverage"]["form_only_terms"], [])
        # A form counts in no file when it stands only on a navigation page, so it is not listed.
        self.assertEqual(report["coverage"]["query_terms"][0]["forms"], [])
        self.assertEqual(report["coverage"]["query_terms"][0]["forms_total"], 0)

    def test_form_file_counts_follow_where_a_form_counts(self) -> None:
        pages = {
            "wiki/concepts/index.md": page("Konzepte", "Alle Tarife und der Tarif im Überblick."),
            "wiki/concepts/a.md": page("A", "Die Tarife gelten."),
            "wiki/concepts/b.md": page("B", "Der Tarif gilt."),
        }
        with TempPages(pages) as root:
            report = search_core.search(root, "Tarif", limit=10)
        term = report["coverage"]["query_terms"][0]
        self.assertEqual(term["forms"], [
            {"token": "tarif", "rule": "exact", "weight": 1.0, "files": 2},
            {"token": "tarife", "rule": "stem", "weight": 0.6, "files": 1},
        ])
        self.assertEqual(term["files"]["wiki"], 3)

    def test_forms_are_bounded_per_term(self) -> None:
        words = " ".join(f"Tarif{suffix}" for suffix in ("e", "en", "es", "s"))
        compounds = " ".join(f"{prefix}tarif" for prefix in ("Strom", "Gas", "Wasser", "Fest", "Grund", "Spar", "Nacht", "Haus"))
        pages = {"wiki/a.md": page("A", f"{words} {compounds} Strom Wasser Fest Grund Spar Nacht Haus Tarif")}
        with TempPages(pages) as root:
            report = search_core.search(root, "Tarif", limit=10)
        term = report["coverage"]["query_terms"][0]
        self.assertEqual(len(term["forms"]), search_core.FORMS_LISTED)
        self.assertGreater(term["forms_total"], search_core.FORMS_LISTED)

    def test_a_selector_does_not_change_what_a_word_matches(self) -> None:
        selector = {"kind": "paths", "paths": ["wiki/concepts/netz.md"]}
        with TempPages(self.PAGES) as root:
            narrowed = search_core.search(root, "Netzentgeld Tarif", limit=10, selector=selector)
            everything = search_core.search(root, "Netzentgeld Tarif", limit=10)
        self.assertEqual(narrowed["coverage"]["query_terms"], everything["coverage"]["query_terms"])
        self.assertEqual([item["path"] for item in narrowed["results"]], ["wiki/concepts/netz.md"])

    def test_results_do_not_depend_on_the_hash_seed(self) -> None:
        script = (
            "import json, sys\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            "import search_core\n"
            "from pathlib import Path\n"
            "report = search_core.search(Path(sys.argv[1]), sys.argv[2], limit=20)\n"
            "print(json.dumps(report, sort_keys=True))\n"
        )
        with TempPages(self.PAGES) as root:
            outputs = set()
            for seed in ("0", "1", "4242"):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", script, str(root), "Tarife Netzentgeld Wärmepumpe Zählers"],
                    capture_output=True,
                    encoding="utf-8",
                    env={**os.environ, "PYTHONHASHSEED": seed},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.add(result.stdout)
        self.assertEqual(len(outputs), 1)
        self.assertTrue(json.loads(outputs.pop())["results"])


class ExpansionRuleNotice(unittest.TestCase):
    """Owner decision E1: CONCEPTS.md states the reworded rule; an old wiki gets a notice."""

    OLD = "Search may expand a query only through confirmed preferred terms and aliases."
    NEW = (
        "Search expands a query in meaning only through confirmed preferred terms and aliases. Forms of the same "
        "word (inflection, umlaut spelling, hyphenation) count as matches of that word. Compound parts and "
        "one-letter typo corrections are disclosed heuristics. Reformulations by the agent are listed in the answer."
    )

    @staticmethod
    def notices(report: dict) -> list[str]:
        return [message for message in report["warnings"] if "expansion rule" in message]

    def test_a_new_wiki_states_the_new_rule_and_an_old_one_gets_a_notice_only(self) -> None:
        from harness import TempWiki

        with TempWiki() as wiki:
            concepts = wiki.read("schema/CONCEPTS.md")
            self.assertIn(self.NEW, " ".join(concepts.split()))
            self.assertNotIn(self.OLD, " ".join(concepts.split()))
            fresh = wiki.lint()
            fresh_report = json.loads(fresh.stdout)
            self.assertEqual(self.notices(fresh_report), [])

            # The old template wrapped the sentence across two lines.
            wrapped = concepts.replace(
                "Search expands a query in meaning only through\nconfirmed preferred terms and aliases.",
                "Search may expand a query only through confirmed\npreferred terms and aliases.",
            )
            self.assertNotEqual(wrapped, concepts)
            wiki.write("schema/CONCEPTS.md", wrapped)
            old = wiki.lint()
            old_report = json.loads(old.stdout)
            notices = self.notices(old_report)
            self.assertEqual(len(notices), 1)
            self.assertIn(self.NEW, notices[0])
            # A notice, not an error: validity and exit code are unchanged.
            self.assertEqual(old.returncode, fresh.returncode)
            self.assertEqual(old_report["valid"], fresh_report["valid"])
            self.assertEqual(old_report["errors"], fresh_report["errors"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
