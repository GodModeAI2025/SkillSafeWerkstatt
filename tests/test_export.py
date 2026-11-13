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
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import export_wiki_skill  # noqa: E402
from harness import MAINTAIN, REPO, build_wiki  # noqa: E402


EXPORTER = MAINTAIN / "export_wiki_skill.py"
ENTRYPOINT_CALLS = {
    "verify_knowledge.py": (),
    "identity_status.py": (),
    "assess_quality.py": (),
    "search_knowledge.py": ("--query", "Testwiki"),
}
WRITERS = {
    "release_wiki.py", "page_batch.py", "snapshot_wiki.py", "restore_wiki.py",
    "frontmatter_actions.py", "verify_pages.py", "resolve_conflict_copy.py",
    "register_source.py", "init_wiki.py", "build_graph.py", "portable_io.py",
    "navigation.py", "export_wiki_skill.py", "wiki_lock.py", "run_locked.py",
}


def clean_environment() -> dict[str, str]:
    """No PYTHONPATH or user site: the export has to be self-contained."""
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def export(
    exporter: Path,
    target: Path,
    output_dir: Path,
    name: str = "testwissen",
    *,
    python: str = sys.executable,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [python, "-B", str(exporter), "--target", str(target), "--output-dir", str(output_dir), "--skill-name", name],
        capture_output=True,
        text=True,
        cwd=str(exporter.parent),
        env=env,
    )


def run_every_entrypoint(test: unittest.TestCase, skill: Path, cwd: Path) -> None:
    """Run each bundled helper the way a host does, with nothing but the stdlib."""
    for script, arguments in ENTRYPOINT_CALLS.items():
        with test.subTest(script=script, skill=str(skill)):
            result = subprocess.run(
                [sys.executable, "-B", "-S", "-s", str(skill / "scripts" / script), *arguments],
                capture_output=True,
                cwd=str(cwd),
                env=clean_environment(),
            )
            test.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
            report = json.loads(result.stdout.decode("utf-8"))
            if script == "verify_knowledge.py":
                test.assertEqual(report["state"], "ready", report)
            if script == "search_knowledge.py":
                test.assertIn("results", report)
                test.assertEqual(report["release"]["state"], "ready")


class ExportedSkillRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.mkdtemp(prefix="lmwiki-export-")
        cls.tmp = Path(cls._dir)
        (cls.tmp / "source").mkdir()
        cls.wiki = build_wiki(cls.tmp / "source")
        # A released file whose name looks like an interpreter cache is still
        # bound by the manifest and must survive packaging.
        cls.wiki.write("graph/legacy.pyc", "released data, not bytecode\n")
        cls.wiki.release("export-pyc-1")
        cls.result = export(EXPORTER, cls.wiki.path, cls.tmp / "out")
        cls.skill = cls.tmp / "out" / "testwissen"
        cls.package = cls.tmp / "out" / "testwissen.skill"

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._dir, ignore_errors=True)

    def test_the_export_succeeds(self) -> None:
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        self.assertEqual(json.loads(self.result.stdout)["state"], "exported")

    def test_every_entrypoint_runs_from_the_installed_folder_alone(self) -> None:
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(exist_ok=True)
        run_every_entrypoint(self, self.skill, elsewhere)

    def test_every_entrypoint_runs_from_the_extracted_package(self) -> None:
        """The .skill file is what users install, so it is checked on its own."""
        extracted = self.tmp / "extracted"
        with zipfile.ZipFile(self.package) as archive:
            archive.extractall(extracted)
        run_every_entrypoint(self, extracted / "testwissen", extracted)

    def test_a_released_file_named_like_a_cache_is_packaged(self) -> None:
        names = zipfile.ZipFile(self.package).namelist()
        self.assertIn("testwissen/references/knowledge/graph/legacy.pyc", names)

    def test_the_export_ships_only_reviewed_libraries(self) -> None:
        shipped = {path.name for path in (self.skill / "scripts").iterdir()}
        self.assertTrue(set(ENTRYPOINT_CALLS) <= shipped, sorted(set(ENTRYPOINT_CALLS) - shipped))
        libraries = shipped - set(ENTRYPOINT_CALLS)
        self.assertTrue(libraries <= set(export_wiki_skill.EXPORTABLE_LIBRARIES), sorted(libraries))
        # trust_contract.py is imported by wiki_filters.py; it was the module
        # the hand-written copy list forgot.
        self.assertIn("trust_contract.py", shipped)
        self.assertEqual(shipped & WRITERS, set())

    def test_no_interpreter_cache_reaches_the_helpers_in_folder_or_package(self) -> None:
        self.assertEqual(list((self.skill / "scripts").rglob("__pycache__")), [])
        names = zipfile.ZipFile(self.package).namelist()
        helpers = [name for name in names if name.startswith("testwissen/scripts/")]
        self.assertEqual([name for name in helpers if "__pycache__" in name or name.endswith(".pyc")], [])

    def test_two_exports_of_one_release_are_byte_identical(self) -> None:
        second = export(EXPORTER, self.wiki.path, self.tmp / "out-again")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(
            json.loads(second.stdout)["skill_sha256"],
            json.loads(self.result.stdout)["skill_sha256"],
        )


