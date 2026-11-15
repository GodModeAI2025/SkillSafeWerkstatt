#!/usr/bin/env python3
"""Locator resolution and source coverage (Stufe 5, package A).

`source_coverage.py` is a maintenance-only, pure library. Lint resolves every
claim locator of a canonical form (`page=`, `slide=`, `section=`, `heading=`,
`sheet=`, `timestamp=`, `document`) against the registered extraction and
warns when one does not resolve; an unknown source ID stays an error. Which
registered sources and which of their pages, slides or sections no active or
disputed claim points to is a statistic, `stats.source_coverage`: never a
warning, never an error, never part of meta/quality-status.json, never a
release blocker. The same line-anchored marker drives the reading-view anchors
and the preflight.
"""

from __future__ import annotations

import contextlib
import io
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import build_graph  # noqa: E402
import lint_wiki  # noqa: E402
import search_core  # noqa: E402
import source_coverage as sc  # noqa: E402
import validate_extraction  # noqa: E402
from harness import TempWiki, Wiki  # noqa: E402
from test_lifecycle import SOURCE_MARKDOWN, add_cluster_and_concept  # noqa: E402


def wrapped(text: str, first_line: int = 20) -> sc.Structure:
    """The structure of an extraction as register_source.py stores it, below its two wrapper headings."""
    return sc.source_structure("# Titel der Quelle\n\n## Extracted content\n\n" + text, first_line)


def resolve(locator: str, structure: sc.Structure) -> sc.Resolution:
    return sc.resolve(sc.parse_locator(locator), structure)


def source(source_id: str, structure: Optional[sc.Structure], status: str = "active", path: str = "") -> dict[str, Any]:
    return {
        "source_id": source_id,
        "path": path or f"sources/{source_id}-quelle.md",
        "title": f"Quelle {source_id}",
        "status": status,
        "structure": structure,
    }


def citation(source_id: str, locator: str, structure: sc.Structure, claim: str = "clm-0", status: str = "active",
             page: str = "wiki/topics/a.md") -> dict[str, Any]:
    return {
        "page": page,
        "page_display": page,
        "claim_id": claim,
        "claim_status": status,
        "source_id": source_id,
        "entry": f"{source_id}@{locator}",
        "resolution": resolve(locator, structure),
    }


PAGED = wrapped(
    "Titelblatt der Broschüre\n<!-- page: 1 -->\nA\n<!-- page: 2 -->\nB\n<!-- page: 3 -->\nC\n<!-- page: 4 -->\nD\n"
)


