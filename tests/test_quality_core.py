#!/usr/bin/env python3
"""The one quality assessment of the query skill and of every exported knowledge skill.

`quality_core.py` decides everything after release verification. Until it
existed the export carried its own copy of `assess_quality.py`, which had lost
the trust-tier distribution and the count of pages past their end date. These
tests pin the decisions both helpers now share and the one thing that differs:
the wording of advisories that say how to obtain a new release.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "query-llm-wiki" / "scripts"))

import quality_core  # noqa: E402


NOW = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
RELEASE = {
    "state": "ready",
    "release_id": "r1",
    "version": "0.1.1",
    "released_at": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
}
IDENTITY = {"state": "configured", "advisories": []}


def status(**overrides: object) -> dict:
    """A released quality status with current reviews and a valid lint."""
    value: dict = {
        "format": "lmwiki-quality/1",
        "release_id": "r1",
        "version": "0.1.1",
        "policy": dict(quality_core.DEFAULT_POLICY),
        "reviews": {},
        "technical": {"valid": True, "errors": 0, "warnings": 0},
        "open_question_items": 0,
        "trust": {"counts": {"human-reviewed": 1, "machine-confirmed": 0, "unverified": 1}, "pages": 2},
        "freshness": {"expired": 0, "pages": 2, "with_expiry": 0},
    }
    value.update(overrides)
    return value


class Assessment(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="lmwiki-quality-core-")
        self.root = Path(self._dir.name)
        (self.root / "meta").mkdir()
        self.identity_calls: list[Path] = []

    def tearDown(self) -> None:
        self._dir.cleanup()

    def identity(self, root: Path) -> dict:
        self.identity_calls.append(root)
        return IDENTITY

    def assess(self, content, *, frozen: bool = False, release: dict = RELEASE, now: datetime = NOW) -> dict:
        path = self.root / "meta" / "quality-status.json"
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif content is not None:
            path.write_text(json.dumps(content), encoding="utf-8")
        return quality_core.assess(release, self.root, self.identity, frozen=frozen, now=now)

    @staticmethod
    def codes(report: dict) -> list[str]:
        return [item["code"] for item in report["quality"]["advisories"]]

    def test_a_current_wiki_reports_both_disclosure_blocks(self) -> None:
        report = self.assess(status())
        self.assertEqual(report["state"], "ready")
        quality = report["quality"]
        self.assertEqual(quality["state"], "current")
        self.assertEqual(quality["trust"]["pages"], 2)
        self.assertEqual(quality["freshness"]["with_expiry"], 0)
        self.assertEqual(quality["advisories"], [])
        self.assertEqual(self.identity_calls, [self.root])

    def test_the_disclosures_never_move_the_overall_state(self) -> None:
        """No human review and an expired page are disclosed, not counted as a due review."""
        report = self.assess(status(
            trust={"counts": {"human-reviewed": 0, "unverified": 50}, "pages": 50},
            freshness={"expired": 3, "pages": 50, "with_expiry": 4},
        ))
        self.assertEqual(report["quality"]["state"], "current")
        self.assertEqual(self.codes(report), ["no_page_was_human_reviewed", "pages_past_their_expiry"])
        self.assertTrue(all(item["severity"] == "notice" for item in report["quality"]["advisories"]))

    def test_a_warning_still_decides_and_the_disclosures_come_last(self) -> None:
        report = self.assess(status(
            technical={"valid": False, "errors": 1},
            trust={"counts": {}, "pages": 2},
            freshness={"expired": 1},
        ))
        self.assertEqual(report["quality"]["state"], "attention-needed")
        self.assertEqual(
            self.codes(report),
            ["technical_quality_attention_needed", "no_page_was_human_reviewed", "pages_past_their_expiry"],
        )

    def test_review_and_snapshot_ages_follow_the_policy(self) -> None:
        old = (NOW - timedelta(days=80)).isoformat().replace("+00:00", "Z")
        report = self.assess(status(), release={**RELEASE, "released_at": old})
        quality = report["quality"]
        self.assertEqual(quality["reviews"]["quality"]["state"], "overdue")
        self.assertEqual(quality["reviews"]["cleaning"]["state"], "due-soon")
        self.assertEqual(quality["snapshot"], {"state": "old", "age_days": 80})
        self.assertEqual(quality["state"], "attention-needed")
        self.assertIn("This released snapshot is 80 day(s) old.", [a["message"] for a in quality["advisories"]])

    def test_a_missing_undecodable_or_foreign_status_is_unknown_quality(self) -> None:
        for content, code in (
            (None, "quality_status_missing"),
            (b"{not json", "quality_status_missing"),
            # Bytes that are not UTF-8 used to escape as a traceback.
            (b'{"format": "lmwiki-quality/1", "x": "\xff"}', "quality_status_missing"),
            ([], "quality_status_invalid"),
            ({"format": "lmwiki-quality/0"}, "quality_status_invalid"),
        ):
            with self.subTest(content=content):
                (self.root / "meta" / "quality-status.json").unlink(missing_ok=True)
                self.identity_calls.clear()
                report = self.assess(content)
                self.assertEqual(report["state"], "ready")
                self.assertEqual(report["quality"]["state"], "unknown")
                self.assertEqual(self.codes(report), [code])
                self.assertEqual(self.identity_calls, [], "identity is read only for a valid status")

    def test_an_unverified_release_is_passed_through_without_quality(self) -> None:
        for release, frozen, state in (
            ({"state": "wiki_busy"}, False, "wiki_busy"),
            ({"state": "snapshot_changed"}, False, "snapshot_changed"),
            ({}, False, "invalid_wiki"),
            ({}, True, "invalid_snapshot"),
            ({"state": "invalid_snapshot", "errors": ["x"]}, True, "invalid_snapshot"),
        ):
            with self.subTest(release=release, frozen=frozen):
                report = self.assess(status(), release=release, frozen=frozen)
                self.assertEqual(report, {"state": state, "release": release, "quality": None})
                self.assertEqual(self.identity_calls, [])

    def test_exit_codes_follow_the_report_state(self) -> None:
        for state, code in (("ready", 0), ("wiki_busy", 2), ("snapshot_changed", 3), ("invalid_wiki", 4),
                            ("invalid_snapshot", 4), ("hydration_required", 4), (None, 4)):
            with self.subTest(state=state):
                self.assertEqual(quality_core.exit_code({"state": state}), code)


class FrozenWording(unittest.TestCase):
    """Only advisories about obtaining a new release read differently in an export."""

    def test_both_wordings_cover_the_same_advisories(self) -> None:
        self.assertEqual(set(quality_core.RELEASE_TEXT), set(quality_core.FROZEN_TEXT))
        for code in quality_core.RELEASE_TEXT:
            with self.subTest(code=code):
                self.assertNotEqual(quality_core.RELEASE_TEXT[code], quality_core.FROZEN_TEXT[code])
                action = quality_core.FROZEN_TEXT[code][1]
                self.assertIn("canonical", action)
                self.assertIn("export", action.lower())
                self.assertNotIn("maintenance skill", action)

    def test_a_frozen_report_differs_only_in_that_wording(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lmwiki-quality-core-") as directory:
            root = Path(directory)
            (root / "meta").mkdir()
            old = (NOW - timedelta(days=90)).isoformat().replace("+00:00", "Z")
            (root / "meta" / "quality-status.json").write_text(json.dumps(status(
                release_id="other",
                technical={},
                policy=None,
                reviews={"quality": {"reviewed_at": old, "outcome": "attention-needed"}},
                trust={"counts": {}, "pages": 2},
                freshness={"expired": 1},
            )), encoding="utf-8")
            release = {**RELEASE, "released_at": old}
            reader = quality_core.assess(release, root, lambda _root: IDENTITY, now=NOW)
            frozen = quality_core.assess(release, root, lambda _root: IDENTITY, frozen=True, now=NOW)
        reader_advisories = reader["quality"].pop("advisories")
        frozen_advisories = frozen["quality"].pop("advisories")
        self.assertEqual(reader, frozen)
        self.assertEqual([a["code"] for a in reader_advisories], [a["code"] for a in frozen_advisories])
        reworded = {a["code"] for a in reader_advisories} & set(quality_core.FROZEN_TEXT)
        self.assertEqual(reworded, {
            "snapshot_old", "technical_quality_attention_needed", "quality_release_mismatch",
            "no_page_was_human_reviewed",
        })
        for mine, theirs in zip(reader_advisories, frozen_advisories):
            with self.subTest(code=mine["code"]):
                if mine["code"] in reworded:
                    self.assertNotEqual(mine["recommended_action"], theirs["recommended_action"])
                else:
                    self.assertEqual(mine, theirs)
        # A frozen export cannot record a page review; its notice says where that happens.
        unreviewed = [a for a in frozen_advisories if a["code"] == "no_page_was_human_reviewed"]
        self.assertEqual(unreviewed, [{
            "code": "no_page_was_human_reviewed",
            "severity": "notice",
            "message": "None of the 2 pages records a human review.",
            "recommended_action": "Answers may still be well sourced. Record reviews on the pages that matter "
                                  "most in the canonical wiki and export a new skill.",
        }])
        self.assertIn(
            "Use the maintenance skill",
            [a for a in reader_advisories if a["code"] == "no_page_was_human_reviewed"][0]["recommended_action"],
        )

    def test_the_trust_disclosure_takes_the_frozen_wording_directly(self) -> None:
        unreviewed = {"trust": {"counts": {"unverified": 3}, "pages": 3}}
        block, reader = quality_core.trust_disclosure(unreviewed)
        _, frozen = quality_core.trust_disclosure(unreviewed, frozen=True)
        self.assertEqual(block, unreviewed["trust"])
        self.assertEqual(reader[0]["recommended_action"], quality_core.RELEASE_TEXT["no_page_was_human_reviewed"][1])
        self.assertEqual(frozen[0]["recommended_action"], quality_core.FROZEN_TEXT["no_page_was_human_reviewed"][1])
        self.assertEqual(reader[0]["message"], frozen[0]["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
