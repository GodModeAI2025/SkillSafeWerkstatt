#!/usr/bin/env python3
"""Structural integrity of both skill folders and the installable packages."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
SKILLS = ("maintain-llm-wiki", "query-llm-wiki")
STANDARD_LIBRARY_ALLOWED = True
# Helpers the exporter copies into every frozen knowledge skill. They resolve
# their imports against themselves plus the maintenance skill's library modules.
KNOWLEDGE_TEMPLATES = REPO / "maintain-llm-wiki" / "assets" / "knowledge-skill"
# The README promises Python 3.9 or newer.
OLDEST_PYTHON = (3, 9)


def oldest_available_python() -> Optional[str]:
    """The oldest interpreter between 3.9 and 3.11 on PATH, verified by asking it."""
    for minor in (9, 10, 11):
        candidate = shutil.which(f"python3.{minor}")
        if not candidate:
            continue
        probe = subprocess.run(
            [candidate, "-I", "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0 and probe.stdout.split() == ["3", str(minor)]:
            return candidate
    return None


def every_helper() -> list[Path]:
    paths = [path for skill in SKILLS for path in sorted((REPO / skill / "scripts").glob("*.py"))]
    return paths + sorted(KNOWLEDGE_TEMPLATES.glob("*.py"))


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

    def test_every_knowledge_skill_template_resolves_its_imports(self) -> None:
        """The exported skill's helpers were outside every static check before."""
        available = {path.stem for path in KNOWLEDGE_TEMPLATES.glob("*.py")}
        available |= {path.stem for path in (REPO / "maintain-llm-wiki" / "scripts").glob("*.py")}
        for path in sorted(KNOWLEDGE_TEMPLATES.glob("*.py")):
            for name in local_imports(path):
                if name in available:
                    continue
                with self.subTest(template=path.name, imports=name):
                    result = subprocess.run([sys.executable, "-c", f"import {name}"], capture_output=True)
                    self.assertEqual(
                        result.returncode,
                        0,
                        f"knowledge-skill template {path.name} imports {name!r}, which is neither a "
                        f"bundled template or library module nor in the standard library",
                    )

    def test_every_helper_parses_with_the_oldest_supported_grammar(self) -> None:
        """Catches what `feature_version` detects (match, except*, type statements).

        It does not catch PEP 701 f-strings or star-unpacking in subscripts on a
        newer parser; the compile test below does, where an old Python exists.
        """
        for path in every_helper():
            with self.subTest(path=str(path.relative_to(REPO))):
                ast.parse(path.read_text(encoding="utf-8"), str(path), feature_version=OLDEST_PYTHON)

    def test_every_helper_compiles_on_the_oldest_available_python(self) -> None:
        interpreter = oldest_available_python()
        if interpreter is None:
            self.skipTest("no Python 3.9 to 3.11 on PATH; newer-only grammar such as PEP 701 f-strings is unchecked")
        program = "import sys\nfor p in sys.argv[1:]:\n    compile(open(p, encoding='utf-8').read(), p, 'exec')\n"
        result = subprocess.run(
            [interpreter, "-I", "-c", program, *map(str, every_helper())], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, f"{interpreter}: {result.stderr}")

    def test_no_helper_depends_on_a_third_party_package(self) -> None:
        forbidden = {"yaml", "requests", "pydantic", "numpy", "frontmatter", "markdown"}
        for path in every_helper():
            with self.subTest(path=str(path.relative_to(REPO))):
                self.assertEqual(local_imports(path) & forbidden, set())


