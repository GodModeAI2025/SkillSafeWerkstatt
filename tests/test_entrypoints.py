#!/usr/bin/env python3
"""Every helper starts on every host: under `python -I` and through legacy-code-page pipes.

Two host behaviours broke helpers before these guarantees existed:

* `python -I` (and on Python 3.11+ also `-P` or PYTHONSAFEPATH=1) leaves the
  script's own folder off sys.path, so the first sibling import failed with
  ModuleNotFoundError. Security guides recommend `-I` for code from unpacked
  archives, which is exactly how a skill arrives.
* On Windows, Python 3.9 to 3.14 write piped output in the ANSI code page. One
  page character outside it, such as "≥", made the JSON output crash.

An entrypoint is any helper with an `if __name__ == "__main__":` block in either
skill's scripts folder or among the knowledge-skill templates. Each one puts
its own folder at the front of sys.path before its first sibling import and
switches stdout and stderr to UTF-8 before it runs. A helper that captures the
output of another helper therefore decodes it as UTF-8, not in the host's
locale encoding, or the switch would turn into mojibake one pipe later.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import MAINTAIN, QUERY, REPO, build_wiki  # noqa: E402


TEMPLATES = REPO / "maintain-llm-wiki" / "assets" / "knowledge-skill"
FOLDERS = (MAINTAIN, QUERY, TEMPLATES)
EXPORTER = MAINTAIN / "export_wiki_skill.py"
#: Characters outside Windows-1252 that a released page carries.
OUTSIDE_CP1252 = ("≥", "→")
PAGE_SENTENCE = "Grenzwert: Anschlussleistung ≥ 30 kW → Lastgangmessung."
QUERY_WORD = "Lastgangmessung"
EXPORTED_CALLS = {
    "verify_knowledge.py": (),
    "identity_status.py": (),
    "assess_quality.py": (),
    "search_knowledge.py": ("--query", QUERY_WORD),
}


def is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    test = node.test
    return (
        isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), str(path))


def entrypoints() -> list[Path]:
    return [
        path
        for folder in FOLDERS
        for path in sorted(folder.glob("*.py"))
        if any(is_main_guard(node) for node in parse(path).body)
    ]


def sibling_modules(path: Path) -> set[str]:
    """Modules that resolve next to the helper, wherever it is installed."""
    names = {item.stem for item in path.parent.glob("*.py")}
    if path.parent == TEMPLATES:
        # The exporter copies the templates' library modules in beside them.
        names |= {item.stem for item in MAINTAIN.glob("*.py")}
    return names


def imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module.split(".")[0]]
    return []


def first_sibling_import(path: Path, tree: ast.Module) -> Optional[int]:
    siblings = sibling_modules(path)
    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom)) and set(imported_names(node)) & siblings
    ]
    return min(lines, default=None)


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted(node.value)}.{node.attr}"
    return ""


def mentions_own_folder(node: Optional[ast.AST]) -> bool:
    """The expression is built from `__file__` and names its parent folder."""
    if node is None:
        return False
    names = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
    attributes = {item.attr for item in ast.walk(node) if isinstance(item, ast.Attribute)}
    return "__file__" in names and "parent" in attributes


def path_line(tree: ast.Module) -> Optional[int]:
    """Line of the module-level statement that puts the helper's folder first on sys.path."""
    assigned: dict[str, ast.AST] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            assigned[statement.targets[0].id] = statement.value
        if not isinstance(statement, (ast.If, ast.Expr)):
            continue
        for node in ast.walk(statement):
            if not (isinstance(node, ast.Call) and dotted(node.func) == "sys.path.insert" and len(node.args) == 2):
                continue
            position, value = node.args
            if not (isinstance(position, ast.Constant) and position.value == 0):
                continue
            if isinstance(value, ast.Name):
                value = assigned.get(value.id)
            if mentions_own_folder(value):
                return statement.lineno
    return None


def reconfigures_output_first(guard: ast.If) -> bool:
    """The `__main__` block starts by switching stdout and stderr to UTF-8 where it can."""
    loop = guard.body[0]
    if not isinstance(loop, ast.For) or not isinstance(loop.iter, ast.Tuple):
        return False
    if sorted(dotted(item) for item in loop.iter.elts) != ["sys.stderr", "sys.stdout"]:
        return False
    calls = [node for node in ast.walk(loop) if isinstance(node, ast.Call)]
    guarded = any(
        dotted(call.func) == "hasattr"
        and len(call.args) == 2
        and isinstance(call.args[1], ast.Constant)
        and call.args[1].value == "reconfigure"
        for call in calls
    )
    switched = any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "reconfigure"
        and any(
            keyword.arg == "encoding"
            and isinstance(keyword.value, ast.Constant)
            and str(keyword.value.value).lower() == "utf-8"
            for keyword in call.keywords
        )
        for call in calls
    )
    return guarded and switched


