#!/usr/bin/env python3
"""Optional per-page expiry, following the OKF v0.2 `stale_after` field.

The wiki already governs freshness for the whole wiki through
`schema/QUALITY_POLICY.md`: how often someone should review it, how often to
consider cleaning. That is the right instrument for a review rhythm, and the
wrong one for a page whose content has an actual end date - a price list valid
until year end, a certification, a regulation superseded on a known day.

`stale_after` expresses that per page. It is optional and stays optional: most
knowledge has no expiry date, and inventing one would be worse than having none.

A passed date is a **disclosure, not a verdict**. It says the page announced its
own end date and that date has gone by. It does not say the content is wrong,
and nothing filters an expired page out of an answer: a superseded regulation is
often exactly what a reader asked about. The reader names it; the reader does not
decide it.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional


#: Frontmatter field this module owns. Optional on every page.
STALE_AFTER = "stale_after"


def parse_instant(value: Any) -> Optional[date]:
    """Read a date or ISO-8601 instant, or None when it is not one.

    Both forms are accepted because OKF permits an instant while a maintainer
    usually thinks in days. A time of day is kept out of the comparison: expiry
    at a particular hour is a precision this contract does not have.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def validate(data: dict[str, Any], label: str) -> list[str]:
    """Return every problem with the expiry recorded on one page."""
    value = data.get(STALE_AFTER)
    if value in (None, ""):
        return []
    if parse_instant(value) is None:
        return [
            f"{label}: {STALE_AFTER} must be a date (YYYY-MM-DD) or an ISO-8601 instant, "
            f"not {value!r}"
        ]
    return []


def is_stale(data: dict[str, Any], *, today: Optional[date] = None) -> bool:
    """True when the page named an end date and that date has passed.

    A page without the field is never stale: absence of a claim is not a claim.
    """
    moment = parse_instant(data.get(STALE_AFTER))
    if moment is None:
        return False
    return moment < (today or datetime.now(timezone.utc).date())


def days_past(data: dict[str, Any], *, today: Optional[date] = None) -> Optional[int]:
    """How many days a page is past its own end date, or None."""
    moment = parse_instant(data.get(STALE_AFTER))
    if moment is None:
        return None
    delta = (today or datetime.now(timezone.utc).date()) - moment
    return delta.days if delta.days > 0 else None


def summary(pages: list[dict[str, Any]], *, today: Optional[date] = None) -> dict[str, Any]:
    """Describe how many pages carry an expiry and how many have passed it."""
    declared = [data for data in pages if parse_instant(data.get(STALE_AFTER)) is not None]
    expired = [data for data in declared if is_stale(data, today=today)]
    return {
        "pages": len(pages),
        "with_expiry": len(declared),
        "expired": len(expired),
        "boundary": (
            "A passed stale_after says the page announced an end date that has gone by. It "
            "does not say the content is wrong, and no answer filters such a page out."
        ),
    }
