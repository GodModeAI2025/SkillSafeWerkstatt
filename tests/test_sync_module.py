#!/usr/bin/env python3
"""Unit tests for the shared synchronization-artifact classifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import sync_artifacts as sa  # noqa: E402


class ConflictCopyRecognition(unittest.TestCase):
    def test_windows_device_suffix(self) -> None:
        artifact = sa.classify("wiki/concepts/governance-DESKTOP-A1B2C3.md")
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.kind, sa.CONFLICT_COPY)
        self.assertEqual(artifact.original, "wiki/concepts/governance.md")

    def test_parenthesized_conflicted_copy(self) -> None:
        artifact = sa.classify("wiki/concepts/governance (Max's conflicted copy 2026-09-06).md")
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.kind, sa.CONFLICT_COPY)

    def test_parenthesized_device_conflict(self) -> None:
        artifact = sa.classify("wiki/concepts/governance (WORKSTATION conflict).md")
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.kind, sa.CONFLICT_COPY)

    def test_an_uppercase_suffix_beside_its_base_page_is_ordinary_curation(self) -> None:
        """The decisive false positive: this must never block a wiki.

        German wikis routinely hold `energie-KRITIS` beside `energie`. Reading
        that as a conflict copy fails the lint and takes the whole wiki offline,
        whereas a missed conflict copy is merely reported as an unexpected file.
        The asymmetry is why only documented client patterns count.
        """
        for name in (
            "wiki/concepts/energie-KRITIS.md",
            "wiki/concepts/nis2-DORA.md",
            "wiki/concepts/weg-BGB.md",
            "wiki/concepts/vertrag-AGB.md",
        ):
            with self.subTest(name=name):
                self.assertIsNone(sa.classify(name))

    def test_classification_does_not_depend_on_neighbouring_files(self) -> None:
        # Whatever else exists, a name classifies the same way.
        self.assertIsNone(sa.classify("wiki/concepts/energie-wende.md"))
        self.assertEqual(
            sa.classify_all(
                ["wiki/concepts/energie.md", "wiki/concepts/energie-KRITIS.md"]
            ),
            [],
        )

    def test_a_normal_page_never_classifies(self) -> None:
        for name in (
            "wiki/index.md",
            "wiki/concepts/governance.md",
            "sources/src-0123456789abcdef-beispiel.md",
            "schema/WIKI_RULES.md",
            "graph/pages/wiki/overview.html",
        ):
            with self.subTest(name=name):
                self.assertIsNone(sa.classify(name))


class OperatingSystemArtifacts(unittest.TestCase):
    def test_known_artifacts(self) -> None:
        for name in ("sources/.DS_Store", "wiki/Thumbs.db", "wiki/desktop.ini", "wiki/~$draft.md"):
            with self.subTest(name=name):
                artifact = sa.classify(name)
                self.assertIsNotNone(artifact, name)
                self.assertTrue(artifact.ignorable, f"{name} must be ignorable")

    def test_case_insensitive(self) -> None:
        self.assertTrue(sa.is_ignorable("sources/.ds_store"))
        self.assertTrue(sa.is_ignorable("wiki/THUMBS.DB"))


class StorageRules(unittest.TestCase):
    def test_reserved_stems_with_and_without_extension(self) -> None:
        for name in ("wiki/concepts/aux.md", "wiki/concepts/CON.md", "wiki/com1.md", "wiki/NUL"):
            with self.subTest(name=name):
                artifact = sa.classify(name)
                self.assertIsNotNone(artifact, name)
                self.assertEqual(artifact.kind, sa.RESERVED_NAME)

    def test_forbidden_fragment(self) -> None:
        artifact = sa.classify("wiki/concepts/my_vti_page.md")
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.kind, sa.RESERVED_NAME)

    def test_invalid_characters(self) -> None:
        artifact = sa.classify("wiki/concepts/was ist das?.md")
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.kind, sa.INVALID_CHARACTER)

    def test_trailing_period_and_space(self) -> None:
        for name in ("wiki/concepts/seite .md", "wiki/concepts/seite."):
            with self.subTest(name=name):
                artifact = sa.classify(name)
                self.assertIsNotNone(artifact, name)
                self.assertEqual(artifact.kind, sa.TRAILING_CHARACTER)

    def test_dot_lock_is_reserved_but_the_skill_lock_is_not(self) -> None:
        reserved = sa.classify(".lock")
        self.assertIsNotNone(reserved)
        self.assertEqual(reserved.kind, sa.RESERVED_NAME)
        # The skill's own lock file must stay acceptable to the storage layer.
        self.assertIsNone(sa.classify(".llmwiki.lock"))


class PathBudget(unittest.TestCase):
    def test_relative_path_alone_stays_under_budget(self) -> None:
        self.assertEqual(sa.path_budget_findings(["wiki/concepts/kurz.md"]), [])

    def test_prefix_pushes_a_path_over_budget(self) -> None:
        relative = "wiki/concepts/governance.md"
        # Size the prefix so the total lands exactly one character over budget.
        prefix = "s" * (sa.PATH_BUDGET - len(relative))
        findings = sa.path_budget_findings([relative], prefix=prefix)
        self.assertEqual(len(findings), 1, f"expected one finding, got {findings}")
        self.assertEqual(findings[0]["characters"], sa.PATH_BUDGET + 1)

    def test_prefix_exactly_at_budget_is_accepted(self) -> None:
        relative = "wiki/concepts/governance.md"
        prefix = "s" * (sa.PATH_BUDGET - len(relative) - 1)
        self.assertEqual(sa.path_budget_findings([relative], prefix=prefix), [])

    def test_long_relative_path_is_caught_without_a_prefix(self) -> None:
        long_name = "wiki/concepts/" + "a" * 400 + ".md"
        self.assertEqual(len(sa.path_budget_findings([long_name])), 1)


class CaseCollisions(unittest.TestCase):
    def test_detects_case_only_difference(self) -> None:
        collisions = sa.case_collisions(
            ["wiki/concepts/Governance.md", "wiki/concepts/governance.md", "wiki/index.md"]
        )
        self.assertEqual(len(collisions), 1)
        self.assertEqual(len(collisions[0]["paths"]), 2)

    def test_no_false_positive(self) -> None:
        self.assertEqual(sa.case_collisions(["a.md", "b.md"]), [])


class Parity(unittest.TestCase):
    """Both skills must classify identically, so the modules must stay in step."""

    def test_query_copy_is_identical(self) -> None:
        root = Path(__file__).resolve().parent.parent
        maintain = root / "maintain-llm-wiki" / "scripts" / "sync_artifacts.py"
        query = root / "query-llm-wiki" / "scripts" / "sync_artifacts.py"
        self.assertTrue(query.is_file(), "the read skill needs the same classifier")
        self.assertEqual(
            maintain.read_bytes(),
            query.read_bytes(),
            "the two copies of sync_artifacts.py have drifted apart",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
