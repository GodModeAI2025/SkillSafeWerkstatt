#!/usr/bin/env python3
"""Validate and render the confirmed identity of a SkillSafeWerkstatt wiki."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from frontmatter_contract import FrontmatterError, dump_frontmatter, parse_document


PLAN_FORMAT = "lmwiki-identity-plan/1"
SOUL_FIELDS = (
    "purpose",
    "knowledge_types",
    "audience",
    "answer_language",
    "form_of_address",
    "tone",
    "detail",
    "answer_structure",
    "citation_display",
    "uncertainty_style",
    "history_presentation",
    "boundaries",
    "taboos",
)
POLICY_FIELDS = (
    "update_model",
    "supersession_policy",
    "removal_policy",
    "conflict_policy",
)
UPDATE_MODELS = {"current-state", "historical-ledger", "hybrid"}
REMOVAL_POLICY = "preview-confirm-never-automatic"
CONFLICT_POLICY = "preserve-and-disclose"
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class IdentityError(ValueError):
    """Raised when an identity proposal or released identity is invalid."""


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_value(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def clean_string(value: Any, field: str, *, maximum: int = 1000) -> str:
    if not isinstance(value, str):
        raise IdentityError(f"{field} must be a string")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise IdentityError(f"{field} must not be empty")
    if len(cleaned) > maximum:
        raise IdentityError(f"{field} exceeds {maximum} characters")
    return cleaned


def clean_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise IdentityError(f"{field} must be a non-empty string list")
    cleaned = [clean_string(item, f"{field} item", maximum=160) for item in value]
    if len(cleaned) > 32:
        raise IdentityError(f"{field} may contain at most 32 items")
    return list(dict.fromkeys(cleaned))


def normalize_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IdentityError("identity must be an object")
    unknown = set(value) - set(SOUL_FIELDS)
    missing = set(SOUL_FIELDS) - set(value)
    if unknown:
        raise IdentityError(f"identity contains unknown fields: {sorted(unknown)}")
    if missing:
        raise IdentityError(f"identity is missing fields: {sorted(missing)}")
    normalized: dict[str, Any] = {}
    for field in SOUL_FIELDS:
        normalized[field] = (
            clean_string_list(value[field], field)
            if field == "knowledge_types"
            else clean_string(value[field], field)
        )
    if not LANGUAGE_RE.fullmatch(str(normalized["answer_language"])):
        raise IdentityError("answer_language must be a portable BCP-47-style language code")
    return normalized


def normalize_policy(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise IdentityError("content_policy must be an object")
    unknown = set(value) - set(POLICY_FIELDS)
    missing = set(POLICY_FIELDS) - set(value)
    if unknown:
        raise IdentityError(f"content_policy contains unknown fields: {sorted(unknown)}")
    if missing:
        raise IdentityError(f"content_policy is missing fields: {sorted(missing)}")
    normalized = {field: clean_string(value[field], field) for field in POLICY_FIELDS}
    if normalized["update_model"] not in UPDATE_MODELS:
        raise IdentityError(f"update_model must be one of {sorted(UPDATE_MODELS)}")
    if normalized["removal_policy"] != REMOVAL_POLICY:
        raise IdentityError(f"removal_policy must be {REMOVAL_POLICY}")
    if normalized["conflict_policy"] != CONFLICT_POLICY:
        raise IdentityError(f"conflict_policy must be {CONFLICT_POLICY}")
    return normalized


def render_soul(identity: dict[str, Any]) -> str:
    frontmatter = {
        "soul_version": 1,
        "status": "confirmed",
        **identity,
    }
    knowledge = "\n".join(f"- {item}" for item in identity["knowledge_types"])
    return dump_frontmatter(frontmatter) + f"""
# SOUL

Diese Datei beschreibt die bestätigte Identität und Antwortform dieses Wissensraums.
Sie steuert keine Berechtigungen und ändert keine belegten Inhalte.

## Zweck und Wissensarten

{identity['purpose']}

{knowledge}

## Zielgruppe

{identity['audience']}

## Tonalität und Antwortstil

- Antwortsprache: {identity['answer_language']}
- Anrede: {identity['form_of_address']}
- Tonalität: {identity['tone']}
- Ausführlichkeit: {identity['detail']}
- Antwortstruktur: {identity['answer_structure']}
- Quellenanzeige: {identity['citation_display']}
- Unsicherheit: {identity['uncertainty_style']}
- Historie in Antworten: {identity['history_presentation']}

