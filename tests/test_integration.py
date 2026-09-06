#!/usr/bin/env python3
"""End-to-end behaviour on a larger, realistic wiki.

The small fixtures elsewhere prove each rule in isolation. This one checks the
properties that only appear at scale or across features: that nothing leaks an
absolute path, that ranking stays sensible with many pages, and that the whole
storage and trust machinery holds together on one wiki at once.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import TempWiki, Wiki  # noqa: E402

TOPICS = [
    ("netzentgelte", "Netzentgelte", "Arbeitspreis und Leistungspreis der Netznutzung"),
    ("bilanzkreis", "Bilanzkreis", "Ausgleich von Einspeisung und Entnahme"),
    ("redispatch", "Redispatch", "Eingriff in die Fahrweise von Erzeugungsanlagen"),
    ("messkonzept", "Messkonzept", "Zuordnung von Zählpunkten und Messwerten"),
    ("lastgang", "Lastgang", "Zeitlich aufgelöste Verbrauchsmessung"),
    ("regelenergie", "Regelenergie", "Kurzfristiger Ausgleich von Frequenzabweichungen"),
    ("konzessionsabgabe", "Konzessionsabgabe", "Entgelt für die Nutzung öffentlicher Wege"),
    ("netzanschluss", "Netzanschluss", "Technische und rechtliche Anbindung an das Netz"),
]


def seed_pages(wiki: Wiki, source_id: str, source_stem: str, claim_ids: list[str]) -> None:
    """Write several curated pages through the real batch helper in one plan."""
    staging = wiki.root / "staging"
    targets: list[str] = []
    for (slug, title, description), claim_id in zip(TOPICS, claim_ids):
        relative = f"wiki/concepts/{slug}.md"
        targets.append(relative)
        page = f"""---
id: "concept-{slug}"
title: "{title}"
type: "concept"
status: "active"
created: "2026-09-06"
updated: "2026-09-06"
description: "{description}."
language: "de"
generated_by: "agent/test-suite"
generated_at: "2026-09-06T08:00:00Z"
sources:
  - "[[sources/{source_stem}|Netzentgelte 2026]]"
clusters:
  - "netz"
concepts:
  - "netzentgelt"
tags:
  - "type/wiki-concept"
---

# {title}

## Einordnung

{description} im Kontext des Verteilnetzbetriebs.

