#!/usr/bin/env python3
"""The guarded absence finding (Stufe 4): passages, hit rule, budget, absence_check, search_record, command line.

An empty or wrong result list does not show that a wiki lacks a topic. With
`--exhaustive`, one call also ranks the sources and scans every passage of the
wiki pages, `meta/questions.md` and the source Markdown (history only with
`--include-history`) for all content words of all formulations, in the forms
the ranking resolved. The hits come back under `exhaustive_hits` within a
budget of 100,000 printed characters, and every report carries `absence_check`
and `search_record`. These tests pin the contract:

- segmentation into header, heading, claim, paragraph (list items, tables)
  and open-question passages, with 1-based file lines;
- the coordination hit rule over the ranking's own members, concept
  alternatives, word-form versus heuristic strength and `matched`;
- page order, the printed-size budget, excerpts and references to claims that
  are already printed;
- `complete`, `reasons` and `next_steps` from closed vocabularies, the search
  record line, and the invariant that the scan only adds keys.

Core tests use invented rock names (quarzit, basalt, granit, gneis) so that no
word-form heuristic interferes where none is under test; command-line tests run
on a released harness wiki.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "query-llm-wiki" / "scripts"))

import search_core  # noqa: E402
from harness import QUERY, REPO, TempWiki  # noqa: E402
from test_search_coverage import assert_absence_identities, build_coverage_wiki  # noqa: E402
from wiki_filters import validate_selector  # noqa: E402

INVARIANT_KEYS = (
    "results", "reformulation_results", "formulations", "dropped_formulations", "matched_concepts",
    "expanded_terms", "facets", "coverage", "searched_files", "filtered_out",
)
PREFIX = "references/knowledge/"
ABSENCE_RULE = (
    "State that the wiki contains nothing on a question, or on part of it, only when a search for this answer "
    "reported `absence_check.complete: true` and no returned result or exhaustive hit answers it; otherwise state "
    "that nothing was found with the searched words in this release version, and quote `search_record.line` in "
    "both cases."
)
CONCEPTS = (
    "# Concepts\n\n## gestein-quarz\n- preferred: Quarzit\n- aliases: Quarzgestein | Fels aus Quarz\n"
    "- status: active\n"
)


def page(title: str, body: str, kind: str = "concept", extra: tuple = ()) -> str:
    return "\n".join(["---", f'title: "{title}"', 'status: "active"', f'type: "{kind}"', *extra, "---", "", body, ""])


def claim(claim_id: str, text: str, status: str = "active") -> str:
    head = f"id: {claim_id}\n" if claim_id else ""
    return f"<!-- claim\n{head}kind: fact\nstatus: {status}\nsources: src-1@page=1\n-->\n{text}\n<!-- /claim -->"


class Tree:
    """A folder the search core can read: WIKI.md and an index unless given, plus the given files."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def __enter__(self) -> Path:
        self._directory = tempfile.TemporaryDirectory(prefix="lmwiki-absence-")
        root = Path(self._directory.name)
        files = {"WIKI.md": "# Wiki\n", "wiki/index.md": page("Index", "Startseite.", "index"), **self.files}
        for relative, text in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        return root

    def __exit__(self, *_exc: object) -> None:
        self._directory.cleanup()


def passages(text: str, relative: str = "wiki/page.md") -> list:
    document = search_core.read_document(Path(relative), relative, text, forms=True)
    return search_core.scan_passages(relative, text, document)


def outline(found: list) -> list[tuple]:
    return [(item.kind, item.line, item.locator, item.text) for item in found]


def hit_list(report: dict) -> list[tuple]:
    return [(entry["path"], hit["kind"], hit["line"]) for entry in report["exhaustive_hits"] for hit in entry["hits"]]


def exhaustive(root: Path, query: str, also: tuple = (), **options: object) -> dict:
    return search_core.search(root, query, also=list(also), exhaustive=True, **options)


TWO = ("Basalt Halde", "Granit Lager")


