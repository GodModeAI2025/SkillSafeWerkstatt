#!/usr/bin/env python3
"""Build the installable .skill packages from the unpacked skill folders.

A .skill file is a ZIP whose archive root is exactly one skill folder. Test
scenarios under evals/ are development material and are excluded, which is what
the README has always described; the previously committed packages contained
them, so this script is what makes the documented convention true.

Entries are written sorted, without timestamps, and without host metadata, so
rebuilding an unchanged skill produces an identical file.

    python3 tools/package_skills.py            # build
    python3 tools/package_skills.py --check    # verify the committed packages
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SKILLS = ("maintain-llm-wiki", "query-llm-wiki")

#: Development material that never belongs in an installable package.
EXCLUDED_DIRS = {"evals", "__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}

#: A fixed timestamp keeps the archive byte-identical across rebuilds.
FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def included_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if EXCLUDED_DIRS & set(relative.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES or path.name in EXCLUDED_NAMES:
            continue
        found.append(path)
    return sorted(found, key=lambda item: item.relative_to(root).as_posix())


def build(name: str) -> bytes:
    root = REPO / name
    if not root.is_dir():
        raise SystemExit(f"skill folder is missing: {name}")
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in included_files(root):
            arcname = f"{name}/{path.relative_to(root).as_posix()}"
            info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if a package is out of date")
    args = parser.parse_args()

    failures = []
    for name in SKILLS:
        content = build(name)
        package = REPO / f"{name}.skill"
        digest = hashlib.sha256(content).hexdigest()
        if args.check:
            current = package.read_bytes() if package.is_file() else b""
            if hashlib.sha256(current).hexdigest() != digest:
                failures.append(name)
                print(f"out of date: {package.name}", file=sys.stderr)
            else:
                print(f"current: {package.name} ({len(content)} bytes, sha256 {digest[:12]})")
        else:
            package.write_bytes(content)
            entries = len(included_files(REPO / name))
            print(f"wrote {package.name}: {entries} entries, {len(content)} bytes, sha256 {digest[:12]}")
    if failures:
        print("Run: python3 tools/package_skills.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
