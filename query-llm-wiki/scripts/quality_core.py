#!/usr/bin/env python3
"""The wiki-quality assessment both read-only quality helpers share.

The query skill's `assess_quality.py` and every exported knowledge skill's
`assess_quality.py` differ only in how they verify their release: a `--target`
with an optional manifest pin, or the bundled frozen snapshot. Each verifies
first and passes the verifier's report, the release root, and its identity
validator to `assess()`. Everything after that - review ages, snapshot age,
technical state, release match, trust-tier distribution, page expiry, and the
overall state - is decided here once, so the two helpers cannot drift apart
again; the export's separate copy had lost the trust and expiry disclosures.

This module verifies nothing and writes nothing. It reads only
`meta/quality-status.json` below the root it is given; the identity validator
the caller passes reads the identity files.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional


DEFAULT_POLICY = {
    "quality_review_after_days": 30,
    "cleaning_review_after_days": 90,
    "snapshot_warning_after_days": 60,
}

#: Exit codes of both quality helpers by report state; anything else exits 4.
#: A frozen snapshot only ever reports `ready` or `invalid_snapshot`.
EXIT_CODES = {"ready": 0, "wiki_busy": 2, "snapshot_changed": 3}

#: The advisories whose text says how to obtain a new release, including the
#: page reviews that only a new release can carry. A frozen export cannot be
#: released: its reader maintains the canonical wiki and exports again. Every
#: other advisory reads the same in both helpers.
RELEASE_TEXT = {
    "quality_status_missing": (
        "This release has no valid meta/quality-status.json.",
        "Use the maintenance skill to add the quality policy and publish a new release.",
    ),
    "quality_status_invalid": (
        "The released quality status uses an unsupported format.",
        "Use the maintenance skill to regenerate and release the quality status.",
    ),
    "snapshot_age_unknown": (
        "The release timestamp is unavailable.",
        "Use the maintenance skill to publish a valid release.",
    ),
    "snapshot_old": (
        "This released snapshot is {days} day(s) old.",
        "Check the canonical wiki for a newer release before relying on time-sensitive content.",
    ),
    "technical_quality_attention_needed": (
        "The released technical quality status is missing or not valid.",
        "Use the maintenance skill to lint, repair, and publish a new release.",
    ),
    "quality_release_mismatch": (
        "The quality status does not identify the verified release.",
        "Use the maintenance skill to regenerate and release the quality status.",
    ),
    "no_page_was_human_reviewed": (
        "None of the {total} pages records a human review.",
        "Answers may still be well sourced. Use the maintenance skill to record "
        "reviews on the pages that matter most.",
    ),
}
FROZEN_TEXT = {
    "quality_status_missing": (
        "This frozen release has no valid meta/quality-status.json.",
        "Maintain the canonical wiki and export a new knowledge skill.",
    ),
    "quality_status_invalid": (
        "The frozen quality status uses an unsupported format.",
        "Maintain the canonical wiki and export a new knowledge skill.",
    ),
    "snapshot_age_unknown": (
        "The frozen release timestamp is unavailable.",
        "Export a new knowledge skill from a valid canonical release.",
    ),
    "snapshot_old": (
        "This frozen snapshot is {days} day(s) old.",
        "Check the canonical wiki for a newer release and export a new skill if needed.",
    ),
    "technical_quality_attention_needed": (
        "The frozen technical quality status is missing or not valid.",
        "Repair the canonical wiki, release it, and export a new knowledge skill.",
    ),
    "quality_release_mismatch": (
        "The quality status does not identify this verified frozen release.",
        "Release the canonical wiki and export a new knowledge skill.",
    ),
    "no_page_was_human_reviewed": (
        "None of the {total} pages records a human review.",
        "Answers may still be well sourced. Record reviews on the pages that "
        "matter most in the canonical wiki and export a new skill.",
    ),
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


def advisory(code: str, severity: str, message: str, action: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "recommended_action": action}


def release_advisory(code: str, severity: str, frozen: bool, **values: Any) -> dict[str, str]:
    """An advisory whose wording depends on whether the release can be re-released."""
    message, action = (FROZEN_TEXT if frozen else RELEASE_TEXT)[code]
    return advisory(code, severity, message.format(**values), action)


def safe_policy(value: Any) -> tuple[dict[str, int], list[dict[str, str]]]:
    policy = dict(DEFAULT_POLICY)
    advisories: list[dict[str, str]] = []
    if not isinstance(value, dict):
        advisories.append(advisory(
            "quality_policy_missing", "notice",
            "No released quality policy is available; conservative default intervals are shown.",
            "Use the maintenance skill to add and release schema/QUALITY_POLICY.md.",
        ))
        return policy, advisories
    for field, fallback in DEFAULT_POLICY.items():
        raw = value.get(field)
        if isinstance(raw, int) and not isinstance(raw, bool) and 1 <= raw <= 3650:
            policy[field] = raw
        else:
            policy[field] = fallback
            advisories.append(advisory(
                f"invalid_{field}", "notice",
                f"Released quality policy field {field} is unavailable or invalid.",
                "Use the maintenance skill to correct and release the quality policy.",
            ))
    return policy, advisories


def review_freshness(
    name: str,
    record: Any,
    fallback_time: Optional[datetime],
    interval_days: int,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """The age and state of one wiki-wide review, counted from the release when none is recorded."""
    review = record if isinstance(record, dict) else {}
    reviewed_at = parse_time(review.get("reviewed_at"))
    basis = reviewed_at or fallback_time
    outcome = str(review.get("outcome") or "not-recorded")
    summary = str(review.get("summary") or "")
    if basis is None:
        return ({
            "state": "unknown",
            "last_reviewed_at": "",
            "basis": "none",
            "age_days": None,
            "due_after_days": interval_days,
            "next_due_at": "",
            "outcome": outcome,
            "summary": summary,
        }, [advisory(
            f"{name}_review_unknown", "warning",
            f"The {name} review age cannot be determined.",
            f"Use the maintenance skill to perform and record a {name} review.",
        )])

    age_days = max(0, int((now - basis).total_seconds() // 86400))
    due_at = basis + timedelta(days=interval_days)
    remaining = interval_days - age_days
    due_soon_window = min(14, max(3, int(round(interval_days * 0.2))))
    state = "current"
    advisories: list[dict[str, str]] = []
    if outcome == "attention-needed":
        state = "attention-needed"
        advisories.append(advisory(
            f"{name}_review_attention_needed", "warning",
            f"The latest {name} review recorded issues that still need attention.",
            f"Use the maintenance skill to address the recorded {name} findings.",
        ))
    elif age_days >= interval_days:
        state = "overdue"
        advisories.append(advisory(
            f"{name}_review_overdue", "warning",
            f"The {name} review is overdue by {age_days - interval_days} day(s).",
            f"Use the maintenance skill to perform a {name} review; do not clean automatically.",
        ))
    elif remaining <= due_soon_window:
        state = "due-soon"
        advisories.append(advisory(
            f"{name}_review_due_soon", "notice",
            f"The {name} review is due in {remaining} day(s).",
            f"Plan a {name} review with the maintenance skill.",
        ))
    return ({
        "state": state,
        "last_reviewed_at": iso(reviewed_at) if reviewed_at else "",
        "basis": "recorded-review" if reviewed_at else "release-fallback",
        "age_days": age_days,
        "due_after_days": interval_days,
        "next_due_at": iso(due_at),
        "outcome": outcome,
        "summary": summary,
    }, advisories)


def overall_state(advisories: list[dict[str, str]], review_states: set[Any]) -> str:
    severities = {item.get("severity") for item in advisories}
    if "warning" in severities or review_states & {"overdue", "attention-needed", "unknown"}:
        return "attention-needed"
    if "notice" in severities or "due-soon" in review_states:
        return "due-soon"
    return "current"


def trust_disclosure(status: dict[str, Any], frozen: bool = False) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """The released trust-tier distribution, and a notice when no page records a human review.

    A wiki-wide review says when someone last looked; the per-page tiers say
    how much of the wiki that covered. Report both, and never let one stand in
    for the other. A frozen export cannot record a review itself, so its
    notice points to the canonical wiki and a new export.
    """
    trust = status.get("trust") if isinstance(status.get("trust"), dict) else {}
    counts = trust.get("counts") if isinstance(trust.get("counts"), dict) else {}
    total = safe_int(trust.get("pages"))
    if not total or safe_int(counts.get("human-reviewed")):
        return trust, []
    return trust, [release_advisory("no_page_was_human_reviewed", "notice", frozen, total=total)]


def expiry_disclosure(status: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """The released page-expiry counts, and a notice when a page is past its own end date.

    The count is the one the release recorded. Never let it hide a page: a
    superseded rule is often the question.
    """
    fresh = status.get("freshness") if isinstance(status.get("freshness"), dict) else {}
    expired = safe_int(fresh.get("expired"))
    if not expired:
        return fresh, []
    return fresh, [advisory(
        "pages_past_their_expiry", "notice",
        f"{expired} page(s) declared an end date that has passed.",
        "Name it when such a page carries the answer. It is a disclosure, not a "
        "verdict: the content may still be correct, and nothing filters it out.",
    )]


def unknown_quality(code: str, frozen: bool, release: dict[str, Any], current: datetime) -> dict[str, Any]:
    return {
        "state": "ready",
        "release": release,
        "quality": {
            "state": "unknown",
            "assessed_at": iso(current),
            "advisories": [release_advisory(code, "warning", frozen)],
        },
    }


def assess(
    release: dict[str, Any],
    root: Path,
    identity: Callable[[Path], dict[str, Any]],
    *,
    frozen: bool = False,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Assess the quality of a release the caller has just verified.

    `release` is the verifier's report; anything but `ready` is passed through
    with `quality: None`. `root` is the verified release root and `identity`
    the caller's identity validator, called with it only once the quality
    status has been read. `frozen` selects the wording of a frozen export.
    """
    if release.get("state") != "ready":
        fallback = "invalid_snapshot" if frozen else "invalid_wiki"
        return {"state": str(release.get("state") or fallback), "release": release, "quality": None}
    current = (now or utc_now()).astimezone(timezone.utc)
    try:
        status = json.loads((root / "meta/quality-status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # ValueError covers both malformed JSON and bytes that are not UTF-8.
        return unknown_quality("quality_status_missing", frozen, release, current)
    if not isinstance(status, dict) or status.get("format") != "lmwiki-quality/1":
        return unknown_quality("quality_status_invalid", frozen, release, current)

    policy, advisories = safe_policy(status.get("policy"))
    identity_report = identity(root)
    advisories.extend(identity_report.get("advisories", []))
    released_at = parse_time(release.get("released_at"))
    reviews = status.get("reviews") if isinstance(status.get("reviews"), dict) else {}
    quality_review, quality_advisories = review_freshness(
        "quality", reviews.get("quality"), released_at, policy["quality_review_after_days"], current,
    )
    cleaning_review, cleaning_advisories = review_freshness(
        "cleaning", reviews.get("cleaning"), released_at, policy["cleaning_review_after_days"], current,
    )
    advisories.extend(quality_advisories)
    advisories.extend(cleaning_advisories)

    snapshot_age = max(0, int((current - released_at).total_seconds() // 86400)) if released_at else None
    snapshot_state = "current"
    if snapshot_age is None:
        snapshot_state = "unknown"
        advisories.append(release_advisory("snapshot_age_unknown", "warning", frozen))
    elif snapshot_age >= policy["snapshot_warning_after_days"]:
        snapshot_state = "old"
        advisories.append(release_advisory("snapshot_old", "notice", frozen, days=snapshot_age))

    technical = status.get("technical") if isinstance(status.get("technical"), dict) else {}
    if not technical or not bool(technical.get("valid")) or safe_int(technical.get("errors")) > 0:
        advisories.append(release_advisory("technical_quality_attention_needed", "warning", frozen))
    if status.get("release_id") != release.get("release_id") or status.get("version") != release.get("version"):
        advisories.append(release_advisory("quality_release_mismatch", "warning", frozen))

    state = overall_state(advisories, {quality_review.get("state"), cleaning_review.get("state")})
    # The two disclosures are added after the state is decided, on purpose: a
    # wiki where no page records a human review, or where a page is past its
    # own end date, is not due for a review because of it. Counted as notices,
    # they would hold almost every wiki at `due-soon` for good.
    trust, trust_advisories = trust_disclosure(status, frozen)
    fresh, expiry_advisories = expiry_disclosure(status)
    advisories.extend(trust_advisories)
    advisories.extend(expiry_advisories)
    return {
        "state": "ready",
        "release": release,
        "quality": {
            "state": state,
            "assessed_at": iso(current),
            "policy": policy,
            "technical": technical,
            "reviews": {"quality": quality_review, "cleaning": cleaning_review},
            "snapshot": {"state": snapshot_state, "age_days": snapshot_age},
            "open_question_items": safe_int(status.get("open_question_items")),
            "identity": identity_report,
            "trust": trust,
            "freshness": fresh,
            "advisories": advisories,
        },
    }


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def exit_code(report: dict[str, Any]) -> int:
    return EXIT_CODES.get(str(report.get("state")), 4)
