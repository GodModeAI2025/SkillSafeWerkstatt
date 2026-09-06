#!/usr/bin/env python3
"""Progressive disclosure through generated directory indexes (OKF stage 2a).

A single root index grows linearly with the wiki, so orientation costs more the
larger the wiki gets - before a single page has been read. Directory indexes let
a reader load the root, choose a branch, and read only that branch.

The indexes are generated, never hand-maintained, which is the whole reason the
decision needed care: they are the first generated files inside the curated
`wiki/` namespace. See docs/lernen-von-okf-agent-memory.md for the reasoning.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import navigation  # noqa: E402
from harness import TempWiki  # noqa: E402
from test_integration import TOPICS, build_large_wiki  # noqa: E402


class Generation(unittest.TestCase):
    def test_a_directory_with_pages_gets_an_index(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            index = wiki.path / "wiki" / "concepts" / "index.md"
            self.assertTrue(index.is_file(), "concepts/ holds pages and needs an index")

    def test_an_empty_directory_gets_none(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            # entities/ exists but holds no pages in this fixture.
            self.assertFalse((wiki.path / "wiki" / "entities" / "index.md").exists())

    def test_the_index_lists_every_page_in_its_directory(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            text = wiki.read("wiki/concepts/index.md")
            for slug, title, _ in TOPICS:
                with self.subTest(page=slug):
                    self.assertIn(f"[[wiki/concepts/{slug}|{title}]]", text)

    def test_the_index_carries_each_page_description(self) -> None:
        """The description is what lets a reader choose without opening pages."""
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            text = wiki.read("wiki/concepts/index.md")
            for _, _, description in TOPICS:
                with self.subTest(description=description[:30]):
                    self.assertIn(description, text)

    def test_the_index_is_a_valid_wiki_page(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])

    def test_the_index_declares_itself_generated(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            text = wiki.read("wiki/concepts/index.md")
            self.assertIn("generated_by:", text)
            self.assertIn(navigation.GENERATOR, text)
            self.assertIn("wird bei jedem Graphlauf neu erzeugt", text.lower() + text)


class RootIndex(unittest.TestCase):
    def test_the_root_index_need_not_list_every_page(self) -> None:
        """This is the whole point: the root must stop growing with the wiki."""
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            # Replace the root's per-page entries with links to the directory index.
            wiki.write(
                "wiki/index.md",
                wiki.read("wiki/index.md").split("- [[wiki/concepts/")[0].rstrip()
                + "\n\n- [[wiki/concepts/index|Konzepte]]\n",
            )
            wiki.rebuild()
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(
                report["valid"],
                f"a page listed in its directory index must count as listed: {report['errors']}",
            )

    def test_a_page_listed_nowhere_is_still_an_error(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            # Remove the page from its directory index and from the root.
            index = wiki.path / "wiki" / "concepts" / "index.md"
            index.write_text(
                "\n".join(
                    line
                    for line in index.read_text(encoding="utf-8").splitlines()
                    if "netzentgelte" not in line
                )
                + "\n",
                encoding="utf-8",
            )
            wiki.write(
                "wiki/index.md",
                "\n".join(
                    line
                    for line in wiki.read("wiki/index.md").splitlines()
                    if "netzentgelte" not in line
                )
                + "\n",
            )
            report = json.loads(wiki.lint().stdout)
            self.assertFalse(report["valid"])
            self.assertTrue(
                any("netzentgelte" in item and "does not list" in item for item in report["errors"]),
                report["errors"],
            )

    def test_every_page_is_reachable_through_exactly_one_branch(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            branch = wiki.read("wiki/concepts/index.md")
            self.assertEqual(
                sum(1 for slug, _, _ in TOPICS if f"wiki/concepts/{slug}|" in branch),
                len(TOPICS),
            )


class Staleness(unittest.TestCase):
    def test_a_stale_index_is_reported(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            index = wiki.path / "wiki" / "concepts" / "index.md"
            index.write_text(
                index.read_text(encoding="utf-8").replace("Netzentgelte", "Falscher Titel", 1),
                encoding="utf-8",
            )
            report = json.loads(wiki.lint().stdout)
            self.assertFalse(report["valid"])
            self.assertTrue(
                any("index" in item and "stale" in item.lower() for item in report["errors"]),
                report["errors"],
            )

    def test_rebuilding_restores_a_hand_edited_index(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            index = wiki.path / "wiki" / "concepts" / "index.md"
            original = index.read_text(encoding="utf-8")
            index.write_text(original + "\nHandgeschriebener Zusatz.\n", encoding="utf-8")
            wiki.rebuild()
            self.assertEqual(
                index.read_text(encoding="utf-8"),
                original,
                "a generated index is rebuilt, so hand edits do not survive",
            )

    def test_generation_is_deterministic(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            first = wiki.read("wiki/concepts/index.md")
            wiki.rebuild()
            self.assertEqual(wiki.read("wiki/concepts/index.md"), first)


class ReleaseAndRead(unittest.TestCase):
    def test_the_indexes_travel_with_a_release(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            wiki.release("nav-1")
            manifest = json.loads(wiki.read("meta/manifest.json"))
            paths = {entry["path"] for entry in manifest["files"]}
            self.assertIn("wiki/concepts/index.md", paths)
            self.assertEqual(wiki.verify()["state"], "ready")

    def test_a_directory_index_is_not_exported_as_an_okf_concept(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            wiki.release("nav-2")
            destination = wiki.root / "bundle"
            result = wiki.maintain(
                "export_okf_bundle.py",
                "--target", str(wiki.path), "--destination", str(destination),
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(
                (destination / "concepts" / "index.md").exists(),
                "OKF generates its own root index; a wiki index has no OKF role",
            )


class BackwardCompatibility(unittest.TestCase):
    def test_a_wiki_without_subdirectory_pages_is_unaffected(self) -> None:
        with TempWiki() as wiki:
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertFalse((wiki.path / "wiki" / "concepts" / "index.md").exists())

    def test_a_root_index_that_lists_everything_still_passes(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            # The fixture's root lists every page directly, as before this change.
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])


class Economics(unittest.TestCase):
    """What staged orientation actually buys, measured rather than asserted.

    The saving is not unconditional. A branch index carries a description per
    page, so for a handful of pages in a single group it costs more than a flat
    root. Two properties do hold, and they are what the change is for.
    """

    def _staged_root(self, wiki) -> str:
        kept = [
            line for line in wiki.read("wiki/index.md").splitlines()
            if "wiki/concepts/" not in line
        ]
        return "\n".join(kept).rstrip() + "\n- [[wiki/concepts/index|Konzepte]]\n"

    def test_a_staged_root_does_not_grow_when_pages_are_added(self) -> None:
        """The scaling property: orientation cost stops tracking wiki size."""
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            before = len(self._staged_root(wiki))

            # Add another page to the same group and rebuild.
            extra = wiki.path / "wiki" / "concepts" / "zusatz.md"
            template = (wiki.path / "wiki" / "concepts" / "lastgang.md").read_text(
                encoding="utf-8"
            )
            extra.write_text(
                template.replace("concept-lastgang", "concept-zusatz").replace(
                    "Lastgang", "Zusatz"
                ),
                encoding="utf-8",
            )
            wiki.rebuild()

            after = len(self._staged_root(wiki))
            self.assertEqual(
                before, after, "a root that links to branches must not grow with the pages"
            )
            self.assertIn("Zusatz", wiki.read("wiki/concepts/index.md"))

    def test_a_branch_index_is_far_smaller_than_the_pages_it_describes(self) -> None:
        """Why disclosure works: choose from the index, open only what is needed."""
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            branch = len(wiki.read("wiki/concepts/index.md"))
            pages = sum(
                len(wiki.read(f"wiki/concepts/{slug}.md")) for slug, _, _ in TOPICS
            )
            self.assertLess(
                branch,
                pages / 2,
                f"the index ({branch}) must be much cheaper than reading every page ({pages})",
            )

    def test_the_common_case_is_not_repeated_on_every_line(self) -> None:
        """Status and tier are noise when they match the norm on every page."""
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            text = wiki.read("wiki/concepts/index.md")
            self.assertNotIn(
                "— active —", text, "an active page is the norm and needs no label"
            )

    def test_a_page_that_deviates_is_labelled(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            plan_file = wiki.root / "verify.json"
            wiki.locked(
                "verify_pages.py", "plan",
                "--actor", "human:mzi",
                "--page", "wiki/concepts/netzentgelte.md",
                "--output", str(plan_file),
            )
            plan = json.loads(plan_file.read_text(encoding="utf-8"))
            wiki.locked(
                "verify_pages.py", "apply",
                "--plan-file", str(plan_file),
                "--expect-plan-sha256", plan["plan_sha256"],
                "--user-confirmed-human-review",
            )
            wiki.rebuild()
            text = wiki.read("wiki/concepts/index.md")
            self.assertIn("human-reviewed", text, "the exception must be visible")
            self.assertEqual(text.count("human-reviewed"), 1, "only the page that has it")

    def test_a_long_description_is_capped(self) -> None:
        entry = {
            "link": "wiki/concepts/x",
            "title": "X",
            "description": "wort " * 100,
            "status": "active",
            "trust_tier": "unverified",
        }
        line = navigation.render_entry(entry)
        self.assertLess(len(line), navigation.DESCRIPTION_BUDGET + 60)
        self.assertTrue(line.endswith("…"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
