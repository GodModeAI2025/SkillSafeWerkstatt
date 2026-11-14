#!/usr/bin/env python3
"""Export one verified SkillSafeWerkstatt release as a frozen read-only knowledge skill."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

# Siblings are imported from this folder even where the interpreter leaves it
# off sys.path: python -I, python -P, PYTHONSAFEPATH=1.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from verify_release import verify_snapshot


SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
DEFAULT_DESCRIPTION = (
    "Use this skill whenever a question may be answered by its bundled SkillSafeWerkstatt knowledge, including requests "
    "to explain, compare, summarize, trace, or cite its knowledge. Verify the frozen snapshot and "
    "answer with claim-level source citations. Never maintain or modify it."
)
RESERVED_SKILL_WORDS = {"anthropic", "claude"}
# The exported skill's executable helpers. The bundled library modules they
# import, directly or transitively, are computed from the source, so a new
# import can never again leave the exported search unable to start unnoticed.
TEMPLATE_ENTRYPOINTS = ("verify_knowledge.py", "search_knowledge.py", "assess_quality.py", "identity_status.py")
# The exported SKILL.md. Its text lives in a template file, not in Python: an
# f-string turned every brace of an example into a formatting error. Only the
# two placeholders are replaced, by plain string replacement.
SKILL_TEMPLATE = "SKILL.template.md"
NAME_PLACEHOLDER = "__SKILL_NAME__"
DESCRIPTION_PLACEHOLDER = "__SKILL_DESCRIPTION__"
# Library modules reviewed as read-only: no writes, no entrypoint. Only these
# may enter an export. A template that comes to import any other module of the
# maintenance skill is refused by name until that module has been reviewed and
# listed here; this is an allowlist on purpose, because writer libraries such as
# portable_io.py or navigation.py have no entrypoint a heuristic could detect.
EXPORTABLE_LIBRARIES = (
    "bm25.py",
    "freshness.py",
    "frontmatter_contract.py",
    "search_core.py",
    "trust_contract.py",
    "wiki_filters.py",
    "wordforms.py",
)
# Standard-library modules exported code may import. Reviewed for presence on
# Python 3.9+ on Windows, macOS and Linux and for offering no file writing,
# process control, or network access of their own. Any other import in a
# template or allowlisted library is refused by name until reviewed here.
EXPORTED_STDLIB = frozenset({
    "__future__", "argparse", "dataclasses", "datetime", "hashlib", "json",
    "math", "pathlib", "re", "typing", "unicodedata",
    # Entrypoints use sys only to put their own folder on sys.path and to
    # switch stdout and stderr to UTF-8; it writes no files of its own.
    "sys",
})
# The request path SKILL.md routes Windows and quoted text through: one JSON
# object on standard input, with a UTF-8 BOM, a \u escape and a reformulation
# that repeats the query and is dropped.
SELF_CHECK_REQUEST_CALL = ("search_knowledge.py", "--request", "-")
SELF_CHECK_REQUEST = b'\xef\xbb\xbf{"query": "wiki", "also": ["\\u00dcbersicht", "Wiki"]}'
# The self-check runs every entrypoint once inside the generated skill.
SELF_CHECK_CALLS = (
    ("verify_knowledge.py",),
    ("identity_status.py",),
    ("assess_quality.py",),
    ("search_knowledge.py", "--query", "wiki", "--include-sources"),
    # The selector and trust-tier path, which SKILL.md tells agents to use.
    (
        "search_knowledge.py", "--query", "wiki", "--filter-json",
        '{"kind":"filter","conditions":[{"property":"__trust_tier","operator":"equals","value":"unverified"}]}',
    ),
    SELF_CHECK_REQUEST_CALL,
)


def fail(message: str) -> None:
    raise SystemExit(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def safe_manifest_path(relative: Any) -> str:
    if not isinstance(relative, str) or not relative:
        fail("Release manifest contains an empty file path")
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or ".." in windows.parts
        or "\\" in relative
        or posix.as_posix() != relative
    ):
        fail(f"Release manifest contains a non-portable path: {relative}")
    return relative


def wiki_title(target: Path) -> str:
    text = (target / "WIKI.md").read_text(encoding="utf-8")
    match = H1.search(text)
    title = " ".join((match.group(1) if match else "SkillSafeWerkstatt").split())
    return title or "SkillSafeWerkstatt"


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def skill_markdown(name: str, description: str, template_root: Path) -> str:
    """The exported SKILL.md: the template with name and description filled in.

    Plain replacement, never str.format: the template may contain braces. The
    name is replaced first; its grammar cannot spell the description
    placeholder, and the description goes in last, so nothing a user writes
    into it is ever read as a placeholder.
    """
    path = template_root / SKILL_TEMPLATE
    if not path.is_file():
        fail(f"Knowledge-skill template is missing: {SKILL_TEMPLATE}")
    template = path.read_text(encoding="utf-8")
    for placeholder in (NAME_PLACEHOLDER, DESCRIPTION_PLACEHOLDER):
        if template.count(placeholder) != 1:
            fail(f"{SKILL_TEMPLATE} must contain {placeholder} exactly once")
    return template.replace(NAME_PLACEHOLDER, yaml_string(name)).replace(
        DESCRIPTION_PLACEHOLDER, yaml_string(description)
    )


def validate_skill_text(skill_dir: Path, name: str, description: str, source_target: Path) -> None:
    skill_path = skill_dir / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or text.count("---\n") < 2:
        fail("Generated SKILL.md has invalid frontmatter")
    if f"name: {yaml_string(name)}" not in text or f"description: {yaml_string(description)}" not in text:
        fail("Generated SKILL.md frontmatter does not match the requested identity")
    if len(description) > 1024 or "\n" in description or "\r" in description or "<" in description or ">" in description:
        fail("Skill description must be one line of at most 1024 characters without angle brackets")
    forbidden = (str(source_target), source_target.as_uri())
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(value in content for value in forbidden):
            fail(f"Generated skill leaks the absolute source path in {path.relative_to(skill_dir).as_posix()}")


def bare_imports(path: Path) -> set[str]:
    """Top-level module names a helper imports, wherever the import statement sits.

    Relative and dynamic imports are refused: the closure could not see what
    they load, so an export could pass its self-check and still fail later.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                fail(f"Knowledge-skill helper {path.name} uses a relative import, which exported skills do not support")
            if node.module:
                found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
            fail(f"Knowledge-skill helper {path.name} imports dynamically, which the exporter cannot check")
    return found


