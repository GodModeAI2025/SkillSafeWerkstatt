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


class LandingPage(unittest.TestCase):
    """The published page must not point at sections that do not exist."""

    def _html(self) -> str:
        return (REPO / "index.html").read_text(encoding="utf-8")

    def test_every_navigation_anchor_resolves(self) -> None:
        import re

        html = self._html()
        ids = set(re.findall(r'id="([a-zA-Z0-9_-]+)"', html))
        anchors = set(re.findall(r'href="#([a-zA-Z0-9_-]+)"', html))
        self.assertTrue(anchors, "the page should have in-page navigation")
        self.assertEqual(
            sorted(anchors - ids), [], "navigation points at sections that do not exist"
        )

    def test_the_downloads_exist(self) -> None:
        import re

        for name in re.findall(r'href="([^"]+\.skill)"', self._html()):
            with self.subTest(download=name):
                self.assertTrue((REPO / name).is_file(), name)

    def test_the_page_parses(self) -> None:
        import html.parser

        class Strict(html.parser.HTMLParser):
            def error(self, message: str) -> None:  # pragma: no cover - defensive
                raise AssertionError(message)

        Strict().feed(self._html())


class Documentation(unittest.TestCase):
    """The README must describe the capabilities that actually exist."""

    def test_the_readme_covers_every_maintenance_helper_group(self) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for topic in (
            "Vertrauensstufe",
            "Konfliktkopie",
            "Open Knowledge Format",
            "storage_path_prefix",
            "hydration_required",
        ):
            with self.subTest(topic=topic):
                self.assertIn(topic, readme)

    def test_the_readme_links_only_to_files_that_exist(self) -> None:
        import re

        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#:]+)\)", readme):
            if target.startswith(("http", "//", "mailto")):
                continue
            with self.subTest(link=target):
                self.assertTrue((REPO / target).exists(), target)


class SkillOnly(unittest.TestCase):
    """No server, service, or background process - a deliberate product limit.

    A wiki is a directory of Markdown files; anything that can read it can use
    it. A server component would add operating, update, and attack surface the
    format does not need, and would weaken the guarantee that a wiki stays fully
    readable without running software. This test exists because that kind of
    boundary erodes quietly.
    """

    #: Ways a helper could grow a server or long-running component.
    FORBIDDEN_IMPORTS = {
        "socketserver",
        "http",
        "asyncio",
        "threading",
        "multiprocessing",
        "wsgiref",
        "xmlrpc",
        "ftplib",
        "smtpd",
    }

    def test_no_helper_starts_a_server_or_background_process(self) -> None:
        for skill in SKILLS:
            for path in sorted((REPO / skill / "scripts").glob("*.py")):
                with self.subTest(path=f"{skill}/{path.name}"):
                    offending = local_imports(path) & self.FORBIDDEN_IMPORTS
                    self.assertEqual(
                        offending,
                        set(),
                        f"{path.name} imports {sorted(offending)}; this distribution is "
                        f"skill-only and ships no server or background process",
                    )

    def test_no_helper_opens_a_listening_socket(self) -> None:
        import re

        listener = re.compile(r"\.(?:listen|bind)\s*\(|serve_forever|socket\.socket")
        for skill in SKILLS:
            for path in sorted((REPO / skill / "scripts").glob("*.py")):
                with self.subTest(path=f"{skill}/{path.name}"):
                    self.assertIsNone(
                        listener.search(path.read_text(encoding="utf-8")),
                        f"{path.name} appears to open a socket; the distribution is skill-only",
                    )

    def test_no_skill_advertises_an_mcp_endpoint(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                text = (REPO / skill / "SKILL.md").read_text(encoding="utf-8").lower()
                self.assertNotIn(
                    "mcp",
                    text,
                    "the skills must not offer an endpoint this distribution does not ship",
                )

    def test_the_readme_states_the_boundary(self) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("Skill-only", readme)
        self.assertIn("Keine Erweiterung führt einen Server", readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
