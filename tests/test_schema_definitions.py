#!/usr/bin/env python3
"""One parser for the definition blocks of schema/CONCEPTS.md and schema/CLUSTERS.md.

`search_core.schema_definitions` is the only reader of both files: the search
(query skill and every new export) uses it for concepts, lint for concepts and
clusters, and build_graph.py for clusters. A level-two heading with a stable ID
starts a definition; any other ATX heading ends it. A `- Field: value` line
below such a heading belongs to no definition. Older versions applied it
silently to the definition above, so a trailing `## Hinweise` / `- Status:
draft` took a concept out of the search. Lint now reports an orphaned field of
the documented shape as an error with its line; every other wiki parses exactly
as before, which keeps the precision gate unchanged.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Optional

# The fixture's data modules are imported from inside the repository; their bytecode must not be cached there.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "search_quality"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "query-llm-wiki" / "scripts"))

import search_core  # noqa: E402
from harness import MAINTAIN, PageTree, TempWiki, Wiki, page  # noqa: E402
from test_lifecycle import SOURCE_MARKDOWN, add_cluster_and_concept, curate_page  # noqa: E402
from content.schema import CLUSTERS_MD, CONCEPTS_MD  # noqa: E402


LEGACY_HEADING = re.compile(r"^##\s+([a-z0-9]+(?:-[a-z0-9]+)*)\s*$")
LEGACY_FIELD = re.compile(r"^-\s+([A-Za-z]+):\s*(.*)$")


def legacy_definitions(text: str) -> dict[str, dict[str, Any]]:
    """The loop every parser ran before Stufe 5, kept verbatim as the reference."""
    definitions: dict[str, dict[str, Any]] = {}
    current: Optional[dict[str, Any]] = None
    fenced = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = LEGACY_HEADING.match(line)
        if heading:
            concept_id = heading.group(1)
            current = {"id": concept_id}
            definitions[concept_id] = current
            continue
        field = LEGACY_FIELD.match(line)
        if field and current is not None:
            current[field.group(1).casefold()] = field.group(2).strip()
    return definitions


def legacy_controlled_concepts(text: str) -> dict[str, dict[str, Any]]:
    return {
        concept_id: {**definition, "terms": [definition.get("preferred", "")] + search_core.split_pipe(definition.get("aliases", ""))}
        for concept_id, definition in legacy_definitions(text).items()
        if definition.get("status") == "active"
    }


def controlled_concepts_of(text: str) -> dict[str, dict[str, Any]]:
    with PageTree({"schema/CONCEPTS.md": text}) as root:
        return search_core.controlled_concepts(root / "schema/CONCEPTS.md")


SAMPLE = """---
schema_version: 1
---

# Concept worlds

Intro text.

## tarif
- Preferred: Tarif
- Status: active
- Definition: Preisgestaltung
- Aliases: Preisplan

