#!/usr/bin/env python3
"""The one quality assessment of the query skill and of every exported knowledge skill.

`quality_core.py` decides everything after release verification. Until it
existed the export carried its own copy of `assess_quality.py`, which had lost
the trust-tier distribution and the count of pages past their end date. These
tests pin the decisions both helpers now share and the one thing that differs:
the wording of advisories that name a maintenance step, which an export cannot
take.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
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


def wording_key(code: str):
    """The RELEASE_TEXT/FROZEN_TEXT key a concrete advisory code was made from, or None."""
    for key in quality_core.RELEASE_TEXT:
        pattern = re.escape(key).replace(r"\{field\}", "(?:[a-z_]+)").replace(r"\{name\}", "(?:quality|cleaning)")
        if re.fullmatch(pattern, code):
            return key
    return None


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

    def test_a_frozen_report_exits_4_for_every_state_but_ready(self) -> None:
        """As the export's verifier and search do; a changed snapshot is not exit 3 there."""
        for state, code in (("ready", 0), ("snapshot_changed", 4), ("invalid_snapshot", 4), ("wiki_busy", 4), (None, 4)):
            with self.subTest(state=state):
                self.assertEqual(quality_core.exit_code({"state": state}, frozen=True), code)


class ExpiryAtAssessment(unittest.TestCase):
    """The pages past their end date are counted on the day of the assessment, beside the release's count."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="lmwiki-quality-expiry-")
        self.root = Path(self._dir.name)
        (self.root / "meta").mkdir()
        (self.root / "wiki").mkdir()
        self.released: list[str] = []

    def tearDown(self) -> None:
        self._dir.cleanup()

    def release_file(self, relative: str, content: bytes, listed: bool = True) -> None:
        """Write one file below the root and, unless `listed` is False, list it in meta/manifest.json."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if listed:
            self.released.append(relative)
        self.write_manifest()

    def write_manifest(self) -> None:
        files = [{"path": name, "sha256": "0" * 64, "bytes": 0} for name in sorted(self.released)]
        manifest = {"format": "lmwiki-release/1", "files": files}
        (self.root / "meta" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def page(self, relative: str, stale_after: str, body: str = "Text.", folder: str = "wiki", listed: bool = True) -> None:
        """Write a page with an optional `stale_after` below `folder`, listed in the manifest unless `listed` is False."""
        stem = Path(relative).stem
        field = f'stale_after: "{stale_after}"\n' if stale_after else ""
        text = f'---\nid: "{stem}"\ntitle: "{stem}"\n{field}---\n\n{body}\n'
        self.release_file(f"{folder}/{relative}", text.encode("utf-8"), listed)

    def assess(self, released: dict, now: datetime = NOW) -> dict:
        (self.root / "meta" / "quality-status.json").write_text(json.dumps(status(freshness=released)), encoding="utf-8")
        return quality_core.assess(RELEASE, self.root, lambda _root: IDENTITY, now=now)["quality"]

    def test_a_page_that_expired_after_the_release_is_counted_and_disclosed(self) -> None:
        released = {"expired": 0, "pages": 2, "with_expiry": 1}
        self.page("preise.md", "2026-11-16")
        self.page("glossar.md", "")
        quality = self.assess(released)
        self.assertEqual(quality["freshness"], released, "the released block stays as the release recorded it")
        self.assertEqual(quality["expiry"], {"as_of": "2026-11-17", "with_expiry": 1, "expired": 1})
        [notice] = [a for a in quality["advisories"] if a["code"] == "pages_past_their_expiry"]
        self.assertEqual(notice["message"], "1 page(s) declared an end date that has passed.")
        self.assertEqual(quality["state"], "current", "an expiry is a disclosure, never a due review")

    def test_the_end_date_itself_is_not_yet_past(self) -> None:
        self.page("preise.md", "2026-11-17")
        quality = self.assess({"expired": 0, "with_expiry": 1})
        self.assertEqual(quality["expiry"], {"as_of": "2026-11-17", "with_expiry": 1, "expired": 0})
        self.assertNotIn("pages_past_their_expiry", [a["code"] for a in quality["advisories"]])
        later = self.assess({"expired": 0, "with_expiry": 1}, now=NOW + timedelta(days=1))
        self.assertEqual(later["expiry"], {"as_of": "2026-11-18", "with_expiry": 1, "expired": 1})

    def test_a_page_past_its_end_date_in_the_release_and_today_is_one_page(self) -> None:
        """The release and the day of the assessment count the same page: the notice names it once, not twice."""
        self.page("preise.md", "2026-01-01")
        quality = self.assess({"expired": 1, "pages": 1, "with_expiry": 1})
        self.assertEqual(quality["expiry"], {"as_of": "2026-11-17", "with_expiry": 1, "expired": 1})
        [notice] = [a for a in quality["advisories"] if a["code"] == "pages_past_their_expiry"]
        self.assertEqual(notice["message"], "1 page(s) declared an end date that has passed.")

    def test_the_release_count_is_never_hidden(self) -> None:
        """A clock behind the release, or a page that no longer parses, must not drop a page the release counted."""
        quality = self.assess({"expired": 3, "pages": 50, "with_expiry": 4})
        self.assertEqual(quality["expiry"], {"as_of": "2026-11-17", "with_expiry": 0, "expired": 0})
        [notice] = [a for a in quality["advisories"] if a["code"] == "pages_past_their_expiry"]
        self.assertEqual(notice["message"], "3 page(s) declared an end date that has passed.")

    def test_only_pages_with_a_valid_end_date_in_their_frontmatter_count(self) -> None:
        self.page("abgelaufen.md", "2020-01-01")
        self.page("unterordner/auch.md", "2026-01-01T08:00:00Z")
        self.page("kuenftig.md", "2027-01-01")
        self.page("unlesbar.md", "irgendwann")
        self.page("nur-im-text.md", "", body='Das Feld stale_after: "2020-01-01" steht hier nur im Text.')
        self.page(".versteckt.md", "2020-01-01")
        self.release_file("wiki/kaputt.md", b'---\nstale_after: "2020-01-01"\n')
        self.release_file("wiki/binaer.md", b'---\nstale_after: "2020-01-01"\n---\n\xff\xfe\n')
        # Released Markdown outside wiki/, or a released file below wiki/ that is not Markdown, is no page,
        # even with an end date in its frontmatter.
        self.page("preisblatt.md", "2020-01-01", folder="sources")
        self.page("notiz.txt", "2020-01-01")
        self.page("2026-01-01/alt.md", "2020-01-01", folder="meta/history")
        # An editor's lock file beside the pages was never released: the verifier ignores it.
        self.page("~$owner.md", "2020-01-01", listed=False)
        # A listed path whose file is gone, and a listed path that is a folder, are skipped.
        self.release_file("wiki/ordner.md/darin.txt", b"Text.\n", listed=False)
        self.released.extend(["wiki/fehlt.md", "wiki/ordner.md"])
        self.write_manifest()
        quality = self.assess({"expired": 0, "with_expiry": 0})
        self.assertEqual(quality["expiry"], {"as_of": "2026-11-17", "with_expiry": 3, "expired": 2})

    def test_without_a_readable_manifest_no_page_is_counted(self) -> None:
        """The release's own count still decides the notice then."""
        self.page("abgelaufen.md", "2020-01-01")
        self.assertEqual(self.assess({"expired": 0})["expiry"]["expired"], 1)
        manifests = (
            b"", b"[]", b"\xff", b'{"files": "wiki/abgelaufen.md"}', b'{"files": [["wiki/abgelaufen.md"]]}',
            b'{"files": [{"path": 7}]}', b'{"files": [{"path": "abgelaufen.md"}]}',
        )
        for manifest in manifests:
            with self.subTest(manifest=manifest):
                (self.root / "meta" / "manifest.json").write_bytes(manifest)
                quality = self.assess({"expired": 0})
                self.assertEqual(quality["expiry"], {"as_of": "2026-11-17", "with_expiry": 0, "expired": 0})
                self.assertNotIn("pages_past_their_expiry", [a["code"] for a in quality["advisories"]])
                [notice] = [a for a in self.assess({"expired": 2})["advisories"] if a["code"] == "pages_past_their_expiry"]
                self.assertEqual(notice["message"], "2 page(s) declared an end date that has passed.")
        (self.root / "meta" / "manifest.json").unlink()
        self.assertEqual(self.assess({"expired": 0})["expiry"]["expired"], 0)

    def test_a_wiki_without_pages_counts_nothing(self) -> None:
        (self.root / "wiki").rmdir()
        self.assertEqual(self.assess({})["expiry"], {"as_of": "2026-11-17", "with_expiry": 0, "expired": 0})

    def test_a_missing_or_invalid_quality_status_still_counts_the_pages(self) -> None:
        """With no released count, the count on the day of the assessment alone decides the notice."""
        self.page("abgelaufen.md", "2020-01-01")
        self.page("kuenftig.md", "2027-01-01")
        status_file = self.root / "meta" / "quality-status.json"
        for code, content in (("quality_status_missing", None), ("quality_status_invalid", "[]")):
            for frozen in (False, True):
                with self.subTest(code=code, frozen=frozen):
                    status_file.unlink(missing_ok=True)
                    if content is not None:
                        status_file.write_text(content, encoding="utf-8")
                    report = quality_core.assess(RELEASE, self.root, lambda _root: IDENTITY, frozen=frozen, now=NOW)
                    quality = report["quality"]
                    self.assertEqual((report["state"], quality["state"]), ("ready", "unknown"))
                    self.assertEqual(quality["expiry"], {"as_of": "2026-11-17", "with_expiry": 2, "expired": 1})
                    self.assertEqual([a["code"] for a in quality["advisories"]], [code, "pages_past_their_expiry"])
                    self.assertEqual(quality["advisories"][1]["message"], "1 page(s) declared an end date that has passed.")
        status_file.unlink()
        early = quality_core.assess(RELEASE, self.root, lambda _root: IDENTITY, now=datetime(2019, 6, 1, tzinfo=timezone.utc))
        self.assertEqual(early["quality"]["expiry"], {"as_of": "2019-06-01", "with_expiry": 2, "expired": 0})
        self.assertEqual([a["code"] for a in early["quality"]["advisories"]], ["quality_status_missing"])

    def test_the_count_matches_the_linter_rule(self) -> None:
        """The same pages the release-time summary counts, on the same day."""
        import freshness
        values = ["2020-01-01", "2026-11-16", "2026-11-17", "2026-11-18", "irgendwann", ""]
        for index, value in enumerate(values):
            self.page(f"p{index}.md", value)
        pages = [{freshness.STALE_AFTER: value} for value in values if value]
        summary = freshness.summary(pages, today=date(2026, 11, 17))
        expiry = quality_core.expiry_on(self.root, date(2026, 11, 17))
        self.assertEqual((expiry["with_expiry"], expiry["expired"]), (summary["with_expiry"], summary["expired"]))


class FrozenWording(unittest.TestCase):
    """Only advisories about obtaining a new release read differently in an export."""

    def test_both_wordings_cover_the_same_advisories(self) -> None:
        self.assertEqual(set(quality_core.RELEASE_TEXT), set(quality_core.FROZEN_TEXT))
        for code in quality_core.RELEASE_TEXT:
            with self.subTest(code=code):
                self.assertNotEqual(quality_core.RELEASE_TEXT[code], quality_core.FROZEN_TEXT[code])
                action = quality_core.FROZEN_TEXT[code][1]
                self.assertIn("canonical", action)
                # One phrase for every frozen action, as in the export's identity advisories.
                self.assertIn("export a new knowledge skill", action.lower())
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
        reworded = {a["code"] for a in reader_advisories if wording_key(a["code"])}
        self.assertEqual(reworded, {
            "snapshot_old", "technical_quality_attention_needed", "quality_release_mismatch",
            "no_page_was_human_reviewed", "quality_policy_missing", "quality_review_attention_needed",
            "cleaning_review_overdue",
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
                                  "most in the canonical wiki and export a new knowledge skill.",
        }])
        self.assertIn(
            "Use the maintenance skill",
            [a for a in reader_advisories if a["code"] == "no_page_was_human_reviewed"][0]["recommended_action"],
        )

    def test_a_missing_invalid_or_undated_state_takes_the_frozen_wording(self) -> None:
        """The three advisories of an unknown state name the canonical wiki in an export, never the maintenance skill."""
        with tempfile.TemporaryDirectory(prefix="lmwiki-quality-core-") as directory:
            root = Path(directory)
            (root / "meta").mkdir()
            reports = {"quality_status_missing": quality_core.assess(RELEASE, root, lambda _root: IDENTITY, frozen=True, now=NOW)}
            (root / "meta" / "quality-status.json").write_text("[]", encoding="utf-8")
            reports["quality_status_invalid"] = quality_core.assess(RELEASE, root, lambda _root: IDENTITY, frozen=True, now=NOW)
            (root / "meta" / "quality-status.json").write_text(json.dumps(status()), encoding="utf-8")
            undated = {key: value for key, value in RELEASE.items() if key != "released_at"}
            reports["snapshot_age_unknown"] = quality_core.assess(undated, root, lambda _root: IDENTITY, frozen=True, now=NOW)
        for code, report in reports.items():
            with self.subTest(code=code):
                [advisory] = [item for item in report["quality"]["advisories"] if item["code"] == code]
                self.assertEqual((advisory["message"], advisory["recommended_action"]), quality_core.FROZEN_TEXT[code])
                self.assertNotIn("maintenance skill", advisory["recommended_action"])

    def test_no_frozen_advisory_names_the_maintenance_skill(self) -> None:
        """Every advisory this module can emit, driven once each, as an export words it.

        Every wording key must be reached, so a new keyed advisory needs a case
        here, and every emitted code but the expiry disclosure must come from a
        key, so an inline advisory naming the maintenance skill cannot slip in.
        """
        old = (NOW - timedelta(days=200)).isoformat().replace("+00:00", "Z")
        soon = (NOW - timedelta(days=25)).isoformat().replace("+00:00", "Z")
        undated = {key: value for key, value in RELEASE.items() if key != "released_at"}
        cases = [
            (None, RELEASE),
            ([], RELEASE),
            (status(policy=None), RELEASE),
            (status(policy={"quality_review_after_days": 0, "cleaning_review_after_days": "x",
                            "snapshot_warning_after_days": True}), RELEASE),
            (status(), undated),
            (status(reviews={"quality": {"reviewed_at": old, "outcome": "attention-needed"},
                             "cleaning": {"reviewed_at": old, "outcome": "attention-needed"}}), RELEASE),
            (status(release_id="other", technical={}), {**RELEASE, "released_at": old}),
            (status(reviews={"quality": {"reviewed_at": soon}, "cleaning": {"reviewed_at": (NOW - timedelta(days=85)).isoformat()}}), RELEASE),
            (status(trust={"counts": {}, "pages": 4}, freshness={"expired": 2}), RELEASE),
        ]
        reached: set[str] = set()
        emitted: set[str] = set()
        with tempfile.TemporaryDirectory(prefix="lmwiki-quality-core-") as directory:
            root = Path(directory)
            (root / "meta").mkdir()
            path = root / "meta" / "quality-status.json"
            for content, release in cases:
                path.unlink(missing_ok=True)
                if content is not None:
                    path.write_text(json.dumps(content), encoding="utf-8")
                frozen = quality_core.assess(release, root, lambda _root: IDENTITY, frozen=True, now=NOW)
                reader = quality_core.assess(release, root, lambda _root: IDENTITY, now=NOW)
                pairs = zip(frozen["quality"]["advisories"], reader["quality"]["advisories"])
                for mine, theirs in pairs:
                    with self.subTest(code=mine["code"]):
                        self.assertEqual(mine["code"], theirs["code"])
                        self.assertNotIn("maintenance skill", mine["message"] + mine["recommended_action"])
                        emitted.add(mine["code"])
                        key = wording_key(mine["code"])
                        if key is None:
                            self.assertEqual(mine, theirs)
                            continue
                        reached.add(key)
                        self.assertIn("canonical", mine["recommended_action"])
                        self.assertIn("export", mine["recommended_action"].lower())
        self.assertEqual(reached, set(quality_core.FROZEN_TEXT))
        self.assertEqual({code for code in emitted if not wording_key(code)}, {"pages_past_their_expiry"})
        for name in ("quality", "cleaning"):
            for state in ("unknown", "attention_needed", "overdue", "due_soon"):
                self.assertIn(f"{name}_review_{state}", emitted)
        for field in quality_core.DEFAULT_POLICY:
            self.assertIn(f"invalid_{field}", emitted)

    def test_the_query_wording_of_the_keyed_advisories_is_unchanged(self) -> None:
        """Moving them into the table must not change one byte of what the query skill prints."""
        with tempfile.TemporaryDirectory(prefix="lmwiki-quality-core-") as directory:
            root = Path(directory)
            (root / "meta").mkdir()
            old = (NOW - timedelta(days=95)).isoformat().replace("+00:00", "Z")
            (root / "meta" / "quality-status.json").write_text(json.dumps(status(
                policy={"quality_review_after_days": 0, "cleaning_review_after_days": 90, "snapshot_warning_after_days": 60},
                reviews={"quality": {"reviewed_at": (NOW - timedelta(days=25)).isoformat(), "outcome": "ok"}},
            )), encoding="utf-8")
            report = quality_core.assess({**RELEASE, "released_at": old}, root, lambda _root: IDENTITY, now=NOW)
        texts = {a["code"]: (a["severity"], a["message"], a["recommended_action"]) for a in report["quality"]["advisories"]}
        self.assertEqual(texts["invalid_quality_review_after_days"], (
            "notice", "Released quality policy field quality_review_after_days is unavailable or invalid.",
            "Use the maintenance skill to correct and release the quality policy.",
        ))
        self.assertEqual(texts["quality_review_due_soon"], (
            "notice", "The quality review is due in 5 day(s).", "Plan a quality review with the maintenance skill.",
        ))
        self.assertEqual(texts["cleaning_review_overdue"], (
            "warning", "The cleaning review is overdue by 5 day(s).",
            "Use the maintenance skill to perform a cleaning review; do not clean automatically.",
        ))
        _, [missing] = quality_core.safe_policy(None)
        self.assertEqual(missing, {
            "code": "quality_policy_missing", "severity": "notice",
            "message": "No released quality policy is available; conservative default intervals are shown.",
            "recommended_action": "Use the maintenance skill to add and release schema/QUALITY_POLICY.md.",
        })
        unknown, [advisory] = quality_core.review_freshness("cleaning", None, None, 90, NOW)
        self.assertEqual(unknown["state"], "unknown")
        self.assertEqual((advisory["code"], advisory["severity"], advisory["message"], advisory["recommended_action"]), (
            "cleaning_review_unknown", "warning", "The cleaning review age cannot be determined.",
            "Use the maintenance skill to perform and record a cleaning review.",
        ))
        _, [attention] = quality_core.review_freshness(
            "quality", {"reviewed_at": RELEASE["released_at"], "outcome": "attention-needed"}, None, 30, NOW,
        )
        self.assertEqual(attention["message"], "The latest quality review recorded issues that still need attention.")
        self.assertEqual(attention["recommended_action"], "Use the maintenance skill to address the recorded quality findings.")

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
