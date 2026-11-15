#!/usr/bin/env python3
"""Shared, dependency-free harness for building throwaway wikis in tests.

The harness drives the real bundled helpers exactly as the maintenance skill
would: it builds a hash-bound identity proposal, initializes a released wiki,
and exposes locked helper invocation. Nothing here reimplements skill logic.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4
from typing import Any, Iterable, Optional


REPO = Path(__file__).resolve().parent.parent
MAINTAIN = REPO / "maintain-llm-wiki" / "scripts"
QUERY = REPO / "query-llm-wiki" / "scripts"


def python_environment(**overrides: str) -> dict[str, str]:
    """The current environment for a child Python, without the caller's PYTHON* settings.

    PYTHONHOME and PYTHONPLATLIBDIR stay, because the interpreter may need them
    to start at all; PYTHONDONTWRITEBYTECODE=1 keeps bytecode out of the
    repository. `overrides` are applied last.
    """
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    for key in ("PYTHONHOME", "PYTHONPLATLIBDIR"):
        if key in os.environ:
            environment[key] = os.environ[key]
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.update(overrides)
    return environment


def page(
    title: str,
    body: str,
    kind: Optional[str] = "concept",
    fields: Iterable[str] = (),
    *,
    aliases: object = None,
    heading: bool = False,
) -> str:
    """A minimal page for the search core: frontmatter, a blank line, then `body`.

    The frontmatter holds the title, status "active", type `kind` (left out
    when None), the aliases (a list as list items, any other value as one JSON
    scalar) and the raw `fields` lines, in this order. With `heading`, the
    title follows as an H1 before the body.
    """
    lines = ["---", f'title: "{title}"', 'status: "active"']
    if kind is not None:
        lines.append(f'type: "{kind}"')
    if isinstance(aliases, list):
        lines.append("aliases:")
        lines += [f'  - "{alias}"' for alias in aliases]
    elif aliases is not None:
        lines.append(f"aliases: {json.dumps(aliases, ensure_ascii=False)}")
    lines += [*fields, "---", ""]
    if heading:
        lines += [f"# {title}", ""]
    return "\n".join(lines + [body, ""])


#: The root index PageTree writes unless a test gives its own.
INDEX_PAGE = page("Index", "Startseite.", "index")


class PageTree:
    """A temporary folder the search core reads without a release: WIKI.md, a root index, and the given files.

    Given files replace the defaults of the same path; `index=None` leaves the
    root index out. Every file is written as UTF-8 bytes, so its line numbers
    are the same on every platform.
    """

    def __init__(self, files: dict[str, str], *, index: Optional[str] = INDEX_PAGE) -> None:
        defaults = {"WIKI.md": "# Wiki\n"}
        if index is not None:
            defaults["wiki/index.md"] = index
        self.files = {**defaults, **files}

    def __enter__(self) -> Path:
        self._directory = tempfile.TemporaryDirectory(prefix="lmwiki-pages-")
        root = Path(self._directory.name)
        for relative, text in self.files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        return root

    def __exit__(self, *_exc: object) -> None:
        self._directory.cleanup()


IDENTITY = {
    "identity": {
        "purpose": "Test the SkillSafeWerkstatt contract end to end.",
        "knowledge_types": ["concept", "entity"],
        "audience": "Maintainers of this repository.",
        "answer_language": "de",
        "form_of_address": "Sie",
        "tone": "neutral",
        "detail": "medium",
        "answer_structure": "Antwort, dann Belege.",
        "citation_display": "claim_id, Titel, Quelle",
        "uncertainty_style": "Unsicherheit ausdruecklich benennen.",
        "history_presentation": "Abgeloestes als Historie kennzeichnen.",
        "boundaries": "Nur belegtes Wissen aus diesem Wiki.",
        "taboos": "Keine erfundenen Quellen.",
    },
    "content_policy": {
        "update_model": "current-state",
        "supersession_policy": "Neuere belegte Aussage ersetzt aeltere nur ausdruecklich.",
        "removal_policy": "preview-confirm-never-automatic",
        "conflict_policy": "preserve-and-disclose",
    },
}


class HelperError(RuntimeError):
    """Raised when a bundled helper exits non-zero."""

    def __init__(self, argv: list[str], result: subprocess.CompletedProcess) -> None:
        self.argv = argv
        self.result = result
        super().__init__(
            f"helper failed ({result.returncode}): {' '.join(argv)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def run(script: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run one bundled helper with its own scripts directory importable."""
    argv = [sys.executable, str(script), *args]
    result = subprocess.run(
        argv,
        capture_output=True,
        encoding="utf-8",  # helpers print UTF-8 on every host
        cwd=str(script.parent),
    )
    if check and result.returncode != 0:
        raise HelperError(argv, result)
    return result


def run_json(script: Path, *args: str, check: bool = True) -> Any:
    result = run(script, *args, check=check)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic path
        raise HelperError([str(script), *args], result) from exc