## zaehler
- Preferred: Zähler
- Status: draft
- Definition: Messgerät
- Status: active
"""


class Parser(unittest.TestCase):
    def test_definitions_and_fields_in_file_order_with_line_numbers(self) -> None:
        definitions, orphans = search_core.schema_definitions(SAMPLE)
        self.assertEqual(
            definitions,
            [
                {"id": "tarif", "line": 9, "fields": {"preferred": "Tarif", "status": "active", "definition": "Preisgestaltung", "aliases": "Preisplan"}},
                # A repeated field keeps its last value, as before.
                {"id": "zaehler", "line": 15, "fields": {"preferred": "Zähler", "status": "active", "definition": "Messgerät"}},
            ],
        )
        self.assertEqual(orphans, [])

    def test_any_atx_heading_ends_the_open_definition(self) -> None:
        for closer in ("## Hinweise", "### Beispiele", "# Anhang", "## tarif ##", "## Access Control", "####", "######  x"):
            with self.subTest(closer=closer):
                text = SAMPLE + f"\n{closer}\n- Status: superseded\n- Aliases: Zählwerk\n"
                definitions, orphans = search_core.schema_definitions(text)
                self.assertEqual(definitions[-1]["fields"]["status"], "active")
                self.assertNotIn("aliases", definitions[-1]["fields"])
                self.assertEqual([orphan["field"] for orphan in orphans], ["status", "aliases"])

    def test_orphans_name_the_nearest_heading_and_the_closed_definition(self) -> None:
        text = SAMPLE + "\n## Notes\n\nText.\n\n### Details\n- Status: draft\n\n## next-one\n- Status: active\n"
        definitions, orphans = search_core.schema_definitions(text)
        self.assertEqual([item["id"] for item in definitions], ["tarif", "zaehler", "next-one"])
        self.assertEqual(orphans, [{"line": 26, "field": "status", "heading": "### Details", "closed": "zaehler"}])
        # A new definition clears the closer: its fields belong to it again.
        self.assertEqual(definitions[-1]["fields"], {"status": "active"})

    def test_prose_after_a_definition_produces_no_orphan(self) -> None:
        text = SAMPLE + "\n### Beispiele\nStromsperre heißt im Wiki Versorgungsunterbrechung.\n\n**Hinweis:** fett ist keine Überschrift.\n"
        self.assertEqual(search_core.schema_definitions(text)[1], [])
        # Headings before the first definition close nothing, so fields below them are no orphans.
        before = "# Titel\n\n## Erklärung\n- Status: draft\n\n## tarif\n- Status: active\n"
        definitions, orphans = search_core.schema_definitions(before)
        self.assertEqual(orphans, [])
        self.assertEqual(definitions[0]["fields"], {"status": "active"})
        # Setext headings and bold lines are no ATX headings: they do not end a definition.
        setext = "## tarif\n- Status: active\nHinweise\n--------\n- Aliases: Preisplan\n"
        self.assertEqual(search_core.schema_definitions(setext)[0][0]["fields"], {"status": "active", "aliases": "Preisplan"})

    def test_fenced_examples_are_skipped(self) -> None:
        text = "## tarif\n- Status: active\n```markdown\n## beispiel\n- Status: draft\n# Anhang\n```\n- Aliases: Preisplan\n"
        definitions, orphans = search_core.schema_definitions(text)
        self.assertEqual(definitions, [{"id": "tarif", "line": 1, "fields": {"status": "active", "aliases": "Preisplan"}}])
        self.assertEqual(orphans, [])

    def test_hash_lines_that_are_no_markdown_heading_end_nothing(self) -> None:
        # A '#' line in a tilde fence, in a nested four-backtick fence, in an HTML
        # comment over several lines, or indented by four spaces is no heading in
        # Markdown, so it keeps the definition open, as the old parse read it.
        expected = {"preferred": "Tarif", "status": "active", "aliases": "Preismodell | Stromtarif"}
        blocks = {
            "tilde fence": "~~~markdown\n# Beispiel einer Rechnung\nArbeitspreis 30 ct/kWh\n~~~\n",
            "long tilde fence": "~~~~\n~~~\n# Beispiel\n~~~\n~~~~\n",
            "nested backtick fence": "````markdown\n```\n# Beispiel\n```\n````\n",
            "html comment": "<!--\n## Alte Fassung (verworfen)\n-->\n",
            "html comment with text": "<!-- Entwurf:\n# Notiz\nnoch offen -->\n",
            "indented hash line": "    # eingerueckt ist das keine Ueberschrift\n",
        }
        for name, block in blocks.items():
            with self.subTest(block=name):
                text = "# Begriffswelten\n\n## tarif\n- Preferred: Tarif\n" + block + "- Status: active\n- Aliases: Preismodell | Stromtarif\n"
                definitions, orphans = search_core.schema_definitions(text)
                self.assertEqual(orphans, [])
                self.assertEqual([(item["id"], item["fields"]) for item in definitions], [("tarif", expected)])
                self.assertIn("tarif", controlled_concepts_of(text))
                if "comment" not in name and "indented" not in name:
                    self.assertEqual(legacy_definitions(text)["tarif"], {"id": "tarif", **expected})
        # A fence closes only with the same character, at least as long.
        text = "## tarif\n- Status: active\n~~~\n```\n- Status: draft\n~~~\n- Aliases: Preisplan\n"
        self.assertEqual(search_core.schema_definitions(text)[0][0]["fields"], {"status": "active", "aliases": "Preisplan"})
        # Up to three spaces still make a heading, and a heading still ends the definition after a comment.
        text = "## tarif\n- Status: active\n<!-- eine Zeile -->\n   ## Hinweise\n- Status: draft\n"
        self.assertEqual([orphan["line"] for orphan in search_core.schema_definitions(text)[1]], [5])

    def test_commented_out_lines_define_nothing(self) -> None:
        # A definition heading or a field inside an HTML comment is commented out: the
        # old parse applied it anyway, the shared parser skips it like a fenced example.
        text = "## tarif\n- Status: active\n<!--\n- Status: draft\n## alt\n- Status: active\n-->\n- Aliases: Preisplan\n"
        definitions, orphans = search_core.schema_definitions(text)
        self.assertEqual(definitions, [{"id": "tarif", "line": 1, "fields": {"status": "active", "aliases": "Preisplan"}}])
        self.assertEqual(orphans, [])


class Equivalence(unittest.TestCase):
    """Well-formed files parse exactly as before; this protects the precision gate."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._wiki = TempWiki()
        wiki = cls._wiki.__enter__()
        cls.concepts_template = wiki.read("schema/CONCEPTS.md")
        cls.clusters_template = wiki.read("schema/CLUSTERS.md")
        add_cluster_and_concept(wiki)
        cls.lifecycle_concepts = wiki.read("schema/CONCEPTS.md")
        cls.lifecycle_clusters = wiki.read("schema/CLUSTERS.md")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._wiki.__exit__(None, None, None)

    def variants(self) -> dict[str, str]:
        return {
            "template+fixture concepts": self.concepts_template.rstrip() + "\n" + CONCEPTS_MD,
            "template+fixture clusters": self.clusters_template.rstrip() + "\n" + CLUSTERS_MD,
            "lifecycle concepts": self.lifecycle_concepts,
            "lifecycle clusters": self.lifecycle_clusters,
        }

    def test_well_formed_files_parse_exactly_as_before(self) -> None:
        for name, text in self.variants().items():
            with self.subTest(file=name):
                definitions, orphans = search_core.schema_definitions(text)
                self.assertEqual(orphans, [])
                rebuilt = {item["id"]: {"id": item["id"], **item["fields"]} for item in definitions}
                self.assertEqual(rebuilt, legacy_definitions(text))
                self.assertTrue(rebuilt or "template" not in name)
                self.assertEqual(controlled_concepts_of(text), legacy_controlled_concepts(text))

    def test_a_fresh_wiki_has_no_orphan(self) -> None:
        for text in (self.concepts_template, self.clusters_template):
            self.assertEqual(search_core.schema_definitions(text), ([], []))