class Structure(unittest.TestCase):
    def test_the_registration_wrapper_is_not_part_of_the_extraction(self) -> None:
        structure = wrapped("## Abschnitt\nText.\n")
        self.assertEqual([item.text for item in structure.headings], ["Abschnitt"])
        self.assertEqual(
            resolve("section=Extracted content", structure).reason,
            "no heading of the extraction matches 'Extracted content'",
        )
        self.assertEqual(resolve("section=Titel der Quelle", structure).state, "unresolved")
        own = sc.source_structure("# Eigener Titel\nVorwort.\n## Teil\nText.\n## Rest\nMehr.\n")
        self.assertEqual([item.text for item in own.headings], ["Eigener Titel", "Teil", "Rest"])
        # The title spans every other section: its own text is no unit (see the next test).
        self.assertEqual(own.units, ("section=Teil", "section=Rest"))
        # Only the exact pair is the wrapper: an H1 followed by another heading stays.
        other = sc.source_structure("# Eigener Titel\n## Inhalt\nText.\n")
        self.assertEqual([item.text for item in other.headings], ["Eigener Titel", "Inhalt"])

    def test_page_markers_make_page_units_and_unnameable_text_does_not_count(self) -> None:
        structure = wrapped(
            "Titelblatt\n<!-- page: 1 -->\nA\n<!-- page: 2 -->\n## Nur eine Überschrift\n"
            "<!-- PAGE: 3 -->\nC\n<!--page:1-->\nNoch mehr von Seite 1\n"
        )
        self.assertEqual(structure.unit_kind, "page")
        self.assertEqual(structure.units, ("page=1", "page=3"))
        self.assertEqual(structure.markers, (("page", "1"), ("page", "2"), ("page", "3")))
        self.assertEqual(PAGED.units, ("page=1", "page=2", "page=3", "page=4"))

    def test_slide_markers_make_slide_units(self) -> None:
        structure = wrapped("<!-- slide: 1 -->\nAgenda\n<!-- slide: 2 -->\nPreise\n")
        self.assertEqual(structure.unit_kind, "slide")
        self.assertEqual(structure.units, ("slide=1", "slide=2"))
        self.assertEqual(resolve("slide=2", structure).units, frozenset({"slide=2"}))

    def test_headings_make_section_units_without_markers(self) -> None:
        structure = wrapped(
            "Vorspann ohne Überschrift\n# Teil\n## A\ntext a\n### A1\ntext a1\n## B\ntext b\n## A\nnoch einmal\n",
            first_line=20,
        )
        # Lines 20-23 are the wrapper and a blank line; the extraction starts at line 24.
        self.assertEqual(structure.unit_kind, "section")
        self.assertEqual(structure.units, ("section=A (line 26)", "section=A1", "section=B", "section=A (line 32)"))
        self.assertEqual([(item.text, item.line, item.level) for item in structure.headings],
                         [("Teil", 25, 1), ("A", 26, 2), ("A1", 28, 3), ("B", 30, 2), ("A", 32, 2)])
        # The parent without text of its own is no unit, but it spans its subsections.
        self.assertEqual(structure.heading_units[0], frozenset(structure.units))
        self.assertEqual(structure.heading_units[1], frozenset({"section=A (line 26)", "section=A1"}))

    def test_the_own_text_of_a_title_spanning_every_section_is_no_unit(self) -> None:
        # Only section=<title> or document could name the title's own text, and both are
        # broad on a source with several sections, so it could never count as cited.
        note = wrapped("# Handbuch Abrechnung\nVorwort [00:00:05].\n## Kapitel A\na\n### A.1 Details\nmehr\n## Kapitel B\nb\n")
        self.assertEqual(note.units, ("section=Kapitel A", "section=A.1 Details", "section=Kapitel B"))
        self.assertEqual(resolve("section=Handbuch Abrechnung", note).units, frozenset(note.units))
        # Its time stamps still resolve; such a locator credits nothing.
        self.assertEqual(resolve("timestamp=00:00:05", note), sc.Resolution("resolved", frozenset(), "", ""))
        citations = [citation("src-a", locator, note, f"clm-{index}")
                     for index, locator in enumerate(("section=Handbuch Abrechnung", "document", "section=Kapitel A"))]
        stats = sc.coverage_stats([source("src-a", note)], citations)
        self.assertEqual(stats["by_source"], {"src-a": [3, 2, 3, 2, 0]})
        self.assertEqual(stats["sources"][0]["uncited_units"], ["section=Kapitel B"])
        # A chain of single chapters gives up each spanning level in turn.
        chain = wrapped("# Titel\nVorwort\n## Teil\nEinleitung\n### Eins\na\n### Zwei\nb\n")
        self.assertEqual(chain.units, ("section=Eins", "section=Zwei"))
        # A title beside other top-level sections, or alone, keeps its unit.
        beside = wrapped("# Titel\nVorwort\n## A\na\n# Anhang\nx\n")
        self.assertEqual(beside.units, ("section=Titel", "section=A", "section=Anhang"))
        self.assertEqual(wrapped("# Titel\nNur Vorwort\n").units, ("section=Titel",))
        single = wrapped("# Titel\nVorwort\n## Einzig\nText\n")
        self.assertEqual(single.units, ("section=Einzig",))
        self.assertEqual(resolve("section=Titel", single).units, frozenset({"section=Einzig"}))
        # Pages are units of their own; a title on a paged source changes nothing.
        self.assertEqual(wrapped("# Titel\n<!-- page: 1 -->\nA\n## B\n<!-- page: 2 -->\nC\n").units, ("page=1", "page=2"))

    def test_a_source_without_markers_or_headings_is_one_document_unit(self) -> None:
        structure = wrapped("Nur ein Absatz.\n\nUnd ein zweiter.\n")
        self.assertEqual((structure.unit_kind, structure.units), ("document", ("document",)))
        empty = wrapped("\n\n")
        self.assertEqual((empty.unit_kind, empty.units), ("empty", ()))
        self.assertEqual(sc.source_structure("").unit_kind, "empty")

    def test_fenced_code_hides_markers_and_headings_but_counts_as_text(self) -> None:
        structure = wrapped("```markdown\n<!-- page: 1 -->\n# Kopf\n```\n")
        self.assertEqual((structure.unit_kind, structure.markers, structure.headings), ("document", (), ()))
        paged = wrapped("<!-- page: 1 -->\nText\n<!-- page: 2 -->\n```\n```\n")
        self.assertEqual(paged.units, ("page=1", "page=2"))
        # The fence rule is the scan's: tildes fence too, after at most three spaces.
        body = "<!-- page: 1 -->\n\nErste Seite.\n\n~~~\n<!-- page: 2 -->\n# Kommentar im Code\n~~~\n\nNoch Seite eins.\n"
        tilde = sc.source_structure(body)
        self.assertEqual((tilde.units, tilde.markers, tilde.headings), (("page=1",), (("page", "1"),), ()))
        document = search_core.read_document(Path("sources/a.md"), "sources/a.md", body)
        passages = search_core.scan_passages("sources/a.md", body, document)
        self.assertEqual({passage.locator for passage in passages} - {""}, {"page=1"})
        self.assertEqual(resolve("page=2", tilde).state, "unresolved")
        indented = sc.source_structure("<!-- page: 1 -->\nA\n    ```\n<!-- page: 2 -->\nB\n")
        self.assertEqual(indented.units, ("page=1", "page=2"))

    def test_inline_markers_are_not_markers(self) -> None:
        structure = wrapped("Text <!-- page: 1 --> mehr\nund <!-- slide: 2 -->\n")
        self.assertEqual((structure.unit_kind, structure.markers), ("document", ()))
        self.assertTrue(sc.ANY_MARKER.search("Text <!-- page: 1 --> mehr"))
        self.assertIsNone(sc.PAGE_MARKER.match("Text <!-- page: 1 --> mehr"))
        self.assertEqual(sc.PAGE_MARKER.match("<!-- Slide : iv -->").groups(), ("Slide", "iv"))


