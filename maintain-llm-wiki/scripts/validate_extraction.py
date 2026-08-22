#!/usr/bin/env python3
"""Assess a staged Markdown extraction before it enters a wiki."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


PAGE_MARKER = re.compile(r"<!--\s*(?:page|slide)\s*:\s*[^>]+-->", re.IGNORECASE)
SUSPICIOUS_HEADING = re.compile(r"^#{1,6}\s+#+(?:\s+#+)*\s*$")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def assess(path: Path, source_type: str = "unknown") -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        return {"state": "rejected", "errors": [f"extraction is not valid UTF-8: {exc}"], "warnings": []}
    except OSError as exc:
        return {"state": "rejected", "errors": [f"extraction is unavailable: {exc}"], "warnings": []}
    if not text.strip():
        errors.append("extraction is empty")
    if CONTROL.search(text):
        errors.append("extraction contains control characters")
    if "\ufffd" in text:
        errors.append("extraction contains Unicode replacement characters")
    lines = text.splitlines()
    longest = max((len(line) for line in lines), default=0)
    extreme_lines = [index for index, line in enumerate(lines, 1) if len(line) > 20000]
    long_lines = [index for index, line in enumerate(lines, 1) if 2000 < len(line) <= 20000]
    if extreme_lines:
        errors.append(f"extraction contains extremely long flattened lines: {extreme_lines[:10]}")
    if long_lines:
        warnings.append(f"extraction contains unusually long lines: {long_lines[:10]}")
    suspicious = [index for index, line in enumerate(lines, 1) if SUSPICIOUS_HEADING.fullmatch(line.strip())]
    if suspicious:
        warnings.append(f"extraction contains suspicious heading artifacts: {suspicious[:10]}")
    fences = sum(1 for line in lines if line.strip().startswith("```"))
    if fences % 2:
        errors.append("extraction contains an unclosed fenced code block")
    markers = len(PAGE_MARKER.findall(text))
    if source_type.casefold() in {"pdf", "presentation", "slides"} and markers == 0:
        warnings.append("page or slide markers are missing from a paged source extraction")
    table_dividers = sum(1 for line in lines if re.fullmatch(r"\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*", line))
    table_rows = sum(1 for line in lines if line.count("|") >= 2)
    if table_rows >= 4 and table_dividers == 0:
        warnings.append("table-like rows exist without a recognizable Markdown table divider")
    state = "rejected" if errors else "attention-needed" if warnings else "acceptable"
    return {
        "state": state,
        "recommended_status": "partial" if warnings or errors else "active",
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "bytes": len(text.encode("utf-8")),
            "lines": len(lines),
            "longest_line": longest,
            "page_or_slide_markers": markers,
            "table_like_rows": table_rows,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown-file", required=True)
    parser.add_argument("--source-type", default="unknown")
    args = parser.parse_args()
    report = assess(Path(args.markdown_file), args.source_type)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 4 if report["state"] == "rejected" else 2 if report["state"] == "attention-needed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
