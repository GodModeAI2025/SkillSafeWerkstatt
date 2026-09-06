#!/usr/bin/env python3
"""OKF v0.2 compatibility report and bundle export (OKF stage 3).

The previous report checked a v0.1-era field set including `timestamp`, which is
not a field of this specification, and produced no export path at all.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import okf_contract  # noqa: E402
import trust_contract  # noqa: E402
from harness import TempWiki  # noqa: E402
from test_lifecycle import SOURCE_MARKDOWN, add_cluster_and_concept, curate_page  # noqa: E402


def build_curated_wiki(wiki) -> None:
    """Reproduce the lifecycle fixture: one source, one evidence-linked page."""
    extract = wiki.root / "netzentgelte.md"
    extract.write_text(SOURCE_MARKDOWN, encoding="utf-8")
    registered = json.loads(
        wiki.locked(
            "register_source.py",
            "--markdown-file", str(extract),
            "--title", "Netzentgelte 2026",
            "--original-ref", "intern/netzentgelte-2026.pdf",
            "--content-language", "de",
        ).stdout
    )["source"]
    add_cluster_and_concept(wiki)
    index = wiki.read("wiki/index.md")
    wiki.write(
        "wiki/index.md",
        index.rstrip() + "\n\n- [[wiki/concepts/netzentgelte|Netzentgelte]]\n",
    )
    claim_id = json.loads(wiki.locked("claim_id.py", "--count", "1").stdout)["claim_ids"][0]
    curate_page(wiki, registered["source_id"], Path(registered["path"]).stem, claim_id)
    wiki.rebuild()
    wiki.release("okf-fixture")


class Mapping(unittest.TestCase):
    def test_statuses_map_onto_the_okf_set(self) -> None:
        self.assertEqual(okf_contract.okf_status("active"), "stable")
        self.assertEqual(okf_contract.okf_status("superseded"), "deprecated")
        self.assertEqual(okf_contract.okf_status("draft"), "draft")

    def test_an_unknown_status_defaults_to_stable(self) -> None:
        self.assertEqual(okf_contract.okf_status("etwas-anderes"), "stable")

    def test_a_lossy_mapping_is_explained(self) -> None:
        note = okf_contract.status_note("disputed")
        self.assertIn("no disputed status", note)

    def test_a_lossless_mapping_needs_no_note(self) -> None:
        self.assertEqual(okf_contract.status_note("active"), "")

    def test_the_actor_record_is_composed_from_the_flat_fields(self) -> None:
        record = okf_contract.actor_record("human:mzi", "2026-09-06T10:00:00Z")
        self.assertEqual(record, {"by": "human:mzi", "at": "2026-09-06T10:00:00Z"})

    def test_an_invalid_actor_composes_to_nothing(self) -> None:
        self.assertIsNone(okf_contract.actor_record("mzi", "2026-09-06T10:00:00Z"))
        self.assertIsNone(okf_contract.actor_record("human:mzi", "gestern"))

    def test_only_registered_sources_are_emitted(self) -> None:
        registry = {"src-0123456789abcdef": {"title": "Q", "original_ref": "a/b.pdf"}}
        records = okf_contract.source_records(
            ["[[sources/src-0123456789abcdef-q|Q]]", "[[sources/src-ffffffffffffffff-x|X]]"],
            registry,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], "src-0123456789abcdef")

    def test_nothing_is_invented_for_an_incomplete_registry(self) -> None:
        registry = {"src-0123456789abcdef": {}}
        records = okf_contract.source_records(["[[sources/src-0123456789abcdef-q]]"], registry)
        self.assertEqual(records, [{"id": "src-0123456789abcdef"}])


class Report(unittest.TestCase):
    def test_the_report_targets_v0_2(self) -> None:
        with TempWiki() as wiki:
            report = json.loads(wiki.locked("report_okf.py").stdout)
            self.assertEqual(report["okf_version"], "0.2")
            self.assertEqual(report["format"], "lmwiki-okf-compatibility/2")

    def test_timestamp_is_no_longer_treated_as_an_okf_field(self) -> None:
        self.assertNotIn("timestamp", okf_contract.RECOMMENDED)
        with TempWiki() as wiki:
            report = json.loads(wiki.locked("report_okf.py").stdout)
            self.assertNotIn("timestamp", json.dumps(report))

    def test_the_report_changes_nothing(self) -> None:
        with TempWiki() as wiki:
            before = json.loads(wiki.read("meta/manifest.json"))
            wiki.locked("report_okf.py")
            self.assertEqual(json.loads(wiki.read("meta/manifest.json")), before)
            self.assertEqual(wiki.verify()["state"], "ready")

    def test_v0_2_trust_fields_are_checked(self) -> None:
        with TempWiki() as wiki:
            page = wiki.path / "wiki" / "overview.md"
            page.write_text(
                page.read_text(encoding="utf-8").replace(
                    'language: "de"', 'language: "de"\nverified_at: "2026-09-06T10:00:00Z"', 1
                ),
                encoding="utf-8",
            )
            report = json.loads(wiki.locked("report_okf.py").stdout)
            warnings = [w for item in report["documents"] for w in item["warnings"]]
            self.assertTrue(any("verified_at" in w for w in warnings), warnings)

    def test_the_report_names_what_an_export_would_lose(self) -> None:
        with TempWiki() as wiki:
            report = json.loads(wiki.locked("report_okf.py").stdout)
            joined = " ".join(report["not_exported"])
            self.assertIn("locator", joined)
            self.assertIn("release manifest", joined)


class Export(unittest.TestCase):
    def _export(self, wiki, extra: list[str] | None = None):
        destination = wiki.root / "okf-bundle"
        result = wiki.maintain(
            "export_okf_bundle.py",
            "--target", str(wiki.path),
            "--destination", str(destination),
            *(extra or []),
            check=False,
        )
        return destination, result

    def test_a_bundle_is_written_from_a_verified_release(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, result = self._export(wiki)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["state"], "exported")
            self.assertEqual(payload["okf_version"], "0.2")
            self.assertTrue((destination / "index.md").is_file())
            self.assertTrue((destination / "concepts" / "netzentgelte.md").is_file())

    def test_the_root_index_declares_the_version_and_nothing_else(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            text = (destination / "index.md").read_text(encoding="utf-8")
            frontmatter = text.split("---")[1].strip().splitlines()
            self.assertEqual(frontmatter, ['okf_version: "0.2"'])

    def test_type_is_present_on_every_concept(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            for path in destination.rglob("*.md"):
                if path.name in {"index.md", "README.md"}:
                    continue
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---"), path)
                self.assertIn("type:", text.split("---")[1], path)

    def test_trust_metadata_is_composed_into_the_nested_okf_form(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            plan_file = wiki.root / "v.json"
            wiki.locked(
                "verify_pages.py", "plan",
                "--actor", "human:mzi",
                "--page", "wiki/concepts/netzentgelte.md",
                "--output", str(plan_file),
            )
            plan = json.loads(plan_file.read_text(encoding="utf-8"))
            wiki.locked(
                "verify_pages.py", "apply",
                "--plan-file", str(plan_file),
                "--expect-plan-sha256", plan["plan_sha256"],
                "--user-confirmed-human-review",
            )
            wiki.rebuild()
            wiki.release("okf-verified")
            destination, result = self._export(wiki)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = (destination / "concepts" / "netzentgelte.md").read_text(encoding="utf-8")
            self.assertIn('verified: { by: "human:mzi", at:', text)

    def test_registered_sources_become_okf_source_entries(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            text = (destination / "concepts" / "netzentgelte.md").read_text(encoding="utf-8")
            self.assertIn("sources:", text)
            self.assertIn("id: \"src-", text)
            self.assertIn('resource: "intern/netzentgelte-2026.pdf"', text)

    def test_claim_markers_are_stripped_but_the_statement_survives(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            text = (destination / "concepts" / "netzentgelte.md").read_text(encoding="utf-8")
            self.assertNotIn("<!-- claim", text)
            self.assertNotIn("claim_id", text)
            self.assertIn("7,2 Cent", text, "the maintained statement must survive")

    def test_wikilinks_become_bundle_relative_links(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            for path in destination.rglob("*.md"):
                self.assertNotIn("[[", path.read_text(encoding="utf-8"), path)

    def test_the_readme_names_every_loss(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            readme = (destination / "README.md").read_text(encoding="utf-8")
            self.assertIn("not the wiki", readme)
            for item in okf_contract.NOT_EXPORTED:
                self.assertIn(item, readme)

    def test_the_wiki_is_untouched_by_an_export(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            before = json.loads(wiki.read("meta/manifest.json"))
            self._export(wiki)
            self.assertEqual(json.loads(wiki.read("meta/manifest.json")), before)
            self.assertEqual(wiki.verify()["state"], "ready")

    def test_an_unverifiable_release_produces_no_bundle(self) -> None:
        with TempWiki() as wiki:
            page = wiki.path / "wiki" / "overview.md"
            page.write_text(page.read_text(encoding="utf-8") + "\nmanipuliert\n", encoding="utf-8")
            destination, result = self._export(wiki)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["state"], "not_exported")
            self.assertFalse(destination.exists(), "no partial bundle may be left behind")

    def test_a_non_empty_destination_is_refused(self) -> None:
        with TempWiki() as wiki:
            destination = wiki.root / "okf-bundle"
            destination.mkdir()
            (destination / "vorhanden.md").write_text("x", encoding="utf-8")
            result = wiki.maintain(
                "export_okf_bundle.py",
                "--target", str(wiki.path),
                "--destination", str(destination),
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not empty", result.stderr)

    def test_the_destination_may_not_sit_inside_the_wiki(self) -> None:
        with TempWiki() as wiki:
            result = wiki.maintain(
                "export_okf_bundle.py",
                "--target", str(wiki.path),
                "--destination", str(wiki.path / "okf"),
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside the wiki", result.stderr)



class EdgeCases(unittest.TestCase):
    def test_a_wiki_file_without_a_heading_does_not_break_the_export(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            # A WIKI.md whose first line is not a heading must not raise.
            (wiki.path / "WIKI.md").write_text("Nur Fliesstext.\n", encoding="utf-8")
            destination = wiki.root / "bundle-no-heading"
            result = wiki.maintain(
                "export_okf_bundle.py",
                "--target", str(wiki.path),
                "--destination", str(destination),
                check=False,
            )
            # The release no longer verifies, so no bundle is written - but the
            # failure must be the verification, never a crash.
            self.assertIn(result.returncode, (0, 4), result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_an_empty_wiki_title_falls_back_without_raising(self) -> None:
        import export_okf_bundle

        index = export_okf_bundle.build_index([], "Wiki", "Export.")
        self.assertIn('okf_version: "0.2"', index)
        self.assertIn("# Wiki", index)
if __name__ == "__main__":
    unittest.main(verbosity=2)
