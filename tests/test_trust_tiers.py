#!/usr/bin/env python3
"""Per-page trust tiers (OKF stage 1).

The wiki could previously only say when someone last reviewed *the wiki*. These
tests cover the per-page record that replaces that blunt signal, and the rule
that an agent must never mark its own output as read by a person.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "query-llm-wiki" / "scripts"))

import trust_contract as tc  # noqa: E402
from harness import TempWiki  # noqa: E402


class TierDerivation(unittest.TestCase):
    def test_no_confirmation_is_unverified(self) -> None:
        self.assertEqual(tc.trust_tier({}), tc.UNVERIFIED)

    def test_an_agent_confirmation_is_machine_confirmed(self) -> None:
        self.assertEqual(
            tc.trust_tier({tc.VERIFIED_BY: "agent/claude-opus-5"}), tc.MACHINE_CONFIRMED
        )

    def test_a_process_confirmation_is_machine_confirmed(self) -> None:
        self.assertEqual(
            tc.trust_tier({tc.VERIFIED_BY: "process:nightly-check"}), tc.MACHINE_CONFIRMED
        )

    def test_only_a_human_actor_yields_human_reviewed(self) -> None:
        self.assertEqual(tc.trust_tier({tc.VERIFIED_BY: "human:mzi"}), tc.HUMAN_REVIEWED)

    def test_a_malformed_actor_never_raises_the_tier(self) -> None:
        for bogus in ("human", "Human:mzi", "mzi", "", None, 42, "human:"):
            with self.subTest(actor=bogus):
                self.assertEqual(
                    tc.trust_tier({tc.VERIFIED_BY: bogus}),
                    tc.UNVERIFIED,
                    "unparseable metadata must never be read as a confirmation",
                )


class Validation(unittest.TestCase):
    def test_a_page_without_trust_metadata_is_valid(self) -> None:
        self.assertEqual(tc.validate({}, "p"), [])

    def test_a_timestamp_without_an_actor_is_rejected(self) -> None:
        problems = tc.validate({tc.VERIFIED_AT: "2026-09-06T10:00:00Z"}, "p")
        self.assertTrue(any("requires" in item for item in problems))

    def test_an_actor_without_a_timestamp_is_rejected(self) -> None:
        problems = tc.validate({tc.VERIFIED_BY: "human:mzi"}, "p")
        self.assertTrue(any("requires" in item for item in problems))

    def test_a_non_iso_instant_is_rejected(self) -> None:
        problems = tc.validate(
            {tc.VERIFIED_BY: "human:mzi", tc.VERIFIED_AT: "06.09.2026"}, "p"
        )
        self.assertTrue(any("ISO-8601" in item for item in problems))

    def test_a_well_formed_record_passes(self) -> None:
        self.assertEqual(
            tc.validate(
                {
                    tc.GENERATED_BY: "agent/claude-opus-5",
                    tc.GENERATED_AT: "2026-09-06T09:00:00Z",
                    tc.VERIFIED_BY: "human:mzi",
                    tc.VERIFIED_AT: "2026-09-06T10:00:00Z",
                },
                "p",
            ),
            [],
        )

    def test_stamping_never_overwrites_an_existing_record(self) -> None:
        original = {tc.GENERATED_BY: "agent/first", tc.GENERATED_AT: "2026-01-01T00:00:00Z"}
        self.assertEqual(tc.stamp_generated(original, "agent/second"), original)


class Distribution(unittest.TestCase):
    def test_counts_and_share(self) -> None:
        pages = [
            {},
            {tc.VERIFIED_BY: "human:a"},
            {tc.VERIFIED_BY: "human:b"},
            {tc.VERIFIED_BY: "agent/x"},
        ]
        summary = tc.summary(tc.distribution(pages))
        self.assertEqual(summary["counts"][tc.HUMAN_REVIEWED], 2)
        self.assertEqual(summary["counts"][tc.MACHINE_CONFIRMED], 1)
        self.assertEqual(summary["counts"][tc.UNVERIFIED], 1)
        self.assertEqual(summary["human_reviewed_share"], 0.5)

    def test_the_summary_states_what_a_tier_does_not_prove(self) -> None:
        summary = tc.summary(tc.distribution([]))
        self.assertIn("does not assert", summary["boundary"])


class EndToEnd(unittest.TestCase):
    def _mark(self, wiki, actor: str, page: str = "wiki/overview.md", confirm: bool = True):
        plan_file = wiki.root / "verify-plan.json"
        wiki.locked(
            "verify_pages.py", "plan",
            "--actor", actor, "--page", page, "--output", str(plan_file),
        )
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        args = [
            "verify_pages.py", "apply",
            "--plan-file", str(plan_file),
            "--expect-plan-sha256", plan["plan_sha256"],
        ]
        if confirm:
            args.append("--user-confirmed-human-review")
        return plan, wiki.locked(*args, check=False)

    def test_an_existing_wiki_without_trust_metadata_stays_valid(self) -> None:
        with TempWiki() as wiki:
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["stats"]["trust"]["counts"][tc.UNVERIFIED], 2)

    def test_a_human_review_requires_explicit_confirmation(self) -> None:
        with TempWiki() as wiki:
            _, result = self._mark(wiki, "human:mzi", confirm=False)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["state"], "confirmation_required")
            self.assertEqual(payload["writes"], 0)
            self.assertEqual(
                json.loads(wiki.lint().stdout)["stats"]["trust"]["counts"][tc.HUMAN_REVIEWED],
                0,
                "an agent must not be able to record a human review on its own",
            )

    def test_a_machine_confirmation_needs_no_extra_flag(self) -> None:
        with TempWiki() as wiki:
            _, result = self._mark(wiki, "agent/claude-opus-5", confirm=False)
            self.assertEqual(json.loads(result.stdout)["state"], "applied")
            counts = json.loads(wiki.lint().stdout)["stats"]["trust"]["counts"]
            self.assertEqual(counts[tc.MACHINE_CONFIRMED], 1)
            self.assertEqual(counts[tc.HUMAN_REVIEWED], 0)

    def test_a_confirmed_human_review_is_recorded_and_snapshotted(self) -> None:
        with TempWiki() as wiki:
            _, result = self._mark(wiki, "human:mzi")
            payload = json.loads(result.stdout)
            self.assertEqual(payload["state"], "applied")
            self.assertEqual(payload["pages"][0]["tier"], tc.HUMAN_REVIEWED)
            self.assertTrue(list((wiki.path / "meta/history").iterdir()), "must be recoverable")
            self.assertTrue(json.loads(wiki.lint().stdout)["valid"])

    def test_a_stale_verification_plan_writes_nothing(self) -> None:
        with TempWiki() as wiki:
            plan_file = wiki.root / "verify-plan.json"
            wiki.locked(
                "verify_pages.py", "plan",
                "--actor", "human:mzi", "--page", "wiki/overview.md",
                "--output", str(plan_file),
            )
            plan = json.loads(plan_file.read_text(encoding="utf-8"))
            page = wiki.path / "wiki" / "overview.md"
            page.write_text(page.read_text(encoding="utf-8") + "\nspaeter\n", encoding="utf-8")
            result = json.loads(
                wiki.locked(
                    "verify_pages.py", "apply",
                    "--plan-file", str(plan_file),
                    "--expect-plan-sha256", plan["plan_sha256"],
                    "--user-confirmed-human-review",
                    check=False,
                ).stdout
            )
            self.assertEqual(result["state"], "stale_plan")
            self.assertEqual(result["writes"], 0)

    def test_an_index_cannot_be_marked_reviewed(self) -> None:
        with TempWiki() as wiki:
            result = wiki.locked(
                "verify_pages.py", "plan",
                "--actor", "human:mzi", "--page", "wiki/index.md",
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no assertions", result.stderr)

    def test_the_reader_receives_the_distribution(self) -> None:
        with TempWiki() as wiki:
            self._mark(wiki, "human:mzi")
            wiki.rebuild()
            wiki.release("trust-1")
            quality = wiki.query_json("assess_quality.py", "--target", str(wiki.path), check=False)
            counts = quality["quality"]["trust"]["counts"]
            self.assertEqual(counts[tc.HUMAN_REVIEWED], 1)
            self.assertEqual(counts[tc.UNVERIFIED], 1)

    def test_the_reader_is_told_when_nothing_was_human_reviewed(self) -> None:
        with TempWiki() as wiki:
            wiki.release("trust-none")
            quality = wiki.query_json("assess_quality.py", "--target", str(wiki.path), check=False)
            codes = [item["code"] for item in quality["quality"]["advisories"]]
            self.assertIn("no_page_was_human_reviewed", codes)

    def test_search_results_disclose_the_tier(self) -> None:
        with TempWiki() as wiki:
            self._mark(wiki, "human:mzi")
            wiki.rebuild()
            wiki.release("trust-2")
            found = wiki.query_json(
                "search_wiki.py", "--target", str(wiki.path), "--query", "Wiki"
            )
            tiers = {item["path"]: item["trust_tier"] for item in found["results"]}
            self.assertEqual(tiers.get("wiki/overview.md"), tc.HUMAN_REVIEWED)

    def test_a_malformed_actor_in_a_page_fails_the_lint(self) -> None:
        with TempWiki() as wiki:
            page = wiki.path / "wiki" / "overview.md"
            text = page.read_text(encoding="utf-8").replace(
                'language: "de"',
                'language: "de"\nverified_by: "mzi"\nverified_at: "2026-09-06T10:00:00Z"',
                1,
            )
            page.write_text(text, encoding="utf-8")
            report = json.loads(wiki.lint().stdout)
            self.assertFalse(report["valid"])
            self.assertTrue(any("verified_by" in item for item in report["errors"]))


class Parity(unittest.TestCase):
    def test_both_skills_share_the_same_contract(self) -> None:
        root = Path(__file__).resolve().parent.parent
        maintain = root / "maintain-llm-wiki" / "scripts" / "trust_contract.py"
        query = root / "query-llm-wiki" / "scripts" / "trust_contract.py"
        self.assertTrue(query.is_file())
        self.assertEqual(maintain.read_bytes(), query.read_bytes())



class BackwardCompatibility(unittest.TestCase):
    """A wiki written before this work must keep working unchanged."""

    def test_a_page_without_trust_metadata_lints_and_answers(self) -> None:
        with TempWiki() as wiki:
            page = wiki.read("wiki/overview.md")
            self.assertNotIn("generated_by", page, "the fixture must predate the new fields")
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            found = wiki.query_json(
                "search_wiki.py", "--target", str(wiki.path), "--query", "Wiki"
            )
            self.assertTrue(found["results"])
            self.assertEqual(found["results"][0]["trust_tier"], tc.UNVERIFIED)

    def test_a_missing_generated_by_is_a_warning_not_an_error(self) -> None:
        with TempWiki() as wiki:
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"])
            self.assertTrue(
                any("generated_by" in item for item in report["warnings"]),
                report["warnings"],
            )

    def test_a_quality_status_without_a_trust_block_degrades_quietly(self) -> None:
        """An older release has no trust block; the reader must not fail on it."""
        import assess_quality

        for status in ({}, {"trust": None}, {"trust": {"counts": None}}):
            with self.subTest(status=status):
                trust = status.get("trust") if isinstance(status.get("trust"), dict) else {}
                counts = trust.get("counts") if isinstance(trust.get("counts"), dict) else {}
                self.assertEqual(assess_quality.safe_int(counts.get("human-reviewed")), 0)
                self.assertEqual(assess_quality.safe_int(trust.get("pages")), 0)
if __name__ == "__main__":
    unittest.main(verbosity=2)