<!-- claim
id: {claim_id}
kind: fact
status: active
sources: {source_id}@page=2
-->
{description} wird jaehrlich durch den Netzbetreiber festgelegt.
<!-- /claim -->
"""
        staged = staging / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(page, encoding="utf-8")

    index = wiki.read("wiki/index.md").rstrip()
    for slug, title, _ in TOPICS:
        index += f"\n- [[wiki/concepts/{slug}|{title}]]"
    wiki.write("wiki/index.md", index + "\n")

    plan_file = wiki.root / "batch.json"
    wiki.locked(
        "page_batch.py", "plan",
        "--staging-dir", str(staging),
        "--paths-json", json.dumps(targets),
        "--output", str(plan_file),
    )
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    wiki.locked(
        "page_batch.py", "apply",
        "--staging-dir", str(staging),
        "--plan-file", str(plan_file),
        "--expect-plan-sha256", plan["plan_sha256"],
    )


def build_large_wiki(wiki: Wiki) -> None:
    from test_lifecycle import SOURCE_MARKDOWN, add_cluster_and_concept

    extract = wiki.root / "quelle.md"
    extract.write_text(SOURCE_MARKDOWN, encoding="utf-8")
    record = json.loads(
        wiki.locked(
            "register_source.py",
            "--markdown-file", str(extract),
            "--title", "Netzentgelte 2026",
            "--original-ref", "intern/netzentgelte-2026.pdf",
            "--content-language", "de",
        ).stdout
    )["source"]
    add_cluster_and_concept(wiki)
    claim_ids = json.loads(
        wiki.locked("claim_id.py", "--count", str(len(TOPICS))).stdout
    )["claim_ids"]
    seed_pages(wiki, record["source_id"], Path(record["path"]).stem, claim_ids)
    wiki.rebuild()


class LargeWiki(unittest.TestCase):
    def test_a_realistic_wiki_lints_releases_and_verifies(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["stats"]["wiki_pages"], len(TOPICS) + 2)
            self.assertEqual(report["stats"]["claims"], len(TOPICS))
            self.assertEqual(wiki.release("large-1").returncode, 0)
            self.assertEqual(wiki.verify()["state"], "ready")
            self.assertEqual(wiki.verify(query_side=True)["state"], "ready")

    def test_ranking_separates_topics_at_scale(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            wiki.release("large-2")
            for slug, title, _ in TOPICS:
                with self.subTest(topic=title):
                    found = wiki.query_json(
                        "search_wiki.py", "--target", str(wiki.path), "--query", title
                    )
                    self.assertTrue(found["results"], title)
                    self.assertEqual(
                        found["results"][0]["path"],
                        f"wiki/concepts/{slug}.md",
                        f"searching {title!r} must rank its own page first",
                    )

    def test_every_generated_reference_is_relative(self) -> None:
        """No output may leak an absolute machine path."""
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            wiki.release("large-3")
            root = str(wiki.path)
            offenders: list[str] = []
            for path in wiki.path.rglob("*"):
                if not path.is_file() or path.suffix not in {".md", ".json", ".jsonl", ".html"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if root in text or "file://" in text:
                    offenders.append(path.relative_to(wiki.path).as_posix())
            self.assertEqual(offenders, [], f"absolute paths leaked into {offenders}")

    def test_helper_reports_do_not_leak_the_target_path(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)
            wiki.release("large-4")
            root = str(wiki.path)
            for name, args in (
                ("verify_release.py", ()),
                ("assess_quality.py", ()),
                ("inventory_wiki.py", ()),
            ):
                with self.subTest(helper=name):
                    output = wiki.query(name, "--target", root, *args, check=False).stdout
                    self.assertNotIn(root, output, f"{name} leaked the absolute target path")

    def test_trust_storage_and_okf_hold_together_on_one_wiki(self) -> None:
        with TempWiki() as wiki:
            build_large_wiki(wiki)

            # Confirm two pages, leave the rest unverified.
            plan_file = wiki.root / "verify.json"
            wiki.locked(
                "verify_pages.py", "plan",
                "--actor", "human:mzi",
                "--page", "wiki/concepts/netzentgelte.md",
                "--page", "wiki/concepts/redispatch.md",
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
            wiki.release("combined-1")

            counts = json.loads(wiki.read("meta/quality-status.json"))["trust"]["counts"]
            self.assertEqual(counts["human-reviewed"], 2)
            self.assertEqual(counts["machine-confirmed"], 0)

            # A sync artifact appears and must not be mistaken for damage.
            copy = "wiki/concepts/netzentgelte-DESKTOP-A1B2C3.md"
            wiki.write(copy, wiki.read("wiki/concepts/netzentgelte.md"))
            self.assertEqual(wiki.verify()["state"], "sync_artifacts_present")

            conflict_plan = wiki.root / "conflict.json"
            wiki.locked("resolve_conflict_copy.py", "plan", "--output", str(conflict_plan))
            resolution = json.loads(conflict_plan.read_text(encoding="utf-8"))
            self.assertEqual(resolution["conflicts"][0]["recommended"], "keep-original")
            wiki.locked(
                "resolve_conflict_copy.py", "apply",
                "--plan-file", str(conflict_plan),
                "--expect-plan-sha256", resolution["plan_sha256"],
                "--decision", f"{copy}=keep-original",
            )
            self.assertEqual(wiki.verify()["state"], "ready")

            # The OKF export carries the confirmations it was given.
            destination = wiki.root / "bundle"
            result = wiki.maintain(
                "export_okf_bundle.py",
                "--target", str(wiki.path),
                "--destination", str(destination),
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            exported = (destination / "concepts" / "netzentgelte.md").read_text(encoding="utf-8")
            self.assertIn('verified: { by: "human:mzi"', exported)
            unreviewed = (destination / "concepts" / "lastgang.md").read_text(encoding="utf-8")
            self.assertNotIn("verified:", unreviewed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
