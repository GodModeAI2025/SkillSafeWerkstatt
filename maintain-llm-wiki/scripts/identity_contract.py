#!/usr/bin/env python3
"""Validate and render the confirmed identity of a SkillSafeWerkstatt wiki."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from frontmatter_contract import FrontmatterError, dump_frontmatter, parse_document


PLAN_FORMAT = "lmwiki-identity-plan/2"
PLAN_INPUT_FIELDS = ("identity", "content_policy", "wiki_language")
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

#: Scaffolding prose of the rendered identity files, keyed by primary language.
#: The user's field values are written exactly as supplied; only the headings
#: and explanatory paragraphs the generator adds follow the wiki language, as
#: the wiki-language contract requires for maintained prose. Codes without a
#: table fall back to English, the same choice `init_wiki.py` makes for its
#: generated navigation prose.
FALLBACK_LANGUAGE = "en"
IDENTITY_TEXTS: dict[str, dict[str, str]] = {
    "de": {
        "soul_intro": (
            "Diese Datei beschreibt die bestätigte Identität und Antwortform dieses Wissensraums.\n"
            "Sie steuert keine Berechtigungen und ändert keine belegten Inhalte."
        ),
        "soul_purpose": "Zweck und Wissensarten",
        "soul_audience": "Zielgruppe",
        "soul_style": "Tonalität und Antwortstil",
        "answer_language": "Antwortsprache",
        "form_of_address": "Anrede",
        "tone": "Tonalität",
        "detail": "Ausführlichkeit",
        "answer_structure": "Antwortstruktur",
        "citation_display": "Quellenanzeige",
        "uncertainty_style": "Unsicherheit",
        "history_presentation": "Historie in Antworten",
        "soul_limits": "Grenzen und Tabus",
        "boundaries": "Grenzen",
        "taboos": "Tabus",
        "policy_title": "Content policy",
        "policy_intro": (
            "Diese Datei steuert die Pflege von aktuellem, historischem, ersetztem und\n"
            "widersprüchlichem Wissen. Sie verändert oder löscht nichts automatisch."
        ),
        "policy_update": "Aktualisierungsmodell",
        "policy_supersession": "Ersetzung",
        "policy_removal": "Entfernung",
        "policy_removal_text": (
            "Entfernungsvorschläge benötigen immer eine Vorschau und eine ausdrückliche\n"
            "Bestätigung. Quellen, Claims, Seiten und Historie werden niemals automatisch\n"
            "gelöscht."
        ),
        "policy_conflicts": "Widersprüche",
        "policy_conflicts_text": (
            "Belegte widersprüchliche Positionen bleiben erhalten und werden offengelegt,\n"
            "bis ihre Anwendbarkeit oder Ersetzung belastbar geklärt ist."
        ),
    },
    "en": {
        "soul_intro": (
            "This file describes the confirmed identity and answer form of this knowledge space.\n"
            "It grants no permissions and changes no sourced content."
        ),
        "soul_purpose": "Purpose and knowledge types",
        "soul_audience": "Audience",
        "soul_style": "Tone and answer style",
        "answer_language": "Answer language",
        "form_of_address": "Form of address",
        "tone": "Tone",
        "detail": "Detail",
        "answer_structure": "Answer structure",
        "citation_display": "Citation display",
        "uncertainty_style": "Uncertainty",
        "history_presentation": "History in answers",
        "soul_limits": "Boundaries and taboos",
        "boundaries": "Boundaries",
        "taboos": "Taboos",
        "policy_title": "Content policy",
        "policy_intro": (
            "This file governs how current, historical, superseded and conflicting knowledge\n"
            "is maintained. It changes or deletes nothing automatically."
        ),
        "policy_update": "Update model",
        "policy_supersession": "Supersession",
        "policy_removal": "Removal",
        "policy_removal_text": (
            "Removal proposals always require a preview and an explicit confirmation.\n"
            "Sources, claims, pages and history are never deleted automatically."
        ),
        "policy_conflicts": "Conflicts",
        "policy_conflicts_text": (
            "Sourced conflicting positions are preserved and disclosed until their\n"
            "applicability or supersession is reliably settled."
        ),
    },
}


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


def normalize_wiki_language(value: Any) -> str:
    """Return the wiki-language code the identity files are rendered for."""
    if not isinstance(value, str) or not LANGUAGE_RE.fullmatch(value.strip()):
        raise IdentityError("wiki_language must be a portable BCP-47-style language code")
    return value.strip()


def primary_language(wiki_language: str) -> str:
    """`en-GB` and `en-US` share one scaffolding; the primary subtag decides."""
    return wiki_language.split("-", 1)[0].casefold()


def identity_texts(wiki_language: str) -> dict[str, str]:
    return IDENTITY_TEXTS.get(primary_language(wiki_language), IDENTITY_TEXTS[FALLBACK_LANGUAGE])


def render_soul(identity: dict[str, Any], wiki_language: str) -> str:
    frontmatter = {
        "soul_version": 1,
        "status": "confirmed",
        **identity,
    }
    knowledge = "\n".join(f"- {item}" for item in identity["knowledge_types"])
    text = identity_texts(wiki_language)
    return dump_frontmatter(frontmatter) + f"""