class Segmentation(unittest.TestCase):
    """`scan_passages` is pure: one file in, its passages out."""

    PAGE = "\n".join([
        "---",
        'title: "Quarzit"',
        'status: "active"',
        "aliases:",
        '  - "Quarzgestein"',
        'description: "Ein hartes Gestein."',
        "---",
        "",
        "# Quarzit",
        "",
        "Einleitung über [[wiki/basalt|Basaltsäulen]] und [Granit](wiki/granit.md).",
        "",
        "## Vorkommen",
        "",
        "### Lagerstätten",
        "",
        "Ein Absatz unter der dritten Ebene.",
        "",
        claim("clm-0001", "Quarzit kommt im Gebirge vor.", "disputed"),
        "",
        "- Erster Punkt",
        "  Fortsetzung des ersten Punktes",
        "- Zweiter Punkt",
        "",
        "| Spalte | Wert |",
        "|---|---|",
        "| Härte | hoch |",
        "",
    ])
    SOURCE = "\n".join([
        "---", 'title: "Quelle"', 'type: "source"', "---",
        "<!-- page: 1 -->",
        "Text auf Seite eins.",
        "",
        "<!-- PAGE: 2 --> Text nach Marker.",
        "<!-- Slide: 3 -->",
        "Folientext hier.",
        "",
    ])

    def test_passages_cover_headers_headings_claims_paragraphs_items_and_tables(self) -> None:
        found = passages(self.PAGE)
        self.assertEqual(outline(found), [
            ("header", 1, "", "Quarzit — Quarzgestein — Ein hartes Gestein."),
            ("paragraph", 11, "", "Einleitung über Basaltsäulen und Granit."),
            ("heading", 13, "", "Vorkommen"),
            ("heading", 15, "", "Lagerstätten"),
            ("paragraph", 17, "", "Ein Absatz unter der dritten Ebene."),
            ("claim", 19, "clm-0001", "Quarzit kommt im Gebirge vor."),
            ("paragraph", 28, "", "- Erster Punkt Fortsetzung des ersten Punktes"),
            ("paragraph", 30, "", "- Zweiter Punkt"),
            ("paragraph", 32, "", "| Spalte | Wert | |---|---| | Härte | hoch |"),
        ])
        by_line = {item.line: item for item in found}
        self.assertEqual(by_line[1].section, ())
        self.assertEqual(by_line[1].tokens, frozenset({"quarzit", "quarzgestein", "ein", "hartes", "gestein"}))
        # A heading passage carries its ancestors only; the H1 equal to the title is pushed, not emitted.
        self.assertEqual(by_line[13].section, ("Quarzit",))
        self.assertEqual(by_line[15].section, ("Quarzit", "Vorkommen"))
        self.assertEqual(by_line[17].section, ("Quarzit", "Vorkommen", "Lagerstätten"))
        self.assertEqual(by_line[19].section, ("Quarzit", "Vorkommen", "Lagerstätten"))
        self.assertEqual(by_line[19].status, "disputed")
        # Link labels count, link targets do not.
        self.assertIn("basaltsaulen", by_line[11].tokens)
        self.assertNotIn("basalt", by_line[11].tokens)
        self.assertNotIn("wiki", by_line[11].tokens)
        source = passages(self.SOURCE, "sources/quelle.md")
        self.assertEqual(outline(source), [
            ("header", 1, "", "Quelle"),
            ("paragraph", 6, "page=1", "Text auf Seite eins."),
            ("paragraph", 8, "page=2", "Text nach Marker."),
            ("paragraph", 10, "slide=3", "Folientext hier."),
        ])

    def test_headings_count_only_at_column_0_and_outside_fences(self) -> None:
        text = page("T", "\n".join([
            " # Eingerückt",
            "",
            "```",
            "# Im Zaun",
            "<!-- page: 9 -->",
            "```",
            "",
            "~~~",
            "## Auch im Zaun",
            "~~~",
            "## Echt",
            "Danach.",
        ]))
        self.assertEqual(outline(passages(text))[1:], [
            ("paragraph", 7, "", "# Eingerückt"),
            ("paragraph", 10, "", "# Im Zaun <!-- page: 9 -->"),
            ("paragraph", 15, "", "## Auch im Zaun"),
            ("heading", 17, "", "Echt"),
            ("paragraph", 18, "", "Danach."),
        ])

    def test_long_passages_are_cut_at_1500_characters(self) -> None:
        line = " ".join(["Wort"] * 20)
        body = [f"{line} {number:03d}" for number in range(40)]
        found = passages(page("T", "\n".join(body)))[1:]
        self.assertEqual([item.line for item in found], [7, 22, 37])
        joined = [len("\n".join(body[0:15])), len("\n".join(body[15:30])), len("\n".join(body[30:40]))]
        self.assertGreaterEqual(joined[0], search_core.PASSAGE_MAX_CHARS)
        self.assertLess(len("\n".join(body[0:14])), search_core.PASSAGE_MAX_CHARS)
        self.assertEqual([item.text for item in found], [" ".join(body[0:15]), " ".join(body[15:30]), " ".join(body[30:40])])
        self.assertEqual(joined[2], len("\n".join(body[30:40])))
        sentences = " ".join(f"Satz Nummer {number} endet hier." for number in range(200))
        cut = passages(page("T", "Davor.\n" + sentences + "\nDanach."))[1:]
        self.assertEqual(cut[0].text, "Davor.")
        chunks = cut[1:-1]
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(item.line == 8 for item in chunks))
        self.assertTrue(all(len(item.text) <= search_core.PASSAGE_MAX_CHARS for item in chunks))
        self.assertTrue(all(item.text.endswith("endet hier.") for item in chunks))
        self.assertEqual(" ".join(item.text for item in chunks), sentences)
        self.assertEqual((cut[-1].line, cut[-1].text), (9, "Danach."))

    def test_lines_are_split_on_newline_only(self) -> None:
        text = page("T", "Erste Zeile\fmit Formfeed\n\f\nZweite Zeile\n\n## Titel\n\n" + claim("clm-1", "Schluss.") + "\nNach dem Claim.")
        found = passages(text)
        self.assertEqual(outline(found)[1:], [
            ("paragraph", 7, "", "Erste Zeile mit Formfeed"),
            ("paragraph", 9, "", "Zweite Zeile"),
            ("heading", 11, "", "Titel"),
            ("claim", 13, "clm-1", "Schluss."),
            ("paragraph", 21, "", "Nach dem Claim."),
        ])
        crlf = passages(text.replace("\n", "\r\n"))
        self.assertEqual(crlf, found)

    def test_setext_headings_labels_and_parent_list_items_head_what_follows(self) -> None:
        text = page("T", "\n".join([
            "Quarzit",                 # 7: a setext heading, level 1
            "=======",
            "",
            "Ein Satz darunter.",      # 10
            "",
            "**Basalt**",              # 12: a label of bold text
            "",
            "Noch ein Satz.",          # 14
            "",
            "Lager:",                  # 16: a label ending in a colon replaces the one before
            "- Granit",                # 17
            "  - Halde: voll",         # 18: a nested item under its parent
            "- Gneis",                 # 19
            "",
            "Danach.",                 # 21
            "",
            "Unterpunkt",              # 23: a setext heading, level 2, ends every label
            "----------",
            "",
            "Schluss.",                # 26
        ]))
        found = passages(text)
        self.assertEqual(outline(found)[1:], [
            ("heading", 7, "", "Quarzit"),
            ("paragraph", 10, "", "Ein Satz darunter."),
            ("paragraph", 12, "", "**Basalt**"),
            ("paragraph", 14, "", "Noch ein Satz."),
            ("paragraph", 16, "", "Lager:"),
            ("paragraph", 17, "", "- Granit"),
            ("paragraph", 18, "", "- Halde: voll"),
            ("paragraph", 19, "", "- Gneis"),
            ("paragraph", 21, "", "Danach."),
            ("heading", 23, "", "Unterpunkt"),
            ("paragraph", 26, "", "Schluss."),
        ])
        by_line = {item.line: item for item in found}
        self.assertEqual(by_line[10].section, ("Quarzit",))
        self.assertEqual((by_line[12].section, by_line[12].opens), (("Quarzit",), ("Quarzit", "**Basalt**")))
        self.assertEqual(by_line[14].section, ("Quarzit", "**Basalt**"))
        self.assertEqual((by_line[16].section, by_line[16].opens), (("Quarzit",), ("Quarzit", "Lager:")))
        self.assertEqual((by_line[17].section, by_line[17].opens), (("Quarzit", "Lager:"), ("Quarzit", "Lager:", "- Granit")))
        self.assertEqual(by_line[18].section, ("Quarzit", "Lager:", "- Granit"))
        self.assertEqual(by_line[19].section, ("Quarzit", "Lager:"))
        self.assertEqual(by_line[21].section, ("Quarzit", "Lager:"))
        self.assertEqual(by_line[23].section, ("Quarzit",))
        self.assertEqual(by_line[26].section, ("Quarzit", "Unterpunkt"))
        # A long line, a line inside a list and a paragraph of two lines are no labels; "---" under a list item is no heading.
        other = passages(page("T", "\n".join([
            "Dies ist ein langer Satz, der mit einem Doppelpunkt endet, aber viel zu lang für eine Zwischenzeile ist:",
            "",
            "Zwei Zeilen",
            "enden hier:",
            "",
            "- Punkt",
            "---",
            "",
            "Text.",
        ])))
        self.assertEqual({item.section for item in other}, {()})
        self.assertEqual([item.kind for item in other], ["header", "paragraph", "paragraph", "paragraph", "paragraph"])

    def test_a_split_table_carries_its_first_row(self) -> None:
        rows = ["| Leistung | Quarzit | Basalt |", "|---|---|---|"]
        rows += [f"| Position {number} mit etwas Text | {number},00 | {number},50 |" for number in range(1, 60)]
        rows.append("| Halde | 2.000,00 | 1.500,00 |")
        found = passages(page("T", "## Preise\n\n" + "\n".join(rows)))
        chunks = [item for item in found if item.kind == "paragraph"]
        self.assertGreater(len(chunks), 1)
        head = "| Leistung | Quarzit | Basalt |"
        self.assertEqual((chunks[0].section, chunks[0].opens), (("Preise",), ("Preise", head)))
        self.assertEqual(chunks[0].opens_tokens, frozenset({"leistung", "quarzit", "basalt"}))
        self.assertTrue(all(item.section == ("Preise", head) and not item.opens for item in chunks[1:]))
        with Tree({"wiki/t.md": page("Tabelle", "## Preise\n\n" + "\n".join(rows))}) as root:
            report = exhaustive(root, "Quarzit Halde", TWO)
        self.assertIn(("wiki/t.md", "paragraph", chunks[-1].line), hit_list(report))

    def test_claims_and_headers_carry_their_identifiers(self) -> None:
        text = "\n".join([
            "---", 'id: "concept-quarzit"', 'title: "Quarzit"', 'status: "active"',
            "sources:", '  - "[[sources/src-0123456789abcdef-quelle|Quelle]]"', "---", "",
            "<!-- claim\nid: clm-00000000000000aa\nkind: fact\nstatus: active\n"
            "sources: src-0123456789abcdef@page=1 | src-fedcba9876543210@page=2\n"
            "replaces: clm-00000000000000bb\n-->\nDie Härte ist hoch.\n<!-- /claim -->",
            "",
        ])
        found = passages(text)
        self.assertEqual(found[0].identifiers, frozenset({"concept-quarzit", "src-0123456789abcdef"}))
        self.assertLessEqual(found[0].identifiers, found[0].tokens)
        self.assertEqual(found[1].identifiers, frozenset({
            "clm-00000000000000aa", "src-0123456789abcdef", "src-fedcba9876543210", "clm-00000000000000bb",
        }))
        self.assertEqual(found[1].tokens, found[1].identifiers | {"die", "harte", "ist", "hoch"})
        self.assertEqual(found[1].text, "Die Härte ist hoch.")

    def test_a_claim_over_several_lines_repairs_a_hyphen_at_a_line_end(self) -> None:
        [_, item] = passages(page("T", claim("clm-1", "Der Quarz-\ngang ist alt.")))
        # The display text stays the claim text as claims_in collapses it, so dedupe by text still works.
        self.assertEqual(item.text, "Der Quarz- gang ist alt.")
        self.assertIn("quarzgang", item.tokens)
        self.assertNotIn("quarz", item.tokens)

    def test_navigation_files_are_skipped_and_open_questions_are_scanned(self) -> None:
        files = {
            "WIKI.md": "# Wiki\n\nQuarzit Übersicht.\n",
            "wiki/index.md": page("Index", "- [[wiki/a|Quarzit]]", "index"),
            "wiki/sub/index.md": page("Unterindex", "Quarzit", "index"),
            "wiki/a.md": page("Seite A", "Quarzit liegt hier."),
            "meta/questions.md": "# Offene Fragen\n\n- Wo liegt Quarzit genau?\n- Wann kommt Basalt?\n",
        }
        with Tree(files) as root:
            loaded = search_core.load(root, include_sources=True, exhaustive=True)
            report = exhaustive(root, "Quarzit", TWO)
        self.assertEqual(loaded.scan.counts["wiki"]["navigation_skipped"], 3)
        self.assertEqual(loaded.scan.counts["wiki"]["files"], 2)
        questions = [item for item in loaded.scan.passages if item.kind == "open_question"]
        self.assertEqual([(item.line, item.text) for item in questions], [
            (3, "- Wo liegt Quarzit genau?"), (4, "- Wann kommt Basalt?"),
        ])
        self.assertEqual(sorted({path for path, _, _ in hit_list(report)}), ["meta/questions.md", "wiki/a.md"])
        self.assertIn(("meta/questions.md", "open_question", 3), hit_list(report))
        for path in ("WIKI.md", "wiki/index.md", "wiki/sub/index.md", "meta/history/x/WIKI.md", "meta/history/x/wiki/index.md"):
            self.assertTrue(search_core.scan_navigation(path), path)
        for path in ("meta/questions.md", "meta/history/x/meta/questions.md", "wiki/WIKI.md"):
            self.assertFalse(search_core.scan_navigation(path), path)

    def test_history_is_scanned_only_with_include_history(self) -> None:
        files = {
            "wiki/a.md": page("Seite A", "Quarzit liegt hier."),
            "meta/history/snap-1/WIKI.md": "# Wiki\n\nQuarzit\n",
            "meta/history/snap-1/wiki/index.md": page("Index", "Quarzit", "index"),
            "meta/history/snap-1/wiki/a.md": page("Seite A", "Quarzit lag früher hier."),
            "meta/history/snap-1/meta/questions.md": "# Fragen\n\n- Quarzit wohin?\n",
        }
        with Tree(files) as root:
            plain = exhaustive(root, "Quarzit", TWO)
            history = exhaustive(root, "Quarzit", TWO, include_history=True)
        self.assertEqual(
            plain["absence_check"]["scopes"]["history"],
            {"scanned": False, "shipped": True, "files": None, "navigation_skipped": None, "passages": None, "chars": None},
        )
        self.assertFalse(any(path.startswith("meta/history/") for path, _, _ in hit_list(plain)))
        self.assertTrue(plain["absence_check"]["complete"])
        self.assertTrue(history["coverage"]["scopes"]["history"]["searched"])
        scope = history["absence_check"]["scopes"]["history"]
        self.assertEqual((scope["scanned"], scope["files"], scope["navigation_skipped"]), (True, 2, 2))
        pages = [entry["path"] for entry in history["exhaustive_hits"]]
        self.assertEqual(pages[0], "wiki/a.md")
        self.assertEqual(sorted(pages[1:]), ["meta/history/snap-1/meta/questions.md", "meta/history/snap-1/wiki/a.md"])
        self.assertIn(("meta/history/snap-1/meta/questions.md", "open_question", 3), hit_list(history))
        self.assertTrue(history["absence_check"]["complete"])
        assert_absence_identities(self, plain)
        assert_absence_identities(self, history)


