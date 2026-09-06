#!/usr/bin/env python3
"""Invoke an allowlisted maintenance helper using a private runtime token file."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


HELPERS = {
    "apply_identity.py",
    "build_graph.py",
    "claim_id.py",
    "frontmatter_actions.py",
    "init_wiki.py",
    "inventory_wiki.py",
    "lint_wiki.py",
    "move_wiki_page.py",
    "page_batch.py",
    "plan_language_migration.py",
    "record_quality_review.py",
    "register_source.py",
    "release_wiki.py",
    "report_okf.py",
    "resolve_conflict_copy.py",
    "restore_wiki.py",
    "snapshot_wiki.py",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--helper", required=True, choices=sorted(HELPERS))
    # Everything not owned by this wrapper belongs to the selected helper.
    # parse_known_args allows ordinary helper flags without requiring a fragile
    # separator whose literal value could otherwise reach the child parser.
    args, helper_arguments = parser.parse_known_args()
    token_path = Path(args.token_file).expanduser().resolve()
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SystemExit(f"Runtime token file is unavailable: {exc}") from exc
    if not token.startswith("lk_"):
        raise SystemExit("Runtime token file does not contain a valid lock capability")
    helper = Path(__file__).resolve().parent / args.helper
    if helper_arguments[:1] == ["--"]:
        helper_arguments = helper_arguments[1:]
    command = [sys.executable, str(helper), *helper_arguments, "--lock-token", token]
    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