def library_closure(
    template_root: Path,
    library_root: Path,
    entrypoints: tuple[str, ...],
    allowed: tuple[str, ...] = EXPORTABLE_LIBRARIES,
    stdlib: frozenset = EXPORTED_STDLIB,
) -> list[Path]:
    """Every bundled library module the template entrypoints import, transitively.

    Each imported name must be another entrypoint, a module of `library_root`
    on the reviewed allowlist, or a reviewed standard-library module. Anything
    else is refused by name before output is written, so an export can neither
    ship a maintenance helper or writer library nor silently miss a module.
    """
    templates = {name[:-3] for name in entrypoints}
    pending: list[Path] = []
    for name in entrypoints:
        template = template_root / name
        if not template.is_file():
            fail(f"Knowledge-skill template is missing: {name}")
        pending.append(template)
    needed: dict[str, Path] = {}
    while pending:
        current = pending.pop()
        for name in sorted(bare_imports(current)):
            if name in templates or name in needed:
                continue
            if (template_root / f"{name}.py").is_file():
                fail(
                    f"{current.name} imports {name}.py from the knowledge-skill templates, which is not an "
                    "exported entrypoint; add it to TEMPLATE_ENTRYPOINTS or move the code"
                )
            candidate = library_root / f"{name}.py"
            if not candidate.is_file():
                if name not in stdlib:
                    fail(
                        f"{current.name} imports {name}, which is not on the exporter's reviewed list of "
                        "standard-library modules for exported skills (EXPORTED_STDLIB); review it for "
                        "Python 3.9+ on every platform and for write access before adding it"
                    )
                continue
            if candidate.name not in allowed:
                fail(
                    f"Knowledge-skill templates import {candidate.name}, which is not a reviewed read-only "
                    "library for exported skills. Maintenance helpers and writer libraries must never be "
                    "copied into an export; a new read-only library must be reviewed and added to "
                    "EXPORTABLE_LIBRARIES first"
                )
            needed[name] = candidate
            pending.append(candidate)
    return [needed[name] for name in sorted(needed)]


def self_check_environment() -> dict[str, str]:
    """An interpreter environment without PYTHONPATH, user site, or bytecode writing.

    Together with `-S` (no site-packages, no .pth files), neither PYTHONPATH nor
    installed packages can satisfy an import. PYTHONHOME and PYTHONPLATLIBDIR
    are kept: some relocated interpreters find their standard library only
    through them. UTF-8 output is forced: the check is about bundling, not
    host encodings. PYTHONSAFEPATH keeps the script folder off sys.path on
    Python 3.11+, as `python -I` does everywhere, so each helper must find its
    bundled siblings itself.
    """
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    for key in ("PYTHONHOME", "PYTHONPLATLIBDIR"):
        if key in os.environ:
            environment[key] = os.environ[key]
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONSAFEPATH"] = "1"
    return environment