class Locators(unittest.TestCase):
    def test_canonical_locators_parse_and_others_stay_unchecked(self) -> None:
        table = {
            "page=3": ("page", "page", "3", 3, 3),
            "Page = 3": ("page", "page", "3", 3, 3),
            "page=3-5": ("page", "page", "3-5", 3, 5),
            "page=3–5": ("page", "page", "3–5", 3, 5),
            "page=3 — 5": ("page", "page", "3 — 5", 3, 5),
            "page=iv": ("page", "page", "iv", None, None),
            "slide=2": ("slide", "slide", "2", 2, 2),
            "section=4.1 Berechnung": ("section", "section", "4.1 Berechnung", None, None),
            "heading=Preise": ("section", "heading", "Preise", None, None),
            "sheet=Tarife 2026": ("section", "sheet", "Tarife 2026", None, None),
            "timestamp=00:12:30": ("timestamp", "timestamp", "00:12:30", None, None),
            "document": ("document", "document", "", None, None),
            " Document ": ("document", "document", "", None, None),
            "S. 12": ("unchecked", "", "S. 12", None, None),
            "p. 4": ("unchecked", "", "p. 4", None, None),
            "paragraph=4": ("unchecked", "", "paragraph=4", None, None),
        }
        for raw, expected in table.items():
            with self.subTest(locator=raw):
                self.assertEqual(tuple(sc.parse_locator(raw)), expected)
        self.assertEqual(resolve("S. 12", PAGED), sc.Resolution("unchecked", frozenset(), "", ""))

    def test_page_and_slide_locators_resolve_against_markers(self) -> None:
        zeros = wrapped("<!-- page: 01 -->\nA\n<!-- page: 02 -->\nB\n<!-- page: 03 -->\nC\n")
        labelled = wrapped("<!-- page: iv -->\nVorwort\n<!-- page: A-1 -->\nAnhang\n")
        resolved = {
            ("page=2", PAGED): {"page=2"},
            ("page=03", PAGED): {"page=3"},
            ("page=3", zeros): {"page=03"},
            ("page=2-3", PAGED): {"page=2", "page=3"},
            ("page=2–4", PAGED): {"page=2", "page=3", "page=4"},
            ("page=IV", labelled): {"page=iv"},
            ("page=a-1", labelled): {"page=A-1"},
        }
        for (locator, structure), units in resolved.items():
            with self.subTest(locator=locator):
                self.assertEqual(resolve(locator, structure), sc.Resolution("resolved", frozenset(units), "", ""))
        reasons = {
            "page=7": "the extraction marks pages 1-4",
            "page=3-2": "the range 3-2 is reversed; write page=2-3",
            "page=3-9": "the extraction marks pages 1-4",
            "page=1,2": "write one entry per page, or a range such as page=3-5",
            "page=3 (Tabelle 2)": "'3 (Tabelle 2)' is not a page marker value; write page=3 and keep further detail in the claim text",
            "page=v": "the extraction marks pages 1-4",
            "page=": "the locator names no page",
        }
        for locator, reason in reasons.items():
            with self.subTest(locator=locator):
                self.assertEqual(resolve(locator, PAGED), sc.Resolution("unresolved", frozenset(), reason, ""))
        self.assertEqual(resolve("page=v", labelled).reason, "the extraction marks pages iv, A-1")
        many = wrapped("".join(f"<!-- page: {number} -->\nSeite {number}\n" for number in range(1, 40, 2)))
        self.assertEqual(
            resolve("page=2", many).reason,
            "the extraction marks pages 1, 3, 5, 7, 9, 11, 13, 15, 17, 19 and 10 more",
        )
        sections = wrapped("## A\nText\n")
        self.assertEqual(resolve("page=1", sections),
                         sc.Resolution("unresolved", frozenset(), "the extraction has no page markers", "page"))
        self.assertEqual(resolve("slide=1", PAGED),
                         sc.Resolution("unresolved", frozenset(), "the extraction has no slide markers", "slide"))

    def test_section_locators_match_folded_headings(self) -> None:
        numbered = wrapped(
            "## § 3 Preise\nx\n## 4 Abrechnung\ny\n### 4.1 Berechnung des Abschlags\nz\n## 10 Schluss\nw\n"
            "## 1 Anspruch\na\n### 1.2 X\nb\n## **Zähler-Wechsel**:\nc\n## Teil 1\nt1\n## Teil 2\nt2\n"
            "## 5.1 Fristen\nf\n## 6.1 Fristen\ng\n"
        )
        cases = {
            "section=§3 Preise": {"section=§ 3 Preise"},
            "section=§3": {"section=§ 3 Preise"},
            "section=zahler-wechsel": {"section=**Zähler-Wechsel**:"},
            "heading=ZÄHLER-WECHSEL.": {"section=**Zähler-Wechsel**:"},
            "section=  4   Abrechnung": {"section=4 Abrechnung", "section=4.1 Berechnung des Abschlags"},
            "section=4": {"section=4 Abrechnung", "section=4.1 Berechnung des Abschlags"},
            "section=Berechnung des Abschlags": {"section=4.1 Berechnung des Abschlags"},
            "section=Preise": {"section=§ 3 Preise"},
            "section=1": {"section=1 Anspruch", "section=1.2 X"},
            "section=`Teil 2`": {"section=Teil 2"},
        }
        for locator, units in cases.items():
            with self.subTest(locator=locator):
                self.assertEqual(resolve(locator, numbered), sc.Resolution("resolved", frozenset(units), "", ""))
        reasons = {
            "section=Fristen": "2 headings match 'Fristen'; cite the full heading with its number",
            "section=Teil": "2 headings begin with 'Teil'; cite the full heading",
            "section=Nichts": "no heading of the extraction matches 'Nichts'",
            "section=**": "the locator names no section",
            "heading=": "the locator names no heading",
        }
        for locator, reason in reasons.items():
            with self.subTest(locator=locator):
                self.assertEqual(resolve(locator, numbered), sc.Resolution("unresolved", frozenset(), reason, ""))
        # An exact match wins over prefixes.
        exact = wrapped("## Teil\nx\n## Teil 1\ny\n## Teil 2\nz\n")
        self.assertEqual(resolve("section=Teil", exact).units, frozenset({"section=Teil"}))
        # On a paged source a section covers the pages it spans.
        paged = wrapped("# Leitfaden\n<!-- page: 1 -->\n## A\ntext\n<!-- page: 2 -->\nmehr A\n## B\ntext b\n"
                        "<!-- page: 3 -->\n## C\nc\n")
        self.assertEqual(resolve("section=A", paged).units, frozenset({"page=1", "page=2"}))
        self.assertEqual(resolve("section=B", paged).units, frozenset({"page=2"}))
        self.assertEqual(resolve("section=Leitfaden", paged).units, frozenset(paged.units))

    def test_timestamp_locators_need_a_whole_time_stamp(self) -> None:
        transcript = wrapped("## Protokoll\n[00:11:00] Begrüßung\n[00:21:00] Preise\n## Fragen\n[00:30:15] Fragen\n")
        self.assertEqual(resolve("timestamp=1:00", transcript).reason,
                         "the extraction does not contain the time stamp '1:00'")
        self.assertEqual(resolve("timestamp=[00:30:15]", transcript).units, frozenset({"section=Fragen"}))
        self.assertEqual(resolve("timestamp=00:21:00", transcript).units, frozenset({"section=Protokoll"}))
        self.assertEqual(resolve("timestamp=Minute 3", transcript).reason,
                         "'Minute 3' is not a time stamp such as 00:12:30 or 12:30")
        # A time stamp in a heading belongs to that heading's section.
        headed = wrapped("## [00:00:05] Begrüßung\nHallo.\n## 00:12:30 Preise\nPreise.\n[00:20:00] B: Danke.\n"
                         "## 00:40:00 Pause\n## 00:45:00 Fragen\nFragen.\n")
        self.assertEqual(resolve("timestamp=00:00:05", headed).units, frozenset({"section=[00:00:05] Begrüßung"}))
        self.assertEqual(resolve("timestamp=00:12:30", headed).units, frozenset({"section=00:12:30 Preise"}))
        self.assertEqual(resolve("timestamp=[00:20:00]", headed).units, frozenset({"section=00:12:30 Preise"}))
        # A stamped heading without text of its own resolves and credits nothing.
        self.assertEqual(resolve("timestamp=00:40:00", headed), sc.Resolution("resolved", frozenset(), "", ""))
        # So does a stamp before the first marker.
        paged = wrapped("Deckblatt, Stand 09:30\n<!-- page: 1 -->\nA\n<!-- page: 2 -->\nB 10:15\n")
        self.assertEqual(resolve("timestamp=09:30", paged), sc.Resolution("resolved", frozenset(), "", ""))
        self.assertEqual(resolve("timestamp=10:15", paged).units, frozenset({"page=2"}))

    def test_document_resolves_always(self) -> None:
        self.assertEqual(resolve("document", PAGED), sc.Resolution("resolved", frozenset(PAGED.units), "", ""))
        self.assertEqual(resolve("document", wrapped("")), sc.Resolution("resolved", frozenset(), "", ""))


