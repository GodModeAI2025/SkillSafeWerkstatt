#!/usr/bin/env python3
"""Shared, dependency-free harness for building throwaway wikis in tests.

The harness drives the real bundled helpers exactly as the maintenance skill
would: it builds a hash-bound identity proposal, initializes a released wiki,
and exposes locked helper invocation. Nothing here reimplements skill logic.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4
from typing import Any, Optional


REPO = Path(__file__).resolve().parent.parent
MAINTAIN = REPO / "maintain-llm-wiki" / "scripts"
QUERY = REPO / "query-llm-wiki" / "scripts"


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
        text=True,
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
