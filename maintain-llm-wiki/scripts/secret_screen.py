#!/usr/bin/env python3
"""Keep credentials out of the wiki, and out of every report about them.

The contract has always said that generated files contain no secrets. Nothing
checked it. A wiki is copied, synchronized through OneDrive or SharePoint,
released, exported as a frozen skill, and exported as an OKF bundle; once a key
has travelled that far it cannot be called back.

The screen is deliberately narrow. It recognizes forms that practically never
occur by accident in prose: private key blocks, token prefixes with a fixed
shape, JSON Web Tokens, and URLs carrying a user name and password. There is
no entropy heuristic, because every finding stops registration and release,
and a check that cries wolf gets worked around.

A finding names the file, the line, and the kind of credential - **never the
matched text**. The lint report is itself written into the wiki; repeating the
secret there would leak it a second time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


#: (kind, pattern). Kinds are stable identifiers suitable for reports.
PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("api-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("json-web-token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("url-credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@<>\"'`]+:[^/\s:@<>\"'`]+@")),
)

#: Text formats a wiki holds. Everything else is refused elsewhere or derived.
SCANNED_SUFFIXES = {".md", ".json", ".jsonl"}


def scan_text(text: str) -> list[tuple[int, str]]:
    """Return (line number, kind) for every credential-shaped line."""
    findings: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        for kind, pattern in PATTERNS:
            if pattern.search(line):
                findings.append((number, kind))
                break
    return findings


def describe(label: str, findings: Iterable[tuple[int, str]]) -> list[str]:
    """Render findings as report lines that never contain the matched value."""
    return [
        f"{label}:{number}: possible credential ({kind}); remove it and rotate it, "
        f"never publish it"
        for number, kind in findings
    ]


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Scan one file; unreadable files are reported by the checks that own them."""
    try:
        return scan_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return []