class Statistic(unittest.TestCase):
    def test_a_locator_naming_the_whole_source_credits_nothing(self) -> None:
        three = wrapped("# Leitfaden\n<!-- page: 1 -->\nA\n<!-- page: 2 -->\nB\n<!-- page: 3 -->\nC\n")
        citations = [citation("src-a", locator, three, f"clm-{index}") for index, locator in
                     enumerate(("document", "section=Leitfaden", "page=1-3"))]
        stats = sc.coverage_stats([source("src-a", three)], citations)
        self.assertEqual(stats["by_source"], {"src-a": [3, 0, 3, 3, 0]})
        self.assertEqual((stats["units_cited"], stats["broad_citations"]), (0, 3))
        self.assertEqual(stats["sources"][0]["uncited_units"], ["page=1-3"])
        for structure in (wrapped("Nur Text."), wrapped("<!-- page: 1 -->\nEine Seite\n"), wrapped("## Einzig\nText\n")):
            with self.subTest(units=structure.units):
                one = sc.coverage_stats([source("src-b", structure)], [citation("src-b", "document", structure)])
                self.assertEqual(one["by_source"], {"src-b": [1, 1, 1, 0, 0]})
                self.assertEqual(one["sources"], [])

    def test_markers_with_digits_int_refuses_are_values_as_written(self) -> None:
        # "²" and "①" pass str.isdigit() but not int(): they are compared as written.
        structure = wrapped("<!-- page: 1 -->\nA\n<!-- page: ² -->\nB\n<!-- page: 3 -->\nC\n<!-- page: ① -->\nD\n"
                            "<!-- page: ３ -->\nE\n")
        self.assertEqual(structure.units, ("page=1", "page=²", "page=3", "page=①", "page=３"))
        self.assertEqual(resolve("page=9", structure).reason, "the extraction marks pages 1, ², 3, ①, ３")
        self.assertEqual(resolve("page=²", structure).units, frozenset({"page=²"}))
        # Decimal digits of any script compare as integers.
        self.assertEqual(resolve("page=3", structure).units, frozenset({"page=3", "page=３"}))
        stats = sc.coverage_stats([source("src-a", structure)], [citation("src-a", "page=1", structure)])
        self.assertEqual(stats["sources"][0]["uncited_units"], ["page=²", "page=3", "page=①", "page=３"])
        self.assertEqual(sc.compress(["1", "²", "3", "４"]), ["1", "²", "3-４"])

    def test_unit_labels_compress_consecutive_pages(self) -> None:
        self.assertEqual(sc.compress(["1", "2", "3", "5", "iv", "7", "8"]), ["1-3", "5", "iv", "7-8"])
        structure = wrapped("".join(f"<!-- page: {value} -->\nText\n" for value in ("1", "2", "3", "5", "iv", "7", "8")))
        stats = sc.coverage_stats([source("src-a", structure)], [])
        self.assertEqual(stats["sources"][0]["uncited_units"], ["page=1-3", "page=5", "page=iv", "page=7-8"])
        self.assertEqual(stats["sources"][0]["uncited_units_omitted"], 0)

    def test_coverage_counts_only_active_and_disputed_claims(self) -> None:
        citations = [
            citation("src-a", "page=1", PAGED, "clm-1", "active"),
            citation("src-a", "page=2", PAGED, "clm-2", "disputed"),
            citation("src-a", "page=3", PAGED, "clm-3", "superseded"),
            citation("src-a", "page=4", PAGED, "clm-4", "unsupported"),
            citation("src-a", "page=9", PAGED, "clm-5", "superseded"),
        ]
        stats = sc.coverage_stats([source("src-a", PAGED)], citations)
        self.assertEqual(stats["by_source"], {"src-a": [4, 2, 2, 0, 0]})
        self.assertEqual(stats["sources"][0]["uncited_units"], ["page=3-4"])
        # Resolution counts every entry, whatever its claim's status.
        self.assertEqual(stats["locators"], {"resolved": 4, "unresolved": 1, "unchecked": 0})

    def test_only_active_and_partial_sources_are_assessed(self) -> None:
        sources = [source("src-a", PAGED, "active"), source("src-b", PAGED, "partial"),
                   source("src-c", PAGED, "superseded"), source("src-d", PAGED, "withdrawn"),
                   source("src-e", None, "")]
        stats = sc.coverage_stats(sources, [citation("src-c", "page=1", PAGED)])
        self.assertEqual((stats["sources_assessed"], stats["sources_not_assessed"]), (2, 3))
        self.assertEqual((stats["sources_uncited"], stats["units_total"]), (2, 8))
        self.assertEqual([entry["source_id"] for entry in stats["sources"]], ["src-a", "src-b"])
        self.assertEqual(stats["by_source"], {})
        self.assertEqual(stats["locators"]["resolved"], 1)

    def test_by_source_lists_every_cited_source_and_no_uncited_one(self) -> None:
        sources = [source(f"src-u{index:02d}", PAGED) for index in range(60)]
        sources.append(source("src-zz", PAGED, path="sources/zz.md"))
        stats = sc.coverage_stats(sources, [citation("src-zz", "page=2", PAGED)])
        self.assertEqual(stats["by_source"], {"src-zz": [4, 1, 1, 0, 0]})
        self.assertEqual(stats["sources_uncited"], 60)
        # The capped display list hides the partly cited source; the map does not.
        self.assertEqual(len(stats["sources"]), 50)
        self.assertEqual(stats["sources_omitted"], 11)
        self.assertNotIn("src-zz", [entry["source_id"] for entry in stats["sources"]])

    def test_the_display_list_puts_uncited_sources_first_and_caps_its_lists(self) -> None:
        long = wrapped("".join(f"<!-- page: {number} -->\nText\n" for number in range(1, 46)))
        cited = [citation("src-a", f"page={number}", long, f"clm-{number}") for number in range(2, 46, 2)]
        sources = [source("src-a", long, path="sources/a.md"), source("src-b", PAGED, path="sources/b.md")]
        stats = sc.coverage_stats(sources, cited)
        self.assertEqual([entry["source_id"] for entry in stats["sources"]], ["src-b", "src-a"])
        entry = stats["sources"][1]
        self.assertEqual(len(entry["uncited_units"]), 20)
        self.assertEqual(entry["uncited_units"][:2], ["page=1", "page=3"])
        # units - cited_units = units the shown labels stand for + uncited_units_omitted
        self.assertEqual((entry["units"], entry["cited_units"], entry["uncited_units_omitted"]), (45, 22, 3))
        self.assertEqual(entry["units"] - entry["cited_units"], len(entry["uncited_units"]) + entry["uncited_units_omitted"])
        ranged = wrapped("".join(f"<!-- page: {number} -->\nText\n" for number in range(1, 10)))
        stats = sc.coverage_stats([source("src-r", ranged)], [citation("src-r", "page=5", ranged)])
        entry = stats["sources"][0]
        self.assertEqual(entry["uncited_units"], ["page=1-4", "page=6-9"])
        self.assertEqual(entry["units"] - entry["cited_units"], 8)
        self.assertEqual(entry["uncited_units_omitted"], 0)

    def test_the_statistic_does_not_depend_on_input_order(self) -> None:
        unmarked = wrapped("## A\nText\n")
        structures = {"src-a": PAGED, "src-b": unmarked, "src-c": PAGED}
        sources = [source(source_id, structure) for source_id, structure in structures.items()]
        citations = [
            citation("src-a", "page=1", PAGED, "clm-3", page="wiki/b.md"),
            citation("src-a", "S. 4", PAGED, "clm-2", page="wiki/a.md"),
            citation("src-a", "S. 2", PAGED, "clm-1", page="wiki/a.md"),
            citation("src-b", "page=1", unmarked, "clm-5"),
            citation("src-b", "page=2", unmarked, "clm-4"),
            citation("src-c", "document", PAGED, "clm-6", "disputed"),
        ]
        expected = sc.coverage_stats(sources, citations)
        self.assertEqual([entry["claim_id"] for entry in expected["unchecked_examples"]], ["clm-1", "clm-2"])
        self.assertEqual(expected["unresolved_without_markers"],
                         [{"source_id": "src-b", "path": "sources/src-b-quelle.md", "kind": "page", "claim_ids": ["clm-4", "clm-5"]}])
        shuffler = random.Random(5)
        for _ in range(20):
            shuffler.shuffle(sources)
            shuffler.shuffle(citations)
            self.assertEqual(json.dumps(sc.coverage_stats(sources, citations)), json.dumps(expected))