class SearchReadsTheNewWay(unittest.TestCase):
    def test_a_trailing_status_no_longer_deactivates_the_concept_above(self) -> None:
        concepts = CONCEPTS_MD.rstrip() + "\n\n## Hinweise\n- Status: draft\n"
        last = search_core.schema_definitions(CONCEPTS_MD)[0][-1]
        self.assertEqual(last["fields"]["status"], "active")
        files = {
            "schema/CONCEPTS.md": concepts,
            "wiki/topics/stoerung.md": page("Störung", "Bei einer Versorgungsunterbrechung informiert das Netz.", "topic"),
        }
        with PageTree(files) as root:
            definitions = search_core.controlled_concepts(root / "schema/CONCEPTS.md")
            self.assertIn(last["id"], definitions)
            # The old parse took it out of the search.
            self.assertNotIn(last["id"], legacy_controlled_concepts(concepts))
            preferred = last["fields"]["preferred"]
            alias = search_core.split_pipe(last["fields"]["aliases"])[0]
            report = search_core.search(root, alias)
            self.assertIn(preferred, report["expanded_terms"])


ORPHAN_CONCEPT = "\n\n## Hinweise\n\nDiese Begriffswelt ist neu.\n- Status: draft\n"
ORPHAN_CLUSTER = "\n\n### Farben\n- Color: #FC6538\n"


