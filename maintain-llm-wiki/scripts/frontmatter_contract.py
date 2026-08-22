#!/usr/bin/env python3
"""Strict, dependency-free frontmatter contract shared by SkillSafeWerkstatt helpers.

The wiki deliberately uses a portable YAML subset: one top-level mapping whose
values are scalars or flat scalar lists. Unsupported YAML is rejected with a
line-specific error instead of being guessed or silently discarded.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. -]{0,127}$")
INTEGER_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
FLOAT_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)\.[0-9]+(?:[eE][+-]?[0-9]+)?$")
RESERVED_KEYS = {"__proto__", "constructor", "prototype"}


class FrontmatterError(ValueError):
    """Raised when a document is outside the canonical frontmatter subset."""


@dataclass(frozen=True)
class ParsedDocument:
    data: dict[str, Any]
    body: str
    frontmatter: str
    comments: tuple[str, ...]
    newline: str
    has_frontmatter: bool


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def is_safe_property_name(key: object) -> bool:
    return (
        isinstance(key, str)
        and bool(KEY_RE.fullmatch(key))
        and key.strip() == key
        and key not in RESERVED_KEYS
    )


def require_safe_property_name(key: object) -> str:
    if not is_safe_property_name(key):
        raise FrontmatterError(f"unsafe or unsupported frontmatter property name: {key!r}")
    return str(key)


def _line_error(source: str, number: int, message: str) -> FrontmatterError:
    return FrontmatterError(f"{source}:{number}: {message}")


def _split_inline_list(value: str, source: str, number: int) -> list[str]:
    inner = value[1:-1].strip()
    if not inner:
        return []
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for character in inner:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\" and quote == '"':
            current.append(character)
            escaped = True
            continue
        if quote:
            current.append(character)
            if character == quote:
                quote = ""
            continue
        if character in {'"', "'"}:
            current.append(character)
            quote = character
            continue
        if character == ",":
            parts.append("".join(current).strip())
            current = []
            continue
        if character in "[]{}":
            raise _line_error(source, number, "nested collections are not supported")
        current.append(character)
    if quote:
        raise _line_error(source, number, "unterminated quoted value in inline list")
    parts.append("".join(current).strip())
    if any(part == "" for part in parts):
        raise _line_error(source, number, "inline lists may not contain empty items")
    return parts


def parse_scalar(value: str, source: str = "<memory>", number: int = 1, *, allow_list: bool = True) -> Any:
    raw = value.strip()
    if raw == "":
        return ""
    if raw[0] in "|>" or raw.startswith(("&", "*", "!")):
        raise _line_error(source, number, "block scalars, anchors, aliases, and tags are unsupported")
    if raw.startswith("[") or raw.endswith("]"):
        if not allow_list or not (raw.startswith("[") and raw.endswith("]")):
            raise _line_error(source, number, "malformed or nested inline list")
        return [parse_scalar(part, source, number, allow_list=False) for part in _split_inline_list(raw, source, number)]
    if raw.startswith("{") or raw.endswith("}"):
        raise _line_error(source, number, "nested mappings are not supported")
    if raw.startswith('"'):
        if not raw.endswith('"') or len(raw) < 2:
            raise _line_error(source, number, "unterminated double-quoted value")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _line_error(source, number, f"invalid double-quoted value: {exc.msg}") from exc
        if not isinstance(parsed, str):
            raise _line_error(source, number, "quoted scalar must decode to a string")
        return parsed
    if raw.startswith("'"):
        if not raw.endswith("'") or len(raw) < 2:
            raise _line_error(source, number, "unterminated single-quoted value")
        return raw[1:-1].replace("''", "'")
    lowered = raw.casefold()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if INTEGER_RE.fullmatch(raw):
        return int(raw)
    if FLOAT_RE.fullmatch(raw):
        parsed_float = float(raw)
        if not math.isfinite(parsed_float):
            raise _line_error(source, number, "non-finite numbers are unsupported")
        return parsed_float
    return raw


def parse_document(text: str, source: str = "<memory>", *, require_frontmatter: bool = False) -> ParsedDocument:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        if require_frontmatter:
            raise _line_error(source, 1, "missing YAML frontmatter")
        return ParsedDocument({}, text, "", (), newline, False)

    end = -1
    for index, line in enumerate(lines[1:], 1):
        if line.rstrip("\r\n") == "---":
            end = index
            break
    if end < 0:
        raise _line_error(source, 1, "unclosed YAML frontmatter")

    data: dict[str, Any] = {}
    comments: list[str] = []
    current_list: Optional[str] = None
    for index, raw_line in enumerate(lines[1:end], 2):
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise _line_error(source, index, "tabs are not allowed for indentation")
        if line.lstrip().startswith("#"):
            comments.append(line.lstrip())
            continue
        if line.startswith("  - "):
            if current_list is None:
                raise _line_error(source, index, "list item has no preceding property")
            item = parse_scalar(line[4:], source, index, allow_list=False)
            if isinstance(item, (list, dict)):
                raise _line_error(source, index, "nested list items are not supported")
            data[current_list].append(item)
            continue
        if line.startswith("-") or line.startswith(" "):
            raise _line_error(source, index, "only two-space-indented flat list items are supported")
        if ":" not in line:
            raise _line_error(source, index, "expected a top-level key followed by ':'")
        raw_key, raw_value = line.split(":", 1)
        if raw_key != raw_key.strip():
            raise _line_error(source, index, "frontmatter property names may not have surrounding whitespace")
        key = require_safe_property_name(raw_key)
        if key in data:
            raise _line_error(source, index, f"duplicate frontmatter property {key!r}")
        if raw_value.strip() == "":
            data[key] = []
            current_list = key
        else:
            data[key] = parse_scalar(raw_value, source, index)
            current_list = None

    frontmatter = "".join(lines[: end + 1])
    body = "".join(lines[end + 1 :])
    return ParsedDocument(data, body, frontmatter, tuple(comments), newline, True)


def parse_file(path: Path, *, require_frontmatter: bool = False) -> ParsedDocument:
    return parse_document(
        path.read_text(encoding="utf-8"),
        path.as_posix(),
        require_frontmatter=require_frontmatter,
    )


def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        item_types = sorted({value_type(item) for item in value})
        return "list" if not item_types else f"list<{ '|'.join(item_types) }>"
    return "unsupported"


def _dump_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise FrontmatterError(f"unsupported frontmatter value type: {type(value).__name__}")


def dump_frontmatter(data: dict[str, Any], comments: Iterable[str] = (), newline: str = "\n") -> str:
    lines = ["---"]
    lines.extend(str(comment) for comment in comments)
    for raw_key, value in data.items():
        key = require_safe_property_name(raw_key)
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    if isinstance(item, (list, dict)):
                        raise FrontmatterError(f"nested collection in property {key!r} is unsupported")
                    lines.append(f"  - {_dump_scalar(item)}")
        elif isinstance(value, dict):
            raise FrontmatterError(f"nested mapping in property {key!r} is unsupported")
        else:
            lines.append(f"{key}: {_dump_scalar(value)}")
    lines.append("---")
    return newline.join(lines) + newline


def compose_document(document: ParsedDocument, data: dict[str, Any]) -> str:
    body = document.body
    return dump_frontmatter(data, document.comments, document.newline) + body
