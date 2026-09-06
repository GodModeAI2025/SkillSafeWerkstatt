#!/usr/bin/env python3
"""Per-page expiry and observation sources.

Two decisions, both about what the wiki is allowed to say about itself:

- `stale_after` lets one page declare its own end date, without the wiki-wide
  quality policy having to pretend it knows about that page.
- An observation is a registered source whose origin is an event rather than a
  document, so knowledge that arises during the work has a way in without the
  evidence chain acquiring a gap.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import freshness  # noqa: E402
from harness import TempWiki  # noqa: E402


class ParseExpiry(unittest.TestCase):
    def test_a_plain_date_is_accepted(self) -> None:
        self.assertEqual(freshness.parse_instant("2026-12-31"), date(2026, 12, 31))

    def test_an_iso_instant_is_accepted(self) -> None:
        self.assertEqual(freshness.parse_instant("2026-12-31T23:59:00Z"), date(2026, 12, 31))

    def test_anything_else_is_not_a_date(self) -> None:
        for value in ("31.12.2026", "irgendwann", "", None, 42, "2026-13-01"):
            with self.subTest(value=value):
                self.assertIsNone(freshness.parse_instant(value))


class Staleness(unittest.TestCase):
    def test_a_page_without_an_expiry_is_never_stale(self) -> None:
        self.assertFalse(freshness.is_stale({}))

    def test_an_unparseable_expiry_is_never_stale(self) -> None:
        """A malformed value must not silently expire a page."""
        self.assertFalse(freshness.is_stale({freshness.STALE_AFTER: "irgendwann"}))

    def test_a_passed_date_is_stale(self) -> None:
        self.assertTrue(
            freshness.is_stale({freshness.STALE_AFTER: "2020-01-01"}, today=date(2026, 9, 6))
        )

    def test_the_date_itself_is_not_yet_past(self) -> None:
        self.assertFalse(
            freshness.is_stale({freshness.STALE_AFTER: "2026-09-06"}, today=date(2026, 9, 6))
        )

    def test_days_past_counts_only_forward(self) -> None:
        self.assertEqual(
            freshness.days_past({freshness.STALE_AFTER: "2026-09-01"}, today=date(2026, 9, 6)), 5
        )
        self.assertIsNone(
            freshness.days_past({freshness.STALE_AFTER: "2026-12-31"}, today=date(2026, 9, 6))
        )

    def test_the_summary_states_what_an_expiry_does_not_mean(self) -> None:
        summary = freshness.summary([{freshness.STALE_AFTER: "2020-01-01"}])
        self.assertEqual(summary["expired"], 1)
        self.assertIn("does not say the content is wrong", summary["boundary"])


class InTheWiki(unittest.TestCase):
    def _with_expiry(self, wiki, value: str) -> None:
        page = wiki.path / "wiki" / "overview.md"
        page.write_text(
            page.read_text(encoding="utf-8").replace(
                'language: "de"', f'language: "de"\nstale_after: "{value}"', 1
            ),
            encoding="utf-8",
        )

    def test_a_page_without_an_expiry_stays_valid(self) -> None:
        with TempWiki() as wiki:
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["stats"]["freshness"]["with_expiry"], 0)

    def test_a_well_formed_expiry_is_accepted_and_counted(self) -> None:
        with TempWiki() as wiki:
            self._with_expiry(wiki, "2020-01-01")
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["stats"]["freshness"]["with_expiry"], 1)
            self.assertEqual(report["stats"]["freshness"]["expired"], 1)

    def test_a_malformed_expiry_fails_the_lint(self) -> None:
        with TempWiki() as wiki:
            self._with_expiry(wiki, "irgendwann")
            report = json.loads(wiki.lint().stdout)
            self.assertFalse(report["valid"])
            self.assertTrue(any("stale_after" in item for item in report["errors"]))

    def test_the_reader_is_told_and_does_not_hide_the_page(self) -> None:
        with TempWiki() as wiki:
            self._with_expiry(wiki, "2020-01-01")
            wiki.rebuild()
            wiki.release("expiry-1")

            quality = wiki.query_json("assess_quality.py", "--target", str(wiki.path), check=False)
            codes = [item["code"] for item in quality["quality"]["advisories"]]
            self.assertIn("pages_past_their_expiry", codes)

            found = wiki.query_json(
                "search_wiki.py", "--target", str(wiki.path), "--query", "Überblick"
            )
            paths = {item["path"]: item for item in found["results"]}
            self.assertIn(
                "wiki/overview.md",
                paths,
                "an expired page must still be findable; expiry is a disclosure, not a filter",
            )
            self.assertTrue(paths["wiki/overview.md"]["past_expiry"])

    def test_the_export_carries_the_expiry(self) -> None:
        with TempWiki() as wiki:
            self._with_expiry(wiki, "2026-12-31")
            wiki.rebuild()
            wiki.release("expiry-2")
            destination = wiki.root / "bundle"
            result = wiki.maintain(
                "export_okf_bundle.py",
                "--target", str(wiki.path), "--destination", str(destination),
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                'stale_after: "2026-12-31"',
                (destination / "overview.md").read_text(encoding="utf-8"),
            )


OBSERVATION = "# Entscheidung\n\n<!-- page: 1 -->\n\nWir rechnen ab 2027 mit dem Arbeitspreis.\n"


class ObservationSources(unittest.TestCase):
    def _register(self, wiki, *extra: str, check: bool = True):
        record = wiki.root / "beobachtung.md"
        record.write_text(OBSERVATION, encoding="utf-8")
        return wiki.locked(
            "register_source.py",
            "--markdown-file", str(record),
            "--title", "Entscheidung Netzentgelte",
            "--original-ref", "observation:2026-09-06/entscheidung-netzentgelte",
            "--content-language", "de",
            "--source-type", "observation",
            *extra,
            check=check,
        )

    def test_an_observation_becomes_a_registered_source(self) -> None:
        with TempWiki() as wiki:
            result = self._register(
                wiki, "--observed-by", "human:mzi", "--occasion", "Architekturrunde"
            )
            record = json.loads(result.stdout)["source"]
            self.assertEqual(record["source_type"], "observation")
            self.assertEqual(record["observed_by"], "human:mzi")
            self.assertEqual(record["occasion"], "Architekturrunde")
            self.assertRegex(record["source_id"], r"^src-[0-9a-f]{16}$")

    def test_an_observation_nobody_is_named_for_is_refused(self) -> None:
        with TempWiki() as wiki:
            result = self._register(wiki, "--occasion", "Runde", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("observed-by", result.stderr)

    def test_an_observation_without_an_occasion_is_refused(self) -> None:
        with TempWiki() as wiki:
            result = self._register(wiki, "--observed-by", "human:mzi", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("occasion", result.stderr)

    def test_a_malformed_actor_is_refused(self) -> None:
        with TempWiki() as wiki:
            result = self._register(
                wiki, "--observed-by", "mzi", "--occasion", "Runde", check=False
            )
            self.assertNotEqual(result.returncode, 0)

    def test_the_fields_belong_to_observations_only(self) -> None:
        with TempWiki() as wiki:
            record = wiki.root / "doc.md"
            record.write_text(OBSERVATION, encoding="utf-8")
            result = wiki.locked(
                "register_source.py",
                "--markdown-file", str(record),
                "--title", "Ein Dokument",
                "--original-ref", "intern/doc.pdf",
                "--content-language", "de",
                "--observed-by", "human:mzi",
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("observation", result.stderr)

    def test_a_registered_observation_passes_the_lint(self) -> None:
        with TempWiki() as wiki:
            self._register(wiki, "--observed-by", "human:mzi", "--occasion", "Architekturrunde")
            wiki.rebuild()
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["stats"]["registered_sources"], 1)

    def test_an_observation_missing_its_actor_in_the_registry_fails_the_lint(self) -> None:
        with TempWiki() as wiki:
            self._register(wiki, "--observed-by", "human:mzi", "--occasion", "Architekturrunde")
            wiki.rebuild()
            registry = wiki.path / "meta" / "sources.jsonl"
            record = json.loads(registry.read_text(encoding="utf-8").strip())
            record.pop("observed_by")
            registry.write_text(json.dumps(record) + "\n", encoding="utf-8")
            report = json.loads(wiki.lint().stdout)
            self.assertFalse(report["valid"])
            self.assertTrue(
                any("observation without a valid observed_by" in item for item in report["errors"]),
                report["errors"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
