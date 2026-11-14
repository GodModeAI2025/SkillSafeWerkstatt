#!/usr/bin/env python3
"""Alias maintenance (Stufe 3): scalar aliases and the lint statistic `stats.alias_review`.

Page aliases weigh almost as much as a title, so a common or ambiguous word as
an alias pulls its page into unrelated questions, and an alias on several pages
has no page that should rank first. Lint lists both for the user to confirm.
It is a statistic, never an error or a warning, so it never blocks a release.

A single string `aliases: Foo` is read by the shared search core as one alias
(lint warns until it is a list); any other non-list value is ignored.
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
MAINTAIN_SCRIPTS = HERE.parent / "maintain-llm-wiki" / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(MAINTAIN_SCRIPTS))

import lint_wiki  # noqa: E402
import search_core  # noqa: E402
from harness import TempWiki  # noqa: E402


def page(title: str, body: str, aliases: object = None, kind: str = "concept") -> str:
    lines = ["---", f'title: "{title}"', 'status: "active"', f'type: "{kind}"']
    if isinstance(aliases, list):
        lines.append("aliases:")
        lines += [f'  - "{alias}"' for alias in aliases]
    elif aliases is not None:
        lines.append(f"aliases: {json.dumps(aliases, ensure_ascii=False)}")
    return "\n".join(lines + ["---", "", f"# {title}", "", body, ""])


class Tree:
    """A folder with WIKI.md, a root index and the given files."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def __enter__(self) -> Path:
        self._directory = tempfile.TemporaryDirectory(prefix="lmwiki-aliases-")
        root = Path(self._directory.name)
        for relative, text in {"WIKI.md": "# Wiki\n", "wiki/index.md": page("Index", "Start.", kind="index"), **self.files}.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    def __exit__(self, *_exc: object) -> None:
        self._directory.cleanup()


def review(root: Path, concepts: dict[str, dict[str, str]] | None = None) -> dict:
    files = sorted((root / "wiki").rglob("*.md"))
    return lint_wiki.alias_review(root, files, concepts or {})


def concept(concept_id: str, aliases: str, status: str = "active") -> dict[str, dict[str, str]]:
    return {concept_id: {"id": concept_id, "preferred": concept_id.capitalize(), "status": status, "aliases": aliases}}


def filler_pages(count: int, body: str, prefix: str = "seite") -> dict[str, str]:
    return {f"wiki/{prefix}-{number:02d}.md": page(f"Seite {number}", body) for number in range(1, count + 1)}


class ScalarAliases(unittest.TestCase):
    def test_alias_values(self) -> None:
        self.assertEqual(search_core.alias_values(["Ökostrom", 5]), ["Ökostrom", "5"])
        self.assertEqual(search_core.alias_values("Ökostrom"), ["Ökostrom"])
        for value in ("", "   ", 5, None, True, {"a": 1}):
            with self.subTest(value=value):
                self.assertEqual(search_core.alias_values(value), [])

    def test_a_scalar_alias_scores_like_a_one_item_list(self) -> None:
        body = "Strom aus erneuerbaren Quellen."
        with Tree({"wiki/a.md": page("Tarif", body, "Ökostrom")}) as root:
            scalar = search_core.search(root, "Ökostrom", limit=5)
        with Tree({"wiki/a.md": page("Tarif", body, ["Ökostrom"])}) as root:
            listed = search_core.search(root, "Ökostrom", limit=5)
        self.assertTrue(scalar["results"])
        self.assertEqual(
            [(item["path"], item["score"]) for item in scalar["results"]],
            [(item["path"], item["score"]) for item in listed["results"]],
        )

    def test_a_non_string_alias_value_is_ignored(self) -> None:
        body = "Ökostrom aus erneuerbaren Quellen."
        with Tree({"wiki/a.md": page("Tarif", body, 5), "wiki/b.md": page("Liste", body, "")}) as root:
            ignored = search_core.search(root, "Ökostrom 5", limit=5)
        with Tree({"wiki/a.md": page("Tarif", body), "wiki/b.md": page("Liste", body)}) as root:
            without = search_core.search(root, "Ökostrom 5", limit=5)
        self.assertEqual(
            [(item["path"], item["score"]) for item in ignored["results"]],
            [(item["path"], item["score"]) for item in without["results"]],
        )

    def test_lint_warns_on_a_scalar_alias_and_stays_valid(self) -> None:
        with TempWiki() as wiki:
            before = json.loads(wiki.lint().stdout)
            overview = wiki.read("wiki/overview.md")
            wiki.write("wiki/overview.md", overview.replace('language: "de"\n', 'language: "de"\naliases: "Startseite"\n', 1))
            scalar = json.loads(wiki.lint().stdout)
            wiki.write("wiki/overview.md", overview.replace('language: "de"\n', 'language: "de"\naliases: 7\n', 1))
            other = json.loads(wiki.lint().stdout)
        self.assertEqual((scalar["valid"], scalar["errors"]), (before["valid"], before["errors"]))
        self.assertEqual((other["valid"], other["errors"]), (before["valid"], before["errors"]))
        self.assertEqual(
            sorted(set(scalar["warnings"]) - set(before["warnings"])),
            [
                "./wiki/overview.md: aliases is a single string, not a list; search reads it as the one alias "
                "'Startseite'. Write it as a list item through a confirmed frontmatter plan"
            ],
        )
        self.assertEqual(
            sorted(set(other["warnings"]) - set(before["warnings"])),
            ["./wiki/overview.md: aliases must be a list of strings; search ignores this value"],
        )