class ExportableLibraries(unittest.TestCase):
    """Code the exporter copies into a frozen skill stays read-only.

    The exporter itself refuses imports outside its reviewed lists; this test
    keeps the reviewed files honest. It reads the lists the way the exporter
    uses them, at runtime, and scans the templates as well as the libraries.
    """

    # Names whose mere presence means file writing, processes, or sockets.
    FORBIDDEN_NAMES = ("shutil", "tempfile", "subprocess", "socket", "portable_io", "atomic_write")
    # pathlib and file-object methods that create, change, or delete files.
    WRITE_METHODS = {
        "write_text", "write_bytes", "write", "writelines", "mkdir", "makedirs", "touch", "unlink",
        "rmdir", "remove", "symlink_to", "hardlink_to", "link_to", "chmod", "lchmod", "truncate",
    }
    # Path.replace(target) and Path.rename(target) take exactly one argument;
    # str.replace and datetime.replace do not, so they stay allowed.
    ONE_ARGUMENT_WRITES = {"replace", "rename"}

    def write_calls(self, path: Path) -> list[str]:
        found = [name for name in self.FORBIDDEN_NAMES if name in path.read_text(encoding="utf-8")]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
            if isinstance(function, ast.Name) and name in {"exec", "eval", "compile", "__import__"}:
                found.append(f"{name}() at line {node.lineno}")
            if name == "open":
                position = 1 if isinstance(function, ast.Name) else 0
                mode_nodes = [keyword.value for keyword in node.keywords if keyword.arg == "mode"]
                if len(node.args) > position:
                    mode_nodes.append(node.args[position])
                for mode in mode_nodes:
                    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)) or set(mode.value) & set("wax+"):
                        found.append(f"open() for writing at line {node.lineno}")
            if isinstance(function, ast.Attribute):
                if name in self.WRITE_METHODS:
                    found.append(f".{name}() at line {node.lineno}")
                if name in self.ONE_ARGUMENT_WRITES and len(node.args) == 1 and not node.keywords:
                    found.append(f".{name}(target) at line {node.lineno}")
        return found

    @staticmethod
    def exporter():
        sys.path.insert(0, str(REPO / "maintain-llm-wiki" / "scripts"))
        import export_wiki_skill

        return export_wiki_skill

    def exported_files(self) -> list[Path]:
        exporter = self.exporter()
        libraries = [REPO / "maintain-llm-wiki" / "scripts" / name for name in exporter.EXPORTABLE_LIBRARIES]
        templates = [KNOWLEDGE_TEMPLATES / name for name in exporter.TEMPLATE_ENTRYPOINTS]
        return templates + libraries

    def test_the_exporter_uses_its_reviewed_lists_unchanged(self) -> None:
        source = (REPO / "maintain-llm-wiki" / "scripts" / "export_wiki_skill.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                self.assertNotIn(node.target.id, {"EXPORTABLE_LIBRARIES", "EXPORTED_STDLIB", "TEMPLATE_ENTRYPOINTS"})
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "library_closure":
                self.assertEqual([keyword.arg for keyword in node.keywords], [], "main() must use the default lists")

    def test_every_exported_file_exists_and_writes_nothing(self) -> None:
        files = self.exported_files()
        self.assertTrue(files)
        for path in files:
            with self.subTest(file=str(path.relative_to(REPO))):
                self.assertTrue(path.is_file(), path.name)
                self.assertEqual(
                    self.write_calls(path), [], f"{path.name} is copied into exported skills and must stay read-only"
                )

    def test_the_write_scan_recognises_ordinary_write_idioms(self) -> None:
        """The scan must flag the idioms an earlier substring check missed."""
        sample = (
            "from pathlib import Path\n"
            "def save(path, text):\n"
            "    Path(path).write_text(text)\n"
            "    Path(path).replace(path + '.bak')\n"
            "    open(path, 'a').write(text)\n"
            "    Path(path).parent.mkdir()\n"
            "    Path(path).touch()\n"
            "def harmless(value, moment):\n"
            "    return value.replace('a', 'b'), moment.replace(microsecond=0), Path(value).read_text()\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(sample, encoding="utf-8")
            found = self.write_calls(probe)
        self.assertEqual(
            sorted(item.split(" at ")[0] for item in found),
            sorted([".write_text()", ".replace(target)", "open() for writing", ".write()", ".mkdir()", ".touch()"]),
        )

    def test_exported_code_imports_only_reviewed_modules(self) -> None:
        exporter = self.exporter()
        local = {name[:-3] for name in exporter.TEMPLATE_ENTRYPOINTS + exporter.EXPORTABLE_LIBRARIES}
        allowed = set(exporter.EXPORTED_STDLIB) | local
        for path in self.exported_files():
            with self.subTest(file=path.name):
                self.assertEqual(local_imports(path) - allowed, set())

    def test_no_libraries_beyond_the_closure_are_listed(self) -> None:
        """An allowlist entry nothing imports is a stale review that could hide a writer later."""
        exporter = self.exporter()
        closure = exporter.library_closure(
            KNOWLEDGE_TEMPLATES, REPO / "maintain-llm-wiki" / "scripts", exporter.TEMPLATE_ENTRYPOINTS
        )
        self.assertEqual(sorted(path.name for path in closure), sorted(exporter.EXPORTABLE_LIBRARIES))


class SharedModuleParity(unittest.TestCase):
    """Modules both skills carry must be byte-identical, or they will diverge."""

    SHARED = ("sync_artifacts.py", "trust_contract.py", "freshness.py", "verify_release.py")

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


class ActionCatalog(unittest.TestCase):
    """The catalog is the machine-readable invocation surface.

    A caller builds its command line from `helper`, so a helper string that
    argparse rejects is as wrong as a missing action.
    """

    def catalog(self, skill: str) -> dict:
        result = subprocess.run(
            [sys.executable, str(REPO / skill / "scripts" / "describe_actions.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_every_helper_names_the_subcommand_its_script_requires(self) -> None:
        for skill in SKILLS:
            scripts = REPO / skill / "scripts"
            for entry in self.catalog(skill)["actions"]:
                with self.subTest(skill=skill, action=entry["id"]):
                    parts = entry["helper"].split()
                    script = scripts / parts[0]
                    self.assertTrue(script.is_file(), entry["helper"])
                    source = script.read_text(encoding="utf-8")
                    if "add_subparsers" in source:
                        self.assertEqual(
                            len(parts),
                            2,
                            "the script takes a subcommand, so the catalog must name it",
                        )
                    else:
                        self.assertEqual(
                            len(parts),
                            1,
                            "the script takes no subcommand, so the catalog must not name one",
                        )


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