def lint_report(wiki: Wiki) -> dict[str, Any]:
    return json.loads(wiki.lint().stdout)


class LintAndGraph(unittest.TestCase):
    def test_lint_reports_an_orphaned_shape_field_with_its_line(self) -> None:
        with TempWiki() as wiki:
            add_cluster_and_concept(wiki)
            concepts = wiki.read("schema/CONCEPTS.md").rstrip() + ORPHAN_CONCEPT
            clusters = wiki.read("schema/CLUSTERS.md").rstrip() + ORPHAN_CLUSTER
            wiki.write("schema/CONCEPTS.md", concepts)
            wiki.write("schema/CLUSTERS.md", clusters)
            concept_line = concepts.splitlines().index("- Status: draft") + 1
            cluster_line = clusters.splitlines().index("- Color: #FC6538") + 1
            report = lint_report(wiki)
            self.assertFalse(report["valid"])
            self.assertIn(
                f"schema/CONCEPTS.md:{concept_line}: field 'status' under heading '## Hinweise' belongs to no "
                "concept; older versions applied it to concept netzentgelt. Move it above that heading if it "
                "belongs to concept netzentgelt, rename the heading to a stable lowercase ID such as "
                "'## hinweise' if it was meant to start a concept, or move the section above the first concept "
                "if it only explains",
                report["errors"],
            )
            self.assertIn(
                f"schema/CLUSTERS.md:{cluster_line}: field 'color' under heading '### Farben' belongs to no "
                "cluster; older versions applied it to cluster netz. Move it above that heading if it belongs "
                "to cluster netz, rename the heading to a stable lowercase ID such as '## farben' if it was "
                "meant to start a cluster, or move the section above the first cluster if it only explains",
                report["errors"],
            )
            self.assertEqual(len(report["errors"]), 2, report["errors"])

    def test_a_definition_heading_without_a_valid_id_is_named_as_such(self) -> None:
        # "## Preisbestandteile" with its own Preferred was meant as a concept. Moving
        # its fields into the concept above would merge the two, so the message asks
        # for a valid ID instead.
        sys.path.insert(0, str(MAINTAIN))
        try:
            import lint_wiki
        finally:
            sys.path.remove(str(MAINTAIN))
        text = (
            "## zahler\n- Preferred: Zahler\n- Status: active\n\n## Preisbestandteile\n- Preferred: Preisbestandteil\n"
            "- Status: active\n- Aliases: Arbeitspreis\n\n## Тарифы\n- Label: Тарифы\n- Status: active\n"
        )
        with PageTree({"schema/CONCEPTS.md": text, "schema/CLUSTERS.md": text}) as root:
            concept_errors: list[str] = []
            lint_wiki.load_concepts(root / "schema/CONCEPTS.md", concept_errors)
            cluster_errors: list[str] = []
            lint_wiki.load_clusters(root / "schema/CLUSTERS.md", cluster_errors, [])
        misnamed = (
            "'## Preisbestandteile' is no concept heading, because a concept needs a stable lowercase ID such as "
            "'## preisbestandteile': rename the heading if it starts a new concept, rather than moving its fields "
            "into concept zahler"
        )
        orphan_errors = [error for error in concept_errors if "belongs to no concept" in error]
        self.assertEqual([error.split(":")[1] for error in orphan_errors], ["6", "7", "8", "12"])
        for error in orphan_errors[:3]:
            self.assertTrue(error.endswith(misnamed), error)
        # Below a heading without the naming field, all three ways stay open; no ID can be made from Cyrillic.
        self.assertIn("rename the heading to a stable lowercase ID (lowercase letters, digits, and hyphens)", orphan_errors[3])
        # For clusters the naming field is Label.
        cluster_orphans = [error for error in cluster_errors if "belongs to no cluster" in error]
        self.assertTrue(cluster_orphans[-1].endswith(
            "'## Тарифы' is no cluster heading, because a cluster needs a stable lowercase ID (lowercase letters, "
            "digits, and hyphens): rename the heading if it starts a new cluster, rather than moving its fields "
            "into cluster zahler"
        ), cluster_orphans)

    def test_lint_stays_valid_with_prose_sections_and_foreign_list_items(self) -> None:
        with TempWiki() as wiki:
            source = wiki.register_source(SOURCE_MARKDOWN, "Netzentgelte 2026", "intern/netzentgelte-2026.pdf")
            add_cluster_and_concept(wiki)
            # An example in a tilde fence and a commented-out draft inside the definition end nothing.
            wiki.write("schema/CONCEPTS.md", wiki.read("schema/CONCEPTS.md").replace(
                "- Preferred: Netzentgelt\n",
                "- Preferred: Netzentgelt\n\n~~~markdown\n# Beispiel einer Rechnungszeile\nNetzentgelt 7,2 ct/kWh\n~~~\n"
                "\n<!--\n## Alte Fassung (verworfen)\n-->\n",
            ))
            for relative in ("schema/CONCEPTS.md", "schema/CLUSTERS.md"):
                wiki.write(
                    relative,
                    wiki.read(relative).rstrip()
                    + "\n\n### Beispiele\nStromsperre heißt im Wiki Versorgungsunterbrechung.\n"
                    + "\n## Notes\n- Hinweis: siehe Ticket 12\n",
                )
            wiki.write("wiki/index.md", wiki.read("wiki/index.md").rstrip() + "\n\n- [[wiki/concepts/netzentgelte|Netzentgelte]]\n")
            claim_id = json.loads(wiki.locked("claim_id.py", "--count", "1").stdout)["claim_ids"][0]
            # page_batch.py apply refuses on any lint error, so the batch applying is the proof.
            curate_page(wiki, source["source_id"], Path(source["path"]).stem, claim_id)
            wiki.rebuild()
            report = lint_report(wiki)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["stats"]["controlled_concepts"], 1)

    def test_lint_search_and_graph_read_the_same_definitions(self) -> None:
        sys.path.insert(0, str(MAINTAIN))
        try:
            import build_graph
            import lint_wiki
        finally:
            sys.path.remove(str(MAINTAIN))
        base = CLUSTERS_MD
        variants = {
            "plain": base,
            "trailing color": base.rstrip() + "\n\n## Farben\n- Color: #FC6538\n- Label: Falsch\n",
            "prose": base.rstrip() + "\n\n### Beispiele\nText.\n",
            "duplicate": base.rstrip() + "\n\n## vertrag\n- Label: Doppelt\n- Color: #84C041\n- Status: active\n- Purpose: x\n",
        }
        for name, text in variants.items():
            with self.subTest(variant=name), PageTree({"schema/CLUSTERS.md": text}) as root:
                path = root / "schema/CLUSTERS.md"
                shared = search_core.schema_definitions(text)[0]
                errors: list[str] = []
                linted = lint_wiki.load_clusters(path, errors, [])
                graphed = build_graph.parse_cluster_definitions(path)
                expected_ids = list(dict.fromkeys(item["id"] for item in shared))
                self.assertEqual(list(linted), expected_ids)
                self.assertEqual(list(graphed), expected_ids)
                last = {item["id"]: item["fields"] for item in shared}
                for cluster_id in expected_ids:
                    self.assertEqual(graphed[cluster_id]["color"], last[cluster_id]["color"])
                    self.assertEqual(linted[cluster_id]["label"], last[cluster_id]["label"])
                if name == "trailing color":
                    # The trailing field no longer sets the label or color of the last cluster.
                    final = expected_ids[-1]
                    self.assertNotEqual(graphed[final]["color"], "#FC6538")
                    self.assertNotEqual(graphed[final]["label"], "Falsch")
                    self.assertEqual(len(errors), 2, errors)
                elif name == "duplicate":
                    self.assertEqual(len(errors), 1, errors)
                    self.assertIn("duplicate cluster ID vertrag", errors[0])
                else:
                    self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
