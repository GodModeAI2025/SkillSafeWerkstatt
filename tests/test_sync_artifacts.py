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
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts")
)

import sync_artifacts as sa  # noqa: E402
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


class ConflictResolutionTests(unittest.TestCase):
    """S1c: resolving a conflict copy is a confirmed, snapshotted transaction."""

    def _wiki_with_conflict(self, wiki, copy_text: str) -> str:
        wiki.write("wiki/concepts/governance.md", PAGE)
        wiki.write("wiki/concepts/governance-DESKTOP-A1B2C3.md", copy_text)
        return "wiki/concepts/governance-DESKTOP-A1B2C3.md"

    def _plan(self, wiki):
        plan_file = wiki.root / "conflict-plan.json"
        wiki.locked(
            "resolve_conflict_copy.py", "plan", "--output", str(plan_file)
        )
        return plan_file, json.loads(plan_file.read_text(encoding="utf-8"))

    def test_plan_shows_both_sides_and_changes_nothing(self) -> None:
        with TempWiki() as wiki:
            copy = self._wiki_with_conflict(wiki, PAGE + "\nZusatz aus Geraet B.\n")
            _, plan = self._plan(wiki)
            self.assertEqual(len(plan["conflicts"]), 1)
            entry = plan["conflicts"][0]
            self.assertEqual(entry["copy"]["path"], copy)
            self.assertEqual(entry["original"]["path"], "wiki/concepts/governance.md")
            self.assertFalse(entry["identical"])
            self.assertEqual(entry["recommended"], "", "a diverged copy is the user's decision")
            self.assertTrue((wiki.path / copy).is_file(), "planning must not delete anything")

    def test_an_identical_copy_is_recommended_for_removal(self) -> None:
        with TempWiki() as wiki:
            self._wiki_with_conflict(wiki, PAGE)
            _, plan = self._plan(wiki)
            entry = plan["conflicts"][0]
            self.assertTrue(entry["identical"])
            self.assertEqual(entry["recommended"], "keep-original")

    def test_apply_without_a_decision_writes_nothing(self) -> None:
        with TempWiki() as wiki:
            copy = self._wiki_with_conflict(wiki, PAGE + "\nAbweichung.\n")
            plan_file, plan = self._plan(wiki)
            result = json.loads(
                wiki.locked(
                    "resolve_conflict_copy.py", "apply",
                    "--plan-file", str(plan_file),
                    "--expect-plan-sha256", plan["plan_sha256"],
                    check=False,
                ).stdout
            )
            self.assertEqual(result["state"], "decision_required")
            self.assertEqual(result["writes"], 0)
            self.assertTrue((wiki.path / copy).is_file())

    def test_a_stale_plan_writes_nothing(self) -> None:
        with TempWiki() as wiki:
            copy = self._wiki_with_conflict(wiki, PAGE + "\nAbweichung.\n")
            plan_file, plan = self._plan(wiki)
            # The copy changes after the plan was confirmed.
            wiki.write(copy, PAGE + "\nSpaetere Abweichung.\n")
            result = json.loads(
                wiki.locked(
                    "resolve_conflict_copy.py", "apply",
                    "--plan-file", str(plan_file),
                    "--expect-plan-sha256", plan["plan_sha256"],
                    "--decision", f"{copy}=keep-original",
                    check=False,
                ).stdout
            )
            self.assertEqual(result["state"], "stale_plan")
            self.assertEqual(result["writes"], 0)
            self.assertTrue((wiki.path / copy).is_file())

    def test_keep_original_removes_the_copy_after_a_snapshot(self) -> None:
        with TempWiki() as wiki:
            copy = self._wiki_with_conflict(wiki, PAGE + "\nAbweichung.\n")
            plan_file, plan = self._plan(wiki)
            result = json.loads(
                wiki.locked(
                    "resolve_conflict_copy.py", "apply",
                    "--plan-file", str(plan_file),
                    "--expect-plan-sha256", plan["plan_sha256"],
                    "--decision", f"{copy}=keep-original",
                ).stdout
            )
            self.assertEqual(result["state"], "applied")
            self.assertFalse((wiki.path / copy).exists())
            self.assertTrue((wiki.path / "wiki/concepts/governance.md").is_file())
            snapshots = list((wiki.path / "meta/history").iterdir())
            self.assertEqual(len(snapshots), 1, "the removal must be recoverable")
            recovered = snapshots[0] / copy
            self.assertTrue(recovered.is_file(), "the discarded copy must live on in the snapshot")

    def test_keep_copy_promotes_the_copy_content(self) -> None:
        with TempWiki() as wiki:
            diverged = PAGE + "\nNur auf Geraet B.\n"
            copy = self._wiki_with_conflict(wiki, diverged)
            plan_file, plan = self._plan(wiki)
            wiki.locked(
                "resolve_conflict_copy.py", "apply",
                "--plan-file", str(plan_file),
                "--expect-plan-sha256", plan["plan_sha256"],
                "--decision", f"{copy}=keep-copy",
            )
            self.assertFalse((wiki.path / copy).exists())
            self.assertEqual(wiki.read("wiki/concepts/governance.md"), diverged)

    def test_keep_both_renames_to_a_storage_safe_name(self) -> None:
        with TempWiki() as wiki:
            copy = self._wiki_with_conflict(wiki, PAGE + "\nAbweichung.\n")
            plan_file, plan = self._plan(wiki)
            result = json.loads(
                wiki.locked(
                    "resolve_conflict_copy.py", "apply",
                    "--plan-file", str(plan_file),
                    "--expect-plan-sha256", plan["plan_sha256"],
                    "--decision", f"{copy}=keep-both",
                ).stdout
            )
            self.assertEqual(result["state"], "applied")
            self.assertFalse((wiki.path / copy).exists())
            renamed = wiki.path / "wiki/concepts/governance-konflikt.md"
            self.assertTrue(renamed.is_file())
            # The new name must itself be acceptable to the storage layer.
            self.assertIsNone(sa.classify("wiki/concepts/governance-konflikt.md"))

    def test_resolution_restores_a_readable_release(self) -> None:
        with TempWiki() as wiki:
            # A conflict copy of a file that is part of the current release.
            copy = "wiki/overview-DESKTOP-A1B2C3.md"
            wiki.write(copy, wiki.read("wiki/overview.md") + "\nAbweichung.\n")
            self.assertEqual(wiki.verify()["state"], "sync_artifacts_present")

            plan_file, plan = self._plan(wiki)
            wiki.locked(
                "resolve_conflict_copy.py", "apply",
                "--plan-file", str(plan_file),
                "--expect-plan-sha256", plan["plan_sha256"],
                "--decision", f"{copy}=keep-original",
            )
            self.assertEqual(
                wiki.verify()["state"],
                "ready",
                "resolving the copy must make the release readable again",
            )

    def test_an_unreleased_real_page_still_fails_closed(self) -> None:
        with TempWiki() as wiki:
            # Not a sync artifact: a genuine file the manifest does not describe.
            wiki.write("wiki/concepts/governance.md", PAGE)
            self.assertEqual(
                wiki.verify()["state"],
                "invalid_wiki",
                "only sync artifacts get the softer diagnosis",
            )