class PackagingFiltersOnlyHelperCaches(unittest.TestCase):
    def test_caches_beside_helpers_are_dropped_and_released_files_kept(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lmwiki-export-zip-") as directory:
            root = Path(directory)
            skill = root / "demo"
            files = {
                "SKILL.md": "x",
                "scripts/search_knowledge.py": "x",
                "scripts/__pycache__/search_knowledge.cpython-313.pyc": "x",
                "scripts/stray.pyc": "x",
                "references/knowledge/graph/legacy.pyc": "x",
                "references/knowledge/wiki/__pycache__/page.md": "x",
            }
            for relative, text in files.items():
                path = skill / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            package = root / "demo.skill"
            export_wiki_skill.deterministic_skill_package(skill, package, "2026-01-01T00:00:00Z")
            names = set(zipfile.ZipFile(package).namelist())
            self.assertEqual(
                names,
                {
                    "demo/SKILL.md",
                    "demo/scripts/search_knowledge.py",
                    "demo/references/knowledge/graph/legacy.pyc",
                    "demo/references/knowledge/wiki/__pycache__/page.md",
                },
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
        self.exporter = self.skill_copy / "scripts" / "export_wiki_skill.py"
        self.template = self.skill_copy / "assets" / "knowledge-skill" / "search_knowledge.py"

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def add_template_import(self, line: str) -> None:
        text = self.template.read_text(encoding="utf-8")
        anchor = "from wiki_filters import matches_selector, validate_selector\n"
        self.assertIn(anchor, text)
        self.template.write_text(text.replace(anchor, anchor + line + "\n"), encoding="utf-8")

    def outside_module(self) -> Path:
        """A directory outside the skill that holds the module a template imports."""
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "lmwiki_outside.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.add_template_import("import lmwiki_outside")
        return outside

    def assert_refused(self, result: subprocess.CompletedProcess, message: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertFalse((self.tmp / "out" / "testwissen.skill").exists())
        self.assertFalse((self.tmp / "out" / "testwissen").exists(), "a broken skill folder was left behind")

    def test_an_import_nothing_can_satisfy_fails_the_self_check(self) -> None:
        self.add_template_import("import lmwiki_module_that_does_not_exist")
        result = export(self.exporter, self.wiki.path, self.tmp / "out")
        self.assert_refused(result, "self-check")
        self.assertIn("search_knowledge.py", result.stderr)

    def test_a_module_on_pythonpath_cannot_satisfy_the_self_check(self) -> None:
        outside = self.outside_module()
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(outside)
        result = export(self.exporter, self.wiki.path, self.tmp / "out", env=environment)
        self.assert_refused(result, "self-check")

    def test_site_packages_cannot_satisfy_the_self_check(self) -> None:
        """A .pth file in site-packages must not hide a module the export lacks."""
        outside = self.outside_module()
        venv = self.tmp / "venv"
        created = subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(venv)], capture_output=True, text=True
        )
        if created.returncode != 0:
            self.skipTest(f"venv is unavailable: {created.stderr.strip()}")
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        purelib = subprocess.run(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        Path(purelib).mkdir(parents=True, exist_ok=True)
        (Path(purelib) / "lmwiki_outside.pth").write_text(str(outside) + "\n", encoding="utf-8")
        visible = subprocess.run([str(python), "-c", "import lmwiki_outside"], capture_output=True)
        self.assertEqual(visible.returncode, 0, "the .pth file should make the module importable normally")
        result = export(self.exporter, self.wiki.path, self.tmp / "out", python=str(python))
        self.assert_refused(result, "self-check")

    def test_an_unreviewed_library_is_refused_by_name(self) -> None:
        (self.skill_copy / "scripts" / "lmwiki_new_library.py").write_text(
            '"""A library module nobody has reviewed for exports."""\nVALUE = 1\n',
            encoding="utf-8",
        )
        self.add_template_import("import lmwiki_new_library")
        result = export(self.exporter, self.wiki.path, self.tmp / "out")
        self.assert_refused(result, "lmwiki_new_library.py, which is not a reviewed read-only library")

    def test_maintenance_helpers_and_writer_libraries_are_refused(self) -> None:
        # release_wiki has an entrypoint; navigation and portable_io write files
        # but have none, which is why the exporter uses an allowlist.
        original = self.template.read_text(encoding="utf-8")
        for module in ("release_wiki", "navigation", "portable_io"):
            with self.subTest(module=module):
                self.template.write_text(original, encoding="utf-8")
                self.add_template_import(f"import {module}")
                result = export(self.exporter, self.wiki.path, self.tmp / "out")
                self.assert_refused(result, f"{module}.py, which is not a reviewed read-only library")


if __name__ == "__main__":
    unittest.main()