UNMARKED_SOURCE = """# Merkblatt Abschlag

## Abschlag

Der Abschlag wird monatlich gezahlt.

## Erstattung

Ein Guthaben wird erstattet.
"""


def page_text(slug: str, sources: list[tuple[str, str]], claims: list[tuple[str, str, str]]) -> str:
    """A content page citing `sources` (id, stem) with `claims` (id, status, source entries)."""
    listed = "\n".join(f'  - "[[sources/{stem}|Quelle]]"' for _, stem in sources)
    blocks = "\n\n".join(
        f"<!-- claim\nid: {claim_id}\nkind: fact\nstatus: {status}\nsources: {entries}\n-->\n"
        f"Aussage {number} über Netzentgelte.\n<!-- /claim -->"
        for number, (claim_id, status, entries) in enumerate(claims, 1)
    )
    return f"""---
id: "concept-{slug}"
title: "Netzentgelte {slug}"
type: "concept"
status: "active"
created: "2026-09-06"
updated: "2026-09-06"
description: "Netzentgelte."
language: "de"
sources:
{listed}
clusters:
  - "netz"
concepts:
  - "netzentgelt"
tags:
  - "type/wiki-concept"
---

# Netzentgelte {slug}

{blocks}
"""


class Curated:
    """A released wiki with the lifecycle source, a cluster, a concept and claim ids ready."""

    def __init__(self, wiki: Wiki) -> None:
        self.wiki = wiki
        record = wiki.register_source(SOURCE_MARKDOWN, "Netzentgelte 2026", "intern/netzentgelte-2026.pdf")
        self.source_id = record["source_id"]
        self.stem = Path(record["path"]).stem
        self.source_path = record["path"]
        add_cluster_and_concept(wiki)
        self.ids = json.loads(wiki.locked("claim_id.py", "--count", "8").stdout)["claim_ids"]

    def register(self, markdown: str, title: str) -> tuple[str, str]:
        record = self.wiki.register_source(markdown, title, f"intern/{title.lower().replace(' ', '-')}.pdf")
        return record["source_id"], Path(record["path"]).stem

    def publish(self, slug: str, text: str, *, batch: bool = True) -> None:
        relative = f"wiki/concepts/{slug}.md"
        index = self.wiki.read("wiki/index.md")
        if f"[[wiki/concepts/{slug}|" not in index:
            self.wiki.write("wiki/index.md", index.rstrip() + f"\n\n- [[wiki/concepts/{slug}|{slug}]]\n")
        if batch:
            self.wiki.apply_pages({relative: text})
        else:
            self.wiki.write(relative, text)
        self.wiki.rebuild()


