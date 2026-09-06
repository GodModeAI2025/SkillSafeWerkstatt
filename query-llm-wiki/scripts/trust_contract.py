#!/usr/bin/env python3
"""Per-page trust tiers derived from who produced and who confirmed a page.

Quality reviews are recorded for the wiki as a whole, so the wiki could not say
whether any individual page had been read by a human. This module adds that,
following the Open Knowledge Format v0.2 actor convention and its rule that the
tier is *derived* from a confirmation event rather than stored as a claim of its
own. A page cannot assert that it is trustworthy; it can only record who checked
it and when.

The fields stay flat because the wiki's frontmatter contract deliberately rejects
nested mappings. The OKF export composes the nested form from them.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional


#: Frontmatter fields this contract owns. All are optional.
GENERATED_BY = "generated_by"
GENERATED_AT = "generated_at"
VERIFIED_BY = "verified_by"
VERIFIED_AT = "verified_at"
TRUST_FIELDS = (GENERATED_BY, GENERATED_AT, VERIFIED_BY, VERIFIED_AT)

#: Trust tiers, from least to most confirmed.
UNVERIFIED = "unverified"
MACHINE_CONFIRMED = "machine-confirmed"
HUMAN_REVIEWED = "human-reviewed"
TIERS = (UNVERIFIED, MACHINE_CONFIRMED, HUMAN_REVIEWED)

#: Actor forms: agent/<producer>, human:<id>, process:<id>.
HUMAN_PREFIX = "human:"
ACTOR_RE = re.compile(
    r"^(?:agent/[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
    r"|human:[A-Za-z0-9][A-Za-z0-9._@-]{0,63}"
    r"|process:[A-Za-z0-9][A-Za-z0-9._-]{0,63})$"
)

#: Actor recorded when the producing agent did not identify itself.
UNKNOWN_AGENT = "agent/unknown"


class TrustError(ValueError):
    """Raised when trust metadata is present but malformed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def valid_actor(value: Any) -> bool:
    return isinstance(value, str) and bool(ACTOR_RE.fullmatch(value))


def is_human(actor: Any) -> bool:
    return isinstance(actor, str) and actor.startswith(HUMAN_PREFIX)


def valid_instant(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def trust_tier(data: dict[str, Any]) -> str:
    """Derive the tier from the confirmation recorded on one page.

    No confirmation means unverified. A confirmation by a non-human actor means
    the page was checked by a machine. Only a human actor yields human-reviewed,
    which is why marking agent work as human-verified is forbidden elsewhere.
    """
    verified = data.get(VERIFIED_BY)
    if not valid_actor(verified):
        return UNVERIFIED
    return HUMAN_REVIEWED if is_human(verified) else MACHINE_CONFIRMED


def validate(data: dict[str, Any], label: str) -> list[str]:
    """Return every problem with the trust metadata on one page."""
    problems: list[str] = []
    for field in (GENERATED_BY, VERIFIED_BY):
        value = data.get(field)
        if value in (None, ""):
            continue
        if not valid_actor(value):
            problems.append(
                f"{label}: {field} must be agent/<name>, human:<id>, or process:<id>, not {value!r}"
            )
    for field in (GENERATED_AT, VERIFIED_AT):
        value = data.get(field)
        if value in (None, ""):
            continue
        if not valid_instant(value):
            problems.append(f"{label}: {field} must be an ISO-8601 instant ending in Z")
    # A timestamp without an actor cannot be attributed, so it claims nothing.
    if data.get(VERIFIED_AT) and not data.get(VERIFIED_BY):
        problems.append(f"{label}: {VERIFIED_AT} requires {VERIFIED_BY}")
    if data.get(GENERATED_AT) and not data.get(GENERATED_BY):
        problems.append(f"{label}: {GENERATED_AT} requires {GENERATED_BY}")
    if data.get(VERIFIED_BY) and not data.get(VERIFIED_AT):
        problems.append(f"{label}: {VERIFIED_BY} requires {VERIFIED_AT}")
    return problems


def stamp_generated(
    data: dict[str, Any],
    actor: str = UNKNOWN_AGENT,
    *,
    at: Optional[str] = None,
) -> dict[str, Any]:
    """Record who produced a page, without ever overwriting an existing record."""
    if not valid_actor(actor):
        raise TrustError(f"invalid actor {actor!r}")
    if data.get(GENERATED_BY):
        return data
    return {**data, GENERATED_BY: actor, GENERATED_AT: at or utc_now()}


def distribution(pages: list[dict[str, Any]]) -> dict[str, int]:
    """Count pages per tier, so a wiki can report how much of it was reviewed."""
    counts = {tier: 0 for tier in TIERS}
    for data in pages:
        counts[trust_tier(data)] += 1
    return counts


def summary(counts: dict[str, int]) -> dict[str, Any]:
    """Describe a tier distribution without overstating what it proves."""
    total = sum(counts.values())
    reviewed = counts.get(HUMAN_REVIEWED, 0)
    return {
        "counts": dict(counts),
        "pages": total,
        "human_reviewed_share": round(reviewed / total, 4) if total else 0.0,
        "boundary": (
            "A trust tier records who confirmed a page and when. It does not assert that the "
            "page is correct, complete, or current."
        ),
    }
