#!/usr/bin/env python3
"""Plan and apply hash-guarded frontmatter actions inside SkillSafeWerkstatt."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Optional
from uuid import uuid4

from frontmatter_contract import (
    FrontmatterError,
    compose_document,
    dump_frontmatter,
    parse_document,
    require_safe_property_name,
    sha256_bytes,
)
from snapshot_wiki import create_snapshot
from wiki_filters import matches_selector, validate_selector
from wiki_lock import require_lock


PLAN_FORMAT = "lmwiki-frontmatter-plan/1"
RESULT_FORMAT = "lmwiki-frontmatter-result/1"
WIKILINK = re.compile(r"^\[\[([^\]#|]+)(#[^\]|]+)?(?:\|([^\]]*))?\]\]$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TRANSFORMS = {"trim", "lowercase", "titlecase", "strip_diacritics"}
CONFLICT_MODES = {"skip", "overwrite", "merge_list"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def portable_relative(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return not posix.is_absolute() and not windows.is_absolute() and not windows.drive and ".." not in posix.parts and "\\" not in value and posix.as_posix() == value


def candidate_paths(target: Path, selector: dict[str, Any]) -> list[Path]:
    roots = (target / "wiki", target / "sources")
    found = [path for root in roots if root.is_dir() for path in root.rglob("*.md")]
    if selector["kind"] == "paths":
        selected = []
        for relative in selector["paths"]:
            if not portable_relative(relative):
                raise ValueError(f"selector path is not portable: {relative!r}")
            path = target / relative
            if path.is_symlink():
                raise ValueError(f"selector path may not be a symbolic link: {relative!r}")
            if not path.is_file():
                raise ValueError(f"selector path does not exist: {relative!r}")
            if path.suffix.casefold() != ".md":
                raise ValueError(f"selector path is not Markdown: {relative!r}")
            selected.append(path)
        return sorted(set(selected))
    symbolic = [path.relative_to(target).as_posix() for path in found if path.is_symlink()]
    if symbolic:
        raise ValueError(f"frontmatter planning refuses symbolic links: {symbolic}")
    return sorted(found)


def supported_value(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    return isinstance(value, list) and all(supported_value(item) and not isinstance(item, list) for item in value)


def _only(action: dict[str, Any], fields: set[str]) -> None:
    unknown = set(action) - fields
    if unknown:
        raise ValueError(f"unknown action fields: {sorted(unknown)}")


def validate_action(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("action must be a JSON object")
    action_type = value.get("type")
    if not isinstance(action_type, str):
        raise ValueError("action type must be a string")
    if action_type == "set":
        _only(value, {"type", "property", "value", "mode"})
        property_name = require_safe_property_name(value.get("property"))
        field_value = value.get("value")
        if not supported_value(field_value):
            raise ValueError("set value must be a scalar or flat scalar list")
        mode = value.get("mode", "skip")
        if not isinstance(mode, str) or mode not in {"skip", "overwrite", "merge_list"}:
            raise ValueError("set mode must be skip, overwrite, or merge_list")
        return {"type": action_type, "property": property_name, "value": field_value, "mode": mode}
    if action_type == "delete":
        _only(value, {"type", "properties"})
        properties = value.get("properties")
        if not isinstance(properties, list) or not properties:
            raise ValueError("delete requires a non-empty properties array")
        return {"type": action_type, "properties": [require_safe_property_name(item) for item in properties]}
    if action_type in {"rename", "copy", "merge"}:
        _only(value, {"type", "from_properties", "to_property", "on_conflict"})
        sources = value.get("from_properties")
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"{action_type} requires a non-empty from_properties array")
        conflict = value.get("on_conflict", "skip" if action_type != "merge" else "merge_list")
        if not isinstance(conflict, str) or conflict not in CONFLICT_MODES:
            raise ValueError("on_conflict must be skip, overwrite, or merge_list")
        return {
            "type": action_type,
            "from_properties": [require_safe_property_name(item) for item in sources],
            "to_property": require_safe_property_name(value.get("to_property")),
            "on_conflict": conflict,
        }
    if action_type == "normalize_values":
        _only(value, {"type", "property", "transforms", "mappings", "preserve_wikilinks"})
        transforms = value.get("transforms", [])
        if not isinstance(transforms, list) or any(not isinstance(item, str) or item not in TRANSFORMS for item in transforms):
            raise ValueError(f"transforms must contain only {sorted(TRANSFORMS)}")
        mappings = value.get("mappings", [])
        if not isinstance(mappings, list):
            raise ValueError("mappings must be an array")
        normalized_mappings = []
        for mapping in mappings:
            if not isinstance(mapping, dict) or set(mapping) != {"from", "to"} or not all(isinstance(mapping.get(key), str) for key in ("from", "to")):
                raise ValueError("each mapping must contain string fields from and to")
            normalized_mappings.append({"from": mapping["from"], "to": mapping["to"]})
        return {
            "type": action_type,
            "property": require_safe_property_name(value.get("property")),
            "transforms": transforms,
            "mappings": normalized_mappings,
            "preserve_wikilinks": bool(value.get("preserve_wikilinks", True)),
        }
    if action_type == "dedupe_wikilinks":
        _only(value, {"type", "properties"})
        properties = value.get("properties", [])
        if not isinstance(properties, list):
            raise ValueError("dedupe_wikilinks properties must be an array")
        return {"type": action_type, "properties": [require_safe_property_name(item) for item in properties]}
    raise ValueError("action type must be set, delete, rename, copy, merge, normalize_values, or dedupe_wikilinks")


def merge_values(left: Any, right: Any) -> list[Any]:
    values = (left if isinstance(left, list) else [left]) + (right if isinstance(right, list) else [right])
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def normalize_string(value: str, transforms: Iterable[str]) -> str:
    result = value
    for transform in transforms:
        if transform == "trim":
            result = result.strip()
        elif transform == "lowercase":
            result = result.casefold()
        elif transform == "titlecase":
            result = result.title()
        elif transform == "strip_diacritics":
            decomposed = unicodedata.normalize("NFKD", result)
            result = "".join(character for character in decomposed if not unicodedata.combining(character))
    return result


def normalize_value(value: Any, action: dict[str, Any]) -> Any:
    mappings = {item["from"]: item["to"] for item in action["mappings"]}

    def one(item: Any) -> Any:
        if not isinstance(item, str):
            return item
        if action["preserve_wikilinks"] and WIKILINK.fullmatch(item):
            return item
        transformed = normalize_string(item, action["transforms"])
        return mappings.get(transformed, transformed)

    if isinstance(value, list):
        result = []
        for item in value:
            mapped = one(item)
            if mapped == "":
                continue
            if mapped not in result:
                result.append(mapped)
        return result
    return one(value)


def link_resolver(target: Path) -> dict[str, Optional[str]]:
    markdown = [path for root in (target / "wiki", target / "sources", target / "schema") if root.is_dir() for path in root.rglob("*.md")]
    canonical = {path.relative_to(target).with_suffix("").as_posix(): path for path in markdown}
    by_stem: dict[str, list[str]] = {}
    for name in canonical:
        by_stem.setdefault(PurePosixPath(name).name, []).append(name)
    resolver: dict[str, Optional[str]] = {name: name for name in canonical}
    for stem, names in by_stem.items():
        resolver[stem] = names[0] if len(names) == 1 else None
    return resolver


def dedupe_link_value(value: Any, resolver: dict[str, Optional[str]]) -> tuple[Any, list[dict[str, str]]]:
    scalar = not isinstance(value, list)
    items = value if isinstance(value, list) else [value]
    output: list[Any] = []
    seen: set[str] = set()
    changes: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, str):
            output.append(item)
            continue
        match = WIKILINK.fullmatch(item)
        if not match:
            output.append(item)
            continue
        raw_target, subpath, alias = match.group(1).strip(), match.group(2) or "", match.group(3)
        raw_path = raw_target.replace("\\", "/")
        portable = not PurePosixPath(raw_path).is_absolute() and ".." not in PurePosixPath(raw_path).parts and "\\" not in raw_target
        normalized_target = raw_path.removesuffix(".md").removeprefix("./")
        resolved = resolver.get(normalized_target) if portable else None
        canonical = resolved or normalized_target
        alias_part = "" if alias is None else "|" + alias
        emitted = f"[[{canonical}{subpath}{alias_part}]]" if resolved else item
        key = f"{resolved or 'broken:' + item}\0{subpath}\0{alias or ''}"
        if key in seen:
            changes.append({"kind": "removed-duplicate", "from": item, "to": ""})
            continue
        seen.add(key)
        if emitted != item:
            changes.append({"kind": "canonicalized", "from": item, "to": emitted})
        output.append(emitted)
    if scalar:
        return (output[0] if output else value), changes
    return output, changes


def apply_action(data: dict[str, Any], action: dict[str, Any], resolver: dict[str, Optional[str]]) -> tuple[dict[str, Any], str, list[dict[str, str]]]:
    after = copy.deepcopy(data)
    action_type = action["type"]
    details: list[dict[str, str]] = []
    if action_type == "set":
        property_name = action["property"]
        exists = property_name in after and after[property_name] not in (None, "", [])
        if exists and action["mode"] == "skip":
            return after, "property already set", details
        if exists and action["mode"] == "merge_list":
            after[property_name] = merge_values(after[property_name], action["value"])
        else:
            after[property_name] = copy.deepcopy(action["value"])
    elif action_type == "delete":
        removed = [property_name for property_name in action["properties"] if property_name in after]
        for property_name in removed:
            del after[property_name]
        if not removed:
            return after, "no matching property", details
    elif action_type in {"rename", "copy", "merge"}:
        source_properties = [item for item in action["from_properties"] if item in after]
        if not source_properties:
            return after, "no source property present", details
        collected: Any = after[source_properties[0]]
        for property_name in source_properties[1:]:
            collected = merge_values(collected, after[property_name])
        target_property = action["to_property"]
        target_exists = target_property in after and after[target_property] not in (None, "", [])
        if target_exists and action["on_conflict"] == "skip":
            return after, "target property exists", details
        if target_exists and action["on_conflict"] == "merge_list":
            collected = merge_values(after[target_property], collected)
        after[target_property] = copy.deepcopy(collected)
        if action_type in {"rename", "merge"}:
            for property_name in source_properties:
                if property_name != target_property:
                    del after[property_name]
    elif action_type == "normalize_values":
        property_name = action["property"]
        if property_name not in after:
            return after, "property not present", details
        after[property_name] = normalize_value(after[property_name], action)
    elif action_type == "dedupe_wikilinks":
        properties = action["properties"] or list(after)
        touched = False
        for property_name in properties:
            if property_name not in after:
                continue
            rewritten, changes = dedupe_link_value(after[property_name], resolver)
            if changes:
                after[property_name] = rewritten
                details.extend({"property": property_name, **change} for change in changes)
                touched = True
        if not touched:
            return after, "no duplicate or non-canonical wikilink", details
    if after == data:
        return after, "no value change", details
    return after, "", details


def action_destructive(action: dict[str, Any]) -> bool:
    if action["type"] in {"delete", "rename", "merge", "normalize_values", "dedupe_wikilinks"}:
        return True
    if action["type"] == "set":
        return action["mode"] == "overwrite"
    return action.get("on_conflict") == "overwrite"


def load_json_argument(raw: str, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} is invalid JSON: {exc}") from exc


def plan_action(target: Path, selector: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    target = target.expanduser().resolve()
    resolver = link_resolver(target)
    entries: list[dict[str, Any]] = []
    parser_errors: list[dict[str, str]] = []
    matched = 0
    for path in candidate_paths(target, selector):
        relative = path.relative_to(target).as_posix()
        try:
            original_bytes = path.read_bytes()
            document = parse_document(original_bytes.decode("utf-8"), relative, require_frontmatter=True)
        except (OSError, UnicodeError, FrontmatterError) as exc:
            parser_errors.append({"path": relative, "error": str(exc)})
            continue
        if not matches_selector(document.data, relative, selector):
            continue
        matched += 1
        after, skipped, details = apply_action(document.data, action, resolver)
        after_text = compose_document(document, after)
        canonical_before = dump_frontmatter(document.data, document.comments, document.newline)
        entry = {
            "path": relative,
            "before_sha256": sha256_bytes(original_bytes),
            "after_sha256": sha256_bytes(after_text.encode("utf-8")),
            "changed": after != document.data,
            "skipped_reason": skipped,
            "before": document.data,
            "after": after,
            "after_order": list(after),
            "details": details,
            "frontmatter_reformatted": after != document.data and document.frontmatter != canonical_before,
        }
        entries.append(entry)
    core = {
        "format": PLAN_FORMAT,
        "plan_id": str(uuid4()),
        "created_at": utc_now(),
        "target": ".",
        "selector": selector,
        "action": action,
        "destructive": action_destructive(action),
        "requires_confirmation": action_destructive(action),
        "matched_count": matched,
        "change_count": sum(1 for entry in entries if entry["changed"]),
        "skipped_count": sum(1 for entry in entries if not entry["changed"]),
        "parser_errors": parser_errors,
        "files": entries,
    }
    core["plan_sha256"] = hashlib.sha256(canonical_json(core)).hexdigest()
    return core


def validate_plan(value: object, expected_hash: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("format") != PLAN_FORMAT:
        raise ValueError("unsupported or missing frontmatter plan format")
    allowed_plan_fields = {"format", "plan_id", "created_at", "target", "selector", "action", "destructive", "requires_confirmation", "matched_count", "change_count", "skipped_count", "parser_errors", "files", "plan_sha256"}
    if set(value) != allowed_plan_fields:
        raise ValueError(f"frontmatter plan fields differ from the contract: {sorted(set(value) ^ allowed_plan_fields)}")
    recorded = value.get("plan_sha256")
    core = {key: item for key, item in value.items() if key != "plan_sha256"}
    actual = hashlib.sha256(canonical_json(core)).hexdigest()
    if not isinstance(recorded, str) or recorded != actual:
        raise ValueError("frontmatter plan integrity check failed")
    if expected_hash != recorded:
        raise ValueError("confirmed plan hash does not match the plan")
    files = value.get("files")
    if not isinstance(files, list):
        raise ValueError("frontmatter plan files must be an array")
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or not portable_relative(entry.get("path")):
            raise ValueError("frontmatter plan contains a non-portable path")
        if entry["path"] in seen:
            raise ValueError(f"frontmatter plan contains duplicate path: {entry['path']}")
        seen.add(entry["path"])
        if not isinstance(entry.get("before_sha256"), str) or not SHA256.fullmatch(str(entry.get("before_sha256"))) or not isinstance(entry.get("after_sha256"), str) or not SHA256.fullmatch(str(entry.get("after_sha256"))) or not isinstance(entry.get("after"), dict):
            raise ValueError(f"frontmatter plan entry is incomplete: {entry['path']}")
        if any(not supported_value(item) for item in entry["after"].values()):
            raise ValueError(f"frontmatter plan contains unsupported output values: {entry['path']}")
        after_order = entry.get("after_order")
        if not isinstance(after_order, list) or not all(isinstance(item, str) for item in after_order) or len(after_order) != len(set(after_order)) or set(after_order) != set(entry["after"]):
            raise ValueError(f"frontmatter plan has an invalid property order: {entry['path']}")
    validate_selector(value.get("selector"))
    validate_action(value.get("action"))
    return value


def apply_plan(target: Path, lock_token: str, plan: dict[str, Any], confirm_destructive: bool) -> tuple[dict[str, Any], int]:
    target = target.expanduser().resolve()
    require_lock(target, lock_token)
    if plan.get("parser_errors"):
        return {"format": RESULT_FORMAT, "state": "plan_refused", "reason": "plan contains parser errors", "parser_errors": plan["parser_errors"]}, 2
    if plan.get("destructive") and not confirm_destructive:
        return {"format": RESULT_FORMAT, "state": "confirmation_required", "plan_sha256": plan["plan_sha256"]}, 2
    changed = [entry for entry in plan["files"] if entry.get("changed")]
    conflicts = []
    preparation_errors: list[dict[str, str]] = []
    prepared: dict[str, bytes] = {}
    for entry in changed:
        path = target / entry["path"]
        try:
            current_bytes = path.read_bytes()
            current_hash = sha256_bytes(current_bytes)
        except OSError:
            current_bytes = b""
            current_hash = ""
        if current_hash != entry["before_sha256"]:
            conflicts.append({"path": entry["path"], "expected_sha256": entry["before_sha256"], "current_sha256": current_hash})
            continue
        try:
            document = parse_document(current_bytes.decode("utf-8"), entry["path"], require_frontmatter=True)
            ordered_after = {key: entry["after"][key] for key in entry["after_order"]}
            output = compose_document(document, ordered_after).encode("utf-8")
            if sha256_bytes(output) != entry["after_sha256"]:
                raise ValueError("planned output hash could not be reproduced")
            prepared[entry["path"]] = output
        except (UnicodeError, FrontmatterError, KeyError, ValueError) as exc:
            preparation_errors.append({"path": entry["path"], "error": str(exc)})
    if conflicts:
        return {"format": RESULT_FORMAT, "state": "stale_plan", "plan_sha256": plan["plan_sha256"], "conflicts": conflicts, "written": []}, 3
    if preparation_errors:
        return {"format": RESULT_FORMAT, "state": "plan_refused", "plan_sha256": plan["plan_sha256"], "errors": preparation_errors, "written": []}, 2
    if not changed:
        return {"format": RESULT_FORMAT, "state": "no_changes", "plan_sha256": plan["plan_sha256"], "written": [], "skipped_count": plan["skipped_count"]}, 0

    snapshot = create_snapshot(target, lock_token, operation=f"frontmatter:{plan['action']['type']}", selected_files=[entry["path"] for entry in changed])
    written: list[str] = []
    errors: list[dict[str, str]] = []
    for entry in changed:
        path = target / entry["path"]
        try:
            current_bytes = path.read_bytes()
            current_hash = sha256_bytes(current_bytes)
            if current_hash != entry["before_sha256"]:
                errors.append({"path": entry["path"], "error": "concurrent edit detected immediately before write"})
                break
            output = prepared[entry["path"]]
            atomic_write(path, output)
            written.append(entry["path"])
        except (OSError, UnicodeError, FrontmatterError, ValueError) as exc:
            errors.append({"path": entry["path"], "error": str(exc)})
            break
    result = {
        "format": RESULT_FORMAT,
        "state": "applied" if not errors else "partial_failure",
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "action": plan["action"]["type"],
        "snapshot": snapshot["snapshot"],
        "written": written,
        "written_count": len(written),
        "skipped_count": plan["skipped_count"],
        "errors": errors,
    }
    snapshot_dir = target / snapshot["snapshot"]
    atomic_write(snapshot_dir / "action-result.json", json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return result, 0 if not errors else 5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="Create an immutable before/after plan")
    plan_parser.add_argument("--target", required=True)
    plan_parser.add_argument("--lock-token", required=True)
    plan_parser.add_argument("--selector-json", default='{"kind":"all"}')
    plan_parser.add_argument("--action-json", required=True)
    plan_parser.add_argument("--output", required=True, help="Temporary plan file used for the approved apply step")
    apply_parser = subparsers.add_parser("apply", help="Apply exactly one confirmed plan")
    apply_parser.add_argument("--target", required=True)
    apply_parser.add_argument("--lock-token", required=True)
    apply_parser.add_argument("--plan-file", required=True)
    apply_parser.add_argument("--expect-plan-sha256", required=True)
    apply_parser.add_argument("--confirm-destructive", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    if args.command == "plan":
        selector = validate_selector(load_json_argument(args.selector_json, "selector-json"))
        action = validate_action(load_json_argument(args.action_json, "action-json"))
        plan = plan_action(target, selector, action)
        output = Path(args.output).expanduser().resolve()
        atomic_write(output, json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if not plan["parser_errors"] else 2
    try:
        raw_plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
        plan = validate_plan(raw_plan, args.expect_plan_sha256)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"Cannot apply frontmatter plan: {exc}") from exc
    result, code = apply_plan(target, args.lock_token, plan, args.confirm_destructive)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
