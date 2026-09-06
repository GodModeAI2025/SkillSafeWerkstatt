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

    def test_type_is_present_on_every_non_reserved_document(self) -> None:
        """OKF reserves index.md and log.md; everything else is a concept."""
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            checked = 0
            for path in destination.rglob("*.md"):
                if path.name in okf_contract.RESERVED_FILES:
                    continue
                with self.subTest(path=path.name):
                    data = okf_contract.read_okf_frontmatter(
                        path.read_text(encoding="utf-8"), path.name
                    )
                    self.assertTrue(str(data.get("type") or "").strip(), path)
                    checked += 1
            self.assertGreater(checked, 0)

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

        index = export_okf_bundle.build_index([], [], "Wiki", "Export.")
        self.assertIn('okf_version: "0.2"', index)
        self.assertIn("# Wiki", index)
if __name__ == "__main__":
    unittest.main(verbosity=2)


class OkfSubsetReader(unittest.TestCase):
    """The bundle uses shapes the wiki's own parser rejects, so it needs its own."""

    def test_the_wiki_parser_cannot_read_an_okf_bundle(self) -> None:
        from frontmatter_contract import FrontmatterError, parse_document

        text = '---\ngenerated: { by: "agent/x", at: "2026-09-06T09:00:00Z" }\n---\n'
        with self.assertRaises(FrontmatterError):
            parse_document(text, "x", require_frontmatter=True)

    def test_the_okf_reader_handles_every_shape_the_export_emits(self) -> None:
        text = (
            '---\n'
            'type: "Concept"\n'
            'title: "Netzentgelte"\n'
            'generated: { by: "agent/x", at: "2026-09-06T09:00:00Z" }\n'
            'tags:\n'
            '  - "type/wiki-concept"\n'
            'sources:\n'
            '  - id: "src-0123456789abcdef"\n'
            '    title: "Titel, mit Komma"\n'
            '    resource: "a/b.pdf"\n'
            '---\nbody\n'
        )
        data = okf_contract.read_okf_frontmatter(text, "x")
        self.assertEqual(data["generated"], {"by": "agent/x", "at": "2026-09-06T09:00:00Z"})
        self.assertEqual(data["tags"], ["type/wiki-concept"])
        self.assertEqual(data["sources"][0]["title"], "Titel, mit Komma")

    def test_a_missing_block_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            okf_contract.read_okf_frontmatter("kein frontmatter\n", "x")

    def test_an_unterminated_block_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            okf_contract.read_okf_frontmatter('---\ntype: "C"\n', "x")

    def test_a_duplicate_property_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            okf_contract.read_okf_frontmatter('---\ntype: "A"\ntype: "B"\n---\n', "x")


class BundleConformance(unittest.TestCase):
    def test_a_written_bundle_validates(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination = wiki.root / "bundle"
            result = wiki.maintain(
                "export_okf_bundle.py",
                "--target", str(wiki.path), "--destination", str(destination),
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(okf_contract.validate_bundle(destination), [])
            self.assertIn("validated against OKF", json.loads(result.stdout)["conformance"])

    def test_a_non_conformant_bundle_is_detected(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.md").write_text('---\nokf_version: "0.2"\n---\n', encoding="utf-8")
            (root / "broken.md").write_text("kein frontmatter\n", encoding="utf-8")
            (root / "typeless.md").write_text('---\ntitle: "X"\n---\n', encoding="utf-8")
            problems = okf_contract.validate_bundle(root)
            self.assertEqual(len(problems), 2, problems)

    def test_a_missing_root_index_is_detected(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            problems = okf_contract.validate_bundle(Path(directory))
            self.assertTrue(any("index.md is missing" in item for item in problems))

    def test_the_readme_is_itself_a_conformant_concept(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination = wiki.root / "bundle"
            wiki.maintain(
                "export_okf_bundle.py",
                "--target", str(wiki.path), "--destination", str(destination),
                check=False,
            )
            data = okf_contract.read_okf_frontmatter(
                (destination / "README.md").read_text(encoding="utf-8"), "README.md"
            )
            self.assertEqual(data["type"], "Documentation")


class SelfContainedBundle(unittest.TestCase):
    """A bundle whose pages cite sources it lacks has broken provenance."""

    def _export(self, wiki, *extra: str):
        destination = wiki.root / "bundle"
        result = wiki.maintain(
            "export_okf_bundle.py",
            "--target", str(wiki.path), "--destination", str(destination),
            *extra, check=False,
        )
        return destination, result

    def test_registered_sources_are_part_of_the_bundle(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, result = self._export(wiki)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["sources"], 1)
            exported = list((destination / "sources").glob("*.md"))
            self.assertEqual(len(exported), 1)
            data = okf_contract.read_okf_frontmatter(
                exported[0].read_text(encoding="utf-8"), "source"
            )
            self.assertEqual(data["type"], "Source")
            self.assertEqual(data["resource"], "intern/netzentgelte-2026.pdf")
            self.assertIn("language/de", data["tags"])

    def test_the_source_extraction_text_survives(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            text = next((destination / "sources").glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("7,2 Cent", text, "the faithful extraction must come with the bundle")

    def test_the_index_lists_the_sources(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            index = (destination / "index.md").read_text(encoding="utf-8")
            self.assertIn("## Sources", index)
            self.assertIn("/sources/src-", index)

    def test_sources_can_be_omitted_deliberately(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, result = self._export(wiki, "--no-sources")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["sources"], 0)
            self.assertFalse((destination / "sources").exists())
            self.assertEqual(okf_contract.validate_bundle(destination), [])

    def test_the_reserved_log_carries_the_change_record(self) -> None:
        with TempWiki() as wiki:
            build_curated_wiki(wiki)
            destination, _ = self._export(wiki)
            log = destination / "log.md"
            self.assertTrue(log.is_file(), "OKF reserves log.md for the chronological record")
            text = log.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# Log"))
            self.assertNotIn("[[", text, "wikilinks must be converted in the log too")

    def test_a_partial_extraction_maps_to_draft_with_a_note(self) -> None:
        record = {"title": "Q", "original_ref": "a/b.pdf", "status": "partial"}
        import export_okf_bundle

        okf, notes = export_okf_bundle.convert_source(record, "body")
        self.assertEqual(okf["status"], "draft")
        self.assertTrue(any("no partial status" in note for note in notes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