# SOUL

{text['soul_intro']}

## {text['soul_purpose']}

{identity['purpose']}

{knowledge}

## {text['soul_audience']}

{identity['audience']}

## {text['soul_style']}

- {text['answer_language']}: {identity['answer_language']}
- {text['form_of_address']}: {identity['form_of_address']}
- {text['tone']}: {identity['tone']}
- {text['detail']}: {identity['detail']}
- {text['answer_structure']}: {identity['answer_structure']}
- {text['citation_display']}: {identity['citation_display']}
- {text['uncertainty_style']}: {identity['uncertainty_style']}
- {text['history_presentation']}: {identity['history_presentation']}

## {text['soul_limits']}

{text['boundaries']}: {identity['boundaries']}

{text['taboos']}: {identity['taboos']}
"""


def render_content_policy(policy: dict[str, str], wiki_language: str) -> str:
    frontmatter = {
        "policy_version": 1,
        "status": "confirmed",
        **policy,
    }
    text = identity_texts(wiki_language)
    return dump_frontmatter(frontmatter) + f"""
# {text['policy_title']}

{text['policy_intro']}

## {text['policy_update']}

{policy['update_model']}

## {text['policy_supersession']}

{policy['supersession_policy']}

## {text['policy_removal']}

{text['policy_removal_text']}

## {text['policy_conflicts']}

{text['policy_conflicts_text']}
"""


def build_plan(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise IdentityError("identity input must be an object")
    if set(raw) != set(PLAN_INPUT_FIELDS):
        raise IdentityError(
            "identity input must contain exactly identity, content_policy, and wiki_language"
        )
    identity = normalize_identity(raw["identity"])
    policy = normalize_policy(raw["content_policy"])
    wiki_language = normalize_wiki_language(raw["wiki_language"])
    payload = {
        "format": PLAN_FORMAT,
        "wiki_language": wiki_language,
        "identity": identity,
        "content_policy": policy,
        "soul_markdown": render_soul(identity, wiki_language),
        "content_policy_markdown": render_content_policy(policy, wiki_language),
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
    canonical = build_plan({field: plan.get(field) for field in PLAN_INPUT_FIELDS})
    if canonical != plan:
        raise IdentityError("identity proposal content is not canonical")
    return plan


def load_plan(path: Path, expected_sha256: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityError(f"identity plan is unavailable or invalid: {exc}") from exc
    return validate_plan(value, expected_sha256)


def require_plan_language(plan: dict[str, Any], wiki_language: str, described_as: str) -> None:
    """Refuse a proposal rendered for a different wiki language than the target's.

    The rendered headings and prose are part of what the user confirmed, so a
    plan for one language must not be written into a wiki of another. Codes
    compare case-insensitively, like every other BCP-47 comparison here.
    """
    plan_language = str(plan.get("wiki_language") or "")
    if plan_language.casefold() != wiki_language.strip().casefold():
        raise IdentityError(
            f"identity proposal was rendered for wiki language {plan_language!r}, "
            f"but {described_as} is {wiki_language!r}; render a new proposal for that language"
        )


def profile_wiki_language(target: Path) -> str:
    """Read the configured wiki language of an initialized wiki, or refuse."""
    relative = "schema/WIKI_PROFILE.md"
    path = target / relative
    if not path.is_file():
        raise IdentityError(f"{relative} is missing; the wiki language of the target is unknown")
    try:
        document = parse_document(path.read_text(encoding="utf-8"), relative, require_frontmatter=True)
    except (OSError, UnicodeError, FrontmatterError) as exc:
        raise IdentityError(f"{relative} is unreadable: {exc}") from exc
    value = document.data.get("wiki_language")
    if not isinstance(value, str) or not LANGUAGE_RE.fullmatch(value):
        raise IdentityError(f"{relative} has no readable wiki_language")
    return value


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