def lint_report(wiki: Wiki) -> dict[str, Any]:
    return json.loads(wiki.lint().stdout)


class LintPlumbing(unittest.TestCase):
    def test_lint_warns_on_each_unresolved_locator_and_stays_valid(self) -> None:
        with TempWiki() as wiki:
            curated = Curated(wiki)
            claims = [(curated.ids[0], "active", f"{curated.source_id}@page=2"),
                      (curated.ids[1], "active", f"{curated.source_id}@page=7"),
                      (curated.ids[2], "superseded", f"{curated.source_id}@section=Preise")]
            curated.publish("netzentgelte", page_text("netzentgelte", [(curated.source_id, curated.stem)], claims))
            report = lint_report(wiki)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["errors"], [])
            unresolved = [warning for warning in report["warnings"] if "does not resolve" in warning]
            self.assertEqual(unresolved, [
                f"./wiki/concepts/netzentgelte.md: claim {curated.ids[1]} locator {curated.source_id}@page=7 "
                f"does not resolve in {curated.source_path}: the extraction marks pages 1-2",
                f"./wiki/concepts/netzentgelte.md: claim {curated.ids[2]} locator {curated.source_id}@section=Preise "
                f"does not resolve in {curated.source_path}: no heading of the extraction matches 'Preise'",
            ])
            coverage = report["stats"]["source_coverage"]
            self.assertEqual(coverage["locators"], {"resolved": 1, "unresolved": 2, "unchecked": 0})
            self.assertEqual(coverage["by_source"], {curated.source_id: [2, 1, 2, 0, 0]})

    def test_locators_into_a_source_without_markers_are_one_stable_warning_per_source(self) -> None:
        with TempWiki() as wiki:
            curated = Curated(wiki)
            plain_id, plain_stem = curated.register(UNMARKED_SOURCE, "Merkblatt Abschlag")
            sources = [(curated.source_id, curated.stem), (plain_id, plain_stem)]
            first = [(curated.ids[0], "active", f"{curated.source_id}@page=1 | {plain_id}@page=1")]
            curated.publish("netzentgelte", page_text("netzentgelte", sources, first))
            expected = (
                f"./sources/{plain_stem}.md: every claim locator that cites a page does not resolve, because the "
                "extraction has no page markers; cite a heading with section=, or register an extraction with page "
                "markers (stats.source_coverage.unresolved_without_markers lists the claims)"
            )
            report = lint_report(wiki)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual([w for w in report["warnings"] if "does not resolve" in w], [expected])
            second = first + [(curated.ids[1], "active", f"{plain_id}@page=2 | {plain_id}@section=Erstattung")]
            curated.publish("netzentgelte", page_text("netzentgelte", sources, second))
            report = lint_report(wiki)
            self.assertEqual([w for w in report["warnings"] if "does not resolve" in w], [expected])
            coverage = report["stats"]["source_coverage"]
            self.assertEqual(coverage["unresolved_without_markers"], [{
                "source_id": plain_id, "path": f"sources/{plain_stem}.md", "kind": "page",
                "claim_ids": sorted(curated.ids[:2]),
            }])
            self.assertEqual(coverage["by_source"][plain_id], [2, 1, 3, 0, 0])

    def test_entries_with_errors_are_neither_resolved_nor_counted(self) -> None:
        with TempWiki() as wiki:
            curated = Curated(wiki)
            other_id, _ = curated.register(UNMARKED_SOURCE, "Merkblatt Abschlag")
            claims = [
                (curated.ids[0], "active", f"{curated.source_id}@page=2"),
                (curated.ids[1], "active", "src-0000000000000000@page=1"),
                (curated.ids[2], "active", f"{other_id}@section=Abschlag"),
            ]
            curated.publish("netzentgelte", page_text("netzentgelte", [(curated.source_id, curated.stem)], claims),
                            batch=False)
            report = lint_report(wiki)
            self.assertFalse(report["valid"])
            self.assertTrue(any("references unknown source src-0000000000000000" in e for e in report["errors"]))
            self.assertTrue(any(f"uses {other_id}, but page frontmatter does not cite it" in e for e in report["errors"]))
            coverage = report["stats"]["source_coverage"]
            self.assertEqual(coverage["locators"], {"resolved": 1, "unresolved": 0, "unchecked": 0})
            self.assertNotIn(other_id, coverage["by_source"])

    def test_an_uncited_source_is_a_statistic_not_a_warning(self) -> None:
        with TempWiki() as wiki:
            curated = Curated(wiki)
            claims = [(curated.ids[0], "active", f"{curated.source_id}@page=2")]
            curated.publish("netzentgelte", page_text("netzentgelte", [(curated.source_id, curated.stem)], claims))
            first = json.loads(wiki.release("coverage-1").stdout)
            first_lint = json.loads(wiki.read("meta/lint-report.json"))
            first_status = json.loads(wiki.read("meta/quality-status.json"))
            first_quality = wiki.query_json("assess_quality.py", "--target", str(wiki.path))
            curated.register(UNMARKED_SOURCE, "Merkblatt Abschlag")
            wiki.rebuild()
            second = json.loads(wiki.release("coverage-2").stdout)
            second_lint = json.loads(wiki.read("meta/lint-report.json"))
            second_status = json.loads(wiki.read("meta/quality-status.json"))
            second_quality = wiki.query_json("assess_quality.py", "--target", str(wiki.path))
            self.assertEqual(
                second["stats"]["source_coverage"]["sources_uncited"],
                first["stats"]["source_coverage"]["sources_uncited"] + 1,
            )
            self.assertEqual(second_lint["warnings"], first_lint["warnings"])
            self.assertEqual(second_status["technical"]["warnings"], first_status["technical"]["warnings"])
            self.assertEqual(second_quality["quality"]["state"], first_quality["quality"]["state"])
            self.assertNotIn("coverage", json.dumps(second_status))

    def test_a_marker_with_a_superscript_digit_keeps_lint_valid(self) -> None:
        # str.isdigit() accepts "²", int() refuses it: lint used to crash on such a
        # source, and every page batch and release refused with it.
        with TempWiki() as wiki:
            curated = Curated(wiki)
            superscript_id, stem = curated.register(
                "<!-- page: 1 -->\n\nVorwort.\n\n<!-- page: ² -->\n\nZweite Seite.\n\n<!-- page: 3 -->\n\nDritte Seite.\n",
                "Broschuere Hochzahl",
            )
            claims = [(curated.ids[0], "active", f"{superscript_id}@page=9")]
            curated.publish("hochzahl", page_text("hochzahl", [(superscript_id, stem)], claims))
            report = lint_report(wiki)
            self.assertTrue(report["valid"], report["errors"])
            self.assertTrue(any(
                warning.endswith("the extraction marks pages 1, ², 3") for warning in report["warnings"]
            ), report["warnings"])
            listed = {entry["source_id"]: entry for entry in report["stats"]["source_coverage"]["sources"]}
            self.assertEqual(listed[superscript_id]["uncited_units"], ["page=1", "page=²", "page=3"])

    def test_release_output_carries_the_statistic(self) -> None:
        with TempWiki() as wiki:
            curated = Curated(wiki)
            claims = [(curated.ids[0], "active", f"{curated.source_id}@page=2")]
            curated.publish("netzentgelte", page_text("netzentgelte", [(curated.source_id, curated.stem)], claims))
            released = json.loads(wiki.release("coverage-out").stdout)
            coverage = released["stats"]["source_coverage"]
            self.assertEqual(coverage["format"], "lmwiki-source-coverage/1")
            self.assertEqual((coverage["units_total"], coverage["units_cited"]), (2, 1))
            self.assertEqual(json.loads(wiki.read("meta/lint-report.json"))["stats"]["source_coverage"], coverage)

    def test_each_source_locator_pair_is_resolved_once(self) -> None:
        with TempWiki() as wiki:
            curated = Curated(wiki)
            claims = [(curated.ids[0], "active", f"{curated.source_id}@page=2"),
                      (curated.ids[1], "active", f"{curated.source_id}@page=2"),
                      (curated.ids[2], "disputed", f"{curated.source_id}@page=1 | {curated.source_id}@page=2")]
            curated.publish("netzentgelte", page_text("netzentgelte", [(curated.source_id, curated.stem)], claims))
            token_file = wiki.root / "lint-token"
            wiki.maintain("wiki_lock.py", "acquire", "--target", str(wiki.path), "--token-file", str(token_file),
                          "--owner", "test/harness")
            try:
                token = token_file.read_text(encoding="utf-8").strip()
                output = io.StringIO()
                argv = ["lint_wiki.py", "--target", str(wiki.path), "--lock-token", token, "--check-only"]
                with mock.patch.object(sys, "argv", argv), \
                        mock.patch.object(sc, "resolve", wraps=sc.resolve) as counted, \
                        contextlib.redirect_stdout(output):
                    self.assertEqual(lint_wiki.main(), 0)
            finally:
                wiki.maintain("wiki_lock.py", "release", "--target", str(wiki.path), "--token-file", str(token_file),
                              check=False)
            report = json.loads(output.getvalue())
            self.assertEqual(report["stats"]["source_coverage"]["locators"]["resolved"], 4)
            self.assertEqual(counted.call_count, 2)

    def test_a_page_locator_links_to_its_page_marker(self) -> None:
        with TempWiki() as wiki:
            curated = Curated(wiki)
            claims = [(curated.ids[0], "active", f"{curated.source_id}@page=2"),
                      (curated.ids[1], "active", f"{curated.source_id}@S. 1")]
            curated.publish("netzentgelte", page_text("netzentgelte", [(curated.source_id, curated.stem)], claims))
            view = wiki.read("graph/pages/wiki/concepts/netzentgelte.html")
            self.assertIn(f'{curated.stem}.html#page-2">{curated.source_id}@page=2</a>', view)
            self.assertIn(f'{curated.stem}.html#page-1">{curated.source_id}@S. 1</a>', view)
            source_view = wiki.read(f"graph/pages/sources/{curated.stem}.html")
            self.assertIn('id="page-2"', source_view)
        # A marker in a tilde fence is code, as for lint and the scan; a marker right
        # below a text line is still a marker.
        rendered = build_graph.render_markdown(
            "<!-- page: 1 -->\nA\n~~~text\n<!-- page: 2 -->\n# Kopf\n```\n~~~\nText direkt davor\n<!-- page: 3 -->\nB\n",
            Path("graph/pages/sources/a.html"), {}, source_mode=True,
        )
        self.assertNotIn('id="page-2"', rendered)
        self.assertIn('<pre><code class="language-text">&lt;!-- page: 2 --&gt;\n# Kopf\n```</code></pre>', rendered)
        self.assertIn('<p>Text direkt davor</p>\n<div class="page-marker" id="page-3"', rendered)
        anchors = {
            "page=12": "page-12", "page=03": "page-3", "page=3-5": "page-3", "slide=2": "page-2",
            "page=iv": "page-iv", "S. 12": "page-12", "p. 04": "page-4", "section=A": "", "document": "",
        }
        for locator, anchor in anchors.items():
            with self.subTest(locator=locator):
                self.assertEqual(build_graph.locator_anchor(locator), anchor)
        self.assertEqual([build_graph.marker_anchor(value) for value in ("03", "iv", "A 1")], ["page-3", "page-iv", "page-A-1"])

    def test_the_preflight_warns_about_inline_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def assess(text: str, source_type: str = "pdf") -> dict[str, Any]:
                path = Path(directory) / "extract.md"
                path.write_text(text, encoding="utf-8")
                return validate_extraction.assess(path, source_type)

            mixed = assess("Text <!-- page: 1 --> mehr\n\n<!-- page: 2 -->\nB\n```\n<!-- page: 9 -->\nx <!-- page: 8 -->\n```\n")
            self.assertEqual(mixed["warnings"], ["page or slide markers must stand on a line of their own: lines 1"])
            self.assertEqual((mixed["stats"]["page_or_slide_markers"], mixed["stats"]["inline_page_or_slide_markers"]), (1, 1))
            inline_only = assess("Seite eins <!-- page: 1 -->\nSeite zwei <!-- page: 2 -->\n")
            self.assertEqual(inline_only["warnings"], [
                "page or slide markers must stand on a line of their own: lines 1, 2",
                "page or slide markers are missing from a paged source extraction",
            ])
            self.assertEqual(inline_only["recommended_status"], "partial")
            clean = assess("<!-- page: 1 -->\nA\n<!-- slide: 2 -->\nB\n")
            self.assertEqual((clean["state"], clean["stats"]["page_or_slide_markers"]), ("acceptable", 2))
            # Tilde fences hide markers as for the scan and coverage.
            tilde = assess("<!-- page: 1 -->\nA\n~~~\n<!-- page: 2 -->\nx <!-- page: 3 -->\n~~~\n")
            self.assertEqual((tilde["warnings"], tilde["stats"]["page_or_slide_markers"]), ([], 1))


if __name__ == "__main__":
    unittest.main()