class Matching(unittest.TestCase):
    """The coordination rule, over the ranking's own word-form members."""

    def test_a_passage_hits_when_every_content_word_is_in_it_a_heading_above_or_its_header(self) -> None:
        files = {
            "wiki/q.md": page("Quarzit", claim("clm-a", "Die Härte ist hoch.") + "\n\nEin Absatz ohne Bezug."),
            "wiki/b.md": page("Seite B", "## Basalt\n\n### Details\n\nGranit liegt daneben.\n\n## Anderes\n\nGranit allein."),
            "wiki/g.md": page("Gneis Glimmer", "Nichts davon hier.\n\nAuch hier nicht."),
        }
        with Tree(files) as root:
            self.assertEqual(hit_list(exhaustive(root, "Quarzit Härte")), [("wiki/q.md", "claim", 7)])
            self.assertEqual(hit_list(exhaustive(root, "Basalt Granit")), [("wiki/b.md", "paragraph", 11)])
            self.assertEqual(hit_list(exhaustive(root, "Gneis Glimmer")), [("wiki/g.md", "header", 1)])

    def test_closed_class_and_scan_function_words_are_not_required(self) -> None:
        self.assertIn("ans", search_core.SCAN_FUNCTION_WORDS)
        self.assertTrue({"ab", "ans", "uber", "zwischen", "within"} <= search_core.SCAN_EXCLUDED)
        with Tree({"wiki/a.md": page("Seite", "Quarzit im Lager.")}) as root:
            report = exhaustive(root, "Quarzit ans Lager ab")
        self.assertEqual(report["absence_check"]["formulations"][0]["content_words"], ["quarzit", "lager"])
        self.assertEqual(hit_list(report), [("wiki/a.md", "paragraph", 7)])
        # The ranking is unchanged: it still searches the function word.
        self.assertIn("ans", [item["term"] for item in report["coverage"]["query_terms"]])

    WORDS = {
        "wiki/a.md": page("Seite A", "Quarzit liegt hier."),
        "wiki/b.md": page("Seite B", "Der Granitblock steht."),
        "wiki/c.md": page("Seite C", "Ein Block allein. Ein Granit allein."),
        "wiki/d.md": page("Seite D", "Die Pegmatitader zieht durch."),
    }

    def test_word_forms_count_and_heuristics_are_marked(self) -> None:
        with Tree(self.WORDS) as root:
            stem = exhaustive(root, "Quarzits")
            compound = exhaustive(root, "Granit")
            typo = exhaustive(root, "Pegmatitadr")
        [hit] = stem["exhaustive_hits"][0]["hits"]
        self.assertEqual((hit["strength"], "matched" in hit), ("word_form", False))
        by_page = {entry["path"]: entry["hits"][0] for entry in compound["exhaustive_hits"]}
        self.assertEqual(by_page["wiki/c.md"]["strength"], "word_form")
        self.assertEqual(by_page["wiki/b.md"]["strength"], "heuristic")
        self.assertEqual(
            by_page["wiki/b.md"]["matched"],
            [{"term": "granit", "token": "granitblock", "rule": "compound_modifier", "in": "text"}],
        )
        self.assertEqual([entry["path"] for entry in compound["exhaustive_hits"]], ["wiki/c.md", "wiki/b.md"])
        [hit] = typo["exhaustive_hits"][0]["hits"]
        self.assertEqual(hit["matched"], [{"term": "pegmatitadr", "token": "pegmatitader", "rule": "typo", "in": "text"}])
        self.assertEqual(typo["absence_check"]["counts"]["hits_heuristic"], 1)

    def test_the_scan_matches_the_rankings_members(self) -> None:
        with Tree(self.WORDS) as root:
            loaded = search_core.load(root, include_sources=True, exhaustive=True)
            for query in ("Granit", "Quarzits", "Pegmatitadr", "Granit Block Quarzit"):
                with self.subTest(query=query):
                    ranking = search_core.rank(loaded, query, limit=12)
                    report = search_core.search_loaded(loaded, query, exhaustive=True)
                    check = report["absence_check"]
                    self.assertEqual(check["formulations"][0]["content_words"], search_core.content_words(ranking.terms))
                    for entry in check["terms"]:
                        members = ranking.members[entry["term"]]
                        ordered = sorted(members, key=lambda member: (-member[2], -loaded.vocabulary[member[0]], member[0]))
                        self.assertEqual(entry["forms"], [{"token": token, "rule": rule} for token, rule, _ in ordered[:10]])
                        self.assertEqual(entry["forms_total"], len(members))
                        tokens = {token for token, _, _ in members}
                        holders = [item for item in loaded.scan.passages if not tokens.isdisjoint(item.tokens)]
                        self.assertEqual(entry["passages"]["wiki"], len(holders))

    def test_concept_aliases_stand_in_for_the_words_they_cover(self) -> None:
        files = {
            "schema/CONCEPTS.md": CONCEPTS,
            "wiki/a.md": page("Seite A", "Quarzit im Lager."),
            "wiki/b.md": page("Seite B", "Quarzit im Granitlager."),
            "wiki/c.md": page("Seite C", "Ein Granit allein."),
        }
        with Tree(files) as root:
            definitions = search_core.controlled_concepts(root / "schema/CONCEPTS.md")
            report = exhaustive(root, "Quarzgestein Lager")
        for query in ("Quarzgestein Lager", "Fels aus Quarz", "Quarzit", "nichts", "Quarzgesteine", "Lager Quarzgestein Quarzit"):
            with self.subTest(query=query):
                self.assertEqual(
                    list(search_core.concept_runs(query, definitions)), search_core.expand_query(query, definitions, True)[1]
                )
        runs = search_core.concept_runs("Quarzgestein Lager", definitions)
        self.assertEqual(runs, {"gestein-quarz": ["quarzgestein"]})
        # The closed-class word inside "Fels aus Quarz" is not required.
        self.assertEqual(
            search_core.alternatives(["quarzgestein", "lager"], runs, definitions),
            {
                "quarzgestein": [(None, ("quarzgestein",)), ("gestein-quarz", ("quarzit",)), ("gestein-quarz", ("fels", "quarz"))],
                "lager": [(None, ("lager",))],
            },
        )
        by_page = {entry["path"]: entry["hits"][0] for entry in report["exhaustive_hits"]}
        self.assertEqual(by_page["wiki/a.md"]["strength"], "word_form")
        self.assertEqual(by_page["wiki/b.md"]["strength"], "heuristic")
        self.assertEqual(by_page["wiki/b.md"]["matched"], [
            {"term": "quarzgestein", "token": "quarzit", "rule": "exact", "in": "text", "concept": "gestein-quarz"},
            {"term": "lager", "token": "granitlager", "rule": "compound_head", "in": "text"},
        ])
        self.assertEqual(report["absence_check"]["absent_terms"], ["quarzgestein"])

    def test_a_word_that_occurs_nowhere_is_absent_and_its_formulation_has_no_hits(self) -> None:
        with Tree({"wiki/a.md": page("Seite A", "Quarzit liegt hier."), "wiki/b.md": page("Seite B", "Basalt liegt dort.")}) as root:
            report = exhaustive(root, "Quarzit Zirkon", ("Basalt", "Granit Halde"))
        check = report["absence_check"]
        self.assertIn("zirkon", check["absent_terms"])
        self.assertNotIn("quarzit", check["absent_terms"])
        self.assertEqual([entry["hits"] for entry in check["formulations"]], [0, 1, 0])
        terms = {entry["term"]: entry for entry in check["terms"]}
        self.assertEqual(terms["zirkon"]["passages"], {"wiki": 0, "sources": 0, "history": None})
        self.assertEqual(terms["quarzit"]["files"], {"wiki": 1, "sources": 0, "history": None})

    def test_hits_name_every_formulation_they_match(self) -> None:
        files = {"wiki/a.md": page("Seite A", "Quarzit und Basalt im Lager."), "wiki/b.md": page("Seite B", "Granit allein.")}
        with Tree(files) as root:
            report = exhaustive(root, "Quarzit Lager", ("Basalt Lager", "Granit"))
        hits = {entry["path"]: entry["hits"][0]["formulations"] for entry in report["exhaustive_hits"]}
        self.assertEqual(hits, {"wiki/a.md": [0, 1], "wiki/b.md": [2]})
        self.assertEqual([entry["hits"] for entry in report["absence_check"]["formulations"]], [1, 1, 1])
        self.assertEqual([entry["path"] for entry in report["exhaustive_hits"]], ["wiki/a.md", "wiki/b.md"])

    def test_context_reaches_passages_under_labels_parent_items_and_setext_headings(self) -> None:
        files = {
            "wiki/a.md": page("Seite A", "**Quarzit**\n\nDer Block liegt im Lager."),
            "wiki/b.md": page("Seite B", "- Quarzit\n  - Lager: voll\n- Basalt"),
            "wiki/c.md": page("Seite C", "Quarzit\n=======\n\nIm Lager."),
            "wiki/d.md": page("Seite D", "Quarzit:\n- Lager voll"),
            "wiki/e.md": page("Seite E", "Quarzit allein.\n\nIm Lager."),
        }
        with Tree(files) as root:
            report = exhaustive(root, "Quarzit Lager", TWO)
        self.assertEqual(sorted(hit_list(report)), [
            ("wiki/a.md", "paragraph", 9),
            ("wiki/b.md", "paragraph", 8),
            ("wiki/c.md", "paragraph", 10),
            ("wiki/d.md", "paragraph", 8),
        ])
        self.assertNotIn("wiki/e.md", {path for path, _, _ in hit_list(report)})
        self.assertTrue(report["absence_check"]["complete"])
        assert_absence_identities(self, report)

    def test_hyphen_parts_match_in_both_directions(self) -> None:
        self.assertEqual(search_core.hyphen_units("smart-meter-gateway"), ("smart", "meter", "gateway"))
        for word in ("gneis", "e-mobilitat", "end-to-end", "x-y"):
            with self.subTest(word=word):
                self.assertEqual(search_core.hyphen_units(word), ())
        files = {
            "wiki/a.md": page("Seite A", "Die Gneis-Halde liegt am Hang."),
            "wiki/b.md": page("Seite B", "Der Basalt Bruch ist alt."),
        }
        with Tree(files) as root:
            apart = exhaustive(root, "Gneis Halde", TWO)
            joined = exhaustive(root, "Basalt-Bruch", TWO)
            plain = search_core.search(root, "Gneis Halde", also=list(TWO), include_sources=True)
        [hit] = [hit for entry in apart["exhaustive_hits"] if entry["path"] == "wiki/a.md" for hit in entry["hits"]]
        self.assertEqual((hit["strength"], hit["formulations"]), ("heuristic", [0]))
        self.assertEqual(hit["matched"], [
            {"term": "gneis", "token": "gneis-halde", "rule": "hyphen_part", "in": "text"},
            {"term": "halde", "token": "gneis-halde", "rule": "hyphen_part", "in": "text"},
        ])
        check = apart["absence_check"]
        self.assertNotIn("gneis", check["absent_terms"])
        terms = {entry["term"]: entry for entry in check["terms"]}
        self.assertEqual(terms["gneis"]["forms"], [{"token": "gneis-halde", "rule": "hyphen_part"}])
        self.assertEqual(terms["gneis"]["passages"]["wiki"], 1)
        # The ranking does not know the rule: everything outside the scan is unchanged.
        for key in INVARIANT_KEYS:
            self.assertEqual(apart[key], plain[key], key)
        [hit] = [hit for entry in joined["exhaustive_hits"] if entry["path"] == "wiki/b.md" for hit in entry["hits"]]
        self.assertEqual(hit["strength"], "heuristic")
        self.assertEqual(hit["matched"], [{"term": "basalt-bruch", "token": "basalt", "rule": "hyphen_part", "in": "text"}])
        joined_terms = {entry["term"]: entry for entry in joined["absence_check"]["terms"]}
        self.assertEqual(joined_terms["basalt-bruch"]["passages"]["wiki"], 1)
        self.assertNotIn("basalt-bruch", joined["absence_check"]["absent_terms"])

    def test_identifiers_match_as_whole_tokens(self) -> None:
        files = {
            "wiki/q.md": "\n".join([
                "---", 'id: "concept-quarzit"', 'title: "Quarzit"', 'status: "active"',
                "sources:", '  - "[[sources/src-0123456789abcdef-quelle|Quelle]]"', "---", "",
                "## Härte", "", claim("clm-00000000000000aa", "Die Härte ist hoch."), "",
            ]),
            "sources/src-0123456789abcdef-quelle.md": page("Quelle", "Ein Text.", "source", ('source_id: "src-0123456789abcdef"',)),
        }
        with Tree(files) as root:
            by_claim = exhaustive(root, "clm-00000000000000aa", ("Härte Quarzit", "Granit"))
            by_source = exhaustive(root, "src-0123456789abcdef", ("Quelle Quarzit", "Granit"))
            by_page = exhaustive(root, "concept-quarzit", TWO)
            by_part = exhaustive(root, "concept", TWO)
        self.assertIn(("wiki/q.md", "claim", 11), hit_list(by_claim))
        [hit] = [hit for entry in by_claim["exhaustive_hits"] for hit in entry["hits"] if hit["kind"] == "claim"]
        self.assertEqual((hit["strength"], hit["formulations"]), ("word_form", [0, 1]))
        terms = {entry["term"]: entry for entry in by_claim["absence_check"]["terms"]}
        self.assertEqual(terms["clm-00000000000000aa"]["forms"], [{"token": "clm-00000000000000aa", "rule": "exact"}])
        self.assertNotIn("clm-00000000000000aa", by_claim["absence_check"]["absent_terms"])
        self.assertEqual(
            sorted(hit for hit in hit_list(by_source) if hit[1] == "header"),
            [("sources/src-0123456789abcdef-quelle.md", "header", 1), ("wiki/q.md", "header", 1)],
        )
        self.assertIn(("wiki/q.md", "header", 1), hit_list(by_page))
        # An identifier is matched whole; its parts never stand for a word.
        self.assertIn("concept", by_part["absence_check"]["absent_terms"])
        self.assertEqual(by_part["absence_check"]["formulations"][0]["hits"], 0)

    def test_light_verbs_of_a_question_are_not_required(self) -> None:
        self.assertTrue({"gibt", "geht", "gilt", "passiert", "steht"} <= search_core.SCAN_FUNCTION_WORDS)
        with Tree({"wiki/a.md": page("Seite A", "Im Lager liegt Quarzit.")}) as root:
            report = exhaustive(root, "Gibt es Quarzit im Lager?", TWO)
        self.assertEqual(report["absence_check"]["formulations"][0]["content_words"], ["quarzit", "lager"])
        self.assertIn(("wiki/a.md", "paragraph", 7), hit_list(report))

    def test_a_heading_with_nothing_under_it_is_scanned_without_error(self) -> None:
        files = {"wiki/e.md": page("Seite E", "## Basalt\n\n## Granit\n\nText hier.\n\n## Gneis")}
        with Tree(files) as root:
            loaded = search_core.load(root, include_sources=True, exhaustive=True)
            for query, line in (("Basalt", 7), ("Gneis", 13), ("Granit Text", 11)):
                with self.subTest(query=query):
                    report = search_core.search_loaded(loaded, query, also=["Quarzit Halde", "Lager"], exhaustive=True)
                    self.assertIn(("wiki/e.md", "heading" if line != 11 else "paragraph", line), hit_list(report))
        # Only a heading with passages under it is context.
        self.assertNotIn("basalt", loaded.scan.section_index)
        self.assertNotIn("gneis", loaded.scan.section_index)
        self.assertIn("granit", loaded.scan.section_index)


