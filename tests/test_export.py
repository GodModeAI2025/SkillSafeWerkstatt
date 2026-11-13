#!/usr/bin/env python3
"""The exported frozen knowledge skill must actually run, not merely verify.

Until these tests existed nothing exercised the exporter: the exported search
imported a module the exporter did not copy, and every export still reported
`exported` because its self-check ran only the integrity verifier.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from harness import MAINTAIN, REPO, build_wiki


EXPORTER = MAINTAIN / "export_wiki_skill.py"
ENTRYPOINTS = ("verify_knowledge.py", "search_knowledge.py", "assess_quality.py", "identity_status.py")
WRITERS = {
    "release_wiki.py", "page_batch.py", "snapshot_wiki.py", "restore_wiki.py",
    "frontmatter_actions.py", "verify_pages.py", "resolve_conflict_copy.py",
    "register_source.py", "init_wiki.py", "build_graph.py", "portable_io.py",
    "export_wiki_skill.py", "wiki_lock.py", "run_locked.py",
}


def clean_environment() -> dict[str, str]:
    """No PYTHONPATH or user site: the export has to be self-contained."""
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def export(exporter: Path, target: Path, output_dir: Path, name: str = "testwissen") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(exporter), "--target", str(target), "--output-dir", str(output_dir), "--skill-name", name],
        capture_output=True,
        text=True,
        cwd=str(exporter.parent),
    )


class ExportedSkillRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.mkdtemp(prefix="lmwiki-export-")
        cls.tmp = Path(cls._dir)
        (cls.tmp / "source").mkdir()
        cls.wiki = build_wiki(cls.tmp / "source")
        cls.result = export(EXPORTER, cls.wiki.path, cls.tmp / "out")
        cls.skill = cls.tmp / "out" / "testwissen"

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._dir, ignore_errors=True)

    def test_the_export_succeeds(self) -> None:
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        self.assertEqual(json.loads(self.result.stdout)["state"], "exported")

    def test_every_entrypoint_runs_from_the_installed_folder_alone(self) -> None:
        calls = {
            "verify_knowledge.py": (),
            "identity_status.py": (),
            "assess_quality.py": (),
            "search_knowledge.py": ("--query", "Testwiki"),
        }
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(exist_ok=True)
        for script, arguments in calls.items():
            with self.subTest(script=script):
                result = subprocess.run(
                    [sys.executable, "-B", "-s", str(self.skill / "scripts" / script), *arguments],
                    capture_output=True,
                    cwd=str(elsewhere),
                    env=clean_environment(),
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
                report = json.loads(result.stdout.decode("utf-8"))
                if script == "search_knowledge.py":
                    self.assertIn("results", report)
                    self.assertEqual(report["release"]["state"], "ready")

    def test_the_export_ships_its_import_closure_and_no_helper_of_the_maintainer(self) -> None:
        shipped = {path.name for path in (self.skill / "scripts").iterdir()}
        self.assertTrue(set(ENTRYPOINTS) <= shipped, sorted(set(ENTRYPOINTS) - shipped))
        # trust_contract.py is imported by wiki_filters.py; it was the module
        # the hand-written copy list forgot.
        self.assertIn("trust_contract.py", shipped)
        self.assertEqual(shipped & WRITERS, set())
        self.assertEqual({name for name in shipped if not name.endswith(".py")}, set())

    def test_no_interpreter_cache_reaches_the_folder_or_the_package(self) -> None:
        self.assertEqual(list(self.skill.rglob("__pycache__")), [])
        names = zipfile.ZipFile(self.tmp / "out" / "testwissen.skill").namelist()
        self.assertEqual([name for name in names if "__pycache__" in name or name.endswith(".pyc")], [])

    def test_two_exports_of_one_release_are_byte_identical(self) -> None:
        second = export(EXPORTER, self.wiki.path, self.tmp / "out-again")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(
            json.loads(second.stdout)["skill_sha256"],
            json.loads(self.result.stdout)["skill_sha256"],
        )


class ExportRefusesABrokenSkill(unittest.TestCase):
    """A template change that would break the exported skill must stop the export."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix="lmwiki-export-guard-")
        self.tmp = Path(self._dir)
        (self.tmp / "source").mkdir()
        self.wiki = build_wiki(self.tmp / "source")
        self.skill_copy = self.tmp / "maintain-llm-wiki"
        shutil.copytree(
            REPO / "maintain-llm-wiki",
            self.skill_copy,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "evals"),
        )
        self.template = self.skill_copy / "assets" / "knowledge-skill" / "search_knowledge.py"

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def add_template_import(self, line: str) -> None:
        text = self.template.read_text(encoding="utf-8")
        anchor = "from wiki_filters import matches_selector, validate_selector\n"
        self.assertIn(anchor, text)
        self.template.write_text(text.replace(anchor, anchor + line + "\n"), encoding="utf-8")

    def test_an_import_nothing_can_satisfy_fails_the_self_check(self) -> None:
        self.add_template_import("import lmwiki_module_that_does_not_exist")
        result = export(self.skill_copy / "scripts" / "export_wiki_skill.py", self.wiki.path, self.tmp / "out")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("self-check", result.stderr)
        self.assertIn("search_knowledge.py", result.stderr)
        self.assertFalse((self.tmp / "out" / "testwissen.skill").exists())

    def test_a_new_library_import_is_copied_without_editing_the_exporter(self) -> None:
        (self.skill_copy / "scripts" / "lmwiki_new_library.py").write_text(
            '"""A library module the exporter has never heard of."""\nVALUE = 1\n',
            encoding="utf-8",
        )
        self.add_template_import("import lmwiki_new_library")
        result = export(self.skill_copy / "scripts" / "export_wiki_skill.py", self.wiki.path, self.tmp / "out")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.tmp / "out" / "testwissen" / "scripts" / "lmwiki_new_library.py").is_file())

    def test_a_template_that_imports_a_maintenance_helper_is_refused(self) -> None:
        self.add_template_import("import release_wiki")
        result = export(self.skill_copy / "scripts" / "export_wiki_skill.py", self.wiki.path, self.tmp / "out")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("executable helper", result.stderr)
        self.assertFalse((self.tmp / "out" / "testwissen").exists())


if __name__ == "__main__":
    unittest.main()