def subprocess_environment(**overrides: str) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    for key in ("PYTHONHOME", "PYTHONPLATLIBDIR"):
        if key in os.environ:
            environment[key] = os.environ[key]
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.update(overrides)
    return environment


def run_isolated(script: Path, *arguments: str, cwd: Path) -> subprocess.CompletedProcess:
    """`-I` drops the script folder from sys.path on every supported Python, 3.9 included."""
    return subprocess.run(
        [sys.executable, "-I", "-B", str(script), *arguments],
        capture_output=True,
        cwd=str(cwd),
        env=subprocess_environment(),
    )


def decode_json(test: unittest.TestCase, result: subprocess.CompletedProcess) -> dict:
    test.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
    return json.loads(result.stdout.decode("utf-8"))


class EntrypointStructure(unittest.TestCase):
    """Static: the path line and the UTF-8 switch are where they must be."""

    def test_entrypoints_are_found_in_every_folder(self) -> None:
        found = {path.parent for path in entrypoints()}
        self.assertEqual(found, set(FOLDERS))
        self.assertIn(QUERY / "search_wiki.py", entrypoints())
        self.assertIn(TEMPLATES / "search_knowledge.py", entrypoints())

    def test_every_entrypoint_puts_its_folder_first_before_any_sibling_import(self) -> None:
        for path in entrypoints():
            tree = parse(path)
            first = first_sibling_import(path, tree)
            if first is None:
                continue
            with self.subTest(entrypoint=str(path.relative_to(REPO))):
                line = path_line(tree)
                self.assertIsNotNone(
                    line,
                    "no module-level sys.path.insert(0, <folder of __file__>); the helper fails under python -I",
                )
                self.assertLess(line, first, "the folder must be on sys.path before the first sibling import")

    def test_every_entrypoint_switches_stdout_and_stderr_to_utf8_first(self) -> None:
        for path in entrypoints():
            tree = parse(path)
            with self.subTest(entrypoint=str(path.relative_to(REPO))):
                guard = next(node for node in tree.body if is_main_guard(node))
                self.assertTrue(
                    reconfigures_output_first(guard),
                    "the __main__ block must start with a hasattr-guarded "
                    "reconfigure(encoding='utf-8') of sys.stdout and sys.stderr",
                )
                self.assertTrue(
                    any(
                        isinstance(node, ast.Import) and any(alias.name == "sys" and not alias.asname for alias in node.names)
                        for node in tree.body
                    ),
                    "sys must be imported at module level",
                )

    def test_helpers_decode_captured_helper_output_as_utf8(self) -> None:
        """text=True decodes in the locale encoding, the ANSI code page on Windows."""
        launchers = {"subprocess.run", "subprocess.Popen", "subprocess.check_output"}
        for folder in FOLDERS:
            for path in sorted(folder.glob("*.py")):
                for node in ast.walk(parse(path)):
                    if not isinstance(node, ast.Call) or dotted(node.func) not in launchers:
                        continue
                    keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
                    text_mode = any(
                        isinstance(keywords.get(name), ast.Constant) and bool(keywords[name].value)
                        for name in ("text", "universal_newlines")
                    )
                    encoding = keywords.get("encoding")
                    with self.subTest(helper=str(path.relative_to(REPO)), line=node.lineno):
                        self.assertFalse(text_mode and encoding is None, "decode child output with encoding='utf-8'")
                        if encoding is not None:
                            self.assertIsInstance(encoding, ast.Constant)
                            self.assertEqual(str(encoding.value).lower(), "utf-8")

    def test_future_import_stays_the_first_statement(self) -> None:
        for path in entrypoints():
            body = parse(path).body
            future = [
                index for index, node in enumerate(body)
                if isinstance(node, ast.ImportFrom) and node.module == "__future__"
            ]
            if not future:
                continue
            with self.subTest(entrypoint=str(path.relative_to(REPO))):
                docstring = isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant)
                self.assertEqual(future, [1 if docstring else 0])