class OrderBudgetDedupe(unittest.TestCase):
    def test_pages_are_ordered_by_history_corroboration_question_strength_scope_and_path(self) -> None:
        files = {
            "wiki/zz.md": page("Seite Z", "Quarzit und Basalt."),
            "wiki/aa.md": page("Seite A", "Basalt."),
            "wiki/mm.md": page("Seite M", "Quarzit."),
            "wiki/hh.md": page("Seite H", "Quarzitblock am Block."),
            "sources/qq.md": page("Quelle Q", "Quarzit.", "source"),
            "meta/history/s1/wiki/zz.md": page("Seite Z", "Quarzit und Basalt."),
        }
        with Tree(files) as root:
            report = exhaustive(root, "Quarzit", ("Basalt",), include_history=True)
        self.assertEqual(
            [entry["path"] for entry in report["exhaustive_hits"]],
            ["wiki/zz.md", "wiki/mm.md", "sources/qq.md", "wiki/hh.md", "wiki/aa.md", "meta/history/s1/wiki/zz.md"],
        )
        strength = {entry["path"]: entry["hits"][0]["strength"] for entry in report["exhaustive_hits"]}
        self.assertEqual(strength["wiki/hh.md"], "heuristic")

    def test_the_budget_counts_printed_characters_and_cuts_at_a_hit_boundary(self) -> None:
        files = {
            f"wiki/p{number:02d}.md": page(f"Seite {number}", "Quarzit eins.\n\nQuarzit zwei.\n\nQuarzit drei.")
            for number in range(25)
        }
        with Tree(files) as root:
            loaded = search_core.load(root, include_sources=True, exhaustive=True)
            full = search_core.search_loaded(loaded, "Quarzit", also=TWO, exhaustive=True, exhaustive_budget=10**9)
            walk = [(entry["path"], hit) for entry in full["exhaustive_hits"] for hit in entry["hits"]]
            needed = full["absence_check"]["budget"]["needed_chars"]
            self.assertEqual(full["absence_check"]["budget"]["used_chars"], needed)
            partial_seen = exhausted_seen = 0
            for budget in list(range(2, needed + 200, 211)) + [needed - 1, needed]:
                with self.subTest(budget=budget):
                    report = search_core.search_loaded(loaded, "Quarzit", also=TWO, exhaustive=True, exhaustive_budget=budget)
                    check = report["absence_check"]
                    assert_absence_identities(self, report)
                    printed = json.dumps(report, ensure_ascii=False, indent=search_core.REPORT_INDENT)
                    without = json.dumps({**report, "exhaustive_hits": None}, ensure_ascii=False, indent=search_core.REPORT_INDENT)
                    self.assertEqual(len(printed) - len(without) + 4, check["budget"]["used_chars"])
                    returned = [(entry["path"], hit) for entry in report["exhaustive_hits"] for hit in entry["hits"]]
                    self.assertEqual(returned, walk[: len(returned)], "the output is a strict prefix")
                    self.assertEqual(check["budget"]["needed_chars"], needed)
                    self.assertEqual(check["budget"]["limit_chars"], budget)
                    shown = {entry["path"] for entry in report["exhaustive_hits"]}
                    self.assertEqual(
                        check["omitted_pages"],
                        [{"path": entry["path"], "hits": 3} for entry in full["exhaustive_hits"] if entry["path"] not in shown][:20],
                    )
                    if len(returned) < len(walk):
                        # The next hit in walk order would not have fit.
                        path, hit = walk[len(returned)]
                        grown = [dict(entry, hits=list(entry["hits"])) for entry in report["exhaustive_hits"]]
                        if grown and grown[-1]["path"] == path:
                            grown[-1]["hits"].append(hit)
                        else:
                            entry = next(item for item in full["exhaustive_hits"] if item["path"] == path)
                            grown.append(dict(entry, hits=[hit]))
                        self.assertGreater(search_core.printed_chars(grown, 1), budget)
                    partial_seen += check["counts"]["pages_partial"]
                    exhausted_seen += "budget_exhausted" in check["reasons"]
            self.assertGreater(partial_seen, 0)
            self.assertGreater(exhausted_seen, 0)
            empty = search_core.search_loaded(loaded, "Quarzit", also=TWO, exhaustive=True, exhaustive_budget=2)
        self.assertEqual(empty["exhaustive_hits"], [])
        self.assertEqual(len(empty["absence_check"]["omitted_pages"]), 20)
        self.assertEqual(empty["absence_check"]["counts"]["pages_not_returned"], 25)
        self.assertEqual(empty["absence_check"]["reasons"], ["budget_exhausted"])

    def test_long_passages_show_a_window_around_the_first_match(self) -> None:
        wanted = frozenset({"quarzit"})
        middle = " ".join(["Vorwort"] * 80 + ["Quarzit"] + ["Nachwort"] * 80)
        text, cut = search_core.excerpt(middle, wanted)
        self.assertTrue(cut)
        self.assertLessEqual(len(text), 400)
        self.assertTrue(text.startswith("… ") and text.endswith(" …"))
        self.assertIn("Quarzit", text)
        self.assertLessEqual(text.index("Quarzit"), 2 + 100 + 1)
        start, _ = search_core.excerpt("Quarzit " + " ".join(["Nachwort"] * 80), wanted)
        self.assertTrue(start.startswith("Quarzit ") and start.endswith(" …"))
        end, _ = search_core.excerpt(" ".join(["Vorwort"] * 80) + " Quarzit", wanted)
        self.assertTrue(end.startswith("… ") and end.endswith(" Quarzit"))
        none, _ = search_core.excerpt(" ".join(["Vorwort"] * 80), wanted)
        self.assertFalse(none.startswith("…"))
        long_word = "Quarzit" + "e" * 450
        hard, cut = search_core.excerpt("Vorwort " * 5 + long_word + " Nachwort", frozenset({long_word.lower()}))
        self.assertEqual(hard, "… " + long_word[:396] + " …")
        self.assertEqual(len(hard), 400)
        self.assertEqual(search_core.excerpt("kurz", wanted), ("kurz", False))
        body = " ".join(["Vorwort"] * 80) + " Quarzit Lager " + " ".join(["Nachwort"] * 80)
        with Tree({"wiki/a.md": page("Seite A", body)}) as root:
            report = exhaustive(root, "Quarzit Lager")
        [hit] = report["exhaustive_hits"][0]["hits"]
        self.assertTrue(hit["excerpt"])
        self.assertEqual(hit["text_chars"], len(body))
        self.assertLessEqual(len(hit["text"]), 400)
        self.assertIn("Quarzit Lager", hit["text"])

    def test_claims_printed_in_results_are_referenced_not_repeated(self) -> None:
        files = {
            "wiki/a.md": page("Seite A", claim("clm-a1", "Quarzit liegt auf der Halde.") + "\n\nQuarzit auf der Halde."),
            "wiki/b.md": page("Seite B", claim("clm-b1", "Basalt liegt im Lager.")),
            "wiki/c.md": page("Seite C", "\n\n".join(claim("", f"Gneis Nummer {number} im Fach.") for number in range(10))),
        }
        with Tree(files) as root:
            for prefix in ("", PREFIX):
                with self.subTest(prefix=prefix):
                    report = exhaustive(root, "Quarzit Halde", ("Basalt Lager", "Gneis Fach"), path_prefix=prefix)
                    self.assertEqual([item["path"] for item in report["results"]], [prefix + "wiki/a.md"])
                    self.assertEqual(
                        sorted(item["path"] for item in report["reformulation_results"]), [prefix + "wiki/b.md", prefix + "wiki/c.md"]
                    )
                    hits = {entry["path"][len(prefix):]: entry["hits"] for entry in report["exhaustive_hits"]}
                    self.assertEqual([hit.get("shown_in") for hit in hits["wiki/a.md"]], ["results", None])
                    self.assertEqual(hits["wiki/a.md"][1]["text"], "Quarzit auf der Halde.")
                    self.assertEqual(list(hits["wiki/a.md"][0]), [
                        "kind", "line", "locator", "status", "formulations", "strength", "shown_in",
                    ])
                    self.assertEqual([hit.get("shown_in") for hit in hits["wiki/b.md"]], ["reformulation_results"])
                    # Claims without an ID are keyed by their text: 8 of 10 are printed.
                    shown = [hit.get("shown_in") for hit in hits["wiki/c.md"]]
                    self.assertEqual(shown.count("reformulation_results"), 8)
                    self.assertEqual(shown.count(None), 2)
                    counts = report["absence_check"]["counts"]
                    self.assertEqual((counts["hits_total"], counts["hits_already_printed"]), (13, 10))
                    assert_absence_identities(self, report)

    def test_the_scan_ignores_the_selector_and_marks_selected_pages(self) -> None:
        files = {"wiki/a.md": page("Seite A", "Quarzit hier."), "wiki/b.md": page("Seite B", "Quarzit dort.")}
        selector = validate_selector({"kind": "paths", "paths": ["wiki/a.md"]})
        with Tree(files) as root:
            narrowed = exhaustive(root, "Quarzit", TWO, selector=selector)
            plain = exhaustive(root, "Quarzit", TWO)
        self.assertEqual([item["path"] for item in narrowed["results"]], ["wiki/a.md"])
        self.assertEqual(
            [(entry["path"], entry["selected"]) for entry in narrowed["exhaustive_hits"]],
            [("wiki/a.md", True), ("wiki/b.md", False)],
        )
        self.assertEqual(list(narrowed["exhaustive_hits"][0]), ["path", "scope", "title", "status", "hits_total", "selected", "hits"])
        self.assertTrue(all("selected" not in entry for entry in plain["exhaustive_hits"]))
        self.assertEqual(hit_list(narrowed), hit_list(plain))