class AliasReview(unittest.TestCase):
    def test_the_common_threshold_is_a_tenth_and_at_least_3(self) -> None:
        for pages, threshold in ((0, 3), (10, 3), (30, 3), (31, 4), (45, 5), (4626, 463)):
            with self.subTest(pages=pages):
                self.assertEqual(lint_wiki.common_threshold(pages), threshold)

    def test_a_common_page_alias_word_is_listed_with_its_page_count(self) -> None:
        files = {
            **filler_pages(4, "Der Tarif gilt."),
            "wiki/a.md": page("Festpreis", "Preisgarantie.", ["Tarif mit Garantie", "Preisbremse"]),
            "wiki/b.md": page("Bremse", "Preisbremse gilt."),
        }
        with Tree(files) as root:
            found = review(root)
        self.assertEqual((found["format"], found["content_pages"], found["common_threshold_pages"]), ("lmwiki-alias-review/1", 6, 3))
        self.assertEqual(
            found["common_alias_words"],
            [
                {
                    "word": "tarif", "alias": "Tarif mit Garantie", "source": "page", "where": "wiki/a.md",
                    "pages_with_word": 4,
                    "message": "alias word 'tarif' ('Tarif mit Garantie' on wiki/a.md) occurs in 4 of 6 content pages; "
                    "a common word as an alias lifts this page or concept for many unrelated questions. Confirm it "
                    "with the user, narrow it, or remove it.",
                }
            ],
            "garantie and preisbremse are rare; mit is a stopword",
        )

    def test_a_common_single_word_concept_alias_is_listed_and_a_phrase_is_not(self) -> None:
        files = filler_pages(5, "Der Abschlag wird monatlich gezahlt.")
        concepts = {
            **concept("abschlagszahlung", "Abschlag | monatlicher Abschlag"),
            **concept("rabatt", "Abschlag", status="draft"),
        }
        with Tree(files) as root:
            found = review(root, concepts)
        self.assertEqual(
            [(entry["word"], entry["alias"], entry["source"], entry["where"], entry["pages_with_word"]) for entry in found["common_alias_words"]],
            [("abschlag", "Abschlag", "concept", "schema/CONCEPTS.md#abschlagszahlung", 5)],
        )

    def test_word_forms_count_toward_commonness_compounds_do_not(self) -> None:
        files = {
            "wiki/a.md": page("A", "Die Tarife gelten."),
            "wiki/b.md": page("B", "Zwei Tarifen."),
            "wiki/c.md": page("C", "Der Tarifwechsel."),
            "wiki/d.md": page("D", "Ein Stromtarif."),
            "wiki/e.md": page("E", "Ohne Bezug.", ["Tarif"]),
        }
        with Tree(files) as root:
            found = review(root)
        self.assertEqual(
            [(entry["word"], entry["pages_with_word"]) for entry in found["common_alias_words"]], [],
            "only a and b hold a form of tarif; compounds are no forms",
        )
        files["wiki/f.md"] = page("F", "Ein Tarif.")
        with Tree(files) as root:
            found = review(root)
        self.assertEqual([(entry["word"], entry["pages_with_word"]) for entry in found["common_alias_words"]], [("tarif", 3)])

    def test_navigation_pages_and_the_alias_field_do_not_count(self) -> None:
        files = {
            "wiki/index.md": page("Index", "Netz Netz Netz", kind="index"),
            "wiki/teil/index.md": page("Teil", "Netz", kind="index"),
            "wiki/a.md": page("A", "Netz hier.", ["Netz"]),
            "wiki/b.md": page("B", "Nichts.", ["Netz"]),
            "wiki/c.md": page("C", "Nichts.", ["Netz"]),
            "wiki/d.md": page("D", "Netz dort."),
        }
        with Tree(files) as root:
            found = review(root)
        self.assertEqual(found["content_pages"], 4)
        self.assertEqual(found["common_alias_words"], [], "only a and d use the word themselves")

    def test_an_alias_on_two_pages_is_listed_as_shared(self) -> None:
        files = {
            "wiki/a.md": page("A", "Text.", ["Grünstrom"]),
            "wiki/b.md": page("B", "Text.", ["GRUNSTROM", "Ökostrom"]),
            "wiki/c.md": page("C", "Text.", ["Ökostrom-Tarif"]),
            "wiki/index.md": page("Index", "Start.", ["Grünstrom"], kind="index"),
        }
        with Tree(files) as root:
            found = review(root)
        self.assertEqual(
            found["shared_aliases"],
            [
                {
                    "alias": "Grünstrom", "pages": ["wiki/a.md", "wiki/b.md"],
                    "message": "alias 'Grünstrom' is on 2 pages (wiki/a.md, wiki/b.md); give it to the one page that "
                    "should rank first, or move it to a concept in schema/CONCEPTS.md.",
                }
            ],
        )

    def test_the_alias_review_never_changes_validity_errors_or_warnings(self) -> None:
        with TempWiki() as wiki:
            before = json.loads(wiki.lint().stdout)
            overview = wiki.read("wiki/overview.md")
            wiki.write(
                "wiki/overview.md",
                overview.replace('language: "de"\n', 'language: "de"\naliases:\n  - "Überblick"\n  - "Synthese"\n', 1),
            )
            after = json.loads(wiki.lint().stdout)
        self.assertEqual(
            {key: after[key] for key in ("valid", "errors", "warnings")},
            {key: before[key] for key in ("valid", "errors", "warnings")},
        )
        review_after = after["stats"]["alias_review"]
        self.assertEqual(review_after["content_pages"], 1)
        self.assertEqual(before["stats"]["alias_review"]["shared_aliases"], [])
        self.assertEqual(review_after["format"], "lmwiki-alias-review/1")

    def test_the_alias_review_is_deterministic(self) -> None:
        files = {
            **filler_pages(4, "Tarif Netz Abschlag."),
            "wiki/a.md": page("A", "Text.", ["Netz", "Tarif", "Grünstrom"]),
            "wiki/b.md": page("B", "Text.", ["Tarif", "grünstrom"]),
        }
        script = (
            "import json, sys\n"
            f"sys.path.insert(0, {str(MAINTAIN_SCRIPTS)!r})\n"
            "from pathlib import Path\n"
            "import lint_wiki\n"
            "root = Path(sys.argv[1])\n"
            "concepts = {'abschlag': {'id': 'abschlag', 'status': 'active', 'preferred': 'Abschlag', 'aliases': 'Abschlag | Teilzahlung'}}\n"
            "print(json.dumps(lint_wiki.alias_review(root, sorted((root / 'wiki').rglob('*.md')), concepts)))\n"
        )
        with Tree(files) as root:
            outputs = set()
            for seed in ("0", "1", "77"):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", script, str(root)],
                    capture_output=True,
                    encoding="utf-8",
                    env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.add(result.stdout)
        self.assertEqual(len(outputs), 1)
        found = json.loads(outputs.pop())
        # Sorted by page count, then word, then place; one entry per word and place.
        self.assertEqual(
            [(entry["word"], entry["where"], entry["pages_with_word"]) for entry in found["common_alias_words"]],
            [
                ("abschlag", "schema/CONCEPTS.md#abschlag", 4),
                ("netz", "wiki/a.md", 4),
                ("tarif", "wiki/a.md", 4),
                ("tarif", "wiki/b.md", 4),
            ],
        )
        self.assertEqual(
            [(entry["alias"], entry["pages"]) for entry in found["shared_aliases"]],
            [("Grünstrom", ["wiki/a.md", "wiki/b.md"]), ("Tarif", ["wiki/a.md", "wiki/b.md"])],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
