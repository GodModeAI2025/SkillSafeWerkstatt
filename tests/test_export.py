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
from unittest import mock

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
# Every maintenance-skill module that is not a reviewed exportable library.
WRITERS = {path.name for path in MAINTAIN.glob("*.py")} - set(export_wiki_skill.EXPORTABLE_LIBRARIES)


def clean_environment() -> dict[str, str]:
    """No PYTHONPATH or user site: the export has to be self-contained."""
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    for key in ("PYTHONHOME", "PYTHONPLATLIBDIR"):
        if key in os.environ:
            environment[key] = os.environ[key]
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
        encoding="utf-8",
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

    def test_package_entries_carry_the_release_time_and_fixed_modes(self) -> None:
        # The harness release is seconds old, so this cannot tell the release
        # time from the clock; PackagingFiltersOnlyHelperCaches pins that.
        snapshot = json.loads((self.skill / "references" / "SNAPSHOT.json").read_text(encoding="utf-8"))
        expected = export_wiki_skill.zip_datetime(snapshot["released_at"])
        for info in zipfile.ZipFile(self.package).infolist():
            with self.subTest(entry=info.filename):
                self.assertEqual(info.date_time, expected)
                self.assertEqual(info.external_attr, 0o100644 << 16)

    def exported_search(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", "-S", "-s", str(self.skill / "scripts" / "search_knowledge.py"), *arguments],
            capture_output=True,
            cwd=str(self.tmp),
            env=clean_environment(),
        )

    def test_the_exported_search_ranks_like_the_query_skill(self) -> None:
        """One shared core: same paths, order, scores, and coverage counts."""
        for arguments in (("--query", "Wiki"), ("--query", "Testwiki Überblick", "--include-sources", "--limit", "100")):
            with self.subTest(arguments=arguments):
                exported = self.exported_search(*arguments)
                self.assertEqual(exported.returncode, 0, exported.stderr.decode("utf-8", errors="replace"))
                report = json.loads(exported.stdout.decode("utf-8"))
                reader = subprocess.run(
                    [sys.executable, "-B", str(REPO / "query-llm-wiki" / "scripts" / "search_wiki.py"),
                     "--target", str(self.wiki.path), *arguments],
                    capture_output=True, encoding="utf-8",
                )
                self.assertEqual(reader.returncode, 0, reader.stderr)
                expected = json.loads(reader.stdout)
                self.assertTrue(report["results"])
                prefix = "references/knowledge/"
                self.assertTrue(all(item["path"].startswith(prefix) for item in report["results"]))
                self.assertEqual(
                    [(item["path"][len(prefix):], item["score"]) for item in report["results"]],
                    [(item["path"], item["score"]) for item in expected["results"]],
                )
                for key in ("matched", "returned", "truncated", "omitted_count", "query_terms", "unmatched_terms"):
                    self.assertEqual(report["coverage"][key], expected["coverage"][key], key)

    def test_the_exported_coverage_says_history_is_not_shipped(self) -> None:
        exported = self.exported_search("--query", "Wiki", "--limit", "1")
        self.assertEqual(exported.returncode, 0, exported.stderr.decode("utf-8", errors="replace"))
        coverage = json.loads(exported.stdout.decode("utf-8"))["coverage"]
        self.assertEqual(coverage["format"], "lmwiki-search-coverage/1")
        self.assertEqual(
            coverage["scopes"]["history"],
            {"searched": False, "shipped": False, "files": None, "files_with_a_query_term": None},
        )
        self.assertEqual(coverage["returned"] + coverage["omitted_count"], coverage["matched"])
        self.assertTrue(all(item["path"].startswith("references/knowledge/") for item in coverage["omitted_top"]))

    def test_the_exported_search_refuses_a_different_snapshot(self) -> None:
        verified = subprocess.run(
            [sys.executable, "-B", "-S", "-s", str(self.skill / "scripts" / "verify_knowledge.py")],
            capture_output=True, env=clean_environment(),
        )
        manifest_sha256 = json.loads(verified.stdout.decode("utf-8"))["manifest_sha256"]
        stale = self.exported_search("--query", "Wiki", "--expect-manifest-sha256", "f" * 64)
        self.assertEqual(stale.returncode, 4)
        report = json.loads(stale.stdout.decode("utf-8"))
        self.assertEqual(report["results"], [])
        self.assertEqual(report["release"]["state"], "snapshot_changed")
        self.assertEqual(report["release"]["manifest_sha256"], manifest_sha256)
        matching = self.exported_search("--query", "Wiki", "--expect-manifest-sha256", manifest_sha256)
        self.assertEqual(matching.returncode, 0, matching.stderr.decode("utf-8", errors="replace"))

    def test_the_exported_skill_file_carries_resolution_and_coverage_rules(self) -> None:
        text = (self.skill / "SKILL.md").read_text(encoding="utf-8")
        block = text.split("---", 2)[1]
        keys = {line.split(":", 1)[0] for line in block.splitlines() if line.strip()}
        self.assertEqual(keys, {"name", "description"})
        self.assertNotIn("mcp", text.lower())
        self.assertNotIn("__SKILL_", text)
        for phrase in (
            "<skill-root>/scripts/search_knowledge.py", "${CLAUDE_SKILL_DIR}", "--expect-manifest-sha256",
            "truncated", "claims_returned", "claims_total", "unmatched_terms",
            "terms_only_in_unsearched.sources", "--include-sources", "coverage.boundary",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

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
            # A release time far from now: a package stamped with the clock
            # instead of the release would show a different date here.
            export_wiki_skill.deterministic_skill_package(skill, package, "2001-02-03T04:05:06Z")
            infos = zipfile.ZipFile(package).infolist()
            self.assertEqual({info.date_time for info in infos}, {(2001, 2, 3, 4, 5, 6)})
            names = {info.filename for info in infos}
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

    def add_template_line(self, line: str, anchor: str = "from wiki_filters import validate_selector\n") -> None:
        text = self.template.read_text(encoding="utf-8")
        self.assertIn(anchor, text)
        self.template.write_text(text.replace(anchor, anchor + line + "\n", 1), encoding="utf-8")

    def treat_as_standard_library(self, module: str) -> None:
        """Simulate a reviewer wrongly listing a module as standard library."""
        text = self.exporter.read_text(encoding="utf-8")
        anchor = '"math", "pathlib", "re", "typing", "unicodedata",'
        self.assertIn(anchor, text)
        self.exporter.write_text(text.replace(anchor, anchor + f' "{module}",'), encoding="utf-8")

    def outside_module(self) -> Path:
        """A directory outside the skill that holds a module a template imports."""
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "lmwiki_outside.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.treat_as_standard_library("lmwiki_outside")
        self.add_template_line("import lmwiki_outside")
        return outside

    def assert_refused(self, result: subprocess.CompletedProcess, message: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertFalse((self.tmp / "out" / "testwissen.skill").exists())
        self.assertFalse((self.tmp / "out" / "testwissen.skill.sha256").exists())
        self.assertFalse((self.tmp / "out" / "testwissen").exists(), "a broken skill folder was left behind")

    # -- refused before anything is written ---------------------------------

    def test_an_unknown_module_is_refused_by_name(self) -> None:
        self.add_template_line("import lmwiki_module_that_does_not_exist")
        result = export(self.exporter, self.wiki.path, self.tmp / "out")
        self.assert_refused(result, "imports lmwiki_module_that_does_not_exist, which is not on the exporter's reviewed list")

    def test_an_unreviewed_standard_library_module_is_refused(self) -> None:
        # tomllib is missing before Python 3.11; os and shutil can write files.
        original = self.template.read_text(encoding="utf-8")
        for module in ("tomllib", "os", "shutil", "importlib"):
            with self.subTest(module=module):
                self.template.write_text(original, encoding="utf-8")
                self.add_template_line(f"import {module}")
                result = export(self.exporter, self.wiki.path, self.tmp / "out")
                self.assert_refused(result, f"imports {module}, which is not on the exporter's reviewed list")

    def test_relative_and_dynamic_imports_are_refused(self) -> None:
        original = self.template.read_text(encoding="utf-8")
        cases = {
            "from . import trust_contract": "relative import",
            '_tiers = __import__("trust_contract")': "imports dynamically",
        }
        for line, message in cases.items():
            with self.subTest(line=line):
                self.template.write_text(original, encoding="utf-8")
                self.add_template_line(line)
                result = export(self.exporter, self.wiki.path, self.tmp / "out")
                self.assert_refused(result, message)

    def test_a_template_module_that_is_not_an_entrypoint_is_refused(self) -> None:
        (self.template.parent / "knowledge_common.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.add_template_line("import knowledge_common")
        result = export(self.exporter, self.wiki.path, self.tmp / "out")
        self.assert_refused(result, "knowledge_common.py from the knowledge-skill templates, which is not an exported entrypoint")

    def test_an_unreviewed_library_is_refused_by_name(self) -> None:
        (self.skill_copy / "scripts" / "lmwiki_new_library.py").write_text(
            '"""A library module nobody has reviewed for exports."""\nVALUE = 1\n',
            encoding="utf-8",
        )
        self.add_template_line("import lmwiki_new_library")
        result = export(self.exporter, self.wiki.path, self.tmp / "out")
        self.assert_refused(result, "lmwiki_new_library.py, which is not a reviewed read-only library")

    def test_maintenance_helpers_and_writer_libraries_are_refused(self) -> None:
        # release_wiki has an entrypoint; navigation and portable_io write files
        # but have none, which is why the exporter uses an allowlist.
        original = self.template.read_text(encoding="utf-8")
        for module in ("release_wiki", "navigation", "portable_io"):
            with self.subTest(module=module):
                self.template.write_text(original, encoding="utf-8")
                self.add_template_line(f"import {module}")
                result = export(self.exporter, self.wiki.path, self.tmp / "out")
                self.assert_refused(result, f"{module}.py, which is not a reviewed read-only library")

    # -- caught by the self-check, the second line of defence ---------------

    def test_a_listed_module_that_is_missing_fails_the_self_check(self) -> None:
        self.treat_as_standard_library("lmwiki_module_that_does_not_exist")
        self.add_template_line("import lmwiki_module_that_does_not_exist")
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

    def test_the_self_check_covers_the_metadata_filter_path(self) -> None:
        """SKILL.md tells agents to pass --filter-json; that path must run too."""
        self.add_template_line(
            '    if selector.get("kind") != "all":\n        raise RuntimeError("filter path is broken")',
            anchor="    release = verify()\n",
        )
        result = export(self.exporter, self.wiki.path, self.tmp / "out")
        self.assert_refused(result, "self-check")

    @unittest.skipIf(sys.version_info < (3, 11), "PYTHONSAFEPATH exists from Python 3.11")
    def test_a_template_that_relies_on_the_script_folder_fails_the_self_check(self) -> None:
        """Hosts may run helpers with python -I; a template must put its own folder on sys.path."""
        text = self.template.read_text(encoding="utf-8")
        line = "    sys.path.insert(0, _SCRIPT_DIR)\n"
        self.assertIn(line, text)
        self.template.write_text(text.replace(line, "    pass\n", 1), encoding="utf-8")
        result = export(self.exporter, self.wiki.path, self.tmp / "out")
        self.assert_refused(result, "self-check")
        self.assertIn("ModuleNotFoundError", result.stderr)

    # -- every other failure after writing began also leaves nothing --------

    def test_a_refused_export_leaves_no_output_behind(self) -> None:
        # A released file that contains the absolute wiki path is refused by
        # the leak check after the folder was written; nothing may remain.
        self.wiki.write("graph/notes.txt", f"{self.wiki.path}\n")
        self.wiki.release("export-leak-1")
        result = export(self.exporter, self.wiki.path, self.tmp / "out")
        self.assert_refused(result, "leaks the absolute source path")
        again = export(self.exporter, self.wiki.path, self.tmp / "out")
        self.assertNotIn("Refusing to overwrite", again.stderr)


class SkillTemplate(unittest.TestCase):
    """The exported SKILL.md is a template file filled by plain replacement."""

    TEMPLATES = REPO / "maintain-llm-wiki" / "assets" / "knowledge-skill"

    def test_braces_and_placeholder_text_in_a_description_stay_literal(self) -> None:
        description = 'Answers {"kind": "all"} questions about {topic}, even __SKILL_NAME__ and __SKILL_DESCRIPTION__.'
        text = export_wiki_skill.skill_markdown("demo-wissen", description, self.TEMPLATES)
        self.assertTrue(text.startswith('---\nname: "demo-wissen"\ndescription: '))
        self.assertIn(export_wiki_skill.yaml_string(description), text)
        self.assertEqual(text.count("__SKILL_NAME__"), 1, "only the description's own copy remains")

    def test_a_template_without_its_placeholders_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / export_wiki_skill.SKILL_TEMPLATE
            broken.write_text("---\nname: x\ndescription: y\n---\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                export_wiki_skill.skill_markdown("demo-wissen", "Demo.", Path(directory))


class SelfCheckEnvironment(unittest.TestCase):
    def test_pythonhome_survives_and_pythonpath_does_not(self) -> None:
        patched = {"PYTHONHOME": "/opt/relocated", "PYTHONPATH": "/elsewhere", "PYTHONSTARTUP": "/x.py"}
        with mock.patch.dict(os.environ, patched):
            environment = export_wiki_skill.self_check_environment()
        self.assertEqual(environment.get("PYTHONHOME"), "/opt/relocated")
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("PYTHONSTARTUP", environment)
        self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
        # On Python 3.11+ the script folder stays off sys.path, as under python -I.
        self.assertEqual(environment["PYTHONSAFEPATH"], "1")


if __name__ == "__main__":
    unittest.main()
