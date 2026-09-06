#!/usr/bin/env python3
"""The full maintenance and reading cycle on a realistic wiki.

This is the regression floor for every other change: initialize, register a
source, curate an evidence-linked page, rebuild derived views, lint, release,
verify, and answer from the released state.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import TempWiki, Wiki  # noqa: E402


SOURCE_MARKDOWN = """# Netzentgelte 2026

<!-- page: 1 -->

## Grundlagen

Die Netzentgelte werden jaehrlich durch den Netzbetreiber festgelegt.

<!-- page: 2 -->

## Berechnung

Der Arbeitspreis betraegt 7,2 Cent je Kilowattstunde.
"""


def curate_page(wiki: Wiki, source_id: str, source_stem: str, claim_id: str) -> None:
    """Stage and apply one evidence-linked page through the real batch helper."""
    staging = wiki.root / "staging"
    staging.mkdir(exist_ok=True)
    page = f"""---
id: "concept-netzentgelte"
title: "Netzentgelte"
type: "concept"
status: "active"
created: "2026-09-06"
updated: "2026-09-06"
description: "Grundlagen und Berechnung der Netzentgelte."
language: "de"
sources:
  - "[[sources/{source_stem}|Netzentgelte 2026]]"
clusters:
  - "netz"
concepts:
  - "netzentgelt"
tags:
  - "type/wiki-concept"
---

# Netzentgelte

<!-- claim
id: {claim_id}
kind: fact
status: active
sources: {source_id}@page=2
-->
Der Arbeitspreis betraegt 7,2 Cent je Kilowattstunde.
<!-- /claim -->
"""
    # The staged tree mirrors the wiki-relative target path.
    target_path = "wiki/concepts/netzentgelte.md"
    staged = staging / target_path
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(page, encoding="utf-8")
    plan_file = wiki.root / "page-plan.json"
    wiki.locked(
        "page_batch.py",
        "plan",
        "--staging-dir",
        str(staging),
        "--paths-json",
        json.dumps([target_path]),
        "--output",
        str(plan_file),
    )
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    wiki.locked(
        "page_batch.py",
        "apply",
        "--staging-dir",
        str(staging),
        "--plan-file",
        str(plan_file),
        "--expect-plan-sha256",
        plan["plan_sha256"],
    )


def add_cluster_and_concept(wiki: Wiki) -> None:
    """Confirm one navigation cluster and one controlled concept."""
    clusters = wiki.read("schema/CLUSTERS.md")
    wiki.write(
        "schema/CLUSTERS.md",
        clusters.rstrip()
        + (
            "\n\n## netz\n"
            "- Label: Netz\n"
            "- Color: #000099\n"
            "- Status: active\n"
            "- Purpose: Netzbetrieb und Entgelte\n"
        ),
    )
    concepts = wiki.read("schema/CONCEPTS.md")
    wiki.write(
        "schema/CONCEPTS.md",
        concepts.rstrip()
        + (
            "\n\n## netzentgelt\n"
            "- Preferred: Netzentgelt\n"
            "- Status: active\n"
            "- Definition: Entgelt fuer die Nutzung des Stromnetzes\n"
            "- Aliases: Netznutzungsentgelt | Arbeitspreis\n"
        ),
    )


class FullCycle(unittest.TestCase):
    def test_initialize_curate_release_and_read(self) -> None:
        with TempWiki() as wiki:
            # 1. A fresh wiki is immediately valid and readable.
            self.assertEqual(wiki.verify()["state"], "ready")
            self.assertTrue(json.loads(wiki.lint().stdout)["valid"])

            # 2. Register a faithful extraction.
            extract = wiki.root / "netzentgelte.md"
            extract.write_text(SOURCE_MARKDOWN, encoding="utf-8")
            registered = wiki.locked(
                "register_source.py",
                "--markdown-file",
                str(extract),
                "--title",
                "Netzentgelte 2026",
                "--original-ref",
                "intern/netzentgelte-2026.pdf",
                "--content-language",
                "de",
            )
            record = json.loads(registered.stdout)["source"]
            source_id = record["source_id"]
            source_stem = Path(record["path"]).stem
            self.assertRegex(source_id, r"^src-[0-9a-f]{16}$")

            # 3. Confirm navigation, vocabulary and the index entry. The batch
            #    helper refuses a page the index does not yet reference.
            add_cluster_and_concept(wiki)
            index = wiki.read("wiki/index.md")
            wiki.write(
                "wiki/index.md",
                index.rstrip() + "\n\n- [[wiki/concepts/netzentgelte|Netzentgelte]]\n",
            )

            # 4. Curate an evidence-linked page and rebuild derived views.
            claim_id = json.loads(
                wiki.locked("claim_id.py", "--count", "1").stdout
            )["claim_ids"][0]
            curate_page(wiki, source_id, source_stem, claim_id)
            wiki.rebuild()

            # 5. Lint must pass on the curated state.
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["stats"]["registered_sources"], 1)
            self.assertEqual(report["stats"]["claims"], 1)

            # 6. Release and verify.
            before = wiki.current_version()
            result = wiki.release("cycle-1")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotEqual(wiki.current_version(), before, "a release must bump the version")
            state = wiki.verify()
            self.assertEqual(state["state"], "ready", state)
            self.assertEqual(wiki.verify(query_side=True)["state"], "ready")

            # 7. The read skill finds the curated page and its evidence.
            found = wiki.query_json(
                "search_wiki.py", "--target", str(wiki.path), "--query", "Arbeitspreis Netzentgelte"
            )
            paths = [item["path"] for item in found["results"]]
            self.assertIn("wiki/concepts/netzentgelte.md", paths, found)

    def test_release_is_idempotent_per_operation_id(self) -> None:
        with TempWiki() as wiki:
            first = wiki.release("same-operation")
            version_after_first = wiki.current_version()
            second = wiki.release("same-operation")
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(
                wiki.current_version(),
                version_after_first,
                "replaying one operation id must not bump the version twice",
            )

    def test_reader_refuses_while_maintenance_holds_the_lock(self) -> None:
        with TempWiki() as wiki:
            token_file = wiki.root / "held-token"
            wiki.maintain(
                "wiki_lock.py",
                "acquire",
                "--target",
                str(wiki.path),
                "--token-file",
                str(token_file),
                "--owner",
                "test/holder",
            )
            try:
                self.assertEqual(wiki.verify(query_side=True)["state"], "wiki_busy")
            finally:
                wiki.maintain(
                    "wiki_lock.py",
                    "release",
                    "--target",
                    str(wiki.path),
                    "--token-file",
                    str(token_file),
                    check=False,
                )
            self.assertEqual(wiki.verify(query_side=True)["state"], "ready")

    def test_tampering_with_a_released_file_is_detected(self) -> None:
        with TempWiki() as wiki:
            page = wiki.path / "wiki" / "overview.md"
            page.write_text(page.read_text(encoding="utf-8") + "\nmanipuliert\n", encoding="utf-8")
            state = wiki.verify()
            self.assertEqual(
                state["state"],
                "invalid_wiki",
                "a changed released file must still fail closed",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