class AbsenceCheck(unittest.TestCase):
    FILES = {
        "wiki/a.md": page("Seite A", "Quarzit und Basalt im Lager."),
        "wiki/b.md": page("Seite B", "Granit an der Halde."),
        "wiki/c.md": page("Seite C", "Käse und Quarzit."),
    }
    RELEASE = {"version": "1.2.3", "release_id": "rel-1", "manifest_sha256": "abcdef0123456789" * 4}

    def test_every_report_carries_absence_check_and_search_record(self) -> None:
        with Tree(self.FILES) as root:
            report = search_core.search(root, "Quarzit", also=list(TWO))
        self.assertIsNone(report["exhaustive_hits"])
        self.assertEqual(report["absence_check"], {
            "format": "lmwiki-absence-check/1", "complete": False, "reasons": ["not_exhaustive"], "next_steps": None,
            "reformulations_counted": None, "budget": None, "counts": None, "omitted_pages": None,
            "absent_terms": None, "formulations": None, "scopes": None, "terms": None,
            "boundary": search_core.ABSENCE_BOUNDARY,
        })
        line = search_core.search_record(report, self.RELEASE)["line"]
        self.assertTrue(line.endswith("ranked=wiki exhaustive=false results=2/2 hits=none complete=false"), line)
        assert_absence_identities(self, report)

    def test_complete_requires_each_condition(self) -> None:
        cases = (
            ("Quarzit", ["Basalt Lager", "Granit Halde"], None, [], 2),
            ("Quarzit", ["Basalt Lager"], None, ["too_few_reformulations"], 1),
            ("Quarzit", ["Basalt Lager", "Granit Halde"], 10, ["budget_exhausted"], 2),
            ("die und", ["der", "das"], None, ["too_few_reformulations", "no_content_words"], 0),
            ("Quarzit", ["quarzit!", "Basalt Lager"], None, ["too_few_reformulations"], 1),
            ("Quarzit Lager", ["Lager Quarzit", "Basalt"], None, ["too_few_reformulations"], 1),
            ("Quarzit Käse", ["Quarzit Kaese", "Basalt"], None, ["too_few_reformulations"], 1),
            ("Quarzit", ["über das", "Basalt"], None, ["too_few_reformulations"], 1),
            ("Quarzit", ["Quarzite", "Basalt"], None, ["too_few_reformulations"], 1),
            # Adding words to the question or to a counted reformulation only narrows the hits.
            ("Quarzit", ["Basalt", "Quarzit Basalt"], None, ["too_few_reformulations"], 1),
            ("Quarzit", ["Quarzit Lager", "Basalt Halde"], None, ["too_few_reformulations"], 1),
            ("Quarzit Lager", ["Lager", "Basalt"], None, [], 2),
        )
        with Tree(self.FILES) as root:
            loaded = search_core.load(root, include_sources=True, exhaustive=True)
            for query, also, budget, reasons, counted in cases:
                with self.subTest(query=query, also=also, budget=budget):
                    options = {} if budget is None else {"exhaustive_budget": budget}
                    report = search_core.search_loaded(loaded, query, also=also, exhaustive=True, **options)
                    check = report["absence_check"]
                    self.assertEqual(check["reasons"], reasons)
                    self.assertEqual(check["complete"], not reasons)
                    self.assertEqual(check["reformulations_counted"], counted)
                    self.assertEqual(sum(entry["counted"] for entry in check["formulations"]), counted)
                    assert_absence_identities(self, report)
        formulations = [{"origin": "query"}, {"origin": "also"}, {"origin": "also"}, {"origin": "also"}]
        self.assertEqual(
            search_core.counted_reformulations(formulations, [["quarzit"], ["basalt"], ["basalte"], ["granit", "quarzit"]]),
            [False, True, False, False],
        )
        self.assertEqual(
            search_core.counted_reformulations(formulations, [["quarzit", "lager"], ["lager"], ["basalt", "lager"], ["granit"]]),
            [False, True, False, True],
        )
        self.assertEqual(search_core.counted_reformulations(formulations[:2], [[], ["basalt"]]), [False, True])
        # A hyphenated word counts as its parts: another spelling of the same words.
        self.assertEqual(
            search_core.counted_reformulations(
                formulations, [["quarzit", "lager"], ["quarzit-lager"], ["basalt-halde"], ["basalt", "halde", "granit"]]
            ),
            [False, False, True, False],
        )
        # A question without content words leaves nothing to be a superset of.
        self.assertEqual(
            search_core.counted_reformulations(formulations[:3], [[], ["basalt"], ["granit", "halde"]]), [False, True, True]
        )

    def test_reasons_and_next_steps_come_from_the_closed_vocabulary_in_order(self) -> None:
        self.assertEqual(
            search_core.ABSENCE_REASONS, ("not_exhaustive", "too_few_reformulations", "no_content_words", "budget_exhausted")
        )
        self.assertEqual(search_core.ABSENCE_STEPS, (
            "read_withheld_claims", "read_results_without_claims", "read_reformulation_results", "read_exhaustive_hits",
            "add_reformulations", "narrow_formulations",
        ))
        with Tree(self.FILES) as root:
            loaded = search_core.load(root, include_sources=True, exhaustive=True)
            for query, also, budget in (
                ("Quarzit", ["Basalt Lager", "Granit Halde"], 10), ("die", [], 10), ("Quarzit Lager", ["Basalt"], 300),
                ("Granit", ["Halde"], None),
            ):
                options = {} if budget is None else {"exhaustive_budget": budget}
                check = search_core.search_loaded(loaded, query, also=also, exhaustive=True, **options)["absence_check"]
                with self.subTest(query=query, reasons=check["reasons"], steps=check["next_steps"]):
                    self.assertEqual(check["reasons"], [item for item in search_core.ABSENCE_REASONS if item in check["reasons"]])
                    self.assertEqual(check["next_steps"], [item for item in search_core.ABSENCE_STEPS if item in check["next_steps"]])
                    self.assertTrue(check["reasons"])

    def test_each_next_step_is_emitted_exactly_when_its_condition_holds(self) -> None:
        steps = search_core.absence_steps
        withheld = {"navigation": False, "claims_returned": 3, "claims_total": 12}
        self.assertEqual(steps([], [withheld], [], []), ["read_withheld_claims"])
        self.assertEqual(steps([], [{**withheld, "navigation": True}], [], []), [])
        self.assertEqual(steps([], [{**withheld, "claims_returned": 12}], [], []), [])
        self.assertEqual(steps([], [], [withheld], []), ["read_withheld_claims", "read_reformulation_results"])
        self.assertEqual(steps([], [], [{**withheld, "claims_returned": 12}], []), ["read_reformulation_results"])
        self.assertEqual(steps([], [], [], [{"hits": [{"text": "x"}]}]), ["read_exhaustive_hits"])
        self.assertEqual(steps([], [], [], [{"hits": [{"shown_in": "results"}]}]), [])
        self.assertEqual(steps(["too_few_reformulations"], [], [], []), ["add_reformulations"])
        self.assertEqual(steps(["too_few_reformulations", "no_content_words"], [], [], []), ["add_reformulations"])
        self.assertEqual(steps(["budget_exhausted"], [], [], []), ["narrow_formulations"])
        # Narrower reformulations cannot help once the question's own hits exceed the budget.
        self.assertEqual(steps(["budget_exhausted"], [], [], [], narrowable=False), [])
        # An entry that prints no claims (a source, a page without claim blocks) shows only its snippet.
        bare = {"navigation": False, "claims_returned": 0, "claims_total": 0}
        self.assertEqual(steps([], [bare], [], []), ["read_results_without_claims"])
        self.assertEqual(steps([], [{**bare, "navigation": True}], [], []), [])
        self.assertEqual(steps([], [], [bare], []), ["read_results_without_claims", "read_reformulation_results"])
        files = {
            "wiki/heavy.md": page(
                "Seite H",
                "\n\n".join(claim(f"clm-h{number:02d}", "Quarzit im Fach." if number < 3 else f"Anderer Satz {number}.") for number in range(12)),
            ),
            "wiki/light.md": page("Seite L", claim("clm-l1", "Basalt im Fach.")),
        }
        with Tree(files) as root:
            report = exhaustive(root, "Quarzit", ("Basalt Fach", "Granit"))
            single = exhaustive(root, "Quarzit", ("Basalt Fach",))
            hopeless = exhaustive(root, "Quarzit", ("Basalt Fach", "Granit"), exhaustive_budget=10)
            question_only = [
                {**entry, "hits_total": len(own), "hits": own}
                for entry in report["exhaustive_hits"]
                for own in [[hit for hit in entry["hits"] if 0 in hit["formulations"]]]
                if own
            ]
            fits = search_core.printed_chars(question_only, 1)
            self.assertLess(fits, report["absence_check"]["budget"]["needed_chars"])
            tight = exhaustive(root, "Quarzit", ("Basalt Fach", "Granit"), exhaustive_budget=fits)
            over = exhaustive(root, "Quarzit", ("Basalt Fach", "Granit"), exhaustive_budget=fits - 1)
        heavy = report["results"][0]
        self.assertEqual((heavy["claims_returned"], heavy["claims_total"]), (3, 12))
        self.assertEqual(report["absence_check"]["next_steps"], ["read_withheld_claims", "read_reformulation_results"])
        self.assertTrue(report["absence_check"]["complete"])
        self.assertEqual(report["absence_check"]["counts"]["hits_already_printed"], 4)
        self.assertEqual(single["absence_check"]["next_steps"], ["read_withheld_claims", "read_reformulation_results", "add_reformulations"])
        for case in (tight, over, hopeless):
            self.assertEqual(case["absence_check"]["reasons"], ["budget_exhausted"])
        self.assertEqual(tight["absence_check"]["next_steps"], ["read_withheld_claims", "read_reformulation_results", "narrow_formulations"])
        self.assertEqual(over["absence_check"]["next_steps"], ["read_withheld_claims", "read_reformulation_results"])
        self.assertEqual(hopeless["absence_check"]["next_steps"], ["read_withheld_claims", "read_reformulation_results"])

    def test_the_search_record_line_is_stable(self) -> None:
        found = {
            "formulations": [{"text": 'Was heißt "Quarzit"?'}, {"text": "a"}, {"text": "b"}],
            "coverage": {"scopes": {"wiki": {"searched": True}, "sources": {"searched": True}, "history": {"searched": False}}, "matched": 7},
            "results": [{}, {}, {}],
            "exhaustive_hits": [],
            "absence_check": {"complete": True, "counts": {"hits_returned": 4, "hits_total": 5}},
        }
        self.assertEqual(search_core.search_record(found, self.RELEASE), {
            "format": "lmwiki-search-record/1",
            "line": 'lmwiki-search-record/1 release=1.2.3 id=rel-1 manifest=abcdef012345 query="Was heißt \\"Quarzit\\"?" '
                    "reformulations=2 ranked=wiki+sources exhaustive=true results=3/7 hits=4/5 complete=true",
        })
        long = {**found, "formulations": [{"text": "x" * 250}], "exhaustive_hits": None,
                "absence_check": {"complete": False, "counts": None}}
        self.assertEqual(
            search_core.search_record(long, {})["line"],
            f'lmwiki-search-record/1 release= id= manifest= query="{"x" * 200}…" reformulations=0 ranked=wiki+sources '
            "exhaustive=false results=3/7 hits=none complete=false",
        )

    def test_exhaustive_adds_keys_and_changes_no_ranking(self) -> None:
        files = {
            **self.FILES,
            "sources/quelle.md": page("Quelle", "<!-- page: 1 -->\nQuarzit in der Quelle.\n\nBasalt im Lager.", "source"),
            "schema/CONCEPTS.md": CONCEPTS,
        }
        with Tree(files) as root:
            for query, also, limit in (("Quarzit", TWO, 12), ("Quarzgestein Lager", ("Basalt",), 1), ("Granit", (), 100)):
                with self.subTest(query=query):
                    scanned = exhaustive(root, query, also, limit=limit)
                    plain = search_core.search(root, query, also=list(also), limit=limit, include_sources=True)
                    self.assertEqual(list(scanned), list(plain))
                    for key in INVARIANT_KEYS:
                        self.assertEqual(scanned[key], plain[key], key)
                    self.assertTrue(scanned["coverage"]["scopes"]["sources"]["searched"])
                    self.assertIsNone(plain["exhaustive_hits"])
                    self.assertIsInstance(scanned["exhaustive_hits"], list)
            self.assertEqual(
                exhaustive(root, "Quarzit", TWO, include_sources=False)["coverage"],
                search_core.search(root, "Quarzit", also=list(TWO), include_sources=True)["coverage"],
            )
            with self.assertRaises(ValueError):
                exhaustive(root, "Quarzit", word_forms=False)
            with self.assertRaises(ValueError):
                search_core.load(root, exhaustive=True)
            with self.assertRaises(ValueError):
                search_core.search_loaded(search_core.load(root, include_sources=True), "Quarzit", exhaustive=True)

    def test_the_export_ships_no_history_and_its_check_can_be_complete(self) -> None:
        files = {**self.FILES, "meta/history/s1/wiki/a.md": page("Seite A", "Quarzit früher.")}
        with Tree(files) as root:
            report = exhaustive(root, "Quarzit", TWO, history_shipped=False, path_prefix=PREFIX)
            with self.assertRaises(ValueError):
                exhaustive(root, "Quarzit", TWO, history_shipped=False, include_history=True)
        check = report["absence_check"]
        self.assertEqual(
            check["scopes"]["history"],
            {"scanned": False, "shipped": False, "files": None, "navigation_skipped": None, "passages": None, "chars": None},
        )
        self.assertTrue(check["complete"])
        self.assertTrue(all(entry["path"].startswith(PREFIX + "wiki/") for entry in report["exhaustive_hits"]))
        self.assertEqual({entry["passages"]["history"] for entry in check["terms"]}, {None})

    def test_every_file_is_read_once_in_an_exhaustive_call(self) -> None:
        files = {
            **self.FILES,
            "sources/quelle.md": page("Quelle", "Quarzit in der Quelle.", "source"),
            "meta/questions.md": "# Fragen\n\n- Quarzit?\n",
            "meta/history/s1/wiki/a.md": page("Seite A", "Quarzit früher."),
            "schema/CONCEPTS.md": CONCEPTS,
        }
        counts: dict[str, int] = {}
        depth = [0]
        original_text, original_bytes = Path.read_text, Path.read_bytes

        def counted(original):  # noqa: ANN001, ANN202
            def read(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
                if not depth[0]:
                    counts[str(self)] = counts.get(str(self), 0) + 1
                depth[0] += 1
                try:
                    return original(self, *args, **kwargs)
                finally:
                    depth[0] -= 1
            return read

        with Tree(files) as root:
            with mock.patch.object(Path, "read_text", counted(original_text)), mock.patch.object(Path, "read_bytes", counted(original_bytes)):
                report = exhaustive(root, "Quarzit", TWO, include_history=True)
        self.assertTrue(report["exhaustive_hits"])
        self.assertEqual({path: count for path, count in counts.items() if count > 1}, {})
        self.assertGreaterEqual(len(counts), len(files) + 2)

    def test_parser_errors_skip_the_scan(self) -> None:
        files = {**self.FILES, "wiki/kaputt.md": "---\ntitle: offen\n"}
        with Tree(files) as root:
            with mock.patch.object(search_core, "scan_passages", wraps=search_core.scan_passages) as scanner:
                loaded = search_core.load(root, include_sources=True, exhaustive=True)
                report = exhaustive(root, "Quarzit", TWO)
            self.assertEqual(scanner.call_count, 0)
        self.assertIsNone(loaded.scan)
        self.assertTrue(loaded.parser_errors)
        self.assertTrue(report["parser_errors"])
        self.assertIsNone(report["exhaustive_hits"])
        self.assertEqual(report["absence_check"]["reasons"], ["not_exhaustive"])


class CommandLine(unittest.TestCase):
    """The query skill's wrapper on a released wiki."""

    ALSO = ("--also", "Messpunkt", "--also", "Zählerstand")

    @classmethod
    def setUpClass(cls) -> None:
        cls._context = TempWiki()
        cls.wiki = cls._context.__enter__()
        build_coverage_wiki(cls.wiki)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._context.__exit__(None, None, None)

    def cli(self, *arguments: str, stdin: bytes = b"", **environment: str) -> subprocess.CompletedProcess:
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", **environment})
        return subprocess.run(
            [sys.executable, "-B", str(QUERY / "search_wiki.py"), "--target", str(self.wiki.path), *arguments],
            input=stdin,
            capture_output=True,
            env=env,
        )

    def report(self, *arguments: str, stdin: bytes = b"", **environment: str) -> tuple[dict, str]:
        result = self.cli(*arguments, stdin=stdin, **environment)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        text = result.stdout.decode("utf-8")
        return json.loads(text), text

    def test_exhaustive_on_the_command_line_equals_the_core(self) -> None:
        report, text = self.report("--query", "Ablesung", *self.ALSO, "--exhaustive")
        core = search_core.search(self.wiki.path, "Ablesung", also=["Messpunkt", "Zählerstand"], exhaustive=True)
        for key in ("formulations", "results", "reformulation_results", "coverage", "absence_check", "exhaustive_hits"):
            self.assertEqual(report[key], core[key], key)
        keys = list(report)
        self.assertEqual(keys[4:7], ["release", "search_record", "absence_check"])
        self.assertEqual(keys[-1], "exhaustive_hits")
        self.assertIs(report["include_sources"], True)
        self.assertIs(report["include_sources"], report["coverage"]["scopes"]["sources"]["searched"])
        release = self.wiki.verify(query_side=True)
        self.assertEqual(report["release"]["manifest_sha256"], release["manifest_sha256"])
        line = report["search_record"]["line"]
        self.assertEqual(report["search_record"], search_core.search_record(core, report["release"]))
        self.assertTrue(line.startswith(
            f"lmwiki-search-record/1 release={release['version']} id={release['release_id']} "
            f"manifest={release['manifest_sha256'][:12]} query=\"Ablesung\" reformulations=2 ranked=wiki+sources exhaustive=true "
        ), line)
        assert_absence_identities(self, report)
        self.assertTrue(report["exhaustive_hits"])
        without = json.dumps({**report, "exhaustive_hits": None}, ensure_ascii=False, indent=2)
        self.assertEqual(len(text.rstrip("\n")) - len(without) + 4, report["absence_check"]["budget"]["used_chars"])
        plain, _ = self.report("--query", "Ablesung", *self.ALSO)
        self.assertIsNone(plain["exhaustive_hits"])
        self.assertEqual(plain["absence_check"]["reasons"], ["not_exhaustive"])
        self.assertIs(plain["include_sources"], False)
        self.assertIn(" exhaustive=false ", plain["search_record"]["line"])
        self.assertTrue(plain["search_record"]["line"].endswith(" hits=none complete=false"))

    def test_a_word_in_the_heading_of_an_empty_section_is_scanned(self) -> None:
        """register_source.py writes '## Extracted content' above an extract that starts with its own heading."""
        report, _ = self.report("--query", "Extracted content", "--also", "Inhalt", "--also", "Auszug", "--exhaustive")
        headings = [
            hit for entry in report["exhaustive_hits"] if entry["path"].startswith("sources/")
            for hit in entry["hits"] if hit["kind"] == "heading"
        ]
        self.assertTrue(headings)
        self.assertTrue(all(hit["text"] == "Extracted content" for hit in headings))

    def test_exhaustive_combines_with_a_request_and_the_request_refuses_an_exhaustive_key(self) -> None:
        request = '{"query": "Ablesung", "also": ["Messpunkt", "Z\\u00e4hlerstand"]}'.encode("ascii")
        piped, _ = self.report("--request", "-", "--exhaustive", stdin=request)
        flags, _ = self.report("--query", "Ablesung", *self.ALSO, "--exhaustive")
        self.assertEqual(piped, flags)
        refused = self.cli("--request", "-", stdin=b'{"query": "Ablesung", "exhaustive": true}')
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(refused.stdout, b"")
        self.assertIn(
            "request is invalid: unknown key 'exhaustive'; allowed keys are query, also, filter; pass --exhaustive on the command line",
            refused.stderr.decode("utf-8"),
        )
        other = self.cli("--request", "-", stdin=b'{"query": "Ablesung", "limit": 3}')
        self.assertIn(
            "request is invalid: unknown key 'limit'; allowed keys are query, also, filter\n", other.stderr.decode("utf-8")
        )

    def test_exhaustive_output_is_deterministic_across_hash_seeds(self) -> None:
        arguments = ("--query", "Messpunkt Zählerstand", "--also", "Netzbetreiber", "--also", "Ablesung", "--exhaustive")
        outputs = {self.cli(*arguments, PYTHONHASHSEED=seed).stdout for seed in ("0", "1")}
        self.assertEqual(len(outputs), 1)
        self.assertTrue(json.loads(outputs.pop().decode("utf-8"))["exhaustive_hits"])


class Instructions(unittest.TestCase):
    TEXTS = {
        "query SKILL.md": REPO / "query-llm-wiki" / "SKILL.md",
        "answer contract": REPO / "query-llm-wiki" / "references" / "answer-contract.md",
        "knowledge-skill template": REPO / "maintain-llm-wiki" / "assets" / "knowledge-skill" / "SKILL.template.md",
    }

    def test_the_absence_rule_is_verbatim_in_all_three_instruction_texts(self) -> None:
        everywhere = (
            ABSENCE_RULE, "--exhaustive", "absence_check", "search_record.line", "exhaustive_hits", "next_steps",
            "absent_terms", "100,000 characters", "at least two reformulations", "read_results_without_claims",
            "hyphen_part", "not its snippet",
        )
        texts = {label: path.read_text(encoding="utf-8") for label, path in self.TEXTS.items()}
        for label, text in texts.items():
            for phrase in everywhere:
                with self.subTest(text=label, phrase=phrase[:40]):
                    self.assertIn(phrase, text)
            self.assertEqual(text.count(ABSENCE_RULE), 1, label)
            # It stands as a paragraph of its own (indented inside a numbered step).
            self.assertRegex(text, r"\n\n {0,3}" + re.escape(ABSENCE_RULE) + r"\n", label)
        contract = texts["answer contract"]
        self.assertIn("The one exception is the exhaustive search", contract)
        self.assertIn("Do not read every directory index by reflex", contract)
        self.assertIn("the one exception to staged reading", texts["query SKILL.md"])
        for label in ("answer contract", "knowledge-skill template"):
            self.assertIn("except for the exhaustive search, which always needs at least two", texts[label])
        self.assertNotIn("meta/history/", texts["knowledge-skill template"].split("## Absence findings", 1)[1])
        for label in ("answer contract", "knowledge-skill template"):
            text = texts[label]
            # Every step of the closed vocabulary is explained, and so are the keys an agent meets in the hits.
            for word in (*search_core.ABSENCE_STEPS, *search_core.ABSENCE_REASONS):
                self.assertIn(f"`{word}`", text, f"{label}: {word}")
            for key in ("`selected`", "`hits_total`", "`text_chars`", "`pages_partial`", "`hits_already_printed`", "`reformulations_counted`"):
                self.assertIn(key, text, f"{label}: {key}")
            self.assertIn("never only add", text)
            self.assertIn("Never change the question", text)

    def test_eval_11_is_unchanged_and_the_absence_evals_exist(self) -> None:
        evals = {item["id"]: item for item in json.loads((REPO / "query-llm-wiki" / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]}
        self.assertEqual(evals[11]["prompt"], "Was steht im Wiki zu den Netzentgelten?")
        self.assertEqual(len(evals[11]["expectations"]), 4)
        for number in (20, 21, 22, 23):
            self.assertIn("search_record.line", " ".join(evals[number]["expectations"]))
        self.assertIn("--include-history", evals[23]["expected_output"])
        self.assertIn("read_results_without_claims", " ".join(evals[24]["expectations"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
