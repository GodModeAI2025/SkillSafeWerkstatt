#!/usr/bin/env python3
"""The wiki-quality assessment both read-only quality helpers share.

The query skill's `assess_quality.py` and every exported knowledge skill's
`assess_quality.py` differ only in how they verify their release: a `--target`
or the bundled frozen snapshot, each with an optional manifest pin. Each
verifies first and passes the verifier's report, the release root, and its
identity validator to `assess()`. Everything after that - review ages, snapshot
age, technical state, release match, trust-tier distribution, page expiry, the
overall state, and the exit code - is decided here once, so the two helpers
cannot drift apart again; the export's separate copy had lost the trust and
expiry disclosures.

This module verifies nothing and writes nothing. It reads
`meta/quality-status.json` below the root it is given and, to count the pages
past their end date on the day of the assessment, `meta/manifest.json` and the
frontmatter of the released wiki pages that mention `stale_after`; the
identity validator the caller passes reads the identity files.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import freshness
from frontmatter_contract import FrontmatterError, parse_document


DEFAULT_POLICY = {
    "quality_review_after_days": 30,
    "cleaning_review_after_days": 90,
    "snapshot_warning_after_days": 60,
}

#: Exit codes of the query skill's quality helper by report state, the same as
#: its verifier and search; anything else exits 4. An exported skill exits 4
#: for every state but `ready` (see `exit_code`).
EXIT_CODES = {"ready": 0, "wiki_busy": 2, "snapshot_changed": 3}

#: Every advisory of this module that names a maintenance step: how to obtain a
#: new release, and the reviews and the quality policy that only a maintained
#: and released wiki can carry. A frozen export can be neither maintained nor
#: released: its reader maintains the canonical wiki and exports again, so no
#: frozen action names the maintenance skill, which an export does not bring.
#: Keys are code templates: `{field}` and `{name}` are filled in like the
#: message and the action. The identity advisories come from the caller's
#: identity validator; the export's own validator words them for a frozen
#: release. `pages_past_their_expiry` reads the same in both helpers.
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
    "quality_policy_missing": (
        "No released quality policy is available; conservative default intervals are shown.",
        "Use the maintenance skill to add and release schema/QUALITY_POLICY.md.",
    ),
    "invalid_{field}": (
        "Released quality policy field {field} is unavailable or invalid.",
        "Use the maintenance skill to correct and release the quality policy.",
    ),
    "{name}_review_unknown": (
        "The {name} review age cannot be determined.",
        "Use the maintenance skill to perform and record a {name} review.",
    ),
    "{name}_review_attention_needed": (
        "The latest {name} review recorded issues that still need attention.",
        "Use the maintenance skill to address the recorded {name} findings.",
    ),
    "{name}_review_overdue": (
        "The {name} review is overdue by {days} day(s).",
        "Use the maintenance skill to perform a {name} review; do not clean automatically.",
    ),
    "{name}_review_due_soon": (
        "The {name} review is due in {days} day(s).",
        "Plan a {name} review with the maintenance skill.",
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
        "Check the canonical wiki for a newer release and export a new knowledge skill if needed.",
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
        "matter most in the canonical wiki and export a new knowledge skill.",
    ),
    "quality_policy_missing": (
        "No released quality policy is available; conservative default intervals are shown.",
        "Add schema/QUALITY_POLICY.md to the canonical wiki, release it, and export a new knowledge skill.",
    ),
    "invalid_{field}": (
        "Released quality policy field {field} is unavailable or invalid.",
        "Correct the quality policy in the canonical wiki, release it, and export a new knowledge skill.",
    ),
    "{name}_review_unknown": (
        "The {name} review age cannot be determined.",
        "Perform and record a {name} review in the canonical wiki and export a new knowledge skill.",
    ),
    "{name}_review_attention_needed": (
        "The latest {name} review recorded issues that still need attention.",
        "Address the recorded {name} findings in the canonical wiki and export a new knowledge skill.",
    ),
    "{name}_review_overdue": (
        "The {name} review is overdue by {days} day(s).",
        "Perform a {name} review in the canonical wiki and export a new knowledge skill; "
        "do not clean automatically.",
    ),
    "{name}_review_due_soon": (
        "The {name} review is due in {days} day(s).",
        "Plan a {name} review in the canonical wiki and export a new knowledge skill after it.",
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


def release_advisory(key: str, severity: str, frozen: bool, **values: Any) -> dict[str, str]:
    """An advisory whose wording depends on whether the wiki can be maintained and re-released.

    `key` is a code template of RELEASE_TEXT and FROZEN_TEXT; `values` fill in
    the code, the message, and the action alike.
    """
    message, action = (FROZEN_TEXT if frozen else RELEASE_TEXT)[key]
    return advisory(key.format(**values), severity, message.format(**values), action.format(**values))


def safe_policy(value: Any, frozen: bool = False) -> tuple[dict[str, int], list[dict[str, str]]]:
    policy = dict(DEFAULT_POLICY)
    advisories: list[dict[str, str]] = []
    if not isinstance(value, dict):
        advisories.append(release_advisory("quality_policy_missing", "notice", frozen))
        return policy, advisories
    for field, fallback in DEFAULT_POLICY.items():
        raw = value.get(field)
        if isinstance(raw, int) and not isinstance(raw, bool) and 1 <= raw <= 3650:
            policy[field] = raw
        else:
            policy[field] = fallback
            advisories.append(release_advisory("invalid_{field}", "notice", frozen, field=field))
    return policy, advisories


def review_freshness(
    name: str,
    record: Any,
    fallback_time: Optional[datetime],
    interval_days: int,
    now: datetime,
    frozen: bool = False,
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
        }, [release_advisory("{name}_review_unknown", "warning", frozen, name=name)])

    age_days = max(0, int((now - basis).total_seconds() // 86400))
    due_at = basis + timedelta(days=interval_days)
    remaining = interval_days - age_days
    due_soon_window = min(14, max(3, int(round(interval_days * 0.2))))
    state = "current"
    advisories: list[dict[str, str]] = []
    if outcome == "attention-needed":
        state = "attention-needed"
        advisories.append(release_advisory("{name}_review_attention_needed", "warning", frozen, name=name))
    elif age_days >= interval_days:
        state = "overdue"
        advisories.append(release_advisory(
            "{name}_review_overdue", "warning", frozen, name=name, days=age_days - interval_days,
        ))
    elif remaining <= due_soon_window:
        state = "due-soon"
        advisories.append(release_advisory("{name}_review_due_soon", "notice", frozen, name=name, days=remaining))
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


def expiry_on(root: Path, day: date) -> dict[str, Any]:
    """How many released wiki pages declare an end date, and how many are past it on `day`.

    The release recorded the same counts on the day it was made, and a page can
    expire after that; `past_expiry` on a search result is decided on the day
    of the search, and so is this. A page counts as the linter counts it: its
    `stale_after` is a valid date and lies before `day`. Only the Markdown files
    below `wiki/` that `meta/manifest.json` lists are pages: a file beside them
    that the verifier ignores or tolerates, such as an editor's lock file, was
    never released. Only pages whose text names the field are parsed. A page
    that cannot be read or parsed, or a manifest that cannot be read, counts as
    no end date, which the larger of the two counts in `expiry_disclosure`
    makes up for.
    """
    pages: list[dict[str, Any]] = []
    try:
        listed = json.loads((root / "meta" / "manifest.json").read_text(encoding="utf-8")).get("files") or []
    except (OSError, ValueError, AttributeError):
        listed = []
    # Only the released pages: a file the verifier ignores (an OS artifact) or tolerates is no page.
    names = sorted(
        entry["path"] for entry in listed
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        and entry["path"].startswith("wiki/") and entry["path"].endswith(".md")
    )
    for name in names:
        path = root / name
        if path.name.startswith(".") or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        if freshness.STALE_AFTER not in text:
            continue
        try:
            pages.append(parse_document(text, path.name, require_frontmatter=True).data)
        except FrontmatterError:
            continue
    counts = freshness.summary(pages, today=day)
    return {"as_of": day.isoformat(), "with_expiry": counts["with_expiry"], "expired": counts["expired"]}


def expiry_disclosure(
    status: dict[str, Any], expiry: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """The released page-expiry counts, and a notice when a page is past its own end date.

    The released block is returned as the release recorded it. The notice
    counts the pages past their end date on the day of the assessment, or the
    release's count when that is larger: a clock behind the release, or a page
    that no longer parses, must never hide a page the release already counted.
    Never let either hide a page: a superseded rule is often the question.
    """
    fresh = status.get("freshness") if isinstance(status.get("freshness"), dict) else {}
    expired = max(safe_int(fresh.get("expired")), safe_int((expiry or {}).get("expired")))
    if not expired:
        return fresh, []
    return fresh, [advisory(
        "pages_past_their_expiry", "notice",
        f"{expired} page(s) declared an end date that has passed.",
        "Name it when such a page carries the answer. It is a disclosure, not a "
        "verdict: the content may still be correct, and nothing filters it out.",
    )]


def unknown_quality(
    code: str, frozen: bool, release: dict[str, Any], root: Path, current: datetime,
) -> dict[str, Any]:
    """A verified release whose quality status is missing or unreadable.

    Its pages are still counted on the day of the assessment: without a
    released count, `expiry` alone decides the notice, and no page past its end
    date may go unnamed because the status file is gone.
    """
    expiry = expiry_on(root, current.date())
    _, expiry_advisories = expiry_disclosure({}, expiry)
    return {
        "state": "ready",
        "release": release,
        "quality": {
            "state": "unknown",
            "assessed_at": iso(current),
            "expiry": expiry,
            "advisories": [release_advisory(code, "warning", frozen), *expiry_advisories],
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
        return unknown_quality("quality_status_missing", frozen, release, root, current)
    if not isinstance(status, dict) or status.get("format") != "lmwiki-quality/1":
        return unknown_quality("quality_status_invalid", frozen, release, root, current)

    policy, advisories = safe_policy(status.get("policy"), frozen)
    identity_report = identity(root)
    advisories.extend(identity_report.get("advisories", []))
    released_at = parse_time(release.get("released_at"))
    reviews = status.get("reviews") if isinstance(status.get("reviews"), dict) else {}
    quality_review, quality_advisories = review_freshness(
        "quality", reviews.get("quality"), released_at, policy["quality_review_after_days"], current, frozen,
    )
    cleaning_review, cleaning_advisories = review_freshness(
        "cleaning", reviews.get("cleaning"), released_at, policy["cleaning_review_after_days"], current, frozen,
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
    expiry = expiry_on(root, current.date())
    fresh, expiry_advisories = expiry_disclosure(status, expiry)
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
            "expiry": expiry,
            "advisories": advisories,
        },
    }


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def exit_code(report: dict[str, Any], frozen: bool = False) -> int:
    """The exit code of a report.

    An exported skill exits 4 for every state but `ready`, as its verifier and
    its search do: a bundled snapshot that changed after it was verified is the
    same integrity failure as a damaged one, and a frozen snapshot has no lock.
    """
    if frozen:
        return 0 if report.get("state") == "ready" else 4
    return EXIT_CODES.get(str(report.get("state")), 4)