class IsolatedAndLegacyCodePageHosts(unittest.TestCase):
    """Runtime: the helpers run under `python -I` and print UTF-8 through a cp1252 pipe."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.mkdtemp(prefix="lmwiki-entrypoints-")
        cls.tmp = Path(cls._dir)
        (cls.tmp / "source").mkdir()
        cls.elsewhere = cls.tmp / "elsewhere"
        cls.elsewhere.mkdir()
        cls.wiki = build_wiki(cls.tmp / "source")
        overview = cls.wiki.read("wiki/overview.md")
        cls.wiki.write("wiki/overview.md", overview.rstrip() + f"\n\n{PAGE_SENTENCE}\n")
        cls.wiki.release("entrypoints-encoding-1")
        # The exporter itself runs isolated too; its self-check keeps the
        # script folder off sys.path where the interpreter supports that.
        cls.export = run_isolated(
            EXPORTER,
            "--target", str(cls.wiki.path),
            "--output-dir", str(cls.tmp / "out"),
            "--skill-name", "kodierwissen",
            cwd=cls.elsewhere,
        )
        cls.skill = cls.tmp / "out" / "kodierwissen"

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._dir, ignore_errors=True)

    def test_isolated_mode_really_drops_the_script_folder(self) -> None:
        """Without this, the isolated runs below would prove nothing on this interpreter."""
        probe = self.tmp / "probe" / "where.py"
        probe.parent.mkdir(exist_ok=True)
        probe.write_text(
            "import sys\nfrom pathlib import Path\n"
            "print(str(Path(__file__).resolve().parent) in [str(Path(p).resolve()) for p in sys.path if p])\n",
            encoding="utf-8",
        )
        result = run_isolated(probe, cwd=self.elsewhere)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stdout.decode("utf-8").strip(), "False")

    def test_the_query_search_runs_isolated(self) -> None:
        report = decode_json(
            self,
            run_isolated(QUERY / "search_wiki.py", "--target", str(self.wiki.path), "--query", QUERY_WORD, cwd=self.elsewhere),
        )
        self.assertEqual(report["release"]["state"], "ready")
        self.assertIn("wiki/overview.md", [item["path"] for item in report["results"]])

    def test_every_repository_entrypoint_imports_its_siblings_isolated(self) -> None:
        """`--help` loads every sibling module and stops before any work."""
        for path in entrypoints():
            if path.parent == TEMPLATES:
                continue  # Templates run where the exporter installs them, below.
            with self.subTest(entrypoint=str(path.relative_to(REPO))):
                result = run_isolated(path, "--help", cwd=self.elsewhere)
                stderr = result.stderr.decode("utf-8", errors="replace")
                self.assertEqual(result.returncode, 0, stderr)
                self.assertNotIn("ModuleNotFoundError", stderr)

    def test_the_export_and_every_exported_entrypoint_run_isolated(self) -> None:
        self.assertEqual(self.export.returncode, 0, self.export.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(json.loads(self.export.stdout.decode("utf-8"))["state"], "exported")
        for script, arguments in EXPORTED_CALLS.items():
            with self.subTest(script=script):
                report = decode_json(self, run_isolated(self.skill / "scripts" / script, *arguments, cwd=self.elsewhere))
                if script == "search_knowledge.py":
                    self.assertEqual(report["release"]["state"], "ready")
                    self.assertIn(
                        "references/knowledge/wiki/overview.md", [item["path"] for item in report["results"]]
                    )

    def test_a_cp1252_pipe_reproduces_the_windows_failure(self) -> None:
        """Without the UTF-8 switch, the simulated Windows pipe breaks on these characters."""
        result = subprocess.run(
            [sys.executable, "-B", "-c", f"print({OUTSIDE_CP1252[0]!r})"],
            capture_output=True,
            env=subprocess_environment(PYTHONIOENCODING="cp1252"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UnicodeEncodeError", result.stderr.decode("utf-8", errors="replace"))

    def test_search_output_through_a_cp1252_pipe_is_utf8_json(self) -> None:
        calls = {
            "query skill": [str(QUERY / "search_wiki.py"), "--target", str(self.wiki.path), "--query", QUERY_WORD],
            "exported skill": [str(self.skill / "scripts" / "search_knowledge.py"), "--query", QUERY_WORD],
        }
        for label, command in calls.items():
            with self.subTest(search=label):
                result = subprocess.run(
                    [sys.executable, "-B", *command],
                    capture_output=True,
                    cwd=str(self.elsewhere),
                    env=subprocess_environment(PYTHONIOENCODING="cp1252"),
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
                text = result.stdout.decode("utf-8")
                report = json.loads(text)
                self.assertTrue(report["results"])
                for character in OUTSIDE_CP1252:
                    self.assertIn(character, text)

    def test_a_request_on_stdin_survives_a_cp1252_environment(self) -> None:
        """--request - reads bytes: a legacy code page on the text layer changes nothing."""
        request = json.dumps(
            {"query": QUERY_WORD, "also": ["Anschlussleistung ≥ Grenzwert"]}, ensure_ascii=False
        ).encode("utf-8")
        calls = {
            "query skill": [str(QUERY / "search_wiki.py"), "--target", str(self.wiki.path), "--request", "-"],
            "exported skill": [str(self.skill / "scripts" / "search_knowledge.py"), "--request", "-"],
        }
        for label, command in calls.items():
            with self.subTest(search=label):
                result = subprocess.run(
                    [sys.executable, "-B", *command],
                    input=request,
                    capture_output=True,
                    cwd=str(self.elsewhere),
                    env=subprocess_environment(PYTHONIOENCODING="cp1252"),
                )
                report = decode_json(self, result)
                self.assertEqual(
                    [item["text"] for item in report["formulations"]], [QUERY_WORD, "Anschlussleistung ≥ Grenzwert"]
                )
                self.assertTrue(report["results"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