def run_self_check(skill_dir: Path) -> None:
    """Run every bundled entrypoint inside the generated skill, on this interpreter.

    Verification alone does not import the search, so a missing library module
    would otherwise surface only when an end user asks the first question. The
    check covers the paths in SELF_CHECK_CALLS on the exporting Python only,
    including a request on standard input.
    """
    environment = self_check_environment()
    for call in SELF_CHECK_CALLS:
        script, *arguments = call
        # Every call gets its own standard input, so none inherits the exporter's.
        result = subprocess.run(
            [sys.executable, "-B", "-S", "-s", str(skill_dir / "scripts" / script), *arguments],
            capture_output=True,
            input=SELF_CHECK_REQUEST if call == SELF_CHECK_REQUEST_CALL else b"",
            cwd=str(skill_dir),
            env=environment,
            check=False,
        )
        failure = ""
        if result.returncode != 0:
            failure = f"exited with {result.returncode}"
        else:
            try:
                json.loads(result.stdout.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                failure = "did not print one JSON document"
        if failure:
            for stream in (result.stdout, result.stderr):
                if stream:
                    print(stream.decode("utf-8", errors="replace"), end="", file=sys.stderr)
            fail(f"Generated knowledge skill failed its self-check: scripts/{script} {failure}")


def is_script_cache(relative: PurePosixPath) -> bool:
    """An interpreter cache next to the bundled helpers.

    Only `scripts/` is filtered: every file under `references/knowledge/` is
    bound by the release manifest, whatever its name, and must be packaged.
    """
    parts = relative.parts
    return bool(parts) and parts[0] == "scripts" and (
        "__pycache__" in parts or relative.suffix in {".pyc", ".pyo"}
    )


def packaged_files(skill_dir: Path) -> list[Path]:
    """Files that belong in the package; caches beside the helpers never do."""
    return sorted(
        (
            item
            for item in skill_dir.rglob("*")
            if item.is_file() and not is_script_cache(PurePosixPath(item.relative_to(skill_dir).as_posix()))
        ),
        key=lambda item: item.relative_to(skill_dir).as_posix(),
    )


def zip_datetime(released_at: str) -> tuple[int, int, int, int, int, int]:
    try:
        parsed = datetime.fromisoformat(released_at.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime(1980, 1, 1)
    year = min(max(parsed.year, 1980), 2107)
    second = parsed.second - (parsed.second % 2)
    return year, parsed.month, parsed.day, parsed.hour, parsed.minute, second


def deterministic_skill_package(skill_dir: Path, package_path: Path, released_at: str) -> None:
    timestamp = zip_datetime(released_at)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in packaged_files(skill_dir):
            archive_name = f"{skill_dir.name}/{path.relative_to(skill_dir).as_posix()}"
            info = zipfile.ZipInfo(archive_name, date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Canonical released wiki directory")
    parser.add_argument("--output-dir", required=True, help="Directory that will receive the skill folder and .skill package")
    parser.add_argument("--skill-name", required=True, help="Lowercase hyphenated skill name")
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION, help="Trigger description, at most 1024 characters")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    name = args.skill_name.strip()
    description = args.description.strip()
    if len(name) > 64 or not SKILL_NAME.fullmatch(name):
        fail("skill-name must be lowercase hyphenated alphanumerics and at most 64 characters")
    if RESERVED_SKILL_WORDS & set(name.split("-")):
        fail("skill-name contains a reserved product name and cannot be uploaded as a custom skill")
    if (
        not description
        or len(description) > 1024
        or "\n" in description
        or "\r" in description
        or "<" in description
        or ">" in description
    ):
        fail("description must be one non-empty line of at most 1024 characters without angle brackets")

    initial = verify_snapshot(target)
    if initial.get("state") != "ready":
        print(json.dumps({"state": "export_refused", "release": initial}, ensure_ascii=False, indent=2))
        return {"wiki_busy": 2, "snapshot_changed": 3}.get(str(initial.get("state")), 4)

    skill_dir = output_dir / name
    package_path = output_dir / f"{name}.skill"
    checksum_path = output_dir / f"{name}.skill.sha256"
    if is_within(skill_dir, target) or is_within(target, skill_dir):
        fail("The exported skill must not be placed inside the canonical wiki or contain it")
    for path in (skill_dir, package_path, checksum_path):
        if path.exists():
            fail(f"Refusing to overwrite existing export output: {path.relative_to(output_dir).as_posix()}")

    manifest_path = target / "meta/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        fail("Release manifest contains no files")

    # Resolve the helper set before anything is written, so a refused template
    # change leaves no partial skill folder behind.
    template_root = Path(__file__).resolve().parent.parent / "assets" / "knowledge-skill"
    libraries = library_closure(template_root, Path(__file__).resolve().parent, TEMPLATE_ENTRYPOINTS)
    skill_text = skill_markdown(name, description, template_root)

    # Creating the skill folder without exist_ok claims this export name; a
    # concurrent export of the same name fails here, before cleanup applies.
    output_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.mkdir()
    # Every output path was checked above not to exist, so whatever exists of
    # them after a failure was written by this run and is removed again: hosts
    # install unpacked folders too, and a half-written or unchecked skill must
    # never look installable. This covers refusals, errors, and interrupts.
    completed = False
    try:
        result = write_export(
            target, skill_dir, package_path, checksum_path, name, description,
            initial, entries, manifest_path, template_root, libraries, skill_text,
        )
        completed = result == 0
        return result
    finally:
        if not completed:
            remove_incomplete_export(skill_dir, package_path, checksum_path)


def remove_incomplete_export(skill_dir: Path, package_path: Path, checksum_path: Path) -> None:
    shutil.rmtree(skill_dir, ignore_errors=True)
    for path in (package_path, checksum_path):
        try:
            path.unlink()
        except OSError:
            pass
    leftovers = [path.name for path in (skill_dir, package_path, checksum_path) if path.exists()]
    if leftovers:
        print(
            "Incomplete export output could not be removed: " + ", ".join(leftovers)
            + ". Delete it before exporting again and do not install it.",
            file=sys.stderr,
        )


def write_export(
    target: Path,
    skill_dir: Path,
    package_path: Path,
    checksum_path: Path,
    name: str,
    description: str,
    initial: dict[str, Any],
    entries: list[Any],
    manifest_path: Path,
    template_root: Path,
    libraries: list[Path],
    skill_text: str,
) -> int:
    """Write the skill folder and package; the caller removes them on any failure."""
    knowledge_dir = skill_dir / "references" / "knowledge"
    scripts_dir = skill_dir / "scripts"
    knowledge_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)

    copied = 0
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            fail("Release manifest contains a non-object file entry")
        relative = safe_manifest_path(entry.get("path"))
        if relative in seen:
            fail(f"Release manifest contains a duplicate path: {relative}")
        seen.add(relative)
        source = target / relative
        if source.is_symlink():
            fail(f"Released symbolic links cannot be exported: {relative}")
        resolved_source = source.resolve()
        if not is_within(resolved_source, target):
            fail(f"Released file resolves outside the wiki: {relative}")
        destination = knowledge_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        copied += 1
    shutil.copyfile(manifest_path, knowledge_dir / "meta" / "manifest.json")

    for script_name in TEMPLATE_ENTRYPOINTS:
        shutil.copyfile(template_root / script_name, scripts_dir / script_name)
    for module in libraries:
        shutil.copyfile(module, scripts_dir / module.name)

    title = wiki_title(target)
    (skill_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
    snapshot = {
        "format": "lmwiki-skill-snapshot/1",
        "skill_name": name,
        "wiki_title": title,
        "version": initial.get("version", ""),
        "release_id": initial.get("release_id", ""),
        "released_at": initial.get("released_at", ""),
        "source_manifest_sha256": initial.get("manifest_sha256", ""),
        "source_file_count": initial.get("files", 0),
        "read_only": True,
        "self_maintenance": False,
    }
    (skill_dir / "references" / "SNAPSHOT.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    final = verify_snapshot(target, str(initial.get("manifest_sha256") or ""))
    if final.get("state") != "ready":
        print(json.dumps({"state": "export_refused", "release": final}, ensure_ascii=False, indent=2))
        return {"wiki_busy": 2, "snapshot_changed": 3}.get(str(final.get("state")), 4)
    validate_skill_text(skill_dir, name, description, target)
    run_self_check(skill_dir)

    deterministic_skill_package(skill_dir, package_path, str(initial.get("released_at") or ""))
    package_sha256 = sha256_file(package_path)
    checksum_path.write_text(f"{package_sha256}  {package_path.name}\n", encoding="utf-8")
    print(json.dumps({
        "state": "exported",
        "skill_folder": name,
        "skill_package": package_path.name,
        "skill_sha256": package_sha256,
        "checksum_file": checksum_path.name,
        "wiki_title": title,
        "version": initial.get("version", ""),
        "release_id": initial.get("release_id", ""),
        "source_manifest_sha256": initial.get("manifest_sha256", ""),
        "released_files": copied,
        "read_only": True,
        "self_maintenance": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
