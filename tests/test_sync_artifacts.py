#!/usr/bin/env python3
"""Behaviour of the skills on a synchronized OneDrive or SharePoint folder.

Every test here mirrors one finding from docs/sharepoint-onedrive-implikationen.md.
The synchronization client is simulated by writing exactly the files a real client
would create: conflict copies named after the device, and operating-system
artifacts.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import TempWiki  # noqa: E402


PAGE = """---
id: "concept-governance"
title: "Governance"
type: "concept"
status: "active"
created: "2026-09-06"
updated: "2026-09-06"
description: "Testseite fuer Konfliktkopien."
language: "de"
sources: []
---

# Governance

Inhalt.
"""


class ConflictCopyTests(unittest.TestCase):
    """B1: a sync conflict copy must not present as a broken release."""

    def test_conflict_copy_does_not_report_invalid_wiki(self) -> None:
        with TempWiki() as wiki:
            self.assertEqual(wiki.verify()["state"], "ready")
            # OneDrive resolves a conflict by keeping both copies and renaming
            # one after the device. The copy lands in the same directory.
            wiki.write("wiki/concepts/governance-DESKTOP-A1B2C3.md", PAGE)

            state = wiki.verify()
            self.assertNotEqual(
                state["state"],
                "invalid_wiki",
                "a sync conflict copy must not make an intact release unreadable",
            )
            self.assertEqual(state["state"], "sync_artifacts_present")
            self.assertTrue(
                any(
                    "governance-DESKTOP-A1B2C3.md" in str(item)
                    for item in state.get("sync_artifacts", [])
                ),
                f"the offending file must be named in the result: {state}",
            )

    def test_conflict_copy_is_reported_as_such_by_the_linter(self) -> None:
        with TempWiki() as wiki:
            wiki.write("wiki/concepts/governance.md", PAGE)
            wiki.write("wiki/concepts/governance-DESKTOP-A1B2C3.md", PAGE)
            report = json.loads(wiki.lint().stdout)
            joined = " ".join(report["errors"])
            self.assertIn(
                "conflict copy",
                joined.lower(),
                f"the linter must name the sync artifact, not a duplicate id: {report['errors']}",
            )

    def test_query_side_verify_agrees_with_maintenance_side(self) -> None:
        with TempWiki() as wiki:
            wiki.write("wiki/concepts/governance-DESKTOP-A1B2C3.md", PAGE)
            self.assertEqual(
                wiki.verify()["state"],
                wiki.verify(query_side=True)["state"],
                "both skills must classify the same directory identically",
            )


class OperatingSystemArtifactTests(unittest.TestCase):
    """B6: lint, release and verify must treat the same artifact identically."""

    def test_ds_store_in_sources_is_not_reported_as_a_binary_original(self) -> None:
        with TempWiki() as wiki:
            (wiki.path / "sources" / ".DS_Store").write_bytes(b"\x00\x01macos")
            report = json.loads(wiki.lint().stdout)
            joined = " ".join(report["errors"])
            self.assertNotIn(
                "must remain outside the wiki",
                joined,
                f"a macOS artifact is not a smuggled original file: {report['errors']}",
            )

    def test_ds_store_does_not_block_a_release(self) -> None:
        with TempWiki() as wiki:
            (wiki.path / "sources" / ".DS_Store").write_bytes(b"\x00\x01macos")
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(
                report["valid"],
                f"opening sources/ in Finder must not block maintenance: {report['errors']}",
            )

    def test_desktop_ini_never_enters_a_release_manifest(self) -> None:
        with TempWiki() as wiki:
            (wiki.path / "wiki" / "desktop.ini").write_text("[.ShellClassInfo]\n", encoding="utf-8")
            result = wiki.release("test-desktop-ini")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads(wiki.read("meta/manifest.json"))
            paths = [entry["path"] for entry in manifest["files"]]
            self.assertNotIn(
                "wiki/desktop.ini",
                paths,
                "a Windows shell artifact must never be hashed into a release",
            )

    def test_thumbs_db_is_reported_but_never_blocks_a_reader(self) -> None:
        with TempWiki() as wiki:
            (wiki.path / "wiki" / "Thumbs.db").write_bytes(b"\x00thumbs")
            state = wiki.verify()
            self.assertEqual(
                state["state"],
                "ready",
                "operating-system noise must not take a wiki offline",
            )
            self.assertTrue(
                any("Thumbs.db" in item["path"] for item in state.get("ignored_artifacts", [])),
                f"the artifact must still be disclosed: {state}",
            )


class ReservedNameTests(unittest.TestCase):
    """B8: names the storage layer rejects must be detected before they spread."""

    def test_reserved_windows_name_is_reported(self) -> None:
        with TempWiki() as wiki:
            wiki.write("wiki/concepts/aux.md", PAGE)
            report = json.loads(wiki.lint().stdout)
            storage = [
                message
                for message in report["errors"]
                if "aux.md" in message and "refuse" in message.lower()
            ]
            self.assertTrue(
                storage,
                f"a name the storage layer rejects must be named as such: {report['errors']}",
            )

    def test_invalid_character_is_reported(self) -> None:
        with TempWiki() as wiki:
            wiki.write("wiki/concepts/frage?.md", PAGE)
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(
                any("frage?" in message and "refuse" in message.lower() for message in report["errors"]),
                report["errors"],
            )

    def test_case_only_collision_is_reported(self) -> None:
        with TempWiki() as wiki:
            wiki.write("wiki/concepts/Governance.md", PAGE)
            wiki.write("wiki/concepts/governance.md", PAGE)
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(
                any("differ only in case" in message for message in report["errors"]),
                report["errors"],
            )

    def test_a_clean_wiki_reports_no_storage_findings(self) -> None:
        with TempWiki() as wiki:
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(
                [m for m in report["errors"] + report["warnings"] if "refuse" in m.lower()],
                [],
                "an untouched wiki must not trigger storage findings",
            )

    def test_tilde_dollar_prefix_is_an_artifact_not_a_page(self) -> None:
        with TempWiki() as wiki:
            wiki.write("wiki/concepts/~$governance.md", PAGE)
            state = wiki.verify()
            self.assertEqual(state["state"], "ready")
            self.assertTrue(
                any("~$governance" in item["path"] for item in state.get("ignored_artifacts", []))
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
