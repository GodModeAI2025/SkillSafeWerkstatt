#!/usr/bin/env python3
"""Inspect the released SOUL and content policy without executing their prose."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from frontmatter_contract import FrontmatterError, parse_document


SOUL_REQUIRED = {
    "soul_version", "status", "purpose", "knowledge_types", "audience",
    "answer_language", "form_of_address", "tone", "detail", "answer_structure",
    "citation_display", "uncertainty_style", "history_presentation",
    "boundaries", "taboos",
}
POLICY_REQUIRED = {
    "policy_version", "status", "update_model", "supersession_policy",
    "removal_policy", "conflict_policy",
}
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def read_frontmatter(path: Path, source: str) -> dict[str, Any]:
    return parse_document(path.read_text(encoding="utf-8"), source, require_frontmatter=True).data


def assess_identity(target: Path) -> dict[str, Any]:
    advisories: list[dict[str, str]] = []
    result: dict[str, str] = {"soul": "missing", "content_policy": "missing"}
    soul = target / "SOUL.md"
    policy = target / "schema/CONTENT_POLICY.md"
    if soul.is_file():
        try:
            data = read_frontmatter(soul, "SOUL.md")
            missing = SOUL_REQUIRED - set(data)
            if missing:
                raise ValueError(f"missing fields: {sorted(missing)}")
            if data.get("soul_version") != 1 or data.get("status") != "confirmed":
                raise ValueError("soul_version 1 and status confirmed are required")
            if not LANGUAGE_RE.fullmatch(str(data.get("answer_language") or "")):
                raise ValueError("answer_language is invalid")
            if not isinstance(data.get("knowledge_types"), list) or not data["knowledge_types"]:
                raise ValueError("knowledge_types must be a non-empty list")
            result["soul"] = "confirmed"
        except (OSError, UnicodeError, FrontmatterError, ValueError) as exc:
            result["soul"] = "invalid"
            advisories.append({
                "code": "soul_invalid",
                "severity": "warning",
                "message": f"SOUL.md is invalid: {exc}",
                "recommended_action": "Use the maintenance skill to discuss and confirm a corrected identity proposal.",
            })
    else:
        advisories.append({
            "code": "soul_missing",
            "severity": "notice",
            "message": "This released wiki has no confirmed SOUL.md.",
            "recommended_action": "Use the maintenance skill to complete the identity interview and publish a new release.",
        })
    if policy.is_file():
        try:
            data = read_frontmatter(policy, "schema/CONTENT_POLICY.md")
            missing = POLICY_REQUIRED - set(data)
            if missing:
                raise ValueError(f"missing fields: {sorted(missing)}")
            if data.get("policy_version") != 1 or data.get("status") != "confirmed":
                raise ValueError("policy_version 1 and status confirmed are required")
            if data.get("update_model") not in {"current-state", "historical-ledger", "hybrid"}:
                raise ValueError("update_model is invalid")
            if data.get("removal_policy") != "preview-confirm-never-automatic":
                raise ValueError("removal_policy is invalid")
            if data.get("conflict_policy") != "preserve-and-disclose":
                raise ValueError("conflict_policy is invalid")
            result["content_policy"] = "confirmed"
        except (OSError, UnicodeError, FrontmatterError, ValueError) as exc:
            result["content_policy"] = "invalid"
            advisories.append({
                "code": "content_policy_invalid",
                "severity": "warning",
                "message": f"schema/CONTENT_POLICY.md is invalid: {exc}",
                "recommended_action": "Use the maintenance skill to confirm a corrected content-policy proposal.",
            })
    else:
        advisories.append({
            "code": "content_policy_missing",
            "severity": "notice",
            "message": "This released wiki has no confirmed schema/CONTENT_POLICY.md.",
            "recommended_action": "Use the maintenance skill to confirm history and supersession behavior.",
        })
    result["state"] = (
        "configured"
        if result["soul"] == "confirmed" and result["content_policy"] == "confirmed"
        else "attention-needed"
    )
    return {**result, "advisories": advisories}


def identity_contract(target: Path) -> dict[str, Any]:
    result = assess_identity(target)
    response: dict[str, Any] = {**result, "identity": {}, "content_policy_values": {}}
    if result["soul"] == "confirmed":
        soul = read_frontmatter(target / "SOUL.md", "SOUL.md")
        response["identity"] = {key: soul[key] for key in sorted(SOUL_REQUIRED - {"soul_version", "status"})}
    if result["content_policy"] == "confirmed":
        policy = read_frontmatter(target / "schema/CONTENT_POLICY.md", "schema/CONTENT_POLICY.md")
        response["content_policy_values"] = {
            key: policy[key] for key in sorted(POLICY_REQUIRED - {"policy_version", "status"})
        }
    return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    print(json.dumps(identity_contract(Path(args.target).expanduser().resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