## Grenzen und Tabus

Grenzen: {identity['boundaries']}

Tabus: {identity['taboos']}
"""


def render_content_policy(policy: dict[str, str]) -> str:
    frontmatter = {
        "policy_version": 1,
        "status": "confirmed",
        **policy,
    }
    return dump_frontmatter(frontmatter) + f"""
# Content policy

Diese Datei steuert die Pflege von aktuellem, historischem, ersetztem und
widersprüchlichem Wissen. Sie verändert oder löscht nichts automatisch.

## Aktualisierungsmodell

{policy['update_model']}

## Ersetzung

{policy['supersession_policy']}

## Entfernung

Entfernungsvorschläge benötigen immer eine Vorschau und eine ausdrückliche
Bestätigung. Quellen, Claims, Seiten und Historie werden niemals automatisch
gelöscht.

## Widersprüche

Belegte widersprüchliche Positionen bleiben erhalten und werden offengelegt,
bis ihre Anwendbarkeit oder Ersetzung belastbar geklärt ist.
"""


def build_plan(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise IdentityError("identity input must be an object")
    if set(raw) != {"identity", "content_policy"}:
        raise IdentityError("identity input must contain exactly identity and content_policy")
    identity = normalize_identity(raw["identity"])
    policy = normalize_policy(raw["content_policy"])
    payload = {
        "format": PLAN_FORMAT,
        "identity": identity,
        "content_policy": policy,
        "soul_markdown": render_soul(identity),
        "content_policy_markdown": render_content_policy(policy),
    }
    return {**payload, "proposal_sha256": sha256_value(payload)}


def validate_plan(plan: Any, expected_sha256: str) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("format") != PLAN_FORMAT:
        raise IdentityError("unsupported identity plan")
    actual_hash = str(plan.get("proposal_sha256") or "")
    payload = {key: value for key, value in plan.items() if key != "proposal_sha256"}
    calculated = sha256_value(payload)
    if not expected_sha256 or expected_sha256 != actual_hash or actual_hash != calculated:
        raise IdentityError("identity proposal is stale or was modified after confirmation")
    canonical = build_plan({"identity": plan.get("identity"), "content_policy": plan.get("content_policy")})
    if canonical != plan:
        raise IdentityError("identity proposal content is not canonical")
    return plan


def load_plan(path: Path, expected_sha256: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityError(f"identity plan is unavailable or invalid: {exc}") from exc
    return validate_plan(value, expected_sha256)


def validate_identity_files(target: Path, *, required: bool) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    status = {"soul": "missing", "content_policy": "missing"}
    soul_path = target / "SOUL.md"
    policy_path = target / "schema/CONTENT_POLICY.md"
    if not soul_path.is_file():
        if required:
            errors.append("SOUL.md is missing; the wiki identity was not confirmed")
    else:
        try:
            document = parse_document(soul_path.read_text(encoding="utf-8"), "SOUL.md", require_frontmatter=True)
            data = dict(document.data)
            if data.pop("soul_version", None) != 1 or data.pop("status", None) != "confirmed":
                raise IdentityError("SOUL.md must have soul_version 1 and status confirmed")
            normalize_identity(data)
            status["soul"] = "confirmed"
        except (OSError, UnicodeError, FrontmatterError, IdentityError) as exc:
            status["soul"] = "invalid"
            errors.append(str(exc))
    if not policy_path.is_file():
        if required:
            errors.append("schema/CONTENT_POLICY.md is missing; the curation policy was not confirmed")
    else:
        try:
            document = parse_document(policy_path.read_text(encoding="utf-8"), "schema/CONTENT_POLICY.md", require_frontmatter=True)
            data = dict(document.data)
            if data.pop("policy_version", None) != 1 or data.pop("status", None) != "confirmed":
                raise IdentityError("schema/CONTENT_POLICY.md must have policy_version 1 and status confirmed")
            normalize_policy(data)
            status["content_policy"] = "confirmed"
        except (OSError, UnicodeError, FrontmatterError, IdentityError) as exc:
            status["content_policy"] = "invalid"
            errors.append(str(exc))
    return status, errors