class Wiki:
    """One throwaway released wiki plus the helpers that operate on it."""

    def __init__(self, root: Path, target: Path) -> None:
        self.root = root
        self.path = target

    # -- helper invocation -------------------------------------------------

    def maintain(self, name: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return run(MAINTAIN / name, *args, check=check)

    def maintain_json(self, name: str, *args: str, check: bool = True) -> Any:
        return run_json(MAINTAIN / name, *args, check=check)

    def query(self, name: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return run(QUERY / name, *args, check=check)

    def query_json(self, name: str, *args: str, check: bool = True) -> Any:
        return run_json(QUERY / name, *args, check=check)

    def locked(self, name: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run one allowlisted helper under a freshly acquired lock."""
        # A fresh private token path per run; the release removes it again.
        token_file = self.root / f"runtime-token-{uuid4().hex}"
        self.maintain(
            "wiki_lock.py",
            "acquire",
            "--target",
            str(self.path),
            "--token-file",
            str(token_file),
            "--owner",
            "test/harness",
        )
        # Helpers with subcommands need the subcommand ahead of any option, so
        # a leading bare word is passed through before --target.
        leading: tuple[str, ...] = ()
        if args and not args[0].startswith("-"):
            leading, args = (args[0],), args[1:]
        try:
            return self.maintain(
                "run_locked.py",
                "--token-file",
                str(token_file),
                "--helper",
                name,
                "--",
                *leading,
                "--target",
                str(self.path),
                *args,
                check=check,
            )
        finally:
            self.maintain(
                "wiki_lock.py",
                "release",
                "--target",
                str(self.path),
                "--token-file",
                str(token_file),
                check=False,
            )

    # -- convenience -------------------------------------------------------

    def verify(self, *, query_side: bool = False) -> Any:
        script = "verify_release.py"
        args = ["--target", str(self.path)]
        return self.query_json(script, *args, check=False) if query_side else self.maintain_json(
            script, *args, check=False
        )

    def lint(self, *extra: str) -> subprocess.CompletedProcess:
        """Run the strict linter under a lock, as the maintenance skill does."""
        return self.locked("lint_wiki.py", "--check-only", *extra, check=False)

    def current_version(self) -> str:
        return self.read("WIKI_VERSION").strip()

    def release(
        self, operation_id: str, *extra: str, check: bool = True
    ) -> subprocess.CompletedProcess:
        """Publish one release, supplying the version precondition the contract requires."""
        return self.locked(
            "release_wiki.py",
            "--operation-id",
            operation_id,
            "--expect-current-version",
            self.current_version(),
            *extra,
            check=check,
        )

    def rebuild(self) -> subprocess.CompletedProcess:
        """Regenerate derived graph and reading views after content changes."""
        return self.locked("build_graph.py")

    def read(self, relative: str) -> str:
        return (self.path / relative).read_text(encoding="utf-8")

    def write(self, relative: str, text: str) -> Path:
        path = self.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def register_source(self, markdown: str, title: str, original_ref: str, language: str = "de") -> dict[str, Any]:
        """Register one Markdown extraction through register_source.py and return its registry record."""
        extract = self.root / "extract.md"
        extract.write_text(markdown, encoding="utf-8")
        result = self.locked(
            "register_source.py",
            "--markdown-file", str(extract),
            "--title", title,
            "--original-ref", original_ref,
            "--content-language", language,
        )
        return json.loads(result.stdout)["source"]

    def apply_pages(self, pages: dict[str, str]) -> None:
        """Stage wiki pages and apply them in one plan through page_batch.py.

        The batch helper refuses a page no index references yet, so the index
        entries have to be written first.
        """
        staging = self.root / "staging"
        for relative, text in pages.items():
            staged = staging / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(text, encoding="utf-8")
        plan_file = self.root / "batch.json"
        self.locked(
            "page_batch.py", "plan",
            "--staging-dir", str(staging),
            "--paths-json", json.dumps(sorted(pages)),
            "--output", str(plan_file),
        )
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        self.locked(
            "page_batch.py", "apply",
            "--staging-dir", str(staging),
            "--plan-file", str(plan_file),
            "--expect-plan-sha256", plan["plan_sha256"],
        )


def build_wiki(
    tmp: Path,
    *,
    title: str = "Testwiki",
    topic: str = "Vertragspruefung",
    language: str = "de",
) -> Wiki:
    """Create one initialized and released wiki under `tmp`."""
    target = tmp / "wiki"
    identity_input = tmp / "identity-input.json"
    identity_plan = tmp / "identity-plan.json"
    identity_input.write_text(json.dumps(IDENTITY, ensure_ascii=False), encoding="utf-8")

    plan = run_json(
        MAINTAIN / "plan_identity.py",
        "--input",
        str(identity_input),
        "--wiki-language",
        language,
        "--output",
        str(identity_plan),
    )
    digest = plan["proposal_sha256"]

    run(
        MAINTAIN / "initialize_wiki.py",
        "--target",
        str(target),
        "--title",
        title,
        "--topic",
        topic,
        "--wiki-language",
        language,
        "--identity-plan",
        str(identity_plan),
        "--expect-identity-sha256",
        digest,
        "--owner",
        "test/harness",
    )
    return Wiki(tmp, target)


class TempWiki:
    """Context manager yielding a fresh released wiki in a temporary directory."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self._dir: Optional[str] = None
        self.wiki: Optional[Wiki] = None

    def __enter__(self) -> Wiki:
        self._dir = tempfile.mkdtemp(prefix="lmwiki-test-")
        self.wiki = build_wiki(Path(self._dir), **self.kwargs)
        return self.wiki

    def __exit__(self, *exc: Any) -> None:
        if self._dir:
            shutil.rmtree(self._dir, ignore_errors=True)
