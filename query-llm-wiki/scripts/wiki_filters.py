#!/usr/bin/env python3
"""Validated, read-only selectors for SkillSafeWerkstatt Markdown frontmatter."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Iterable

from frontmatter_contract import require_safe_property_name


OPERATORS = {
    "exists", "not_exists", "equals", "not_equals", "contains", "not_contains",
    "starts_with", "ends_with", "is_empty", "is_not_empty", "is_list", "is_string",
    "in_path",
}
VIRTUAL_PROPERTIES = {"__path", "__folder", "__filename", "__extension"}


def _virtual_value(property_name: str, path: str) -> str:
    pure = PurePosixPath(path)
    if property_name == "__path": return path
    if property_name == "__folder": return pure.parent.as_posix() if pure.parent.as_posix() != "." else ""
    if property_name == "__filename": return pure.stem
    if property_name == "__extension": return pure.suffix.lstrip(".")
    raise ValueError(f"unknown virtual property: {property_name}")


def validate_selector(value: object) -> dict[str, Any]:
    if value is None: return {"kind": "all"}
    if not isinstance(value, dict): raise ValueError("selector must be a JSON object")
    kind = value.get("kind", "filter")
    if kind == "all":
        if set(value) - {"kind"}: raise ValueError("all selector accepts only the kind field")
        return {"kind": "all"}
    if kind == "paths":
        paths = value.get("paths")
        if not isinstance(paths, list) or not paths or not all(isinstance(path, str) and path for path in paths):
            raise ValueError("paths selector requires a non-empty string array")
        return {"kind": "paths", "paths": sorted(set(paths))}
    if kind != "filter": raise ValueError("selector kind must be all, paths, or filter")
    conditions = value.get("conditions")
    if not isinstance(conditions, list) or not conditions or len(conditions) > 100:
        raise ValueError("filter selector requires between 1 and 100 conditions")
    combinator = value.get("combinator", "AND")
    if combinator not in {"AND", "OR"}: raise ValueError("selector combinator must be AND or OR")
    normalized: list[dict[str, Any]] = []
    for condition in conditions:
        if not isinstance(condition, dict): raise ValueError("each selector condition must be an object")
        unknown = set(condition) - {"property", "operator", "value", "case_sensitive"}
        if unknown: raise ValueError(f"unknown selector condition fields: {sorted(unknown)}")
        property_name = condition.get("property")
        if not isinstance(property_name, str): raise ValueError("selector condition property must be a string")
        if property_name not in VIRTUAL_PROPERTIES: property_name = require_safe_property_name(property_name)
        operator = condition.get("operator")
        if not isinstance(operator, str) or operator not in OPERATORS: raise ValueError(f"unsupported selector operator: {operator!r}")
        raw_value = condition.get("value", "")
        if "value" in condition and not isinstance(raw_value, (str, int, float, bool)):
            raise ValueError(f"selector value for {operator} must be scalar")
        if "case_sensitive" in condition and not isinstance(condition["case_sensitive"], bool): raise ValueError("selector case_sensitive must be boolean")
        normalized.append({"property": property_name, "operator": operator, "value": raw_value, "case_sensitive": condition.get("case_sensitive", False)})
    return {"kind": "filter", "conditions": normalized, "combinator": combinator}


def _empty(value: Any) -> bool: return value is None or value == "" or value == []
def _items(value: Any) -> list[Any]: return value if isinstance(value, list) else [value]
def _text(value: Any, case_sensitive: bool) -> str:
    rendered = str(value)
    return rendered if case_sensitive else rendered.casefold()


def matches_condition(data: dict[str, Any], path: str, condition: dict[str, Any]) -> bool:
    property_name = condition["property"]
    virtual = property_name in VIRTUAL_PROPERTIES
    present = virtual or property_name in data
    value = _virtual_value(property_name, path) if virtual else data.get(property_name)
    operator = condition["operator"]
    if operator == "exists": return present
    if operator == "not_exists": return not present
    if operator == "is_empty": return not present or _empty(value)
    if operator == "is_not_empty": return present and not _empty(value)
    if operator == "is_list": return present and isinstance(value, list)
    if operator == "is_string": return present and isinstance(value, str)
    case_sensitive = bool(condition.get("case_sensitive"))
    needle = _text(condition.get("value", ""), case_sensitive)
    if operator == "in_path": return needle in _text(path, case_sensitive)
    candidates = [_text(item, case_sensitive) for item in _items(value)] if present else []
    if operator == "equals": return any(item == needle for item in candidates)
    if operator == "not_equals": return not any(item == needle for item in candidates)
    if operator == "contains": return any(needle in item for item in candidates)
    if operator == "not_contains": return not any(needle in item for item in candidates)
    if operator == "starts_with": return any(item.startswith(needle) for item in candidates)
    if operator == "ends_with": return any(item.endswith(needle) for item in candidates)
    return False


def matches_selector(data: dict[str, Any], path: str, selector: dict[str, Any]) -> bool:
    if selector["kind"] == "all": return True
    if selector["kind"] == "paths": return path in selector["paths"]
    results = [matches_condition(data, path, condition) for condition in selector["conditions"]]
    return all(results) if selector["combinator"] == "AND" else any(results)


def select_rows(rows: Iterable[tuple[str, dict[str, Any]]], selector: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(path, data) for path, data in rows if matches_selector(data, path, selector)]
