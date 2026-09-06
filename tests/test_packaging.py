#!/usr/bin/env python3
"""Structural integrity of both skill folders and the installable packages."""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = ("maintain-llm-wiki", "query-llm-wiki")
STANDARD_LIBRARY_ALLOWED = True


def local_imports(path: Path) -> set[str]:
    """Names imported as bare top-level modules, which must resolve locally."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


class ImportIntegrity(unittest.TestCase):
    def test_every_helper_parses(self) -> None:
        for skill in SKILLS:
            for path in sorted((REPO / skill / "scripts").glob("*.py")):
                with self.subTest(path=str(path)):
                    ast.parse(path.read_text(encoding="utf-8"), str(path))

    def test_every_local_import_exists_in_the_same_skill(self) -> None:
        for skill in SKILLS:
            scripts = REPO / skill / "scripts"
            available = {path.stem for path in scripts.glob("*.py")}
            for path in sorted(scripts.glob("*.py")):
                for name in local_imports(path):
                    if name in available:
                        continue
                    with self.subTest(script=path.name, imports=name):
                        # Anything not local must be importable from the
                        # standard library, which is the skills' only dependency.
                        result = subprocess.run(
                            [sys.executable, "-c", f"import {name}"],
                            capture_output=True,
                        )
                        self.assertEqual(
                            result.returncode,
                            0,
                            f"{skill}/scripts/{path.name} imports {name!r}, which is neither "
                            f"bundled with this skill nor in the standard library",
                        )

    def test_no_helper_depends_on_a_third_party_package(self) -> None:
        forbidden = {"yaml", "requests", "pydantic", "numpy", "frontmatter", "markdown"}
        for skill in SKILLS:
            for path in sorted((REPO / skill / "scripts").glob("*.py")):
                with self.subTest(path=path.name):
                    self.assertEqual(local_imports(path) & forbidden, set())


class SharedModuleParity(unittest.TestCase):
    """Modules both skills carry must be byte-identical, or they will diverge."""

    SHARED = ("sync_artifacts.py", "trust_contract.py")

    def test_shared_modules_are_identical(self) -> None:
        for name in self.SHARED:
            with self.subTest(module=name):
                maintain = REPO / "maintain-llm-wiki" / "scripts" / name
                query = REPO / "query-llm-wiki" / "scripts" / name
                self.assertTrue(maintain.is_file(), name)
                self.assertTrue(query.is_file(), name)
                self.assertEqual(maintain.read_bytes(), query.read_bytes(), name)

    def test_the_read_skill_carries_no_writer(self) -> None:
        """The read skill must not ship code that can change a wiki."""
        writers = {"release_wiki.py", "page_batch.py", "snapshot_wiki.py", "restore_wiki.py",
                   "frontmatter_actions.py", "verify_pages.py", "resolve_conflict_copy.py",
                   "register_source.py", "init_wiki.py", "build_graph.py", "portable_io.py"}
        present = {path.name for path in (REPO / "query-llm-wiki" / "scripts").glob("*.py")}
        self.assertEqual(
            present & writers,
            set(),
            "the read skill is read-only by construction and must ship no writer",
        )


class Packages(unittest.TestCase):
    def test_the_committed_packages_are_current(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "package_skills.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_each_package_has_exactly_one_skill_folder_as_its_root(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                names = zipfile.ZipFile(REPO / f"{skill}.skill").namelist()
                roots = {name.split("/")[0] for name in names}
                self.assertEqual(roots, {skill})

    def test_development_material_is_not_shipped(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                names = zipfile.ZipFile(REPO / f"{skill}.skill").namelist()
                self.assertFalse(
                    [name for name in names if "evals/" in name],
                    "evals are development material and the README says they are excluded",
                )
                self.assertFalse([name for name in names if "__pycache__" in name])

    def test_every_package_contains_its_skill_file_and_scripts(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                names = set(zipfile.ZipFile(REPO / f"{skill}.skill").namelist())
                self.assertIn(f"{skill}/SKILL.md", names)
                on_disk = {
                    f"{skill}/scripts/{path.name}"
                    for path in (REPO / skill / "scripts").glob("*.py")
                }
                self.assertTrue(on_disk <= names, sorted(on_disk - names))


class SkillFrontmatter(unittest.TestCase):
    def test_only_portable_fields_are_declared(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                text = (REPO / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"))
                block = text.split("---", 2)[1]
                keys = {
                    line.split(":", 1)[0].strip()
                    for line in block.splitlines()
                    if line.strip() and not line.startswith((" ", "\t"))
                }
                self.assertEqual(
                    keys,
                    {"name", "description"},
                    "the frontmatter stays portable across Claude Code, Cowork and Codex",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
