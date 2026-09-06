#!/usr/bin/env python3
"""Assess a released wiki's quality freshness without modifying it."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from identity_status import assess_identity
from verify_release import verify_snapshot


DEFAULT_POLICY = {
    "quality_review_after_days": 30,
    "cleaning_review_after_days": 90,
    "snapshot_warning_after_days": 60,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def safe_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def safe_policy(value: Any) -> tuple[dict[str, int], list[dict[str, str]]]:
    policy = dict(DEFAULT_POLICY)
    advisories: list[dict[str, str]] = []
    if not isinstance(value, dict):
        advisories.append({
            "code": "quality_policy_missing",
            "severity": "notice",
            "message": "No released quality policy is available; conservative default intervals are shown.",
            "recommended_action": "Use the maintenance skill to add and release schema/QUALITY_POLICY.md.",
        })
        return policy, advisories
    for field, fallback in DEFAULT_POLICY.items():
        raw = value.get(field)
        if isinstance(raw, int) and not isinstance(raw, bool) and 1 <= raw <= 3650:
            policy[field] = raw
        else:
            policy[field] = fallback
            advisories.append({
                "code": f"invalid_{field}",
                "severity": "notice",
                "message": f"Released quality policy field {field} is unavailable or invalid.",
                "recommended_action": "Use the maintenance skill to correct and release the quality policy.",
            })
    return policy, advisories


def freshness(
    name: str,
    record: Any,
    fallback_time: Optional[datetime],
    interval_days: int,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    review = record if isinstance(record, dict) else {}
    reviewed_at = parse_time(review.get("reviewed_at"))
    basis = reviewed_at or fallback_time
    if basis is None:
        return ({
            "state": "unknown",
            "last_reviewed_at": "",
            "basis": "none",
            "age_days": None,
            "due_after_days": interval_days,
            "next_due_at": "",
            "outcome": str(review.get("outcome") or "not-recorded"),
            "summary": str(review.get("summary") or ""),
        }, [{
            "code": f"{name}_review_unknown",
            "severity": "warning",
            "message": f"The {name} review age cannot be determined.",
            "recommended_action": f"Use the maintenance skill to perform and record a {name} review.",
        }])

    age_days = max(0, int((now - basis).total_seconds() // 86400))
    due_at = basis + timedelta(days=interval_days)
    remaining = interval_days - age_days
    due_soon_window = min(14, max(3, int(round(interval_days * 0.2))))
    outcome = str(review.get("outcome") or "not-recorded")
    state = "current"
    advisories: list[dict[str, str]] = []
    if outcome == "attention-needed":
        state = "attention-needed"
        advisories.append({
            "code": f"{name}_review_attention_needed",
            "severity": "warning",
            "message": f"The latest {name} review recorded issues that still need attention.",
            "recommended_action": f"Use the maintenance skill to address the recorded {name} findings.",
        })
    elif age_days >= interval_days:
        state = "overdue"
        advisories.append({
            "code": f"{name}_review_overdue",
            "severity": "warning",
            "message": f"The {name} review is overdue by {age_days - interval_days} day(s).",
            "recommended_action": f"Use the maintenance skill to perform a {name} review; do not clean automatically.",
        })
    elif remaining <= due_soon_window:
        state = "due-soon"
        advisories.append({
            "code": f"{name}_review_due_soon",
            "severity": "notice",
            "message": f"The {name} review is due in {remaining} day(s).",
            "recommended_action": f"Plan a {name} review with the maintenance skill.",
        })
    return ({
        "state": state,
        "last_reviewed_at": iso(reviewed_at) if reviewed_at else "",
        "basis": "recorded-review" if reviewed_at else "release-fallback",
        "age_days": age_days,
        "due_after_days": interval_days,
        "next_due_at": iso(due_at),
        "outcome": outcome,
        "summary": str(review.get("summary") or ""),
    }, advisories)


def assess_quality(target: Path, expected_manifest_sha256: str = "", now: Optional[datetime] = None) -> dict[str, Any]:
    release = verify_snapshot(target, expected_manifest_sha256)
    if release.get("state") != "ready":
        return {"state": str(release.get("state") or "invalid_wiki"), "release": release, "quality": None}
    current = (now or utc_now()).astimezone(timezone.utc)
    status_path = target / "meta/quality-status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "state": "ready",
            "release": release,
            "quality": {
                "state": "unknown",
                "assessed_at": iso(current),
                "advisories": [{
                    "code": "quality_status_missing",
                    "severity": "warning",
                    "message": "This release has no valid meta/quality-status.json.",
                    "recommended_action": "Use the maintenance skill to add the quality policy and publish a new release.",
                }],
            },
        }
    if not isinstance(status, dict) or status.get("format") != "lmwiki-quality/1":
        return {
            "state": "ready",
            "release": release,
            "quality": {
                "state": "unknown",
                "assessed_at": iso(current),
                "advisories": [{
                    "code": "quality_status_invalid",
                    "severity": "warning",
                    "message": "The released quality status uses an unsupported format.",
                    "recommended_action": "Use the maintenance skill to regenerate and release the quality status.",
                }],
            },
        }

    policy, advisories = safe_policy(status.get("policy"))
    identity = assess_identity(target)
    advisories.extend(identity.get("advisories", []))
    released_at = parse_time(release.get("released_at"))
    reviews = status.get("reviews") if isinstance(status.get("reviews"), dict) else {}
    quality_review, quality_advisories = freshness(
        "quality",
        reviews.get("quality") if isinstance(reviews, dict) else None,
        released_at,
        policy["quality_review_after_days"],
        current,
    )
    cleaning_review, cleaning_advisories = freshness(
        "cleaning",
        reviews.get("cleaning") if isinstance(reviews, dict) else None,
        released_at,
        policy["cleaning_review_after_days"],
        current,
    )
    advisories.extend(quality_advisories)
    advisories.extend(cleaning_advisories)

    snapshot_age = max(0, int((current - released_at).total_seconds() // 86400)) if released_at else None
    snapshot_state = "current"
    if snapshot_age is None:
        snapshot_state = "unknown"
        advisories.append({
            "code": "snapshot_age_unknown",
            "severity": "warning",
            "message": "The release timestamp is unavailable.",
            "recommended_action": "Use the maintenance skill to publish a valid release.",
        })
    elif snapshot_age >= policy["snapshot_warning_after_days"]:
        snapshot_state = "old"
        advisories.append({
            "code": "snapshot_old",
            "severity": "notice",
            "message": f"This released snapshot is {snapshot_age} day(s) old.",
            "recommended_action": "Check the canonical wiki for a newer release before relying on time-sensitive content.",
        })

    technical = status.get("technical") if isinstance(status.get("technical"), dict) else {}
    if not technical or not bool(technical.get("valid")) or safe_int(technical.get("errors")) > 0:
        advisories.append({
            "code": "technical_quality_attention_needed",
            "severity": "warning",
            "message": "The released technical quality status is missing or not valid.",
            "recommended_action": "Use the maintenance skill to lint, repair, and publish a new release.",
        })
    if status.get("release_id") != release.get("release_id") or status.get("version") != release.get("version"):
        advisories.append({
            "code": "quality_release_mismatch",
            "severity": "warning",
            "message": "The quality status does not identify the verified release.",
            "recommended_action": "Use the maintenance skill to regenerate and release the quality status.",
        })

    severity_states = {item.get("severity") for item in advisories}
    # A wiki-wide review says when someone last looked; the per-page tiers say
    # how much of the wiki that covered. Report both, and never let one stand in
    # for the other.
    trust = status.get("trust") if isinstance(status.get("trust"), dict) else {}
    counts = trust.get("counts") if isinstance(trust.get("counts"), dict) else {}
    reviewed = safe_int(counts.get("human-reviewed"))
    total = safe_int(trust.get("pages"))
    if total and not reviewed:
        advisories.append(
            {
                "severity": "notice",
                "code": "no_page_was_human_reviewed",
                "message": f"None of the {total} pages records a human review.",
                "recommended_action": (
                    "Answers may still be well sourced. Use the maintenance skill to record "
                    "reviews on the pages that matter most."
                ),
            }
        )

    review_states = {quality_review.get("state"), cleaning_review.get("state")}
    overall = "current"
    if "warning" in severity_states or review_states & {"overdue", "attention-needed", "unknown"}:
        overall = "attention-needed"
    elif "notice" in severity_states or "due-soon" in review_states:
        overall = "due-soon"
    return {
        "state": "ready",
        "release": release,
        "quality": {
            "state": overall,
            "assessed_at": iso(current),
            "policy": policy,
            "technical": technical,
            "reviews": {"quality": quality_review, "cleaning": cleaning_review},
            "snapshot": {"state": snapshot_state, "age_days": snapshot_age},
            "open_question_items": safe_int(status.get("open_question_items")),
            "identity": identity,
            "trust": trust,
            "advisories": advisories,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--expect-manifest-sha256", default="")
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    report = assess_quality(target, args.expect_manifest_sha256)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {"ready": 0, "wiki_busy": 2, "snapshot_changed": 3}.get(str(report.get("state")), 4)


if __name__ == "__main__":
    raise SystemExit(main())
